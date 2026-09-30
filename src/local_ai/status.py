"""Path-free Local AI status contract shared by service and API layers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LocalAIStatus:
    """The deliberately small, path-free status exposed to API callers."""

    state: str = "not_installed"
    model_id: str | None = None
    model_name: str | None = None
    host: str | None = None
    port: int | None = None
    context_tokens: int | None = None
    mtp_enabled: bool = False
    mtp_draft_tokens: int | None = None
    accelerator: str | None = None
    downloaded_bytes: int = 0
    total_bytes: int = 0
    available_disk_bytes: int | None = None
    download_phase: str | None = None
    import_bytes: int = 0
    import_total: int = 0
    import_phase: str | None = None
    job_id: str | None = None
    operation_kind: str | None = None
    operation_state: str | None = None
    operation_model_id: str | None = None
    error_code: str | None = None
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return only fields safe to serialize to the browser."""

        return {
            "state": self.state,
            "model_id": self.model_id,
            "model_name": self.model_name,
            "host": self.host,
            "port": self.port,
            "context_tokens": self.context_tokens,
            "mtp_enabled": self.mtp_enabled,
            "mtp_draft_tokens": self.mtp_draft_tokens,
            "accelerator": self.accelerator,
            "downloaded_bytes": self.downloaded_bytes,
            "total_bytes": self.total_bytes,
            "available_disk_bytes": self.available_disk_bytes,
            "download_phase": self.download_phase,
            "import_bytes": self.import_bytes,
            "import_total": self.import_total,
            "import_phase": self.import_phase,
            "job_id": self.job_id,
            "operation_kind": self.operation_kind,
            "operation_state": self.operation_state,
            "operation_model_id": self.operation_model_id,
            "error_code": self.error_code,
            "message": self.message,
        }


__all__ = ["LocalAIStatus"]
