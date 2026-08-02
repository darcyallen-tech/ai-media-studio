"""
Music Prompt Builder — structured controls → clean music generation prompts.

Mirrors the Studio Scene Builder pattern: dropdowns auto-fill a free-editable prompt.
Custom notes / exclude are never clobbered by structured-field changes; they are
always appended after the auto-built structured block.
"""

from __future__ import annotations

from typing import Any

from media_studio.helper_none import HELPER_NONE, with_none

# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------

GENRES: list[str] = with_none([
    "Ambient",
    "Cinematic",
    "Classical",
    "Country",
    "Electronic",
    "Folk",
    "Hip-Hop",
    "Jazz",
    "Latin",
    "Metal",
    "Pop",
    "R&B / Soul",
    "Rock",
    "World",
])

SUBGENRES: dict[str, list[str]] = {
    "Ambient": [
        "Dark Ambient",
        "Drone",
        "New Age",
        "Space Ambient",
        "Ambient Pop",
        "Chillout",
    ],
    "Cinematic": [
        "Epic Trailer",
        "Orchestral Score",
        "Hybrid Trailer",
        "Documentary",
        "Suspense / Thriller",
        "Emotional Piano",
        "Adventure",
    ],
    "Classical": [
        "Baroque",
        "Romantic",
        "Chamber",
        "Minimalist Classical",
        "Neo-Classical",
        "Solo Piano",
    ],
    "Country": [
        "Classic Country",
        "Outlaw",
        "Americana",
        "Bluegrass",
        "Country Pop",
        "Modern Country",
    ],
    "Electronic": [
        "House",
        "Techno",
        "Trance",
        "Drum & Bass",
        "Synthwave",
        "Lo-fi Electronic",
        "IDM",
        "EDM Pop",
        "Downtempo",
    ],
    "Folk": [
        "Indie Folk",
        "Traditional Folk",
        "Folk Rock",
        "Singer-Songwriter",
        "Acoustic Folk",
        "Celtic",
    ],
    "Hip-Hop": [
        "Boom Bap",
        "Trap",
        "Lo-fi Hip-Hop",
        "Conscious",
        "Old School",
        "Cloud Rap",
        "Instrumental Hip-Hop",
    ],
    "Jazz": [
        "Smooth Jazz",
        "Bebop",
        "Cool Jazz",
        "Jazz Fusion",
        "Nu Jazz",
        "Swing",
        "Modal Jazz",
    ],
    "Latin": [
        "Bossa Nova",
        "Salsa",
        "Reggaeton",
        "Latin Pop",
        "Tango",
        "Cumbia",
        "Flamenco",
    ],
    "Metal": [
        "Heavy Metal",
        "Thrash",
        "Metalcore",
        "Doom",
        "Prog Metal",
        "Power Metal",
    ],
    "Pop": [
        "Indie Pop",
        "Synth Pop",
        "Dance Pop",
        "Dream Pop",
        "Electropop",
        "K-Pop style",
        "Soft Pop",
    ],
    "R&B / Soul": [
        "Classic Soul",
        "Neo-Soul",
        "Contemporary R&B",
        "Funk",
        "Quiet Storm",
        "Gospel-tinged",
    ],
    "Rock": [
        "Alternative",
        "Grunge",
        "Southern Rock",
        "Indie Rock",
        "Classic Rock",
        "Hard Rock",
        "Punk",
        "Progressive Rock",
        "Soft Rock",
        "Blues Rock",
    ],
    "World": [
        "Afrobeat",
        "Reggae",
        "Indian Classical-inspired",
        "Middle Eastern",
        "East Asian Fusion",
        "Nordic Folk",
    ],
}

ERAS: list[str] = with_none([
    "60s",
    "70s",
    "80s",
    "90s",
    "2000s",
    "2010s",
    "Modern",
    "Timeless / classic",
])

TEMPO_PRESETS: list[str] = with_none([
    "Slow",
    "Medium",
    "Fast",
    "Custom BPM",
])

