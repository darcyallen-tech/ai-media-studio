"""Trace aspect_ratio presence for Vision + Studio video models (audit only)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from media_studio.aspect_omit import (  # noqa: E402
    OMIT_ASPECT_ENDPOINT_MATCHERS,
    endpoint_omits_aspect_ratio,
)
from media_studio.fal.models import (  # noqa: E402
    VIDEO_MODELS,
    build_i2v_arguments,
    build_video_edit_arguments,
)
from media_studio.flux3_draft import strip_omitted_aspect  # noqa: E402
from media_studio.params_ui import control_options  # noqa: E402
from media_studio.vision_registry import (  # noqa: E402
    BRIDGE_MODELS,
    EXTEND_MODELS,
    I2V_MODELS,
    R2V_MODELS,
    T2V_MODELS,
    V2V_MODELS,
    build_vision_arguments,
)


def safe_vision(spec, aspect_ratio="16:9"):
    mode = spec.mode
    base = dict(
        prompt="test shot with refs",
        duration=spec.default_duration or "5",
        aspect_ratio=aspect_ratio,
        resolution=spec.default_resolution or "720p",
    )
    if mode == "image_to_video":
        base["image_url"] = "https://example.com/a.jpg"
    elif mode == "reference_to_video":
        base["ref_urls"] = [
            "https://example.com/a.jpg",
            "https://example.com/b.jpg",
        ]
        base["image_url"] = "https://example.com/a.jpg"
    elif mode in ("video_to_video", "extend"):
        base["source_video_url"] = "https://example.com/v.mp4"
    elif mode == "bridge":
        base["first_frame_url"] = "https://example.com/a.jpg"
        base["last_frame_url"] = "https://example.com/b.jpg"
    try:
        args = build_vision_arguments(spec, **base)
    except Exception as e:
        return {"_err": str(e)}, None, None
    stripped = strip_omitted_aspect(dict(args), endpoint=spec.endpoint)
    draft_ep = getattr(spec, "draft_endpoint", None)
    draft_args = (
        strip_omitted_aspect(dict(args), endpoint=draft_ep) if draft_ep else None
    )
    return args, stripped, draft_args


def main() -> int:
    print("OMIT LIST:", OMIT_ASPECT_ENDPOINT_MATCHERS)
    print()
    print("=== CREATIVE VISION MODELS ===")
    print(
        f"{'tab':6} {'key':30} {'omitL':5} {'flag':5} "
        f"{'build':8} {'val':24} {'strip':5} endpoint"
    )
    for registry, name in [
        (T2V_MODELS, "T2V"),
        (I2V_MODELS, "I2V"),
        (R2V_MODELS, "R2V"),
        (V2V_MODELS, "V2V"),
        (BRIDGE_MODELS, "Bridge"),
        (EXTEND_MODELS, "Extend"),
    ]:
        for key, spec in registry.items():
            ep = spec.endpoint
            omit = endpoint_omits_aspect_ratio(ep)
            flag = bool(getattr(spec, "omit_aspect_ratio", False))
            args, stripped, _ = safe_vision(spec)
            if isinstance(args, dict) and "_err" in args:
                has, val, has_s = "ERR", args["_err"][:22], "?"
            else:
                has = "aspect_ratio" in args
                val = args.get("aspect_ratio")
                has_s = "aspect_ratio" in stripped if stripped else "?"
            # also auto
            args_auto, stripped_auto, _ = safe_vision(spec, aspect_ratio="auto")
            auto_has = (
                "aspect_ratio" in args_auto
                if isinstance(args_auto, dict) and "_err" not in args_auto
                else "?"
            )
            auto_val = (
                args_auto.get("aspect_ratio")
                if isinstance(args_auto, dict) and "_err" not in args_auto
                else None
            )
            print(
                f"{name:6} {key[:30]:30} {str(omit):5} {str(flag):5} "
                f"{str(has):8} {str(val)[:24]:24} {str(has_s):5} {ep[:48]}"
            )
            if auto_has is True and auto_val is not None:
                print(f"       auto→ has={auto_has} val={auto_val!r}")

    print()
    print("=== STUDIO VIDEO (build_i2v / edit) ===")
    for key, spec in VIDEO_MODELS.items():
        if spec.task not in ("image_to_video", "video_edit"):
            continue
        omit = endpoint_omits_aspect_ratio(spec.endpoint)
        ar_param = spec.aspect_ratio_param
        try:
            if spec.task == "image_to_video":
                args, notes = build_i2v_arguments(
                    spec,
                    prompt="test",
                    image_url="https://e.com/a.jpg",
                    parameters={
                        "aspect_ratio": "16:9",
                        "duration": spec.default_duration or "5",
                        "resolution": spec.default_resolution,
                    },
                )
            else:
                args, notes = build_video_edit_arguments(
                    spec,
                    prompt="test",
                    video_url="https://e.com/v.mp4",
                    image_urls=["https://e.com/a.jpg"],
                    parameters={
                        "aspect_ratio": "16:9",
                        "duration": spec.default_duration or "5",
                    },
                )
            has = "aspect_ratio" in args
            val = args.get("aspect_ratio")
            stripped = strip_omitted_aspect(args, endpoint=spec.endpoint)
            has_s = "aspect_ratio" in stripped
            # UI
            try:
                opts = control_options(spec.label)
                ui_ar = opts.get("aspect_value")
                ui_en = opts.get("aspect_enabled")
            except Exception:
                ui_ar, ui_en = "?", "?"
        except Exception as e:
            has, val, has_s = "ERR", str(e)[:40], "?"
            ui_ar, ui_en = "?", "?"
        print(
            f"{key[:32]:32} param={str(ar_param)[:14]:14} omit={omit} "
            f"has={has} val={val} strip={has_s} UI={ui_ar!r} en={ui_en} "
            f"{spec.endpoint[:40]}"
        )

    # Critical Seedance R2V deep dive
    print()
    print("=== SEEDANCE R2V DEEP DIVE ===")
    from media_studio.vision_registry import find_vision_model

    vs = find_vision_model("Seedance 2.0 · Reference-to-Video", "reference_to_video")
    print("vision spec:", vs.key if vs else None, "omit_flag=", getattr(vs, "omit_aspect_ratio", None))
    print("default_aspect=", repr(getattr(vs, "default_aspect", None)))
    print("aspect_choices=", getattr(vs, "aspect_choices", None))
    for ar in ("16:9", "auto", "Follows refs / adaptive", None, ""):
        a, s, _ = safe_vision(vs, aspect_ratio=ar)  # type: ignore[arg-type]
        print(
            f"  aspect_ratio arg={ar!r:30} build_has={'aspect_ratio' in a if isinstance(a, dict) and '_err' not in a else a} "
            f"val={a.get('aspect_ratio') if isinstance(a, dict) and '_err' not in a else None!r} "
            f"strip_has={'aspect_ratio' in s if s else None}"
        )

    # Does H3 omni send adaptive?
    print()
    print("=== H3 R2V DEEP DIVE ===")
    h3 = find_vision_model("MiniMax H3", "reference_to_video") or find_vision_model(
        "h3", "reference_to_video"
    )
    if h3 is None:
        for k, s in R2V_MODELS.items():
            if "h3" in k or "omni" in k:
                h3 = s
                break
    if h3:
        print("H3 key", h3.key, h3.endpoint)
        for ar in ("16:9", "adaptive", "auto", None):
            a, s, _ = safe_vision(h3, aspect_ratio=ar)  # type: ignore[arg-type]
            print(
                f"  ar={ar!r:12} has={'aspect_ratio' in a if isinstance(a,dict) and '_err' not in a else a} "
                f"val={a.get('aspect_ratio') if isinstance(a,dict) and '_err' not in a else None!r}"
            )

    # flux3_draft.strip_resolution_for_draft always pops aspect
    print()
    print("strip_resolution_for_draft always pops aspect_ratio (yes — see flux3_draft.py)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
