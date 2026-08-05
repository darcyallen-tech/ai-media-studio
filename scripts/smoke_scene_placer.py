"""
Smoke helpers for Scene Placer (no fal call).

Checks prompt contract, cost label, and that Camera Man + a city scene
are available for the manual UI smoke:

  Camera Man + city overlook/sidewalk + "flying toward camera, cape billowing"
  → Place in scene → Expand → Send to Director · Keyframe Take as pin
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    from media_studio.character_store import load_characters
    from media_studio.scene_placer import (
        build_scene_placer_prompt,
        character_ref_paths,
        estimate_scene_placer_cost,
        preferred_scene_placer_model,
        resolve_scene_path,
    )
    from media_studio.scene_store import load_scenes

    pose = "fighting stance"
    happening = "blocking an incoming punch"
    placement = "midground center"
    prompt = build_scene_placer_prompt(
        pose=pose, placement=placement, happening=happening
    )
    assert "SCENE plate" in prompt or "scene" in prompt.lower()
    assert "identity" in prompt.lower() or "CHARACTER" in prompt
    assert pose in prompt
    assert happening in prompt
    assert "What is happening" in prompt or "action" in prompt.lower()
    assert "midground" in prompt
    print("prompt ok ·", len(prompt), "chars")
    print("  pose + happening folded:", pose, "+", happening)

    # Flight smoke path still valid
    fly = build_scene_placer_prompt(
        pose="flying toward camera, cape billowing",
        placement="upper sky small in frame",
    )
    assert "flying toward camera" in fly
    assert "upper sky" in fly

    model = preferred_scene_placer_model()
    cost = estimate_scene_placer_cost(model_key=model)
    print("model:", model)
    print("cost:", cost)
    assert "flux" in model.lower() or "Est" in cost

    cams = [c for c in load_characters() if "camera" in c.name.lower()]
    if not cams:
        print("WARN: no Camera Man character in local store (UI smoke needs one)")
    else:
        cam = cams[0]
        refs = character_ref_paths(cam)
        print(f"character: {cam.name} · refs={len(refs)}")
        assert refs, "Camera Man has no stills"

    scenes = load_scenes()
    cityish = [
        s
        for s in scenes
        if any(
            k in (s.name or "").lower()
            for k in ("city", "sidewalk", "park", "street", "overlook", "sky")
        )
    ]
    if not cityish:
        print("WARN: no city-like scene in local store")
    else:
        sc = cityish[0]
        path = resolve_scene_path(sc.resolved_still_path())
        print(f"scene: {sc.name} · still={bool(path)}")
        assert path, f"Scene still missing: {sc.name}"

    print("smoke_scene_placer: OK (dry)")
    print(
        "Manual: Characters → Place in scene → pose \"fighting stance\" + "
        "What's happening \"blocking an incoming punch\" → still reflects both; "
        "or flying + cape → Expand → Send to Director Keyframe Take"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
