"""
Single-instance guard for AI Media Studio.

Primary holds a lock under app data. A second launch (e.g. Resolve “Send”)
signals the primary via a wake file and exits without opening a window.

Fail soft: if locking is unavailable, return “unlocked” so the app still runs.
"""

from __future__ import annotations

import atexit
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from media_studio.secrets_store import app_data_dir

LOCK_FILENAME = "instance.lock"
WAKE_FILENAME = "instance.wake"
PID_FILENAME = "instance.pid"

Outcome = Literal["primary", "secondary", "unlocked"]

# Held by the primary UI process so Refresh app can release before respawn
_current_lock: InstanceLock | None = None  # type: ignore[name-defined]


def _lock_path() -> Path:
    return app_data_dir() / LOCK_FILENAME


def _wake_path() -> Path:
    return app_data_dir() / WAKE_FILENAME


def _pid_path() -> Path:
    return app_data_dir() / PID_FILENAME


@dataclass
class InstanceLock:
    """Held open for the process lifetime to keep the exclusive lock."""

    path: Path
    _fh: object  # open file handle

    def release(self) -> None:
        try:
            _unlock_file(self._fh)
        except Exception:
            pass
        try:
            self._fh.close()  # type: ignore[union-attr]
        except Exception:
            pass
        try:
            if _pid_path().is_file():
                # Only remove pid if it matches us
                raw = _pid_path().read_text(encoding="utf-8").strip()
                if raw == str(os.getpid()):
                    _pid_path().unlink(missing_ok=True)  # type: ignore[arg-type]
        except Exception:
            pass


def _lock_file(fh) -> bool:
    """Non-blocking exclusive lock. True if acquired."""
    try:
        if sys.platform.startswith("win"):
            import msvcrt

            # Lock one byte at start of file
            fh.seek(0)
            try:
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                return True
            except OSError:
                return False
        else:
            import fcntl

            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return True
            except (OSError, BlockingIOError):
                return False
    except Exception:
        return False


def _unlock_file(fh) -> None:
    try:
        if sys.platform.startswith("win"):
            import msvcrt

            fh.seek(0)
            try:
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        else:
            import fcntl

            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    except Exception:
        pass


def try_acquire_primary() -> tuple[Outcome, InstanceLock | None]:
    """
    Try to become the sole running instance.

    Returns:
      ("primary", lock) — hold ``lock`` until process exit
      ("secondary", None) — another instance owns the lock
      ("unlocked", None) — locking failed; caller may run without guard
    """
    try:
        app_data_dir().mkdir(parents=True, exist_ok=True)
        path = _lock_path()
        # a+b create if missing; ensure ≥1 byte so Windows locking works
        fh = open(path, "a+b")
        fh.seek(0, 2)
        if fh.tell() == 0:
            fh.write(b"\0")
            fh.flush()
        fh.seek(0)
        if not _lock_file(fh):
            try:
                fh.close()
            except Exception:
                pass
            return "secondary", None
        # Write pid for diagnostics (keep file length ≥1 for the lock byte)
        try:
            fh.seek(0)
            fh.truncate(0)
            fh.write(f"{os.getpid()}\n".encode("ascii", errors="replace"))
            fh.flush()
            fh.seek(0)
        except Exception:
            pass
        try:
            _pid_path().write_text(str(os.getpid()), encoding="utf-8")
        except Exception:
            pass
        lock = InstanceLock(path=path, _fh=fh)

        def _cleanup() -> None:
            try:
                lock.release()
            except Exception:
                pass

        atexit.register(_cleanup)
        global _current_lock
        _current_lock = lock
        return "primary", lock
    except Exception:
        return "unlocked", None


def register_primary_lock(lock: InstanceLock | None) -> None:
    """Remember the primary lock for relaunch (app.py)."""
    global _current_lock
    _current_lock = lock


def release_for_relaunch() -> None:
    """
    Drop single-instance lock so a respawned process can become primary.

    Safe to call when unlocked / secondary. Does not delete user data.
    """
    global _current_lock
    lock = _current_lock
    _current_lock = None
    if lock is not None:
        try:
            lock.release()
        except Exception:
            pass
    # Best-effort: clear pid file if it was ours
    try:
        if _pid_path().is_file():
            raw = _pid_path().read_text(encoding="utf-8").strip()
            if raw == str(os.getpid()):
                _pid_path().unlink(missing_ok=True)  # type: ignore[arg-type]
    except Exception:
        pass


def signal_primary_instance(*, reason: str = "resolve_handoff") -> bool:
    """
    Notify the primary instance (wake file under app data).

    Resolve already writes the handoff JSON; this only nudges the primary
    poll loop. Returns True if the wake file was written.
    """
    try:
        app_data_dir().mkdir(parents=True, exist_ok=True)
        payload = f"{time.time():.3f}\t{reason}\t{os.getpid()}\n"
        _wake_path().write_text(payload, encoding="utf-8")
        return True
    except Exception:
        return False


def consume_wake_signal() -> bool:
    """
    If a wake file exists, delete it and return True (primary should poll handoff).
    """
    p = _wake_path()
    try:
        if not p.is_file():
            return False
        try:
            p.unlink()
        except OSError:
            # Still treat as signaled if we saw it
            pass
        return True
    except Exception:
        return False


def bring_app_window_to_front(page) -> None:
    """Best-effort: show + raise the desktop window (Windows + Flet APIs)."""
    if page is None:
        return
    try:
        win = getattr(page, "window", None)
        if win is not None:
            try:
                win.visible = True
            except Exception:
                pass
            to_front = getattr(win, "to_front", None)
            if callable(to_front):
                try:
                    to_front()
                except Exception:
                    pass
            # Flet 0.86: focused / maximized toggles sometimes help raise
            try:
                if hasattr(win, "focused"):
                    win.focused = True
            except Exception:
                pass
    except Exception:
        pass
    # Windows: try SetForegroundWindow via title match
    if sys.platform.startswith("win"):
        try:
            import ctypes

            user32 = ctypes.windll.user32  # type: ignore[attr-defined]
            # Enumerate is heavy; use FindWindowW with partial title is unreliable.
            # Flash taskbar as softer alternative when SetForeground is blocked.
            hwnd = user32.GetForegroundWindow()
            _ = hwnd
            # Attempt to bring any window with our title
            from media_studio.config import APP_TITLE

            found = user32.FindWindowW(None, APP_TITLE)
            if found:
                user32.ShowWindow(found, 9)  # SW_RESTORE
                user32.SetForegroundWindow(found)
        except Exception:
            pass
