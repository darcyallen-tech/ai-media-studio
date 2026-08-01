"""
Scene Builder — structured dropdowns → high-quality real-estate staging prompts.
"""

from __future__ import annotations

from media_studio.helper_none import HELPER_NONE, active_helper, is_helper_none, with_none

ROOM_TYPES: list[str] = [
    "Living Room",
    "Primary Bedroom",
    "Kids Room (Boy)",
    "Kids Room (Girl)",
    "Kids Room (Neutral)",
    "Teen Room (Boy)",
    "Teen Room (Girl)",
    "Teen Room (Neutral)",
    "Home Office",
    "Dining Room",
    "Patio / Outdoor",
]

# Styles available for most rooms; room-specific overrides below
STYLES_ALL: list[str] = [
    "Modern",
    "Contemporary",
    "Mid-century Modern",
    "Minimalist",
    "Transitional",
    "Coastal / Light & Airy",
    "Traditional",
    "Industrial",
]

# Per-room style lists (must stay within STYLES_ALL names)
_ROOM_STYLES: dict[str, list[str]] = {
    "Living Room": STYLES_ALL,
    "Primary Bedroom": [
        "Modern",
        "Contemporary",
        "Mid-century Modern",
        "Minimalist",
        "Transitional",
        "Coastal / Light & Airy",
        "Traditional",
    ],
    "Kids Room (Boy)": [
        "Modern",
        "Contemporary",
        "Minimalist",
        "Transitional",
        "Coastal / Light & Airy",
    ],
    "Kids Room (Girl)": [
        "Modern",
        "Contemporary",
        "Minimalist",
        "Transitional",
        "Coastal / Light & Airy",
        "Traditional",
    ],
    "Kids Room (Neutral)": [
        "Modern",
        "Contemporary",
        "Minimalist",
        "Transitional",
        "Coastal / Light & Airy",
    ],
    "Teen Room (Boy)": [
        "Modern",
        "Contemporary",
        "Minimalist",
        "Industrial",
        "Mid-century Modern",
    ],
    "Teen Room (Girl)": [
        "Modern",
        "Contemporary",
        "Minimalist",
        "Coastal / Light & Airy",
        "Transitional",
    ],
    "Teen Room (Neutral)": [
        "Modern",
        "Contemporary",
        "Minimalist",
        "Transitional",
        "Industrial",
    ],
    "Home Office": [
        "Modern",
        "Contemporary",
        "Minimalist",
        "Mid-century Modern",
        "Industrial",
        "Transitional",
    ],
    "Dining Room": [
        "Modern",
        "Contemporary",
        "Mid-century Modern",
        "Minimalist",
        "Transitional",
        "Coastal / Light & Airy",
        "Traditional",
        "Industrial",
    ],
    "Patio / Outdoor": [
        "Modern",
        "Contemporary",
        "Minimalist",
        "Coastal / Light & Airy",
        "Transitional",
        "Industrial",
    ],
}

FURNITURE_DENSITY: list[str] = with_none(
    [
        "Minimal (only key pieces)",
        "Balanced",
        "Fully staged",
    ]
)

# Level "None" = zero decor/plants (semantic), not the helper skip sentinel
DECOR_AMOUNT: list[str] = ["None", "Light", "Medium", "Heavy"]
PLANTS: list[str] = ["None", "Light", "Medium", "Heavy"]
CAMERA_FEEL: list[str] = with_none(
    [
        "Wide (more spacious, wider angle look)",
        "Natural",
        "Tight (more compressed, longer lens feel)",
    ]
)
# Styles offered with skip option (room lists stay pure; UI prepends HELPER_NONE)
STYLES_ALL_WITH_NONE: list[str] = with_none(STYLES_ALL)

# Defaults for Clear
DEFAULTS = {
    "room_type": "Living Room",
    "style": "Modern",
    "furniture_density": "Balanced",
    "decor_amount": "Light",
    "plants": "Light",
    "camera_feel": "Natural",
}


def styles_for_room(room_type: str | None) -> list[str]:
    room = (room_type or DEFAULTS["room_type"]).strip()
    return with_none(list(_ROOM_STYLES.get(room, STYLES_ALL)))


