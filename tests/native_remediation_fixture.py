"""Test-only destructive-remediation fixtures with disposable-root confinement."""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import stat
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REMEDIATION_BASE = PROJECT_ROOT / "dist" / "native-remediation-fixtures"
FAULT_CONTROL_ID = "AQA_TEST_FAILED_SESSION_LIST_REFRESH_ONCE"
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_STATE_DIRECTORY = ".native-remediation-fixture"


def _reject_symlink_chain(path: Path, stop: Path) -> None:
    candidate = path
    while True:
        if candidate.is_symlink():
            raise ValueError(f"symlink paths are forbidden: {candidate}")
        if candidate == stop:
            return
        if candidate.parent == candidate:
            raise ValueError(f"path is not below the remediation base: {path}")
        candidate = candidate.parent


def validate_remediation_root(root: Path) -> Path:
    """Return one existing direct child of the fixed disposable remediation base."""
    base = REMEDIATION_BASE.resolve()
    supplied = root.expanduser().absolute()
    _reject_symlink_chain(supplied, base)
    resolved = supplied.resolve(strict=True)
    if resolved.parent != base or not resolved.is_dir() or not _SAFE_NAME.fullmatch(resolved.name):
        raise ValueError(f"root must be one named run directly below {base}")
    return resolved


def _validate_descendant(path: Path, root: Path, *, require_directory: bool) -> Path:
    supplied = path.expanduser().absolute()
    _reject_symlink_chain(supplied, root)
    resolved = supplied.resolve(strict=True)
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"path must remain below disposable run root: {path}") from exc
    if not relative.parts:
        raise ValueError("the run root itself is not a valid target")
    if require_directory and not resolved.is_dir():
        raise ValueError(f"expected an existing directory: {path}")
    return resolved


def session_target(root: Path, conversations_dir: Path, session_id: str) -> Path:
    safe_root = validate_remediation_root(root)
    if not _SAFE_NAME.fullmatch(session_id) or session_id.startswith("."):
        raise ValueError("session ID must be an exact safe filename stem")
    directory = _validate_descendant(conversations_dir, safe_root, require_directory=True)
    target = directory / f"{session_id}.json"
    if target.is_symlink() or not target.is_file():
        raise ValueError("the exact regular session JSON file must already exist")
    if target.stat(follow_symlinks=False).st_nlink != 1:
        raise ValueError("hard-linked session targets are forbidden")
    if target.resolve(strict=True).parent != directory:
        raise ValueError("session target escapes the exact conversations directory")
    return target


def _state_path(root: Path, session_id: str, *, create_directory: bool = True) -> Path:
    state_dir = root / _STATE_DIRECTORY
    if state_dir.is_symlink():
        raise ValueError("fixture state directory must not be a symlink")
    if create_directory:
        state_dir.mkdir(mode=0o700, exist_ok=True)
    return state_dir / f"{session_id}.state.json"


