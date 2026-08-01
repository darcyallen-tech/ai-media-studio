#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Send selected / current timeline clip → AI Media Studio handoff.

Does NOT render. You must Render in Place (or Deliver) first so the clip’s
media path is already a graded, practical-size file.

Install (Windows)
-----------------
1. Copy this file to Resolve's Utility scripts folder, e.g.:

   %APPDATA%\\Blackmagic Design\\DaVinci Resolve\\Support\\Fusion\\Scripts\\Utility\\

2. Preferences → System → General → External scripting = Local

3. Studio root is auto-detected (no personal path in this file). See
   resolve_studio_root() / README. Optional: set AI_MEDIA_STUDIO_ROOT, or put
   the project path in a one-line studio_root.txt next to this script.

4. In Resolve: Workspace → Scripts → Send_to_AI_Media_Studio

Workflow
--------
1. Grade the clip.
2. Render in Place (or replace with a Deliver export) so media includes grade.
3. Park playhead on that clip.
4. Run this script → still + video path written for AI Media Studio.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path

HANDOFF_SUBDIR = Path("data") / "resolve_handoff"
LAUNCH_BAT = "Start AI Media Studio.bat"
LAUNCH_ON_SEND = True

# Warn (do not hard-fail) when selected media looks like a camera master
MASTER_WARN_BYTES = 150 * 1024 * 1024  # 150 MB


def _looks_like_studio_root(p: Path) -> bool:
    """True if path is an AI Media Studio project root (has app.py)."""
    try:
        return p.is_dir() and (p / "app.py").is_file()
    except OSError:
        return False


def _read_root_file(path: Path) -> Path | None:
    """Read a one-line path file; return Path if it points at Studio root."""
    try:
        if not path.is_file():
            return None
        text = path.read_text(encoding="utf-8", errors="replace").strip()
        if not text:
            return None
        line = text.splitlines()[0].strip().strip('"').strip("'")
        if not line or line.startswith("#"):
            return None
        cand = Path(line).expanduser()
        if _looks_like_studio_root(cand):
            return cand.resolve()
    except OSError:
        return None
    return None


def _appdata_studio_root_file() -> Path:
    """
    Same marker the desktop app writes on launch
    (%LOCALAPPDATA%/AI Media Studio/studio_root.txt).
    """
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or str(
            Path.home() / "AppData" / "Local"
        )
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(
            Path.home() / ".config"
        )
    return Path(base) / "AI Media Studio" / "studio_root.txt"


def resolve_studio_root() -> Path:
    """
    Locate the AI Media Studio project folder without any hardcoded user path.

    Order:
      1. Environment variable AI_MEDIA_STUDIO_ROOT
      2. studio_root.txt next to this script (for Utility-folder copies)
      3. %LOCALAPPDATA%/AI Media Studio/studio_root.txt (written when the app runs)
      4. Parent of resolve_scripts/ when this file still lives in a git clone
    """
    # 1) Explicit env
    env = (os.environ.get("AI_MEDIA_STUDIO_ROOT") or "").strip()
    if env:
        cand = Path(env).expanduser()
        if _looks_like_studio_root(cand):
            return cand.resolve()
        raise RuntimeError(
            f"AI_MEDIA_STUDIO_ROOT is set but is not a valid Studio root:\n{cand}\n\n"
            "It must be a folder that contains app.py."
        )

    # 2) Sidecar next to this script (works after copy into Resolve Utility/)
    script_dir = Path(__file__).resolve().parent
    for name in ("studio_root.txt", "AI_MEDIA_STUDIO_ROOT.txt"):
        hit = _read_root_file(script_dir / name)
        if hit is not None:
            return hit

    # 3) App-data marker written by AI Media Studio on launch
    hit = _read_root_file(_appdata_studio_root_file())
    if hit is not None:
        return hit

    # 4) Dev / un-copied: this file still under <project>/resolve_scripts/
    if script_dir.name.lower() == "resolve_scripts":
        parent = script_dir.parent
        if _looks_like_studio_root(parent):
            return parent.resolve()

    raise RuntimeError(
        "Could not find the AI Media Studio project folder.\n\n"
        "Do one of the following (no code edit required):\n"
        "  • Open AI Media Studio once (it registers this machine’s path), then re-run.\n"
        "  • Set environment variable AI_MEDIA_STUDIO_ROOT to the folder that contains app.py.\n"
        "  • Create studio_root.txt next to this script with a single line: the full path\n"
        "    to the AI Media Studio folder (the one that contains app.py).\n"
    )


