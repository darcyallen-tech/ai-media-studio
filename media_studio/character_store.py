"""
Local Characters store — reusable character stills for Motion Sync, Director, etc.

Identity pack: Front / Side / Close-up (up to 3 slots).
Saved under data/characters.json; stills in data/character_stills/. No cloud.
"""

from __future__ import annotations

import json
import re
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from media_studio.config import PROJECT_ROOT

DATA_DIR = PROJECT_ROOT / "data"
CHARACTERS_FILE = DATA_DIR / "characters.json"
STILLS_DIR = DATA_DIR / "character_stills"

# Identity pack slots (order matters for primary preference)
IDENTITY_SLOTS: tuple[str, ...] = ("front", "side", "closeup")
SLOT_LABELS: dict[str, str] = {
    "front": "Front (full or ¾ body)",
    "side": "Side (profile)",
    "closeup": "Close-up (face)",
}
SLOT_SHORT: dict[str, str] = {
    "front": "Front",
    "side": "Side",
    "closeup": "Close-up",
}
SLOT_VIEW_HINT: dict[str, str] = {
    "front": "front view, full or three-quarter body, head fully visible",
    "side": "side profile view of the same person",
    "closeup": "face close-up portrait of the same person",
}

# Shared clean-plate language for generated identity / costume angles
CLEAN_PLATE_BG = (
    "Pure solid black background only (#000000). Isolated subject on a clean plate — "
    "no environment, no floor, no ground plane, no vignette, no props, no furniture, "
    "no other people, no text, no logo. Clean silhouette, full subject correctly framed "
    "and fully visible for the target angle. Ready for composite / Motion Sync."
)

MAX_STILLS_PER_CHARACTER = 3

# Default I2I prompt for Generate variation (face-lock style)
VARIATION_PROMPT = (
    "Keep the same person identity, face, hair, age, and body proportions. "
    "Create a subtle character-reference variation: alternate angle or slight pose "
    "change only. Photoreal, full-body or clear upper body, head fully visible. "
    + CLEAN_PLATE_BG
)

DEFAULT_VARIATION_MODEL = "flux 2 pro"
DEFAULT_COSTUME_MODEL = "flux 2 pro"  # multi-ref image edit


