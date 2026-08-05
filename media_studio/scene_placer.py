"""
Scene Placer — composite a Character into a Scene still with pose control.

Multi-ref I2I:
  · Primary plate = Scene still (architecture / lighting lock)
  · Character ref(s) = Front/hero first, optional extra identity angles
  · Prompt = insert character + pose/body language only; do not redesign scene

Default model: Flux 2 Pro / Max edit (same multi-ref ladder as Costume swap).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from media_studio.character_store import (
    SavedCharacter,
    estimate_costume_swap_cost,
    preferred_costume_model,
)

# Scenario key for job receipts / Library history rows
SCENARIO_KEY = "scene-placer"

# Prompt contract — identity + scene locks; only character insert + pose changes
_PROMPT_CORE = (
    "You are compositing a person into an existing scene still. "
    "IMAGE ORDER: (1) first image is the SCENE plate — keep its architecture, "
    "layout, furniture/city geometry, camera angle, perspective, and lighting "
    "exactly. Do not redesign, restyle, repaint, or invent a different room or "
    "city. (2) following image(s) are the CHARACTER identity reference(s) — "
    "match face, hair, body proportions, skin tone, age, and wardrobe from "
    "those refs as closely as possible (identity lock). "
    "ONLY CHANGE: insert that character into the scene with the requested "
    "pose / body language, action (what is happening), and placement. "
    "Match ground contact, scale, and cast lighting so the person belongs "
    "in the plate. Photoreal, no text, no watermark, no logo."
)


def preferred_scene_placer_model() -> str:
    """Prefer multi-ref Flux-family edit models (Flux 2 Pro / Max)."""
    return preferred_costume_model()


def estimate_scene_placer_cost(
    *,
    model_key: str | None = None,
    resolution: str | None = None,
) -> str:
    """Cost for one Scene Placer still (single I2I call)."""
    return estimate_costume_swap_cost(
        1,
        model_key=model_key or preferred_scene_placer_model(),
        resolution=resolution,
    )


def build_scene_placer_prompt(
    *,
    pose: str,
    placement: str = "",
    happening: str = "",
) -> str:
    """
    Auto prompt contract for multi-ref edit.

    pose: free-text body language (required content).
    happening: optional action / moment (mid-fight block, landing after flight).
    placement: optional framing/location hint (midground left, upper sky, …).
    """
    pose_txt = (pose or "").strip()
    place_txt = (placement or "").strip()
    happen_txt = (happening or "").strip()
    if not pose_txt:
        pose_txt = "natural standing pose, relaxed stance"

    parts = [
        _PROMPT_CORE,
        f"Pose / body language: {pose_txt}.",
    ]
    if happen_txt:
        parts.append(
            f"What is happening (action / moment): {happen_txt}. "
            "Show that action clearly in the character's body, hands, "
            "expression, and any implied contact or motion — still one "
            "frozen still, not a new scene."
        )
    if place_txt:
        parts.append(
            f"Placement in frame: {place_txt}. "
            "Respect that location within the existing scene geometry."
        )
    else:
        parts.append(
            "Placement: compose the character naturally in the scene "
            "(midground unless pose implies otherwise — e.g. flying → sky)."
        )
    parts.append(
        "Do not change the background environment beyond what is required "
        "to integrate the character (soft contact shadows, local occlusion)."
    )
    return " ".join(parts)


def character_ref_paths(character: SavedCharacter | None) -> list[str]:
    """
    Character refs for multi-ref I2I: Front/hero first, then other filled slots.
    """
    if character is None:
        return []
    out: list[str] = []
    primary = character.primary_still()
    if primary and Path(primary).is_file():
        out.append(str(Path(primary).resolve()))
    for p in character.all_stills():
        if not p or not Path(p).is_file():
            continue
        try:
            rp = str(Path(p).resolve())
        except OSError:
            continue
        if rp not in out:
            out.append(rp)
    return out


def resolve_scene_path(path: str | None) -> str | None:
    if not path:
        return None
    try:
        p = Path(path).expanduser().resolve()
        if p.is_file() and p.stat().st_size > 0:
            return str(p)
    except OSError:
        return None
    return None


def enhance_context(
    *,
    character_name: str = "",
    scene_label: str = "",
    pose: str = "",
    placement: str = "",
    happening: str = "",
) -> dict[str, Any]:
    """Extra context for Grok Enhance — identity lock + pose/action rewrite."""
    return {
        "workspace": "characters",
        "mode": "scene_placer",
        "character": character_name or "",
        "scene": scene_label or "",
        "pose": (pose or "").strip(),
        "happening": (happening or "").strip(),
        "placement": (placement or "").strip(),
        "guidance": (
            "Rewrite pose / body language for a multi-ref image-edit model that "
            "composites a character into a scene plate. If What's happening "
            "(action/moment) is provided, weave that action clearly into the "
            "rewritten pose (blocking, stumbling, interviewing, landing, etc.) "
            "so both stance and action read in one still. Keep identity lock on "
            "the character (same person/outfit from refs). Keep scene "
            "architecture and lighting locked — do not invent a new location. "
            "Optional placement stays separate (midground left, upper sky). "
            "Concrete and concise. No wardrobe redesign unless the action "
            "implies it."
        ),
    }