# Approximate BPM anchors when only a preset is chosen
TEMPO_BPM_HINTS: dict[str, tuple[int, int, str]] = {
    "Slow": (60, 80, "slow, unhurried tempo"),
    "Medium": (90, 115, "medium, steady tempo"),
    "Fast": (120, 145, "fast, energetic tempo"),
}

MOODS: list[str] = with_none([
    "Calm / peaceful",
    "Uplifting / hopeful",
    "Warm / intimate",
    "Melancholic / reflective",
    "Dark / moody",
    "Epic / dramatic",
    "Playful / light",
    "Mysterious",
    "Romantic",
    "Tense / suspenseful",
    "Dreamy / ethereal",
    "Confident / bold",
    "Nostalgic",
    "Corporate clean",
    "Listing / real-estate friendly",
])

ENERGY: list[str] = with_none([
    "Very low",
    "Low",
    "Medium",
    "High",
    "Very high",
])

VOCALS: list[str] = with_none([
    "Instrumental only",
    "Female lead",
    "Male lead",
    "Harmonics only",
    "Choir",
    "Mixed",
])

INSTRUMENTS: list[str] = with_none([
    "Guitar-driven",
    "Synth / electronic",
    "Piano / keys",
    "Sparse / minimal",
    "Full band",
    "Orchestral / strings",
    "Acoustic / organic",
])

# ----- Arrangement / layer builder (optional; ElevenLabs-friendly form language) -----
INTRO_ENERGY: list[str] = with_none(["Restrained", "Half", "Full"])
INTRO_LENGTH: list[str] = with_none(["~4s", "~8s", "~16s", "Custom"])
LIFT_CUE: list[str] = with_none([
    "After intro",
    "Around 8s",
    "Around 16s",
    "Around 30s",
    "Mid-track",
    "Custom time",
])
SOLO_INSTRUMENT: list[str] = with_none(["Lead guitar", "Synth lead", "None"])
SOLO_START: list[str] = with_none([
    "After lift",
    "Around 20s",
    "Around 30s",
    "Around 45s",
    "Late track",
    "Custom time",
])
SOLO_LENGTH: list[str] = with_none(["~4s", "~8s", "~12s", "~16s", "Custom"])
OUTRO_STYLE: list[str] = with_none([
    "Tight cutoff",
    "Short fade",
    "Long fade",
    "Cold stop",
])
# Short band-layer list only (multi-select in UI)
BAND_LAYERS: list[str] = [
    "Drums",
    "Bass",
    "Rhythm guitar",
    "Lead",
    "Keys/pads",
    "Strings",
]

DEFAULTS: dict[str, Any] = {
    "genre": "Ambient",
    "subgenre": "Chillout",
    "era": "Modern",
    "tempo": "Slow",
    "bpm": None,  # optional exact BPM
    "mood": "Calm / peaceful",
    "energy": "Low",
    "vocals": "Instrumental only",
    "instruments": HELPER_NONE,
    "lyrics": "",
    "custom_notes": "",
    "exclude": "",
    "instrumental": True,  # derived from vocals for API convenience
    # Arrangement (all optional)
    "intro_energy": HELPER_NONE,
    "intro_length": HELPER_NONE,
    "intro_length_custom_s": None,
    "lift_cue": HELPER_NONE,
    "lift_cue_custom": "",
    "solo_instrument": HELPER_NONE,
    "solo_start": HELPER_NONE,
    "solo_start_custom": "",
    "solo_length": HELPER_NONE,
    "solo_length_custom_s": None,
    "outro": HELPER_NONE,
    "layers": (),  # tuple of BAND_LAYERS names
}


def _norm_genre(genre: str | None) -> str:
    """Normalize a genre choice (str / list / None)."""
    if genre is None:
        return DEFAULTS["genre"]
    if isinstance(genre, (list, tuple)):
        genre = genre[0] if genre else DEFAULTS["genre"]
    g = str(genre).strip()
    if not g:
        return DEFAULTS["genre"]
    if g in SUBGENRES:
        return g
    lower = g.lower()
    for key in SUBGENRES:
        if key.lower() == lower:
            return key
    return g


