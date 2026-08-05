"""
Local Scenes store — reusable location / establishing stills.

Saved under data/scenes.json; stills in data/scene_stills/. No cloud.
Parallel to Characters (who) — Scenes are where (Director scene refs, etc.).
"""

from __future__ import annotations

import json
import re
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from media_studio.config import PROJECT_ROOT
from media_studio.helper_none import HELPER_NONE, active_helper, is_helper_none, with_none

DATA_DIR = PROJECT_ROOT / "data"
SCENES_FILE = DATA_DIR / "scenes.json"
STILLS_DIR = DATA_DIR / "scene_stills"

# Establishing-plate bias for T2I (no hero talent unless the user asks)
SCENE_T2I_BIAS = (
    "Photoreal establishing / location plate. "
    "Environment and architecture primary — empty or lightly populated space only. "
    "No hero talent, no portrait subject, no close-up of a person unless the "
    "description explicitly requests people. Clean, usable as a Director scene "
    "reference still. Natural light, sharp detail, no text, no logo, no watermark."
)

# ----- Plate builder helpers (Scenes T2I) — None = skip that dimension -----
PLATE_SETTINGS: list[str] = with_none(["Interior", "Exterior", "Mixed"])
PLATE_TYPES: list[str] = with_none(
    [
        "Living room",
        "Kitchen",
        "Bedroom",
        "Gym",
        "Office",
        "Street",
        "Park",
        "Sidewalk",
        "Driveway",
        "Empty lot",
        "Custom",
    ]
)
PLATE_TIMES: list[str] = with_none(
    ["Golden hour", "Midday", "Blue hour", "Night", "Overcast"]
)
PLATE_WEATHER: list[str] = with_none(
    ["Clear", "Overcast", "Rain", "Snow", "Fog"]
)
# Default bias is empty when skipped; explicit Empty / Lightly populated available
PLATE_ACTIVITY: list[str] = with_none(["Empty", "Lightly populated"])

# Variation transform quick chips (append to I2I transform prompt)
VARIATION_CHIPS: tuple[str, ...] = (
    "Winter",
    "Night",
    "Rain",
    "Golden hour",
    "Overcast",
)

_PLATE_TYPE_LANG: dict[str, str] = {
    "Living room": "a living room interior",
    "Kitchen": "a kitchen interior",
    "Bedroom": "a bedroom interior",
    "Gym": "a modern gym / fitness interior",
    "Office": "an office / workspace interior",
    "Street": "an urban street establishing view",
    "Park": "a public park establishing view",
    "Sidewalk": "a city sidewalk establishing view",
    "Driveway": "a residential driveway and facade establishing view",
    "Empty lot": "an empty lot / undeveloped parcel establishing view",
    "Custom": "a location establishing plate",
}

_PLATE_TIME_LANG: dict[str, str] = {
    "Golden hour": "golden hour warm low sun, long soft shadows",
    "Midday": "midday clear light, bright even daylight",
    "Blue hour": "blue hour twilight, cool ambient sky light",
    "Night": "nighttime, practical lights and soft ambient night illumination",
    "Overcast": "overcast soft diffused daylight, flat even light",
}

_PLATE_WEATHER_LANG: dict[str, str] = {
    "Clear": "clear weather, crisp air",
    "Overcast": "overcast cloudy sky",
    "Rain": "wet surfaces from rain, rainy atmosphere",
    "Snow": "snow-covered ground and surfaces, winter air",
    "Fog": "light fog / mist, soft distance falloff",
}


def assemble_plate_description(
    *,
    setting: str | None = None,
    place_type: str | None = None,
    time_of_day: str | None = None,
    weather: str | None = None,
    activity: str | None = None,
    notes: str | None = None,
) -> str:
    """
    Rebuild location description from plate helpers (Studio/music builder pattern).

    Skipped helpers (None) omit that dimension. Always keeps establishing bias:
    empty or light activity, no hero talent, unless notes ask for people.
    """
    set_v = active_helper(setting)
    type_v = active_helper(place_type)
    time_v = active_helper(time_of_day)
    weather_v = active_helper(weather)
    act_v = active_helper(activity)
    note = (notes or "").strip()

    bits: list[str] = []

    # Core place
    if type_v and type_v != "Custom":
        place = _PLATE_TYPE_LANG.get(type_v, f"a {type_v.lower()} location")
        bits.append(place)
    elif type_v == "Custom" and note:
        bits.append("a custom location establishing plate")
    elif set_v:
        bits.append(
            {
                "Interior": "an interior establishing plate",
                "Exterior": "an exterior establishing plate",
                "Mixed": "an interior/exterior establishing plate",
            }.get(set_v, "a location establishing plate")
        )

    if set_v:
        bits.append(f"{set_v.lower()} setting")

    if time_v:
        bits.append(_PLATE_TIME_LANG.get(time_v, time_v.lower()))

    # Weather: prefer exterior / mixed; still allow if user set it alone
    if weather_v:
        if not set_v or set_v in ("Exterior", "Mixed") or weather_v:
            bits.append(_PLATE_WEATHER_LANG.get(weather_v, weather_v.lower()))

    # Activity — default empty bias when helpers are used but activity skipped
    if act_v == "Empty":
        bits.append("empty space, no people visible")
    elif act_v == "Lightly populated":
        bits.append("lightly populated only, no hero talent or portrait subject")
    elif any((set_v, type_v, time_v, weather_v)):
        bits.append("empty or lightly populated, no hero talent")

    if note:
        bits.append(note.rstrip("."))

    if not bits:
        return ""

    # Readable sentence
    text = ", ".join(bits)
    if not text.endswith("."):
        text += "."
    # Capitalize first letter
    return text[0].upper() + text[1:] if text else ""

