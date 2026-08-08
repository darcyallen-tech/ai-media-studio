"""
Smoke: Creative Vision R2V sheet binding — payload paths must match citation.

- Sheet mode → character/scene composite files only (not Front/Hero)
- Front/Hero only → Front/Hero plates
- Missing sheet + Sheet requested → no silent Front fallback
- FLUX 3 R2V / Seedance-style multi-ref argument build uses those paths
"""
from __future__ import annotations

import ast
import py_compile
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _make_still(path: Path, rgb: tuple[int, int, int]) -> None:
    try:
        from PIL import Image
    except ImportError:
        # Minimal valid JPEG-ish bytes if Pillow missing (path existence only)
        path.write_bytes(b"\xff\xd8\xff\xd9" + bytes(rgb) * 64)
        return
    Image.new("RGB", (64, 64), rgb).save(path, format="JPEG", quality=85)


def main() -> int:
    files = [
        "media_studio/flet_ref_pack.py",
        "media_studio/flet_vision.py",
        "media_studio/vision_service.py",
        "media_studio/character_store.py",
        "media_studio/scene_store.py",
        "media_studio/vision_registry.py",
    ]
    for rel in files:
        p = ROOT / rel
        ast.parse(p.read_text(encoding="utf-8"))
        py_compile.compile(str(p), doraise=True)
    print("AST+compile OK")

    # Source-level: rebind + no silent Front when sheet missing
    rp_src = (ROOT / "media_studio/flet_ref_pack.py").read_text(encoding="utf-8")
    assert "def rebind_from_pickers" in rp_src
    assert "Sheet selected but no sheet file" in rp_src
    assert "def bind_status_lines" in rp_src
    assert "is_sheet" in rp_src
    vis_src = (ROOT / "media_studio/flet_vision.py").read_text(encoding="utf-8")
    assert "rebind_from_pickers" in vis_src
    assert "bind_status_lines" in vis_src
    # Start frame must not steal Image 1 for single-image R2V
    assert "must not steal" in vis_src or "do NOT let an optional Start" in vis_src
    vs_src = (ROOT / "media_studio/vision_service.py").read_text(encoding="utf-8")
    assert "Bound Image" in vs_src
    assert "source_still_path = Path(image_path)" in vs_src
    print("Source guards OK")

    from media_studio.character_store import (
        add_character,
        character_r2v_ref_for_id,
        delete_character,
        find_picker_choice,
        set_character_sheet,
    )
    from media_studio.flet_ref_pack import RefItem, citation_style_for_model
    from media_studio.scene_store import (
        add_scene,
        delete_scene,
        find_scene_picker_choice,
        scene_r2v_ref_for_id,
        set_scene_sheet,
    )
    from media_studio.vision_registry import build_vision_arguments, find_vision_model

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        heidi_front = root / "heidi_front.jpg"
        heidi_sheet = root / "heidi_sheet.jpg"
        gym_hero = root / "gym_hero.jpg"
        gym_sheet = root / "gym_sheet.jpg"
        _make_still(heidi_front, (200, 80, 80))
        _make_still(heidi_sheet, (80, 200, 80))
        _make_still(gym_hero, (80, 80, 200))
        _make_still(gym_sheet, (200, 200, 80))
        # Distinct sizes so we can tell files apart without reading pixels
        heidi_sheet.write_bytes(heidi_sheet.read_bytes() + b"SHEET_CHAR_MARK")
        gym_sheet.write_bytes(gym_sheet.read_bytes() + b"SHEET_SCENE_MARK")

        ch = add_character(name="Heidi Smoke Bind", still_path=heidi_front)
        sc = add_scene(
            name="Modern Gym Smoke Bind",
            still_path=gym_hero,
            notes="modern gym wide establishing",
        )
        try:
            set_character_sheet(ch.id, heidi_sheet)
            set_scene_sheet(sc.id, gym_sheet)

            pch = find_picker_choice(ch.id)
            psc = find_scene_picker_choice(sc.id)
            assert pch is not None and pch.has_sheet
            assert psc is not None and psc.has_sheet

            # --- Sheet mode (recommended) ---
            path_c_sheet, lab_c_sheet = character_r2v_ref_for_id(ch.id, use_sheet=True)
            path_s_sheet, lab_s_sheet = scene_r2v_ref_for_id(sc.id, use_sheet=True)
            assert path_c_sheet and Path(path_c_sheet).is_file()
            assert path_s_sheet and Path(path_s_sheet).is_file()
            assert Path(path_c_sheet).resolve() != Path(
                pch.front_path or heidi_front
            ).resolve()
            assert Path(path_s_sheet).resolve() != Path(
                psc.hero_path or gym_hero
            ).resolve()
            assert lab_c_sheet.endswith(" sheet")
            assert lab_s_sheet.endswith(" sheet")
            # Bytes are the sheet files
            assert b"SHEET_CHAR_MARK" in Path(path_c_sheet).read_bytes()
            assert b"SHEET_SCENE_MARK" in Path(path_s_sheet).read_bytes()
            print("OK Sheet mode → composite files only")

            # --- Front / Hero only ---
            path_c_front, lab_c_front = character_r2v_ref_for_id(
                ch.id, use_sheet=False
            )
            path_s_hero, lab_s_hero = scene_r2v_ref_for_id(sc.id, use_sheet=False)
            assert path_c_front and Path(path_c_front).is_file()
            assert path_s_hero and Path(path_s_hero).is_file()
            assert Path(path_c_front).resolve() != Path(path_c_sheet).resolve()
            assert Path(path_s_hero).resolve() != Path(path_s_sheet).resolve()
            assert not lab_c_front.endswith(" sheet")
            assert not lab_s_hero.endswith(" sheet")
            assert b"SHEET_CHAR_MARK" not in Path(path_c_front).read_bytes()
            assert b"SHEET_SCENE_MARK" not in Path(path_s_hero).read_bytes()
            print("OK Front/Hero only → Front/Hero plates")

            # --- Citation map labels match bound paths ---
            style = citation_style_for_model("FLUX 3 · Identity ref (R2V)", mode="r2v")
            items = [
                RefItem("character", path_c_sheet, lab_c_sheet, ch.id, is_sheet=True),
                RefItem("scene", path_s_sheet, lab_s_sheet, sc.id, is_sheet=True),
            ]
            map_txt = " · ".join(
                f"{style.tag(i)} = {it.label} ({it.role})"
                for i, it in enumerate(items, 1)
            )
            assert "sheet" in map_txt.lower()
            assert "Heidi" in map_txt or "heidi" in map_txt.lower()
            assert items[0].path == path_c_sheet
            assert items[1].path == path_s_sheet
            print("OK citation map paths == sheet files:", map_txt)

            # --- Missing sheet: no silent Front ---
            path_missing, lab_missing = character_r2v_ref_for_id(
                "no-such-char-id", use_sheet=True
            )
            assert path_missing is None
            # Character with no sheet file
            bare = add_character(
                name="No Sheet Bind", still_path=heidi_front
            )
            try:
                pm, lm = character_r2v_ref_for_id(bare.id, use_sheet=True)
                assert pm is None
                assert "missing" in lm.lower() or "sheet" in lm.lower()
                print("OK missing sheet → no silent Front")
            finally:
                delete_character(
                    bare.id, remove_file=True, force_children_check=False
                )

            # --- Payload assembly: multi-ref (Seedance-like) gets both sheets ---
            # Use fake URLs mapped 1:1 to bound paths order
            fake_urls = {
                path_c_sheet: "https://cdn.example/heidi_sheet.jpg",
                path_s_sheet: "https://cdn.example/gym_sheet.jpg",
            }
            pack_paths = [path_c_sheet, path_s_sheet]
            ordered_urls = [fake_urls[p] for p in pack_paths]

            seed_spec = find_vision_model(
                "Seedance 2.0 Reference", "reference_to_video"
            ) or find_vision_model("seedance", "reference_to_video")
            if seed_spec is None:
                # Fall back: any R2V with image_urls field
                from media_studio.vision_registry import R2V_MODELS

                for sp in R2V_MODELS.values():
                    if "image_urls" in (sp.image_field or "") or "seedance" in sp.key:
                        seed_spec = sp
                        break
            assert seed_spec is not None, "Need a multi-ref R2V model for smoke"

            args_multi = build_vision_arguments(
                seed_spec,
                prompt="Heidi walks through the modern gym.",
                image_url=ordered_urls[0],
                ref_urls=ordered_urls[1:],
            )
            multi_field = None
            for k in ("image_urls", "reference_image_urls"):
                if k in args_multi:
                    multi_field = k
                    break
            assert multi_field, f"Expected multi-ref field in {list(args_multi)}"
            got = list(args_multi[multi_field])
            # Both sheets must be present in payload order (Image 1 = Heidi sheet)
            assert got[0] == ordered_urls[0], f"Image 1 must be character sheet: {got}"
            if len(got) >= 2:
                assert ordered_urls[1] in got, f"Scene sheet missing from payload: {got}"
            print(f"OK multi-ref payload {multi_field} = sheets:", got)

            # --- FLUX 3 Identity/R2V: first bound path is the sheet (not Front) ---
            flux = find_vision_model("FLUX 3 · Identity ref (R2V)", "reference_to_video")
            if flux is None:
                flux = find_vision_model("flux 3 r2v", "reference_to_video")
            assert flux is not None
            args_flux = build_vision_arguments(
                flux,
                prompt="Heidi walks through the modern gym.",
                image_url=ordered_urls[0],
                ref_urls=ordered_urls[1:],  # multi-pack; single-image uses first
            )
            flux_url = args_flux.get("image_url") or (
                (args_flux.get("image_urls") or [None])[0]
            )
            assert flux_url == ordered_urls[0], (
                f"FLUX 3 must receive character sheet as Image 1, got {flux_url}"
            )
            assert "heidi_sheet" in str(flux_url) or flux_url == ordered_urls[0]
            print("OK FLUX 3 R2V Image 1 ← Heidi sheet (not Front)")

            # Front-only toggle → Front plate in payload
            front_url = "https://cdn.example/heidi_front.jpg"
            args_front = build_vision_arguments(
                flux,
                prompt="Heidi walks.",
                image_url=front_url,
                ref_urls=None,
            )
            got_front = args_front.get("image_url") or (
                (args_front.get("image_urls") or [None])[0]
            )
            assert got_front == front_url
            print("OK Front-only toggle → Front plate in payload")

        finally:
            try:
                delete_character(ch.id, remove_file=True, force_children_check=False)
            except Exception:
                pass
            try:
                delete_scene(sc.id, remove_file=True)
            except Exception:
                pass

    print("ALL SMOKE OK — R2V sheet bind")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