def _style_language(style: str) -> str:
    mapping = {
        "Modern": (
            "modern aesthetic with clean lines, simple silhouettes, and a restrained "
            "neutral palette (warm grays, soft whites, light wood)"
        ),
        "Contemporary": (
            "contemporary look with current designer forms, soft neutrals, and polished "
            "but livable finishes"
        ),
        "Mid-century Modern": (
            "mid-century modern character—tapered legs, warm wood tones, organic curves, "
            "and a retro-modern palette"
        ),
        "Minimalist": (
            "minimalist staging—essential pieces only, lots of negative space, muted tones, "
            "and zero visual clutter"
        ),
        "Transitional": (
            "transitional style blending classic comfort with modern simplicity—soft lines, "
            "balanced neutrals, approachable elegance"
        ),
        "Coastal / Light & Airy": (
            "coastal light-and-airy feel—pale woods, soft blues/whites, breezy textiles, "
            "and bright natural light"
        ),
        "Traditional": (
            "traditional elegance—classic furniture forms, richer fabrics, refined symmetry, "
            "and warm inviting tones"
        ),
        "Industrial": (
            "industrial-inspired staging—metal accents, raw textures used sparingly, "
            "darker neutrals, and utilitarian chic"
        ),
    }
    return mapping.get(style, f"{style.lower()} aesthetic")


def _room_furniture_brief(room: str, density: str) -> str:
    """Key pieces language per room + density."""
    d = density or "Balanced"
    is_min = d.startswith("Minimal")
    is_full = d.startswith("Fully")

    briefs: dict[str, tuple[str, str, str]] = {
        # (minimal, balanced, full)
        "Living Room": (
            "a well-proportioned sofa and one coffee table only",
            "a sofa, coffee table, and one side accent (chair or floor lamp)",
            "a complete living set: sofa, coffee table, side seating, rug, and layered lighting",
        ),
        "Primary Bedroom": (
            "a bed with clean bedding and one nightstand",
            "a bed, matching nightstands, and a dresser or bench",
            "a fully staged bedroom: bed, nightstands, dresser, seating, and soft textiles",
        ),
        "Kids Room (Boy)": (
            "a twin/full bed and a small storage piece",
            "a bed, simple desk or play table, and storage",
            "a fully staged kids room: bed, desk, storage, play seating, and age-appropriate accents",
        ),
        "Kids Room (Girl)": (
            "a twin/full bed and a small storage piece",
            "a bed, simple desk or vanity table, and storage",
            "a fully staged kids room: bed, desk, storage, soft seating, and age-appropriate accents",
        ),
        "Kids Room (Neutral)": (
            "a twin/full bed and a small storage piece",
            "a bed, simple desk or play table, and storage",
            "a fully staged kids room: bed, desk, storage, seating, and gender-neutral accents",
        ),
        "Teen Room (Boy)": (
            "a bed and a desk",
            "a bed, desk with chair, and a dresser",
            "a fully staged teen room: bed, desk workstation, storage, seating, and casual styling",
        ),
        "Teen Room (Girl)": (
            "a bed and a desk",
            "a bed, desk with chair, and a dresser",
            "a fully staged teen room: bed, desk, storage, soft seating, and polished casual styling",
        ),
        "Teen Room (Neutral)": (
            "a bed and a desk",
            "a bed, desk with chair, and a dresser",
            "a fully staged teen room: bed, desk workstation, storage, seating, and clean styling",
        ),
        "Home Office": (
            "a desk and a task chair",
            "a desk, task chair, and a shelf or side storage",
            "a complete office: desk, chair, shelving, guest seating, and organized desk styling",
        ),
        "Dining Room": (
            "a dining table and chairs only",
            "a dining table with chairs and a simple sideboard or pendant feel",
            "a fully staged dining room: table, chairs, sideboard, lighting accents, and place settings",
        ),
        "Patio / Outdoor": (
            "a simple outdoor seating set (sofa or chairs + low table)",
            "outdoor seating with a coffee/side table and light lounge feel",
            "a fully staged patio: lounge seating, dining or side table, outdoor textiles, and layered comfort",
        ),
    }
    trip = briefs.get(room, briefs["Living Room"])
    if is_min:
        return trip[0]
    if is_full:
        return trip[2]
    return trip[1]


