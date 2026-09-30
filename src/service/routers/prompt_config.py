"""Shared persistence and filesystem boundaries for prompt configuration routes."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from functools import wraps
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from src.config.user_data import mutable_data_lock


def _prompt_defaults_root(context: Any, prompt_root: Path) -> Path:
    """Return the immutable prompt-default root paired with the active prompt tree."""

    configured = getattr(context.settings, "prompt_defaults_path", None)
    if type(configured) is str:
        return Path(configured).resolve()
    return prompt_root.parent / "prompt_defaults"


def _resolve_prompt_data_directory_for_reveal(context: Any, directory: Path) -> Path:
    """Validate a prompt-owned directory before opening it in the file manager."""

    try:
        prompt_root = Path(context.prompts.base_path).resolve()
        data_root = prompt_root.parent.resolve()
        candidate = directory.resolve()
    except (OSError, RuntimeError, TypeError, AttributeError):
        raise HTTPException(status_code=404, detail="Directory is unavailable") from None
    if candidate == data_root or data_root not in candidate.parents or not candidate.is_dir():
        raise HTTPException(status_code=404, detail="Directory is unavailable")
    return candidate


def _open_directory(path: Path) -> None:
    """Open a validated directory without exposing its path in an API response."""

    if sys.platform == "darwin":
        argv = ["open", str(path)]
    elif sys.platform == "win32":
        argv = ["explorer", str(path)]
    else:
        argv = ["xdg-open", str(path)]
    try:
        result = subprocess.run(
            argv,
            check=False,
            shell=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        if isinstance(result.returncode, int) and result.returncode != 0:
            raise HTTPException(status_code=502, detail="Directory is unavailable")
    except (OSError, subprocess.TimeoutExpired) as error:
        raise HTTPException(status_code=502, detail="Directory is unavailable") from error


def _reveal_path(path: Path) -> None:
    """Reveal a validated file without returning a local path to the client."""

    if sys.platform == "darwin":
        argv = ["open", "-R", str(path)]
    elif sys.platform == "win32":
        argv = ["explorer", f"/select,{path}"]
    else:
        argv = ["xdg-open", str(path.parent)]
    try:
        subprocess.run(
            argv,
            shell=False,
            check=False,
            timeout=5,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.TimeoutExpired, OSError) as error:
        raise HTTPException(
            status_code=502, detail="Reveal command could not be launched"
        ) from error


def _atomic_copy_bytes(src: Path, dst: Path) -> None:
    """Copy a validated prompt asset through a same-directory atomic replacement."""

    with mutable_data_lock:
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = dst.with_name(f".{dst.name}.{uuid.uuid4().hex}.tmp")
        try:
            with open(tmp_path, "wb") as handle:
                handle.write(src.read_bytes())
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, dst)
        except Exception:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass
            raise


def _serializes_mutable_data(function):
    """Keep a mutable prompt read-modify-write operation atomic."""

    @wraps(function)
    def wrapped(*args, **kwargs):
        with mutable_data_lock:
            return function(*args, **kwargs)

    return wrapped


def _trigger_session_configuration_reload(context: Any) -> None:
    """Reload prompt-dependent discussion configuration after a committed mutation."""

    context.discussion.reload_session_configuration()
