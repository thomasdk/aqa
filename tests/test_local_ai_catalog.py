from __future__ import annotations

import re

import pytest
import requests

import src.local_ai.platform as platform_module
from src.local_ai.catalog import (
    BINARY_SPECS,
    MODELS,
    binary_for_profile,
    companion_for_binary,
    latest_binary_for_profile,
)
from src.local_ai.downloads import (
    binary_download_spec,
    draft_download_spec,
    model_download_spec,
)
from src.local_ai.platform import (
    HardwareProfile,
    binary_candidates,
    detect_hardware_profile,
    inference_memory_for_binary,
    parse_runtime_devices,
    select_binary,
)


def test_catalog_offers_the_three_supported_qat_models_in_order() -> None:
    assert list(MODELS) == ["gemma-4-e2b", "gemma-4-e4b", "gemma-4-12b"]
    assert MODELS["gemma-4-e2b"].api_alias == "gemma-4-E2B-it"
    assert MODELS["gemma-4-e2b"].model_filename == "gemma-4-E2B-it-qat-UD-Q4_K_XL.gguf"
    assert MODELS["gemma-4-e2b"].draft_filename == "mtp-gemma-4-E2B-it.gguf"
    assert MODELS["gemma-4-e4b"].model_filename == "gemma-4-E4B-it-qat-UD-Q4_K_XL.gguf"
    assert MODELS["gemma-4-e4b"].api_alias == "gemma-4-E4B-it"
    assert MODELS["gemma-4-e4b"].draft_filename == "mtp-gemma-4-E4B-it.gguf"
    assert MODELS["gemma-4-12b"].api_alias == "gemma-4-12B-it"
    assert MODELS["gemma-4-12b"].model_filename == "gemma-4-12B-it-qat-UD-Q4_K_XL.gguf"
    assert MODELS["gemma-4-12b"].draft_filename == "mtp-gemma-4-12B-it.gguf"
    assert MODELS["gemma-4-e2b"].flash_attention == "on"
    assert MODELS["gemma-4-e4b"].flash_attention == "off"
    assert MODELS["gemma-4-12b"].flash_attention == "on"
    assert MODELS["gemma-4-12b"].supported_context_tokens == 262_144


def test_model_metadata_allow_lists_only_the_three_repositories_and_fixed_gguf_names() -> None:
    e2b = MODELS["gemma-4-e2b"]
    e4b = MODELS["gemma-4-e4b"]
    model_12b = MODELS["gemma-4-12b"]

    assert e2b.repo_id == "unsloth/gemma-4-E2B-it-qat-GGUF"
    assert e2b.model_filename == "gemma-4-E2B-it-qat-UD-Q4_K_XL.gguf"
    assert e2b.draft_filename == "mtp-gemma-4-E2B-it.gguf"

    assert e4b.repo_id == "unsloth/gemma-4-E4B-it-qat-GGUF"
    assert e4b.model_filename == "gemma-4-E4B-it-qat-UD-Q4_K_XL.gguf"
    assert e4b.draft_filename == "mtp-gemma-4-E4B-it.gguf"

    assert model_12b.repo_id == "unsloth/gemma-4-12B-it-qat-GGUF"
    assert model_12b.model_filename == "gemma-4-12B-it-qat-UD-Q4_K_XL.gguf"
    assert model_12b.draft_filename == "mtp-gemma-4-12B-it.gguf"

    for model in MODELS.values():
        assert re.fullmatch(r"[0-9a-f]{40}", model.revision)
        assert re.fullmatch(r"[0-9a-f]{64}", model.model_sha256)
        assert re.fullmatch(r"[0-9a-f]{64}", model.draft_sha256)
        assert model.model_bytes > 0
        assert model.draft_bytes > 0
        assert f"/resolve/{model.revision}/" in model.model_url
        assert f"/resolve/{model.revision}/" in model.draft_url


def test_model_main_and_draft_identities_match_the_pinned_repository_revisions() -> None:
    expected = {
        "gemma-4-e2b": (
            "66a399f68ddd113b06dff02fca9523e55465d11d",
            2_620_370_976,
            "e531007218dfab990486a5de7676a6932d6ea8dea233d1f698d7c21cf8a16889",
            59_235_648,
            "586f2460b909008640981ec34060aa864e03c144fbabfb3173c4335087e4aae0",
        ),
        "gemma-4-e4b": (
            "8c5a9e4fd5482e2be20fe0bf013b4c262a8f4265",
            4_215_695_776,
            "df0fd4ee07072c607c29a0a1cb4f98918426cca12f45a2776bdd6ee6d09a4de3",
            59_678_016,
            "423074e537504b4f9ec5eafed5c639fac82c96631626efccacdd3c4039b20605",
        ),
        "gemma-4-12b": (
            "980b060c40a8539ac159e0501a3e0f66a6365af3",
            6_716_356_800,
            "90fd44e29e0d7cffeb0fd00dc73cfdab9ed0b0e95306ecf7821ea634c940c370",
            253_708_800,
            "fcb35dea42c71333db904cee11baac525c9ef872818ee3753f6cb156f3c6f4f6",
        ),
    }

    for model_id, identity in expected.items():
        model = MODELS[model_id]
        revision, model_bytes, model_sha256, draft_bytes, draft_sha256 = identity
        assert model.revision == revision
        assert (model.model_bytes, model.model_sha256) == (model_bytes, model_sha256)
        assert (model.draft_bytes, model.draft_sha256) == (draft_bytes, draft_sha256)
        assert model.model_url.startswith(
            f"https://huggingface.co/{model.repo_id}/resolve/{revision}/"
        )
        assert model.draft_url.startswith(
            f"https://huggingface.co/{model.repo_id}/resolve/{revision}/"
        )


