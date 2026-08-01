"""
Reliable file picking for AI Media Studio (Flet 0.86 desktop).

Why this module does **not** use ``ft.FilePicker`` on desktop
-------------------------------------------------------------
On Flet 0.80+ ``FilePicker`` is a Service, not a visual control.
Putting it in ``page.overlay`` (or any layout) produces the red banner:

    Unknown control: FilePicker

Creating ephemeral pickers also yields:

    TimeoutException: Timeout waiting for invoke method listener…

For a **desktop** app we open the native OS file dialog directly
(tkinter / Windows Forms via PowerShell fallback). No Flet control is
sent to the client, so the banner and timeouts cannot occur.

Public API (stable for call sites)::

    files = await pick_image(page, dialog_title="…")
    path = files[0].path   # if files
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

IMAGE_EXTS = ["png", "jpg", "jpeg", "webp", "bmp"]
VIDEO_EXTS = ["mp4", "mov", "webm", "m4v", "avi", "mkv"]
AUDIO_EXTS = ["mp3", "wav", "m4a", "ogg", "flac", "aac"]


@dataclass
class PickedFile:
    """Minimal stand-in for flet.FilePickerFile (``.path`` / ``.name``)."""

    path: str
    name: str
    size: int = 0


def ensure_file_picker(page: Any = None) -> None:
    """
    No-op retained for startup compatibility.

    Desktop path never mounts a Flet FilePicker (avoids Unknown control).
    """
    return None


def _ext_filter(allowed: Sequence[str] | None, title: str) -> list[tuple[str, str]]:
    if not allowed:
        return [("All files", "*.*")]
    patterns = " ".join(f"*.{e.lstrip('.').lower()}" for e in allowed)
    label = f"{title} ({patterns})" if title else patterns
    return [(label, patterns), ("All files", "*.*")]


def _native_pick_files(
    *,
    dialog_title: str | None,
    allowed_extensions: Sequence[str] | None,
    allow_multiple: bool,
    initial_directory: str | None,
) -> list[PickedFile]:
    title = dialog_title or "Choose file"
    initial = initial_directory or str(Path.home())

    # --- Preferred: tkinter (stdlib, works on Win/macOS/Linux with Tk) ---
    try:
        return _tk_pick(
            title=title,
            allowed_extensions=allowed_extensions,
            allow_multiple=allow_multiple,
            initial_directory=initial,
        )
    except Exception:
        pass

    # --- Windows fallback: PowerShell OpenFileDialog ---
    if sys.platform.startswith("win"):
        try:
            return _win_forms_pick(
                title=title,
                allowed_extensions=allowed_extensions,
                allow_multiple=allow_multiple,
                initial_directory=initial,
            )
        except Exception:
            pass

    return []


def _tk_pick(
    *,
    title: str,
    allowed_extensions: Sequence[str] | None,
    allow_multiple: bool,
    initial_directory: str,
) -> list[PickedFile]:
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    try:
        # Keep dialog above the Flet window
        root.attributes("-topmost", True)
    except Exception:
        pass
    root.update_idletasks()

    filetypes = _ext_filter(allowed_extensions, title)
    kwargs: dict[str, Any] = {
        "title": title,
        "initialdir": initial_directory if Path(initial_directory).is_dir() else str(Path.home()),
        "filetypes": filetypes,
    }

    try:
        if allow_multiple:
            paths = filedialog.askopenfilenames(**kwargs)
            path_list = list(paths) if paths else []
        else:
            p = filedialog.askopenfilename(**kwargs)
            path_list = [p] if p else []
    finally:
        try:
            root.destroy()
        except Exception:
            pass

    return _paths_to_picked(path_list)


def _win_forms_pick(
    *,
    title: str,
    allowed_extensions: Sequence[str] | None,
    allow_multiple: bool,
    initial_directory: str,
) -> list[PickedFile]:
    """PowerShell System.Windows.Forms.OpenFileDialog (Windows only)."""
    # Build filter string: "Label|*.png;*.jpg|All|*.*"
    if allowed_extensions:
        patterns = ";".join(f"*.{e.lstrip('.').lower()}" for e in allowed_extensions)
        filt = f"{title}|{patterns}|All files|*.*"
    else:
        filt = "All files|*.*"

    multi = "$true" if allow_multiple else "$false"
    init = initial_directory.replace("'", "''")
    title_esc = title.replace("'", "''")
    filt_esc = filt.replace("'", "''")

    ps = f"""
