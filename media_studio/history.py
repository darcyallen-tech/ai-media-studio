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
    # Import provenance: "" | "resolve" (Resolve plugin / Import from Resolve)
    origin: str = ""

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
            origin=str(data.get("origin") or ""),
        )

    @property
    def is_from_resolve(self) -> bool:
        return (self.origin or "").strip().lower() == "resolve"

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
            "director",
            "multi_shot",
            "multi-shot",
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
    origin: str | None = None,
) -> HistoryEntry:
    """Prepend a successful generation (or Resolve import) to history.json."""
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

    origin_val = (origin or "").strip().lower()
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
        origin=origin_val,
    )
    entry.label = make_label(entry)

    with _lock:
        items = load_history(output_dir)
        items = [e for e in items if e.id != entry.id]
        items.insert(0, entry)
        items = items[:HISTORY_MAX]
        save_history(items, output_dir)
    return entry


def record_resolve_library(
    *,
    still_path: str | Path | None = None,
    video_path: str | Path | None = None,
    clip_name: str | None = None,
    handoff_id: str | None = None,
    output_dir: str | Path | None = None,
) -> list[HistoryEntry]:
    """
    Record Resolve handoff media in Library with origin=resolve.

    Stable ids per handoff (resolve_<id>_still / _video) so re-import updates
    rather than spam duplicates.
    """
    name = (clip_name or "Resolve").strip() or "Resolve"
    hid_raw = (handoff_id or "").strip() or datetime.now().strftime("%Y%m%d_%H%M%S")
    # Sanitize id segment for history.json keys
    hid = "".join(c if c.isalnum() or c in "-_" else "_" for c in hid_raw)[:64]
    written: list[HistoryEntry] = []

    still = None
    if still_path:
        try:
            sp = Path(str(still_path))
            if sp.is_file():
                still = str(sp.resolve())
        except OSError:
            still = None
    video = None
    if video_path:
        try:
            vp = Path(str(video_path))
            if vp.is_file():
                video = str(vp.resolve())
        except OSError:
            video = None

    if still:
        written.append(
            append_history(
                job_kind="image",
                model="Resolve",
                prompt=name,
                files=[still],
                notes=["Resolve handoff still"],
                origin="resolve",
                timestamp=f"resolve_{hid}_still",
                output_dir=output_dir,
            )
        )
    if video:
        written.append(
            append_history(
                job_kind="video",
                model="Resolve",
                prompt=name,
                files=[video],
                notes=["Resolve handoff clip"],
                origin="resolve",
                timestamp=f"resolve_{hid}_video",
                output_dir=output_dir,
            )
        )
    return written


def list_job_names(output_dir: str | Path | None = None) -> list[str]:
    """
    Distinct non-empty job labels for filters / Assign menus.

    Prefer human labels from history (newest first), then any folder names under
    ``outputs/jobs/`` that are not already represented.
    """
    seen: set[str] = set()
    out: list[str] = []
    for e in load_history(output_dir):
        j = (e.job or "").strip()
        if j and j.lower() not in seen:
            seen.add(j.lower())
            out.append(j)
    # Folder slugs from disk (older jobs that only exist as directories)
    try:
        root = ensure_output_dir(Path(output_dir) if output_dir else None)
        jobs_dir = root / "jobs"
        if jobs_dir.is_dir():
            for p in sorted(jobs_dir.iterdir(), key=lambda x: x.name.lower()):
                if not p.is_dir() or p.name.startswith("."):
                    continue
                # Prefer pretty label; skip if a history label already maps to this slug
                label = p.name.replace("-", " ").strip()
                if not label:
                    continue
                if label.lower() in seen or p.name.lower() in seen:
                    continue
                # Also skip if any existing job slug-matches this folder
                try:
                    from media_studio.naming import job_name_slug

                    if any(job_name_slug(x) == p.name for x in out):
                        continue
                except Exception:
                    pass
                seen.add(label.lower())
                out.append(label)
    except OSError:
        pass
    return out


