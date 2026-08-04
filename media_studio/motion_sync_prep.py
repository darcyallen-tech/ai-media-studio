"""
Local input prep for Motion Sync API limits.

Creates temporary proxies (trim / scale / still downscale) without mutating
user originals. Uses system ffmpeg or imageio-ffmpeg.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from media_studio.pricing import probe_video_duration

ProgressCallback = Callable[[str], None]

# Soft limits that match fal “shorter 3–10s · ≤ ~100 MB” guidance
MAX_MOTION_BYTES = 90 * 1024 * 1024  # stay under ~100 MB
TARGET_MOTION_MAX_S = 10.0  # prefer 3–10s
TARGET_MOTION_MIN_S = 3.0
MOTION_LONG_EDGE = 1280  # 720p-class long edge (safe + smaller)
MOTION_LONG_EDGE_FALLBACK = 960
MAX_STILL_SIDE = 2048


def _ffmpeg_exe() -> str | None:
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and Path(exe).is_file():
            return str(exe)
    except Exception:
        pass
    return None


def _proxy_dir(output_dir: str | Path) -> Path:
    from media_studio.config import ensure_output_dir

    d = ensure_output_dir(Path(output_dir)) / "_motion_sync_proxies"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _fingerprint(path: Path, *, tag: str) -> str:
    try:
        st = path.stat()
        raw = f"{path.resolve()}|{st.st_size}|{int(st.st_mtime)}|{tag}"
    except OSError:
        raw = f"{path}|{tag}"
    return hashlib.sha1(raw.encode("utf-8", errors="replace")).hexdigest()[:16]


def _file_size(path: Path) -> int:
    try:
        return int(path.stat().st_size)
    except OSError:
        return 0


def _even(n: int) -> int:
    n = max(2, int(n))
    return n - (n % 2)


@dataclass
class PrepResult:
    path: Path
    used_proxy: bool = False
    note: str = ""
    duration_s: float | None = None
    notes: list[str] = field(default_factory=list)


def prepare_character_still(
    path: str | Path,
    *,
    output_dir: str | Path,
    max_side: int = MAX_STILL_SIDE,
    on_progress: ProgressCallback | None = None,
) -> PrepResult:
    """
    Downscale still if longest side exceeds ``max_side``. Original untouched.
    """
    src = Path(path)
    if not src.is_file():
        raise FileNotFoundError(f"Character still missing: {src}")

    def progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    try:
        from PIL import Image

        with Image.open(src) as im:
            w, h = im.size
            long_side = max(w, h)
            if long_side <= int(max_side):
                return PrepResult(path=src.resolve(), used_proxy=False, note="")

            scale = float(max_side) / float(long_side)
            tw = _even(max(2, int(round(w * scale))))
            th = _even(max(2, int(round(h * scale))))
            tag = f"still_{tw}x{th}"
            dest = _proxy_dir(output_dir) / (
                f"{src.stem[:40]}_{_fingerprint(src, tag=tag)}_char.jpg"
            )
            if dest.is_file() and dest.stat().st_size > 1024:
                progress(f"Using cached still proxy ({tw}×{th})")
                return PrepResult(
                    path=dest.resolve(),
                    used_proxy=True,
                    note="Using optimized proxy for API (original kept)",
                    notes=[f"still_proxy={dest.name}", f"still {w}x{h}→{tw}x{th}"],
                )

            progress(f"Downscaling character still {w}×{h} → {tw}×{th}…")
            rgb = im.convert("RGB")
            rgb = rgb.resize((tw, th), Image.Resampling.LANCZOS)
            rgb.save(dest, format="JPEG", quality=90, optimize=True)
            return PrepResult(
                path=dest.resolve(),
                used_proxy=True,
                note="Using optimized proxy for API (original kept)",
                notes=[f"still_proxy={dest.name}", f"still {w}x{h}→{tw}x{th}"],
            )
    except Exception as exc:
        # Soft fail — try original; API may still accept
        return PrepResult(
            path=src.resolve(),
            used_proxy=False,
            note="",
            notes=[f"still_prep_skipped: {exc}"],
        )


def _motion_needs_proxy(
    path: Path,
    *,
    duration_s: float | None,
    max_duration_s: float = TARGET_MOTION_MAX_S,
    max_bytes: int = MAX_MOTION_BYTES,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    size = _file_size(path)
    if size > max_bytes:
        reasons.append(f"size {size / (1024 * 1024):.0f} MB > {max_bytes // (1024 * 1024)} MB")
    if duration_s is not None and duration_s > max_duration_s + 0.25:
        reasons.append(f"duration {duration_s:.1f}s > {max_duration_s:.0f}s")
    return bool(reasons), reasons


def prepare_motion_video(
    path: str | Path,
    *,
    output_dir: str | Path,
    max_duration_s: float = TARGET_MOTION_MAX_S,
    max_bytes: int = MAX_MOTION_BYTES,
    long_edge: int = MOTION_LONG_EDGE,
    on_progress: ProgressCallback | None = None,
) -> PrepResult:
    """
    Trim + downscale motion clip when too long or too large.

    Prefer first ``max_duration_s`` (default 10s), scale long edge, H.264 + AAC.
    Original file is never modified.
    """
    src = Path(path)
    if not src.is_file():
        raise FileNotFoundError(f"Motion video missing: {src}")

    def progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    dur = probe_video_duration(src)
    needs, reasons = _motion_needs_proxy(
        src, duration_s=dur, max_duration_s=max_duration_s, max_bytes=max_bytes
    )
    if not needs:
        return PrepResult(
            path=src.resolve(),
            used_proxy=False,
            note="",
            duration_s=dur,
        )

    exe = _ffmpeg_exe()
    if not exe:
        raise RuntimeError(
            "Motion clip exceeds API limits and ffmpeg was not found. "
            "Install ffmpeg (or imageio-ffmpeg) or export a shorter ≤10s / ≤100 MB proxy."
        )

    trim_s = float(max_duration_s)
    if dur is not None and 0 < dur < trim_s:
        trim_s = float(dur)

    tag = f"mot_t{int(trim_s)}_e{int(long_edge)}_crf23"
    dest = _proxy_dir(output_dir) / (
        f"{src.stem[:40]}_{_fingerprint(src, tag=tag)}_motion.mp4"
    )
    if dest.is_file() and dest.stat().st_size > 50_000:
        d2 = probe_video_duration(dest) or trim_s
        progress(f"Using cached motion proxy ({dest.name})")
        return PrepResult(
            path=dest.resolve(),
            used_proxy=True,
            note="Using optimized proxy for API (original kept)",
            duration_s=d2,
            notes=[
                f"motion_proxy={dest.name}",
                f"reasons={'; '.join(reasons)}",
            ],
        )

    progress(
        f"Preparing motion proxy (trim ≤{trim_s:.0f}s, scale long-edge ≤{long_edge}px)…"
    )
    # Fit inside long_edge×long_edge box; preserve aspect (even dims via -2 in pad step)
    vf = (
        f"scale={int(long_edge)}:{int(long_edge)}:force_original_aspect_ratio=decrease,"
        f"scale=trunc(iw/2)*2:trunc(ih/2)*2"
    )
    cmd = [
        exe,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(src.resolve()),
        "-ss",
        "0",
        "-t",
        f"{trim_s:.3f}",
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-ac",
        "2",
        "-ar",
        "44100",
        "-movflags",
        "+faststart",
        str(dest),
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"ffmpeg missing: {exe}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Motion proxy timed out (ffmpeg).") from exc

    if proc.returncode != 0 or not dest.is_file() or dest.stat().st_size < 10_000:
        err = (proc.stderr or proc.stdout or "ffmpeg error").strip()
        raise RuntimeError(f"Motion proxy failed: {err[:400]}")

    # If still too large, retry more aggressive
    if _file_size(dest) > max_bytes and long_edge > MOTION_LONG_EDGE_FALLBACK:
        progress("Proxy still large — retrying at lower resolution…")
        try:
            dest.unlink(missing_ok=True)
        except OSError:
            pass
        return prepare_motion_video(
            src,
            output_dir=output_dir,
            max_duration_s=min(max_duration_s, 8.0),
            max_bytes=max_bytes,
            long_edge=MOTION_LONG_EDGE_FALLBACK,
            on_progress=on_progress,
        )

    out_dur = probe_video_duration(dest) or trim_s
    notes = [
        f"motion_proxy={dest.name}",
        f"reasons={'; '.join(reasons)}",
        f"proxy_size_mb={_file_size(dest) / (1024 * 1024):.1f}",
        f"proxy_duration≈{out_dur:.1f}s",
    ]
    progress(
        f"Motion proxy ready · {out_dur:.1f}s · "
        f"{_file_size(dest) / (1024 * 1024):.1f} MB"
    )
    return PrepResult(
        path=dest.resolve(),
        used_proxy=True,
        note="Using optimized proxy for API (original kept)",
        duration_s=out_dur,
        notes=notes,
    )


def prepare_motion_sync_inputs(
    *,
    character_path: str | Path,
    motion_path: str | Path,
    output_dir: str | Path,
    max_motion_duration_s: float = TARGET_MOTION_MAX_S,
    on_progress: ProgressCallback | None = None,
) -> tuple[PrepResult, PrepResult]:
    """Prepare character still + motion video; returns (char_prep, motion_prep)."""
    char = prepare_character_still(
        character_path, output_dir=output_dir, on_progress=on_progress
    )
    motion = prepare_motion_video(
        motion_path,
        output_dir=output_dir,
        max_duration_s=max_motion_duration_s,
        on_progress=on_progress,
    )
    return char, motion