def test_model_and_draft_download_specs_are_strict_and_rooted() -> None:
    e2b = MODELS["gemma-4-e2b"]

    model_spec = model_download_spec("gemma-4-e2b")
    assert model_spec.url == e2b.model_url
    assert model_spec.destination.name == e2b.model_filename
    assert model_spec.verification == "strict"
    assert model_spec.expected_sha256 == e2b.model_sha256
    assert model_spec.expected_bytes == e2b.model_bytes
    assert model_spec.catalog_key == "model:gemma-4-e2b"

    draft_spec = draft_download_spec("gemma-4-e2b")
    assert draft_spec.url == e2b.draft_url
    assert draft_spec.destination.name == e2b.draft_filename
    assert draft_spec.verification == "strict"
    assert draft_spec.expected_sha256 == e2b.draft_sha256
    assert draft_spec.expected_bytes == e2b.draft_bytes
    assert draft_spec.catalog_key == "draft:gemma-4-e2b"

    # The two helpers share the same fixed-root contract: every destination
    # is contained under ``<root>/models/<model-id>/``.
    assert model_spec.destination.parent.parent.parent == model_spec.destination.parents[2]
    assert draft_spec.destination.parent.parent.parent == draft_spec.destination.parents[2]


def test_binary_download_spec_remains_strict_with_pinned_digest_and_size() -> None:
    spec = binary_download_spec("macos-arm64-metal")
    assert spec.verification == "strict"
    assert re.fullmatch(r"[0-9a-fA-F]{64}", spec.expected_sha256 or "")
    assert spec.expected_bytes is not None and spec.expected_bytes > 0
    assert spec.catalog_key == "binary:macos-arm64-metal"


def test_binary_spec_exposes_only_canonical_archive_fields() -> None:
    binary = BINARY_SPECS["macos-arm64-metal"]

    assert binary.archive_filename.startswith("llama-b10976-bin-")
    assert binary.archive_url.endswith(binary.archive_filename)
    assert len(binary.archive_sha256) == 64
    for removed_name in ("filename", "url", "sha256"):
        assert not hasattr(binary, removed_name)


def test_latest_binary_resolution_uses_the_selected_release_asset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binary = BINARY_SPECS["windows-arm64-cpu"]
    tag = "b10043"
    filename = "llama-b10043-bin-win-cpu-arm64.zip"
    digest = "a" * 64

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "tag_name": tag,
                "assets": [
                    {
                        "name": filename,
                        "browser_download_url": (
                            f"https://github.com/ggml-org/llama.cpp/releases/download/{tag}/{filename}"
                        ),
                        "size": 12_345_678,
                        "digest": f"sha256:{digest}",
                    }
                ],
            }

    monkeypatch.setattr("src.local_ai.catalog.requests.get", lambda *_args, **_kwargs: Response())

    resolved = latest_binary_for_profile(binary)

    assert resolved.release_tag == tag
    assert resolved.archive_filename == filename
    assert resolved.archive_url == (
        f"https://github.com/ggml-org/llama.cpp/releases/download/{tag}/{filename}"
    )
    assert resolved.archive_bytes == 12_345_678
    assert resolved.archive_sha256 == digest


def test_latest_binary_retries_an_incomplete_release_then_uses_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binary = BINARY_SPECS["windows-arm64-cpu"]
    tag = "b10044"
    filename = "llama-b10044-bin-win-cpu-arm64.zip"
    attempts = 0
    sleeps: list[float] = []

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            nonlocal attempts
            attempts += 1
            assets = (
                []
                if attempts == 1
                else [
                    {
                        "name": filename,
                        "browser_download_url": f"https://github.com/ggml-org/llama.cpp/releases/download/{tag}/{filename}",
                        "size": 123,
                        "digest": f"sha256:{'b' * 64}",
                    }
                ]
            )
            return {"tag_name": tag, "assets": assets}

    monkeypatch.setattr("src.local_ai.catalog.requests.get", lambda *_args, **_kwargs: Response())
    monkeypatch.setattr("src.local_ai.catalog.time.sleep", sleeps.append)

    resolved = latest_binary_for_profile(binary)

    assert attempts == 2
    assert sleeps == [0.25]
    assert resolved.release_tag == tag


