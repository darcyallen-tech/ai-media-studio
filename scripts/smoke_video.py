"""Smoke checks for video-edit wiring (no live API required)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from media_studio.fal.client import extract_video_url
from media_studio.fal.models import (
    build_video_edit_arguments,
    default_video_edit_model,
    resolve_job_kind,
    resolve_video_edit_model,
)
from media_studio.services import describe_job_kind, generate


def main() -> None:
    from media_studio.fal.models import resolve_video_model

    kling = resolve_video_model("Kling Edit") or resolve_video_edit_model("Kling Edit")
    assert kling is not None
    assert "o3/standard/video-to-video/edit" in kling.endpoint
    assert "o3" in default_video_edit_model().endpoint
    print("resolve video models OK")

    args, notes = build_video_edit_arguments(
        kling,
        prompt="replace the sofa with a modern velvet couch",
        video_url="https://example.com/clip.mp4",
        image_urls=["https://example.com/sofa.png"],
        parameters={"keep_audio": True},
    )
    assert args["video_url"].endswith("clip.mp4")
    assert args["image_urls"] == ["https://example.com/sofa.png"]
    assert args["keep_audio"] is True
    assert "@Image1" in args["prompt"]
    assert any("Injected" in n or "@Image" in n for n in notes)
    print("build_video_edit_arguments OK")

    i2v = resolve_video_model("kling o3 standard i2v")
    assert i2v and i2v.task == "image_to_video"
    from media_studio.fal.models import build_i2v_arguments

    args2, notes2 = build_i2v_arguments(
        i2v,
        prompt="camera pans left",
        image_url="https://example.com/frame.png",
        parameters={"duration_seconds": 20},
    )
    assert args2["image_url"].endswith("frame.png")
    assert args2["duration"] == "15"  # clamped
    print("i2v duration clamp OK")

    url = extract_video_url(
        {"video": {"url": "https://cdn.example/out.mp4", "content_type": "video/mp4"}}
    )
    assert url == "https://cdn.example/out.mp4"
    print("extract_video_url OK")

    assert resolve_job_kind(None, has_image=True, has_video=False) == "image"
    assert resolve_job_kind(None, has_image=True, has_video=True) == "video"
    assert resolve_job_kind("Nano Banana Pro", has_image=True, has_video=True) == "image"
    assert resolve_job_kind("Kling Edit", has_image=True, has_video=False) == "video"
    print("resolve_job_kind OK")

    label = describe_job_kind("Auto (default)", None, None)
    assert "IMAGE" in label
    print("describe_job_kind:", label)

    # Missing video for video model
    res = generate(prompt="edit the room", model_choice="Kling Edit", video_file=None)
    assert not res.ok and res.job_kind == "video"
    assert "video" in res.status.lower()
    print("missing video handled:", res.status[:90])

    build_ui()
    print("UI builds OK")
    print("ALL VIDEO SMOKE CHECKS PASSED")


if __name__ == "__main__":
    main()
