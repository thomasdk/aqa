"""Pure platform normalization and conservative Local AI binary selection."""

from __future__ import annotations

import ctypes
import os
import platform as system_platform
import re
import shutil
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from .catalog import BINARY_SPECS, BinarySpec, binary_for_profile
from .process_launch import hidden_console_flags

CapabilityState = Literal["unknown", "cpu_confirmed", "gpu_candidate", "gpu_verified"]


@dataclass(frozen=True)
class HardwareProfile:
    """Detected facts used for selection, with no install side effects.

    ``gpu`` and ``driver_runtime`` contain raw probe vocabulary. The canonical
    GPU family is available as ``gpu_family`` and the selected executable is
    represented by ``BinarySpec.engine_name``. Runtime evidence is deliberately
    optional: an accelerator is never selected from a GPU label alone.
    """

    os: str
    arch: str
    gpu: str = "unknown"
    ram_gb: int | None = None
    vram_gb: int | None = None
    gpu_memory_kind: Literal["vram", "unified"] | None = None
    driver_runtime: str | None = None
    driver_runtime_compatible: bool | None = None
    selected_engine: str | None = None
    gpu_family: str | None = None
    cpu_name: str | None = None
    logical_cpu_count: int | None = None
    os_label: str | None = None
    cpu_label: str | None = None
    gpu_label: str | None = None
    gpu_adapters: tuple[str, ...] = ()
    capability_state: CapabilityState = "unknown"

    def __post_init__(self) -> None:
        if self.gpu_family is None:
            object.__setattr__(self, "gpu_family", _normalized_gpu(self.gpu))
        if self.os_label is None:
            object.__setattr__(self, "os_label", _display_os_label(self.os, self.arch))
        if self.cpu_label is None:
            object.__setattr__(
                self,
                "cpu_label",
                _display_cpu_label(self.cpu_name, self.logical_cpu_count, self.os, self.arch),
            )
        if self.capability_state == "unknown" and self.gpu_label:
            object.__setattr__(self, "capability_state", "gpu_candidate")
        if not self.gpu_adapters and self.gpu_label:
            object.__setattr__(self, "gpu_adapters", (self.gpu_label,))


@dataclass(frozen=True)
class RuntimeDevice:
    """One physical accelerator enumerated by the candidate llama.cpp runtime."""

    identifier: str
    name: str


@dataclass(frozen=True)
class RuntimeProbe:
    """Bounded result of invoking an exact runtime's device enumerator."""

    state: Literal["gpu_candidate", "cpu_only", "failed"]
    devices: tuple[RuntimeDevice, ...] = ()
    reason: (
        Literal[
            "no_gpu",
            "missing_runtime_library",
            "driver_unavailable",
            "probe_timeout",
            "probe_failed",
            "malformed_output",
        ]
        | None
    ) = None


@dataclass(frozen=True)
class InferenceMemory:
    """The memory pool used by one already-selected Local AI binary.

    ``gb`` remains optional because hardware probes are best-effort. ``kind``
    still describes the selected execution path when its capacity is unknown,
    which lets the UI truthfully say, for example, "Not reported" for VRAM.
    """

    gb: int | None
    kind: Literal["ram", "vram", "unified"] | None


def _normalized_os(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"darwin", "macos", "mac"}:
        return "macos"
    if normalized in {"windows", "win", "win32", "cygwin"}:
        return "windows"
    if normalized in {"linux", "ubuntu"}:
        return "linux"
    return normalized


def _normalized_arch(value: str) -> str:
    normalized = value.strip().lower().replace("-", "_")
    if normalized in {"amd64", "x64", "x86_64"}:
        return "x86_64"
    if normalized in {"aarch64", "arm64"}:
        return "arm64"
    return normalized


def _normalized_gpu(value: str) -> str:
    """Normalize vendor/backend labels to a conservative GPU family."""
    normalized = value.strip().lower().replace("_", "-")
    if normalized in {"metal", "apple", "apple-gpu", "apple-silicon"}:
        return "metal"
    if normalized in {"cuda", "nvidia", "nvidia-cuda", "nvidia-gpu"}:
        return "nvidia"
    if normalized in {
        "hip",
        "amd",
        "amd-gpu",
        "amd-radeon",
        "radeon",
        "rocm",
        "amd-rocm",
    }:
        return "amd"
    if normalized in {"cpu", "none", "unknown", "", "vulkan"}:
        return "unknown"
    return "unknown"


def _display_os_label(operating_system: str, architecture: str) -> str | None:
    normalized_os = _normalized_os(operating_system)
    if normalized_os == "macos":
        return "macOS (Apple Silicon)" if _normalized_arch(architecture) == "arm64" else "macOS"
    if normalized_os == "windows":
        return "Windows"
    if normalized_os == "linux":
        return "Linux"
    return None