def test_latest_binary_falls_back_to_verified_pin_after_api_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binary = BINARY_SPECS["macos-arm64-metal"]
    calls = 0

    def fail(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise requests.ConnectionError("offline")

    monkeypatch.setattr("src.local_ai.catalog.requests.get", fail)
    monkeypatch.setattr("src.local_ai.catalog.time.sleep", lambda _seconds: None)

    assert latest_binary_for_profile(binary) is binary
    assert calls == 3


def test_windows_cuda_has_exact_allow_listed_cudart_companion() -> None:
    companion = companion_for_binary("windows-x86_64-cuda")

    assert companion.kind == "cudart"
    assert companion.archive_filename == "cudart-llama-bin-win-cuda-12.4-x64.zip"
    assert companion.archive_bytes == 391_443_627
    assert companion.archive_sha256 == (
        "8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6"
    )
    assert companion.archive_url.endswith(f"/b10976/{companion.archive_filename}")
    assert companion.license_filename == "NVIDIA-CUDA-EULA-2024-01-12.txt"
    assert companion.license_sha256 == (
        "e2c71babfd18a8e69542dd7e9ca018f9caa438094001a58e6bc4d8c999bf0d07"
    )
    assert companion.license_bytes == 63_021
    assert companion.installed_license_filename == "NVIDIA-CUDA-EULA.txt"
    with pytest.raises(ValueError, match="no 'cudart' companion"):
        companion_for_binary("windows-x86_64-cpu")


@pytest.mark.parametrize(
    ("profile", "license_filename", "license_sha256", "license_bytes"),
    (
        (
            "windows-x86_64-cuda",
            "NVIDIA-CUDA-EULA-2024-01-12.txt",
            "e2c71babfd18a8e69542dd7e9ca018f9caa438094001a58e6bc4d8c999bf0d07",
            63_021,
        ),
        (
            "linux-x86_64-cuda",
            "NVIDIA-CUDA-EULA-2024-01-12.txt",
            "e2c71babfd18a8e69542dd7e9ca018f9caa438094001a58e6bc4d8c999bf0d07",
            63_021,
        ),
        (
            "linux-arm64-cuda",
            "NVIDIA-CUDA-EULA-2026-01-26.txt",
            "088381bc2d891e719a2a9398645b00bb45f3b24231473a8283ac7e3e66b8a028",
            68_070,
        ),
        (
            "windows-arm64-cuda",
            "NVIDIA-CUDA-EULA-2026-01-26.txt",
            "088381bc2d891e719a2a9398645b00bb45f3b24231473a8283ac7e3e66b8a028",
            68_070,
        ),
    ),
)
def test_cuda_companions_pin_source_matched_license_material(
    profile: str, license_filename: str, license_sha256: str, license_bytes: int
) -> None:
    companion = companion_for_binary(profile)

    assert companion.license_filename == license_filename
    assert companion.license_sha256 == license_sha256
    assert companion.license_bytes == license_bytes
    assert companion.installed_license_filename == "NVIDIA-CUDA-EULA.txt"


def test_latest_windows_cuda_requires_and_resolves_companion_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binary = BINARY_SPECS["windows-x86_64-cuda"]
    tag = "b10045"
    main_name = "llama-b10045-bin-win-cuda-12.4-x64.zip"
    companion_name = "cudart-llama-bin-win-cuda-12.4-x64.zip"

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "tag_name": tag,
                "assets": [
                    {
                        "name": main_name,
                        "browser_download_url": f"https://github.com/ggml-org/llama.cpp/releases/download/{tag}/{main_name}",
                        "size": 10,
                        "digest": f"sha256:{'c' * 64}",
                    },
                    {
                        "name": companion_name,
                        "browser_download_url": f"https://github.com/ggml-org/llama.cpp/releases/download/{tag}/{companion_name}",
                        "size": 20,
                        "digest": f"sha256:{'d' * 64}",
                    },
                ],
            }

    monkeypatch.setattr("src.local_ai.catalog.requests.get", lambda *_args, **_kwargs: Response())
    resolved = latest_binary_for_profile(binary)

    companion = companion_for_binary(resolved)
    assert resolved.release_tag == tag
    assert companion.release_tag == tag
    assert companion.archive_bytes == 20
    assert companion.archive_sha256 == "d" * 64


def test_catalog_urls_and_archive_members_cannot_contain_unsafe_input() -> None:
    url_pattern = re.compile(
        r"^https://huggingface\.co/[^/]+/[^/]+/resolve/[0-9a-f]{40}/[^/]+\.gguf$"
    )
    for model in MODELS.values():
        assert url_pattern.fullmatch(model.model_url)
        assert url_pattern.fullmatch(model.draft_url)
        assert ".." not in model.model_filename
        assert ".." not in model.draft_filename
        assert "/" not in model.model_filename
        assert "/" not in model.draft_filename

    for binary in BINARY_SPECS.values():
        assert binary.archive_url.startswith(
            "https://github.com/ggml-org/llama.cpp/releases/download/b10976/"
        )
        assert binary.archive_url.endswith(binary.archive_filename)
        assert len(binary.archive_sha256) == 64
        assert binary.engine_name in {"llama-server", "llama-server.exe"}
        assert all(
            ".." not in member and not member.startswith("/") for member in binary.archive_members
        )


