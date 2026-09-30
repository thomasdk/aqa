"""Pinned catalog and platform selection for the Local AI feature."""

from .catalog import (
    BINARY_SPECS,
    DEFAULT_MTP_DRAFT_TOKENS,
    DEFAULT_MTP_ENABLED,
    DEFAULT_PORT,
    IDLE_SLEEP_SECONDS,
    LOCAL_HOST,
    LOCAL_HOST_LABEL_PREFIX,
    MODELS,
    MTP_DRAFT_TOKEN_CHOICES,
    BinaryCompanionSpec,
    BinarySpec,
    ModelSpec,
    binary_for_profile,
    companion_for_binary,
    latest_binary_for_profile,
)
from .platform import HardwareProfile, detect_hardware_profile, select_binary

__all__ = [
    "BINARY_SPECS",
    "DEFAULT_MTP_DRAFT_TOKENS",
    "DEFAULT_MTP_ENABLED",
    "DEFAULT_PORT",
    "IDLE_SLEEP_SECONDS",
    "LOCAL_HOST",
    "LOCAL_HOST_LABEL_PREFIX",
    "MODELS",
    "MTP_DRAFT_TOKEN_CHOICES",
    "BinarySpec",
    "BinaryCompanionSpec",
    "BinaryCompanionSpec",
    "HardwareProfile",
    "ModelSpec",
    "binary_for_profile",
    "companion_for_binary",
    "detect_hardware_profile",
    "latest_binary_for_profile",
    "select_binary",
]
