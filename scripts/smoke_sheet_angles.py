"""Smoke: Character sheet angles Phase 1 (store + prompts + accept path)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from PIL import Image

from media_studio.character_store import (
    ALL_IDENTITY_SLOTS,
    SHEET_ANGLE_SLOTS,
    SLOT_SHORT,
    add_character,
    delete_character,
    find_character,
    is_sheet_angle_slot,
    load_characters,
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


if __name__ == "__main__":
    test_sheet_slots_and_prompts()
    test_accept_back_slot()
    test_edit_form_preserves_sheet()
    test_costume_pack_not_parent()
    print("all smoke_sheet_angles passed")