def test_llama_cpp_b10976_assets_are_pinned_with_sizes_and_digests() -> None:
    assert set(BINARY_SPECS) == {
        "macos-arm64-metal",
        "macos-x86_64-cpu",
        "windows-x86_64-cpu",
        "windows-x86_64-cuda",
        "windows-x86_64-vulkan",
        "windows-x86_64-rocm",
        "windows-x86_64-sycl",
        "windows-arm64-cpu",
        "windows-arm64-cuda",
        "windows-arm64-opencl",
        "linux-x86_64-cpu",
        "linux-x86_64-cuda",
        "linux-x86_64-vulkan",
        "linux-x86_64-rocm",
        "linux-arm64-cpu",
        "linux-arm64-cuda",
        "linux-arm64-vulkan",
    }
    assert all(
        binary.archive_filename.startswith("llama-b10976-bin-") for binary in BINARY_SPECS.values()
    )
    assert all(binary.archive_bytes > 0 for binary in BINARY_SPECS.values())

    assert BINARY_SPECS["macos-arm64-metal"].archive_sha256 == (
        "a85c95ca6f5aa38c32f8ad470dba2b660e861f05a30d681b77e2bbe3bb2f5dab"
    )
    assert BINARY_SPECS["windows-x86_64-cuda"].archive_sha256 == (
        "047242d39959e6bf97b2961bd8c04b356809c7e794e3de3b0d55f5940c70a1da"
    )
    assert BINARY_SPECS["linux-x86_64-rocm"].archive_sha256 == (
        "c0b22c62670e56f37379eff363ec9fef781845de3070d0f9b44d0a7b4214d028"
    )
    assert BINARY_SPECS["windows-x86_64-vulkan"].archive_sha256 == (
        "7357b0a14f2e8a1002b6c3edfa054e5f9cad2357a4af2e009f098c6d60a466b8"
    )
    assert BINARY_SPECS["windows-x86_64-vulkan"].archive_bytes == 31_675_956
    assert BINARY_SPECS["linux-x86_64-vulkan"].archive_sha256 == (
        "bf5c969d34ce1dad3a00088aeb3279714fd538b5b1149c01edac0bec7bfb8f49"
    )
    assert BINARY_SPECS["linux-x86_64-vulkan"].archive_bytes == 30_189_596
    assert BINARY_SPECS["windows-x86_64-cuda"].engine_name == "llama-server.exe"
    assert BINARY_SPECS["linux-x86_64-vulkan"].engine_name == "llama-server"

    windows_arm64 = BINARY_SPECS["windows-arm64-cpu"]
    assert windows_arm64.platform == "windows-arm64"
    assert windows_arm64.accelerator == "cpu"
    assert windows_arm64.archive_filename == "llama-b10976-bin-win-cpu-arm64.zip"
    assert windows_arm64.archive_sha256 == (
        "b59e7a11a666d5fc9400649a0a286645e0062d08e0b6ce63c57904e2d607b80d"
    )
    assert windows_arm64.archive_bytes == 11_997_120
    assert "LICENSE-LLVM-OpenMP" in windows_arm64.archive_members
    assert windows_arm64.engine_name == "llama-server.exe"

    linux_arm64 = BINARY_SPECS["linux-arm64-cpu"]
    assert linux_arm64.platform == "linux-arm64"
    assert linux_arm64.accelerator == "cpu"
    assert linux_arm64.archive_filename == "llama-b10976-bin-ubuntu-arm64.tar.gz"
    assert linux_arm64.archive_sha256 == (
        "ed41c5fd09ae86dbe13e525a57549f1d27d51e7efdc9a9aa4583d42016be7786"
    )
    assert linux_arm64.archive_bytes == 13_469_344
    assert linux_arm64.archive_members == (
        "llama-b10976/llama-server",
        "llama-b10976/LICENSE",
    )
    assert linux_arm64.engine_name == "llama-server"

    for binary in BINARY_SPECS.values():
        if not binary.platform.startswith("windows-"):
            assert f"llama-{binary.release_tag}/LICENSE" in binary.archive_members


def test_apple_silicon_selects_the_metal_capable_macos_archive() -> None:
    selected = select_binary(HardwareProfile(os="Darwin", arch="arm64", gpu="metal"))
    assert selected.platform == "macos-arm64"
    assert selected.accelerator == "metal"
    assert selected.archive_filename == "llama-b10976-bin-macos-arm64.tar.gz"
    # A Metal-capable selection must remain GPU-capable: any non-CPU
    # accelerator means llama.cpp should offload layers to the GPU.
    assert selected.accelerator != "cpu"


def test_unknown_evidence_keeps_the_cpu_binary_zero_gpu_layers() -> None:
    selected = select_binary(
        HardwareProfile(os="Windows", arch="AMD64", gpu="unknown", driver_runtime=None)
    )
    assert selected.accelerator == "cpu"
    # A CPU binary paired with the conservative "safe CPU fallback" basis
    # is the only one the API may expose as zero GPU layers.
    assert selected.accelerator == "cpu"  # noqa: PLR0124 -- explained above


def test_unknown_gpu_falls_back_to_cpu_instead_of_guessing() -> None:
    selected = select_binary(HardwareProfile(os="Windows", arch="AMD64", gpu="unknown"))
    assert selected.accelerator == "cpu"
    assert selected.archive_filename == "llama-b10976-bin-win-cpu-x64.zip"


