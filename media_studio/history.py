"""Simple generation history stored under the output folder."""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from media_studio.config import OUTPUT_DIR, ensure_output_dir

HISTORY_FILENAME = "history.json"
HISTORY_MAX = 200

_lock = threading.Lock()

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
VIDEO_EXTS = {".mp4", ".mov", ".webm", ".m4v", ".avi", ".mkv"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac", ".opus"}


@dataclass
class HistoryEntry:
    id: str
    timestamp: str
    job_kind: str  # image | video | image_to_video | audio | music | sfx | ...
    model: str
    prompt: str
    files: list[str] = field(default_factory=list)
    cost_estimate: str = ""
    notes: list[str] = field(default_factory=list)
    label: str = ""
    scenario: str = ""
    # Optional Job / Listing label (address, client, shoot) — empty = ungrouped
    job: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HistoryEntry:
        return cls(
            id=str(data.get("id") or ""),
            timestamp=str(data.get("timestamp") or ""),
            job_kind=str(data.get("job_kind") or "image"),
            model=str(data.get("model") or ""),
            prompt=str(data.get("prompt") or ""),
            files=list(data.get("files") or []),
            cost_estimate=str(data.get("cost_estimate") or ""),
            notes=list(data.get("notes") or []),
            label=str(data.get("label") or ""),
            scenario=str(data.get("scenario") or ""),
            job=str(data.get("job") or data.get("listing") or ""),
        )

    @property
    def media_type(self) -> str:
        """Image, Video, or Audio for UI badges / filters."""
        kind = (self.job_kind or "").lower()
        if kind in (
            "audio",
            "music",
            "sfx",
            "ambience",
            "voiceover",
            "vo",
            "video-sfx",
            "video_sfx",
            "audio-sfx",
            "audio-music",
            "audio-ambience",
            "audio-vsfx",
            "audio-vo",
        ):
            return "Audio"
        if first_audio_path(self) and not first_image_path(self) and not first_video_path(self):
            return "Audio"
        if kind in (
            "video",
            "image_to_video",
            "v2v",
            "i2v",
            "video-upscale",
            "creative_vision",
            "creative-vision",
            "vision",
            "aleph_keyframe",
            "aleph-keyframe",
            "aleph",
        ):
            return "Video"
        if first_video_path(self):
            return "Video"
        if first_audio_path(self) and not first_image_path(self):
            return "Audio"
        return "Image"

    def primary_path(self) -> str | None:
        img = first_image_path(self)
        if img:
            return img
        vid = first_video_path(self)
        if vid:
            return vid
        return first_audio_path(self)


def history_path(output_dir: str | Path | None = None) -> Path:
    root = ensure_output_dir(Path(output_dir) if output_dir else None)
    return root / HISTORY_FILENAME


def _short_prompt(prompt: str, max_len: int = 42) -> str:
    p = " ".join((prompt or "").split())
    if len(p) <= max_len:
        return p or "(no prompt)"
    return p[: max_len - 1] + "…"


def format_timestamp(ts: str) -> str:
    """Human-readable time from compact stamp or ISO."""
    if not ts:
        return ""
    if len(ts) == 15 and "_" in ts:
        try:
            dt = datetime.strptime(ts, "%Y%m%d_%H%M%S")
            return dt.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            pass
    return ts


def make_label(entry: HistoryEntry) -> str:
    """Dropdown-friendly one-liner."""
    ts = format_timestamp(entry.timestamp) or entry.timestamp
    kind = (entry.job_kind or "?").upper()
    model = entry.model or "model"
    cost = f" · {entry.cost_estimate}" if entry.cost_estimate else ""
    job = f" · [{entry.job}]" if (entry.job or "").strip() else ""
    return f"{ts} · {kind} · {model}{job} · {_short_prompt(entry.prompt)}{cost}"


def load_history(output_dir: str | Path | None = None) -> list[HistoryEntry]:
    path = history_path(output_dir)
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(raw, list):
        return []
    entries: list[HistoryEntry] = []
    for item in raw:
        if isinstance(item, dict):
            entry = HistoryEntry.from_dict(item)
            if not entry.label:
                entry.label = make_label(entry)
            entries.append(entry)
    return entries


def save_history(entries: list[HistoryEntry], output_dir: str | Path | None = None) -> None:
    path = history_path(output_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [e.to_dict() for e in entries[:HISTORY_MAX]]
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)  # atomic-ish on Windows same volume


def append_history(
    *,
    job_kind: str,
    model: str,
    prompt: str,
    files: list[str],
    cost_estimate: str = "",
    notes: list[str] | None = None,
    output_dir: str | Path | None = None,
    timestamp: str | None = None,
    scenario: str | None = None,
    job: str | None = None,
) -> HistoryEntry:
    """Prepend a successful generation to history.json."""
    stamp = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    # Only keep files that still exist
    existing = []
    for f in files:
        try:
            if f and Path(f).is_file():
                existing.append(str(Path(f).resolve()))
        except OSError:
            continue

    job_label = (job or "").strip()
    if not job_label:
        try:
            from media_studio.job_context import current_job_name

            job_label = current_job_name()
        except Exception:
            job_label = ""

    entry = HistoryEntry(
        id=stamp,
        timestamp=stamp,
        job_kind=job_kind,
        model=model,
        prompt=prompt,
        files=existing,
        cost_estimate=cost_estimate,
        notes=list(notes or []),
        scenario=str(scenario or ""),
        job=job_label,
    )
    entry.label = make_label(entry)

    with _lock:
        items = load_history(output_dir)
        items = [e for e in items if e.id != entry.id]
        items.insert(0, entry)
        items = items[:HISTORY_MAX]
        save_history(items, output_dir)
    return entry


def list_job_names(output_dir: str | Path | None = None) -> list[str]:
    """Distinct non-empty job labels from history (newest-first order preserved)."""
    seen: set[str] = set()
    out: list[str] = []
    for e in load_history(output_dir):
        j = (e.job or "").strip()
        if j and j not in seen:
            seen.add(j)
            out.append(j)
    return out


def history_dropdown_choices(output_dir: str | Path | None = None) -> list[str]:
    return [e.label for e in load_history(output_dir)]


def find_by_label(label: str | None, output_dir: str | Path | None = None) -> HistoryEntry | None:
    if not label:
        return None
    for entry in load_history(output_dir):
        if entry.label == label or entry.id == label:
            return entry
    return None


def find_by_id(entry_id: str | None, output_dir: str | Path | None = None) -> HistoryEntry | None:
    if not entry_id:
        return None
    for entry in load_history(output_dir):
        if entry.id == entry_id:
            return entry
    return None


def first_image_path(entry: HistoryEntry) -> str | None:
    """First existing image file from a history entry (for use as reference)."""
    for f in entry.files:
        p = Path(f)
        try:
            if p.is_file() and p.suffix.lower() in IMAGE_EXTS:
                return str(p.resolve())
        except OSError:
            continue
    return None


def first_video_path(entry: HistoryEntry) -> str | None:
    for f in entry.files:
        p = Path(f)
        try:
            if p.is_file() and p.suffix.lower() in VIDEO_EXTS:
                return str(p.resolve())
        except OSError:
            continue
    return None


def first_audio_path(entry: HistoryEntry) -> str | None:
    for f in entry.files:
        p = Path(f)
        try:
            if p.is_file() and p.suffix.lower() in AUDIO_EXTS:
                return str(p.resolve())
        except OSError:
            continue
    return None


def library_entries(
    output_dir: str | Path | None = None,
    *,
    existing_only: bool = True,
) -> list[HistoryEntry]:
    """
    Newest-first history for the Library tab.

    When existing_only, drop entries whose files are all missing.
    """
    out: list[HistoryEntry] = []
    for e in load_history(output_dir):
        if existing_only:
            has = False
            for f in e.files:
                try:
                    if f and Path(f).is_file():
                        has = True
                        break
                except OSError:
                    continue
            if not has:
                continue
        out.append(e)
    return out