Add-Type -AssemblyName System.Windows.Forms
$d = New-Object System.Windows.Forms.OpenFileDialog
$d.Title = '{title_esc}'
$d.Filter = '{filt_esc}'
$d.Multiselect = {multi}
$d.InitialDirectory = '{init}'
if ($d.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {{
  if ($d.Multiselect) {{ $d.FileNames -join "`n" }} else {{ $d.FileName }}
}}
"""
    result = subprocess.run(
        ["powershell", "-NoProfile", "-STA", "-Command", ps],
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    out = (result.stdout or "").strip()
    if not out:
        return []
    paths = [ln.strip() for ln in out.splitlines() if ln.strip()]
    return _paths_to_picked(paths)


def _paths_to_picked(paths: Sequence[str]) -> list[PickedFile]:
    out: list[PickedFile] = []
    for p in paths:
        if not p:
            continue
        path = str(Path(p).expanduser().resolve())
        if not Path(path).is_file():
            # Still return path if dialog gave something (race)
            if not os.path.exists(path):
                continue
        try:
            size = Path(path).stat().st_size
        except OSError:
            size = 0
        out.append(PickedFile(path=path, name=Path(path).name, size=size))
    return out


async def pick_files(
    page: Any = None,
    *,
    dialog_title: str | None = None,
    allowed_extensions: Sequence[str] | None = None,
    allow_multiple: bool = False,
    file_type: Any = None,  # accepted for API compat; ignored on native path
    initial_directory: str | None = None,
) -> list[PickedFile]:
    """
    Open the system file dialog and return selected files.

    ``page`` is optional (kept for call-site compatibility). Never mounts a
    Flet FilePicker control.
    """
    # Prefer native dialog off the UI thread so Flet stays responsive
    return await asyncio.to_thread(
        _native_pick_files,
        dialog_title=dialog_title,
        allowed_extensions=allowed_extensions,
        allow_multiple=allow_multiple,
        initial_directory=initial_directory,
    )


def _native_pick_folder(
    *,
    dialog_title: str | None,
    initial_directory: str | None,
) -> str | None:
    """Native folder chooser; returns absolute path or None."""
    title = dialog_title or "Choose folder"
    initial = initial_directory or str(Path.home())
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        try:
            root.attributes("-topmost", True)
        except Exception:
            pass
        root.update_idletasks()
        try:
            path = filedialog.askdirectory(
                title=title,
                initialdir=initial if Path(initial).is_dir() else str(Path.home()),
            )
        finally:
            try:
                root.destroy()
            except Exception:
                pass
        if path:
            return str(Path(path).expanduser().resolve())
    except Exception:
        pass

    if sys.platform.startswith("win"):
        try:
            init = (initial_directory or str(Path.home())).replace("'", "''")
            title_esc = title.replace("'", "''")
            ps = f"""
Add-Type -AssemblyName System.Windows.Forms
$d = New-Object System.Windows.Forms.FolderBrowserDialog
$d.Description = '{title_esc}'
$d.SelectedPath = '{init}'
if ($d.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {{ $d.SelectedPath }}
"""
            result = subprocess.run(
                ["powershell", "-NoProfile", "-STA", "-Command", ps],
                capture_output=True,
                text=True,
                timeout=600,
                check=False,
            )
            out = (result.stdout or "").strip()
            if out:
                return str(Path(out).expanduser().resolve())
        except Exception:
            pass
    return None


async def pick_folder(
    page: Any = None,
    *,
    dialog_title: str = "Choose output folder",
    initial_directory: str | None = None,
) -> str | None:
    """Open a native folder dialog. Returns absolute path or None if cancelled."""
    return await asyncio.to_thread(
        _native_pick_folder,
        dialog_title=dialog_title,
        initial_directory=initial_directory,
    )


async def pick_image(
    page: Any = None,
    *,
    dialog_title: str = "Choose image",
    allow_multiple: bool = False,
) -> list[PickedFile]:
    return await pick_files(
        page,
        dialog_title=dialog_title,
        allowed_extensions=IMAGE_EXTS,
        allow_multiple=allow_multiple,
    )


async def pick_video(
    page: Any = None,
    *,
    dialog_title: str = "Choose video",
    allow_multiple: bool = False,
) -> list[PickedFile]:
    return await pick_files(
        page,
        dialog_title=dialog_title,
        allowed_extensions=VIDEO_EXTS,
        allow_multiple=allow_multiple,
    )


async def pick_audio(
    page: Any = None,
    *,
    dialog_title: str = "Choose audio",
    allow_multiple: bool = False,
) -> list[PickedFile]:
    return await pick_files(
        page,
        dialog_title=dialog_title,
        allowed_extensions=AUDIO_EXTS,
        allow_multiple=allow_multiple,
    )