# Canonical aspect tokens stored on SavedScene.aspect
SCENE_ASPECT_CORE: tuple[str, ...] = ("16:9", "9:16", "1:1", "4:3", "3:4")

# UI labels (Horizontal / Vertical helpers)
SCENE_ASPECT_UI: tuple[tuple[str, str], ...] = (
    ("16:9", "16:9 · Horizontal"),
    ("9:16", "9:16 · Vertical"),
    ("1:1", "1:1 · Square"),
    ("4:3", "4:3 · Horizontal"),
    ("3:4", "3:4 · Vertical"),
)

SCENE_FRAMING_HINT: dict[str, str] = {
    "16:9": "Wide horizontal establishing shot, cinematic landscape framing.",
    "9:16": "Tall vertical establishing shot, full-height location plate for phone/story.",
    "1:1": "Square establishing plate, balanced location composition.",
    "4:3": "Classic horizontal establishing shot (4:3).",
    "3:4": "Tall classic establishing plate (3:4).",
}


# Multi-angle pack (parallel to character Front / Side / Close-up)
# still_path = Hero / wide (required). Angle B/C are optional extra views.
SCENE_ANGLE_SLOTS: tuple[str, ...] = ("hero", "angle_b", "angle_c")
SCENE_ANGLE_LABELS: dict[str, str] = {
    "hero": "Hero (wide)",
    "angle_b": "Left (B)",
    "angle_c": "Right (C)",
}
# One-click generate targets → fill angle_b or angle_c
SCENE_ANGLE_TARGETS: dict[str, str] = {
    "left": "angle_b",
    "right": "angle_c",
    "reverse": "angle_b",  # reverse prefers B; if B filled, UI can send to C
}
SCENE_ANGLE_TARGET_LABELS: dict[str, str] = {
    "left": "Generate Left",
    "right": "Generate Right",
    "reverse": "Generate Reverse",
}


@dataclass
class SavedScene:
    id: str
    name: str
    still_path: str
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""
    locked: bool = False
    # Canonical aspect e.g. "16:9" (from generate or detected from still)
    aspect: str = ""
    # Variation child: points at base scene id (None = top-level base)
    parent_id: str | None = None
    # Optional multi-angle pack (each variation keeps its own)
    angle_b_path: str = ""
    angle_c_path: str = ""

    def display_notes(self) -> str:
        """Secondary list line — short notes only, never a full T2I dump."""
        n = (self.notes or "").strip()
        if not n:
            return ""
        low = n.lower()
        looks_like_prompt = len(n) > 80 and any(
            tok in low
            for tok in (
                "photoreal",
                "establishing",
                "location plate",
                "empty or lightly",
                "no hero",
                "creative intent",
                "no text",
                "no logo",
                "watermark",
            )
        )
        if looks_like_prompt:
            # First clause only
            first = re.split(r"[.!\n]", n, maxsplit=1)[0].strip()
            if len(first) > 72:
                first = first[:69].rstrip() + "…"
            return first or n[:72].rstrip() + "…"
        if len(n) > 120:
            return n[:117].rstrip() + "…"
        return n

    def display_name(self) -> str:
        """
        User-facing list title. Prefer short Name; if Name was polluted by a long
        generate prompt, show a truncated title (never put the full prompt first).
        """
        n = (self.name or "").strip() or "Untitled scene"
        low = n.lower()
        looks_like_prompt = len(n) > 40 and any(
            tok in low
            for tok in (
                "photoreal",
                "establishing",
                "location plate",
                "empty or lightly",
                "no hero",
                "creative intent",
                "natural light",
                "no text",
                "no logo",
            )
        )
        if looks_like_prompt:
            # Prefer first short phrase before comma/period
            first = re.split(r"[,.\n]", n, maxsplit=1)[0].strip()
            if 3 <= len(first) <= 48:
                return first
            return n[:40].rstrip(" .,;:-") + "…"
        if len(n) > 56:
            return n[:53].rstrip() + "…"
        return n

    def has_still(self) -> bool:
        p = self.resolved_still_path()
        return bool(p)

    def resolved_still_path(self) -> str | None:
        """Hero / wide still path (required)."""
        return self._resolve_path(self.still_path)

    def _resolve_path(self, raw: str | None) -> str | None:
        """Return a readable still path, repairing basename under scene_stills/."""
        s = (raw or "").strip()
        if not s:
            return None
        try:
            p = Path(s)
            if p.is_file():
                return str(p.resolve())
        except OSError:
            pass
        try:
            cand = STILLS_DIR / Path(s).name
            if cand.is_file():
                return str(cand.resolve())
        except OSError:
            pass
        return None

    def resolved_angle_path(self, slot: str) -> str | None:
        """hero | angle_b | angle_c → absolute path or None."""
        key = (slot or "hero").strip().lower()
        if key in ("hero", "wide", "main", "primary"):
            return self.resolved_still_path()
        if key in ("angle_b", "b", "left"):
            return self._resolve_path(self.angle_b_path)
        if key in ("angle_c", "c", "right"):
            return self._resolve_path(self.angle_c_path)
        return None

    def angle_pack(self) -> dict[str, str]:
        """Slot → path for all filled angles (hero required for pack)."""
        out: dict[str, str] = {}
        h = self.resolved_still_path()
        if h:
            out["hero"] = h
        b = self.resolved_angle_path("angle_b")
        if b:
            out["angle_b"] = b
        c = self.resolved_angle_path("angle_c")
        if c:
            out["angle_c"] = c
        return out

    def angle_extra_paths(self) -> list[str]:
        """Non-hero angles for multi-ref Director binding (order B, C)."""
        out: list[str] = []
        for slot in ("angle_b", "angle_c"):
            p = self.resolved_angle_path(slot)
            if p:
                out.append(p)
        return out

    def has_angle_pack(self) -> bool:
        return bool(self.angle_extra_paths())

    def is_variation(self) -> bool:
        return bool((self.parent_id or "").strip())

    def is_base(self) -> bool:
        return not self.is_variation()

    def aspect_badge(self) -> str:
        """Short badge for list thumbs (e.g. 16:9)."""
        a = normalize_scene_aspect(self.aspect)
        if a:
            return a
        det = detect_still_aspect(self.resolved_still_path() or self.still_path)
        return det or ""


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _slug_name(name: str) -> str:
    s = re.sub(r"[^\w\s-]", "", (name or "").strip().lower())
    s = re.sub(r"[-\s]+", "-", s).strip("-")
    return (s or "scene")[:48]


