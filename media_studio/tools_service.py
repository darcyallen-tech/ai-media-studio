"""Run Tools-tab utilities (upscale / cleanup / sky / relight / restore) via fal."""

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
from media_studio.naming import job_media_dir, make_output_stem, timestamp_now, unique_path
from media_studio.pricing import (
    extract_cost_usd_from_response,
    format_cost_label,
    format_render_metrics,
)
from media_studio.tools_registry import (
    AMENITY_MODELS,
    BLOWN_OUT_MODELS,
    CLEANUP_MODELS,
    DEHAZE_MODELS,
    INPAINT_MODELS,
    MATCH_LOOK_MODELS,
    MIRROR_MODELS,
    REASPECT_IMAGE_MODELS,
    REASPECT_VIDEO_MODELS,
    RELIGHT_MODELS,
    RESTORE_VIDEO_MODELS,
    SEASON_MODELS,
    SKY_MODELS,
    UPSCALERS,
    VIDEO_AMENITY_MODELS,
    VIDEO_CLEANUP_MODELS,
    VIDEO_DENOISE_MODELS,
    VIDEO_INTERPOLATE_MODELS,
    VIDEO_MIRROR_MODELS,
    VIDEO_SKY_MODELS,
    VIDEO_UPSCALERS,
    ToolSpec,
    amenity_prompt,
    blown_out_prompt,
    build_codeformer_args,
    build_nafnet_deblur_args,
    build_edit_args,
    build_inpaint_args,
    build_upscale_args,
    build_video_denoise_args,
    build_video_interpolate_args,
    build_video_upscale_args,
    cleanup_prompt,
    dehaze_prompt,
    estimate_video_denoise_cost,
    estimate_video_interpolate_cost,
    estimate_video_upscale_cost,
    find_tool,
    format_tool_cost,
    format_video_denoise_cost,
    format_video_interpolate_cost,
    format_video_upscale_cost,
    match_look_prompt,
    mirror_prompt,
    parse_aspect_choice,
    reaspect_prompt,
    relight_prompt,
    restore_image_registry,
    restore_prompt,
    season_tool_prompt,
    sky_prompt,
    video_cleanup_prompt,
    video_sky_prompt,
)

ProgressCallback = Callable[[str], None]


@dataclass
class ToolResult:
    ok: bool
    path: str | None = None
    paths: list[str] = field(default_factory=list)
    status: str = ""
    metrics_line: str = ""
    cost_label: str = ""
    notes: list[str] = field(default_factory=list)


def _extract_single_image(result: dict[str, Any]) -> str | None:
    urls = extract_image_urls(result)
    if urls:
        return urls[0]
    # Topaz returns {image: {url}}
    img = result.get("image")
    if isinstance(img, dict) and img.get("url"):
        return str(img["url"])
    if isinstance(img, str):
        return img
    return None


def _run_tool(
    *,
    spec: ToolSpec,
    image_path: str | Path,
    arguments: dict[str, Any],
    output_dir: str | Path,
    prompt_for_name: str,
    kind: str,
    on_progress: ProgressCallback | None = None,
) -> ToolResult:
    def progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    path = Path(image_path)
    if not path.is_file():
        return ToolResult(ok=False, status="Upload an image first.")

    est = format_tool_cost(spec)
    progress(f"{spec.label} · {est}")
    progress(f"Endpoint: {spec.endpoint}")

    try:
        url = upload_file(path, on_progress=progress)
    except (FalClientError, Exception) as exc:
        return ToolResult(ok=False, status=friendly_error(exc, context=spec.label), cost_label=est)

    # Inject uploaded URL into arguments (replace placeholder keys if needed)
    args = dict(arguments)
    if "image_url" in args and not str(args.get("image_url", "")).startswith("http"):
        args["image_url"] = url
    if "image_urls" in args:
        args["image_urls"] = [url]
    if "image_url" not in args and "image_urls" not in args:
        args["image_url"] = url

    progress("Running on fal…")
    t0 = time.perf_counter()
    try:
        result = subscribe(spec.endpoint, args, on_progress=progress)
    except FalClientError as exc:
        render_s = time.perf_counter() - t0
        return ToolResult(
            ok=False,
            status=str(exc),
            metrics_line=format_render_metrics(render_s, None, cost_is_estimate=True),
            cost_label=est,
        )
    render_s = time.perf_counter() - t0

    exact = extract_cost_usd_from_response(result)
    cost_usd = exact if exact is not None else spec.cost_estimate_usd
    is_est = exact is None
    metrics = format_render_metrics(render_s, cost_usd, cost_is_estimate=is_est)
    cost_lbl = format_cost_label(cost_usd, estimate=is_est)

    out_url = _extract_single_image(result)
    if not out_url:
        return ToolResult(
            ok=False,
            status=f"{spec.label}: fal returned no image.",
            metrics_line=metrics,
            cost_label=cost_lbl,
        )

    stamp = timestamp_now()
    media_dir = job_media_dir(output_dir, stamp=stamp)
    stem = make_output_stem(prompt_for_name, spec.key, stamp=stamp, kind=kind)
    dest = unique_path(media_dir, stem, ".png")

    try:
        download_url(out_url, dest, on_progress=progress)
    except FalClientError as exc:
        return ToolResult(
            ok=False,
            status=str(exc),
            metrics_line=metrics,
            cost_label=cost_lbl,
        )

    resolved = str(dest.resolve())
    status = (
        f"{spec.label} OK. Saved {Path(resolved).name} → {media_dir}. "
        f"{metrics}. Use Show in folder or Send to Resolve."
    )
    _index_tool_result(
        kind=kind,
        model=spec.label,
        prompt=prompt_for_name,
        path=resolved,
        cost=cost_lbl,
        output_dir=output_dir,
        stamp=stamp,
    )
    return ToolResult(
        ok=True,
        path=resolved,
        status=status,
        metrics_line=metrics,
        cost_label=cost_lbl,
        notes=[spec.notes] if spec.notes else [],
    )


def _index_tool_result(
    *,
    kind: str,
    model: str,
    prompt: str,
    path: str,
    cost: str,
    output_dir: str | Path,
    stamp: str | None = None,
) -> None:
    try:
        from media_studio.history import append_history

        is_vid = Path(path).suffix.lower() in {
            ".mp4",
            ".mov",
            ".webm",
            ".m4v",
            ".mkv",
        }
        append_history(
            job_kind="video" if is_vid else "image",
            model=model,
            prompt=prompt or kind,
            files=[path],
            cost_estimate=cost,
            output_dir=output_dir,
            timestamp=stamp,
            scenario=kind,
        )
    except Exception:
        pass


def run_upscale(
    *,
    image_path: str | None,
    model_label: str | None,
    upscale_factor: float = 2.0,
    output_dir: str | Path,
    on_progress: ProgressCallback | None = None,
) -> ToolResult:
    spec = find_tool(model_label, UPSCALERS)
    if not spec:
        return ToolResult(ok=False, status="Choose an upscaler.")
    if not image_path:
        return ToolResult(ok=False, status="Upload an image to upscale.")
    # Need URL in args — build with placeholder then _run_tool overwrites after upload
    args = build_upscale_args(spec, "pending", upscale_factor=upscale_factor)
    return _run_tool(
        spec=spec,
        image_path=image_path,
        arguments=args,
        output_dir=output_dir,
        prompt_for_name=f"upscale-{spec.key}-x{upscale_factor}",
        kind="upscale",
        on_progress=on_progress,
    )