def _load_state(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise ValueError("fixture state must be an exact regular file")
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError("invalid fixture state")
    return value


def prepare_session_file(root: Path, conversations_dir: Path, session_id: str) -> dict[str, Any]:
    """Make one disposable session immutable and non-writable without reading it."""
    if sys.platform != "darwin" or not hasattr(os, "chflags"):
        raise RuntimeError("the immutable session fixture is supported only on macOS")
    safe_root = validate_remediation_root(root)
    target = session_target(safe_root, conversations_dir, session_id)
    state_path = _state_path(safe_root, session_id)
    existing = _load_state(state_path)
    if existing is not None:
        if existing.get("target") != str(target.relative_to(safe_root)):
            raise ValueError("existing fixture state belongs to a different exact target")
        return existing

    metadata = target.stat(follow_symlinks=False)
    state_record: dict[str, Any] = {
        "target": str(target.relative_to(safe_root)),
        "mode": stat.S_IMODE(metadata.st_mode),
        "flags": int(metadata.st_flags),
    }
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(state_path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(state_record, handle, sort_keys=True)
            handle.write("\n")
        os.chmod(target, state_record["mode"] & ~0o222, follow_symlinks=False)
        os.chflags(target, state_record["flags"] | stat.UF_IMMUTABLE, follow_symlinks=False)
    except BaseException:
        os.chflags(target, state_record["flags"], follow_symlinks=False)
        os.chmod(target, state_record["mode"], follow_symlinks=False)
        state_path.unlink(missing_ok=True)
        raise
    return state_record


def restore_session_file(root: Path, conversations_dir: Path, session_id: str) -> bool:
    """Idempotently restore the exact flags and mode recorded by prepare_session_file."""
    safe_root = validate_remediation_root(root)
    target = session_target(safe_root, conversations_dir, session_id)
    state_path = _state_path(safe_root, session_id)
    record = _load_state(state_path)
    if record is None:
        return False
    if record.get("target") != str(target.relative_to(safe_root)):
        raise ValueError("fixture state does not match the exact target")
    os.chflags(target, int(record["flags"]), follow_symlinks=False)
    os.chmod(target, int(record["mode"]), follow_symlinks=False)
    state_path.unlink()
    return True


@contextmanager
def guarded_session_file(
    root: Path, conversations_dir: Path, session_id: str
) -> Iterator[dict[str, Any]]:
    """Prepare one target and restore it in ``finally`` around a supervised operation."""
    record = prepare_session_file(root, conversations_dir, session_id)
    try:
        yield record
    finally:
        restore_session_file(root, conversations_dir, session_id)


class FailedSessionRefreshOnce:
    """ASGI wrapper that fails one post-deletion session-list refresh."""

    def __init__(self, application: Any, remediation_root: Path, user_data_dir: Path) -> None:
        self.application = application
        self.remediation_root = validate_remediation_root(remediation_root)
        self.user_data_dir = _validate_descendant(
            user_data_dir, self.remediation_root, require_directory=True
        )
        self._armed = False
        self._lock = threading.Lock()

    @staticmethod
    def _is_loopback(scope: dict[str, Any]) -> bool:
        client = scope.get("client")
        return bool(client) and client[0] in {"127.0.0.1", "::1"}

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Any,
        send: Any,
    ) -> None:
        if scope.get("type") != "http":
            await self.application(scope, receive, send)
            return
        if not self._is_loopback(scope):
            await self._response(send, 403, b'{"detail":"test fixture is loopback-only"}')
            return

        method = str(scope.get("method", ""))
        path = str(scope.get("path", ""))
        if method == "GET" and path == "/api/sessions":
            with self._lock:
                fail_now = self._armed
                self._armed = False
            if fail_now:
                await self._response(
                    send,
                    503,
                    b'{"detail":"deterministic test-only session list refresh failure"}',
                )
                return

        is_deletion = (method == "DELETE" and path.startswith("/api/sessions/")) or (
            method == "POST" and path == "/api/sessions/bulk-delete"
        )
        if not is_deletion:
            await self.application(scope, receive, send)
            return

        messages: list[dict[str, Any]] = []

        async def capture(message: dict[str, Any]) -> None:
            messages.append(message)

        await self.application(scope, receive, capture)
        successful = self._successful_deletion(messages)
        if successful:
            with self._lock:
                self._armed = True
        for message in messages:
            await send(message)

    @staticmethod
    def _successful_deletion(messages: list[dict[str, Any]]) -> bool:
        status = next(
            (
                int(message["status"])
                for message in messages
                if message.get("type") == "http.response.start"
            ),
            500,
        )
        if not 200 <= status < 300:
            return False
        body = b"".join(
            message.get("body", b"")
            for message in messages
            if message.get("type") == "http.response.body"
        )
        try:
            payload = json.loads(body)
        except (TypeError, ValueError):
            return False
        if not isinstance(payload, dict):
            return False
        deleted_count = payload.get("deleted_count")
        return payload.get("deleted") is True or (
            isinstance(deleted_count, int)
            and not isinstance(deleted_count, bool)
            and deleted_count > 0
        )

    @staticmethod
    async def _response(send: Any, status: int, body: bytes) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": body})


def create_failed_refresh_app(
    application: Any, remediation_root: Path, user_data_dir: Path
) -> FailedSessionRefreshOnce:
    return FailedSessionRefreshOnce(application, remediation_root, user_data_dir)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("status", "restore"):
        child = subparsers.add_parser(command)
        _add_target_arguments(child)
    guard = subparsers.add_parser(
        "guard", help="apply flags for a bounded interval and always restore them"
    )
    _add_target_arguments(guard)
    guard.add_argument("--hold-seconds", type=float, required=True)
    serve = subparsers.add_parser(
        "serve-failed-refresh", help="serve the real app behind the one-shot test wrapper"
    )
    serve.add_argument("--root", type=Path, required=True)
    serve.add_argument("--user-data-dir", type=Path, required=True)
    serve.add_argument("--port", type=int, default=4174)
    return parser


def _add_target_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--conversations-dir", type=Path, required=True)
    parser.add_argument("--session-id", required=True)


def _serve(arguments: argparse.Namespace) -> int:
    root = validate_remediation_root(arguments.root)
    user_data = _validate_descendant(arguments.user_data_dir, root, require_directory=True)
    if not 1024 <= arguments.port <= 65535:
        raise ValueError("--port must be between 1024 and 65535")
    for variable in (
        "AQA_SETTINGS_PATH",
        "AQA_CONVERSATIONS_DIR",
        "PROMPT_LIBRARY_PATH",
        "PROMPT_DEFAULTS_PATH",
        "AQA_PROMPT_DEFAULTS_DIR",
        "AQA_LOCAL_AI_DIR",
    ):
        os.environ.pop(variable, None)
    os.environ["AQA_PACKAGED_MODE"] = "1"
    os.environ["AQA_USER_DATA_DIR"] = str(user_data)
    os.environ["AQA_SYNC_PROMPTS_FROM_SOURCE"] = "1"
    import uvicorn

    from src.service.api_app import create_app

    application = create_failed_refresh_app(create_app(), root, user_data)
    uvicorn.run(application, host="127.0.0.1", port=arguments.port, log_level="warning")
    return 0


def main() -> int:
    arguments = _parser().parse_args()
    if arguments.command == "serve-failed-refresh":
        return _serve(arguments)
    root = validate_remediation_root(arguments.root)
    target = session_target(root, arguments.conversations_dir, arguments.session_id)
    state = _load_state(_state_path(root, arguments.session_id, create_directory=False))
    if arguments.command == "status":
        print(f"target={target} prepared={state is not None}")
        return 0
    if arguments.command == "restore":
        restored = restore_session_file(root, arguments.conversations_dir, arguments.session_id)
        print(f"target={target} restored={restored}")
        return 0
    if arguments.hold_seconds <= 0:
        raise ValueError("--hold-seconds must be positive")
    previous_handlers = {
        signum: signal.getsignal(signum) for signum in (signal.SIGINT, signal.SIGTERM)
    }

    def interrupt(_signum: int, _frame: object) -> None:
        raise KeyboardInterrupt

    for signum in previous_handlers:
        signal.signal(signum, interrupt)
    try:
        with guarded_session_file(root, arguments.conversations_dir, arguments.session_id):
            print(f"target={target} prepared=True")
            time.sleep(arguments.hold_seconds)
    except KeyboardInterrupt:
        return 130
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)
    print(f"target={target} restored=True")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