def _ensure_store() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    STILLS_DIR.mkdir(parents=True, exist_ok=True)
    if not SCENES_FILE.is_file():
        SCENES_FILE.write_text(
            json.dumps({"scenes": []}, indent=2) + "\n",
            encoding="utf-8",
        )


def normalize_scene_aspect(raw: str | None) -> str:
    """Map free-form / UI labels → canonical 16:9 | 9:16 | 1:1 | 4:3 | 3:4."""
    s = (raw or "").strip()
    if not s:
        return ""
    bare = s.lower().replace(" ", "").replace("·", "").replace("•", "")
    # Prefer longer ratio tokens first
    for tok in ("9:16", "16:9", "3:4", "4:3", "1:1"):
        if tok in bare:
            return tok
    if "vertical" in bare or "portrait" in bare or "tall" in bare:
        return "9:16"
    if "horizontal" in bare or "landscape" in bare or "wide" in bare:
        return "16:9"
    if "square" in bare:
        return "1:1"
    return ""


def detect_still_aspect(path: str | Path | None) -> str:
    """Infer nearest canonical aspect from image dimensions."""
    if not path:
        return ""
    try:
        p = Path(path)
        if not p.is_file():
            return ""
        from PIL import Image

        with Image.open(p) as im:
            w, h = im.size
        if w <= 0 or h <= 0:
            return ""
        r = float(w) / float(h)
        targets = {
            "16:9": 16 / 9,
            "9:16": 9 / 16,
            "1:1": 1.0,
            "4:3": 4 / 3,
            "3:4": 3 / 4,
        }
        best = min(targets.items(), key=lambda kv: abs(kv[1] - r))
        # Only accept if reasonably close
        if abs(best[1] - r) / best[1] > 0.18:
            # Fall back to orientation
            if r > 1.15:
                return "16:9"
            if r < 0.87:
                return "9:16"
            return "1:1"
        return best[0]
    except Exception:
        return ""


def _from_dict(item: dict[str, Any]) -> SavedScene | None:
    name = str(item.get("name") or "").strip()
    still = str(item.get("still_path") or "").strip()
    if not name:
        return None
    aspect = normalize_scene_aspect(str(item.get("aspect") or ""))
    if not aspect and still:
        aspect = detect_still_aspect(still)
    parent_raw = item.get("parent_id")
    parent_id = str(parent_raw).strip() if parent_raw else None
    if parent_id == "":
        parent_id = None
    return SavedScene(
        id=str(item.get("id") or uuid.uuid4().hex[:12]),
        name=name,
        still_path=still,
        notes=str(item.get("notes") or ""),
        created_at=str(item.get("created_at") or _now_iso()),
        updated_at=str(item.get("updated_at") or item.get("created_at") or ""),
        locked=bool(item.get("locked") or False),
        aspect=aspect,
        parent_id=parent_id,
        angle_b_path=str(item.get("angle_b_path") or "").strip(),
        angle_c_path=str(item.get("angle_c_path") or "").strip(),
    )


