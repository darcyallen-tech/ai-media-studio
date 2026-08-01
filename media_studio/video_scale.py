"""
fal-ai/workflow-utilities/scale-video — 1080p-class proxies for Aleph / Frame Editor.

Uses FAL_KEY only (not Runware). Cheap vs Aleph; preserves aspect ratio.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from media_studio.errors import friendly_error
from media_studio.fal.client import (
    FalClientError,
    download_url,
    extract_video_url,
    subscribe,
    upload_file,
)
from media_studio.naming import unique_path

ProgressCallback = Callable[[str], None]

SCALE_ENDPOINT = "fal-ai/workflow-utilities/scale-video"
# 1080p-class long edge / short edge boxes
_MAX_LONG = 1920
_MAX_SHORT = 1080
# Rough cost for scale-video (cheap workflow util)
SCALE_COST_USD = 0.02


def _proxy_fingerprint(path: Path, tw: int, th: int) -> str:
    """Stable cache key: path stem + size + mtime + target dims."""
    try:
        st = path.stat()
        raw = f"{path.resolve()}|{st.st_size}|{int(st.st_mtime)}|{tw}x{th}"
    except OSError:
        raw = f"{path}|{tw}x{th}"
    return hashlib.sha1(raw.encode("utf-8", errors="replace")).hexdigest()[:16]


def _proxy_cache_path(path: Path, output_dir: Path, tw: int, th: int) -> Path:
    from media_studio.config import ensure_output_dir

    proxy_dir = ensure_output_dir(Path(output_dir)) / "_aleph_proxies"
    proxy_dir.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in path.stem)[:50]
    fp = _proxy_fingerprint(path, tw, th)
    return proxy_dir / f"{safe}_{fp}_{tw}x{th}.mp4"


def find_cached_proxy(
    video_path: str | Path,
    *,
    output_dir: str | Path,
    target_w: int,
    target_h: int,
) -> Path | None:
    """Return existing proxy file for this source+target if present and non-empty."""
    path = Path(video_path)
    if not path.is_file():
        return None
    cand = _proxy_cache_path(path, Path(output_dir), int(target_w), int(target_h))
    try:
        if cand.is_file() and cand.stat().st_size > 10_000:
            return cand
    except OSError:
        return None
    return None


@dataclass(frozen=True)
class ScaleNeed:
    needs_scale: bool
    width: int
    height: int
    target_w: int | None = None
    target_h: int | None = None
    reason: str = ""


@dataclass
class ScaleResult:
    ok: bool
    path: str | None = None
    status: str = ""
    original_w: int = 0
    original_h: int = 0
    scaled_w: int = 0
    scaled_h: int = 0
    cost_label: str = f"Est. scale: ~${SCALE_COST_USD:.2f}"


def _even(n: int) -> int:
    n = max(2, int(n))
    return n - (n % 2)


def fit_1080p_dims(width: int, height: int) -> tuple[int, int] | None:
    """
    Return (tw, th) even pixels fitting inside 1920×1080 (landscape) or
    1080×1920 (portrait), or None if already within limits.
    """
    w, h = int(width), int(height)
    if w <= 0 or h <= 0:
        return None
    if h >= w:
        box_w, box_h = _MAX_SHORT, _MAX_LONG  # 1080×1920
    else:
        box_w, box_h = _MAX_LONG, _MAX_SHORT  # 1920×1080
    # Already fits
    if w <= box_w and h <= box_h and max(w, h) <= _MAX_LONG:
        return None
    scale = min(box_w / w, box_h / h, 1.0)
    if scale >= 0.999:
        return None
    tw = _even(round(w * scale))
    th = _even(round(h * scale))
    if tw < 2 or th < 2:
        return None
    # Avoid no-op if rounding bounced back
    if tw >= w and th >= h:
        return None
    return tw, th


def needs_1080p_proxy(width: int | None, height: int | None) -> ScaleNeed:
    if not width or not height:
        return ScaleNeed(False, 0, 0, reason="unknown resolution")
    w, h = int(width), int(height)
    dims = fit_1080p_dims(w, h)
    if dims is None:
        return ScaleNeed(False, w, h, reason="within 1080p-class limits")
    tw, th = dims
    return ScaleNeed(
        True,
        w,
        h,
        target_w=tw,
        target_h=th,
        reason=f"{w}×{h} exceeds 1080p-class (max ~{_MAX_LONG}×{_MAX_SHORT} oriented)",
    )


def scale_video_to_1080p(
    video_path: str | Path,
    *,
    output_dir: str | Path,
    width: int | None = None,
    height: int | None = None,
    on_progress: ProgressCallback | None = None,
) -> ScaleResult:
    """
    Create a local 1080p-class proxy via fal scale-video.

    Original file is never modified. Requires FAL_KEY.
    """

    def progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    path = Path(video_path)
    if not path.is_file():
        return ScaleResult(ok=False, status=f"Scale: missing video {path}")

    # Resolve target dims
    ow, oh = width, height
    if not ow or not oh:
        try:
            import cv2

            cap = cv2.VideoCapture(str(path))
            try:
                ow = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
                oh = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
            finally:
                cap.release()
        except Exception as exc:
            return ScaleResult(ok=False, status=f"Scale: cannot read resolution ({exc})")

    need = needs_1080p_proxy(ow, oh)
    if not need.needs_scale or not need.target_w or not need.target_h:
        return ScaleResult(
            ok=True,
            path=str(path.resolve()),
            status="Already within 1080p-class — no scale needed.",
            original_w=need.width,
            original_h=need.height,
            scaled_w=need.width,
            scaled_h=need.height,
            cost_label="Est. scale: $0 (skipped)",
        )

    tw, th = need.target_w, need.target_h

    # Fingerprint cache — same source + target dims → reuse, no re-bill
    cached = find_cached_proxy(
        path, output_dir=output_dir, target_w=tw, target_h=th
    )
    if cached is not None:
        progress(f"Using cached 1080p proxy ({tw}×{th})…")
        return ScaleResult(
            ok=True,
            path=str(cached.resolve()),
            status=(
                f"Using cached {tw}×{th} proxy for Aleph "
                f"(source was {need.width}×{need.height}; original kept). "
                "No re-scale charge."
            ),
            original_w=need.width,
            original_h=need.height,
            scaled_w=tw,
            scaled_h=th,
            cost_label="Est. scale: $0 (cached)",
        )

    progress(
        f"Scaling {need.width}×{need.height} → {tw}×{th} (1080p proxy for Aleph)…"
    )
    progress(f"Est. scale cost ~${SCALE_COST_USD:.2f} (fal workflow util)")

    try:
        video_url = upload_file(path, on_progress=progress)
    except (FalClientError, Exception) as exc:
        return ScaleResult(
            ok=False,
            status=friendly_error(exc, context="Scale upload"),
            original_w=need.width,
            original_h=need.height,
        )

    # stretch to pre-computed aspect-preserving dims (no pad/crop distortion)
    args: dict[str, Any] = {
        "video_url": video_url,
        "width": tw,
        "height": th,
        "mode": "stretch",
        "codec": "libx264",
        "preset": "fast",
        "crf": 20,
    }
    progress(f"Running {SCALE_ENDPOINT}…")
    try:
        result = subscribe(SCALE_ENDPOINT, args, on_progress=progress)
    except (FalClientError, Exception) as exc:
        return ScaleResult(
            ok=False,
            status=friendly_error(exc, context="Scale video"),
            original_w=need.width,
            original_h=need.height,
        )

    out_url = extract_video_url(result)
    if not out_url:
        return ScaleResult(
            ok=False,
            status="Scale: fal returned no video URL.",
            original_w=need.width,
            original_h=need.height,
        )

    # Prefer reported scaled dims from API
    sw = int(result.get("scaled_width") or tw) if isinstance(result, dict) else tw
    sh = int(result.get("scaled_height") or th) if isinstance(result, dict) else th
    ow_api = int(result.get("original_width") or need.width) if isinstance(result, dict) else need.width
    oh_api = int(result.get("original_height") or need.height) if isinstance(result, dict) else need.height

    dest = _proxy_cache_path(path, Path(output_dir), tw, th)
    # If API returned slightly different dims, still write under planned fingerprint path
    try:
        if dest.is_file():
            dest.unlink()
    except OSError:
        dest = unique_path(dest.parent, dest.stem, dest.suffix)

    try:
        download_url(out_url, dest, on_progress=progress)
    except (FalClientError, Exception) as exc:
        return ScaleResult(
            ok=False,
            status=friendly_error(exc, context="Scale download"),
            original_w=ow_api,
            original_h=oh_api,
        )

    resolved = str(dest.resolve())
    return ScaleResult(
        ok=True,
        path=resolved,
        status=(
            f"Source was {ow_api}×{oh_api} — using {sw}×{sh} proxy for Aleph "
            f"(original kept). Scale ~${SCALE_COST_USD:.2f}."
        ),
        original_w=ow_api,
        original_h=oh_api,
        scaled_w=sw,
        scaled_h=sh,
        cost_label=f"Est. scale: ~${SCALE_COST_USD:.2f}",
    )
