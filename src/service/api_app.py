"""FastAPI construction, lifecycle, static assets, and error envelopes."""

from __future__ import annotations

import threading
from collections.abc import Mapping
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from src import __version__
from src.server_logging import configure_access_log_filter
from src.service.activity import (
    ApplicationActivity,
    is_activity_request,
    request_params,
    should_record_successful_request,
)
from src.service.api_errors import api_error
from src.service.context import build_app_context
from src.service.host_routes import router as host_router
from src.service.routers import (
    application_router,
    defaults_router,
    discussions_router,
    globals_router,
    local_ai_router,
    preview_router,
    quick_actions_router,
    roles_router,
    session_types_router,
    sessions_router,
)

_GENERIC_HTTP_ERROR_CODES = {
    400: "bad_request",
    401: "authentication_required",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    422: "validation_failed",
    429: "rate_limited",
    500: "internal_error",
    503: "service_unavailable",
}


@asynccontextmanager
async def _lifespan(application: FastAPI):
    application.state.application_activity.record("server_started")
    try:
        yield
    finally:
        application.state.application_activity.record("server_stopped")
        manager = getattr(application.state, "local_ai_manager", None)
        if manager is not None:
            manager.shutdown()


async def _structured_http_exception_handler(
    _request: Request, exception: HTTPException
) -> JSONResponse:
    code = getattr(exception, "error_code", None)
    if not isinstance(code, str) or not code:
        code = _GENERIC_HTTP_ERROR_CODES.get(exception.status_code, f"http_{exception.status_code}")
    params = getattr(exception, "error_params", {})
    if not isinstance(params, Mapping):
        params = {}
    return JSONResponse(
        status_code=exception.status_code,
        content={
            "detail": exception.detail,
            "error": {"code": code, "params": dict(params)},
        },
        headers=exception.headers,
    )


async def _structured_request_validation_handler(
    _request: Request, exception: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "detail": jsonable_encoder(exception.errors()),
            "error": {"code": "request_validation_failed", "params": {}},
        },
    )


def create_app() -> FastAPI:
    """Create the complete application with every HTTP route and lifecycle hook."""

    configure_access_log_filter()
    application = FastAPI(
        title="AQA API",
        version=__version__,
        lifespan=_lifespan,
    )
    application.state.app_context = None
    application.state.app_context_factory = build_app_context
    application.state.app_context_lock = threading.Lock()
    application.state.local_ai_manager_lock = threading.Lock()
    application.state.application_activity = ApplicationActivity(capacity=500)

    @application.middleware("http")
    async def record_application_activity(request: Request, call_next):
        """Record only fixed, non-sensitive metadata for application API calls."""

        if not is_activity_request(request.url.path):
            return await call_next(request)

        try:
            response = await call_next(request)
        except Exception:
            application.state.application_activity.record(
                "unexpected_failure",
                level="error",
                params=request_params(request.method, _route_template(request)),
            )
            raise

        if response.status_code >= 400:
            application.state.application_activity.record(
                "http_rejection",
                level="error" if response.status_code >= 500 else "warning",
                params={
                    **request_params(request.method, _route_template(request)),
                    "status": response.status_code,
                },
            )
        elif should_record_successful_request(request.method):
            application.state.application_activity.record(
                "request_completed",
                params={
                    **request_params(request.method, _route_template(request)),
                    "status": response.status_code,
                },
            )
        return response

    application.add_exception_handler(HTTPException, _structured_http_exception_handler)
    application.add_exception_handler(
        RequestValidationError, _structured_request_validation_handler
    )
    application.include_router(application_router)
    application.include_router(preview_router)
    application.include_router(defaults_router)
    application.include_router(quick_actions_router)
    application.include_router(sessions_router)
    application.include_router(host_router)
    application.include_router(discussions_router)
    application.include_router(local_ai_router)
    application.include_router(roles_router)
    application.include_router(session_types_router)
    application.include_router(globals_router)

    dist_dir = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if dist_dir.exists():
        assets_dir = dist_dir / "assets"
        if assets_dir.exists():
            application.mount(
                "/assets",
                StaticFiles(directory=assets_dir),
                name="static-assets",
            )

        @application.get("/")
        def serve_frontend() -> FileResponse:
            return FileResponse(dist_dir / "index.html")

    return application


def _route_template(request: Request) -> str | None:
    """Return a resolved route pattern, never the actual request path."""

    route = request.scope.get("route")
    route_path = getattr(route, "path", None)
    return route_path if isinstance(route_path, str) and route_path.startswith("/api/") else None


__all__ = ["api_error", "create_app"]