def subgenres_for(genre: str | None) -> list[str]:
    """Sub-genre choices with (None) so the dimension can be silenced."""
    if _noneish(genre):
        return with_none(["General"])
    g = _norm_genre(genre)
    return with_none(list(SUBGENRES.get(g, ["General"])))


def default_subgenre(genre: str | None) -> str:
    g = _norm_genre(genre)
    subs = subgenres_for(g)
    preferred = {
        "Ambient": "Chillout",
        "Cinematic": "Emotional Piano",
        "Rock": "Indie Rock",
        "Pop": "Soft Pop",
        "Electronic": "Downtempo",
        "Hip-Hop": "Lo-fi Hip-Hop",
        "Folk": "Acoustic Folk",
        "Jazz": "Smooth Jazz",
        "R&B / Soul": "Neo-Soul",
        "Country": "Americana",
        "Classical": "Neo-Classical",
        "Latin": "Bossa Nova",
        "Metal": "Prog Metal",
        "World": "Afrobeat",
    }
    pick = preferred.get(g)
    if pick and pick in subs:
        return pick
    return subs[0]


def _noneish(value: str | None) -> bool:
    """Treat UI None/Off/(none / auto) as silent for prompt injection."""
    try:
        from media_studio.helper_none import is_helper_none

        if is_helper_none(value):
            return True
    except Exception:
        pass
    if value is None:
        return True
    s = str(value).strip()
    return not s or s.lower() in {"(none)", "none", "—", "-", "(none / auto)", "auto", "off", "(off)"}


def _era_phrase(era: str) -> str:
    if _noneish(era):
        return ""
    e = (era or "").strip()
    if not e:
        return ""
    if e == "Modern":
        return "modern production and contemporary sound design"
    if e == "Timeless / classic":
        return "a timeless, classic feel that is not locked to a specific decade"
    if e.endswith("s") and e[0].isdigit():
        return f"{e} era character and production aesthetics"
    return f"{e} vibe"


def _tempo_phrase(tempo: str | None, bpm: int | float | None) -> str:
    """Build tempo language; exact BPM wins when provided."""
    try:
        bpm_val = int(float(bpm)) if bpm is not None and str(bpm).strip() != "" else None
    except (TypeError, ValueError):
        bpm_val = None
    if bpm_val is not None and bpm_val > 0:
        bpm_val = max(40, min(220, bpm_val))
        return f"tempo around {bpm_val} BPM"

    if _noneish(tempo):
        return ""
    t = (tempo or "Medium").strip()
    if t == "Custom BPM":
        return "a clear, intentional tempo"
    hint = TEMPO_BPM_HINTS.get(t)
    if hint:
        lo, hi, phrase = hint
        return f"{phrase} (about {lo}–{hi} BPM)"
    return "a natural, musical tempo"


def _mood_phrase(mood: str | None) -> str:
    if _noneish(mood):
        return ""
    return mood.strip().lower()


def _energy_phrase(energy: str | None) -> str:
    if _noneish(energy):
        return ""
    e = energy.strip().lower()
    mapping = {
        "very low": "very low energy, sparse and restrained",
        "low": "low energy, gentle dynamics",
        "medium": "medium energy with balanced drive",
        "high": "high energy, driving and assertive",
        "very high": "very high energy, intense and full-throttle",
    }
    return mapping.get(e, f"{e} energy")


def vocals_is_instrumental(vocals: str | None) -> bool:
    if _noneish(vocals):
        return True  # no vocal line → treat as instrumental for lyrics attach
    v = (vocals or DEFAULTS["vocals"]).strip()
    return v.lower() in {"instrumental only", "instrumental", ""}


