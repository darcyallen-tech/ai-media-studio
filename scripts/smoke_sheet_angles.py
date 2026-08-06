"""Smoke: Character sheet angles Phase 1 (store + prompts + accept path)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from PIL import Image

from media_studio.character_store import (
    ALL_IDENTITY_SLOTS,
    LOCAL_SHEET_LAYOUT_MODEL,
    SHEET_AI_AREA_TOO_LARGE_MSG,
    SHEET_AI_MAX_SIDE,
    SHEET_ANGLE_SLOTS,
    SLOT_SHORT,
    add_character,
    auto_sheet_layout,
    character_sheet_citation_label,
    compose_character_sheet_local,
    delete_character,
    find_character,
    friendly_sheet_compose_error,
    is_local_sheet_layout,
    is_sheet_angle_slot,
    is_sheet_area_too_large_error,
    load_characters,
    prepare_sheet_ai_angle_refs,
    set_character_sheet,
    set_character_slot,
    sheet_angle_identity_for_character,
    sheet_angle_prompt_for_slot,
    sheet_angle_ref_order,
)


def _make_still(path: Path, color: tuple[int, int, int]) -> None:
    Image.new("RGB", (64, 64), color).save(path, format="JPEG")


def test_sheet_slots_and_prompts() -> None:
    assert "back" in SHEET_ANGLE_SLOTS
    assert "threequarter_front" in SHEET_ANGLE_SLOTS
    assert is_sheet_angle_slot("Back")
    assert is_sheet_angle_slot("¾ front") or is_sheet_angle_slot("threequarter_front")
    p = sheet_angle_prompt_for_slot("back")
    assert "same person" in p.lower() or "Same person" in p
    assert "outfit" in p.lower()
    assert "back" in p.lower()
    assert "no new clothing" in p.lower() or "no costume" in p.lower()
    print("OK prompts + slot keys")


def test_accept_back_slot() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        front = root / "front.jpg"
        side = root / "side.jpg"
        closeup = root / "closeup.jpg"
        back = root / "back.jpg"
        _make_still(front, (200, 100, 80))
        _make_still(side, (190, 95, 75))
        _make_still(closeup, (180, 90, 70))
        _make_still(back, (170, 85, 65))

        # Use real store paths under project data via add_character
        entry = add_character(
            name="Sheet Smoke Test Char",
            still_path=front,
            notes="smoke sheet angles",
            identity={
                "front": front,
                "side": side,
                "closeup": closeup,
            },
        )
        try:
            assert entry.has_front()
            missing = entry.missing_sheet_angles()
            assert "back" in missing
            assert set(missing) == set(SHEET_ANGLE_SLOTS)

            refs = sheet_angle_ref_order(entry.normalized_identity())
            assert len(refs) >= 3
            # Front first
            assert Path(refs[0]).is_file()

            updated = set_character_slot(entry.id, "back", back)
            assert updated is not None
            assert updated.get_slot("back")
            assert Path(updated.get_slot("back") or "").is_file()
            assert "back" not in updated.missing_sheet_angles()
            assert "Back" in updated.slot_summary() or "back" in updated.slot_summary().lower()

            # Core pack intact
            assert updated.get_slot("front")
            assert updated.get_slot("side")
            assert updated.get_slot("closeup")

            # all_stills includes Back for refs elsewhere
            stills = updated.all_stills()
            assert len(stills) == 4

            # Reload from disk
            reloaded = find_character(entry.id) or next(
                (c for c in load_characters() if c.id == entry.id), None
            )
            assert reloaded is not None
            assert reloaded.get_slot("back")
            print("OK accept Back slot + persistence + ref list")
        finally:
            delete_character(entry.id, remove_file=True, force_children_check=False)


def test_edit_form_preserves_sheet() -> None:
    """update_character with core-only identity must not wipe sheet angles."""
    from media_studio.character_store import update_character

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        front = root / "f.jpg"
        side = root / "s.jpg"
        closeup = root / "c.jpg"
        back = root / "b.jpg"
        for p, col in (
            (front, (1, 2, 3)),
            (side, (4, 5, 6)),
            (closeup, (7, 8, 9)),
            (back, (10, 11, 12)),
        ):
            _make_still(p, col)

        entry = add_character(
            name="Sheet Preserve Test",
            still_path=front,
            identity={"front": front, "side": side, "closeup": closeup},
        )
        try:
            set_character_slot(entry.id, "back", back)
            # Simulate Edit form save (core only)
            updated = update_character(
                entry.id,
                identity={
                    "front": entry.get_slot("front") or front,
                    "side": entry.get_slot("side") or side,
                    "closeup": entry.get_slot("closeup") or closeup,
                },
            )
            assert updated is not None
            assert updated.get_slot("back"), "sheet angle wiped by core-only update"
            print("OK edit-form preserve sheet angles")
        finally:
            delete_character(entry.id, remove_file=True, force_children_check=False)


def test_costume_pack_not_parent() -> None:
    """Sheet angles on a costume use costume F/S/C only; Accept stays on costume."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        # Parent base — different stills (would be wrong if leaked into costume lock)
        bf, bs, bc = root / "bf.jpg", root / "bs.jpg", root / "bc.jpg"
        # Costume outfit pack
        cf, cs, cc, cback = (
            root / "cf.jpg",
            root / "cs.jpg",
            root / "cc.jpg",
            root / "cback.jpg",
        )
        for p, col in (
            (bf, (10, 10, 10)),
            (bs, (20, 20, 20)),
            (bc, (30, 30, 30)),
            (cf, (200, 50, 50)),
            (cs, (190, 40, 40)),
            (cc, (180, 30, 30)),
            (cback, (170, 20, 20)),
        ):
            _make_still(p, col)

        base = add_character(
            name="Sheet Base Parent",
            still_path=bf,
            identity={"front": bf, "side": bs, "closeup": bc},
        )
        costume = add_character(
            name="Sheet Base Parent – Red Look",
            still_path=cf,
            identity={"front": cf, "side": cs, "closeup": cc},
            parent_id=base.id,
        )
        try:
            assert costume.is_costume_variant()
            lock = sheet_angle_identity_for_character(costume)
            assert set(lock.keys()) == {"front", "side", "closeup"}
            # Must not include parent base stills
            for p in lock.values():
                assert "bf" not in Path(p).name
                assert "bs" not in Path(p).name
                assert "bc" not in Path(p).name
            refs = sheet_angle_ref_order(lock, core_only=True)
            assert len(refs) == 3
            # Accept Back on costume only
            updated = set_character_slot(costume.id, "back", cback)
            assert updated is not None
            assert updated.id == costume.id
            assert updated.get_slot("back")
            # Parent unchanged
            parent = find_character(base.id)
            assert parent is not None
            assert parent.get_slot("back") is None
            assert "back" not in (parent.normalized_identity() or {})
            print("OK costume sheet lock + accept on costume pack only")
        finally:
            delete_character(costume.id, remove_file=True, force_children_check=False)
            delete_character(base.id, remove_file=True, delete_children=True)


