"""Process-creation contracts for console-subsystem children of the GUI app."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import src.local_ai.folder_picker as folder_picker
import src.local_ai.manager as manager_module
import src.local_ai.platform as platform_module
from src.local_ai.catalog import BINARY_SPECS
from src.local_ai.manager import LocalAIManager
from src.local_ai.process_launch import hidden_console_flags


def test_windows_flags_hide_console_and_keep_local_ai_process_group() -> None:
    assert hidden_console_flags() == 0x08000000
    assert hidden_console_flags(process_group=True) == 0x08000200


def test_managed_local_ai_child_keeps_pipes_and_group_without_console(
    tmp_path: Path,
    monkeypatch,
) -> None:
    manager = LocalAIManager(local_dir=tmp_path, port=0, cpu_threads=1)
    popen = Mock(return_value=object())
    monkeypatch.setattr(manager_module, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(manager_module.subprocess, "Popen", popen)

    manager._spawn(["runtime.exe", "--port", "43123"])

    assert popen.call_args.args[0] == ["runtime.exe", "--port", "43123"]
    assert popen.call_args.kwargs["creationflags"] == hidden_console_flags(process_group=True)
    assert popen.call_args.kwargs["stdout"] == manager_module.subprocess.PIPE
    assert popen.call_args.kwargs["stderr"] == manager_module.subprocess.PIPE
    assert popen.call_args.kwargs["shell"] is False


def test_windows_runtime_probes_capture_diagnostics_without_console(
    tmp_path: Path,
    monkeypatch,
) -> None:
    binary = BINARY_SPECS["windows-x86_64-cpu"]
    server = tmp_path / binary.engine_name
    server.write_text("synthetic", encoding="utf-8")
    manager = LocalAIManager(local_dir=tmp_path, port=0, cpu_threads=1)
    help_output = " ".join(manager_module._REQUIRED_RUNTIME_FLAGS)
    run = Mock(
        side_effect=[
            SimpleNamespace(stdout=help_output, returncode=0),
            SimpleNamespace(stdout="Available devices:", returncode=0),
        ]
    )
    monkeypatch.setattr(
        manager_module,
        "os",
        SimpleNamespace(name="nt", lstat=os.lstat, access=os.access, X_OK=os.X_OK),
    )
    monkeypatch.setattr(manager_module.subprocess, "run", run)

    manager._preflight_runtime(binary, server)

    assert [call.kwargs["creationflags"] for call in run.call_args_list] == [
        hidden_console_flags(),
        hidden_console_flags(),
    ]
    assert all(
        call.kwargs["stdout"] == manager_module.subprocess.PIPE for call in run.call_args_list
    )


def test_windows_hardware_probe_hides_console_and_captures_output(monkeypatch) -> None:
    run = Mock(return_value=SimpleNamespace(stdout="GPU", stderr="", returncode=0))
    monkeypatch.setattr(platform_module, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(platform_module.shutil, "which", lambda _name: "probe.exe")
    monkeypatch.setattr(platform_module.subprocess, "run", run)

    assert platform_module._probe_command("probe") == "gpu\n"
    assert run.call_args.kwargs["creationflags"] == hidden_console_flags()
    assert run.call_args.kwargs["capture_output"] is True


def test_windows_folder_picker_hides_powershell_console(monkeypatch, tmp_path: Path) -> None:
    run = Mock(return_value=SimpleNamespace(stdout=str(tmp_path), returncode=0))
    monkeypatch.setattr(folder_picker.platform, "system", lambda: "Windows")
    monkeypatch.setattr(folder_picker.subprocess, "run", run)

    assert folder_picker.choose_directory() == tmp_path
    assert run.call_args.kwargs["creationflags"] == hidden_console_flags()
    assert run.call_args.kwargs["capture_output"] is True