@dataclass
class SavedCharacter:
    id: str
    name: str
    still_path: str  # primary (Front preferred) — Phase 1 compat
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""
    # Ordered list for Phase 2 compat (front, side, closeup filled only)
    still_paths: list[str] = field(default_factory=list)
    # Named identity pack: slot key -> absolute path
    identity: dict[str, str] = field(default_factory=dict)
    # Costume variant: points at base character id (None = top-level base)
    parent_id: str | None = None
    # Protect from retention / auto-delete of character stills
    locked: bool = False

    def display_notes(self) -> str:
        return (self.notes or "").strip()

    def is_costume_variant(self) -> bool:
        return bool((self.parent_id or "").strip())

    def is_base(self) -> bool:
        return not self.is_costume_variant()

    def _sync_from_identity(self) -> None:
        """Keep still_path / still_paths aligned with identity pack."""
        pack = self.normalized_identity()
        self.identity = pack
        ordered = [pack[s] for s in IDENTITY_SLOTS if pack.get(s)]
        self.still_paths = ordered
        self.still_path = ordered[0] if ordered else ""

    def normalized_identity(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for slot in IDENTITY_SLOTS:
            p = (self.identity.get(slot) or "").strip()
            if p:
                out[slot] = p
        # Fallback from still_paths if identity empty
        if not out and self.still_paths:
            for slot, p in zip(IDENTITY_SLOTS, self.still_paths):
                s = (p or "").strip()
                if s:
                    out[slot] = s
        elif not out and self.still_path:
            out["front"] = self.still_path.strip()
        return out

    def all_stills(self) -> list[str]:
        """Filled stills in slot order (Front → Side → Close-up)."""
        pack = self.normalized_identity()
        return [pack[s] for s in IDENTITY_SLOTS if pack.get(s)]

    def primary_still(self) -> str | None:
        """Front preferred, else first available slot."""
        pack = self.normalized_identity()
        if pack.get("front"):
            return pack["front"]
        for s in IDENTITY_SLOTS:
            if pack.get(s):
                return pack[s]
        return None

    def angle_count(self) -> int:
        return len(self.all_stills())

    def filled_slots(self) -> list[tuple[str, str]]:
        pack = self.normalized_identity()
        return [(s, pack[s]) for s in IDENTITY_SLOTS if pack.get(s)]

    def get_slot(self, slot: str) -> str | None:
        key = _norm_slot(slot)
        if not key:
            return None
        return self.normalized_identity().get(key)

    def slot_summary(self) -> str:
        pack = self.normalized_identity()
        parts = [SLOT_SHORT[s] for s in IDENTITY_SLOTS if pack.get(s)]
        if not parts:
            return "no stills"
        return " · ".join(parts)


def _norm_slot(slot: str | None) -> str | None:
    if not slot:
        return None
    s = slot.strip().lower().replace("-", "").replace(" ", "").replace("_", "")
    aliases = {
        "front": "front",
        "primary": "front",
        "full": "front",
        "side": "side",
        "profile": "side",
        "closeup": "closeup",
        "close": "closeup",
        "face": "closeup",
    }
    return aliases.get(s)


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


def _from_dict(item: dict[str, Any]) -> SavedCharacter | None:
    name = str(item.get("name") or "").strip()
    if not name:
        return None

    identity: dict[str, str] = {}
    raw_id = item.get("identity")
    if isinstance(raw_id, dict):
        for slot in IDENTITY_SLOTS:
            p = str(raw_id.get(slot) or "").strip()
            if p:
                identity[slot] = p

    # Legacy still_paths / still_path → fill empty slots in order
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

    if not identity and paths:
        for slot, p in zip(IDENTITY_SLOTS, paths):
            identity[slot] = p
    elif identity and paths:
        # Ensure primary still appears as front if front empty
        if still and not identity.get("front"):
            identity["front"] = still

    if not identity:
        return None

    parent_raw = item.get("parent_id")
    parent_id = str(parent_raw).strip() if parent_raw else None
    if parent_id == "":
        parent_id = None
    entry = SavedCharacter(
        id=str(item.get("id") or uuid.uuid4().hex[:12]),
        name=name,
        still_path="",
        notes=str(item.get("notes") or ""),
        created_at=str(item.get("created_at") or _now_iso()),
        updated_at=str(item.get("updated_at") or item.get("created_at") or ""),
        still_paths=[],
        identity=identity,
        parent_id=parent_id,
        locked=bool(item.get("locked") or False),
    )
    entry._sync_from_identity()
    return entry


def _to_dict(c: SavedCharacter) -> dict[str, Any]:
    c._sync_from_identity()
    return {
        "id": c.id,
        "name": c.name,
        "still_path": c.still_path,
        "still_paths": list(c.still_paths),
        "identity": dict(c.normalized_identity()),
        "notes": c.notes or "",
        "created_at": c.created_at,
        "updated_at": c.updated_at,
        "parent_id": c.parent_id or None,
        "locked": bool(c.locked),
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
    slot: str = "front",
) -> Path:
    _ensure_store()
    if not src.is_file():
        raise FileNotFoundError(f"Still missing: {src}")
    ext = src.suffix.lower() or ".jpg"
    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".bmp"):
        ext = ".jpg"
    slot_key = _norm_slot(slot) or "front"
    dest = STILLS_DIR / f"{_slug_name(name)}_{char_id}_{slot_key}{ext}"
    if dest.is_file():
        try:
            if src.resolve() == dest.resolve():
                return dest
        except OSError:
            pass
        dest = STILLS_DIR / (
            f"{_slug_name(name)}_{char_id}_{slot_key}_{uuid.uuid4().hex[:6]}{ext}"
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


def _store_path(
    src: Path,
    *,
    char_id: str,
    name: str,
    slot: str,
) -> str:
    if _owned_still(src):
        return str(src.resolve())
    return str(_copy_still(src, char_id=char_id, name=name, slot=slot))


def add_character(
    *,
    name: str,
    still_path: str | Path,
    notes: str = "",
    extra_stills: list[str | Path] | None = None,
    identity: dict[str, str | Path] | None = None,
    parent_id: str | None = None,
    locked: bool = False,
) -> SavedCharacter:
    """
    Create character. ``still_path`` fills Front unless ``identity`` provides slots.
    ``extra_stills`` fill Side then Close-up in order.
    """
    name = (name or "").strip()
    if not name:
        raise ValueError("Name is required.")

    pack: dict[str, str] = {}
    char_id = uuid.uuid4().hex[:12]

    if identity:
        for slot in IDENTITY_SLOTS:
            raw = identity.get(slot)
            if not raw:
                continue
            p = Path(raw)
            if p.is_file():
                pack[slot] = _store_path(
                    p, char_id=char_id, name=name, slot=slot
                )
    if not pack:
        src = Path(still_path)
        if not src.is_file():
            raise FileNotFoundError(f"Still missing: {src}")
        pack["front"] = _store_path(src, char_id=char_id, name=name, slot="front")
        for slot, extra in zip(("side", "closeup"), extra_stills or []):
            ep = Path(extra)
            if ep.is_file():
                pack[slot] = _store_path(
                    ep, char_id=char_id, name=name, slot=slot
                )

    if not pack:
        raise ValueError("At least one identity still is required.")

    parent = (parent_id or "").strip() or None
    if parent:
        # Resolve parent from current store (must exist to attach costume)
        parent_ok = any(c.id == parent for c in load_characters())
        if not parent_ok:
            raise ValueError(
                f"Costume parent id not found: {parent}. "
                "Save as a top-level character or open Costume swap from the parent."
            )
    now = _now_iso()
    entry = SavedCharacter(
        id=char_id,
        name=name,
        still_path="",
        notes=(notes or "").strip(),
        created_at=now,
        updated_at=now,
        identity=pack,
        parent_id=parent,
        locked=bool(locked),
    )
    entry._sync_from_identity()
    characters = load_characters()
    characters.insert(0, entry)
    save_characters(characters)
    return entry


def list_base_characters() -> list[SavedCharacter]:
    """Top-level characters only (not costume children)."""
    migrate_orphan_costume_links()
    return [c for c in load_characters() if c.is_base()]


def list_costume_children(parent_id: str | None) -> list[SavedCharacter]:
    if not parent_id:
        return []
    pid = parent_id.strip()
    return [c for c in load_characters() if (c.parent_id or "") == pid]


@dataclass(frozen=True)
class CharacterPickerChoice:
    """One row for app-wide Character picker (base or costume variant)."""

    id: str
    label: str
    still_path: str
    is_costume: bool = False
    parent_id: str | None = None
    parent_name: str | None = None

    @property
    def has_still(self) -> bool:
        try:
            return bool(self.still_path) and Path(self.still_path).is_file()
        except OSError:
            return False


def _costume_display_name(costume_name: str, parent_name: str | None) -> str:
    """
    Outfit part of picker labels like ``Alice / Red Dress``.
    Strips leading ``Parent – `` when costume was named ``Alice – Red Dress``.
    """
    name = (costume_name or "").strip() or "Outfit"
    parent = (parent_name or "").strip()
    if parent:
        for sep in (" – ", " — ", " - ", " –", " —", " -"):
            prefix = parent + sep
            if name.lower().startswith(prefix.lower()):
                rest = name[len(prefix) :].strip()
                if rest:
                    return rest
        if name.lower().startswith(parent.lower() + " "):
            rest = name[len(parent) :].strip(" -–—")
            if rest:
                return rest
    return name


def character_picker_choices() -> list[CharacterPickerChoice]:
    """
    Flat list for dropdowns: bases first, then each costume as ``Parent / Costume``.
    Only entries with at least one usable still (Front preferred).
    """
    migrate_orphan_costume_links()
    all_chars = load_characters()
    by_id = {c.id: c for c in all_chars}
    bases = [c for c in all_chars if c.is_base()]
    out: list[CharacterPickerChoice] = []
    for base in bases:
        still = base.primary_still()
        if still and Path(still).is_file():
            out.append(
                CharacterPickerChoice(
                    id=base.id,
                    label=base.name,
                    still_path=still,
                    is_costume=False,
                )
            )
        for kid in list_costume_children(base.id):
            kstill = kid.primary_still()
            if not kstill or not Path(kstill).is_file():
                continue
            outfit = _costume_display_name(kid.name, base.name)
            out.append(
                CharacterPickerChoice(
                    id=kid.id,
                    label=f"{base.name} / {outfit}",
                    still_path=kstill,
                    is_costume=True,
                    parent_id=base.id,
                    parent_name=base.name,
                )
            )
    # Orphan costumes (parent missing) still appear
    for c in all_chars:
        if c.is_base() or c.id in {x.id for x in out}:
            continue
        still = c.primary_still()
        if not still or not Path(still).is_file():
            continue
        parent = by_id.get(c.parent_id or "")
        if parent:
            outfit = _costume_display_name(c.name, parent.name)
            label = f"{parent.name} / {outfit}"
            parent_name = parent.name
        else:
            label = c.name
            parent_name = None
        out.append(
            CharacterPickerChoice(
                id=c.id,
                label=label,
                still_path=still,
                is_costume=True,
                parent_id=c.parent_id,
                parent_name=parent_name,
            )
        )
    return out


def find_picker_choice(char_id: str | None) -> CharacterPickerChoice | None:
    if not char_id:
        return None
    for ch in character_picker_choices():
        if ch.id == char_id:
            return ch
    return None


_COSTUME_NAME_SEPS = (" – ", " — ", " - ")


def migrate_orphan_costume_links() -> int:
    """
    Link top-level entries named like ``{Base} – outfit`` as children of Base.

    Idempotent. Fixes costumes saved before parent_id wiring (e.g.
    ``Camera Man – Secret Identity`` under ``Camera Man``).
    """
    characters = load_characters()
    if not characters:
        return 0
    # Prefer longest base name match so nested names resolve correctly
    bases = [c for c in characters if c.is_base()]
    bases_by_lower = {c.name.strip().lower(): c for c in bases}
    changed = 0
    for c in characters:
        if c.parent_id:
            continue
        # Skip true bases that already own costumes or have no separator
        raw = (c.name or "").strip()
        parent_match: SavedCharacter | None = None
        for sep in _COSTUME_NAME_SEPS:
            if sep not in raw:
                continue
            prefix = raw.split(sep, 1)[0].strip()
            if not prefix:
                continue
            cand = bases_by_lower.get(prefix.lower())
            if cand and cand.id != c.id:
                parent_match = cand
                break
        if parent_match is None:
            continue
        # Do not reparent if this character is itself a base for others
        if any((o.parent_id or "") == c.id for o in characters):
            continue
        c.parent_id = parent_match.id
        changed += 1
    if changed:
        save_characters(characters)
    return changed


def set_character_locked(char_id: str, locked: bool) -> SavedCharacter | None:
    characters = load_characters()
    for i, c in enumerate(characters):
        if c.id != char_id:
            continue
        c.locked = bool(locked)
        c.updated_at = _now_iso()
        characters[i] = c
        save_characters(characters)
        return c
    return None


def update_character(
    char_id: str,
    *,
    name: str | None = None,
    notes: str | None = None,
    still_path: str | Path | None = None,
    still_paths: list[str | Path] | None = None,
    identity: dict[str, str | Path | None] | None = None,
    parent_id: str | None | object = ...,  # type: ignore[assignment]
    locked: bool | None = None,
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
    pack = dict(found.normalized_identity())

    if identity is not None:
        pack = {}
        for slot in IDENTITY_SLOTS:
            raw = identity.get(slot)
            if raw is None or raw == "":
                continue
            p = Path(str(raw))
            if p.is_file():
                pack[slot] = _store_path(
                    p, char_id=found.id, name=new_name, slot=slot
                )
    elif still_paths is not None:
        pack = {}
        for slot, p in zip(IDENTITY_SLOTS, still_paths):
            src = Path(p)
            if src.is_file():
                pack[slot] = _store_path(
                    src, char_id=found.id, name=new_name, slot=slot
                )
    elif still_path is not None:
        src = Path(still_path)
        if not src.is_file():
            raise FileNotFoundError(f"Still missing: {src}")
        pack["front"] = _store_path(
            src, char_id=found.id, name=new_name, slot="front"
        )

    if not pack:
        raise ValueError("At least one identity still is required.")

    new_parent = found.parent_id
    if parent_id is not ...:  # explicit set (including None)
        new_parent = (str(parent_id).strip() if parent_id else None) or None
    new_locked = found.locked if locked is None else bool(locked)

    updated = SavedCharacter(
        id=found.id,
        name=new_name,
        still_path="",
        notes=(new_notes or "").strip(),
        created_at=found.created_at or _now_iso(),
        updated_at=_now_iso(),
        identity=pack,
        parent_id=new_parent,
        locked=new_locked,
    )
    updated._sync_from_identity()
    characters[idx] = updated
    save_characters(characters)
    return updated


def set_character_slot(
    char_id: str,
    slot: str,
    still_path: str | Path | None,
    *,
    clear: bool = False,
) -> SavedCharacter | None:
    """Assign or clear one identity slot. Front preferred; last still cannot clear all."""
    found = find_character(char_id)
    if found is None:
        return None
    key = _norm_slot(slot)
    if not key:
        raise ValueError(f"Unknown slot: {slot}")
    pack = dict(found.normalized_identity())
    if clear or still_path is None:
        if key in pack:
            old = pack.pop(key)
            if not pack:
                raise ValueError(
                    "Cannot clear the last still — delete the character instead."
                )
            _delete_owned(old)
        return update_character(char_id, identity=pack)

    src = Path(still_path)
    if not src.is_file():
        raise FileNotFoundError(f"Still missing: {src}")
    pack[key] = _store_path(
        src, char_id=found.id, name=found.name, slot=key
    )
    return update_character(char_id, identity=pack)


def add_character_angle(
    char_id: str,
    still_path: str | Path,
    *,
    as_primary: bool = False,
    slot: str | None = None,
) -> SavedCharacter | None:
    """
    Add still to identity pack.
    If ``slot`` given, assign that slot; else first empty (front→side→closeup).
    ``as_primary`` forces Front.
    """
    found = find_character(char_id)
    if found is None:
        return None
    src = Path(still_path)
    if not src.is_file():
        raise FileNotFoundError(f"Still missing: {src}")
    pack = dict(found.normalized_identity())
    if as_primary:
        target = "front"
    elif slot:
        target = _norm_slot(slot)
        if not target:
            raise ValueError(f"Unknown slot: {slot}")
    else:
        target = None
        for s in IDENTITY_SLOTS:
            if s not in pack:
                target = s
                break
        if target is None:
            raise ValueError(
                f"Max {MAX_STILLS_PER_CHARACTER} identity stills. "
                "Clear a slot first."
            )
    return set_character_slot(char_id, target, src)


def remove_character_angle(char_id: str, still_path: str) -> SavedCharacter | None:
    found = find_character(char_id)
    if found is None:
        return None
    pack = dict(found.normalized_identity())
    target_slot = None
    for slot, p in pack.items():
        try:
            same = p == still_path or str(Path(p).resolve()) == str(
                Path(still_path).resolve()
            )
        except OSError:
            same = p == still_path
        if same:
            target_slot = slot
            break
    if not target_slot:
        raise ValueError("Still not found on this character.")
    return set_character_slot(char_id, target_slot, None, clear=True)


def set_primary_angle(char_id: str, still_path: str) -> SavedCharacter | None:
    """Promote a still to Front (swap with current Front if needed)."""
    found = find_character(char_id)
    if found is None:
        return None
    pack = dict(found.normalized_identity())
    match_slot = None
    for slot, p in pack.items():
        try:
            same = p == still_path or str(Path(p).resolve()) == str(
                Path(still_path).resolve()
            )
        except OSError:
            same = p == still_path
        if same:
            match_slot = slot
            break
    if not match_slot:
        raise ValueError("Still not found on this character.")
    if match_slot == "front":
        return found
    old_front = pack.get("front")
    pack["front"] = pack[match_slot]
    if old_front:
        pack[match_slot] = old_front
    else:
        del pack[match_slot]
    return update_character(char_id, identity=pack)


class CharacterHasChildrenError(ValueError):
    """Raised when deleting a base character that still has costume variants."""

    def __init__(self, char_id: str, children: list[SavedCharacter]) -> None:
        self.char_id = char_id
        self.children = children
        super().__init__(
            f"Character has {len(children)} costume variant(s). "
            "Delete costumes first, or confirm delete with children."
        )


def delete_character(
    char_id: str | None,
    *,
    remove_file: bool = True,
    delete_children: bool = False,
    force_children_check: bool = True,
) -> bool:
    """
    Delete a character. Base characters with costume children raise
    ``CharacterHasChildrenError`` unless ``delete_children=True``.
    """
    if not char_id:
        return False
    characters = load_characters()
    removed: SavedCharacter | None = None
    for c in characters:
        if c.id == char_id:
            removed = c
            break
    if removed is None:
        return False

    kids = [c for c in characters if (c.parent_id or "") == char_id]
    if kids and force_children_check and not delete_children:
        raise CharacterHasChildrenError(char_id, kids)

    remove_ids = {char_id}
    if delete_children:
        remove_ids |= {k.id for k in kids}

    keep: list[SavedCharacter] = []
    to_wipe: list[SavedCharacter] = []
    for c in characters:
        if c.id in remove_ids:
            to_wipe.append(c)
        else:
            keep.append(c)
    save_characters(keep)
    if remove_file:
        # Collect paths still referenced by remaining characters
        keep_paths: set[str] = set()
        for c in keep:
            for p in c.all_stills():
                try:
                    keep_paths.add(str(Path(p).resolve()))
                except OSError:
                    keep_paths.add(p)
        for c in to_wipe:
            for p in c.all_stills():
                try:
                    if str(Path(p).resolve()) not in keep_paths:
                        _delete_owned(p)
                except OSError:
                    _delete_owned(p)
    return True


def locked_still_paths() -> set[str]:
    """Absolute paths belonging to locked characters (skip on retention prune)."""
    out: set[str] = set()
    for c in load_characters():
        if not c.locked:
            continue
        for p in c.all_stills():
            try:
                out.add(str(Path(p).resolve()))
            except OSError:
                out.add(p)
    return out


def prune_unlocked_characters(
    *,
    retention_days: int | None,
) -> dict[str, int]:
    """
    Age-prune unlocked characters (and their stills) under data/character_stills.

    Locked characters are never removed. Costume children of a kept base stay
    if the base is kept; when a base is pruned, its unlocked children go too.
    """
    stats = {"deleted_chars": 0, "deleted_files": 0, "skipped_locked": 0}
    if not retention_days or retention_days <= 0:
        return stats
    cutoff = datetime.now(timezone.utc).timestamp() - float(retention_days) * 86400.0
    characters = load_characters()
    remove_ids: set[str] = set()

    def _age_ts(c: SavedCharacter) -> float:
        raw = c.updated_at or c.created_at or ""
        try:
            # ISO from _now_iso
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
        except Exception:
            return 0.0

    for c in characters:
        if c.locked:
            stats["skipped_locked"] += 1
            continue
        if _age_ts(c) < cutoff:
            remove_ids.add(c.id)

    # If base is removed, drop children too (unless child locked)
    for c in characters:
        if c.parent_id and c.parent_id in remove_ids:
            if c.locked:
                stats["skipped_locked"] += 1
                remove_ids.discard(c.id)  # keep locked child; reparent later
            else:
                remove_ids.add(c.id)

    if not remove_ids:
        return stats

    keep: list[SavedCharacter] = []
    wipe: list[SavedCharacter] = []
    for c in characters:
        if c.id in remove_ids:
            wipe.append(c)
        else:
            # Reparent locked children of pruned parents to top-level
            if c.parent_id and c.parent_id in remove_ids:
                c.parent_id = None
            keep.append(c)

    keep_paths: set[str] = set()
    for c in keep:
        for p in c.all_stills():
            try:
                keep_paths.add(str(Path(p).resolve()))
            except OSError:
                keep_paths.add(p)

    save_characters(keep)
    stats["deleted_chars"] = len(wipe)
    for c in wipe:
        for p in c.all_stills():
            try:
                rp = str(Path(p).resolve())
            except OSError:
                rp = p
            if rp not in keep_paths:
                before = Path(p).is_file() if p else False
                _delete_owned(p)
                if before:
                    stats["deleted_files"] += 1
    return stats


# ---------------------------------------------------------------------------
# Background remove (fal)
# ---------------------------------------------------------------------------

BG_REMOVE_ENDPOINT = "fal-ai/bria/background/remove"
BG_REMOVE_LABEL = "Bria RMBG 2.0"
BG_REMOVE_COST_PER_IMAGE = 0.018


def estimate_bg_remove_cost(n_images: int) -> str:
    from media_studio.pricing import format_job_cost

    n = max(0, int(n_images or 0))
    if n <= 0:
        return "Est. cost: —"
    total = round(BG_REMOVE_COST_PER_IMAGE * n, 3)
    return format_job_cost(
        total,
        unit=f"{n} image{'s' if n != 1 else ''}",
        model=BG_REMOVE_LABEL,
    )


def run_background_remove(
    image_path: str | Path,
    *,
    output_dir: str | Path | None = None,
    on_progress: Any = None,
) -> str:
    """
    Remove background via fal Bria RMBG. Returns local path to PNG result.
    Does not modify the source file.
    """
    from media_studio.fal.client import (
        download_url,
        extract_image_urls,
        subscribe,
        upload_file,
    )
    from media_studio.naming import unique_path
    from media_studio.config import ensure_output_dir, OUTPUT_DIR

    src = Path(image_path)
    if not src.is_file():
        raise FileNotFoundError(f"Still missing: {src}")

    def progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    progress("Uploading still for background remove…")
    url = upload_file(src, on_progress=progress)
    progress(f"Running {BG_REMOVE_LABEL}…")
    result = subscribe(
        BG_REMOVE_ENDPOINT,
        {"image_url": url},
        on_progress=progress,
    )
    urls = extract_image_urls(result) if isinstance(result, dict) else []
    if not urls:
        # Bria sometimes nests under image
        if isinstance(result, dict):
            img = result.get("image")
            if isinstance(img, dict) and img.get("url"):
                urls = [str(img["url"])]
            elif isinstance(img, str):
                urls = [img]
    if not urls:
        raise RuntimeError("Background remove returned no image.")

    out_root = ensure_output_dir(Path(output_dir) if output_dir else OUTPUT_DIR)
    dest_dir = out_root / "_character_bg"
    dest_dir.mkdir(parents=True, exist_ok=True)
    # unique_path(directory, stem, ext) — same as Studio / Library helpers
    dest = unique_path(dest_dir, f"{src.stem}_nobg", ".png")
    progress("Downloading cutout…")
    download_url(urls[0], dest, on_progress=progress)
    if not dest.is_file():
        raise RuntimeError("Background remove download failed.")
    return str(dest.resolve())


# ---------------------------------------------------------------------------
# Costume swap helpers
# ---------------------------------------------------------------------------


def costume_prompt_for_slot(outfit: str, slot: str) -> str:
    """Build multi-ref I2I prompt for one identity-pack angle (clean black plate)."""
    outfit = (outfit or "").strip()
    key = _norm_slot(slot) or "front"
    view = PROFILE_VIEW_PROMPTS.get(key) or SLOT_VIEW_HINT.get(
        key, "character reference still"
    )
    body = (
        f"{_FULL_BODY_INVENT_BODY} "
        if key in ("front", "side")
        else "Head unobstructed. "
    )
    return (
        "Keep the same person identity, face, hair, age, skin tone, and body "
        "proportions from the reference images. Do not change who they are. "
        "Preserve lighting direction on the subject from the references. "
        f"Change only the wardrobe / outfit / clothing to: {outfit}. "
        f"Generate a photoreal character-reference still: {view}. "
        f"{body}"
        + CLEAN_PLATE_BG
    )


def short_outfit_label(outfit: str, *, max_len: int = 28) -> str:
    """
    Short costume **name** suggestion from a long wardrobe prompt.
    e.g. "elegant red silk evening dress with …" → "Red Silk Evening Dress"
    """
    s = re.sub(r"\s+", " ", (outfit or "").strip())
    if not s:
        return "Outfit"
    # Drop filler lead-ins
    s = re.sub(
        r"^(a |an |the |wearing |wear |in a |in an |dressed in )+",
        "",
        s,
        flags=re.I,
    ).strip()
    words = [w for w in re.split(r"[^\w\-']+", s) if w]
    # Prefer first 2–4 content words
    take = words[:4] if len(words) > 1 else words[:1]
    name = " ".join(take).strip(" -_")
    if not name:
        name = "Outfit"
    # Title-case lightly (keep small words lower mid-phrase)
    parts = name.split()
    small = {"a", "an", "the", "and", "or", "with", "of", "in"}
    titled = []
    for i, w in enumerate(parts):
        if i > 0 and w.lower() in small:
            titled.append(w.lower())
        else:
            titled.append(w[:1].upper() + w[1:] if w else w)
    name = " ".join(titled)
    if len(name) > max_len:
        name = name[: max_len - 1].rstrip() + "…"
    return name


def estimate_costume_swap_cost(
    filled_slots: int,
    *,
    model_key: str = DEFAULT_COSTUME_MODEL,
    resolution: str | None = None,
) -> str:
    """Cost for N slot images (each is one I2I call), scaled by resolution when known."""
    from media_studio.fal.models import resolve_image_edit_model, default_image_edit_model
    from media_studio.pricing import format_job_cost

    n = max(0, int(filled_slots or 0))
    if n <= 0:
        return "Est. cost: —"
    spec = resolve_image_edit_model(model_key) or default_image_edit_model()
    amt = spec.estimate_cost(n, resolution=resolution)
    if amt is None:
        per = float(getattr(spec, "cost_per_image", 0.03) or 0.03)
        amt = round(per * n, 3)
    else:
        amt = round(float(amt), 3)
    unit = f"{n} image{'s' if n != 1 else ''}"
    if resolution and str(resolution).lower() not in ("", "auto", "default"):
        unit = f"{unit} · {resolution}"
    return format_job_cost(amt, unit=unit, model=spec.label)


# Concrete image_size presets for Flux-family edit when registry only has "auto"
_FLUX_IMAGE_SIZE_CHOICES: tuple[str, ...] = (
    "square_hd",  # ~2K-class preferred default
    "square",
    "landscape_16_9",
    "portrait_16_9",
    "landscape_4_3",
    "portrait_4_3",
)

# Friendly labels for dropdown display (value stays the API enum)
RESOLUTION_DISPLAY: dict[str, str] = {
    "0.5K": "0.5K",
    "1K": "1K",
    "2K": "2K",
    "4K": "4K",
    "auto": "Default (auto)",
    "auto_1K": "Auto 1K",
    "auto_2K": "Auto 2K",
    "auto_4K": "Auto 4K",
    "square_hd": "Square HD (~2K)",
    "square": "Square (~1K)",
    "landscape_16_9": "Landscape 16:9",
    "portrait_16_9": "Portrait 9:16",
    "landscape_4_3": "Landscape 4:3",
    "portrait_4_3": "Portrait 3:4",
    "1:1 square": "Square (~1K)",
    "1:1 square HD": "Square HD (~2K)",
}


def resolution_display_label(value: str) -> str:
    v = (value or "").strip()
    if not v:
        return "Default"
    return RESOLUTION_DISPLAY.get(v, RESOLUTION_DISPLAY.get(v.lower(), v))


def edit_resolution_options(model_label: str | None) -> list[str]:
    """
    Resolution / size choices the image-edit model actually accepts.

    Prefers concrete sizes over opaque ``auto`` when the model uses image_size.
    Empty list → hide control (true no-size models).
    """
    from media_studio.fal.models import resolve_image_edit_model, default_image_edit_model

    spec = resolve_image_edit_model(model_label) or default_image_edit_model()
    has_res = bool(getattr(spec, "resolution_param", None))
    has_size = bool(getattr(spec, "image_size_param", None))
    if not has_res and not has_size:
        return []
    allowed = list(getattr(spec, "allowed_resolutions", ()) or ())
    # Only opaque auto → expand to concrete presets for image_size models
    if has_size and (
        not allowed
        or all(str(a).lower() in ("auto", "default") for a in allowed)
    ):
        return list(_FLUX_IMAGE_SIZE_CHOICES)
    if not allowed:
        return []
    ladder = ("0.5K", "1K", "2K", "4K")
    max_r = getattr(spec, "max_resolution", None) or ""
    out: list[str] = []
    for r in allowed:
        rl = str(r)
        if rl.lower() in ("auto", "default") and has_size:
            # Skip bare auto when we can offer real sizes instead
            continue
        if rl in ladder and max_r in ladder:
            if ladder.index(rl) > ladder.index(max_r):
                continue
        out.append(rl)
    if not out and has_size:
        return list(_FLUX_IMAGE_SIZE_CHOICES)
    if not out and allowed:
        # Single opaque size — surface a clear label token
        only = str(allowed[0])
        if only.lower() in ("auto", "default"):
            return [f"Default ({only})"]
        return [only]
    return out


def default_practical_resolution(options: list[str]) -> str:
    """Prefer ~2K-class quality without defaulting to extreme 4K cost."""
    if not options:
        return "2K"
    prefs = (
        "2K",
        "auto_2K",
        "Auto 2K",
        "square_hd",
        "Square HD (~2K)",
        "1K",
        "square",
        "auto_1K",
    )
    lower_map = {o.lower(): o for o in options}
    for p in prefs:
        if p.lower() in lower_map:
            return lower_map[p.lower()]
    non4k = [o for o in options if "4k" not in o.lower()]
    return non4k[0] if non4k else options[0]


def t2i_resolution_options(model_label: str | None) -> list[str]:
    """
    T2I resolution options from vision model; Flux-style models without a
    resolution enum get concrete square sizes (not opaque auto).
    """
    from media_studio.vision_registry import find_vision_model

    spec = find_vision_model(model_label, "text_to_image") if model_label else None
    if spec and getattr(spec, "resolution_choices", None):
        opts = list(spec.resolution_choices)
        return opts if opts else ["1K", "2K"]
    # Flux / Recraft: image_size via aspect — concrete quality tiers
    return ["1:1 square", "1:1 square HD"]


def default_practical_t2i_resolution(options: list[str]) -> str:
    if not options:
        return "1:1 square HD"
    lower_map = {o.lower(): o for o in options}
    for p in ("2K", "1:1 square HD", "1:1 square hd", "1K", "1:1 square"):
        if p.lower() in lower_map:
            return lower_map[p.lower()]
    non4k = [o for o in options if "4k" not in o.lower()]
    return non4k[0] if non4k else options[0]


def edit_params_json_for_resolution(resolution: str | None) -> str | None:
    """parameters_json fragment for ``generate()`` image-edit path."""
    import json

    r = (resolution or "").strip()
    if not r or r.lower() in ("auto", "default"):
        # Still pass auto when selected
        if r.lower() == "auto":
            return json.dumps({"resolution": "auto", "image_size": "auto"})
        return None
    # Send both keys; build_edit_arguments picks what the model supports
    return json.dumps({"resolution": r, "image_size": r})


def preferred_costume_model() -> str:
    """Prefer multi-ref Flux-family edit models."""
    from media_studio.fal.models import IMAGE_EDIT_MODELS

    for key in (
        "flux 2 pro",
        "flux 2 max",
        "flux 2 flex",
        "nano banana pro",
        "seedream 5 pro",
    ):
        spec = IMAGE_EDIT_MODELS.get(key)
        if spec and getattr(spec, "multi_image", False) and int(
            getattr(spec, "max_ref_images", 1) or 1
        ) >= 2:
            return key
    return DEFAULT_COSTUME_MODEL


# ---------------------------------------------------------------------------
# Generate missing profile (Front / Side / Close-up)
# ---------------------------------------------------------------------------

PROFILE_VIEW_PROMPTS: dict[str, str] = {
    "front": (
        "Full-body head-to-toe front view, entire figure visible including feet, "
        "standing straight, neutral pose, arms relaxed at sides, facing the camera, "
        "subject centered, no crop at head or feet"
    ),
    "side": (
        "Full-body head-to-toe clear side profile view, entire figure visible including "
        "feet, standing straight, neutral pose, arms relaxed, clean silhouette, "
        "subject centered, no crop at head or feet"
    ),
    "closeup": (
        "Face close-up portrait, shoulders up, sharp facial features, "
        "match identity from the references, subject correctly framed"
    ),
}

# Extra full-body bias when inventing body from face-only refs
_FULL_BODY_INVENT_BODY = (
    "Match face and identity from the reference image(s) exactly. "
    "If the reference is only a close-up or partial body, invent a proportionate "
    "full body consistent with that face — do NOT crop to match the close-up framing. "
    "Bias toward new full-body framing over matching a close-up crop. "
    "If wardrobe is unclear in the refs, use simple fitted neutral clothes "
    "(tee and pants). Head unobstructed."
)


def profile_prompt_for_slot(slot: str, *, note: str = "") -> str:
    """
    Identity lock prompt for generating a missing pack angle from existing
    stills (multi-ref I2I). Front/Side force head-to-toe; Close-up is shoulders-up.
    Pure black clean plate for Motion Sync.
    """
    key = _norm_slot(slot) or "front"
    view = PROFILE_VIEW_PROMPTS.get(key) or SLOT_VIEW_HINT.get(
        key, "character reference still"
    )
    if key in ("front", "side"):
        base = (
            "Same person as the reference image(s). "
            f"Generate a photoreal character-reference still: {view}. "
            f"{_FULL_BODY_INVENT_BODY} "
            "Preserve skin tone, age, hair, and lighting direction from the refs. "
            "Do not invent a different person. "
            + CLEAN_PLATE_BG
        )
    else:
        base = (
            "Same person as the reference image(s). "
            f"Generate a photoreal character-reference still: {view}. "
            "Preserve face, proportions, hair, skin tone, age, and lighting "
            "direction from the reference stills. Do not invent a different person. "
            "Head unobstructed. "
            + CLEAN_PLATE_BG
        )
    n = (note or "").strip()
    if n:
        # Append only — never replace core framing instructions
        base += f" Optional user note (secondary): {n}"
    return base


def estimate_profile_cost(
    *,
    model_key: str | None = None,
    resolution: str | None = None,
) -> str:
    """Cost for one profile generate (single image)."""
    return estimate_costume_swap_cost(
        1,
        model_key=model_key or preferred_costume_model(),
        resolution=resolution,
    )


# ---------------------------------------------------------------------------
# New character · T2I builder helpers + sequential prompts
# ---------------------------------------------------------------------------

HELPER_NONE = "(None / skip)"

CHAR_GENDER_OPTS = (HELPER_NONE, "Male", "Female")
CHAR_AGE_OPTS = (HELPER_NONE, "20s", "30s", "40s", "50s", "60+")
CHAR_BUILD_OPTS = (HELPER_NONE, "slim", "average", "athletic", "heavy")
CHAR_HEIGHT_OPTS = (HELPER_NONE, "short", "average", "tall")
CHAR_HAIR_COLOR_OPTS = (
    HELPER_NONE,
    "black",
    "dark brown",
    "brown",
    "blonde",
    "red",
    "gray",
    "white",
)
CHAR_HAIR_LENGTH_OPTS = (HELPER_NONE, "bald", "short", "medium", "long")
CHAR_HAIR_STYLE_OPTS = (
    HELPER_NONE,
    "straight",
    "wavy",
    "curly",
    "coily",
    "pulled back",
    "bun",
)
CHAR_FACIAL_HAIR_OPTS = (
    HELPER_NONE,
    "none",
    "stubble",
    "short beard",
    "full beard",
    "mustache",
    "goatee",
)
CHAR_SKIN_OPTS = (
    HELPER_NONE,
    "light",
    "medium",
    "olive",
    "tan",
    "deep",
    "free text below",
)
DEFAULT_CLOTHES = "simple fitted neutral tee and pants (no costume flash)"

# Sequential identity-pack order for New Character T2I (Front first)
T2I_SEQ_ORDER: tuple[str, ...] = ("front", "side", "closeup")


def _helper_val(v: str | None) -> str | None:
    s = (v or "").strip()
    if not s or s == HELPER_NONE or s.lower().startswith("(none"):
        return None
    return s


def assemble_character_t2i_description(
    *,
    description: str = "",
    gender: str | None = None,
    age: str | None = None,
    build: str | None = None,
    height: str | None = None,
    hair_color: str | None = None,
    hair_length: str | None = None,
    hair_style: str | None = None,
    facial_hair: str | None = None,
    skin: str | None = None,
    skin_free: str | None = None,
    clothes: str | None = None,
) -> str:
    """Merge helpers + free description into a single character brief (pre-Enhance)."""
    parts: list[str] = []
    g = _helper_val(gender)
    a = _helper_val(age)
    if g and a:
        parts.append(f"{g.lower()} in their {a}")
    elif g:
        parts.append(g.lower())
    elif a:
        parts.append(f"adult in their {a}")
    for label, val in (
        ("build", build),
        ("height", height),
    ):
        v = _helper_val(val)
        if v:
            parts.append(f"{v} {label}" if label == "build" else f"{v} height")
    hc, hl, hs = _helper_val(hair_color), _helper_val(hair_length), _helper_val(hair_style)
    hair_bits = [x for x in (hc, hl, hs) if x]
    if hair_bits:
        parts.append("hair: " + ", ".join(hair_bits))
    fh = _helper_val(facial_hair)
    if fh and fh.lower() != "none":
        parts.append(f"facial hair: {fh}")
    sk = _helper_val(skin)
    if sk and sk.lower().startswith("free"):
        sk = None
    sk_free = (skin_free or "").strip()
    if sk_free:
        parts.append(f"skin/appearance: {sk_free}")
    elif sk:
        parts.append(f"skin tone: {sk}")
    cl = (clothes or "").strip() or DEFAULT_CLOTHES
    if cl.lower() not in ("none", "(none / skip)"):
        parts.append(f"wardrobe: {cl}")
    desc = (description or "").strip()
    head = ", ".join(parts)
    if head and desc:
        return f"{head}. {desc}"
    return desc or head or ""


def character_t2i_prompt_for_slot(
    slot: str,
    *,
    base_description: str,
    insights: str = "",
) -> str:
    """
    Full T2I prompt for first guided plate (Front by default) — pure black clean plate.
    """
    key = _norm_slot(slot) or "front"
    view = PROFILE_VIEW_PROMPTS.get(key) or SLOT_VIEW_HINT.get(key, "portrait")
    desc = (base_description or "").strip() or "photoreal adult person"
    ins = (insights or "").strip()
    bits = [
        f"Photoreal character reference still of: {desc}.",
        f"Framing: {view}.",
        "Single subject only, head unobstructed, natural expression.",
    ]
    if key in ("front", "side"):
        bits.append(
            "Entire figure visible head to toe including feet; no crop; subject centered."
        )
    bits.append(CLEAN_PLATE_BG)
    if ins:
        bits.append(f"Creative intent (soft): {ins}")
    return " ".join(bits)


def character_t2i_i2i_prompt_for_slot(
    slot: str,
    *,
    base_description: str = "",
    insights: str = "",
) -> str:
    """
    I2I multi-ref prompt for later sequential angles after the first plate.
    Uses stronger full-body language for Front/Side even if refs are close-ups.
    """
    base = profile_prompt_for_slot(slot)
    extra = (base_description or "").strip()
    if extra:
        base += f" Subject description guide: {extra}."
    ins = (insights or "").strip()
    if ins:
        base += f" Soft creative intent: {ins}."
    return base


def estimate_t2i_character_cost(
    *,
    t2i_label: str | None = None,
    n_remaining: int = 1,
    resolution: str | None = None,
) -> str:
    """Rough est. for remaining sequential plates (T2I first ~same as edit ballpark)."""
    from media_studio.pricing import format_job_cost
    from media_studio.vision_registry import find_vision_model

    n = max(1, int(n_remaining or 1))
    spec = find_vision_model(t2i_label, "text_to_image") if t2i_label else None
    per = float(getattr(spec, "cost_estimate_usd", 0) or 0.04) if spec else 0.04
    # Soft resolution mult when classic ladder is selected
    mult = 1.0
    ru = (resolution or "").strip().upper()
    if ru in ("2K", "AUTO_2K") or "square hd" in (resolution or "").lower():
        mult = 1.25
    elif ru in ("4K", "AUTO_4K"):
        mult = 2.0
    elif ru in ("0.5K",):
        mult = 0.75
    total = round(per * n * mult, 3)
    model = spec.label if spec else "T2I + multi-ref"
    unit = f"{n} image{'s' if n != 1 else ''}"
    if resolution and str(resolution).lower() not in ("", "auto", "default"):
        unit = f"{unit} · {resolution}"
    return format_job_cost(total, unit=unit, model=model)


def t2i_character_model_labels() -> list[str]:
    from media_studio.studio_modality import models_for_image_modality

    labs = models_for_image_modality("t2i")
    return labs or ["Flux 2 Pro (T2I)"]


def multi_ref_image_edit_labels() -> list[str]:
    """Dropdown labels for multi-ref image-edit models (profile / costume)."""
    from media_studio.fal.models import IMAGE_EDIT_MODELS, default_image_edit_model

    out: list[str] = []
    for key in (
        "flux 2 pro",
        "flux 2 max",
        "flux 2 flex",
        "nano banana pro",
        "nano banana 2",
        "seedream 5 pro",
    ):
        spec = IMAGE_EDIT_MODELS.get(key)
        if not spec:
            continue
        if getattr(spec, "multi_image", False) and int(
            getattr(spec, "max_ref_images", 1) or 1
        ) >= 2:
            if spec.label not in out:
                out.append(spec.label)
    # Fallback: any multi-ref edit model
    if not out:
        for spec in IMAGE_EDIT_MODELS.values():
            if getattr(spec, "multi_image", False) and int(
                getattr(spec, "max_ref_images", 1) or 1
            ) >= 2:
                out.append(spec.label)
    if not out:
        out.append(default_image_edit_model().label)
    return out
