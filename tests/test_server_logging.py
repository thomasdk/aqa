"""Contracts for the focused local-server terminal output."""

from __future__ import annotations

import logging

from src.server_logging import ActivityAccessLogFilter


def _record(message: str) -> logging.LogRecord:
    return logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
    )


def test_activity_polling_is_hidden_but_other_access_logs_remain_visible() -> None:
    access_filter = ActivityAccessLogFilter()

    assert not access_filter.filter(
        _record('127.0.0.1 - "GET /api/application/activity?after=2&limit=200 HTTP/1.1" 200 OK')
    )
    assert access_filter.filter(_record('127.0.0.1 - "GET /api/hosts HTTP/1.1" 200 OK'))
    assert access_filter.filter(
        _record('127.0.0.1 - "POST /api/discussions/start HTTP/1.1" 200 OK')
    )
