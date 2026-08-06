"""Smoke: ASPECT_DEBUG visible via classify + written to aspect_debug.log."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from media_studio.aspect_omit import (
    append_aspect_debug_log,
    apply_aspect_policy,
    aspect_debug_line,
    strip_all_aspect_keys,
)
from media_studio.flet_progress import classify_progress


def main() -> int:
    long = (
        "ASPECT_DEBUG source=fal.subscribe "
        "endpoint=bytedance/seedance-2.0/reference-to-video omit=True "
        "keys=['duration', 'generate_audio', 'image_urls', 'prompt', 'resolution'] "
        "aspect_ratio='<missing>'"
    )
    out = classify_progress(long)
    assert out.startswith("ASPECT_DEBUG"), out
    assert "Generating" not in out, out
    print("classify pass-through OK")

    ep = "bytedance/seedance-2.0/reference-to-video"
    args = apply_aspect_policy(
        {
            "aspect_ratio": "16:9",
            "image_aspect_ratio": "16:9",
            "aspectRatio": "9:16",
            "prompt": "x",
        },
        endpoint=ep,
        requested="16:9",
    )
    args = strip_all_aspect_keys(args)
    for k in ("aspect_ratio", "aspectRatio", "image_aspect_ratio"):
        assert k not in args, args
    line = aspect_debug_line(
        endpoint=ep,
        arguments=args,
        mode="reference_to_video",
        omit=True,
        source="fal.subscribe",
    )
    print(line)
    p = append_aspect_debug_log(line)
    print("log path", p, "exists", p.is_file())
    tail = p.read_text(encoding="utf-8").splitlines()[-1]
    print(tail)
    assert "ASPECT_DEBUG" in tail
    print("SMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
