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

    def display_notes(self) -> str:
        n = (self.notes or "").strip()
        # Don't surface long T2I prompt blobs as notes if name is short
        if len(n) > 160:
            return n[:157].rstrip() + "…"
        return n

    def display_name(self) -> str:
        """
        User-facing list title. Prefer short Name; if Name was polluted by a long
        generate prompt, show a truncated title (never put the full prompt first).
        """
        n = (self.name or "").strip() or "Untitled scene"
        low = n.lower()
        looks_like_prompt = len(n) > 48 and any(
            tok in low
            for tok in (
                "photoreal",
                "establishing",
                "location plate",
                "empty or lightly",
                "no hero",
                "creative intent",
            )
        )
        if looks_like_prompt:
            return n[:40].rstrip(" .,;:-") + "…"
        if len(n) > 56:
            return n[:53].rstrip() + "…"
        return n

    def has_still(self) -> bool:
        p = self.resolved_still_path()
        return bool(p)

    def resolved_still_path(self) -> str | None:
        """Return a readable still path, repairing basename under scene_stills/."""
        raw = (self.still_path or "").strip()
        if not raw:
            return None
        try:
            p = Path(raw)
            if p.is_file():
                return str(p.resolve())
        except OSError:
            pass
        # Repair: same filename in local store dir
        try:
            cand = STILLS_DIR / Path(raw).name
            if cand.is_file():
                return str(cand.resolve())
        except OSError:
            pass
        return None

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
    )


def _to_dict(s: SavedScene) -> dict[str, Any]:
    return {
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
    )
    scenes[idx] = updated
    save_scenes(scenes)
    # Drop previous owned still if replaced
    if still_path is not None and old_still and old_still != new_still:
        _delete_owned(old_still)
    return updated


def set_scene_locked(scene_id: str, locked: bool) -> SavedScene | None:
    scenes = load_scenes()
    for i, s in enumerate(scenes):
        if s.id != scene_id:
            continue
        s.locked = bool(locked)
        s.updated_at = _now_iso()
        scenes[i] = s
        save_scenes(scenes)
        return s
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
        try:
            if s.still_path:
                keep_paths.add(str(Path(s.still_path).resolve()))
        except OSError:
            pass
    for s in to_wipe:
        try:
            p = str(Path(s.still_path).resolve()) if s.still_path else ""
            if p and p not in keep_paths:
                _delete_owned(s.still_path)
        except OSError:
            _delete_owned(s.still_path)
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
