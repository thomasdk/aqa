"""Immutable, allow-listed Local AI models and llama.cpp release assets."""

from __future__ import annotations

import re
import time
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Literal

import requests

FlashAttention = Literal["on", "off"]
ModelId = Literal["gemma-4-e2b", "gemma-4-e4b", "gemma-4-12b"]
BinaryAccelerator = Literal["cpu", "metal", "cuda", "hip", "rocm", "vulkan", "sycl", "opencl"]
BinaryCompanionKind = Literal["cudart"]

LOCAL_HOST = "127.0.0.1"
LOCAL_HOST_LABEL_PREFIX = "Local AI — "
DEFAULT_PORT = 8080
IDLE_SLEEP_SECONDS = 300
DEFAULT_MTP_ENABLED = False
DEFAULT_MTP_DRAFT_TOKENS = 4
MTP_DRAFT_TOKEN_CHOICES = (1, 2, 3, 4, 5, 6)


@dataclass(frozen=True)
class BinaryCompanionSpec:
    """One verified, allow-listed archive required by a binary archive."""

    kind: BinaryCompanionKind
    archive_filename: str
    archive_url: str
    archive_sha256: str
    archive_bytes: int
    archive_members: tuple[str, ...]
    license_filename: str
    license_sha256: str
    license_bytes: int
    installed_license_filename: str = "NVIDIA-CUDA-EULA.txt"
    release_tag: str = "b10976"


@dataclass(frozen=True)
class BinarySpec:
    """A verified llama.cpp release archive for one hardware profile."""

    profile: str
    platform: str
    accelerator: BinaryAccelerator
    archive_filename: str
    archive_url: str
    archive_sha256: str
    archive_bytes: int
    archive_members: tuple[str, ...]
    engine_name: str = ""
    runtime: str | None = None
    release_tag: str = "b10976"
    companions: tuple[BinaryCompanionSpec, ...] = ()

    def __post_init__(self) -> None:
        """Derive the executable name from the verified archive platform."""
        if not self.engine_name:
            object.__setattr__(
                self,
                "engine_name",
                "llama-server.exe" if self.platform.startswith("windows-") else "llama-server",
            )


@dataclass(frozen=True)
class ModelSpec:
    """A revision-pinned Unsloth Gemma 4 QAT target and matching MTP drafter."""

    id: ModelId
    # Public OpenAI-compatible name exposed by the local llama.cpp server.
    # This is deliberately separate from the immutable GGUF artifact name.
    api_alias: str
    label: str
    repo_id: str
    revision: str
    model_filename: str
    model_url: str
    model_sha256: str
    model_bytes: int
    draft_filename: str
    draft_url: str
    draft_sha256: str
    draft_bytes: int
    flash_attention: FlashAttention
    supported_context_tokens: int


def _model_url(repo_id: str, revision: str, filename: str) -> str:
    return f"https://huggingface.co/{repo_id}/resolve/{revision}/{filename}"


_LLAMA_CPP_REPOSITORY = "ggml-org/llama.cpp"
_LLAMA_CPP_LATEST_RELEASE_URL = (
    f"https://api.github.com/repos/{_LLAMA_CPP_REPOSITORY}/releases/latest"
)


def _binary_url(release_tag: str, filename: str) -> str:
    return f"https://github.com/{_LLAMA_CPP_REPOSITORY}/releases/download/{release_tag}/{filename}"


def _companion(
    *,
    kind: BinaryCompanionKind,
    filename: str,
    sha256: str,
    size: int,
    archive_members: tuple[str, ...],
    license_filename: str,
    license_sha256: str,
    license_bytes: int,
    release_tag: str = "b10976",
) -> BinaryCompanionSpec:
    return BinaryCompanionSpec(
        kind=kind,
        archive_filename=filename,
        archive_url=_binary_url(release_tag, filename),
        archive_sha256=sha256,
        archive_bytes=size,
        archive_members=archive_members,
        license_filename=license_filename,
        license_sha256=license_sha256,
        license_bytes=license_bytes,
        release_tag=release_tag,
    )


