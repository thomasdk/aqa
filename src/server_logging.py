"""Logging adjustments for the local application server."""

from __future__ import annotations

import logging

_ACTIVITY_ENDPOINT = "/api/application/activity"


class ActivityAccessLogFilter(logging.Filter):
    """Keep the Activity polling transport out of the terminal request log."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - never let logging break a request
            return True
        return _ACTIVITY_ENDPOINT not in message


def configure_access_log_filter() -> None:
    """Install the Activity access-log filter once for the current process."""

    logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(active, ActivityAccessLogFilter) for active in logger.filters):
        logger.addFilter(ActivityAccessLogFilter())


__all__ = ["ActivityAccessLogFilter", "configure_access_log_filter"]