def run_video_upscale(
    *,
    video_path: str | None,
    model_label: str | None,
    target_label: str | None = None,
    duration_s: float = 8.0,
    output_dir: str | Path,
    on_progress: ProgressCallback | None = None,
) -> ToolResult:
    """Upscale a source video with fal video upscalers (not image endpoints)."""
    def progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    spec = find_tool(model_label, VIDEO_UPSCALERS)
    if not spec:
        return ToolResult(ok=False, status="Choose a video upscaler.")
    path = Path(video_path) if video_path else None
    if not path or not path.is_file():
        return ToolResult(ok=False, status="Upload a video to upscale.")

    # Warn on huge camera masters (upload always from local)
    try:
        size_mb = path.stat().st_size / (1024 * 1024)
    except OSError:
        size_mb = 0.0
    if size_mb > 400:
        progress(
            f"Warning: large file ({size_mb:.0f} MB). Upload may be slow — "
            "prefer a graded proxy for camera masters."
        )
    elif size_mb > 150:
        progress(f"Large video ({size_mb:.0f} MB) — uploading from local path…")

    est_usd = estimate_video_upscale_cost(
        spec, target_label=target_label, duration_s=duration_s
    )
    est = format_video_upscale_cost(
        spec, target_label=target_label, duration_s=duration_s
    )
    progress(f"{spec.label} · {est}")
    progress(f"Endpoint: {spec.endpoint}")

    try:
        video_url = upload_file(path, on_progress=progress)
    except (FalClientError, Exception) as exc:
        return ToolResult(
            ok=False,
            status=friendly_error(exc, context=spec.label),
            cost_label=est,
        )

    args = build_video_upscale_args(spec, video_url, target_label=target_label)
    progress("Running video upscale on fal…")
    t0 = time.perf_counter()
    try:
        result = subscribe(spec.endpoint, args, on_progress=progress)
    except FalClientError as exc:
        render_s = time.perf_counter() - t0
        return ToolResult(
            ok=False,
            status=str(exc),
            metrics_line=format_render_metrics(render_s, None, cost_is_estimate=True),
            cost_label=est,
        )
    render_s = time.perf_counter() - t0

    exact = extract_cost_usd_from_response(result)
    cost_usd = exact if exact is not None else est_usd
    is_est = exact is None
    metrics = format_render_metrics(render_s, cost_usd, cost_is_estimate=is_est)
    cost_lbl = format_cost_label(cost_usd, estimate=is_est)

    out_url = extract_video_url(result)
    if not out_url:
        # Some endpoints nest under video.url already handled; try image fallbacks no-op
        return ToolResult(
            ok=False,
            status=f"{spec.label}: fal returned no video.",
            metrics_line=metrics,
            cost_label=cost_lbl,
        )

    stamp = timestamp_now()
    media_dir = job_media_dir(output_dir, stamp=stamp)
    target_bit = (target_label or "upscale").split()[0].replace("(", "").replace(")", "")
    stem = make_output_stem(
        f"vupscale-{spec.key}-{target_bit}",
        spec.key,
        stamp=stamp,
        kind="video-upscale",
    )
    dest = unique_path(media_dir, stem, ".mp4")

    try:
        download_url(out_url, dest, on_progress=progress)
    except FalClientError as exc:
        return ToolResult(
            ok=False,
            status=str(exc),
            metrics_line=metrics,
            cost_label=cost_lbl,
        )

    resolved = str(dest.resolve())
    status = (
        f"{spec.label} OK. Saved {Path(resolved).name} → {media_dir}. "
        f"{metrics}. Use Show in folder or Send to Resolve."
    )
    _index_tool_result(
        kind="video-upscale",
        model=spec.label,
        prompt=f"vupscale-{spec.key}",
        path=resolved,
        cost=cost_lbl,
        output_dir=output_dir,
        stamp=stamp,
    )
    return ToolResult(
        ok=True,
        path=resolved,
        status=status,
        metrics_line=metrics,
        cost_label=cost_lbl,
        notes=[spec.notes] if spec.notes else [],
    )


def _run_video_tool(
    *,
    spec: ToolSpec,
    video_path: str | Path,
    arguments: dict[str, Any],
    output_dir: str | Path,
    prompt_for_name: str,
    kind: str,
    est_usd: float,
    est_label: str,
    on_progress: ProgressCallback | None = None,
) -> ToolResult:
    """Shared upload → subscribe → download path for V2V tools (denoise, interpolate)."""

    def progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    path = Path(video_path)
    if not path.is_file():
        return ToolResult(ok=False, status="Upload a video first.")

    try:
        size_mb = path.stat().st_size / (1024 * 1024)
    except OSError:
        size_mb = 0.0
    if size_mb > 400:
        progress(
            f"Warning: large file ({size_mb:.0f} MB). Prefer a graded proxy for masters."
        )
    elif size_mb > 150:
        progress(f"Large video ({size_mb:.0f} MB) — uploading…")

    progress(f"{spec.label} · {est_label}")
    progress(f"Endpoint: {spec.endpoint}")

    try:
        video_url = upload_file(path, on_progress=progress)
    except (FalClientError, Exception) as exc:
        return ToolResult(
            ok=False,
            status=friendly_error(exc, context=spec.label),
            cost_label=est_label,
        )

    args = dict(arguments)
    args["video_url"] = video_url
    progress("Running on fal…")
    t0 = time.perf_counter()
    try:
        result = subscribe(spec.endpoint, args, on_progress=progress)
    except FalClientError as exc:
        render_s = time.perf_counter() - t0
        return ToolResult(
            ok=False,
            status=str(exc),
            metrics_line=format_render_metrics(render_s, None, cost_is_estimate=True),
            cost_label=est_label,
        )
    render_s = time.perf_counter() - t0

    exact = extract_cost_usd_from_response(result)
    cost_usd = exact if exact is not None else est_usd
    is_est = exact is None
    metrics = format_render_metrics(render_s, cost_usd, cost_is_estimate=is_est)
    cost_lbl = format_cost_label(cost_usd, estimate=is_est)

    out_url = extract_video_url(result)
    if not out_url:
        return ToolResult(
            ok=False,
            status=f"{spec.label}: fal returned no video.",
            metrics_line=metrics,
            cost_label=cost_lbl,
        )

    stamp = timestamp_now()
    media_dir = job_media_dir(output_dir, stamp=stamp)
    stem = make_output_stem(prompt_for_name, spec.key, stamp=stamp, kind=kind)
    dest = unique_path(media_dir, stem, ".mp4")

    try:
        download_url(out_url, dest, on_progress=progress)
    except FalClientError as exc:
        return ToolResult(
            ok=False,
            status=str(exc),
            metrics_line=metrics,
            cost_label=cost_lbl,
        )

    resolved = str(dest.resolve())
    status = (
        f"{spec.label} OK. Saved {Path(resolved).name} → {media_dir}. "
        f"{metrics}. Use Show in folder or Send to Resolve."
    )
    _index_tool_result(
        kind=kind,
        model=spec.label,
        prompt=prompt_for_name,
        path=resolved,
        cost=cost_lbl,
        output_dir=output_dir,
        stamp=stamp,
    )
    return ToolResult(
        ok=True,
        path=resolved,
        status=status,
        metrics_line=metrics,
        cost_label=cost_lbl,
        notes=[spec.notes] if spec.notes else [],
    )


def run_video_denoise(
    *,
    video_path: str | None,
    model_label: str | None = None,
    noise: float | None = 0.35,
    compression: float | None = 0.25,
    recover_detail: float | None = 0.2,
    halo: float | None = None,
    upscale_factor: float = 1.0,
    duration_s: float = 8.0,
    output_dir: str | Path,
    on_progress: ProgressCallback | None = None,
) -> ToolResult:
    """Topaz Nyx / Artemis denoise-clean pass (control-driven, no long prompt)."""
    spec = find_tool(model_label, VIDEO_DENOISE_MODELS)
    if not spec:
        return ToolResult(ok=False, status="Choose a denoise model (Nyx / Artemis).")
    path = Path(video_path) if video_path else None
    if not path or not path.is_file():
        return ToolResult(ok=False, status="Upload a clip to denoise.")

    est_usd = estimate_video_denoise_cost(
        spec, duration_s=duration_s, upscale_factor=upscale_factor
    )
    est = format_video_denoise_cost(
        spec, duration_s=duration_s, upscale_factor=upscale_factor
    )
    # Placeholder URL filled in _run_video_tool after upload
    args = build_video_denoise_args(
        spec,
        "pending",
        noise=noise,
        compression=compression,
        recover_detail=recover_detail,
        halo=halo,
        upscale_factor=upscale_factor,
    )
    return _run_video_tool(
        spec=spec,
        video_path=path,
        arguments=args,
        output_dir=output_dir,
        prompt_for_name=f"vdenoise-{spec.key}",
        kind="video-denoise",
        est_usd=est_usd,
        est_label=est,
        on_progress=on_progress,
    )