def test_known_windows_and_linux_accelerators_select_only_matching_release_assets() -> None:
    assert (
        select_binary(
            HardwareProfile(os="Windows", arch="x86_64", gpu="nvidia", driver_runtime="cuda-12.4")
        ).accelerator
        == "cuda"
    )
    assert (
        select_binary(
            HardwareProfile(os="Windows", arch="x86_64", gpu="amd", driver_runtime="rocm-10.0")
        ).accelerator
        == "rocm"
    )
    assert (
        select_binary(
            HardwareProfile(os="Windows", arch="x86_64", gpu="amd", driver_runtime="vulkan")
        ).accelerator
        == "vulkan"
    )
    assert (
        select_binary(
            HardwareProfile(os="Linux", arch="x86_64", gpu="amd", driver_runtime="rocm-10.0")
        ).accelerator
        == "rocm"
    )
    assert (
        select_binary(
            HardwareProfile(os="Linux", arch="x86_64", gpu="nvidia", driver_runtime="vulkan")
        ).accelerator
        == "vulkan"
    )
    assert (
        select_binary(
            HardwareProfile(os="Linux", arch="x86_64", gpu="nvidia", driver_runtime="cuda-12.4")
        ).accelerator
        == "cpu"
    )


def test_accelerated_selection_requires_a_matching_runtime_and_safe_fallback() -> None:
    assert (
        select_binary(HardwareProfile(os="Windows", arch="x86_64", gpu="nvidia")).accelerator
        == "cpu"
    )
    assert (
        select_binary(
            HardwareProfile(os="Windows", arch="x86_64", gpu="nvidia", driver_runtime="cuda-13.3")
        ).accelerator
        == "cpu"
    )
    assert (
        select_binary(
            HardwareProfile(os="Windows", arch="x86_64", gpu="rocm", driver_runtime="rocm-10.0")
        ).accelerator
        == "rocm"
    )
    assert (
        select_binary(
            HardwareProfile(os="Linux", arch="x86_64", gpu="cuda", driver_runtime="cuda-12.4")
        ).accelerator
        == "cpu"
    )
    assert (
        select_binary(
            HardwareProfile(
                os="Windows", arch="x86_64", gpu="nvidia", driver_runtime_compatible=True
            )
        ).accelerator
        == "cuda"
    )


def test_detection_records_runtime_evidence_without_install_side_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("src.local_ai.platform.system_platform.system", lambda: "Windows")
    monkeypatch.setattr("src.local_ai.platform.system_platform.machine", lambda: "AMD64")

    def probe(command: str, *_arguments: str) -> str:
        return "AMD Radeon\\nROCm 7.2" if command == "rocminfo" else ""

    monkeypatch.setattr("src.local_ai.platform._probe_command", probe)
    profile = detect_hardware_profile()
    assert profile.gpu == "rocm"
    assert profile.driver_runtime == "rocm-7.2"


def test_nvidia_detection_uses_full_status_for_cuda_version_and_still_probes_vulkan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("src.local_ai.platform.system_platform.system", lambda: "Windows")
    monkeypatch.setattr("src.local_ai.platform.system_platform.machine", lambda: "AMD64")
    calls: list[tuple[str, tuple[str, ...]]] = []

    def probe(command: str, *arguments: str) -> str:
        calls.append((command, arguments))
        if command == "nvidia-smi":
            return (
                "NVIDIA-SMI 572.83   Driver Version: 572.83   CUDA Version: 12.4\n"
                "NVIDIA GeForce RTX 4070"
            )
        if command == "vulkaninfo":
            return "GPU0: NVIDIA GeForce RTX 4070"
        return ""

    monkeypatch.setattr("src.local_ai.platform._probe_command", probe)
    profile = detect_hardware_profile()

    assert ("nvidia-smi", ()) in calls
    assert not any(command == "nvidia-smi" and arguments == ("-L",) for command, arguments in calls)
    assert ("vulkaninfo", ("--summary",)) in calls
    assert profile.gpu == "cuda"
    assert profile.driver_runtime == "cuda-12.4"
    assert select_binary(profile).accelerator == "cuda"


def test_incompatible_nvidia_cuda_uses_independently_detected_vulkan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("src.local_ai.platform.system_platform.system", lambda: "Windows")
    monkeypatch.setattr("src.local_ai.platform.system_platform.machine", lambda: "x86_64")

    def probe(command: str, *_arguments: str) -> str:
        if command == "nvidia-smi":
            return "NVIDIA-SMI 600.00   CUDA Version: 13.3\nNVIDIA RTX"
        if command == "vulkaninfo":
            return "GPU0:\n  deviceName = NVIDIA RTX\n  apiVersion = 1.3"
        return ""

    monkeypatch.setattr("src.local_ai.platform._probe_command", probe)
    profile = detect_hardware_profile()

    assert profile.gpu_family == "nvidia"
    assert profile.driver_runtime == "vulkan"
    assert select_binary(profile).accelerator == "vulkan"


def test_incompatible_linux_rocm_uses_independently_detected_vulkan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("src.local_ai.platform.system_platform.system", lambda: "Linux")
    monkeypatch.setattr("src.local_ai.platform.system_platform.machine", lambda: "x86_64")

    def probe(command: str, *_arguments: str) -> str:
        if command == "rocminfo":
            return "Agent 2: AMD Radeon RX 7900 XTX"
        if command == "hipconfig":
            return "HIP version: 6.4.43482"
        if command == "vulkaninfo":
            return "GPU0: AMD Radeon RX 7900 XTX (RADV NAVI31)"
        return ""

    monkeypatch.setattr("src.local_ai.platform._probe_command", probe)
    profile = detect_hardware_profile()

    assert profile.gpu_family == "amd"
    assert profile.driver_runtime == "vulkan"
    assert select_binary(profile).accelerator == "vulkan"


