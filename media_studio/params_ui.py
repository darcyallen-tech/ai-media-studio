"""
Model-aware parameter options, clamping, and JSON sync for the UI.
"""

from __future__ import annotations

import json
from typing import Any

from media_studio.fal.models import (
    ImageEditModelSpec,
    VideoModelSpec,
    default_image_edit_model,
    default_i2v_model,
    default_video_edit_model,
    resolve_enum_aspect_ratio,
    resolve_image_edit_model,
    resolve_job_kind,
    resolve_video_model,
)

ASPECT_COMMON = ["auto", "1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3"]
# UI "auto" is mapped at request build time to nearest fal enum (never send "default")
ASPECT_KONTEXT = [
    "auto",
    "21:9",
    "16:9",
    "4:3",
    "3:2",
    "1:1",
    "2:3",
    "3:4",
    "9:16",
    "9:21",
]
NONE = "—"  # sentinel for unused controls


def is_auto_model(choice: str | None) -> bool:
    if not choice:
        return True
    return choice.strip().lower() in ("", "auto", "auto (default)", "default")


def resolve_vision_studio_model(model_choice: str | None):
    """
    Resolve Creative Vision / Studio T2I·T2V labels (not fal IMAGE_EDIT / VIDEO_MODELS).

    Returns VisionModelSpec or None. Prefer pure T2V / T2I over omni/ref packs for
    control_options and cost (omni stays Vision UI).
    """
    if not model_choice or is_auto_model(model_choice):
        return None
    try:
        from media_studio.vision_registry import find_vision_model

        # Explicit modes first (Studio modality lists)
        for mode in (
            "text_to_video",
            "text_to_image",
            "image_to_image",
            "reference_to_image",
            "image_to_video",
            "reference_to_video",
            "video_to_video",
            "bridge",
            "extend",
        ):
            spec = find_vision_model(model_choice, mode)  # type: ignore[arg-type]
            if spec is not None:
                return spec
        return find_vision_model(model_choice)
    except Exception:
        return None


def resolve_active_model(
    model_choice: str | None,
    *,
    has_image: bool = False,
    has_video: bool = False,
) -> tuple[str, ImageEditModelSpec | VideoModelSpec | None]:
    """
    Returns (job_kind, spec) for the selected model or Auto defaults.
    """
    kind = resolve_job_kind(
        model_choice if not is_auto_model(model_choice) else None,
        has_image=has_image,
        has_video=has_video,
    )
    if is_auto_model(model_choice):
        if kind == "video":
            return "video", default_video_edit_model()
        if kind == "image_to_video":
            return "image_to_video", default_i2v_model()
        return "image", default_image_edit_model()

    img = resolve_image_edit_model(model_choice)
    if img:
        return "image", img
    vid = resolve_video_model(model_choice)
    if vid:
        return ("image_to_video" if vid.task == "image_to_video" else "video"), vid
    # Vision T2V/T2I labels: not fal VIDEO/IMAGE registry — leave kind for caller;
    # control_options handles VisionModelSpec via resolve_vision_studio_model.
    return kind, default_image_edit_model()