def run_video_interpolate(
    *,
    video_path: str | None,
    model_label: str | None = None,
    factor_label: str | None = None,
    use_scene_detection: bool = False,
    duration_s: float = 8.0,
    output_dir: str | Path,
    on_progress: ProgressCallback | None = None,
) -> ToolResult:
    """RIFE / FILM frame interpolation (smooth fps or short slow-mo)."""
    spec = find_tool(model_label, VIDEO_INTERPOLATE_MODELS)
    if not spec:
        return ToolResult(ok=False, status="Choose an interpolate model (RIFE / FILM).")
    path = Path(video_path) if video_path else None
    if not path or not path.is_file():
        return ToolResult(ok=False, status="Upload a clip to interpolate.")

    est_usd = estimate_video_interpolate_cost(
        spec, duration_s=duration_s, factor_label=factor_label
    )
    est = format_video_interpolate_cost(
        spec, duration_s=duration_s, factor_label=factor_label
    )
    args = build_video_interpolate_args(
        spec,
        "pending",
        factor_label=factor_label,
        use_scene_detection=use_scene_detection,
        use_calculated_fps=True,
    )
    return _run_video_tool(
        spec=spec,
        video_path=path,
        arguments=args,
        output_dir=output_dir,
        prompt_for_name=f"vinterp-{spec.key}",
        kind="video-interpolate",
        est_usd=est_usd,
        est_label=est,
        on_progress=on_progress,
    )


def run_cleanup(
    *,
    image_path: str | None = None,
    video_path: str | None = None,
    mode: str = "image",
    model_label: str | None = None,
    prompt: str | None = None,
    strength: float = 0.7,
    output_dir: str | Path,
    on_progress: ProgressCallback | None = None,
) -> ToolResult:
    mode_l = (mode or "image").strip().lower()
    if mode_l == "video":
        return _run_v2v_tool(
            video_path=video_path,
            model_label=model_label,
            registry=VIDEO_CLEANUP_MODELS,
            video_model_map={
                "kling o3 standard clean": "kling o3 standard edit",
                "kling o3 pro clean": "kling o3 pro edit",
                "seedance v2v clean": "seedance 2.0 v2v",
                "grok video clean": "grok imagine edit video",
            },
            prompt=video_cleanup_prompt(prompt),
            output_dir=output_dir,
            scenario="cleanup",
            on_progress=on_progress,
            empty_status="Upload a video to remove people/cars/clutter.",
        )
    spec = find_tool(model_label, CLEANUP_MODELS)
    if not spec:
        return ToolResult(ok=False, status="Choose a cleanup model.")
    if not image_path:
        return ToolResult(ok=False, status="Upload an image to clean up.")
    full_prompt = cleanup_prompt(prompt, strength=strength)
    args = build_edit_args(spec, "pending", full_prompt, strength=strength)
    return _run_tool(
        spec=spec,
        image_path=image_path,
        arguments=args,
        output_dir=output_dir,
        prompt_for_name=full_prompt,
        kind="cleanup",
        on_progress=on_progress,
    )


def run_sky(
    *,
    image_path: str | None = None,
    video_path: str | None = None,
    mode: str = "image",
    model_label: str | None = None,
    sky_preset: str | None = None,
    custom_prompt: str | None = None,
    prompt: str | None = None,  # alias from DualMedia cards
    time_of_day: str | None = None,
    output_dir: str | Path,
    on_progress: ProgressCallback | None = None,
) -> ToolResult:
    mode_l = (mode or "image").strip().lower()
    note = custom_prompt if custom_prompt is not None else prompt
    if mode_l == "video":
        return _run_v2v_tool(
            video_path=video_path,
            model_label=model_label,
            registry=VIDEO_SKY_MODELS,
            video_model_map={
                "kling o3 standard sky": "kling o3 standard edit",
                "kling o3 pro sky": "kling o3 pro edit",
                "seedance v2v sky": "seedance 2.0 v2v",
            },
            prompt=video_sky_prompt(sky_preset, note),
            output_dir=output_dir,
            scenario="sky",
            on_progress=on_progress,
            empty_status="Upload an exterior video for sky/weather pass.",
        )
    spec = find_tool(model_label, SKY_MODELS) or next(iter(SKY_MODELS.values()))
    if not image_path:
        return ToolResult(ok=False, status="Upload an exterior image for sky replacement.")
    full_prompt = sky_prompt(sky_preset, note, time_of_day=time_of_day)
    args = build_edit_args(spec, "pending", full_prompt)
    return _run_tool(
        spec=spec,
        image_path=image_path,
        arguments=args,
        output_dir=output_dir,
        prompt_for_name=full_prompt,
        kind="sky",
        on_progress=on_progress,
    )


def _run_v2v_tool(
    *,
    video_path: str | Path | None,
    model_label: str | None,
    registry: dict[str, ToolSpec],
    video_model_map: dict[str, str],
    prompt: str,
    output_dir: str | Path,
    scenario: str,
    on_progress: ProgressCallback | None = None,
    empty_status: str = "Upload a video first.",
    reference_image: str | None = None,
) -> ToolResult:
    """Shared V2V path via Studio video_edit pipeline."""
    from media_studio.fal.video_edit import run_video_edit

    path = Path(video_path) if video_path else None
    if not path or not path.is_file():
        return ToolResult(ok=False, status=empty_status)
    spec = find_tool(model_label, registry) or next(iter(registry.values()))
    model_choice = video_model_map.get(spec.key, "kling o3 standard edit")
    refs = [reference_image] if reference_image and Path(reference_image).is_file() else None
    result = run_video_edit(
        prompt=prompt,
        video_path=path,
        reference_image_paths=refs,
        model_choice=model_choice,
        parameters={"keep_audio": True},
        output_dir=output_dir,
        on_progress=on_progress,
        scenario=scenario,
    )
    if not result.ok:
        return ToolResult(
            ok=False,
            status=result.status or f"{spec.label} failed.",
            metrics_line=result.metrics_line or "",
            cost_label=result.cost_estimate or format_tool_cost(spec),
            notes=list(result.notes or []),
        )
    tr = ToolResult(
        ok=True,
        path=result.path,
        status=result.status or f"{spec.label} OK.",
        metrics_line=result.metrics_line or "",
        cost_label=result.cost_estimate or format_tool_cost(spec),
        notes=list(result.notes or []) + ([spec.notes] if spec.notes else []),
    )
    if tr.path:
        _index_tool_result(
            kind=scenario,
            model=spec.label,
            prompt=prompt,
            path=tr.path,
            cost=tr.cost_label,
            output_dir=output_dir,
        )
    return tr


def run_mirror(
    *,
    image_path: str | None = None,
    video_path: str | None = None,
    mode: str = "image",
    model_label: str | None = None,
    prompt: str | None = None,
    output_dir: str | Path,
    on_progress: ProgressCallback | None = None,
) -> ToolResult:
    mode_l = (mode or "image").strip().lower()
    full = mirror_prompt(prompt)
    if mode_l == "video":
        return _run_v2v_tool(
            video_path=video_path,
            model_label=model_label,
            registry=VIDEO_MIRROR_MODELS,
            video_model_map={
                "kling o3 standard mirror": "kling o3 standard edit",
                "kling o3 pro mirror": "kling o3 pro edit",
            },
            prompt=full,
            output_dir=output_dir,
            scenario="mirror",
            on_progress=on_progress,
            empty_status="Upload a video for mirror/glass cleanup.",
        )
    spec = find_tool(model_label, MIRROR_MODELS) or next(iter(MIRROR_MODELS.values()))
    if not image_path:
        return ToolResult(ok=False, status="Upload a still with mirror/glass reflection.")
    args = build_edit_args(spec, "pending", full)
    return _run_tool(
        spec=spec,
        image_path=image_path,
        arguments=args,
        output_dir=output_dir,
        prompt_for_name=full,
        kind="mirror",
        on_progress=on_progress,
    )


