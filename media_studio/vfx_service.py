"""Run VFX jobs (in-scene + element plates) via fal."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from media_studio.errors import friendly_error
from media_studio.fal.client import FalClientError
from media_studio.history import append_history
from media_studio.naming import job_media_dir, make_output_stem, timestamp_now, unique_path
from media_studio.pricing import (
    extract_cost_usd_from_response,
    format_cost_label,
    format_render_metrics,
)
from media_studio.vfx_registry import (
    VfxMode,
    assemble_vfx_prompt,
    estimate_vfx_cost,
    find_vfx_preset,
    format_vfx_cost,
    model_is_t2v,
    model_is_video_edit,
    resolve_vfx_model,
)

ProgressCallback = Callable[[str], None]


@dataclass
class VfxResult:
    ok: bool
    path: str | None = None
    status: str = ""
    model_key: str = ""
    endpoint: str = ""
    notes: list[str] = field(default_factory=list)
    cost_label: str = ""
    metrics_line: str = ""
    timestamp: str = ""
    mode: str = "in_scene"


def _result_cost_label(result: Any, est: float | None) -> str:
    """
    Normalize cost display across fal result shapes.

    ImageToVideoResult / VideoEditResult use ``cost_estimate``;
    VisionResult uses ``cost_label``. Fall back to the pre-job estimate.
    """
    for attr in ("cost_label", "cost_estimate"):
        val = getattr(result, attr, None)
        if val is not None and str(val).strip():
            return str(val).strip()
    return format_cost_label(est, estimate=True)


def _to_vfx_result(
    r: Any,
    *,
    notes: list[str],
    est: float | None,
    model_fallback: str = "",
    extra_notes: list[str] | None = None,
) -> VfxResult:
    """Map Studio I2V / V2V / Vision results onto VfxResult."""
    n = list(notes)
    if extra_notes:
        n.extend(extra_notes)
    r_notes = getattr(r, "notes", None)
    if r_notes:
        n.extend(list(r_notes))
    return VfxResult(
        ok=bool(getattr(r, "ok", False)),
        path=getattr(r, "path", None),
        status=getattr(r, "status", None) or ("OK" if getattr(r, "ok", False) else "Failed"),
        model_key=getattr(r, "model_key", "") or model_fallback,
        endpoint=getattr(r, "endpoint", "") or "",
        notes=n,
        cost_label=_result_cost_label(r, est),
        metrics_line=getattr(r, "metrics_line", "") or "",
        timestamp=getattr(r, "timestamp", "") or "",
    )


def _ensure_black_plate(output_dir: Path, *, size: tuple[int, int] = (1280, 720)) -> Path:
    """Create a reusable pure-black PNG for element-plate I2V."""
    cache = output_dir / "_vfx" / "black_plate_1280x720.png"
    cache.parent.mkdir(parents=True, exist_ok=True)
    if cache.is_file() and cache.stat().st_size > 64:
        return cache
    try:
        from PIL import Image

        img = Image.new("RGB", size, (0, 0, 0))
        img.save(cache, format="PNG")
    except Exception:
        # Minimal 1x1 fallback — some APIs still accept it
        cache.write_bytes(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00"
            b"\x0cIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00"
            b"\x00\x00IEND\xaeB`\x82"
        )
    return cache


def run_vfx(
    *,
    mode: VfxMode = "in_scene",
    prompt: str,
    preset_label: str | None = None,
    model_label: str | None = None,
    source_path: str | Path | None = None,
    strength: float = 0.7,
    duration_s: float = 5.0,
    resolution: str | None = "720p",
    use_black_plate: bool = True,
    output_dir: str | Path,
    on_progress: ProgressCallback | None = None,
) -> VfxResult:
    """
    Generate VFX.

    In-scene: source still → I2V (or image edit) / source clip → video edit.
    Element: black plate I2V or T2V with Screen/Add-oriented prompt.
    """
    def progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    preset = find_vfx_preset(preset_label)
    full_prompt = assemble_vfx_prompt(
        mode=mode,
        preset=preset,
        user_prompt=prompt,
        strength=strength,
        duration_s=duration_s,
    )
    if not full_prompt.strip():
        return VfxResult(ok=False, status="Enter a prompt or pick an effect preset.")

    kind, spec = resolve_vfx_model(model_label)
    if spec is None:
        return VfxResult(ok=False, status="Select a VFX-capable model.")

    est = estimate_vfx_cost(
        model_label, duration_s=duration_s, resolution=resolution
    )
    est_lbl = format_cost_label(est, estimate=True)
    progress(f"VFX · {mode} · {getattr(spec, 'label', model_label)}")
    progress(est_lbl)

    notes: list[str] = [f"mode={mode}"]
    if preset:
        notes.append(f"preset={preset.key}")
    notes.append(f"strength={strength:.2f}")

    src = Path(source_path) if source_path else None
    is_video_src = bool(
        src
        and src.is_file()
        and src.suffix.lower() in {".mp4", ".mov", ".webm", ".m4v", ".avi", ".mkv"}
    )
    is_image_src = bool(
        src
        and src.is_file()
        and src.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
    )

    t0 = time.perf_counter()
    try:
        # ---- Element plates: prefer T2V or I2V on black ----
        if mode == "element":
            if model_is_t2v(model_label) or (
                kind == "vision" and getattr(spec, "mode", None) == "text_to_video"
            ):
                result = _run_t2v(
                    spec=spec,
                    prompt=full_prompt,
                    duration_s=duration_s,
                    resolution=resolution,
                    output_dir=output_dir,
                    progress=progress,
                    notes=notes,
                    est=est,
                )
            else:
                out_root = Path(output_dir)
                black = _ensure_black_plate(out_root) if use_black_plate else None
                if black is None or not black.is_file():
                    return VfxResult(
                        ok=False,
                        status="Element plates need a black plate (or use a T2V model).",
                        notes=notes,
                    )
                notes.append("black_plate")
                result = _run_i2v(
                    model_label=model_label or getattr(spec, "label", ""),
                    prompt=full_prompt,
                    image_path=black,
                    duration_s=duration_s,
                    resolution=resolution,
                    output_dir=output_dir,
                    progress=progress,
                    notes=notes,
                    est=est,
                )
        # ---- In-scene video source ----
        elif is_video_src and (model_is_video_edit(model_label) or True):
            # Prefer video-edit models; if user picked I2V, still try edit path
            # with Grok/Kling edit when available
            result = _run_video_edit_or_i2v(
                model_label=model_label,
                prompt=full_prompt,
                source=src,  # type: ignore[arg-type]
                duration_s=duration_s,
                resolution=resolution,
                output_dir=output_dir,
                progress=progress,
                notes=notes,
                est=est,
            )
        # ---- In-scene still ----
        elif is_image_src:
            result = _run_i2v(
                model_label=model_label or getattr(spec, "label", ""),
                prompt=full_prompt,
                image_path=src,  # type: ignore[arg-type]
                duration_s=duration_s,
                resolution=resolution,
                output_dir=output_dir,
                progress=progress,
                notes=notes,
                est=est,
            )
        else:
            return VfxResult(
                ok=False,
                status=(
                    "In-scene needs a source still or clip. "
                    "Element plates can run without a source (black plate / T2V)."
                    if mode == "in_scene"
                    else "Could not start Element plate job."
                ),
                notes=notes,
            )
    except Exception as exc:
        render_s = time.perf_counter() - t0
        return VfxResult(
            ok=False,
            status=friendly_error(exc, context="VFX"),
            notes=notes,
            metrics_line=format_render_metrics(render_s, None, cost_is_estimate=True),
            mode=mode,
        )

    result.mode = mode
    # Ensure Library index (I2V/video_edit may not always write history)
    if result.ok and result.path:
        try:
            append_history(
                job_kind="vfx",
                model=getattr(spec, "label", None) or (model_label or "VFX"),
                prompt=full_prompt[:800],
                files=[result.path],
                cost_estimate=result.cost_label
                or format_vfx_cost(
                    model_label, duration_s=duration_s, resolution=resolution
                ),
                notes=list(result.notes or notes),
                output_dir=output_dir,
                scenario=f"vfx-{mode}",
                timestamp=result.timestamp or None,
            )
        except Exception:
            pass
    return result


def _run_i2v(
    *,
    model_label: str,
    prompt: str,
    image_path: Path,
    duration_s: float,
    resolution: str | None,
    output_dir: str | Path,
    progress: ProgressCallback,
    notes: list[str],
    est: float | None,
) -> VfxResult:
    from media_studio.fal.image_to_video import run_image_to_video

    params: dict[str, Any] = {
        "duration": str(int(round(duration_s))),
        "duration_seconds": float(duration_s),
    }
    if resolution:
        params["resolution"] = resolution

    r = run_image_to_video(
        prompt=prompt,
        image_path=image_path,
        model_choice=model_label,
        parameters=params,
        output_dir=output_dir,
        on_progress=progress,
        scenario="vfx",
    )
    return _to_vfx_result(r, notes=notes, est=est, model_fallback=model_label)


def _run_t2v(
    *,
    spec: Any,
    prompt: str,
    duration_s: float,
    resolution: str | None,
    output_dir: str | Path,
    progress: ProgressCallback,
    notes: list[str],
    est: float | None,
) -> VfxResult:
    from media_studio.vision_service import run_vision

    r = run_vision(
        mode="text_to_video",
        prompt=prompt,
        model_label=getattr(spec, "label", None),
        duration=str(int(round(duration_s))),
        resolution=resolution,
        aspect_ratio=getattr(spec, "default_aspect", None) or "16:9",
        output_dir=output_dir,
        on_progress=progress,
    )
    # Re-tag history as vfx when possible (vision already wrote history)
    cost_lbl = _result_cost_label(r, est)
    if r.ok and r.path:
        try:
            append_history(
                job_kind="vfx",
                model=getattr(spec, "label", "VFX"),
                prompt=prompt[:800],
                files=[r.path],
                cost_estimate=cost_lbl,
                notes=notes + ["element_plate", "t2v"],
                output_dir=output_dir,
                scenario="vfx-element",
            )
        except Exception:
            pass
    return _to_vfx_result(
        r,
        notes=notes,
        est=est,
        model_fallback=getattr(spec, "key", "") or "",
        extra_notes=["element_plate", "t2v"],
    )


def _run_video_edit_or_i2v(
    *,
    model_label: str | None,
    prompt: str,
    source: Path,
    duration_s: float,
    resolution: str | None,
    output_dir: str | Path,
    progress: ProgressCallback,
    notes: list[str],
    est: float | None,
) -> VfxResult:
    """In-scene with a clip: video edit if model supports it, else poster I2V."""
    if model_is_video_edit(model_label):
        from media_studio.fal.video_edit import run_video_edit

        params: dict[str, Any] = {}
        if resolution:
            params["resolution"] = resolution
        r = run_video_edit(
            prompt=prompt,
            video_path=source,
            model_choice=model_label,
            parameters=params,
            output_dir=output_dir,
            on_progress=progress,
            scenario="vfx",
        )
        return _to_vfx_result(
            r,
            notes=notes,
            est=est,
            model_fallback=model_label or "",
            extra_notes=["v2v_edit"],
        )

    # Fallback: extract a poster frame and I2V
    progress("Model is I2V — using a still from the clip as start frame…")
    try:
        from media_studio.media import video_poster_path

        poster = video_poster_path(source)
    except Exception as exc:
        return VfxResult(
            ok=False,
            status=f"Could not sample frame from clip: {exc}",
            notes=notes,
        )
    if not poster or not Path(poster).is_file():
        return VfxResult(
            ok=False,
            status="Could not sample a still from the clip. Try an I2V-friendly still.",
            notes=notes,
        )
    notes.append(f"poster={Path(poster).name}")
    return _run_i2v(
        model_label=model_label or "grok imagine 1.5 i2v",
        prompt=prompt,
        image_path=Path(poster),
        duration_s=duration_s,
        resolution=resolution,
        output_dir=output_dir,
        progress=progress,
        notes=notes,
        est=est,
    )
