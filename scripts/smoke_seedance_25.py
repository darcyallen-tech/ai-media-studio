"""
Smoke: Seedance 2.5 T2V / I2V / R2V registration, cost tokens, sheet bind, policy copy.
"""
from __future__ import annotations

import ast
import py_compile
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    files = [
        "media_studio/vision_registry.py",
        "media_studio/aspect_omit.py",
        "media_studio/fal/models.py",
        "media_studio/errors.py",
        "media_studio/flet_dialogs.py",
        "media_studio/flet_ref_pack.py",
    ]
    for rel in files:
        p = ROOT / rel
        ast.parse(p.read_text(encoding="utf-8"))
        py_compile.compile(str(p), doraise=True)
    print("AST+compile OK")

    from media_studio.aspect_omit import (
        is_seedance_reference_endpoint,
        sanitize_seedance_r2v_arguments,
        seedance_duration_max,
    )
    from media_studio.errors import detect_content_policy_violation
    from media_studio.fal.models import resolve_video_model
    from media_studio.flet_dialogs import set_seedance_likeness_banner_visible
    from media_studio.flet_ref_pack import max_character_slots
    from media_studio.vision_registry import (
        I2V_MODELS,
        R2V_MODELS,
        T2V_MODELS,
        build_vision_arguments,
        estimate_seedance_25_cost,
        estimate_vision_cost,
        find_vision_model,
        format_vision_cost,
        is_seedance_25_spec,
        vision_labels,
    )

    # --- Registry selectable ---
    t2v = find_vision_model("Seedance 2.5 · Text→Video", "text_to_video")
    i2v = find_vision_model("Seedance 2.5 · Image→Video", "image_to_video")
    r2v = find_vision_model("Seedance 2.5 · Reference-to-Video", "reference_to_video")
    assert t2v and t2v.key == "seedance 2.5 t2v"
    assert i2v and i2v.key == "seedance 2.5 i2v"
    assert r2v and r2v.key == "seedance 2.5 reference"
    assert "seedance-2.5/text-to-video" in t2v.endpoint
    assert "seedance-2.5/image-to-video" in i2v.endpoint
    assert "seedance-2.5/reference-to-video" in r2v.endpoint
    assert "30" in t2v.duration_choices and "4" in t2v.duration_choices
    assert t2v.resolution_choices == ("480p", "720p")
    assert r2v.max_refs >= 30 and r2v.max_total_refs == 50
    assert is_seedance_25_spec(r2v)
    assert "Seedance 2.5 · Reference-to-Video" in vision_labels("reference_to_video")
    assert "Seedance 2.5 · Image→Video" in vision_labels("image_to_video")
    assert "Seedance 2.5 · Text→Video" in vision_labels("text_to_video")
    print("OK selectable T2V/I2V/R2V")

    # Studio labels
    studio_i2v = resolve_video_model("Video · Seedance 2.5 – Image-to-Video")
    studio_r2v = resolve_video_model("Video · Seedance 2.5 – Reference-to-Video")
    assert studio_i2v and "seedance-2.5/image-to-video" in studio_i2v.endpoint
    assert studio_r2v and "seedance-2.5/reference-to-video" in studio_r2v.endpoint
    print("OK Studio I2V/R2V resolve")

    # --- Token cost (fal worked examples) ---
    # 5s @720p 16:9 → 108000 tokens → ~$2.31
    c5 = estimate_seedance_25_cost(
        duration_s=5, resolution="720p", aspect_ratio="16:9"
    )
    assert 2.20 <= c5 <= 2.45, f"expected ~2.31, got {c5}"
    # 10s @720p → ~$4.62
    c10 = estimate_seedance_25_cost(
        duration_s=10, resolution="720p", aspect_ratio="16:9"
    )
    assert 4.40 <= c10 <= 4.85, f"expected ~4.62, got {c10}"
    # 480p cheaper
    c480 = estimate_seedance_25_cost(
        duration_s=10, resolution="480p", aspect_ratio="16:9"
    )
    assert c480 < c10
    # Video refs: ×0.6 and include input duration
    c_v = estimate_seedance_25_cost(
        duration_s=10,
        resolution="720p",
        aspect_ratio="16:9",
        has_video_refs=True,
        input_video_duration_s=8,
    )
    # 10+8=18s tokens * 0.6 ≈ 388800 * 0.0214/1000 ≈ 4.99
    assert 4.70 <= c_v <= 5.30, f"expected ~4.99, got {c_v}"
    est = estimate_vision_cost(
        r2v, duration_token="5", resolution="720p", aspect_ratio="16:9"
    )
    assert abs(est - c5) < 0.05
    label = format_vision_cost(
        r2v, duration_token="10", resolution="720p", aspect_ratio="16:9"
    )
    assert "Est. cost" in label and "$" in label
    label_v = format_vision_cost(
        r2v,
        duration_token="10",
        resolution="720p",
        has_video_refs=True,
    )
    assert "video-ref" in label_v.lower()
    print("OK cost estimate:", label)
    print("OK video-ref cost:", label_v)

    # --- Payload: 2 character+scene sheets → image_urls ---
    args = build_vision_arguments(
        r2v,
        prompt="Character walks through the gym. Image 1 identity, Image 2 location.",
        image_url="https://cdn.example/heidi_sheet.jpg",
        ref_urls=["https://cdn.example/gym_sheet.jpg"],
        duration="8",
        resolution="720p",
        aspect_ratio="16:9",
        generate_audio=True,
    )
    assert "image_urls" in args
    urls = list(args["image_urls"])
    assert urls[0] == "https://cdn.example/heidi_sheet.jpg"
    assert "https://cdn.example/gym_sheet.jpg" in urls
    assert args.get("duration") == "8"
    assert args.get("resolution") == "720p"
    assert args.get("generate_audio") is True
    assert "negative_prompt" not in args
    print("OK R2V payload image_urls = two sheets:", urls)

    # sanitize duration 30 for 2.5
    assert seedance_duration_max("bytedance/seedance-2.5/reference-to-video") == 30
    assert seedance_duration_max("bytedance/seedance-2.0/reference-to-video") == 15
    san = sanitize_seedance_r2v_arguments(
        {"prompt": "x", "image_urls": ["u"], "duration": 30, "resolution": "720p"},
        endpoint="bytedance/seedance-2.5/reference-to-video",
    )
    assert san["duration"] == "30"
    san20 = sanitize_seedance_r2v_arguments(
        {"prompt": "x", "image_urls": ["u"], "duration": 30, "resolution": "720p"},
        endpoint="bytedance/seedance-2.0/reference-to-video",
    )
    assert san20["duration"] == "15"
    assert is_seedance_reference_endpoint(
        "bytedance/seedance-2.5/reference-to-video"
    )
    print("OK sanitize duration 2.5=30 / 2.0=15")

    # Ref pack slots higher for 2.5
    assert max_character_slots("Seedance 2.5 · Reference-to-Video", mode="r2v") >= 9
    print("OK ref pack slots")

    # --- Policy: Seedance copy only on Seedance ---
    p_seed = detect_content_policy_violation(
        "partner_validation_failed: likeness of real people",
        context="Generate",
        model_hint="Seedance 2.5 · Reference-to-Video",
    )
    assert p_seed is not None and p_seed.kind == "likeness"
    assert "seedance" in p_seed.short_reason.lower()

    p_other = detect_content_policy_violation(
        "partner_validation_failed: likeness of real people",
        context="Generate",
        model_hint="FLUX 3 · Identity ref (R2V)",
    )
    assert p_other is not None and p_other.kind == "likeness"
    assert "seedance" not in p_other.short_reason.lower()
    assert "provider" in p_other.short_reason.lower()

    # Error body that already says Seedance still gets Seedance copy
    p_from_err = detect_content_policy_violation(
        "Seedance rejected — likeness / real people filter",
        context="Generate",
        model_hint="Kling O3 Pro",
    )
    assert p_from_err is not None
    assert "seedance" in p_from_err.short_reason.lower()
    print("OK policy Seedance vs neutral")

    class Fake:
        visible = False

    b = Fake()
    assert set_seedance_likeness_banner_visible(
        b, endpoint="bytedance/seedance-2.5/reference-to-video"
    )
    assert b.visible
    assert not set_seedance_likeness_banner_visible(
        b, endpoint="blackforestlabs/flux-3/image-to-video"
    )
    assert not b.visible
    print("OK banner 2.5 on / FLUX off")

    # Guide / hints presence
    from media_studio.model_hints import lookup_best_for

    bf = lookup_best_for("seedance 2.5 reference") or lookup_best_for("seedance 2.5")
    assert bf is not None
    blob = f"{bf.short} {bf.detail}".lower()
    assert "long" in blob or "30" in blob or "ref" in blob
    assert "face" in blob or "filter" in blob or "action" in blob
    print("OK model hints:", bf.short)

    # Keys present in registries
    assert "seedance 2.5 t2v" in T2V_MODELS
    assert "seedance 2.5 i2v" in I2V_MODELS
    assert "seedance 2.5 reference" in R2V_MODELS
    print("ALL SMOKE OK — Seedance 2.5")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