def test_intel_macos_requires_explicit_metal_support(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("src.local_ai.platform.system_platform.system", lambda: "Darwin")
    monkeypatch.setattr("src.local_ai.platform.system_platform.machine", lambda: "x86_64")
    monkeypatch.setattr(
        "src.local_ai.platform._probe_command",
        lambda command, *_arguments: (
            '{"SPDisplaysDataType":[{"spdisplays_metal":"spdisplays_unsupported"}]}'
            if command == "system_profiler"
            else ""
        ),
    )

    profile = detect_hardware_profile()
    assert profile.gpu == "unknown"
    assert profile.driver_runtime is None
    assert select_binary(profile).accelerator == "cpu"


def test_intel_macos_official_archive_remains_truthfully_cpu_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("src.local_ai.platform.system_platform.system", lambda: "Darwin")
    monkeypatch.setattr("src.local_ai.platform.system_platform.machine", lambda: "x86_64")
    monkeypatch.setattr(
        "src.local_ai.platform._probe_command",
        lambda command, *_arguments: (
            '{"SPDisplaysDataType":[{"spdisplays_metal":"spdisplays_supported"}]}'
            if command == "system_profiler"
            else ""
        ),
    )

    profile = detect_hardware_profile()
    assert profile.driver_runtime == "metal"
    assert select_binary(profile).accelerator == "cpu"


def test_apple_silicon_keeps_metal_without_external_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("src.local_ai.platform.system_platform.system", lambda: "Darwin")
    monkeypatch.setattr("src.local_ai.platform.system_platform.machine", lambda: "arm64")

    def unexpected_probe(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("Apple Silicon must not need an external GPU probe")

    monkeypatch.setattr("src.local_ai.platform._probe_command", unexpected_probe)
    profile = detect_hardware_profile()
    assert profile.driver_runtime == "metal"
    assert select_binary(profile).accelerator == "metal"


def test_apple_silicon_hardware_labels_and_sysctl_memory_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("src.local_ai.platform.system_platform.system", lambda: "Darwin")
    monkeypatch.setattr("src.local_ai.platform.system_platform.machine", lambda: "arm64")
    monkeypatch.setattr("src.local_ai.platform.system_platform.processor", lambda: "")
    monkeypatch.setattr("src.local_ai.platform.os.cpu_count", lambda: None)
    monkeypatch.setattr(
        "src.local_ai.platform.os.sysconf",
        lambda _name: (_ for _ in ()).throw(OSError()),
        raising=False,
    )
    monkeypatch.setattr(
        "src.local_ai.platform._sysctl_value",
        lambda name: {
            "machdep.cpu.brand_string": "Apple M2",
            "hw.ncpu": "8",
            "hw.memsize": str(16 * 1024**3),
        }.get(name, ""),
    )

    profile = detect_hardware_profile()

    assert profile.os_label == "macOS (Apple Silicon)"
    assert profile.cpu_label == "Apple M2"
    assert profile.ram_gb == 16


def test_hardware_labels_use_sanitized_cross_platform_fallbacks() -> None:
    profile = HardwareProfile(
        os="Windows",
        arch="AMD64",
        cpu_name="CPU / internal -- label",
        logical_cpu_count=12,
    )

    assert profile.os_label == "Windows"
    assert profile.cpu_label == "CPU  internal - label"


def test_windows_arm64_selects_the_safe_cpu_only_archive() -> None:
    selected = select_binary(HardwareProfile(os="Windows", arch="ARM64", gpu="unknown"))
    assert selected.profile == "windows-arm64-cpu"
    assert selected.platform == "windows-arm64"
    assert selected.accelerator == "cpu"
    assert selected.archive_filename == "llama-b10976-bin-win-cpu-arm64.zip"
    # A CPU binary paired with Windows-ARM64 is the only allowed basis on
    # this architecture; any other accelerator would imply unverified
    # GPU offload and must be rejected.
    assert selected.accelerator == "cpu"


def test_linux_aarch64_selects_the_safe_cpu_only_archive() -> None:
    selected = select_binary(HardwareProfile(os="Linux", arch="aarch64", gpu="unknown"))
    assert selected.profile == "linux-arm64-cpu"
    assert selected.platform == "linux-arm64"
    assert selected.accelerator == "cpu"
    assert selected.archive_filename == "llama-b10976-bin-ubuntu-arm64.tar.gz"
    # A CPU binary paired with Linux-ARM64 is the only allowed basis on
    # this architecture; any other accelerator would imply unverified
    # GPU offload and must be rejected.
    assert selected.accelerator == "cpu"


def test_windows_ram_uses_native_memory_and_rounds_nominal_capacity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "src.local_ai.platform._windows_total_physical_memory_bytes", lambda: 15_600 * 1024**2
    )
    monkeypatch.setattr(
        "src.local_ai.platform.os.sysconf",
        lambda _name: (_ for _ in ()).throw(AssertionError("Windows must use native memory")),
        raising=False,
    )

    from src.local_ai.platform import _detected_ram_gb

    assert _detected_ram_gb("windows") == 15


def test_linux_ram_falls_back_to_meminfo_when_sysconf_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "src.local_ai.platform.os.sysconf",
        lambda _name: (_ for _ in ()).throw(OSError()),
        raising=False,
    )
    monkeypatch.setattr("src.local_ai.platform._linux_meminfo_total_bytes", lambda: 16 * 1024**3)

    from src.local_ai.platform import _detected_ram_gb

    assert _detected_ram_gb("linux") == 16