def run_amenity(
    *,
    image_path: str | None = None,
    video_path: str | None = None,
    mode: str = "image",
    model_label: str | None = None,
    amenity: str | None = None,
    prompt: str | None = None,
    output_dir: str | Path,
    on_progress: ProgressCallback | None = None,
) -> ToolResult:
    mode_l = (mode or "image").strip().lower()
    full = amenity_prompt(amenity, prompt)
    if mode_l == "video":
        return _run_v2v_tool(
            video_path=video_path,
            model_label=model_label,
            registry=VIDEO_AMENITY_MODELS,
            video_model_map={
                "kling o3 standard amenity": "kling o3 standard edit",
            },
            prompt=full,
            output_dir=output_dir,
            scenario="amenity",
            on_progress=on_progress,
            empty_status="Upload a video for amenity activation.",
        )
    spec = find_tool(model_label, AMENITY_MODELS) or next(iter(AMENITY_MODELS.values()))
    if not image_path:
        return ToolResult(ok=False, status="Upload a still to turn on amenities.")
    # Prefer full image-edit pipeline for multi-ref support
    from media_studio.fal.image_edit import run_image_edit

    map_keys = {
        "flux 2 pro amenity": "flux 2 pro",
        "nano banana 2 amenity": "nano banana 2",
        "seedream amenity": "seedream 5 pro",
    }
    model_choice = map_keys.get(spec.key, "flux 2 pro")
    result = run_image_edit(
        prompt=full,
        image_paths=[image_path],
        model_choice=model_choice,
        parameters={"num_images": 1, "output_format": "png"},
        output_dir=output_dir,
        on_progress=on_progress,
        scenario="amenity",
    )
    if not result.ok:
        return ToolResult(
            ok=False,
            status=result.status or "Amenity pass failed.",
            cost_label=result.cost_estimate or format_tool_cost(spec),
        )
    tr = ToolResult(
        ok=True,
        path=result.primary_path,
        status=result.status or f"{spec.label} OK.",
        metrics_line=result.metrics_line or "",
        cost_label=result.cost_estimate or format_tool_cost(spec),
        notes=list(result.notes or []),
    )
    if tr.path:
        _index_tool_result(
            kind="amenity",
            model=spec.label,
            prompt=full,
            path=tr.path,
            cost=tr.cost_label,
            output_dir=output_dir,
        )
    return tr


def run_match_look(
    *,
    result_path: str | None,
    source_path: str | None = None,
    model_label: str | None = None,
    prompt: str | None = None,
    output_dir: str | Path,
    on_progress: ProgressCallback | None = None,
) -> ToolResult:
    """Grade-match an AI plate toward the original source still."""
    res = Path(result_path) if result_path else None
    if not res or not res.is_file():
        return ToolResult(ok=False, status="Need an AI result image to match.")
    full = match_look_prompt(prompt)
    spec = find_tool(model_label, MATCH_LOOK_MODELS) or next(iter(MATCH_LOOK_MODELS.values()))
    from media_studio.fal.image_edit import run_image_edit

    map_keys = {
        "flux 2 pro match": "flux 2 pro",
        "nano banana 2 match": "nano banana 2",
        "seedream match": "seedream 5 pro",
    }
    model_choice = map_keys.get(spec.key, "flux 2 pro")
    paths: list[str | Path] = [res]
    src = Path(source_path) if source_path else None
    if src and src.is_file():
        paths.append(src)
        full = (
            f"{full} "
            "The second image is the original source look reference — "
            "match its white balance, contrast, and grade."
        )
    result = run_image_edit(
        prompt=full,
        image_paths=paths,
        model_choice=model_choice,
        parameters={"num_images": 1, "output_format": "png"},
        output_dir=output_dir,
        on_progress=on_progress,
        scenario="match_look",
    )
    if not result.ok:
        return ToolResult(
            ok=False,
            status=result.status or "Match look failed.",
            cost_label=result.cost_estimate or format_tool_cost(spec),
        )
    tr = ToolResult(
        ok=True,
        path=result.primary_path,
        status=result.status or f"{spec.label} OK.",
        metrics_line=result.metrics_line or "",
        cost_label=result.cost_estimate or format_tool_cost(spec),
        notes=list(result.notes or []),
    )
    if tr.path:
        _index_tool_result(
            kind="match_look",
            model=spec.label,
            prompt=full,
            path=tr.path,
            cost=tr.cost_label,
            output_dir=output_dir,
        )
    return tr


def run_season(
    *,
    image_path: str | None,
    model_label: str | None = None,
    season: str | None = None,
    prompt: str | None = None,
    output_dir: str | Path,
    on_progress: ProgressCallback | None = None,
) -> ToolResult:
    if not image_path:
        return ToolResult(ok=False, status="Upload an exterior still for season / curb appeal.")
    full = season_tool_prompt(season, prompt)
    spec = find_tool(model_label, SEASON_MODELS) or next(iter(SEASON_MODELS.values()))
    from media_studio.fal.image_edit import run_image_edit

    map_keys = {
        "flux 2 pro season": "flux 2 pro",
        "nano banana 2 season": "nano banana 2",
        "seedream season": "seedream 5 pro",
    }
    model_choice = map_keys.get(spec.key, "flux 2 pro")
    result = run_image_edit(
        prompt=full,
        image_paths=[image_path],
        model_choice=model_choice,
        parameters={"num_images": 1, "output_format": "png"},
        output_dir=output_dir,
        on_progress=on_progress,
        scenario="season",
    )
    if not result.ok:
        return ToolResult(
            ok=False,
            status=result.status or "Season pass failed.",
            cost_label=result.cost_estimate or format_tool_cost(spec),
        )
    tr = ToolResult(
        ok=True,
        path=result.primary_path,
        status=result.status or f"{spec.label} OK.",
        metrics_line=result.metrics_line or "",
        cost_label=result.cost_estimate or format_tool_cost(spec),
        notes=list(result.notes or []),
    )
    if tr.path:
        _index_tool_result(
            kind="season",
            model=spec.label,
            prompt=full,
            path=tr.path,
            cost=tr.cost_label,
            output_dir=output_dir,
        )
    return tr


def run_relight(
    *,
    image_path: str | None,
    model_label: str | None,
    prompt: str | None,
    output_dir: str | Path,
    on_progress: ProgressCallback | None = None,
) -> ToolResult:
    spec = find_tool(model_label, RELIGHT_MODELS) or next(iter(RELIGHT_MODELS.values()))
    if not image_path:
        return ToolResult(ok=False, status="Upload an image to relight.")
    full_prompt = relight_prompt(prompt)
    args = build_edit_args(spec, "pending", full_prompt)
    return _run_tool(
        spec=spec,
        image_path=image_path,
        arguments=args,
        output_dir=output_dir,
        prompt_for_name=full_prompt,
        kind="relight",
        on_progress=on_progress,
    )


def run_dehaze(
    *,
    image_path: str | None,
    model_label: str | None,
    prompt: str | None = None,
    strength: float = 0.75,
    output_dir: str | Path,
    on_progress: ProgressCallback | None = None,
) -> ToolResult:
    """Clear smoke / haze / smog — simple upload → clear air → result."""
    spec = find_tool(model_label, DEHAZE_MODELS) or next(iter(DEHAZE_MODELS.values()))
    if not image_path:
        return ToolResult(ok=False, status="Upload an image to dehaze (e.g. smoky exterior).")
    full_prompt = dehaze_prompt(prompt, strength=strength)
    args = build_edit_args(spec, "pending", full_prompt, strength=strength)
    return _run_tool(
        spec=spec,
        image_path=image_path,
        arguments=args,
        output_dir=output_dir,
        prompt_for_name=full_prompt,
        kind="dehaze",
        on_progress=on_progress,
    )


