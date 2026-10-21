from __future__ import annotations

import hashlib
import json
import os
import signal
import socket
import sys
import threading
import time
import zipfile
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest
import requests

import src.local_ai.manager as manager_module
from src.local_ai.catalog import BINARY_SPECS, MODELS
from src.local_ai.manager import LocalAIManager, LocalAIStateError
from src.local_ai.platform import HardwareProfile, RuntimeDevice, RuntimeProbe, select_binary


def _gguf(payload: bytes = b"fixture") -> bytes:
    """Small structurally identifiable GGUF used by manager-only tests."""
    return b"GGUF\x03\x00\x00\x00" + payload


def test_import_publishes_only_a_complete_verified_model_pair(tmp_path: Path) -> None:
    instance = LocalAIManager(local_dir=tmp_path, port=0, cpu_threads=1)

    session = instance.begin_import("gemma-4-e2b")
    session.main_part.write_bytes(_gguf(b"main"))
    session.draft_part.write_bytes(_gguf(b"draft"))
    instance.finish_import(session.import_id)

    inventory = {entry["model_id"]: entry for entry in instance.inventory()}
    assert inventory["gemma-4-e2b"]["installed"] is True
    assert not session.directory.exists()
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert set(manifest["models"]) == {"gemma-4-e2b"}


def test_import_completion_notifies_the_selected_model(tmp_path: Path) -> None:
    instance = LocalAIManager(local_dir=tmp_path, port=0, cpu_threads=1)
    completed: list[str] = []
    instance.set_install_completion_callback(completed.append)

    session = instance.begin_import("gemma-4-12b")
    session.main_part.write_bytes(_gguf(b"main"))
    session.draft_part.write_bytes(_gguf(b"draft"))
    instance.finish_import(session.import_id)

    assert completed == ["gemma-4-12b"]


def test_import_rejects_a_partial_pair_without_publishing_model(tmp_path: Path) -> None:
    instance = LocalAIManager(local_dir=tmp_path, port=0, cpu_threads=1)
    session = instance.begin_import("gemma-4-e2b")
    session.main_part.write_bytes(_gguf(b"main"))

    with pytest.raises(LocalAIStateError):
        instance.finish_import(session.import_id)

    assert not (tmp_path / "models" / "gemma-4-e2b").exists()
    assert instance.inventory()[0]["installed"] is False


def test_background_import_cleans_stale_artifacts_and_publishes_from_packaged_root(
    tmp_path: Path,
) -> None:
    instance = LocalAIManager(local_dir=tmp_path / "current", port=0, cpu_threads=1)
    source = tmp_path / "older" / ".aqa" / "local-ai" / "models" / "gemma-4-e2b"
    source.mkdir(parents=True)
    model = manager_module.MODELS["gemma-4-e2b"]
    (source / model.model_filename).write_bytes(_gguf(b"main"))
    (source / model.draft_filename).write_bytes(_gguf(b"draft"))
    stale = instance.local_dir / ".imports" / "stale"
    stale.mkdir(parents=True)
    (stale / "orphan.part").write_bytes(b"orphan")

    job_id = instance.start_background_import("gemma-4-e2b", tmp_path / "older")
    assert job_id
    deadline = time.monotonic() + 2.0
    while instance.status().state == "importing" and time.monotonic() < deadline:
        time.sleep(0.01)

    assert instance.status().state == "installed"
    assert not stale.exists()
    assert instance.inventory()[0]["installed"] is True


def test_detected_background_import_recognizes_the_catalog_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    instance = LocalAIManager(local_dir=tmp_path / "current", port=0, cpu_threads=1)
    source = tmp_path / "portable" / "models" / "gemma-4-e4b"
    source.mkdir(parents=True)
    model = MODELS["gemma-4-e4b"]
    (source / model.model_filename).write_bytes(_gguf(b"main"))
    (source / model.draft_filename).write_bytes(_gguf(b"draft"))
    start_import = Mock(return_value="job-123")
    monkeypatch.setattr(instance, "start_background_import", start_import)

    job_id, model_id = instance.start_detected_background_import(tmp_path / "portable")

    assert (job_id, model_id) == ("job-123", "gemma-4-e4b")
    start_import.assert_called_once_with("gemma-4-e4b", (tmp_path / "portable").resolve())


def test_detected_background_import_rejects_an_ambiguous_bundle(tmp_path: Path) -> None:
    instance = LocalAIManager(local_dir=tmp_path / "current", port=0, cpu_threads=1)
    source = tmp_path / "portable"
    for model_id in ("gemma-4-e2b", "gemma-4-e4b"):
        model_directory = source / "models" / model_id
        model_directory.mkdir(parents=True)
        model = MODELS[model_id]
        (model_directory / model.model_filename).write_bytes(_gguf(b"main"))
        (model_directory / model.draft_filename).write_bytes(_gguf(b"draft"))

    with pytest.raises(LocalAIStateError, match="multiple complete models"):
        instance.start_detected_background_import(source)


def test_detected_background_import_rejects_an_unrecognized_bundle(tmp_path: Path) -> None:
    instance = LocalAIManager(local_dir=tmp_path / "current", port=0, cpu_threads=1)
    source = tmp_path / "portable"
    source.mkdir()

    with pytest.raises(LocalAIStateError, match="no compatible complete model pair"):
        instance.start_detected_background_import(source)


def test_background_import_is_global_and_blocks_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    instance = LocalAIManager(local_dir=tmp_path / "current", port=0, cpu_threads=1)
    source = tmp_path / "older" / "models" / "gemma-4-e2b"
    source.mkdir(parents=True)
    model = manager_module.MODELS["gemma-4-e2b"]
    (source / model.model_filename).write_bytes(_gguf(b"main"))
    (source / model.draft_filename).write_bytes(_gguf(b"draft"))
    entered = threading.Event()
    release = threading.Event()
    original_copy = instance._copy_import_artifact

    def paused_copy(*args, **kwargs):
        entered.set()
        assert release.wait(2)
        return original_copy(*args, **kwargs)

    monkeypatch.setattr(instance, "_copy_import_artifact", paused_copy)
    instance.start_background_import("gemma-4-e2b", tmp_path / "older")
    assert entered.wait(2)
    with pytest.raises(LocalAIStateError, match="import"):
        instance.begin_import("gemma-4-e4b")
    with pytest.raises(LocalAIStateError, match="import"):
        instance.install("gemma-4-e4b", start_after_install=False)
    release.set()


class FakeProcess:
    _next_pid = 40_000

    def __init__(self, *_args, **_kwargs):
        type(self)._next_pid += 1
        self.pid = type(self)._next_pid
        self.returncode = None
        self.stdout = iter(())
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = 0

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


