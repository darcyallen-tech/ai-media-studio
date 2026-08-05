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
    extract_draft_cache_url,
    extract_video_url,
    subscribe,
    upload_file,
)
from media_studio.fal.models import (
    build_i2v_arguments,
    default_i2v_model,
    resolve_video_model,
)
from media_studio.flux3_draft import (
    draft_endpoint_for,
    estimate_draft_cost_usd,
    model_supports_draft,
    strip_omitted_aspect,
    strip_resolution_for_draft,
)
from media_studio.naming import job_media_dir, make_output_stem, timestamp_now, unique_path
from media_studio.pricing import format_job_cost, format_render_metrics, resolve_generation_cost

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
    is_draft: bool = False
    draft_cache_url: str | None = None


def run_image_to_video(
    *,
    prompt: str,
    image_path: str | Path | None = None,
    model_choice: str | None = None,
    parameters: dict[str, Any] | None = None,
    output_dir: str | Path,
    on_progress: ProgressCallback | None = None,
    scenario: str | None = None,
    extra_image_paths: list[str | Path] | None = None,
    ref_video_paths: list[str | Path] | None = None,
    ref_audio_paths: list[str | Path] | None = None,
) -> ImageToVideoResult:
    prompt = (prompt or "").strip()
    ipath = Path(image_path) if image_path else None

    spec = resolve_video_model(model_choice)
    if spec is None or spec.task != "image_to_video":
        spec = default_i2v_model()
        auto_note = f"Using default I2V model: {spec.label}."
    else:
        auto_note = None

    is_omni = bool(getattr(spec, "ref_image_field", None)) and (
        "reference-to-video" in (spec.endpoint or "")
    )
    has_still = bool(ipath and ipath.is_file())
    has_vrefs = bool(
        ref_video_paths
        or (parameters or {}).get("video_urls")
        or (parameters or {}).get("reference_video_urls")
    )
    if not has_still and not (is_omni and has_vrefs):
        return ImageToVideoResult(
            ok=False,
            status=(
                "Generate (image-to-video): upload a still as the start frame."
                if not is_omni
                else "MiniMax H3 omni needs at least one reference still or motion clip."
            ),
        )

    def progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    progress(f"Model: {spec.label} ({spec.endpoint})")
    if has_still:
        progress(f"Start frame: {ipath.name}")  # type: ignore[union-attr]

    notes: list[str] = []
    if auto_note:
        notes.append(auto_note)

    params = dict(parameters or {})
    try:
        image_url = ""
        if has_still and ipath is not None:
            image_url = upload_file(ipath, on_progress=progress)

        # Extra stills (multi-ref / omni Image 2+)
        extra_urls: list[str] = []
        cap_img = max(1, int(getattr(spec, "max_ref_images", 1) or 1))
        for raw in extra_image_paths or []:
            if len(extra_urls) + (1 if image_url else 0) >= cap_img:
                break
            try:
                p = Path(raw)
                if not p.is_file():
                    continue
                if has_still and ipath and p.resolve() == ipath.resolve():
                    continue
                progress(f"Uploading ref still: {p.name}")
                extra_urls.append(upload_file(p, on_progress=progress))
            except Exception as exc:
                progress(f"Skip ref still {raw}: {exc}")
        if extra_urls:
            params["image_urls"] = extra_urls

        # Optional end frame (first→last) — local path in parameters
        end_local = params.pop("end_image_path", None) or params.pop(
            "end_image_file", None
        )
        if end_local and Path(str(end_local)).is_file() and (
            getattr(spec, "supports_end_frame", False)
            or "minimax/h3" in (spec.endpoint or "")
            or "hailuo" in (spec.endpoint or "")
        ):
            progress(f"Uploading end frame: {Path(str(end_local)).name}")
            params["end_image_url"] = upload_file(
                Path(str(end_local)), on_progress=progress
            )

        # Reference videos (omni / Seedance)
        v_urls: list[str] = list(
            params.get("video_urls") or params.get("reference_video_urls") or []
        )
        if isinstance(v_urls, str):
            v_urls = [v_urls]
        cap_v = max(0, int(getattr(spec, "max_ref_videos", 0) or 0)) or 3
        for raw in ref_video_paths or []:
            if len(v_urls) >= cap_v:
                break
            try:
                p = Path(raw)
                if not p.is_file():
                    continue
                progress(f"Uploading ref video: {p.name}")
                v_urls.append(upload_file(p, on_progress=progress))
            except Exception as exc:
                progress(f"Skip ref video {raw}: {exc}")
        if v_urls:
            if getattr(spec, "ref_video_field", None):
                params["reference_video_urls"] = v_urls[:cap_v]
            else:
                params["video_urls"] = v_urls[:cap_v]

        # Reference audio (H3 omni)
        a_urls: list[str] = list(
            params.get("audio_urls") or params.get("reference_audio_urls") or []
        )
        if isinstance(a_urls, str):
            a_urls = [a_urls]
        cap_a = max(0, int(getattr(spec, "max_ref_audios", 0) or 0))
        for raw in ref_audio_paths or []:
            if cap_a and len(a_urls) >= cap_a:
                break
            try:
                p = Path(raw)
                if not p.is_file():
                    continue
                progress(f"Uploading ref audio: {p.name}")
                a_urls.append(upload_file(p, on_progress=progress))
            except Exception as exc:
                progress(f"Skip ref audio {raw}: {exc}")
        if a_urls and getattr(spec, "ref_audio_field", None):
            params["reference_audio_urls"] = a_urls[: max(1, cap_a or 3)]

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
            parameters=params,
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

    # FLUX 3 draft: cheaper /draft endpoint (no resolution); keep draft_cache for enhance
    use_draft = bool(params.get("draft") or params.get("draft_first"))
    draft_ep = draft_endpoint_for(spec) if use_draft else None
    if use_draft and not draft_ep:
        notes.append("Draft not available for this model — running full quality.")
        use_draft = False
    endpoint = draft_ep if (use_draft and draft_ep) else spec.endpoint
    if use_draft:
        arguments = strip_resolution_for_draft(arguments)
        progress(f"Running DRAFT image-to-video on fal… ({endpoint})")
    else:
        progress("Running image-to-video on fal…")
    # Hard omit aspect_ratio for FLUX 3 I2V full + draft (never send, even auto)
    arguments = strip_omitted_aspect(arguments, endpoint=endpoint)
    arguments = strip_omitted_aspect(
        arguments, endpoint=getattr(spec, "endpoint", None)
    )
    if "aspect_ratio" in arguments and (
        "flux-3/image-to-video" in (endpoint or "").lower()
    ):
        arguments.pop("aspect_ratio", None)
        notes.append(
            "aspect_ratio stripped before submit — FLUX 3 I2V/draft rejects it."
        )

    t0 = time.perf_counter()
    try:
        result = subscribe(endpoint, arguments, on_progress=progress)
    except FalClientError as exc:
        render_s = time.perf_counter() - t0
        return ImageToVideoResult(
            ok=False,
            model_key=spec.key,
            endpoint=endpoint,
            status=str(exc),
            notes=notes,
            render_seconds=render_s,
            metrics_line=format_render_metrics(render_s, None, cost_is_estimate=True),
        )
    render_s = time.perf_counter() - t0

    draft_cache = extract_draft_cache_url(result) if use_draft else None
    if use_draft:
        # Duration for draft cost estimate
        dur_raw = arguments.get("duration") or params.get("duration") or 8
        try:
            if str(dur_raw).lower() == "auto":
                dur_s = 8.0
            else:
                dur_s = float(str(dur_raw).replace("s", ""))
        except (TypeError, ValueError):
            dur_s = 8.0
        cost_usd = estimate_draft_cost_usd(spec, duration_s=dur_s)
        is_est = True
        if cost_usd is not None:
            cost_str = format_job_cost(
                cost_usd, unit=f"{int(round(dur_s))}s draft", model=spec.label
            )
        else:
            cost_str = ""
        notes.append("Draft preview — use Enhance to full when ready.")
    else:
        cost_usd, is_est = resolve_generation_cost(
            result,
            model_key=spec.key,
            job_kind="image_to_video",
            parameters=parameters,
        )
        cost_str = ""
    metrics = format_render_metrics(render_s, cost_usd, cost_is_estimate=is_est)
    if not cost_str:
        cost_str = metrics.split(" · ")[-1] if " · " in metrics else metrics
    if cost_usd is not None:
        notes.append(cost_str)

    out_url = extract_video_url(result)
    if not out_url:
        return ImageToVideoResult(
            ok=False,
            model_key=spec.key,
            endpoint=endpoint,
            status="Generate: fal returned no video.",
            notes=notes,
            cost_estimate=cost_str if cost_usd is not None else "",
            render_seconds=render_s,
            metrics_line=metrics,
            is_draft=use_draft,
            draft_cache_url=draft_cache,
        )

    stamp = timestamp_now()
    media_dir = job_media_dir(output_dir, stamp=stamp)
    kind_tag = "i2v-draft" if use_draft else "i2v"
    stem = make_output_stem(
        prompt or "i2v", spec.key, stamp=stamp, kind=kind_tag, scenario=scenario
    )
    dest = unique_path(media_dir, stem, ".mp4")

    try:
        download_url(out_url, dest, on_progress=progress, timeout=600.0)
    except FalClientError as exc:
        return ImageToVideoResult(
            ok=False,
            model_key=spec.key,
            endpoint=endpoint,
            status=str(exc),
            notes=notes,
            cost_estimate=cost_str if cost_usd is not None else "",
            timestamp=stamp,
            render_seconds=render_s,
            metrics_line=metrics,
            is_draft=use_draft,
            draft_cache_url=draft_cache,
        )

    resolved = str(dest.resolve())
    mode_lbl = "draft" if use_draft else "image-to-video"
    status_parts = [
        f"Generate OK — {spec.label} ({mode_lbl}).",
        f"Saved {Path(resolved).name} → {media_dir.name}/.",
        metrics + ".",
    ]
    if use_draft and draft_cache:
        status_parts.append("Draft cache ready for Enhance to full.")
    other = [n for n in notes if n != cost_str]
    if other:
        status_parts.append("Notes: " + "; ".join(other))

    return ImageToVideoResult(
        ok=True,
        path=resolved,
        model_key=spec.key,
        endpoint=endpoint,
        status=" ".join(status_parts),
        notes=notes,
        cost_estimate=cost_str if cost_usd is not None else "",
        timestamp=stamp,
        render_seconds=render_s,
        metrics_line=metrics,
        is_draft=use_draft,
        draft_cache_url=draft_cache,
    )
