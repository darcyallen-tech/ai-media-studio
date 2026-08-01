"""Prompt history + favorites (original + enhanced prompts)."""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from media_studio.config import ensure_output_dir

PROMPT_HISTORY_FILE = "prompt_history.json"
PROMPT_HISTORY_MAX = 50

_lock = threading.Lock()


@dataclass
class PromptEntry:
    id: str
    timestamp: str
    original_prompt: str
    enhanced_prompt: str
    model: str
    starred: bool = False
    label: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PromptEntry:
        return cls(
            id=str(data.get("id") or ""),
            timestamp=str(data.get("timestamp") or ""),
            original_prompt=str(data.get("original_prompt") or ""),
            enhanced_prompt=str(data.get("enhanced_prompt") or ""),
            model=str(data.get("model") or ""),
            starred=bool(data.get("starred")),
            label=str(data.get("label") or ""),
        )


def _path(output_dir: str | Path | None = None) -> Path:
    root = ensure_output_dir(Path(output_dir) if output_dir else None)
    return root / PROMPT_HISTORY_FILE


def _short(text: str, n: int = 40) -> str:
    t = " ".join((text or "").split())
    if len(t) <= n:
        return t or "(empty)"
    return t[: n - 1] + "…"


def make_label(entry: PromptEntry) -> str:
    ts = entry.timestamp
    if len(ts) == 15 and "_" in ts:
        try:
            dt = datetime.strptime(ts, "%Y%m%d_%H%M%S")
            ts = dt.strftime("%m-%d %H:%M")
        except ValueError:
            pass
    star = "★ " if entry.starred else ""
    model = entry.model or "model"
    # Prefer enhanced snippet; fall back to original
    snip = _short(entry.enhanced_prompt or entry.original_prompt)
    return f"{star}{ts} · {model} · {snip}"


def load_entries(output_dir: str | Path | None = None) -> list[PromptEntry]:
    path = _path(output_dir)
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(raw, list):
        return []
    out: list[PromptEntry] = []
    for item in raw:
        if isinstance(item, dict):
            e = PromptEntry.from_dict(item)
            e.label = make_label(e)
            out.append(e)
    return out


def save_entries(entries: list[PromptEntry], output_dir: str | Path | None = None) -> None:
    path = _path(output_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [e.to_dict() for e in entries[:PROMPT_HISTORY_MAX]]
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def append_prompt(
    *,
    original_prompt: str,
    enhanced_prompt: str,
    model: str,
    output_dir: str | Path | None = None,
    timestamp: str | None = None,
) -> PromptEntry:
    stamp = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    # Avoid id collisions within the same second
    with _lock:
        items = load_entries(output_dir)
        entry_id = stamp
        existing_ids = {e.id for e in items}
        n = 1
        while entry_id in existing_ids:
            entry_id = f"{stamp}_{n}"
            n += 1
        entry = PromptEntry(
            id=entry_id,
            timestamp=stamp,
            original_prompt=original_prompt or "",
            enhanced_prompt=enhanced_prompt or original_prompt or "",
            model=model or "",
            starred=False,
        )
        entry.label = make_label(entry)
        items.insert(0, entry)
        items = items[:PROMPT_HISTORY_MAX]
        save_entries(items, output_dir)
    return entry


def recent_entries(output_dir: str | Path | None = None) -> list[PromptEntry]:
    return load_entries(output_dir)


def favorite_entries(output_dir: str | Path | None = None) -> list[PromptEntry]:
    return [e for e in load_entries(output_dir) if e.starred]


def recent_choices(output_dir: str | Path | None = None) -> list[tuple[str, str]]:
    """Gradio dropdown choices as (label, id)."""
    return [(e.label, e.id) for e in recent_entries(output_dir)]


def favorite_choices(output_dir: str | Path | None = None) -> list[tuple[str, str]]:
    return [(e.label, e.id) for e in favorite_entries(output_dir)]


def recent_labels(output_dir: str | Path | None = None) -> list[str]:
    """Back-compat: list of labels only."""
    return [e.label for e in recent_entries(output_dir)]


def favorite_labels(output_dir: str | Path | None = None) -> list[str]:
    return [e.label for e in favorite_entries(output_dir)]


def find_prompt(
    key: str | None, output_dir: str | Path | None = None
) -> PromptEntry | None:
    """Find by id (preferred) or label."""
    if not key:
        return None
    for e in load_entries(output_dir):
        if e.id == key or e.label == key:
            return e
    return None


def toggle_star(
    key: str | None, output_dir: str | Path | None = None
) -> PromptEntry | None:
    if not key:
        return None
    with _lock:
        items = load_entries(output_dir)
        found = None
        for e in items:
            if e.id == key or e.label == key:
                e.starred = not e.starred
                e.label = make_label(e)
                found = e
                break
        if found:
            save_entries(items, output_dir)
        return found
