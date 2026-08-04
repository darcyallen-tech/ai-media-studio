"""
Disk safety: prune app-owned caches and apply retention under outputs/ + handoff.

Never deletes outside the configured output root or data/resolve_handoff/.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from media_studio.config import OUTPUT_DIR, PROJECT_ROOT, ensure_output_dir

# Cache subdirs under the active output root (not user project files elsewhere).
# Matches Phase E allow-list — never wipe dated generation folders.
CACHE_SUBDIRS = (
    "_aleph_keyframes",
    "_aleph_proxies",
    "_region",
    "_fal_upload",
    "_previews",
)

# Max age for filmstrip/proxy side-files when retention is "Never" (still bound growth)
DEFAULT_CACHE_MAX_AGE_DAYS = 30
DEFAULT_FILMSTRIP_MAX_FILES = 400
DEFAULT_PROXY_MAX_FILES = 40

HANDOFF_DIR = PROJECT_ROOT / "data" / "resolve_handoff"


@dataclass
class PruneStats:
    deleted: int = 0
    bytes_freed: int = 0
    errors: int = 0
    details: list[str] = field(default_factory=list)

    def merge(self, other: "PruneStats") -> None:
        self.deleted += other.deleted
        self.bytes_freed += other.bytes_freed
        self.errors += other.errors
        self.details.extend(other.details)

    def summary(self) -> str:
        mb = self.bytes_freed / (1024 * 1024)
        return f"Removed {self.deleted} file(s), ~{mb:.1f} MB" + (
            f", {self.errors} error(s)" if self.errors else ""
        )


def _safe_under(root: Path, path: Path) -> bool:
    """True if path resolves inside root (no escape)."""
    try:
        root_r = root.resolve()
        path_r = path.resolve()
        return root_r == path_r or root_r in path_r.parents
    except OSError:
        return False


def _unlink(path: Path, root: Path, stats: PruneStats) -> None:
    if not _safe_under(root, path):
        stats.errors += 1
        stats.details.append(f"skip outside root: {path}")
        return
    try:
        size = path.stat().st_size if path.is_file() else 0
        if path.is_file():
            path.unlink(missing_ok=True)
            stats.deleted += 1
            stats.bytes_freed += size
        elif path.is_dir():
            # only empty dirs
            try:
                path.rmdir()
            except OSError:
                pass
    except OSError as exc:
        stats.errors += 1
        stats.details.append(f"{path.name}: {exc}")


def _iter_files(folder: Path) -> Iterable[Path]:
    if not folder.is_dir():
        return
    try:
        for p in folder.rglob("*"):
            if p.is_file():
                yield p
    except OSError:
        return


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def prune_dir_by_age(
    folder: Path,
    *,
    root: Path,
    max_age_days: float,
    stats: PruneStats | None = None,
) -> PruneStats:
    """Delete files under folder older than max_age_days (must stay under root)."""
    out = stats or PruneStats()
    if not folder.is_dir() or not _safe_under(root, folder):
        return out
    cutoff = time.time() - max(0.1, float(max_age_days)) * 86400.0
    for f in list(_iter_files(folder)):
        if not _safe_under(root, f):
            continue
        if f.name in (".gitkeep", ".keep"):
            continue
        if _mtime(f) < cutoff:
            _unlink(f, root, out)
    return out


def prune_dir_lru(
    folder: Path,
    *,
    root: Path,
    max_files: int,
    stats: PruneStats | None = None,
) -> PruneStats:
    """Keep newest max_files under folder; delete oldest."""
    out = stats or PruneStats()
    if not folder.is_dir() or not _safe_under(root, folder):
        return out
    files = [f for f in _iter_files(folder) if f.name not in (".gitkeep", ".keep")]
    files = [f for f in files if _safe_under(root, f)]
    if len(files) <= max(1, int(max_files)):
        return out
    files.sort(key=_mtime, reverse=True)
    for f in files[max(1, int(max_files)) :]:
        _unlink(f, root, out)
    return out


def clear_app_caches(output_dir: str | Path | None = None) -> PruneStats:
    """
    Wipe known cache subdirs under the output root (not dated generation folders).
    Also purges resolve handoff media (keeps latest.json / state files).
    """
    stats = PruneStats()
    root = ensure_output_dir(Path(output_dir) if output_dir else OUTPUT_DIR).resolve()
    for name in CACHE_SUBDIRS:
        folder = root / name
        if not folder.is_dir():
            continue
        for f in list(_iter_files(folder)):
            if f.name in (".gitkeep", ".keep"):
                continue
            _unlink(f, root, stats)
        stats.details.append(f"cleared {name}/")

    # Handoff — only under data/resolve_handoff
    try:
        hstats = _wipe_handoff_artifacts()
        stats.merge(hstats)
        stats.details.append("cleared resolve_handoff artifacts")
    except Exception as exc:
        stats.errors += 1
        stats.details.append(f"handoff: {exc}")

    return stats


def _wipe_handoff_artifacts() -> PruneStats:
    """Delete handoff_*.json / stills under data/resolve_handoff only."""
    stats = PruneStats()
    root = HANDOFF_DIR
    if not root.is_dir():
        return stats
    try:
        root_r = root.resolve()
    except OSError:
        return stats
    keep = {"latest.json", ".last_imported_id", "video_history.json", ".gitkeep"}
    try:
        for p in root.iterdir():
            if not p.is_file():
                continue
            if p.name in keep:
                continue
            if not _safe_under(root_r, p):
                continue
            _unlink(p, root_r, stats)
    except OSError as exc:
        stats.errors += 1
        stats.details.append(str(exc))
    return stats


def apply_retention(
    output_dir: str | Path | None = None,
    *,
    retention_days: int | None,
) -> PruneStats:
    """
    Age-based retention under output root + handoff.

    ``retention_days`` None = never delete generation media (still bounds cache dirs
    with DEFAULT_CACHE_MAX_AGE_DAYS / LRU caps).
    """
    stats = PruneStats()
    root = ensure_output_dir(Path(output_dir) if output_dir else OUTPUT_DIR).resolve()

    # Always bound cache growth
    cache_age = float(retention_days) if retention_days else float(DEFAULT_CACHE_MAX_AGE_DAYS)
    for name in CACHE_SUBDIRS:
        folder = root / name
        prune_dir_by_age(folder, root=root, max_age_days=cache_age, stats=stats)
        # Extra LRU on filmstrip/proxy
        if name == "_aleph_keyframes":
            prune_dir_lru(
                folder / "filmstrip",
                root=root,
                max_files=DEFAULT_FILMSTRIP_MAX_FILES,
                stats=stats,
            )
            prune_dir_lru(
                folder,
                root=root,
                max_files=DEFAULT_FILMSTRIP_MAX_FILES + 200,
                stats=stats,
            )
        if name == "_aleph_proxies":
            prune_dir_lru(
                folder,
                root=root,
                max_files=DEFAULT_PROXY_MAX_FILES,
                stats=stats,
            )

    # Orphan job_*.json at output root older than retention (or 90d if never)
    job_age = float(retention_days) if retention_days else 90.0
    job_cutoff = time.time() - job_age * 86400.0
    try:
        for p in root.glob("job_*.json"):
            if p.is_file() and _mtime(p) < job_cutoff and _safe_under(root, p):
                _unlink(p, root, stats)
    except OSError:
        stats.errors += 1

    # Dated generation folders: prune files older than retention when set
    if retention_days and retention_days > 0:
        cutoff = time.time() - float(retention_days) * 86400.0
        try:
            for day_dir in root.iterdir():
                if not day_dir.is_dir():
                    continue
                # YYYY-MM-DD or loose dated names
                name = day_dir.name
                if len(name) >= 10 and name[4] == "-" and name[7] == "-":
                    for f in list(_iter_files(day_dir)):
                        if f.name in (".gitkeep", ".keep"):
                            continue
                        if _mtime(f) < cutoff and _safe_under(root, f):
                            _unlink(f, root, stats)
        except OSError:
            stats.errors += 1

        # History: drop entries with all files missing or all older than retention
        try:
            from media_studio.history import load_history, save_history

            entries = load_history(root)
            kept = []
            for e in entries:
                files_ok = []
                for fp in e.files:
                    try:
                        p = Path(fp)
                        if p.is_file():
                            if _mtime(p) >= cutoff or not _safe_under(root, p):
                                # keep entry if any file is new or outside (don't track outside delete)
                                files_ok.append(fp)
                            # old files under root already deleted above; drop from entry
                    except OSError:
                        pass
                if files_ok:
                    e.files = files_ok
                    kept.append(e)
                # else drop entry (all media gone)
            if len(kept) != len(entries):
                save_history(kept, root)
                stats.details.append(
                    f"history: {len(entries) - len(kept)} entry(ies) pruned"
                )
        except Exception as exc:
            stats.errors += 1
            stats.details.append(f"history: {exc}")

    # Handoff retention (always age-bound; use retention or 7 days)
    try:
        from media_studio.resolve_import import (
            HANDOFF_MAX_AGE_DAYS,
            HANDOFF_MAX_FILES,
            purge_handoff_cache,
        )

        days = int(retention_days) if retention_days else HANDOFF_MAX_AGE_DAYS
        h = purge_handoff_cache(
            max_age_days=max(1, days),
            max_files=HANDOFF_MAX_FILES,
            force=True,
        )
        stats.deleted += int(h.get("deleted") or 0)
        stats.details.append(f"handoff: deleted {h.get('deleted', 0)}")
    except Exception as exc:
        stats.errors += 1

    # Characters store: age-prune unlocked only (locked skip)
    if retention_days and retention_days > 0:
        try:
            from media_studio.character_store import prune_unlocked_characters

            cs = prune_unlocked_characters(retention_days=int(retention_days))
            stats.deleted += int(cs.get("deleted_files") or 0)
            if cs.get("deleted_chars") or cs.get("skipped_locked"):
                stats.details.append(
                    "characters: removed "
                    f"{cs.get('deleted_chars', 0)} unlocked · "
                    f"skipped locked {cs.get('skipped_locked', 0)}"
                )
        except Exception as exc:
            stats.errors += 1
            stats.details.append(f"characters: {exc}")
        stats.details.append(f"handoff: {exc}")

    return stats


def prune_aleph_side_files(output_dir: str | Path | None = None) -> PruneStats:
    """Lightweight bound on filmstrip/proxy growth (call after sampling)."""
    stats = PruneStats()
    root = ensure_output_dir(Path(output_dir) if output_dir else OUTPUT_DIR).resolve()
    kf = root / "_aleph_keyframes"
    prune_dir_by_age(
        kf / "filmstrip",
        root=root,
        max_age_days=DEFAULT_CACHE_MAX_AGE_DAYS,
        stats=stats,
    )
    prune_dir_lru(
        kf / "filmstrip",
        root=root,
        max_files=DEFAULT_FILMSTRIP_MAX_FILES,
        stats=stats,
    )
    prune_dir_lru(
        root / "_aleph_proxies",
        root=root,
        max_files=DEFAULT_PROXY_MAX_FILES,
        stats=stats,
    )
    return stats