# Map restore ToolSpec keys → IMAGE_EDIT_MODELS keys for the full edit pipeline
_RESTORE_IMAGE_MODEL_MAP: dict[str, str] = {
    "nano banana 2 restore": "nano banana 2",
    "nano banana 2 restore ref": "nano banana 2",
    "nano banana pro restore ref": "nano banana pro",
    "flux kontext restore": "flux kontext pro",
    "grok imagine restore": "grok imagine edit",
    "grok imagine restore ref": "grok imagine edit",
    "seedream restore ref": "seedream 5 pro",
    "flux 2 pro restore ref": "flux 2 pro",
}


def _run_restore_image_edit(
    *,
    spec: ToolSpec,
    image_paths: list[str | Path],
    prompt: str,
    output_dir: str | Path,
    on_progress: ProgressCallback | None = None,
) -> ToolResult:
    """Use the Studio image-edit pipeline (aspect ratio, multi-ref, costs)."""
    from media_studio.fal.image_edit import run_image_edit

    model_choice = _RESTORE_IMAGE_MODEL_MAP.get(spec.key, "nano banana 2")
    result = run_image_edit(
        prompt=prompt,
        image_paths=image_paths,
        model_choice=model_choice,
        parameters={"num_images": 1, "output_format": "png"},
        output_dir=output_dir,
        on_progress=on_progress,
        scenario="restore",
    )
    if not result.ok:
        return ToolResult(
            ok=False,
            status=result.status or "Image restore failed.",
            metrics_line=result.metrics_line or "",
            cost_label=result.cost_estimate or format_tool_cost(spec),
            notes=list(result.notes or []),
        )
    path = result.primary_path
    status = result.status or f"{spec.label} OK."
    if path:
        status = (
            f"{spec.label} OK. Saved {Path(path).name}. "
            f"{result.metrics_line or ''}. Use Show in folder or Send to Resolve."
        )
    return ToolResult(
        ok=True,
        path=path,
        status=status,
        metrics_line=result.metrics_line or "",
        cost_label=result.cost_estimate or format_tool_cost(spec),
        notes=list(result.notes or []) + ([spec.notes] if spec.notes else []),
    )


def run_restore(
    *,
    mode: str = "image",
    source_path: str | None = None,
    reference_path: str | None = None,
    model_label: str | None = None,
    prompt: str | None = None,
    strength: float = 0.75,
    output_dir: str | Path,
    on_progress: ProgressCallback | None = None,
) -> ToolResult:
    """
    Sharpen / Restore — recover soft or out-of-focus people (realtor shots).

    Image + no ref → CodeFormer (or prompt restore models).
    Image + ref → multi-image identity-locked edit.
    Video → V2V edit with optional identity still.
    """
    mode_l = (mode or "image").strip().lower()
    if mode_l not in ("image", "video"):
        return ToolResult(ok=False, status="Mode must be Image or Video.")

    src = Path(source_path) if source_path else None
    if not src or not src.is_file():
        kind = "soft source image" if mode_l == "image" else "soft source video"
        return ToolResult(ok=False, status=f"Upload a {kind} first.")

    ref = Path(reference_path) if reference_path else None
    has_ref = bool(ref and ref.is_file())
    if reference_path and not has_ref:
        return ToolResult(ok=False, status="Reference image path is invalid.")

    full_prompt = restore_prompt(
        prompt,
        has_reference=has_ref,
        strength=float(strength),
        mode=mode_l,
    )

    # --- Video path: reuse video_edit pipeline ---
    if mode_l == "video":
        return _run_restore_video(
            source_path=src,
            reference_path=ref if has_ref else None,
            model_label=model_label,
            prompt=full_prompt,
            output_dir=output_dir,
            on_progress=on_progress,
        )

    # --- Image path ---
    registry = restore_image_registry(has_reference=has_ref)
    spec = find_tool(model_label, registry) or next(iter(registry.values()))

    # CodeFormer: fidelity API (map strength → fidelity); no ref still
    if "codeformer" in spec.endpoint:
        return _run_codeformer(
            spec=spec,
            image_path=src,
            fidelity=float(strength),
            output_dir=output_dir,
            on_progress=on_progress,
        )

    # NAFNet whole-frame deblur; no prompt / no ref still
    if "nafnet" in spec.endpoint:
        return _run_nafnet_deblur(
            spec=spec,
            image_path=src,
            output_dir=output_dir,
            on_progress=on_progress,
        )

    paths: list[Path] = [src]
    if has_ref and ref:
        paths.append(ref)

    return _run_restore_image_edit(
        spec=spec,
        image_paths=paths,
        prompt=full_prompt,
        output_dir=output_dir,
        on_progress=on_progress,
    )


def _run_codeformer(
    *,
    spec: ToolSpec,
    image_path: Path,
    fidelity: float,
    output_dir: str | Path,
    on_progress: ProgressCallback | None = None,
) -> ToolResult:
    def progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    est = format_tool_cost(spec)
    progress(f"{spec.label} · {est}")
    progress(f"Endpoint: {spec.endpoint} · fidelity={fidelity:.2f}")

    try:
        url = upload_file(image_path, on_progress=progress)
    except (FalClientError, Exception) as exc:
        return ToolResult(ok=False, status=friendly_error(exc, context=spec.label), cost_label=est)

    # Higher slider = keep original identity closer (CodeFormer convention)
    args = build_codeformer_args(url, fidelity=fidelity, upscale_factor=1.0)

    progress("Running CodeFormer on fal…")
    t0 = time.perf_counter()
    try:
        result = subscribe(spec.endpoint, args, on_progress=progress)
    except FalClientError as exc:
        render_s = time.perf_counter() - t0
        return ToolResult(
            ok=False,
            status=str(exc),
            metrics_line=format_render_metrics(render_s, None, cost_is_estimate=True),
            cost_label=est,
        )
    render_s = time.perf_counter() - t0

    exact = extract_cost_usd_from_response(result)
    cost_usd = exact if exact is not None else spec.cost_estimate_usd
    is_est = exact is None
    metrics = format_render_metrics(render_s, cost_usd, cost_is_estimate=is_est)
    cost_lbl = format_cost_label(cost_usd, estimate=is_est)

    out_url = _extract_single_image(result)
    if not out_url:
        return ToolResult(
            ok=False,
            status=f"{spec.label}: fal returned no image.",
            metrics_line=metrics,
            cost_label=cost_lbl,
        )

    stamp = timestamp_now()
    media_dir = job_media_dir(output_dir, stamp=stamp)
    stem = make_output_stem(
        f"codeformer-fidelity-{fidelity:.2f}",
        spec.key,
        stamp=stamp,
        kind="restore",
    )
    dest = unique_path(media_dir, stem, ".png")

    try:
        download_url(out_url, dest, on_progress=progress)
    except FalClientError as exc:
        return ToolResult(
            ok=False,
            status=str(exc),
            metrics_line=metrics,
            cost_label=cost_lbl,
        )

    resolved = str(dest.resolve())
    status = (
        f"{spec.label} OK. Saved {Path(resolved).name} → {media_dir}. "
        f"{metrics}. Use Show in folder or Send to Resolve."
    )
    return ToolResult(
        ok=True,
        path=resolved,
        status=status,
        metrics_line=metrics,
        cost_label=cost_lbl,
        notes=[spec.notes] if spec.notes else [],
    )


