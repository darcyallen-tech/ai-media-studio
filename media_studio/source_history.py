"""
Recently used *source* media (stills and clips — not generated results).

Persists last N paths under outputs/ so picker/temp files remain available.
Images are cached into `_source_history/`; videos store durable path refs
(and only copy when small enough to be practical).
"""

from __future__ import annotations

import hashlib
import json
import shutil
import threading
from datetime import datetime
from pathlib import Path
from typing import Literal

from media_studio.config import ensure_output_dir

SOURCE_HISTORY_FILE = "source_history.json"
SOURCE_HISTORY_DIR = "_source_history"
SOURCE_HISTORY_MAX = 5
# Avoid copying huge camera masters into the cache
_VIDEO_COPY_MAX_MB = 80.0

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tiff"}
_VIDEO_EXTS = {".mp4", ".mov", ".webm", ".m4v", ".avi", ".mkv"}
_lock = threading.Lock()

MediaKind = Literal["image", "video", "all"]


def _root(output_dir: str | Path | None = None) -> Path:
    return ensure_output_dir(Path(output_dir) if output_dir else None)


def _history_path(output_dir: str | Path | None = None) -> Path:
    return _root(output_dir) / SOURCE_HISTORY_FILE


def _cache_dir(output_dir: str | Path | None = None) -> Path:
    d = _root(output_dir) / SOURCE_HISTORY_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _is_image_file(path: Path) -> bool:
    try:
        return path.is_file() and path.suffix.lower() in _IMAGE_EXTS
    except OSError:
        return False


def _is_video_file(path: Path) -> bool:
    try:
        return path.is_file() and path.suffix.lower() in _VIDEO_EXTS
    except OSError:
        return False


def _kind_of(path: Path) -> str | None:
    if _is_image_file(path):
        return "image"
    if _is_video_file(path):
        return "video"
    return None


def _file_fingerprint(path: Path) -> str:
    """Short content hash so re-uploads of the same media de-dupe."""
    h = hashlib.sha1()
    try:
        with path.open("rb") as f:
            chunk = f.read(256 * 1024)
            h.update(chunk)
            h.update(str(path.stat().st_size).encode())
    except OSError:
        h.update(str(path).encode())
    return h.hexdigest()[:12]


def _load_raw_unlocked(output_dir: str | Path | None = None) -> list[dict]:
    path = _history_path(output_dir)
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(raw, list):
        return []
    return [x for x in raw if isinstance(x, dict)]


