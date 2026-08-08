"""Smoke: Seedance likeness banner + content-policy popup detection."""

from __future__ import annotations

from media_studio.errors import detect_content_policy_violation, friendly_error
from media_studio.flet_dialogs import (
    make_seedance_likeness_banner,
    set_seedance_likeness_banner_visible,
)


def test_policy_likeness() -> None:
    cases = [
        "partner_validation_failed: The input images may contain likeness of real people.",
        '{"type":"content_policy_violation","message":"Sensitive content detected"}',
        "content_policy_violation: private information",
        "FalClientError: request failed with partner_validation_failed",
        "Generate: Seedance rejected — likeness / real people filter",
    ]
    for c in cases:
        p = detect_content_policy_violation(c, context="Generate")
        assert p is not None, f"expected policy for: {c[:60]}"
        assert p.short_reason
        assert p.body.startswith("Your generation was stopped because:")
        print("OK policy:", p.kind, p.short_reason[:72] + "…")


def test_policy_not_matched() -> None:
    for c in (
        "Network timeout talking to API",
        "insufficient credits — top up",
        "422 Unprocessable: invalid duration",
    ):
        p = detect_content_policy_violation(c, context="Generate")
        assert p is None, f"unexpected policy for: {c}"
        print("OK no policy:", c[:40])


def test_likeness_reason_maps() -> None:
    p = detect_content_policy_violation(
        "partner_validation_failed: likeness of real people",
        context="Generate",
        model_hint="Seedance 2.5 · Reference-to-Video",
    )
    assert p is not None
    assert p.kind == "likeness"
    assert "stylized" in p.short_reason.lower() or "character-sheet" in p.short_reason.lower()
    assert "seedance" in p.short_reason.lower()
    p_n = detect_content_policy_violation(
        "partner_validation_failed: likeness of real people",
        context="Generate",
        model_hint="FLUX 3 · Identity ref (R2V)",
    )
    assert p_n is not None
    assert "seedance" not in p_n.short_reason.lower()
    fe = friendly_error(
        "partner_validation_failed: likeness of real people",
        context="Generate",
    )
    assert "real people" in fe.lower() or "stylized" in fe.lower()
    print("OK likeness map + friendly_error (Seedance vs neutral)")


def test_banner_toggle() -> None:
    class Fake:
        def __init__(self) -> None:
            self.visible = False

    b = Fake()
    assert set_seedance_likeness_banner_visible(
        b, endpoint="bytedance/seedance-2.0/reference-to-video"
    )
    assert b.visible is True
    assert set_seedance_likeness_banner_visible(
        b, endpoint="bytedance/seedance-2.5/reference-to-video"
    )
    assert b.visible is True
    assert not set_seedance_likeness_banner_visible(b, endpoint="fal-ai/flux-pro")
    assert b.visible is False
    assert set_seedance_likeness_banner_visible(
        b, model_choice="Video · Seedance 2.0 – Reference-to-Video"
    )
    assert b.visible is True
    assert set_seedance_likeness_banner_visible(
        b, model_choice="Seedance 2.5 · Reference-to-Video"
    )
    assert b.visible is True
    assert not set_seedance_likeness_banner_visible(
        b, model_choice="Video · Kling 2.1"
    )
    assert b.visible is False
    # I2V Seedance (not R2V) — no banner
    assert not set_seedance_likeness_banner_visible(
        b, endpoint="bytedance/seedance-2.0/image-to-video"
    )
    assert b.visible is False
    # FLUX 3 / non-seedance labels
    assert not set_seedance_likeness_banner_visible(
        b, model_choice="Video · FLUX 3 – Image-to-Video"
    )
    banner = make_seedance_likeness_banner()
    assert banner.visible is False
    print("OK banner toggle")


if __name__ == "__main__":
    test_policy_likeness()
    test_policy_not_matched()
    test_likeness_reason_maps()
    test_banner_toggle()
    print("all smoke_content_policy_ui passed")