def _control_options_vision(spec: Any) -> dict[str, Any]:
    """control_options payload for Creative Vision T2I / video models."""
    mode = getattr(spec, "mode", "") or ""
    if mode in (
        "text_to_video",
        "image_to_video",
        "reference_to_video",
        "video_to_video",
        "bridge",
        "extend",
    ):
        dur_choices = list(spec.duration_choices or ()) or ["5", "6", "8"]
        dur_value = (
            spec.default_duration
            if spec.default_duration in dur_choices
            else dur_choices[0]
        )
        from media_studio.aspect_omit import (
            aspect_omit_ui_label,
            endpoint_omits_aspect_ratio,
        )

        omit_ar = bool(getattr(spec, "omit_aspect_ratio", False)) or endpoint_omits_aspect_ratio(
            getattr(spec, "endpoint", None)
        )
        if omit_ar:
            label = aspect_omit_ui_label(getattr(spec, "endpoint", None))
            ar_choices = [label]
            ar_value = label
            show_ar = True  # show disabled Follows still / Follows refs
            ar_enabled = False
        else:
            ar_choices = list(spec.aspect_choices or ()) or ["16:9"]
            ar_value = (
                spec.default_aspect
                if spec.default_aspect in ar_choices
                else ar_choices[0]
            )
            show_ar = True
            ar_enabled = True
        res_choices = list(spec.resolution_choices or ())
        show_res = bool(res_choices)
        res_value = (
            (
                spec.default_resolution
                if spec.default_resolution in res_choices
                else res_choices[0]
            )
            if show_res
            else NONE
        )
        return {
            "kind": mode or "text_to_video",
            "resolution_choices": res_choices if show_res else [NONE],
            "resolution_value": res_value,
            "resolution_visible": show_res,
            "num_images_choices": ["1"],
            "num_images_value": "1",
            "num_images_visible": False,
            "duration_choices": dur_choices,
            "duration_value": dur_value,
            "duration_visible": True,
            "duration_api": True,
            "aspect_choices": ar_choices,
            "aspect_value": ar_value,
            "aspect_visible": show_ar,
            "aspect_enabled": ar_enabled,
            "aspect_follows_still": omit_ar,
            "aspect_omit_label": ar_value if omit_ar else "",
            "strength_visible": False,
            "strength_value": 0.6,
            "generate_audio_visible": bool(getattr(spec, "supports_audio", False)),
            "generate_audio_value": bool(getattr(spec, "supports_audio", False)),
            "keep_audio_visible": False,
            "keep_audio_value": False,
            "start_time_visible": False,
            "start_time_value": 0.0,
            "native_stereo": bool(getattr(spec, "native_stereo_audio", False)),
        }

    # text_to_image
    ar_choices = list(spec.aspect_choices or ()) or [
        "16:9 landscape",
        "9:16 portrait",
        "1:1 square",
    ]
    ar_value = (
        spec.default_aspect
        if spec.default_aspect in ar_choices
        else ar_choices[0]
    )
    res_choices = list(spec.resolution_choices or ())
    show_res = bool(res_choices)
    res_value = (
        (
            spec.default_resolution
            if spec.default_resolution in res_choices
            else res_choices[0]
        )
        if show_res
        else NONE
    )
    max_n = max(1, int(getattr(spec, "max_num_images", 1) or 1))
    _UI_BATCH_MAX = 4
    num_choices = [str(i) for i in range(1, _UI_BATCH_MAX + 1)]
    return {
        "kind": "text_to_image",
        "resolution_choices": res_choices if show_res else [NONE],
        "resolution_value": res_value if show_res else NONE,
        "resolution_visible": show_res,
        "num_images_choices": num_choices,
        "num_images_value": "1",
        "num_images_visible": True,
        "duration_choices": [NONE],
        "duration_value": NONE,
        "duration_visible": False,
        "aspect_choices": ar_choices,
        "aspect_value": ar_value,
        "aspect_visible": True,
        "strength_visible": False,
        "strength_value": 0.6,
        "generate_audio_visible": False,
        "generate_audio_value": False,
        "max_num_images_api": max_n,
    }