_WINDOWS_CUDA_12_4_COMPANION = _companion(
    kind="cudart",
    filename="cudart-llama-bin-win-cuda-12.4-x64.zip",
    sha256="8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6",
    size=391_443_627,
    archive_members=("cublas64_12.dll", "cublasLt64_12.dll", "cudart64_12.dll"),
    license_filename="NVIDIA-CUDA-EULA-2024-01-12.txt",
    license_sha256="e2c71babfd18a8e69542dd7e9ca018f9caa438094001a58e6bc4d8c999bf0d07",
    license_bytes=63_021,
    release_tag="b10976",
)

_WINDOWS_ARM_CUDA_13_4_COMPANION = _companion(
    kind="cudart",
    filename="cudart-llama-bin-win-cuda-13.4-arm64.zip",
    sha256="642dcde8805b3e3165ca710a5443b3b4044b27d96bd3ee3132473988c9bcb774",
    size=153_262_407,
    archive_members=("cublas64_13.dll", "cublasLt64_13.dll", "cudart64_13.dll"),
    license_filename="NVIDIA-CUDA-EULA-2026-01-26.txt",
    license_sha256="088381bc2d891e719a2a9398645b00bb45f3b24231473a8283ac7e3e66b8a028",
    license_bytes=68_070,
    release_tag="b10976",
)

_LINUX_X64_CUDA_12_8_COMPANION = _companion(
    kind="cudart",
    filename="cudart-llama-b10976-bin-ubuntu-cuda-12.8-x64.tar.gz",
    sha256="08e11f701ad2957021af68c9f2b81f0c4ea2e616fffc4c3e482c30b61dc90044",
    size=594_373_752,
    archive_members=(
        "cudart-llama-b10976-bin-ubuntu-cuda-12.8-x64/libcudart.so.12",
        "cudart-llama-b10976-bin-ubuntu-cuda-12.8-x64/libcublas.so.12",
        "cudart-llama-b10976-bin-ubuntu-cuda-12.8-x64/libcublasLt.so.12",
    ),
    license_filename="NVIDIA-CUDA-EULA-2024-01-12.txt",
    license_sha256="e2c71babfd18a8e69542dd7e9ca018f9caa438094001a58e6bc4d8c999bf0d07",
    license_bytes=63_021,
)

_LINUX_ARM_CUDA_13_3_COMPANION = _companion(
    kind="cudart",
    filename="cudart-llama-b10976-bin-ubuntu-cuda-13.3-arm64.tar.gz",
    sha256="e8cc4f80afeff5043dbf9a42430278f27230bd9a31e3ef5de0082dd217e842d3",
    size=518_393_024,
    archive_members=(
        "cudart-llama-b10976-bin-ubuntu-cuda-13.3-arm64/libcudart.so.13",
        "cudart-llama-b10976-bin-ubuntu-cuda-13.3-arm64/libcublas.so.13",
        "cudart-llama-b10976-bin-ubuntu-cuda-13.3-arm64/libcublasLt.so.13",
    ),
    license_filename="NVIDIA-CUDA-EULA-2026-01-26.txt",
    license_sha256="088381bc2d891e719a2a9398645b00bb45f3b24231473a8283ac7e3e66b8a028",
    license_bytes=68_070,
)


_E2B_REPO = "unsloth/gemma-4-E2B-it-qat-GGUF"
_E4B_REPO = "unsloth/gemma-4-E4B-it-qat-GGUF"
_12B_REPO = "unsloth/gemma-4-12B-it-qat-GGUF"
_E2B_REVISION = "66a399f68ddd113b06dff02fca9523e55465d11d"
_E4B_REVISION = "8c5a9e4fd5482e2be20fe0bf013b4c262a8f4265"
_12B_REVISION = "980b060c40a8539ac159e0501a3e0f66a6365af3"

