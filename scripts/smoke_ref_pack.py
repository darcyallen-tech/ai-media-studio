"""Smoke: R2V/R2I ref pack UI wiring (no Flet page required)."""
from __future__ import annotations

import ast
import py_compile
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FILES = [
    "media_studio/flet_ref_pack.py",
    "media_studio/flet_vision.py",
    "media_studio/flet_video.py",
    "media_studio/flet_app.py",
]


def main() -> int:
    for rel in FILES:
        p = ROOT / rel
        ast.parse(p.read_text(encoding="utf-8"))
        py_compile.compile(str(p), doraise=True)
    print("AST+compile OK")

    from media_studio.flet_ref_pack import (
        RefItem,
        citation_style_for_model,
        max_character_slots,
    )

    assert citation_style_for_model("H3 Omni", mode="r2v").tag(1) == "Image 1"
    assert citation_style_for_model("H3 Omni", mode="r2v").tag(2) == "Image 2"
    assert max_character_slots("H3 Omni", mode="r2v") >= 2

    items = [
        RefItem("character", "c1.jpg", "Camera Man"),
        RefItem("character", "c2.jpg", "Alice"),
        RefItem("scene", "s1.jpg", "Tavern"),
    ]
    style = citation_style_for_model("H3 Omni", mode="r2v")
    map_txt = " · ".join(
        f"{style.tag(i)} = {it.label} ({it.role})" for i, it in enumerate(items, 1)
    )
    assert "Image 1 = Camera Man (character)" in map_txt
    assert "Image 2 = Alice (character)" in map_txt
    assert "Image 3 = Tavern (scene)" in map_txt
    print("citation map:", map_txt)

    app = (ROOT / "media_studio/flet_app.py").read_text(encoding="utf-8")
    assert "_on_image_ref_pack_change" in app
    assert "Character identity ref (not source)" in app
    assert "RefPackPanel" in app

    vid = (ROOT / "media_studio/flet_video.py").read_text(encoding="utf-8")
    idx = vid.find("async def _add_identity_char_slot")
    assert idx > 0
    chunk = vid[idx : idx + 900]
    assert "CharacterPicker" in chunk
    assert "pick_image" not in chunk
    assert "RefPackPanel" in vid
    print("Studio Video Add character → CharacterPicker (not folder)")

    rp = (ROOT / "media_studio/flet_ref_pack.py").read_text(encoding="utf-8")
    idx = rp.find("async def _on_add_character")
    chunk = rp[idx : idx + 600]
    assert "_ensure_char_pickers" in chunk
    assert "pick_image" not in chunk
    print("RefPack Add character → library dropdown")

    vis = (ROOT / "media_studio/flet_vision.py").read_text(encoding="utf-8")
    assert "start_frames_row" in vis
    assert "Character is identity, not source" in vis
    assert "ref_pack" in vis

    from media_studio.studio_modality import models_for_video_modality

    r2v = models_for_video_modality("r2v")
    i2v = models_for_video_modality("i2v")
    assert any("omni" in m.lower() or "reference" in m.lower() for m in r2v)
    assert not any("omni" in m.lower() and "reference" in m.lower() for m in i2v)
    print("R2V holds multi-ref/omni; I2V does not leak omni reference")
    print("ALL SMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