def control_options(model_choice: str | None) -> dict[str, Any]:
    """
    Dropdown choices + visibility for the currently selected model.
    """
    # Vision T2I / T2V first (Studio modality lists) — before fal fallback to Flux edit
    vspec = resolve_vision_studio_model(model_choice)
    if vspec is not None and getattr(vspec, "mode", "") in (
        "text_to_video",
        "text_to_image",
        "image_to_image",
        "reference_to_image",
        "image_to_video",
        "reference_to_video",
        "video_to_video",
        "bridge",
        "extend",
    ):
        return _control_options_vision(vspec)

    kind, spec = resolve_active_model(model_choice, has_image=True, has_video=True)

    if isinstance(spec, ImageEditModelSpec):
        res_choices = list(spec.allowed_resolutions) or ["1K"]
        # Prefer default if valid
        res_value = (
            spec.default_resolution
            if spec.default_resolution in res_choices
            else res_choices[0]
        )
        # Phase 2: UI always offers 1–4 variants. Models with max_num_images=1
        # still list 2–4; generate() runs sequential singles for the excess.
        _UI_BATCH_MAX = 4
        num_choices = [str(i) for i in range(1, _UI_BATCH_MAX + 1)]
        if spec.allowed_aspect_ratios:
            # Avoid doubling "auto" when the API enum already includes it (e.g. Grok Imagine)
            ar_choices = list(spec.allowed_aspect_ratios)
            if "auto" not in {a.lower() for a in ar_choices}:
                ar_choices = ["auto", *ar_choices]
        elif "kontext" in spec.key:
            ar_choices = ASPECT_KONTEXT
        else:
            ar_choices = ASPECT_COMMON
        # Prefer "auto" for enum models (mapped server-side); never "default"
        if "auto" in ar_choices and (
            not spec.default_aspect_ratio
            or str(spec.default_aspect_ratio).lower() in ("auto", "default")
        ):
            ar_value = "auto"
        elif spec.default_aspect_ratio in ar_choices:
            ar_value = spec.default_aspect_ratio
        else:
            ar_value = ar_choices[0]
        show_res = bool(spec.resolution_param or spec.image_size_param)
        show_ar = bool(spec.aspect_ratio_param)
        show_num = True
        show_dur = False
        # Always show for image edit; models that ignore strength simply drop it server-side.
        # ~0.6 is a solid Flux 2 Pro default (enough change without over-denoise).
        show_strength = True
        strength_default = 0.6
        return {
            "kind": "image",
            "resolution_choices": res_choices if show_res else [NONE],
            "resolution_value": res_value if show_res else NONE,
            "resolution_visible": show_res,
            "num_images_choices": num_choices,
            "num_images_value": "1",
            "num_images_visible": show_num,
            "duration_choices": [NONE],
            "duration_value": NONE,
            "duration_visible": show_dur,
            "aspect_choices": ar_choices if show_ar else [NONE],
            "aspect_value": ar_value if show_ar else NONE,
            "aspect_visible": show_ar,
            "strength_visible": show_strength,
            "strength_value": strength_default,
            "generate_audio_visible": False,
            "generate_audio_value": False,
        }

    if isinstance(spec, VideoModelSpec):
        # Duration choices always shown for video models (API or cost/source match)
        dur_choices = list(spec.allowed_durations) or [
            str(i)
            for i in range(
                int(spec.min_duration_seconds), int(spec.max_duration_seconds) + 1
            )
        ]
        dur_value = (
            spec.default_duration
            if spec.default_duration in dur_choices
            else (dur_choices[0] if dur_choices else "5")
        )
        # No aspect_ratio param or central omit list → disabled Follows still/refs
        from media_studio.aspect_omit import (
            aspect_omit_ui_label,
            endpoint_omits_aspect_ratio,
            spec_omits_aspect_ratio,
        )

        omit_ar = spec_omits_aspect_ratio(spec) or endpoint_omits_aspect_ratio(
            getattr(spec, "endpoint", None)
        )
        show_ar = bool(spec.aspect_ratio_param) and not omit_ar
        ar_enabled = True
        aspect_follows_still = False
        aspect_omit_label = aspect_omit_ui_label(getattr(spec, "endpoint", None))
        if omit_ar or (
            not show_ar and getattr(spec, "task", "") == "image_to_video"
        ):
            show_ar = True
            ar_enabled = False
            aspect_follows_still = True
            ar_choices = [aspect_omit_label]
            ar_value = aspect_omit_label
        elif show_ar and spec.allowed_aspect_ratios:
            ar_choices = list(spec.allowed_aspect_ratios)
            ar_value = NONE
        elif show_ar:
            ar_choices = ASPECT_COMMON
            ar_value = NONE
        else:
            ar_choices = [NONE]
            ar_value = NONE
        if show_ar and ar_enabled:
            if (
                spec.default_aspect_ratio
                and spec.default_aspect_ratio in ar_choices
            ):
                ar_value = spec.default_aspect_ratio
            elif "auto" in ar_choices:
                ar_value = "auto"
            else:
                ar_value = ar_choices[0]
        show_gen_audio = bool(spec.generate_audio_param)
        show_keep_audio = bool(spec.keep_audio_param)
        # Explicit resolution enum (Grok, Seedance, etc.) vs Kling-style "matches source"
        if spec.resolution_param and spec.allowed_resolutions:
            res_choices = list(spec.allowed_resolutions)
            res_value = (
                spec.default_resolution
                if spec.default_resolution in res_choices
                else res_choices[0]
            )
            show_res = True
        elif spec.task == "video_edit":
            # V2V: output size follows source clip (720–3840px per fal docs)
            res_choices = ["Matches source (720–3840px)"]
            res_value = res_choices[0]
            show_res = True
        else:
            res_choices = [NONE]
            res_value = NONE
            show_res = False
        show_start = "ltx" in spec.key or "retake" in spec.endpoint
        return {
            "kind": spec.task,
            "resolution_choices": res_choices,
            "resolution_value": res_value,
            "resolution_visible": show_res,
            "num_images_choices": ["1"],
            "num_images_value": "1",
            "num_images_visible": False,
            "duration_choices": dur_choices,
            "duration_value": dur_value,
            "duration_visible": True,
            "duration_api": bool(spec.duration_param),
            "aspect_choices": ar_choices if show_ar else [NONE],
            "aspect_value": ar_value if show_ar else NONE,
            "aspect_visible": show_ar,
            "aspect_enabled": ar_enabled if show_ar else False,
            "aspect_follows_still": aspect_follows_still,
            "aspect_omit_label": aspect_omit_label if aspect_follows_still else "",
            "strength_visible": False,
            "strength_value": 0.8,
            "generate_audio_visible": show_gen_audio,
            "generate_audio_value": bool(spec.default_generate_audio),
            "keep_audio_visible": show_keep_audio,
            "keep_audio_value": bool(spec.default_keep_audio),
            "start_time_visible": show_start,
            "start_time_value": 0.0,
        }

    return control_options("Auto (default)")


