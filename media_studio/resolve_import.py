"""
Resolve → AI Media Studio handoff (reverse of Send to Resolve).

DaVinci Resolve script writes JSON + media under data/resolve_handoff/.
The Studio app watches that folder and loads still + video into Image/Video.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from media_studio.config import PROJECT_ROOT

HANDOFF_DIR = PROJECT_ROOT / "data" / "resolve_handoff"
LATEST_NAME = "latest.json"
STATE_NAME = ".last_imported_id"
VIDEO_HISTORY_NAME = "video_history.json"
VIDEO_HISTORY_MAX = 8

# Retention: only files inside HANDOFF_DIR (never outside)
HANDOFF_MAX_AGE_DAYS = 7
HANDOFF_MAX_FILES = 200  # non-keep files; oldest by mtime dropped first
_KEEP_NAMES = frozenset(
    {
        LATEST_NAME,
        STATE_NAME,
        VIDEO_HISTORY_NAME,
        ".gitkeep",
        "studio_root.txt",  # never present here; defensive
    }
)
_last_purge_monotonic: float = 0.0
_PURGE_MIN_INTERVAL_S = 3600.0  # at most once per hour unless forced

_VIDEO_EXTS = {".mp4", ".mov", ".webm", ".m4v", ".avi", ".mkv", ".mxf", ".r3d", ".braw"}


@dataclass
class ResolveHandoff:
    still_path: str | None
    video_path: str | None
    clip_name: str
    timestamp: str
    handoff_id: str
    raw: dict[str, Any]
    json_path: str
    video_missing: bool = False  # path in JSON but file not found
    video_is_proxy: bool = False  # graded Deliver proxy (not camera master)
    proxy_graded: bool = False

    @property
    def has_still(self) -> bool:
        return bool(self.still_path and Path(self.still_path).is_file())

    @property
    def has_video(self) -> bool:
        return bool(self.video_path and Path(self.video_path).is_file())

    @property
    def ok(self) -> bool:
        return self.has_still or self.has_video or bool(self.video_path)


def _studio_root_marker_path() -> Path:
    """LocalAppData marker so Resolve script finds this install without a hard-coded path."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(
            Path.home() / "AppData" / "Local"
        )
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "AI Media Studio" / "studio_root.txt"


def write_studio_root_marker() -> None:
    """
    Register this machine's Studio project path for the Resolve handoff script.

    Writes one line (absolute PROJECT_ROOT) under LocalAppData. Safe to call often.
    """
    try:
        p = _studio_root_marker_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        root = str(Path(PROJECT_ROOT).resolve())
        # Avoid rewrite noise if unchanged
        if p.is_file():
            try:
                if p.read_text(encoding="utf-8").strip() == root:
                    return
            except OSError:
                pass
        p.write_text(root + "\n", encoding="utf-8")
    except OSError:
        pass


def ensure_handoff_dir() -> Path:
    HANDOFF_DIR.mkdir(parents=True, exist_ok=True)
    write_studio_root_marker()
    return HANDOFF_DIR


def handoff_dir() -> Path:
    return ensure_handoff_dir()


