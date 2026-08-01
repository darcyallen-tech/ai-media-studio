"""Unit checks for model lock + parameter clamp (no live API)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from media_studio.params_ui import clamp_parameters_to_model, is_auto_model
from media_studio.services import _normalize_enhance_payload


def main() -> None:
    assert is_auto_model("Auto (default)")
    assert is_auto_model(None)
    assert not is_auto_model("Image · Flux 2 Pro (edit)")

    # Flux 2 Pro: max 1 image, resolution auto
    params, notes = clamp_parameters_to_model(
        "flux 2 pro",
        {"num_images": 4, "resolution": "4K"},
        locked_model_key="flux 2 pro",
    )
    assert params["num_images"] == 1
    assert any("num_images" in n for n in notes)
    print("flux clamp OK", params, notes)

    # Nano Banana Pro: 4K may clamp to 2K (max_resolution)
    params2, notes2 = clamp_parameters_to_model(
        "nano banana pro",
        {"num_images": 9, "resolution": "4K"},
        locked_model_key="nano banana pro",
    )
    assert params2["num_images"] == 4
    assert params2["resolution"] == "2K"
    print("nano pro clamp OK", params2, notes2)

    r = _normalize_enhance_payload(
        {
            "optimized_prompt": "nice sofa",
            "chosen_model": "nano banana pro",
            "parameters": {"num_images": 2},
            "notes": ["ok"],
        },
        "raw",
    )
    assert r.optimized_prompt == "nice sofa"
    print("ALL ENHANCE LOCK UNIT CHECKS PASSED")


if __name__ == "__main__":
    main()
