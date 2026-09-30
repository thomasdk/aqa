"""Application health and packaged-process control endpoints."""

from __future__ import annotations

import os

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Query, Request

from src.config.settings import DEFAULT_LOCAL_AI_CONTEXT_TOKENS
from src.local_ai.catalog import MODELS
from src.service.activity import ApplicationActivity
from src.service.api_schemas import (
    ApplicationActivityResponse,
    UIPreferencesResponse,
    UIPreferencesUpdateRequest,
)

from .dependencies import ContextDependency

router = APIRouter(tags=["application"])


def require_packaged_loopback(request: Request) -> None:
    """Restrict packaged-process actions to local requests from the desktop app."""

    if os.environ.get("AQA_PACKAGED_MODE") != "1":
        raise HTTPException(status_code=404, detail="Packaged action is unavailable")
    host = request.client.host if request.client else ""
    if host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        raise HTTPException(status_code=403, detail="Packaged action requires a local connection")


@router.get("/api/health")
def healthcheck() -> dict:
    return {
        "status": "ok",
    }


@router.get("/api/application/status")
def application_status(request: Request) -> dict[str, bool | str | None]:
    callback = getattr(request.app.state, "shutdown_callback", None)
    token = getattr(request.app.state, "quit_token", None)
    can_quit = (
        os.environ.get("AQA_PACKAGED_MODE") == "1"
        and callable(callback)
        and isinstance(token, str)
        and bool(token)
    )
    return {
        "can_quit": can_quit,
        "quit_token": token if can_quit else None,
    }


@router.get("/api/application/preferences", response_model=UIPreferencesResponse)
def application_preferences(context: ContextDependency) -> UIPreferencesResponse:
    return UIPreferencesResponse(
        ui_locale=context.settings.ui_locale,
        appearance=context.settings.appearance,
        ai_source=context.settings.ai_source,
        local_ai_context_tokens=context.settings.local_ai_context_tokens,
        local_ai_context_default_tokens=DEFAULT_LOCAL_AI_CONTEXT_TOKENS,
        local_ai_mtp_enabled=context.settings.local_ai_mtp_enabled,
        notifications_enabled=context.settings.notifications_enabled,
        notification_permission_auto_attempted=context.settings.notification_permission_auto_attempted,
        prevent_sleep_while_generating=context.settings.prevent_sleep_while_generating,
        last_active_discussion_id=context.settings.last_active_discussion_id,
    )


@router.put("/api/application/preferences", response_model=UIPreferencesResponse)
def update_application_preferences(
    payload: UIPreferencesUpdateRequest,
    context: ContextDependency,
) -> UIPreferencesResponse:
    if payload.ui_locale is not None:
        context.settings.ui_locale = payload.ui_locale
    if payload.appearance is not None:
        context.settings.appearance = payload.appearance
    if payload.ai_source is not None:
        context.settings.ai_source = payload.ai_source
    if payload.local_ai_context_tokens is not None:
        maximum = (
            MODELS[payload.local_ai_context_model_id].supported_context_tokens
            if payload.local_ai_context_model_id
            else 131_072
        )
        if payload.local_ai_context_tokens > maximum:
            raise HTTPException(status_code=422, detail="Context exceeds the selected model limit")
        context.settings.local_ai_context_tokens = payload.local_ai_context_tokens
    if payload.local_ai_mtp_enabled is not None:
        context.settings.local_ai_mtp_enabled = payload.local_ai_mtp_enabled
    if payload.notifications_enabled is not None:
        context.settings.notifications_enabled = payload.notifications_enabled
    if payload.notification_permission_auto_attempted is not None:
        context.settings.notification_permission_auto_attempted = True
    if payload.prevent_sleep_while_generating is not None:
        context.settings.prevent_sleep_while_generating = payload.prevent_sleep_while_generating
    if "last_active_discussion_id" in payload.model_fields_set:
        context.settings.last_active_discussion_id = payload.last_active_discussion_id
    context.settings.save_user_settings()
    return application_preferences(context)


@router.get(
    "/api/application/activity",
    response_model=ApplicationActivityResponse,
)
def application_activity(
    request: Request,
    after: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
) -> dict:
    """Return safe, process-local technical activity after a cursor."""

    activity = getattr(request.app.state, "application_activity", None)
    if not isinstance(activity, ApplicationActivity):
        # ``create_app`` always sets this state. The fallback protects direct
        # router embedding without exposing implementation data.
        activity = ApplicationActivity()
        request.app.state.application_activity = activity
    events, next_cursor, truncated = activity.since(after, limit)
    return {
        "events": events,
        "next_cursor": next_cursor,
        "truncated": truncated,
    }


@router.post("/api/application/quit", status_code=202)
def quit_application(
    request: Request,
    background_tasks: BackgroundTasks,
    context: ContextDependency,
    x_aqa_action: str | None = Header(default=None),
) -> dict[str, str]:
    require_packaged_loopback(request)
    expected_token = getattr(request.app.state, "quit_token", None)
    if not isinstance(expected_token, str) or not expected_token or x_aqa_action != expected_token:
        raise HTTPException(
            status_code=403,
            detail="Application shutdown confirmation is invalid",
        )
    shutdown_callback = getattr(request.app.state, "shutdown_callback", None)
    if not callable(shutdown_callback):
        raise HTTPException(
            status_code=503,
            detail="Application shutdown is unavailable for this server",
        )

    context.discussion.cancel_active_generation()
    background_tasks.add_task(shutdown_callback)
    return {"status": "shutting_down"}
