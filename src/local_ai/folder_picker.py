"""Small, dependency-free native directory picker for importing older data."""

from __future__ import annotations

import platform
import shutil
import subprocess
from pathlib import Path

from .process_launch import hidden_console_flags


class FolderPickerUnavailable(RuntimeError):
    """The current desktop has no supported native directory picker."""


class FolderPickerCancelled(RuntimeError):
    """The user dismissed the directory picker without making a choice."""


def choose_directory() -> Path:
    """Return a directory selected in the host's native UI."""
    system = platform.system().lower()
    if system == "darwin":
        command = [
            "/usr/bin/osascript",
            "-e",
            'POSIX path of (choose folder with prompt "Ältere AQA-Version auswählen")',
        ]
    elif system == "windows":
        command = [
            "powershell.exe",
            "-NoProfile",
            "-Sta",
            "-Command",
            "Add-Type -AssemblyName System.Windows.Forms; $d=New-Object System.Windows.Forms.FolderBrowserDialog; "
            "$d.Description='Ältere AQA-Version auswählen'; if($d.ShowDialog() -eq 'OK'){[Console]::Out.Write($d.SelectedPath)}",
        ]
    elif shutil.which("zenity"):
        command = [
            "zenity",
            "--file-selection",
            "--directory",
            "--title=Ältere AQA-Version auswählen",
        ]
    elif shutil.which("kdialog"):
        command = [
            "kdialog",
            "--getexistingdirectory",
            ".",
            "--title",
            "Ältere AQA-Version auswählen",
        ]
    else:
        raise FolderPickerUnavailable("no native directory picker is available")
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            **({"creationflags": hidden_console_flags()} if system == "windows" else {}),
        )
    except OSError as exc:
        raise FolderPickerUnavailable("native directory picker could not be started") from exc
    selected = result.stdout.strip()
    if result.returncode != 0 or not selected:
        raise FolderPickerCancelled("directory selection cancelled")
    path = Path(selected).expanduser()
    if not path.is_dir():
        raise FolderPickerCancelled("directory selection cancelled")
    return path
