"""FastAPI transport layer for the shared application context.

Endpoints validate HTTP payloads and delegate application behavior to the
shared context. Business rules remain in the services that own them.
"""

from __future__ import annotations

import os
import re
import uuid
import xml.etree.ElementTree as ET
from functools import wraps
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.config.user_data import mutable_data_lock
from src.service.api_errors import api_error
from src.service.api_schemas import (
    PromptConfigurationAcknowledgementResponse,
    RestoreDefaultsResponse,
    RevealRoleResponse,
    RevealRolesDirectoryResponse,
    RoleResponse,
)

from .dependencies import ContextDependency
from .prompt_config import (
    _atomic_copy_bytes,
    _open_directory,
    _reveal_path,
    _trigger_session_configuration_reload,
)

router = APIRouter()

_ROLE_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_SESSION_TYPE_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")

_ROLE_REFERENCED_BY_SESSION_TYPES = "role_referenced_by_session_types"
_SESSION_TYPE_DEPENDENCY_CHECK_UNAVAILABLE = "session_type_dependency_check_unavailable"


class RoleCreateRequest(BaseModel):
    """Body for POST /api/prompts/roles."""

    id: str = Field(..., min_length=1, description="Unique role identifier")
    label: str = Field(..., min_length=1, description="Human-readable label")
    role: str = Field(..., min_length=1, description="Role instruction text")
    task: str | None = Field(default=None, description="Task instruction text")
    output_format: str | None = Field(default=None, description="Output format instruction")
    description: str | None = Field(default=None, description="Non-prompt setup description")


class RoleUpdateRequest(BaseModel):
    """Body for PUT /api/prompts/roles/{role_id}. All fields optional."""

    label: str | None = Field(default=None, min_length=1, description="New label")
    role: str | None = Field(default=None, description="New role text")
    task: str | None = Field(default=None, description="New task text")
    output_format: str | None = Field(default=None, description="New output format")
    description: str | None = Field(default=None, description="New non-prompt setup description")


def _prompt_defaults_root(context, prompt_root: Path) -> Path:
    """Use an explicit immutable baseline while preserving lightweight test contexts."""

    configured = getattr(context.settings, "prompt_defaults_path", None)
    if type(configured) is str:
        return Path(configured).resolve()
    return (prompt_root.parent / "prompt_defaults").resolve()


def _resolve_restore_paths(context) -> tuple[Path, Path, Path]:
    """Resolve and validate active/baseline restore directories."""
    roles_dir = _get_roles_dir(context)
    prompts_root = context.prompts.base_path.resolve()
    baseline_root = _prompt_defaults_root(context, prompts_root)
    baseline_dir = (baseline_root / "roles").resolve()

    try:
        roles_dir.relative_to(prompts_root)
        baseline_dir.relative_to(baseline_root)
        if roles_dir == prompts_root:
            raise HTTPException(
                status_code=500,
                detail="Active roles directory is not inside the prompt root",
            )
        if baseline_dir == baseline_root:
            raise HTTPException(
                status_code=500,
                detail="Baseline roles directory is not inside the baseline root",
            )
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail="Failed to resolve baseline roles directory",
        ) from error

    return roles_dir, prompts_root, baseline_dir


def _baseline_path_for_role(baseline_dir: Path, role_id: str) -> Path:
    """Return the only baseline path eligible for *role_id*."""
    baseline_path = (baseline_dir / f"{role_id}.poml").resolve()
    if baseline_path != baseline_dir and baseline_dir not in baseline_path.parents:
        raise HTTPException(
            status_code=500,
            detail=f"Resolved baseline path escapes baseline directory: {baseline_path}",
        )
    return baseline_path


def _validate_baseline_file(baseline_path: Path, *, expected_role_id: str | None = None) -> str:
    """Parse one baseline and return its validated role id before any writes."""
    try:
        tree = ET.parse(baseline_path)
    except ET.ParseError as error:
        raise HTTPException(
            status_code=422,
            detail=(f"Baseline POML is not valid XML: {baseline_path.name} ({error})"),
        ) from error
    except OSError as error:
        raise HTTPException(
            status_code=422,
            detail=f"Baseline POML cannot be read: {baseline_path.name} ({error})",
        ) from error

    root = tree.getroot()
    if not root.findall("prompt"):
        raise HTTPException(
            status_code=422,
            detail=f"Baseline POML contains no <prompt> elements: {baseline_path.name}",
        )

    role_id = _derive_role_id_from_baseline(baseline_path)
    if not role_id:
        raise HTTPException(
            status_code=422,
            detail=(f"Cannot derive a valid role id from baseline file: {baseline_path.name}"),
        )
    if expected_role_id is not None and role_id != expected_role_id:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Baseline file '{baseline_path.name}' contains role id "
                f"'{role_id}', expected '{expected_role_id}'"
            ),
        )
    return role_id


