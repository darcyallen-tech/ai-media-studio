"""
DaVinci Resolve Studio — send media to the Media Pool (local scripting).

Requires:
  - Resolve Studio open with a project loaded
  - Preferences → System → General → External scripting = Local

Windows module search paths are set up automatically when possible.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any


@dataclass
class ResolveSendResult:
    ok: bool
    message: str
    bin_name: str | None = None
    clips: int = 0


def _ensure_resolve_module_path() -> None:
    """Add Blackmagic Scripting Modules to sys.path on Windows/macOS/Linux."""
    candidates: list[Path] = []

    # Env override
    env_api = os.environ.get("RESOLVE_SCRIPT_API") or os.environ.get("RESOLVE_SCRIPT_API_PATH")
    if env_api:
        candidates.append(Path(env_api) / "Modules")

    if sys.platform.startswith("win"):
        program_data = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
        candidates.append(
            Path(program_data)
            / "Blackmagic Design"
            / "DaVinci Resolve"
            / "Support"
            / "Developer"
            / "Scripting"
            / "Modules"
        )
        # Also common install-relative path
        for base in (
            r"C:\Program Files\Blackmagic Design\DaVinci Resolve",
            r"C:\Program Files\Blackmagic Design\DaVinci Resolve Studio",
        ):
            candidates.append(Path(base) / "Developer" / "Scripting" / "Modules")
        # fusionscript.dll path for some loaders
        lib = os.environ.get("RESOLVE_SCRIPT_LIB")
        if not lib:
            for dll in (
                r"C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll",
                r"C:\Program Files\Blackmagic Design\DaVinci Resolve Studio\fusionscript.dll",
            ):
                if Path(dll).is_file():
                    os.environ.setdefault("RESOLVE_SCRIPT_LIB", dll)
                    break
    elif sys.platform == "darwin":
        candidates.append(
            Path(
                "/Library/Application Support/Blackmagic Design/DaVinci Resolve/"
                "Developer/Scripting/Modules"
            )
        )
    else:
        candidates.append(
            Path(
                "/opt/resolve/Developer/Scripting/Modules"
            )
        )
        candidates.append(
            Path.home()
            / "resolve"
            / "Developer"
            / "Scripting"
            / "Modules"
        )

    for mod in candidates:
        if mod.is_dir():
            s = str(mod.resolve())
            if s not in sys.path:
                sys.path.insert(0, s)


def _connect_resolve() -> tuple[Any | None, str | None]:
    """
    Return (resolve_app, error_message).
    """
    _ensure_resolve_module_path()
    try:
        import DaVinciResolveScript as dvr  # type: ignore
    except ImportError as exc:
        return None, (
            "DaVinciResolveScript not found. Install Resolve Studio, enable "
            "External scripting = Local, and ensure Scripting Modules are on the path. "
            f"({exc})"
        )
    except Exception as exc:
        return None, f"Failed to load DaVinciResolveScript: {exc}"

    try:
        resolve = dvr.scriptapp("Resolve")
    except Exception as exc:
        return None, (
            f"Could not connect to Resolve ({exc}). "
            "Is DaVinci Resolve Studio open with a project loaded? "
            "Preferences → System → General → External scripting must be Local."
        )

    if resolve is None:
        return None, (
            "Resolve is not running or scripting is disabled. "
            "Open Resolve Studio, load a project, set External scripting = Local, then try again."
        )
    return resolve, None


def _find_or_create_bin(media_pool: Any, root_folder: Any, bin_name: str) -> Any:
    """
    Find a subfolder of root by name, or create it.
    API names vary slightly across Resolve versions.
    """
    # List existing
    try:
        subs = root_folder.GetSubFolderList() or []
    except Exception:
        subs = []
    for sub in subs:
        try:
            name = sub.GetName()
        except Exception:
            name = None
        if name == bin_name:
            return sub

    # Create
    create = getattr(media_pool, "AddSubFolder", None)
    if callable(create):
        try:
            folder = create(root_folder, bin_name)
            if folder:
                return folder
        except Exception:
            pass
    # Older name
    create2 = getattr(root_folder, "AddSubFolder", None)
    if callable(create2):
        try:
            folder = create2(bin_name)
            if folder:
                return folder
        except Exception:
            pass
    # Fallback: use root
    return root_folder


def default_bin_name(*, dated: bool = True) -> str:
    if dated:
        return f"AI Media Studio / {date.today().isoformat()}"
    return "AI Media Studio"


def send_file_to_resolve(
    path: str | Path | None,
    *,
    bin_name: str | None = None,
) -> ResolveSendResult:
    """
    Import a single media file into the current project's Media Pool.

    Places the clip in ``bin_name`` (created if needed). Default bin:
    ``AI Media Studio / YYYY-MM-DD``.
    """
    if not path or not str(path).strip():
        return ResolveSendResult(ok=False, message="No file path to send.")
    file_path = Path(path).expanduser()
    try:
        file_path = file_path.resolve()
    except OSError as exc:
        return ResolveSendResult(ok=False, message=f"Invalid path: {exc}")
    if not file_path.is_file():
        return ResolveSendResult(ok=False, message=f"File not found: {file_path}")

    # Windows paths as plain strings work with ImportMedia
    abs_path = str(file_path)

    resolve, err = _connect_resolve()
    if err or resolve is None:
        return ResolveSendResult(ok=False, message=err or "Could not connect to Resolve.")

    try:
        pm = resolve.GetProjectManager()
        if pm is None:
            return ResolveSendResult(
                ok=False,
                message="No Project Manager — is Resolve fully started?",
            )
        project = pm.GetCurrentProject()
        if project is None:
            return ResolveSendResult(
                ok=False,
                message="No project is open in Resolve. Open or create a project, then try again.",
            )
        media_pool = project.GetMediaPool()
        if media_pool is None:
            return ResolveSendResult(ok=False, message="Could not access the Media Pool.")

        root = media_pool.GetRootFolder()
        if root is None:
            return ResolveSendResult(ok=False, message="Media Pool root folder unavailable.")

        target_bin = bin_name or default_bin_name(dated=True)
        folder = _find_or_create_bin(media_pool, root, target_bin)

        # Set current folder so ImportMedia lands in the right bin
        try:
            media_pool.SetCurrentFolder(folder)
        except Exception:
            pass

        clips = media_pool.ImportMedia([abs_path])
        if not clips:
            # Some versions return empty list on failure
            return ResolveSendResult(
                ok=False,
                message=(
                    f"Import returned no clips for {file_path.name}. "
                    "Check the format is supported and the path is readable."
                ),
                bin_name=target_bin,
            )
        n = len(clips) if isinstance(clips, (list, tuple)) else 1
        return ResolveSendResult(
            ok=True,
            message=f"Sent “{file_path.name}” to Resolve Media Pool → {target_bin}",
            bin_name=target_bin,
            clips=int(n),
        )
    except Exception as exc:
        return ResolveSendResult(
            ok=False,
            message=(
                f"Resolve scripting error: {exc}. "
                "Confirm Studio is open, a project is loaded, and External scripting = Local."
            ),
        )


def resolve_icon_path() -> str | None:
    """Path to bundled Resolve-style icon, if present."""
    p = Path(__file__).resolve().parent / "assets" / "resolve_icon.png"
    if p.is_file():
        return str(p)
    return None