def _vocals_phrase(vocals: str | None) -> str:
    if _noneish(vocals):
        return ""
    v = vocals.strip()
    mapping = {
        "Instrumental only": (
            "Fully instrumental only — no vocals, no lyrics, no choir, no spoken word."
        ),
        "Female lead": "Feature a clear female lead vocal with natural diction.",
        "Male lead": "Feature a clear male lead vocal with natural diction.",
        "Harmonics only": (
            "Use soft harmonic / background vocal pads only — no lead lyrics, no spoken word."
        ),
        "Choir": "Include a rich choir or group vocal texture (no spoken word).",
        "Mixed": "Include mixed male and female vocals with clear lead and light harmonies.",
    }
    return mapping.get(v, "")


def _instruments_phrase(instruments: str | None) -> str:
    if _noneish(instruments):
        return ""
    inst = instruments.strip()
    mapping = {
        "Guitar-driven": "Guitar-driven arrangement; guitars lead the texture.",
        "Synth / electronic": "Synth and electronic textures front-and-center.",
        "Piano / keys": "Piano and keys focused; melodic keyboard presence.",
        "Sparse / minimal": "Sparse, minimal instrumentation with breathing space.",
        "Full band": "Full-band arrangement with tight ensemble feel.",
        "Orchestral / strings": "Orchestral / string-led arrangement.",
        "Acoustic / organic": "Acoustic, organic instruments and natural room feel.",
    }
    return mapping.get(inst, f"Instrument focus: {inst.lower()}.")


def _custom_seconds(value: Any) -> int | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        n = int(round(float(value)))
        return max(1, min(120, n))
    except (TypeError, ValueError):
        return None


def _layers_list(layers: Any) -> list[str]:
    if not layers:
        return []
    if isinstance(layers, str):
        parts = [p.strip() for p in layers.replace(";", ",").split(",")]
        raw = [p for p in parts if p]
    else:
        try:
            raw = [str(x).strip() for x in layers if str(x).strip()]
        except TypeError:
            return []
    allowed = {x.lower(): x for x in BAND_LAYERS}
    out: list[str] = []
    for r in raw:
        key = r.lower()
        if key in allowed and allowed[key] not in out:
            out.append(allowed[key])
    return out


