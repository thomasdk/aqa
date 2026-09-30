"""Domain errors for LLM adapter failures."""

from __future__ import annotations

import re
from collections.abc import Iterable


class LLMError(RuntimeError):
    """Base error for LLM adapter failures."""

    code = "provider_request_failed"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code


class LLMRequestError(LLMError):
    """Raised when an HTTP request to the LLM backend fails."""


class LLMConnectionError(LLMRequestError):
    """Raised when the LLM backend is unreachable or times out."""

    code = "provider_connection_failed"


class LLMModelCrashedError(LLMRequestError):
    """Raised when an OpenAI-compatible host reports a model crash."""

    code = "provider_model_crashed"


class LLMHealthCheckError(LLMError):
    """Raised when an adapter health-check fails."""

    code = "provider_health_check_failed"


class LLMTokenCountError(LLMRequestError):
    """Raised when a host cannot return a valid token-count response."""


class LLMTokenCountUnsupportedError(LLMTokenCountError):
    """Raised when an otherwise usable host does not expose a count endpoint."""


class LLMGenerationLengthLimitError(LLMRequestError):
    """Raised after a stream ends because the provider reached its length limit."""


# Bound provider error text so upstream HTML responses cannot flood the UI.
MAX_ERROR_LEN = 500
# Non-JSON response previews use a smaller bound within the full error message.
ERROR_PREVIEW_LEN = 200

_SENSITIVE_ERROR_PATTERNS = (
    re.compile(r"(?i)(\bbearer\s+)([^\s,;\]\[{}\"']+)"),
    re.compile(
        r"(?i)(\b(?:authorization|api[_ -]?key|access[_ -]?token|refresh[_ -]?token)"
        r"\s*[:=]\s*[\"']?)([^\s,;\]\[{}\"']+)"
    ),
    re.compile(r"(?i)([?&](?:api_key|access_token|refresh_token|token)=)([^&\s]+)"),
)


def redact_sensitive_error(text: str | None, *, secrets: Iterable[str] = ()) -> str:
    """Remove credentials from untrusted provider and transport error text."""
    if not text:
        return ""
    redacted = str(text)
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "[REDACTED]")
    for pattern in _SENSITIVE_ERROR_PATTERNS:
        redacted = pattern.sub(r"\1[REDACTED]", redacted)
    return redacted


def truncate_error(text: str | None, *, limit: int = MAX_ERROR_LEN) -> str:
    """Return ``text`` shortened to ``limit`` characters with a marker.

    If truncated, appends ``...[truncated]`` so the user can see the cap kicked
    in. Empty / None input becomes the empty string.
    """
    if not text:
        return ""
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - len("...[truncated]")] + "...[truncated]"


def preview_response_body(body: str | None, *, limit: int = ERROR_PREVIEW_LEN) -> str:
    """Return a short, human-friendly preview of a response body.

    Strips newlines so the preview fits on one line in the UI. Use this for
    non-JSON error bodies (Vercel HTML, plain-text 404s, etc.) where the full
    body would be useless noise.
    """
    if not body:
        return ""
    one_line = " ".join(body.split())
    return truncate_error(one_line, limit=limit)
