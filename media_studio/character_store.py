"""
Local Characters store — reusable character stills for Motion Sync, Director, etc.

Saved under data/characters.json; still files copied to data/character_stills/.
Supports 1–3 stills per character (primary + optional angles). No cloud sync.
"""

from __future__ import annotations

import json
import re
import shutil
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from media_studio.config import PROJECT_ROOT

DATA_DIR = PROJECT_ROOT / "data"
CHARACTERS_FILE = DATA_DIR / "characters.json"
STILLS_DIR = DATA_DIR / "character_stills"

MAX_STILLS_PER_CHARACTER = 3

# Default I2I prompt for Generate variation (face-lock style)
VARIATION_PROMPT = (
    "Keep the same person identity, face, hair, age, and body proportions. "
    "Create a subtle character-reference variation: alternate angle or slight pose "
    "change only. Photoreal, clean simple background, full-body or clear upper body, "
    "head fully visible and unobstructed."
)

DEFAULT_VARIATION_MODEL = "flux 2 pro"


@dataclass
class SavedCharacter:
    id: str
    name: str
    still_path: str  # primary still (Phase 1 compat)
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""
    # Extra angles after primary; full list = [still_path] + extras when empty
    still_paths: list[str] = field(default_factory=list)

    def display_notes(self) -> str:
        return (self.notes or "").strip()

    def all_stills(self) -> list[str]:
        """Ordered unique paths: primary first, then extras (max 3)."""
        ordered: list[str] = []
        if self.still_paths:
            for p in self.still_paths:
                s = (p or "").strip()
                if s and s not in ordered:
                    ordered.append(s)
        primary = (self.still_path or "").strip()
        if primary and primary not in ordered:
            ordered.insert(0, primary)
        elif primary and ordered and ordered[0] != primary:
            # Prefer explicit still_path as primary
            ordered = [primary] + [p for p in ordered if p != primary]
        return ordered[:MAX_STILLS_PER_CHARACTER]

    def primary_still(self) -> str | None:
        alls = self.all_stills()
        return alls[0] if alls else None

    def angle_count(self) -> int:
        return len(self.all_stills())


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


def _normalize_paths(primary: str, extras: list[str] | None) -> tuple[str, list[str]]:
    ordered: list[str] = []
    for p in [primary] + list(extras or []):
        s = (p or "").strip()
        if s and s not in ordered:
            ordered.append(s)
    ordered = ordered[:MAX_STILLS_PER_CHARACTER]
    if not ordered:
        return "", []
    return ordered[0], ordered


def _from_dict(item: dict[str, Any]) -> SavedCharacter | None:
    name = str(item.get("name") or "").strip()
    still = str(item.get("still_path") or "").strip()
    raw_paths = item.get("still_paths")
    paths: list[str] = []
    if isinstance(raw_paths, list):
        for p in raw_paths:
            s = str(p or "").strip()
            if s and s not in paths:
                paths.append(s)
    if still and still not in paths:
        paths.insert(0, still)
    if not name or not paths:
        return None
    primary, all_paths = _normalize_paths(paths[0], paths[1:])
    return SavedCharacter(
        id=str(item.get("id") or uuid.uuid4().hex[:12]),
        name=name,
        still_path=primary,
        notes=str(item.get("notes") or ""),
        created_at=str(item.get("created_at") or _now_iso()),
        updated_at=str(item.get("updated_at") or item.get("created_at") or ""),
        still_paths=all_paths,
    )


def _to_dict(c: SavedCharacter) -> dict[str, Any]:
    alls = c.all_stills()
    primary = alls[0] if alls else (c.still_path or "")
    return {
        "id": c.id,
        "name": c.name,
        "still_path": primary,
        "still_paths": alls,
        "notes": c.notes or "",
        "created_at": c.created_at,
        "updated_at": c.updated_at,
    }


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
        entry = _from_dict(item)
        if entry:
            out.append(entry)
    return out


def save_characters(characters: list[SavedCharacter]) -> None:
    _ensure_store()
    payload: dict[str, Any] = {
        "characters": [_to_dict(c) for c in characters],
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


def _copy_still(
    src: Path,
    *,
    char_id: str,
    name: str,
    angle_index: int = 0,
) -> Path:
    """Copy still into data/character_stills; returns destination path."""
    _ensure_store()
    if not src.is_file():
        raise FileNotFoundError(f"Still missing: {src}")
    ext = src.suffix.lower() or ".jpg"
    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".bmp"):
        ext = ".jpg"
    suffix = "" if angle_index == 0 else f"_a{angle_index}"
    dest = STILLS_DIR / f"{_slug_name(name)}_{char_id}{suffix}{ext}"
    # Avoid clobbering when multiple adds race — unique if exists
    if dest.is_file():
        try:
            if src.resolve() == dest.resolve():
                return dest
        except OSError:
            pass
        dest = STILLS_DIR / (
            f"{_slug_name(name)}_{char_id}{suffix}_{uuid.uuid4().hex[:6]}{ext}"
        )
    shutil.copy2(str(src), str(dest))
    return dest.resolve()


def _owned_still(path: str | Path) -> bool:
    try:
        p = Path(path).resolve()
        return STILLS_DIR.resolve() in p.parents and p.is_file()
    except OSError:
        return False