def purge_handoff_cache(
    *,
    max_age_days: int = HANDOFF_MAX_AGE_DAYS,
    max_files: int = HANDOFF_MAX_FILES,
    force: bool = False,
) -> dict[str, Any]:
    """
    Delete old Resolve handoff files **only** under ``data/resolve_handoff/``.

    Keeps ``latest.json``, ``.last_imported_id``, and ``video_history.json``.
    Never touches paths outside the handoff folder.

    Returns stats: deleted, kept, errors, skipped (throttled).
    """
    global _last_purge_monotonic
    now_m = time.monotonic()
    if not force and (now_m - _last_purge_monotonic) < _PURGE_MIN_INTERVAL_S:
        return {
            "deleted": 0,
            "kept": 0,
            "errors": 0,
            "skipped": True,
            "dir": str(HANDOFF_DIR),
        }

    ensure_handoff_dir()
    # Safety: only operate inside resolved HANDOFF_DIR
    try:
        root = HANDOFF_DIR.resolve()
    except OSError as exc:
        return {
            "deleted": 0,
            "kept": 0,
            "errors": 1,
            "skipped": False,
            "error": str(exc),
            "dir": str(HANDOFF_DIR),
        }

    cutoff = time.time() - max(1, int(max_age_days)) * 86400.0
    deleted = 0
    errors = 0
    candidates: list[tuple[float, Path]] = []

    try:
        entries = list(root.iterdir())
    except OSError as exc:
        return {
            "deleted": 0,
            "kept": 0,
            "errors": 1,
            "skipped": False,
            "error": str(exc),
            "dir": str(root),
        }

    for p in entries:
        try:
            # Never leave the handoff directory (no recurse into odd trees)
            if not p.is_file():
                continue
            rp = p.resolve()
            if root not in rp.parents and rp != root:
                # File not under handoff root — skip
                continue
            if p.name in _KEEP_NAMES:
                continue
            # Only purge handoff media / JSON artifacts
            name = p.name.lower()
            if not (
                name.startswith("handoff_")
                or name.endswith(".png")
                or name.endswith(".jpg")
                or name.endswith(".jpeg")
                or name.endswith(".json")
            ):
                # Leave unknown files alone
                continue
            if name == LATEST_NAME.lower():
                continue
            mtime = p.stat().st_mtime
            candidates.append((mtime, p))
        except OSError:
            errors += 1

    # Age pass
    survivors: list[tuple[float, Path]] = []
    for mtime, p in candidates:
        if mtime < cutoff:
            try:
                p.unlink(missing_ok=True)
                deleted += 1
            except OSError:
                errors += 1
        else:
            survivors.append((mtime, p))

    # Count pass — keep newest max_files
    survivors.sort(key=lambda t: t[0], reverse=True)
    if len(survivors) > max(1, int(max_files)):
        for _, p in survivors[max(1, int(max_files)) :]:
            try:
                p.unlink(missing_ok=True)
                deleted += 1
            except OSError:
                errors += 1
        survivors = survivors[: max(1, int(max_files))]

    _last_purge_monotonic = now_m
    return {
        "deleted": deleted,
        "kept": len(survivors) + len(_KEEP_NAMES),
        "errors": errors,
        "skipped": False,
        "dir": str(root),
        "max_age_days": max_age_days,
        "max_files": max_files,
    }


def maybe_purge_handoff_cache() -> dict[str, Any]:
    """Throttled purge for background use (poll / startup)."""
    return purge_handoff_cache(force=False)


def _state_path() -> Path:
    return ensure_handoff_dir() / STATE_NAME


def _video_history_path() -> Path:
    return ensure_handoff_dir() / VIDEO_HISTORY_NAME


def get_last_imported_id() -> str | None:
    p = _state_path()
    if not p.is_file():
        return None
    try:
        return p.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def set_last_imported_id(handoff_id: str) -> None:
    try:
        _state_path().write_text(str(handoff_id).strip(), encoding="utf-8")
    except OSError:
        pass


