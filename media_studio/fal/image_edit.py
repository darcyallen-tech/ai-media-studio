"""
Image editing pipeline via fal.ai.

Upload local image(s) → run edit model → download results to ./outputs.
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
    extract_image_urls,
    subscribe,
    upload_file,
    _extension_from_url_or_type,
)
from media_studio.fal.models import (
    build_edit_arguments,
    default_image_edit_model,
    resolve_image_edit_model,
)
from media_studio.naming import job_media_dir, make_output_stem, timestamp_now, unique_path
from media_studio.pricing import format_render_metrics, resolve_generation_cost

ProgressCallback = Callable[[str], None]


@dataclass
class ImageEditResult:
    ok: bool
    paths: list[str] = field(default_factory=list)
    model_key: str = ""
    endpoint: str = ""
    status: str = ""
    notes: list[str] = field(default_factory=list)
    fal_description: str = ""
    cost_estimate: str = ""
    timestamp: str = ""
    render_seconds: float | None = None
    metrics_line: str = ""

    @property
    def primary_path(self) -> str | None:
        return self.paths[0] if self.paths else None


def run_image_edit(
    *,
    prompt: str,
    image_paths: list[str | Path],
    model_choice: str | None = None,
    parameters: dict[str, Any] | None = None,
    output_dir: str | Path,
    on_progress: ProgressCallback | None = None,
    scenario: str | None = None,
) -> ImageEditResult:
    """Full image-edit job."""
    prompt = (prompt or "").strip()
    if not prompt:
        return ImageEditResult(ok=False, status="Generate: enter a prompt first.")

    paths = [Path(p) for p in image_paths if p]
    paths = [p for p in paths if p.is_file()]
    if not paths:
        return ImageEditResult(
            ok=False,
            status=(
                "Generate (image edit): upload a still image first "
                "(or a video so the first frame can be used)."
            ),
        )

    spec = resolve_image_edit_model(model_choice)
    if spec is None:
        if model_choice and str(model_choice).strip().lower() not in (
            "",
            "auto",
            "auto (default)",
            "default",
        ):
            lower = str(model_choice).lower()
            if "kling" in lower or "video" in lower:
                return ImageEditResult(
                    ok=False,
                    status=(
                        f"Generate: '{model_choice}' is a video model. "
                        "Upload a video clip, or pick an image model (e.g. Nano Banana Pro)."
                    ),
                )
        spec = default_image_edit_model()
        auto_note = f"Using default image editor: {spec.label}."
    else:
        auto_note = None

    def progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    progress(f"Model: {spec.label} ({spec.endpoint})")

    image_urls: list[str] = []
    try:
        for p in paths:
            image_urls.append(upload_file(p, on_progress=progress))
    except (FalClientError, Exception) as exc:
        return ImageEditResult(
            ok=False,
            model_key=spec.key,
            endpoint=spec.endpoint,
            status=friendly_error(exc, context="Image edit"),
        )

    try:
        arguments, build_notes = build_edit_arguments(
            spec,
            prompt=prompt,
            image_urls=image_urls,
            parameters=parameters,
            # Local path used to derive aspect_ratio when UI says auto/default
            source_image_path=paths[0],
        )
    except ValueError as exc:
        return ImageEditResult(
            ok=False,
            model_key=spec.key,
            endpoint=spec.endpoint,
            status=friendly_error(exc, context="Image edit"),
        )

    notes = list(build_notes)
    if auto_note:
        notes.insert(0, auto_note)

    num_images = int(arguments.get(spec.num_images_param, 1) or 1)

    progress(
        f"Running edit — num_images={num_images}, "
        f"resolution={arguments.get(spec.resolution_param) if spec.resolution_param else 'n/a'}"
    )

    t0 = time.perf_counter()
    try:
        result = subscribe(spec.endpoint, arguments, on_progress=progress)
    except FalClientError as exc:
        render_s = time.perf_counter() - t0
        return ImageEditResult(
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
        job_kind="image",
        num_images=num_images,
        parameters=parameters,
    )
    metrics = format_render_metrics(render_s, cost_usd, cost_is_estimate=is_est)
    cost_str = metrics.split(" · ")[-1] if " · " in metrics else metrics
    if cost_usd is not None:
        notes.append(cost_str)

    urls = extract_image_urls(result)
    if not urls:
        return ImageEditResult(
            ok=False,
            model_key=spec.key,
            endpoint=spec.endpoint,
            status="Generate: fal returned no images. Try a simpler prompt or another model.",
            notes=notes,
            cost_estimate=cost_str if cost_usd is not None else "",
            render_seconds=render_s,
            metrics_line=metrics,
        )

    stamp = timestamp_now()
    media_dir = job_media_dir(output_dir, stamp=stamp)
    stem = make_output_stem(
        prompt, spec.key, stamp=stamp, kind="edit", scenario=scenario
    )
    saved: list[str] = []

    for i, url in enumerate(urls, start=1):
        ext = _extension_from_url_or_type(url)
        if arguments.get("output_format"):
            fmt = str(arguments["output_format"]).lower()
            if fmt in ("png", "jpeg", "jpg", "webp"):
                ext = ".jpg" if fmt in ("jpeg", "jpg") else f".{fmt}"
        dest = unique_path(
            media_dir,
            stem,
            ext,
            index=i if len(urls) > 1 else None,
        )
        try:
            download_url(url, dest, on_progress=progress)
            saved.append(str(dest.resolve()))
        except FalClientError as exc:
            notes.append(f"Failed to save image {i}: {exc}")

    if not saved:
        return ImageEditResult(
            ok=False,
            model_key=spec.key,
            endpoint=spec.endpoint,
            status="Generate: could not download any result images.",
            notes=notes,
            cost_estimate=cost_str if cost_usd is not None else "",
            timestamp=stamp,
            render_seconds=render_s,
            metrics_line=metrics,
        )

    desc = str(result.get("description") or "").strip()
    status_parts = [
        f"Generate OK — {spec.label} (image).",
        f"Saved {len(saved)} file(s) → {media_dir.name}/: "
        f"{', '.join(Path(p).name for p in saved)}.",
        metrics + ".",
    ]
    if notes:
        other = [n for n in notes if n != cost_str]
        if other:
            status_parts.append("Notes: " + "; ".join(other))
    if desc:
        status_parts.append(f"Model description: {desc[:200]}")

    return ImageEditResult(
        ok=True,
        paths=saved,
        model_key=spec.key,
        endpoint=spec.endpoint,
        status=" ".join(status_parts),
        notes=notes,
        fal_description=desc,
        cost_estimate=cost_str if cost_usd is not None else "",
        timestamp=stamp,
        render_seconds=render_s,
        metrics_line=metrics,
    )