def test_nvidia_vram_uses_largest_single_gpu_and_ignores_malformed_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "src.local_ai.platform._probe_command",
        lambda command, *_arguments: (
            "16384\nnot reported\n24576\n0" if command == "nvidia-smi" else ""
        ),
    )

    from src.local_ai.platform import _nvidia_vram_bytes

    assert _nvidia_vram_bytes() == 24_576 * 1024**2


def test_linux_amd_vram_prefers_drm_and_uses_vulkan_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("src.local_ai.platform._linux_amd_drm_vram_bytes", lambda: 16 * 1024**3)
    monkeypatch.setattr("src.local_ai.platform._rocm_vram_bytes", lambda: 24 * 1024**3)
    monkeypatch.setattr(
        "src.local_ai.platform._vulkan_device_local_memory_bytes",
        lambda: (_ for _ in ()).throw(AssertionError("DRM evidence should win")),
    )

    from src.local_ai.platform import _detected_gpu_memory

    assert _detected_gpu_memory("linux", "x86_64", "amd") == (16, "vram")

    monkeypatch.setattr("src.local_ai.platform._linux_amd_drm_vram_bytes", lambda: None)
    monkeypatch.setattr("src.local_ai.platform._rocm_vram_bytes", lambda: None)
    monkeypatch.setattr(
        "src.local_ai.platform._vulkan_device_local_memory_bytes", lambda: 12 * 1024**3
    )
    assert _detected_gpu_memory("linux", "x86_64", "amd") == (12, "vram")


def test_vulkan_device_local_memory_parses_standard_heap_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "src.local_ai.platform._probe_command",
        lambda command, *_arguments: (
            "memoryHeaps[0]:\n  size = 8589934592\n  flags = DEVICE_LOCAL_BIT\n"
            "memoryHeaps[1]:\n  size = 17179869184\n  flags = DEVICE_LOCAL_BIT"
            if command == "vulkaninfo"
            else ""
        ),
    )

    from src.local_ai.platform import _vulkan_device_local_memory_bytes

    assert _vulkan_device_local_memory_bytes() == 16 * 1024**3


def test_macos_memory_distinguishes_shared_and_apple_silicon_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "src.local_ai.platform._probe_command",
        lambda command, *_arguments: (
            '{"spdisplays_vram":"1536 MB","spdisplays_vram_shared":"1536 MB"}'
            if command == "system_profiler"
            else ""
        ),
    )

    from src.local_ai.platform import _detected_gpu_memory

    assert _detected_gpu_memory("macos", "x86_64", "metal") == (1, "unified")
    assert _detected_gpu_memory("macos", "arm64", "metal") == (None, "unified")


def test_inference_memory_uses_the_explicit_selected_runtime() -> None:
    cpu_profile = HardwareProfile(os="Windows", arch="x86_64", ram_gb=16, vram_gb=24)
    assert inference_memory_for_binary(cpu_profile, BINARY_SPECS["windows-x86_64-cpu"]).gb == 16
    assert (
        inference_memory_for_binary(cpu_profile, BINARY_SPECS["windows-x86_64-cpu"]).kind == "ram"
    )

    accelerated = HardwareProfile(os="Windows", arch="x86_64", ram_gb=64, vram_gb=16)
    assert inference_memory_for_binary(accelerated, BINARY_SPECS["windows-x86_64-cuda"]).gb == 16
    assert (
        inference_memory_for_binary(accelerated, BINARY_SPECS["windows-x86_64-cuda"]).kind == "vram"
    )

    apple_silicon = HardwareProfile(os="Darwin", arch="arm64", ram_gb=24, vram_gb=None)
    assert inference_memory_for_binary(apple_silicon, BINARY_SPECS["macos-arm64-metal"]).gb == 24
    assert (
        inference_memory_for_binary(apple_silicon, BINARY_SPECS["macos-arm64-metal"]).kind
        == "unified"
    )

    missing_vram = HardwareProfile(os="Windows", arch="x86_64", ram_gb=64, vram_gb=None)
    assert inference_memory_for_binary(missing_vram, BINARY_SPECS["windows-x86_64-cuda"]).gb is None
    assert (
        inference_memory_for_binary(missing_vram, BINARY_SPECS["windows-x86_64-cuda"]).kind
        == "vram"
    )


def test_unknown_binary_profile_is_rejected_without_building_a_command() -> None:
    with pytest.raises(ValueError, match="unsupported binary profile"):
        binary_for_profile("../../run-this")


@pytest.mark.parametrize(
    ("profile", "expected"),
    [
        (HardwareProfile(os="Darwin", arch="arm64", gpu="metal"), ["metal", "cpu"]),
        (HardwareProfile(os="Darwin", arch="x86_64", gpu="metal"), ["cpu"]),
        (
            HardwareProfile(os="Windows", arch="x86_64", gpu="nvidia", gpu_label="NVIDIA RTX"),
            ["cuda", "vulkan", "cpu"],
        ),
        (
            HardwareProfile(os="Windows", arch="arm64", gpu_label="Qualcomm Adreno X1"),
            ["opencl", "cpu"],
        ),
        (
            HardwareProfile(os="Linux", arch="x86_64", gpu_label="Intel Graphics"),
            ["vulkan", "cpu"],
        ),
        (
            HardwareProfile(os="Linux", arch="arm64", gpu="nvidia", gpu_label="NVIDIA Graphics"),
            ["cuda", "vulkan", "cpu"],
        ),
    ],
)
def test_runtime_candidates_cover_all_six_targets_in_bounded_order(
    profile: HardwareProfile, expected: list[str]
) -> None:
    assert [candidate.accelerator for candidate in binary_candidates(profile)] == expected


