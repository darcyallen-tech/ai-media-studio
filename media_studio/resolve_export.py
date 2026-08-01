"""
DaVinci Resolve Studio — Send to Resolve (Tier A: smarter send).

When Resolve Studio is open with a project:
  1. Import into Media Pool bin: AI Media Studio / <Job name or today’s date>
  2. Optionally place on video track (default V2) at playhead when API allows
  3. Optional timeline/clip marker (model, scenario, cost when known)

Soft fail: scripting unavailable, bin fails, or Resolve closed → reveal the
file in the OS folder; never crash the app or Resolve.

Does not: render-in-place, compounds, auto transitions, or grade baking.

Requires:
  - Resolve Studio open with a project loaded
  - Preferences → System → General → External scripting = Local
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any


@dataclass
class ResolveSendResult:
    ok: bool
    message: str
    bin_name: str | None = None
    clips: int = 0
    placed_on_timeline: bool = False
    marker_added: bool = False
    fallback_folder: bool = False
    notes: list[str] = field(default_factory=list)


def _ensure_resolve_module_path() -> None:
    """Add Blackmagic Scripting Modules to sys.path on Windows/macOS/Linux."""
    candidates: list[Path] = []

    env_api = os.environ.get("RESOLVE_SCRIPT_API") or os.environ.get(
        "RESOLVE_SCRIPT_API_PATH"
    )
    if env_api:
        candidates.append(Path(env_api) / "Modules")

    if sys.platform.startswith("win"):
        program_data = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
        candidates.append(
            Path(program_data)
            / "Blackmagic Design"
            / "DaVinci Resolve"
            / "Support"
            / "Developer"
            / "Scripting"
            / "Modules"
        )
        for base in (
            r"C:\Program Files\Blackmagic Design\DaVinci Resolve",
            r"C:\Program Files\Blackmagic Design\DaVinci Resolve Studio",
        ):
            candidates.append(Path(base) / "Developer" / "Scripting" / "Modules")
        lib = os.environ.get("RESOLVE_SCRIPT_LIB")
        if not lib:
            for dll in (
                r"C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll",
                r"C:\Program Files\Blackmagic Design\DaVinci Resolve Studio\fusionscript.dll",
            ):
                if Path(dll).is_file():
                    os.environ.setdefault("RESOLVE_SCRIPT_LIB", dll)
                    break
    elif sys.platform == "darwin":
        candidates.append(
            Path(
                "/Library/Application Support/Blackmagic Design/DaVinci Resolve/"
                "Developer/Scripting/Modules"
            )
        )
    else:
        candidates.append(Path("/opt/resolve/Developer/Scripting/Modules"))
        candidates.append(
            Path.home() / "resolve" / "Developer" / "Scripting" / "Modules"
        )

    for mod in candidates:
        if mod.is_dir():
            s = str(mod.resolve())
            if s not in sys.path:
                sys.path.insert(0, s)


def _connect_resolve() -> tuple[Any | None, str | None]:
    """Return (resolve_app, error_message)."""
    _ensure_resolve_module_path()
    try:
        import DaVinciResolveScript as dvr  # type: ignore
    except ImportError as exc:
        return None, (
            "DaVinciResolveScript not found. Install Resolve Studio, enable "
            "External scripting = Local, and ensure Scripting Modules are on the path. "
            f"({exc})"
        )
    except Exception as exc:
        return None, f"Failed to load DaVinciResolveScript: {exc}"

    try:
        resolve = dvr.scriptapp("Resolve")
    except Exception as exc:
        return None, (
            f"Could not connect to Resolve ({exc}). "
            "Is DaVinci Resolve Studio open with a project loaded? "
            "Preferences → System → General → External scripting must be Local."
        )

    if resolve is None:
        return None, (
            "Resolve is not running or scripting is disabled. "
            "Open Resolve Studio, load a project, set External scripting = Local, then try again."
        )
    return resolve, None


def _safe_bin_segment(name: str, *, max_len: int = 64) -> str:
    """Sanitize a single Media Pool folder name segment."""
    raw = (name or "").strip()
    if not raw:
        return date.today().isoformat()
    # Resolve is picky about some characters; keep it human-readable
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", raw)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    if not cleaned:
        cleaned = date.today().isoformat()
    return cleaned[:max_len]


def default_bin_leaf(*, job_name: str | None = None) -> str:
    """Leaf folder under AI Media Studio: job label or today’s date."""
    job = (job_name or "").strip()
    if not job:
        try:
            from media_studio.job_context import current_job_name

            job = current_job_name()
        except Exception:
            job = ""
    if not job:
        try:
            from media_studio.ui_prefs import get_job_name

            job = get_job_name()
        except Exception:
            job = ""
    if job:
        return _safe_bin_segment(job)
    return date.today().isoformat()


def default_bin_name(*, dated: bool = True, job_name: str | None = None) -> str:
    """Display path: AI Media Studio / <job or date>."""
    leaf = default_bin_leaf(job_name=job_name) if (dated or job_name) else "Inbox"
    return f"AI Media Studio / {leaf}"


def _find_or_create_bin(media_pool: Any, parent_folder: Any, bin_name: str) -> Any:
    """Find a subfolder of parent by name, or create it. Soft-fails to parent."""
    try:
        subs = parent_folder.GetSubFolderList() or []
    except Exception:
        subs = []
    for sub in subs:
        try:
            name = sub.GetName()
        except Exception:
            name = None
        if name == bin_name:
            return sub

    create = getattr(media_pool, "AddSubFolder", None)
    if callable(create):
        try:
            folder = create(parent_folder, bin_name)
            if folder:
                return folder
        except Exception:
            pass
    create2 = getattr(parent_folder, "AddSubFolder", None)
    if callable(create2):
        try:
            folder = create2(bin_name)
            if folder:
                return folder
        except Exception:
            pass
    return parent_folder


def _find_or_create_nested(
    media_pool: Any, root_folder: Any, segments: list[str]
) -> Any:
    folder = root_folder
    for seg in segments:
        if not seg:
            continue
        folder = _find_or_create_bin(media_pool, folder, seg)
    return folder


def _timeline_fps(timeline: Any) -> float:
    try:
        raw = timeline.GetSetting("timelineFrameRate")
        fps = float(raw)
        if fps > 1.0:
            return fps
    except Exception:
        pass
    return 24.0


def _timecode_to_frame(tc: str | None, fps: float) -> int | None:
    """Parse Resolve timecode (HH:MM:SS:FF or ; drop-frame) → frame index."""
    if not tc:
        return None
    s = str(tc).strip().replace(";", ":")
    parts = s.split(":")
    if len(parts) != 4:
        return None
    try:
        h, m, sec, fr = (int(p) for p in parts)
    except ValueError:
        return None
    return int(round((h * 3600 + m * 60 + sec) * float(fps) + fr))


def _playhead_frame(timeline: Any) -> int | None:
    """Best-effort current timeline frame for recordFrame / markers."""
    fps = _timeline_fps(timeline)
    # Prefer GetCurrentTimecode
    try:
        tc = timeline.GetCurrentTimecode()
        fr = _timecode_to_frame(tc, fps)
        if fr is not None:
            return max(0, fr)
    except Exception:
        pass
    # Some builds expose GetCurrentFrame or similar — probe gently
    for meth in ("GetCurrentVideoItem",):
        try:
            fn = getattr(timeline, meth, None)
            if callable(fn):
                item = fn()
                if item is not None:
                    # Cannot reliably get frame from item alone
                    pass
        except Exception:
            pass
    return None


def _resolve_track_index() -> int:
    """Video track for optional place (1-based). Default 2 (V2)."""
    try:
        from media_studio.ui_prefs import get_resolve_video_track

        return get_resolve_video_track()
    except Exception:
        return 2


def _want_place_on_timeline() -> bool:
    try:
        from media_studio.ui_prefs import get_resolve_place_on_timeline

        return get_resolve_place_on_timeline()
    except Exception:
        return True


def _want_marker() -> bool:
    try:
        from media_studio.ui_prefs import get_resolve_add_marker

        return get_resolve_add_marker()
    except Exception:
        return True


def _first_clip(clips: Any) -> Any | None:
    if clips is None:
        return None
    if isinstance(clips, (list, tuple)):
        return clips[0] if clips else None
    # Some APIs return a single item
    return clips


def _append_at_playhead(
    media_pool: Any,
    timeline: Any,
    clip: Any,
    *,
    track_index: int,
) -> bool:
    """
    Place clip on video track at playhead when API supports dict form.
    Falls back to plain AppendToTimeline([clip]) (end of timeline).
    """
    record = _playhead_frame(timeline)
    # Dict form (Resolve 17+ / Studio)
    try:
        info: dict[str, Any] = {
            "mediaPoolItem": clip,
            "trackIndex": max(1, int(track_index)),
            "mediaType": 1,  # video
        }
        if record is not None:
            info["recordFrame"] = int(record)
        result = media_pool.AppendToTimeline([info])
        if result:
            return True
    except Exception:
        pass
    # Simple append (end)
    try:
        result = media_pool.AppendToTimeline([clip])
        return bool(result)
    except Exception:
        return False


def _build_marker_note(
    *,
    model: str | None = None,
    scenario: str | None = None,
    cost: str | None = None,
    extra: str | None = None,
) -> str:
    bits: list[str] = []
    if model:
        bits.append(str(model).strip())
    if scenario:
        bits.append(str(scenario).strip())
    if cost:
        bits.append(str(cost).strip())
    if extra:
        bits.append(str(extra).strip())
    note = " · ".join(b for b in bits if b)
    return note[:240] if note else "From AI Media Studio"


def _add_markers(
    timeline: Any | None,
    clip: Any | None,
    *,
    note: str,
    record_frame: int | None,
) -> bool:
    """Add timeline marker at playhead and/or clip marker at start. Soft fail."""
    added = False
    name = "AI Media Studio"
    color = "Blue"
    duration = 1

    if timeline is not None:
        try:
            fr = record_frame if record_frame is not None else _playhead_frame(timeline)
            if fr is None:
                fr = 0
            ok = timeline.AddMarker(int(fr), color, name, note, duration, "")
            if ok:
                added = True
        except Exception:
            pass

    if clip is not None:
        try:
            ok = clip.AddMarker(0, color, name, note, duration, "")
            if ok:
                added = True
        except Exception:
            pass
    return added


def _lookup_history_meta(
    path: str, *, output_dir: str | Path | None = None
) -> dict[str, str]:
    """Best-effort model / scenario / cost / job from history for this file."""
    out: dict[str, str] = {}
    try:
        from media_studio.history import load_history

        target = str(Path(path).resolve())
    except Exception:
        return out
    try:
        for e in load_history(output_dir):
            for f in e.files or []:
                try:
                    if str(Path(f).resolve()) == target:
                        if e.model:
                            out["model"] = e.model
                        if e.scenario:
                            out["scenario"] = e.scenario
                        if e.cost_estimate:
                            out["cost"] = e.cost_estimate
                        if e.job:
                            out["job"] = e.job
                        return out
                except OSError:
                    continue
    except Exception:
        pass
    return out


def _soft_open_folder(path: Path) -> str:
    """Reveal file; never raise."""
    try:
        from media_studio.folder_util import show_in_folder

        return show_in_folder(str(path))
    except Exception as exc:
        return f"File location: {path.parent} ({exc})"


def send_file_to_resolve(
    path: str | Path | None,
    *,
    bin_name: str | None = None,
    job_name: str | None = None,
    model: str | None = None,
    scenario: str | None = None,
    cost: str | None = None,
    place_on_timeline: bool | None = None,
    add_marker: bool | None = None,
    video_track: int | None = None,
    output_dir: str | Path | None = None,
) -> ResolveSendResult:
    """
    Tier A smarter send: Media Pool bin + optional timeline place + marker.

    Soft-fails to folder reveal when Resolve/scripting is unavailable.
    """
    if not path or not str(path).strip():
        return ResolveSendResult(ok=False, message="No file path to send.")
    file_path = Path(path).expanduser()
    try:
        file_path = file_path.resolve()
    except OSError as exc:
        return ResolveSendResult(ok=False, message=f"Invalid path: {exc}")
    if not file_path.is_file():
        return ResolveSendResult(ok=False, message=f"File not found: {file_path}")

    abs_path = str(file_path)

    # Enrich meta from history when callers omit it
    hist = _lookup_history_meta(abs_path, output_dir=output_dir)
    job = (job_name or hist.get("job") or "").strip() or None
    model = (model or hist.get("model") or "").strip() or None
    scenario = (scenario or hist.get("scenario") or "").strip() or None
    cost = (cost or hist.get("cost") or "").strip() or None

    resolve, err = _connect_resolve()
    if err or resolve is None:
        folder_msg = _soft_open_folder(file_path)
        return ResolveSendResult(
            ok=False,
            message=(
                f"{err or 'Could not connect to Resolve.'} "
                f"File kept on disk — {folder_msg}"
            ),
            fallback_folder=True,
        )

    notes: list[str] = []
    try:
        pm = resolve.GetProjectManager()
        if pm is None:
            folder_msg = _soft_open_folder(file_path)
            return ResolveSendResult(
                ok=False,
                message=f"No Project Manager — is Resolve fully started? {folder_msg}",
                fallback_folder=True,
            )
        project = pm.GetCurrentProject()
        if project is None:
            folder_msg = _soft_open_folder(file_path)
            return ResolveSendResult(
                ok=False,
                message=(
                    "No project is open in Resolve. Open or create a project, then try again. "
                    f"{folder_msg}"
                ),
                fallback_folder=True,
            )
        media_pool = project.GetMediaPool()
        if media_pool is None:
            folder_msg = _soft_open_folder(file_path)
            return ResolveSendResult(
                ok=False,
                message=f"Could not access the Media Pool. {folder_msg}",
                fallback_folder=True,
            )

        root = media_pool.GetRootFolder()
        if root is None:
            folder_msg = _soft_open_folder(file_path)
            return ResolveSendResult(
                ok=False,
                message=f"Media Pool root folder unavailable. {folder_msg}",
                fallback_folder=True,
            )

        # Nested bin: AI Media Studio / <Job or date>
        if bin_name and "/" not in bin_name and "\\" not in bin_name:
            segments = ["AI Media Studio", _safe_bin_segment(bin_name)]
            display_bin = f"AI Media Studio / {segments[1]}"
        elif bin_name and ("/" in bin_name or "\\" in bin_name):
            parts = re.split(r"[/\\]", bin_name)
            segments = [_safe_bin_segment(p) for p in parts if p.strip()]
            if not segments:
                segments = ["AI Media Studio", default_bin_leaf(job_name=job)]
            display_bin = " / ".join(segments)
        else:
            leaf = default_bin_leaf(job_name=job)
            segments = ["AI Media Studio", leaf]
            display_bin = f"AI Media Studio / {leaf}"

        folder = _find_or_create_nested(media_pool, root, segments)
        try:
            media_pool.SetCurrentFolder(folder)
        except Exception:
            pass

        clips = None
        try:
            clips = media_pool.ImportMedia([abs_path])
        except Exception as exc:
            folder_msg = _soft_open_folder(file_path)
            return ResolveSendResult(
                ok=False,
                message=f"Import failed ({exc}). {folder_msg}",
                bin_name=display_bin,
                fallback_folder=True,
            )

        if not clips:
            folder_msg = _soft_open_folder(file_path)
            return ResolveSendResult(
                ok=False,
                message=(
                    f"Import returned no clips for {file_path.name}. "
                    f"Check format/path. {folder_msg}"
                ),
                bin_name=display_bin,
                fallback_folder=True,
            )

        n = len(clips) if isinstance(clips, (list, tuple)) else 1
        clip = _first_clip(clips)
        placed = False
        marker_ok = False
        record_fr: int | None = None

        do_place = (
            _want_place_on_timeline()
            if place_on_timeline is None
            else bool(place_on_timeline)
        )
        do_marker = _want_marker() if add_marker is None else bool(add_marker)
        track = (
            max(1, int(video_track))
            if video_track is not None
            else _resolve_track_index()
        )

        timeline = None
        try:
            timeline = project.GetCurrentTimeline()
        except Exception:
            timeline = None

        if do_place and timeline is not None and clip is not None:
            try:
                record_fr = _playhead_frame(timeline)
                placed = _append_at_playhead(
                    media_pool, timeline, clip, track_index=track
                )
                if placed:
                    notes.append(
                        f"timeline V{track}"
                        + (f" @ frame {record_fr}" if record_fr is not None else "")
                    )
                else:
                    notes.append("timeline place skipped")
            except Exception as exc:
                notes.append(f"timeline place soft-fail ({type(exc).__name__})")
        elif do_place and timeline is None:
            notes.append("no active timeline — Media Pool only")

        if do_marker:
            marker_note = _build_marker_note(
                model=model, scenario=scenario, cost=cost
            )
            try:
                marker_ok = _add_markers(
                    timeline,
                    clip,
                    note=marker_note,
                    record_frame=record_fr,
                )
                if marker_ok:
                    notes.append(f"marker: {marker_note}")
            except Exception as exc:
                notes.append(f"marker soft-fail ({type(exc).__name__})")

        msg = f"Sent “{file_path.name}” to Resolve Media Pool → {display_bin}"
        if notes:
            msg += " · " + "; ".join(notes[:4])

        return ResolveSendResult(
            ok=True,
            message=msg,
            bin_name=display_bin,
            clips=int(n),
            placed_on_timeline=placed,
            marker_added=marker_ok,
            notes=notes,
        )
    except Exception as exc:
        # Never crash app or Resolve
        folder_msg = _soft_open_folder(file_path)
        return ResolveSendResult(
            ok=False,
            message=(
                f"Resolve scripting error: {exc}. "
                "Confirm Studio is open, a project is loaded, and External scripting = Local. "
                f"{folder_msg}"
            ),
            fallback_folder=True,
        )


def resolve_icon_path() -> str | None:
    """Path to bundled Resolve-style icon, if present."""
    p = Path(__file__).resolve().parent / "assets" / "resolve_icon.png"
    if p.is_file():
        return str(p)
    return None
