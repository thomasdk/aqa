"""Resolve mutable application data separately from shipped application files."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
from pathlib import Path

from src import __version__

# All mutable-data writers in this process use this re-entrant barrier.  Keep
# it defined before importing the prompt package: ``src.prompts`` re-exports
# session types, which use the same lock during their module initialization.
mutable_data_lock = threading.RLock()

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
USER_DATA_FORMAT_VERSION = 1
_SYNC_PROMPTS_FROM_SOURCE_ENV = "AQA_SYNC_PROMPTS_FROM_SOURCE"


def _override(name: str) -> Path | None:
    value = os.environ.get(name)
    return Path(value).expanduser().resolve() if value else None


def user_data_dir() -> Path | None:
    """Return the configured user-data root, if one is set."""

    return _override("AQA_USER_DATA_DIR")


def _packaged_user_data_dir() -> Path | None:
    """Return the packaged root, rejecting an incomplete environment."""

    if os.environ.get("AQA_PACKAGED_MODE") != "1":
        return None
    root = user_data_dir()
    if root is None:
        raise RuntimeError("AQA_PACKAGED_MODE requires AQA_USER_DATA_DIR")
    return root


def settings_path() -> Path:
    packaged_root = _packaged_user_data_dir()
    if packaged_root is not None:
        return packaged_root / "settings.json"
    explicit = _override("AQA_SETTINGS_PATH")
    if explicit is not None:
        return explicit
    root = user_data_dir()
    return root / "settings.json" if root is not None else (_PROJECT_ROOT / "data/settings.json")


def conversations_dir() -> Path:
    packaged_root = _packaged_user_data_dir()
    if packaged_root is not None:
        return packaged_root / "conversations"
    explicit = _override("AQA_CONVERSATIONS_DIR")
    if explicit is not None:
        return explicit
    root = user_data_dir()
    return root / "conversations" if root is not None else (_PROJECT_ROOT / "conversations")


def prompt_library_dir() -> Path:
    packaged_root = _packaged_user_data_dir()
    if packaged_root is not None:
        return packaged_root / "prompts"
    explicit = _override("PROMPT_LIBRARY_PATH")
    if explicit is not None:
        return explicit
    root = user_data_dir()
    return root / "prompts" if root is not None else (_PROJECT_ROOT / "data/prompts")


def prompt_defaults_dir() -> Path:
    """Return the immutable shipped prompt baseline, never the mutable user tree."""

    # A packaged app must always compare against its own shipped baseline.
    # Inherited development overrides would otherwise change import provenance
    # and default restoration outside the bundle.
    if _packaged_user_data_dir() is not None:
        return _PROJECT_ROOT / "data/prompt_defaults"
    explicit = _override("AQA_PROMPT_DEFAULTS_DIR")
    return explicit if explicit is not None else (_PROJECT_ROOT / "data/prompt_defaults")


def local_ai_dir_path() -> Path | None:
    """Return a configured Local AI root, leaving native per-user defaults untouched."""

    packaged_root = _packaged_user_data_dir()
    if packaged_root is not None:
        return packaged_root / "local-ai"
    explicit = _override("AQA_LOCAL_AI_DIR")
    if explicit is not None:
        return explicit
    root = user_data_dir()
    return root / "local-ai" if root is not None else None


def _fsync_directory(directory: Path) -> None:
    """Persist a directory entry after rename/unlink where the OS supports it."""

    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except OSError:
        # Windows does not expose directory handles through ``os.open``.
        # File replacement is still atomic there; POSIX packaged apps get
        # the stronger directory-durability guarantee.
        if os.name == "nt":
            return
        raise
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}-", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _atomic_copy(source: Path, destination: Path) -> None:
    """Durably replace ``destination`` with a copy of ``source``."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}-", suffix=".tmp", dir=destination.parent
    )
    temporary = Path(temporary_name)
    try:
        with source.open("rb") as reader, os.fdopen(fd, "wb") as writer:
            shutil.copyfileobj(reader, writer)
            writer.flush()
            os.fsync(writer.fileno())
        shutil.copystat(source, temporary, follow_symlinks=False)
        os.replace(temporary, destination)
        _fsync_directory(destination.parent)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _replace_prompts_from_source(prompts: Path, shipped: Path) -> None:
    """Replace the editable prompt tree after a complete source copy succeeds.

    This development-only path keeps a source checkout's test instance exact:
    the active ``User Data/prompts`` tree mirrors ``data/prompts`` on every
    launcher start. The existing tree stays in an operation-local backup until the
    replacement has been installed, so a copy failure cannot leave a partial
    prompt library behind.
    """

    operation_root = Path(tempfile.mkdtemp(prefix=".prompts-source-sync-", dir=prompts.parent))
    replacement = operation_root / "replacement"
    backup = operation_root / "backup"
    moved_current = False
    try:
        shutil.copytree(shipped, replacement)
        if prompts.exists():
            os.replace(prompts, backup)
            moved_current = True
        try:
            os.replace(replacement, prompts)
        except BaseException:
            if moved_current and backup.exists():
                os.replace(backup, prompts)
            raise
        _fsync_directory(prompts.parent)
    finally:
        shutil.rmtree(operation_root, ignore_errors=True)


def _seed_prompt_library(prompts: Path, shipped: Path) -> None:
    """Install the initial editable prompt library only after a complete copy.

    A first-run API request can arrive alongside other startup requests.  Keep
    those readers from observing a half-copied prompt tree if startup is
    interrupted while the mutable library is being seeded.
    """

    operation_root = Path(tempfile.mkdtemp(prefix=".prompts-bootstrap-", dir=prompts.parent))
    replacement = operation_root / "replacement"
    try:
        shutil.copytree(shipped, replacement)
        os.replace(replacement, prompts)
        _fsync_directory(prompts.parent)
    finally:
        shutil.rmtree(operation_root, ignore_errors=True)


def bootstrap_user_data() -> Path | None:
    """Initialize packaged mutable data without overwriting an existing workspace."""

    # A single process receives concurrent metadata requests on initial page
    # load.  The prompt library must be created exactly once before any of
    # those requests build a PromptRepository from it.
    with mutable_data_lock:
        root = _packaged_user_data_dir() or user_data_dir()
        if root is None:
            return None
        root.mkdir(parents=True, exist_ok=True)

        prompts = prompt_library_dir()
        shipped = _PROJECT_ROOT / "data/prompts"
        if os.environ.get(_SYNC_PROMPTS_FROM_SOURCE_ENV) == "1":
            _replace_prompts_from_source(prompts, shipped)
        elif not prompts.exists():
            _seed_prompt_library(prompts, shipped)

        (root / "conversations").mkdir(exist_ok=True)
        (root / "local-ai").mkdir(exist_ok=True)

        manifest = root / "manifest.json"
        if not manifest.exists():
            _atomic_text(
                manifest,
                json.dumps(
                    {"data_schema": USER_DATA_FORMAT_VERSION, "created_by": __version__},
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
            )

        readme = root / "README.txt"
        if not readme.exists():
            _atomic_text(
                readme,
                "AQA User Data\n\n"
                "This folder contains your settings, conversations, prompt changes, and Local AI "
                "files. Back it up if you want to keep your work. settings.json can contain API "
                "credentials, so do not share this folder unless you have removed sensitive data.\n",
            )
        return root
