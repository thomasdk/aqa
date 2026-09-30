"""Internal Local AI installation and import job records."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path


@dataclass
class InstallJob:
    job_id: str
    model_id: str
    start_after_install: bool
    cancel_event: threading.Event
    cpu_fallback: bool = False
    context_tokens: int | None = None
    mtp_enabled: bool = False
    mtp_draft_tokens: int = 4
    readiness_model_id: str | None = None


@dataclass
class ImportSession:
    """Private staging locations for one browser-to-localhost model import."""

    import_id: str
    model_id: str
    directory: Path
    main_part: Path
    draft_part: Path


@dataclass
class BackgroundImportJob:
    """A server-owned copy operation from a selected portable bundle.

    The job owns the transfer after source selection, so a browser-tab reload
    cannot interrupt it.
    """

    job_id: str
    session: ImportSession
    source_main: Path
    source_draft: Path
    cancel_event: threading.Event


__all__ = ["BackgroundImportJob", "ImportSession", "InstallJob"]