def _to_dict(s: SavedScene) -> dict[str, Any]:
    d: dict[str, Any] = {
        "id": s.id,
        "name": s.name,
        "still_path": s.still_path,
        "notes": s.notes or "",
        "created_at": s.created_at,
        "updated_at": s.updated_at,
        "locked": bool(s.locked),
        "aspect": normalize_scene_aspect(s.aspect) or s.aspect or "",
        "parent_id": s.parent_id or None,
    }
    if (s.angle_b_path or "").strip():
        d["angle_b_path"] = s.angle_b_path
    if (s.angle_c_path or "").strip():
        d["angle_c_path"] = s.angle_c_path
    return d


def load_scenes() -> list[SavedScene]:
    _ensure_store()
    try:
        data = json.loads(SCENES_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    raw = data.get("scenes") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return []
    out: list[SavedScene] = []
    repaired = False
    for item in raw:
        if not isinstance(item, dict):
            continue
        entry = _from_dict(item)
        if not entry:
            continue
        # Repair broken absolute paths → local scene_stills basename
        fixed = entry.resolved_still_path()
        if fixed and fixed != (entry.still_path or ""):
            entry.still_path = fixed
            repaired = True
        fb = entry.resolved_angle_path("angle_b")
        if fb and fb != (entry.angle_b_path or ""):
            entry.angle_b_path = fb
            repaired = True
        fc = entry.resolved_angle_path("angle_c")
        if fc and fc != (entry.angle_c_path or ""):
            entry.angle_c_path = fc
            repaired = True
        out.append(entry)
    if repaired:
        try:
            save_scenes(out)
        except Exception:
            pass
    return out


def save_scenes(scenes: list[SavedScene]) -> None:
    _ensure_store()
    payload: dict[str, Any] = {"scenes": [_to_dict(s) for s in scenes]}
    SCENES_FILE.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def find_scene(id_or_name: str | None) -> SavedScene | None:
    if not id_or_name:
        return None
    key = id_or_name.strip()
    for s in load_scenes():
        if s.id == key or s.name.lower() == key.lower():
            return s
    return None


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


def _copy_still(src: Path, *, scene_id: str, name: str) -> Path:
    _ensure_store()
    if not src.is_file():
        raise FileNotFoundError(f"Still missing: {src}")
    ext = src.suffix.lower() or ".jpg"
    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".bmp"):
        ext = ".jpg"
    dest = STILLS_DIR / f"{_slug_name(name)}_{scene_id}{ext}"
    if dest.is_file():
        try:
            if src.resolve() == dest.resolve():
                return dest
        except OSError:
            pass
        dest = STILLS_DIR / (
            f"{_slug_name(name)}_{scene_id}_{uuid.uuid4().hex[:6]}{ext}"
        )
    shutil.copy2(str(src), str(dest))
    return dest.resolve()


def _store_path(src: Path, *, scene_id: str, name: str) -> str:
    if _owned_still(src):
        return str(src.resolve())
    return str(_copy_still(src, scene_id=scene_id, name=name))


def add_scene(
    *,
    name: str,
    still_path: str | Path,
    notes: str = "",
    locked: bool = False,
    aspect: str | None = None,
    parent_id: str | None = None,
) -> SavedScene:
    name = (name or "").strip()
    if not name:
        raise ValueError("Name is required.")
    src = Path(still_path)
    if not src.is_file():
        raise FileNotFoundError(f"Still missing: {src}")
    scene_id = uuid.uuid4().hex[:12]
    stored = _store_path(src, scene_id=scene_id, name=name)
    now = _now_iso()
    ar = normalize_scene_aspect(aspect) or detect_still_aspect(stored)
    pid = (parent_id or "").strip() or None
    if pid:
        parent = find_scene(pid)
        if parent is None:
            raise ValueError("Parent scene not found.")
        if parent.is_variation():
            raise ValueError("Cannot nest a variation under another variation.")
        # Inherit aspect from parent when not set
        if not ar:
            ar = parent.aspect or detect_still_aspect(parent.still_path)
    entry = SavedScene(
        id=scene_id,
        name=name,
        still_path=stored,
        notes=(notes or "").strip(),
        created_at=now,
        updated_at=now,
        locked=bool(locked),
        aspect=ar,
        parent_id=pid,
        angle_b_path="",
        angle_c_path="",
    )
    scenes = load_scenes()
    scenes.append(entry)
    save_scenes(scenes)
    return entry


def list_base_scenes() -> list[SavedScene]:
    return [s for s in load_scenes() if s.is_base()]


def list_scene_variations(parent_id: str | None) -> list[SavedScene]:
    if not parent_id:
        return []
    pid = parent_id.strip()
    return [s for s in load_scenes() if (s.parent_id or "") == pid]


