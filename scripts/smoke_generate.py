"""Smoke checks for fal image-edit wiring (no live API required)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from media_studio.fal.client import extract_image_urls, slugify
from media_studio.fal.models import (
    build_edit_arguments,
    default_image_edit_model,
    resolve_image_edit_model,
)
from media_studio.services import GenerateResult, _parse_parameters_json, generate


def main() -> None:
    pro = resolve_image_edit_model("Nano Banana Pro")
    assert pro is not None
    assert pro.endpoint == "fal-ai/nano-banana-pro/edit"
    assert default_image_edit_model().key == "nano banana pro"
    print("resolve models OK")

    args, notes = build_edit_arguments(
        pro,
        prompt="make it sunset",
        image_urls=["https://example.com/a.png"],
        parameters={
            "num_images": 9,
            "resolution": "4K",
            "aspect_ratio": "16:9",
            "seed": 42,
        },
    )
    assert args["prompt"] == "make it sunset"
    assert args["image_urls"] == ["https://example.com/a.png"]
    assert args["num_images"] == 4  # clamped
    assert args["resolution"] == "2K"  # clamped from 4K
    assert args["aspect_ratio"] == "16:9"
    assert args["seed"] == 42
    assert any("clamped" in n.lower() or "num_images" in n for n in notes)
    print("build_edit_arguments OK:", args, notes)

    nano = resolve_image_edit_model("nano banana")
    assert nano and nano.endpoint.endswith("nano-banana/edit")

    flux = resolve_image_edit_model("flux kontext pro")
    assert flux and flux.image_field == "image_url"
    args2, _ = build_edit_arguments(
        flux,
        prompt="edit",
        image_urls=["https://example.com/a.png", "https://example.com/b.png"],
    )
    assert args2["image_url"] == "https://example.com/a.png"
    print("flux kontext single-image OK")

    urls = extract_image_urls(
        {"images": [{"url": "https://x/a.png"}, {"url": "https://x/b.png"}]}
    )
    assert urls == ["https://x/a.png", "https://x/b.png"]
    assert slugify("Nano Banana Pro") == "nano-banana-pro"
    print("client helpers OK")

    params = _parse_parameters_json('{"num_images": 2, "resolution": "1K"}')
    assert params["num_images"] == 2

    # Missing FAL_KEY should fail cleanly
    import os

    saved = os.environ.pop("FAL_KEY", None)
    os.environ.pop("FAL_API_KEY", None)
    # Use a temp image if we have one, else skip live path and just call with no image
    res = generate(prompt="x", image_file=None, video_file=None)
    assert not res.ok
    assert "image" in res.status.lower() or "upload" in res.status.lower()
    print("missing image handled:", res.status[:80])

    if saved:
        os.environ["FAL_KEY"] = saved

    build_ui()
    print("UI builds OK")
    print("ALL GENERATE SMOKE CHECKS PASSED")


if __name__ == "__main__":
    main()