def _msg(title: str, text: str, error: bool = False) -> None:
    """Show a Windows message box when possible; always print. Never raises."""
    try:
        print(f"[{title}] {text}")
    except Exception:
        pass
    if sys.platform.startswith("win"):
        try:
            import ctypes

            flags = 0x10 if error else 0x40
            ctypes.windll.user32.MessageBoxW(0, str(text)[:2000], str(title)[:120], flags)
        except Exception:
            pass


def _safe_name(name: str, max_len: int = 48) -> str:
    s = "".join(c if c.isalnum() or c in "-_" else "_" for c in (name or "clip"))
    s = re.sub(r"_+", "_", s).strip("_")
    return (s or "clip")[:max_len]


def _format_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    if n < 1024 * 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MB"
    return f"{n / (1024 * 1024 * 1024):.2f} GB"


def _get_resolve():
    try:
        import DaVinciResolveScript as bmd  # type: ignore
    except ImportError:
        if sys.platform.startswith("win"):
            base = Path(os.environ.get("PROGRAMDATA", r"C:\\ProgramData"))
            mod = (
                base
                / "Blackmagic Design"
                / "DaVinci Resolve"
                / "Support"
                / "Developer"
                / "Scripting"
                / "Modules"
                / "DaVinciResolveScript.py"
            )
        else:
            mod = Path(
                "/opt/resolve/Developer/Scripting/Modules/DaVinciResolveScript.py"
            )
        if not mod.is_file():
            raise RuntimeError(
                "DaVinciResolveScript not found. Run this from Resolve "
                "(Workspace → Scripts) with External scripting = Local."
            )
        import importlib.util

        spec = importlib.util.spec_from_file_location("DaVinciResolveScript", mod)
        if not spec or not spec.loader:
            raise RuntimeError("Could not load DaVinciResolveScript module.")
        mod_obj = importlib.util.module_from_spec(spec)
        sys.modules["DaVinciResolveScript"] = mod_obj
        spec.loader.exec_module(mod_obj)
        import DaVinciResolveScript as bmd  # type: ignore

    resolve = bmd.scriptapp("Resolve")
    if resolve is None:
        raise RuntimeError(
            "Could not connect to Resolve. Is Resolve Studio open with a "
            "project loaded? External scripting must be Local."
        )
    return resolve


def _as_existing_file(val) -> str | None:
    if val is None:
        return None
    s = str(val).strip().strip('"').strip("'")
    if not s or s.lower() in ("null", "none", ""):
        return None
    for candidate in (s, s.replace("/", "\\")):
        try:
            p = Path(candidate)
            if p.is_file() and p.stat().st_size > 0:
                return str(p.resolve())
        except OSError:
            continue
    return None


def _clip_file_path(media_pool_item) -> str | None:
    """
    Current media file path for a MediaPoolItem.

    After Render in Place / relink, this is the rendered (graded) file —
    not necessarily the original camera master.
    """
    if media_pool_item is None:
        return None

    # Prefer paths that often reflect the *active* media after RIP
    preferred_keys = (
        "File Path",
        "File path",
        "Clip File Path",
        "Path",
        "Replacement Path",
        "Good Take File Path",
        "Proxy Media Path",
        "Proxy path",
    )

    candidates: list[str] = []
    try:
        props = media_pool_item.GetClipProperty()
    except Exception:
        props = None

    if isinstance(props, dict):
        for key in preferred_keys:
            val = props.get(key)
            if val:
                candidates.append(str(val))
        for k, v in props.items():
            if v is None:
                continue
            kl = str(k).lower()
            if "path" in kl or "file" in kl:
                candidates.append(str(v))

    for key in preferred_keys:
        try:
            val = media_pool_item.GetClipProperty(key)
            if val:
                candidates.append(str(val))
        except Exception:
            pass

    seen: set[str] = set()
    for c in candidates:
        if c in seen:
            continue
        seen.add(c)
        hit = _as_existing_file(c)
        if hit:
            return hit

    # Absolute-looking path even if offline (Studio can show a clear missing error)
    for c in candidates:
        s = str(c).strip()
        if len(s) > 3 and (":" in s or s.startswith("\\\\") or s.startswith("/")):
            return s
    return None


def _timeline_item(timeline):
    """Prefer clip under playhead; else first video item on any track."""
    try:
        item = timeline.GetCurrentVideoItem()
        if item is not None:
            return item
    except Exception:
        pass
    try:
        ntracks = int(timeline.GetTrackCount("video") or 0)
    except Exception:
        ntracks = 0
    for ti in range(1, max(ntracks, 0) + 1):
        try:
            items = timeline.GetItemListInTrack("video", ti) or []
        except Exception:
            items = []
        if items:
            return items[0]
    return None