def update_scene(
    scene_id: str,
    *,
    name: str | None = None,
    notes: str | None = None,
    still_path: str | Path | None = None,
    locked: bool | None = None,
    aspect: str | None = None,
) -> SavedScene | None:
    scenes = load_scenes()
    found: SavedScene | None = None
    idx = -1
    for i, s in enumerate(scenes):
        if s.id == scene_id:
            found = s
            idx = i
            break
    if found is None or idx < 0:
        return None

    new_name = (name if name is not None else found.name).strip()
    if not new_name:
        raise ValueError("Name is required.")
    new_notes = notes if notes is not None else found.notes
    new_still = found.still_path
    old_still = found.still_path

    if still_path is not None:
        src = Path(still_path)
        if not src.is_file():
            raise FileNotFoundError(f"Still missing: {src}")
        new_still = _store_path(src, scene_id=found.id, name=new_name)

    new_locked = found.locked if locked is None else bool(locked)
    if aspect is not None:
        new_aspect = normalize_scene_aspect(aspect) or detect_still_aspect(new_still)
    elif still_path is not None:
        new_aspect = detect_still_aspect(new_still) or found.aspect
    else:
        new_aspect = found.aspect or detect_still_aspect(new_still)
    updated = SavedScene(
        id=found.id,
        name=new_name,
        still_path=new_still,
        notes=(new_notes or "").strip(),
        created_at=found.created_at,
        updated_at=_now_iso(),
        locked=bool(new_locked),
        aspect=new_aspect or "",
        parent_id=found.parent_id,
        angle_b_path=found.angle_b_path,
        angle_c_path=found.angle_c_path,
    )
    scenes[idx] = updated
    save_scenes(scenes)
    # Drop previous owned still if replaced
    if still_path is not None and old_still and old_still != new_still:
        _delete_owned(old_still)
    return updated


def set_scene_angle(
    scene_id: str,
    slot: str,
    still_path: str | Path | None,
) -> SavedScene | None:
    """
    Set or clear Angle B / Angle C. Does not overwrite hero (still_path).

    ``slot``: angle_b | angle_c (or left→b, right→c).
    ``still_path`` None clears the slot.
    """
    key = (slot or "").strip().lower()
    if key in ("left", "b", "angle_b"):
        key = "angle_b"
    elif key in ("right", "c", "angle_c"):
        key = "angle_c"
    elif key in ("reverse", "180"):
        # Prefer empty B, else C (caller usually picks explicitly)
        key = "angle_b"
    if key not in ("angle_b", "angle_c"):
        raise ValueError(f"Invalid angle slot: {slot!r} (use angle_b or angle_c)")

    scenes = load_scenes()
    found: SavedScene | None = None
    idx = -1
    for i, s in enumerate(scenes):
        if s.id == scene_id:
            found = s
            idx = i
            break
    if found is None or idx < 0:
        return None

    # Reverse helper: if B filled and slot was reverse, fill C instead
    if (slot or "").strip().lower() in ("reverse", "180"):
        if found.resolved_angle_path("angle_b") and not found.resolved_angle_path(
            "angle_c"
        ):
            key = "angle_c"
        else:
            key = "angle_b"

    old = found.angle_b_path if key == "angle_b" else found.angle_c_path
    new_path = ""
    if still_path is not None:
        src = Path(still_path)
        if not src.is_file():
            raise FileNotFoundError(f"Still missing: {src}")
        new_path = _store_path(
            src, scene_id=found.id, name=f"{found.name}-{key.replace('_', '-')}"
        )

    ab = found.angle_b_path
    ac = found.angle_c_path
    if key == "angle_b":
        ab = new_path
    else:
        ac = new_path

    updated = SavedScene(
        id=found.id,
        name=found.name,
        still_path=found.still_path,
        notes=found.notes,
        created_at=found.created_at,
        updated_at=_now_iso(),
        locked=found.locked,
        aspect=found.aspect,
        parent_id=found.parent_id,
        angle_b_path=ab or "",
        angle_c_path=ac or "",
    )
    scenes[idx] = updated
    save_scenes(scenes)
    if old and old != new_path:
        _delete_owned(old)
    return updated


