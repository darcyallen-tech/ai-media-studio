"""
Smoke: Tools Sky / Weather full workflow wiring.

- Still sky models + V2V Kling family
- Cost: still = 1 image; V2V = duration (never “1 image”)
- Sky ref path reaches run_sky / _run_v2v_tool
- Still → Use for V2V / Use as sky ref hooks on DualMediaToolCard
- Video result → Send to Upscale handoff (receive_media preload)
"""
from __future__ import annotations

import ast
import inspect
import py_compile
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    files = [
        "media_studio/flet_dual_tool.py",
        "media_studio/flet_tools.py",
        "media_studio/flet_tools_result.py",
        "media_studio/tools_registry.py",
        "media_studio/tools_service.py",
        "media_studio/flet_send_to.py",
    ]
    for rel in files:
        p = ROOT / rel
        ast.parse(p.read_text(encoding="utf-8"))
        py_compile.compile(str(p), doraise=True)
    print("AST+compile OK")

    from media_studio.tools_registry import (
        SKY_MODELS,
        VIDEO_SKY_MODELS,
        format_tool_cost,
        sky_labels,
        video_sky_labels,
    )
    from media_studio.tools_service import run_sky

    # --- Still models preserved ---
    still_labs = sky_labels()
    assert any("Nano Banana" in x for x in still_labs)
    assert all(s.cost_per_second is None for s in SKY_MODELS.values())
    still_spec = next(iter(SKY_MODELS.values()))
    still_cost = format_tool_cost(still_spec, mode="image")
    assert "1 image" in still_cost.lower() or "image" in still_cost.lower()
    assert "s ·" not in still_cost or "1 image" in still_cost.lower()
    print("OK still sky cost:", still_cost)

    # --- V2V Kling family ---
    v_labs = video_sky_labels()
    assert any("Kling O3 Standard" in x for x in v_labs)
    assert any("Kling O3 Pro" in x for x in v_labs)
    assert any("Kling O1" in x for x in v_labs)
    kling = VIDEO_SKY_MODELS["kling o3 standard sky"]
    assert kling.cost_per_second and kling.cost_per_second > 0
    v_cost = format_tool_cost(kling, mode="video", duration_s=5.0)
    assert "1 image" not in v_cost.lower(), v_cost
    assert "5s" in v_cost or "$" in v_cost
    # ~5 * 0.126 = 0.63
    assert "0.63" in v_cost or "0.6" in v_cost
    print("OK V2V Kling cost (not 1 image):", v_cost)

    unk = format_tool_cost(kling, mode="video", duration_s=None)
    assert "duration unknown" in unk.lower() or "5s" in unk
    print("OK V2V unknown duration label:", unk)

    # --- run_sky accepts sky ref ---
    sig = inspect.signature(run_sky)
    assert "reference_image" in sig.parameters or "sky_ref_path" in sig.parameters
    src = (ROOT / "media_studio/tools_service.py").read_text(encoding="utf-8")
    assert "kling o1 standard sky" in src
    assert "reference_image" in src
    print("OK run_sky sky ref + Kling O1 map")

    # --- DualMedia sky ref hooks ---
    dual = (ROOT / "media_studio/flet_dual_tool.py").read_text(encoding="utf-8")
    assert "enable_v2v_ref" in dual
    assert "load_v2v_ref" in dual
    assert "_use_still_for_v2v" in dual
    assert "Use for V2V" in dual
    assert "Use as sky ref" in dual
    assert "_prefer_kling_v2v_model" in dual
    print("OK DualMedia sky-ref + Use for V2V")

    tools = (ROOT / "media_studio/flet_tools.py").read_text(encoding="utf-8")
    assert "enable_v2v_ref=True" in tools
    assert "suggest_kling_on_video=True" in tools
    print("OK Tools sky card flags")

    # --- Upscale handoff ---
    res_src = (ROOT / "media_studio/flet_tools_result.py").read_text(encoding="utf-8")
    assert "Send to Upscale" in res_src
    assert "offer_upscale_prompt" in res_src
    assert "_maybe_offer_upscale" in res_src
    send = (ROOT / "media_studio/flet_send_to.py").read_text(encoding="utf-8")
    assert 'send_to_tool' in send
    assert '"upscale"' in send
    # receive_media preloads upscale video
    assert "receive_media" in tools
    print("OK Send to Upscale wiring")

    # Simulated handoff: ToolsView.receive_media signature
    from media_studio.flet_tools import ToolsView

    assert hasattr(ToolsView, "receive_media")
    print("OK ToolsView.receive_media for Upscale preload")

    print("ALL SMOKE OK — sky weather workflow")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
