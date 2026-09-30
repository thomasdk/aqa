"""Validated, file-backed configuration for discussion Quick Actions.

Quick actions are installation-wide UI conveniences.  They are deliberately
kept outside saved discussion snapshots: activating one only inserts its
prompt into the discussion, so later configuration changes cannot rewrite
history.  The active file lives beside the other prompt assets and its shipped
baseline is kept in ``data/prompt_defaults``.
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class QuickActionError(ValueError):
    """Raised for invalid Quick Action configuration or file operations."""


class QuickAction(BaseModel):
    """One reusable instruction inserted into the next discussion round."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1)
    label: str = Field(..., min_length=1)
    prompt: str = Field(..., min_length=1)

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if not _ID_RE.fullmatch(value):
            raise ValueError("id must match ^[a-z][a-z0-9_]*$")
        return value

    @field_validator("label", "prompt")
    @classmethod
    def validate_nonblank_text(cls, value: str) -> str:
        """Reject blank values without rewriting configured prompt text."""

        # Labels and prompts are configured content.  Prompt indentation and
        # newlines can carry user intent, so validation must not trim them.
        if not value.strip():
            raise ValueError("must not be blank or whitespace-only")
        return value


class QuickActionRepository:
    """Atomically load and write a single ordered YAML action list."""

    filename = "quick_actions.yaml"

    def __init__(self, base_path: Path | str):
        self.base_path = Path(base_path).resolve()

    @property
    def path(self) -> Path:
        path = (self.base_path / self.filename).resolve()
        try:
            path.relative_to(self.base_path)
        except ValueError as error:  # defensive despite the fixed filename
            raise QuickActionError("Quick Action path escapes repository root") from error
        return path

    def list(self) -> list[QuickAction]:
        path = self.path
        if not path.is_file():
            return []
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError) as error:
            raise QuickActionError(f"Cannot read Quick Actions: {error}") from error
        if not isinstance(raw, dict) or set(raw) != {"quick_actions"}:
            raise QuickActionError("Quick Action file must contain only 'quick_actions'")
        entries = raw["quick_actions"]
        if not isinstance(entries, list):
            raise QuickActionError("quick_actions must be a list")
        try:
            actions = [QuickAction.model_validate(item) for item in entries]
        except Exception as error:
            raise QuickActionError(f"Invalid Quick Action: {error}") from error
        ids = [action.id for action in actions]
        if len(ids) != len(set(ids)):
            raise QuickActionError("Quick Action IDs must be unique")
        return actions

    def require(self, action_id: str) -> QuickAction:
        for action in self.list():
            if action.id == action_id:
                return action
        raise QuickActionError(f"Quick Action '{action_id}' not found")

    def write(self, actions: list[QuickAction]) -> None:
        """Validate then atomically replace the active configuration."""

        ids = [action.id for action in actions]
        if len(ids) != len(set(ids)):
            raise QuickActionError("Quick Action IDs must be unique")
        try:
            self.base_path.mkdir(parents=True, exist_ok=True)
            payload = {"quick_actions": [action.model_dump(mode="json") for action in actions]}
            encoded = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
            fd, temporary_name = tempfile.mkstemp(
                prefix=".quick_actions-", suffix=".tmp", dir=self.base_path, text=True
            )
            temporary_path = Path(temporary_name)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(encoded)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary_path, self.path)
            except BaseException:
                temporary_path.unlink(missing_ok=True)
                raise
        except OSError as error:
            raise QuickActionError(f"Cannot write Quick Actions: {error}") from error

    def create(self, action: QuickAction) -> QuickAction:
        actions = self.list()
        if any(current.id == action.id for current in actions):
            raise QuickActionError(f"Quick Action '{action.id}' already exists")
        self.write([*actions, action])
        return action

    def update(self, action_id: str, *, label: str | None, prompt: str | None) -> QuickAction:
        actions = self.list()
        index = next((i for i, action in enumerate(actions) if action.id == action_id), None)
        if index is None:
            raise QuickActionError(f"Quick Action '{action_id}' not found")
        old = actions[index]
        updated = QuickAction(
            id=old.id,
            label=old.label if label is None else label,
            prompt=old.prompt if prompt is None else prompt,
        )
        actions[index] = updated
        self.write(actions)
        return updated

    def delete(self, action_id: str) -> None:
        actions = self.list()
        retained = [action for action in actions if action.id != action_id]
        if len(retained) == len(actions):
            raise QuickActionError(f"Quick Action '{action_id}' not found")
        self.write(retained)


def provenance_for_actions(
    active: list[QuickAction], baseline: list[QuickAction]
) -> list[tuple[QuickAction, bool, str]]:
    """Classify active actions without changing their configured order."""

    shipped = {action.id: action for action in baseline}
    result: list[tuple[QuickAction, bool, str]] = []
    for action in active:
        default = shipped.get(action.id)
        if default is None:
            result.append((action, False, "custom"))
        elif action == default:
            result.append((action, True, "shipped_default"))
        else:
            result.append((action, True, "shipped_modified"))
    return result


def shipped_actions_need_restore(active: list[QuickAction], baseline: list[QuickAction]) -> bool:
    """Report whether a shipped action is missing or differs from its baseline."""

    active_by_id = {action.id: action for action in active}
    return any(active_by_id.get(default.id) != default for default in baseline)


def restore_all_shipped_actions(
    active: list[QuickAction], baseline: list[QuickAction]
) -> list[QuickAction]:
    """Restore every shipped entry while retaining unrelated custom entries.

    Shipped entries take their canonical baseline order.  Custom entries retain
    their active relative order and follow them, making the restored default
    set deterministic regardless of which entries are currently present.
    """

    baseline_ids = {action.id for action in baseline}
    custom = [action for action in active if action.id not in baseline_ids]
    return [*baseline, *custom]
