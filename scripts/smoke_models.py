"""Smoke checks for expanded model catalog + live cost."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from media_studio.config import MODEL_LABELS
from media_studio.fal.models import (
    model_dropdown_choices,
    resolve_image_edit_model,
    resolve_job_kind,
    resolve_video_model,
)
from media_studio.pricing import live_estimate_cost


def main() -> None:
    labels = model_dropdown_choices()
    assert labels[0].startswith("Auto")
    assert labels == MODEL_LABELS
    assert any("Nano Banana Pro" in x for x in labels)
    assert any("Nano Banana 2" in x for x in labels)
    assert any("Flux 2 Pro" in x for x in labels)
    assert any("Flux 2 Flex" in x for x in labels)
    assert any("Grok Imagine Edit" in x and "Quality" not in x for x in labels)
    assert any("Grok Imagine Quality Edit" in x for x in labels)
    assert any("Grok Imagine Edit Video" in x for x in labels)
    assert any("Grok Imagine 1.5" in x for x in labels)
    assert any("O3 Standard" in x and "V2V" in x for x in labels)
    assert any("O3 Pro" in x and "V2V" in x for x in labels)
    assert any("Image-to-Video" in x for x in labels)
    assert any("2.6" in x for x in labels)
    assert any("2.5" in x for x in labels)
    print("dropdown count", len(labels))
    for L in labels:
        print(" ", L)

    pro = resolve_image_edit_model("Image · Nano Banana Pro (edit)")
    assert pro and pro.endpoint.endswith("nano-banana-pro/edit")
    nb2 = resolve_image_edit_model("nano banana 2")
    assert nb2 and nb2.endpoint == "fal-ai/nano-banana-2/edit"
    f2 = resolve_image_edit_model("Image · Flux 2 Pro (edit)")
    assert f2 and f2.endpoint == "fal-ai/flux-2-pro/edit"
    flex = resolve_image_edit_model("flux 2 flex")
    assert flex and flex.endpoint == "fal-ai/flux-2-flex/edit"
    gi = resolve_image_edit_model("Image · Grok Imagine Edit")
    assert gi and gi.endpoint == "xai/grok-imagine-image/edit"
    giq = resolve_image_edit_model("grok imagine quality edit")
    assert giq and giq.endpoint == "xai/grok-imagine-image/quality/edit"

    o3 = resolve_video_model("Video · Kling O3 Pro – V2V Edit")
    assert o3 and "o3/pro/video-to-video/edit" in o3.endpoint
    o3s = resolve_video_model("kling o3 standard edit")
    assert o3s and o3s.task == "video_edit"
    i2v = resolve_video_model("kling o3 standard i2v")
    assert i2v and i2v.task == "image_to_video"
    v3 = resolve_video_model("kling v3 pro i2v")
    assert v3 and "v3/pro/image-to-video" in v3.endpoint
    k26 = resolve_video_model("kling 2.6 pro")
    assert k26 and "v2.6" in k26.endpoint
    k25 = resolve_video_model("kling 2.5 turbo pro")
    assert k25 and "v2.5-turbo" in k25.endpoint
    gev = resolve_video_model("Video · Grok Imagine Edit Video")
    assert gev and gev.endpoint == "xai/grok-imagine-video/edit-video" and gev.task == "video_edit"
    gi2v = resolve_video_model("grok imagine 1.5 i2v")
    assert gi2v and gi2v.endpoint == "xai/grok-imagine-video/v1.5/image-to-video"
    assert gi2v.task == "image_to_video"

    assert resolve_job_kind(None, has_image=True, has_video=True) == "video"
    assert resolve_job_kind(None, has_image=True, has_video=False) == "image"
    assert (
        resolve_job_kind("kling o3 standard i2v", has_image=True, has_video=False)
        == "image_to_video"
    )
    assert (
        resolve_job_kind("Image · Nano Banana Pro (edit)", has_image=True, has_video=True)
        == "image"
    )
    assert (
        resolve_job_kind("grok imagine 1.5 i2v", has_image=True, has_video=False)
        == "image_to_video"
    )

    est = live_estimate_cost(
        model_choice="Image · Nano Banana Pro (edit)",
        parameters_json='{"num_images": 2}',
    )
    assert est.startswith("Est. cost:")
    assert "0.3" in est
    est2 = live_estimate_cost(
        model_choice="Video · Kling O3 Standard – V2V Edit",
        parameters_json='{"duration_seconds": 5}',
    )
    assert est2.startswith("Est. cost:")
    est3 = live_estimate_cost(
        model_choice="kling o3 standard i2v",
        parameters_json='{"duration": "5"}',
    )
    assert est3.startswith("Est. cost:")
    est_gi = live_estimate_cost(
        model_choice="Image · Grok Imagine Edit",
        parameters_json='{"num_images": 1}',
    )
    assert est_gi.startswith("Est. cost:")
    assert "0.022" in est_gi
    est_gev = live_estimate_cost(
        model_choice="Video · Grok Imagine Edit Video",
        parameters_json='{"duration_seconds": 6, "resolution": "480p"}',
    )
    assert est_gev.startswith("Est. cost:")
    # 6s * $0.06 = $0.36
    assert "0.36" in est_gev
    est_gi2v = live_estimate_cost(
        model_choice="grok imagine 1.5 i2v",
        parameters_json='{"duration": "5", "resolution": "720p"}',
    )
    assert est_gi2v.startswith("Est. cost:")
    # 5 * 0.14 + 0.01 = 0.71
    assert "0.71" in est_gi2v
    print(
        "live estimates:",
        est,
        "|",
        est2,
        "|",
        est3,
        "|",
        est_gi,
        "|",
        est_gev,
        "|",
        est_gi2v,
    )

    # Defaults unchanged
    from media_studio.fal.models import default_image_edit_model, default_video_edit_model

    assert default_image_edit_model().key == "flux 2 pro"
    assert default_video_edit_model().key == "kling o3 standard edit"

    print("ALL MODEL EXPANSION CHECKS PASSED")


if __name__ == "__main__":
    main()