def _level_phrase(level: str, kind: str) -> str:
    lv = (level or "None").strip()
    if lv == "None":
        if kind == "decor":
            return "no decorative accessories or clutter"
        return "no plants"
    if kind == "decor":
        mapping = {
            "Light": "light, restrained decor (a few pillows, one art piece or tray max)",
            "Medium": "balanced decor (pillows, art, and a few surface accents—still tidy)",
            "Heavy": "rich layered decor (pillows, throws, art, and styled surfaces—still ordered, not messy)",
        }
    else:
        mapping = {
            "Light": "light greenery (one or two small plants only)",
            "Medium": "moderate plants for life and freshness without overcrowding",
            "Heavy": "generous but tasteful plant presence for a lush, lived-in feel",
        }
    return mapping.get(lv, mapping["Light"])


def _camera_phrase(camera: str) -> str:
    c = camera or "Natural"
    base = (
        "Keep the exact same camera position, framing, and viewpoint as the source image"
    )
    if c.startswith("Wide"):
        return (
            f"{base}; if needed, only a subtle wider-spacious composition feel—"
            "do not re-crop the room or invent a new angle"
        )
    if c.startswith("Tight"):
        return (
            f"{base}; if needed, only a subtle tighter/longer-lens compression feel—"
            "do not re-crop the room or invent a new angle"
        )
    return f"{base}; keep a natural listing-photo feel"


# Appended to every Scene Builder / Furniture Pop-in prompt — strict preservation
PRESERVATION_BLOCK = (
    "CRITICAL PRESERVATION RULES — the room shell must not change: "
    "Preserve the exact original wall color and paint tone (do not lighten, darken, cool, warm, "
    "recolor, repaint, or restain the walls). "
    "Preserve the original flooring and/or carpet color, pattern, and texture exactly. "
    "Preserve the ceiling color and texture exactly. "
    "Preserve all existing trim, baseboards, crown molding, windows, window frames, doors, "
    "door frames, hardware, and architectural details exactly as they appear. "
    "Preserve all existing lighting fixtures (ceiling lights, sconces, recessed lights, fans) "
    "exactly—do not replace, remove, recolor, or redesign them. "
    "Do not alter materials, finishes, or proportions of any permanent structure. "
    "Do not change the camera position, lens, or crop. "
    "You are ONLY allowed to add or replace movable furniture, soft textiles, decor accessories, "
    "and plants. Nothing else may change. "
    "Photorealistic real-estate photography quality, clean and listing-ready."
)

# Opening intent — Flux 2 Pro style: direct edit instruction (Enhance usually unnecessary)
POPIN_INTENT = (
    "Edit this interior photo for real-estate virtual staging: place realistic furniture into the room. "
    "If temporary or sparse items are already present, replace them with the staged set. "
)

# Furniture Swap — room already has furniture; replace it, don't fill an empty room
SWAP_INTENT = (
    "Edit this furnished interior photo for a real-estate furniture swap: "
    "replace the existing furniture, soft goods, and decor with a new staged set. "
    "Remove or fully replace the current movable furniture—do not leave old sofas, tables, "
    "or chairs mixed with the new set. This is a swap of an already-furnished room, "
    "not empty-room staging."
)


def _audience_note(room: str) -> str:
    if "Kids" in room:
        if "Boy" in room:
            return "Age-appropriate for a young boy—playful but listing-clean, no logos or brand text."
        if "Girl" in room:
            return "Age-appropriate for a young girl—soft and cheerful but listing-clean, no logos or brand text."
        return "Age-appropriate and gender-neutral for kids—calm colors, listing-clean, no logos or brand text."
    if "Teen" in room:
        if "Boy" in room:
            return "Age-appropriate for a teenage boy—casual and modern, listing-clean."
        if "Girl" in room:
            return "Age-appropriate for a teenage girl—stylish and calm, listing-clean."
        return "Age-appropriate and gender-neutral for a teen—simple modern, listing-clean."
    if room == "Patio / Outdoor":
        return "Outdoor furniture suitable for a residential patio; weather-appropriate fabrics."
    return ""


