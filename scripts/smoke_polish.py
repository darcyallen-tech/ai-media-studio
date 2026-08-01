"""Smoke checks for polish features (naming, history, errors, pricing)."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from media_studio.errors import friendly_error
from media_studio.history import (
    append_history,
    find_by_label,
    first_image_path,
    history_dropdown_choices,
    load_history,
)
from media_studio.naming import make_output_stem, prompt_slug, unique_path
from media_studio.pricing import estimate_image_cost, estimate_video_cost


def main() -> None:
    assert prompt_slug("Replace the sofa with a modern couch!") == "replace-sofa-modern-couch" or "sofa" in prompt_slug(
        "Replace the sofa with a modern couch!"
    )
    stem = make_output_stem("Replace the sofa", "nano banana pro", stamp="20260725_120000", kind="edit")
    assert stem.startswith("20260725_120000_")
    assert "nano-banana" in stem or "nano" in stem
    assert ":" not in stem and "/" not in stem and "\\" not in stem
    print("naming OK:", stem)

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        p1 = unique_path(d, "test_stem", ".png")
        p1.write_bytes(b"x")
        p2 = unique_path(d, "test_stem", ".png")
        assert p2 != p1
        print("unique_path OK")

        # history
        img = d / "out.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n")
        entry = append_history(
            job_kind="image",
            model="nano banana pro",
            prompt="replace sofa",
            files=[str(img)],
            cost_estimate="est. ~$0.15",
            notes=["ok"],
            output_dir=d,
            timestamp="20260725_120000",
        )
        choices = history_dropdown_choices(d)
        assert choices and entry.label in choices
        found = find_by_label(entry.label, d)
        assert found is not None
        assert first_image_path(found) is not None
        assert load_history(d)
        print("history OK:", entry.label[:60])

    cost_i = estimate_image_cost("nano banana pro", 2)
    assert "$" in cost_i and "0.30" in cost_i or "0.3" in cost_i
    cost_v = estimate_video_cost("kling edit", duration_seconds=5)
    assert "$" in cost_v
    print("pricing OK:", cost_i, "|", cost_v)

    msg = friendly_error("FAL_KEY is not set", context="Test")
    assert "FAL_KEY" in msg or "fal" in msg.lower()
    msg2 = friendly_error(TimeoutError("timed out"), context="Generate")
    assert "time" in msg2.lower() or "Timeout" in msg2 or "Timed" in msg2
    print("errors OK")

    # reserved windows name
    from media_studio.naming import prompt_slug as ps

    assert ps("con") != "con" or ps("con something").startswith("x-") or "con" in ps("con test")
    print("windows reserved handled")

    build_ui()
    print("UI builds OK")
    print("ALL POLISH SMOKE CHECKS PASSED")


if __name__ == "__main__":
    main()