def _safe_move_under_job(
    file_path: str,
    *,
    output_dir: str | Path,
    job_label: str,
    stamp_hint: str = "",
) -> tuple[str, str | None]:
    """
    Move a media file into jobs/<slug>/<date>/ when it lives under output_dir.

    Returns (new_or_same_path, note_or_None). Never moves files outside the
    output root. Clear-job (empty label) does not move.
    """
    try:
        from media_studio.naming import date_bucket, job_name_slug
    except Exception:
        return file_path, None

    slug = job_name_slug(job_label)
    if not slug:
        return file_path, None

    try:
        src = Path(file_path).expanduser().resolve()
        if not src.is_file():
            return file_path, None
        root = Path(output_dir).expanduser().resolve()
        try:
            src.relative_to(root)
        except ValueError:
            # Outside app output tree — leave path as-is (metadata-only assign)
            return str(src), "file outside output folder — path unchanged"
    except OSError:
        return file_path, None

    # Prefer existing date folder segment if present
    day = None
    parts = src.parts
    for part in reversed(parts):
        if len(part) == 10 and part[4] == "-" and part[7] == "-":
            day = part
            break
    if not day:
        day = date_bucket(stamp_hint)

    dest_dir = root / "jobs" / slug / day
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return str(src), f"could not create job folder: {exc}"

    dest = dest_dir / src.name
    if dest.resolve() == src:
        return str(src), None
    if dest.exists():
        stem, ext = src.stem, src.suffix
        n = 1
        while dest.exists():
            dest = dest_dir / f"{stem}_{n}{ext}"
            n += 1
    try:
        src.replace(dest)  # atomic move on same volume
        return str(dest.resolve()), None
    except OSError:
        try:
            import shutil

            shutil.move(str(src), str(dest))
            return str(dest.resolve()), None
        except OSError as exc:
            return str(src), f"move failed: {exc}"


def assign_entry_job(
    entry_id: str,
    job_name: str | None,
    *,
    output_dir: str | Path | None = None,
    move_files: bool = True,
) -> tuple[HistoryEntry | None, str]:
    """
    Assign (or clear) Job / Listing on an existing history row.

    Updates metadata always. When ``move_files`` and job is non-empty, attempts
    to move media under ``outputs/jobs/<slug>/<date>/`` if files live under the
    output root. Clearing a job only updates metadata (no reverse move).

    Returns ``(entry, status_message)``.
    """
    eid = (entry_id or "").strip()
    if not eid:
        return None, "Missing history id."

    new_job = (job_name or "").strip()
    notes: list[str] = []

    with _lock:
        items = load_history(output_dir)
        found: HistoryEntry | None = None
        idx = -1
        for i, e in enumerate(items):
            if e.id == eid:
                found = e
                idx = i
                break
        if found is None:
            return None, f"History item not found: {eid}"

        old_job = (found.job or "").strip()
        if old_job == new_job:
            return found, (
                f"Already under “{new_job}”." if new_job else "Already ungrouped."
            )

        # Optional relocate media into job folder
        new_files: list[str] = []
        if move_files and new_job:
            root = ensure_output_dir(Path(output_dir) if output_dir else None)
            for f in found.files:
                nf, note = _safe_move_under_job(
                    f,
                    output_dir=root,
                    job_label=new_job,
                    stamp_hint=found.timestamp or found.id,
                )
                new_files.append(nf)
                if note:
                    notes.append(note)
            found.files = new_files
        # Clear job: keep files where they are (safer)

        found.job = new_job
        found.label = make_label(found)
        items[idx] = found
        save_history(items, output_dir)

    if new_job:
        msg = f"Assigned to job “{new_job}”."
    else:
        msg = "Cleared job — now Ungrouped."
    if notes:
        msg += " " + "; ".join(notes[:2])
    return found, msg


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
