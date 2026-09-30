"""Installation-wide Quick Action configuration endpoints."""

from __future__ import annotations

from functools import wraps
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.config.user_data import mutable_data_lock
from src.prompts.quick_actions import (
    QuickAction,
    QuickActionError,
    QuickActionRepository,
    provenance_for_actions,
    restore_all_shipped_actions,
    shipped_actions_need_restore,
)

from .dependencies import ContextDependency

router = APIRouter(prefix="/api/quick-actions", tags=["quick-actions"])


def _serializes_mutable_data(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with mutable_data_lock:
            return function(*args, **kwargs)

    return wrapped


class QuickActionInfo(QuickAction):
    """Editor response including immutable shipped/default provenance."""

    is_shipped: bool
    origin: str


class QuickActionCreateRequest(QuickAction):
    """New actions append to the configured installation-wide order."""


class QuickActionUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str | None = Field(default=None, min_length=1)
    prompt: str | None = Field(default=None, min_length=1)

    @field_validator("label", "prompt")
    @classmethod
    def validate_nonblank_text(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must not be blank or whitespace-only")
        return value


class QuickActionDeleteResponse(BaseModel):
    deleted: str


class QuickActionRestoreResponse(BaseModel):
    restored: list[str]


class QuickActionListResponse(BaseModel):
    """Current actions plus whether restoring defaults would change them."""

    actions: list[QuickActionInfo]
    can_restore_defaults: bool


def _repositories(
    context: ContextDependency,
) -> tuple[QuickActionRepository, QuickActionRepository]:
    """Resolve active and baseline files below the shared prompt-data root."""

    active_root = Path(context.settings.prompt_library_path).resolve()
    configured = getattr(context.settings, "prompt_defaults_path", None)
    baseline_root = (
        Path(configured).resolve()
        if type(configured) is str
        else (active_root.parent / "prompt_defaults").resolve()
    )
    return QuickActionRepository(active_root), QuickActionRepository(baseline_root)


def _read(repository: QuickActionRepository, *, baseline: bool = False) -> list[QuickAction]:
    try:
        actions = repository.list()
    except QuickActionError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if baseline and not actions:
        raise HTTPException(status_code=422, detail="Quick Action baseline is empty or missing")
    return actions


def _info(active: list[QuickAction], baseline: list[QuickAction]) -> list[QuickActionInfo]:
    return [
        QuickActionInfo(
            **action.model_dump(),
            is_shipped=is_shipped,
            origin=origin,
        )
        for action, is_shipped, origin in provenance_for_actions(active, baseline)
    ]


def _write(repository: QuickActionRepository, actions: list[QuickAction]) -> None:
    try:
        repository.write(actions)
    except QuickActionError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("", response_model=QuickActionListResponse)
def list_quick_actions(context: ContextDependency) -> QuickActionListResponse:
    active_repo, baseline_repo = _repositories(context)
    active = _read(active_repo)
    baseline = _read(baseline_repo, baseline=True)
    return QuickActionListResponse(
        actions=_info(active, baseline),
        can_restore_defaults=shipped_actions_need_restore(active, baseline),
    )


@router.post("", response_model=QuickActionInfo, status_code=201)
@_serializes_mutable_data
def create_quick_action(
    payload: QuickActionCreateRequest, context: ContextDependency
) -> QuickActionInfo:
    active_repo, baseline_repo = _repositories(context)
    active = _read(active_repo)
    baseline = _read(baseline_repo, baseline=True)
    if any(action.id == payload.id for action in active):
        raise HTTPException(status_code=409, detail=f"Quick Action '{payload.id}' already exists")
    if any(action.id == payload.id for action in baseline):
        raise HTTPException(
            status_code=409,
            detail=(
                f"Quick Action '{payload.id}' is shipped; "
                "restore it instead of creating a custom replacement"
            ),
        )
    action = QuickAction.model_validate(payload.model_dump())
    _write(active_repo, [*active, action])
    return _info([*active, action], baseline)[-1]


@router.put("/{action_id}", response_model=QuickActionInfo)
@_serializes_mutable_data
def update_quick_action(
    action_id: str, payload: QuickActionUpdateRequest, context: ContextDependency
) -> QuickActionInfo:
    active_repo, baseline_repo = _repositories(context)
    active = _read(active_repo)
    baseline = _read(baseline_repo, baseline=True)
    index = next((index for index, action in enumerate(active) if action.id == action_id), None)
    if index is None:
        raise HTTPException(status_code=404, detail=f"Quick Action '{action_id}' not found")
    current = active[index]
    replacement = QuickAction(
        id=current.id,
        label=current.label if payload.label is None else payload.label,
        prompt=current.prompt if payload.prompt is None else payload.prompt,
    )
    active[index] = replacement
    _write(active_repo, active)
    return _info(active, baseline)[index]


@router.delete("/{action_id}", response_model=QuickActionDeleteResponse)
@_serializes_mutable_data
def delete_quick_action(action_id: str, context: ContextDependency) -> QuickActionDeleteResponse:
    active_repo, _baseline_repo = _repositories(context)
    active = _read(active_repo)
    retained = [action for action in active if action.id != action_id]
    if len(retained) == len(active):
        raise HTTPException(status_code=404, detail=f"Quick Action '{action_id}' not found")
    _write(active_repo, retained)
    return QuickActionDeleteResponse(deleted=action_id)


def _restore_single(
    active: list[QuickAction], baseline: list[QuickAction], action_id: str
) -> list[QuickAction]:
    default_index = next((i for i, action in enumerate(baseline) if action.id == action_id), None)
    if default_index is None:
        raise HTTPException(status_code=404, detail=f"No shipped Quick Action '{action_id}'")
    replacement = baseline[default_index]
    existing_index = next((i for i, action in enumerate(active) if action.id == action_id), None)
    if existing_index is not None:
        active[existing_index] = replacement
        return active

    # Restore deleted defaults at their canonical position among existing
    # shipped actions, without disturbing unrelated custom action order.
    baseline_positions = {action.id: index for index, action in enumerate(baseline)}
    insert_at = next(
        (
            i
            for i, action in enumerate(active)
            if action.id in baseline_positions and baseline_positions[action.id] > default_index
        ),
        len(active),
    )
    active.insert(insert_at, replacement)
    return active


@router.post("/{action_id}/restore-default", response_model=QuickActionRestoreResponse)
@_serializes_mutable_data
def restore_default_quick_action(
    action_id: str, context: ContextDependency
) -> QuickActionRestoreResponse:
    active_repo, baseline_repo = _repositories(context)
    active = _read(active_repo)
    baseline = _read(baseline_repo, baseline=True)
    restored = _restore_single(active, baseline, action_id)
    _write(active_repo, restored)
    return QuickActionRestoreResponse(restored=[action_id])


@router.post("/restore-defaults", response_model=QuickActionRestoreResponse)
@_serializes_mutable_data
def restore_default_quick_actions(context: ContextDependency) -> QuickActionRestoreResponse:
    active_repo, baseline_repo = _repositories(context)
    # Both sources are fully parsed before the one active write, making the
    # bulk reset all-or-nothing for malformed baseline files.
    active = _read(active_repo)
    baseline = _read(baseline_repo, baseline=True)
    _write(active_repo, restore_all_shipped_actions(active, baseline))
    return QuickActionRestoreResponse(restored=[action.id for action in baseline])


__all__ = [
    "QuickActionCreateRequest",
    "QuickActionDeleteResponse",
    "QuickActionInfo",
    "QuickActionListResponse",
    "QuickActionRestoreResponse",
    "QuickActionUpdateRequest",
    "router",
]
