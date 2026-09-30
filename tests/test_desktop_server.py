"""Focused contracts for the Tauri-owned FastAPI entry point."""

from __future__ import annotations

import errno
import importlib
import sys
from pathlib import Path

import pytest


def _module():
    sys.modules.pop("src.desktop_server", None)
    return importlib.import_module("src.desktop_server")


def test_readiness_record_is_compact_machine_readable_json() -> None:
    mod = _module()
    assert mod.desktop_listen_record("127.0.0.1", 43123) == (
        'AQA_DESKTOP_LISTEN {"host":"127.0.0.1","port":43123}'
    )


def test_listener_refuses_non_loopback_bindings() -> None:
    mod = _module()
    with pytest.raises(ValueError, match="127.0.0.1"):
        mod.create_loopback_listener("0.0.0.0", 0)


def test_listener_uses_an_os_assigned_loopback_port() -> None:
    mod = _module()
    try:
        listener = mod.create_loopback_listener("127.0.0.1", 0)
    except PermissionError as error:
        if error.errno == errno.EPERM:
            pytest.skip("network namespaces can forbid loopback binding")
        raise
    try:
        assert listener.getsockname()[0] == "127.0.0.1"
        assert listener.getsockname()[1] > 0
    finally:
        listener.close()


def test_main_registers_quit_contract_and_never_opens_a_browser(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    mod = _module()
    observed: dict[str, object] = {}

    class FakeSocket:
        def getsockname(self):
            return ("127.0.0.1", 43123)

        def close(self):
            observed["closed"] = True

    class FakeServer:
        def __init__(self, config):
            self.config = config
            self.should_exit = False

        def run(self, *, sockets):
            observed["sockets"] = sockets
            observed["token"] = mod.app.state.quit_token
            mod.app.state.shutdown_callback()
            observed["should_exit"] = self.should_exit

    monkeypatch.setattr(mod.uvicorn, "Server", FakeServer)
    monkeypatch.setenv("API_HOST", "127.0.0.1")
    monkeypatch.setenv("API_PORT", "0")
    mod.main(listener_factory=lambda host, port: FakeSocket())

    assert 'AQA_DESKTOP_LISTEN {"host":"127.0.0.1","port":43123}' in capsys.readouterr().out
    assert observed["should_exit"] is True
    assert observed["closed"] is True
    assert isinstance(observed["token"], str)
    assert not hasattr(mod.app.state, "shutdown_callback")


def test_native_shell_uses_packaged_process_controls() -> None:
    source = (Path(__file__).parents[1] / "desktop/src-tauri/src/main.rs").read_text()

    assert '.env("AQA_PACKAGED_MODE", "1")' in source
    assert '.env("AQA_USER_DATA_DIR", data_dir)' in source
    assert 'join("Library/Application Support/AQA")' in source
    assert 'join("AQA")' in source
    assert 'join("aqa")' in source
    assert "AQA Workbench" not in source
