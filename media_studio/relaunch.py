"""
Hard relaunch of AI Media Studio (dev / test QoL after code pulls).

Spawns a new process with the same entrypoint, then exits this process.
Does not wipe Settings, API keys, or library data.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable

from media_studio.config import PROJECT_ROOT

OnError = Callable[[str], None]
OnStatus = Callable[[str], None]


def _project_root() -> Path:
    return Path(PROJECT_ROOT).resolve()


def _app_entry() -> Path:
    return _project_root() / "app.py"


def _python_executable() -> str:
    """Prefer the running interpreter (usually project .venv)."""
    return sys.executable or "python"


def relaunch_command() -> list[str]:
    """Command list used to start Studio (for diagnostics)."""
    return [_python_executable(), str(_app_entry())]


def try_relaunch(
    *,
    page=None,
    on_status: OnStatus | None = None,
    on_error: OnError | None = None,
    delay_s: float = 1.0,
) -> bool:
    """
    Schedule a delayed spawn of ``python app.py`` from the project root,
    release the single-instance lock, then exit this process.

    Returns True if the spawn helper was started (exit follows shortly).
    Returns False and keeps the app open if spawn fails.
    """
    root = _project_root()
    entry = _app_entry()
    py = _python_executable()

    if not entry.is_file():
        msg = f"Cannot relaunch — entry not found: {entry}"
        if on_error:
            on_error(msg)
        return False
    if not Path(py).is_file() and py not in ("python", "python3"):
        # sys.executable may be a valid path; allow bare python on PATH
        pass

    def _status(m: str) -> None:
        if on_status:
            try:
                on_status(m)
            except Exception:
                pass

    _status("Relaunching…")

    # Child waits so this process can release the instance lock and exit
    delay = max(0.4, float(delay_s))
    # Use a small Python trampoline so we don't depend on start.bat / shell
    trampoline = (
        "import subprocess,sys,time;"
        f"time.sleep({delay!r});"
        f"subprocess.Popen({[py, str(entry)]!r}, cwd={str(root)!r}, "
        "env=None, close_fds=True)"
    )

    try:
        from media_studio.single_instance import release_for_relaunch

        release_for_relaunch()
    except Exception:
        pass

    env = os.environ.copy()
    env["AMS_RELAUNCH"] = "1"

    popen_kwargs: dict = {
        "cwd": str(root),
        "env": env,
        "close_fds": True,
    }
    if sys.platform.startswith("win"):
        # Detach so closing this console/window doesn't kill the child
        flags = 0
        flags |= getattr(subprocess, "DETACHED_PROCESS", 0)
        flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        # Avoid flashing a console for the trampoline when possible
        flags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
        if flags:
            popen_kwargs["creationflags"] = flags
        popen_kwargs["stdin"] = subprocess.DEVNULL
        popen_kwargs["stdout"] = subprocess.DEVNULL
        popen_kwargs["stderr"] = subprocess.DEVNULL

    try:
        subprocess.Popen([py, "-c", trampoline], **popen_kwargs)
    except Exception as exc:
        msg = f"Relaunch failed to start: {exc}"
        if on_error:
            on_error(msg)
        return False

    def _exit_soon() -> None:
        time.sleep(0.35)
        try:
            if page is not None:
                win = getattr(page, "window", None)
                if win is not None:
                    close = getattr(win, "close", None) or getattr(win, "destroy", None)
                    if callable(close):
                        try:
                            close()
                        except Exception:
                            pass
        except Exception:
            pass
        try:
            sys.exit(0)
        except SystemExit:
            raise
        except Exception:
            os._exit(0)

    threading.Thread(target=_exit_soon, daemon=True).start()
    return True