def test_compose_sheet_phase2() -> None:
    """Front+Side+Close-up+Back+¾ → local compose → Accept on character."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        paths = {}
        for i, key in enumerate(
            ("front", "side", "closeup", "back", "threequarter_front")
        ):
            p = root / f"{key}.jpg"
            _make_still(p, (40 + i * 30, 50, 60))
            paths[key] = p

        entry = add_character(
            name="Sheet Compose Smoke",
            still_path=paths["front"],
            identity={k: paths[k] for k in ("front", "side", "closeup")},
        )
        try:
            set_character_slot(entry.id, "back", paths["back"])
            set_character_slot(
                entry.id, "threequarter_front", paths["threequarter_front"]
            )
            ch = find_character(entry.id)
            assert ch is not None
            assert ch.can_compose_sheet()
            assert ch.angle_count() >= 5
            assert auto_sheet_layout(5) in ("2×3", "2x3") or "2" in auto_sheet_layout(5)
            assert is_local_sheet_layout(LOCAL_SHEET_LAYOUT_MODEL)

            out = root / "sheet_out.jpg"
            angles = ch.filled_angles_ordered()
            dest = compose_character_sheet_local(
                angles, layout="auto", output_path=out
            )
            assert Path(dest).is_file()
            assert Path(dest).stat().st_size > 500

            updated = set_character_sheet(entry.id, dest)
            assert updated is not None
            assert updated.has_sheet()
            # Angle slots untouched
            assert updated.get_slot("front")
            assert updated.get_slot("back")
            assert updated.angle_count() == 5
            cite = character_sheet_citation_label(updated)
            assert cite.startswith("Character sheet:")
            assert "Sheet Compose Smoke" in cite
            print("OK Phase 2 compose + accept + citation")
        finally:
            delete_character(entry.id, remove_file=True, force_children_check=False)


def test_ai_compose_downscale_and_megapixel_msg() -> None:
    """7 large plates → AI prep longest ≤1024; megapixel errors collapse to one line."""
    from PIL import Image as PILImage

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        big_paths: list[str] = []
        for i in range(7):
            p = root / f"big_{i}.jpg"
            # 2048-class plate (would trip multi-ref megapixel budgets)
            PILImage.new("RGB", (2048, 1536), (40 + i * 20, 80, 100)).save(
                p, format="JPEG", quality=92
            )
            big_paths.append(str(p))

        prepped = prepare_sheet_ai_angle_refs(
            big_paths,
            output_dir=root / "out",
            model_choice="Image · Flux 2 Pro (edit)",
        )
        assert len(prepped) == 7
        for orig, prep in zip(big_paths, prepped):
            assert Path(prep).is_file()
            with PILImage.open(prep) as im:
                assert max(im.size) <= SHEET_AI_MAX_SIDE, im.size
            # Never upscale: small plates stay as-is
        small = root / "tiny.jpg"
        PILImage.new("RGB", (200, 300), (10, 20, 30)).save(small, format="JPEG")
        tiny_out = prepare_sheet_ai_angle_refs(
            [str(small)],
            output_dir=root / "out",
            model_choice="flux 2 pro",
        )
        assert len(tiny_out) == 1
        with PILImage.open(tiny_out[0]) as im:
            # prepare may re-encode if bytes large; dims must not grow
            assert max(im.size) <= 300

        # Local compose still works with 7 angles (no AI prep path)
        angles = [(f"a{i}", p) for i, p in enumerate(big_paths)]
        # Map to real slot keys for labels
        keys = list(ALL_IDENTITY_SLOTS)[:7]
        angles = list(zip(keys, big_paths))
        dest = compose_character_sheet_local(
            angles, layout="auto", output_path=root / "local7.jpg"
        )
        assert Path(dest).is_file()

        dump = "\n".join(
            ["Requested area too large for the model"] * 8
        )
        assert is_sheet_area_too_large_error(dump)
        msg = friendly_sheet_compose_error(dump)
        assert msg == SHEET_AI_AREA_TOO_LARGE_MSG
        assert msg.count("Too many") == 1
        # friendly_error path also maps megapixel
        from media_studio.errors import friendly_error

        fe = friendly_error(
            "fal: Requested area too large / megapixel limit",
            context="Sheet compose",
            media_kind="image",
        )
        assert "Local layout" in fe or "fewer angles" in fe
        print("OK AI downscale + megapixel one-liner + local 7-up")


if __name__ == "__main__":
    test_sheet_slots_and_prompts()
    test_accept_back_slot()
    test_edit_form_preserves_sheet()
    test_costume_pack_not_parent()
    test_compose_sheet_phase2()
    test_ai_compose_downscale_and_megapixel_msg()
    print("all smoke_sheet_angles passed")
