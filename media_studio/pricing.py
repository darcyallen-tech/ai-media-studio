"""Cost extraction from fal responses + live estimates."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from media_studio.fal.models import (
    resolve_image_edit_model,
    resolve_job_kind,
    resolve_video_model,
    default_image_edit_model,
    default_video_edit_model,
    default_i2v_model,
)


def extract_cost_usd_from_response(result: Any) -> float | None:
    if result is None:
        return None
    if not isinstance(result, dict):
        data = getattr(result, "data", None)
        if isinstance(data, dict):
            found = extract_cost_usd_from_response(data)
            if found is not None:
                return found
        for attr in ("cost", "price", "metrics", "usage", "billing"):
            if hasattr(result, attr):
                found = extract_cost_usd_from_response(getattr(result, attr))
                if found is not None:
                    return found
        return None

    for key in (
        "cost", "price", "total_cost", "usd_cost", "billable_cost", "amount", "usd",
    ):
        if key in result and result[key] is not None:
            val = _as_usd(result[key])
            if val is not None:
                return val

    for key in ("metrics", "usage", "billing", "stats", "meta", "metadata"):
        nested = result.get(key)
        if nested is not None:
            found = extract_cost_usd_from_response(nested)
            if found is not None:
                return found
    return None


def _as_usd(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        v = float(value)
        if v < 0 or v > 1_000_000:
            return None
        return v
    if isinstance(value, str):
        s = value.strip().replace("$", "").replace(",", "")
        try:
            return float(s)
        except ValueError:
            return None
    if isinstance(value, dict):
        for k in ("usd", "amount", "cost", "price", "value"):
            if k in value:
                return _as_usd(value[k])
    return None


def format_cost_label(amount: float | None, *, estimate: bool = True) -> str:
    """Always: Est. cost: $X.XX (or Cost: for exact API)."""
    if amount is None:
        return "Est. cost: —"
    if amount < 0.01:
        s = f"${amount:.4f}"
    elif amount < 1:
        s = f"${amount:.3f}"
    else:
        s = f"${amount:.2f}"
    return f"Est. cost: {s}" if estimate else f"Cost: {s}"


def format_render_metrics(
    render_seconds: float | None,
    cost_usd: float | None,
    *,
    cost_is_estimate: bool,
) -> str:
    parts: list[str] = []
    if render_seconds is not None and render_seconds >= 0:
        parts.append(f"Rendered in {render_seconds:.1f}s")
    if cost_usd is not None and cost_usd >= 0:
        parts.append(format_cost_label(cost_usd, estimate=cost_is_estimate))
    return " · ".join(parts)


def _parse_params(parameters_json: str | dict | None) -> dict[str, Any]:
    if parameters_json is None:
        return {}
    if isinstance(parameters_json, dict):
        return parameters_json
    if not str(parameters_json).strip():
        return {}
    try:
        data = json.loads(parameters_json)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def probe_video_duration(path: str | Path | None) -> float | None:
    """Return source video length in seconds, or None if unreadable."""
    if not path:
        return None
    try:
        import cv2

        cap = cv2.VideoCapture(str(path))
        try:
            fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
            frames = float(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)
            if fps > 0 and frames > 0:
                return round(frames / fps, 2)
        finally:
            cap.release()
    except Exception:
        return None
    return None


# Back-compat alias
_probe_duration = probe_video_duration


def live_estimate_cost(
    *,
    model_choice: str | None,
    image_file: str | None = None,
    video_file: str | None = None,
    parameters_json: str | dict | None = None,
    probe_video: bool = False,
) -> str:
    """
    Pre-Generate estimate that updates with model / params / media.
    Always labeled Est. cost: $X.XX

    probe_video: if True, open the clip with OpenCV to measure duration.
    Default False — probing on every upload is slow and can glitch the Video tab.
    """
    params = _parse_params(parameters_json)
    other = params.get("other") if isinstance(params.get("other"), dict) else {}
    has_image = bool(image_file and Path(str(image_file)).is_file())
    has_video = bool(video_file and Path(str(video_file)).is_file())

    kind = resolve_job_kind(
        model_choice, has_image=has_image, has_video=has_video
    )

    # duration from params first; optional probe
    dur = params.get("duration_seconds") or params.get("duration")
    if dur is None:
        dur = other.get("duration_seconds") or other.get("duration")
    try:
        dur_f = float(dur) if dur is not None else None
    except (TypeError, ValueError):
        dur_f = None
    if dur_f is None and has_video and probe_video:
        dur_f = _probe_duration(video_file)
    if dur_f is None and has_video:
        # Stable default for V2V cost label without probing
        dur_f = 5.0

    num_images = params.get("num_images") or other.get("num_images") or 1
    try:
        num_images = int(num_images)
    except (TypeError, ValueError):
        num_images = 1

    resolution = params.get("resolution") or other.get("resolution")
    gen_audio = bool(params.get("generate_audio") or other.get("generate_audio"))

    if kind == "image":
        spec = resolve_image_edit_model(model_choice) or default_image_edit_model()
        amount = spec.estimate_cost(num_images, resolution=str(resolution) if resolution else None)
        return format_cost_label(amount, estimate=True)

    if kind == "image_to_video":
        spec = resolve_video_model(model_choice) or default_i2v_model()
        if spec.task != "image_to_video":
            spec = default_i2v_model()
        amount = spec.estimate_cost(
            dur_f,
            generate_audio=gen_audio,
            resolution=str(resolution) if resolution else None,
        )
        return format_cost_label(amount, estimate=True)

    # video edit — cost often scales with source length
    spec = resolve_video_model(model_choice) or default_video_edit_model()
    if spec.task != "video_edit":
        spec = default_video_edit_model()
    amount = spec.estimate_cost(
        dur_f,
        generate_audio=gen_audio,
        resolution=str(resolution) if resolution else None,
    )
    return format_cost_label(amount, estimate=True)


def image_cost_usd(model_key: str, num_images: int, resolution: str | None = None) -> float | None:
    spec = resolve_image_edit_model(model_key)
    if not spec:
        return None
    return spec.estimate_cost(num_images, resolution=resolution)


def video_cost_usd(
    model_key: str,
    *,
    duration_seconds: float | None = None,
    video_path: str | Path | None = None,
    parameters: dict[str, Any] | None = None,
) -> float | None:
    spec = resolve_video_model(model_key)
    if not spec:
        return None
    secs = duration_seconds
    if secs is None and video_path:
        secs = _probe_duration(video_path)
    params = parameters or {}
    other = params.get("other") if isinstance(params.get("other"), dict) else {}
    gen_audio = bool(params.get("generate_audio") or other.get("generate_audio"))
    res = params.get("resolution") or other.get("resolution")
    return spec.estimate_cost(
        secs,
        generate_audio=gen_audio,
        resolution=str(res) if res is not None else None,
    )


def estimate_image_cost(model_key: str, num_images: int) -> str:
    return format_cost_label(image_cost_usd(model_key, num_images), estimate=True)


def estimate_video_cost(
    model_key: str,
    *,
    duration_seconds: float | None = None,
    video_path: str | Path | None = None,
    parameters: dict[str, Any] | None = None,
) -> str:
    return format_cost_label(
        video_cost_usd(
            model_key,
            duration_seconds=duration_seconds,
            video_path=video_path,
            parameters=parameters,
        ),
        estimate=True,
    )


def resolve_generation_cost(
    result: Any,
    *,
    model_key: str,
    job_kind: str,
    num_images: int = 1,
    video_path: str | Path | None = None,
    parameters: dict[str, Any] | None = None,
) -> tuple[float | None, bool]:
    exact = extract_cost_usd_from_response(result)
    if exact is not None:
        return exact, False

    if job_kind in ("video", "image_to_video"):
        est = video_cost_usd(
            model_key,
            video_path=video_path,
            parameters=parameters,
        )
    else:
        res = None
        if parameters:
            res = parameters.get("resolution")
        est = image_cost_usd(model_key, num_images, resolution=str(res) if res else None)
    return est, True