def _resolve_restore_paths_from_repo(context, prompts_repo) -> tuple[Path, Path, Path]:
    """Resolve restore paths for a repository-like object used by role listing."""
    roles_dir = (prompts_repo.base_path / "roles").resolve()
    prompts_root = prompts_repo.base_path.resolve()
    baseline_root = _prompt_defaults_root(context, prompts_root)
    baseline_dir = (baseline_root / "roles").resolve()
    if prompts_root not in roles_dir.parents:
        raise HTTPException(
            status_code=500,
            detail="Active roles directory is not inside the prompt root",
        )
    if baseline_root not in baseline_dir.parents:
        raise HTTPException(
            status_code=500,
            detail="Baseline roles directory escapes the baseline root",
        )
    return roles_dir, prompts_root, baseline_dir


def _is_shipped_role(context, role_id: str, prompts_repo) -> bool:
    """Return whether the exact shipped baseline file exists safely."""
    if not _validate_role_id(role_id):
        return False
    try:
        _, _, baseline_dir = _resolve_restore_paths_from_repo(context, prompts_repo)
        return _baseline_path_for_role(baseline_dir, role_id).is_file()
    except (HTTPException, OSError):
        return False


def _compute_role_origin(context, role_id: str, template, prompts_repo) -> str:
    """Return the additive provenance string for a role.

    Values are stable contract literals:
        * ``"shipped_default"``  — shipped baseline exists AND active bytes match.
        * ``"shipped_modified"`` — shipped baseline exists AND active bytes differ.
        * ``"custom"``           — no shipped baseline for this role id.

    A missing baseline is reported as ``custom``; the bulk restore endpoint is
    the authoritative recovery path for missing shipped roles.
    """
    if not _validate_role_id(role_id):
        return "custom"
    try:
        _, _, baseline_dir = _resolve_restore_paths_from_repo(context, prompts_repo)
        baseline_path = _baseline_path_for_role(baseline_dir, role_id)
    except (HTTPException, OSError):
        return "custom"
    if not baseline_path.is_file():
        return "custom"

    source_file = str(template.metadata.get("source_file", ""))
    try:
        active_path = Path(source_file)
        if not active_path.is_file():
            return "shipped_modified"
        if active_path.read_bytes() == baseline_path.read_bytes():
            return "shipped_default"
        return "shipped_modified"
    except OSError:
        # If we cannot read the active file, treat it as modified so the user
        # sees a clear actionable state in the UI rather than a misleading one.
        return "shipped_modified"


def _restore_parsed_baselines(
    context, roles_dir: Path, parsed: list[tuple[Path, str]]
) -> RestoreDefaultsResponse:
    """Atomically copy validated baselines, then reload all prompt consumers."""
    restored: list[str] = []
    try:
        for baseline_path, role_id in parsed:
            target = (roles_dir / f"{role_id}.poml").resolve()
            if roles_dir != target and roles_dir not in target.parents:
                raise HTTPException(
                    status_code=500,
                    detail=f"Resolved target path escapes roles directory: {target}",
                )
            _atomic_copy_bytes(baseline_path, target)
            restored.append(role_id)
    except HTTPException:
        raise
    except OSError as error:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to write baseline file: {error}",
        ) from error

    context.prompts.reload()
    _trigger_session_configuration_reload(context)
    restored.sort()
    return RestoreDefaultsResponse(restored=restored)


def _build_role_response(context, template, prompts_repo) -> dict:
    """Build a role response dict from a PromptTemplate and the repository.

    The active ``.poml`` filesystem location is intentionally NOT
    exposed: it is an internal implementation detail used only to
    compute the public ``editable`` and ``origin`` fields.  The reveal
    endpoint is the only authorised way to surface a source path, and
    it does so by launching the OS file manager — never by returning
    the path itself.
    """
    source_file = str(template.metadata.get("source_file", ""))
    try:
        sf_path = Path(source_file).resolve()
        roles_dir = (prompts_repo.base_path / "roles").resolve()
        editable = roles_dir in sf_path.parents
    except Exception:
        editable = False
    is_shipped = _is_shipped_role(context, template.id, prompts_repo)
    payload = {
        "id": template.id,
        "label": template.label,
        "role": template.role,
        "task": template.task or "",
        "output_format": template.output_format or "",
        "description": template.description,
        # ``source_file`` is intentionally redacted from the public
        # payload.  The editability / origin checks below still read
        # it internally so the public response remains path-free.
        "editable": editable,
        "is_shipped": is_shipped,
        "origin": (
            _compute_role_origin(context, template.id, template, prompts_repo)
            if is_shipped
            else "custom"
        ),
    }
    return payload