def _display_cpu_label(
    cpu_name: str | None,
    _logical_cpu_count: int | None,
    operating_system: str,
    architecture: str,
) -> str | None:
    """Build a short browser-safe CPU label from bounded host facts."""
    name = " ".join(cpu_name.split()) if isinstance(cpu_name, str) else ""
    # CPU labels are display data, never command fragments or arbitrary probe output.
    name = re.sub(r"[^A-Za-z0-9 .+()_-]", "", name)[:100].strip()
    name = name.replace("--", "-")
    if (
        not name
        and _normalized_os(operating_system) == "macos"
        and _normalized_arch(architecture) == "arm64"
    ):
        name = "Apple Silicon"
    if name:
        return name
    return None


def _cpu_variant(binary: BinarySpec) -> BinarySpec:
    """Use a Metal-capable macOS archive in CPU mode when necessary."""
    return replace(binary, accelerator="cpu", runtime=None)


def _catalog_binary(profile_key: str) -> BinarySpec | None:
    """Return an optional catalog profile without treating an absent backend as fatal."""
    return BINARY_SPECS.get(profile_key)


def _runtime_text(profile: HardwareProfile) -> str:
    return (profile.driver_runtime or "").strip().lower()


def _runtime_matches(required: str | None, advertised: str) -> bool:
    """Match only the runtime family/version declared by the catalog."""
    if required is None:
        return True
    if not advertised:
        return False
    required = required.lower()
    if required.startswith("cuda-"):
        return bool(
            re.search(
                rf"cuda[^0-9]*{re.escape(required.removeprefix('cuda-'))}(?:[^0-9]|$)", advertised
            )
        )
    if required.startswith("rocm-"):
        return bool(
            re.search(
                rf"(?:rocm|hip)[^0-9]*{re.escape(required.removeprefix('rocm-'))}(?:[^0-9]|$)",
                advertised,
            )
        )
    if required == "rocm":
        return "rocm" in advertised or "hip" in advertised
    if required == "vulkan":
        return "vulkan" in advertised
    if required == "metal":
        return "metal" in advertised or "apple" in advertised
    return required in advertised


def binary_runtime_compatible(profile: HardwareProfile, binary: BinarySpec) -> bool:
    """Return whether a catalog binary has matching, explicitly safe runtime facts."""
    if binary.accelerator == "cpu":
        return True
    if (
        binary.accelerator == "metal"
        and _normalized_gpu(profile.gpu_family or profile.gpu) == "metal"
    ):
        return profile.driver_runtime_compatible is not False
    if profile.driver_runtime_compatible is not None:
        if not profile.driver_runtime_compatible:
            return False
        return not _runtime_text(profile) or _runtime_matches(
            binary.runtime, _runtime_text(profile)
        )
    return _runtime_matches(binary.runtime, _runtime_text(profile))


def _select_if_compatible(profile: HardwareProfile, profile_key: str) -> BinarySpec | None:
    candidate = binary_for_profile(profile_key)
    return candidate if binary_runtime_compatible(profile, candidate) else None


def _accelerated_or_vulkan(
    profile: HardwareProfile, accelerated_profile: str, vulkan_profile: str
) -> BinarySpec | None:
    """Return a validated accelerated asset, then a validated Vulkan asset."""

    accelerated = _select_if_compatible(profile, accelerated_profile)
    if accelerated is not None:
        return accelerated
    vulkan = _select_if_compatible(profile, vulkan_profile)
    return vulkan if vulkan is not None and _runtime_text(profile) == "vulkan" else None


def _select_windows_x86_64(profile: HardwareProfile, family: str) -> BinarySpec:
    """Select a Windows x86_64 asset from verified runtime evidence."""

    profiles = {"nvidia": "cuda", "amd": "rocm"}
    accelerated = profiles.get(family)
    if accelerated:
        selected = _accelerated_or_vulkan(
            profile, f"windows-x86_64-{accelerated}", "windows-x86_64-vulkan"
        )
        if selected is not None:
            return selected
    return binary_for_profile("windows-x86_64-cpu")


def _select_linux_x86_64(profile: HardwareProfile, family: str) -> BinarySpec:
    """Select a Linux x86_64 asset from verified runtime evidence."""

    if family == "amd":
        selected = _accelerated_or_vulkan(profile, "linux-x86_64-rocm", "linux-x86_64-vulkan")
        if selected is not None:
            return selected
    elif family == "nvidia":
        selected = _select_if_compatible(profile, "linux-x86_64-vulkan")
        if selected is not None and _runtime_text(profile) == "vulkan":
            return selected
    return binary_for_profile("linux-x86_64-cpu")


