"""FastAPI transport layer for the shared application context.

Endpoints validate HTTP payloads and delegate application behavior to the
shared context. Business rules remain in the services that own them.
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.prompts.session_types import (
    SessionInputDefinition,
    SessionTypeDefinition,
    SessionTypeError,
    SessionTypeRepository,
    default_session_inputs,
    validate_session_inputs,
)
from src.service.api_errors import api_error as _api_error
from src.service.api_schemas import (
    DeletePromptConfigurationResponse,
    PromptSessionTypeResponse,
    RestoreDefaultsResponse,
    RevealSessionTypesDirectoryResponse,
)

from .dependencies import ContextDependency
from .prompt_config import (
    _atomic_copy_bytes,
    _open_directory,
    _prompt_defaults_root,
    _resolve_prompt_data_directory_for_reveal,
    _serializes_mutable_data,
)

router = APIRouter()

_SESSION_TYPE_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def _resolve_session_restore_paths(context) -> tuple[Path, Path, Path]:
    """Resolve active/default session paths below the shared data root."""

    prompt_root = Path(context.settings.prompt_library_path).resolve()
    baseline_root = _prompt_defaults_root(context, prompt_root)
    # The active directory may be explicitly injected into DiscussionService;
    # use that live repository path while deriving shipped defaults from the
    # configured prompt-library sibling data root.
    active_dir = Path(_get_session_type_repo(context).base_path).resolve()
    baseline_dir = (baseline_root / "session_contexts").resolve()
    try:
        # Explicitly injected session repositories may be siblings of the
        # prompt library; packaged production storage remains below User Data.
        active_dir.relative_to(prompt_root.parent)
        baseline_dir.relative_to(baseline_root)
    except ValueError as error:
        raise HTTPException(
            status_code=500,
            detail="Resolved session directory escapes its configured root",
        ) from error
    return active_dir, prompt_root, baseline_dir


def _session_baseline_path(baseline_dir: Path, key: str) -> Path:
    """Resolve one validated session baseline without allowing path escape."""

    path = (baseline_dir / f"{key}.md").resolve()
    try:
        path.relative_to(baseline_dir)
    except ValueError as error:
        raise HTTPException(
            status_code=500,
            detail=f"Resolved session baseline path escapes its directory: {path}",
        ) from error
    return path


def _load_session_baselines(baseline_dir: Path) -> dict[str, tuple[Path, SessionTypeDefinition]]:
    """Validate every baseline through an independent repository before writes."""

    if not baseline_dir.exists() or not baseline_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Baseline directory not found: {baseline_dir}")
    files = sorted(path for path in baseline_dir.glob("*.md") if path.is_file())
    if not files:
        raise HTTPException(status_code=422, detail=f"Baseline directory is empty: {baseline_dir}")
    try:
        baseline_repo = SessionTypeRepository(base_path=baseline_dir)
        definitions = baseline_repo.list()
    except (SessionTypeError, OSError) as error:
        raise HTTPException(status_code=422, detail=f"Invalid session baseline: {error}") from error
    # SessionTypeRepository intentionally skips malformed files. A count check
    # turns that tolerant read behavior into all-or-nothing restore validation.
    if len(definitions) != len(files):
        raise HTTPException(status_code=422, detail="Baseline session set contains invalid files")
    result: dict[str, tuple[Path, SessionTypeDefinition]] = {}
    try:
        for definition in definitions:
            path = _session_baseline_path(baseline_dir, definition.key)
            path.read_bytes()
            result[definition.key] = (path, definition)
    except OSError as error:
        raise HTTPException(
            status_code=422, detail=f"Cannot read session baseline: {error}"
        ) from error
    return result


def _load_single_session_baseline(
    baseline_dir: Path, key: str
) -> tuple[Path, SessionTypeDefinition]:
    """Validate exactly one shipped source for a row-level restore.

    Bulk restores validate every baseline before changing any active file. A
    row-level restore intentionally validates only its own source, so an
    unrelated malformed baseline cannot block restoring the selected item.
    ``_load_file`` is the repository's canonical YAML/frontmatter parser and
    does not depend on repository instance state.
    """

    if not baseline_dir.exists() or not baseline_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Baseline directory not found: {baseline_dir}")
    baseline_path = _session_baseline_path(baseline_dir, key)
    if not baseline_path.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"No shipped baseline found for session type '{key}'",
        )
    try:
        parser = SessionTypeRepository.__new__(SessionTypeRepository)
        definition = parser._load_file(baseline_path)
        baseline_path.read_bytes()
    except (SessionTypeError, OSError) as error:
        raise HTTPException(status_code=422, detail=f"Invalid session baseline: {error}") from error
    return baseline_path, definition


def _session_provenance(key: str, context) -> tuple[bool, str]:
    """Return ``(is_shipped, origin)`` for an active session definition."""

    try:
        active_dir, _data_root, baseline_dir = _resolve_session_restore_paths(context)
        baseline_path = _session_baseline_path(baseline_dir, key)
    except (HTTPException, OSError):
        return False, "custom"
    if not baseline_path.is_file():
        return False, "custom"
    active_path = (active_dir / f"{key}.md").resolve()
    try:
        origin = (
            "shipped_default"
            if active_path.is_file() and active_path.read_bytes() == baseline_path.read_bytes()
            else "shipped_modified"
        )
    except OSError:
        origin = "shipped_modified"
    return True, origin


def _session_type_payload_to_dict(definition: SessionTypeDefinition, context=None) -> dict:
    """Serialize a :class:`SessionTypeDefinition` for editor endpoints."""

    payload = {
        "key": definition.key,
        "label": definition.label,
        "description": definition.description,
        "default_agent_prompt_ids": list(definition.default_agent_prompt_ids),
        "include_unchanged_research_material_context_in_prompt": bool(
            definition.include_unchanged_research_material_context_in_prompt
        ),
        "inputs": [
            item.model_dump(mode="json", exclude_none=True) for item in definition.session_inputs
        ],
        "body": definition.body,
    }
    if context is not None:
        payload["is_shipped"], payload["origin"] = _session_provenance(definition.key, context)
    return payload


def _get_session_type_repo(context) -> SessionTypeRepository:
    """Return the repository owned by the live discussion service."""

    return context.discussion.session_type_repo


def _trigger_session_configuration_reload(context) -> None:
    """Reload the live discussion service after a session-type mutation."""

    context.discussion.reload_session_configuration()


class SessionTypeCreateRequest(BaseModel):
    """Body for ``POST /api/prompts/session-types``.

    Mirrors :class:`SessionTypeDefinition` so Pydantic enforces the
    repository's invariants (key format, non-empty fields, valid agent
    IDs) and returns 422 on bad input.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    key: str = Field(..., min_length=1)
    label: str
    description: str
    default_agent_prompt_ids: list[str] = Field(default_factory=list)
    include_unchanged_research_material_context_in_prompt: bool = False
    inputs: list[SessionInputDefinition] = Field(default_factory=default_session_inputs)
    body: str = Field(..., min_length=1)

    @field_validator("key")
    @classmethod
    def _validate_key(cls, value: str) -> str:
        if not _SESSION_TYPE_KEY_RE.match(value):
            raise ValueError("key muss mit ^[a-z][a-z0-9_]*$ matchen")
        return value

    @field_validator("default_agent_prompt_ids")
    @classmethod
    def _validate_agents(cls, value: list[str]) -> list[str]:
        for agent_id in value:
            if not isinstance(agent_id, str) or not _SESSION_TYPE_KEY_RE.match(agent_id):
                raise ValueError(f"default_agent_prompt_ids enthält ungültige ID: {agent_id!r}")
        return list(value)

    @field_validator("inputs")
    @classmethod
    def _validate_inputs(cls, value: list[SessionInputDefinition]) -> list[SessionInputDefinition]:
        return validate_session_inputs(value)

    def to_definition(self) -> SessionTypeDefinition:
        return SessionTypeDefinition(
            key=self.key,
            label=self.label,
            description=self.description,
            default_agent_prompt_ids=list(self.default_agent_prompt_ids),
            include_unchanged_research_material_context_in_prompt=self.include_unchanged_research_material_context_in_prompt,
            session_inputs=list(self.inputs),
            body=self.body,
        )


