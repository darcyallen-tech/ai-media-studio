"""
Local “My Voices” store for custom MiniMax clones.

Saved under data/my_voices.json so custom voices reappear in Voiceover.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from media_studio.config import PROJECT_ROOT

VOICES_DIR = PROJECT_ROOT / "data"
VOICES_FILE = VOICES_DIR / "my_voices.json"
SAMPLES_DIR = VOICES_DIR / "voice_samples"

_MY_PREFIX = "My · "
_DEFAULT_PREFIX = "Default · "


@dataclass
class SavedVoice:
    id: str
    name: str
    provider: str  # minimax
    custom_voice_id: str
    created_at: str
    preview_path: str | None = None
    sample_path: str | None = None
    notes: str = ""

    def choice_label(self) -> str:
        return f"{_MY_PREFIX}{self.name}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _ensure_store() -> None:
    VOICES_DIR.mkdir(parents=True, exist_ok=True)
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    if not VOICES_FILE.is_file():
        VOICES_FILE.write_text(
            json.dumps({"voices": []}, indent=2),
            encoding="utf-8",
        )


def load_voices() -> list[SavedVoice]:
    _ensure_store()
    try:
        data = json.loads(VOICES_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    raw = data.get("voices") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return []
    out: list[SavedVoice] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        vid = str(item.get("custom_voice_id") or "").strip()
        if not name or not vid:
            continue
        out.append(
            SavedVoice(
                id=str(item.get("id") or uuid.uuid4().hex[:12]),
                name=name,
                provider=str(item.get("provider") or "minimax"),
                custom_voice_id=vid,
                created_at=str(item.get("created_at") or _now_iso()),
                preview_path=item.get("preview_path"),
                sample_path=item.get("sample_path"),
                notes=str(item.get("notes") or ""),
            )
        )
    return out


def save_voices(voices: list[SavedVoice]) -> None:
    _ensure_store()
    payload = {"voices": [asdict(v) for v in voices]}
    VOICES_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _slug_name(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower())
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return (s or "voice")[:40]


def add_voice(
    *,
    name: str,
    custom_voice_id: str,
    provider: str = "minimax",
    preview_path: str | None = None,
    sample_path: str | None = None,
    notes: str = "",
) -> SavedVoice:
    name = (name or "").strip()
    if not name:
        raise ValueError("Voice name is required.")
    custom_voice_id = (custom_voice_id or "").strip()
    if not custom_voice_id:
        raise ValueError("custom_voice_id is required.")

    voices = load_voices()
    # Replace same name
    voices = [v for v in voices if v.name.lower() != name.lower()]
    entry = SavedVoice(
        id=uuid.uuid4().hex[:12],
        name=name,
        provider=provider,
        custom_voice_id=custom_voice_id,
        created_at=_now_iso(),
        preview_path=preview_path,
        sample_path=sample_path,
        notes=notes or "",
    )
    voices.insert(0, entry)
    save_voices(voices)
    return entry


def delete_voice(name_or_id: str | None) -> bool:
    if not name_or_id:
        return False
    key = name_or_id.strip()
    if key.startswith(_MY_PREFIX):
        key = key[len(_MY_PREFIX) :].strip()
    voices = load_voices()
    before = len(voices)
    voices = [
        v
        for v in voices
        if v.id != key and v.name.lower() != key.lower() and v.choice_label() != name_or_id
    ]
    if len(voices) == before:
        return False
    save_voices(voices)
    return True


def find_voice(label_or_name: str | None) -> SavedVoice | None:
    if not label_or_name:
        return None
    raw = label_or_name.strip()
    if raw.startswith(_MY_PREFIX):
        raw = raw[len(_MY_PREFIX) :].strip()
    elif raw.startswith("My: "):
        raw = raw[4:].strip()
    for v in load_voices():
        if v.name.lower() == raw.lower() or v.id == raw or v.choice_label() == label_or_name:
            return v
    return None


def is_my_voice_label(label: str | None) -> bool:
    if not label:
        return False
    s = label.strip()
    return s.startswith(_MY_PREFIX) or s.startswith("My: ") or find_voice(s) is not None


def strip_default_prefix(label: str | None) -> str:
    if not label:
        return ""
    s = label.strip()
    if s.startswith(_DEFAULT_PREFIX):
        return s[len(_DEFAULT_PREFIX) :].strip()
    return s


def voice_choice_labels(*, default_voices: list[str]) -> list[str]:
    """My voices first, then Default · built-ins."""
    mine = [v.choice_label() for v in load_voices()]
    defaults = [f"{_DEFAULT_PREFIX}{n}" for n in default_voices]
    return mine + defaults


def my_voice_names() -> list[str]:
    return [v.choice_label() for v in load_voices()]


def copy_sample_to_store(src: str | Path, voice_name: str) -> str | None:
    """Best-effort local copy of the clone sample for reference."""
    path = Path(src)
    if not path.is_file():
        return None
    _ensure_store()
    dest = SAMPLES_DIR / f"{_slug_name(voice_name)}{path.suffix or '.wav'}"
    try:
        dest.write_bytes(path.read_bytes())
        return str(dest.resolve())
    except OSError:
        return None
