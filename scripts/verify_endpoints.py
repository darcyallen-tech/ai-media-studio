"""Verify every registered model has a plausible fal endpoint ID."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from media_studio.audio_registry import (
    AMBIENCE_MODELS,
    MUSIC_MODELS,
    SFX_MODELS,
    VIDEO_SFX_MODELS,
    VOICE_CLONE_MODELS,
    VOICEOVER_MODELS,
)
from media_studio.fal.models import IMAGE_EDIT_MODELS, VIDEO_MODELS
from media_studio.tools_registry import (
    CLEANUP_MODELS,
    DEHAZE_MODELS,
    SKY_MODELS,
    UPSCALERS,
    VIDEO_UPSCALERS,
)

# Known-good endpoint IDs (from fal.ai docs / playgrounds)
EXPECTED_IMAGE = {
    "flux 2 pro": "fal-ai/flux-2-pro/edit",
    "flux 2 max": "fal-ai/flux-2-max/edit",
    "mai image 2.5 pro": "microsoft/mai-image-2.5-pro/edit",
    "mai image 2.5": "microsoft/mai-image-2.5/edit",
    "nano banana pro": "fal-ai/nano-banana-pro/edit",
    "nano banana 2": "fal-ai/nano-banana-2/edit",
    "seedream 5 pro": "fal-ai/bytedance/seedream/v4.5/edit",
    "flux 2 flex": "fal-ai/flux-2-flex/edit",
    "flux kontext pro": "fal-ai/flux-pro/kontext",
    "grok imagine edit": "xai/grok-imagine-image/edit",
    "grok imagine quality edit": "xai/grok-imagine-image/quality/edit",
    "nano banana": "fal-ai/nano-banana/edit",
}

EXPECTED_VIDEO = {
    "kling o3 standard edit": "fal-ai/kling-video/o3/standard/video-to-video/edit",
    "kling o3 pro edit": "fal-ai/kling-video/o3/pro/video-to-video/edit",
    "kling o1 standard edit": "fal-ai/kling-video/o1/standard/video-to-video/edit",
    "kling o1 pro edit": "fal-ai/kling-video/o1/video-to-video/edit",
    "seedance 2.0 v2v": "bytedance/seedance-2.0/reference-to-video",
    "seedance 2.0 fast v2v": "bytedance/seedance-2.0/fast/reference-to-video",
    "ltx retake": "fal-ai/ltx-2.3/retake-video",
    "grok imagine edit video": "xai/grok-imagine-video/edit-video",
    "kling o3 standard i2v": "fal-ai/kling-video/o3/standard/image-to-video",
    "kling o3 pro i2v": "fal-ai/kling-video/o3/pro/image-to-video",
    "kling v3 standard i2v": "fal-ai/kling-video/v3/standard/image-to-video",
    "kling v3 pro i2v": "fal-ai/kling-video/v3/pro/image-to-video",
    "kling 2.6 pro i2v": "fal-ai/kling-video/v2.6/pro/image-to-video",
    "kling 2.5 turbo pro i2v": "fal-ai/kling-video/v2.5-turbo/pro/image-to-video",
    "grok imagine 1.5 i2v": "xai/grok-imagine-video/v1.5/image-to-video",
    "seedance 2.0 i2v": "bytedance/seedance-2.0/image-to-video",
    "seedance 2.0 fast i2v": "bytedance/seedance-2.0/fast/image-to-video",
    "seedance 2.0 reference": "bytedance/seedance-2.0/reference-to-video",
}


def main() -> None:
    ok = True
    for key, spec in IMAGE_EDIT_MODELS.items():
        exp = EXPECTED_IMAGE.get(key)
        status = "OK" if exp and exp == spec.endpoint else ("CHECK" if not exp else "MISMATCH")
        if status != "OK":
            ok = False
        print(f"[{status}] image {key}: {spec.endpoint}")

    for key, spec in VIDEO_MODELS.items():
        if key == "kling edit":
            continue
        exp = EXPECTED_VIDEO.get(key)
        status = "OK" if exp and exp == spec.endpoint else ("CHECK" if not exp else "MISMATCH")
        if status != "OK" and key in EXPECTED_VIDEO:
            ok = False
        print(f"[{status}] video {key}: {spec.endpoint}")

    print("--- tools ---")
    for reg_name, reg in (
        ("upscale", UPSCALERS),
        ("video_upscale", VIDEO_UPSCALERS),
        ("cleanup", CLEANUP_MODELS),
        ("sky", SKY_MODELS),
        ("dehaze", DEHAZE_MODELS),
    ):
        for key, spec in reg.items():
            print(f"[tool:{reg_name}] {key}: {spec.endpoint} (${spec.cost_estimate_usd})")

    print("--- audio ---")
    for reg_name, reg in (
        ("music", MUSIC_MODELS),
        ("sfx", SFX_MODELS),
        ("ambience", AMBIENCE_MODELS),
        ("video_sfx", VIDEO_SFX_MODELS),
        ("voiceover", VOICEOVER_MODELS),
        ("clone", VOICE_CLONE_MODELS),
    ):
        for key, spec in reg.items():
            print(f"[audio:{reg_name}] {key}: {spec.endpoint}")

    # Minimums for UX goal
    assert len([k for k in IMAGE_EDIT_MODELS if k != "nano banana"]) >= 4
    assert len(UPSCALERS) >= 2
    assert len(VIDEO_UPSCALERS) >= 2
    assert len(CLEANUP_MODELS) >= 2
    assert len(SKY_MODELS) >= 2
    assert len(DEHAZE_MODELS) >= 2
    assert len(MUSIC_MODELS) >= 3
    assert len(SFX_MODELS) >= 2
    assert len(AMBIENCE_MODELS) >= 1
    assert len(VIDEO_SFX_MODELS) >= 4  # MMAudio, Mirelo, Sonilo, Kling (+ mix)
    assert "mmaudio v2" in VIDEO_SFX_MODELS
    assert VIDEO_SFX_MODELS["mmaudio v2"].endpoint == "fal-ai/mmaudio-v2"
    assert "mirelo sfx v1.5" in VIDEO_SFX_MODELS
    assert "kling video to audio" in VIDEO_SFX_MODELS
    assert "sonilo video sfx" in VIDEO_SFX_MODELS
    assert len(VOICEOVER_MODELS) >= 2
    assert "flux 2 max" in IMAGE_EDIT_MODELS
    assert "mai image 2.5 pro" in IMAGE_EDIT_MODELS
    assert "seedance 2.0 v2v" in VIDEO_MODELS
    print("verify_endpoints OK" if ok else "verify_endpoints had CHECK/MISMATCH rows")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