def build_arrangement_block(
    *,
    intro_energy: str | None = None,
    intro_length: str | None = None,
    intro_length_custom_s: int | float | None = None,
    lift_cue: str | None = None,
    lift_cue_custom: str | None = None,
    solo_instrument: str | None = None,
    solo_start: str | None = None,
    solo_start_custom: str | None = None,
    solo_length: str | None = None,
    solo_length_custom_s: int | float | None = None,
    outro: str | None = None,
    layers: Any = None,
) -> str:
    """
    Optional arrangement / form language for ElevenLabs-style music prompts.

    Empty fields → no text (caller omits the whole block if return is empty).
    """
    parts: list[str] = []

    # Ensemble layers first (what plays)
    layer_names = _layers_list(layers)
    if layer_names:
        if len(layer_names) == 1:
            parts.append(f"Ensemble focus: {layer_names[0].lower()} only.")
        else:
            listed = ", ".join(n.lower() for n in layer_names[:-1])
            parts.append(
                f"Ensemble: {listed}, and {layer_names[-1].lower()} — "
                "clear parts, cohesive band texture."
            )

    # Intro
    intro_bits: list[str] = []
    if not _noneish(intro_energy):
        e = (intro_energy or "").strip().lower()
        intro_bits.append(
            {
                "restrained": "restrained, held-back energy",
                "half": "half energy, not yet full drive",
                "full": "full energy from the top",
            }.get(e, f"{e} energy")
        )
    if not _noneish(intro_length):
        ln = (intro_length or "").strip()
        if ln.lower() == "custom":
            sec = _custom_seconds(intro_length_custom_s)
            if sec:
                intro_bits.append(f"about {sec} seconds")
        else:
            intro_bits.append(ln.replace("~", "about ").strip())
    if intro_bits:
        parts.append("Intro: " + ", ".join(intro_bits) + ".")

    # Lift — when full energy hits
    if not _noneish(lift_cue):
        cue = (lift_cue or "").strip()
        custom = (lift_cue_custom or "").strip()
        if cue.lower() == "custom time" and custom:
            when = custom if custom.lower().startswith(("at ", "after ", "around ")) else f"at {custom}"
        else:
            when = {
                "After intro": "right after the intro",
                "Around 8s": "around 8 seconds",
                "Around 16s": "around 16 seconds",
                "Around 30s": "around 30 seconds",
                "Mid-track": "mid-track",
                "Custom time": "at a clear timed cue",
            }.get(cue, cue.lower())
        parts.append(
            f"Lift: full energy and full arrangement hit {when} "
            "(build cleanly into the lift)."
        )

    # Solo (optional)
    solo_inst = "" if _noneish(solo_instrument) else (solo_instrument or "").strip()
    if solo_inst and solo_inst.lower() != "none":
        inst_map = {
            "Lead guitar": "a lead guitar solo",
            "Synth lead": "a synth lead solo",
        }
        solo_name = inst_map.get(solo_inst, f"a {solo_inst.lower()} solo")
        start_bits: list[str] = []
        if not _noneish(solo_start):
            ss = (solo_start or "").strip()
            sc = (solo_start_custom or "").strip()
            if ss.lower() == "custom time" and sc:
                start_bits.append(
                    sc if sc.lower().startswith(("at ", "after ", "around ")) else f"starting at {sc}"
                )
            else:
                start_bits.append(
                    {
                        "After lift": "after the lift",
                        "Around 20s": "around 20 seconds",
                        "Around 30s": "around 30 seconds",
                        "Around 45s": "around 45 seconds",
                        "Late track": "late in the track",
                        "Custom time": "at a clear timed cue",
                    }.get(ss, ss.lower())
                )
        len_bits: list[str] = []
        if not _noneish(solo_length):
            sl = (solo_length or "").strip()
            if sl.lower() == "custom":
                sec = _custom_seconds(solo_length_custom_s)
                if sec:
                    len_bits.append(f"about {sec} seconds long")
            else:
                len_bits.append(sl.replace("~", "about ").strip() + " long")
        solo_line = f"Solo: feature {solo_name}"
        if start_bits:
            solo_line += f", {start_bits[0]}"
        if len_bits:
            solo_line += f", {len_bits[0]}"
        solo_line += " (supportive bed under the solo, not a full drop-out)."
        parts.append(solo_line)

    # Outro
    if not _noneish(outro):
        o = (outro or "").strip()
        outro_map = {
            "Tight cutoff": "Outro: tight cutoff — end cleanly with little or no tail.",
            "Short fade": "Outro: short natural fade to silence.",
            "Long fade": "Outro: long gradual fade to silence.",
            "Cold stop": "Outro: cold stop — hard stop with no fade.",
        }
        parts.append(outro_map.get(o, f"Outro: {o.lower()}."))

    if not parts:
        return ""
    return " ".join(parts).strip()


def duration_hard_limit_phrase(duration_s: int | float | None) -> str:
    """
    Hard length language for music models that ignore API duration.

    Empty / invalid → \"\" (caller omits).
    """
    try:
        if duration_s is None or str(duration_s).strip() == "":
            return ""
        n = int(round(float(duration_s)))
    except (TypeError, ValueError):
        return ""
    if n < 1:
        return ""
    n = max(3, min(180, n))
    return (
        f"Total length strictly about {n} seconds; end with a tight cutoff at {n} seconds; "
        f"do not extend or add a long fade past the target."
    )


def ensure_duration_in_prompt(prompt: str | None, duration_s: int | float | None) -> str:
    """
    Ensure hard-limit duration language is present (for freeform / Generate).

    If a total-length constraint already appears, leave the prompt alone.
    """
    text = (prompt or "").strip()
    phrase = duration_hard_limit_phrase(duration_s)
    if not phrase:
        return text
    low = text.lower()
    if "total length strictly" in low or (
        "strictly about" in low and "second" in low
    ):
        return text
    if not text:
        return phrase
    return f"{text}\n\n{phrase}".strip()