def _looks_like_camera_master(path: str | None) -> tuple[bool, str]:
    """Heuristic: very large file → warn user to Render in Place first."""
    if not path:
        return False, ""
    try:
        p = Path(path)
        if not p.is_file():
            return False, ""
        size = p.stat().st_size
    except OSError:
        return False, ""

    if size >= MASTER_WARN_BYTES:
        return True, (
            f"Selected media is large ({_format_bytes(size)}):\n{path}\n\n"
            "Please Render in Place first for a graded, smaller proxy, "
            "then run Send to AI Media Studio again on that rendered clip."
        )
    return False, ""


def _export_still(project, still_path: Path) -> bool:
    """Export current playhead frame as still (graded look on Color page)."""
    try:
        still_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"Cannot create still folder: {exc}")
        return False

    target = str(still_path)
    try:
        ok = project.ExportCurrentFrameAsStill(target)
        if ok and still_path.is_file() and still_path.stat().st_size > 0:
            return True
    except Exception as exc:
        print(f"ExportCurrentFrameAsStill failed: {exc}")

    # Fallback: thumbnail RGB → PNG (no third-party deps)
    try:
        timeline = project.GetCurrentTimeline()
        thumb = timeline.GetCurrentClipThumbnailImage() if timeline else None
        if thumb and isinstance(thumb, dict) and thumb.get("data"):
            return _write_thumb_png(thumb, still_path)
    except Exception as exc:
        print(f"Thumbnail still fallback failed: {exc}")
    return False


def _write_thumb_png(thumb: dict, dest: Path) -> bool:
    import base64
    import struct
    import zlib

    try:
        w = int(thumb["width"])
        h = int(thumb["height"])
        raw = base64.b64decode(thumb["data"])
    except Exception:
        return False
    expected = w * h * 3
    if w < 1 or h < 1 or len(raw) < expected:
        return False
    raw = raw[:expected]

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    rows = b"".join(b"\x00" + raw[y * w * 3 : (y + 1) * w * 3] for y in range(h))
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(rows, 9))
        + chunk(b"IEND", b"")
    )
    try:
        dest.write_bytes(png)
        return dest.is_file() and dest.stat().st_size > 0
    except OSError:
        return False


def _launch_studio_if_needed(root: Path) -> None:
    if not LAUNCH_ON_SEND:
        return
    bat = root / LAUNCH_BAT
    app_py = root / "app.py"
    try:
        if bat.is_file():
            subprocess.Popen(
                ["cmd", "/c", "start", "", str(bat)],
                cwd=str(root),
                close_fds=True,
            )
            print(f"Launched: {bat}")
            return
        if app_py.is_file():
            subprocess.Popen(
                [sys.executable or "python", str(app_py)],
                cwd=str(root),
                close_fds=True,
            )
    except Exception as exc:
        print(f"Could not launch Studio: {exc}")


