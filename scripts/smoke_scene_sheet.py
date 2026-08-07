"""Smoke: Scene reference sheet (single-shot + Enhance tone rules)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from PIL import Image

from media_studio.scene_store import (
    SHEET_DENSITY_OPTS,
    SHEET_HELPER_NONE,
    add_scene,
    assemble_scene_sheet_prompt,
    delete_scene,
    find_scene,
    find_scene_picker_choice,
    preferred_scene_sheet_model,
    prompt_has_banned_real_estate,
    scene_sheet_enhance_guidance,
    set_scene_sheet,
)


def _still(path: Path, color: tuple[int, int, int] = (80, 90, 100)) -> None:
    Image.new("RGB", (128, 96), color).save(path, format="JPEG")


def test_prompt_t2i_and_i2i() -> None:
    t2i = assemble_scene_sheet_prompt(
        mode="t2i",
        location_type="Urban street",
        condition="Damaged/aftermath",
        time_light="Overcast",
        camera_lang=SHEET_HELPER_NONE,  # None → no real-estate
        density="Standard",
        landmarks="scorched storefront, broken glass",
        no_people=True,
        no_logos=True,
        scene_name="Damaged street",
    )
    assert "SINGLE still" in t2i or "single still" in t2i.lower()
    assert "North" in t2i and "South" in t2i
    assert "production design" in t2i.lower() or "location-bible" in t2i.lower()
    assert "invent ONE coherent" in t2i or "invent one coherent" in t2i.lower()
    # Neutral path: production-design default, no user-selected RE camera line
    assert "user-selected" not in t2i.lower()
    assert "production design" in t2i.lower()
    # No long NOT MLS/brochure spam in default prompt
    assert "mls" not in t2i.lower()
    assert "brochure" not in t2i.lower()

    i2i = assemble_scene_sheet_prompt(
        mode="i2i",
        location_type="Commercial interior",
        condition="Pristine",
        density="Compact",
        landmarks="rubber mats, mirrors",
        no_people=True,
    )
    assert "AUTHORITATIVE" in i2i or "authoritative" in i2i.lower()
    assert "do not restyle" in i2i.lower()
    assert "Standard" in SHEET_DENSITY_OPTS
    print("OK scene sheet prompts T2I + I2I (no RE default)")


def test_camera_lang_real_estate_only_when_selected() -> None:
    """Camera language None + cinematic intent → no RE; Documentary/RE → allowed."""
    neutral = assemble_scene_sheet_prompt(
        mode="t2i",
        location_type="Urban street",
        condition="Damaged/aftermath",
        camera_lang=None,
        landmarks="marvel-cinematic ruined street, wet asphalt, smoke columns",
    )
    assert "production design" in neutral.lower()
    assert "user-selected" not in neutral.lower()
    assert "mls" not in neutral.lower() and "brochure" not in neutral.lower()
    # Marvel-cinematic landmarks allowed as content without RE camera
    assert "marvel-cinematic" in neutral.lower() or "ruined street" in neutral.lower()

    re_prompt = assemble_scene_sheet_prompt(
        mode="t2i",
        location_type="Residential interior",
        camera_lang="Documentary/real-estate",
        landmarks="warm kitchen, evening light",
    )
    assert "user-selected" in re_prompt.lower()
    assert "documentary" in re_prompt.lower() or "real-estate" in re_prompt.lower()

    cin = assemble_scene_sheet_prompt(
        mode="t2i",
        camera_lang="Cinematic wide",
        landmarks="ruined avenue",
    )
    assert "cinematic wide" in cin.lower()
    assert "user-selected" in cin.lower()

    elev = assemble_scene_sheet_prompt(
        mode="t2i",
        camera_lang="Architectural elevation",
    )
    assert "architectural elevation" in elev.lower()

    # Exterior toggle
    ext = assemble_scene_sheet_prompt(
        mode="t2i",
        location_type="Residential interior",
        include_exterior_entrance=True,
    )
    assert "exterior" in ext.lower() or "entrance" in ext.lower()
    print("OK camera language + exterior toggle")


def test_enhance_guidance_tone() -> None:
    g_none = scene_sheet_enhance_guidance(camera_lang=None, mode="t2i")
    assert "production design" in g_none.lower() or "location reference" in g_none.lower()
    # No long MLS/brochure negation spam
    assert "mls" not in g_none.lower()
    assert "brochure" not in g_none.lower()
    assert g_none.lower().count("not ") < 4

    g_re = scene_sheet_enhance_guidance(
        camera_lang="Documentary/real-estate", mode="t2i"
    )
    assert "documentary" in g_re.lower() or "real-estate" in g_re.lower()
    assert "allowed" in g_re.lower()
    print("OK Enhance guidance tone (short, no MLS spam)")


def test_accept_stores_sheet_and_picker_prefers() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        hero = root / "gym.jpg"
        sheet = root / "sheet.jpg"
        _still(hero, (40, 50, 60))
        _still(sheet, (10, 20, 30))

        entry = add_scene(name="Modern Gym Smoke", still_path=hero, notes="gym plate")
        try:
            assert not entry.has_sheet()
            updated = set_scene_sheet(entry.id, sheet)
            assert updated is not None
            assert updated.has_sheet()
            assert updated.sheet_file()
            # Hero pack unchanged
            assert updated.resolved_still_path()
            assert Path(updated.resolved_still_path() or "").is_file()

            reloaded = find_scene(entry.id)
            assert reloaded is not None and reloaded.has_sheet()

            ch = find_scene_picker_choice(entry.id)
            assert ch is not None
            assert ch.has_sheet
            path_sheet = ch.ref_path(use_sheet=True)
            path_hero = ch.ref_path(use_sheet=False)
            assert path_sheet and Path(path_sheet).is_file()
            assert path_hero and Path(path_hero).is_file()
            assert Path(path_sheet).resolve() != Path(path_hero).resolve()
            assert ch.ref_label(use_sheet=True).endswith(" sheet")
            assert not ch.ref_label(use_sheet=False).endswith(" sheet")
            print("OK Accept stores sheet; picker prefers composite")
        finally:
            delete_scene(entry.id, force=True, force_children_check=False)


def test_preferred_model_suggests_nano_or_seedream() -> None:
    m = preferred_scene_sheet_model(mode="t2i").lower()
    assert m
    print("OK preferred sheet model:", preferred_scene_sheet_model(mode="t2i"))


def test_multi_max_and_variation_accept() -> None:
    """Batch max ≥1; accept variation creates child under parent, not top-level."""
    from media_studio.scene_store import (
        list_base_scenes,
        list_scene_variations,
        scene_sheet_max_images,
    )

    n = scene_sheet_max_images(preferred_scene_sheet_model(mode="t2i"), mode="t2i")
    assert n >= 1
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        hero = root / "h.jpg"
        sh1 = root / "s1.jpg"
        sh2 = root / "s2.jpg"
        _still(hero)
        _still(sh1, (1, 2, 3))
        _still(sh2, (4, 5, 6))
        parent = add_scene(name="City Park Multi", still_path=hero)
        try:
            set_scene_sheet(parent.id, sh1)
            # Variation = child under parent
            var = add_scene(
                name=f"{parent.display_name()} · sheet var 1",
                still_path=sh2,
                parent_id=parent.id,
            )
            kids = list_scene_variations(parent.id)
            assert any(k.id == var.id for k in kids)
            bases = [b.id for b in list_base_scenes()]
            assert var.id not in bases
            assert parent.id in bases
            print("OK multi max + variation under scene")
        finally:
            delete_scene(parent.id, force=True, delete_children=True)


if __name__ == "__main__":
    test_prompt_t2i_and_i2i()
    test_camera_lang_real_estate_only_when_selected()
    test_enhance_guidance_tone()
    test_accept_stores_sheet_and_picker_prefers()
    test_preferred_model_suggests_nano_or_seedream()
    test_multi_max_and_variation_accept()
    print("all smoke_scene_sheet passed")
