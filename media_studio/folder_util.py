"""Open folders in the system file manager (Windows-friendly)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def open_folder(path: str | Path | None) -> str:
    """
    Open a folder in Explorer / Finder / xdg-open.
    Creates the folder if missing.
    """
    if not path or not str(path).strip():
        return "Open folder: path is empty."
    folder = Path(path).expanduser()
    try:
        folder.mkdir(parents=True, exist_ok=True)
        folder = folder.resolve()
    except OSError as exc:
        return f"Open folder failed: cannot create/access {folder} ({exc})"

    try:
        if sys.platform.startswith("win"):
            os.startfile(str(folder))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", str(folder)], check=False)
        else:
            subprocess.run(["xdg-open", str(folder)], check=False)
    except OSError as exc:
        return f"Open folder failed: {exc}"

    return f"Opened folder: {folder}"


def show_in_folder(path: str | Path | None) -> str:
    """
    Reveal a file in the OS file manager (select file when possible).

    Windows: explorer /select
    macOS: open -R
    Linux: open containing folder
    """
    if not path or not str(path).strip():
        return "Show in folder: path is empty."
    target = Path(path).expanduser()
    try:
        if target.is_file():
            folder = target.parent.resolve()
            file_path = target.resolve()
        elif target.is_dir():
            return open_folder(target)
        else:
            # Missing file — open parent if it exists
            parent = target.parent
            if parent.is_dir():
                return open_folder(parent)
            return f"Show in folder: not found — {target}"
    except OSError as exc:
        return f"Show in folder failed: {exc}"

    try:
        if sys.platform.startswith("win"):
            # /select, highlights the file in Explorer
            subprocess.run(
                ["explorer", f"/select,{file_path}"],
                check=False,
            )
        elif sys.platform == "darwin":
            subprocess.run(["open", "-R", str(file_path)], check=False)
        else:
            # Linux: open directory (file select is DE-specific)
            subprocess.run(["xdg-open", str(folder)], check=False)
    except OSError as exc:
        return f"Show in folder failed: {exc}"

    return f"Showed in folder: {file_path.name}"