def _get_roles_dir(context) -> Path:
    """Return the resolved path to the roles subdirectory."""
    return (context.prompts.base_path / "roles").resolve()


def _resolve_roles_directory_for_reveal(context) -> Path:
    """Return the active roles directory after safe reveal-only validation.

    The roles directory must be a real directory below the active prompt data
    root.  Every failure maps to a path-free 404 response; launching the OS
    file manager is deliberately deferred until this validation completes.
    """

    try:
        prompts_root = context.prompts.base_path.resolve()
        data_root = prompts_root.parent.resolve()
        roles_dir = (prompts_root / "roles").resolve()
    except (OSError, RuntimeError, TypeError, AttributeError):
        raise HTTPException(status_code=404, detail="Roles directory is unavailable") from None

    # A symlinked or tampered roles directory must remain inside both the
    # configured prompt root and its enclosing data root.
    if (
        roles_dir == prompts_root
        or prompts_root not in roles_dir.parents
        or data_root not in roles_dir.parents
        or not roles_dir.is_dir()
    ):
        raise HTTPException(status_code=404, detail="Roles directory is unavailable")
    return roles_dir


def _resolve_prompt_data_directory_for_reveal(context, directory: Path) -> Path:
    """Validate an active prompt-data directory before opening it.

    Session types intentionally live beside the prompt-library directory,
    while globals live in the prompt-library directory itself.  Both must
    resolve below the active prompt data root and exist as real directories.
    This helper never includes a filesystem path in its public failures.
    """

    try:
        prompts_root = Path(context.prompts.base_path).resolve()
        data_root = prompts_root.parent.resolve()
        candidate = directory.resolve()
    except (OSError, RuntimeError, TypeError, AttributeError):
        raise HTTPException(status_code=404, detail="Directory is unavailable") from None

    if candidate == data_root or data_root not in candidate.parents or not candidate.is_dir():
        raise HTTPException(status_code=404, detail="Directory is unavailable")
    return candidate


def _resolve_role_source_path(context, role_id: str) -> Path:
    """Resolve a role's source ``.poml`` to an absolute, contained path.

    Validates the role id against the strict grammar *before* any
    filesystem I/O.  Looks up the active :class:`PromptTemplate`,
    resolves its metadata ``source_file`` (an internal-only value the
    prompt repository injects when it loads a POML), and confirms the
    resolved regular file is contained in the resolved active
    ``data/prompts/roles`` directory.

    Returns the resolved, contained :class:`Path`.  Raises
    :class:`HTTPException` with a generic message on any validation,
    containment, or existence failure — never returns paths or details
    to callers.
    """

    if not _validate_role_id(role_id):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid role ID '{role_id}': must match ^[a-z][a-z0-9_]*$",
        )
    template = context.prompts.get_template(role_id)
    if template is None:
        raise HTTPException(status_code=404, detail=f"Role '{role_id}' not found")

    roles_dir = _get_roles_dir(context)
    source_file = str(template.metadata.get("source_file", ""))
    if not source_file:
        raise HTTPException(status_code=404, detail=f"Role '{role_id}' has no resolvable source")
    try:
        resolved = Path(source_file).resolve()
    except (OSError, RuntimeError):
        raise HTTPException(
            status_code=404, detail=f"Role '{role_id}' source is not resolvable"
        ) from None

    if not resolved.is_file():
        raise HTTPException(
            status_code=404, detail=f"Role '{role_id}' source is not a regular file"
        )

    # Cached source metadata is untrusted until resolved inside the active roles directory.
    if roles_dir != resolved and roles_dir not in resolved.parents:
        raise HTTPException(
            status_code=404, detail=f"Role '{role_id}' source is outside the roles directory"
        )
    return resolved