def _run_nafnet_deblur(
    *,
    spec: ToolSpec,
    image_path: Path,
    output_dir: str | Path,
    on_progress: ProgressCallback | None = None,
) -> ToolResult:
    """fal-ai/nafnet/deblur — whole-frame soft/defocus restore."""

    def progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    est = format_tool_cost(spec)
    progress(f"{spec.label} · {est}")
    progress(f"Endpoint: {spec.endpoint}")

    try:
        url = upload_file(image_path, on_progress=progress)
    except (FalClientError, Exception) as exc:
        return ToolResult(
            ok=False,
            status=friendly_error(exc, context=spec.label),
            cost_label=est,
        )

    args = build_nafnet_deblur_args(url)
    progress("Running NAFNet deblur on fal…")
    t0 = time.perf_counter()
    try:
        result = subscribe(spec.endpoint, args, on_progress=progress)
    except FalClientError as exc:
        render_s = time.perf_counter() - t0
        return ToolResult(
            ok=False,
            status=str(exc),
            metrics_line=format_render_metrics(render_s, None, cost_is_estimate=True),
            cost_label=est,
        )
    render_s = time.perf_counter() - t0

    exact = extract_cost_usd_from_response(result)
    cost_usd = exact if exact is not None else spec.cost_estimate_usd
    is_est = exact is None
    metrics = format_render_metrics(render_s, cost_usd, cost_is_estimate=is_est)
    cost_lbl = format_cost_label(cost_usd, estimate=is_est)

    out_url = _extract_single_image(result)
    if not out_url:
        return ToolResult(
            ok=False,
            status=f"{spec.label}: fal returned no image.",
            metrics_line=metrics,
            cost_label=cost_lbl,
        )

    stamp = timestamp_now()
    media_dir = job_media_dir(output_dir, stamp=stamp)
    stem = make_output_stem("nafnet-deblur", spec.key, stamp=stamp, kind="restore")
    dest = unique_path(media_dir, stem, ".png")

    try:
        download_url(out_url, dest, on_progress=progress)
    except FalClientError as exc:
        return ToolResult(
            ok=False,
            status=str(exc),
            metrics_line=metrics,
            cost_label=cost_lbl,
        )

    resolved = str(dest.resolve())
    status = (
        f"{spec.label} OK. Saved {Path(resolved).name} → {media_dir}. "
        f"{metrics}. Use Show in folder or Send to Resolve."
    )
    try:
        from media_studio.history import append_history

        append_history(
            job_kind="image",
            model=spec.label,
            prompt="NAFNet deblur",
            files=[resolved],
            cost_estimate=cost_lbl,
            notes=["restore", "nafnet"],
            output_dir=output_dir,
            timestamp=stamp,
            scenario="restore",
        )
    except Exception:
        pass
    return ToolResult(
        ok=True,
        path=resolved,
        status=status,
        metrics_line=metrics,
        cost_label=cost_lbl,
        notes=[spec.notes] if spec.notes else [],
    )


def _run_restore_video(
    *,
    source_path: Path,
    reference_path: Path | None,
    model_label: str | None,
    prompt: str,
    output_dir: str | Path,
    on_progress: ProgressCallback | None = None,
) -> ToolResult:
    """Map tool registry choice → fal video_edit pipeline."""
    from media_studio.fal.video_edit import run_video_edit

    spec = find_tool(model_label, RESTORE_VIDEO_MODELS) or next(
        iter(RESTORE_VIDEO_MODELS.values())
    )
    # Map restore ToolSpec → video model keys used by resolve_video_model
    video_model_map = {
        "kling o3 standard restore": "kling o3 standard edit",
        "kling o3 pro restore": "kling o3 pro edit",
        "grok imagine restore video": "grok imagine edit video",
    }
    model_choice = video_model_map.get(spec.key, "kling o3 standard edit")

    refs = [str(reference_path)] if reference_path else None
    # Grok edit-video ignores image refs at API level; still pass for prompt notes
    result = run_video_edit(
        prompt=prompt,
        video_path=source_path,
        reference_image_paths=refs,
        model_choice=model_choice,
        parameters={"keep_audio": True},
        output_dir=output_dir,
        on_progress=on_progress,
        scenario="restore",
    )

    if not result.ok:
        return ToolResult(
            ok=False,
            status=result.status or "Video restore failed.",
            metrics_line=result.metrics_line or "",
            cost_label=result.cost_estimate or format_tool_cost(spec),
            notes=list(result.notes or []),
        )

    return ToolResult(
        ok=True,
        path=result.path,
        status=result.status or f"{spec.label} OK.",
        metrics_line=result.metrics_line or "",
        cost_label=result.cost_estimate or format_tool_cost(spec),
        notes=list(result.notes or []) + ([spec.notes] if spec.notes else []),
    )


# ---------------------------------------------------------------------------
# Blown Out Repair
# ---------------------------------------------------------------------------

_BLOWN_OUT_EDIT_MAP: dict[str, str] = {
    "nano banana 2 blownout": "nano banana 2",
    "nano banana pro blownout": "nano banana pro",
    "flux kontext blownout": "flux kontext pro",
    "flux 2 pro blownout": "flux 2 pro",
    "seedream blownout": "seedream 5 pro",
    "grok imagine blownout": "grok imagine edit",
}


def run_blown_out(
    *,
    image_path: str | None,
    model_label: str | None,
    prompt: str | None = None,
    strength: float = 0.75,
    windows_only: bool = True,
    output_dir: str | Path,
    on_progress: ProgressCallback | None = None,
) -> ToolResult:
    """Repair overexposed / blown-out windows on interior shots."""
    spec = find_tool(model_label, BLOWN_OUT_MODELS) or next(iter(BLOWN_OUT_MODELS.values()))
    if not image_path:
        return ToolResult(ok=False, status="Upload an interior image with blown-out windows.")
    full_prompt = blown_out_prompt(
        prompt, strength=float(strength), windows_only=bool(windows_only)
    )

    # Prefer full image-edit pipeline (aspect / multi-ref handling)
    from media_studio.fal.image_edit import run_image_edit

    model_choice = _BLOWN_OUT_EDIT_MAP.get(spec.key, "nano banana 2")
    result = run_image_edit(
        prompt=full_prompt,
        image_paths=[image_path],
        model_choice=model_choice,
        parameters={"num_images": 1, "output_format": "png"},
        output_dir=output_dir,
        on_progress=on_progress,
        scenario="blownout",
    )
    if not result.ok:
        return ToolResult(
            ok=False,
            status=result.status or "Blown-out repair failed.",
            metrics_line=result.metrics_line or "",
            cost_label=result.cost_estimate or format_tool_cost(spec),
            notes=list(result.notes or []),
        )
    path = result.primary_path
    status = (
        f"{spec.label} OK. Saved {Path(path).name}. {result.metrics_line or ''}. "
        "Use Show in folder or Send to Resolve."
        if path
        else (result.status or "OK")
    )
    return ToolResult(
        ok=True,
        path=path,
        status=status,
        metrics_line=result.metrics_line or "",
        cost_label=result.cost_estimate or format_tool_cost(spec),
        notes=list(result.notes or []) + ([spec.notes] if spec.notes else []),
    )


# ---------------------------------------------------------------------------
# Re-Aspect (image + video)
# ---------------------------------------------------------------------------


def run_reaspect(
    *,
    mode: str = "image",
    source_path: str | None = None,
    model_label: str | None = None,
    aspect_ratio: str | None = None,
    prompt: str | None = None,
    output_dir: str | Path,
    on_progress: ProgressCallback | None = None,
) -> ToolResult:
    """Change aspect ratio via intelligent reframe / outpaint."""
    mode_l = (mode or "image").strip().lower()
    ar = parse_aspect_choice(aspect_ratio or "9:16 (Vertical / Reels)")
    full_prompt = reaspect_prompt(prompt, aspect_ratio=ar, mode=mode_l)
    src = Path(source_path) if source_path else None
    if not src or not src.is_file():
        need = "image" if mode_l == "image" else "video"
        return ToolResult(ok=False, status=f"Upload a source {need} to re-aspect.")

    if mode_l == "video":
        return _run_reaspect_video(
            source_path=src,
            model_label=model_label,
            aspect_ratio=ar,
            prompt=full_prompt,
            output_dir=output_dir,
            on_progress=on_progress,
        )

    return _run_reaspect_image(
        source_path=src,
        model_label=model_label,
        aspect_ratio=ar,
        prompt=full_prompt,
        output_dir=output_dir,
        on_progress=on_progress,
    )


