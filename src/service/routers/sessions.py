"""Stored-session listing, hydration, metadata, reveal, and deletion routes."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import TypeAdapter

from src.service.api_errors import api_error
from src.service.api_schemas import (
    AgentSnapshotModel,
    BulkDeleteSessionsRequest,
    BulkDeleteSessionsResponse,
    DeleteSessionResponse,
    MaterialContextSnapshotModel,
    MessageSnapshotModel,
    OpenSessionResponse,
    RenameSessionRequest,
    RevealSessionResponse,
    SessionSummaryModel,
    SetSessionFavoriteRequest,
    SynthesisConfigModel,
)
from src.service.context import AppContext
from src.service.discussion_storage import SessionDeletionRollbackError

from .dependencies import ContextDependency

router = APIRouter(prefix="/api/sessions", tags=["sessions"])
_message_snapshot_adapter = TypeAdapter(MessageSnapshotModel)


def reveal_path(path: Path) -> None:
    """Open the platform file manager without exposing paths to the client."""

    if sys.platform == "darwin":
        argv = ["open", "-R", str(path)]
    elif sys.platform == "win32":
        argv = ["explorer", f"/select,{path}"]
    else:
        argv = ["xdg-open", str(path.parent)]
    try:
        subprocess.run(
            argv,
            shell=False,
            check=False,
            timeout=5,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.TimeoutExpired, OSError):
        raise HTTPException(
            status_code=502,
            detail="Reveal command could not be launched",
        ) from None


def current_open_file_id(context: AppContext) -> str | None:
    return context.discussion.current_session_file_id()


def summarize_session(
    item: dict,
    *,
    is_open: bool,
) -> SessionSummaryModel:
    return SessionSummaryModel(
        file_id=str(item["file_id"]),
        title=str(item.get("title", "")),
        created=str(item.get("created", "")),
        updated=str(item.get("updated", "")),
        session_type=str(item["session_type"]),
        round_count=int(item.get("round_count", 0)),
        is_open=is_open,
        is_favorite=bool(item.get("is_favorite", False)),
    )


@router.get("", response_model=list[SessionSummaryModel])
def list_sessions(context: ContextDependency) -> list[SessionSummaryModel]:
    current_id = current_open_file_id(context)
    return [
        summarize_session(
            item,
            is_open=current_id == item.get("file_id"),
        )
        for item in context.discussion.list_sessions()
    ]


@router.post("/{file_id}/open", response_model=OpenSessionResponse)
def open_session(file_id: str, context: ContextDependency) -> OpenSessionResponse:
    try:
        snapshot = context.discussion.snapshot_open_session(file_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Session not found")

    context.settings.last_active_discussion_id = str(snapshot["file_id"])
    try:
        context.settings.save_user_settings()
    except OSError:
        # Opening a valid discussion must not depend on the resume convenience.
        pass

    material_context = MaterialContextSnapshotModel.model_validate(snapshot["material_context"])
    safe_agents = [
        {
            key: value
            for key, value in agent.items()
            if key not in {"api_key", "api_secret", "token", "password"}
        }
        for agent in snapshot["agents"]
    ]
    return OpenSessionResponse.model_validate(
        {
            "file_id": snapshot["file_id"],
            "title": snapshot["title"],
            "material": snapshot["material"],
            "initial_question": snapshot["initial_question"],
            "messages": [
                _message_snapshot_adapter.validate_python(message)
                for message in snapshot["messages"]
            ],
            "material_context": material_context,
            "agents": [AgentSnapshotModel.model_validate(agent) for agent in safe_agents],
            "synthesis": SynthesisConfigModel.model_validate(snapshot["synthesis"]),
            "sequential_mode": snapshot["sequential_mode"],
            "round_number": snapshot["round_number"],
            "round_status": snapshot.get("round_status"),
            "has_active_discussion": snapshot["has_active_discussion"],
            "round_provider_provenance": snapshot.get("round_provider_provenance", []),
        }
    )


def _updated_summary(context: AppContext, file_id: str) -> SessionSummaryModel:
    item = next(
        (
            candidate
            for candidate in context.discussion.list_sessions()
            if candidate.get("file_id") == file_id
        ),
        None,
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return summarize_session(
        item,
        is_open=current_open_file_id(context) == file_id,
    )


@router.patch("/{file_id}", response_model=SessionSummaryModel)
def rename_session(
    file_id: str,
    payload: RenameSessionRequest,
    context: ContextDependency,
) -> SessionSummaryModel:
    title = payload.title.strip()
    if not title:
        raise HTTPException(
            status_code=422,
            detail="title must not be blank or whitespace-only",
        )
    try:
        updated = context.discussion.rename_session(file_id, title)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not updated:
        raise HTTPException(status_code=404, detail="Session not found")
    return _updated_summary(context, file_id)


@router.put("/{file_id}/favorite", response_model=SessionSummaryModel)
def set_session_favorite(
    file_id: str,
    payload: SetSessionFavoriteRequest,
    context: ContextDependency,
) -> SessionSummaryModel:
    try:
        updated = context.discussion.set_session_favorite(
            file_id,
            payload.is_favorite,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not updated:
        raise HTTPException(status_code=404, detail="Session not found")
    return _updated_summary(context, file_id)


@router.post("/{file_id}/reveal", response_model=RevealSessionResponse)
def reveal_session(file_id: str, context: ContextDependency) -> RevealSessionResponse:
    try:
        path = context.discussion.session_path_for_reveal(file_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if path is None:
        raise HTTPException(status_code=404, detail="Session not found")
    reveal_path(path)
    return RevealSessionResponse()


@router.post("/bulk-delete", response_model=BulkDeleteSessionsResponse)
def bulk_delete_sessions(
    payload: BulkDeleteSessionsRequest, context: ContextDependency
) -> BulkDeleteSessionsResponse:
    try:
        result = context.discussion.delete_sessions(payload.mode, payload.expected_file_ids)
    except ValueError as exc:
        if str(exc) == "session_catalog_changed":
            raise api_error(
                409,
                "session_catalog_changed",
                "The session catalogue changed before deletion.",
            ) from exc
        raise
    except SessionDeletionRollbackError as exc:
        if context.settings.last_active_discussion_id in exc.deleted_ids:
            context.settings.last_active_discussion_id = None
            try:
                context.settings.save_user_settings()
            except OSError:
                pass
        raise api_error(
            500,
            "session_deletion_inconsistent",
            "Session deletion could not be fully rolled back.",
            params={
                "deleted_ids": exc.deleted_ids,
                "retained_ids": exc.retained_ids,
                "deleted_count": len(exc.deleted_ids),
                "retained_count": len(exc.retained_ids),
                "was_open": exc.was_active,
            },
        ) from exc
    except OSError as exc:
        raise api_error(
            500,
            "session_deletion_failed",
            "Sessions could not be deleted; no sessions were changed.",
        ) from exc
    last_active_id = context.settings.last_active_discussion_id
    if last_active_id and last_active_id in result.get("deleted_ids", []):
        context.settings.last_active_discussion_id = None
        try:
            context.settings.save_user_settings()
        except OSError:
            pass
    return BulkDeleteSessionsResponse(
        deleted_count=int(result.get("deleted_count", 0)),
        was_open=bool(result.get("was_active", False)),
        deleted_ids=list(result.get("deleted_ids", [])),
    )


@router.delete("/{file_id}", response_model=DeleteSessionResponse)
def delete_session(file_id: str, context: ContextDependency) -> DeleteSessionResponse:
    try:
        result = context.discussion.delete_session(file_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OSError as exc:
        raise api_error(
            500,
            "session_deletion_failed",
            "The session could not be deleted; it was not changed.",
        ) from exc
    if not result.get("deleted"):
        raise HTTPException(status_code=404, detail="Session not found")
    if context.settings.last_active_discussion_id == file_id:
        context.settings.last_active_discussion_id = None
        try:
            context.settings.save_user_settings()
        except OSError:
            pass
    return DeleteSessionResponse(
        deleted=bool(result.get("deleted", False)),
        was_open=bool(result.get("was_active", False)),
        deleted_ids=list(result.get("deleted_ids", [])),
        deleted_count=len(result.get("deleted_ids", [])),
    )
