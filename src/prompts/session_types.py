"""Validated, file-backed session-type definitions.

Each Markdown file combines UI metadata, setup fields, default agent prompts,
and discussion guidance. Writes are atomic and all file paths remain within the
configured repository root.
"""

from __future__ import annotations

import builtins
import os
import re
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from src.config.user_data import mutable_data_lock

# IDs use lowercase letters, digits, and underscores, starting with a letter.
_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def normalize_session_type_key(value: str | None) -> str:
    """Normalize whitespace around a canonical session type ID."""

    return (value or "").strip()


# These keys are a product contract, not user-configurable metadata.  A
# session type can change how a field is presented, but every discussion must
# carry the same three semantic values so prompt assembly and orchestration do
# not have to infer their meaning from a session-specific key.
SESSION_INPUT_KEYS: tuple[str, str, str] = (
    "research_material_context",
    "main_input",
    "additional_instructions",
)
SESSION_INPUT_REQUIRED: dict[str, bool] = {
    "research_material_context": False,
    "main_input": True,
    "additional_instructions": False,
}


def effective_session_input_value(
    key: str,
    value: str,
    default_text: str | None,
    include_unchanged_research_material_context: bool,
) -> str:
    """Return the saved input that belongs in effective model context.

    Only the research-material scaffold has an opt-in for an unchanged default.
    Line-ending normalization prevents a transport-only edit from activating it.
    """

    text = value.strip()
    if key != "research_material_context" or not text:
        return text

    def normalized(item: str) -> str:
        return item.replace("\r\n", "\n").replace("\r", "\n").strip()

    if (
        normalized(text) == normalized(default_text or "")
        and not include_unchanged_research_material_context
    ):
        return ""
    return text


class SessionInputDefinition(BaseModel):
    """One semantic setup field with session-specific UI metadata.

    ``prompt_heading`` is intentionally not localized: it becomes a stable
    heading in the model context, whereas labels and hints are UI metadata.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    key: str = Field(..., min_length=1)
    label: str = Field(..., min_length=1)
    hint: str | None = None
    default_text: str | None = None
    prompt_heading: str = Field(..., min_length=1)
    required: bool = False

    @field_validator("key")
    @classmethod
    def _validate_key(cls, value: str) -> str:
        if not _ID_RE.match(value):
            raise ValueError("key muss mit ^[a-z][a-z0-9_]*$ matchen")
        return value


def default_session_inputs() -> list[SessionInputDefinition]:
    """Return independent default metadata for the fixed setup contract."""

    return [
        SessionInputDefinition(
            key="research_material_context",
            label="Research Material Context",
            hint="Optional context about the material and collection.",
            prompt_heading="RESEARCH MATERIAL CONTEXT",
            required=False,
        ),
        SessionInputDefinition(
            key="main_input",
            label="Main input",
            hint="The central question, interpretation, or task for this session.",
            prompt_heading="USER INPUT",
            required=True,
        ),
        SessionInputDefinition(
            key="additional_instructions",
            label="Additional instructions",
            hint="Optional guidance for the approach.",
            prompt_heading="ADDITIONAL USER INSTRUCTIONS",
            required=False,
        ),
    ]


def validate_session_inputs(
    definitions: list[SessionInputDefinition],
) -> list[SessionInputDefinition]:
    """Validate the immutable setup-field order and requiredness.

    Labels, hints, defaults and prompt headings are deliberately left free for
    each session type.  Keys, ordering and the required main input are not.
    """

    keys = [item.key for item in definitions]
    if keys != list(SESSION_INPUT_KEYS):
        raise ValueError(
            "session_inputs muss genau research_material_context, main_input, "
            "additional_instructions in dieser Reihenfolge enthalten"
        )
    invalid_required = [
        item.key for item in definitions if item.required is not SESSION_INPUT_REQUIRED[item.key]
    ]
    if invalid_required:
        raise ValueError(
            "Nur main_input ist erforderlich; research_material_context und "
            "additional_instructions sind optional"
        )
    return list(definitions)


def normalize_session_input_values(
    values: Mapping[str, object] | None = None,
) -> dict[str, str]:
    """Return the complete canonical value mapping and reject unknown keys."""

    source = values or {}
    unknown = set(source) - set(SESSION_INPUT_KEYS)
    if unknown:
        rendered = ", ".join(sorted(str(key) for key in unknown))
        raise ValueError(f"Unbekannte Session-Eingabeschlüssel: {rendered}")
    return {key: str(source.get(key) or "") for key in SESSION_INPUT_KEYS}


class SessionTypeError(ValueError):
    """Raised for session-type validation, path, and repository errors."""


class SessionTypeDefinition(BaseModel):
    """Validated session-type file content.

    The key is the file stem. ``session_inputs`` supplies UI metadata for the
    fixed setup contract, while ``body`` provides discussion guidance.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    key: str = Field(..., min_length=1)
    label: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    default_agent_prompt_ids: list[str] = Field(default_factory=list)
    # Authoritative setup schema. Prompt bodies remain separate from this UI
    # definition and are not translated.
    session_inputs: list[SessionInputDefinition] = Field(default_factory=default_session_inputs)
    include_unchanged_research_material_context_in_prompt: bool = False
    body: str = Field(..., min_length=1)

    @field_validator("key")
    @classmethod
    def _validate_key(cls, value: str) -> str:
        if not _ID_RE.match(value):
            raise ValueError("key muss mit ^[a-z][a-z0-9_]*$ matchen")
        return value

    @field_validator("default_agent_prompt_ids")
    @classmethod
    def _validate_agents(cls, value: list[str]) -> list[str]:
        for agent_id in value:
            if not isinstance(agent_id, str) or not _ID_RE.match(agent_id):
                raise ValueError(f"default_agent_prompt_ids enthält ungültige ID: {agent_id!r}")
        return list(value)

    @field_validator("session_inputs")
    @classmethod
    def _validate_inputs(cls, value: list[SessionInputDefinition]) -> list[SessionInputDefinition]:
        return validate_session_inputs(value)

    def input_for_key(self, key: str) -> SessionInputDefinition | None:
        return next((item for item in self.session_inputs if item.key == key), None)