def build_parameters_dict(
    *,
    resolution: str | None = None,
    num_images: str | int | None = None,
    duration: str | None = None,
    aspect_ratio: str | None = None,
    strength: float | None = None,
    generate_audio: bool | None = None,
    keep_audio: bool | None = None,
    start_time: float | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if resolution and resolution != NONE and not str(resolution).startswith("Matches"):
        params["resolution"] = resolution
        # image_size enums (auto, auto_2K, square_hd, …) map 1:1
        params["image_size"] = resolution
    if num_images is not None and str(num_images) != NONE:
        try:
            params["num_images"] = int(num_images)
        except (TypeError, ValueError):
            params["num_images"] = 1
    if duration and duration != NONE:
        try:
            params["duration_seconds"] = int(float(duration))
            params["duration"] = str(int(float(duration)))
        except (TypeError, ValueError):
            pass
    if aspect_ratio and aspect_ratio != NONE:
        ar_l = str(aspect_ratio).strip().lower()
        # Never pass UI sentinels that mean "omit" (FLUX 3 I2V / follows still)
        if ar_l not in (
            "follows still",
            "auto (from start still)",
            "auto (from ref still)",
            "none",
            "—",
        ):
            params["aspect_ratio"] = aspect_ratio
    if strength is not None:
        try:
            params["strength"] = float(strength)
        except (TypeError, ValueError):
            pass
    if generate_audio is not None:
        params["generate_audio"] = bool(generate_audio)
    if keep_audio is not None:
        params["keep_audio"] = bool(keep_audio)
    if start_time is not None:
        try:
            params["start_time"] = max(0.0, float(start_time))
        except (TypeError, ValueError):
            pass
    if extra:
        params.update(extra)
    return params


def parameters_to_json(params: dict[str, Any]) -> str:
    return json.dumps(params or {}, indent=2, ensure_ascii=False)


def clamp_parameters_to_model(
    model_choice: str | None,
    params: dict[str, Any] | None,
    *,
    locked_model_key: str | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """
    Lower unsupported parameters to model max/allowed values.
    Returns (clamped_params, adjustment_notes).
    """
    notes: list[str] = []
    raw = dict(params or {})
    choice = model_choice
    if locked_model_key:
        choice = locked_model_key

    img = resolve_image_edit_model(choice)
    vid = resolve_video_model(choice)

    if img:
        # num_images: keep 1–4 for multi-variant UI; API max is applied at generate
        # time (one fal call vs sequential singles). Do not force down to api max here.
        n_in = raw.get("num_images", 1)
        try:
            n = int(n_in)
        except (TypeError, ValueError):
            n = 1
        n2 = max(1, min(4, n))
        if n2 != n:
            notes.append(f"num_images {n} → {n2} (batch 1–4)")
        raw["num_images"] = n2

        # resolution
        if img.resolution_param or img.image_size_param:
            res_in = raw.get("resolution") or raw.get("image_size")
            res = img.clamp_resolution(str(res_in) if res_in else None)
            if res_in and res and str(res_in).strip().upper() != str(res).upper():
                notes.append(f"resolution {res_in!r} → {res} (limit for {img.label})")
            if res:
                raw["resolution"] = res
                if img.image_size_param:
                    raw["image_size"] = res if res != "1K" else "auto"

        # aspect_ratio — never leave "default" for strict-enum models
        if img.aspect_ratio_param:
            ar_in = raw.get("aspect_ratio")
            if img.allowed_aspect_ratios:
                # Keep "auto" for UI (build_edit_arguments maps using source still)
                if ar_in is None or str(ar_in).strip().lower() in ("", "default"):
                    raw["aspect_ratio"] = "auto"
                    if ar_in is not None and str(ar_in).strip().lower() == "default":
                        notes.append("aspect_ratio 'default' → 'auto' (mapped at generate)")
                elif str(ar_in).strip().lower() != "auto":
                    ar_out, ar_note = resolve_enum_aspect_ratio(
                        str(ar_in),
                        allowed=img.allowed_aspect_ratios,
                        default="1:1",
                        resolution_hint=str(
                            raw.get("resolution") or raw.get("image_size") or ""
                        )
                        or None,
                    )
                    if ar_out != str(ar_in).strip():
                        notes.append(ar_note or f"aspect_ratio {ar_in!r} → {ar_out}")
                    raw["aspect_ratio"] = ar_out
            elif ar_in is not None and str(ar_in).strip().lower() == "default":
                raw["aspect_ratio"] = "auto"
                notes.append("aspect_ratio 'default' → 'auto'")

        # strength 0-1
        if "strength" in raw and raw["strength"] is not None:
            try:
                s = float(raw["strength"])
                s2 = max(0.0, min(1.0, s))
                if s2 != s:
                    notes.append(f"strength {s} → {s2} (0–1)")
                raw["strength"] = s2
            except (TypeError, ValueError):
                notes.append(f"dropped invalid strength={raw['strength']!r}")
                raw.pop("strength", None)
        return raw, notes

    if vid:
        if "duration" in raw or "duration_seconds" in raw or vid.duration_param:
            d_in = raw.get("duration_seconds", raw.get("duration"))
            d = vid.nearest_duration(d_in)
            if d_in is not None and str(d_in).strip() not in (d, f"{d}s"):
                notes.append(f"duration {d_in!r} → {d}s (limit for {vid.label})")
            raw["duration"] = d
            raw["duration_seconds"] = int(d)
        if vid.resolution_param:
            res_in = raw.get("resolution")
            res = vid.clamp_resolution(str(res_in) if res_in is not None else None)
            if res:
                if res_in and str(res_in).strip().lower() != str(res).lower():
                    notes.append(f"resolution {res_in!r} → {res} (limit for {vid.label})")
                raw["resolution"] = res
        if "keep_audio" in raw:
            raw["keep_audio"] = bool(raw["keep_audio"])
        return raw, notes

    return raw, notes


def controls_from_parameters(
    model_choice: str | None,
    params: dict[str, Any] | None,
) -> dict[str, Any]:
    """Map a parameters dict onto control values, clamped to model options."""
    opts = control_options(model_choice)
    params = params or {}
    clamped, _ = clamp_parameters_to_model(model_choice, params)

    res = str(clamped.get("resolution") or opts["resolution_value"])
    if res not in opts["resolution_choices"]:
        res = opts["resolution_value"]

    num = str(clamped.get("num_images") or opts["num_images_value"])
    if num not in opts["num_images_choices"]:
        num = opts["num_images_value"]

    dur = str(clamped.get("duration") or clamped.get("duration_seconds") or opts["duration_value"])
    if dur not in opts["duration_choices"]:
        dur = opts["duration_value"]

    ar = str(clamped.get("aspect_ratio") or opts["aspect_value"])
    if ar not in opts["aspect_choices"]:
        ar = opts["aspect_value"]

    try:
        strength = float(clamped.get("strength", opts["strength_value"]))
    except (TypeError, ValueError):
        strength = opts["strength_value"]

    gen_audio = bool(clamped.get("generate_audio", opts.get("generate_audio_value", False)))
    keep_audio = bool(clamped.get("keep_audio", opts.get("keep_audio_value", True)))

    return {
        **opts,
        "resolution_value": res,
        "num_images_value": num,
        "duration_value": dur,
        "aspect_value": ar,
        "strength_value": strength,
        "generate_audio_value": gen_audio,
        "keep_audio_value": keep_audio,
        "parameters": clamped,
        "parameters_json": parameters_to_json(clamped),
    }