def select_binary(profile: HardwareProfile) -> BinarySpec:
    """Select a pinned release asset conservatively from validated evidence."""

    if not isinstance(profile, HardwareProfile):
        raise TypeError("profile must be a HardwareProfile")
    operating_system = _normalized_os(profile.os)
    architecture = _normalized_arch(profile.arch)
    family = _normalized_gpu(profile.gpu_family or profile.gpu)
    if operating_system == "macos" and architecture in {"arm64", "x86_64"}:
        if architecture == "x86_64":
            return binary_for_profile("macos-x86_64-cpu")
        metal = binary_for_profile("macos-arm64-metal")
        return (
            metal
            if family == "metal" and binary_runtime_compatible(profile, metal)
            else _cpu_variant(metal)
        )
    if architecture == "arm64" and operating_system in {"windows", "linux"}:
        return binary_candidates(profile)[0]
    if operating_system == "windows" and architecture == "x86_64":
        return _select_windows_x86_64(profile, family)
    if operating_system == "linux" and architecture == "x86_64":
        return _select_linux_x86_64(profile, family)
    raise ValueError(
        f"unsupported hardware profile: {profile.os!r}/{profile.arch!r}; "
        "supported binary profiles are macOS arm64/x86_64, Windows arm64/x86_64, "
        "and Linux arm64/x86_64"
    )


def binary_candidates(profile: HardwareProfile) -> tuple[BinarySpec, ...]:  # noqa: C901
    """Return bounded runtime candidates ordered by useful capability.

    Native hardware facts narrow the list, but do not prove acceleration. The
    caller must execute each non-CPU candidate and accept it only after
    :func:`parse_runtime_devices` reports a physical GPU.
    """
    if not isinstance(profile, HardwareProfile):
        raise TypeError("profile must be a HardwareProfile")
    operating_system = _normalized_os(profile.os)
    architecture = _normalized_arch(profile.arch)
    family = _normalized_gpu(profile.gpu_family or profile.gpu)
    adapter_text = " ".join(profile.gpu_adapters or ((profile.gpu_label or ""),)).lower()
    families = {family}
    if "nvidia" in adapter_text:
        families.add("nvidia")
    if "amd" in adapter_text or "radeon" in adapter_text:
        families.add("amd")
    keys: list[str] = []

    if operating_system == "macos" and architecture in {"arm64", "x86_64"}:
        if architecture == "x86_64":
            return (binary_for_profile("macos-x86_64-cpu"),)
        metal = binary_for_profile("macos-arm64-metal")
        if family == "metal" or profile.gpu_label:
            return (metal, _cpu_variant(metal))
        return (_cpu_variant(metal),)

    prefix = f"{operating_system}-{architecture}"
    if operating_system == "windows" and architecture == "x86_64":
        vendor_backends = (("amd", "rocm"), ("nvidia", "cuda"))
        if family != "amd":
            vendor_backends = tuple(reversed(vendor_backends))
        for vendor, backend in vendor_backends:
            if vendor in families and _catalog_binary(f"{prefix}-{backend}"):
                keys.append(f"{prefix}-{backend}")
        if "intel" in adapter_text:
            keys.append(f"{prefix}-sycl")
    elif operating_system == "windows" and architecture == "arm64":
        if "nvidia" in families and _catalog_binary(f"{prefix}-cuda"):
            keys.append(f"{prefix}-cuda")
        if any(vendor in adapter_text for vendor in ("qualcomm", "adreno")):
            keys.append(f"{prefix}-opencl")
    elif operating_system == "linux" and architecture == "x86_64":
        vendor_backends = (("amd", "rocm"), ("nvidia", "cuda"))
        if family != "amd":
            vendor_backends = tuple(reversed(vendor_backends))
        for vendor, backend in vendor_backends:
            if vendor in families and _catalog_binary(f"{prefix}-{backend}"):
                keys.append(f"{prefix}-{backend}")
    elif operating_system == "linux" and architecture == "arm64":
        if "nvidia" in families and _catalog_binary(f"{prefix}-cuda"):
            keys.append(f"{prefix}-cuda")

    # Vulkan remains a broad physical-GPU candidate, including Intel and
    # unknown vendors. It is not attempted when no native GPU fact exists.
    if (
        profile.gpu_adapters
        or profile.gpu_label
        or families & {"nvidia", "amd"}
        or _runtime_text(profile) == "vulkan"
    ):
        if _catalog_binary(f"{prefix}-vulkan"):
            keys.append(f"{prefix}-vulkan")

    cpu_key = f"{prefix}-cpu"
    if _catalog_binary(cpu_key):
        keys.append(cpu_key)
    if not keys:
        # Keep the public unsupported-platform error and its complete six-target wording.
        select_binary(profile)
    return tuple(binary_for_profile(key) for key in dict.fromkeys(keys))


_SOFTWARE_DEVICE_MARKERS = (
    "llvmpipe",
    "swiftshader",
    "microsoft basic render",
    "software rasterizer",
    "lavapipe",
)

_FAILED_DEVICE_MARKERS = (
    "failed",
    "error",
    "not found",
    "not detected",
    "no compatible",
    "no cuda-capable",
    "unavailable",
    "unsupported",
)