def scene_angle_prompt(
    target: str,
    *,
    base_name: str = "",
    notes: str = "",
) -> str:
    """
    I2I prompt: same place/lighting, **clearly different camera position**.

    Left/Right force a lateral move of several meters and a different composition
    (not a crop of the reference). Reverse uses 180° opposite direction.
    """
    t = (target or "left").strip().lower()
    if t in ("left", "l", "angle_b_left"):
        cam = (
            "Same location as the reference still, but the camera has moved several "
            "meters to the LEFT of the original viewpoint. Look back into the space "
            "from the left side — show the left side of the room, path, street, or "
            "landscape that was only partly visible (or off-frame) in the reference. "
            "Different framing and composition than the reference: new foreground "
            "elements on the left, shifted perspective lines, not a slight pan or crop "
            "of the same plate. Same lighting, time of day, weather, architecture, and "
            "materials. Establishing / wide view."
        )
    elif t in ("right", "r", "angle_c_right"):
        cam = (
            "Same location as the reference still, but the camera has moved several "
            "meters to the RIGHT of the original viewpoint. Look back into the space "
            "from the right side — show the right side of the room, path, street, or "
            "landscape that was only partly visible (or off-frame) in the reference. "
            "Different framing and composition than the reference: new foreground "
            "elements on the right, shifted perspective lines, not a slight pan or crop "
            "of the same plate. Same lighting, time of day, weather, architecture, and "
            "materials. Establishing / wide view."
        )
    elif t in ("reverse", "180", "opposite"):
        cam = (
            "Turn the camera 180 degrees for a reverse establishing view looking "
            "back through the same location from the opposite direction — clearly "
            "opposite facing, not a small turn. Same lighting, time of day, and architecture."
        )
    else:
        cam = (
            f"Move the camera for a clearly different establishing angle ({t}) of the "
            "same location — not a crop of the reference"
        )

    bits = [
        "Image-to-image edit of this establishing / location plate only.",
        "CRITICAL: change the camera viewpoint substantially. Do NOT return a near-duplicate "
        "or slight crop of the reference — the result must read as a different camera position.",
        cam,
        "Preserve identity of the place: same architecture, layout, season, time of day, "
        "and lighting continuity with the reference.",
        "Empty or lightly populated — no new hero talent or portrait subject.",
        "Photoreal, no text, no logo, no watermark.",
    ]
    if base_name:
        bits.append(f"Location name: {base_name}.")
    note = (notes or "").strip()
    if note:
        bits.append(f"User note (soft): {note}")
    return " ".join(bits)


def preferred_scene_still_bundle(
    scene_id: str | None = None,
    *,
    still_path: str | None = None,
) -> dict[str, Any]:
    """
    Resolve hero still + optional angle extras for Director binding.

    Returns: path (hero), label, id, extras [angle_b, angle_c], has_pack.
    """
    out: dict[str, Any] = {
        "path": None,
        "label": None,
        "id": scene_id,
        "extras": [],
        "has_pack": False,
    }
    s: SavedScene | None = None
    if scene_id:
        s = find_scene(scene_id)
    if s is None and still_path:
        # Match by resolved path
        try:
            want = str(Path(still_path).resolve())
        except OSError:
            want = (still_path or "").strip()
        for cand in load_scenes():
            hp = cand.resolved_still_path()
            if hp and hp == want:
                s = cand
                break
    if s is None:
        if still_path and Path(still_path).is_file():
            out["path"] = str(Path(still_path).resolve())
        return out
    hero = s.resolved_still_path()
    out["path"] = hero
    out["label"] = s.display_name()
    out["id"] = s.id
    extras = s.angle_extra_paths()
    out["extras"] = extras
    out["has_pack"] = bool(extras)
    return out


def set_scene_locked(scene_id: str, locked: bool) -> SavedScene | None:
    scenes = load_scenes()
    for i, s in enumerate(scenes):
        if s.id != scene_id:
            continue
        scenes[i] = SavedScene(
            id=s.id,
            name=s.name,
            still_path=s.still_path,
            notes=s.notes,
            created_at=s.created_at,
            updated_at=_now_iso(),
            locked=bool(locked),
            aspect=s.aspect,
            parent_id=s.parent_id,
            angle_b_path=s.angle_b_path,
            angle_c_path=s.angle_c_path,
        )
        save_scenes(scenes)
        return scenes[i]
    return None


class SceneHasChildrenError(ValueError):
    """Raised when deleting a base scene that still has variations."""

    def __init__(self, scene_id: str, children: list[SavedScene]) -> None:
        self.scene_id = scene_id
        self.children = children
        super().__init__(
            f"Scene has {len(children)} variation(s). "
            "Delete variations first, or confirm delete with children."
        )


def delete_scene(
    scene_id: str,
    *,
    force: bool = False,
    delete_children: bool = False,
    force_children_check: bool = True,
) -> bool:
    """
    Delete a scene. Base scenes with variations raise ``SceneHasChildrenError``
    unless ``delete_children=True``. Locked scenes require ``force=True``.
    """
    if not scene_id:
        return False
    scenes = load_scenes()
    removed: SavedScene | None = None
    for s in scenes:
        if s.id == scene_id:
            removed = s
            break
    if removed is None:
        return False
    if removed.locked and not force:
        raise ValueError(
            f"“{removed.name}” is locked — unlock before delete, or force."
        )

    kids = [s for s in scenes if (s.parent_id or "") == scene_id]
    if kids and force_children_check and not delete_children:
        raise SceneHasChildrenError(scene_id, kids)

    remove_ids = {scene_id}
    if delete_children:
        remove_ids |= {k.id for k in kids}

    keep: list[SavedScene] = []
    to_wipe: list[SavedScene] = []
    for s in scenes:
        if s.id in remove_ids:
            if s.locked and not force and s.id != scene_id:
                # Skip locked children unless force
                keep.append(s)
                continue
            to_wipe.append(s)
        else:
            keep.append(s)
    save_scenes(keep)
    keep_paths: set[str] = set()
    for s in keep:
        for raw in (s.still_path, s.angle_b_path, s.angle_c_path):
            try:
                if raw:
                    keep_paths.add(str(Path(raw).resolve()))
            except OSError:
                pass
    for s in to_wipe:
        for raw in (s.still_path, s.angle_b_path, s.angle_c_path):
            try:
                p = str(Path(raw).resolve()) if raw else ""
                if p and p not in keep_paths:
                    _delete_owned(raw)
            except OSError:
                _delete_owned(raw)
    return True


