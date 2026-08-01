"""Run Creative Vision jobs (T2I / T2V / I2V / bridge) via fal."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from media_studio.errors import friendly_error
from media_studio.fal.client import (
    FalClientError,
    download_url,
    extract_image_urls,
    extract_video_url,
    subscribe,
    upload_file,
)
from media_studio.history import append_history
from media_studio.naming import job_media_dir, make_output_stem, timestamp_now, unique_path
from media_studio.pricing import (
    extract_cost_usd_from_response,
    format_cost_label,
    format_render_metrics,
)
from media_studio.vision_registry import (
    VisionMode,
    build_vision_arguments,
    default_vision_model,
    estimate_vision_cost,
    find_vision_model,
    format_vision_cost,
)

ProgressCallback = Callable[[str], None]


@dataclass
class VisionResult:
    ok: bool
    path: str | None = None
    model_key: str = ""
    endpoint: str = ""
    status: str = ""
    notes: list[str] = field(default_factory=list)
    cost_label: str = ""
    metrics_line: str = ""
    timestamp: str = ""


def run_vision(
    *,
    mode: VisionMode,
    prompt: str,
    model_label: str | None = None,
    image_path: str | None = None,
    first_frame_path: str | None = None,
    last_frame_path: str | None = None,
    ref_paths: list[str] | None = None,
    duration: str | None = None,
    aspect_ratio: str | None = None,
    resolution: str | None = None,
    negative_prompt: str | None = None,
    generate_audio: bool | None = None,
    output_dir: str | Path,
    on_progress: ProgressCallback | None = None,
) -> VisionResult:
    """
    Generate a Creative Vision still (T2I) or clip (T2V / I2V / bridge).

    T2I indexes as Image; video modes as creative_vision (Video filter).
    """
    spec = find_vision_model(model_label, mode) or default_vision_model(mode)

    def progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    est = estimate_vision_cost(
        spec,
        duration_token=duration or spec.default_duration,
        resolution=resolution,
        aspect_ratio=aspect_ratio,
        generate_audio=generate_audio,
    )
    est_lbl = format_cost_label(est, estimate=True)
    progress(f"{spec.label} · {est_lbl}")
    progress(f"Endpoint: {spec.endpoint}")

    # Upload media (not needed for pure T2I)
    image_url = None
    first_url = None
    last_url = None
    ref_urls: list[str] = []

    try:
        if mode == "text_to_image":
            pass  # no uploads
        elif mode == "image_to_video":
            ip = Path(image_path) if image_path else None
            if not ip or not ip.is_file():
                return VisionResult(
                    ok=False,
                    model_key=spec.key,
                    endpoint=spec.endpoint,
                    status="Image→Video needs a start still.",
                    cost_label=format_vision_cost(spec, duration_token=duration),
                )
            progress(f"Uploading start frame: {ip.name}")
            image_url = upload_file(ip, on_progress=progress)
            # Optional end for Hailuo I2V
            if last_frame_path and Path(last_frame_path).is_file():
                progress(f"Uploading end frame: {Path(last_frame_path).name}")
                last_url = upload_file(Path(last_frame_path), on_progress=progress)

        elif mode == "bridge":
            fp = Path(first_frame_path) if first_frame_path else None
            lp = Path(last_frame_path) if last_frame_path else None
            if not fp or not fp.is_file() or not lp or not lp.is_file():
                return VisionResult(
                    ok=False,
                    model_key=spec.key,
                    endpoint=spec.endpoint,
                    status="Bridge needs both start and end stills.",
                    cost_label=format_vision_cost(spec, duration_token=duration),
                )
            progress(f"Uploading start frame: {fp.name}")
            first_url = upload_file(fp, on_progress=progress)
            progress(f"Uploading end frame: {lp.name}")
            last_url = upload_file(lp, on_progress=progress)

        # Reference pack (and subject stills) for reference-to-video / vision context
        for rp in ref_paths or []:
            try:
                p = Path(rp)
                if not p.is_file():
                    continue
                progress(f"Uploading ref: {p.name}")
                ref_urls.append(upload_file(p, on_progress=progress))
            except Exception as exc:
                progress(f"Skip ref {rp}: {exc}")
            if len(ref_urls) >= max(1, spec.max_refs or 8):
                break

    except (FalClientError, Exception) as exc:
        return VisionResult(
            ok=False,
            model_key=spec.key,
            endpoint=spec.endpoint,
            status=friendly_error(exc, context="Creative Vision upload"),
            cost_label=est_lbl,
        )

    try:
        arguments = build_vision_arguments(
            spec,
            prompt=prompt,
            image_url=image_url,
            first_frame_url=first_url,
            last_frame_url=last_url,
            ref_urls=ref_urls or None,
            duration=duration,
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            negative_prompt=negative_prompt,
            generate_audio=generate_audio,
        )
    except ValueError as exc:
        return VisionResult(
            ok=False,
            model_key=spec.key,
            endpoint=spec.endpoint,
            status=str(exc),
            cost_label=est_lbl,
        )

    progress("Running Creative Vision on fal…")
    t0 = time.perf_counter()
    try:
        result = subscribe(spec.endpoint, arguments, on_progress=progress)
    except FalClientError as exc:
        render_s = time.perf_counter() - t0
        return VisionResult(
            ok=False,
            model_key=spec.key,
            endpoint=spec.endpoint,
            status=str(exc),
            cost_label=est_lbl,
            metrics_line=format_render_metrics(render_s, None, cost_is_estimate=True),
        )
    except Exception as exc:
        render_s = time.perf_counter() - t0
        return VisionResult(
            ok=False,
            model_key=spec.key,
            endpoint=spec.endpoint,
            status=friendly_error(exc, context=spec.label),
            cost_label=est_lbl,
            metrics_line=format_render_metrics(render_s, None, cost_is_estimate=True),
        )
    render_s = time.perf_counter() - t0

    exact = extract_cost_usd_from_response(result)
    cost_usd = exact if exact is not None else est
    is_est = exact is None
    metrics = format_render_metrics(render_s, cost_usd, cost_is_estimate=is_est)
    cost_lbl = format_cost_label(cost_usd, estimate=is_est)

    is_t2i = mode == "text_to_image" or spec.mode == "text_to_image"
    if is_t2i:
        urls = extract_image_urls(result)
        out_url = urls[0] if urls else None
        if not out_url:
            # Nested {image: {url}} already handled in extract_image_urls
            img = result.get("image") if isinstance(result, dict) else None
            if isinstance(img, dict) and img.get("url"):
                out_url = str(img["url"])
            elif isinstance(img, str):
                out_url = img
        if not out_url:
            return VisionResult(
                ok=False,
                model_key=spec.key,
                endpoint=spec.endpoint,
                status=f"{spec.label}: fal returned no image.",
                cost_label=cost_lbl,
                metrics_line=metrics,
            )
        ext = ".jpg"
        low = out_url.lower().split("?")[0]
        if low.endswith(".png"):
            ext = ".png"
        elif low.endswith(".webp"):
            ext = ".webp"
        kind_tag = "creative-vision-t2i"
        job_kind = "image"
        scenario = "creative_vision_t2i"
        media_word = "image"
    else:
        out_url = extract_video_url(result)
        if not out_url:
            return VisionResult(
                ok=False,
                model_key=spec.key,
                endpoint=spec.endpoint,
                status=f"{spec.label}: fal returned no video.",
                cost_label=cost_lbl,
                metrics_line=metrics,
            )
        ext = ".mp4"
        kind_tag = "creative-vision"
        job_kind = "creative_vision"
        scenario = "creative_vision"
        media_word = "video"

    stamp = timestamp_now()
    media_dir = job_media_dir(output_dir, stamp=stamp)
    stem = make_output_stem(
        prompt or "vision",
        spec.key,
        stamp=stamp,
        kind=kind_tag,
    )
    dest = unique_path(media_dir, stem, ext)

    try:
        download_url(out_url, dest, on_progress=progress, timeout=900.0)
    except FalClientError as exc:
        return VisionResult(
            ok=False,
            model_key=spec.key,
            endpoint=spec.endpoint,
            status=str(exc),
            cost_label=cost_lbl,
            metrics_line=metrics,
            timestamp=stamp,
        )

    resolved = str(dest.resolve())
    status = (
        f"{spec.label} OK. Saved {Path(resolved).name} → {media_dir.name}/. "
        f"{metrics}. "
        + (
            "Send to Start / End frame for a bridge, or Studio Image."
            if is_t2i
            else "Use Show in folder or Send to Resolve."
        )
    )

    try:
        append_history(
            job_kind=job_kind,
            model=spec.label,
            prompt=prompt or "",
            files=[resolved],
            cost_estimate=cost_lbl,
            notes=[spec.notes] if spec.notes else [f"mode={mode}"],
            output_dir=output_dir,
            timestamp=stamp,
            scenario=scenario,
        )
    except Exception:
        pass

    return VisionResult(
        ok=True,
        path=resolved,
        model_key=spec.key,
        endpoint=spec.endpoint,
        status=status,
        notes=[spec.notes] if spec.notes else [],
        cost_label=cost_lbl,
        metrics_line=metrics,
        timestamp=stamp,
    )