def _normalize_path(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip().strip('"').strip("'")
    if not s or s.lower() in ("null", "none", "undefined"):
        return None
    # Resolve may use forward slashes on Windows
    try:
        p = Path(s).expanduser()
        # Prefer resolved absolute form when the file exists
        if p.is_file():
            return str(p.resolve())
        # Keep absolute/normalized string even if offline (diagnostics)
        try:
            return str(p if p.is_absolute() else p.resolve())
        except OSError:
            return str(p)
    except (TypeError, ValueError, OSError):
        return s


def _parse_handoff(data: dict[str, Any], json_path: Path) -> ResolveHandoff | None:
    still = data.get("still_path") or data.get("still") or None
    video = data.get("video_path") or data.get("video") or data.get("clip_path") or None
    still_s = _normalize_path(still)
    video_s = _normalize_path(video)
    clip = str(data.get("clip_name") or data.get("name") or "Resolve clip").strip()
    ts = str(data.get("timestamp") or "")
    hid = str(data.get("id") or data.get("handoff_id") or ts or json_path.stem)
    video_missing = bool(video_s and not Path(video_s).is_file())
    is_proxy = bool(
        data.get("video_is_proxy")
        or data.get("proxy_graded")
        or (video_s and "AI_Media_Studio_Handoff" in str(video_s).replace("\\", "/"))
        or (video_s and "_proxy" in Path(str(video_s)).name.lower())
    )
    return ResolveHandoff(
        still_path=still_s,
        video_path=video_s,
        clip_name=clip or "Resolve clip",
        timestamp=ts,
        handoff_id=hid,
        raw=data,
        json_path=str(json_path),
        video_missing=video_missing,
        video_is_proxy=is_proxy,
        proxy_graded=bool(data.get("proxy_graded") or is_proxy),
    )


def read_handoff_file(path: str | Path) -> ResolveHandoff | None:
    p = Path(path)
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return _parse_handoff(data, p)


def read_latest_handoff() -> ResolveHandoff | None:
    """Read data/resolve_handoff/latest.json if present."""
    ensure_handoff_dir()
    latest = HANDOFF_DIR / LATEST_NAME
    if not latest.is_file():
        candidates = sorted(
            HANDOFF_DIR.glob("handoff_*.json"),
            key=lambda x: x.stat().st_mtime,
            reverse=True,
        )
        if not candidates:
            return None
        return read_handoff_file(candidates[0])
    return read_handoff_file(latest)


def poll_new_handoff(*, mark: bool = False) -> ResolveHandoff | None:
    """
    Return a new handoff that has not been imported yet, or None.

    When ``mark`` is True, records the id as imported (caller usually marks
    after a successful UI apply).
    """
    h = read_latest_handoff()
    if not h or not h.ok:
        return None
    last = get_last_imported_id()
    if last and last == h.handoff_id:
        return None
    if mark:
        set_last_imported_id(h.handoff_id)
    return h


def format_import_status(h: ResolveHandoff) -> str:
    """Clear toast/status line for Resolve imports."""
    name = h.clip_name or "clip"
    proxy_tag = " graded proxy" if (h.video_is_proxy or h.proxy_graded) else ""
    size_note = ""
    if h.has_video and h.video_path:
        try:
            mb = Path(h.video_path).stat().st_size / (1024 * 1024)
            size_note = f" ({mb:.1f} MB)"
        except OSError:
            pass
    if h.has_still and h.has_video:
        return f"Imported still +{proxy_tag} video from Resolve: {name}{size_note}"
    if h.has_still and h.video_missing:
        return (
            f"Imported still from Resolve: {name} "
            f"(video path missing on disk: {Path(h.video_path).name if h.video_path else '?'})"
        )
    if h.has_still and h.video_path and not h.has_video:
        return f"Imported still from Resolve: {name} (video not available)"
    if h.has_still:
        return f"Imported still from Resolve: {name}"
    if h.has_video:
        return f"Imported{proxy_tag} video from Resolve: {name}{size_note}"
    if h.video_missing:
        return (
            f"Resolve handoff for {name}: video file not found "
            f"({h.video_path}). Re-run Send_to_AI_Media_Studio so it exports a graded proxy."
        )
    return f"Resolve handoff for {name}: no media files found."


# ---------------------------------------------------------------------------
# Recently from Resolve (video sources)
# ---------------------------------------------------------------------------


@dataclass
class ResolveVideoEntry:
    path: str
    clip_name: str
    still_path: str | None = None
    handoff_id: str | None = None
    timestamp: str = ""

    def label(self) -> str:
        name = self.clip_name or Path(self.path).name
        return name


def _load_video_history_raw() -> list[dict]:
    p = _video_history_path()
    if not p.is_file():
        return []
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [x for x in raw if isinstance(x, dict)] if isinstance(raw, list) else []


def _save_video_history_raw(entries: list[dict]) -> None:
    try:
        _video_history_path().write_text(
            json.dumps(entries[:VIDEO_HISTORY_MAX], indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass


def load_resolve_video_history() -> list[ResolveVideoEntry]:
    """Newest-first Resolve video sources that still exist on disk."""
    ensure_handoff_dir()
    out: list[ResolveVideoEntry] = []
    kept: list[dict] = []
    for e in _load_video_history_raw():
        path = _normalize_path(e.get("path"))
        if not path or not Path(path).is_file():
            continue
        still = _normalize_path(e.get("still_path"))
        entry = ResolveVideoEntry(
            path=path,
            clip_name=str(e.get("clip_name") or Path(path).name),
            still_path=still if still and Path(still).is_file() else None,
            handoff_id=str(e.get("handoff_id") or "") or None,
            timestamp=str(e.get("timestamp") or ""),
        )
        out.append(entry)
        kept.append(
            {
                "path": entry.path,
                "clip_name": entry.clip_name,
                "still_path": entry.still_path,
                "handoff_id": entry.handoff_id,
                "timestamp": entry.timestamp,
            }
        )
        if len(out) >= VIDEO_HISTORY_MAX:
            break
    if len(kept) != len(_load_video_history_raw()):
        _save_video_history_raw(kept)
    return out


def record_resolve_video(
    *,
    video_path: str | Path | None,
    clip_name: str | None = None,
    still_path: str | Path | None = None,
    handoff_id: str | None = None,
) -> list[ResolveVideoEntry]:
    """Remember a Resolve video import for the Video tab recent list."""
    ensure_handoff_dir()
    path = _normalize_path(video_path)
    if not path or not Path(path).is_file():
        return load_resolve_video_history()
    still = _normalize_path(still_path)
    if still and not Path(still).is_file():
        still = None
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = (clip_name or Path(path).name).strip() or Path(path).name
    entry = {
        "path": path,
        "clip_name": name,
        "still_path": still,
        "handoff_id": handoff_id,
        "timestamp": stamp,
    }
    existing = [
        e
        for e in _load_video_history_raw()
        if _normalize_path(e.get("path")) != path
    ]
    existing.insert(0, entry)
    _save_video_history_raw(existing[:VIDEO_HISTORY_MAX])
    return load_resolve_video_history()


def write_handoff_json(
    *,
    still_path: str | Path | None,
    video_path: str | Path | None,
    clip_name: str,
    dest_dir: str | Path | None = None,
) -> Path:
    """
    Write a handoff payload (used by the Resolve script and tests).

    Returns path to latest.json.
    """
    out = Path(dest_dir) if dest_dir else ensure_handoff_dir()
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    local_ts = datetime.now().isoformat(timespec="seconds")
    hid = f"handoff_{stamp}"

    def _stable(src: str | Path | None, kind: str, ext: str) -> str | None:
        if not src:
            return None
        p = Path(src)
        if not p.is_file():
            return None
        try:
            if p.resolve().parent == out.resolve():
                return str(p.resolve())
        except OSError:
            pass
        dest = out / f"{hid}_{kind}{ext}"
        try:
            shutil.copy2(p, dest)
            return str(dest.resolve())
        except OSError:
            return str(p.resolve())

    still_s = None
    if still_path:
        sp = Path(still_path)
        still_s = _stable(sp, "still", sp.suffix.lower() or ".png")
    video_s = None
    if video_path:
        vp = Path(video_path)
        # Keep absolute path (no large copy)
        if vp.is_file():
            video_s = str(vp.resolve())
        else:
            video_s = str(vp)

    payload = {
        "id": hid,
        "timestamp": local_ts,
        "clip_name": clip_name or "Resolve clip",
        "still_path": still_s,
        "video_path": video_s,
        "source": "davinci_resolve",
    }
    latest = out / LATEST_NAME
    archive = out / f"{hid}.json"
    text = json.dumps(payload, indent=2)
    archive.write_text(text, encoding="utf-8")
    latest.write_text(text, encoding="utf-8")
    return latest


def wait_for_file(path: str | Path, *, timeout_s: float = 8.0) -> bool:
    """Wait briefly for Resolve export flush."""
    p = Path(path)
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if p.is_file() and p.stat().st_size > 0:
            return True
        time.sleep(0.15)
    return p.is_file() and p.stat().st_size > 0