MODELS: Mapping[ModelId, ModelSpec] = {
    "gemma-4-e2b": ModelSpec(
        id="gemma-4-e2b",
        api_alias="gemma-4-E2B-it",
        label="Gemma 4 E2B",
        repo_id=_E2B_REPO,
        revision=_E2B_REVISION,
        model_filename="gemma-4-E2B-it-qat-UD-Q4_K_XL.gguf",
        model_url=_model_url(_E2B_REPO, _E2B_REVISION, "gemma-4-E2B-it-qat-UD-Q4_K_XL.gguf"),
        model_sha256="e531007218dfab990486a5de7676a6932d6ea8dea233d1f698d7c21cf8a16889",
        model_bytes=2_620_370_976,
        draft_filename="mtp-gemma-4-E2B-it.gguf",
        draft_url=_model_url(_E2B_REPO, _E2B_REVISION, "mtp-gemma-4-E2B-it.gguf"),
        draft_sha256="586f2460b909008640981ec34060aa864e03c144fbabfb3173c4335087e4aae0",
        draft_bytes=59_235_648,
        flash_attention="on",
        supported_context_tokens=131_072,
    ),
    "gemma-4-e4b": ModelSpec(
        id="gemma-4-e4b",
        api_alias="gemma-4-E4B-it",
        label="Gemma 4 E4B",
        repo_id=_E4B_REPO,
        revision=_E4B_REVISION,
        model_filename="gemma-4-E4B-it-qat-UD-Q4_K_XL.gguf",
        model_url=_model_url(_E4B_REPO, _E4B_REVISION, "gemma-4-E4B-it-qat-UD-Q4_K_XL.gguf"),
        model_sha256="df0fd4ee07072c607c29a0a1cb4f98918426cca12f45a2776bdd6ee6d09a4de3",
        model_bytes=4_215_695_776,
        draft_filename="mtp-gemma-4-E4B-it.gguf",
        draft_url=_model_url(_E4B_REPO, _E4B_REVISION, "mtp-gemma-4-E4B-it.gguf"),
        draft_sha256="423074e537504b4f9ec5eafed5c639fac82c96631626efccacdd3c4039b20605",
        draft_bytes=59_678_016,
        flash_attention="off",
        supported_context_tokens=131_072,
    ),
    "gemma-4-12b": ModelSpec(
        id="gemma-4-12b",
        api_alias="gemma-4-12B-it",
        label="Gemma 4 12B",
        repo_id=_12B_REPO,
        revision=_12B_REVISION,
        model_filename="gemma-4-12B-it-qat-UD-Q4_K_XL.gguf",
        model_url=_model_url(_12B_REPO, _12B_REVISION, "gemma-4-12B-it-qat-UD-Q4_K_XL.gguf"),
        model_sha256="90fd44e29e0d7cffeb0fd00dc73cfdab9ed0b0e95306ecf7821ea634c940c370",
        model_bytes=6_716_356_800,
        draft_filename="mtp-gemma-4-12B-it.gguf",
        draft_url=_model_url(_12B_REPO, _12B_REVISION, "mtp-gemma-4-12B-it.gguf"),
        draft_sha256="fcb35dea42c71333db904cee11baac525c9ef872818ee3753f6cb156f3c6f4f6",
        draft_bytes=253_708_800,
        flash_attention="on",
        supported_context_tokens=262_144,
    ),
}


def _binary(
    *,
    profile: str,
    platform: str,
    accelerator: BinaryAccelerator,
    filename: str,
    sha256: str,
    size: int,
    archive_members: tuple[str, ...],
    runtime: str | None = None,
    companions: tuple[BinaryCompanionSpec, ...] = (),
) -> BinarySpec:
    return BinarySpec(
        profile=profile,
        platform=platform,
        accelerator=accelerator,
        archive_filename=filename,
        archive_url=_binary_url("b10976", filename),
        archive_sha256=sha256,
        archive_bytes=size,
        archive_members=archive_members,
        engine_name="llama-server.exe" if platform.startswith("windows-") else "llama-server",
        runtime=runtime,
        companions=companions,
        release_tag="b10976",
    )


