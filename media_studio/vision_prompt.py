"""
Creative Vision prompt helpers — still photography + cinematic video language.

T2I uses still-only helpers (no push-in / pan / motion).
T2V / I2V / Bridge keep camera-motion language.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Video helpers (T2V / I2V / Bridge)
# ---------------------------------------------------------------------------

SHOT_TYPES: list[str] = [
    "Wide establishing",
    "Slow push-in",
    "Orbit around subject",
    "Drone rise / reveal",
    "Handheld walk-through",
    "Static locked-off",
    "Tracking lateral",
    "Crash zoom (subtle)",
]

LENS_FEELS: list[str] = [
    "24mm wide",
    "35mm natural",
    "50mm intimate",
    "85mm compressed",
]

MOTIONS: list[str] = [
    "Static",
    "Slow pan left",
    "Slow pan right",
    "Push in",
    "Pull out",
    "Crane up",
    "Crane down",
    "Gentle orbit",
]

# Video style presets (may imply motion / B-roll energy)
STYLE_PRESETS: dict[str, str] = {
    "Twilight lifestyle": (
        "Twilight exterior lifestyle, warm practicals glowing, deep blue hour sky, "
        "cinematic real-estate grade, subtle lens bloom, no text overlays"
    ),
    "Clean modern day": (
        "Bright clean modern daylight, soft window light, neutral white balance, "
        "architectural photography look, crisp edges, no people unless specified"
    ),
    "Moody sold story": (
        "Moody sold-story cinematic grade, richer contrast, gentle shadows, "
        "emotional still-motion, filmic color, premium listing B-roll"
    ),
    "Aerial luxury": (
        "Aerial luxury property reveal, smooth drone altitude, golden highlights on roof, "
        "sweeping estate context, high-end travel commercial energy"
    ),
}

# ---------------------------------------------------------------------------
# Still-only helpers (Text → Image)
# ---------------------------------------------------------------------------

STILL_FRAMINGS: list[str] = [
    "Wide establishing",
    "Medium full view",
    "Detail close-up",
    "Low angle",
    "High angle",
    "Eye-level documentary",
]

# Photographic FOV only — no motion language
STILL_LENS_LOOKS: list[str] = [
    "24mm wide",
    "35mm natural",
    "50mm intimate",
    "85mm compressed",
]

STILL_LIGHTING: list[str] = [
    "Natural soft daylight",
    "Golden hour warmth",
    "Blue hour cool practicals",
    "Overcast even",
    "Dramatic directional",
    "Interior window light",
]

# Still photography styles — no camera move language
STILL_STYLE_PRESETS: dict[str, str] = {
    "Clean modern day": (
        "Bright clean modern daylight, soft window light, neutral white balance, "
        "architectural photography look, crisp edges, no people unless specified"
    ),
    "Golden hour": (
        "Golden hour exterior still, warm low sun, long soft shadows, "
        "honey rim light, photoreal real-estate grade, no text overlays"
    ),
    "Dramatic dusk": (
        "Dramatic dusk still, deep blue hour sky, warm practicals glowing, "
        "rich contrast, cinematic still photography, no motion blur"
    ),
    "Documentary": (
        "Documentary still photography, naturalistic color, honest exposure, "
        "observational framing, subtle grain optional, no stylized grade"
    ),
    "Cinematic still": (
        "Cinematic still frame, filmic contrast and color, shallow depth of field "
        "where appropriate, anamorphic feel optional, locked single frame — not a video move"
    ),
    "Twilight lifestyle": (
        "Twilight exterior lifestyle still, warm practicals glowing, deep blue hour sky, "
        "cinematic real-estate grade, subtle lens bloom, no text overlays"
    ),
}


def compile_vision_prompt(
    *,
    base_prompt: str | None = None,
    shot_type: str | None = None,
    lens: str | None = None,
    motion: str | None = None,
    style_preset: str | None = None,
    style_text: str | None = None,
    bridge: bool = False,
    subject_notes: str | None = None,
) -> str:
    """
    Compose a video-oriented generation prompt from helpers + free text.

    May include camera motion language. Do **not** use for Text→Image —
    use ``compile_still_prompt`` instead.
    """
    parts: list[str] = []

    style = (style_text or "").strip()
    if not style and style_preset and style_preset in STYLE_PRESETS:
        style = STYLE_PRESETS[style_preset]
    if style:
        parts.append(style.rstrip(".,; ") + ".")

    cam: list[str] = []
    if shot_type:
        cam.append(f"shot: {shot_type}")
    if lens:
        cam.append(f"lens feel: {lens}")
    if motion and motion.lower() != "static":
        cam.append(f"camera motion: {motion}")
    elif motion:
        cam.append("camera locked / static")
    if cam:
        parts.append("Camera — " + "; ".join(cam) + ".")

    if bridge:
        parts.append(
            "Bridge the start frame to the end frame as one continuous move. "
            "Keep architecture, materials, and layout consistent; only camera path "
            "and natural motion change. No morphing walls, no teleport cuts."
        )

    sub = (subject_notes or "").strip()
    if sub:
        parts.append(
            f"Subject consistency help (not a perfect lock): {sub}."
        )

    body = (base_prompt or "").strip()
    if body:
        parts.append(body)

    if not parts:
        return (
            "Cinematic real-estate B-roll, smooth camera, keep architecture consistent, "
            "no text, no watermark."
        )
    return " ".join(parts)


def compile_still_prompt(
    *,
    base_prompt: str | None = None,
    framing: str | None = None,
    lens_look: str | None = None,
    lighting: str | None = None,
    style_preset: str | None = None,
    style_text: str | None = None,
    subject_notes: str | None = None,
) -> str:
    """
    Compose a **still photography** prompt — never injects camera motion.

    No push-in, pan, orbit, tracking, whip, or motion verbs from helpers.
    User free-text is appended as-is (if they type motion, that is intentional).
    """
    parts: list[str] = []

    style = (style_text or "").strip()
    if not style and style_preset and style_preset in STILL_STYLE_PRESETS:
        style = STILL_STYLE_PRESETS[style_preset]
    # Fall back to video style table if a shared name is selected
    if not style and style_preset and style_preset in STYLE_PRESETS:
        style = STYLE_PRESETS[style_preset]
    if style:
        parts.append(style.rstrip(".,; ") + ".")

    still: list[str] = []
    if framing:
        still.append(f"framing: {framing}")
    if lens_look:
        still.append(f"lens look: {lens_look}")
    if lighting:
        still.append(f"lighting: {lighting}")
    if still:
        parts.append("Still photography — " + "; ".join(still) + ".")

    parts.append(
        "Single still image, locked frame, no camera move, no pan, no push-in, "
        "no motion blur from camera movement."
    )

    sub = (subject_notes or "").strip()
    if sub:
        parts.append(
            f"Subject consistency help (not a perfect lock): {sub}."
        )

    body = (base_prompt or "").strip()
    if body:
        parts.append(body)

    if not parts:
        return (
            "Photoreal real-estate still photograph, natural light, "
            "sharp locked frame, no text, no watermark."
        )
    return " ".join(parts)


def default_bridge_prompt() -> str:
    return compile_vision_prompt(
        base_prompt=(
            "Smooth connect from the first room to the second — "
            "path along the natural doorway/hallway, measured pace."
        ),
        shot_type="Slow push-in",
        lens="35mm natural",
        motion="Push in",
        bridge=True,
    )


def default_still_prompt() -> str:
    return compile_still_prompt(
        framing=STILL_FRAMINGS[0],
        lens_look=STILL_LENS_LOOKS[1],
        lighting=STILL_LIGHTING[0],
        style_preset="Clean modern day",
    )


def clear_vision_helper_values() -> dict[str, Any]:
    return {
        "shot_type": SHOT_TYPES[1],  # Slow push-in (video)
        "lens": LENS_FEELS[1],
        "motion": MOTIONS[3],  # Push in (video)
        "style_preset": "Clean modern day",
        "style_text": STYLE_PRESETS["Clean modern day"],
        "base_prompt": "",
        # Still defaults
        "framing": STILL_FRAMINGS[0],
        "lens_look": STILL_LENS_LOOKS[1],
        "lighting": STILL_LIGHTING[0],
        "still_style_preset": "Clean modern day",
    }
