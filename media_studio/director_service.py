"""Run Director multi-shot jobs via fal."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from media_studio.director_registry import (
    DirectorModelSpec,
    DirectorPolish,
    DirectorShot,
    build_director_arguments,
    default_director_model,
    find_director_model,
    validate_shots,
    write_shot_list_sidecar,
)
from media_studio.errors import friendly_error
from media_studio.fal.client import FalClientError, download_url, extract_video_url, subscribe, upload_file
from media_studio.history import append_history
from media_studio.naming import job_media_dir, make_output_stem, timestamp_now, unique_path
from media_studio.pricing import (
    extract_cost_usd_from_response,
    format_cost_label,
    format_render_metrics,
)

ProgressCallback = Callable[[str], None]


@dataclass
class DirectorResult:
    ok: bool
    path: str | None = None
    status: str = ""
    model_key: str = ""
    endpoint: str = ""
    notes: list[str] = field(default_factory=list)
    cost_label: str = ""
    metrics_line: str = ""
    timestamp: str = ""


def run_director(
    *,
    master: str,
    shots: list[DirectorShot],
    model_label: str | None = None,
    duration_s: float = 10.0,
    aspect_ratio: str | None = "16:9",
    style_pack: str | None = "None",
    generate_audio: bool | None = None,
    negative_prompt: str | None = None,
    polish: DirectorPolish | None = None,
    output_dir: str | Path,
    on_progress: ProgressCallback | None = None,
) -> DirectorResult:
    """
    Generate one multi-shot video from ordered Director shots.

    Validates times, uploads optional first-ref still for I2V multi-shot,
    posts multi_prompt to Kling V3/O3 endpoints.
    When polish.output_mode is clip pack, also writes a shot-list .txt sidecar
    (API still returns a single multi-shot clip).
    """
    spec = find_director_model(model_label) or default_director_model()

    def progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    errs = validate_shots(
        shots,
        total_duration_s=float(duration_s),
        max_shots=spec.max_shots,
        allow_overlap=False,
        polish=polish,
    )
    if errs:
        return DirectorResult(
            ok=False,
            model_key=spec.key,
            endpoint=spec.endpoint,
            status=" · ".join(errs),
        )

    notes: list[str] = []
    start_url: str | None = None
    ref_urls: list[str] = []
    is_grok = (getattr(spec, "engine", None) or "") == "grok_imagine"

    if is_grok:
        # Upload all shot ref stills in order (up to model max, typically 7)
        cap = max(1, int(spec.max_shots or 7))
        for sh in shots:
            if len(ref_urls) >= cap:
                break
            if sh.ref_path and Path(sh.ref_path).is_file():
                try:
                    progress(f"Uploading shot ref: {Path(sh.ref_path).name}")
                    url = upload_file(Path(sh.ref_path), on_progress=progress)
                    ref_urls.append(url)
                    notes.append(f"Ref {len(ref_urls)}: {Path(sh.ref_path).name}")
                except Exception as exc:
                    notes.append(f"Skip ref upload: {exc}")
    else:
        # Prefer first shot with a ref still as start frame (I2V multi-shot)
        for sh in shots:
            if sh.ref_path and Path(sh.ref_path).is_file():
                try:
                    progress(f"Uploading shot ref: {Path(sh.ref_path).name}")
                    start_url = upload_file(Path(sh.ref_path), on_progress=progress)
                    notes.append(f"Start frame from shot ref: {Path(sh.ref_path).name}")
                    break
                except Exception as exc:
                    notes.append(f"Skip ref upload: {exc}")

    try:
        endpoint, arguments = build_director_arguments(
            spec,
            master=master or "",
            shots=shots,
            duration_s=duration_s,
            aspect_ratio=aspect_ratio,
            style_pack=style_pack,
            generate_audio=generate_audio,
            start_image_url=start_url,
            negative_prompt=negative_prompt,
            polish=polish,
            ref_image_urls=ref_urls or None,
        )
    except ValueError as exc:
        return DirectorResult(
            ok=False,
            model_key=spec.key,
            endpoint=spec.endpoint,
            status=str(exc),
            notes=notes,
        )

    kind = (
        f"Grok Imagine · {len(ref_urls)} ref(s)"
        if is_grok
        else f"multi-shot × {len(shots)}"
    )
    progress(f"{spec.label} · {kind}")
    progress(f"Endpoint: {endpoint}")
    progress("Running Director on fal…")

    t0 = time.perf_counter()
    try:
        result = subscribe(endpoint, arguments, on_progress=progress)
    except FalClientError as exc:
        render_s = time.perf_counter() - t0
        return DirectorResult(
            ok=False,
            model_key=spec.key,
            endpoint=endpoint,
            status=str(exc),
            notes=notes,
            metrics_line=format_render_metrics(render_s, None, cost_is_estimate=True),
        )
    except Exception as exc:
        render_s = time.perf_counter() - t0
        return DirectorResult(
            ok=False,
            model_key=spec.key,
            endpoint=endpoint,
            status=friendly_error(exc, context="Director"),
            notes=notes,
            metrics_line=format_render_metrics(render_s, None, cost_is_estimate=True),
        )
    render_s = time.perf_counter() - t0

    from media_studio.director_registry import estimate_director_cost

    est = estimate_director_cost(
        spec,
        duration_s=float(duration_s),
        generate_audio=bool(
            generate_audio
            if generate_audio is not None
            else spec.default_generate_audio
        ),
    )
    exact = extract_cost_usd_from_response(result)
    cost_usd = exact if exact is not None else est
    is_est = exact is None
    metrics = format_render_metrics(render_s, cost_usd, cost_is_estimate=is_est)
    cost_lbl = format_cost_label(cost_usd, estimate=is_est)

    out_url = extract_video_url(result)
    if not out_url:
        return DirectorResult(
            ok=False,
            model_key=spec.key,
            endpoint=endpoint,
            status="Director: fal returned no video.",
            notes=notes,
            cost_label=cost_lbl,
            metrics_line=metrics,
        )

    stamp = timestamp_now()
    media_dir = job_media_dir(output_dir, stamp=stamp)
    stem = make_output_stem(
        (master or "director")[:80],
        spec.key,
        stamp=stamp,
        kind="director",
    )
    dest = unique_path(media_dir, stem, ".mp4")
    try:
        download_url(out_url, dest, on_progress=progress, timeout=900.0)
    except FalClientError as exc:
        return DirectorResult(
            ok=False,
            model_key=spec.key,
            endpoint=endpoint,
            status=str(exc),
            notes=notes,
            cost_label=cost_lbl,
            metrics_line=metrics,
        )

    resolved = str(dest.resolve())
    hist_files = [resolved]
    # Clip pack mode: API still returns one multi-shot clip; always write shot list
    # sidecar so Resolve / offline edit has the ordered breakdown.
    if polish is not None and polish.wants_shot_list_sidecar():
        side = write_shot_list_sidecar(
            resolved,
            master=master or "",
            shots=shots,
            model_label=spec.label,
            duration_s=float(duration_s),
            aspect_ratio=aspect_ratio,
            polish=polish,
        )
        if side:
            notes.append(f"Shot list: {Path(side).name}")
            hist_files.append(side)
            progress(f"Wrote shot list {Path(side).name}")
        else:
            notes.append("Shot list sidecar failed to write")
    status = (
        f"{spec.label} OK · {len(shots)} shot(s). "
        f"Saved {Path(resolved).name}. {metrics}."
    )
    try:
        append_history(
            job_kind="director",
            model=spec.label,
            prompt=(master or "")[:800],
            files=hist_files,
            cost_estimate=cost_lbl,
            notes=notes + [f"{len(shots)} shots"],
            output_dir=output_dir,
            timestamp=stamp,
            scenario="director",
        )
    except Exception:
        pass

    return DirectorResult(
        ok=True,
        path=resolved,
        status=status,
        model_key=spec.key,
        endpoint=endpoint,
        notes=notes,
        cost_label=cost_lbl,
        metrics_line=metrics,
        timestamp=stamp,
    )