_FRONTMATTER_RE = re.compile(
    r"\A---\s*\n(?P<fm>.*?)\n---\s*\n?(?P<body>.*)\Z",
    re.DOTALL,
)


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split YAML frontmatter from the Markdown body."""

    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise SessionTypeError("Datei hat kein gültiges YAML-Frontmatter (erwartet: --- ... ---)")
    raw_yaml = match.group("fm")
    body = match.group("body")
    try:
        loaded = yaml.safe_load(raw_yaml)
    except yaml.YAMLError as error:
        raise SessionTypeError(f"YAML-Frontmatter ist ungültig: {error}") from error
    if loaded is None:
        loaded = {}
    if not isinstance(loaded, dict):
        raise SessionTypeError("YAML-Frontmatter muss ein Mapping (Schlüssel/Wert) sein")
    return loaded, body


def _dump_frontmatter(frontmatter: dict[str, Any], body: str) -> str:
    """Build a Markdown document with YAML frontmatter."""

    yaml_text = yaml.safe_dump(
        frontmatter,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )
    # Persist a single trailing newline for stable file output.
    body_text = body if body.endswith("\n") else body + "\n"
    return f"---\n{yaml_text}---\n{body_text}"


class SessionTypeRepository:
    """Read and write ``SessionTypeDefinition`` files safely."""

    _GLOB = "*.md"

    def __init__(self, base_path: Path | str) -> None:
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
        # The cache is replaced only after a complete repository reload.
        self._cache: dict[str, SessionTypeDefinition] = {}
        self.reload()

    def reload(self) -> None:
        """Reload every direct ``*.md`` file in the repository directory."""

        new_cache: dict[str, SessionTypeDefinition] = {}
        for file_path in sorted(self.base_path.glob(self._GLOB)):
            if not file_path.is_file():
                continue
            try:
                definition = self._load_file(file_path)
            except SessionTypeError as error:
                logger.warning(
                    "Skipping invalid session-type file {path}: {error}",
                    path=file_path,
                    error=error,
                )
                continue

            if definition.key in new_cache:
                raise SessionTypeError(
                    f"Doppelte Session-Type-ID {definition.key!r} in {file_path}"
                )
            new_cache[definition.key] = definition

        self._cache = new_cache

    def list(self) -> builtins.list[SessionTypeDefinition]:
        """Return all session types sorted by key."""

        return [self._cache[key] for key in sorted(self._cache.keys())]

    def get(self, key: str) -> SessionTypeDefinition | None:
        """Return one session type, or ``None`` when it is absent."""

        return self._cache.get(key)

    def default(self) -> str:
        """Return the deterministically selected default session-type ID."""

        entries = self.list()
        if entries:
            return entries[0].key
        return "exploration"

    def create(self, definition: SessionTypeDefinition) -> SessionTypeDefinition:
        """Create a session type whose key is not already present."""

        self._validate(definition)
        if definition.key in self._cache:
            raise SessionTypeError(f"Session-Typ {definition.key!r} existiert bereits")
        self._write_file(definition)
        self._cache[definition.key] = definition
        logger.info("Created session type {key}", key=definition.key)
        return definition

    def update(self, definition: SessionTypeDefinition) -> SessionTypeDefinition:
        """Update an existing session type without changing its key."""

        self._validate(definition)
        existing = self._cache.get(definition.key)
        if existing is None:
            raise SessionTypeError(f"Session-Typ {definition.key!r} existiert nicht (Update)")
        self._write_file(definition)
        self._cache[definition.key] = definition
        logger.info("Updated session type {key}", key=definition.key)
        return definition

    def delete(self, key: str) -> None:
        """Delete a session type from the cache and file system."""

        if key not in self._cache:
            raise SessionTypeError(f"Session-Typ {key!r} existiert nicht (Löschen)")
        target = self._safe_path(key)
        with mutable_data_lock:
            try:
                target.unlink()
            except FileNotFoundError as error:
                raise SessionTypeError(
                    f"Session-Typ {key!r} existiert nicht mehr auf dem Dateisystem"
                ) from error
            except OSError as error:
                raise SessionTypeError(
                    f"Session-Typ {key!r} konnte nicht gelöscht werden: {error}"
                ) from error
        del self._cache[key]
        logger.info("Deleted session type {key}", key=key)

    def _load_file(self, file_path: Path) -> SessionTypeDefinition:
        text = file_path.read_text(encoding="utf-8")
        frontmatter, body = _split_frontmatter(text)

        key_from_fm = frontmatter.get("key") or file_path.stem
        data: dict[str, Any] = {
            "key": key_from_fm,
            "label": frontmatter.get("label", ""),
            "description": frontmatter.get("description", ""),
            "default_agent_prompt_ids": list(frontmatter.get("default_agent_prompt_ids", []) or []),
            "include_unchanged_research_material_context_in_prompt": frontmatter.get(
                "include_unchanged_research_material_context_in_prompt", False
            ),
            "body": body.strip("\n"),
        }
        # Omitted setup metadata receives the canonical defaults.  An
        # explicitly provided list must contain the complete fixed contract.
        if "session_inputs" in frontmatter:
            data["session_inputs"] = list(frontmatter.get("session_inputs") or [])
        try:
            definition = SessionTypeDefinition.model_validate(data)
        except ValidationError as error:
            raise SessionTypeError(f"Session-Type {file_path.name} ungültig: {error}") from error

        # The frontmatter key must match the file name.
        if definition.key != file_path.stem:
            raise SessionTypeError(
                f"key {definition.key!r} passt nicht zum Dateinamen {file_path.name!r}"
            )
        return definition

    def _validate(self, definition: SessionTypeDefinition) -> None:
        """Apply semantic validation in addition to Pydantic constraints."""

        # Revalidate objects supplied by callers that bypassed model creation.
        try:
            SessionTypeDefinition.model_validate(definition.model_dump())
        except ValidationError as error:
            raise SessionTypeError(f"Ungültige SessionTypeDefinition: {error}") from error

    def _write_file(self, definition: SessionTypeDefinition) -> None:
        target = self._safe_path(definition.key)
        frontmatter = {
            "key": definition.key,
            "label": definition.label,
            "description": definition.description,
            "default_agent_prompt_ids": list(definition.default_agent_prompt_ids),
            "include_unchanged_research_material_context_in_prompt": bool(
                definition.include_unchanged_research_material_context_in_prompt
            ),
            "session_inputs": [
                item.model_dump(mode="json", exclude_none=True)
                for item in definition.session_inputs
            ],
        }
        document = _dump_frontmatter(frontmatter, definition.body)
        _atomic_write(target, document)


def _safe_path(base_path: Path, key: str) -> Path:
    """Resolve a session-type key to a path contained by ``base_path``."""

    if not _ID_RE.match(key):
        raise SessionTypeError(f"Ungültige Session-Type-ID {key!r}: muss ^[a-z][a-z0-9_]*$ matchen")
    target = (base_path / f"{key}.md").resolve()
    base_resolved = base_path.resolve()
    try:
        target.relative_to(base_resolved)
    except ValueError as error:
        raise SessionTypeError(
            f"Pfad-Traversal erkannt: {target} liegt außerhalb von {base_resolved}"
        ) from error
    return target


def _atomic_write(target: Path, content: str) -> None:
    """Atomically write ``content`` to ``target`` in the same directory."""

    with mutable_data_lock:
        target.parent.mkdir(parents=True, exist_ok=True)
        # Same-directory replacement is atomic on POSIX and Windows.
        fd, tmp_path = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=str(target.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, target)
        except Exception:
            # Do not leave partial temporary files after a failed write.
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise


SessionTypeRepository._safe_path = lambda self, key: _safe_path(self.base_path, key)  # type: ignore[attr-defined]