@pytest.fixture
def fake_process(monkeypatch: pytest.MonkeyPatch):
    processes: list[FakeProcess] = []

    def popen(*args, **kwargs):
        process = FakeProcess(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(manager_module.subprocess, "Popen", popen)
    monkeypatch.setattr(
        LocalAIManager, "_posix_process_start_token", staticmethod(lambda _pid: "fake-birth")
    )
    return processes


@pytest.fixture
def manager(tmp_path: Path, fake_process, monkeypatch: pytest.MonkeyPatch) -> LocalAIManager:
    binary = tmp_path / "llama-server"
    model = tmp_path / "gemma.gguf"
    draft = tmp_path / "draft.gguf"
    binary.write_bytes(b"test-artifact")
    model.write_bytes(_gguf())
    draft.write_bytes(_gguf())
    instance = LocalAIManager(
        local_dir=tmp_path,
        binary_path=binary,
        model_paths={model_id: model for model_id in manager_module.MODELS},
        draft_paths={model_id: draft for model_id in manager_module.MODELS},
        port=0,
        cpu_threads=7,
        accelerator_available=True,
    )
    monkeypatch.setattr(instance, "_validate_artifacts", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(instance, "_read_server_model_id", lambda _port: "server-reported-gemma")
    monkeypatch.setattr(instance, "_posix_process_start_token", lambda _pid: "fake-birth")
    return instance


def _healthy_requests(monkeypatch: pytest.MonkeyPatch) -> Mock:
    # The restricted test sandbox does not permit binding even to loopback.
    monkeypatch.setattr(LocalAIManager, "_reserve_loopback_port", lambda _self: 43123)
    requests_get = Mock()

    def get(url, **_kwargs):
        if url.endswith("/health"):
            return SimpleNamespace(status_code=200)
        return SimpleNamespace(
            status_code=200, json=lambda: {"data": [{"id": "server-reported-gemma"}]}
        )

    requests_get.side_effect = get
    monkeypatch.setattr(manager_module.requests, "get", requests_get)
    return requests_get


def test_start_with_mtp_uses_loopback_and_model_specific_flash_attention(
    manager: LocalAIManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    _healthy_requests(monkeypatch)

    status = manager.start("gemma-4-e2b", mtp_enabled=True)
    command = manager._process_command

    assert status.state == "running"
    assert ["--host", "127.0.0.1"] == command[command.index("--host") : command.index("--host") + 2]
    assert command[command.index("--model-draft") + 1].endswith("draft.gguf")
    assert command[command.index("--spec-type") + 1] == "draft-mtp"
    assert command[command.index("--spec-draft-n-max") + 1] == "4"
    assert command[command.index("--flash-attn") + 1] == "on"
    assert command[command.index("--alias") + 1] == "gemma-4-E2B-it"
    assert command[command.index("--ctx-size") + 1] == "32768"
    assert "--reasoning" not in command
    assert "--reasoning-format" not in command
    assert command[command.index("--sleep-idle-seconds") + 1] == "300"
    assert command[command.index("--n-gpu-layers") + 1] == "auto"
    assert command[command.index("--fit") + 1] == "on"
    assert command[command.index("--verbosity") + 1] == "4"
    assert "--threads" not in command
    assert status.model_name == "server-reported-gemma"

    reference = manager.configured_command_reference(
        "gemma-4-e2b", context_tokens=65_536, mtp_enabled=False
    )
    assert reference is not None
    assert reference.startswith("llama-server --model <managed-main-model>")
    assert "--model-draft <managed-mtp-draft>" in reference
    assert "--ctx-size 32768" in reference
    assert "--port 43123" in reference
    assert "/" not in reference
    assert "\\" not in reference


def test_configured_command_reference_tracks_next_start_settings_and_survives_reload(
    manager: LocalAIManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    reference = manager.configured_command_reference(
        "gemma-4-e2b", context_tokens=65_536, mtp_enabled=True
    )

    assert reference is not None
    assert reference.startswith("llama-server --model <managed-main-model>")
    assert "--model-draft <managed-mtp-draft>" in reference
    assert "--spec-draft-n-max 4" in reference
    assert "--ctx-size 65536" in reference
    assert "--n-gpu-layers auto" in reference
    assert "--fit on" in reference
    assert "--port <available-loopback-port>" in reference
    assert str(manager.local_dir) not in reference

    other_model_reference = manager.configured_command_reference(
        "gemma-4-e4b", context_tokens=65_536, mtp_enabled=False
    )
    assert other_model_reference is not None
    assert "--alias gemma-4-E4B-it" in other_model_reference
    assert "--model-draft" not in other_model_reference

    _healthy_requests(monkeypatch)
    manager.start("gemma-4-e2b", context_tokens=65_536, mtp_enabled=True)
    active_details = manager.runtime_details()
    manager.mark_request_active()
    manager.mark_request_idle()
    assert manager.runtime_details() == active_details
    manager.stop()
    restored = LocalAIManager(local_dir=manager.local_dir)
    persisted = restored.runtime_details()["command_reference"]
    assert persisted == reference.replace("--port <available-loopback-port>", "--port 43123")


def test_configured_command_reference_never_probes_runtime_devices(
    manager: LocalAIManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager._binary_spec = BINARY_SPECS["macos-arm64-metal"]
    manager._runtime_probe = RuntimeProbe("gpu_candidate", (RuntimeDevice("Metal", "Apple GPU"),))
    probe = Mock(side_effect=AssertionError("diagnostics must not launch the runtime"))
    monkeypatch.setattr(manager, "_probe_runtime_devices", probe)

    reference = manager.configured_command_reference(
        "gemma-4-e2b", context_tokens=32_768, mtp_enabled=False
    )

    assert reference is not None
    assert "--device Metal" in reference
    probe.assert_not_called()


@pytest.mark.parametrize(
    "value",
    [
        "llama-server --model /private/model.gguf",
        r"llama-server.exe --model C:\\private\\model.gguf",
        "llama-server --model https://example.invalid/model.gguf",
        "llama-server --model model.gguf; open secret",
        "other-server --model <managed-main-model>",
        "llama-server\n--model <managed-main-model>",
        "llama-server " + "x" * 2000,
    ],
)
def test_command_reference_rejects_path_bearing_or_unsafe_values(value: str) -> None:
    assert LocalAIManager.safe_command_reference(value) is None


def test_command_reference_accepts_the_windows_engine_name() -> None:
    reference = LocalAIManager._command_reference(
        [
            r"C:\\managed\\llama-server.exe",
            "--model",
            r"C:\\managed\\model.gguf",
            "--ctx-size",
            "32768",
        ]
    )

    assert reference == "llama-server.exe --model <managed-main-model> --ctx-size 32768"


def test_command_reference_fails_closed_for_an_unrecognized_path_argument() -> None:
    assert (
        LocalAIManager._command_reference(
            [
                "/managed/llama-server",
                "--model",
                "/managed/model.gguf",
                "--future-path",
                "/private/value",
            ]
        )
        is None
    )


def test_start_without_mtp_omits_draft_flags(
    manager: LocalAIManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    _healthy_requests(monkeypatch)

    manager.start("gemma-4-e2b", mtp_enabled=False)
    command = manager._process_command

    assert "--model-draft" not in command
    assert "--spec-type" not in command
    assert "--spec-draft-n-max" not in command
    assert command[command.index("--n-gpu-layers") + 1] == "auto"
    assert command[command.index("--fit") + 1] == "on"
    assert command[command.index("--verbosity") + 1] == "4"


def test_12b_start_uses_flash_attention_with_or_without_mtp(
    manager: LocalAIManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    _healthy_requests(monkeypatch)

    manager.start("gemma-4-12b", mtp_enabled=False)
    without_mtp = manager._process_command
    assert without_mtp[without_mtp.index("--flash-attn") + 1] == "on"
    assert "--model-draft" not in without_mtp
    manager.stop()

    manager.start("gemma-4-12b", mtp_enabled=True)
    with_mtp = manager._process_command
    assert with_mtp[with_mtp.index("--flash-attn") + 1] == "on"
    assert with_mtp[with_mtp.index("--model-draft") + 1].endswith("draft.gguf")


@pytest.mark.parametrize("model_id", ["gemma-4-e2b", "gemma-4-e4b", "gemma-4-12b"])
def test_context_size_defaults_to_workstation_safe_value(
    model_id: str, manager: LocalAIManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    _healthy_requests(monkeypatch)

    status = manager.start(model_id)

    command = manager._process_command
    assert command[command.index("--ctx-size") + 1] == "32768"
    assert status.context_tokens == 32_768


def test_start_accepts_explicit_supported_context_size(
    manager: LocalAIManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    _healthy_requests(monkeypatch)

    status = manager.start("gemma-4-e2b", context_tokens=32_768)

    command = manager._process_command
    assert command[command.index("--ctx-size") + 1] == "32768"
    assert status.context_tokens == 32_768


@pytest.mark.parametrize("context_tokens", [8_191, 131_073])
def test_start_rejects_unsupported_context_size(
    manager: LocalAIManager, context_tokens: int
) -> None:
    with pytest.raises(ValueError, match="context_tokens"):
        manager.start("gemma-4-e2b", context_tokens=context_tokens)


@pytest.mark.parametrize("context_tokens", [8_192, 8_193, 131_072])
def test_start_accepts_any_integer_within_model_bounds(
    manager: LocalAIManager, monkeypatch: pytest.MonkeyPatch, context_tokens: int
) -> None:
    _healthy_requests(monkeypatch)
    assert (
        manager.start("gemma-4-e2b", context_tokens=context_tokens).context_tokens == context_tokens
    )


def test_twelve_b_allows_its_documented_maximum(manager: LocalAIManager) -> None:
    model = manager._model("gemma-4-12b")
    assert manager._validated_start_options(model, 262_144, False, 4) == 262_144


def test_start_rejects_invalid_mtp_draft_tokens(manager: LocalAIManager) -> None:
    with pytest.raises(ValueError, match="1.*6"):
        manager.start("gemma-4-e2b", mtp_enabled=True, mtp_draft_tokens=7)


def test_start_requires_loopback_server_and_returns_server_reported_model(
    manager: LocalAIManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    requests_get = _healthy_requests(monkeypatch)

    status = manager.start("gemma-4-e2b")

    assert "--host" in manager._process_command
    assert status.host.startswith("http://127.0.0.1:")
    assert status.model_name == "server-reported-gemma"
    assert requests_get.call_count >= 2
    assert requests_get.call_args_list[0].args[0].endswith("/health")
    assert requests_get.call_args_list[1].args[0].endswith("/v1/models")


def test_start_when_loopback_port_is_unavailable_raises_bounded_error(
    manager: LocalAIManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    import errno

    real_socket = manager_module.socket.socket

    class _BusyPortSocket:
        def __init__(self, *args, **kwargs):
            self._sock = real_socket(*args, **kwargs)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            try:
                self._sock.close()
            except OSError:
                pass
            return False

        def setsockopt(self, *args, **kwargs):
            return self._sock.setsockopt(*args, **kwargs)

        def bind(self, addr):
            # Simulate the OS refusing to bind a port that is already in use.
            raise OSError(errno.EADDRINUSE, "Address already in use")

        def getsockname(self):
            return self._sock.getsockname()

    monkeypatch.setattr(manager_module.socket, "socket", _BusyPortSocket)

    with pytest.raises(LocalAIStateError) as excinfo:
        manager.start("gemma-4-e2b")

    message = str(excinfo.value)
    assert message == "loopback port is unavailable"
    assert "Errno" not in message
    assert "Address already in use" not in message
    # The startup must not have spawned a child process.
    assert manager._process is None
    assert manager._port is None


def test_startup_exit_retains_sanitized_exit_diagnostics_and_allows_retry(
    manager: LocalAIManager, fake_process, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(LocalAIManager, "_reserve_loopback_port", lambda _self: 43123)
    process = FakeProcess()
    process.returncode = 127
    process.stdout = __import__("io").StringIO(
        "error while loading shared libraries\n/private/model\n"
    )
    monkeypatch.setattr(manager, "_spawn", lambda _command: process)
    with pytest.raises(LocalAIStateError) as raised:
        manager.start("gemma-4-e2b")
    assert raised.value.code == "process_exited", str(raised.value)
    assert manager.status().error_code == "process_exited"
    details = manager.runtime_details()
    assert details["exit_code"] == 127
    assert details["log_tail"] == ["error while loading shared libraries"]
    assert "/" not in (manager.local_dir / "startup-diagnostics.json").read_text()
    monkeypatch.setattr(manager, "_spawn", LocalAIManager._spawn.__get__(manager, LocalAIManager))
    _healthy_requests(monkeypatch)
    status = manager.start("gemma-4-e2b")
    assert status.state == "running"


@pytest.mark.parametrize(
    "profile",
    ["macos-arm64-metal", "windows-x86_64-cpu", "linux-x86_64-cpu"],
)
def test_runtime_preflight_uses_the_same_bounded_contract_on_every_supported_os(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, profile: str
) -> None:
    binary = BINARY_SPECS[profile]
    server = tmp_path / binary.engine_name
    server.write_text("fixture", encoding="utf-8")
    server.chmod(0o755)
    manager = LocalAIManager(local_dir=tmp_path, port=0, cpu_threads=1)
    help_output = " ".join(manager_module._REQUIRED_RUNTIME_FLAGS).replace("--temp ", "--temp, ")
    device_output = "Metal: Apple GPU" if binary.accelerator != "cpu" else "Available devices:"
    run = Mock(
        side_effect=[
            SimpleNamespace(returncode=0, stdout=help_output),
            SimpleNamespace(returncode=0, stdout=device_output),
        ]
    )
    monkeypatch.setattr(manager_module.subprocess, "run", run)

    manager._preflight_runtime(binary, server)

    assert run.call_args_list[0].args[0] == [str(server), "--help"]
    assert run.call_args_list[1].args[0] == [str(server), "--list-devices"]
    assert run.call_args_list[0].kwargs["cwd"] == str(tmp_path)
    assert run.call_args_list[0].kwargs["timeout"] == manager_module.RUNTIME_PREFLIGHT_TIMEOUT
    # The packaged Metal runtime needed about 50 seconds on its first M2 launch.
    assert run.call_args_list[0].kwargs["timeout"] >= 60
    assert run.call_args_list[1].kwargs["timeout"] == manager_module.RUNTIME_DEVICE_PROBE_TIMEOUT
    # The packaged Metal device check also needs time for first-run initialization.
    assert run.call_args_list[1].kwargs["timeout"] >= 60
    assert run.call_args_list[0].kwargs["shell"] is False


def test_runtime_preflight_rejects_missing_flags_without_publishing_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = BINARY_SPECS["macos-arm64-metal"]
    server = tmp_path / binary.engine_name
    server.write_text("fixture", encoding="utf-8")
    server.chmod(0o755)
    manager = LocalAIManager(local_dir=tmp_path, port=0, cpu_threads=1)
    monkeypatch.setattr(
        manager_module.subprocess,
        "run",
        Mock(return_value=SimpleNamespace(returncode=0, stdout="--model --port")),
    )

    with pytest.raises(LocalAIStateError) as raised:
        manager._preflight_runtime(binary, server)

    assert raised.value.code == "runtime_incompatible"


@pytest.mark.parametrize(
    ("failure", "reason"),
    [(0xC0000135, "missing_runtime_library"), ("timeout", "probe_timeout")],
)
def test_windows_runtime_preflight_distinguishes_missing_dll_and_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: int | str, reason: str
) -> None:
    binary = BINARY_SPECS["windows-x86_64-sycl"]
    server = tmp_path / binary.engine_name
    server.write_bytes(b"fixture")
    server.chmod(0o755)
    manager = LocalAIManager(local_dir=tmp_path, port=0, cpu_threads=1)
    if failure == "timeout":
        run = Mock(side_effect=manager_module.subprocess.TimeoutExpired([str(server)], 120))
    else:
        run = Mock(return_value=SimpleNamespace(returncode=failure, stdout=""))
    monkeypatch.setattr(manager_module.subprocess, "run", run)

    with pytest.raises(LocalAIStateError) as raised:
        manager._preflight_runtime(binary, server)

    assert raised.value.code == "runtime_incompatible"
    assert raised.value.selection_reason == reason


@pytest.mark.parametrize(
    ("failure", "reason"),
    [(0xC0000135, "missing_runtime_library"), ("timeout", "probe_timeout")],
)
def test_windows_device_probe_distinguishes_missing_dll_and_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: int | str, reason: str
) -> None:
    server = tmp_path / "llama-server.exe"
    if failure == "timeout":
        run = Mock(side_effect=manager_module.subprocess.TimeoutExpired([str(server)], 120))
    else:
        run = Mock(return_value=SimpleNamespace(returncode=failure, stdout=""))
    monkeypatch.setattr(manager_module.subprocess, "run", run)

    probe = LocalAIManager._probe_runtime_devices(server)

    assert probe.state == "failed"
    assert probe.reason == reason


def test_model_load_exit_quarantines_the_catalog_model_pair(
    manager: LocalAIManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = MODELS["gemma-4-e2b"]
    directory = manager.local_dir / "models" / "gemma-4-e2b"
    directory.mkdir(parents=True)
    main = directory / spec.model_filename
    draft = directory / spec.draft_filename
    main.write_bytes(_gguf(b"magic-prefixed-but-unloadable"))
    draft.write_bytes(_gguf(b"draft"))
    process = FakeProcess()
    process.returncode = 1
    monkeypatch.setattr(LocalAIManager, "_reserve_loopback_port", lambda _self: 43123)
    monkeypatch.setattr(manager, "_spawn", lambda _command: process)
    monkeypatch.setattr(
        manager,
        "_start_log_reader",
        lambda _process: manager._log_lines.append("failed to load GGUF model"),
    )

    with pytest.raises(LocalAIStateError) as raised:
        manager.start("gemma-4-e2b")

    assert raised.value.code == "artifact_invalid"
    assert manager.status().error_code == "artifact_invalid"
    assert not main.exists()
    assert not draft.exists()


def test_default_context_is_preserved_after_oom(
    manager: LocalAIManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    failed = FakeProcess()
    failed.returncode = 1
    monkeypatch.setattr(LocalAIManager, "_reserve_loopback_port", lambda _self: 43123)
    spawned: list[list[str]] = []
    monkeypatch.setattr(manager, "_spawn", lambda command: spawned.append(command) or failed)
    monkeypatch.setattr(
        manager,
        "_start_log_reader",
        lambda process: (
            manager._log_lines.append("error: out of memory") if process is failed else None
        ),
    )
    _healthy_requests(monkeypatch)

    with pytest.raises(LocalAIStateError) as raised:
        manager.start("gemma-4-e2b")

    assert raised.value.code == "insufficient_resources"
    assert len(spawned) == 1
    assert spawned[0][spawned[0].index("--ctx-size") + 1] == "32768"


def test_accelerated_start_uses_exact_probed_device_and_requires_real_offload(
    manager: LocalAIManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    _healthy_requests(monkeypatch)
    manager._binary_spec = BINARY_SPECS["macos-arm64-metal"]
    manager._runtime_probe = RuntimeProbe("gpu_candidate", (RuntimeDevice("Metal", "Apple GPU"),))
    commands: list[list[str]] = []
    original_spawn = manager._spawn
    monkeypatch.setattr(
        manager, "_spawn", lambda command: commands.append(command) or original_spawn(command)
    )

    with pytest.raises(LocalAIStateError) as raised:
        manager.start("gemma-4-e2b", context_tokens=65_536)

    assert raised.value.code == "accelerator_failed"
    command = commands[0]
    assert command[command.index("--device") + 1] == "Metal"
    assert command[command.index("--ctx-size") + 1] == "65536"
    assert command[command.index("--n-gpu-layers") + 1] == "auto"
    assert command[command.index("--fit") + 1] == "on"


def test_runtime_candidate_integrity_failure_never_falls_back_to_cpu(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.local_ai.downloads import DownloadIntegrityError

    manager = LocalAIManager(local_dir=tmp_path, port=0, cpu_threads=1)
    candidates = (
        BINARY_SPECS["windows-x86_64-vulkan"],
        BINARY_SPECS["windows-x86_64-cpu"],
    )
    attempted: list[str] = []

    def fail_download(_job, _phase, spec, _is_runtime):
        attempted.append(spec.catalog_key)
        raise DownloadIntegrityError("SHA-256 digest mismatch")

    monkeypatch.setattr(manager, "_download_install_artifact", fail_download)
    with pytest.raises(DownloadIntegrityError):
        manager._install_best_runtime(
            SimpleNamespace(cancel_event=threading.Event()),
            candidates,
            preserve_installed=False,
        )

    assert attempted == ["binary:windows-x86_64-vulkan"]


def test_linux_cuda_companions_are_verified_beside_the_server(tmp_path: Path) -> None:
    binary = BINARY_SPECS["linux-x86_64-cuda"]
    companion = binary.companions[0]
    for member in companion.archive_members:
        (tmp_path / Path(member).name).write_bytes(b"runtime")
    license_source = manager_module.bundled_third_party_license_path(companion.license_filename)
    installed_license = tmp_path / companion.installed_license_filename
    installed_license.write_bytes(license_source.read_bytes())

    assert LocalAIManager._has_required_runtime_companions(binary, tmp_path) is True

    installed_license.write_bytes(b"altered")
    assert LocalAIManager._has_required_runtime_companions(binary, tmp_path) is False

    installed_license.write_bytes(license_source.read_bytes())
    installed_license.unlink()
    assert LocalAIManager._has_required_runtime_companions(binary, tmp_path) is False


def test_accelerator_repair_selects_the_matching_cpu_runtime(tmp_path: Path) -> None:
    manager = LocalAIManager(
        local_dir=tmp_path,
        binary_spec=BINARY_SPECS["macos-arm64-metal"],
        port=0,
        cpu_threads=1,
    )

    repaired = manager._runtime_update_binary(SimpleNamespace(cpu_fallback=True))

    assert repaired.profile == "macos-arm64-metal"
    assert repaired.accelerator == "cpu"


def test_runtime_repair_advances_through_backends_to_cpu_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gpu = BINARY_SPECS["linux-x86_64-vulkan"]
    cpu = BINARY_SPECS["linux-x86_64-cpu"]
    manager = LocalAIManager(local_dir=tmp_path, port=0, cpu_threads=1)
    job = SimpleNamespace(cancel_event=threading.Event(), cpu_fallback=False)
    monkeypatch.setattr(manager, "_runtime_update_candidates", lambda _job: (gpu, cpu))
    attempted: list[str] = []

    def install_candidate(_job, binary, _previous):
        attempted.append(binary.accelerator)
        if binary.accelerator != "cpu":
            raise LocalAIStateError("backend unavailable", code="accelerator_failed")
        manager._binary_spec = binary
        runtime = tmp_path / "cpu" / "llama-server"
        runtime.parent.mkdir(parents=True)
        runtime.write_bytes(b"runtime")
        manager._binary_path = runtime

    monkeypatch.setattr(manager, "_install_runtime_update_candidate", install_candidate)

    manager._run_update_runtime_job(job)

    assert attempted == ["vulkan", "cpu"]
    assert manager._binary_spec == cpu
    assert manager.runtime_capability_state() == "cpu_confirmed"
    assert manager.status().state == "not_installed"


def test_runtime_repair_does_not_fallback_after_download_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gpu = BINARY_SPECS["linux-x86_64-vulkan"]
    cpu = BINARY_SPECS["linux-x86_64-cpu"]
    manager = LocalAIManager(local_dir=tmp_path, port=0, cpu_threads=1)
    job = SimpleNamespace(cancel_event=threading.Event(), cpu_fallback=False)
    monkeypatch.setattr(manager, "_runtime_update_candidates", lambda _job: (gpu, cpu))
    attempted: list[str] = []

    def fail_download(_job, binary, _previous):
        attempted.append(binary.accelerator)
        raise LocalAIStateError("network unavailable", code="download_failed")

    monkeypatch.setattr(manager, "_install_runtime_update_candidate", fail_download)

    with pytest.raises(LocalAIStateError) as raised:
        manager._run_update_runtime_job(job)

    assert raised.value.code == "download_failed"
    assert attempted == ["vulkan"]


def test_accelerator_loader_output_has_a_dedicated_repair_code(tmp_path: Path) -> None:
    manager = LocalAIManager(local_dir=tmp_path, port=0, cpu_threads=1)
    manager._log_lines.append("CUDA driver error: no compatible device")

    assert manager._process_exit_code() == "accelerator_failed"


def test_install_failure_exposes_a_typed_disk_space_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = LocalAIManager(local_dir=tmp_path, port=0, cpu_threads=1)
    job = SimpleNamespace(job_id="disk", model_id="gemma-4-e2b", cancel_event=threading.Event())
    monkeypatch.setattr(
        manager,
        "_run_install_job",
        lambda _job: (_ for _ in ()).throw(RuntimeError("insufficient free space for download")),
    )

    manager._run_install_job_wrapper(job)

    assert manager.status().state == "error"
    assert manager.status().error_code == "insufficient_disk_space"


def test_marker_write_failure_stops_the_just_spawned_child(
    manager: LocalAIManager, fake_process, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(LocalAIManager, "_reserve_loopback_port", lambda _self: 43123)
    _healthy_requests(monkeypatch)
    monkeypatch.setattr(
        manager, "_write_owner_marker", lambda *_args: (_ for _ in ()).throw(OSError())
    )
    with pytest.raises(LocalAIStateError):
        manager.start("gemma-4-e2b")
    assert fake_process[0].terminated is True
    assert manager._process is None
    assert not manager._owner_marker_path.exists()


def test_status_reconciles_a_child_that_crashes_after_start(
    manager: LocalAIManager, fake_process, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(LocalAIManager, "_reserve_loopback_port", lambda _self: 43123)
    _healthy_requests(monkeypatch)
    manager.start("gemma-4-e2b")
    fake_process[0].returncode = 9
    status = manager.status()
    assert status.state == "error"
    assert status.error_code == "process_exited"
    assert manager._process is None
    assert not manager._owner_marker_path.exists()


def test_status_reconciles_runtime_removed_after_manager_initialization(
    manager: LocalAIManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = manager._binary_path
    assert binary is not None
    manager._status = manager_module.LocalAIStatus(state="installed", model_id="gemma-4-e2b")
    binary.unlink()

    status = manager.status()

    assert status.state == "not_installed"
    assert manager._binary_path is None
    monkeypatch.setattr(
        manager_module,
        "detect_hardware_profile",
        lambda: HardwareProfile(os="Darwin", arch="arm64", gpu="metal"),
    )
    with pytest.raises(LocalAIStateError) as raised:
        manager.start("gemma-4-e2b")
    assert raised.value.code == "runtime_incompatible"


def test_loopback_port_reservation_does_not_leak_raw_oserror(
    manager: LocalAIManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    import errno

    real_socket = manager_module.socket.socket

    class _BusyPortSocket:
        def __init__(self, *args, **kwargs):
            self._sock = real_socket(*args, **kwargs)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            try:
                self._sock.close()
            except OSError:
                pass
            return False

        def setsockopt(self, *args, **kwargs):
            return self._sock.setsockopt(*args, **kwargs)

        def bind(self, addr):
            # Simulate the OS refusing to bind a port that is already in use.
            raise OSError(errno.EADDRINUSE, "Address already in use")

        def getsockname(self):
            return self._sock.getsockname()

    monkeypatch.setattr(manager_module.socket, "socket", _BusyPortSocket)

    with pytest.raises(LocalAIStateError) as excinfo:
        manager._reserve_loopback_port()

    message = str(excinfo.value)
    assert message == "loopback port is unavailable"
    assert "Errno" not in message
    assert "Address already in use" not in message


def test_busy_preferred_loopback_port_falls_back_to_an_available_port(tmp_path: Path) -> None:
    with manager_module.socket.socket(
        manager_module.socket.AF_INET, manager_module.socket.SOCK_STREAM
    ) as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        busy_port = int(occupied.getsockname()[1])
        manager = LocalAIManager(local_dir=tmp_path, port=busy_port, cpu_threads=1)

        selected_port = manager._reserve_loopback_port()

    assert selected_port > 0
    assert selected_port != busy_port


def test_windows_loopback_reservation_uses_exclusive_address_ownership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    options: list[tuple[int, int, int]] = []

    class _WindowsSocket:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def setsockopt(self, level, option, value):
            options.append((level, option, value))

        def bind(self, _address):
            return None

        def getsockname(self):
            return ("127.0.0.1", 43123)

    monkeypatch.setattr(manager_module.platform, "system", lambda: "Windows")
    monkeypatch.setattr(manager_module.socket, "SO_EXCLUSIVEADDRUSE", 0x100, raising=False)
    monkeypatch.setattr(manager_module.socket, "socket", lambda *_args: _WindowsSocket())
    instance = LocalAIManager(local_dir=tmp_path, port=8080, cpu_threads=1)

    assert instance._reserve_loopback_port() == 43123
    assert options == [(manager_module.socket.SOL_SOCKET, 0x100, 1)]
    assert all(option != manager_module.socket.SO_REUSEADDR for _, option, _ in options)


def test_stop_never_kills_a_process_not_owned_by_this_manager(manager: LocalAIManager) -> None:
    manager._process = None
    manager._owner_pid = 999999

    assert manager.stop() is False


def test_stop_terminates_owned_process_and_removes_marker(
    manager: LocalAIManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    _healthy_requests(monkeypatch)
    manager.start("gemma-4-e2b")
    process = manager._process
    marker = manager._owner_marker_path
    assert marker.exists()

    assert manager.stop() is True
    assert process.terminated is True
    assert not marker.exists()
    assert manager.status().state == "stopped"


def test_process_level_start_generation_stop_and_port_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server = tmp_path / "llama-server"
    server.write_text(
        f"""#!{sys.executable}
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

port = int(sys.argv[sys.argv.index('--port') + 1])

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        return

    def _send(self, payload):
        encoded = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self):
        if self.path == '/health':
            self._send({{'status': 'ok'}})
        elif self.path == '/v1/models':
            self._send({{'data': [{{'id': 'fixture-model'}}]}})
        else:
            self.send_error(404)

    def do_POST(self):
        length = int(self.headers.get('Content-Length', '0'))
        json.loads(self.rfile.read(length) or b'{{}}')
        self._send({{'choices': [{{'text': 'pong'}}]}})

HTTPServer(('127.0.0.1', port), Handler).serve_forever()
""",
        encoding="utf-8",
    )
    server.chmod(0o700)
    model = tmp_path / "main.gguf"
    draft = tmp_path / "draft.gguf"
    model.write_bytes(_gguf(b"main"))
    draft.write_bytes(_gguf(b"draft"))
    manager = LocalAIManager(
        local_dir=tmp_path,
        binary_path=server,
        model_paths={model_id: model for model_id in MODELS},
        draft_paths={model_id: draft for model_id in MODELS},
        port=0,
        cpu_threads=1,
        accelerator_available=False,
        startup_timeout=5,
        health_interval=0.01,
    )
    monkeypatch.setattr(manager, "_validate_artifacts", lambda *_args, **_kwargs: None)

    running = manager.start("gemma-4-e2b", mtp_enabled=False)
    assert running.state == "running"
    assert running.model_name == "fixture-model"
    response = requests.post(
        f"{running.host}/v1/completions",
        json={"prompt": "ping", "max_tokens": 1},
        timeout=1,
    )
    assert response.json()["choices"][0]["text"] == "pong"
    port = running.port
    process = manager._process
    repeated = manager.start("gemma-4-e2b", mtp_enabled=False)
    assert repeated.state == "running"
    assert manager._process is process

    assert manager.stop() is True
    assert process.poll() is not None
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.2)
        assert probe.connect_ex(("127.0.0.1", int(port))) != 0

    restarted = manager.start("gemma-4-e2b", mtp_enabled=False)
    assert restarted.state == "running"
    assert manager._process is not process
    assert manager.stop() is True


def test_active_request_blocks_start_or_context_restart(
    manager: LocalAIManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    _healthy_requests(monkeypatch)
    manager.start("gemma-4-e2b")
    manager.mark_request_active()

    with pytest.raises(LocalAIStateError, match="active"):
        manager.start("gemma-4-e4b")

    manager.mark_request_idle()


def test_request_lease_rejects_a_stopped_runtime_without_incrementing_ownership(
    manager: LocalAIManager,
) -> None:
    with pytest.raises(LocalAIStateError, match="not running") as raised:
        manager.mark_request_active("gemma-4-e2b")

    assert raised.value.code == "local_ai_not_running"
    assert manager._active_requests == 0


def test_request_lease_rejects_a_different_running_model(
    manager: LocalAIManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    _healthy_requests(monkeypatch)
    manager.start("gemma-4-e2b")

    with pytest.raises(LocalAIStateError, match="expected") as raised:
        manager.mark_request_active("gemma-4-e4b")

    assert raised.value.code == "local_ai_wrong_model_running"
    assert manager._active_requests == 0


def test_request_lease_atomically_rejects_stop_winning_after_preflight(
    manager: LocalAIManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    _healthy_requests(monkeypatch)
    preflight = manager.start("gemma-4-e2b")
    assert preflight.state == "running"
    assert preflight.model_id == "gemma-4-e2b"
    stopped = threading.Event()

    def stop_after_preflight() -> None:
        assert manager.stop() is True
        stopped.set()

    stop_thread = threading.Thread(target=stop_after_preflight)
    stop_thread.start()
    assert stopped.wait(1)

    with pytest.raises(LocalAIStateError, match="not running") as raised:
        manager.mark_request_active(preflight.model_id)

    stop_thread.join(1)
    assert raised.value.code == "local_ai_not_running"
    assert manager._active_requests == 0
    assert manager.status().state == "stopped"


def test_request_lease_winning_the_race_blocks_ordinary_stop(
    manager: LocalAIManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    _healthy_requests(monkeypatch)
    manager.start("gemma-4-e2b")
    manager.mark_request_active("gemma-4-e2b")

    with pytest.raises(LocalAIStateError, match="request is active") as raised:
        manager.stop()

    assert raised.value.code == "state_conflict"
    assert manager.status().state == "running"
    manager.mark_request_idle()
    assert manager.stop() is True


def test_overlapping_identical_start_is_bounded_as_busy(
    manager: LocalAIManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    health_entered = threading.Event()
    health_release = threading.Event()

    def wait_for_health(_port: int) -> str:
        health_entered.set()
        assert health_release.wait(2)
        return "server-reported-gemma"

    monkeypatch.setattr(manager, "_poll_health", wait_for_health)
    monkeypatch.setattr(manager, "_reserve_loopback_port", lambda: 43123)
    outcome: dict[str, object] = {}
    thread = threading.Thread(
        target=lambda: outcome.setdefault("status", manager.start("gemma-4-e2b"))
    )
    thread.start()
    assert health_entered.wait(1)

    with pytest.raises(LocalAIStateError, match="already starting") as raised:
        manager.start("gemma-4-e2b")
    assert raised.value.code == "busy"

    health_release.set()
    thread.join(2)
    assert not thread.is_alive()
    assert getattr(outcome.get("status"), "state", None) == "running"


def test_port_bind_failure_in_child_log_is_classified_as_port_conflict(
    manager: LocalAIManager,
) -> None:
    manager._log_lines.append("server: failed to bind: Address already in use")

    assert manager._process_exit_code() == "port_conflict"


def test_request_activity_surfaces_idle_unload_and_wake(
    manager: LocalAIManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = [100.0]
    monkeypatch.setattr(manager_module.time, "monotonic", lambda: now[0])
    _healthy_requests(monkeypatch)
    manager._accelerator_available = False
    manager.start("gemma-4-e2b")

    now[0] += manager_module.IDLE_SLEEP_SECONDS - 1
    assert manager.status().state == "running"
    now[0] += 1
    assert manager.status().state == "sleeping"

    manager.mark_request_active()
    assert manager.status().state == "running"
    manager.mark_request_idle()
    now[0] += manager_module.IDLE_SLEEP_SECONDS - 1
    assert manager.status().state == "running"


def test_status_contains_only_sanitized_operational_fields(manager: LocalAIManager) -> None:
    status = manager.status()
    payload = status.to_dict()

    assert set(payload) >= {"state", "model_id", "model_name", "host", "message"}
    assert "binary_path" not in payload
    assert "command" not in payload
    assert "log" not in payload
    assert str(manager._owner_marker_path) not in repr(status)


def test_install_returns_job_id_and_supports_cancellation(
    manager: LocalAIManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = []

    monkeypatch.setattr(
        manager,
        "_run_install_job",
        lambda job: (started.append(job.job_id), job.cancel_event.wait(1)),
    )
    job_id = manager.install("gemma-4-e2b", start_after_install=False)
    assert job_id
    manager.cancel_install(job_id)

    deadline = time.monotonic() + 2
    while manager._jobs and time.monotonic() < deadline:
        time.sleep(0.01)
    assert started == [job_id]
    assert manager.status().state == "installed"
    assert not manager.status().message


def test_manifest_is_written_after_start_and_reloaded_on_new_manager(
    tmp_path: Path, fake_process, monkeypatch: pytest.MonkeyPatch
) -> None:
    _healthy_requests(monkeypatch)
    binary = tmp_path / "llama-server"
    model = tmp_path / "models" / "gemma-4-e2b" / "gemma-4-E2B-it-qat-UD-Q4_K_XL.gguf"
    draft = tmp_path / "models" / "gemma-4-e2b" / "mtp-gemma-4-E2B-it.gguf"
    binary.write_bytes(b"test-artifact")
    model.parent.mkdir(parents=True, exist_ok=True)
    draft.parent.mkdir(parents=True, exist_ok=True)
    model.write_bytes(_gguf())
    draft.write_bytes(_gguf())

    first = LocalAIManager(
        local_dir=tmp_path,
        binary_path=binary,
        binary_spec=BINARY_SPECS["macos-arm64-metal"],
        model_paths={"gemma-4-e2b": model, "gemma-4-e4b": model},
        draft_paths={"gemma-4-e2b": draft, "gemma-4-e4b": draft},
        port=0,
        cpu_threads=7,
        accelerator_available=True,
    )
    monkeypatch.setattr(first, "_validate_artifacts", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(first, "_read_server_model_id", lambda _port: "server-reported-gemma")
    monkeypatch.setattr(first, "_runtime_device_for_start", lambda _path: "Metal")
    monkeypatch.setattr(first, "_observed_gpu_offload_layers", lambda: 1)

    first.start("gemma-4-e2b", mtp_enabled=False)
    assert first._runtime_offloaded_layers == 1
    assert first.runtime_details()["observed_offloaded_layers"] == 1
    assert (tmp_path / "manifest.json").exists()

    # The second manager needs its own Popen patch after the first context exits.
    monkeypatch.setattr(manager_module.subprocess, "Popen", lambda *_args, **_kwargs: FakeProcess())
    # The fixture artifacts are intentionally tiny, so bypass only the catalog
    # checksum verification while testing manifest state restoration.
    monkeypatch.setattr(LocalAIManager, "_verify_file", lambda *_args, **_kwargs: None)
    second = LocalAIManager(
        local_dir=tmp_path,
        port=0,
        cpu_threads=7,
        accelerator_available=True,
    )
    assert second.runtime_details()["observed_offloaded_layers"] == 1
    assert second.status().state == "installed"
    assert second.status().model_id is None
    assert second._binary_path == binary.resolve()
    assert second._model_paths["gemma-4-e2b"] == model.resolve()
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert "gemma-4-e2b" in manifest["models"]


def test_install_reuses_verified_runtime_and_skips_binary_download(
    manager: LocalAIManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = []
    completed: list[str] = []
    auto_started: list[str | None] = []

    def fake_download(spec, *, progress_callback=None, cancel_event=None):
        calls.append(spec.catalog_key)
        spec.destination.parent.mkdir(parents=True, exist_ok=True)
        spec.destination.write_bytes(_gguf())
        if progress_callback is not None:
            progress_callback(spec.expected_bytes, spec.expected_bytes)
        return spec.destination

    monkeypatch.setattr(manager_module, "download_catalog_artifact", fake_download)
    monkeypatch.setattr(manager, "_verify_installed_runtime", lambda *_args, **_kwargs: None)
    starts: list[dict[str, object]] = []

    def record_start(_model_id, **kwargs):
        starts.append(kwargs)
        manager._status = manager_module.LocalAIStatus(
            state="running",
            model_id="gemma-4-e2b",
            model_name="gemma-4-E2B-it",
            host="http://127.0.0.1:43123",
        )

    monkeypatch.setattr(manager, "start", record_start)
    monkeypatch.setattr(manager, "_resolve_binary_path", lambda: manager._binary_path)
    manager.set_install_completion_callback(
        lambda model_id: completed.append(f"{model_id}:{manager.status().state}")
    )
    manager.set_auto_start_completion_callback(lambda status: auto_started.append(status.host))
    manager._binary_path = manager.local_dir / "llama-server"
    manager._binary_path.write_bytes(b"fixture")
    from src.local_ai.platform import HardwareProfile

    manager._binary_spec = select_binary(HardwareProfile(os="Darwin", arch="arm64", gpu="metal"))
    if binary_extract_path := getattr(manager_module, "binary_extract_path", None):
        extraction = binary_extract_path(manager._binary_spec.profile, root=manager.local_dir)
        extraction.mkdir(parents=True, exist_ok=True)
        (extraction / "llama-server").write_bytes(b"fixture")

    job_id = manager.install(
        "gemma-4-e2b",
        start_after_install=True,
        context_tokens=65_536,
        mtp_enabled=True,
        mtp_draft_tokens=5,
    )
    assert job_id
    time.sleep(0.05)
    assert not any(key.startswith("binary:") for key in calls), calls
    assert any(key == "model:gemma-4-e2b" for key in calls), calls
    assert completed == ["gemma-4-e2b:running"]
    assert auto_started == ["http://127.0.0.1:43123"]
    assert starts == [{"context_tokens": 65_536, "mtp_enabled": True, "mtp_draft_tokens": 5}]


def test_fresh_install_uses_the_catalog_pinned_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = LocalAIManager(local_dir=tmp_path, port=0, cpu_threads=4)
    monkeypatch.setattr(manager, "_preflight_runtime", lambda *_args: None)
    readiness_calls: list[tuple[str, tuple[object, ...]]] = []

    def verify_installed_runtime(job, candidates, **_kwargs):
        assert manager._model_paths[job.model_id].is_file()
        assert manager._draft_paths[job.model_id].is_file()
        readiness_calls.append((job.model_id, candidates))

    monkeypatch.setattr(manager, "_verify_installed_runtime", verify_installed_runtime)
    template = BINARY_SPECS["windows-arm64-cpu"]
    resolved = replace(
        template,
        release_tag="b10043",
        archive_filename="llama-b10043-bin-win-cpu-arm64.zip",
        archive_url=(
            "https://github.com/ggml-org/llama.cpp/releases/download/b10043/"
            "llama-b10043-bin-win-cpu-arm64.zip"
        ),
        archive_sha256="b" * 64,
        archive_bytes=12_345_678,
    )
    monkeypatch.setattr(manager_module, "binary_candidates", lambda _profile: (template,))
    monkeypatch.setattr(manager_module, "latest_binary_for_profile", lambda _binary: resolved)

    binary_downloads: list[tuple[str, int, str]] = []

    def fake_download_verified(*, url, destination, expected_sha256, expected_bytes, **_kwargs):
        binary_downloads.append((url, expected_bytes, expected_sha256))
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"runtime")
        return destination

    def fake_catalog_download(spec, **_kwargs):
        spec.destination.parent.mkdir(parents=True, exist_ok=True)
        spec.destination.write_bytes(_gguf(b"model"))
        return spec.destination

    def fake_extract(archive, destination, *, allowed_members, **_kwargs):
        server = destination / allowed_members[0]
        server.parent.mkdir(parents=True, exist_ok=True)
        server.write_bytes(b"runtime")
        return server

    monkeypatch.setattr(manager_module, "download_verified", fake_download_verified)
    monkeypatch.setattr(manager_module, "download_catalog_artifact", fake_catalog_download)
    monkeypatch.setattr(manager_module, "extract_verified_archive", fake_extract)

    manager._run_install_job(
        SimpleNamespace(
            job_id="install-latest",
            model_id="gemma-4-e2b",
            start_after_install=False,
            cancel_event=threading.Event(),
        )
    )

    assert binary_downloads == [
        (template.archive_url, template.archive_bytes, template.archive_sha256)
    ]
    assert manager._binary_spec == template
    assert readiness_calls == [("gemma-4-e2b", (template,))]


def test_delete_model_allows_inactive_model_while_another_model_is_active(
    manager: LocalAIManager, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    e4b_main = tmp_path / "e4b-main.gguf"
    e4b_draft = tmp_path / "e4b-draft.gguf"
    e4b_main.write_bytes(_gguf(b"e4b-main"))
    e4b_draft.write_bytes(_gguf(b"e4b-draft"))
    manager._model_paths["gemma-4-e4b"] = e4b_main
    manager._draft_paths["gemma-4-e4b"] = e4b_draft
    _healthy_requests(monkeypatch)
    manager.start("gemma-4-e2b")
    manager._active_requests = 1

    assert manager.delete_model("gemma-4-e4b") is True
    assert manager._process_is_running() is True
    assert not e4b_main.exists() and not e4b_draft.exists()

    with pytest.raises(LocalAIStateError, match="active") as raised:
        manager.delete_model("gemma-4-e2b")
    assert raised.value.code == "state_conflict"
    manager._active_requests = 0
    assert manager.stop() is True
    assert manager.delete_model("gemma-4-e2b") is True


def test_download_status_preserves_running_service_identity(
    manager: LocalAIManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    _healthy_requests(monkeypatch)
    running = manager.start("gemma-4-e2b")
    manager._binary_spec = select_binary(HardwareProfile(os="Darwin", arch="arm64", gpu="metal"))
    manager._model_paths.pop("gemma-4-e4b")
    manager._draft_paths.pop("gemma-4-e4b")
    started = threading.Event()

    def wait_for_cancel(job) -> None:
        started.set()
        job.cancel_event.wait(1)

    monkeypatch.setattr(manager, "_run_install_job", wait_for_cancel)
    job_id = manager.install("gemma-4-e4b", start_after_install=False)
    assert started.wait(1)

    status = manager.status()
    assert status.state == "running"
    assert status.model_id == "gemma-4-e2b"
    assert status.host == running.host
    assert status.operation_state == "downloading"
    assert status.operation_model_id == "gemma-4-e4b"
    assert status.job_id == job_id

    cancelling = manager.cancel_install(job_id)
    assert cancelling.state == "running"
    assert cancelling.operation_state == "cancelling"
    deadline = time.monotonic() + 2
    while manager._jobs and time.monotonic() < deadline:
        time.sleep(0.01)
    assert manager.status().state == "running"
    assert manager.status().operation_state is None


def test_download_started_while_stopped_keeps_another_model_startable(
    manager: LocalAIManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager._status = manager_module.LocalAIStatus(state="stopped")
    manager._binary_spec = select_binary(HardwareProfile(os="Darwin", arch="arm64", gpu="metal"))
    manager._model_paths.pop("gemma-4-e4b")
    manager._draft_paths.pop("gemma-4-e4b")
    worker_started = threading.Event()
    worker_release = threading.Event()

    def wait_for_release(_job) -> None:
        worker_started.set()
        assert worker_release.wait(2)

    monkeypatch.setattr(manager, "_run_install_job", wait_for_release)
    job_id = manager.install("gemma-4-e4b", start_after_install=False)
    assert worker_started.wait(1)

    downloading = manager.status()
    assert downloading.state == "stopped"
    assert downloading.operation_kind == "model_download"
    assert downloading.operation_state == "downloading"
    assert downloading.operation_model_id == "gemma-4-e4b"

    _healthy_requests(monkeypatch)
    monkeypatch.setattr(manager, "_runtime_device_for_start", lambda _path: "Metal")
    monkeypatch.setattr(manager, "_observed_gpu_offload_layers", lambda: 1)
    started = manager.start("gemma-4-e2b")
    assert started.state == "running"
    assert started.model_id == "gemma-4-e2b"
    assert started.operation_kind == "model_download"
    assert started.operation_state == "downloading"
    assert started.job_id == job_id

    worker_release.set()
    deadline = time.monotonic() + 2
    while manager._jobs and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not manager._jobs


def test_start_health_poll_does_not_block_transfer_cancellation(
    manager: LocalAIManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager._status = manager_module.LocalAIStatus(state="stopped")
    manager._model_paths.pop("gemma-4-e4b")
    manager._draft_paths.pop("gemma-4-e4b")
    install_started = threading.Event()
    install_release = threading.Event()

    def wait_for_release(_job) -> None:
        install_started.set()
        assert install_release.wait(2)

    monkeypatch.setattr(manager, "_run_install_job", wait_for_release)
    job_id = manager.install("gemma-4-e4b", start_after_install=False)
    assert install_started.wait(1)

    health_entered = threading.Event()
    health_release = threading.Event()

    def wait_for_health(_port: int) -> str:
        health_entered.set()
        assert health_release.wait(2)
        return "server-reported-gemma"

    monkeypatch.setattr(manager, "_poll_health", wait_for_health)
    monkeypatch.setattr(manager, "_reserve_loopback_port", lambda: 43123)
    start_outcome: dict[str, object] = {}

    def run_start() -> None:
        try:
            start_outcome["status"] = manager.start("gemma-4-e2b")
        except Exception as exc:  # pragma: no cover - assertion reports the captured failure
            start_outcome["error"] = exc

    start_thread = threading.Thread(target=run_start)
    start_thread.start()
    assert health_entered.wait(1)

    cancel_done = threading.Event()

    def cancel_transfer() -> None:
        manager.cancel_install(job_id)
        cancel_done.set()

    cancel_thread = threading.Thread(target=cancel_transfer)
    cancel_thread.start()
    assert cancel_done.wait(0.5)
    assert manager.status().state == "starting"

    health_release.set()
    install_release.set()
    start_thread.join(2)
    cancel_thread.join(2)
    assert not start_thread.is_alive()
    assert not cancel_thread.is_alive()
    assert "error" not in start_outcome
    assert getattr(start_outcome.get("status"), "state", None) == "running"


def test_status_reconciliation_during_health_poll_releases_start_ownership(
    manager: LocalAIManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    health_entered = threading.Event()
    health_release = threading.Event()

    def wait_for_health(_port: int) -> str:
        health_entered.set()
        assert health_release.wait(2)
        return "server-reported-gemma"

    monkeypatch.setattr(manager, "_poll_health", wait_for_health)
    monkeypatch.setattr(manager, "_reserve_loopback_port", lambda: 43123)
    outcome: dict[str, object] = {}

    def run_start() -> None:
        try:
            manager.start("gemma-4-e2b")
        except Exception as exc:  # pragma: no cover - assertion reports the captured failure
            outcome["error"] = exc

    start_thread = threading.Thread(target=run_start)
    start_thread.start()
    assert health_entered.wait(1)
    manager._process.returncode = 17

    reconciled = manager.status()
    assert reconciled.state == "error"
    assert reconciled.error_code == "process_exited"
    assert manager._start_in_flight is None

    health_release.set()
    start_thread.join(2)
    assert not start_thread.is_alive()
    assert isinstance(outcome.get("error"), LocalAIStateError)
    assert manager._start_in_flight is None


def test_background_import_preserves_a_different_running_model(
    manager: LocalAIManager, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _healthy_requests(monkeypatch)
    running = manager.start("gemma-4-e2b")
    manager._model_paths.pop("gemma-4-e4b")
    manager._draft_paths.pop("gemma-4-e4b")
    source = tmp_path / "import-source"
    source.mkdir()
    spec = MODELS["gemma-4-e4b"]
    (source / spec.model_filename).write_bytes(_gguf(b"import-main"))
    (source / spec.draft_filename).write_bytes(_gguf(b"import-draft"))
    copy_entered = threading.Event()
    copy_release = threading.Event()
    original_copy = manager._copy_import_artifact

    def paused_copy(*args, **kwargs):
        copy_entered.set()
        assert copy_release.wait(2)
        return original_copy(*args, **kwargs)

    monkeypatch.setattr(manager, "_copy_import_artifact", paused_copy)
    job_id = manager.start_background_import("gemma-4-e4b", source)
    assert copy_entered.wait(1)

    importing = manager.status()
    assert importing.state == "running"
    assert importing.model_id == "gemma-4-e2b"
    assert importing.host == running.host
    assert importing.operation_kind == "model_import"
    assert importing.operation_state == "importing"
    assert importing.operation_model_id == "gemma-4-e4b"
    assert importing.job_id == job_id

    copy_release.set()
    deadline = time.monotonic() + 2
    while manager._background_import_jobs and time.monotonic() < deadline:
        time.sleep(0.01)
    completed = manager.status()
    assert completed.state == "running"
    assert completed.operation_state is None
    assert (
        next(entry for entry in manager.inventory() if entry["model_id"] == "gemma-4-e4b")[
            "installed"
        ]
        is True
    )


def test_completed_download_keeps_running_model_and_installs_target(
    manager: LocalAIManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    _healthy_requests(monkeypatch)
    running = manager.start("gemma-4-e2b")
    manager._binary_spec = select_binary(HardwareProfile(os="Darwin", arch="arm64", gpu="metal"))
    manager._model_paths.pop("gemma-4-e4b")
    manager._draft_paths.pop("gemma-4-e4b")

    def fake_download(spec, *, progress_callback=None, cancel_event=None):
        spec.destination.parent.mkdir(parents=True, exist_ok=True)
        spec.destination.write_bytes(_gguf(spec.catalog_key.encode()))
        if progress_callback is not None:
            progress_callback(spec.expected_bytes, spec.expected_bytes)
        return spec.destination

    monkeypatch.setattr(manager_module, "download_catalog_artifact", fake_download)
    monkeypatch.setattr(manager, "_verify_installed_runtime", lambda *_args, **_kwargs: None)
    manager._run_install_job(
        SimpleNamespace(
            job_id="download-e4b",
            model_id="gemma-4-e4b",
            start_after_install=False,
            cancel_event=threading.Event(),
        )
    )

    status = manager.status()
    assert status.state == "running"
    assert status.model_id == "gemma-4-e2b"
    assert status.host == running.host
    assert status.operation_state is None
    assert (
        next(entry for entry in manager.inventory() if entry["model_id"] == "gemma-4-e4b")[
            "installed"
        ]
        is True
    )


def test_running_service_crash_remains_visible_during_download(
    manager: LocalAIManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    _healthy_requests(monkeypatch)
    manager.start("gemma-4-e2b")
    manager._model_paths.pop("gemma-4-e4b")
    manager._draft_paths.pop("gemma-4-e4b")
    started = threading.Event()

    def wait_for_cancel(job) -> None:
        started.set()
        job.cancel_event.wait(1)

    monkeypatch.setattr(manager, "_run_install_job", wait_for_cancel)
    job_id = manager.install("gemma-4-e4b", start_after_install=False)
    assert started.wait(1)
    manager._process.returncode = 17

    status = manager.status()
    assert status.state == "error"
    assert status.error_code == "process_exited"
    assert status.operation_state == "downloading"
    assert status.operation_model_id == "gemma-4-e4b"

    manager.cancel_install(job_id)


def test_download_rejects_the_active_model(
    manager: LocalAIManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    _healthy_requests(monkeypatch)
    manager.start("gemma-4-e2b")

    with pytest.raises(LocalAIStateError, match="currently active") as raised:
        manager.install("gemma-4-e2b", start_after_install=False)

    assert raised.value.code == "state_conflict"


def test_delete_model_removes_artifacts_and_manifest_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AQA_LOCAL_AI_DIR", str(tmp_path / "local-ai"))
    from src.local_ai.catalog import MODELS

    manager = LocalAIManager(local_dir=tmp_path / "local-ai", port=0, cpu_threads=4)
    model_dir = manager.local_dir / "models" / "gemma-4-e2b"
    model_dir.mkdir(parents=True, exist_ok=True)
    spec = MODELS["gemma-4-e2b"]
    (model_dir / spec.model_filename).write_bytes(b"main")
    (model_dir / spec.draft_filename).write_bytes(b"draft")
    manager._model_paths["gemma-4-e2b"] = model_dir / spec.model_filename
    manager._draft_paths["gemma-4-e2b"] = model_dir / spec.draft_filename
    manager._binary_spec = select_binary(HardwareProfile(os="Darwin", arch="arm64", gpu="metal"))
    manager._binary_path = manager.local_dir / "llama-server"
    manager._binary_path.write_bytes(b"binary")
    manager._write_manifest()

    assert manager.delete_model("gemma-4-e2b") is True
    assert "gemma-4-e2b" not in manager._model_paths
    manifest = json.loads((manager.local_dir / "manifest.json").read_text())
    assert "gemma-4-e2b" not in manifest.get("models", {})


def test_delete_model_refuses_conflicting_operations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = LocalAIManager(local_dir=tmp_path, port=0, cpu_threads=1)
    model_dir = tmp_path / "models" / "gemma-4-e2b"
    model_dir.mkdir(parents=True)
    spec = MODELS["gemma-4-e2b"]
    main = model_dir / spec.model_filename
    draft = model_dir / spec.draft_filename
    main.write_bytes(_gguf(b"main"))
    draft.write_bytes(_gguf(b"draft"))
    manager._model_paths["gemma-4-e2b"] = main
    manager._draft_paths["gemma-4-e2b"] = draft
    manager._jobs["job"] = SimpleNamespace(cancel_event=threading.Event())
    with pytest.raises(LocalAIStateError, match="another operation"):
        manager.delete_model("gemma-4-e2b")
    assert main.exists() and draft.exists()


def test_delete_model_allows_a_different_model_during_download(tmp_path: Path) -> None:
    manager = LocalAIManager(local_dir=tmp_path, port=0, cpu_threads=1)
    installed_paths: dict[str, tuple[Path, Path]] = {}
    for model_id in ("gemma-4-e2b", "gemma-4-e4b"):
        spec = MODELS[model_id]
        model_dir = tmp_path / "models" / model_id
        model_dir.mkdir(parents=True)
        main = model_dir / spec.model_filename
        draft = model_dir / spec.draft_filename
        main.write_bytes(_gguf(f"{model_id}-main".encode()))
        draft.write_bytes(_gguf(f"{model_id}-draft".encode()))
        manager._model_paths[model_id] = main
        manager._draft_paths[model_id] = draft
        installed_paths[model_id] = (main, draft)

    transfer = SimpleNamespace(model_id="gemma-4-12b", cancel_event=threading.Event())
    manager._jobs["download"] = transfer

    assert manager.delete_model("gemma-4-e4b") is True
    assert not any(path.exists() for path in installed_paths["gemma-4-e4b"])
    assert all(path.exists() for path in installed_paths["gemma-4-e2b"])

    transfer.model_id = "gemma-4-e2b"
    with pytest.raises(LocalAIStateError, match="another operation") as raised:
        manager.delete_model("gemma-4-e2b")
    assert raised.value.code == "state_conflict"
    assert all(path.exists() for path in installed_paths["gemma-4-e2b"])


def test_delete_model_restores_files_and_registry_when_manifest_write_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = LocalAIManager(local_dir=tmp_path, port=0, cpu_threads=1)
    model_dir = tmp_path / "models" / "gemma-4-e2b"
    model_dir.mkdir(parents=True)
    spec = MODELS["gemma-4-e2b"]
    main = model_dir / spec.model_filename
    draft = model_dir / spec.draft_filename
    main.write_bytes(_gguf(b"main"))
    draft.write_bytes(_gguf(b"draft"))
    manager._model_paths["gemma-4-e2b"] = main
    manager._draft_paths["gemma-4-e2b"] = draft

    def fail_manifest() -> None:
        raise OSError("manifest unavailable")

    monkeypatch.setattr(manager, "_write_manifest", fail_manifest)
    with pytest.raises(LocalAIStateError, match="could not delete model files"):
        manager.delete_model("gemma-4-e2b")
    assert main.exists() and draft.exists()
    assert manager._model_paths["gemma-4-e2b"] == main
    assert manager._draft_paths["gemma-4-e2b"] == draft


def test_delete_model_keeps_committed_manifest_when_staging_cleanup_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = LocalAIManager(local_dir=tmp_path, port=0, cpu_threads=1)
    model_dir = tmp_path / "models" / "gemma-4-e2b"
    model_dir.mkdir(parents=True)
    spec = MODELS["gemma-4-e2b"]
    main = model_dir / spec.model_filename
    draft = model_dir / spec.draft_filename
    main.write_bytes(_gguf(b"main"))
    draft.write_bytes(_gguf(b"draft"))
    manager._model_paths["gemma-4-e2b"] = main
    manager._draft_paths["gemma-4-e2b"] = draft
    manager._write_manifest()

    def fail_cleanup(_path: Path, *args: Any, **kwargs: Any) -> None:
        raise OSError("cleanup unavailable")

    monkeypatch.setattr(manager_module.shutil, "rmtree", fail_cleanup)
    assert manager.delete_model("gemma-4-e2b") is True
    assert not main.exists() and not draft.exists()
    assert "gemma-4-e2b" not in manager._model_paths
    assert not next(entry for entry in manager.inventory() if entry["model_id"] == "gemma-4-e2b")[
        "installed"
    ]
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert "gemma-4-e2b" not in manifest["models"]


def test_delete_runtime_refuses_when_running_or_models_remain(
    manager: LocalAIManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(LocalAIStateError, match="models"):
        manager.delete_runtime()


def test_runtime_mutations_reject_active_service(
    manager: LocalAIManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    _healthy_requests(monkeypatch)
    manager.start("gemma-4-e2b")

    with pytest.raises(LocalAIStateError, match="server is active") as update_error:
        manager.update_runtime()
    assert update_error.value.code == "state_conflict"
    with pytest.raises(LocalAIStateError, match="server is running"):
        manager.delete_runtime()


def test_runtime_update_blocks_start_and_runtime_delete(tmp_path: Path) -> None:
    binary = tmp_path / "llama-server"
    binary.write_bytes(b"runtime")
    manager = LocalAIManager(local_dir=tmp_path, binary_path=binary, port=0, cpu_threads=1)
    runtime_job = SimpleNamespace(model_id="__runtime_update__", cancel_event=threading.Event())
    manager._jobs["runtime-job"] = runtime_job
    manager._operation_status = manager_module.LocalAIStatus(
        state="downloading",
        model_id="__runtime_update__",
        job_id="runtime-job",
        operation_kind="runtime_update",
    )

    with pytest.raises(LocalAIStateError, match="runtime is being updated") as start_error:
        manager.start("gemma-4-e2b")
    assert start_error.value.code == "state_conflict"
    with pytest.raises(LocalAIStateError, match="another operation") as delete_error:
        manager.delete_runtime()
    assert delete_error.value.code == "state_conflict"
    assert binary.exists()


def test_update_runtime_verifies_candidate_before_switching_and_keeps_existing_until_valid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AQA_LOCAL_AI_DIR", str(tmp_path))
    manager = LocalAIManager(local_dir=tmp_path, port=0, cpu_threads=4)
    binary = select_binary(HardwareProfile(os="Darwin", arch="arm64", gpu="metal"))
    manager._binary_spec = binary
    manager._binary_path = (
        tmp_path / "llama.cpp" / "b10976" / binary.platform / "extracted" / "llama-server"
    )
    manager._binary_path.parent.mkdir(parents=True, exist_ok=True)
    manager._binary_path.write_bytes(b"old")
    manager._write_manifest()

    archive = tmp_path / "llama.cpp" / "b10976" / binary.platform / binary.archive_filename
    archive.parent.mkdir(parents=True, exist_ok=True)
    _write_server_tar(archive, b"new")

    monkeypatch.setattr(manager, "_process_is_running", lambda: False)
    updated = replace(
        binary,
        release_tag="b10043",
        archive_filename="llama-b10043-bin-macos-arm64.tar.gz",
        archive_url=(
            "https://github.com/ggml-org/llama.cpp/releases/download/b10043/"
            "llama-b10043-bin-macos-arm64.tar.gz"
        ),
        archive_sha256="c" * 64,
        archive_bytes=12_345_678,
        archive_members=("llama-b10043/llama-server",),
    )
    monkeypatch.setattr(manager_module, "latest_binary_for_profile", lambda _binary: updated)

    def fake_download(*, expected_bytes, progress_callback=None, **_kwargs):
        if progress_callback is not None:
            progress_callback(expected_bytes, expected_bytes)
        return archive

    monkeypatch.setattr(manager_module, "download_verified", fake_download)

    def fake_extract_verified_archive(
        archive_path, destination, *, expected_sha256, expected_bytes, allowed_members
    ):
        # Simulate extraction failure by never creating the server; verify was already done.
        raise ValueError("extraction failed")

    monkeypatch.setattr(manager_module, "extract_verified_archive", fake_extract_verified_archive)

    old_path = manager._binary_path
    manager.update_runtime()
    time.sleep(0.05)
    assert manager._binary_path == old_path
    manifest = json.loads((manager.local_dir / "manifest.json").read_text())
    assert manifest.get("runtime", {}).get("executable") == str(old_path)


def test_runtime_update_cancelled_at_download_barrier_keeps_active_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AQA_LOCAL_AI_DIR", str(tmp_path))
    manager = LocalAIManager(local_dir=tmp_path, port=0, cpu_threads=4)
    binary = select_binary(HardwareProfile(os="Darwin", arch="arm64", gpu="metal"))
    old_path = (
        tmp_path
        / "llama.cpp"
        / binary.release_tag
        / binary.platform
        / "extracted"
        / binary.engine_name
    )
    old_path.parent.mkdir(parents=True, exist_ok=True)
    old_path.write_bytes(b"old-runtime")
    manager._binary_spec = binary
    manager._binary_path = old_path
    manager._write_manifest()

    entered = threading.Event()
    release = threading.Event()
    job = SimpleNamespace(
        job_id="runtime-update-barrier",
        model_id="__runtime_update__",
        cancel_event=threading.Event(),
        cpu_fallback=False,
    )

    def blocked_download(*_args: object, **_kwargs: object) -> None:
        entered.set()
        assert release.wait(timeout=2)

    monkeypatch.setattr(manager_module, "download_verified", blocked_download)
    outcome: dict[str, BaseException] = {}

    def run() -> None:
        try:
            manager._run_update_runtime_job(job)
        except BaseException as exc:  # pragma: no cover - asserted below
            outcome["error"] = exc

    thread = threading.Thread(target=run)
    thread.start()
    assert entered.wait(timeout=2)
    job.cancel_event.set()
    release.set()
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert isinstance(outcome.get("error"), LocalAIStateError)
    assert manager._binary_path == old_path
    assert old_path.read_bytes() == b"old-runtime"
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["runtime"]["executable"] == str(old_path)


def _write_server_tar(path: Path, payload: bytes) -> None:
    import io
    import tarfile

    with tarfile.open(path, "w:gz") as archive:
        info = tarfile.TarInfo("llama-b10976/llama-server")
        info.size = len(payload)
        info.mode = 0o755
        archive.addfile(info, io.BytesIO(payload))


# Lifecycle tests run the real install job with local downloader fakes and an
# explicit tmp_path, covering manifest restoration, failure isolation, and the
# Windows directory-fsync exception without reading user state or using HTTP.


def _install_fixture_fakes(
    *,
    main_payload: bytes = _gguf(b"e2b-main-payload" * 17),
    draft_payload: bytes = _gguf(b"e2b-draft-payload" * 11),
) -> dict[str, object]:
    """Build narrow, local-only fakes for the install downloaders/extractors.

    Returns a dict of callables and capture lists so individual tests can
    assert exactly which specs the manager routed to which downloader, in
    which order, with which arguments.  No network or archive IO is
    performed — every artifact is written directly to the manager's
    catalog-rooted destination with the byte count the test asserts.
    """
    binary_calls: list[tuple[str, int, str]] = []
    catalog_calls: list[tuple[str, Path]] = []
    extract_calls: list[Path] = []

    def fake_download_verified(*, url, destination, expected_sha256, expected_bytes, **_kwargs):
        # Strict binary path: capture the (url, expected_bytes, expected_sha256)
        # tuple the manager routed to us.  The destination is whatever the
        # manager pre-computed via ``binary_download_spec``; writing the
        # payload is enough to satisfy any downstream fsync/sync calls.
        binary_calls.append((url, expected_bytes, expected_sha256))
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"runtime-bytes" * 32)
        return destination

    def fake_catalog_download(spec, *, progress_callback=None, **_kwargs):
        # Transfer-only path: capture the catalog key + destination so the
        # test can assert the (model, draft) ordering.  Write the test
        # payload directly to the destination, exactly the way a real
        # ``download_transfer_complete`` would.
        key = spec.catalog_key
        catalog_calls.append((key, spec.destination))
        spec.destination.parent.mkdir(parents=True, exist_ok=True)
        if key.startswith("model:"):
            spec.destination.write_bytes(main_payload)
        elif key.startswith("draft:"):
            spec.destination.write_bytes(draft_payload)
        else:  # pragma: no cover - defensive
            spec.destination.write_bytes(b"")
        if progress_callback is not None:
            try:
                size = spec.destination.stat().st_size
            except OSError:
                size = 0
            progress_callback(size, size)
        return spec.destination

    def fake_extract(archive, destination, *, allowed_members, **_kwargs):
        # The manager derives the executable name from the first allowed
        # member; we materialize that same path inside the extraction root
        # so ``_resolve_binary_path`` and the manifest writer both find it.
        extract_calls.append(destination)
        destination.mkdir(parents=True, exist_ok=True)
        server_member = allowed_members[0]
        server_path = destination / server_member
        server_path.parent.mkdir(parents=True, exist_ok=True)
        server_path.write_bytes(b"server-binary")
        return server_path

    return {
        "fake_download_verified": fake_download_verified,
        "fake_catalog_download": fake_catalog_download,
        "fake_extract": fake_extract,
        "binary_calls": binary_calls,
        "catalog_calls": catalog_calls,
        "extract_calls": extract_calls,
    }


def _resolved_binary_for_test(
    monkeypatch: pytest.MonkeyPatch, profile: str = "macos-arm64-metal"
) -> Any:
    """Pin a deterministic BinarySpec and short-circuit the GitHub lookup.

    ``_run_install_job`` calls ``latest_binary_for_profile`` to resolve the
    current release from GitHub.  We do not want network here, so we
    monkeypatch the helper to return the catalog's pinned b10976 spec for
    the local platform.  ``select_binary`` is similarly replaced with a
    deterministic stub so the manager never reads real hardware.
    """
    from src.local_ai.catalog import BINARY_SPECS

    binary = BINARY_SPECS[profile]
    monkeypatch.setattr(manager_module, "binary_candidates", lambda _profile: (binary,))
    monkeypatch.setattr(manager_module, "latest_binary_for_profile", lambda _b: binary)
    return binary


def test_install_publishes_runtime_and_models_then_fresh_manager_reports_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = _resolved_binary_for_test(monkeypatch)
    fakes = _install_fixture_fakes()
    monkeypatch.setattr(manager_module, "download_verified", fakes["fake_download_verified"])
    monkeypatch.setattr(manager_module, "download_catalog_artifact", fakes["fake_catalog_download"])
    monkeypatch.setattr(manager_module, "extract_verified_archive", fakes["fake_extract"])

    # An explicit local_dir prevents access to per-user settings or overrides.
    first = LocalAIManager(local_dir=tmp_path, port=0, cpu_threads=4)
    monkeypatch.setattr(first, "_preflight_runtime", lambda *_args: None)
    monkeypatch.setattr(first, "_verify_installed_runtime", lambda *_args, **_kwargs: None)
    first._run_install_job(
        SimpleNamespace(
            job_id="install-lifecycle",
            model_id="gemma-4-e2b",
            start_after_install=False,
            cancel_event=threading.Event(),
        )
    )

    assert fakes["binary_calls"] == [
        (binary.archive_url, binary.archive_bytes, binary.archive_sha256)
    ]

    catalog_keys = [key for key, _dest in fakes["catalog_calls"]]
    assert catalog_keys == ["model:gemma-4-e2b", "draft:gemma-4-e2b"]
    model_dest = fakes["catalog_calls"][0][1]
    draft_dest = fakes["catalog_calls"][1][1]
    assert model_dest == tmp_path / "models" / "gemma-4-e2b" / (
        # Catalog filenames are fixed at import time; keep the assertion
        # anchored to the catalog rather than re-implementing them.
        __import__("src.local_ai.catalog", fromlist=["MODELS"]).MODELS["gemma-4-e2b"].model_filename
    )
    assert draft_dest == tmp_path / "models" / "gemma-4-e2b" / (
        __import__("src.local_ai.catalog", fromlist=["MODELS"]).MODELS["gemma-4-e2b"].draft_filename
    )

    assert fakes["extract_calls"] == [
        tmp_path
        / "llama.cpp"
        / binary.release_tag
        / binary.platform
        / "backends"
        / binary.profile
        / "extracted"
    ]
    assert first._binary_path is not None
    assert first._binary_path.name == binary.engine_name
    assert first._binary_path.is_file()

    manifest_path = tmp_path / "manifest.json"
    assert manifest_path.is_file()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    main_entry = manifest["models"]["gemma-4-e2b"]["main_model"]
    draft_entry = manifest["models"]["gemma-4-e2b"]["draft_model"]
    assert main_entry["bytes"] == len(_gguf(b"e2b-main-payload" * 17))
    assert draft_entry["bytes"] == len(_gguf(b"e2b-draft-payload" * 11))
    assert main_entry["path"].endswith(model_dest.name)
    assert draft_entry["path"].endswith(draft_dest.name)

    # A fresh instance must derive state from disk rather than patched memory.
    second = LocalAIManager(local_dir=tmp_path, port=0, cpu_threads=4)
    inventory = {entry["model_id"]: entry for entry in second.inventory()}
    assert inventory["gemma-4-e2b"]["installed"] is True
    assert inventory["gemma-4-e2b"]["model_bytes"] == main_entry["bytes"]
    assert inventory["gemma-4-e2b"]["draft_bytes"] == draft_entry["bytes"]
    # ``_model_paths``/``_draft_paths`` are populated from the manifest,
    # not from another manager instance's in-memory state.
    assert second._model_paths["gemma-4-e2b"] == model_dest.resolve()
    assert second._draft_paths["gemma-4-e2b"] == draft_dest.resolve()
    # And the resolved executable is the same file the install published.
    assert second._binary_path == first._binary_path.resolve()

    status = second.status()
    assert status.state == "installed"
    assert status.model_id is None
    assert status.host is None
    assert status.port is None
    assert second._process is None


def test_windows_cuda_install_downloads_and_installs_cudart_companion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = BINARY_SPECS["windows-x86_64-cuda"]
    fakes = _install_fixture_fakes()
    companion_calls: list[tuple[Path, Path, tuple[str, ...], Path]] = []
    monkeypatch.setattr(manager_module, "latest_binary_for_profile", lambda _value: binary)
    monkeypatch.setattr(manager_module, "download_verified", fakes["fake_download_verified"])
    monkeypatch.setattr(manager_module, "download_catalog_artifact", fakes["fake_catalog_download"])
    monkeypatch.setattr(manager_module, "extract_verified_archive", fakes["fake_extract"])

    def install_companion(
        archive,
        destination,
        *,
        allowed_members,
        license_source,
        installed_license_filename,
        **_kwargs,
    ):
        companion_calls.append(
            (Path(archive), Path(destination), tuple(allowed_members), Path(license_source))
        )
        installed = []
        for member in allowed_members:
            target = Path(destination) / member
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"dll")
            installed.append(target)
        (Path(destination) / installed_license_filename).write_bytes(
            Path(license_source).read_bytes()
        )
        return tuple(installed)

    monkeypatch.setattr(manager_module, "install_verified_companion_archive", install_companion)
    manager = LocalAIManager(local_dir=tmp_path, port=0, cpu_threads=4)
    monkeypatch.setattr(manager, "_preflight_runtime", lambda *_args: None)
    monkeypatch.setattr(manager, "_verify_installed_runtime", lambda *_args, **_kwargs: None)
    manager._binary_spec = binary
    manager._run_install_job(
        SimpleNamespace(
            job_id="windows-cuda-install",
            model_id="gemma-4-e2b",
            start_after_install=False,
            cancel_event=threading.Event(),
        )
    )

    assert len(fakes["binary_calls"]) == 2
    assert fakes["binary_calls"][0] == (
        binary.archive_url,
        binary.archive_bytes,
        binary.archive_sha256,
    )
    companion = binary.companions[0]
    assert fakes["binary_calls"][1] == (
        companion.archive_url,
        companion.archive_bytes,
        companion.archive_sha256,
    )
    assert len(companion_calls) == 1
    _archive, destination, allowed, license_source = companion_calls[0]
    assert destination == manager._binary_path.parent
    assert allowed == companion.archive_members
    assert license_source.name == companion.license_filename
    assert all((destination / member).is_file() for member in allowed)
    assert (
        destination / companion.installed_license_filename
    ).read_bytes() == license_source.read_bytes()
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert set(Path(path).name for path in manifest["runtime"]["shared_libraries"]) >= set(allowed)


def test_windows_cuda_manifest_is_rejected_when_required_cudart_dll_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = BINARY_SPECS["windows-x86_64-cuda"]
    server = tmp_path / "llama-server.exe"
    server.write_bytes(b"server")
    manager = LocalAIManager(local_dir=tmp_path, port=0, cpu_threads=1)
    monkeypatch.setattr(manager, "_runtime_matches_current_host", lambda _binary: True)
    runtime = {
        "profile": binary.profile,
        "executable": str(server),
        "version": binary.release_tag,
        "archive_filename": binary.archive_filename,
        "archive_bytes": binary.archive_bytes,
        "archive_sha256": binary.archive_sha256,
        "platform": binary.platform,
        "accelerator": binary.accelerator,
        "archive_path": None,
        "shared_libraries": [],
    }

    manager._apply_manifest_runtime(runtime)

    assert manager._binary_path is None


def test_manifest_preserves_macos_cpu_fallback_after_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = BINARY_SPECS["macos-x86_64-cpu"]
    server = tmp_path / "llama-server"
    server.write_bytes(b"server")
    manager = LocalAIManager(local_dir=tmp_path, port=0, cpu_threads=1)
    monkeypatch.setattr(manager, "_runtime_matches_current_host", lambda _binary: True)

    manager._apply_manifest_runtime(
        {
            "profile": binary.profile,
            "accelerator": "cpu",
            "platform": binary.platform,
            "executable": str(server),
            "version": binary.release_tag,
            "archive_path": None,
            "archive_filename": binary.archive_filename,
            "archive_bytes": binary.archive_bytes,
            "archive_sha256": binary.archive_sha256,
            "shared_libraries": [],
        }
    )

    assert manager._binary_path == server.resolve()
    assert manager._binary_spec.accelerator == "cpu"


def test_install_state_is_never_running_after_persistence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _resolved_binary_for_test(monkeypatch)
    fakes = _install_fixture_fakes()
    monkeypatch.setattr(manager_module, "download_verified", fakes["fake_download_verified"])
    monkeypatch.setattr(manager_module, "download_catalog_artifact", fakes["fake_catalog_download"])
    monkeypatch.setattr(manager_module, "extract_verified_archive", fakes["fake_extract"])

    manager = LocalAIManager(local_dir=tmp_path, port=0, cpu_threads=4)
    monkeypatch.setattr(manager, "_preflight_runtime", lambda *_args: None)
    monkeypatch.setattr(manager, "_verify_installed_runtime", lambda *_args, **_kwargs: None)
    manager._run_install_job(
        SimpleNamespace(
            job_id="install-state",
            model_id="gemma-4-e2b",
            start_after_install=False,
            cancel_event=threading.Event(),
        )
    )
    assert manager.status().state in {"installed", "downloading"}
    # And the same invariant holds after a fresh restart.
    fresh = LocalAIManager(local_dir=tmp_path, port=0, cpu_threads=4)
    assert fresh.status().state == "installed"
    assert fresh._process is None


def test_install_draft_download_failure_does_not_persist_a_model_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.local_ai.downloads import DownloadError as _DownloadError

    _resolved_binary_for_test(monkeypatch)

    binary_calls: list[Path] = []
    catalog_calls: list[str] = []
    extract_calls: list[Path] = []

    def fake_download_verified(*, destination, **_kwargs):
        binary_calls.append(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"runtime")
        return destination

    def fake_catalog_download(spec, *, progress_callback=None, **_kwargs):
        catalog_calls.append(spec.catalog_key)
        spec.destination.parent.mkdir(parents=True, exist_ok=True)
        if spec.catalog_key.startswith("model:"):
            spec.destination.write_bytes(b"main-payload")
        elif spec.catalog_key.startswith("draft:"):
            # Simulate a draft transfer failure.
            raise _DownloadError("draft transfer failed")
        else:  # pragma: no cover - defensive
            spec.destination.write_bytes(b"")
        return spec.destination

    def fake_extract(archive, destination, *, allowed_members, **_kwargs):
        extract_calls.append(destination)
        destination.mkdir(parents=True, exist_ok=True)
        server = destination / allowed_members[0]
        server.parent.mkdir(parents=True, exist_ok=True)
        server.write_bytes(b"server")
        return server

    monkeypatch.setattr(manager_module, "download_verified", fake_download_verified)
    monkeypatch.setattr(manager_module, "download_catalog_artifact", fake_catalog_download)
    monkeypatch.setattr(manager_module, "extract_verified_archive", fake_extract)

    manager = LocalAIManager(local_dir=tmp_path, port=0, cpu_threads=4)
    monkeypatch.setattr(manager, "_preflight_runtime", lambda *_args: None)
    with pytest.raises(_DownloadError, match="draft transfer failed"):
        manager._run_install_job(
            SimpleNamespace(
                job_id="install-draft-fail",
                model_id="gemma-4-e2b",
                start_after_install=False,
                cancel_event=threading.Event(),
            )
        )

    # The downloaders were called in order and the draft was the failing one.
    assert [path.name for path in binary_calls]  # binary was downloaded
    assert catalog_calls == ["model:gemma-4-e2b", "draft:gemma-4-e2b"]
    # The manager did not write a manifest at all (no ``_write_manifest``
    # call was reached because the loop raised before the success path).
    assert not (tmp_path / "manifest.json").exists()
    # The in-memory state is the default — no model paths, no draft paths.
    assert "gemma-4-e2b" not in manager._model_paths
    assert "gemma-4-e2b" not in manager._draft_paths

    # A fresh manager, constructed from disk only, also reports E2B as
    # not installed — there is no manifest entry to restore.
    fresh = LocalAIManager(local_dir=tmp_path, port=0, cpu_threads=4)
    inventory = {entry["model_id"]: entry for entry in fresh.inventory()}
    assert inventory["gemma-4-e2b"]["installed"] is False
    assert inventory["gemma-4-e2b"]["model_bytes"] is None
    assert inventory["gemma-4-e2b"]["draft_bytes"] is None
    # The fresh manager is also not in ``running`` state.
    assert fresh.status().state == "not_installed"
    assert fresh._process is None


@pytest.mark.parametrize(
    "profile",
    ["macos-arm64-metal", "windows-x86_64-cpu", "linux-x86_64-cpu"],
)
def test_runtime_preflight_failure_happens_before_model_download_on_every_supported_os(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, profile: str
) -> None:
    _resolved_binary_for_test(monkeypatch, profile)
    fakes = _install_fixture_fakes()
    monkeypatch.setattr(manager_module, "download_verified", fakes["fake_download_verified"])
    monkeypatch.setattr(manager_module, "download_catalog_artifact", fakes["fake_catalog_download"])
    monkeypatch.setattr(manager_module, "extract_verified_archive", fakes["fake_extract"])

    manager = LocalAIManager(local_dir=tmp_path, port=0, cpu_threads=4)

    def reject_runtime(*_args) -> None:
        raise LocalAIStateError("runtime rejected", code="runtime_incompatible")

    monkeypatch.setattr(manager, "_preflight_runtime", reject_runtime)
    job = SimpleNamespace(
        job_id="runtime-preflight-fail",
        model_id="gemma-4-e2b",
        start_after_install=False,
        cancel_event=threading.Event(),
    )

    manager._run_install_job_wrapper(job)

    assert fakes["catalog_calls"] == []
    assert manager.status().state == "error"
    assert manager.status().error_code == "runtime_incompatible"
    fresh = LocalAIManager(local_dir=tmp_path, port=0, cpu_threads=4)
    inventory = {entry["model_id"]: entry for entry in fresh.inventory()}
    assert inventory["gemma-4-e2b"]["installed"] is False


def test_windows_directory_fsync_failure_does_not_create_install_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hashlib as _hashlib
    import io as _io
    import tarfile as _tarfile

    import src.local_ai.downloads as _dl

    # Build a local tar.gz that matches the on-disk size/SHA we tell the
    # manager.  We use a tiny ``BinarySpec`` so the test does not have to
    # materialize a real 10MB llama-server archive in tmp_path.
    server_payload = b"server-binary"
    archive_path = tmp_path / "runtime.tar.gz"
    with _tarfile.open(archive_path, "w:gz") as archive:
        info = _tarfile.TarInfo("llama-b10976/llama-server")
        info.size = len(server_payload)
        info.mode = 0o755
        archive.addfile(info, _io.BytesIO(server_payload))
    archive_bytes = archive_path.read_bytes()
    archive_sha = _hashlib.sha256(archive_bytes).hexdigest()
    archive_size = len(archive_bytes)

    # Construct a custom BinarySpec whose archive_url/size/sha match the
    # local fixture, so the manager's strict downloader (which we drive
    # from a local-only fake) sees a consistent strict spec.
    base_binary = BINARY_SPECS["macos-arm64-metal"]
    binary = replace(
        base_binary,
        archive_filename=archive_path.name,
        archive_url=archive_path.as_uri(),
        archive_sha256=archive_sha,
        archive_bytes=archive_size,
    )
    monkeypatch.setattr(manager_module, "binary_candidates", lambda _profile: (binary,))
    monkeypatch.setattr(manager_module, "latest_binary_for_profile", lambda _b: binary)

    extraction_root = tmp_path / "llama.cpp" / binary.release_tag / binary.platform / "extracted"
    server_name = "llama-server.exe" if binary.platform.startswith("windows-") else "llama-server"

    # Drive the manager's ``download_verified`` against a no-network local
    # copy that goes through the real ``_fsync_parent_directory`` path.
    # ``_verify_file`` is also called against the local copy, so the
    # strict spec must line up with the fixture's actual bytes/sha.
    class _NoNetworkLocalVerify:
        def __call__(self, *, url, destination, expected_sha256, expected_bytes, **_kwargs):
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(archive_bytes)
            _dl._verify_file(destination, expected_sha256, expected_bytes)
            _dl._fsync_parent_directory(destination)
            return destination

    monkeypatch.setattr(manager_module, "download_verified", _NoNetworkLocalVerify())

    # Allow the manager's catalog model/draft downloads to proceed through the
    # local fake below; only fail if a binary spec is routed to this helper.
    def _catalog_only_model_and_draft(spec, **kwargs):
        if spec.catalog_key.startswith("binary:"):
            raise AssertionError("catalog downloader must not be called for the binary")
        return _install_fixture_fakes()["fake_catalog_download"](spec, **kwargs)

    monkeypatch.setattr(manager_module, "download_catalog_artifact", _catalog_only_model_and_draft)

    # A local-only extract that mirrors the production shape: a single
    # member named after the binary's ``archive_members[0]``.
    def _local_extract(_archive, destination, *, allowed_members, **_kwargs):
        destination.mkdir(parents=True, exist_ok=True)
        server = destination / allowed_members[0]
        server.parent.mkdir(parents=True, exist_ok=True)
        server.write_bytes(server_payload)
        return server

    monkeypatch.setattr(manager_module, "extract_verified_archive", _local_extract)

    # Patch the downloads module's ``os`` proxy so the parent-fsync
    # branch sees ``os.name == 'nt'`` *and* the parent-dir ``os.open``
    # would raise ``OSError`` if it were called (the exact Windows
    # ``_open`` failure mode).  The short-circuit in
    # ``_fsync_parent_directory`` must return before the open, so the
    # install completes without an ``error`` state.
    import os as _real_os

    parent_resolved = str(extraction_root.parent)

    class _WindowsOsProxy:
        name = "nt"

        def open(self, path, flags, *args, **kwargs):
            if str(Path(path).resolve()) == Path(parent_resolved).resolve():
                raise OSError(22, f"os.open({path!r}) not supported on Windows")
            return _real_os.open(path, flags, *args, **kwargs)

        def __getattr__(self, item):
            return getattr(_real_os, item)

    monkeypatch.setattr(_dl, "os", _WindowsOsProxy())

    # Sanity: the proxy's parent-dir open raises, the rest of ``os`` is
    # real, and the proxy reports the Windows platform tag.
    with pytest.raises(OSError):
        _dl.os.open(parent_resolved, _real_os.O_RDONLY)
    assert _dl.os.name == "nt"

    # Counter-test: the same proxy, but with the parent-fsync branch
    # actually exercised (no short-circuit), *would* raise — proving the
    # proxy simulates the real Windows failure mode and not a no-op.
    with pytest.raises(OSError):
        with monkeypatch.context() as ctx:
            ctx.setattr(_dl.os, "name", "posix")
            _dl._fsync_parent_directory(tmp_path / "marker-parent" / "marker-child")

    # Run the install on a manager whose downloads module sees the
    # Windows proxy. The short-circuit in
    # ``_fsync_parent_directory`` returns early, so the install must
    # reach its ``installed`` state.
    manager = LocalAIManager(local_dir=tmp_path, port=0, cpu_threads=4)
    monkeypatch.setattr(manager, "_preflight_runtime", lambda *_args: None)
    monkeypatch.setattr(manager, "_verify_installed_runtime", lambda *_args, **_kwargs: None)
    manager._run_install_job(
        SimpleNamespace(
            job_id="install-windows-fsync",
            model_id="gemma-4-e2b",
            start_after_install=False,
            cancel_event=threading.Event(),
        )
    )
    assert manager.status().state == "installed"
    assert manager._binary_path is not None
    assert manager._binary_path.name == server_name
    assert manager._binary_path.is_file()


def _build_local_ai_dir(tmp_path: Path, *, model_id: str = "gemma-4-e2b") -> dict[str, Path]:
    """Lay out an isolated, root-contained Local AI directory under tmp_path."""
    local_dir = tmp_path / "local-ai"
    (local_dir / "models" / model_id).mkdir(parents=True, exist_ok=True)
    binary = local_dir / "llama-server"
    binary.parent.mkdir(parents=True, exist_ok=True)
    return {"local_dir": local_dir, "binary": binary}


def test_mutable_install_writes_final_files_and_reaches_installed_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = _build_local_ai_dir(tmp_path)
    from src.local_ai.catalog import MODELS

    spec = MODELS["gemma-4-e2b"]
    main_path = layout["local_dir"] / "models" / "gemma-4-e2b" / spec.model_filename
    draft_path = layout["local_dir"] / "models" / "gemma-4-e2b" / spec.draft_filename

    main_payload = _gguf(b"new-upstream-main-payload" * 31)  # ~713 bytes
    draft_payload = _gguf(b"new-upstream-draft-payload" * 19)  # ~418 bytes

    manager = LocalAIManager(local_dir=layout["local_dir"], port=0, cpu_threads=4)

    def fake_catalog_download(spec, *, progress_callback=None, cancel_event=None):
        spec.destination.parent.mkdir(parents=True, exist_ok=True)
        if spec.catalog_key == "model:gemma-4-e2b":
            spec.destination.write_bytes(main_payload)
        elif spec.catalog_key == "draft:gemma-4-e2b":
            spec.destination.write_bytes(draft_payload)
        else:  # pragma: no cover - defensive
            spec.destination.write_bytes(b"")
        if progress_callback is not None:
            try:
                expected = int(spec.expected_bytes) if spec.expected_bytes is not None else 0
            except (TypeError, ValueError):
                expected = 0
            progress_callback(0, expected)
        return spec.destination

    monkeypatch.setattr(manager_module, "download_catalog_artifact", fake_catalog_download)
    manager._binary_path = layout["binary"]
    manager._binary_path.write_bytes(b"runtime")
    monkeypatch.setattr(manager, "_resolve_binary_path", lambda: manager._binary_path)
    manager.set_install_completion_callback(lambda _model_id: None)
    monkeypatch.setattr(manager, "_verify_installed_runtime", lambda *_args, **_kwargs: None)

    manager._run_install_job(
        SimpleNamespace(
            job_id="install-mutable",
            model_id="gemma-4-e2b",
            start_after_install=False,
            cancel_event=threading.Event(),
        )
    )

    assert main_path.is_file() and not main_path.with_name(main_path.name + ".part").exists()
    assert draft_path.is_file() and not draft_path.with_name(draft_path.name + ".part").exists()
    assert main_path.stat().st_size == len(main_payload)
    assert draft_path.stat().st_size == len(draft_payload)
    assert manager._model_paths["gemma-4-e2b"] == main_path.resolve()
    assert manager._draft_paths["gemma-4-e2b"] == draft_path.resolve()
    assert manager.status().state == "installed"

    inventory = {entry["model_id"]: entry for entry in manager.inventory()}
    assert inventory["gemma-4-e2b"]["installed"] is True
    assert inventory["gemma-4-e2b"]["model_bytes"] == len(main_payload)
    assert inventory["gemma-4-e2b"]["draft_bytes"] == len(draft_payload)


def test_invalid_final_model_pair_is_replaced_by_a_same_attempt_redownload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = _build_local_ai_dir(tmp_path)
    spec = MODELS["gemma-4-e2b"]
    main = layout["local_dir"] / "models" / "gemma-4-e2b" / spec.model_filename
    draft = layout["local_dir"] / "models" / "gemma-4-e2b" / spec.draft_filename
    main.write_bytes(b"not-a-gguf")
    draft.write_bytes(_gguf(b"valid"))
    manager = LocalAIManager(local_dir=layout["local_dir"], port=0, cpu_threads=1)
    manager._binary_path = layout["binary"]
    manager._binary_path.write_bytes(b"runtime")
    monkeypatch.setattr(manager, "_verify_installed_runtime", lambda *_args, **_kwargs: None)
    downloaded: list[str] = []

    def redownload(spec, **_kwargs):
        downloaded.append(spec.catalog_key)
        spec.destination.write_bytes(_gguf(spec.catalog_key.encode()))

    monkeypatch.setattr(manager_module, "download_catalog_artifact", redownload)
    manager._run_install_job(
        SimpleNamespace(
            job_id="invalid",
            model_id="gemma-4-e2b",
            start_after_install=False,
            cancel_event=threading.Event(),
        )
    )
    assert downloaded == ["model:gemma-4-e2b", "draft:gemma-4-e2b"]
    assert main.read_bytes().startswith(b"GGUF")
    assert draft.read_bytes().startswith(b"GGUF")
    assert manager.status().state == "installed"


def test_manifest_records_observed_sizes_and_restores_on_fresh_manager(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = _build_local_ai_dir(tmp_path)
    from src.local_ai.catalog import MODELS

    spec = MODELS["gemma-4-e2b"]
    main_path = layout["local_dir"] / "models" / "gemma-4-e2b" / spec.model_filename
    draft_path = layout["local_dir"] / "models" / "gemma-4-e2b" / spec.draft_filename
    main_payload = _gguf(b"observed-main" * 23)
    draft_payload = _gguf(b"observed-draft" * 17)

    first = LocalAIManager(local_dir=layout["local_dir"], port=0, cpu_threads=4)
    first._binary_spec = BINARY_SPECS["macos-arm64-metal"]
    first._binary_path = layout["binary"]
    layout["binary"].write_bytes(b"runtime")
    first._model_paths["gemma-4-e2b"] = main_path
    first._draft_paths["gemma-4-e2b"] = draft_path
    main_path.write_bytes(main_payload)
    draft_path.write_bytes(draft_payload)
    first._write_manifest()

    manifest = json.loads((layout["local_dir"] / "manifest.json").read_text(encoding="utf-8"))
    # The manifest must record the observed final size, not a static catalog
    # digest, so a future restart trusts the on-disk artifact.
    assert manifest["models"]["gemma-4-e2b"]["main_model"]["bytes"] == len(main_payload)
    assert manifest["models"]["gemma-4-e2b"]["draft_model"]["bytes"] == len(draft_payload)
    # Current manifests contain observed final artifact metadata only.
    assert "sha256" not in manifest["models"]["gemma-4-e2b"]["main_model"]

    # Restoration trusts observed manifest metadata, not static catalogue sizes.
    second = LocalAIManager(local_dir=layout["local_dir"], port=0, cpu_threads=4)
    assert second._model_paths["gemma-4-e2b"] == main_path.resolve()
    assert second._draft_paths["gemma-4-e2b"] == draft_path.resolve()
    assert second.status().state == "installed"


def test_model_path_discovery_rejects_only_part_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = _build_local_ai_dir(tmp_path)
    from src.local_ai.catalog import MODELS

    spec = MODELS["gemma-4-e2b"]
    main_path = layout["local_dir"] / "models" / "gemma-4-e2b" / spec.model_filename
    draft_path = layout["local_dir"] / "models" / "gemma-4-e2b" / spec.draft_filename
    main_path.with_name(main_path.name + ".part").write_bytes(b"partial-main")
    draft_path.with_name(draft_path.name + ".part").write_bytes(b"partial-draft")

    manager = LocalAIManager(local_dir=layout["local_dir"], port=0, cpu_threads=4)
    with pytest.raises(LocalAIStateError, match="not installed"):
        manager._model_path("gemma-4-e2b", draft=False)
    with pytest.raises(LocalAIStateError, match="not installed"):
        manager._model_path("gemma-4-e2b", draft=True)
    assert "gemma-4-e2b" not in manager._model_paths
    assert "gemma-4-e2b" not in manager._draft_paths


def test_zero_byte_final_model_is_rejected_at_validate_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = _build_local_ai_dir(tmp_path)
    from src.local_ai.catalog import MODELS

    spec = MODELS["gemma-4-e2b"]
    main_path = layout["local_dir"] / "models" / "gemma-4-e2b" / spec.model_filename
    draft_path = layout["local_dir"] / "models" / "gemma-4-e2b" / spec.draft_filename
    main_path.parent.mkdir(parents=True, exist_ok=True)
    layout["binary"].write_bytes(b"runtime")
    main_path.write_bytes(b"")  # zero-byte main
    draft_path.write_bytes(_gguf(b"non-empty-draft"))

    manager = LocalAIManager(local_dir=layout["local_dir"], port=0, cpu_threads=4)
    with pytest.raises(LocalAIStateError, match="main model"):
        manager._validate_artifacts("gemma-4-e2b", layout["binary"], main_path, draft_path)

    main_path.write_bytes(_gguf(b"non-empty-main"))
    draft_path.write_bytes(b"")
    with pytest.raises(LocalAIStateError, match="draft model"):
        manager._validate_artifacts("gemma-4-e2b", layout["binary"], main_path, draft_path)


def test_transfer_only_progress_is_nonnegative_with_no_expected_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = _build_local_ai_dir(tmp_path)
    manager = LocalAIManager(local_dir=layout["local_dir"], port=0, cpu_threads=4)
    observed_progress: list[tuple[str | None, int, int]] = []
    observed_validation_phases: list[str | None] = []

    def fake_catalog_download(spec, *, progress_callback=None, cancel_event=None):
        spec.destination.parent.mkdir(parents=True, exist_ok=True)
        if spec.catalog_key == "model:gemma-4-e2b":
            spec.destination.write_bytes(_gguf(b"m" * 4096))
        elif spec.catalog_key == "draft:gemma-4-e2b":
            spec.destination.write_bytes(_gguf(b"d" * 2048))
        else:  # pragma: no cover
            spec.destination.write_bytes(b"")
        if progress_callback is not None:
            # Transfer-only spec has expected_bytes=None; progress must
            # still be safe (non-negative integers, never int(None)).
            progress_callback(0, 0)
            status = manager.status()
            observed_progress.append(
                (status.download_phase, status.downloaded_bytes, status.total_bytes)
            )
            progress_callback(1024, 0)
            status = manager.status()
            observed_progress.append(
                (status.download_phase, status.downloaded_bytes, status.total_bytes)
            )
        return spec.destination

    monkeypatch.setattr(manager_module, "download_catalog_artifact", fake_catalog_download)
    manager._binary_path = layout["binary"]
    manager._binary_path.write_bytes(b"runtime")
    monkeypatch.setattr(manager, "_resolve_binary_path", lambda: manager._binary_path)
    monkeypatch.setattr(manager, "_verify_installed_runtime", lambda *_args, **_kwargs: None)
    real_validate = manager._validated_model_file

    def capture_validation(*args, **kwargs):
        observed_validation_phases.append(manager.status().download_phase)
        return real_validate(*args, **kwargs)

    monkeypatch.setattr(manager, "_validated_model_file", capture_validation)
    manager.set_install_completion_callback(lambda _model_id: None)

    manager._run_install_job(
        SimpleNamespace(
            job_id="install-progress",
            model_id="gemma-4-e2b",
            start_after_install=False,
            cancel_event=threading.Event(),
        )
    )

    status = manager.status()
    assert status.state == "installed"
    assert isinstance(status.downloaded_bytes, int) and status.downloaded_bytes >= 0
    assert isinstance(status.total_bytes, int) and status.total_bytes >= 0
    assert observed_progress == [
        ("main_model", 0, 0),
        ("main_model", 1024, 0),
        ("mtp_drafter", 0, 0),
        ("mtp_drafter", 1024, 0),
    ]
    assert observed_validation_phases[:2] == ["finalizing", "finalizing"]


def test_runtime_update_job_is_cancellable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AQA_LOCAL_AI_DIR", str(tmp_path))
    manager = LocalAIManager(local_dir=tmp_path, port=0, cpu_threads=4)
    binary = select_binary(HardwareProfile(os="Darwin", arch="arm64", gpu="metal"))
    manager._binary_spec = binary
    manager._binary_path = tmp_path / "llama-server"
    manager._binary_path.write_bytes(b"old")

    monkeypatch.setattr(manager, "_process_is_running", lambda: False)
    monkeypatch.setattr(manager_module, "latest_binary_for_profile", lambda binary: binary)

    def blocking_download(*, progress_callback=None, cancel_event=None, **_kwargs):
        # Block until cancellation is requested.
        while not getattr(cancel_event, "is_set", lambda: False)():
            if progress_callback is not None:
                progress_callback(1, 100)
            time.sleep(0.01)
        raise manager_module.LocalAIStateError("cancelled")

    monkeypatch.setattr(manager_module, "download_verified", blocking_download)
    job_id = manager.update_runtime()
    manager.cancel_install(job_id)
    deadline = time.monotonic() + 2
    while manager._jobs and time.monotonic() < deadline:
        time.sleep(0.02)
    assert manager.status().state == "not_installed"


def test_validated_model_file_rejects_symlink_to_regular_file(
    tmp_path: Path,
) -> None:
    try:
        target = tmp_path / "external.gguf"
        target.write_bytes(b"some-content")
        link = tmp_path / "main.gguf"
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not supported on this platform")

    manager = LocalAIManager(local_dir=tmp_path, port=0, cpu_threads=4)
    with pytest.raises(LocalAIStateError, match="main model"):
        manager._validated_model_file(link, "main model")
    # Symlink must be rejected even when the gate is required (default).
    with pytest.raises(LocalAIStateError, match="draft model"):
        manager._validated_model_file(link, "draft model", require_root_containment=False)


def test_model_path_rejects_cached_path_outside_local_dir(
    tmp_path: Path,
) -> None:
    layout = _build_local_ai_dir(tmp_path)
    from src.local_ai.catalog import MODELS

    spec = MODELS["gemma-4-e2b"]
    main_path = layout["local_dir"] / "models" / "gemma-4-e2b" / spec.model_filename
    draft_path = layout["local_dir"] / "models" / "gemma-4-e2b" / spec.draft_filename
    main_path.parent.mkdir(parents=True, exist_ok=True)
    # Place the cached model artifact *outside* local_dir; root containment
    # must reject it just as it does during manifest load.  The on-disk
    # fallback discovery path is intentionally absent.
    external_main = tmp_path / "outside-main.gguf"
    external_main.write_bytes(b"external-main")
    external_draft = tmp_path / "outside-draft.gguf"
    external_draft.write_bytes(b"external-draft")

    manager = LocalAIManager(local_dir=layout["local_dir"], port=0, cpu_threads=4)
    manager._model_paths["gemma-4-e2b"] = external_main
    manager._draft_paths["gemma-4-e2b"] = external_draft

    with pytest.raises(LocalAIStateError, match="main model"):
        manager._model_path("gemma-4-e2b", draft=False)
    with pytest.raises(LocalAIStateError, match="draft model"):
        manager._model_path("gemma-4-e2b", draft=True)
    # The invalid cached entries must be dropped so future calls do not
    # keep re-validating the same rejected path; a second call must still
    # raise (no in-memory cache, no in-root on-disk artifact).
    with pytest.raises(LocalAIStateError, match="main model"):
        manager._model_path("gemma-4-e2b", draft=False)
    with pytest.raises(LocalAIStateError, match="draft model"):
        manager._model_path("gemma-4-e2b", draft=True)
    assert "gemma-4-e2b" not in manager._model_paths
    assert "gemma-4-e2b" not in manager._draft_paths
    # And a legitimate in-root on-disk artifact is still discoverable.
    main_path.write_bytes(_gguf(b"non-empty"))
    draft_path.write_bytes(_gguf(b"non-empty"))
    assert manager._model_path("gemma-4-e2b", draft=False) == main_path.resolve()
    assert manager._model_path("gemma-4-e2b", draft=True) == draft_path.resolve()


def test_inventory_reports_invalid_cached_entry_as_not_installed(
    tmp_path: Path,
) -> None:
    layout = _build_local_ai_dir(tmp_path)
    from src.local_ai.catalog import MODELS

    spec = MODELS["gemma-4-e2b"]
    main_path = layout["local_dir"] / "models" / "gemma-4-e2b" / spec.model_filename
    draft_path = layout["local_dir"] / "models" / "gemma-4-e2b" / spec.draft_filename
    main_path.parent.mkdir(parents=True, exist_ok=True)

    # Valid main + bare .part for the draft: the draft must not be treated
    # as installed, so the model is not installed and no byte sizes appear.
    main_path.write_bytes(b"installed-main")
    draft_path.with_name(draft_path.name + ".part").write_bytes(b"partial-draft")

    manager = LocalAIManager(local_dir=layout["local_dir"], port=0, cpu_threads=4)
    manager._model_paths["gemma-4-e2b"] = main_path
    manager._draft_paths["gemma-4-e2b"] = draft_path

    entry = next(item for item in manager.inventory() if item["model_id"] == "gemma-4-e2b")
    assert entry["installed"] is False
    assert entry["integrity"] == "unknown"
    assert entry["model_bytes"] is None
    assert entry["draft_bytes"] is None


def test_write_manifest_skips_invalid_cached_model_entry(
    tmp_path: Path,
) -> None:
    layout = _build_local_ai_dir(tmp_path)
    from src.local_ai.catalog import MODELS

    spec = MODELS["gemma-4-e2b"]
    main_path = layout["local_dir"] / "models" / "gemma-4-e2b" / spec.model_filename
    draft_path = layout["local_dir"] / "models" / "gemma-4-e2b" / spec.draft_filename
    main_path.parent.mkdir(parents=True, exist_ok=True)
    main_path.write_bytes(b"installed-main")
    draft_path.with_name(draft_path.name + ".part").write_bytes(b"partial-draft")

    manager = LocalAIManager(local_dir=layout["local_dir"], port=0, cpu_threads=4)
    manager._binary_spec = BINARY_SPECS["macos-arm64-metal"]
    manager._binary_path = layout["binary"]
    layout["binary"].write_bytes(b"runtime")
    manager._model_paths["gemma-4-e2b"] = main_path
    manager._draft_paths["gemma-4-e2b"] = draft_path

    manager._write_manifest()
    manifest = json.loads((layout["local_dir"] / "manifest.json").read_text(encoding="utf-8"))
    assert "gemma-4-e2b" not in manifest.get("models", {})


@pytest.mark.skipif(
    getattr(os, "symlink", None) is None,
    reason="platform does not support os.symlink",
)
def test_manifest_hydration_rejects_in_root_model_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = _build_local_ai_dir(tmp_path)
    from src.local_ai.catalog import MODELS

    spec = MODELS["gemma-4-e2b"]
    main_target = layout["local_dir"] / "staging" / "target-main.gguf"
    draft_target = layout["local_dir"] / "staging" / "target-draft.gguf"
    main_target.parent.mkdir(parents=True, exist_ok=True)
    main_target.write_bytes(b"in-root-main-payload")
    draft_target.write_bytes(b"in-root-draft-payload")

    # The "final" main path the manifest will reference is a symlink to
    # the in-root target.  The draft is a valid regular file so the only
    # thing under test is the symlink rejection.
    main_link = layout["local_dir"] / "models" / "gemma-4-e2b" / spec.model_filename
    draft_path = layout["local_dir"] / "models" / "gemma-4-e2b" / spec.draft_filename
    main_link.parent.mkdir(parents=True, exist_ok=True)
    draft_path.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(main_target, main_link)
    draft_path.write_bytes(b"installed-draft")

    # Hand-author a current manifest that records the symlink as the main model
    # path with observed byte fields to exercise strict validation.
    manifest_path = layout["local_dir"] / "manifest.json"
    manifest = {
        "version": 1,
        "models": {
            "gemma-4-e2b": {
                "main_model": {
                    "filename": spec.model_filename,
                    "path": str(main_link),
                    "bytes": main_target.stat().st_size,
                },
                "draft_model": {
                    "filename": spec.draft_filename,
                    "path": str(draft_path),
                    "bytes": draft_path.stat().st_size,
                },
            }
        },
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    manager = LocalAIManager(local_dir=layout["local_dir"], port=0, cpu_threads=4)

    # The mutable symlink must not be promoted into the model/draft
    # registries, and the inventory must report the model as not
    # installed. The draft can be present or absent; the contract requires
    # the symlink to be rejected outright.
    assert "gemma-4-e2b" not in manager._model_paths
    inventory = {entry["model_id"]: entry for entry in manager.inventory()}
    assert inventory["gemma-4-e2b"]["installed"] is False
    assert inventory["gemma-4-e2b"]["model_path"] is None
    assert inventory["gemma-4-e2b"]["model_bytes"] is None


def test_write_manifest_drops_invalid_zero_byte_final_files(
    tmp_path: Path,
) -> None:
    layout = _build_local_ai_dir(tmp_path)
    from src.local_ai.catalog import MODELS

    spec = MODELS["gemma-4-e2b"]
    main_path = layout["local_dir"] / "models" / "gemma-4-e2b" / spec.model_filename
    draft_path = layout["local_dir"] / "models" / "gemma-4-e2b" / spec.draft_filename
    main_path.parent.mkdir(parents=True, exist_ok=True)
    main_path.write_bytes(b"")
    draft_path.write_bytes(b"installed-draft")

    manager = LocalAIManager(local_dir=layout["local_dir"], port=0, cpu_threads=4)
    manager._binary_spec = BINARY_SPECS["macos-arm64-metal"]
    manager._binary_path = layout["binary"]
    layout["binary"].write_bytes(b"runtime")
    manager._model_paths["gemma-4-e2b"] = main_path
    manager._draft_paths["gemma-4-e2b"] = draft_path

    manager._write_manifest()
    manifest = json.loads((layout["local_dir"] / "manifest.json").read_text(encoding="utf-8"))
    assert "gemma-4-e2b" not in manifest.get("models", {})


def test_inventory_recovers_complete_final_model_pair_without_manifest(
    tmp_path: Path,
) -> None:
    from src.local_ai.catalog import MODELS

    spec = MODELS["gemma-4-e2b"]
    # Place files under tmp_path so the manager's resolved local_dir contains
    # them.  No manifest.json is written anywhere.
    model_dir = tmp_path / "models" / spec.id
    model_dir.mkdir(parents=True)
    main_payload = _gguf(b"main")
    draft_payload = _gguf(b"draft")
    (model_dir / spec.model_filename).write_bytes(main_payload)
    (model_dir / spec.draft_filename).write_bytes(draft_payload)
    assert not (tmp_path / "manifest.json").exists()

    manager = LocalAIManager(local_dir=tmp_path, port=0, cpu_threads=4)
    entry = next(row for row in manager.inventory() if row["model_id"] == spec.id)

    assert entry["installed"] is True
    assert entry["integrity"] == "verified"
    assert entry["model_bytes"] == len(main_payload)
    assert entry["draft_bytes"] == len(draft_payload)
    # Recovery must not write a manifest as a side effect of inventory.
    assert not (tmp_path / "manifest.json").exists()


def test_inventory_rejects_main_only_pair(
    tmp_path: Path,
) -> None:
    from src.local_ai.catalog import MODELS

    spec = MODELS["gemma-4-e2b"]
    model_dir = tmp_path / "models" / spec.id
    model_dir.mkdir(parents=True)
    # Main is present and final; draft is missing entirely.
    (model_dir / spec.model_filename).write_bytes(b"main")

    manager = LocalAIManager(local_dir=tmp_path, port=0, cpu_threads=4)
    entry = next(row for row in manager.inventory() if row["model_id"] == spec.id)

    assert entry["installed"] is False
    assert entry["integrity"] == "unknown"
    assert entry["model_bytes"] is None
    assert entry["draft_bytes"] is None
    # And no manifest was written as a side effect of inventory.
    assert not (tmp_path / "manifest.json").exists()


def test_default_startup_timeout_allows_slow_portable_hosts(tmp_path: Path) -> None:
    manager = LocalAIManager(local_dir=tmp_path, port=0, cpu_threads=1)
    assert manager._startup_timeout == 120.0


def test_model_validation_rejects_non_gguf_payload(tmp_path: Path) -> None:
    path = tmp_path / "broken.gguf"
    path.write_bytes(b"not-a-gguf-payload")
    manager = LocalAIManager(local_dir=tmp_path, port=0, cpu_threads=1)
    with pytest.raises(LocalAIStateError, match="main model"):
        manager._validated_model_file(path, "main model")


def test_manifest_runtime_rejects_an_incomplete_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = BINARY_SPECS["macos-arm64-metal"]
    executable = tmp_path / "llama-server"
    executable.write_bytes(b"runtime")
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "version": 1,
                "runtime": {
                    "profile": binary.profile,
                    "executable": str(executable),
                },
                "models": {},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(manager_module.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(manager_module.platform, "machine", lambda: "arm64")

    manager = LocalAIManager(local_dir=tmp_path, port=0, cpu_threads=1)
    assert manager._binary_path is None


def test_manifest_model_entries_require_current_artifact_fields(tmp_path: Path) -> None:
    spec = MODELS["gemma-4-e2b"]
    model_path = tmp_path / "models" / "gemma-4-e2b" / spec.model_filename
    draft_path = tmp_path / "models" / "gemma-4-e2b" / spec.draft_filename
    model_path.parent.mkdir(parents=True)
    model_path.write_bytes(_gguf(b"main"))
    draft_path.write_bytes(_gguf(b"draft"))
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "version": 1,
                "models": {
                    "gemma-4-e2b": {
                        "main_model": {"path": str(model_path)},
                        "draft_model": {"path": str(draft_path)},
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    manager = LocalAIManager(local_dir=tmp_path, port=0, cpu_threads=1)

    assert "gemma-4-e2b" not in manager._model_paths
    assert "gemma-4-e2b" not in manager._draft_paths
    assert manager._binary_spec is None


def test_nested_runtime_update_publishes_correct_executable_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old_binary = BINARY_SPECS["macos-arm64-metal"]
    old_path = tmp_path / "old" / "llama-server"
    old_path.parent.mkdir(parents=True)
    old_path.write_bytes(b"old-runtime")
    manager = LocalAIManager(
        local_dir=tmp_path,
        binary_path=old_path,
        binary_spec=old_binary,
        port=0,
        cpu_threads=1,
    )
    updated = replace(
        old_binary,
        release_tag="b10043",
        archive_filename="llama-b10043-bin-macos-arm64.tar.gz",
        archive_members=("llama-b10043/llama-server",),
    )
    archive = tmp_path / "runtime.tar.gz"
    archive.write_bytes(b"archive")
    canonical = tmp_path / "llama.cpp" / "b10043" / updated.platform / "extracted"
    monkeypatch.setattr(manager_module, "latest_binary_for_profile", lambda _value: updated)
    monkeypatch.setattr(
        manager_module,
        "binary_download_spec",
        lambda *_args, **_kwargs: SimpleNamespace(
            url="https://example.invalid/runtime",
            destination=archive,
            expected_sha256="a" * 64,
            expected_bytes=7,
        ),
    )
    monkeypatch.setattr(manager_module, "download_verified", lambda **_kwargs: archive)
    monkeypatch.setattr(manager_module, "binary_extract_path", lambda *_args, **_kwargs: canonical)

    def fake_extract(_archive, destination, **_kwargs):
        server = destination / "llama-b10043" / "llama-server"
        server.parent.mkdir(parents=True)
        server.write_bytes(b"new-runtime")
        return server

    monkeypatch.setattr(manager_module, "extract_verified_archive", fake_extract)
    monkeypatch.setattr(manager, "_preflight_runtime", lambda *_args: None)
    manager._run_update_runtime_job(
        SimpleNamespace(
            job_id="nested-update",
            cancel_event=threading.Event(),
        )
    )

    expected = (canonical / "llama-b10043" / "llama-server").resolve()
    assert manager._binary_path == expected
    assert expected.read_bytes() == b"new-runtime"
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["runtime"]["executable"] == str(expected)


def test_windows_cuda_runtime_update_stages_companion_before_switch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = BINARY_SPECS["windows-x86_64-cuda"]
    old_path = tmp_path / "old" / "llama-server.exe"
    old_path.parent.mkdir(parents=True)
    old_path.write_bytes(b"old")
    manager = LocalAIManager(
        local_dir=tmp_path,
        binary_path=old_path,
        binary_spec=binary,
        port=0,
        cpu_threads=1,
    )
    canonical = tmp_path / "llama.cpp" / binary.release_tag / binary.platform / "extracted"
    downloads: list[Path] = []
    companion_destinations: list[Path] = []
    monkeypatch.setattr(manager_module, "latest_binary_for_profile", lambda _value: binary)
    monkeypatch.setattr(manager_module, "binary_extract_path", lambda *_args, **_kwargs: canonical)

    def fake_download(*, destination, expected_bytes, progress_callback=None, **_kwargs):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"archive")
        downloads.append(destination)
        if progress_callback is not None:
            progress_callback(expected_bytes, expected_bytes)
        return destination

    def fake_extract(_archive, destination, **_kwargs):
        server = destination / "llama-server.exe"
        server.parent.mkdir(parents=True)
        server.write_bytes(b"new")
        return server

    def fake_install(
        _archive,
        destination,
        *,
        allowed_members,
        license_source,
        installed_license_filename,
        **_kwargs,
    ):
        companion_destinations.append(Path(destination))
        installed = []
        for member in allowed_members:
            target = Path(destination) / member
            target.write_bytes(b"dll")
            installed.append(target)
        (Path(destination) / installed_license_filename).write_bytes(
            Path(license_source).read_bytes()
        )
        return tuple(installed)

    monkeypatch.setattr(manager_module, "download_verified", fake_download)
    monkeypatch.setattr(manager_module, "extract_verified_archive", fake_extract)
    monkeypatch.setattr(manager_module, "install_verified_companion_archive", fake_install)
    monkeypatch.setattr(manager, "_preflight_runtime", lambda *_args: None)
    manager._run_update_runtime_job(
        SimpleNamespace(
            job_id="cuda-update",
            cancel_event=threading.Event(),
        )
    )

    assert len(downloads) == 2
    assert len(companion_destinations) == 1
    assert companion_destinations[0].name.startswith("extracted-update-")
    assert manager._binary_path == (canonical / "llama-server.exe").resolve()
    assert all((canonical / member).is_file() for member in binary.companions[0].archive_members)
    companion = binary.companions[0]
    assert (canonical / companion.installed_license_filename).read_bytes() == (
        manager_module.bundled_third_party_license_path(companion.license_filename).read_bytes()
    )


def test_cuda_runtime_missing_license_recovers_without_touching_models_or_unrelated_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog_binary = BINARY_SPECS["windows-x86_64-cuda"]
    catalog_companion = catalog_binary.companions[0]
    main_payload = b"synthetic runtime archive"
    companion_fixture = tmp_path / "companion-fixture.zip"
    with zipfile.ZipFile(companion_fixture, "w") as zipped:
        for member in catalog_companion.archive_members:
            zipped.writestr(member, f"fixture:{member}".encode())
    companion_payload = companion_fixture.read_bytes()
    companion = replace(
        catalog_companion,
        archive_bytes=len(companion_payload),
        archive_sha256=hashlib.sha256(companion_payload).hexdigest(),
    )
    binary = replace(
        catalog_binary,
        archive_bytes=len(main_payload),
        archive_sha256=hashlib.sha256(main_payload).hexdigest(),
        companions=(companion,),
    )
    extraction_root = manager_module.binary_extract_path(binary, root=tmp_path)
    server = extraction_root / binary.engine_name
    server.parent.mkdir(parents=True)
    server.write_bytes(b"otherwise-valid CUDA runtime")
    for member in companion.archive_members:
        (server.parent / Path(member).name).write_bytes(f"installed:{member}".encode())
    license_source = manager_module.bundled_third_party_license_path(companion.license_filename)
    installed_license = server.parent / companion.installed_license_filename
    installed_license.write_bytes(license_source.read_bytes())

    model = MODELS["gemma-4-e2b"]
    model_dir = tmp_path / "models" / model.id
    model_dir.mkdir(parents=True)
    main_model = model_dir / model.model_filename
    draft_model = model_dir / model.draft_filename
    main_model.write_bytes(_gguf(b"preserved-main"))
    draft_model.write_bytes(_gguf(b"preserved-draft"))
    unrelated = tmp_path / "keep-me.txt"
    unrelated.write_bytes(b"unrelated fixture")

    seed = LocalAIManager(
        local_dir=tmp_path,
        binary_path=server,
        binary_spec=binary,
        model_paths={model.id: main_model},
        draft_paths={model.id: draft_model},
        port=0,
        cpu_threads=1,
    )
    seed._write_manifest()
    manifest_before = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    installed_license.unlink()

    monkeypatch.setattr(
        LocalAIManager, "_runtime_matches_current_host", staticmethod(lambda _binary: True)
    )
    manager = LocalAIManager(local_dir=tmp_path, port=0, cpu_threads=1)

    assert manager.status().state == "not_installed"
    assert manager._binary_path is None
    assert {entry["model_id"]: entry["installed"] for entry in manager.inventory()}[
        model.id
    ] is True
    assert main_model.read_bytes() == _gguf(b"preserved-main")
    assert draft_model.read_bytes() == _gguf(b"preserved-draft")
    assert unrelated.read_bytes() == b"unrelated fixture"

    monkeypatch.setattr(manager, "_runtime_update_candidates", lambda _job: (binary,))

    def fake_download(*, destination, expected_sha256, expected_bytes, **_kwargs):
        payload = (
            companion_payload
            if Path(destination).name == companion.archive_filename
            else main_payload
        )
        assert len(payload) == expected_bytes
        assert hashlib.sha256(payload).hexdigest() == expected_sha256
        Path(destination).parent.mkdir(parents=True, exist_ok=True)
        Path(destination).write_bytes(payload)
        return Path(destination)

    def fake_extract(_archive, destination, **_kwargs):
        candidate = Path(destination) / binary.engine_name
        candidate.parent.mkdir(parents=True)
        candidate.write_bytes(b"repaired CUDA runtime")
        return candidate

    monkeypatch.setattr(manager_module, "download_verified", fake_download)
    monkeypatch.setattr(manager_module, "extract_verified_archive", fake_extract)
    monkeypatch.setattr(manager, "_preflight_runtime", lambda *_args: None)
    manager._run_update_runtime_job(
        SimpleNamespace(job_id="repair-missing-license", cancel_event=threading.Event())
    )

    repaired_server = manager_module.binary_extract_path(binary, root=tmp_path) / binary.engine_name
    repaired_license = repaired_server.parent / companion.installed_license_filename
    assert manager.status().state == "installed"
    assert manager._resolve_binary_path() == repaired_server.resolve()
    assert repaired_license.read_bytes() == license_source.read_bytes()
    assert manager._has_required_runtime_companions(binary, repaired_server.parent) is True
    assert manager._model_path(model.id, draft=False) == main_model.resolve()
    assert manager._model_path(model.id, draft=True) == draft_model.resolve()
    assert main_model.read_bytes() == _gguf(b"preserved-main")
    assert draft_model.read_bytes() == _gguf(b"preserved-draft")
    assert unrelated.read_bytes() == b"unrelated fixture"
    manifest_after = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest_after["models"] == manifest_before["models"]


@pytest.mark.parametrize(
    "outcome", ["success", "readiness_failure", "cancelled", "cancel_after_readiness"]
)
def test_runtime_update_validates_real_model_before_publication_and_rolls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    binary = BINARY_SPECS["linux-x86_64-vulkan"]
    old_path = tmp_path / "old" / "llama-server"
    old_path.parent.mkdir(parents=True)
    old_path.write_bytes(b"old")
    model = tmp_path / "models" / "gemma-4-e2b" / MODELS["gemma-4-e2b"].model_filename
    draft = tmp_path / "models" / "gemma-4-e2b" / MODELS["gemma-4-e2b"].draft_filename
    model.parent.mkdir(parents=True)
    model.write_bytes(_gguf(b"main"))
    draft.write_bytes(_gguf(b"draft"))
    manager = LocalAIManager(
        local_dir=tmp_path,
        binary_path=old_path,
        binary_spec=binary,
        model_paths={"gemma-4-e2b": model},
        draft_paths={"gemma-4-e2b": draft},
        port=0,
        cpu_threads=1,
    )
    manager._write_manifest()
    canonical = tmp_path / "runtime" / "extracted"
    archive = tmp_path / "runtime.tar.gz"
    monkeypatch.setattr(manager_module, "binary_extract_path", lambda *_a, **_k: canonical)
    monkeypatch.setattr(
        manager_module,
        "download_verified",
        lambda **_kwargs: archive.write_bytes(b"archive") or archive,
    )

    def fake_extract(_archive, destination, *, allowed_members, **_kwargs):
        server = destination / allowed_members[0]
        server.parent.mkdir(parents=True)
        server.write_bytes(b"candidate")
        return server

    monkeypatch.setattr(manager_module, "extract_verified_archive", fake_extract)
    job = SimpleNamespace(
        job_id="runtime-readiness",
        model_id="__runtime_update__",
        cancel_event=threading.Event(),
        cpu_fallback=False,
        readiness_model_id="gemma-4-e2b",
        context_tokens=65_536,
        mtp_enabled=True,
        mtp_draft_tokens=5,
    )

    def fake_preflight(_binary, _server):
        manager._runtime_probe = RuntimeProbe(
            "gpu_candidate", (RuntimeDevice("Vulkan0", "AMD Radeon"),)
        )
        manager._runtime_device = "Vulkan0"
        if outcome == "cancelled":
            job.cancel_event.set()

    monkeypatch.setattr(manager, "_preflight_runtime", fake_preflight)
    readiness_calls: list[tuple[str, int, bool, int]] = []

    def fake_readiness(readiness_job, model_id):
        readiness_calls.append(
            (
                model_id,
                readiness_job.context_tokens,
                readiness_job.mtp_enabled,
                readiness_job.mtp_draft_tokens,
            )
        )
        published = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
        assert published["runtime"]["executable"] == str(old_path)
        if outcome == "readiness_failure":
            raise LocalAIStateError("no offload", code="accelerator_failed")
        manager._runtime_offload_verified = True
        manager._runtime_offloaded_layers = 23
        if outcome == "cancel_after_readiness":
            job.cancel_event.set()

    monkeypatch.setattr(manager, "_verify_current_runtime_readiness", fake_readiness)

    if outcome == "success":
        manager._run_update_runtime_job(job)
        assert readiness_calls == [("gemma-4-e2b", 65_536, True, 5)]
        assert manager._binary_path == (canonical / binary.archive_members[0]).resolve()
        assert manager._runtime_offloaded_layers == 23
    else:
        with pytest.raises(LocalAIStateError):
            manager._run_update_runtime_job(job)
        assert manager._binary_path == old_path.resolve()
        assert json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))["runtime"][
            "executable"
        ] == str(old_path.resolve())
        if outcome == "cancelled":
            assert readiness_calls == []
        elif outcome == "cancel_after_readiness":
            assert readiness_calls == [("gemma-4-e2b", 65_536, True, 5)]


def test_windows_liveness_never_uses_os_kill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = LocalAIManager(local_dir=tmp_path, port=0, cpu_threads=1)
    monkeypatch.setattr(LocalAIManager, "_windows_host", staticmethod(lambda: True))
    monkeypatch.setattr(
        LocalAIManager,
        "_windows_process_details",
        classmethod(lambda _cls, _pid: ("C:\\llama-server.exe", 42)),
    )
    monkeypatch.setattr(
        manager_module.os, "kill", Mock(side_effect=AssertionError("must not signal"))
    )
    assert manager._pid_alive(1234) is True


def test_install_readiness_advances_candidate_without_changing_workload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gpu = BINARY_SPECS["linux-x86_64-vulkan"]
    cpu = BINARY_SPECS["linux-x86_64-cpu"]
    old_path = tmp_path / "old" / "llama-server"
    gpu_path = tmp_path / "vulkan" / "llama-server"
    cpu_path = tmp_path / "cpu" / "llama-server"
    for path in (old_path, gpu_path, cpu_path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"runtime")
    manager = LocalAIManager(
        local_dir=tmp_path,
        binary_path=gpu_path,
        binary_spec=gpu,
        port=0,
        cpu_threads=1,
    )
    manager._config = ("gemma-4-e2b", 32_768, False, 4)
    previous = (cpu, old_path, RuntimeProbe("cpu_only"), None, False, 0, True)
    starts: list[dict[str, object]] = []

    def fake_start(_model_id, **kwargs):
        starts.append(kwargs)
        if len(starts) == 1:
            raise LocalAIStateError("no offload", code="accelerator_failed")

    def fake_install(_job, candidates, *, preserve_installed):
        assert candidates == (cpu,)
        assert preserve_installed is True
        manager._binary_spec = cpu
        manager._binary_path = cpu_path
        return cpu

    stopped: list[bool] = []
    monkeypatch.setattr(manager, "start", fake_start)
    monkeypatch.setattr(manager, "_install_best_runtime", fake_install)
    monkeypatch.setattr(manager, "stop", lambda: stopped.append(True) or True)

    manager._verify_installed_runtime(
        SimpleNamespace(
            job_id="readiness-fallback",
            model_id="gemma-4-e2b",
            start_after_install=False,
            cancel_event=threading.Event(),
            context_tokens=65_536,
            mtp_enabled=True,
            mtp_draft_tokens=5,
        ),
        (gpu, cpu),
        previous_runtime=previous,
    )

    assert [attempt["context_tokens"] for attempt in starts] == [65_536, 65_536]
    assert [attempt["mtp_enabled"] for attempt in starts] == [True, True]
    assert [attempt["mtp_draft_tokens"] for attempt in starts] == [5, 5]
    assert [attempt["_persist_manifest"] for attempt in starts] == [False, False]
    assert manager._binary_spec == cpu
    assert manager._binary_path == cpu_path
    assert stopped == [True]


@pytest.mark.parametrize("selected_backend", ["sycl", "vulkan", "cpu"])
def test_intel_runtime_selection_records_bounded_fallback_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, selected_backend: str
) -> None:
    candidates = tuple(
        BINARY_SPECS[f"windows-x86_64-{backend}"] for backend in ("sycl", "vulkan", "cpu")
    )
    old_path = tmp_path / "old" / "llama-server.exe"
    old_path.parent.mkdir()
    old_path.write_bytes(b"cpu")
    manager = LocalAIManager(
        local_dir=tmp_path,
        binary_path=old_path,
        binary_spec=candidates[-1],
        port=0,
        cpu_threads=1,
    )
    previous = manager._runtime_state_snapshot()
    manager._begin_runtime_selection("model_install")
    monkeypatch.setattr(manager, "_download_install_artifact", lambda *_args: None)
    monkeypatch.setattr(manager, "_preflight_runtime", lambda *_args: RuntimeProbe("cpu_only"))
    monkeypatch.setattr(manager, "stop", lambda: True)

    def install(binary, _spec, _companions):
        if binary.accelerator != selected_backend and binary.accelerator != "cpu":
            raise LocalAIStateError(
                "synthetic probe rejection",
                code="accelerator_failed",
                selection_reason="no_gpu",
            )
        runtime_path = tmp_path / binary.profile / "llama-server.exe"
        runtime_path.parent.mkdir()
        runtime_path.write_bytes(b"runtime")
        manager._binary_spec = binary
        manager._binary_path = runtime_path

    monkeypatch.setattr(manager, "_install_downloaded_runtime", install)

    def start(_model_id, **_kwargs):
        if manager._binary_spec.accelerator != selected_backend:
            raise LocalAIStateError(
                "synthetic offload rejection",
                code="accelerator_failed",
                selection_reason="model_offload_failed",
            )

    monkeypatch.setattr(manager, "start", start)
    job = SimpleNamespace(
        job_id="synthetic-intel",
        model_id="gemma-4-e2b",
        start_after_install=False,
        cancel_event=threading.Event(),
        context_tokens=32_768,
        mtp_enabled=False,
        mtp_draft_tokens=4,
    )
    manager._install_best_runtime(job, candidates, preserve_installed=True)
    manager._verify_installed_runtime(job, candidates, previous_runtime=previous)

    record = json.loads((tmp_path / "runtime-selection.json").read_text(encoding="utf-8"))
    assert record["selected_profile"] == f"windows-x86_64-{selected_backend}"
    assert record["attempts"][-1]["result"] == "selected"
    assert all(
        set(entry) <= {"profile", "stage", "result", "reason"} for entry in record["attempts"]
    )
    assert len(record["attempts"]) <= 12


def test_runtime_selection_reader_bounds_file_and_rejects_symlink(tmp_path: Path) -> None:
    manager = LocalAIManager(local_dir=tmp_path, port=0)
    record_path = tmp_path / "runtime-selection.json"
    assert manager.read_runtime_selection_record() is None
    record_path.write_bytes(b"{" + b" " * 8191 + b"}")
    with pytest.raises(ValueError):
        manager.read_runtime_selection_record()
    record_path.write_bytes(b'{"version":1}')
    assert manager.read_runtime_selection_record() == b'{"version":1}'
    record_path.unlink()
    target = tmp_path / "synthetic-target.json"
    target.write_bytes(b"{}")
    record_path.symlink_to(target)
    with pytest.raises((OSError, ValueError)):
        manager.read_runtime_selection_record()


def test_existing_intel_cpu_runtime_is_reassessed_by_explicit_update(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = LocalAIManager(
        local_dir=tmp_path,
        binary_spec=BINARY_SPECS["windows-x86_64-cpu"],
        port=0,
        cpu_threads=1,
    )
    monkeypatch.setattr(
        manager_module,
        "detect_hardware_profile",
        lambda: HardwareProfile(os="Windows", arch="x86_64", gpu_label="Intel(R) Graphics"),
    )
    assert [
        binary.accelerator
        for binary in manager._runtime_update_candidates(SimpleNamespace(cpu_fallback=False))
    ] == ["sycl", "vulkan", "cpu"]


def test_install_readiness_restores_previous_runtime_when_candidates_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gpu = BINARY_SPECS["linux-x86_64-vulkan"]
    cpu = BINARY_SPECS["linux-x86_64-cpu"]
    old_path = tmp_path / "old" / "llama-server"
    gpu_path = tmp_path / "vulkan" / "llama-server"
    for path in (old_path, gpu_path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"runtime")
    manager = LocalAIManager(
        local_dir=tmp_path,
        binary_path=gpu_path,
        binary_spec=gpu,
        port=0,
        cpu_threads=1,
    )
    previous = (cpu, old_path, RuntimeProbe("cpu_only"), None, False, 0, True)
    monkeypatch.setattr(
        manager,
        "start",
        Mock(side_effect=LocalAIStateError("no offload", code="accelerator_failed")),
    )
    monkeypatch.setattr(manager_module, "binary_candidates", lambda _profile: ())

    with pytest.raises(LocalAIStateError) as raised:
        manager._verify_installed_runtime(
            SimpleNamespace(
                job_id="readiness-failed",
                model_id="gemma-4-e2b",
                start_after_install=False,
                cancel_event=threading.Event(),
            ),
            (gpu,),
            previous_runtime=previous,
        )

    assert raised.value.code == "accelerator_failed"
    assert manager._binary_spec == cpu
    assert manager._binary_path == old_path


def test_fresh_install_keeps_preflight_runtime_after_transient_readiness_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = BINARY_SPECS["linux-x86_64-cpu"]
    runtime = tmp_path / "runtime" / "llama-server"
    model = tmp_path / "models" / "gemma-4-e2b" / MODELS["gemma-4-e2b"].model_filename
    draft = tmp_path / "models" / "gemma-4-e2b" / MODELS["gemma-4-e2b"].draft_filename
    for path, payload in ((runtime, b"runtime"), (model, _gguf(b"main")), (draft, _gguf(b"draft"))):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    manager = LocalAIManager(
        local_dir=tmp_path,
        binary_path=runtime,
        binary_spec=binary,
        model_paths={"gemma-4-e2b": model},
        draft_paths={"gemma-4-e2b": draft},
        port=0,
        cpu_threads=1,
    )
    monkeypatch.setattr(
        manager,
        "start",
        Mock(side_effect=LocalAIStateError("loopback port is unavailable", code="port_conflict")),
    )

    with pytest.raises(LocalAIStateError) as raised:
        manager._verify_installed_runtime(
            SimpleNamespace(
                job_id="fresh-port-conflict",
                model_id="gemma-4-e2b",
                start_after_install=False,
                cancel_event=threading.Event(),
                context_tokens=32_768,
                mtp_enabled=False,
                mtp_draft_tokens=4,
            ),
            (binary,),
            previous_runtime=(None, None, RuntimeProbe("failed"), None, False, 0, False),
        )

    assert raised.value.code == "port_conflict"
    assert manager._binary_spec == binary
    assert manager._binary_path == runtime.resolve()
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["runtime"]["profile"] == binary.profile
    assert set(manifest["models"]) == {"gemma-4-e2b"}


def test_install_readiness_tries_each_enumerated_device_before_next_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gpu = BINARY_SPECS["linux-x86_64-cuda"]
    gpu_path = tmp_path / "cuda" / "llama-server"
    gpu_path.parent.mkdir(parents=True)
    gpu_path.write_bytes(b"runtime")
    manager = LocalAIManager(
        local_dir=tmp_path,
        binary_path=gpu_path,
        binary_spec=gpu,
        port=0,
        cpu_threads=1,
    )
    manager._runtime_probe = RuntimeProbe(
        "gpu_candidate",
        (
            RuntimeDevice("CUDA0", "Intel Integrated GPU"),
            RuntimeDevice("CUDA1", "NVIDIA RTX 5090"),
        ),
    )
    manager._runtime_device = "CUDA0"
    attempted_devices: list[str | None] = []

    def fake_start(_model_id, **_kwargs):
        attempted_devices.append(manager._runtime_device)
        if manager._runtime_device == "CUDA0":
            raise LocalAIStateError("no offload", code="accelerator_failed")

    monkeypatch.setattr(manager, "start", fake_start)
    monkeypatch.setattr(manager, "stop", lambda: True)
    install_next = Mock()
    monkeypatch.setattr(manager, "_install_best_runtime", install_next)

    manager._verify_installed_runtime(
        SimpleNamespace(
            job_id="multi-device",
            model_id="gemma-4-e2b",
            start_after_install=False,
            cancel_event=threading.Event(),
            context_tokens=32_768,
            mtp_enabled=False,
            mtp_draft_tokens=4,
        ),
        (gpu,),
        previous_runtime=(None, None, RuntimeProbe("failed"), None, False, 0, False),
    )

    assert attempted_devices == ["CUDA0", "CUDA1"]
    install_next.assert_not_called()


@pytest.mark.parametrize("failure", ["cancelled", "download", "model_validation"])
def test_model_install_reassessment_restores_runtime_before_readiness_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    old = BINARY_SPECS["linux-x86_64-cpu"]
    candidate = BINARY_SPECS["linux-x86_64-vulkan"]
    old_path = tmp_path / "old" / "llama-server"
    candidate_path = tmp_path / "vulkan" / "llama-server"
    for path in (old_path, candidate_path):
        path.parent.mkdir(parents=True)
        path.write_bytes(b"runtime")
    manager = LocalAIManager(
        local_dir=tmp_path,
        binary_path=old_path,
        binary_spec=old,
        port=0,
        cpu_threads=1,
    )
    manager._runtime_probe = RuntimeProbe("cpu_only")
    manager._cpu_fallback_confirmed = True
    monkeypatch.setattr(manager_module, "binary_candidates", lambda _profile: (candidate, old))

    def select_candidate(*_args, **_kwargs):
        manager._binary_spec = candidate
        manager._binary_path = candidate_path
        manager._runtime_probe = RuntimeProbe(
            "gpu_candidate", (RuntimeDevice("Vulkan0", "AMD Radeon"),)
        )
        return candidate

    monkeypatch.setattr(manager, "_install_best_runtime", select_candidate)
    job = SimpleNamespace(
        job_id="reassessment-failure",
        model_id="gemma-4-e2b",
        start_after_install=False,
        cancel_event=threading.Event(),
        context_tokens=32_768,
        mtp_enabled=False,
        mtp_draft_tokens=4,
    )

    def fail_after_reassessment(_job, _phase, spec, _runtime):
        if failure == "cancelled":
            job.cancel_event.set()
            spec.destination.parent.mkdir(parents=True, exist_ok=True)
            spec.destination.write_bytes(_gguf())
            return
        if failure == "download":
            raise OSError("network unavailable")
        spec.destination.parent.mkdir(parents=True, exist_ok=True)
        spec.destination.write_bytes(b"invalid")

    monkeypatch.setattr(manager, "_download_install_artifact", fail_after_reassessment)

    with pytest.raises((LocalAIStateError, OSError)):
        manager._run_install_job(job)

    assert manager._binary_spec == old
    assert manager._binary_path == old_path.resolve()
    assert manager.runtime_capability_state() == "cpu_confirmed"


def test_gpu_offload_wait_allows_delayed_log_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = LocalAIManager(local_dir=tmp_path, port=0, cpu_threads=1)
    observed = iter((0, 0, 17))
    monkeypatch.setattr(manager, "_observed_gpu_offload_layers", lambda: next(observed))
    monkeypatch.setattr(manager_module.time, "sleep", lambda _seconds: None)

    assert manager._wait_for_gpu_offload(SimpleNamespace(poll=lambda: None)) == 17


@pytest.mark.parametrize("start_after_install", [False, True])
def test_first_install_cancellation_after_readiness_start_never_publishes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    start_after_install: bool,
) -> None:
    cpu = BINARY_SPECS["linux-x86_64-cpu"]
    candidate_path = tmp_path / "runtime" / "llama-server"
    candidate_path.parent.mkdir(parents=True)
    candidate_path.write_bytes(b"runtime")
    manager = LocalAIManager(local_dir=tmp_path, port=0, cpu_threads=1)
    monkeypatch.setattr(manager_module, "binary_candidates", lambda _profile: (cpu,))

    def select_runtime(*_args, **_kwargs):
        manager._binary_spec = cpu
        manager._binary_path = candidate_path
        manager._runtime_probe = RuntimeProbe("cpu_only")
        return cpu

    monkeypatch.setattr(manager, "_install_best_runtime", select_runtime)

    def download_model(_job, _phase, spec, _runtime):
        spec.destination.parent.mkdir(parents=True, exist_ok=True)
        spec.destination.write_bytes(_gguf())

    monkeypatch.setattr(manager, "_download_install_artifact", download_model)
    job = SimpleNamespace(
        job_id="cancel-after-start",
        model_id="gemma-4-e2b",
        start_after_install=start_after_install,
        cancel_event=threading.Event(),
        context_tokens=32_768,
        mtp_enabled=False,
        mtp_draft_tokens=4,
    )
    candidate_process = FakeProcess()

    def start_then_cancel(*_args, **_kwargs):
        manager._process = candidate_process
        manager._start_in_flight = ("gemma-4-e2b", 32_768, False, 4)
        job.cancel_event.set()

    monkeypatch.setattr(manager, "start", start_then_cancel)
    completion = Mock()
    manager.set_install_completion_callback(completion)

    with pytest.raises(LocalAIStateError, match="cancelled"):
        manager._run_install_job(job)

    assert candidate_process.terminated is True
    assert manager._binary_spec is None
    assert manager._binary_path is None
    assert not (tmp_path / "manifest.json").exists()
    completion.assert_not_called()


def test_cpu_runtime_requires_exhaustive_fallback_evidence_for_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cpu = BINARY_SPECS["linux-x86_64-cpu"]
    path = tmp_path / "llama-server"
    path.write_bytes(b"runtime")
    manager = LocalAIManager(
        local_dir=tmp_path,
        binary_path=path,
        binary_spec=cpu,
        port=0,
        cpu_threads=1,
    )
    manager._runtime_probe = RuntimeProbe("cpu_only")

    assert manager.runtime_capability_state() == "unknown"

    gpu = BINARY_SPECS["linux-x86_64-vulkan"]
    monkeypatch.setattr(manager, "_download_install_artifact", lambda *_args: None)

    def install(binary, _spec, _companions):
        if binary.accelerator != "cpu":
            raise LocalAIStateError("backend rejected", code="accelerator_failed")
        manager._binary_spec = cpu
        manager._binary_path = path
        manager._runtime_probe = RuntimeProbe("cpu_only")

    monkeypatch.setattr(manager, "_install_downloaded_runtime", install)
    manager._install_best_runtime(
        SimpleNamespace(cancel_event=threading.Event()),
        (gpu, cpu),
        preserve_installed=False,
    )

    assert manager.runtime_capability_state() == "cpu_confirmed"


def test_apple_shared_archive_cpu_fallback_is_confirmed_after_exhaustion(
    tmp_path: Path,
) -> None:
    metal = BINARY_SPECS["macos-arm64-metal"]
    cpu_variant = replace(metal, accelerator="cpu", runtime=None)
    path = tmp_path / "llama-server"
    path.write_bytes(b"runtime")
    manager = LocalAIManager(
        local_dir=tmp_path,
        binary_path=path,
        binary_spec=cpu_variant,
        port=0,
        cpu_threads=1,
    )
    manager._runtime_probe = RuntimeProbe(
        "gpu_candidate", (RuntimeDevice("Metal", "Apple M2 GPU"),)
    )

    assert manager.runtime_capability_state() == "unknown"
    manager._cpu_fallback_confirmed = True
    assert manager.runtime_capability_state() == "cpu_confirmed"


def test_windows_crash_recovery_terminates_only_matching_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = str((tmp_path / "llama-server.exe").resolve())
    marker = {
        "parent_pid": 1,
        "child_pid": 1234,
        "executable": executable,
        "port": 8080,
        "process_creation_time": 99,
    }
    (tmp_path / "owner.json").write_text(json.dumps(marker), encoding="utf-8")
    manager = LocalAIManager(local_dir=tmp_path, port=0, cpu_threads=1)
    monkeypatch.setattr(LocalAIManager, "_windows_host", staticmethod(lambda: True))
    monkeypatch.setattr(
        LocalAIManager, "_windows_process_details", classmethod(lambda _cls, _pid: (executable, 99))
    )
    terminated: list[int] = []
    monkeypatch.setattr(
        manager,
        "_terminate_verified_windows_process",
        lambda pid, _executable, _created: terminated.append(pid),
    )
    manager._reconcile_owner_marker()
    assert terminated == [1234]
    assert not manager._owner_marker_path.exists()


def test_windows_reused_pid_is_never_terminated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = str((tmp_path / "llama-server.exe").resolve())
    (tmp_path / "owner.json").write_text(
        json.dumps(
            {
                "child_pid": 1234,
                "executable": executable,
                "port": 8080,
                "process_creation_time": 99,
            }
        ),
        encoding="utf-8",
    )
    manager = LocalAIManager(local_dir=tmp_path, port=0, cpu_threads=1)
    monkeypatch.setattr(LocalAIManager, "_windows_host", staticmethod(lambda: True))
    monkeypatch.setattr(
        LocalAIManager,
        "_windows_process_details",
        classmethod(lambda _cls, _pid: (executable, 100)),
    )
    terminate = Mock()
    monkeypatch.setattr(manager, "_terminate_verified_windows_process", terminate)
    with pytest.raises(LocalAIStateError, match="another process"):
        manager._reconcile_owner_marker()
    terminate.assert_not_called()


def test_posix_marker_matching_requires_exact_executable_and_port_arguments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = str((tmp_path / "llama-server").resolve())
    manager = LocalAIManager(local_dir=tmp_path, port=0, cpu_threads=1)
    monkeypatch.setattr(LocalAIManager, "_windows_host", staticmethod(lambda: False))
    (tmp_path / "owner.json").write_text(
        json.dumps({"process_start_token": "birth-1"}), encoding="utf-8"
    )
    monkeypatch.setattr(manager, "_posix_process_start_token", lambda _pid: "birth-1")
    monkeypatch.setattr(
        manager_module.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout=f"{executable} --host 127.0.0.1 --port 8080\n",
        ),
    )

    assert manager._pid_matches_marker(1234, executable, 8080) is True


@pytest.mark.parametrize(
    "command",
    [
        "{executable}-impostor --port 8080",
        "/usr/bin/python {executable} --port 8080",
        "{executable} --port 80800",
        "{executable} --other-port 8080",
    ],
)
def test_posix_marker_matching_rejects_substring_impersonation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    executable = str((tmp_path / "llama-server").resolve())
    manager = LocalAIManager(local_dir=tmp_path, port=0, cpu_threads=1)
    monkeypatch.setattr(LocalAIManager, "_windows_host", staticmethod(lambda: False))
    (tmp_path / "owner.json").write_text(
        json.dumps({"process_start_token": "birth-1"}), encoding="utf-8"
    )
    monkeypatch.setattr(manager, "_posix_process_start_token", lambda _pid: "birth-1")
    monkeypatch.setattr(
        manager_module.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout=command.format(executable=executable),
        ),
    )

    assert manager._pid_matches_marker(1234, executable, 8080) is False


def test_posix_reused_pid_with_same_command_is_rejected_by_start_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = str((tmp_path / "llama-server").resolve())
    manager = LocalAIManager(local_dir=tmp_path, port=0, cpu_threads=1)
    monkeypatch.setattr(LocalAIManager, "_windows_host", staticmethod(lambda: False))
    (tmp_path / "owner.json").write_text(
        json.dumps({"process_start_token": "original-birth"}), encoding="utf-8"
    )
    monkeypatch.setattr(manager, "_posix_process_start_token", lambda _pid: "reused-birth")
    process_lookup = Mock()
    monkeypatch.setattr(manager_module.subprocess, "run", process_lookup)

    assert manager._pid_matches_marker(1234, executable, 8080) is False
    process_lookup.assert_not_called()


def test_stale_owned_posix_process_escalates_only_after_a_bounded_wait(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = LocalAIManager(local_dir=tmp_path, port=0, cpu_threads=1)
    signals: list[int] = []
    liveness = iter([True, False])
    monkeypatch.setattr(manager, "_pid_alive", lambda _pid: next(liveness))
    monkeypatch.setattr(manager_module.os, "kill", lambda _pid, signal: signals.append(signal))
    monkeypatch.setattr(manager_module, "STALE_PROCESS_TERM_TIMEOUT", 0.0)
    monkeypatch.setattr(manager_module, "STALE_PROCESS_KILL_TIMEOUT", 0.0)

    manager._terminate_stale_posix_process(1234)

    assert signals == [signal.SIGTERM, signal.SIGKILL]
