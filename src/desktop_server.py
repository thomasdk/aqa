"""Desktop-only FastAPI entry point used by the Tauri shell.

It never launches a browser. It binds an ephemeral loopback port, prints one
machine-readable readiness record for the native parent process, and exposes
the authenticated graceful-shutdown contract used by that parent.
"""

from __future__ import annotations

import json
import os
import secrets
import socket
import sys
from collections.abc import Callable

import uvicorn

from src.api_server import app

READINESS_PREFIX = "AQA_DESKTOP_LISTEN "
LOOPBACK_HOST = "127.0.0.1"


def desktop_listen_record(host: str, port: int) -> str:
    """Return the only stdout record consumed by the native parent process."""
    return READINESS_PREFIX + json.dumps({"host": host, "port": port}, separators=(",", ":"))


def create_loopback_listener(host: str, port: int) -> socket.socket:
    """Bind a TCP listener, refusing a network-visible desktop server."""
    if host != LOOPBACK_HOST:
        raise ValueError("Desktop mode must bind exactly to 127.0.0.1")
    if not 0 <= port <= 65535:
        raise ValueError("API_PORT must be between 0 and 65535")
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((host, port))
        listener.listen(socket.SOMAXCONN)
        listener.setblocking(False)
        return listener
    except BaseException:
        listener.close()
        raise


def main(
    *,
    listener_factory: Callable[[str, int], socket.socket] = create_loopback_listener,
) -> None:
    """Run Uvicorn on a reserved dynamic loopback socket without opening a browser."""
    host = os.environ.get("API_HOST", LOOPBACK_HOST)
    try:
        requested_port = int(os.environ.get("API_PORT", "0"))
    except ValueError as error:
        raise RuntimeError("API_PORT must be an integer") from error

    listener = listener_factory(host, requested_port)
    bound_port = int(listener.getsockname()[1])
    config = uvicorn.Config(app, host=host, port=bound_port, reload=False, log_level="info")
    server = uvicorn.Server(config)
    app.state.quit_token = secrets.token_urlsafe(32)
    app.state.shutdown_callback = lambda: setattr(server, "should_exit", True)
    try:
        print(desktop_listen_record(host, bound_port), flush=True)
        server.run(sockets=[listener])
    finally:
        listener.close()
        for name in ("shutdown_callback", "quit_token"):
            if hasattr(app.state, name):
                delattr(app.state, name)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # noqa: BLE001 - surface startup errors to native log
        print(f"AQA_DESKTOP_ERROR {error}", file=sys.stderr, flush=True)
        raise