def scene_variation_prompt(
    transform: str,
    *,
    base_name: str = "",
    insights: str = "",
) -> str:
    """I2I prompt for transforming a base location plate into a variation."""
    t = (transform or "").strip() or "subtle seasonal or time-of-day change"
    ins = (insights or "").strip()
    bits = [
        "Edit this establishing / location plate only.",
        "Keep the same place, camera angle, layout, and architecture identity.",
        f"Transform: {t}.",
        "Empty or lightly populated — no new hero talent unless the transform asks for people.",
        "Photoreal, natural light consistent with the new condition, no text, no logo.",
    ]
    if base_name:
        bits.append(f"Base location: {base_name}.")
    if ins:
        bits.append(f"Creative intent (soft): {ins}")
    return " ".join(bits)


def preferred_scene_edit_model() -> str:
    try:
        from media_studio.character_store import preferred_costume_model

        return preferred_costume_model()
    except Exception:
        return "flux 2 pro"


def scene_edit_model_labels() -> list[str]:
    try:
        from media_studio.character_store import multi_ref_image_edit_labels

        labs = multi_ref_image_edit_labels()
        if labs:
            return labs
    except Exception:
        pass
    from media_studio.studio_modality import models_for_image_modality

    return models_for_image_modality("i2i") or ["Flux 2 Pro"]


def scene_t2i_prompt(
    description: str,
    *,
    insights: str = "",
    aspect: str | None = None,
) -> str:
    """Full T2I prompt for a location plate (establishing bias + framing)."""
    desc = (description or "").strip() or "empty interior or street establishing plate"
    ins = (insights or "").strip()
    ar = normalize_scene_aspect(aspect) or "16:9"
    frame = SCENE_FRAMING_HINT.get(ar) or SCENE_FRAMING_HINT["16:9"]
    bits = [SCENE_T2I_BIAS, frame, f"Location: {desc}."]
    if ins:
        bits.append(f"Creative intent (soft): {ins}")
    return " ".join(bits)


def estimate_scene_t2i_cost(
    *,
    t2i_label: str | None = None,
    quality: str | None = None,
    aspect: str | None = None,
) -> str:
    from media_studio.pricing import format_job_cost
    from media_studio.vision_registry import find_vision_model

    spec = find_vision_model(t2i_label, "text_to_image") if t2i_label else None
    per = float(getattr(spec, "cost_estimate_usd", 0) or 0.04) if spec else 0.04
    mult = 1.0
    q = (quality or "").strip().upper()
    if q in ("2K", "AUTO_2K", "HD") or "2K" in q:
        mult = 1.25
    elif q in ("4K", "AUTO_4K") or "4K" in q:
        mult = 2.0
    elif q in ("0.5K",):
        mult = 0.75
    total = round(per * mult, 3)
    model = spec.label if spec else "T2I"
    unit_bits = ["1 image"]
    ar = normalize_scene_aspect(aspect)
    if ar:
        unit_bits.append(ar)
    if quality and str(quality).lower() not in ("", "auto", "default", "standard"):
        unit_bits.append(str(quality))
    return format_job_cost(total, unit=" · ".join(unit_bits), model=model)


def t2i_scene_model_labels() -> list[str]:
    from media_studio.studio_modality import models_for_image_modality

    return models_for_image_modality("t2i") or ["Flux 2 Pro (T2I)"]


def scene_aspect_ui_options(model_label: str | None = None) -> list[str]:
    """
    Aspect dropdown labels for Scenes generate.
    Always offers 16:9 / 9:16 / 1:1; adds 4:3 / 3:4 when the model lists them.
    """
    from media_studio.vision_registry import find_vision_model

    core = ["16:9 · Horizontal", "9:16 · Vertical", "1:1 · Square"]
    spec = find_vision_model(model_label, "text_to_image") if model_label else None
    joined = " ".join(getattr(spec, "aspect_choices", ()) or ()).lower()
    # Most T2I models accept 4:3 family via image_size or colon enums
    if "4:3" in joined or "3:4" in joined or not joined:
        core.extend(["4:3 · Horizontal", "3:4 · Vertical"])
    return core


def scene_quality_options(model_label: str | None = None) -> list[str]:
    """
    Quality / resolution only — never mixes aspect into the label.
    Nano/Seedream: 1K · 2K · 4K. Flux-style: Standard · HD.
    """
    from media_studio.vision_registry import find_vision_model

    spec = find_vision_model(model_label, "text_to_image") if model_label else None
    if spec and getattr(spec, "resolution_choices", None):
        opts = [str(x) for x in spec.resolution_choices if x]
        # Filter out anything that looks like an aspect blob
        clean = [
            o
            for o in opts
            if ":" not in o and "square" not in o.lower() and "landscape" not in o.lower()
        ]
        return clean if clean else opts
    return ["Standard", "HD"]