def _run_reaspect_image(
    *,
    source_path: Path,
    model_label: str | None,
    aspect_ratio: str,
    prompt: str,
    output_dir: str | Path,
    on_progress: ProgressCallback | None = None,
) -> ToolResult:
    spec = find_tool(model_label, REASPECT_IMAGE_MODELS) or next(
        iter(REASPECT_IMAGE_MODELS.values())
    )

    def progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    est = format_tool_cost(spec)
    progress(f"{spec.label} · {aspect_ratio} · {est}")

    # Dedicated reframe endpoints
    if "reframe" in spec.endpoint and "nano-banana" not in spec.endpoint and "flux" not in spec.endpoint:
        try:
            url = upload_file(source_path, on_progress=progress)
        except (FalClientError, Exception) as exc:
            return ToolResult(
                ok=False,
                status=friendly_error(exc, context=spec.label),
                cost_label=est,
            )
        args = dict(spec.extra_defaults)
        args["image_url"] = url
        args["aspect_ratio"] = aspect_ratio
        # Some reframe APIs accept optional prompt
        if prompt and "image-editing" not in spec.endpoint:
            args["prompt"] = prompt

        progress("Running reframe on fal…")
        t0 = time.perf_counter()
        try:
            result = subscribe(spec.endpoint, args, on_progress=progress)
        except FalClientError as exc:
            render_s = time.perf_counter() - t0
            return ToolResult(
                ok=False,
                status=str(exc),
                metrics_line=format_render_metrics(render_s, None, cost_is_estimate=True),
                cost_label=est,
            )
        render_s = time.perf_counter() - t0
        exact = extract_cost_usd_from_response(result)
        cost_usd = exact if exact is not None else spec.cost_estimate_usd
        is_est = exact is None
        metrics = format_render_metrics(render_s, cost_usd, cost_is_estimate=is_est)
        cost_lbl = format_cost_label(cost_usd, estimate=is_est)
        out_url = _extract_single_image(result)
        if not out_url:
            return ToolResult(
                ok=False,
                status=f"{spec.label}: fal returned no image.",
                metrics_line=metrics,
                cost_label=cost_lbl,
            )
        stamp = timestamp_now()
        media_dir = job_media_dir(output_dir, stamp=stamp)
        stem = make_output_stem(
            f"reaspect-{aspect_ratio}",
            spec.key,
            stamp=stamp,
            kind="reaspect",
        )
        dest = unique_path(media_dir, stem, ".png")
        try:
            download_url(out_url, dest, on_progress=progress)
        except FalClientError as exc:
            return ToolResult(
                ok=False, status=str(exc), metrics_line=metrics, cost_label=cost_lbl
            )
        resolved = str(dest.resolve())
        return ToolResult(
            ok=True,
            path=resolved,
            status=(
                f"{spec.label} OK → {aspect_ratio}. Saved {Path(resolved).name}. "
                f"{metrics}. Use Show in folder or Send to Resolve."
            ),
            metrics_line=metrics,
            cost_label=cost_lbl,
            notes=[spec.notes] if spec.notes else [],
        )

    # Prompt-based outpaint via image edit models
    from media_studio.fal.image_edit import run_image_edit

    edit_map = {
        "nano banana 2 reaspect": "nano banana 2",
        "flux 2 pro reaspect": "flux 2 pro",
    }
    model_choice = edit_map.get(spec.key, "nano banana 2")
    outpaint_prompt = (
        f"{prompt} Expand / outpaint the canvas to aspect ratio {aspect_ratio}. "
        "Keep the original content centered and intact; only fill new borders."
    )
    result = run_image_edit(
        prompt=outpaint_prompt,
        image_paths=[source_path],
        model_choice=model_choice,
        parameters={"num_images": 1, "output_format": "png", "aspect_ratio": aspect_ratio},
        output_dir=output_dir,
        on_progress=on_progress,
        scenario="reaspect",
    )
    if not result.ok:
        return ToolResult(
            ok=False,
            status=result.status or "Re-aspect failed.",
            metrics_line=result.metrics_line or "",
            cost_label=result.cost_estimate or format_tool_cost(spec),
            notes=list(result.notes or []),
        )
    path = result.primary_path
    return ToolResult(
        ok=True,
        path=path,
        status=(
            f"{spec.label} OK → {aspect_ratio}. Saved {Path(path).name if path else '?'}. "
            f"{result.metrics_line or ''}. Use Show in folder or Send to Resolve."
        ),
        metrics_line=result.metrics_line or "",
        cost_label=result.cost_estimate or format_tool_cost(spec),
        notes=list(result.notes or []) + ([spec.notes] if spec.notes else []),
    )


def _run_reaspect_video(
    *,
    source_path: Path,
    model_label: str | None,
    aspect_ratio: str,
    prompt: str,
    output_dir: str | Path,
    on_progress: ProgressCallback | None = None,
) -> ToolResult:
    spec = find_tool(model_label, REASPECT_VIDEO_MODELS) or next(
        iter(REASPECT_VIDEO_MODELS.values())
    )

    def progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    est = format_tool_cost(spec)
    progress(f"{spec.label} · {aspect_ratio} · {est}")
    progress(f"Endpoint: {spec.endpoint}")

    # Map UI ratios to API enums (LTX supports subset)
    ltx_allowed = {"1:1", "4:5", "5:4", "9:16", "16:9"}
    luma_allowed = {"1:1", "16:9", "9:16", "4:3", "3:4", "21:9", "9:21"}
    ar = aspect_ratio
    if "ltx" in spec.endpoint and ar not in ltx_allowed:
        # Nearest common social mapping
        if ar in ("3:4", "4:3"):
            ar = "4:5" if ar == "3:4" else "16:9"
        elif ar == "21:9":
            ar = "16:9"
        else:
            ar = "9:16" if ar.endswith("16") or "9:" in ar else "16:9"
        progress(f"Aspect {aspect_ratio} → {ar} for LTX Reframe")
    if "luma" in spec.endpoint and ar not in luma_allowed:
        ar = "9:16" if "9:16" in aspect_ratio or aspect_ratio.startswith("9:") else "16:9"

    try:
        video_url = upload_file(source_path, on_progress=progress)
    except (FalClientError, Exception) as exc:
        return ToolResult(
            ok=False,
            status=friendly_error(exc, context=spec.label),
            cost_label=est,
        )

    args = dict(spec.extra_defaults)
    args["video_url"] = video_url
    args["aspect_ratio"] = ar
    if prompt and "luma" in spec.endpoint:
        # Luma may ignore prompt; harmless if rejected
        pass

    progress("Running video reframe on fal (can take several minutes)…")
    t0 = time.perf_counter()
    try:
        result = subscribe(spec.endpoint, args, on_progress=progress)
    except FalClientError as exc:
        render_s = time.perf_counter() - t0
        return ToolResult(
            ok=False,
            status=str(exc),
            metrics_line=format_render_metrics(render_s, None, cost_is_estimate=True),
            cost_label=est,
        )
    render_s = time.perf_counter() - t0
    exact = extract_cost_usd_from_response(result)
    cost_usd = exact if exact is not None else spec.cost_estimate_usd
    is_est = exact is None
    metrics = format_render_metrics(render_s, cost_usd, cost_is_estimate=is_est)
    cost_lbl = format_cost_label(cost_usd, estimate=is_est)

    out_url = extract_video_url(result)
    if not out_url:
        return ToolResult(
            ok=False,
            status=f"{spec.label}: fal returned no video.",
            metrics_line=metrics,
            cost_label=cost_lbl,
        )

    stamp = timestamp_now()
    media_dir = job_media_dir(output_dir, stamp=stamp)
    stem = make_output_stem(
        f"reaspect-{ar}",
        spec.key,
        stamp=stamp,
        kind="reaspect",
    )
    dest = unique_path(media_dir, stem, ".mp4")
    try:
        download_url(out_url, dest, on_progress=progress, timeout=600.0)
    except FalClientError as exc:
        return ToolResult(
            ok=False, status=str(exc), metrics_line=metrics, cost_label=cost_lbl
        )

    resolved = str(dest.resolve())
    return ToolResult(
        ok=True,
        path=resolved,
        status=(
            f"{spec.label} OK → {ar}. Saved {Path(resolved).name}. "
            f"{metrics}. Use Show in folder or Send to Resolve."
        ),
        metrics_line=metrics,
        cost_label=cost_lbl,
        notes=[spec.notes] if spec.notes else [],
    )