def _build_poml_content(
    role_id: str,
    label: str,
    role_text: str,
    task_text: str = "",
    output_text: str = "",
    description: str | None = None,
) -> str:
    """Build a POML document string for a single prompt template."""
    lines = ["<prompts>"]
    lines.append(f"  <prompt id={quoteattr(role_id)} label={quoteattr(label)}>")
    lines.append(f"    <role>{escape(role_text)}</role>")
    if description:
        lines.append(f"    <description>{escape(description)}</description>")
    if task_text:
        lines.append(f"    <task>{escape(task_text)}</task>")
    if output_text:
        lines.append(f"    <output-format>{escape(output_text)}</output-format>")
    lines.append("  </prompt>")
    lines.append("</prompts>")
    return "\n".join(lines)


@router.get("/api/prompts/roles", response_model=list[RoleResponse])
def list_roles(context: ContextDependency) -> list[dict]:
    """List all prompt templates with their editable status."""
    templates = context.prompts.list_templates()
    return [_build_role_response(context, tpl, context.prompts) for tpl in templates]


def _validate_role_id(candidate: str) -> bool:
    """Return True if *candidate* is a valid role id format."""
    return bool(candidate) and _ROLE_ID_RE.match(candidate) is not None


def _session_type_dependencies_for_role(context, role_id: str) -> list[dict[str, str]]:
    """Return current Session Types that still reference ``role_id``.

    The caller holds ``mutable_data_lock`` through ``_serializes_mutable_data``.
    Reading the live repository inside that boundary keeps this check atomic with
    Session Type mutations and imports. The repository already excludes malformed
    files from its cache, so unrelated invalid files do not affect the result.
    """

    repository = getattr(context.discussion, "session_type_repo", None)
    list_definitions = getattr(repository, "list", None)
    if not callable(list_definitions):
        raise api_error(
            503,
            _SESSION_TYPE_DEPENDENCY_CHECK_UNAVAILABLE,
            "Session Type dependencies could not be checked",
        )

    try:
        definitions = list_definitions()
    except Exception as error:
        raise api_error(
            503,
            _SESSION_TYPE_DEPENDENCY_CHECK_UNAVAILABLE,
            "Session Type dependencies could not be checked",
        ) from error
    if not isinstance(definitions, list):
        raise api_error(
            503,
            _SESSION_TYPE_DEPENDENCY_CHECK_UNAVAILABLE,
            "Session Type dependencies could not be checked",
        )

    dependencies: dict[str, dict[str, str]] = {}
    for definition in definitions:
        prompt_ids = getattr(definition, "default_agent_prompt_ids", ())
        if not isinstance(prompt_ids, list) or role_id not in prompt_ids:
            continue
        key = getattr(definition, "key", None)
        if not isinstance(key, str) or not _SESSION_TYPE_KEY_RE.fullmatch(key.strip()):
            raise api_error(
                503,
                _SESSION_TYPE_DEPENDENCY_CHECK_UNAVAILABLE,
                "Session Type dependencies could not be checked",
            )
        key = key.strip()
        label = getattr(definition, "label", None)
        if not isinstance(label, str) or not label.strip():
            label = key
        else:
            label = label.strip()
            has_unsafe_label = any(
                ord(character) < 32 or ord(character) == 127 for character in label
            )
            if "/" in label or "\\" in label or len(label) > 160 or has_unsafe_label:
                label = key
        dependencies[key] = {"key": key, "label": label}

    return [dependencies[key] for key in sorted(dependencies)]


def _derive_role_id_from_baseline(baseline_path: Path) -> str | None:
    """Derive a role id from one baseline POML file.

    Tries the ``<prompt id="...">`` attribute first; falls back to the filename
    stem. Returns ``None`` when no valid id can be derived.
    """
    try:
        tree = ET.parse(baseline_path)
    except ET.ParseError:
        return None
    root = tree.getroot()
    for prompt_node in root.findall("prompt"):
        prompt_id = prompt_node.get("id")
        if prompt_id and _validate_role_id(prompt_id):
            return prompt_id
    stem = baseline_path.stem
    if _validate_role_id(stem):
        return stem
    return None


def _serializes_mutable_data(function):
    """Make a prompt read-modify-write atomic against an import."""

    @wraps(function)
    def wrapped(*args, **kwargs):
        with mutable_data_lock:
            return function(*args, **kwargs)

    return wrapped


