"""
Local API key storage for distribution builds.

Keys are stored under the OS user app-data directory — never next to the
project folder that might be shared or committed. Full key values are never
logged by this module.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


APP_DIR_NAME = "AI Media Studio"
SECRETS_FILENAME = "secrets.json"

# JSON keys (internal)
_FAL = "fal_key"
_XAI = "xai_api_key"
# Optional second provider — Runware (Aleph 2.0). Never used for fal models.
_RUNWARE = "runware_key"


def app_data_dir() -> Path:
    """Per-user app data directory (not the project checkout)."""
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / APP_DIR_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_DIR_NAME
    # Linux / other
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "ai-media-studio"
    return Path.home() / ".config" / "ai-media-studio"


def secrets_path() -> Path:
    return app_data_dir() / SECRETS_FILENAME


def _read_raw() -> dict[str, Any]:
    path = secrets_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_raw(data: dict[str, Any]) -> None:
    folder = app_data_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = secrets_path()
    # Restrictive permissions on Unix
    text = json.dumps(data, indent=2) + "\n"
    path.write_text(text, encoding="utf-8")
    try:
        if not sys.platform.startswith("win"):
            os.chmod(path, 0o600)
    except OSError:
        pass


def load_secrets() -> dict[str, str]:
    """Return stored keys (may be empty strings)."""
    raw = _read_raw()
    return {
        "fal_key": str(raw.get(_FAL) or "").strip(),
        "xai_api_key": str(raw.get(_XAI) or "").strip(),
        "runware_key": str(raw.get(_RUNWARE) or "").strip(),
    }


def save_secrets(
    *,
    fal_key: str | None = None,
    xai_api_key: str | None = None,
    runware_key: str | None = None,
    clear_fal: bool = False,
    clear_xai: bool = False,
    clear_runware: bool = False,
) -> dict[str, str]:
    """
    Update stored keys.

    Pass a non-empty string to set; leave as None to keep existing.
    clear_* removes the stored value.
    """
    current = load_secrets()
    if clear_fal:
        current["fal_key"] = ""
    elif fal_key is not None and fal_key.strip():
        current["fal_key"] = fal_key.strip()

    if clear_xai:
        current["xai_api_key"] = ""
    elif xai_api_key is not None and xai_api_key.strip():
        current["xai_api_key"] = xai_api_key.strip()

    if clear_runware:
        current["runware_key"] = ""
    elif runware_key is not None and runware_key.strip():
        current["runware_key"] = runware_key.strip()

    _write_raw(
        {
            _FAL: current["fal_key"],
            _XAI: current["xai_api_key"],
            _RUNWARE: current.get("runware_key") or "",
        }
    )
    return current


def mask_key(key: str | None, *, visible_tail: int = 4) -> str:
    """Safe display string — never the full key."""
    k = (key or "").strip()
    if not k:
        return "(not set)"
    if len(k) <= visible_tail:
        return "••••"
    return f"••••{k[-visible_tail:]}"


def has_fal_key() -> bool:
    """True if a FAL key is available (local store or environment)."""
    return bool(effective_fal_key())


def has_xai_key() -> bool:
    return bool(effective_xai_key())


def has_runware_key() -> bool:
    """True if Runware/Aleph key is available (optional second provider)."""
    return bool(effective_runware_key())


def effective_fal_key() -> str:
    """Local secrets win over environment / .env."""
    stored = load_secrets().get("fal_key") or ""
    if stored.strip():
        return stored.strip()
    return (os.environ.get("FAL_KEY") or os.environ.get("FAL_API_KEY") or "").strip()


def effective_xai_key() -> str:
    stored = load_secrets().get("xai_api_key") or ""
    if stored.strip():
        return stored.strip()
    return (os.environ.get("XAI_API_KEY") or "").strip()


def effective_runware_key() -> str:
    """
    Runware API key for Aleph 2.0 only.

    Never used for fal models. Local secrets win over RUNWARE_API_KEY env.
    """
    stored = load_secrets().get("runware_key") or ""
    if stored.strip():
        return stored.strip()
    return (
        os.environ.get("RUNWARE_API_KEY")
        or os.environ.get("RUNWARE_KEY")
        or ""
    ).strip()


def apply_secrets_to_env() -> None:
    """
    Push effective keys into process env so fal_client / openai / runware work.

    Call on startup and after Settings save.
    FAL and Runware keys stay separate env vars — never mixed.
    """
    fal = effective_fal_key()
    xai = effective_xai_key()
    runware = effective_runware_key()
    if fal:
        os.environ["FAL_KEY"] = fal
    if xai:
        os.environ["XAI_API_KEY"] = xai
    if runware:
        os.environ["RUNWARE_API_KEY"] = runware
    # Invalidate cached xAI client so new keys take effect
    try:
        from media_studio.xai_client import get_client

        get_client.cache_clear()
    except Exception:
        pass
