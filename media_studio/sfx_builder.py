"""
SFX Prompt Builder — structured controls → clean sound-effect prompts.

Same pattern as Music Builder: dropdowns auto-fill a free-editable prompt.
"""

from __future__ import annotations

from typing import Any

from media_studio.helper_none import active_helper, is_helper_none, with_none

# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------

CATEGORIES: list[str] = with_none(
    [
        "Whoosh / Swoosh",
        "Riser",
        "Impact / Hit",
        "Transition",
        "Ambience / Room Tone",
        "Footsteps",
        "Door / Object Interaction",
        "Nature",
        "UI / Digital",
        "Custom / Other",
    ]
)

INTENSITIES: list[str] = with_none(
    [
        "Soft",
        "Medium",
        "Hard / Aggressive",
    ]
)

LENGTHS: list[str] = with_none(
    [
        "Very short (0.5–1s)",
        "Short (1–2s)",
        "Medium (2–4s)",
        "Long / Sustained",
    ]
)

# Suggested API duration (seconds) per length preset
LENGTH_DURATION_S: dict[str, float] = {
    "Very short (0.5–1s)": 0.8,
    "Short (1–2s)": 1.5,
    "Medium (2–4s)": 3.0,
    "Long / Sustained": 6.0,
}

TEXTURES: list[str] = with_none(
    [
        "Clean",
        "Gritty",
        "Airy",
        "Metallic",
        "Organic",
        "Sci-fi / Designed",
    ]
)

DEFAULTS: dict[str, Any] = {
    "category": "Whoosh / Swoosh",
    "intensity": "Medium",
    "length": "Short (1–2s)",
    "texture": "Clean",
    "detail": "",
}


def _category_core(category: str) -> str:
    """Natural-language core description for the SFX type."""
    mapping = {
        "Whoosh / Swoosh": (
            "a fast whoosh / swoosh pass-by — airy motion, clear stereo movement, "
            "smooth attack and decay"
        ),
        "Riser": (
            "a tension riser that builds energy — ascending layers, increasing density, "
            "ready to peak into a hit or cut"
        ),
        "Impact / Hit": (
            "a solid impact / hit — defined transient, weighty body, short controlled tail"
        ),
        "Transition": (
            "a short transition sting for scene changes — wipe-like motion between beats, "
            "clean start and end"
        ),
        "Ambience / Room Tone": (
            "subtle ambience / room tone — steady background presence, no melody, "
            "loop-friendly and non-distracting"
        ),
        "Footsteps": (
            "footsteps on a surface — natural cadence, clear contact, realistic foley detail"
        ),
        "Door / Object Interaction": (
            "a door or object interaction — hinge, latch, or handle contact with believable "
            "material response"
        ),
        "Nature": (
            "a natural environmental sound — outdoor or organic texture, realistic and "
            "spatially open"
        ),
        "UI / Digital": (
            "a short UI / digital interface click or blip — crisp, modern, interface-ready"
        ),
        "Custom / Other": (
            "a designed sound effect with a clear beginning, middle, and end"
        ),
    }
    return mapping.get(category, "a clear, usable sound effect")


def _intensity_phrase(intensity: str) -> str:
    mapping = {
        "Soft": "soft and restrained dynamics, gentle presence, not overpowering",
        "Medium": "medium intensity, balanced and usable in a mix",
        "Hard / Aggressive": (
            "hard, aggressive impact — strong transient and forward energy without clipping harshness"
        ),
    }
    return mapping.get(intensity, "medium intensity")


def _length_phrase(length: str) -> str:
    mapping = {
        "Very short (0.5–1s)": "very short duration (about half a second to one second)",
        "Short (1–2s)": "short duration (about one to two seconds)",
        "Medium (2–4s)": "medium duration (about two to four seconds)",
        "Long / Sustained": "longer sustained duration with a natural decay or hold",
    }
    return mapping.get(length, "short to medium duration")


def _texture_phrase(texture: str) -> str:
    mapping = {
        "Clean": "clean, polished recording quality with minimal noise",
        "Gritty": "gritty texture with light grit, edge, and character",
        "Airy": "airy, open texture with breath and high-frequency space",
        "Metallic": "metallic character — metal resonance, sheen, and hard reflections",
        "Organic": "organic, natural materials and soft real-world texture",
        "Sci-fi / Designed": (
            "sci-fi / designed sound-design character — stylized, processed, cinematic"
        ),
    }
    return mapping.get(texture, "clean texture")


def duration_for_length(length: str | None) -> float:
    """Map length preset → suggested fal duration_seconds."""
    key = (length or DEFAULTS["length"]).strip()
    return float(LENGTH_DURATION_S.get(key, 2.0))


def build_sfx_prompt(
    *,
    category: str | None = None,
    intensity: str | None = None,
    length: str | None = None,
    texture: str | None = None,
    detail: str | None = None,
) -> str:
    """
    Compose a clean SFX prompt from builder controls.

    Optional free-text detail is appended only when non-empty.
    """
    cat = active_helper(category) or DEFAULTS["category"]
    inten = active_helper(intensity)
    leng = active_helper(length)
    tex = active_helper(texture)
    note = (detail or "").strip()

    # Category None → generic SFX core
    if is_helper_none(category):
        core = "a clear, usable sound effect"
    else:
        core = _category_core(cat)
    parts = [f"Sound effect: {core}."]
    if inten:
        parts.append(f"Intensity: {_intensity_phrase(inten)}.")
    if leng:
        parts.append(f"Length: {_length_phrase(leng)}.")
    if tex:
        parts.append(f"Character: {_texture_phrase(tex)}.")
    parts.append(
        "High-quality mono-or-stereo ready SFX, no music, no dialogue, "
        "no reverb wash that muddies the attack."
    )
    if note:
        parts.append(f"Additional detail: {note}.")

    return " ".join(parts).strip()


