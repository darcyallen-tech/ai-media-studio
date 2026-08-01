"""
Video editing pipeline via fal.ai (Kling O1 V2V and similar).

Upload local video (+ optional reference stills) → run model → save to ./outputs.
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
    format_bytes,
    is_remote_url,
    require_local_file,
    extract_video_url,
    subscribe,
    upload_error_detail,
    upload_file,
)
from media_studio.fal.models import (
    build_video_edit_arguments,
    default_video_edit_model,
    resolve_video_model,
)
from media_studio.naming import job_media_dir, make_output_stem, timestamp_now, unique_path
from media_studio.pricing import format_render_metrics, resolve_generation_cost

ProgressCallback = Callable[[str], None]


@dataclass
class VideoEditResult:
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


def _file_download_hint(local: Path, size: int) -> str:
    size_s = format_bytes(size)
    return (
        f"fal could not re-download the uploaded source. "
        f"Local: {local} ({size_s}). "
        "The app always re-uploads from disk right before generate — "
        "do not paste fal.media URLs. "
        "If this keeps failing, export a shorter 3–10s mp4 proxy from Resolve "
        "(camera masters are often too large for the model downloader)."
    )


def run_video_edit(
    *,
    prompt: str,
    video_path: str | Path,
    reference_image_paths: list[str | Path] | None = None,
    model_choice: str | None = None,
    parameters: dict[str, Any] | None = None,
    output_dir: str | Path,
    on_progress: ProgressCallback | None = None,
    scenario: str | None = None,
) -> VideoEditResult:
    """Full video-edit job (video-to-video). Always uploads local files fresh."""
    prompt = (prompt or "").strip()
    if not prompt:
        return VideoEditResult(ok=False, status="Generate: enter a prompt first.")

    # Never treat a remote/handoff URL as an already-public source
    if is_remote_url(video_path):
        return VideoEditResult(
            ok=False,
            status=(
                "Generate (video edit): source is a remote URL, not a local file. "
                "Pick the clip from disk or Recently from Resolve so it uploads fresh."
            ),
        )

    try:
        vpath = require_local_file(video_path, context="Generate (video edit)")
    except FalClientError as exc:
        return VideoEditResult(ok=False, status=str(exc))

    vsize = vpath.stat().st_size

    refs: list[Path] = []
    for p in reference_image_paths or []:
        if not p:
            continue
        if is_remote_url(p):
            continue
        try:
            refs.append(require_local_file(p, context="Reference still"))
        except FalClientError:
            continue

    spec = resolve_video_model(model_choice)
    if spec is None or spec.task != "video_edit":
        spec = default_video_edit_model()
        auto_note = f"Using default video editor: {spec.label}."
    else:
        auto_note = None

    def progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    progress(f"Model: {spec.label} ({spec.endpoint})")
    progress(f"Source video: {vpath.name} ({format_bytes(vsize)})")
    if refs:
        progress(f"Reference image(s): {', '.join(p.name for p in refs)}")

    notes: list[str] = []
    if auto_note:
        notes.append(auto_note)
    if vsize > 200 * 1024 * 1024:
        notes.append(
            f"Large source ({format_bytes(vsize)}). "
            "If fal fails to download, export a shorter 3–10s mp4 from Resolve."
        )
        progress(notes[-1])

    # ---- Always upload local files fresh (never reuse prior fal URLs) ----
    try:
        video_url = upload_file(vpath, on_progress=progress)
        image_urls: list[str] = []
        for p in refs:
            image_urls.append(upload_file(p, on_progress=progress))
    except (FalClientError, Exception) as exc:
        return VideoEditResult(
            ok=False,
            model_key=spec.key,
            endpoint=spec.endpoint,
            status=upload_error_detail(vpath, friendly_error(exc, context="Video edit")),
            notes=notes,
        )

    try:
        arguments, build_notes = build_video_edit_arguments(
            spec,
            prompt=prompt,
            video_url=video_url,
            image_urls=image_urls,
            parameters=parameters,
        )
    except ValueError as exc:
        return VideoEditResult(
            ok=False,
            model_key=spec.key,
            endpoint=spec.endpoint,
            status=friendly_error(exc, context="Video edit"),
            notes=notes,
        )

    notes.extend(build_notes)
    progress("Running video edit on fal (can take several minutes)…")

    t0 = time.perf_counter()
    try:
        result = subscribe(spec.endpoint, arguments, on_progress=progress)
    except FalClientError as exc:
        render_s = time.perf_counter() - t0
        err = str(exc)
        low = err.lower()
        # Model failed to pull our just-uploaded URL — re-upload once and retry
        if "file_download" in low or "failed to download the file" in low:
            progress("fal could not fetch uploaded media; re-uploading fresh and retrying once…")
            try:
                video_url = upload_file(vpath, on_progress=progress)
                image_urls = [upload_file(p, on_progress=progress) for p in refs]
                arguments, more_notes = build_video_edit_arguments(
                    spec,
                    prompt=prompt,
                    video_url=video_url,
                    image_urls=image_urls,
                    parameters=parameters,
                )
                notes.extend(more_notes)
                t0 = time.perf_counter()
                result = subscribe(spec.endpoint, arguments, on_progress=progress)
            except FalClientError as exc2:
                render_s = time.perf_counter() - t0
                return VideoEditResult(
                    ok=False,
                    model_key=spec.key,
                    endpoint=spec.endpoint,
                    status=_file_download_hint(vpath, vsize) + " " + str(exc2)[:180],
                    notes=notes,
                    render_seconds=render_s,
                    metrics_line=format_render_metrics(render_s, None, cost_is_estimate=True),
                )
            except Exception as exc2:
                render_s = time.perf_counter() - t0
                return VideoEditResult(
                    ok=False,
                    model_key=spec.key,
                    endpoint=spec.endpoint,
                    status=upload_error_detail(
                        vpath, friendly_error(exc2, context="Video edit retry")
                    ),
                    notes=notes,
                    render_seconds=render_s,
                    metrics_line=format_render_metrics(render_s, None, cost_is_estimate=True),
                )
        else:
            return VideoEditResult(
                ok=False,
                model_key=spec.key,
                endpoint=spec.endpoint,
                status=err,
                notes=notes,
                render_seconds=render_s,
                metrics_line=format_render_metrics(render_s, None, cost_is_estimate=True),
            )
    render_s = time.perf_counter() - t0

    cost_usd, is_est = resolve_generation_cost(
        result,
        model_key=spec.key,
        job_kind="video",
        video_path=vpath,
        parameters=parameters,
    )
    metrics = format_render_metrics(render_s, cost_usd, cost_is_estimate=is_est)
    cost_str = metrics.split(" · ")[-1] if " · " in metrics else metrics
    if cost_usd is not None:
        notes.append(cost_str)

    out_url = extract_video_url(result)
    if not out_url:
        return VideoEditResult(
            ok=False,
            model_key=spec.key,
            endpoint=spec.endpoint,
            status="Generate: fal returned no video. Check clip length (3–10s) and format (mp4/mov).",
            notes=notes,
            cost_estimate=cost_str if cost_usd is not None else "",
            render_seconds=render_s,
            metrics_line=metrics,
        )

    stamp = timestamp_now()
    media_dir = job_media_dir(output_dir, stamp=stamp)
    stem = make_output_stem(
        prompt, spec.key, stamp=stamp, kind="v2v", scenario=scenario
    )
    dest = unique_path(media_dir, stem, ".mp4")

    try:
        download_url(out_url, dest, on_progress=progress, timeout=600.0)
    except FalClientError as exc:
        return VideoEditResult(
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
        f"Generate OK — {spec.label} (video).",
        f"Saved {Path(resolved).name} → {media_dir.name}/.",
        metrics + ".",
    ]
    other = [n for n in notes if n != cost_str]
    if other:
        status_parts.append("Notes: " + "; ".join(other))

    return VideoEditResult(
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