BINARY_SPECS: Mapping[str, BinarySpec] = {
    "macos-arm64-metal": _binary(
        profile="macos-arm64-metal",
        platform="macos-arm64",
        accelerator="metal",
        filename="llama-b10976-bin-macos-arm64.tar.gz",
        sha256="a85c95ca6f5aa38c32f8ad470dba2b660e861f05a30d681b77e2bbe3bb2f5dab",
        size=11_149_629,
        archive_members=("llama-b10976/llama-server", "llama-b10976/LICENSE"),
        runtime="metal",
    ),
    "macos-x86_64-cpu": _binary(
        profile="macos-x86_64-cpu",
        platform="macos-x86_64",
        accelerator="cpu",
        filename="llama-b10976-bin-macos-x64.tar.gz",
        sha256="a99f6f1f1f1ecd9e33e31d100520568e1cc5ecce53f25b8a376057b88a61ced9",
        size=11_200_001,
        archive_members=("llama-b10976/llama-server", "llama-b10976/LICENSE"),
    ),
    "windows-x86_64-cpu": _binary(
        profile="windows-x86_64-cpu",
        platform="windows-x86_64",
        accelerator="cpu",
        filename="llama-b10976-bin-win-cpu-x64.zip",
        sha256="29b68d5abf165d77f928d6c0d46d9181ec07c46231baf7c112d182b7ecfdb456",
        size=18_428_731,
        archive_members=("llama-server.exe", "LICENSE-LLVM-OpenMP"),
    ),
    "windows-x86_64-cuda": _binary(
        profile="windows-x86_64-cuda",
        platform="windows-x86_64",
        accelerator="cuda",
        filename="llama-b10976-bin-win-cuda-12.4-x64.zip",
        sha256="047242d39959e6bf97b2961bd8c04b356809c7e794e3de3b0d55f5940c70a1da",
        size=254_086_292,
        archive_members=("llama-server.exe", "LICENSE-LLVM-OpenMP"),
        runtime="cuda-12.4",
        companions=(_WINDOWS_CUDA_12_4_COMPANION,),
    ),
    "windows-x86_64-vulkan": _binary(
        profile="windows-x86_64-vulkan",
        platform="windows-x86_64",
        accelerator="vulkan",
        filename="llama-b10976-bin-win-vulkan-x64.zip",
        sha256="7357b0a14f2e8a1002b6c3edfa054e5f9cad2357a4af2e009f098c6d60a466b8",
        size=31_675_956,
        archive_members=("llama-server.exe", "LICENSE-LLVM-OpenMP"),
        runtime="vulkan",
    ),
    "windows-x86_64-rocm": _binary(
        profile="windows-x86_64-rocm",
        platform="windows-x86_64",
        accelerator="rocm",
        filename="llama-b10976-bin-win-rocm-10.0-x64.zip",
        sha256="ce6dfdedac98eb7c9ff36ab25c5c8b8a4c4e1819ae9b84fadf7399a236459da7",
        size=256_018_499,
        archive_members=("llama-server.exe", "LICENSE-LLVM-OpenMP"),
        runtime="rocm-10.0",
    ),
    "windows-x86_64-sycl": _binary(
        profile="windows-x86_64-sycl",
        platform="windows-x86_64",
        accelerator="sycl",
        filename="llama-b10976-bin-win-sycl-x64.zip",
        sha256="88993b8e6b259f9e480103b2ed6fa549c2ae37a5b604533de73820a4a0c3d179",
        size=119_780_520,
        archive_members=("llama-server.exe", "LICENSE-LLVM-OpenMP"),
        runtime="sycl",
    ),
    "windows-arm64-cpu": _binary(
        profile="windows-arm64-cpu",
        platform="windows-arm64",
        accelerator="cpu",
        filename="llama-b10976-bin-win-cpu-arm64.zip",
        sha256="b59e7a11a666d5fc9400649a0a286645e0062d08e0b6ce63c57904e2d607b80d",
        size=11_997_120,
        archive_members=("llama-server.exe", "LICENSE-LLVM-OpenMP"),
    ),
    "windows-arm64-cuda": _binary(
        profile="windows-arm64-cuda",
        platform="windows-arm64",
        accelerator="cuda",
        filename="llama-b10976-bin-win-cuda-13.4-arm64.zip",
        sha256="08b3706607f9dd004cc36c0880f50f4520b4d16bb52195e5a233afe62ad52566",
        size=142_966_524,
        archive_members=("llama-server.exe", "LICENSE-LLVM-OpenMP"),
        runtime="cuda-13.4",
        companions=(_WINDOWS_ARM_CUDA_13_4_COMPANION,),
    ),
    "windows-arm64-opencl": _binary(
        profile="windows-arm64-opencl",
        platform="windows-arm64",
        accelerator="opencl",
        filename="llama-b10976-bin-win-opencl-adreno-arm64.zip",
        sha256="272dfee4e92cfc5cc2503af6f4ed19834415d870da5927d0820f5a6002e3700e",
        size=12_797_026,
        archive_members=("llama-server.exe", "LICENSE-LLVM-OpenMP"),
        runtime="opencl",
    ),
    "linux-x86_64-cpu": _binary(
        profile="linux-x86_64-cpu",
        platform="linux-x86_64",
        accelerator="cpu",
        filename="llama-b10976-bin-ubuntu-x64.tar.gz",
        sha256="bd70d0256c6f22356fc500327b81052c16cc684268581a8eb3848395980d9792",
        size=16_844_927,
        archive_members=("llama-b10976/llama-server", "llama-b10976/LICENSE"),
    ),
    "linux-x86_64-cuda": _binary(
        profile="linux-x86_64-cuda",
        platform="linux-x86_64",
        accelerator="cuda",
        filename="llama-b10976-bin-ubuntu-cuda-12.8-x64.tar.gz",
        sha256="4eeeb19a38624cdf339b61588c86c07a0d4ee320f58f48649f658717dfa075cb",
        size=168_843_699,
        archive_members=("llama-b10976/llama-server", "llama-b10976/LICENSE"),
        runtime="cuda-12.8",
        companions=(_LINUX_X64_CUDA_12_8_COMPANION,),
    ),
    "linux-x86_64-vulkan": _binary(
        profile="linux-x86_64-vulkan",
        platform="linux-x86_64",
        accelerator="vulkan",
        filename="llama-b10976-bin-ubuntu-vulkan-x64.tar.gz",
        sha256="bf5c969d34ce1dad3a00088aeb3279714fd538b5b1149c01edac0bec7bfb8f49",
        size=30_189_596,
        archive_members=("llama-b10976/llama-server", "llama-b10976/LICENSE"),
        runtime="vulkan",
    ),
    "linux-x86_64-rocm": _binary(
        profile="linux-x86_64-rocm",
        platform="linux-x86_64",
        accelerator="rocm",
        filename="llama-b10976-bin-ubuntu-rocm-10.0-x64.tar.gz",
        sha256="c0b22c62670e56f37379eff363ec9fef781845de3070d0f9b44d0a7b4214d028",
        size=238_986_144,
        archive_members=("llama-b10976/llama-server", "llama-b10976/LICENSE"),
        runtime="rocm-10.0",
    ),
    "linux-arm64-cpu": _binary(
        profile="linux-arm64-cpu",
        platform="linux-arm64",
        accelerator="cpu",
        filename="llama-b10976-bin-ubuntu-arm64.tar.gz",
        sha256="ed41c5fd09ae86dbe13e525a57549f1d27d51e7efdc9a9aa4583d42016be7786",
        size=13_469_344,
        archive_members=("llama-b10976/llama-server", "llama-b10976/LICENSE"),
    ),
    "linux-arm64-vulkan": _binary(
        profile="linux-arm64-vulkan",
        platform="linux-arm64",
        accelerator="vulkan",
        filename="llama-b10976-bin-ubuntu-vulkan-arm64.tar.gz",
        sha256="bbb89e4c3bda1fbdf47e277544e89ddfeff4a07711f16c3697fb7317272867cb",
        size=24_232_037,
        archive_members=("llama-b10976/llama-server", "llama-b10976/LICENSE"),
        runtime="vulkan",
    ),
    "linux-arm64-cuda": _binary(
        profile="linux-arm64-cuda",
        platform="linux-arm64",
        accelerator="cuda",
        filename="llama-b10976-bin-ubuntu-cuda-13.3-arm64.tar.gz",
        sha256="8a367e4438eca9251f4fd6c5f7cfd87aed40612295857b831651f6f5ba628430",
        size=144_978_375,
        archive_members=("llama-b10976/llama-server", "llama-b10976/LICENSE"),
        runtime="cuda-13.3",
        companions=(_LINUX_ARM_CUDA_13_3_COMPANION,),
    ),
}