def parse_runtime_devices(output: str, *, returncode: int = 0) -> RuntimeProbe:
    """Parse ``llama-server --list-devices`` without trusting vendor labels.

    llama.cpp emits backend-qualified identifiers followed by a human-readable
    description. CPU and known software renderers are rejected. A successful
    empty enumeration is CPU-only evidence only for the exact executable that
    produced it; a non-zero exit is a failed probe, never CPU confirmation.
    """
    if not isinstance(output, str):
        return RuntimeProbe("failed", reason="malformed_output")
    lowered = output.lower()
    if returncode != 0:
        reason = "driver_unavailable" if "driver" in lowered else "probe_failed"
        return RuntimeProbe("failed", reason=reason)
    devices: list[RuntimeDevice] = []
    for raw_line in output.splitlines():
        line = " ".join(raw_line.strip().split())
        if not line or any(
            marker in line.lower()
            for marker in (*_SOFTWARE_DEVICE_MARKERS, *_FAILED_DEVICE_MARKERS)
        ):
            continue
        match = re.match(
            r"^\s*((?:Metal|MTL[0-9]+|CUDA[0-9]+|ROCm[0-9]+|HIP[0-9]+|"
            r"Vulkan[0-9]+|SYCL[0-9]+|OpenCL[0-9]+))"
            r"\s*(?:\||-|:)\s*(.+)$",
            line,
            re.IGNORECASE,
        )
        if match is None:
            continue
        identifier, name = match.groups()
        lowered = f"{identifier} {name}".lower()
        if "cpu" in lowered or "npu" in lowered or "remote" in lowered:
            continue
        safe_name = re.sub(r"[^A-Za-z0-9 .+()_-]", "", name)[:120].strip()
        if safe_name:
            devices.append(RuntimeDevice(identifier=identifier[:80], name=safe_name))
    if devices:
        return RuntimeProbe("gpu_candidate", tuple(devices))
    if any(marker in lowered for marker in _FAILED_DEVICE_MARKERS):
        reason = (
            "driver_unavailable"
            if "driver" in lowered
            else "no_gpu"
            if "no compatible" in lowered or "not detected" in lowered
            else "probe_failed"
        )
        return RuntimeProbe("failed", reason=reason)
    if "available devices:" not in lowered:
        return RuntimeProbe("failed", reason="malformed_output")
    return RuntimeProbe("cpu_only", reason="no_gpu")


