"""
Prompt favorites + simple prompt packs (Phase 4).

Stored under app data (same root as ui_prefs) — not secrets, not the project
outputs folder that may be shared or wiped with retention.
"""

from __future__ import annotations

import json
import re
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from media_studio.secrets_store import app_data_dir

FAVORITES_FILENAME = "prompt_favorites.json"
FAVORITES_MAX = 200
PACK_FORMAT = "ai-media-studio-prompt-pack"
PACK_VERSION = 1

_lock = threading.Lock()


@dataclass
class FavoritePrompt:
    id: str
    text: str
    timestamp: str = ""
    # "user" | "enhanced" | "mixed"
    source: str = "user"
    # studio_image | studio_video | vision | tools | audio | frame_editor | other
    surface: str = "other"
    scenario: str = ""
    model: str = ""
    label: str = ""
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FavoritePrompt:
        return cls(
            id=str(data.get("id") or ""),
            text=str(data.get("text") or data.get("prompt") or "").strip(),
            timestamp=str(data.get("timestamp") or ""),
            source=str(data.get("source") or "user"),
            surface=str(data.get("surface") or "other"),
            scenario=str(data.get("scenario") or ""),
            model=str(data.get("model") or ""),
            label=str(data.get("label") or ""),
            notes=str(data.get("notes") or ""),
        )


def favorites_path() -> Path:
    return app_data_dir() / FAVORITES_FILENAME


def _short(text: str, n: int = 48) -> str:
    t = " ".join((text or "").split())
    if len(t) <= n:
        return t or "(empty)"
    return t[: n - 1] + "…"


def make_favorite_label(fav: FavoritePrompt) -> str:
    if (fav.label or "").strip():
        base = fav.label.strip()
    else:
        base = _short(fav.text)
    bits = [base]
    if fav.scenario:
        bits.append(fav.scenario)
    if fav.source == "enhanced":
        bits.append("enhanced")
    return " · ".join(bits)


def load_favorites() -> list[FavoritePrompt]:
    path = favorites_path()
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return []
    if isinstance(raw, dict):
        raw = raw.get("favorites") or raw.get("prompts") or []
    if not isinstance(raw, list):
        return []
    out: list[FavoritePrompt] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        fav = FavoritePrompt.from_dict(item)
        if not fav.text:
            continue
        if not fav.id:
            fav.id = uuid.uuid4().hex[:12]
        if not fav.label:
            fav.label = make_favorite_label(fav)
        out.append(fav)
    return out


def save_favorites(items: list[FavoritePrompt]) -> None:
    path = favorites_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "format": "ai-media-studio-favorites",
        "version": 1,
        "favorites": [e.to_dict() for e in items[:FAVORITES_MAX]],
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def add_favorite(
    text: str,
    *,
    source: str = "user",
    surface: str = "other",
    scenario: str = "",
    model: str = "",
    label: str = "",
    notes: str = "",
) -> FavoritePrompt | None:
    """Star / save a prompt. Dedupes exact text (case-insensitive strip)."""
    body = (text or "").strip()
    if not body:
        return None
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    with _lock:
        items = load_favorites()
        low = body.lower()
        for e in items:
            if e.text.strip().lower() == low:
                # Refresh metadata on re-star
                e.source = source or e.source
                e.surface = surface or e.surface
                e.scenario = scenario or e.scenario
                e.model = model or e.model
                if label:
                    e.label = label
                e.timestamp = stamp
                e.label = e.label or make_favorite_label(e)
                # Move to front
                items = [e] + [x for x in items if x.id != e.id]
                save_favorites(items)
                return e
        fav = FavoritePrompt(
            id=uuid.uuid4().hex[:12],
            text=body,
            timestamp=stamp,
            source=(source or "user").strip().lower() or "user",
            surface=(surface or "other").strip() or "other",
            scenario=(scenario or "").strip(),
            model=(model or "").strip(),
            label=(label or "").strip(),
            notes=(notes or "").strip(),
        )
        if not fav.label:
            fav.label = make_favorite_label(fav)
        items.insert(0, fav)
        save_favorites(items)
        return fav


def remove_favorite(fav_id: str | None) -> bool:
    if not fav_id:
        return False
    with _lock:
        items = load_favorites()
        new = [e for e in items if e.id != fav_id]
        if len(new) == len(items):
            return False
        save_favorites(new)
        return True