class SessionTypeUpdateRequest(BaseModel):
    """Body for ``PUT /api/prompts/session-types/{key}``.

    The ``key`` from the URL is authoritative; a ``key`` field in the
    body is intentionally ignored (``extra="ignore"``) so clients cannot
    perform a rename by smuggling it through. Every other field is
    optional and falls back to the existing definition's value when
    absent.
    """

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    label: str | None = None
    description: str | None = None
    default_agent_prompt_ids: list[str] | None = None
    include_unchanged_research_material_context_in_prompt: bool | None = None
    inputs: list[SessionInputDefinition] | None = None
    body: str | None = Field(default=None, min_length=1)

    @field_validator("default_agent_prompt_ids")
    @classmethod
    def _validate_agents(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        for agent_id in value:
            if not isinstance(agent_id, str) or not _SESSION_TYPE_KEY_RE.match(agent_id):
                raise ValueError(f"default_agent_prompt_ids enthält ungültige ID: {agent_id!r}")
        return list(value)

    @field_validator("inputs")
    @classmethod
    def _validate_inputs(
        cls, value: list[SessionInputDefinition] | None
    ) -> list[SessionInputDefinition] | None:
        if value is None:
            return None
        return validate_session_inputs(value)

    def merge_into(self, existing: SessionTypeDefinition, *, url_key: str) -> SessionTypeDefinition:
        """Build a fully-populated :class:`SessionTypeDefinition` for *url_key*.

        Existing values fill in any field the client did not provide.
        Re-runs the strict Pydantic model so any field-level validation
        (agent id format, etc.) still produces a 422 on bad input.
        """

        return SessionTypeDefinition(
            key=url_key,
            label=self.label if self.label is not None else existing.label,
            description=self.description if self.description is not None else existing.description,
            default_agent_prompt_ids=(
                list(self.default_agent_prompt_ids)
                if self.default_agent_prompt_ids is not None
                else list(existing.default_agent_prompt_ids)
            ),
            include_unchanged_research_material_context_in_prompt=(
                self.include_unchanged_research_material_context_in_prompt
                if self.include_unchanged_research_material_context_in_prompt is not None
                else existing.include_unchanged_research_material_context_in_prompt
            ),
            session_inputs=(
                list(self.inputs) if self.inputs is not None else list(existing.session_inputs)
            ),
            body=self.body if self.body is not None else existing.body,
        )


@router.get("/api/prompts/session-types", response_model=list[PromptSessionTypeResponse])
def list_prompt_session_types(context: ContextDependency) -> list[dict]:
    """List all session types with the editor-relevant fields."""

    repo = _get_session_type_repo(context)
    return [_session_type_payload_to_dict(definition, context) for definition in repo.list()]


@router.post(
    "/api/prompts/session-types/reveal-directory",
    response_model=RevealSessionTypesDirectoryResponse,
)
def reveal_session_types_directory_endpoint(
    context: ContextDependency,
) -> RevealSessionTypesDirectoryResponse:
    """Open the validated active session-types directory without returning its path."""

    directory = _resolve_prompt_data_directory_for_reveal(
        context, Path(_get_session_type_repo(context).base_path)
    )
    _open_directory(directory)
    return RevealSessionTypesDirectoryResponse(status="ok")


@router.post(
    "/api/prompts/session-types", status_code=201, response_model=PromptSessionTypeResponse
)
@_serializes_mutable_data
def create_prompt_session_type(
    payload: SessionTypeCreateRequest, context: ContextDependency
) -> dict:
    """Create a new session type file and reload the live service."""

    repo = _get_session_type_repo(context)

    definition = payload.to_definition()
    if repo.get(definition.key) is not None:
        raise _api_error(
            409,
            "session_type_already_exists",
            f"Session type '{definition.key}' already exists",
            params={"key": definition.key},
        )
    try:
        created = repo.create(definition)
    except SessionTypeError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    _trigger_session_configuration_reload(context)
    return _session_type_payload_to_dict(created, context)


@router.post(
    "/api/prompts/session-types/restore-defaults",
    response_model=RestoreDefaultsResponse,
)
@_serializes_mutable_data
def restore_default_session_types(context: ContextDependency) -> RestoreDefaultsResponse:
    """Restore every validated shipped session file, preserving custom files."""

    active_dir, _data_root, baseline_dir = _resolve_session_restore_paths(context)
    baselines = _load_session_baselines(baseline_dir)
    restored = sorted(baselines)
    try:
        for key in restored:
            target = (active_dir / f"{key}.md").resolve()
            target.relative_to(active_dir)
            _atomic_copy_bytes(baselines[key][0], target)
    except HTTPException:
        raise
    except (OSError, ValueError) as error:
        raise HTTPException(
            status_code=500, detail=f"Failed to restore session baseline: {error}"
        ) from error
    _trigger_session_configuration_reload(context)
    return RestoreDefaultsResponse(restored=restored)


@router.post(
    "/api/prompts/session-types/{key}/restore-default",
    response_model=RestoreDefaultsResponse,
)
@_serializes_mutable_data
def restore_default_session_type(key: str, context: ContextDependency) -> RestoreDefaultsResponse:
    """Restore one shipped session file without inspecting unrelated baselines."""

    if not _SESSION_TYPE_KEY_RE.match(key):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid session type key {key!r}: must match ^[a-z][a-z0-9_]*$",
        )
    active_dir, _data_root, baseline_dir = _resolve_session_restore_paths(context)
    baseline_path, _definition = _load_single_session_baseline(baseline_dir, key)
    target = (active_dir / f"{key}.md").resolve()
    try:
        target.relative_to(active_dir)
        _atomic_copy_bytes(baseline_path, target)
    except ValueError as error:
        raise HTTPException(
            status_code=500, detail=f"Resolved session target escapes its directory: {target}"
        ) from error
    except OSError as error:
        raise HTTPException(
            status_code=500, detail=f"Failed to restore session baseline: {error}"
        ) from error
    _trigger_session_configuration_reload(context)
    return RestoreDefaultsResponse(restored=[key])


