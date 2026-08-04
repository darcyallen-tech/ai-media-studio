"""Run Motion Sync jobs (character still + driving video) via fal."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
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
from media_studio.history import append_history
from media_studio.motion_sync_registry import (
    build_motion_sync_arguments,
    default_motion_sync_model,
    estimate_motion_sync_cost,
    find_motion_sync_model,
    format_motion_sync_cost,
    friendly_motion_sync_error,
    max_motion_duration_for_orientation,
    normalize_character_orientation,
)
from media_studio.naming import job_media_dir, make_output_stem, timestamp_now, unique_path
from media_studio.pricing import (
    extract_cost_usd_from_response,
    format_cost_label,
    format_render_metrics,
    probe_video_duration,
)

ProgressCallback = Callable[[str], None]


@dataclass
class MotionSyncResult:
    ok: bool
    path: str | None = None
    status: str = ""
    model_key: str = ""
    endpoint: str = ""
    notes: list[str] = field(default_factory=list)
    cost_label: str = ""
    metrics_line: str = ""
    timestamp: str = ""
    duration_s: float | None = None
    used_proxy: bool = False
    proxy_note: str = ""


def run_motion_sync(
    *,
    character_path: str | Path,
    motion_path: str | Path,
    model_label: str | None = None,
    prompt: str | None = None,
    keep_original_sound: bool | None = True,
    character_orientation: str | None = "video",
    adapt_motion: bool | None = None,
    enhance_identity: bool | None = None,
    acceleration: str | None = None,
    output_dir: str | Path,
    on_progress: ProgressCallback | None = None,
) -> MotionSyncResult:
    """
    Transfer motion from ``motion_path`` onto the character in ``character_path``.

    Oversized / over-long inputs are auto-proxied (trim + scale still/video)
    before upload; user originals are never modified.
    """

    def progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    char = Path(character_path) if character_path else None
    motion = Path(motion_path) if motion_path else None
    if char is None or not char.is_file():
        return MotionSyncResult(
            ok=False,
            status="Motion Sync needs a character still (full-body or clear upper body).",
        )
    if motion is None or not motion.is_file():
        return MotionSyncResult(
            ok=False,
            status="Motion Sync needs a motion reference video (driving clip).",
        )

    spec = find_motion_sync_model(model_label) or default_motion_sync_model()
    notes: list[str] = []
    used_proxy = False
    proxy_note = ""
    prep_motion_dur: float | None = None

    ori = normalize_character_orientation(character_orientation)
    # --- Auto-prep before size/duration checks ---
    try:
        from media_studio.motion_sync_prep import (
            TARGET_MOTION_MAX_S,
            prepare_motion_sync_inputs,
        )

        # Prefer 3–10s for API; image orientation hard-caps at 10s (Kling)
        ori_cap = max_motion_duration_for_orientation(ori)
        max_dur = min(
            float(TARGET_MOTION_MAX_S),
            float(ori_cap),
            float(spec.max_duration_s or 30),
        )
        progress("Checking inputs for API limits…")
        char_prep, motion_prep = prepare_motion_sync_inputs(
            character_path=char,
            motion_path=motion,
            output_dir=output_dir,
            max_motion_duration_s=max_dur,
            on_progress=progress,
        )
        char = Path(char_prep.path)
        motion = Path(motion_prep.path)
        notes.extend(char_prep.notes or [])
        notes.extend(motion_prep.notes or [])
        prep_motion_dur = motion_prep.duration_s
        if char_prep.used_proxy or motion_prep.used_proxy:
            used_proxy = True
            from media_studio.motion_sync_prep import PROXY_NOTE

            proxy_note = char_prep.note or motion_prep.note or PROXY_NOTE
            progress(proxy_note)
    except Exception as prep_exc:
        return MotionSyncResult(
            ok=False,
            model_key=spec.key,
            endpoint=spec.endpoint,
            status=friendly_motion_sync_error(
                f"Could not prepare inputs for the API: {prep_exc}. "
                "Export a shorter 3–10s Render-in-Place proxy (≤ ~100 MB) or "
                "downscale the still, then retry."
            ),
            notes=notes + [f"prep_failed: {prep_exc}"],
        )

    dur = probe_video_duration(motion)
    if prep_motion_dur and prep_motion_dur > 0:
        dur = float(prep_motion_dur)
    if dur is None or dur <= 0:
        dur = 5.0
        notes.append("duration probe failed — cost estimate uses 5s")
    else:
        notes.append(f"driving_clip≈{dur:.1f}s")

    # Soft validation after proxy
    if dur < float(spec.min_duration_s) - 0.05:
        return MotionSyncResult(
            ok=False,
            model_key=spec.key,
            endpoint=spec.endpoint,
            status=friendly_motion_sync_error(
                "Motion reference is too short after prep. "
                f"Need at least ~{spec.min_duration_s:.0f}s of clear subject motion."
            ),
            notes=notes,
            used_proxy=used_proxy,
            proxy_note=proxy_note,
            duration_s=dur,
        )

    est = estimate_motion_sync_cost(spec, duration_s=dur)
    est_lbl = format_motion_sync_cost(spec, duration_s=dur)
    progress(f"{spec.label} · {est_lbl}")
    progress(f"Endpoint: {spec.endpoint}")
    progress(f"Character: {char.name}")
    progress(f"Motion: {motion.name} ({dur:.1f}s)")

    t0 = time.perf_counter()
    try:
        progress("Uploading character still…")
        image_url = upload_file(char, on_progress=progress)
        progress("Uploading motion reference…")
        video_url = upload_file(motion, on_progress=progress)

        args = build_motion_sync_arguments(
            spec,
            image_url=image_url,
            video_url=video_url,
            prompt=prompt,
            keep_original_sound=keep_original_sound,
            character_orientation=ori,
            adapt_motion=adapt_motion,
            enhance_identity=enhance_identity,
            acceleration=acceleration,
        )
        # Confirm orientation was applied for Kling
        if spec.supports_character_orientation:
            notes.append(f"character_orientation={args.get('character_orientation')}")
        progress("Running motion transfer on fal…")
        result = subscribe(spec.endpoint, args, on_progress=progress)
    except FalClientError as exc:
        render_s = time.perf_counter() - t0
        return MotionSyncResult(
            ok=False,
            model_key=spec.key,
            endpoint=spec.endpoint,
            status=friendly_motion_sync_error(exc),
            notes=notes,
            cost_label=est_lbl,
            metrics_line=format_render_metrics(render_s, None, cost_is_estimate=True),
            duration_s=dur,
            used_proxy=used_proxy,
            proxy_note=proxy_note,
        )
    except Exception as exc:
        render_s = time.perf_counter() - t0
        raw = friendly_error(exc, context="Motion Sync")
        return MotionSyncResult(
            ok=False,
            model_key=spec.key,
            endpoint=spec.endpoint,
            status=friendly_motion_sync_error(raw),
            notes=notes,
            cost_label=est_lbl,
            metrics_line=format_render_metrics(render_s, None, cost_is_estimate=True),
            duration_s=dur,
            used_proxy=used_proxy,
            proxy_note=proxy_note,
        )

    render_s = time.perf_counter() - t0
    exact = extract_cost_usd_from_response(result)
    cost_usd = exact if exact is not None else est
    is_est = exact is None
    metrics = format_render_metrics(render_s, cost_usd, cost_is_estimate=is_est)
    cost_lbl = format_cost_label(cost_usd, estimate=is_est)

    out_url = extract_video_url(result)
    if not out_url:
        return MotionSyncResult(
            ok=False,
            model_key=spec.key,
            endpoint=spec.endpoint,
            status="Motion Sync: fal returned no video.",
            notes=notes,
            cost_label=cost_lbl,
            metrics_line=metrics,
            duration_s=dur,
        )

    stamp = timestamp_now()
    media_dir = job_media_dir(output_dir, stamp=stamp)
    stem = make_output_stem(
        (prompt or "motion-sync")[:80],
        spec.key,
        stamp=stamp,
        kind="motion-sync",
    )
    dest = unique_path(media_dir, stem, ".mp4")
    try:
        download_url(out_url, dest, on_progress=progress, timeout=900.0)
    except FalClientError as exc:
        return MotionSyncResult(
            ok=False,
            model_key=spec.key,
            endpoint=spec.endpoint,
            status=str(exc),
            notes=notes,
            cost_label=cost_lbl,
            metrics_line=metrics,
            duration_s=dur,
            timestamp=stamp,
        )

    resolved = str(dest.resolve())
    status = (
        f"{spec.label} OK · motion transfer. "
        f"Saved {Path(resolved).name}. {metrics}."
    )
    if used_proxy and proxy_note:
        status = f"{proxy_note} · {status}"
    try:
        append_history(
            job_kind="motion_sync",
            model=spec.label,
            prompt=(prompt or "motion sync")[:800],
            files=[resolved],
            cost_estimate=cost_lbl,
            notes=notes + [f"driving={motion.name}", f"character={char.name}"],
            output_dir=output_dir,
            timestamp=stamp,
            scenario="motion-sync",
        )
    except Exception:
        pass

    return MotionSyncResult(
        ok=True,
        path=resolved,
        status=status,
        model_key=spec.key,
        endpoint=spec.endpoint,
        notes=notes,
        cost_label=cost_lbl,
        metrics_line=metrics,
        timestamp=stamp,
        duration_s=dur,
        used_proxy=used_proxy,
        proxy_note=proxy_note,
    )