def main() -> int:
    """
    Still export + handoff JSON only. No render jobs, no queue, no crash loops.
    """
    try:
        root = resolve_studio_root()
    except Exception as exc:
        _msg("AI Media Studio", str(exc), error=True)
        return 1

    handoff_dir = root / HANDOFF_SUBDIR
    try:
        handoff_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        _msg(
            "AI Media Studio",
            f"Cannot write handoff folder:\n{handoff_dir}\n\n{exc}",
            error=True,
        )
        return 1

    try:
        resolve = _get_resolve()
    except Exception as exc:
        _msg("AI Media Studio", str(exc), error=True)
        return 1

    try:
        pm = resolve.GetProjectManager()
        project = pm.GetCurrentProject() if pm else None
    except Exception as exc:
        _msg("AI Media Studio", f"Could not read project: {exc}", error=True)
        return 1

    if project is None:
        _msg(
            "AI Media Studio",
            "No project open in Resolve. Open a project and try again.",
            error=True,
        )
        return 1

    try:
        project_name = project.GetName() or "Project"
    except Exception:
        project_name = "Project"

    try:
        timeline = project.GetCurrentTimeline()
    except Exception as exc:
        _msg("AI Media Studio", f"Could not read timeline: {exc}", error=True)
        return 1

    if timeline is None:
        _msg(
            "AI Media Studio",
            "No timeline open. Open a timeline, park the playhead on a clip, and try again.",
            error=True,
        )
        return 1

    try:
        item = _timeline_item(timeline)
    except Exception as exc:
        _msg("AI Media Studio", f"Could not read timeline clip: {exc}", error=True)
        return 1

    if item is None:
        _msg(
            "AI Media Studio",
            "No timeline clip found under the playhead.\n"
            "Park the playhead on a video clip (or put a clip on V1) and run again.",
            error=True,
        )
        return 1

    try:
        clip_name = item.GetName() or "Resolve clip"
    except Exception:
        clip_name = "Resolve clip"

    mpi = None
    try:
        mpi = item.GetMediaPoolItem()
    except Exception:
        mpi = None

    try:
        video_path = _clip_file_path(mpi)
    except Exception as exc:
        print(f"Get media path failed: {exc}")
        video_path = None

    if not video_path:
        _msg(
            "AI Media Studio",
            f"No media file path on clip “{clip_name}”.\n\n"
            "This often happens with titles, generators, or compounds.\n"
            "Render in Place (or replace with a media file), then run again.",
            error=True,
        )
        return 1

    video_on_disk = False
    try:
        video_on_disk = Path(video_path).is_file()
    except OSError:
        video_on_disk = False

    if not video_on_disk:
        _msg(
            "AI Media Studio",
            f"Media path not found on disk:\n{video_path}\n\n"
            "Relink the clip or Render in Place, then run again.",
            error=True,
        )
        return 1

    # Large master warning (still proceed so user can ignore if intentional)
    master_warn, master_msg = _looks_like_camera_master(video_path)
    if master_warn:
        _msg("AI Media Studio — Render in Place recommended", master_msg, error=False)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = _safe_name(clip_name, 48)
    still_path = handoff_dir / f"handoff_{stamp}_{safe}_still.png"

    try:
        still_ok = _export_still(project, still_path)
    except Exception as exc:
        print(f"Still export exception: {exc}")
        still_ok = False

    if not still_ok:
        _msg(
            "AI Media Studio",
            "Could not export a still from the current frame.\n"
            "Park the playhead on the clip (Edit or Color page) and try again.",
            error=True,
        )
        return 1

    try:
        video_size = Path(video_path).stat().st_size
        size_s = _format_bytes(video_size)
    except OSError:
        size_s = "?"

    hid = f"handoff_{stamp}"
    payload = {
        "id": hid,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "clip_name": clip_name,
        "still_path": str(Path(still_path).resolve()),
        "video_path": str(Path(video_path).resolve()) if video_on_disk else video_path,
        "source": "davinci_resolve",
        "video_is_proxy": not master_warn,
        "proxy_graded": False,  # unknown; user may have RIP'd
        "render_in_place_recommended": master_warn,
        "timeline": None,
        "project": project_name,
        "notes": (
            "Handoff uses the clip’s current media path (no script render). "
            "Render in Place before send for graded, smaller media."
            + (f" Warning: large source ({size_s})." if master_warn else "")
        ),
    }
    try:
        payload["timeline"] = timeline.GetName()
    except Exception:
        pass

    try:
        text = json.dumps(payload, indent=2)
        latest = handoff_dir / "latest.json"
        archive = handoff_dir / f"{hid}.json"
        archive.write_text(text, encoding="utf-8")
        latest.write_text(text, encoding="utf-8")
    except OSError as exc:
        _msg(
            "AI Media Studio",
            f"Still exported but could not write handoff JSON:\n{exc}",
            error=True,
        )
        return 1

    try:
        _launch_studio_if_needed(root)
    except Exception as exc:
        print(f"Launch skipped: {exc}")

    warn_line = ""
    if master_warn:
        warn_line = (
            "\n\n⚠ Large file — please Render in Place first for a graded, smaller proxy "
            "if AI video jobs fail."
        )

    summary = (
        f"Sent still + clip “{clip_name}” to AI Media Studio.\n\n"
        f"Still: {still_path.name}\n"
        f"Video: {Path(video_path).name} ({size_s})\n"
        f"Path: {video_path}\n\n"
        f"Handoff: {handoff_dir / 'latest.json'}\n\n"
        "No render was started (use Render in Place in Resolve first).\n"
        "In AI Media Studio: Import from Resolve (or wait for auto-import)."
        f"{warn_line}"
    )
    _msg("AI Media Studio", summary, error=False)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        # Last-resort: never leave Resolve without a message
        err = traceback.format_exc()
        try:
            print(err)
        except Exception:
            pass
        try:
            _msg("AI Media Studio", f"Unexpected error (no render was started):\n{err}", error=True)
        except Exception:
            pass
        raise SystemExit(1)
