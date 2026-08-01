"""Real-estate / furniture staging prompt presets."""

from __future__ import annotations

# Display name → base prompt (user can edit after load)
PROMPT_PRESETS: dict[str, str] = {
    "Modern Living Room": (
        "Stage this room as a modern living room. Add a sleek contemporary sofa, "
        "a low rectangular coffee table, and a simple floor lamp. Clean lines, "
        "neutral palette (warm grays, soft white, light wood), soft natural window light, "
        "uncluttered composition. Keep the existing architecture, walls, windows, and "
        "camera angle exactly the same — only replace or add furniture and decor."
    ),
    "Minimal & Clean": (
        "Restage with a minimal, clean look. Keep only essential furniture: one sofa, "
        "one coffee table, and subtle wall art if needed. Plenty of negative space, "
        "muted neutrals, no clutter, no extra props. Soft diffused daylight, calm and "
        "editorial. Preserve the room structure and camera framing; change only furniture "
        "and surface styling."
    ),
    "Bright & Airy": (
        "Create a bright, airy staging. Light-colored sofa, airy textiles, pale wood "
        "coffee table, sheer curtains feel, lots of soft daylight and lifted shadows. "
        "Fresh greens or white florals sparingly. Open, inviting, high-end listing style. "
        "Do not alter walls, floors, windows, or camera position — only furniture and decor."
    ),
    "Luxury Staging": (
        "Stage as luxury real-estate photography. Designer sofa, refined coffee table, "
        "high-end materials (marble, brass, velvet accents used sparingly), polished but "
        "lived-in elegance, balanced composition, soft cinematic lighting. Gallery-quality "
        "finish. Keep room geometry and viewpoint identical; replace furnishings and accents only."
    ),
    "Cozy Family Room": (
        "Stage a cozy family living room: comfortable sofa with throw pillows, warm coffee "
        "table, soft throw blanket, friendly lived-in warmth without mess. Warm wood tones, "
        "soft ambient light, approachable and inviting. Maintain the original room layout "
        "and camera angle; update furniture and soft furnishings only."
    ),
    "Just Sofa + Coffee Table (minimal)": (
        "Minimal furniture only: place a single well-proportioned sofa and one simple coffee "
        "table. No extra chairs, rugs, plants, or wall clutter unless needed for scale. "
        "Clean, product-focused staging for furniture visualization. Keep all architecture "
        "and camera movement/angle unchanged."
    ),
}


def preset_names() -> list[str]:
    return list(PROMPT_PRESETS.keys())


def get_preset(name: str | None) -> str | None:
    if not name:
        return None
    return PROMPT_PRESETS.get(name.strip())