def _atomic_write_text(dst: Path, content: str) -> None:
    """Write UTF-8 text through a same-directory temporary file."""

    with mutable_data_lock:
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = dst.with_name(f".{dst.name}.{uuid.uuid4().hex}.tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, dst)
        except Exception:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass
            raise


@router.post("/api/prompts/roles/restore-defaults", response_model=RestoreDefaultsResponse)
@_serializes_mutable_data
def restore_default_roles(context: ContextDependency) -> RestoreDefaultsResponse:
    """Atomically restore every baseline POML into the active roles directory.

    Recreates missing shipped roles, overwrites edited shipped roles, and leaves
    custom (non-baseline) active roles untouched. Fails clearly (non-2xx) and
    does not mutate the active directory if the baseline directory is missing,
    empty, or any baseline POML fails to parse.
    """
    roles_dir, _data_root, baseline_dir = _resolve_restore_paths(context)

    if not baseline_dir.exists() or not baseline_dir.is_dir():
        raise HTTPException(
            status_code=404,
            detail=f"Baseline directory not found: {baseline_dir}",
        )

    baseline_files = sorted(
        p for p in baseline_dir.iterdir() if p.is_file() and p.suffix.lower() == ".poml"
    )
    if not baseline_files:
        raise HTTPException(
            status_code=400,
            detail=f"Baseline directory is empty: {baseline_dir}",
        )

    # Validate the complete baseline set before the first write.
    parsed: list[tuple[Path, str]] = []
    for baseline_path in baseline_files:
        role_id = _validate_baseline_file(baseline_path)
        if any(rid == role_id for _, rid in parsed):
            raise HTTPException(
                status_code=422,
                detail=f"Duplicate role id '{role_id}' in baseline directory",
            )
        parsed.append((baseline_path, role_id))

    return _restore_parsed_baselines(context, roles_dir, parsed)


@router.post(
    "/api/prompts/roles/reveal-directory",
    response_model=RevealRolesDirectoryResponse,
)
def reveal_roles_directory_endpoint(context: ContextDependency) -> RevealRolesDirectoryResponse:
    """Open the validated active roles directory without disclosing its path."""
    roles_dir = _resolve_roles_directory_for_reveal(context)
    _open_directory(roles_dir)
    return RevealRolesDirectoryResponse(status="ok")


@router.post(
    "/api/prompts/roles/{role_id}/restore-default",
    response_model=RestoreDefaultsResponse,
)
@_serializes_mutable_data
def restore_default_role(role_id: str, context: ContextDependency) -> RestoreDefaultsResponse:
    """Atomically restore one shipped role from its exact baseline file."""
    if not _validate_role_id(role_id):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid role ID '{role_id}': must match ^[a-z][a-z0-9_]*$",
        )

    roles_dir, _data_root, baseline_dir = _resolve_restore_paths(context)
    if not baseline_dir.exists() or not baseline_dir.is_dir():
        raise HTTPException(
            status_code=404,
            detail=f"Baseline directory not found: {baseline_dir}",
        )

    baseline_path = _baseline_path_for_role(baseline_dir, role_id)
    if not baseline_path.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"No shipped baseline found for role '{role_id}'",
        )

    _validate_baseline_file(baseline_path, expected_role_id=role_id)
    return _restore_parsed_baselines(context, roles_dir, [(baseline_path, role_id)])


@router.post(
    "/api/prompts/roles/{role_id}/reveal",
    response_model=RevealRoleResponse,
)
def reveal_role_endpoint(role_id: str, context: ContextDependency) -> RevealRoleResponse:
    """Reveal one validated role file without exposing its path to the client.

    Validation happens before process launch: an invalid id returns 422, a
    missing or out-of-root file returns 404, and launch failures return 502
    without command or path details.
    """
    resolved = _resolve_role_source_path(context, role_id)
    _reveal_path(resolved)
    return RevealRoleResponse(status="ok")


@router.get("/api/prompts/roles/{role_id}", response_model=RoleResponse)
def get_role(role_id: str, context: ContextDependency) -> dict:
    """Get a single prompt template by ID."""
    template = context.prompts.get_template(role_id)
    if template is None:
        raise HTTPException(status_code=404, detail=f"Role '{role_id}' not found")
    return _build_role_response(context, template, context.prompts)


