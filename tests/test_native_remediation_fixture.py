"""Safety and behavior tests for the test-only native remediation fixtures."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from tests import native_remediation_fixture as fixture


@pytest.fixture
def disposable_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    base = tmp_path / "dist/native-remediation-fixtures"
    run = base / "new-run"
    conversations = run / "profile/conversations"
    conversations.mkdir(parents=True)
    monkeypatch.setattr(fixture, "REMEDIATION_BASE", base)
    return run, conversations


def test_target_validation_rejects_escape_symlink_and_unsafe_id(
    disposable_run: tuple[Path, Path], tmp_path: Path
) -> None:
    run, conversations = disposable_run
    session_id = "2026-09-04_12-00_abcd1234"
    target = conversations / f"{session_id}.json"
    target.write_text("never inspected by the fixture", encoding="utf-8")
    assert fixture.session_target(run, conversations, session_id) == target

    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(ValueError, match="not below"):
        fixture.validate_remediation_root(outside)
    with pytest.raises(ValueError, match="exact safe filename stem"):
        fixture.session_target(run, conversations, "../escape")

    target.unlink()
    outside_target = outside / target.name
    outside_target.write_text("outside", encoding="utf-8")
    target.symlink_to(outside_target)
    with pytest.raises(ValueError, match="exact regular"):
        fixture.session_target(run, conversations, session_id)

    target.unlink()
    os.link(outside_target, target)
    with pytest.raises(ValueError, match="hard-linked"):
        fixture.session_target(run, conversations, session_id)


@pytest.mark.skipif(not hasattr(os, "chflags"), reason="macOS flags are unavailable")
def test_guard_records_and_idempotently_restores_exact_mode_and_flags(
    disposable_run: tuple[Path, Path],
) -> None:
    run, conversations = disposable_run
    session_id = "2026-09-04_12-00_abcd1234"
    target = conversations / f"{session_id}.json"
    target.write_text("fixture content must remain untouched", encoding="utf-8")
    os.chmod(target, 0o640)
    original = target.stat(follow_symlinks=False)

    with fixture.guarded_session_file(run, conversations, session_id):
        prepared = target.stat(follow_symlinks=False)
        assert stat.S_IMODE(prepared.st_mode) == 0o440
        assert prepared.st_flags & stat.UF_IMMUTABLE
        first_state = fixture.prepare_session_file(run, conversations, session_id)
        assert first_state["mode"] == 0o640

    restored = target.stat(follow_symlinks=False)
    assert stat.S_IMODE(restored.st_mode) == 0o640
    assert restored.st_flags == original.st_flags
    assert fixture.restore_session_file(run, conversations, session_id) is False
    assert target.read_text(encoding="utf-8") == "fixture content must remain untouched"


def _wrapped_app(run: Path, user_data: Path) -> fixture.FailedSessionRefreshOnce:
    application = FastAPI()
    sessions = ["one"]

    @application.get("/api/sessions")
    def list_sessions() -> list[str]:
        return sessions

    @application.delete("/api/sessions/{session_id}")
    def delete_session(session_id: str) -> JSONResponse:
        if session_id not in sessions:
            return JSONResponse({"detail": "missing"}, status_code=404)
        sessions.remove(session_id)
        return JSONResponse({"deleted": True, "was_open": False})

    @application.post("/api/sessions/bulk-delete")
    def bulk_delete_sessions() -> JSONResponse:
        deleted_count = len(sessions)
        sessions.clear()
        return JSONResponse({"deleted_count": deleted_count, "was_open": False})

    return fixture.create_failed_refresh_app(application, run, user_data)


def _with_client(application: Any, client: tuple[str, int]) -> Any:
    """Set the client address without relying on version-specific TestClient options."""

    async def wrapped(scope: dict[str, Any], receive: Any, send: Any) -> None:
        await application({**scope, "client": client}, receive, send)

    return wrapped


def test_wrapper_fails_exactly_one_list_after_real_successful_deletion(
    disposable_run: tuple[Path, Path],
) -> None:
    run, _ = disposable_run
    user_data = run / "profile"
    client = TestClient(
        _with_client(_wrapped_app(run, user_data), ("127.0.0.1", 50000)),
        raise_server_exceptions=False,
    )
    assert client.delete("/api/sessions/one").status_code == 200
    assert client.get("/api/sessions").status_code == 503
    assert client.get("/api/sessions").json() == []
    assert client.delete("/api/sessions/missing").status_code == 404
    assert client.get("/api/sessions").status_code == 200


def test_wrapper_rejects_non_loopback_and_outside_user_data(
    disposable_run: tuple[Path, Path], tmp_path: Path
) -> None:
    run, _ = disposable_run
    with pytest.raises(ValueError, match="not below"):
        fixture.create_failed_refresh_app(FastAPI(), run, tmp_path)

    user_data = run / "profile"
    client = TestClient(
        _with_client(_wrapped_app(run, user_data), ("192.0.2.1", 50000)),
        raise_server_exceptions=False,
    )
    assert client.get("/api/sessions").status_code == 403


def test_wrapper_arms_only_for_nonempty_successful_bulk_deletion(
    disposable_run: tuple[Path, Path],
) -> None:
    run, _ = disposable_run
    client = TestClient(
        _with_client(_wrapped_app(run, run / "profile"), ("::1", 50000)),
        raise_server_exceptions=False,
    )
    assert client.post("/api/sessions/bulk-delete").json()["deleted_count"] == 1
    assert client.get("/api/sessions").status_code == 503
    assert client.get("/api/sessions").status_code == 200
    assert client.post("/api/sessions/bulk-delete").json()["deleted_count"] == 0
    assert client.get("/api/sessions").status_code == 200
