from __future__ import annotations

import pytest

from src.local_ai.platform import parse_runtime_devices


@pytest.mark.parametrize(
    ("line", "identifier"),
    [
        ("Metal: Apple M4 Pro", "Metal"),
        ("CUDA0: NVIDIA RTX 5090", "CUDA0"),
        ("ROCm0: AMD Radeon PRO W7900", "ROCm0"),
        ("HIP0: AMD Radeon RX 7900 XTX", "HIP0"),
        ("Vulkan0: Intel Arc A770", "Vulkan0"),
        ("SYCL0: Intel Arc A770", "SYCL0"),
        ("OpenCL0: Qualcomm Adreno X1", "OpenCL0"),
    ],
)
def test_runtime_device_parser_accepts_physical_catalog_backend_devices(
    line: str, identifier: str
) -> None:
    probe = parse_runtime_devices(line)

    assert probe.state == "gpu_candidate"
    assert probe.devices[0].identifier == identifier


@pytest.mark.parametrize(
    "line",
    [
        "CUDA0: no CUDA-capable device is detected",
        "ROCm0: backend unavailable",
        "HIP0: failed to initialize device",
        "Vulkan0: unsupported driver",
        "SYCL0: device not found",
        "OpenCL0: initialization error",
        "Vulkan0: llvmpipe (LLVM software rasterizer)",
    ],
)
def test_runtime_device_parser_never_promotes_failure_or_software_text(line: str) -> None:
    assert parse_runtime_devices(line).state == "failed"