def find_favorite(key: str | None) -> FavoritePrompt | None:
    if not key:
        return None
    for e in load_favorites():
        if e.id == key or e.label == key:
            return e
    return None


def favorite_choice_labels() -> list[str]:
    return [e.label for e in load_favorites()]


def favorite_choices() -> list[tuple[str, str]]:
    """(label, id) for dropdowns."""
    return [(e.label, e.id) for e in load_favorites()]


# ---------------------------------------------------------------------------
# Prompt packs (export / import)
# ---------------------------------------------------------------------------


@dataclass
class PromptPack:
    name: str
    prompts: list[dict[str, Any]] = field(default_factory=list)
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": PACK_FORMAT,
            "version": PACK_VERSION,
            "name": self.name,
            "description": self.description,
            "prompts": list(self.prompts),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PromptPack:
        name = str(data.get("name") or "Imported pack").strip() or "Imported pack"
        prompts = data.get("prompts") or data.get("favorites") or []
        if not isinstance(prompts, list):
            prompts = []
        clean: list[dict[str, Any]] = []
        for p in prompts:
            if isinstance(p, str) and p.strip():
                clean.append({"text": p.strip(), "source": "user"})
            elif isinstance(p, dict):
                text = str(p.get("text") or p.get("prompt") or "").strip()
                if not text:
                    continue
                clean.append(
                    {
                        "text": text,
                        "source": str(p.get("source") or "user"),
                        "scenario": str(p.get("scenario") or p.get("tag") or ""),
                        "label": str(p.get("label") or ""),
                        "notes": str(p.get("notes") or ""),
                        "surface": str(p.get("surface") or ""),
                        "model": str(p.get("model") or ""),
                    }
                )
        return cls(
            name=name,
            prompts=clean,
            description=str(data.get("description") or ""),
        )


def export_pack(
    *,
    name: str,
    favorite_ids: list[str] | None = None,
    include_all: bool = False,
    description: str = "",
) -> PromptPack:
    """Build a pack from current favorites (all or selected ids)."""
    items = load_favorites()
    if include_all or not favorite_ids:
        chosen = items
    else:
        idset = set(favorite_ids)
        chosen = [e for e in items if e.id in idset]
    prompts = [
        {
            "text": e.text,
            "source": e.source,
            "scenario": e.scenario,
            "label": e.label,
            "notes": e.notes,
            "surface": e.surface,
            "model": e.model,
        }
        for e in chosen
        if e.text.strip()
    ]
    return PromptPack(
        name=(name or "Prompt pack").strip() or "Prompt pack",
        prompts=prompts,
        description=(description or "").strip(),
    )


def write_pack_file(pack: PromptPack, path: str | Path) -> Path:
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        json.dumps(pack.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return dest


def read_pack_file(path: str | Path) -> PromptPack:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Prompt pack must be a JSON object.")
    return PromptPack.from_dict(raw)


def import_pack(
    pack: PromptPack,
    *,
    merge: bool = True,
) -> tuple[int, int]:
    """
    Import pack prompts into favorites.

    Returns (added, skipped_duplicates).
    """
    added = 0
    skipped = 0
    for p in pack.prompts:
        text = str(p.get("text") or "").strip()
        if not text:
            continue
        existing = {e.text.strip().lower() for e in load_favorites()}
        was_dup = text.lower() in existing
        fav = add_favorite(
            text,
            source=str(p.get("source") or "user"),
            surface=str(p.get("surface") or "other"),
            scenario=str(p.get("scenario") or ""),
            model=str(p.get("model") or ""),
            label=str(p.get("label") or ""),
            notes=str(p.get("notes") or f"from pack: {pack.name}"),
        )
        if not fav:
            skipped += 1
        elif was_dup and merge:
            skipped += 1
        else:
            added += 1
    return added, skipped


def safe_pack_filename(name: str) -> str:
    raw = (name or "prompt-pack").strip().lower()
    raw = re.sub(r"[^a-z0-9\-_\s]+", "", raw)
    raw = re.sub(r"\s+", "-", raw).strip("-") or "prompt-pack"
    return f"{raw[:48]}.json"
