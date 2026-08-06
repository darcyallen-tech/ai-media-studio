"""
Unit tests: unified aspect_ratio policy (no network).

Run: python scripts/test_aspect_policy.py
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from media_studio import aspect_omit as ao  # noqa: E402
from media_studio import flux3_draft as f3  # noqa: E402
from media_studio.aspect_omit import (  # noqa: E402
    apply_aspect_policy,
    endpoint_omits_aspect_ratio,
    strip_omitted_aspect,
)
from media_studio.fal.models import (  # noqa: E402
    build_i2v_arguments,
    resolve_video_model,
)
from media_studio.vision_registry import (  # noqa: E402
    I2V_MODELS,
    build_vision_arguments,
    find_vision_model,
)


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def test_seedance_r2v_keeps_16_9() -> None:
    ep = "bytedance/seedance-2.0/reference-to-video"
    _assert(not endpoint_omits_aspect_ratio(ep), "Seedance R2V must NOT be on omit list")
    out = apply_aspect_policy(
        {"aspect_ratio": "16:9", "prompt": "x"},
        endpoint=ep,
        requested="16:9",
    )
    _assert(out.get("aspect_ratio") == "16:9", f"Seedance R2V must KEEP 16:9, got {out}")


def test_seedance_r2v_keeps_auto() -> None:
    ep = "bytedance/seedance-2.0/reference-to-video"
    out = apply_aspect_policy(
        {"aspect_ratio": "auto"}, endpoint=ep, requested="auto"
    )
    _assert(out.get("aspect_ratio") == "auto", f"Seedance R2V must KEEP auto, got {out}")
    # Follows-refs sentinel → default auto
    out2 = apply_aspect_policy(
        {}, endpoint=ep, requested="Follows refs / adaptive"
    )
    _assert(
        out2.get("aspect_ratio") == "auto",
        f"Follows refs → auto expected, got {out2}",
    )


def test_seedance_r2v_vision_builder() -> None:
    vs = find_vision_model("seedance 2.0 reference", "reference_to_video")
    _assert(vs is not None, "vision seedance r2v missing")
    _assert(not getattr(vs, "omit_aspect_ratio", False), "vision flag must not omit")
    args = build_vision_arguments(
        vs,
        prompt="two people in a tavern",
        image_url="https://e.com/a.jpg",
        ref_urls=["https://e.com/a.jpg", "https://e.com/b.jpg"],
        aspect_ratio="16:9",
        duration="5",
        resolution="720p",
    )
    _assert(args.get("aspect_ratio") == "16:9", f"vision build must keep aspect: {args}")
    # duration string not int
    _assert(
        args.get("duration") == "5" or args.get("duration") == 5,
        f"duration present: {args.get('duration')!r}",
    )
    if "seedance" in (vs.endpoint or ""):
        _assert(
            isinstance(args.get("duration"), str),
            f"Seedance duration must be str, got {type(args.get('duration'))}",
        )


def test_flux3_i2v_full_and_draft() -> None:
    for ep in (
        "blackforestlabs/flux-3/image-to-video",
        "blackforestlabs/flux-3/image-to-video/draft",
    ):
        out = apply_aspect_policy(
            {"aspect_ratio": "16:9"}, endpoint=ep, requested="16:9"
        )
        _assert("aspect_ratio" not in out, f"FLUX 3 I2V {ep} must omit")
    vs = I2V_MODELS.get("flux 3 i2v")
    _assert(vs is not None, "flux 3 i2v missing")
    args = build_vision_arguments(
        vs,
        prompt="walk",
        image_url="https://e.com/a.jpg",
        aspect_ratio="auto",
        duration="8",
        resolution="720p",
    )
    _assert("aspect_ratio" not in args, f"flux3 i2v vision build: {args}")


def test_flux3_first_last_may_have_key() -> None:
    ep = "blackforestlabs/flux-3/first-last-frame-to-video"
    out = apply_aspect_policy({}, endpoint=ep, requested="16:9")
    _assert(
        out.get("aspect_ratio") == "16:9",
        f"first-last should send 16:9, got {out}",
    )
    _assert(
        not endpoint_omits_aspect_ratio(ep),
        "first-last must not be on omit list",
    )


def test_kling_vision_i2v_no_key() -> None:
    ep = "fal-ai/kling-video/o3/pro/image-to-video"
    _assert(endpoint_omits_aspect_ratio(ep), "Kling I2V must omit")
    out = apply_aspect_policy(
        {"aspect_ratio": "16:9"}, endpoint=ep, requested="16:9"
    )
    _assert("aspect_ratio" not in out, f"Kling I2V leaked: {out}")
    vs = I2V_MODELS.get("kling o3 pro i2v")
    if vs is None:
        for k, s in I2V_MODELS.items():
            if "kling" in k and "o3" in k:
                vs = s
                break
    _assert(vs is not None, "kling o3 i2v vision model missing")
    args = build_vision_arguments(
        vs,
        prompt="pan",
        image_url="https://e.com/a.jpg",
        aspect_ratio="16:9",
        duration="5",
    )
    _assert("aspect_ratio" not in args, f"Kling vision build leaked: {args}")


def test_h3_omni_adaptive() -> None:
    ep = "minimax/h3/reference-to-video"
    out = apply_aspect_policy({}, endpoint=ep, requested="adaptive")
    _assert(out.get("aspect_ratio") == "adaptive", f"H3 adaptive: {out}")
    out2 = apply_aspect_policy({}, endpoint=ep, requested="auto")
    _assert(
        out2.get("aspect_ratio") == "adaptive",
        f"H3 auto→adaptive expected, got {out2}",
    )


def test_seedance_i2v_sends_16_9() -> None:
    ep = "bytedance/seedance-2.0/image-to-video"
    out = apply_aspect_policy({}, endpoint=ep, requested="16:9")
    _assert(out.get("aspect_ratio") == "16:9", f"Seedance I2V send: {out}")
    spec = resolve_video_model("seedance 2.0 i2v")
    _assert(spec is not None, "studio seedance i2v missing")
    args, _notes = build_i2v_arguments(
        spec,
        prompt="x",
        image_url="https://e.com/a.jpg",
        parameters={"aspect_ratio": "16:9", "duration": "5"},
    )
    _assert(args.get("aspect_ratio") == "16:9", f"build_i2v: {args}")


def test_last_mile_seedance_keeps_key() -> None:
    ep = "bytedance/seedance-2.0/reference-to-video"
    kept = strip_omitted_aspect(
        {"aspect_ratio": "16:9", "prompt": "x"}, endpoint=ep
    )
    _assert(kept.get("aspect_ratio") == "16:9", f"last-mile must KEEP: {kept}")
    kept2 = f3.strip_omitted_aspect({"aspect_ratio": "auto"}, endpoint=ep)
    _assert(kept2.get("aspect_ratio") == "auto", f"flux3 strip must KEEP: {kept2}")


def test_no_second_omit_definition() -> None:
    """flux3_draft re-exports; Seedance R2V omit is False on both."""
    ep = "bytedance/seedance-2.0/reference-to-video"
    _assert(
        ao.endpoint_omits_aspect_ratio(ep) is False,
        "aspect_omit must False for Seedance R2V",
    )
    _assert(
        f3.endpoint_omits_aspect_ratio(ep) is False,
        "flux3_draft must False for Seedance R2V",
    )
    _assert(
        ao.endpoint_omits_aspect_ratio is f3.endpoint_omits_aspect_ratio
        or (
            ao.endpoint_omits_aspect_ratio(ep)
            == f3.endpoint_omits_aspect_ratio(ep)
        ),
        "twin omit functions disagree",
    )
    src = (ROOT / "media_studio" / "flux3_draft.py").read_text(encoding="utf-8")
    _assert(
        "from media_studio.aspect_omit import" in src
        and "endpoint_omits_aspect_ratio" in src,
        "flux3_draft must import endpoint_omits from aspect_omit",
    )
    tree = ast.parse(src)
    local_defs = [
        n.name
        for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name == "endpoint_omits_aspect_ratio"
    ]
    _assert(
        not local_defs,
        f"flux3_draft must not define local endpoint_omits_aspect_ratio: {local_defs}",
    )


def test_studio_seedance_r2v_keeps_aspect() -> None:
    spec = resolve_video_model("seedance 2.0 reference")
    _assert(spec is not None, "studio seedance reference missing")
    _assert(spec.aspect_ratio_param == "aspect_ratio", "param restored")
    args, _notes = build_i2v_arguments(
        spec,
        prompt="x",
        image_url="https://e.com/a.jpg",
        parameters={
            "aspect_ratio": "16:9",
            "duration": "5",
            "image_urls": ["https://e.com/b.jpg"],
        },
    )
    _assert(args.get("aspect_ratio") == "16:9", f"studio R2V must keep: {args}")
    _assert(isinstance(args.get("duration"), str), f"duration str: {args.get('duration')!r}")


def test_seedance_r2v_allowlist_sanitizer() -> None:
    from media_studio.aspect_omit import sanitize_seedance_r2v_arguments

    ep = "bytedance/seedance-2.0/reference-to-video"
    dirty = {
        "prompt": "x",
        "image_urls": ["a", "b"],
        "negative_prompt": "blur",
        "duration": 10,
        "resolution": "1080p",
        "aspect_ratio": "16:9",
        "generate_audio": True,
        "safety_tolerance": 2,
    }
    clean = sanitize_seedance_r2v_arguments(dirty, endpoint=ep)
    _assert("negative_prompt" not in clean, f"neg leaked: {clean}")
    _assert(clean.get("duration") == "10", f"duration: {clean}")
    _assert(isinstance(clean.get("duration"), str), "duration must be str")
    _assert(clean.get("resolution") == "720p", f"res: {clean}")
    _assert(clean.get("aspect_ratio") == "16:9", f"ar: {clean}")


def test_omit_only_flux3_and_kling() -> None:
    _assert(
        endpoint_omits_aspect_ratio("blackforestlabs/flux-3/image-to-video"),
        "flux3 i2v omit",
    )
    _assert(
        endpoint_omits_aspect_ratio("fal-ai/kling-video/o3/pro/image-to-video"),
        "kling omit",
    )
    _assert(
        not endpoint_omits_aspect_ratio("bytedance/seedance-2.0/reference-to-video"),
        "seedance r2v not omit",
    )
    _assert(
        not endpoint_omits_aspect_ratio("minimax/h3/image-to-video"),
        "h3 i2v not on strict omit-only list (user request)",
    )


def main() -> int:
    tests = [
        test_seedance_r2v_keeps_16_9,
        test_seedance_r2v_keeps_auto,
        test_seedance_r2v_vision_builder,
        test_flux3_i2v_full_and_draft,
        test_flux3_first_last_may_have_key,
        test_kling_vision_i2v_no_key,
        test_h3_omni_adaptive,
        test_seedance_i2v_sends_16_9,
        test_last_mile_seedance_keeps_key,
        test_no_second_omit_definition,
        test_studio_seedance_r2v_keeps_aspect,
        test_seedance_r2v_allowlist_sanitizer,
        test_omit_only_flux3_and_kling,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"OK  {t.__name__}")
        except Exception as e:
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
    print()
    if failed:
        print(f"{failed}/{len(tests)} FAILED")
        return 1
    print(f"ALL {len(tests)} PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