@router.put("/api/prompts/session-types/{key}", response_model=PromptSessionTypeResponse)
@_serializes_mutable_data
def update_prompt_session_type(
    key: str, payload: SessionTypeUpdateRequest, context: ContextDependency
) -> dict:
    """Update an existing session type. The URL key is immutable."""

    if not _SESSION_TYPE_KEY_RE.match(key):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid session type key {key!r}: must match ^[a-z][a-z0-9_]*$",
        )
    repo = _get_session_type_repo(context)

    existing = repo.get(key)
    if existing is None:
        raise HTTPException(
            status_code=404,
            detail=f"Session type '{key}' not found",
        )

    definition = payload.merge_into(existing, url_key=key)
    try:
        updated = repo.update(definition)
    except SessionTypeError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    _trigger_session_configuration_reload(context)
    return _session_type_payload_to_dict(updated, context)


@router.delete(
    "/api/prompts/session-types/{key}",
    response_model=DeletePromptConfigurationResponse,
)
@_serializes_mutable_data
def delete_prompt_session_type(
    key: str, context: ContextDependency
) -> DeletePromptConfigurationResponse:
    """Delete a custom session type; shipped types remain recoverable defaults."""

    if not _SESSION_TYPE_KEY_RE.match(key):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid session type key {key!r}: must match ^[a-z][a-z0-9_]*$",
        )
    repo = _get_session_type_repo(context)
    if repo.get(key) is None:
        raise HTTPException(status_code=404, detail=f"Session type '{key}' not found")
    is_shipped, _origin = _session_provenance(key, context)
    if is_shipped:
        raise HTTPException(
            status_code=409,
            detail=f"Shipped session type '{key}' cannot be deleted; restore it instead",
        )
    try:
        repo.delete(key)
    except SessionTypeError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    _trigger_session_configuration_reload(context)
    return DeletePromptConfigurationResponse(deleted=key)


# Register the list route before ``/{global_id}`` so the dynamic route cannot shadow it.
# Mutations resolve cached source metadata and atomically rewrite only validated files.

_GLOBAL_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
