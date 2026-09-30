from __future__ import annotations

import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from src.api_server import app
from src.local_ai.manager import LocalAIManager, LocalAIStateError, LocalAIStatus
from src.service.discussion import AgentConfig
from src.service.routers.discussions import _managed_local_ai_preflight
from src.service.routers.local_ai import _get_local_ai_manager, _status_payload
from tests.router_test_support import override_context


@pytest.fixture
def managed_hosts() -> dict:
    return {
        "Lokale KI": {
            "url": "http://127.0.0.1:8080",
            "api_key": "",
            "model": "gemma-4-E2B-it",
            "models": ["gemma-4-E2B-it", "gemma-4-E4B-it", "gemma-4-12B-it"],
            "kind": "local_ai",
            "is_favorite": True,
        },
    }


@pytest.fixture
def agent_e2b() -> AgentConfig:
    return AgentConfig(
        name="A1",
        prompt_id="role-1",
        api_host="http://127.0.0.1:8080",
        llm_id="gemma-4-E2B-it",
    )


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def mock_context() -> MagicMock:
    context = MagicMock()
    context.settings.known_llm_hosts = {}
    return context


@pytest.fixture
def mock_local_ai_manager() -> MagicMock:
    manager = MagicMock()
    manager.status.return_value = LocalAIStatus()
    manager.read_runtime_selection_record.return_value = None
    return manager


def _install_manager(manager: MagicMock) -> None:
    app.state.local_ai_manager = manager


def _gguf(payload: bytes = b"fixture") -> bytes:
    return b"GGUF\x03\x00\x00\x00" + payload


def test_concurrent_first_requests_construct_one_app_owned_manager() -> None:
    shared_manager = MagicMock()
    constructions = 0
    constructions_lock = threading.Lock()

    def construct_manager() -> MagicMock:
        nonlocal constructions
        with constructions_lock:
            constructions += 1
        time.sleep(0.02)
        return shared_manager

    state = SimpleNamespace(local_ai_manager=None, local_ai_manager_lock=threading.Lock())
    request = SimpleNamespace(app=SimpleNamespace(state=state))
    context = MagicMock()
    with (
        patch("src.service.routers.local_ai.LocalAIManager", side_effect=construct_manager),
        ThreadPoolExecutor(max_workers=8) as executor,
    ):
        managers = list(
            executor.map(lambda _index: _get_local_ai_manager(request, context), range(8))
        )

    assert constructions == 1
    assert all(manager is shared_manager for manager in managers)


@pytest.mark.parametrize(
    "phase",
    ["preparing", "runtime", "main_model", "mtp_drafter", "finalizing"],
)
def test_status_payload_exposes_only_known_download_phases(phase: str) -> None:
    payload = _status_payload(
        LocalAIStatus(
            state="downloading",
            model_id="gemma-4-e2b",
            downloaded_bytes=12,
            total_bytes=34,
            available_disk_bytes=56,
            download_phase=phase,
        )
    )

    assert payload["download_phase"] == phase
    assert payload["download_bytes"] == 12
    assert payload["download_total"] == 34
    assert payload["available_disk_bytes"] == 56


def test_status_payload_preserves_running_identity_during_model_download() -> None:
    payload = _status_payload(
        LocalAIStatus(
            state="running",
            model_id="gemma-4-e2b",
            host="http://127.0.0.1:43123",
            port=43123,
            job_id="job-e4b",
            operation_kind="model_download",
            operation_state="downloading",
            operation_model_id="gemma-4-e4b",
            download_phase="main_model",
        )
    )

    assert payload["state"] == "running"
    assert payload["model_id"] == "gemma-4-e2b"
    assert payload["host_ready"] is True
    assert payload["operation_kind"] == "model_download"
    assert payload["operation_state"] == "downloading"
    assert payload["operation_model_id"] == "gemma-4-e4b"


def test_status_payload_exposes_import_operation_and_hides_runtime_sentinel() -> None:
    importing = _status_payload(
        LocalAIStatus(
            state="running",
            model_id="gemma-4-e2b",
            job_id="import-e4b",
            operation_kind="model_import",
            operation_state="importing",
            operation_model_id="gemma-4-e4b",
            import_bytes=12,
            import_total=34,
            import_phase="copying",
        )
    )
    runtime_update = _status_payload(
        LocalAIStatus(
            state="stopped",
            job_id="runtime-job",
            operation_kind="runtime_update",
            operation_state="downloading",
            operation_model_id="__runtime_update__",
        )
    )

    assert importing["operation_kind"] == "model_import"
    assert importing["operation_state"] == "importing"
    assert importing["operation_model_id"] == "gemma-4-e4b"
    assert importing["import_bytes"] == 12
    assert importing["import_total"] == 34
    assert importing["import_phase"] == "copying"
    assert runtime_update["operation_kind"] == "runtime_update"
    assert runtime_update["operation_model_id"] is None


def test_status_payload_drops_unknown_download_phase() -> None:
    payload = _status_payload(
        LocalAIStatus(state="downloading", model_id="gemma-4-e2b", download_phase="internal")
    )

    assert payload["download_phase"] is None


def test_import_endpoint_streams_and_publishes_complete_pair(
    client: TestClient, mock_context: MagicMock, tmp_path
) -> None:
    manager = LocalAIManager(local_dir=tmp_path, port=0, cpu_threads=1)
    _install_manager(manager)
    mock_context.settings.known_llm_hosts = {}
    with override_context(app, mock_context):
        started = client.post("/api/local-ai/models/gemma-4-e2b/import")
        assert started.status_code == 200
        import_id = started.json()["import_id"]
        assert (
            client.put(
                f"/api/local-ai/imports/{import_id}/main", content=_gguf(b"main")
            ).status_code
            == 200
        )
        assert (
            client.put(
                f"/api/local-ai/imports/{import_id}/draft", content=_gguf(b"draft")
            ).status_code
            == 200
        )
        finished = client.post("/api/local-ai/imports/finalize", json={"import_id": import_id})

    assert finished.status_code == 200, finished.text
    model = next(item for item in finished.json()["models"] if item["model_id"] == "gemma-4-e2b")
    assert model["installed"] is True
    assert model["import_files"] == {
        "main": "gemma-4-E2B-it-qat-UD-Q4_K_XL.gguf",
        "draft": "mtp-gemma-4-E2B-it.gguf",
    }


