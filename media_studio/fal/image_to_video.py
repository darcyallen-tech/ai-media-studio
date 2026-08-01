"""Image-to-video pipeline via fal.ai (Kling I2V family)."""

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
from media_studio.fal.models import (
    build_i2v_arguments,
    default_i2v_model,
    resolve_video_model,
)
from media_studio.naming import job_media_dir, make_output_stem, timestamp_now, unique_path
from media_studio.pricing import format_render_metrics, resolve_generation_cost

ProgressCallback = Callable[[str], None]


@dataclass
class ImageToVideoResult:
    ok: bool
    path: str | None = None
    model_key: str = ""
    endpoint: str = ""
    status: str = ""
    notes: list[str] = field(default_factory=list)
    cost_estimate: str = ""
    timestamp: str = ""
    render_seconds: float | None = None
    metrics_line: str = ""


def run_image_to_video(
    *,
    prompt: str,
    image_path: str | Path,
    model_choice: str | None = None,
    parameters: dict[str, Any] | None = None,
    output_dir: str | Path,
    on_progress: ProgressCallback | None = None,
    scenario: str | None = None,
) -> ImageToVideoResult:
    prompt = (prompt or "").strip()
    ipath = Path(image_path) if image_path else None
    if not ipath or not ipath.is_file():
        return ImageToVideoResult(
            ok=False,
            status="Generate (image-to-video): upload a still image as the start frame.",
        )

    spec = resolve_video_model(model_choice)
    if spec is None or spec.task != "image_to_video":
        spec = default_i2v_model()
        auto_note = f"Using default I2V model: {spec.label}."
    else:
        auto_note = None

    def progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    progress(f"Model: {spec.label} ({spec.endpoint})")
    progress(f"Start frame: {ipath.name}")

    notes: list[str] = []
    if auto_note:
        notes.append(auto_note)

    try:
        image_url = upload_file(ipath, on_progress=progress)
    except (FalClientError, Exception) as exc:
        return ImageToVideoResult(
            ok=False,
            model_key=spec.key,
            endpoint=spec.endpoint,
            status=friendly_error(exc, context="Image-to-video"),
            notes=notes,
        )

    try:
        arguments, build_notes = build_i2v_arguments(
            spec,
            prompt=prompt,
            image_url=image_url,
            parameters=parameters,
        )
    except ValueError as exc:
        return ImageToVideoResult(
            ok=False,
            model_key=spec.key,
            endpoint=spec.endpoint,
            status=friendly_error(exc, context="Image-to-video"),
            notes=notes,
        )

    notes.extend(build_notes)
    progress("Running image-to-video on fal…")

    t0 = time.perf_counter()
    try:
        result = subscribe(spec.endpoint, arguments, on_progress=progress)
    except FalClientError as exc:
        render_s = time.perf_counter() - t0
        return ImageToVideoResult(
            ok=False,
            model_key=spec.key,
            endpoint=spec.endpoint,
            status=str(exc),
            notes=notes,
            render_seconds=render_s,
            metrics_line=format_render_metrics(render_s, None, cost_is_estimate=True),
        )
    render_s = time.perf_counter() - t0

    cost_usd, is_est = resolve_generation_cost(
        result,
        model_key=spec.key,
        job_kind="image_to_video",
        parameters=parameters,
    )
    metrics = format_render_metrics(render_s, cost_usd, cost_is_estimate=is_est)
    cost_str = metrics.split(" · ")[-1] if " · " in metrics else metrics
    if cost_usd is not None:
        notes.append(cost_str)

    out_url = extract_video_url(result)
    if not out_url:
        return ImageToVideoResult(
            ok=False,
            model_key=spec.key,
            endpoint=spec.endpoint,
            status="Generate: fal returned no video.",
            notes=notes,
            cost_estimate=cost_str if cost_usd is not None else "",
            render_seconds=render_s,
            metrics_line=metrics,
        )

    stamp = timestamp_now()
    media_dir = job_media_dir(output_dir, stamp=stamp)
    stem = make_output_stem(
        prompt or "i2v", spec.key, stamp=stamp, kind="i2v", scenario=scenario
    )
    dest = unique_path(media_dir, stem, ".mp4")

    try:
        download_url(out_url, dest, on_progress=progress, timeout=600.0)
    except FalClientError as exc:
        return ImageToVideoResult(
            ok=False,
            model_key=spec.key,
            endpoint=spec.endpoint,
            status=str(exc),
            notes=notes,
            cost_estimate=cost_str if cost_usd is not None else "",
            timestamp=stamp,
            render_seconds=render_s,
            metrics_line=metrics,
        )

    resolved = str(dest.resolve())
    status_parts = [
        f"Generate OK — {spec.label} (image-to-video).",
        f"Saved {Path(resolved).name} → {media_dir.name}/.",
        metrics + ".",
    ]
    other = [n for n in notes if n != cost_str]
    if other:
        status_parts.append("Notes: " + "; ".join(other))

    return ImageToVideoResult(
        ok=True,
        path=resolved,
        model_key=spec.key,
        endpoint=spec.endpoint,
        status=" ".join(status_parts),
        notes=notes,
        cost_estimate=cost_str if cost_usd is not None else "",
        timestamp=stamp,
        render_seconds=render_s,
        metrics_line=metrics,
    )
