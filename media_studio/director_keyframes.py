"""
Director · Keyframe Take — FLUX 3 keyframes-to-video (continuous shot).

Not Kling multi_prompt. Pins are stills at times (seconds) → frame_index @ 24 fps.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from media_studio.errors import friendly_error
from media_studio.fal.client import (
    FalClientError,
    download_url,
    extract_draft_cache_url,
    extract_video_url,
    subscribe,
    upload_file,
)
from media_studio.flux3_draft import (
    estimate_draft_cost_usd,
    strip_resolution_for_draft,
)
from media_studio.history import append_history
from media_studio.motion_sync_prep import (
    API_STILL_PROXY_NOTE,
    MAX_API_STILL_BYTES,
    MAX_API_STILL_SIDE,
    prepare_api_still,
)
from media_studio.naming import job_media_dir, make_output_stem, timestamp_now, unique_path
from media_studio.pricing import (
    extract_cost_usd_from_response,
    format_cost_label,
    format_job_cost,
    format_render_metrics,
)

ProgressCallback = Callable[[str], None]

# fal: 24 fps; frame_index unique, ≤ duration * 24
KEYFRAME_FPS = 24
KEYFRAME_MAX_PINS = 10
KEYFRAME_MIN_DURATION = 5
KEYFRAME_MAX_DURATION = 20
KEYFRAME_ENDPOINT = "blackforestlabs/flux-3/keyframes-to-video"
KEYFRAME_DRAFT_ENDPOINT = "blackforestlabs/flux-3/keyframes-to-video/draft"
KEYFRAME_COST_720 = 0.17
KEYFRAME_COST_1080 = 0.29
KEYFRAME_COST_DRAFT = 0.06


@dataclass
class KeyframePin:
    """One still pin for Keyframe Take (UI time in seconds)."""

    path: str
    time_s: float = 0.0
    label: str = ""

    def frame_index(self, *, duration_s: int, fps: int = KEYFRAME_FPS) -> int:
        max_f = max(0, int(duration_s) * int(fps))
        try:
            t = float(self.time_s)
        except (TypeError, ValueError):
            t = 0.0
        t = max(0.0, min(t, float(duration_s)))
        fi = int(round(t * fps))
        return max(0, min(fi, max_f))


def keyframe_duration_choices() -> list[str]:
    return [str(i) for i in range(KEYFRAME_MIN_DURATION, KEYFRAME_MAX_DURATION + 1)]


def auto_spread_pin_times(
    n_pins: int,
    duration_s: float,
) -> list[float]:
    """
    Evenly place pins across [0, duration].

    1 pin → 0; 2 pins → 0, duration; 3+ → start, mids, end.
    """
    n = max(0, int(n_pins))
    if n <= 0:
        return []
    total = max(float(KEYFRAME_MIN_DURATION), float(duration_s or KEYFRAME_MIN_DURATION))
    if n == 1:
        return [0.0]
    if n == 2:
        return [0.0, total]
    step = total / (n - 1)
    return [round(i * step, 3) for i in range(n)]


def estimate_keyframe_take_cost(
    *,
    duration_s: float,
    resolution: str | None = "720p",
    draft: bool = False,
) -> float:
    secs = max(1.0, float(duration_s or 8))
    if draft:
        return round(KEYFRAME_COST_DRAFT * secs, 3)
    res = (resolution or "720p").strip().lower()
    rate = KEYFRAME_COST_1080 if "1080" in res else KEYFRAME_COST_720
    return round(rate * secs, 3)


def format_keyframe_take_cost(
    *,
    duration_s: float,
    resolution: str | None = "720p",
    draft: bool = False,
) -> str:
    amt = estimate_keyframe_take_cost(
        duration_s=duration_s, resolution=resolution, draft=draft
    )
    secs = int(round(float(duration_s or 8)))
    if draft:
        return format_job_cost(amt, unit=f"{secs}s draft", model="FLUX 3 · Keyframe Take")
    res = (resolution or "720p").strip()
    return format_job_cost(
        amt, unit=f"{secs}s · {res}", model="FLUX 3 · Keyframe Take"
    )


def validate_keyframe_pins(
    pins: list[KeyframePin],
    *,
    duration_s: float,
) -> list[str]:
    errs: list[str] = []
    if not pins:
        errs.append("Add at least one pin still.")
        return errs
    if len(pins) > KEYFRAME_MAX_PINS:
        errs.append(f"Max {KEYFRAME_MAX_PINS} pins.")
    try:
        dur = int(round(float(duration_s)))
    except (TypeError, ValueError):
        dur = KEYFRAME_MIN_DURATION
    if dur < KEYFRAME_MIN_DURATION or dur > KEYFRAME_MAX_DURATION:
        errs.append(
            f"Duration must be {KEYFRAME_MIN_DURATION}–{KEYFRAME_MAX_DURATION}s."
        )
    seen_fi: set[int] = set()
    for i, p in enumerate(pins):
        if not p.path or not Path(p.path).is_file():
            errs.append(f"Pin {i + 1}: missing still file.")
            continue
        fi = p.frame_index(duration_s=dur)
        if fi in seen_fi:
            errs.append(
                f"Pin {i + 1}: time {p.time_s}s maps to frame {fi} already used — "
                "adjust times so frame indices are unique."
            )
        seen_fi.add(fi)
    return errs


def build_keyframe_take_arguments(
    *,
    prompt: str,
    pins: list[KeyframePin],
    image_urls: list[str],
    duration_s: int | float,
    aspect_ratio: str | None = "auto",
    resolution: str | None = "720p",
    generate_audio: bool = True,
    draft: bool = False,
    safety_tolerance: int = 2,
) -> tuple[str, dict[str, Any]]:
    """
    Map UI pins → fal keyframes-to-video payload.

    ``image_urls`` must align 1:1 with ``pins`` (already uploaded).
    """
    text = (prompt or "").strip()
    if not text:
        raise ValueError("Enter a global motion / shot prompt.")
    if len(pins) != len(image_urls):
        raise ValueError("Internal error: pin count ≠ uploaded stills.")
    try:
        dur = int(round(float(duration_s)))
    except (TypeError, ValueError):
        dur = 8
    dur = max(KEYFRAME_MIN_DURATION, min(KEYFRAME_MAX_DURATION, dur))

    keyframes: list[dict[str, Any]] = []
    used: set[int] = set()
    for pin, url in zip(pins, image_urls):
        fi = pin.frame_index(duration_s=dur)
        # Deduplicate frame_index by bumping slightly if collision after round
        while fi in used and fi < dur * KEYFRAME_FPS:
            fi += 1
        if fi in used:
            raise ValueError(
                "Keyframe times collide after mapping to 24 fps frames — space pins out."
            )
        used.add(fi)
        keyframes.append({"image_url": str(url), "frame_index": int(fi)})

    args: dict[str, Any] = {
        "prompt": text,
        "keyframes": keyframes,
        "duration": dur,
        "generate_audio": bool(generate_audio),
        "safety_tolerance": int(safety_tolerance),
    }
    ar = (aspect_ratio or "auto").strip()
    if ar and ar not in ("—", "none"):
        args["aspect_ratio"] = ar
    res = (resolution or "720p").strip()
    if not draft and res in ("720p", "1080p"):
        args["resolution"] = res

    endpoint = KEYFRAME_DRAFT_ENDPOINT if draft else KEYFRAME_ENDPOINT
    if draft:
        args = strip_resolution_for_draft(args)
    return endpoint, args


@dataclass
class KeyframeTakeResult:
    ok: bool
    path: str | None = None
    status: str = ""
    model_key: str = "flux 3 keyframe take"
    endpoint: str = KEYFRAME_ENDPOINT
    notes: list[str] = field(default_factory=list)
    cost_label: str = ""
    metrics_line: str = ""
    timestamp: str = ""
    is_draft: bool = False
    draft_cache_url: str | None = None


def run_keyframe_take(
    *,
    prompt: str,
    pins: list[KeyframePin],
    duration_s: float = 8.0,
    aspect_ratio: str | None = "auto",
    resolution: str | None = "720p",
    generate_audio: bool = True,
    draft: bool = False,
    output_dir: str | Path,
    on_progress: ProgressCallback | None = None,
) -> KeyframeTakeResult:
    """Upload pins → FLUX 3 keyframes-to-video (or /draft)."""

    def progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    errs = validate_keyframe_pins(pins, duration_s=duration_s)
    if errs:
        return KeyframeTakeResult(ok=False, status=" · ".join(errs))

    notes: list[str] = []
    # Soft layout-lock language for character/scene stills is caller's prompt job;
    # service notes pin times for QC.
    for i, p in enumerate(pins):
        notes.append(
            f"Pin {i + 1}: t={p.time_s}s → frame {p.frame_index(duration_s=int(round(duration_s)))}"
            + (f" ({p.label})" if p.label else "")
        )

    # Prepare + upload stills
    urls: list[str] = []
    proxy_n = 0
    for i, pin in enumerate(pins):
        try:
            prep = prepare_api_still(
                pin.path,
                output_dir=output_dir,
                max_side=MAX_API_STILL_SIDE,
                max_bytes=MAX_API_STILL_BYTES,
                on_progress=progress,
                label=f"pin {i + 1}",
            )
            local = str(prep.path)
            if prep.used_proxy:
                proxy_n += 1
            progress(f"Uploading pin {i + 1}: {Path(local).name}")
            urls.append(upload_file(Path(local), on_progress=progress))
        except Exception as exc:
            return KeyframeTakeResult(
                ok=False,
                status=friendly_error(exc, context="Keyframe Take upload", media_kind="image"),
                notes=notes,
            )
    if proxy_n:
        notes.append(API_STILL_PROXY_NOTE)

    try:
        endpoint, arguments = build_keyframe_take_arguments(
            prompt=prompt,
            pins=pins,
            image_urls=urls,
            duration_s=duration_s,
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            generate_audio=generate_audio,
            draft=draft,
        )
    except ValueError as exc:
        return KeyframeTakeResult(ok=False, status=str(exc), notes=notes)

    est = estimate_keyframe_take_cost(
        duration_s=float(arguments.get("duration") or duration_s),
        resolution=resolution,
        draft=draft,
    )
    est_lbl = format_cost_label(est, estimate=True)
    if draft:
        est_lbl = f"{est_lbl} (draft)"
    progress(f"FLUX 3 · Keyframe Take · {len(pins)} pin(s)")
    progress(f"Endpoint: {endpoint}")
    progress(f"Est. cost: {est_lbl}")
    progress("Running Keyframe Take on fal…")

    t0 = time.perf_counter()
    try:
        result = subscribe(endpoint, arguments, on_progress=progress)
    except FalClientError as exc:
        render_s = time.perf_counter() - t0
        return KeyframeTakeResult(
            ok=False,
            endpoint=endpoint,
            status=friendly_error(exc, context="Keyframe Take", media_kind="image"),
            notes=notes,
            metrics_line=format_render_metrics(render_s, None, cost_is_estimate=True),
            cost_label=est_lbl,
        )
    except Exception as exc:
        return KeyframeTakeResult(
            ok=False,
            endpoint=endpoint,
            status=friendly_error(exc, context="Keyframe Take"),
            notes=notes,
            cost_label=est_lbl,
        )
    render_s = time.perf_counter() - t0

    draft_cache = extract_draft_cache_url(result) if draft else None
    out_url = extract_video_url(result)
    if not out_url:
        return KeyframeTakeResult(
            ok=False,
            endpoint=endpoint,
            status="Keyframe Take: fal returned no video.",
            notes=notes,
            cost_label=est_lbl,
            is_draft=draft,
            draft_cache_url=draft_cache,
        )

    exact = extract_cost_usd_from_response(result)
    cost_usd = exact if exact is not None else est
    is_est = exact is None
    metrics = format_render_metrics(render_s, cost_usd, cost_is_estimate=is_est)
    cost_lbl = format_cost_label(cost_usd, estimate=is_est)
    if draft:
        cost_lbl = f"{cost_lbl} (draft)"

    stamp = timestamp_now()
    media_dir = job_media_dir(output_dir, stamp=stamp)
    kind = "keyframe-take-draft" if draft else "keyframe-take"
    stem = make_output_stem(prompt or "keyframe-take", "flux3-kf", stamp=stamp, kind=kind)
    dest = unique_path(media_dir, stem, ".mp4")
    try:
        download_url(out_url, dest, on_progress=progress, timeout=600.0)
    except FalClientError as exc:
        return KeyframeTakeResult(
            ok=False,
            endpoint=endpoint,
            status=str(exc),
            notes=notes,
            cost_label=cost_lbl,
            metrics_line=metrics,
            is_draft=draft,
            draft_cache_url=draft_cache,
        )

    resolved = str(dest.resolve())
    try:
        append_history(
            job_kind="creative_vision",
            model="FLUX 3 · Keyframe Take",
            prompt=prompt or "",
            files=[resolved],
            cost_estimate=metrics or cost_lbl,
            notes=notes[:6],
            output_dir=output_dir,
            timestamp=stamp,
            scenario="director_keyframe_take",
        )
    except Exception:
        pass

    mode = "draft" if draft else "full"
    status = (
        f"Keyframe Take OK ({mode}) · {len(pins)} pins · {Path(resolved).name}. "
        f"{metrics}."
    )
    if draft and draft_cache:
        status += " Draft cache ready for Enhance to full."
        notes.append("draft_cache ready")

    return KeyframeTakeResult(
        ok=True,
        path=resolved,
        endpoint=endpoint,
        status=status,
        notes=notes,
        cost_label=cost_lbl,
        metrics_line=metrics,
        timestamp=stamp,
        is_draft=draft,
        draft_cache_url=draft_cache,
    )