def run_inpaint(
    *,
    image_path: str | Path | None,
    mask_path: str | Path | None,
    prompt: str | None = None,
    negative_prompt: str | None = None,
    model_label: str | None = None,
    strength: float | None = None,
    num_images: int = 1,
    reference_path: str | Path | None = None,
    output_dir: str | Path,
    on_progress: ProgressCallback | None = None,
) -> ToolResult:
    """
    Freehand / mask inpaint — only white mask regions are rewritten.

    Requires a non-empty mask (any non-black pixels). Soft-fails with a clear
    message if the mask is blank. Optional ``num_images`` batch and reference
    still when the model supports them.
    """

    def progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    img = Path(image_path) if image_path else None
    mask = Path(mask_path) if mask_path else None
    if not img or not img.is_file():
        return ToolResult(ok=False, status="Upload a source still first.")
    if not mask or not mask.is_file():
        return ToolResult(
            ok=False,
            status="Paint a mask on the region to change, then Run.",
        )

    # Assert sizes, reject empty masks, never send mismatched shapes to fal
    try:
        from PIL import Image
        import numpy as np

        with Image.open(img) as im_src:
            iw, ih = im_src.size
        m = Image.open(mask).convert("L")
        mw, mh = m.size
        size_note = f"image {iw}×{ih}, mask {mw}×{mh}"
        if (mw, mh) != (iw, ih):
            # NEAREST only — soft edges break hard masks for fill models
            progress(
                f"Mask size mismatch ({size_note}) — resizing mask "
                f"NEAREST to {iw}×{ih}"
            )
            m = m.resize((iw, ih), Image.Resampling.NEAREST)
            # Write corrected mask so upload matches image pixels 1:1
            fixed = mask.with_name(
                f"{mask.stem}_sized_{iw}x{ih}{mask.suffix}"
            )
            m.save(fixed, format="PNG")
            mask = fixed
            mw, mh = m.size
            size_note = f"image {iw}×{ih}, mask {mw}×{mh}"
            if (mw, mh) != (iw, ih):
                return ToolResult(
                    ok=False,
                    status=(
                        f"Mask/image size mismatch — refused submit. {size_note}"
                    ),
                )

        arr = np.array(m)  # copy so we can close the image
        m.close()
        if arr.size == 0 or int(arr.max()) < 8:
            return ToolResult(
                ok=False,
                status=(
                    "Mask is empty — paint the region to edit (white = change). "
                    f"({size_note})"
                ),
            )
        # Require a minimum painted area so accidental dots don't burn cost
        painted = int((arr > 16).sum())
        if painted < 24:
            return ToolResult(
                ok=False,
                status=(
                    "Mask is nearly empty — paint a larger region, then Run. "
                    f"({size_note})"
                ),
            )
    except Exception as exc:
        return ToolResult(ok=False, status=f"Could not read mask: {exc}")

    from media_studio.tools_registry import (
        inpaint_max_num,
        inpaint_requires_ref,
        inpaint_shows_ref,
    )

    spec = find_tool(model_label, INPAINT_MODELS) or next(
        iter(INPAINT_MODELS.values())
    )
    max_n = inpaint_max_num(spec)
    n_req = max(1, min(max_n, int(num_images or 1)))
    est = format_tool_cost(spec, num_images=n_req)

    ref_path = Path(reference_path) if reference_path else None
    if inpaint_requires_ref(spec):
        if not ref_path or not ref_path.is_file():
            return ToolResult(
                ok=False,
                status=(
                    f"{spec.label} needs a reference still — "
                    "upload Ref still, then Run."
                ),
                cost_label=est,
            )
    elif ref_path and not inpaint_shows_ref(spec):
        # Ignore ref for models that don't accept one
        ref_path = None
        progress("Reference still ignored — this model only uses image + mask.")

    progress(f"{spec.label} · {est}")
    progress(f"Endpoint: {spec.endpoint}")
    progress(f"Sizes: {size_note}")
    if n_req > 1:
        progress(f"Batch: {n_req} images")

    try:
        progress(f"Uploading source: {img.name}")
        image_url = upload_file(img, on_progress=progress)
        progress(f"Uploading mask: {mask.name}")
        mask_url = upload_file(mask, on_progress=progress)
        ref_url = None
        if ref_path and ref_path.is_file() and inpaint_shows_ref(spec):
            progress(f"Uploading ref: {ref_path.name}")
            ref_url = upload_file(ref_path, on_progress=progress)
    except (FalClientError, Exception) as exc:
        return ToolResult(
            ok=False,
            status=f"{friendly_error(exc, context=spec.label)} · {size_note}",
            cost_label=est,
        )

    args = build_inpaint_args(
        spec,
        image_url=image_url,
        mask_url=mask_url,
        prompt=prompt or "",
        negative_prompt=negative_prompt,
        strength=strength,
        num_images=n_req,
        reference_image_url=ref_url,
    )
    progress("Running inpaint on fal…")
    t0 = time.perf_counter()
    try:
        result = subscribe(spec.endpoint, args, on_progress=progress)
    except FalClientError as exc:
        render_s = time.perf_counter() - t0
        err = str(exc)
        low = err.lower()
        if "size" in low or "dimension" in low or "match" in low:
            err = f"{err} · {size_note}"
        return ToolResult(
            ok=False,
            status=err,
            metrics_line=format_render_metrics(render_s, None, cost_is_estimate=True),
            cost_label=est,
        )
    render_s = time.perf_counter() - t0

    exact = extract_cost_usd_from_response(result)
    cost_usd = (
        exact
        if exact is not None
        else float(spec.cost_estimate_usd) * n_req
    )
    is_est = exact is None
    metrics = format_render_metrics(render_s, cost_usd, cost_is_estimate=is_est)
    cost_lbl = format_cost_label(cost_usd, estimate=is_est)

    urls = extract_image_urls(result)
    if not urls:
        single = _extract_single_image(result)
        if single:
            urls = [single]
    if not urls:
        return ToolResult(
            ok=False,
            status=f"{spec.label}: fal returned no image.",
            metrics_line=metrics,
            cost_label=cost_lbl,
        )

    stamp = timestamp_now()
    media_dir = job_media_dir(output_dir, stamp=stamp)
    base_stem = make_output_stem(
        (prompt or "inpaint")[:48],
        spec.key,
        stamp=stamp,
        kind="inpaint",
    )
    saved: list[str] = []
    for i, out_url in enumerate(urls):
        if len(urls) == 1:
            stem = base_stem
        else:
            stem = f"{base_stem}_{i + 1:02d}"
        dest = unique_path(media_dir, stem, ".png")
        try:
            progress(f"Downloading {i + 1}/{len(urls)}…")
            download_url(out_url, dest, on_progress=progress)
            saved.append(str(dest.resolve()))
        except FalClientError as exc:
            if not saved:
                return ToolResult(
                    ok=False,
                    status=str(exc),
                    metrics_line=metrics,
                    cost_label=cost_lbl,
                )
            progress(f"Partial download: {exc}")
            break

    if not saved:
        return ToolResult(
            ok=False,
            status=f"{spec.label}: download failed.",
            metrics_line=metrics,
            cost_label=cost_lbl,
        )

    try:
        from media_studio.history import append_history

        notes = ["inpaint", "mask"]
        if ref_url:
            notes.append("ref")
        if len(saved) > 1:
            notes.append(f"batch×{len(saved)}")
        append_history(
            job_kind="image",
            model=spec.label,
            prompt=(prompt or "inpaint").strip(),
            files=saved,
            cost_estimate=cost_lbl,
            notes=notes,
            output_dir=output_dir,
            timestamp=stamp,
            scenario="inpaint",
        )
    except Exception:
        pass

    first = saved[0]
    if len(saved) == 1:
        status = (
            f"{spec.label} OK. Saved {Path(first).name}. "
            f"{metrics}. Use Show in folder or Send to Resolve."
        )
    else:
        status = (
            f"{spec.label} OK. Saved {len(saved)} stills "
            f"({Path(first).name} + {len(saved) - 1} more). "
            f"{metrics}. All in Library / job folder."
        )
    return ToolResult(
        ok=True,
        path=first,
        paths=saved,
        status=status,
        metrics_line=metrics,
        cost_label=cost_lbl,
        notes=[spec.notes] if spec.notes else [],
    )