def binary_for_profile(profile: str) -> BinarySpec:
    """Return an allow-listed archive, rejecting arbitrary profile input."""
    try:
        return BINARY_SPECS[profile]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"unsupported binary profile: {profile!r}") from exc


def companion_for_binary(
    profile: str | BinarySpec, kind: BinaryCompanionKind = "cudart"
) -> BinaryCompanionSpec:
    """Return one allow-listed companion required by a selected binary."""
    binary = binary_for_profile(profile) if isinstance(profile, str) else profile
    if not isinstance(binary, BinarySpec):
        raise TypeError("profile must be a supported binary profile or BinarySpec")
    try:
        return next(companion for companion in binary.companions if companion.kind == kind)
    except StopIteration as exc:
        raise ValueError(f"binary profile {binary.profile!r} has no {kind!r} companion") from exc


_LATEST_RELEASE_ATTEMPTS = 3
_LATEST_RELEASE_BACKOFF_SECONDS = (0.25, 0.75)


def _verified_release_asset(
    payload: object, filename: str, release_tag: str
) -> tuple[str, int, str]:
    """Return canonical URL, size and digest for one exact GitHub asset."""
    if not isinstance(payload, dict):
        raise ValueError("latest llama.cpp release could not be resolved")
    assets = payload.get("assets")
    if not isinstance(assets, list):
        raise ValueError("latest llama.cpp release has no assets")
    asset = next(
        (item for item in assets if isinstance(item, dict) and item.get("name") == filename),
        None,
    )
    if asset is None:
        raise ValueError("latest llama.cpp release does not support this hardware profile")
    expected_url = _binary_url(release_tag, filename)
    url = asset.get("browser_download_url")
    size = asset.get("size")
    digest = asset.get("digest")
    if (
        url != expected_url
        or isinstance(size, bool)
        or not isinstance(size, int)
        or size <= 0
        or not isinstance(digest, str)
        or not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest)
    ):
        raise ValueError("latest llama.cpp release asset metadata is invalid")
    return expected_url, size, digest.removeprefix("sha256:").lower()