def build_structured_music_block(
    *,
    genre: str | None = None,
    subgenre: str | None = None,
    era: str | None = None,
    tempo: str | None = None,
    bpm: int | float | None = None,
    mood: str | None = None,
    energy: str | None = None,
    vocals: str | None = None,
    instruments: str | None = None,
    lyrics: str | None = None,
    instrumental: bool | None = None,
    intro_energy: str | None = None,
    intro_length: str | None = None,
    intro_length_custom_s: int | float | None = None,
    lift_cue: str | None = None,
    lift_cue_custom: str | None = None,
    solo_instrument: str | None = None,
    solo_start: str | None = None,
    solo_start_custom: str | None = None,
    solo_length: str | None = None,
    solo_length_custom_s: int | float | None = None,
    outro: str | None = None,
    layers: Any = None,
    duration_s: int | float | None = None,
) -> str:
    """
    Auto-built structured portion only (no custom notes / exclude).

    ``instrumental`` is accepted for back-compat; if omitted, derived from ``vocals``.
    Arrangement fields are optional — empty slots add no language.
    """
    g_raw = genre if not _noneish(genre) else None
    g = (g_raw or DEFAULTS["genre"]).strip() if g_raw else ""
    if g:
        subs = subgenres_for(g)
        sg = (subgenre or "").strip()
        if _noneish(subgenre) or not sg or sg not in subs:
            sg = "" if _noneish(subgenre) else default_subgenre(g)
    else:
        sg = ""

    era_s = era if not _noneish(era) else ""
    tempo_s = tempo if not _noneish(tempo) else ""
    vocals_s = "" if _noneish(vocals) else (vocals or "").strip()
    if instrumental is None:
        inst = vocals_is_instrumental(vocals_s or None)
    else:
        # Prefer explicit vocals when set; fall back to instrumental flag
        if vocals_s and vocals_s != DEFAULTS["vocals"]:
            inst = vocals_is_instrumental(vocals_s)
        else:
            inst = bool(instrumental)
            if inst and not vocals_s:
                vocals_s = "Instrumental only"

    def _a(word: str) -> str:
        w = (word or "").strip()
        if not w:
            return "A"
        return "An" if w[0].lower() in "aeiou" else "A"

    if g and sg and sg.lower() != "general" and not _noneish(sg):
        head = f"{_a(sg)} {sg.lower()} track in the {g.lower()} genre"
    elif g:
        head = f"{_a(g)} {g.lower()} track"
    else:
        head = "A music track"

    era_p = _era_phrase(era_s)
    tempo_p = _tempo_phrase(tempo_s, bpm)
    mood_p = _mood_phrase(mood)
    energy_p = _energy_phrase(energy)
    inst_p = _instruments_phrase(instruments)
    vocals_p = _vocals_phrase(vocals_s or None)
    arr_p = build_arrangement_block(
        intro_energy=intro_energy,
        intro_length=intro_length,
        intro_length_custom_s=intro_length_custom_s,
        lift_cue=lift_cue,
        lift_cue_custom=lift_cue_custom,
        solo_instrument=solo_instrument,
        solo_start=solo_start,
        solo_start_custom=solo_start_custom,
        solo_length=solo_length,
        solo_length_custom_s=solo_length_custom_s,
        outro=outro,
        layers=layers,
    )

    body_parts: list[str] = []
    if era_p:
        body_parts.append(f"{head}, with {era_p}.")
    else:
        body_parts.append(f"{head}.")
    if tempo_p:
        body_parts.append(f"Tempo: {tempo_p}.")
    if mood_p:
        body_parts.append(f"Mood: {mood_p}.")
    if energy_p:
        body_parts.append(f"Energy: {energy_p}.")
    if inst_p:
        body_parts.append(inst_p if inst_p.endswith(".") else f"{inst_p}.")
    # Arrangement: ensemble + form over time (ElevenLabs-friendly order)
    if arr_p:
        body_parts.append(arr_p)
    if vocals_p:
        body_parts.append(vocals_p)
    dur_p = duration_hard_limit_phrase(duration_s)
    if dur_p:
        body_parts.append(dur_p)
    body_parts.append(
        "Clean professional mix, cohesive arrangement, suitable for background use "
        "in video and media."
    )

    prompt = " ".join(body_parts)

    lyrics_text = (lyrics or "").strip()
    if not inst and lyrics_text:
        prompt += f"\n\nLyrics / vocal content to feature:\n{lyrics_text}"

    return prompt.strip()


