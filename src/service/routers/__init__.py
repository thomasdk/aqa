"""Domain routers for the AQA HTTP API."""

from .application import router as application_router
from .defaults import router as defaults_router
from .discussions import router as discussions_router
from .globals import router as globals_router
from .local_ai import router as local_ai_router
from .preview import router as preview_router
from .quick_actions import router as quick_actions_router
from .roles import router as roles_router
from .session_types import router as session_types_router
from .sessions import router as sessions_router

__all__ = [
    "application_router",
    "defaults_router",
    "discussions_router",
    "globals_router",
    "local_ai_router",
    "preview_router",
    "quick_actions_router",
    "roles_router",
    "sessions_router",
    "session_types_router",
]