def clear_sfx_builder_values() -> dict[str, Any]:
    d = dict(DEFAULTS)
    d["detail"] = ""
    return d


# ---------------------------------------------------------------------------
# Video → SFX structured builder (real-estate–sensible defaults)
# ---------------------------------------------------------------------------

VS_STYLES: list[str] = with_none(
    [
        "Premium real-estate",
        "Cinematic",
        "Minimal/sparse",
        "Energy social",
        "Soft lifestyle",
    ]
)

VS_PACES: list[str] = with_none(
    [
        "Sparse",
        "Balanced",
        "Busy",
    ]
)

VS_EMPHASIS: list[str] = with_none(
    [
        "Cut transitions",
        "Movement/whooshes",
        "Footsteps & practicals",
        "Room tone/air",
        "Mixed",
    ]
)

VS_EXCLUDES: list[str] = [
    "No music",
    "No voice/dialogue",
    "No big impacts",
    "No sci-fi/cartoon",
    "No heavy bass",
]

VS_DEFAULTS: dict[str, Any] = {
    "style": "Premium real-estate",
    "pace": "Balanced",
    "emphasis": "Mixed",
    "excludes": ["No music", "No voice/dialogue", "No sci-fi/cartoon"],
    "note": "",
}


def _vs_style_phrase(style: str | None) -> str:
    if is_helper_none(style):
        return ""
    s = (style or VS_DEFAULTS["style"]).strip()
    mapping = {
        "Premium real-estate": (
            "premium real-estate listing audio — refined, tasteful, high-end property feel"
        ),
        "Cinematic": "cinematic film-grade foley and transitions, subtle score-less texture",
        "Minimal/sparse": "minimal sparse design — few well-placed sounds, lots of air",
        "Energy social": "energetic social-media pace — crisp cuts and light whooshes for Reels/TikTok",
        "Soft lifestyle": "soft lifestyle / aspirational calm — gentle practicals and soft air",
    }
    return mapping.get(s, mapping["Premium real-estate"])


def _vs_pace_phrase(pace: str | None) -> str:
    if is_helper_none(pace):
        return ""
    p = (pace or VS_DEFAULTS["pace"]).strip().lower()
    if p.startswith("sparse"):
        return "sparse density — leave space between events; avoid constant layering"
    if p.startswith("busy"):
        return "busy denser layering of practicals and transitions without mud"
    return "balanced density — clear events on cuts and motion, not overcrowded"


def _vs_emphasis_phrase(emphasis: str | None) -> str:
    if is_helper_none(emphasis):
        return ""
    e = (emphasis or VS_DEFAULTS["emphasis"]).strip().lower()
    if e.startswith("cut"):
        return "emphasize cut transitions and edit points"
    if e.startswith("movement") or "whoosh" in e:
        return "emphasize movement whooshes and camera-motion accents"
    if e.startswith("foot"):
        return "emphasize footsteps and practical object interactions"
    if e.startswith("room"):
        return "emphasize room tone, air, and subtle environmental bed"
    return "mixed emphasis: transitions, practicals, and light room air"


def build_video_sfx_prompt(
    *,
    style: str | None = None,
    pace: str | None = None,
    emphasis: str | None = None,
    excludes: list[str] | None = None,
    note: str | None = None,
) -> str:
    """
    Compile structured Video→SFX controls into a model prompt.

    Free-text note is always appendable; excludes become hard constraints.
    Helper dimensions set to (None) are omitted.
    """
    ex = list(excludes) if excludes is not None else list(VS_DEFAULTS["excludes"])
    note_txt = (note or "").strip()

    parts = [
        "Generate synchronized sound effects for this real-estate / property video.",
    ]
    sp = _vs_style_phrase(style)
    if sp:
        parts.append(f"Style: {sp}.")
    pp = _vs_pace_phrase(pace)
    if pp:
        parts.append(f"Pace: {pp}.")
    ep = _vs_emphasis_phrase(emphasis)
    if ep:
        parts.append(f"Emphasis: {ep}.")
    parts.append("Match on-screen actions, cuts, and motion timing. Photoreal foley only.")
    if ex:
        # Normalize chip labels into constraint sentences
        rules: list[str] = []
        for chip in ex:
            c = (chip or "").strip()
            if not c:
                continue
            if c.lower().startswith("no "):
                rules.append(c if c.endswith(".") else f"{c}.")
            else:
                rules.append(f"No {c}.")
        if rules:
            parts.append("Hard excludes: " + " ".join(rules))
    if note_txt:
        parts.append(f"Additional creative note: {note_txt}.")
    return " ".join(parts).strip()


def clear_video_sfx_builder_values() -> dict[str, Any]:
    return {
        "style": VS_DEFAULTS["style"],
        "pace": VS_DEFAULTS["pace"],
        "emphasis": VS_DEFAULTS["emphasis"],
        "excludes": list(VS_DEFAULTS["excludes"]),
        "note": "",
    }