def build_music_prompt(
    *,
    genre: str | None = None,
    subgenre: str | None = None,
    era: str | None = None,
    tempo: str | None = None,
    bpm: int | float | None = None,
    mood: str | None = None,
    energy: str | None = None,
    vocals: str | None = None,
    instruments: str | None = None,
    lyrics: str | None = None,
    custom_notes: str | None = None,
    exclude: str | None = None,
    instrumental: bool | None = None,
    intro_energy: str | None = None,
    intro_length: str | None = None,
    intro_length_custom_s: int | float | None = None,
    lift_cue: str | None = None,
    lift_cue_custom: str | None = None,
    solo_instrument: str | None = None,
    solo_start: str | None = None,
    solo_start_custom: str | None = None,
    solo_length: str | None = None,
    solo_length_custom_s: int | float | None = None,
    outro: str | None = None,
    layers: Any = None,
    duration_s: int | float | None = None,
) -> str:
    """
    Full music prompt = structured block + persistent custom notes + exclude.

    Custom notes and exclude are appended after the structured rebuild so they
    survive Genre/Sub-genre/Era/Tempo/Mood/Energy (and other structured) changes.
    """
    structured = build_structured_music_block(
        genre=genre,
        subgenre=subgenre,
        era=era,
        tempo=tempo,
        bpm=bpm,
        mood=mood,
        energy=energy,
        vocals=vocals,
        instruments=instruments,
        lyrics=lyrics,
        instrumental=instrumental,
        intro_energy=intro_energy,
        intro_length=intro_length,
        intro_length_custom_s=intro_length_custom_s,
        lift_cue=lift_cue,
        lift_cue_custom=lift_cue_custom,
        solo_instrument=solo_instrument,
        solo_start=solo_start,
        solo_start_custom=solo_start_custom,
        solo_length=solo_length,
        solo_length_custom_s=solo_length_custom_s,
        outro=outro,
        layers=layers,
        duration_s=duration_s,
    )

    parts = [structured]
    notes = (custom_notes or "").strip()
    if notes:
        parts.append(f"Additional notes: {notes}")
    avoid = (exclude or "").strip()
    if avoid:
        # Normalize so models see a clear negative constraint
        avoid_clean = avoid
        if not avoid_clean.lower().startswith("no ") and "avoid" not in avoid_clean.lower():
            avoid_clean = f"Avoid: {avoid_clean}"
        elif not avoid_clean.lower().startswith("avoid"):
            avoid_clean = f"Avoid: {avoid_clean}"
        parts.append(avoid_clean if avoid_clean.endswith(".") else f"{avoid_clean}.")

    return "\n\n".join(parts).strip()


def clear_builder_values() -> dict[str, Any]:
    """Default field values after Clear / first load."""
    d = dict(DEFAULTS)
    d["subgenre"] = default_subgenre(d["genre"])
    d["bpm"] = None
    d["lyrics"] = ""
    d["custom_notes"] = ""
    d["exclude"] = ""
    d["vocals"] = "Instrumental only"
    d["instruments"] = "(none / auto)"
    d["instrumental"] = True
    d["intro_energy"] = HELPER_NONE
    d["intro_length"] = HELPER_NONE
    d["intro_length_custom_s"] = None
    d["lift_cue"] = HELPER_NONE
    d["lift_cue_custom"] = ""
    d["solo_instrument"] = HELPER_NONE
    d["solo_start"] = HELPER_NONE
    d["solo_start_custom"] = ""
    d["solo_length"] = HELPER_NONE
    d["solo_length_custom_s"] = None
    d["outro"] = HELPER_NONE
    d["layers"] = ()
    return d
