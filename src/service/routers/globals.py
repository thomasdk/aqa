"""FastAPI transport layer for the shared application context.

Endpoints validate HTTP payloads and delegate application behavior to the
shared context. Business rules remain in the services that own them.
"""

from __future__ import annotations

import copy
import os
import re
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from src.config.user_data import mutable_data_lock
from src.service.api_schemas import (
    GlobalBlockResponse,
    RestoreDefaultsResponse,
    RevealGlobalsDirectoryResponse,
)

from .dependencies import ContextDependency
from .prompt_config import (
    _open_directory,
    _prompt_defaults_root,
    _resolve_prompt_data_directory_for_reveal,
    _serializes_mutable_data,
    _trigger_session_configuration_reload,
)

router = APIRouter()

_GLOBAL_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class GlobalUpdateRequest(BaseModel):
    """Body for ``PUT /api/prompts/globals/{global_id}``.

    Only ``label`` and ``content`` are mutable. ``scope`` is
    intentionally read-only (it changes the block's consumer
    eligibility), so the schema rejects any extra field with a 422.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    label: str = Field(..., min_length=1)
    content: str = ""


def _resolve_global_restore_paths(context) -> tuple[Path, Path, Path]:
    """Resolve active/default global files and enforce shared-root containment."""

    prompt_root = Path(context.settings.prompt_library_path).resolve()
    baseline_root = _prompt_defaults_root(context, prompt_root)
    active_path = (prompt_root / "prompts_globals.poml").resolve()
    baseline_path = (baseline_root / "prompts_globals.poml").resolve()
    try:
        active_path.relative_to(prompt_root)
        baseline_path.relative_to(baseline_root)
    except ValueError as error:
        raise HTTPException(
            status_code=500,
            detail="Resolved globals path escapes its configured root",
        ) from error
    return active_path, prompt_root, baseline_path


def _parse_valid_globals_document(
    path: Path, *, description: str
) -> tuple[ET.ElementTree, dict[str, tuple[ET.Element, str, str | None, str]]]:
    """Parse a complete ``<prompts>`` document and validate direct globals."""

    try:
        tree = ET.parse(path)
    except (ET.ParseError, OSError) as error:
        raise HTTPException(
            status_code=422, detail=f"{description} is not valid XML: {error}"
        ) from error
    root = tree.getroot()
    if root.tag != "prompts":
        raise HTTPException(status_code=422, detail=f"{description} must have a <prompts> root")
    blocks: dict[str, tuple[ET.Element, str, str | None, str]] = {}
    for child in list(root):
        if child.tag != "global":
            raise HTTPException(
                status_code=422, detail=f"{description} may contain only direct <global> children"
            )
        global_id = child.get("id")
        if not global_id or not _GLOBAL_ID_RE.match(global_id):
            raise HTTPException(
                status_code=422, detail=f"Invalid global id in {description}: {global_id!r}"
            )
        if global_id in blocks:
            raise HTTPException(
                status_code=422, detail=f"Duplicate global id in {description}: {global_id}"
            )
        label = child.get("label") or global_id
        scope = child.get("scope")
        content_node = child.find("content")
        content = (
            content_node.text.strip()
            if content_node is not None and content_node.text is not None
            else ""
        )
        blocks[global_id] = (child, label, scope, content)
    return tree, blocks


def _global_provenance(global_id: str, context) -> tuple[bool, str]:
    """Return provenance using semantic block fields, not whole-file bytes."""

    try:
        active_path, _data_root, baseline_path = _resolve_global_restore_paths(context)
        if not baseline_path.is_file():
            return False, "custom"
        _baseline_tree, baseline_blocks = _parse_valid_globals_document(
            baseline_path, description="Baseline globals POML"
        )
        baseline = baseline_blocks.get(global_id)
        if baseline is None:
            return False, "custom"
        try:
            _active_tree, active_blocks = _parse_valid_globals_document(
                active_path, description="Active globals POML"
            )
            active = active_blocks.get(global_id)
        except HTTPException:
            return True, "shipped_modified"
        baseline_tuple = (baseline[1], baseline[2], baseline[3])
        active_tuple = (active[1], active[2], active[3]) if active is not None else None
        return True, "shipped_default" if active_tuple == baseline_tuple else "shipped_modified"
    except (HTTPException, OSError):
        return False, "custom"


def _global_payload_to_dict(block, context=None) -> dict:
    """Serialize a global block for editor endpoints."""

    payload = {
        "id": block.id,
        "label": block.label,
        "scope": block.scope,
        "content": block.content,
    }
    if context is not None:
        payload["is_shipped"], payload["origin"] = _global_provenance(block.id, context)
    return payload


def _trusted_globals_source_file(context) -> Path:
    """Resolve the trusted ``prompts_globals.poml`` source.

    Uses the live ``PromptRepository`` base path (the configured
    ``prompt_library_path``); never accepts paths from the client.
    Raises ``HTTPException(500)`` if the trusted path cannot be
    determined or fails basic containment checks.
    """

    base = Path(context.settings.prompt_library_path).resolve()
    candidate = (base / "prompts_globals.poml").resolve()
    try:
        candidate.relative_to(base)
    except ValueError as error:
        raise HTTPException(
            status_code=500,
            detail="Resolved globals POML escapes prompt library root",
        ) from error
    return candidate


def _rewrite_global_block(
    poml_path: Path, *, global_id: str, new_label: str, new_content: str
) -> str:
    """Rewrite a single ``<global id="…">`` block in *poml_path* atomically.

    Parses the full XML to (a) locate the targeted block, (b) build the
    replacement block, and (c) re-validate the entire document as
    well-formed XML before writing. Only the targeted block's bytes
    change; the rest of the document is preserved verbatim so existing
    block formatting, comments, and whitespace survive.
    """

    original_text = poml_path.read_text(encoding="utf-8")

    try:
        tree = ET.parse(poml_path)
    except ET.ParseError as error:
        raise HTTPException(
            status_code=422,
            detail=f"prompts_globals.poml is not valid XML: {error}",
        ) from error

    root = tree.getroot()
    target = None
    for node in root.findall("global"):
        if node.get("id") == global_id:
            target = node
            break
    if target is None:
        raise HTTPException(
            status_code=404,
            detail=f"Global block '{global_id}' not found in {poml_path.name}",
        )

    # Preserve all nodes except the selected label and content.
    target.set("label", new_label)
    content_node = target.find("content")
    if content_node is None:
        content_node = ET.SubElement(target, "content")
    content_node.text = new_content
    content_node.tail = None

    serialized = ET.tostring(root, encoding="unicode")
    try:
        ET.fromstring(serialized)
    except ET.ParseError as error:
        raise HTTPException(
            status_code=422,
            detail=f"Rewritten prompts_globals.poml is not valid XML: {error}",
        ) from error

    # Reject pre-existing duplicate IDs before committing any rewrite.
    re_parsed = ET.fromstring(serialized)
    seen: set[str] = set()
    for node in re_parsed.findall("global"):
        node_id = node.get("id")
        if not node_id or node_id in seen:
            raise HTTPException(
                status_code=422,
                detail=f"Refusing to write prompts_globals.poml: duplicate or missing global id {node_id!r}",
            )
        seen.add(node_id)

    # Persist the canonical wrapped layout even though reads accept bare globals.
    wrapped = serialized
    if not wrapped.lstrip().startswith("<prompts"):
        wrapped = f"<prompts>{wrapped}</prompts>"

    with mutable_data_lock:
        tmp_path = poml_path.with_name(f".{poml_path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as handle:
                handle.write(wrapped)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, poml_path)
        except Exception:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass
            raise

    return original_text


@router.get("/api/prompts/globals", response_model=list[GlobalBlockResponse])
def list_prompt_globals(context: ContextDependency) -> list[dict]:
    """List the existing global prompt blocks.

    Source is the live :class:`PromptRepository`; only existing
    ``<global>`` blocks are surfaced. The on-disk ``source_file`` path
    is never included in the response.
    """

    globals_ = context.prompts.list_globals()
    return [_global_payload_to_dict(block, context) for block in globals_]


@router.post(
    "/api/prompts/globals/reveal-directory",
    response_model=RevealGlobalsDirectoryResponse,
)
def reveal_globals_directory_endpoint(
    context: ContextDependency,
) -> RevealGlobalsDirectoryResponse:
    """Open the validated global-prompts folder without returning its path."""

    directory = _resolve_prompt_data_directory_for_reveal(context, Path(context.prompts.base_path))
    _open_directory(directory)
    return RevealGlobalsDirectoryResponse(status="ok")


def _atomic_write_global_document(path: Path, root: ET.Element) -> None:
    """Serialize and atomically replace one globals document."""

    serialized = ET.tostring(root, encoding="unicode")
    # The in-memory tree was validated before mutation; parse once more to keep
    # the write boundary defensive and all-or-nothing.
    try:
        ET.fromstring(serialized)
    except ET.ParseError as error:
        raise HTTPException(
            status_code=422, detail=f"Rewritten globals POML is invalid: {error}"
        ) from error
    with mutable_data_lock:
        tmp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as handle:
                handle.write(serialized)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, path)
        except OSError as error:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass
            raise HTTPException(
                status_code=500, detail=f"Failed to write globals POML: {error}"
            ) from error


def _restore_global_defaults(context, selected_id: str | None = None) -> RestoreDefaultsResponse:
    """Merge validated baseline global elements into the active document."""

    active_path, _data_root, baseline_path = _resolve_global_restore_paths(context)
    if not baseline_path.is_file():
        raise HTTPException(
            status_code=404, detail=f"Baseline globals POML not found: {baseline_path}"
        )
    _baseline_tree, baseline_blocks = _parse_valid_globals_document(
        baseline_path, description="Baseline globals POML"
    )
    if selected_id is None:
        if not baseline_blocks:
            raise HTTPException(
                status_code=422, detail="Baseline globals POML contains no global blocks"
            )
        selected = sorted(baseline_blocks)
    else:
        if selected_id not in baseline_blocks:
            raise HTTPException(
                status_code=404,
                detail=f"No shipped baseline found for global '{selected_id}'",
            )
        selected = [selected_id]
    active_tree, active_blocks = _parse_valid_globals_document(
        active_path, description="Active globals POML"
    )
    active_root = active_tree.getroot()
    for global_id in selected:
        baseline_node = baseline_blocks[global_id][0]
        active_entry = active_blocks.get(global_id)
        replacement = copy.deepcopy(baseline_node)
        if active_entry is None:
            active_root.append(replacement)
        else:
            current_node = active_entry[0]
            index = list(active_root).index(current_node)
            active_root.remove(current_node)
            active_root.insert(index, replacement)
    _atomic_write_global_document(active_path, active_root)
    _trigger_session_configuration_reload(context)
    return RestoreDefaultsResponse(restored=sorted(selected))


@router.post(
    "/api/prompts/globals/restore-defaults",
    response_model=RestoreDefaultsResponse,
)
@_serializes_mutable_data
def restore_default_globals(context: ContextDependency) -> RestoreDefaultsResponse:
    """Restore all shipped global blocks while preserving custom blocks."""

    return _restore_global_defaults(context)


@router.post(
    "/api/prompts/globals/{global_id}/restore-default",
    response_model=RestoreDefaultsResponse,
)
@_serializes_mutable_data
def restore_default_global(global_id: str, context: ContextDependency) -> RestoreDefaultsResponse:
    """Restore one shipped global block after full baseline validation."""

    if not _GLOBAL_ID_RE.match(global_id):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid global id {global_id!r}: must match ^[a-z][a-z0-9_]*$",
        )
    return _restore_global_defaults(context, selected_id=global_id)


@router.put("/api/prompts/globals/{global_id}", response_model=GlobalBlockResponse)
@_serializes_mutable_data
def update_prompt_global(
    global_id: str, payload: GlobalUpdateRequest, context: ContextDependency
) -> dict:
    """Update the ``label`` and ``content`` of an existing global block.

    ``scope`` is read-only and rejected at the schema level (extra
    field). Path-traversal attempts are rejected before any file I/O.
    The on-disk file is rewritten atomically; only the targeted
    ``<global>`` block is mutated and the full document is validated
    as well-formed XML before the swap.
    """

    if not _GLOBAL_ID_RE.match(global_id):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid global id {global_id!r}: must match ^[a-z][a-z0-9_]*$",
        )

    existing = context.prompts.get_global(global_id)
    if existing is None:
        raise HTTPException(
            status_code=404,
            detail=f"Global block '{global_id}' not found",
        )

    # Cached source metadata is untrusted until resolved inside the prompt library.
    trusted = _trusted_globals_source_file(context)
    cached_source = str(existing.metadata.get("source_file", ""))
    try:
        cached_resolved = Path(cached_source).resolve() if cached_source else None
    except (OSError, RuntimeError):
        cached_resolved = None
    if cached_resolved is not None and cached_resolved != trusted:
        # Refuse ambiguous repository metadata rather than guessing a write target.
        raise HTTPException(
            status_code=409,
            detail=(f"Global block '{global_id}' lives in a non-trusted file; refusing to edit"),
        )
    if not trusted.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"Trusted globals POML not found: {trusted}",
        )

    _rewrite_global_block(
        trusted,
        global_id=global_id,
        new_label=payload.label,
        new_content=payload.content,
    )

    context.discussion.reload_session_configuration()

    refreshed = context.prompts.get_global(global_id)
    if refreshed is None:
        raise HTTPException(
            status_code=500,
            detail="Global block disappeared after update",
        )
    return _global_payload_to_dict(refreshed, context)