def _save_raw_unlocked(entries: list[dict], output_dir: str | Path | None = None) -> None:
    path = _history_path(output_dir)
    try:
        path.write_text(
            json.dumps(entries, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass


def _entry_kind(e: dict) -> str:
    k = str(e.get("kind") or "").strip().lower()
    if k in ("image", "video"):
        return k
    p = Path(str(e.get("path") or ""))
    return _kind_of(p) or "image"


def _paths_from_entries(
    entries: list[dict],
    *,
    media_kind: MediaKind = "image",
    limit: int = SOURCE_HISTORY_MAX,
) -> list[str]:
    paths: list[str] = []
    for e in entries:
        kind = _entry_kind(e)
        if media_kind != "all" and kind != media_kind:
            continue
        p = Path(str(e.get("path") or ""))
        try:
            if not p.is_file():
                continue
            if media_kind == "image" and not _is_image_file(p):
                continue
            if media_kind == "video" and not _is_video_file(p):
                continue
            if media_kind == "all" and _kind_of(p) is None:
                continue
            paths.append(str(p.resolve()))
        except OSError:
            continue
        if len(paths) >= limit:
            break
    return paths


def load_source_paths(
    output_dir: str | Path | None = None,
    *,
    media_kind: MediaKind = "image",
    limit: int = SOURCE_HISTORY_MAX,
) -> list[str]:
    """
    Newest-first list of existing source paths (max ``limit``).

    ``media_kind``: image | video | all
    """
    with _lock:
        entries = _load_raw_unlocked(output_dir)
        kept: list[dict] = []
        for e in entries:
            p = Path(str(e.get("path") or ""))
            kind = _entry_kind(e)
            if not p.is_file():
                continue
            if kind == "image" and not _is_image_file(p):
                continue
            if kind == "video" and not _is_video_file(p):
                continue
            if kind not in ("image", "video"):
                continue
            # Normalize kind on read
            e = dict(e)
            e["kind"] = kind
            kept.append(e)
        # Keep more raw entries than display limit so image+video can coexist
        max_store = max(SOURCE_HISTORY_MAX * 3, 15)
        if len(kept) != len(entries) or len(kept) > max_store:
            _save_raw_unlocked(kept[:max_store], output_dir)
        return _paths_from_entries(kept, media_kind=media_kind, limit=limit)


def record_source(
    source_path: str | Path | None,
    output_dir: str | Path | None = None,
    *,
    media_kind: MediaKind | None = None,
) -> list[str]:
    """
    Remember a source still or clip after a successful load.

    Images: copy into durable cache (same as before).
    Videos: store path ref; copy only when under size threshold.
    Returns newest-first paths for the recorded media kind (or images).
    """
    if not source_path:
        return load_source_paths(output_dir, media_kind=media_kind or "image")

    try:
        src = Path(str(source_path))
    except (TypeError, ValueError):
        return load_source_paths(output_dir, media_kind=media_kind or "image")

    detected = _kind_of(src)
    if not detected:
        return load_source_paths(output_dir, media_kind=media_kind or "image")
    kind = media_kind if media_kind in ("image", "video") else detected
    if kind != detected:
        # Path doesn't match requested kind
        return load_source_paths(output_dir, media_kind=kind)

    # Never treat compare overlays / region live previews as sources
    parts_lower = {p.lower() for p in src.parts}
    if "compare" in parts_lower and "_previews" in parts_lower:
        return load_source_paths(output_dir, media_kind=kind)
    if "_region" in parts_lower and "live_preview" in src.name.lower():
        return load_source_paths(output_dir, media_kind=kind)

    with _lock:
        entries = _load_raw_unlocked(output_dir)
        try:
            fp = _file_fingerprint(src)
        except Exception:
            fp = hashlib.sha1(str(src).encode()).hexdigest()[:12]

        cache = _cache_dir(output_dir)
        entries = [e for e in entries if e.get("fingerprint") != fp]

        try:
            resolved = src.resolve()
        except OSError:
            resolved = src

        if SOURCE_HISTORY_DIR in resolved.parts:
            dest = resolved
        elif kind == "image":
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_name = "".join(
                c if c.isalnum() or c in "._-" else "-" for c in src.name
            )[:80]
            dest = cache / f"{stamp}_{fp}_{safe_name}"
            try:
                if not dest.is_file():
                    shutil.copy2(src, dest)
            except OSError:
                dest = resolved
        else:
            # Video: avoid copying huge masters; use path if still on disk
            dest = resolved
            try:
                size_mb = resolved.stat().st_size / (1024 * 1024)
            except OSError:
                size_mb = 9999.0
            if size_mb <= _VIDEO_COPY_MAX_MB and SOURCE_HISTORY_DIR not in resolved.parts:
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                safe_name = "".join(
                    c if c.isalnum() or c in "._-" else "-" for c in src.name
                )[:80]
                cached = cache / f"{stamp}_{fp}_{safe_name}"
                try:
                    if not cached.is_file():
                        shutil.copy2(src, cached)
                    dest = cached
                except OSError:
                    dest = resolved

        if kind == "image" and not _is_image_file(dest):
            return _paths_from_entries(entries, media_kind=kind)
        if kind == "video" and not _is_video_file(dest):
            return _paths_from_entries(entries, media_kind=kind)

        try:
            dest_str = str(dest.resolve())
        except OSError:
            dest_str = str(dest)

        entry = {
            "path": dest_str,
            "fingerprint": fp,
            "original_name": src.name,
            "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
            "kind": kind,
        }
        entries.insert(0, entry)
        max_store = max(SOURCE_HISTORY_MAX * 3, 15)
        entries = entries[:max_store]
        _save_raw_unlocked(entries, output_dir)
        return _paths_from_entries(entries, media_kind=kind)


def gallery_value(output_dir: str | Path | None = None) -> list[str]:
    """Newest-first image source filepaths (Studio Image compatibility)."""
    return load_source_paths(output_dir, media_kind="image")


def gallery_videos(output_dir: str | Path | None = None) -> list[str]:
    """Newest-first video source filepaths."""
    return load_source_paths(output_dir, media_kind="video")
