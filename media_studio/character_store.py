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

MAX_STILLS_PER_CHARACTER = 3

# Default I2I prompt for Generate variation (face-lock style)
VARIATION_PROMPT = (
    "Keep the same person identity, face, hair, age, and body proportions. "
    "Create a subtle character-reference variation: alternate angle or slight pose "
    "change only. Photoreal, clean simple background, full-body or clear upper body, "
    "head fully visible and unobstructed."
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
    """Build multi-ref I2I prompt for one identity-pack angle."""
    outfit = (outfit or "").strip()
    key = _norm_slot(slot) or "front"
    view = SLOT_VIEW_HINT.get(key, "character reference still")
    return (
        "Keep the same person identity, face, hair, age, skin tone, and body "
        "proportions from the reference images. Do not change who they are. "
        f"Change only the wardrobe / outfit / clothing to: {outfit}. "
        f"Generate a photoreal character-reference still: {view}. "
        "Clean simple background, professional lighting, head unobstructed."
    )


def short_outfit_label(outfit: str, *, max_len: int = 28) -> str:
    s = re.sub(r"\s+", " ", (outfit or "").strip())
    if len(s) <= max_len:
        return s or "outfit"
    return s[: max_len - 1].rstrip() + "…"


def estimate_costume_swap_cost(
    filled_slots: int,
    *,
    model_key: str = DEFAULT_COSTUME_MODEL,
) -> str:
    """Cost for N slot images (each is one I2I call)."""
    from media_studio.fal.models import resolve_image_edit_model, default_image_edit_model
    from media_studio.pricing import format_job_cost

    n = max(0, int(filled_slots or 0))
    if n <= 0:
        return "Est. cost: —"
    spec = resolve_image_edit_model(model_key) or default_image_edit_model()
    per = float(getattr(spec, "cost_per_image", 0.03) or 0.03)
    total = round(per * n, 3)
    return format_job_cost(
        total,
        unit=f"{n} image{'s' if n != 1 else ''}",
        model=spec.label,
    )


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