def test_portable_directory_import_starts_backend_job_from_native_picker(
    mock_context: MagicMock,
    mock_local_ai_manager: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    _install_manager(mock_local_ai_manager)
    mock_local_ai_manager.start_detected_background_import.return_value = (
        "job-123",
        "gemma-4-e2b",
    )
    monkeypatch.setenv("AQA_PACKAGED_MODE", "1")
    with TestClient(app) as loopback_client:
        with (
            override_context(app, mock_context),
            patch("src.service.routers.local_ai.choose_directory", return_value=tmp_path),
        ):
            response = loopback_client.post("/api/local-ai/models/import-from-directory", json={})

    assert response.status_code == 200, response.text
    assert response.json() == {"job_id": "job-123", "model_id": "gemma-4-e2b"}
    mock_local_ai_manager.start_detected_background_import.assert_called_once_with(str(tmp_path))


def test_portable_directory_import_reports_an_already_installed_model(
    mock_context: MagicMock,
    mock_local_ai_manager: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    _install_manager(mock_local_ai_manager)
    mock_local_ai_manager.start_detected_background_import.side_effect = LocalAIStateError(
        "model is already installed", code="model_already_installed"
    )
    monkeypatch.setenv("AQA_PACKAGED_MODE", "1")
    with TestClient(app) as loopback_client:
        with override_context(app, mock_context):
            response = loopback_client.post(
                "/api/local-ai/models/import-from-directory",
                json={"source_path": str(tmp_path)},
            )

    assert response.status_code == 422
    assert response.json()["error"] == {"code": "model_already_installed", "params": {}}


def test_reveal_models_directory_opens_only_the_managed_models_folder(
    client: TestClient, mock_context: MagicMock, tmp_path
) -> None:
    manager = LocalAIManager(local_dir=tmp_path, port=0, cpu_threads=1)
    _install_manager(manager)
    models_directory = tmp_path / "models"
    models_directory.mkdir()

    with (
        override_context(app, mock_context),
        patch("src.service.routers.local_ai.subprocess.run") as run_mock,
    ):
        response = client.post("/api/local-ai/models/reveal-directory")

    assert response.status_code == 200, response.text
    assert response.json() == {"status": "ok"}
    run_mock.assert_called_once()
    opener = (
        "open"
        if sys.platform == "darwin"
        else "explorer"
        if sys.platform == "win32"
        else "xdg-open"
    )
    assert run_mock.call_args.args[0] == [opener, str(models_directory.resolve())]
    assert str(models_directory) not in response.text


def test_install_rejects_unknown_catalog_model(
    client: TestClient, mock_local_ai_manager: MagicMock
) -> None:
    _install_manager(mock_local_ai_manager)
    response = client.post(
        "/api/local-ai/install",
        json={"model_id": "../../anything", "start_after_install": False},
    )
    assert response.status_code == 422
    mock_local_ai_manager.install.assert_not_called()


def test_start_registers_the_managed_loopback_host(
    client: TestClient, mock_context: MagicMock, mock_local_ai_manager: MagicMock
) -> None:
    _install_manager(mock_local_ai_manager)
    mock_context.settings.known_llm_hosts = {}
    mock_local_ai_manager.start.return_value = LocalAIStatus(
        state="running",
        model_id="gemma-4-e2b",
        model_name="gemma-4-E2B-it",
        host="http://127.0.0.1:8080",
        port=8080,
        context_tokens=131_072,
        accelerator="metal",
    )

    with override_context(app, mock_context):
        response = client.post(
            "/api/local-ai/start",
            json={"model_id": "gemma-4-e2b"},
        )

    assert response.status_code == 200, response.text
    hosts = mock_context.settings.known_llm_hosts
    assert "Lokale KI" in hosts
    entry = hosts["Lokale KI"]
    assert entry == {
        "url": "http://127.0.0.1:8080",
        "api_key": "",
        "model": "gemma-4-E2B-it",
        "models": ["gemma-4-E2B-it", "gemma-4-E4B-it", "gemma-4-12B-it"],
        "kind": "local_ai",
        "context_tokens": 131_072,
    }
    assert "api_key" not in response.json()
    mock_context.settings.save_user_settings.assert_called_once()


def test_start_registers_the_actual_fallback_loopback_port(
    client: TestClient, mock_context: MagicMock, mock_local_ai_manager: MagicMock
) -> None:
    _install_manager(mock_local_ai_manager)
    mock_context.settings.known_llm_hosts = {}
    mock_local_ai_manager.start.return_value = LocalAIStatus(
        state="running",
        model_id="gemma-4-e2b",
        model_name="gemma-4-E2B-it",
        host="http://127.0.0.1:43123",
        port=43123,
    )

    with override_context(app, mock_context):
        response = client.post("/api/local-ai/start", json={"model_id": "gemma-4-e2b"})

    assert response.status_code == 200, response.text
    assert mock_context.settings.known_llm_hosts["Lokale KI"]["url"] == ("http://127.0.0.1:43123")


def test_status_redacts_operational_paths_and_logs(
    client: TestClient, mock_context: MagicMock, mock_local_ai_manager: MagicMock
) -> None:
    _install_manager(mock_local_ai_manager)
    mock_local_ai_manager.status.return_value = LocalAIStatus(
        state="running", model_id="gemma-4-e2b", host="http://127.0.0.1:8080", message="ready"
    )

    mock_context.settings.known_llm_hosts = {
        "Lokale KI": {
            "url": "http://127.0.0.1:8080",
            "api_key": "",
            "model": "gemma-4-E4B-it",
            "models": ["gemma-4-E4B-it", "gemma-4-E2B-it", "gemma-4-12B-it"],
            "kind": "local_ai",
        },
    }
    with override_context(app, mock_context):
        payload = client.get("/api/local-ai/status").json()

    assert "binary_path" not in payload
    assert "command" not in payload
    assert "log" not in payload
    assert "runtime_directory" not in payload
    assert "model_directory" not in payload
    assert "command_reference" not in payload
    assert payload["host_ready"] is True
    assert payload["preferred_model_id"] == "gemma-4-e4b"
    # The safe rationale is always present, even on an active install.
    assert "runtime_selection" in payload
    assert payload["runtime_selection"]["runtime_profile"]


def _fake_detect(
    *,
    os: str = "Darwin",
    arch: str = "arm64",
    gpu: str = "metal",
    ram_gb: int | None = None,
    vram_gb: int | None = None,
    driver_runtime: str | None = "metal",
    driver_runtime_compatible: bool | None = True,
    cpu_name: str | None = None,
    logical_cpu_count: int | None = None,
) -> MagicMock:
    from src.local_ai.platform import HardwareProfile

    profile = HardwareProfile(
        os=os,
        arch=arch,
        gpu=gpu,
        ram_gb=ram_gb,
        vram_gb=vram_gb,
        driver_runtime=driver_runtime,
        driver_runtime_compatible=driver_runtime_compatible,
        cpu_name=cpu_name,
        logical_cpu_count=logical_cpu_count,
    )
    return MagicMock(return_value=profile)


def test_status_exposes_server_detected_hardware_labels(
    client: TestClient, mock_context: MagicMock, mock_local_ai_manager: MagicMock
) -> None:
    _install_manager(mock_local_ai_manager)
    mock_local_ai_manager.status.return_value = LocalAIStatus(state="stopped")
    mock_local_ai_manager.inventory.return_value = []

    with (
        override_context(app, mock_context),
        patch(
            "src.service.routers.local_ai.detect_hardware_profile",
            _fake_detect(ram_gb=16, cpu_name="Apple M2", logical_cpu_count=8),
        ),
        patch("src.service.routers.local_ai.select_binary") as select_mock,
    ):
        from src.local_ai.catalog import BINARY_SPECS

        select_mock.return_value = BINARY_SPECS["macos-arm64-metal"]
        payload = client.get("/api/local-ai/status").json()

    assert payload["os_label"] == "macOS (Apple Silicon)"
    assert payload["cpu_label"] == "Apple M2"
    assert payload["logical_cpu_count"] == 8
    assert payload["ram_gb"] == 16
    assert payload["inference_memory_gb"] == 16
    assert payload["inference_memory_kind"] == "unified"


@pytest.mark.parametrize(
    ("profile", "binary_profile"),
    [
        (_fake_detect(ram_gb=8).return_value, "macos-arm64-metal"),
        (_fake_detect(ram_gb=64).return_value, "macos-arm64-metal"),
        (
            _fake_detect(
                os="Windows",
                arch="AMD64",
                gpu="cuda",
                driver_runtime="cuda-12.4",
                ram_gb=64,
                vram_gb=24,
            ).return_value,
            "windows-x86_64-cuda",
        ),
    ],
)
def test_blank_install_keeps_factory_e2b_preference_across_hardware_tiers(
    profile: object,
    binary_profile: str,
    client: TestClient,
    mock_context: MagicMock,
    mock_local_ai_manager: MagicMock,
) -> None:
    from src.local_ai.catalog import BINARY_SPECS

    _install_manager(mock_local_ai_manager)
    mock_local_ai_manager.status.return_value = LocalAIStatus(state="not_installed")
    mock_local_ai_manager.inventory.return_value = []
    mock_context.settings.known_llm_hosts = {
        "Lokale KI": {
            "url": "http://127.0.0.1:8080",
            "api_key": "",
            "model": "gemma-4-E2B-it",
            "models": ["gemma-4-E2B-it", "gemma-4-E4B-it", "gemma-4-12B-it"],
            "kind": "local_ai",
        }
    }

    with (
        override_context(app, mock_context),
        patch("src.service.routers.local_ai.detect_hardware_profile", return_value=profile),
        patch(
            "src.service.routers.local_ai.select_binary",
            return_value=BINARY_SPECS[binary_profile],
        ),
    ):
        payload = client.get("/api/local-ai/status").json()

    assert payload["preferred_model_id"] == "gemma-4-e2b"
    assert payload["model_id"] is None
    assert payload["models"] == []
    assert "recommended_model" not in payload


def test_status_exposes_memory_used_by_the_selected_runtime(
    client: TestClient, mock_context: MagicMock, mock_local_ai_manager: MagicMock
) -> None:
    _install_manager(mock_local_ai_manager)
    mock_local_ai_manager.status.return_value = LocalAIStatus(state="stopped")
    mock_local_ai_manager.inventory.return_value = []

    with (
        override_context(app, mock_context),
        patch(
            "src.service.routers.local_ai.detect_hardware_profile",
            _fake_detect(
                os="Windows",
                arch="AMD64",
                gpu="cuda",
                driver_runtime="cuda-12.4",
                ram_gb=64,
                vram_gb=16,
            ),
        ),
        patch("src.service.routers.local_ai.select_binary") as select_mock,
    ):
        from src.local_ai.catalog import BINARY_SPECS

        select_mock.return_value = BINARY_SPECS["windows-x86_64-cuda"]
        payload = client.get("/api/local-ai/status").json()

    assert payload["ram_gb"] == 64
    assert payload["inference_memory_gb"] == 16
    assert payload["inference_memory_kind"] == "vram"
    assert "recommended_model" not in payload


def test_status_never_leaks_paths_commands_or_probe_output(
    client: TestClient, mock_context: MagicMock, mock_local_ai_manager: MagicMock
) -> None:
    _install_manager(mock_local_ai_manager)
    mock_local_ai_manager.status.return_value = LocalAIStatus(state="stopped")
    mock_local_ai_manager.inventory.return_value = [
        {
            "model_id": "gemma-4-e2b",
            "installed": True,
            "integrity": "verified",
            "model_path": "/private/local-ai/models/main.gguf",
            "draft_path": "/private/local-ai/models/draft.gguf",
        }
    ]

    with (
        override_context(app, mock_context),
        patch("src.service.routers.local_ai.detect_hardware_profile", _fake_detect()),
        patch("src.service.routers.local_ai.select_binary") as select_mock,
    ):
        from src.local_ai.catalog import BINARY_SPECS

        select_mock.return_value = BINARY_SPECS["macos-arm64-metal"]
        payload = client.get("/api/local-ai/status").json()

    forbidden = {
        "runtime_directory",
        "model_directory",
        "command_reference",
        "command",
        "binary_path",
        "log",
        "raw_probe",
    }
    leaked = forbidden & set(payload)
    assert not leaked, f"status payload leaked operational fields: {sorted(leaked)}"
    for inventory_entry in payload["models"]:
        assert inventory_entry["api_alias"] == "gemma-4-E2B-it"
        assert "model_path" not in inventory_entry
        assert "draft_path" not in inventory_entry
    # The only runtime fields that may appear are the safe rationale.
    rationale = payload["runtime_selection"]
    assert rationale["runtime_profile"] == "macos-arm64-metal"
    assert rationale["accelerator_label"] in {"Metal", "CUDA", "ROCm", "HIP", "Vulkan", "CPU"}
    assert rationale["engine_name"] in {"llama-server", "llama-server.exe"}
    assert rationale["decision_basis"] in {
        "detected compatible runtime",
        "safe CPU fallback",
    }
    assert "engine_path" not in rationale
    assert "url" not in rationale
    # No slashes/backslashes or command-like tokens in any string value.
    for value in rationale.values():
        if not isinstance(value, str):
            continue
        assert "/" not in value
        assert "\\" not in value
        assert "--" not in value


def test_diagnostics_returns_only_privacy_safe_attempt_evidence(
    client: TestClient,
    mock_context: MagicMock,
    mock_local_ai_manager: MagicMock,
    managed_hosts: dict,
) -> None:
    _install_manager(mock_local_ai_manager)
    mock_context.settings.known_llm_hosts = managed_hosts
    mock_context.settings.local_ai_context_tokens = 65_536
    mock_context.settings.local_ai_mtp_enabled = True
    mock_local_ai_manager.configured_command_reference.return_value = (
        "llama-server --model <managed-main-model> --model-draft "
        "<managed-mtp-draft> --ctx-size 65536 --host 127.0.0.1 --port 8080"
    )
    mock_local_ai_manager.runtime_details.return_value = {
        "error_code": "process_exited",
        "exit_code": 127,
        "log_tail": ["error while loading shared libraries", "/private/secret"],
        "runtime_directory": "/private/local-ai/llama.cpp",
        "command_reference": "llama-server --model /private/model.gguf",
    }

    with override_context(app, mock_context):
        payload = client.get("/api/local-ai/diagnostics").json()

    assert payload == {
        "command_reference": (
            "llama-server --model <managed-main-model> --model-draft "
            "<managed-mtp-draft> --ctx-size 65536 --host 127.0.0.1 --port 8080"
        ),
        "command_kind": "next_start",
        "error_code": "process_exited",
        "exit_code": 127,
        "log_tail": ["error while loading shared libraries"],
        "runtime_selection_diagnostics": {"state": "missing", "record": None},
    }
    mock_local_ai_manager.configured_command_reference.assert_called_once_with(
        "gemma-4-e2b", context_tokens=65_536, mtp_enabled=True
    )


@pytest.mark.parametrize(
    ("attempts", "selected"),
    [
        (
            [{"profile": "windows-x86_64-sycl", "stage": "runtime_update", "result": "selected"}],
            "windows-x86_64-sycl",
        ),
        (
            [
                {
                    "profile": "windows-x86_64-sycl",
                    "stage": "runtime_preflight",
                    "result": "rejected",
                    "reason": "no_gpu",
                },
                {"profile": "windows-x86_64-cpu", "stage": "model_readiness", "result": "selected"},
            ],
            "windows-x86_64-cpu",
        ),
        (
            [
                {
                    "profile": "windows-x86_64-sycl",
                    "stage": "runtime_preflight",
                    "result": "rejected",
                    "reason": "driver_unavailable",
                },
                {
                    "profile": "windows-x86_64-vulkan",
                    "stage": "runtime_preflight",
                    "result": "rejected",
                    "reason": "model_offload_failed",
                },
            ],
            None,
        ),
    ],
)
def test_selection_diagnostics_preserve_validated_attempt_order(
    client: TestClient,
    mock_context: MagicMock,
    mock_local_ai_manager: MagicMock,
    attempts: list[dict],
    selected: str | None,
) -> None:
    _install_manager(mock_local_ai_manager)
    record = {
        "version": 1,
        "operation": "runtime_update",
        "outcome": "selected" if selected else "incomplete",
        "attempts": attempts,
    }
    if selected:
        record["selected_profile"] = selected
    mock_local_ai_manager.read_runtime_selection_record.return_value = json.dumps(record).encode()
    with override_context(app, mock_context):
        result = client.get("/api/local-ai/diagnostics")
    assert result.status_code == 200
    diagnostics = result.json()["runtime_selection_diagnostics"]
    assert diagnostics["state"] == "available"
    assert [
        {key: value for key, value in entry.items() if value is not None}
        for entry in diagnostics["record"]["attempts"]
    ] == attempts
    assert diagnostics["record"]["selected_profile"] == selected


@pytest.mark.parametrize(
    "mutation",
    [
        {"private_path": "/private/secret"},
        {
            "attempts": [
                {"profile": "/private/secret", "stage": "device_probe", "result": "rejected"}
            ]
        },
        {
            "attempts": [
                {
                    "profile": "windows-x86_64-sycl",
                    "stage": "device_probe",
                    "result": "rejected",
                    "raw_log": "private",
                }
            ]
        },
    ],
)
def test_selection_diagnostics_reject_private_or_unknown_fields(
    client: TestClient,
    mock_context: MagicMock,
    mock_local_ai_manager: MagicMock,
    mutation: dict,
) -> None:
    _install_manager(mock_local_ai_manager)
    record = {
        "version": 1,
        "operation": "model_install",
        "outcome": "incomplete",
        "attempts": [],
    } | mutation
    mock_local_ai_manager.read_runtime_selection_record.return_value = json.dumps(record).encode()
    with override_context(app, mock_context):
        result = client.get("/api/local-ai/diagnostics")
    assert result.status_code == 200
    assert result.json()["runtime_selection_diagnostics"] == {"state": "invalid", "record": None}


@pytest.mark.parametrize("unreadable", [b"{broken", OSError("unreadable")])
def test_selection_diagnostics_contain_invalid_record(
    client: TestClient,
    mock_context: MagicMock,
    mock_local_ai_manager: MagicMock,
    unreadable: bytes | OSError,
) -> None:
    _install_manager(mock_local_ai_manager)
    if isinstance(unreadable, OSError):
        mock_local_ai_manager.read_runtime_selection_record.side_effect = unreadable
    else:
        mock_local_ai_manager.read_runtime_selection_record.return_value = unreadable
    with override_context(app, mock_context):
        result = client.get("/api/local-ai/diagnostics")
    assert result.json()["runtime_selection_diagnostics"] == {"state": "invalid", "record": None}


def test_diagnostics_does_not_substitute_a_stale_command_for_invalid_current_config(
    client: TestClient,
    mock_context: MagicMock,
    mock_local_ai_manager: MagicMock,
    managed_hosts: dict,
) -> None:
    _install_manager(mock_local_ai_manager)
    mock_context.settings.known_llm_hosts = managed_hosts
    mock_context.settings.local_ai_context_tokens = 32_768
    mock_context.settings.local_ai_mtp_enabled = False
    mock_local_ai_manager.status.return_value = LocalAIStatus(state="installed")
    mock_local_ai_manager.configured_command_reference.return_value = None
    mock_local_ai_manager.runtime_details.return_value = {
        "command_reference": "llama-server --model <managed-main-model> --ctx-size 8192",
        "error_code": None,
        "exit_code": None,
        "log_tail": [],
    }

    with override_context(app, mock_context):
        payload = client.get("/api/local-ai/diagnostics").json()

    assert payload["command_reference"] is None
    assert payload["command_kind"] is None


def test_diagnostics_labels_a_failed_attempt_command_when_no_preview_is_available(
    client: TestClient,
    mock_context: MagicMock,
    mock_local_ai_manager: MagicMock,
    managed_hosts: dict,
) -> None:
    _install_manager(mock_local_ai_manager)
    mock_context.settings.known_llm_hosts = managed_hosts
    mock_context.settings.local_ai_context_tokens = 32_768
    mock_context.settings.local_ai_mtp_enabled = False
    mock_local_ai_manager.status.return_value = LocalAIStatus(state="error")
    mock_local_ai_manager.configured_command_reference.return_value = None
    mock_local_ai_manager.runtime_details.return_value = {
        "command_reference": "llama-server --model <managed-main-model> --ctx-size 32768",
        "error_code": "process_exited",
        "exit_code": 1,
        "log_tail": [],
    }

    with override_context(app, mock_context):
        payload = client.get("/api/local-ai/diagnostics").json()

    assert payload["command_kind"] == "last_attempt"
    assert payload["command_reference"].endswith("--ctx-size 32768")


@pytest.mark.parametrize("state", ["running", "sleeping"])
def test_diagnostics_labels_a_live_process_command_as_active(
    state: str,
    client: TestClient,
    mock_context: MagicMock,
    mock_local_ai_manager: MagicMock,
    managed_hosts: dict,
) -> None:
    _install_manager(mock_local_ai_manager)
    mock_context.settings.known_llm_hosts = managed_hosts
    mock_context.settings.local_ai_context_tokens = 65_536
    mock_context.settings.local_ai_mtp_enabled = True
    mock_local_ai_manager.status.return_value = LocalAIStatus(state=state)
    mock_local_ai_manager.configured_command_reference.return_value = (
        "llama-server --model <managed-main-model> --ctx-size 32768"
    )
    mock_local_ai_manager.runtime_details.return_value = {}

    with override_context(app, mock_context):
        payload = client.get("/api/local-ai/diagnostics").json()

    assert payload["command_kind"] == "active"
    assert "--ctx-size 32768" in payload["command_reference"]


def test_status_reflects_installed_binary_when_present(
    client: TestClient, mock_context: MagicMock, mock_local_ai_manager: MagicMock
) -> None:
    _install_manager(mock_local_ai_manager)
    mock_local_ai_manager.status.return_value = LocalAIStatus(state="installed")

    with (
        override_context(app, mock_context),
        patch("src.service.routers.local_ai.detect_hardware_profile", _fake_detect()),
        patch("src.service.routers.local_ai.select_binary") as select_mock,
    ):
        from src.local_ai.catalog import BINARY_SPECS

        # The installed binary differs from the candidate.
        mock_local_ai_manager._binary_spec = BINARY_SPECS["macos-arm64-metal"]
        mock_local_ai_manager._binary_path = "/tmp/fake/llama-server"
        select_mock.return_value = BINARY_SPECS["windows-x86_64-cpu"]
        payload = client.get("/api/local-ai/status").json()

    assert payload["runtime_selection"]["runtime_profile"] == "macos-arm64-metal"
    assert payload["runtime_installed"] is True


def test_status_confirms_acceleration_only_after_gpu_offload_was_verified(
    client: TestClient, mock_context: MagicMock, mock_local_ai_manager: MagicMock
) -> None:
    from src.local_ai.catalog import BINARY_SPECS

    _install_manager(mock_local_ai_manager)
    mock_local_ai_manager.status.return_value = LocalAIStatus(state="stopped")
    mock_local_ai_manager.runtime_capability_state.return_value = "gpu_verified"
    mock_local_ai_manager._binary_spec = BINARY_SPECS["macos-arm64-metal"]
    mock_local_ai_manager._binary_path = "/tmp/fake/llama-server"

    with (
        override_context(app, mock_context),
        patch("src.service.routers.local_ai.detect_hardware_profile", _fake_detect()),
        patch(
            "src.service.routers.local_ai.select_binary",
            return_value=BINARY_SPECS["macos-arm64-metal"],
        ),
    ):
        selection = client.get("/api/local-ai/status").json()["runtime_selection"]

    assert selection["runtime_installed"] is True
    assert selection["acceleration_confirmed"] is True


def test_status_does_not_claim_acceleration_for_an_unverified_installed_gpu_runtime(
    client: TestClient, mock_context: MagicMock, mock_local_ai_manager: MagicMock
) -> None:
    from src.local_ai.catalog import BINARY_SPECS

    _install_manager(mock_local_ai_manager)
    mock_local_ai_manager.status.return_value = LocalAIStatus(state="installed")
    mock_local_ai_manager.runtime_capability_state.return_value = "unknown"
    mock_local_ai_manager._binary_spec = BINARY_SPECS["windows-x86_64-cuda"]
    mock_local_ai_manager._binary_path = "/tmp/fake/llama-server.exe"

    with (
        override_context(app, mock_context),
        patch(
            "src.service.routers.local_ai.detect_hardware_profile",
            _fake_detect(
                os="Windows",
                arch="AMD64",
                gpu="cuda",
                driver_runtime="cuda-12.4",
            ),
        ),
        patch(
            "src.service.routers.local_ai.select_binary",
            return_value=BINARY_SPECS["windows-x86_64-cuda"],
        ),
    ):
        selection = client.get("/api/local-ai/status").json()["runtime_selection"]

    assert selection["accelerator_label"] == "CUDA"
    assert selection["runtime_installed"] is True
    assert selection["acceleration_confirmed"] is False


def test_status_names_an_installed_cpu_backend_without_claiming_cpu_only_hardware(
    client: TestClient, mock_context: MagicMock, mock_local_ai_manager: MagicMock
) -> None:
    from src.local_ai.catalog import BINARY_SPECS

    _install_manager(mock_local_ai_manager)
    mock_local_ai_manager.status.return_value = LocalAIStatus(state="installed")
    mock_local_ai_manager._binary_spec = BINARY_SPECS["windows-x86_64-cpu"]
    mock_local_ai_manager._binary_path = "/tmp/fake/llama-server.exe"

    with (
        override_context(app, mock_context),
        patch(
            "src.service.routers.local_ai.detect_hardware_profile",
            _fake_detect(os="Windows", arch="x86_64", gpu="unknown"),
        ),
        patch(
            "src.service.routers.local_ai.select_binary",
            return_value=BINARY_SPECS["windows-x86_64-cpu"],
        ),
    ):
        selection = client.get("/api/local-ai/status").json()["runtime_selection"]

    assert selection["accelerator_label"] == "CPU"
    assert selection["decision_basis"] is None
    assert selection["acceleration_confirmed"] is False


def test_status_does_not_claim_acceleration_for_an_unknown_candidate_runtime(
    client: TestClient, mock_context: MagicMock, mock_local_ai_manager: MagicMock
) -> None:
    from src.local_ai.catalog import BINARY_SPECS

    _install_manager(mock_local_ai_manager)
    mock_local_ai_manager.status.return_value = LocalAIStatus(state="not_installed")
    mock_local_ai_manager.runtime_capability_state.return_value = "unknown"
    mock_local_ai_manager._binary_spec = None
    mock_local_ai_manager._binary_path = None

    with (
        override_context(app, mock_context),
        patch("src.service.routers.local_ai.detect_hardware_profile", _fake_detect()),
        patch(
            "src.service.routers.local_ai.select_binary",
            return_value=BINARY_SPECS["macos-arm64-metal"],
        ),
    ):
        selection = client.get("/api/local-ai/status").json()["runtime_selection"]

    assert selection["accelerator_label"] == "Metal"
    assert selection["runtime_installed"] is False
    assert selection["acceleration_confirmed"] is False


def test_recommendation_route_is_removed(client: TestClient) -> None:
    response = client.get("/api/local-ai/recommendation")

    assert response.status_code == 404
    assert "/api/local-ai/recommendation" not in app.openapi()["paths"]


def test_install_endpoint_accepts_the_12b_catalog_id(
    client: TestClient, mock_context: MagicMock, mock_local_ai_manager: MagicMock
) -> None:
    _install_manager(mock_local_ai_manager)
    mock_local_ai_manager.install.return_value = "job-12b"
    mock_context.settings.local_ai_context_tokens = 65_536
    mock_context.settings.local_ai_mtp_enabled = True

    with override_context(app, mock_context):
        response = client.post(
            "/api/local-ai/models/gemma-4-12b/install", json={"start_after_install": False}
        )

    assert response.status_code == 200, response.text
    assert response.json() == {"job_id": "job-12b"}
    mock_local_ai_manager.install.assert_called_once_with(
        "gemma-4-12b",
        start_after_install=False,
        context_tokens=65_536,
        mtp_enabled=True,
        mtp_draft_tokens=4,
    )


def test_runtime_update_uses_preferred_model_workload_settings(
    client: TestClient, mock_context: MagicMock, mock_local_ai_manager: MagicMock
) -> None:
    _install_manager(mock_local_ai_manager)
    mock_local_ai_manager.update_runtime.return_value = "runtime-job"
    mock_context.settings.known_llm_hosts = {
        "Lokale KI": {
            "url": "http://127.0.0.1:8080",
            "api_key": "",
            "model": "gemma-4-E4B-it",
            "models": ["gemma-4-E4B-it", "gemma-4-E2B-it", "gemma-4-12B-it"],
            "kind": "local_ai",
            "is_favorite": True,
        }
    }
    mock_context.settings.local_ai_context_tokens = 65_536
    mock_context.settings.local_ai_mtp_enabled = True

    with override_context(app, mock_context):
        response = client.post("/api/local-ai/runtime/update")

    assert response.status_code == 200, response.text
    assert response.json() == {"job_id": "runtime-job"}
    mock_local_ai_manager.update_runtime.assert_called_once_with(
        cpu_fallback=False,
        model_id="gemma-4-e4b",
        context_tokens=65_536,
        mtp_enabled=True,
        mtp_draft_tokens=4,
    )


def test_delete_active_model_returns_a_state_conflict(
    client: TestClient, mock_context: MagicMock, mock_local_ai_manager: MagicMock
) -> None:
    _install_manager(mock_local_ai_manager)
    mock_local_ai_manager.delete_model.side_effect = LocalAIStateError(
        "cannot delete the active model", code="state_conflict"
    )

    with override_context(app, mock_context):
        response = client.delete("/api/local-ai/models/gemma-4-e2b")

    assert response.status_code == 409
    assert response.json() == {
        "detail": "cannot delete the active model",
        "error": {"code": "state_conflict", "params": {}},
    }


def test_start_rejects_unknown_fields_and_validates_context_tokens(
    client: TestClient, mock_local_ai_manager: MagicMock
) -> None:
    _install_manager(mock_local_ai_manager)
    assert (
        client.post(
            "/api/local-ai/start",
            json={"model_id": "gemma-4-e2b", "unexpected": True},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/local-ai/start",
            json={"model_id": "gemma-4-e2b", "context_tokens": 8_191},
        ).status_code
        == 422
    )


def test_start_rejects_explicit_mtp_tuning_when_mtp_is_off(
    client: TestClient, mock_local_ai_manager: MagicMock
) -> None:
    _install_manager(mock_local_ai_manager)
    response = client.post(
        "/api/local-ai/start",
        json={"model_id": "gemma-4-e2b", "mtp_enabled": False, "mtp_draft_tokens": 2},
    )
    assert response.status_code == 422


def test_start_passes_mtp_values_through(
    client: TestClient, mock_local_ai_manager: MagicMock
) -> None:
    _install_manager(mock_local_ai_manager)
    mock_local_ai_manager.start.return_value = LocalAIStatus(
        state="running", model_id="gemma-4-e4b"
    )

    response = client.post(
        "/api/local-ai/start",
        json={
            "model_id": "gemma-4-e4b",
            "mtp_enabled": True,
            "mtp_draft_tokens": 4,
        },
    )

    assert response.status_code == 200
    mock_local_ai_manager.start.assert_called_once_with(
        "gemma-4-e4b", context_tokens=32_768, mtp_enabled=True, mtp_draft_tokens=4
    )


def test_start_passes_context_tokens_through(
    client: TestClient, mock_local_ai_manager: MagicMock
) -> None:
    _install_manager(mock_local_ai_manager)
    mock_local_ai_manager.start.return_value = LocalAIStatus(
        state="running", model_id="gemma-4-e4b", context_tokens=32_768
    )

    response = client.post(
        "/api/local-ai/start",
        json={"model_id": "gemma-4-e4b", "context_tokens": 32_768},
    )

    assert response.status_code == 200
    mock_local_ai_manager.start.assert_called_once_with(
        "gemma-4-e4b", context_tokens=32_768, mtp_enabled=False, mtp_draft_tokens=4
    )


def test_use_as_default_endpoint_is_removed(
    client: TestClient, mock_context: MagicMock, mock_local_ai_manager: MagicMock
) -> None:
    response = client.post("/api/local-ai/use-as-default")
    assert response.status_code == 404


def test_start_rejects_custom_lokale_ki_host(
    client: TestClient, mock_context: MagicMock, mock_local_ai_manager: MagicMock
) -> None:
    _install_manager(mock_local_ai_manager)
    mock_context.settings.known_llm_hosts = {
        "Lokale KI": {
            "url": "https://custom.example/v1",
            "api_key": "custom-secret",
            "model": "custom-model",
            "models": ["custom-model"],
        },
    }
    mock_local_ai_manager.start.return_value = LocalAIStatus(
        state="running",
        model_id="gemma-4-e2b",
        model_name="gemma-4-E2B-it",
        host="http://127.0.0.1:8080",
        port=8080,
    )

    with override_context(app, mock_context):
        response = client.post("/api/local-ai/start", json={"model_id": "gemma-4-e2b"})

    assert response.status_code == 409, response.text
    entry = mock_context.settings.known_llm_hosts["Lokale KI"]
    assert entry["url"] == "https://custom.example/v1"
    assert entry["api_key"] == "custom-secret"
    assert entry["model"] == "custom-model"
    mock_context.settings.save_user_settings.assert_not_called()


def test_lifespan_shuts_down_only_the_app_owned_manager(mock_local_ai_manager: MagicMock) -> None:
    _install_manager(mock_local_ai_manager)
    with TestClient(app):
        pass
    mock_local_ai_manager.shutdown.assert_called_once()


def test_put_preferred_model_reorders_models_and_preserves_invariants(
    client: TestClient, mock_context: MagicMock, mock_local_ai_manager: MagicMock
) -> None:
    _install_manager(mock_local_ai_manager)
    mock_context.settings.known_llm_hosts = {
        "Lokale KI": {
            "url": "http://127.0.0.1:8080",
            "api_key": "",
            "model": "gemma-4-E2B-it",
            "models": ["gemma-4-E2B-it", "gemma-4-E4B-it", "gemma-4-12B-it"],
            "kind": "local_ai",
            "is_favorite": True,
        },
    }
    mock_local_ai_manager.inventory.return_value = [
        {"model_id": "gemma-4-e2b", "installed": True},
        {"model_id": "gemma-4-e4b", "installed": True},
    ]

    with override_context(app, mock_context):
        response = client.put("/api/local-ai/preferred-model", json={"model_id": "gemma-4-e4b"})

    assert response.status_code == 200, response.text
    entry = mock_context.settings.known_llm_hosts["Lokale KI"]
    assert entry["model"] == "gemma-4-E4B-it"
    assert entry["models"] == ["gemma-4-E4B-it", "gemma-4-E2B-it", "gemma-4-12B-it"]
    assert entry["url"] == "http://127.0.0.1:8080"
    assert entry["api_key"] == ""
    assert entry["kind"] == "local_ai"
    assert "is_favorite" not in entry
    mock_context.settings.save_user_settings.assert_called_once()
    # The endpoint must never start/stop anything.
    mock_local_ai_manager.start.assert_not_called()
    mock_local_ai_manager.stop.assert_not_called()
    mock_local_ai_manager.shutdown.assert_not_called()
    assert response.json()["preferred_model_id"] == "gemma-4-e4b"


def test_put_preferred_model_rejects_an_uninstalled_model_without_mutation(
    client: TestClient, mock_context: MagicMock, mock_local_ai_manager: MagicMock
) -> None:
    _install_manager(mock_local_ai_manager)
    before = {
        "url": "http://127.0.0.1:8080",
        "api_key": "",
        "model": "gemma-4-E2B-it",
        "models": ["gemma-4-E2B-it", "gemma-4-E4B-it", "gemma-4-12B-it"],
        "kind": "local_ai",
    }
    mock_context.settings.known_llm_hosts = {"Lokale KI": dict(before)}
    mock_local_ai_manager.inventory.return_value = [
        {"model_id": "gemma-4-e2b", "installed": True},
        {"model_id": "gemma-4-e4b", "installed": False},
    ]

    with override_context(app, mock_context):
        response = client.put("/api/local-ai/preferred-model", json={"model_id": "gemma-4-e4b"})

    assert response.status_code == 409
    assert mock_context.settings.known_llm_hosts["Lokale KI"] == before
    mock_context.settings.save_user_settings.assert_not_called()


def test_completed_model_download_becomes_local_ai_preference(
    client: TestClient, mock_context: MagicMock, mock_local_ai_manager: MagicMock
) -> None:
    _install_manager(mock_local_ai_manager)
    mock_context.settings.known_llm_hosts = {
        "Lokale KI": {
            "url": "http://127.0.0.1:8080",
            "api_key": "",
            "model": "gemma-4-E2B-it",
            "models": ["gemma-4-E2B-it", "gemma-4-E4B-it", "gemma-4-12B-it"],
            "kind": "local_ai",
            "is_favorite": True,
        },
    }
    mock_local_ai_manager.inventory.return_value = [
        {"model_id": "gemma-4-e2b", "installed": False},
        {"model_id": "gemma-4-e4b", "installed": True},
    ]

    with override_context(app, mock_context):
        client.get("/api/local-ai/status")
        completed = mock_local_ai_manager.set_install_completion_callback.call_args.args[0]
        completed("gemma-4-e4b")

    entry = mock_context.settings.known_llm_hosts["Lokale KI"]
    assert entry["model"] == "gemma-4-E4B-it"
    assert entry["models"] == ["gemma-4-E4B-it", "gemma-4-E2B-it", "gemma-4-12B-it"]
    mock_context.settings.save_user_settings.assert_called_once()


def test_automatic_start_after_install_registers_actual_managed_host(
    client: TestClient, mock_context: MagicMock, mock_local_ai_manager: MagicMock
) -> None:
    _install_manager(mock_local_ai_manager)
    mock_context.settings.known_llm_hosts = {}
    mock_local_ai_manager.status.return_value = LocalAIStatus(
        state="running",
        model_id="gemma-4-e2b",
        model_name="gemma-4-E2B-it",
        host="http://127.0.0.1:43123",
        port=43123,
        context_tokens=32_768,
    )

    with override_context(app, mock_context):
        client.get("/api/local-ai/status")
        completed = mock_local_ai_manager.set_auto_start_completion_callback.call_args.args[0]
        completed(mock_local_ai_manager.status.return_value)

    assert mock_context.settings.known_llm_hosts["Lokale KI"]["url"] == ("http://127.0.0.1:43123")
    mock_context.llm_manager.invalidate_model_list.assert_called_once_with("http://127.0.0.1:43123")


def test_local_ai_dependency_wires_managed_request_activity(
    client: TestClient, mock_context: MagicMock, mock_local_ai_manager: MagicMock
) -> None:
    _install_manager(mock_local_ai_manager)

    with override_context(app, mock_context):
        client.get("/api/local-ai/status")

    mock_context.llm_manager.set_managed_local_ai_request_callbacks.assert_called_once_with(
        mock_local_ai_manager.mark_request_active,
        mock_local_ai_manager.mark_request_idle,
    )


def test_later_model_download_preserves_the_deliberate_local_ai_preference(
    client: TestClient, mock_context: MagicMock, mock_local_ai_manager: MagicMock
) -> None:
    _install_manager(mock_local_ai_manager)
    mock_context.settings.known_llm_hosts = {
        "Lokale KI": {
            "url": "http://127.0.0.1:8080",
            "api_key": "",
            "model": "gemma-4-E2B-it",
            "models": ["gemma-4-E2B-it", "gemma-4-E4B-it", "gemma-4-12B-it"],
            "kind": "local_ai",
            "is_favorite": True,
        },
    }
    mock_local_ai_manager.inventory.return_value = [
        {"model_id": "gemma-4-e2b", "installed": True},
        {"model_id": "gemma-4-e4b", "installed": True},
    ]

    with override_context(app, mock_context):
        client.get("/api/local-ai/status")
        completed = mock_local_ai_manager.set_install_completion_callback.call_args.args[0]
        completed("gemma-4-e4b")

    entry = mock_context.settings.known_llm_hosts["Lokale KI"]
    assert entry["model"] == "gemma-4-E2B-it"
    assert entry["models"] == ["gemma-4-E2B-it", "gemma-4-E4B-it", "gemma-4-12B-it"]
    assert entry["is_favorite"] is True
    mock_context.settings.save_user_settings.assert_not_called()


def test_put_preferred_model_rejects_invalid_catalog_id(
    client: TestClient, mock_context: MagicMock, mock_local_ai_manager: MagicMock
) -> None:
    _install_manager(mock_local_ai_manager)
    with override_context(app, mock_context):
        response = client.put("/api/local-ai/preferred-model", json={"model_id": "gemma-4-e8b"})
    assert response.status_code == 422


def test_put_preferred_model_rejects_custom_lokale_ki_host(
    client: TestClient, mock_context: MagicMock, mock_local_ai_manager: MagicMock
) -> None:
    _install_manager(mock_local_ai_manager)
    mock_context.settings.known_llm_hosts = {
        "Lokale KI": {
            "url": "https://custom.example/v1",
            "api_key": "custom-secret",
            "model": "custom-model",
            "models": ["custom-model"],
        },
    }

    with override_context(app, mock_context):
        response = client.put("/api/local-ai/preferred-model", json={"model_id": "gemma-4-e4b"})

    assert response.status_code == 409, response.text
    mock_context.settings.save_user_settings.assert_not_called()


def test_put_preferred_model_refuses_when_managed_host_is_missing(
    client: TestClient, mock_context: MagicMock, mock_local_ai_manager: MagicMock
) -> None:
    _install_manager(mock_local_ai_manager)
    mock_context.settings.known_llm_hosts = {}

    with override_context(app, mock_context):
        response = client.put("/api/local-ai/preferred-model", json={"model_id": "gemma-4-e2b"})

    assert response.status_code == 409, response.text
    assert mock_context.settings.known_llm_hosts == {}
    mock_context.settings.save_user_settings.assert_not_called()


# Managed Local AI preflight — /api/discussions/start contract
def _preflight_context(managed_hosts, mock_local_ai_manager):
    """Build a context-like object that exposes ``settings.known_llm_hosts``."""
    context = MagicMock()
    context.settings.known_llm_hosts = managed_hosts
    return context


def test_preflight_rejects_uninstalled_model_with_download_guidance(
    mock_context: MagicMock,
    mock_local_ai_manager: MagicMock,
    managed_hosts: dict,
    agent_e2b: AgentConfig,
) -> None:
    _install_manager(mock_local_ai_manager)
    mock_context.settings.known_llm_hosts = managed_hosts
    mock_local_ai_manager.inventory.return_value = [
        {"model_id": "gemma-4-e2b", "installed": False},
        {"model_id": "gemma-4-e4b", "installed": False},
    ]
    mock_local_ai_manager.status.return_value = LocalAIStatus(state="installed")

    context = _preflight_context(managed_hosts, mock_local_ai_manager)
    with pytest.raises(HTTPException) as excinfo:
        _managed_local_ai_preflight(context, [agent_e2b], mock_local_ai_manager)

    assert excinfo.value.status_code == 409
    assert excinfo.value.detail == (
        "Öffne Integrierte KI und lade zuerst eine Gemma-Variante herunter."
    )


def test_preflight_rejects_installed_but_stopped_model_with_start_guidance(
    mock_context: MagicMock,
    mock_local_ai_manager: MagicMock,
    managed_hosts: dict,
    agent_e2b: AgentConfig,
) -> None:
    _install_manager(mock_local_ai_manager)
    mock_context.settings.known_llm_hosts = managed_hosts
    mock_local_ai_manager.inventory.return_value = [
        {"model_id": "gemma-4-e2b", "installed": True},
        {"model_id": "gemma-4-e4b", "installed": True},
    ]
    mock_local_ai_manager.status.return_value = LocalAIStatus(
        state="installed",  # installed but not running/sleeping
        model_id="gemma-4-e2b",
    )

    context = _preflight_context(managed_hosts, mock_local_ai_manager)
    with pytest.raises(HTTPException) as excinfo:
        _managed_local_ai_preflight(context, [agent_e2b], mock_local_ai_manager)

    assert excinfo.value.status_code == 409
    assert excinfo.value.detail == (
        "Öffne Integrierte KI und starte zuerst das ausgewählte Modell."
    )


def test_preflight_rejects_different_running_model_with_switch_guidance(
    mock_context: MagicMock,
    mock_local_ai_manager: MagicMock,
    managed_hosts: dict,
    agent_e2b: AgentConfig,
) -> None:
    _install_manager(mock_local_ai_manager)
    mock_context.settings.known_llm_hosts = managed_hosts
    mock_local_ai_manager.inventory.return_value = [
        {"model_id": "gemma-4-e2b", "installed": True},
        {"model_id": "gemma-4-e4b", "installed": True},
    ]
    mock_local_ai_manager.status.return_value = LocalAIStatus(
        state="running",
        model_id="gemma-4-e4b",  # different from the agent's request
        model_name="gemma-4-E4B-it",
        host="http://127.0.0.1:8080",
        port=8080,
    )

    context = _preflight_context(managed_hosts, mock_local_ai_manager)
    with pytest.raises(HTTPException) as excinfo:
        _managed_local_ai_preflight(context, [agent_e2b], mock_local_ai_manager)

    assert excinfo.value.status_code == 409
    assert excinfo.value.detail == (
        "Das ausgewählte Modell läuft nicht. Wähle es unter Integrierte KI aus und starte es."
    )


def test_preflight_passes_when_correct_gemma_e2b_is_running(
    mock_context: MagicMock,
    mock_local_ai_manager: MagicMock,
    managed_hosts: dict,
    agent_e2b: AgentConfig,
) -> None:
    _install_manager(mock_local_ai_manager)
    mock_context.settings.known_llm_hosts = managed_hosts
    mock_local_ai_manager.inventory.return_value = [
        {"model_id": "gemma-4-e2b", "installed": True},
        {"model_id": "gemma-4-e4b", "installed": True},
    ]
    mock_local_ai_manager.status.return_value = LocalAIStatus(
        state="running",
        model_id="gemma-4-e2b",
        model_name="gemma-4-E2B-it",
        host="http://127.0.0.1:8080",
        port=8080,
    )

    context = _preflight_context(managed_hosts, mock_local_ai_manager)
    # No exception means the preflight passed.
    _managed_local_ai_preflight(context, [agent_e2b], mock_local_ai_manager)
    # The preflight must consult the manager's inventory and status.
    mock_local_ai_manager.inventory.assert_called()
    mock_local_ai_manager.status.assert_called()


def test_preflight_rejects_stale_managed_host_context(
    mock_local_ai_manager: MagicMock,
    managed_hosts: dict,
    agent_e2b: AgentConfig,
) -> None:
    managed_hosts["Lokale KI"]["context_tokens"] = 32_768
    mock_local_ai_manager.inventory.return_value = [{"model_id": "gemma-4-e2b", "installed": True}]
    mock_local_ai_manager.status.return_value = LocalAIStatus(
        state="running",
        model_id="gemma-4-e2b",
        context_tokens=8_192,
    )
    with pytest.raises(HTTPException) as excinfo:
        _managed_local_ai_preflight(
            _preflight_context(managed_hosts, mock_local_ai_manager),
            [agent_e2b],
            mock_local_ai_manager,
        )
    assert excinfo.value.status_code == 409
    assert excinfo.value.detail.startswith("Der laufende KI-Dienst")


@pytest.mark.parametrize("unsupported_model", ["gemma-4-e2b", "Gemma 4 E2B"])
def test_preflight_rejects_non_provider_model_names(
    mock_context: MagicMock,
    mock_local_ai_manager: MagicMock,
    managed_hosts: dict,
    unsupported_model: str,
) -> None:
    _install_manager(mock_local_ai_manager)
    mock_context.settings.known_llm_hosts = managed_hosts
    mock_local_ai_manager.inventory.return_value = []
    mock_local_ai_manager.status.return_value = LocalAIStatus(state="installed")
    agent = AgentConfig(
        name="A1",
        prompt_id="role-1",
        api_host="http://127.0.0.1:8080",
        llm_id=unsupported_model,
    )

    with pytest.raises(HTTPException) as excinfo:
        _managed_local_ai_preflight(
            _preflight_context(managed_hosts, mock_local_ai_manager),
            [agent],
            mock_local_ai_manager,
        )

    assert excinfo.value.status_code == 422
    assert excinfo.value.detail == "Das ausgewählte Modell ist für Integrierte KI nicht gültig."


def test_preflight_ignores_inactive_e2b_rows_when_active_e4b_is_running(
    mock_context: MagicMock,
    mock_local_ai_manager: MagicMock,
    managed_hosts: dict,
) -> None:
    _install_manager(mock_local_ai_manager)
    mock_context.settings.known_llm_hosts = managed_hosts
    mock_local_ai_manager.inventory.return_value = [
        {"model_id": "gemma-4-e2b", "installed": True},
        {"model_id": "gemma-4-e4b", "installed": True},
    ]
    mock_local_ai_manager.status.return_value = LocalAIStatus(
        state="running",
        model_id="gemma-4-e4b",
        model_name="gemma-4-E4B-it",
        host="http://127.0.0.1:8080",
        port=8080,
    )
    agents = [
        AgentConfig(
            name="Active E4B",
            prompt_id="role-1",
            api_host="http://127.0.0.1:8080",
            llm_id="gemma-4-E4B-it",
        ),
        AgentConfig(
            name="Disabled E2B",
            prompt_id="role-2",
            enabled=False,
            api_host="http://127.0.0.1:8080",
            llm_id="gemma-4-E2B-it",
        ),
        AgentConfig(
            name="Roleless E2B",
            prompt_id=None,
            api_host="http://127.0.0.1:8080",
            llm_id="gemma-4-E2B-it",
        ),
    ]

    _managed_local_ai_preflight(
        _preflight_context(managed_hosts, mock_local_ai_manager),
        agents,
        mock_local_ai_manager,
    )


def test_start_discussion_preflight_409_for_uninstalled(
    client: TestClient,
    mock_context: MagicMock,
    mock_local_ai_manager: MagicMock,
    managed_hosts: dict,
) -> None:
    _install_manager(mock_local_ai_manager)
    mock_context.settings.known_llm_hosts = managed_hosts
    mock_local_ai_manager.inventory.return_value = [
        {"model_id": "gemma-4-e2b", "installed": False},
    ]
    mock_local_ai_manager.status.return_value = LocalAIStatus(state="installed")

    body = {
        "material": "Material",
        "agents": [
            {
                "name": "A1",
                "client_id": "agent-1",
                "prompt_id": "role-1",
                "api_host": "http://127.0.0.1:8080",
                "llm_id": "gemma-4-E2B-it",
                "perspective_number": 1,
            },
        ],
        "title": "",
        "material_context": {
            "material_type": "document",
            "session_type": "exploration",
            "target_language": "German",
            "input_values": {
                "research_material_context": "",
                "main_input": "Prüfauftrag",
                "additional_instructions": "",
            },
        },
        "synthesis": {
            "enabled": False,
            "api_host": None,
            "llm_id": None,
            "temperature": None,
        },
        "sequential_mode": False,
    }

    with override_context(app, mock_context):
        response = client.post("/api/discussions/start", json=body)

    assert response.status_code == 409, response.text
    assert response.json() == {
        "detail": "Öffne Integrierte KI und lade zuerst eine Gemma-Variante herunter.",
        "error": {
            "code": "local_ai_model_not_installed",
            "params": {"model_id": "gemma-4-e2b"},
        },
    }
    # The discussion service must never be touched when the preflight blocks.
    mock_context.discussion.start_new_discussion.assert_not_called()