def _delete_owned(path: str | None) -> None:
    if not path:
        return
    try:
        p = Path(path)
        if _owned_still(p):
            p.unlink(missing_ok=True)
    except OSError:
        pass


def add_character(
    *,
    name: str,
    still_path: str | Path,
    notes: str = "",
    extra_stills: list[str | Path] | None = None,
) -> SavedCharacter:
    name = (name or "").strip()
    if not name:
        raise ValueError("Name is required.")
    src = Path(still_path)
    if not src.is_file():
        raise FileNotFoundError(f"Still missing: {src}")

    characters = load_characters()
    char_id = uuid.uuid4().hex[:12]
    stored_paths: list[str] = []
    primary = _copy_still(src, char_id=char_id, name=name, angle_index=0)
    stored_paths.append(str(primary))
    for i, extra in enumerate(extra_stills or [], start=1):
        if len(stored_paths) >= MAX_STILLS_PER_CHARACTER:
            break
        ep = Path(extra)
        if not ep.is_file():
            continue
        try:
            if ep.resolve() == src.resolve():
                continue
        except OSError:
            pass
        sp = _copy_still(ep, char_id=char_id, name=name, angle_index=i)
        s = str(sp)
        if s not in stored_paths:
            stored_paths.append(s)

    now = _now_iso()
    entry = SavedCharacter(
        id=char_id,
        name=name,
        still_path=stored_paths[0],
        notes=(notes or "").strip(),
        created_at=now,
        updated_at=now,
        still_paths=stored_paths,
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
    still_paths: list[str | Path] | None = None,
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

    if still_paths is not None:
        copied: list[str] = []
        for ai, p in enumerate(still_paths):
            if len(copied) >= MAX_STILLS_PER_CHARACTER:
                break
            src = Path(p)
            if not src.is_file():
                continue
            # Keep owned paths as-is; copy external ones
            if _owned_still(src):
                s = str(src.resolve())
            else:
                s = str(
                    _copy_still(
                        src, char_id=found.id, name=new_name, angle_index=ai
                    )
                )
            if s not in copied:
                copied.append(s)
        if not copied:
            raise ValueError("At least one still is required.")
        primary, all_paths = _normalize_paths(copied[0], copied[1:])
    elif still_path is not None:
        src = Path(still_path)
        if not src.is_file():
            raise FileNotFoundError(f"Still missing: {src}")
        # Replace primary, keep extras
        new_primary = str(
            _copy_still(src, char_id=found.id, name=new_name, angle_index=0)
        )
        extras = [p for p in found.all_stills()[1:] if p != new_primary]
        primary, all_paths = _normalize_paths(new_primary, extras)
    else:
        primary, all_paths = _normalize_paths(
            found.still_path, found.all_stills()[1:]
        )

    updated = SavedCharacter(
        id=found.id,
        name=new_name,
        still_path=primary,
        notes=(new_notes or "").strip(),
        created_at=found.created_at or _now_iso(),
        updated_at=_now_iso(),
        still_paths=all_paths,
    )
    characters[idx] = updated
    save_characters(characters)
    return updated


def add_character_angle(
    char_id: str,
    still_path: str | Path,
    *,
    as_primary: bool = False,
) -> SavedCharacter | None:
    """Add an angle still (max 3). Optionally make it the new primary."""
    found = find_character(char_id)
    if found is None:
        return None
    src = Path(still_path)
    if not src.is_file():
        raise FileNotFoundError(f"Still missing: {src}")
    current = found.all_stills()

    stored = str(
        _copy_still(
            src,
            char_id=found.id,
            name=found.name,
            angle_index=len(current),
        )
    )
    if as_primary:
        # New primary first; drop oldest extra if already at cap
        new_list = [stored] + [p for p in current if p != stored]
        new_list = new_list[:MAX_STILLS_PER_CHARACTER]
    else:
        if stored in current:
            return found
        if len(current) >= MAX_STILLS_PER_CHARACTER:
            raise ValueError(
                f"Max {MAX_STILLS_PER_CHARACTER} stills per character. "
                "Remove an angle first."
            )
        new_list = current + [stored]
    return update_character(char_id, still_paths=new_list)


def remove_character_angle(char_id: str, still_path: str) -> SavedCharacter | None:
    found = find_character(char_id)
    if found is None:
        return None
    target = str(Path(still_path).resolve()) if Path(still_path).is_file() else still_path
    remaining: list[str] = []
    for p in found.all_stills():
        try:
            same = str(Path(p).resolve()) == target or p == still_path
        except OSError:
            same = p == still_path
        if same:
            _delete_owned(p)
            continue
        remaining.append(p)
    if not remaining:
        raise ValueError("Cannot remove the last still — delete the character instead.")
    return update_character(char_id, still_paths=remaining)


def set_primary_angle(char_id: str, still_path: str) -> SavedCharacter | None:
    found = find_character(char_id)
    if found is None:
        return None
    alls = found.all_stills()
    match = None
    for p in alls:
        try:
            if p == still_path or str(Path(p).resolve()) == str(
                Path(still_path).resolve()
            ):
                match = p
                break
        except OSError:
            if p == still_path:
                match = p
                break
    if not match:
        raise ValueError("Still not found on this character.")
    new_list = [match] + [p for p in alls if p != match]
    return update_character(char_id, still_paths=new_list)


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
    if remove_file:
        for p in removed.all_stills():
            _delete_owned(p)
    return True