def _probe_command(command: str, *arguments: str) -> str:
    executable = shutil.which(command)
    if executable is None:
        return ""
    try:
        completed = subprocess.run(
            [executable, *arguments],
            check=False,
            capture_output=True,
            text=True,
            timeout=1.0,
            shell=False,
            **({"creationflags": hidden_console_flags()} if os.name == "nt" else {}),
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return f"{completed.stdout}\n{completed.stderr}".lower()


def _probe_successful_stdout(command: str, *arguments: str) -> str:
    """Return successful command stdout without mixing errors or changing display casing."""
    executable = shutil.which(command)
    if executable is None:
        return ""
    try:
        completed = subprocess.run(
            [executable, *arguments],
            check=False,
            capture_output=True,
            text=True,
            timeout=1.0,
            shell=False,
            **({"creationflags": hidden_console_flags()} if os.name == "nt" else {}),
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    stdout = completed.stdout if isinstance(completed.stdout, str) else ""
    stderr = completed.stderr if isinstance(completed.stderr, str) else ""
    if completed.returncode != 0 or stderr.strip():
        return ""
    return stdout


def _safe_gpu_label(value: str) -> str | None:
    label = " ".join(value.split())
    if not label or any(marker in label.lower() for marker in _SOFTWARE_DEVICE_MARKERS):
        return None
    label = re.sub(r"[^A-Za-z0-9 .+()_-]", "", label)[:120].strip()
    return label or None


def _gpu_family_from_label(label: str | None) -> str:
    lowered = (label or "").lower()
    if "nvidia" in lowered:
        return "nvidia"
    if "amd" in lowered or "radeon" in lowered:
        return "amd"
    if "apple" in lowered:
        return "metal"
    return "unknown"


def _physical_gpu_labels(operating_system: str, architecture: str) -> tuple[str, ...]:
    """Read sanitized physical-adapter labels from dependency-free OS facts."""
    if operating_system == "macos":
        if architecture == "arm64":
            return ("Apple Silicon GPU",)
        output = _probe_command("system_profiler", "SPDisplaysDataType", "-json")
        labels: list[str] = []
        for key in ("sppci_model", "_name"):
            for match in re.finditer(rf'"{key}"\s*:\s*"([^"]+)"', output, re.IGNORECASE):
                if label := _safe_gpu_label(match.group(1)):
                    labels.append(label)
        return tuple(dict.fromkeys(labels))
    if operating_system == "windows":
        # PowerShell and CIM are standard Windows facilities, unlike SDK tools.
        output = _probe_successful_stdout(
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name",
        )
        if re.search(
            r"get-ciminstance|categoryinfo|fullyqualifiederrorid|exception",
            output,
            re.IGNORECASE,
        ):
            return ()
        return tuple(label for line in output.splitlines() if (label := _safe_gpu_label(line)))
    if operating_system == "linux":
        vendor_names = {
            "0x1002": "AMD Graphics",
            "0x10de": "NVIDIA Graphics",
            "0x8086": "Intel Graphics",
            "0x5143": "Qualcomm Graphics",
        }
        labels = []
        for vendor_path in sorted(Path("/sys/class/drm").glob("card[0-9]*/device/vendor")):
            try:
                vendor = vendor_path.read_text(encoding="ascii").strip().lower()
            except OSError:
                continue
            if label := vendor_names.get(vendor):
                labels.append(label)
            elif re.fullmatch(r"0x[0-9a-f]{4}", vendor):
                labels.append("Graphics Adapter")
        return tuple(labels)
    return ()


def _preferred_gpu_label(labels: tuple[str, ...]) -> str | None:
    """Keep the UI concise while preferring a discrete adapter label."""
    priorities = ("nvidia", "amd", "radeon", "apple", "qualcomm", "adreno", "intel")
    return next(
        (label for marker in priorities for label in labels if marker in label.lower()),
        labels[0] if labels else None,
    )


def _runtime_from_probe(output: str, family: str) -> str | None:
    output = output.lower()
    if family == "nvidia":
        match = re.search(r"cuda(?:\s+version)?\s*[:=]?\s*([0-9]+\.[0-9]+)", output)
        return f"cuda-{match.group(1)}" if match else None
    if family == "amd":
        match = re.search(r"(?:rocm|hip)[^0-9]*([0-9]+\.[0-9]+)", output)
        return f"rocm-{match.group(1)}" if match else "rocm"
    return None


def _probe_supports_profile(
    operating_system: str,
    architecture: str,
    family: str,
    runtime: str | None,
) -> bool:
    """Return whether probe evidence matches an accelerated catalog profile."""
    if architecture != "x86_64" or not runtime:
        return False
    profile_key: str | None = None
    if operating_system == "windows" and family == "nvidia":
        profile_key = "windows-x86_64-cuda"
    elif operating_system == "windows" and family == "amd":
        profile_key = "windows-x86_64-rocm"
    elif operating_system == "linux" and family == "amd":
        profile_key = "linux-x86_64-rocm"
    if profile_key is None:
        return False
    return _runtime_matches(binary_for_profile(profile_key).runtime, runtime)


def _vulkan_family(output: str) -> str | None:
    """Extract only GPU vendors for which AQA publishes Vulkan binaries."""
    lowered = output.lower()
    if "nvidia" in lowered:
        return "nvidia"
    if "amd" in lowered or "radeon" in lowered:
        return "amd"
    return None


def _detected_gpu(operating_system: str, architecture: str) -> tuple[str, str | None]:
    if operating_system == "macos" and architecture == "arm64":
        return "metal", "metal"

    if operating_system == "macos" and architecture == "x86_64":
        # JSON uses stable schema values even when the user's macOS UI is not
        # English (plain system_profiler labels are localized).
        displays = _probe_command("system_profiler", "SPDisplaysDataType", "-json")
        supported_metal = re.search(
            r'"spdisplays_metal"\s*:\s*"spdisplays_supported"', displays.lower()
        )
        return ("metal", "metal") if supported_metal else ("unknown", None)

    # Plain nvidia-smi reports both the installed GPU and the driver's CUDA
    # runtime version (for example ``CUDA Version: 12.4``). ``-L`` reports only
    # GPU names and must not be used as version evidence.
    nvidia = _probe_command("nvidia-smi")
    nvidia_runtime = _runtime_from_probe(nvidia, "nvidia") if nvidia else None

    amd = _probe_command("rocminfo")
    hip_version = _probe_command("hipconfig", "--version") if amd else ""
    amd_runtime = _runtime_from_probe(f"{amd}\n{hip_version}", "amd") if amd else None

    # Vulkan is intentionally probed even when NVIDIA or ROCm tooling exists:
    # it is the safe accelerated fallback when the primary runtime does not
    # match the binary currently published by AQA.
    vulkan = _probe_command("vulkaninfo", "--summary")
    vulkan_family = _vulkan_family(vulkan)

    if nvidia:
        if _probe_supports_profile(operating_system, architecture, "nvidia", nvidia_runtime):
            return "cuda", nvidia_runtime
        if vulkan_family == "nvidia":
            return "nvidia", "vulkan"
        return "nvidia", nvidia_runtime

    if amd:
        if _probe_supports_profile(operating_system, architecture, "amd", amd_runtime):
            return "rocm", amd_runtime
        if vulkan_family == "amd":
            return "amd", "vulkan"
        return "rocm", amd_runtime

    if vulkan_family is not None:
        return vulkan_family, "vulkan"

    return "unknown", None


def _sysctl_value(name: str) -> str:
    """Read one macOS sysctl value without exposing command output elsewhere."""
    executable = shutil.which("sysctl")
    if executable is None:
        return ""
    try:
        completed = subprocess.run(
            [executable, "-n", name],
            check=False,
            capture_output=True,
            text=True,
            timeout=1.0,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return completed.stdout.strip()


def _positive_integer(value: str) -> int | None:
    try:
        result = int(value.strip())
    except (AttributeError, TypeError, ValueError):
        return None
    return result if result > 0 else None


_GIB = 1024**3


def _whole_gib(memory_bytes: int | None) -> int | None:
    """Round a physical capacity to its nominal whole-GiB value."""
    if not isinstance(memory_bytes, int) or isinstance(memory_bytes, bool) or memory_bytes < 1:
        return None
    return max(1, (memory_bytes + (_GIB // 2)) // _GIB)


def _windows_total_physical_memory_bytes() -> int | None:
    """Read Windows physical RAM with GlobalMemoryStatusEx, without a shell probe."""
    if _normalized_os(system_platform.system()) != "windows":
        return None

    class MemoryStatusEx(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    try:
        status = MemoryStatusEx()
        status.dwLength = ctypes.sizeof(status)
        kernel32 = ctypes.windll.kernel32
        if not kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None
    except (AttributeError, OSError):
        return None
    return int(status.ullTotalPhys) if status.ullTotalPhys > 0 else None


def _linux_meminfo_total_bytes() -> int | None:
    """Use MemTotal only when sysconf cannot report physical memory."""
    try:
        contents = Path("/proc/meminfo").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    match = re.search(r"^MemTotal:\s*([0-9]+)\s*kB\s*$", contents, re.MULTILINE | re.IGNORECASE)
    if match is None:
        return None
    total_kb = _positive_integer(match.group(1))
    return total_kb * 1024 if total_kb is not None else None


def _memory_bytes_from_text(value: str, *, default_unit: str | None = None) -> list[int]:
    """Parse bounded byte capacities from normal hardware-tool output."""
    units = {
        "b": 1,
        "kb": 1000,
        "kib": 1024,
        "mb": 1000**2,
        "mib": 1024**2,
        "gb": 1000**3,
        "gib": _GIB,
    }
    default_multiplier = units.get(default_unit or "")
    found: list[int] = []
    for match in re.finditer(r"(?<![0-9])([0-9]+)(?:\s*([kmgt]?i?b))?(?![a-z0-9])", value.lower()):
        amount = _positive_integer(match.group(1))
        unit = match.group(2)
        multiplier = units.get(unit) if unit else default_multiplier
        if amount is not None and multiplier is not None:
            found.append(amount * multiplier)
    return found


def _nvidia_vram_bytes() -> int | None:
    """Return the largest one-GPU NVIDIA memory capacity, never their sum."""
    output = _probe_command(
        "nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"
    )
    values = _memory_bytes_from_text(output, default_unit="mib")
    return max(values, default=None)


def _windows_gpu_memory() -> tuple[int | None, bool]:
    """Read dedicated and shared GPU-memory facts through DXGI on Windows.

    The COM calls intentionally use only the small DXGI adapter-description
    surface. A failed driver call is ordinary probe failure, never setup failure.
    """
    if _normalized_os(system_platform.system()) != "windows":
        return None, False

    class Guid(ctypes.Structure):
        _fields_ = [
            ("Data1", ctypes.c_ulong),
            ("Data2", ctypes.c_ushort),
            ("Data3", ctypes.c_ushort),
            ("Data4", ctypes.c_ubyte * 8),
        ]

    class Luid(ctypes.Structure):
        _fields_ = [("LowPart", ctypes.c_ulong), ("HighPart", ctypes.c_long)]

    class AdapterDesc1(ctypes.Structure):
        _fields_ = [
            ("Description", ctypes.c_wchar * 128),
            ("VendorId", ctypes.c_uint),
            ("DeviceId", ctypes.c_uint),
            ("SubSysId", ctypes.c_uint),
            ("Revision", ctypes.c_uint),
            ("DedicatedVideoMemory", ctypes.c_size_t),
            ("DedicatedSystemMemory", ctypes.c_size_t),
            ("SharedSystemMemory", ctypes.c_size_t),
            ("AdapterLuid", Luid),
            ("Flags", ctypes.c_uint),
        ]

    # IDXGIFactory1 and IDXGIAdapter1 inherit the first IUnknown methods.
    release_index = 2
    enum_adapters1_index = 12
    get_desc1_index = 10
    dxgi_error_not_found = 0x887A0002
    software_adapter = 0x2
    iid_factory1 = Guid(
        0x770AAE78,
        0xF26F,
        0x4DBA,
        (ctypes.c_ubyte * 8)(0xA8, 0x29, 0x25, 0x3C, 0x83, 0xD1, 0xB3, 0x87),
    )
    factory = ctypes.c_void_p()
    try:
        create_factory = ctypes.windll.dxgi.CreateDXGIFactory1
        create_factory.argtypes = [ctypes.POINTER(Guid), ctypes.POINTER(ctypes.c_void_p)]
        create_factory.restype = ctypes.c_long
        if create_factory(ctypes.byref(iid_factory1), ctypes.byref(factory)) != 0 or not factory:
            return None, False

        vtable = ctypes.cast(factory, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        enum_adapters1 = ctypes.WINFUNCTYPE(
            ctypes.c_long, ctypes.c_void_p, ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p)
        )(vtable[enum_adapters1_index])
        release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[release_index])
        largest_dedicated: int | None = None
        has_shared_memory = False
        index = 0
        while True:
            adapter = ctypes.c_void_p()
            result = enum_adapters1(factory, index, ctypes.byref(adapter))
            if (
                result == dxgi_error_not_found
                or result == ctypes.c_long(dxgi_error_not_found).value
            ):
                break
            if result != 0 or not adapter:
                break
            try:
                adapter_vtable = ctypes.cast(
                    adapter, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))
                ).contents
                get_desc1 = ctypes.WINFUNCTYPE(
                    ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(AdapterDesc1)
                )(adapter_vtable[get_desc1_index])
                description = AdapterDesc1()
                if get_desc1(adapter, ctypes.byref(description)) == 0 and not (
                    description.Flags & software_adapter
                ):
                    dedicated = int(description.DedicatedVideoMemory)
                    if dedicated > 0:
                        largest_dedicated = max(largest_dedicated or 0, dedicated)
                    has_shared_memory = has_shared_memory or description.SharedSystemMemory > 0
            finally:
                adapter_vtable = ctypes.cast(
                    adapter, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))
                ).contents
                ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(adapter_vtable[release_index])(
                    adapter
                )
            index += 1
        release(factory)
        return largest_dedicated, has_shared_memory
    except (AttributeError, OSError, ValueError):
        return None, False


def _linux_amd_drm_vram_bytes() -> int | None:
    """Read AMD VRAM counters exposed by the kernel DRM driver."""
    values: list[int] = []
    for path in Path("/sys/class/drm").glob("card*/device/mem_info_vram_total"):
        try:
            memory_bytes = _positive_integer(path.read_text(encoding="utf-8").strip())
        except OSError:
            continue
        if memory_bytes is not None:
            values.append(memory_bytes)
    return max(values, default=None)


def _rocm_vram_bytes() -> int | None:
    """Fallback for AMD VRAM when DRM counters are unavailable."""
    output = _probe_command("rocm-smi", "--showmeminfo", "vram")
    values = _memory_bytes_from_text(output)
    return max(values, default=None)


def _vulkan_device_local_memory_bytes() -> int | None:
    """Extract the largest device-local heap from vulkaninfo's full report."""
    output = _probe_command("vulkaninfo")
    values: list[int] = []
    for block in re.split(r"(?=memoryHeaps\[|heapSize\s*=)", output, flags=re.IGNORECASE):
        if "device_local" not in block.lower():
            continue
        match = re.search(r"(?:heapSize|size)\s*=\s*([0-9]+)", block, re.IGNORECASE)
        if match is not None:
            value = _positive_integer(match.group(1))
            if value is not None:
                values.append(value)
    return max(values, default=None)


def _macos_gpu_memory() -> tuple[int | None, bool]:
    """Inspect stable system_profiler JSON keys for Intel Mac GPU memory."""
    output = _probe_command("system_profiler", "SPDisplaysDataType", "-json")
    if not output:
        return None, False
    values: list[int] = []
    for match in re.finditer(r'"spdisplays_vram"\s*:\s*"([^"]+)"', output):
        values.extend(_memory_bytes_from_text(match.group(1)))
    return max(values, default=None), '"spdisplays_vram_shared"' in output


def _detected_gpu_memory(
    operating_system: str,
    architecture: str,
    gpu_family: str,
    gpu_adapters: tuple[str, ...] = (),
) -> tuple[int | None, Literal["vram", "unified"] | None]:
    """Return capacity and pool type for the accelerated device, if observable."""
    if operating_system == "macos":
        if architecture == "arm64":
            return None, "unified"
        memory_bytes, shared = _macos_gpu_memory()
        return _whole_gib(memory_bytes), "unified" if shared else "vram"

    # Host-wide maximum queries cannot identify which adapter owns the value.
    # With multiple physical adapters, omit it until an authoritative per-device
    # mapping is available from the selected runtime.
    if len(gpu_adapters) > 1:
        return None, None

    if operating_system == "windows":
        nvidia_bytes = _nvidia_vram_bytes() if gpu_family == "nvidia" else None
        dxgi_bytes, has_shared_memory = _windows_gpu_memory()
        memory_bytes = nvidia_bytes or dxgi_bytes
        if memory_bytes is not None:
            return _whole_gib(memory_bytes), "vram"
        return None, "unified" if has_shared_memory else None

    if operating_system == "linux":
        if gpu_family == "nvidia":
            memory_bytes = _nvidia_vram_bytes()
        elif gpu_family == "amd":
            memory_bytes = _linux_amd_drm_vram_bytes() or _rocm_vram_bytes()
        else:
            memory_bytes = None
        memory_bytes = memory_bytes or _vulkan_device_local_memory_bytes()
        return (_whole_gib(memory_bytes), "vram") if memory_bytes is not None else (None, None)

    return None, None


def _detected_cpu(operating_system: str) -> tuple[str | None, int | None]:
    """Return a bounded processor label source and logical core count."""
    core_count = os.cpu_count()
    if not isinstance(core_count, int) or core_count < 1:
        core_count = None
    cpu_name = system_platform.processor() or None
    if operating_system == "macos":
        cpu_name = _sysctl_value("machdep.cpu.brand_string") or cpu_name
        core_count = _positive_integer(_sysctl_value("hw.ncpu")) or core_count
    return cpu_name, core_count


def _detected_ram_gb(operating_system: str) -> int | None:
    """Return physical RAM using native OS facts and conservative fallbacks."""
    if operating_system == "windows":
        memory_bytes = _windows_total_physical_memory_bytes()
        if memory_bytes is not None:
            return _whole_gib(memory_bytes)
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        if pages > 0 and page_size > 0:
            return _whole_gib(pages * page_size)
    except (AttributeError, OSError, TypeError, ValueError):
        pass
    if operating_system == "linux":
        memory_bytes = _linux_meminfo_total_bytes()
        if memory_bytes is not None:
            return _whole_gib(memory_bytes)
    if operating_system == "macos":
        memory_bytes = _positive_integer(_sysctl_value("hw.memsize"))
        if memory_bytes is not None:
            return _whole_gib(memory_bytes)
    return None


def inference_memory_for_binary(profile: HardwareProfile, binary: BinarySpec) -> InferenceMemory:
    """Resolve the memory pool for an explicit, already-selected binary.

    Callers deliberately provide ``binary``: installed and candidate runtimes
    can differ, and status/UI data must describe the executable that
    will really be used rather than whichever accelerator the host advertises.
    """
    if not isinstance(profile, HardwareProfile):
        raise TypeError("profile must be a HardwareProfile")
    if not isinstance(binary, BinarySpec):
        raise TypeError("binary must be a BinarySpec")

    if binary.accelerator == "cpu":
        return InferenceMemory(gb=profile.ram_gb, kind="ram")
    if binary.accelerator == "metal" and _normalized_arch(profile.arch) == "arm64":
        return InferenceMemory(gb=profile.ram_gb, kind="unified")
    if profile.gpu_memory_kind == "unified":
        return InferenceMemory(gb=profile.ram_gb, kind="unified")
    return InferenceMemory(gb=profile.vram_gb, kind="vram")


def detect_hardware_profile() -> HardwareProfile:
    """Inspect harmless host facts without downloading, installing, or starting anything."""
    operating_system = system_platform.system()
    architecture = system_platform.machine()
    normalized_os = _normalized_os(operating_system)
    normalized_architecture = _normalized_arch(architecture)
    detected_gpu, detected_runtime = _detected_gpu(normalized_os, normalized_architecture)
    gpu_adapters = _physical_gpu_labels(normalized_os, normalized_architecture)
    gpu_label = _preferred_gpu_label(gpu_adapters)
    gpu_family = _normalized_gpu(detected_gpu)
    if gpu_family == "unknown":
        gpu_family = _gpu_family_from_label(gpu_label)
    cpu_name, logical_cpu_count = _detected_cpu(normalized_os)
    if normalized_os == "macos" and normalized_architecture == "arm64":
        gpu_label = _safe_gpu_label(f"{cpu_name or 'Apple M-series'} GPU")
    vram_gb, gpu_memory_kind = _detected_gpu_memory(
        normalized_os, normalized_architecture, gpu_family, gpu_adapters
    )
    return HardwareProfile(
        os=operating_system,
        arch=architecture,
        gpu=detected_gpu,
        gpu_family=gpu_family,
        driver_runtime=detected_runtime,
        ram_gb=_detected_ram_gb(normalized_os),
        vram_gb=vram_gb,
        gpu_memory_kind=gpu_memory_kind,
        gpu_label=gpu_label,
        gpu_adapters=gpu_adapters,
        capability_state="gpu_candidate" if gpu_label else "unknown",
        cpu_name=cpu_name,
        logical_cpu_count=logical_cpu_count,
    )
