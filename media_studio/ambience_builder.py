"""
Ambience Prompt Builder — structured beds for real-estate / lifestyle video.

Not one-shot SFX: steady background layers (birds, wind, distant traffic, etc.).
Custom notes are never clobbered when structured controls change.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------

LOCATIONS: list[str] = [
    "(None)",
    "Quiet residential street",
    "Suburban backyard",
    "City park",
    "Busy urban street",
    "Coastal / waterfront",
    "Forest / nature",
    "Quiet interior / room tone",
    "Custom (use free text)",
]

TIMES: list[str] = [
    "(none)",
    "Day",
    "Morning",
    "Evening",
    "Night",
]

WEATHER: list[str] = [
    "(none)",
    "Calm",
    "Light breeze",
    "Windy",
]

# Layer controls: Off / Light / Medium
LAYER_LEVELS: list[str] = ["Off", "Light", "Medium"]

LAYERS: list[str] = [
    "Birds",
    "Wind in trees / leaves",
    "Distant traffic / cars passing",
    "Children playing",
    "Dogs / pets",
    "Insects / summer night",
    "Water / fountain",
    "People / footsteps nearby",
]

DENSITY: list[str] = [
    "(None)",
    "Sparse",
    "Balanced",
    "Lively",
]

DURATIONS_S: list[int] = [15, 30, 60]

DEFAULTS: dict[str, Any] = {
    "location": "Quiet residential street",
    "custom_location": "",
    "time_of_day": "Day",
    "weather": "Light breeze",
    "layers": {
        "Birds": "Light",
        "Wind in trees / leaves": "Light",
        "Distant traffic / cars passing": "Light",
        "Children playing": "Off",
        "Dogs / pets": "Off",
        "Insects / summer night": "Off",
        "Water / fountain": "Off",
        "People / footsteps nearby": "Off",
    },
    "density": "Balanced",
    "duration_s": 30,
    "custom_notes": "",
}


def _noneish(value: str | None) -> bool:
    if value is None:
        return True
    s = str(value).strip()
    return not s or s.lower() in {"(none)", "none", "—", "-", "off"}


def _location_phrase(location: str | None, custom: str | None) -> str:
    if _noneish(location):
        c = (custom or "").strip()
        return c if c else "a quiet outdoor setting"
    loc = (location or DEFAULTS["location"]).strip()
    if loc.startswith("Custom"):
        c = (custom or "").strip()
        if c:
            return c
        return "a quiet outdoor setting"
    return loc.lower()


def _time_phrase(time_of_day: str | None) -> str:
    if _noneish(time_of_day):
        return ""
    t = time_of_day.strip().lower()
    mapping = {
        "day": "daytime",
        "morning": "early morning",
        "evening": "evening / golden hour",
        "night": "nighttime",
    }
    return mapping.get(t, t)


def _weather_phrase(weather: str | None) -> str:
    if _noneish(weather):
        return ""
    w = weather.strip().lower()
    mapping = {
        "calm": "still, calm air",
        "light breeze": "a light breeze",
        "windy": "noticeable wind",
    }
    return mapping.get(w, w)


def _layer_phrase(name: str, level: str) -> str | None:
    lv = (level or "Off").strip()
    if lv.lower() == "off" or _noneish(lv):
        return None
    strength = "soft, light" if lv.lower() == "light" else "clear medium"
    phrases = {
        "Birds": f"{strength} birdsong",
        "Wind in trees / leaves": f"{strength} wind in trees and leaves",
        "Distant traffic / cars passing": f"{strength} distant traffic / cars passing far away",
        "Children playing": f"{strength} distant children playing",
        "Dogs / pets": f"{strength} occasional dogs or pets in the distance",
        "Insects / summer night": f"{strength} insects / summer-night chirps",
        "Water / fountain": f"{strength} water or fountain ambience",
        "People / footsteps nearby": f"{strength} distant people / soft footsteps nearby",
    }
    return phrases.get(name, f"{strength} {name.lower()}")


# Hard ban line — first thing models should see
AMBIENCE_NO_MUSIC_LINE = (
    "No music, no melody, no instruments, no piano, no drums, no harmonic content "
    "— pure environmental ambience only."
)

# ElevenLabs Sound Effects v2 practical prompt limit on fal (~450 chars)
ELEVENLABS_SFX_PROMPT_LIMIT = 450


def _density_phrase(density: str | None) -> str:
    if _noneish(density):
        return ""
    d = (density or "Balanced").strip().lower()
    mapping = {
        "sparse": (
            "Sparse overall density — airy and open, with breathing room between events. "
            "Not empty, but never busy."
        ),
        "balanced": (
            "Balanced density — realistic continuous environmental bed with gentle movement, "
            "quiet enough to sit under dialogue."
        ),
        "lively": (
            "Lively but still background ambience — more environmental activity and layers, "
            "never chaotic, never musical, still suitable under dialogue."
        ),
    }
    return mapping.get(d, mapping["balanced"])


def build_structured_ambience_block(
    *,
    location: str | None = None,
    custom_location: str | None = None,
    time_of_day: str | None = None,
    weather: str | None = None,
    layers: dict[str, str] | None = None,
    density: str | None = None,
    duration_s: int | float | None = None,
) -> str:
    """Auto-built structured portion only (no custom notes)."""
    place = _location_phrase(location, custom_location)
    time_p = _time_phrase(time_of_day)
    weather_p = _weather_phrase(weather)
    layer_map = layers if isinstance(layers, dict) else dict(DEFAULTS["layers"])

    # Setting description
    if time_p and weather_p:
        setting = f"{time_p} {place} with {weather_p}"
    elif time_p:
        setting = f"{time_p} {place}"
    elif weather_p:
        setting = f"{place} with {weather_p}"
    else:
        setting = place

    active_layers: list[str] = []
    for name in LAYERS:
        phrase = _layer_phrase(name, str(layer_map.get(name, "Off")))
        if phrase:
            active_layers.append(phrase)

    try:
        dur = int(float(duration_s)) if duration_s is not None else int(DEFAULTS["duration_s"])
    except (TypeError, ValueError):
        dur = int(DEFAULTS["duration_s"])
    dur = max(5, min(180, dur))

    parts: list[str] = [
        # Explicit genre lock — first lines matter most for diffusion audio models
        "Environmental sound field recording / ambient soundscape only.",
        AMBIENCE_NO_MUSIC_LINE,
        (
            f"Record a continuous, realistic background ambience of a {setting}. "
            "This is NOT a song, NOT a soundtrack, and NOT a musical bed."
        ),
    ]

    if active_layers:
        if len(active_layers) == 1:
            parts.append(f"Natural layers only: {active_layers[0]}.")
        else:
            listed = ", ".join(active_layers[:-1]) + f", and {active_layers[-1]}"
            parts.append(f"Natural environmental layers only: {listed}.")
    else:
        parts.append("Keep layers minimal — soft natural presence only (air, space, room).")

    dens = _density_phrase(density)
    if dens:
        parts.append(dens)
    parts.append(
        f"About {dur} seconds long, seamless and looping-friendly, even level, "
        "no sudden impacts, no voiceover, no speech, no jingles, no risers. "
        "Stereo field, natural perspective, production-ready under dialogue for "
        "real-estate and lifestyle video."
    )
    return " ".join(parts).strip()


def build_ambience_prompt(
    *,
    location: str | None = None,
    custom_location: str | None = None,
    time_of_day: str | None = None,
    weather: str | None = None,
    layers: dict[str, str] | None = None,
    density: str | None = None,
    duration_s: int | float | None = None,
    custom_notes: str | None = None,
) -> str:
    """Full prompt = structured block + persistent custom notes."""
    structured = build_structured_ambience_block(
        location=location,
        custom_location=custom_location,
        time_of_day=time_of_day,
        weather=weather,
        layers=layers,
        density=density,
        duration_s=duration_s,
    )
    notes = (custom_notes or "").strip()
    if notes:
        return f"{structured}\n\nAdditional notes: {notes}".strip()
    return structured


def build_ambience_prompt_short(
    *,
    location: str | None = None,
    custom_location: str | None = None,
    time_of_day: str | None = None,
    weather: str | None = None,
    layers: dict[str, str] | None = None,
    density: str | None = None,
    duration_s: int | float | None = None,
    custom_notes: str | None = None,
    max_chars: int = ELEVENLABS_SFX_PROMPT_LIMIT,
) -> str:
    """
    Compact ambience prompt for models with a hard character limit (~450 for EL SFX).

    Prioritizes: no-music ban + setting + key layers. Truncates notes last if needed.
    """
    place = _location_phrase(location, custom_location)
    time_p = _time_phrase(time_of_day)
    weather_p = _weather_phrase(weather)
    layer_map = layers if isinstance(layers, dict) else dict(DEFAULTS["layers"])

    bits: list[str] = []
    if time_p:
        bits.append(time_p)
    bits.append(place)
    if weather_p:
        bits.append(weather_p)
    setting = " ".join(bits)

    layer_short: list[str] = []
    short_names = {
        "Birds": "birds",
        "Wind in trees / leaves": "wind in trees",
        "Distant traffic / cars passing": "distant traffic",
        "Children playing": "distant children",
        "Dogs / pets": "distant dogs",
        "Insects / summer night": "insects",
        "Water / fountain": "water/fountain",
        "People / footsteps nearby": "distant footsteps",
    }
    for name in LAYERS:
        lv = str(layer_map.get(name, "Off")).strip().lower()
        if lv in ("off", "", "none"):
            continue
        label = short_names.get(name, name.lower())
        layer_short.append(f"{lv} {label}" if lv != "medium" else label)

    dens = (density or "Balanced").strip().lower()
    dens_word = dens if dens in ("sparse", "balanced", "lively") else "balanced"

    try:
        dur = int(float(duration_s)) if duration_s is not None else int(DEFAULTS["duration_s"])
    except (TypeError, ValueError):
        dur = int(DEFAULTS["duration_s"])

    core = (
        f"Pure environmental ambience only. {AMBIENCE_NO_MUSIC_LINE} "
        f"{setting}; {dens_word} density"
    )
    if layer_short:
        core += "; " + ", ".join(layer_short)
    core += (
        f". Continuous ~{dur}s loopable bed under dialogue. "
        "No speech, no impacts, no song."
    )
    notes = (custom_notes or "").strip()
    if notes:
        # Keep notes short if tight on budget
        room = max_chars - len(core) - 12
        if room > 20:
            snippet = notes if len(notes) <= room else notes[: room - 1].rstrip() + "…"
            core = f"{core} Notes: {snippet}"
    if len(core) > max_chars:
        core = core[: max_chars - 1].rstrip() + "…"
    return core.strip()


def fit_ambience_prompt_for_model(
    prompt: str,
    *,
    max_chars: int | None,
    builder_kwargs: dict[str, Any] | None = None,
) -> tuple[str, str | None]:
    """
    Ensure prompt fits model limit.

    Returns (prompt_to_send, status_note_or_None).
    If full prompt is too long and builder_kwargs given, rebuilds a short form.
    """
    text = (prompt or "").strip()
    if not max_chars or max_chars <= 0 or len(text) <= max_chars:
        return text, None

    if builder_kwargs is not None:
        short = build_ambience_prompt_short(max_chars=max_chars, **builder_kwargs)
        note = (
            f"Prompt shortened to {len(short)}/{max_chars} characters for this model "
            f"(full prompt was {len(text)} chars)."
        )
        return short, note

    # Hard truncate as last resort
    truncated = text[: max_chars - 1].rstrip() + "…"
    note = (
        f"Prompt truncated to {max_chars} characters for this model "
        f"(was {len(text)} chars)."
    )
    return truncated, note


def clear_ambience_values() -> dict[str, Any]:
    d = dict(DEFAULTS)
    d["layers"] = dict(DEFAULTS["layers"])
    d["custom_location"] = ""
    d["custom_notes"] = ""
    return d
