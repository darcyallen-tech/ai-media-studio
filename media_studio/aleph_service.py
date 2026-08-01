"""
Aleph 2.0 keyframe video edit via Runware (optional second provider).

Does not use fal. Requires a separate Runware API key.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal

from media_studio.errors import friendly_error
from media_studio.history import append_history
from media_studio.naming import job_media_dir, make_output_stem, timestamp_now, unique_path
from media_studio.pricing import format_cost_label, format_render_metrics, probe_video_duration
from media_studio.runware_client import (
    ALEPH_MAX_DURATION_S,
    ALEPH_MAX_KEYFRAMES,
    ALEPH_MAX_PROMPT_CHARS,
    ALEPH_MIN_DURATION_S,
    RunwareClientError,
    RunwareConfigError,
    download_url,
    estimate_aleph_cost_usd,
    format_aleph_cost,
    run_aleph_video_edit,
    upload_media,
)

ProgressCallback = Callable[[str], None]

# Position pin for a keyframe
KeyframePin = Literal["first", "last", "timestamp"]


@dataclass
class AlephKeyframe:
    """One guidance still pinned to the source timeline."""

    image_path: str
    pin: KeyframePin = "first"
    timestamp_s: float | None = None  # used when pin == "timestamp"

    def to_api_item(self, image_url: str) -> dict[str, Any]:
        if self.pin == "last":
            return {"image": image_url, "frame": "last"}
        if self.pin == "timestamp":
            ts = float(self.timestamp_s or 0.0)
            ts = max(0.0, round(ts, 2))
            return {"image": image_url, "timestamp": ts}
        return {"image": image_url, "frame": "first"}


@dataclass
class AlephResult:
    ok: bool
    path: str | None = None
    status: str = ""
    cost_label: str = ""
    metrics_line: str = ""
    notes: list[str] = field(default_factory=list)
    timestamp: str = ""


def run_aleph_keyframe_edit(
    *,
    video_path: str | None,
    prompt: str | None,
    keyframes: list[AlephKeyframe] | None = None,
    output_dir: str | Path,
    on_progress: ProgressCallback | None = None,
) -> AlephResult:
    """
    Source video + optional edited keyframe stills → Aleph propagates the edit.

    Limits: source 2–30s, up to 5 keyframes, 1080p class.
    """

    def progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    path = Path(video_path) if video_path else None
    if not path or not path.is_file():
        return AlephResult(ok=False, status="Upload a source video for Aleph keyframe edit.")

    text = (prompt or "").strip()
    if not text:
        return AlephResult(
            ok=False,
            status=(
                "Enter a short prompt: what to change "
                '(e.g. "Remove the person in the mirror; change nothing else").'
            ),
        )
    if len(text) > ALEPH_MAX_PROMPT_CHARS:
        text = text[: ALEPH_MAX_PROMPT_CHARS - 1].rstrip() + "…"

    dur = probe_video_duration(path)
    if dur is not None:
        if dur + 0.05 < ALEPH_MIN_DURATION_S:
            return AlephResult(
                ok=False,
                status=(
                    f"Aleph needs about {ALEPH_MIN_DURATION_S:.0f}–{ALEPH_MAX_DURATION_S:.0f}s "
                    f"(yours is {dur:.1f}s). Use a longer clip."
                ),
                cost_label=format_aleph_cost(dur),
            )
        if dur > ALEPH_MAX_DURATION_S + 0.25:
            return AlephResult(
                ok=False,
                status=(
                    f"Aleph max is {ALEPH_MAX_DURATION_S:.0f}s (yours is {dur:.1f}s). "
                    "Trim/export a 2–30s proxy and retry."
                ),
                cost_label=format_aleph_cost(ALEPH_MAX_DURATION_S),
            )

    try:
        size_mb = path.stat().st_size / (1024 * 1024)
    except OSError:
        size_mb = 0.0
    if size_mb > 200:
        return AlephResult(
            ok=False,
            status=(
                f"Source is {size_mb:.0f} MB — too large. Export a shorter 1080p "
                "proxy (2–30s) and retry."
            ),
            cost_label=format_aleph_cost(dur),
        )

    kfs = list(keyframes or [])[:ALEPH_MAX_KEYFRAMES]
    for kf in kfs:
        if not Path(kf.image_path).is_file():
            return AlephResult(
                ok=False,
                status=f"Keyframe missing: {kf.image_path}",
                cost_label=format_aleph_cost(dur),
            )

    est = estimate_aleph_cost_usd(dur)
    est_lbl = format_cost_label(est, estimate=True)
    progress(format_aleph_cost(dur))
    if dur is not None:
        progress(f"Source ≈ {dur:.1f}s · {size_mb:.0f} MB · {len(kfs)} keyframe(s)")

    t0 = time.perf_counter()
    try:
        video_url = upload_media(path, on_progress=progress)
        frame_api: list[dict[str, Any]] = []
        for i, kf in enumerate(kfs):
            progress(f"Uploading keyframe {i + 1}/{len(kfs)}…")
            img_url = upload_media(kf.image_path, on_progress=progress)
            frame_api.append(kf.to_api_item(img_url))

        out_url = run_aleph_video_edit(
            video_url=video_url,
            prompt=text,
            frame_images=frame_api or None,
            on_progress=progress,
        )
    except RunwareConfigError as exc:
        return AlephResult(ok=False, status=str(exc), cost_label=est_lbl)
    except RunwareClientError as exc:
        return AlephResult(
            ok=False,
            status=friendly_error(exc, context="Aleph 2.0"),
            cost_label=est_lbl,
        )
    except Exception as exc:
        return AlephResult(
            ok=False,
            status=friendly_error(exc, context="Aleph 2.0"),
            cost_label=est_lbl,
        )

    render_s = time.perf_counter() - t0
    metrics = format_render_metrics(render_s, est, cost_is_estimate=True)
    cost_lbl = format_cost_label(est, estimate=True)

    stamp = timestamp_now()
    media_dir = job_media_dir(output_dir, stamp=stamp)
    stem = make_output_stem(text or "aleph", "aleph-2", stamp=stamp, kind="aleph-keyframe")
    dest = unique_path(media_dir, stem, ".mp4")

    try:
        download_url(out_url, dest, on_progress=progress)
    except RunwareClientError as exc:
        return AlephResult(
            ok=False,
            status=str(exc),
            cost_label=cost_lbl,
            metrics_line=metrics,
            timestamp=stamp,
        )

    resolved = str(dest.resolve())
    status = (
        f"Aleph 2.0 OK. Saved {Path(resolved).name} → {media_dir.name}/. "
        f"{metrics}. Use Show in folder or Send to Resolve."
    )

    try:
        append_history(
            job_kind="aleph_keyframe",
            model="Aleph 2.0 (Runware)",
            prompt=text,
            files=[resolved],
            cost_estimate=cost_lbl,
            notes=[
                f"keyframes={len(kfs)}",
                f"source={path.name}",
            ],
            output_dir=output_dir,
            timestamp=stamp,
            scenario="aleph_keyframe",
        )
    except Exception:
        pass

    return AlephResult(
        ok=True,
        path=resolved,
        status=status,
        cost_label=cost_lbl,
        metrics_line=metrics,
        notes=[f"{len(kfs)} keyframe(s)"],
        timestamp=stamp,
    )