def _resolve_latest_binary(binary: BinarySpec, payload: object) -> BinarySpec:
    if not isinstance(payload, dict):
        raise ValueError("latest llama.cpp release could not be resolved")
    tag = payload.get("tag_name")
    if not isinstance(tag, str) or not re.fullmatch(r"b\d+", tag):
        raise ValueError("latest llama.cpp release has an unsupported tag")
    expected_filename = binary.archive_filename.replace(binary.release_tag, tag, 1)
    if expected_filename == binary.archive_filename:
        raise ValueError("latest llama.cpp release asset could not be selected")
    url, size, digest = _verified_release_asset(payload, expected_filename, tag)
    companions = []
    for companion in binary.companions:
        companion_filename = companion.archive_filename.replace(companion.release_tag, tag, 1)
        companion_url, companion_size, companion_digest = _verified_release_asset(
            payload, companion_filename, tag
        )
        companions.append(
            replace(
                companion,
                archive_filename=companion_filename,
                archive_url=companion_url,
                archive_sha256=companion_digest,
                archive_bytes=companion_size,
                archive_members=tuple(
                    member.replace(companion.release_tag, tag, 1)
                    for member in companion.archive_members
                ),
                release_tag=tag,
            )
        )
    return replace(
        binary,
        archive_filename=expected_filename,
        archive_url=url,
        archive_sha256=digest,
        archive_bytes=size,
        archive_members=tuple(
            member.replace(binary.release_tag, tag, 1) for member in binary.archive_members
        ),
        release_tag=tag,
        companions=tuple(companions),
    )


def latest_binary_for_profile(profile: str | BinarySpec) -> BinarySpec:
    """Resolve one selected profile to GitHub's current verified release asset.

    This legacy resolver is deliberately not used by installation. Fresh
    installs use the pinned catalog entry as their compatibility contract.
    """
    binary = binary_for_profile(profile) if isinstance(profile, str) else profile
    if not isinstance(binary, BinarySpec):
        raise TypeError("profile must be a supported binary profile or BinarySpec")
    for attempt in range(_LATEST_RELEASE_ATTEMPTS):
        try:
            response = requests.get(
                _LLAMA_CPP_LATEST_RELEASE_URL,
                headers={"Accept": "application/vnd.github+json"},
                timeout=(10, 30),
            )
            response.raise_for_status()
            return _resolve_latest_binary(binary, response.json())
        except (requests.RequestException, ValueError, TypeError):
            if attempt < _LATEST_RELEASE_ATTEMPTS - 1:
                time.sleep(_LATEST_RELEASE_BACKOFF_SECONDS[attempt])
    return binary
