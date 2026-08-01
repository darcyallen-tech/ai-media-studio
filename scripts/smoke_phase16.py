"""Phase 16 + Image/Video tab smoke checks (no network)."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from media_studio.fal.models import default_image_edit_model
from media_studio.naming import (
    date_bucket,
    job_media_dir,
    kind_slug,
    make_output_stem,
    scenario_slug,
)
from media_studio.pricing import format_render_metrics, live_estimate_cost
from media_studio.scenarios import (
    CAMERA_MATCH_CORE,
    DEFAULT_IMAGE_MODEL,
    DEFAULT_VIDEO_EDIT_MODEL,
    build_scenario_prompt,
    build_video_ref_prompt,
)
from media_studio.tools_registry import DEHAZE_MODELS, UPSCALERS, format_tool_cost


def main() -> None:
    stem = make_output_stem(
        "stage living room modern",
        "flux 2 pro",
        kind="edit",
        scenario="furniture_popin",
    )
    assert "__sc-furniture-popin__" in stem, stem
    assert kind_slug("dehaze") == "tool-dehaze"
    assert scenario_slug("day_to_night") == "day-to-night"
    assert date_bucket("20260726_120000") == "2026-07-26"

    td = Path(tempfile.mkdtemp())
    md = job_media_dir(td, stamp="20260726_153000")
    assert md.name == "2026-07-26"

    c1 = live_estimate_cost(
        model_choice=DEFAULT_IMAGE_MODEL,
        parameters_json='{"num_images": 1}',
    )
    assert "Est. cost:" in c1 and "$" in c1, c1
    assert default_image_edit_model().key == "flux 2 pro"

    m = format_render_metrics(7.3, 0.03, cost_is_estimate=True)
    assert "Rendered in 7.3s" in m

    assert "Est. cost:" in format_tool_cost(list(DEHAZE_MODELS.values())[0])
    assert "Est. cost:" in format_tool_cost(list(UPSCALERS.values())[0])

    # Image/Video tab prompts
    vp = build_video_ref_prompt("furniture_popin")
    assert CAMERA_MATCH_CORE in vp
    assert "Do not invent new camera movement" in vp
    for key in (
        "day_to_night",
        "twilight_exterior",
        "sky_mood",
        "lot_to_home",
        "dehaze",
        "landscaper",
    ):
        p = build_video_ref_prompt(key)
        assert "camera movement" in p.lower()
        assert "@Image1" in p and "@Video1" in p

    still = build_scenario_prompt("furniture_popin")
    assert "Edit this" in still or "furniture" in still.lower()

    land = build_scenario_prompt(
        "landscaper",
        opt_a="Medium",
        opt_b="Medium deciduous",
        opt_c="Full foundation",
        opt_d="Established manicured",
    )
    assert "landscap" in land.lower()
    assert "manicured" in land.lower() or "foundation" in land.lower()

    out = _on_scenario_switch("Twilight Exterior", DEFAULT_IMAGE_MODEL)
    assert len(out) == 12
    assert out[7]  # image prompt
    assert "camera" in out[8].lower()  # video prompt
    assert out[9] == DEFAULT_IMAGE_MODEL

    empty = _on_send_to_video(None, None, None, "Furniture Pop-in")
    assert len(empty) == 14

    demo = None  # Flet app; Gradio build_ui removed
    assert demo is not None
    assert True  # Gradio CSS removed
    assert DEFAULT_VIDEO_EDIT_MODEL.startswith("Video · Kling")

    print("OK Phase 16 + Image/Video tabs")
    print("stem:", stem)
    print("video snip:", vp[:140])
    print("image snip:", still[:120])


if __name__ == "__main__":
    main()