def build_scene_prompt(
    *,
    room_type: str | None = None,
    style: str | None = None,
    furniture_density: str | None = None,
    decor_amount: str | None = None,
    plants: str | None = None,
    camera_feel: str | None = None,
    mode: str = "popin",
) -> str:
    """
    Compose a high-quality staging prompt from Scene Builder controls.

    Helper dimensions set to ``(None)`` are omitted (except room type, which is
    required for staging intent). Decor/plants level ``None`` still means zero amount.

    mode:
      - "popin": empty / sparse room furniture placement
      - "swap": replace existing furniture with a new set/style
    """
    room = (room_type or DEFAULTS["room_type"]).strip()
    style_raw = active_helper(style)
    allowed = styles_for_room(room)
    if style_raw and style_raw not in allowed:
        # Invalid for room → drop style rather than force a wrong one when user chose something
        if style_raw not in STYLES_ALL:
            style_raw = None
        elif allowed:
            style_raw = allowed[0]
    density = active_helper(furniture_density)
    # Decor/plants: "None" is a valid level (zero), not HELPER_NONE skip
    decor = (decor_amount or DEFAULTS["decor_amount"]).strip()
    plant = (plants or DEFAULTS["plants"]).strip()
    if is_helper_none(decor_amount) and decor_amount not in ("None",):
        decor = ""
    if is_helper_none(plants) and plants not in ("None",):
        plant = ""
    camera = active_helper(camera_feel)
    mode_key = (mode or "popin").strip().lower()
    is_swap = mode_key in ("swap", "furniture_swap", "furniture-swap")

    density_for_brief = density or "Balanced"
    furniture = _room_furniture_brief(room, density_for_brief)
    style_lang = _style_language(style_raw) if style_raw else "appropriate residential"
    decor_lang = _level_phrase(decor, "decor") if decor else ""
    plant_lang = _level_phrase(plant, "plants") if plant else ""
    camera_lang = _camera_phrase(camera) if camera else ""
    audience = _audience_note(room)

    density_line = {
        "Minimal (only key pieces)": "Furniture density: minimal—only the key pieces listed.",
        "Balanced": "Furniture density: balanced—complete but not crowded.",
        "Fully staged": "Furniture density: fully staged for a premium listing, still orderly.",
    }.get(density or "", "")

    if is_swap:
        parts = [
            SWAP_INTENT,
            (
                f"Restage this {room.lower()} by swapping in a {style_lang} furniture and soft-goods set "
                f"only—style applies to furnishings, not the room shell "
                f"(walls, floors, and architecture stay as photographed)."
            ),
            f"New furniture set should include {furniture}.",
        ]
        if density_line:
            parts.append(density_line)
        if decor_lang:
            parts.append(f"Decor: {decor_lang}.")
        if plant_lang:
            parts.append(f"Plants: {plant_lang}.")
        if camera_lang:
            parts.append(f"{camera_lang}.")
        parts.append(
            "Keep original camera angle, lighting direction, and room geometry locked."
        )
    else:
        parts = [
            POPIN_INTENT,
            (
                f"Stage this space as a {room.lower()} using a {style_lang} for the "
                f"furniture and soft goods only—style applies to furnishings, not the room shell "
                f"(walls, floors, and architecture stay as photographed)."
            ),
            f"Include {furniture}.",
        ]
        if density_line:
            parts.append(density_line)
        if decor_lang:
            parts.append(f"Decor: {decor_lang}.")
        if plant_lang:
            parts.append(f"Plants: {plant_lang}.")
        if camera_lang:
            parts.append(f"{camera_lang}.")
    if audience:
        parts.append(audience)
    parts.append(PRESERVATION_BLOCK)
    return " ".join(parts)


def clear_defaults() -> dict[str, str]:
    return dict(DEFAULTS)