def test_runtime_device_parser_accepts_physical_gpu_and_rejects_other_devices() -> None:
    probe = parse_runtime_devices(
        "Available devices:\n"
        "  MTL0: Apple M2 (12124 MiB, 12123 MiB free)\n"
        "  BLAS: Accelerate (0 MiB, 0 MiB free)\n"
        "Vulkan0: llvmpipe\nCPU: host CPU\nNPU: neural device"
    )

    assert probe.state == "gpu_candidate"
    assert [(device.identifier, device.name) for device in probe.devices] == [
        ("MTL0", "Apple M2 (12124 MiB 12123 MiB free)")
    ]
    assert parse_runtime_devices("Metal: Apple GPU", returncode=1).state == "failed"
    assert parse_runtime_devices("Available devices:").state == "cpu_only"
    assert parse_runtime_devices("").reason == "malformed_output"
    assert (
        parse_runtime_devices("SYCL backend failed: driver unavailable").reason
        == "driver_unavailable"
    )
    assert (
        parse_runtime_devices("Vulkan driver unavailable", returncode=1).reason
        == "driver_unavailable"
    )
    assert parse_runtime_devices("No compatible GPU detected").reason == "no_gpu"


def test_reported_intel_graphics_queues_sycl_vulkan_then_cpu() -> None:
    profile = HardwareProfile(os="Windows", arch="x86_64", gpu_label="Intel(R) Graphics", ram_gb=32)
    assert [binary.profile for binary in binary_candidates(profile)] == [
        "windows-x86_64-sycl",
        "windows-x86_64-vulkan",
        "windows-x86_64-cpu",
    ]


@pytest.mark.parametrize(
    ("adapters", "family", "preferred"),
    [
        (("Intel Graphics", "NVIDIA RTX 5090"), "nvidia", "cuda"),
        (("NVIDIA RTX 5090", "Intel Graphics"), "nvidia", "cuda"),
        (("Intel Graphics", "AMD Radeon RX 7900"), "amd", "rocm"),
        (("AMD Radeon RX 7900", "Intel Graphics"), "amd", "rocm"),
    ],
)
def test_hybrid_adapter_candidates_include_preferred_discrete_backend(
    adapters: tuple[str, ...], family: str, preferred: str
) -> None:
    candidates = binary_candidates(
        HardwareProfile(
            os="Windows",
            arch="x86_64",
            gpu=family,
            gpu_family=family,
            gpu_label=adapters[0],
            gpu_adapters=adapters,
        )
    )

    accelerators = [candidate.accelerator for candidate in candidates]
    assert accelerators[0] == preferred
    assert "sycl" in accelerators
    assert accelerators[-1] == "cpu"


def test_multi_adapter_memory_is_not_borrowed_from_another_gpu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(platform_module, "_nvidia_vram_bytes", lambda: 24 * 1024**3)
    monkeypatch.setattr(platform_module, "_windows_gpu_memory", lambda: (8 * 1024**3, True))

    assert platform_module._detected_gpu_memory(
        "windows", "x86_64", "nvidia", ("Intel Graphics", "NVIDIA RTX")
    ) == (None, None)


def test_windows_adapter_discovery_keeps_all_adapters_but_prefers_discrete_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        platform_module,
        "_probe_successful_stdout",
        lambda *_args: "Intel Iris Xe\nNVIDIA RTX 5090\n",
    )

    adapters = platform_module._physical_gpu_labels("windows", "x86_64")
    assert adapters == ("Intel Iris Xe", "NVIDIA RTX 5090")
    assert platform_module._preferred_gpu_label(adapters) == "NVIDIA RTX 5090"


def test_windows_adapter_discovery_rejects_powershell_stderr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(platform_module.shutil, "which", lambda _command: "powershell.exe")
    monkeypatch.setattr(
        platform_module.subprocess,
        "run",
        lambda *_args, **_kwargs: type(
            "Result",
            (),
            {
                "returncode": 0,
                "stdout": "NVIDIA RTX 5090\n",
                "stderr": "Get-CimInstance : Invalid class\n",
            },
        )(),
    )

    assert platform_module._physical_gpu_labels("windows", "x86_64") == ()


def test_runtime_device_parser_rejects_colon_diagnostics() -> None:
    probe = parse_runtime_devices(
        "load_backend: failed to load CUDA\n"
        "ggml_cuda_init: no CUDA-capable device is detected\n"
        "warning: Vulkan initialization failed\n"
        "CUDA0: NVIDIA RTX 5090\n"
        "Vulkan1 | AMD Radeon RX 7900"
    )

    assert [(device.identifier, device.name) for device in probe.devices] == [
        ("CUDA0", "NVIDIA RTX 5090"),
        ("Vulkan1", "AMD Radeon RX 7900"),
    ]
