"""
Local Characters store — reusable character stills for Motion Sync, Director, etc.

Saved under data/characters.json; still files copied to data/character_stills/.
No cloud sync.
"""

from __future__ import annotations

import json
import re
import shutil
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from media_studio.config import PROJECT_ROOT

DATA_DIR = PROJECT_ROOT / "data"
CHARACTERS_FILE = DATA_DIR / "characters.json"
STILLS_DIR = DATA_DIR / "character_stills"


@dataclass
class SavedCharacter:
    id: str
    name: str
    still_path: str
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""

    def display_notes(self) -> str:
        return (self.notes or "").strip()


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _ensure_store() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    STILLS_DIR.mkdir(parents=True, exist_ok=True)
    if not CHARACTERS_FILE.is_file():
        CHARACTERS_FILE.write_text(
            json.dumps({"characters": []}, indent=2) + "\n",
            encoding="utf-8",
        )


def _slug_name(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower())
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return (s or "character")[:40]


def load_characters() -> list[SavedCharacter]:
    _ensure_store()
    try:
        data = json.loads(CHARACTERS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    raw = data.get("characters") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return []
    out: list[SavedCharacter] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        still = str(item.get("still_path") or "").strip()
        if not name or not still:
            continue
        out.append(
            SavedCharacter(
                id=str(item.get("id") or uuid.uuid4().hex[:12]),
                name=name,
                still_path=still,
                notes=str(item.get("notes") or ""),
                created_at=str(item.get("created_at") or _now_iso()),
                updated_at=str(item.get("updated_at") or item.get("created_at") or ""),
            )
        )
    return out


def save_characters(characters: list[SavedCharacter]) -> None:
    _ensure_store()
    payload: dict[str, Any] = {
        "characters": [asdict(c) for c in characters],
    }
    CHARACTERS_FILE.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def find_character(id_or_name: str | None) -> SavedCharacter | None:
    if not id_or_name:
        return None
    key = id_or_name.strip()
    for c in load_characters():
        if c.id == key or c.name.lower() == key.lower():
            return c
    return None


def _copy_still(src: Path, *, char_id: str, name: str) -> Path:
    """Copy still into data/character_stills; returns destination path."""
    _ensure_store()
    if not src.is_file():
        raise FileNotFoundError(f"Still missing: {src}")
    ext = src.suffix.lower() or ".jpg"
    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".bmp"):
        ext = ".jpg"
    dest = STILLS_DIR / f"{_slug_name(name)}_{char_id}{ext}"
    # Same path already in our store
    try:
        if src.resolve() == dest.resolve():
            return dest
    except OSError:
        pass
    shutil.copy2(str(src), str(dest))
    return dest.resolve()


def add_character(
    *,
    name: str,
    still_path: str | Path,
    notes: str = "",
) -> SavedCharacter:
    name = (name or "").strip()
    if not name:
        raise ValueError("Name is required.")
    src = Path(still_path)
    if not src.is_file():
        raise FileNotFoundError(f"Still missing: {src}")

    characters = load_characters()
    # Unique name: if same name exists, keep both with distinct ids (allow duplicates
    # only when user re-saves as new — replace exact same still+name is update-like)
    char_id = uuid.uuid4().hex[:12]
    stored = _copy_still(src, char_id=char_id, name=name)
    now = _now_iso()
    entry = SavedCharacter(
        id=char_id,
        name=name,
        still_path=str(stored),
        notes=(notes or "").strip(),
        created_at=now,
        updated_at=now,
    )
    characters.insert(0, entry)
    save_characters(characters)
    return entry


def update_character(
    char_id: str,
    *,
    name: str | None = None,
    notes: str | None = None,
    still_path: str | Path | None = None,
) -> SavedCharacter | None:
    characters = load_characters()
    found: SavedCharacter | None = None
    idx = -1
    for i, c in enumerate(characters):
        if c.id == char_id:
            found = c
            idx = i
            break
    if found is None or idx < 0:
        return None

    new_name = (name if name is not None else found.name).strip()
    if not new_name:
        raise ValueError("Name is required.")
    new_notes = notes if notes is not None else found.notes
    new_still = found.still_path
    if still_path is not None:
        src = Path(still_path)
        if not src.is_file():
            raise FileNotFoundError(f"Still missing: {src}")
        new_still = str(_copy_still(src, char_id=found.id, name=new_name))

    updated = SavedCharacter(
        id=found.id,
        name=new_name,
        still_path=new_still,
        notes=(new_notes or "").strip(),
        created_at=found.created_at or _now_iso(),
        updated_at=_now_iso(),
    )
    characters[idx] = updated
    save_characters(characters)
    return updated


def delete_character(char_id: str | None, *, remove_file: bool = True) -> bool:
    if not char_id:
        return False
    characters = load_characters()
    keep: list[SavedCharacter] = []
    removed: SavedCharacter | None = None
    for c in characters:
        if c.id == char_id:
            removed = c
        else:
            keep.append(c)
    if removed is None:
        return False
    save_characters(keep)
    if remove_file and removed.still_path:
        try:
            p = Path(removed.still_path)
            # Only delete files we own under character_stills
            if p.is_file() and STILLS_DIR.resolve() in p.resolve().parents:
                p.unlink(missing_ok=True)
        except OSError:
            pass
    return True
