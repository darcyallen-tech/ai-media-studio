"""Smoke: job-total cost labels across surfaces."""
from __future__ import annotations

from media_studio.audio_registry import MUSIC_MODELS, format_audio_cost
from media_studio.fal.models import resolve_image_edit_model
from media_studio.pricing import format_job_cost, live_estimate_cost
from media_studio.runware_client import format_aleph_cost
from media_studio.tools_registry import (
    UPSCALERS,
    VIDEO_UPSCALERS,
    find_tool,
    format_tool_cost,
    format_video_upscale_cost,
)
from media_studio.vision_registry import (
    estimate_vision_cost,
    find_vision_model,
    format_vision_cost,
)


def main() -> None:
    s = find_vision_model("Veo 3.1 · Image→Video", "image_to_video")
    assert s is not None
    assert abs(estimate_vision_cost(s, duration_token="8s") - 3.20) < 0.01
    assert abs(estimate_vision_cost(s, duration_token="4s") - 1.60) < 0.01
    print(format_vision_cost(s, duration_token="8s"))

    f = find_vision_model("Veo 3.1 Fast · Image→Video", "image_to_video")
    assert f is not None
    assert abs(estimate_vision_cost(f, duration_token="8s") - 1.20) < 0.01
    print(format_vision_cost(f, duration_token="8s"))

    img = resolve_image_edit_model("flux 2 pro")
    assert img is not None
    c1 = img.estimate_cost(1)
    assert c1 is not None
    # Models with max_num_images>1 should scale; clamp-limited models stay flat
    c_multi = img.estimate_cost(max(1, getattr(img, "max_num_images", 1) or 1))
    print(format_job_cost(c1, unit="1 image", model=img.label))
    if (getattr(img, "max_num_images", 1) or 1) > 1:
        assert c_multi is not None and abs(c_multi - c1 * img.max_num_images) < 1e-9
        print(format_job_cost(c_multi, unit=f"{img.max_num_images} images", model=img.label))
    # Synthetic batch multiply for models that allow multi
    from media_studio.fal.models import IMAGE_EDIT_MODELS

    multi = next(
        (m for m in IMAGE_EDIT_MODELS.values() if (m.max_num_images or 1) >= 3 and m.cost_per_image),
        None,
    )
    if multi:
        a = multi.estimate_cost(1)
        b = multi.estimate_cost(3)
        assert a and b and abs(b - 3 * a) < 1e-6
        print("batch", multi.label, format_job_cost(b, unit="3 images", model=multi.label))

    # live_estimate with fake path still resolves model when has_image false → may pick video
    # force image path existence not required for unit multiply test above
    lab = live_estimate_cost(
        model_choice=img.label,
        image_file=None,
        parameters_json={"num_images": 2, "resolution": "1K"},
    )
    print("live (no file):", lab)

    mu = next(iter(MUSIC_MODELS.values()))
    print("audio", format_audio_cost(mu, duration_s=30))

    topaz = find_tool("Topaz · Proteus (general upscale)", VIDEO_UPSCALERS)
    assert topaz is not None
    print(
        "upscale",
        format_video_upscale_cost(
            topaz, target_label="1080p (Full HD)", duration_s=10
        ),
    )
    print("tool", format_tool_cost(next(iter(UPSCALERS.values()))))
    print("aleph", format_aleph_cost(10))

    # Kling / Seedance vision if present
    for lab, mode in (
        ("Kling O3 Pro · Image→Video", "image_to_video"),
        ("Seedance 2.0 · Image→Video", "image_to_video"),
    ):
        m = find_vision_model(lab, mode)  # type: ignore[arg-type]
        if m and m.cost_per_second:
            a = estimate_vision_cost(m, duration_token="5")
            b = estimate_vision_cost(m, duration_token="10")
            assert abs(b - 2 * a) < 0.05, (lab, a, b)
            print(lab, format_vision_cost(m, duration_token="10"))

    print("SMOKE_PRICING_OK")


if __name__ == "__main__":
    main()