@router.post("/api/prompts/roles", status_code=201, response_model=RoleResponse)
@_serializes_mutable_data
def create_role(payload: RoleCreateRequest, context: ContextDependency) -> dict:
    """Create a new role POML file in the roles directory."""

    if not _ROLE_ID_RE.match(payload.id):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid role ID '{payload.id}': must match ^[a-z][a-z0-9_]*$",
        )

    if context.prompts.get_template(payload.id) is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Role '{payload.id}' already exists",
        )

    roles_dir = _get_roles_dir(context)
    roles_dir.mkdir(parents=True, exist_ok=True)
    poml_path = roles_dir / f"{payload.id}.poml"

    poml_content = _build_poml_content(
        role_id=payload.id,
        label=payload.label,
        role_text=payload.role,
        task_text=payload.task or "",
        output_text=payload.output_format or "",
        description=payload.description,
    )

    _atomic_write_text(poml_path, poml_content)

    context.prompts.reload()
    _trigger_session_configuration_reload(context)

    template = context.prompts.get_template(payload.id)
    return _build_role_response(context, template, context.prompts)


@router.put("/api/prompts/roles/{role_id}", response_model=RoleResponse)
@_serializes_mutable_data
def update_role(role_id: str, payload: RoleUpdateRequest, context: ContextDependency) -> dict:
    """Update an existing role's POML file."""
    # Reject path syntax before using the URL role ID in filesystem operations.
    if not _validate_role_id(role_id):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid role ID '{role_id}': must match ^[a-z][a-z0-9_]*$",
        )

    template = context.prompts.get_template(role_id)
    if template is None:
        raise HTTPException(status_code=404, detail=f"Role '{role_id}' not found")

    source_file = str(template.metadata.get("source_file", ""))
    try:
        sf_path = Path(source_file).resolve()
        roles_dir = _get_roles_dir(context)
        editable = roles_dir in sf_path.parents
    except Exception:
        editable = False

    if not editable:
        raise HTTPException(
            status_code=403,
            detail=f"Role '{role_id}' is read-only (system template)",
        )

    new_label = payload.label if payload.label is not None else template.label
    new_role = payload.role if payload.role is not None else template.role
    new_task = payload.task if payload.task is not None else template.task
    new_output = (
        payload.output_format if payload.output_format is not None else template.output_format
    )
    new_description = (
        payload.description if payload.description is not None else template.description
    )

    poml_content = _build_poml_content(
        role_id=role_id,
        label=new_label,
        role_text=new_role or "",
        task_text=new_task or "",
        output_text=new_output or "",
        description=new_description,
    )

    roles_dir = _get_roles_dir(context)
    # Retain containment as a second boundary after role-ID validation.
    poml_path = (roles_dir / f"{role_id}.poml").resolve()
    if roles_dir != poml_path and roles_dir not in poml_path.parents:
        raise HTTPException(
            status_code=500,
            detail=f"Resolved target path escapes roles directory: {poml_path}",
        )
    _atomic_write_text(poml_path, poml_content)

    context.prompts.reload()
    _trigger_session_configuration_reload(context)

    updated_template = context.prompts.get_template(role_id)
    return _build_role_response(context, updated_template, context.prompts)


@router.delete(
    "/api/prompts/roles/{role_id}",
    response_model=PromptConfigurationAcknowledgementResponse,
)
@_serializes_mutable_data
def delete_role(
    role_id: str, context: ContextDependency
) -> PromptConfigurationAcknowledgementResponse:
    """Delete a role's POML file."""

    template = context.prompts.get_template(role_id)
    if template is None:
        raise HTTPException(status_code=404, detail=f"Role '{role_id}' not found")

    source_file = str(template.metadata.get("source_file", ""))
    try:
        sf_path = Path(source_file).resolve()
        roles_dir = _get_roles_dir(context)
        editable = roles_dir in sf_path.parents
    except Exception:
        editable = False

    if not editable:
        raise HTTPException(
            status_code=403,
            detail=f"Role '{role_id}' is read-only (system template)",
        )

    dependencies = _session_type_dependencies_for_role(context, role_id)
    if dependencies:
        raise api_error(
            409,
            _ROLE_REFERENCED_BY_SESSION_TYPES,
            "Role is referenced by current Session Types",
            params={"session_types": dependencies},
        )

    poml_path = Path(source_file).resolve()
    with mutable_data_lock:
        if poml_path.exists():
            poml_path.unlink()

    context.prompts.reload()
    _trigger_session_configuration_reload(context)

    return PromptConfigurationAcknowledgementResponse(status="ok")


# Literal routes must precede dynamic ``/{key}`` routes to avoid shadowing.
# The URL key is immutable; bodies intentionally cannot rename a session type.


_SESSION_TYPE_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")
