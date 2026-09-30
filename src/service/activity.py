"""Privacy-safe, in-memory application activity events.

The activity feed is intentionally diagnostic metadata, not a request log.  It
never accepts arbitrary request values, URLs, paths, exception messages, or
other potentially sensitive content.
"""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from threading import Lock
from typing import Any, Literal

ActivityLevel = Literal["info", "warning", "error"]


@dataclass(frozen=True)
class ActivityEvent:
    """A single public, structured diagnostic event."""

    sequence: int
    timestamp: str
    level: ActivityLevel
    code: str
    params: dict[str, str | int]


class ApplicationActivity:
    """A bounded, thread-safe feed for the lifetime of one application process."""

    def __init__(self, capacity: int = 500) -> None:
        if capacity < 1:
            raise ValueError("Activity capacity must be positive")
        self._events: deque[ActivityEvent] = deque(maxlen=capacity)
        self._lock = Lock()
        self._sequence = 0

    def record(
        self,
        code: str,
        *,
        level: ActivityLevel = "info",
        params: dict[str, str | int] | None = None,
    ) -> ActivityEvent:
        """Append an event whose parameters were selected from a safe allowlist."""

        # The callers provide only fixed event codes and fixed metadata values.
        # Copying avoids later caller mutation changing a recorded event.
        safe_params = dict(params or {})
        with self._lock:
            self._sequence += 1
            event = ActivityEvent(
                sequence=self._sequence,
                timestamp=datetime.now(UTC).isoformat(),
                level=level,
                code=code,
                params=safe_params,
            )
            self._events.append(event)
            return event

    def since(self, after: int, limit: int) -> tuple[list[dict[str, Any]], int, bool]:
        """Return chronological events after a cursor and whether history was lost."""

        with self._lock:
            oldest_sequence = self._events[0].sequence if self._events else self._sequence + 1
            truncated = bool(self._events) and after < oldest_sequence - 1
            events = [event for event in self._events if event.sequence > after][:limit]
            next_cursor = events[-1].sequence if events else after
            return [asdict(event) for event in events], next_cursor, truncated

    def clear(self) -> None:
        """Clear retained events while preserving the monotonic cursor (tests only)."""

        with self._lock:
            self._events.clear()


def is_activity_request(path: str) -> bool:
    """Whether an API request is eligible for activity recording."""

    return path.startswith("/api/") and path not in {
        "/api/health",
        "/api/application/status",
        "/api/application/activity",
    }


def should_record_successful_request(method: str) -> bool:
    """Keep successful activity focused on actions, not read/poll traffic.

    The application makes many successful GET requests while it is idle (for
    example, host and Local-AI status refreshes). Recording those requests
    turns the Activity pane into a request log and quickly hides the useful
    lifecycle and discussion diagnostics. Errors remain recorded regardless
    of method by the middleware.
    """

    return method.upper() != "GET"


def request_params(method: str, route_template: str | None) -> dict[str, str]:
    """Build fixed diagnostic metadata without ever retaining the request path."""

    params = {"method": method}
    if route_template:
        params["route"] = route_template
    return params