def default_scene_quality(options: list[str] | None) -> str:
    opts = list(options or [])
    if not opts:
        return "Standard"
    lower_map = {o.lower(): o for o in opts}
    for p in ("2K", "1K", "hd", "standard"):
        if p.lower() in lower_map:
            return lower_map[p.lower()]
    return opts[0]


def resolve_scene_t2i_args(
    *,
    model_label: str | None,
    aspect_ui: str | None,
    quality: str | None,
) -> tuple[str, str | None, str]:
    """
    Map Scenes UI → (aspect_ratio for run_vision, resolution or None, canonical aspect).

    Aspect and quality stay separate: Flux image_size uses aspect (+ HD only for 1:1);
    Nano uses colon aspect + resolution enum.
    """
    from media_studio.vision_registry import find_vision_model

    ar = normalize_scene_aspect(aspect_ui) or "16:9"
    q = (quality or "").strip() or "Standard"
    spec = find_vision_model(model_label, "text_to_image") if model_label else None
    has_res = bool(spec and getattr(spec, "resolution_choices", None))

    if has_res:
        # Nano Banana etc.: aspect_ratio "16:9", resolution "1K"/"2K"
        return ar, q if q else (spec.default_resolution if spec else "1K"), ar

    # Flux / Seedream: image_size from aspect; HD upgrades 1:1 → square_hd
    if ar == "1:1" and q.lower() in ("hd", "high", "2k"):
        return "1:1 square HD", None, ar
    label_map = {
        "16:9": "16:9 landscape",
        "9:16": "9:16 portrait",
        "4:3": "4:3 landscape",
        "3:4": "3:4 portrait",
        "1:1": "1:1 square",
    }
    return label_map.get(ar, "16:9 landscape"), None, ar


# Back-compat aliases used by older flet_scenes imports
def t2i_resolution_options(model_label: str | None = None) -> list[str]:
    return scene_quality_options(model_label)


def default_practical_t2i_resolution(options: list[str] | None) -> str | None:
    return default_scene_quality(options)


def prune_unlocked_scenes(*, retention_days: int) -> dict[str, int]:
    """Age-prune unlocked scenes (locked always kept)."""
    if retention_days <= 0:
        return {"deleted_scenes": 0, "skipped_locked": 0}
    from datetime import timedelta

    cutoff = datetime.now(timezone.utc) - timedelta(days=int(retention_days))
    scenes = load_scenes()
    keep: list[SavedScene] = []
    deleted = 0
    skipped_locked = 0
    for s in scenes:
        if s.locked:
            keep.append(s)
            skipped_locked += 1
            continue
        try:
            ts = datetime.fromisoformat(
                (s.updated_at or s.created_at or "").replace("Z", "+00:00")
            )
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        except Exception:
            keep.append(s)
            continue
        if ts < cutoff:
            _delete_owned(s.still_path)
            deleted += 1
        else:
            keep.append(s)
    if deleted:
        save_scenes(keep)
    return {"deleted_scenes": deleted, "skipped_locked": skipped_locked}


# ----- Picker helpers (Director / future tabs) -----


@dataclass(frozen=True)
class ScenePickerChoice:
    id: str
    label: str
    still_path: str
    is_variation: bool = False
    parent_id: str | None = None
    aspect: str = ""

    @property
    def has_still(self) -> bool:
        try:
            return bool(self.still_path) and Path(self.still_path).is_file()
        except OSError:
            return False


def scene_picker_choices() -> list[ScenePickerChoice]:
    """
    Flat list for dropdowns: bases first, then each variation.
    Labels use display_name (user Name), not long generate prompts.
    """
    out: list[ScenePickerChoice] = []
    for base in list_base_scenes():
        bp = base.resolved_still_path()
        if bp:
            out.append(
                ScenePickerChoice(
                    id=base.id,
                    label=base.display_name(),
                    still_path=bp,
                    is_variation=False,
                    aspect=base.aspect_badge() or "",
                )
            )
        for kid in list_scene_variations(base.id):
            kp = kid.resolved_still_path()
            if not kp:
                continue
            # Child display name; nest under parent if not already prefixed
            kname = kid.display_name()
            bname = base.display_name()
            if bname and not kname.lower().startswith(bname.lower()[: min(12, len(bname))]):
                label = f"{bname} – {kname}"
            else:
                label = kname
            out.append(
                ScenePickerChoice(
                    id=kid.id,
                    label=label,
                    still_path=kp,
                    is_variation=True,
                    parent_id=base.id,
                    aspect=kid.aspect_badge() or base.aspect_badge() or "",
                )
            )
    return out


def find_scene_picker_choice(scene_id: str | None) -> ScenePickerChoice | None:
    if not scene_id:
        return None
    for ch in scene_picker_choices():
        if ch.id == scene_id:
            return ch
    return None
