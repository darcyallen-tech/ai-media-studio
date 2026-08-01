"""Lightweight UI preferences (last Studio tab, etc.) under app data."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from media_studio.secrets_store import app_data_dir

PREFS_FILENAME = "ui_prefs.json"
_lock = threading.Lock()

# Known keys
STUDIO_MODE = "studio_mode"  # "image" | "video"
APP_SCENARIO = "app_scenario"  # blank_canvas | furniture_popin | … (app-wide)
IMAGE_SCENARIO = "image_scenario"  # legacy alias of APP_SCENARIO
VIDEO_WORKSPACE = "video_workspace"  # received | blank | camera_lock
# Frame Editor: auto 1080p proxy via fal scale-video before Aleph (default ON)
FRAME_EDITOR_AUTO_DOWNSCALE = "frame_editor_auto_downscale"
# Output folder (absolute path string); empty = default project outputs/
OUTPUT_DIR_PREF = "output_dir"
# Library / outputs retention: "never" | "7" | "14" | "30" | "90"
RETENTION_DAYS = "retention_days"
# Library: hide history rows whose media files are all missing
LIBRARY_HIDE_MISSING = "library_hide_missing"
# Cost guard: "off" | "2" | "5" — confirm when estimate ≥ threshold (USD)
COST_CONFIRM_USD = "cost_confirm_usd"
# First-run onboarding dismissed (Quick Start still available from Help)
ONBOARDING_DONE = "onboarding_done"
# Last Job / Listing label (address, client, shoot date) — optional
JOB_NAME = "job_name"
# Quiet GitHub update check on startup (default ON)
CHECK_UPDATES = "check_updates"

RETENTION_CHOICES = ("never", "7", "14", "30", "90")
COST_CONFIRM_CHOICES = ("off", "2", "5")


def prefs_path() -> Path:
    return app_data_dir() / PREFS_FILENAME


def load_prefs() -> dict[str, Any]:
    path = prefs_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_prefs(updates: dict[str, Any]) -> dict[str, Any]:
    """Merge ``updates`` into stored prefs and write."""
    with _lock:
        data = load_prefs()
        data.update(updates)
        path = prefs_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
        return data


def get_studio_mode() -> str:
    """Return ``image`` or ``video`` (default image)."""
    raw = str(load_prefs().get(STUDIO_MODE) or "image").strip().lower()
    return "video" if raw == "video" else "image"


def set_studio_mode(mode: str) -> None:
    m = "video" if str(mode).strip().lower() == "video" else "image"
    save_prefs({STUDIO_MODE: m})


def get_app_scenario() -> str:
    """
    Last app-level scenario key (blank_canvas | furniture_popin | …).

    Prefers ``app_scenario``; falls back to legacy ``image_scenario``.
    """
    data = load_prefs()
    raw = data.get(APP_SCENARIO)
    if not raw:
        raw = data.get(IMAGE_SCENARIO)
    return str(raw or "furniture_popin").strip() or "furniture_popin"


def set_app_scenario(key: str) -> None:
    """Persist app-level scenario (also mirrors legacy image_scenario key)."""
    k = str(key or "furniture_popin").strip() or "furniture_popin"
    save_prefs({APP_SCENARIO: k, IMAGE_SCENARIO: k})


def get_image_scenario() -> str:
    """Back-compat: same as get_app_scenario()."""
    return get_app_scenario()


def set_image_scenario(key: str) -> None:
    """Back-compat: same as set_app_scenario()."""
    set_app_scenario(key)


def get_video_workspace() -> str:
    """Last Video workspace: received | blank | camera_lock."""
    raw = str(load_prefs().get(VIDEO_WORKSPACE) or "camera_lock").strip().lower()
    if raw in ("received", "blank", "blank_canvas", "camera_lock", "camera-lock"):
        if raw in ("blank_canvas",):
            return "blank"
        if raw == "camera-lock":
            return "camera_lock"
        return raw
    return "camera_lock"


def get_frame_editor_auto_downscale() -> bool:
    """Default True: oversized sources get a 1080p fal proxy for Aleph."""
    raw = load_prefs().get(FRAME_EDITOR_AUTO_DOWNSCALE, True)
    if isinstance(raw, bool):
        return raw
    s = str(raw).strip().lower()
    if s in ("0", "false", "no", "off"):
        return False
    return True


def set_frame_editor_auto_downscale(enabled: bool) -> None:
    save_prefs({FRAME_EDITOR_AUTO_DOWNSCALE: bool(enabled)})


def get_output_dir_pref() -> str | None:
    """Persisted output folder, or None to use project default."""
    raw = str(load_prefs().get(OUTPUT_DIR_PREF) or "").strip()
    if not raw:
        return None
    try:
        p = Path(raw).expanduser()
        if p.is_dir() or p.parent.is_dir():
            return str(p)
    except OSError:
        return None
    return raw


def set_output_dir_pref(path: str | None) -> None:
    save_prefs({OUTPUT_DIR_PREF: (str(path).strip() if path else "")})


def get_retention_days() -> int | None:
    """
    Retention window in days, or None = never delete generation media.

    Cache dirs are still age/LRU bounded even when Never.
    """
    raw = str(load_prefs().get(RETENTION_DAYS) or "never").strip().lower()
    if raw in ("", "never", "0", "none", "off"):
        return None
    try:
        n = int(raw)
        if n <= 0:
            return None
        return n
    except (TypeError, ValueError):
        return None


def set_retention_days(value: str | int | None) -> None:
    if value is None:
        save_prefs({RETENTION_DAYS: "never"})
        return
    s = str(value).strip().lower()
    if s in ("never", "0", "none", "off", ""):
        save_prefs({RETENTION_DAYS: "never"})
        return
    try:
        n = int(s)
        if n <= 0:
            save_prefs({RETENTION_DAYS: "never"})
        else:
            save_prefs({RETENTION_DAYS: str(n)})
    except (TypeError, ValueError):
        save_prefs({RETENTION_DAYS: "never"})


def get_library_hide_missing() -> bool:
    raw = load_prefs().get(LIBRARY_HIDE_MISSING, True)
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() not in ("0", "false", "no", "off")


def set_library_hide_missing(enabled: bool) -> None:
    save_prefs({LIBRARY_HIDE_MISSING: bool(enabled)})


def get_cost_confirm_usd() -> float | None:
    """
    Optional cost-guard threshold in USD, or None when off (default).

    When set, expensive generates (e.g. Creative Vision) ask to confirm.
    """
    raw = str(load_prefs().get(COST_CONFIRM_USD) or "off").strip().lower()
    if raw in ("", "off", "0", "none", "never", "false"):
        return None
    try:
        n = float(raw)
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


def get_onboarding_done() -> bool:
    """True when the first-run wizard should not auto-open."""
    raw = load_prefs().get(ONBOARDING_DONE, False)
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def set_onboarding_done(done: bool = True) -> None:
    save_prefs({ONBOARDING_DONE: bool(done)})


def set_cost_confirm_usd(value: str | float | None) -> None:
    if value is None:
        save_prefs({COST_CONFIRM_USD: "off"})
        return
    s = str(value).strip().lower()
    if s in ("", "off", "0", "none", "never", "false"):
        save_prefs({COST_CONFIRM_USD: "off"})
        return
    try:
        n = float(s)
        if n <= 0:
            save_prefs({COST_CONFIRM_USD: "off"})
        else:
            # normalize common choices
            if abs(n - 2) < 0.01:
                save_prefs({COST_CONFIRM_USD: "2"})
            elif abs(n - 5) < 0.01:
                save_prefs({COST_CONFIRM_USD: "5"})
            else:
                save_prefs({COST_CONFIRM_USD: str(int(n) if n == int(n) else n)})
    except (TypeError, ValueError):
        save_prefs({COST_CONFIRM_USD: "off"})


def set_video_workspace(key: str) -> None:
    k = str(key or "camera_lock").strip().lower()
    if k in ("blank_canvas", "blank"):
        k = "blank"
    elif k in ("camera-lock", "camera_lock"):
        k = "camera_lock"
    elif k != "received":
        k = "camera_lock"
    save_prefs({VIDEO_WORKSPACE: k})


def get_job_name() -> str:
    """Last Job / Listing label (may be empty)."""
    return str(load_prefs().get(JOB_NAME) or "").strip()


def set_job_name(name: str | None) -> None:
    """Persist last-used Job / Listing (empty clears)."""
    save_prefs({JOB_NAME: (name or "").strip()})


def get_check_updates() -> bool:
    """True when startup should quietly check GitHub for a newer build (default on)."""
    raw = load_prefs().get(CHECK_UPDATES, True)
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() not in ("0", "false", "no", "off")


def set_check_updates(enabled: bool) -> None:
    save_prefs({CHECK_UPDATES: bool(enabled)})

