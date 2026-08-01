"""
Scenario system for the Studio (Image/Video) workspace.

Each scenario has:
- metadata (label, description, default model)
- which control panels to show
- tailored prompt generation
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from media_studio.scene_builder import (
    DEFAULTS as SCENE_DEFAULTS,
    build_scene_prompt,
)
from media_studio.tools_registry import SKY_PRESETS, dehaze_prompt

# Smart model defaults (labels must match MODEL_LABELS / fal.models)
DEFAULT_IMAGE_MODEL = "Image · Flux 2 Pro (edit)"
DEFAULT_VIDEO_EDIT_MODEL = "Video · Kling O3 Standard – V2V Edit"

# Models that count as “still following scenario defaults” (not a manual pick).
# Only Auto + current smart defaults — manual Nano Banana / Flex / etc. are kept.
_SCENARIO_DEFAULT_MODEL_SET = frozenset(
    {
        DEFAULT_IMAGE_MODEL,
        DEFAULT_VIDEO_EDIT_MODEL,
        "Auto (default)",
        "Auto",
    }
)

# Prefer Kling V2V when a clip is present (still defaults stay Flux for pure still work)
VIDEO_HEAVY_KEYS = frozenset({"day_to_night", "twilight_exterior"})


@dataclass(frozen=True)
class ScenarioSpec:
    key: str
    label: str
    description: str
    enabled: bool = True
    tags: tuple[str, ...] = ()
    default_model_hint: str = DEFAULT_IMAGE_MODEL
    # UI panel flags
    show_furniture_builder: bool = False
    show_presets: bool = False
    show_simple_builder: bool = False
    allow_video_ref: bool = True
    notes: str = ""


# Freeform — no scene builder / scenario template
BLANK_CANVAS_KEY = "blank_canvas"
BLANK_CANVAS_LABEL = "Blank / Custom"

# App-level scenario bar order (Blank first, then staged RE workflows)
APP_SCENARIO_ORDER: tuple[str, ...] = (
    BLANK_CANVAS_KEY,
    "furniture_popin",
    "furniture_swap",
    "day_to_night",
    "twilight_exterior",
    "sky_mood",
    "lot_to_home",
    "dehaze",
    "landscaper",
    "amenity_on",
    "season_change",
)

# Back-compat alias used by Image workspace code
IMAGE_WORKSPACE_ORDER: tuple[str, ...] = APP_SCENARIO_ORDER

# Tools that receive sensible defaults when a scenario is selected
# (Upscale, Re-Aspect, generic audio never appear here.)
SCENARIO_TOOL_DEFAULTS: dict[str, tuple[str, ...]] = {
    "sky_mood": ("sky",),
    "dehaze": ("dehaze",),
    "day_to_night": (),  # Image/Video only — no forced tool inject
    "twilight_exterior": ("sky",),
    "landscaper": (),
    "lot_to_home": (),
    "furniture_popin": (),
    "furniture_swap": (),
    "amenity_on": ("amenity",),
    "season_change": ("season",),
    BLANK_CANVAS_KEY: (),
}

# Video Studio secondary tabs
VIDEO_WORKSPACE_ORDER: tuple[tuple[str, str], ...] = (
    ("received", "Received"),
    ("blank", "Blank Canvas"),
    ("camera_lock", "Camera Lock"),
)


SCENARIOS: dict[str, ScenarioSpec] = {
    BLANK_CANVAS_KEY: ScenarioSpec(
        key=BLANK_CANVAS_KEY,
        label=BLANK_CANVAS_LABEL,
        description=(
            "Freeform — no scene builder or scenario template. "
            "Upload a still or video, choose any model, write your own prompt."
        ),
        enabled=True,
        tags=("general", "edit", "blank", "custom"),
        default_model_hint=DEFAULT_IMAGE_MODEL,
        show_furniture_builder=False,
        show_presets=False,
        show_simple_builder=False,
        allow_video_ref=True,
        notes="Simple source + model + prompt + strength. All models available.",
    ),
    "furniture_popin": ScenarioSpec(
        key="furniture_popin",
        label="Furniture Pop-in",
        description=(
            "Stage furniture into an empty or sparse room. "
            "Image tab: Scene Builder → Generate Image (Flux). "
            "Then Send to Video → upload source clip → Generate Video (camera-matched). "
            "Walls, floors, ceiling, and architecture stay locked."
        ),
        enabled=True,
        tags=("interior", "staging", "furniture"),
        default_model_hint=DEFAULT_IMAGE_MODEL,
        show_furniture_builder=True,
        show_presets=True,
        show_simple_builder=False,
        allow_video_ref=True,
        notes="Primary staging workflow; still → video handoff supported.",
    ),
    "furniture_swap": ScenarioSpec(
        key="furniture_swap",
        label="Furniture Swap",
        description=(
            "Replace existing furniture in an already-furnished room with a new set/style. "
            "Image tab: Scene Builder → Generate Image (Flux 2 Pro). "
            "Architecture, camera angle, and lighting stay locked—only movable furniture/decor change. "
            "Then Send to Video for camera-matched V2V."
        ),
        enabled=True,
        tags=("interior", "staging", "furniture", "swap"),
        default_model_hint=DEFAULT_IMAGE_MODEL,
        show_furniture_builder=True,
        show_presets=True,
        show_simple_builder=False,
        allow_video_ref=True,
        notes="Swap existing furniture; room shell locked; still → video handoff supported.",
    ),
    "day_to_night": ScenarioSpec(
        key="day_to_night",
        label="Day → Night",
        description=(
            "Turn a daytime photo into a natural night look (interior or exterior). "
            "Image tab: scope + intensity → Generate Image. "
            "Send to Video → apply night look while locking camera motion to the source clip. "
            "Architecture locked; only lighting/sky change."
        ),
        enabled=True,
        tags=("exterior", "interior", "lighting", "time-of-day"),
        default_model_hint=DEFAULT_IMAGE_MODEL,
        show_simple_builder=True,
        allow_video_ref=True,
        notes="Architecture-locked day→night stills; night V2V handoff supported.",
    ),
    "twilight_exterior": ScenarioSpec(
        key="twilight_exterior",
        label="Twilight Exterior",
        description=(
            "Classic real-estate twilight: warm interior lights + blue-hour sky. "
            "Image tab → Generate Image → Send to Video for camera-matched V2V. "
            "Home geometry and landscape plan stay fixed."
        ),
        enabled=True,
        tags=("exterior", "lighting"),
        default_model_hint=DEFAULT_IMAGE_MODEL,
        show_simple_builder=True,
        allow_video_ref=True,
        notes="Listing-ready blue-hour exteriors; twilight V2V handoff supported.",
    ),
    "sky_mood": ScenarioSpec(
        key="sky_mood",
        label="Sky + Mood",
        description=(
            "Replace the sky and optionally match ambient mood on the property. "
            "Image tab → Generate Image → optional Send to Video. "
            "Also under Tools → Sky Replacement for a simpler path."
        ),
        enabled=True,
        tags=("exterior", "sky"),
        default_model_hint=DEFAULT_IMAGE_MODEL,
        show_simple_builder=True,
        allow_video_ref=True,
        notes="Sky-only (or soft mood match); architecture locked; optional V2V sky transfer.",
    ),
    "lot_to_home": ScenarioSpec(
        key="lot_to_home",
        label="Lot to Home",
        description=(
            "Visualize a finished home on a vacant lot, pad, or foundation photo. "
            "Image tab → Generate Image → Send to Video for lot walkthrough clips. "
            "Lot ground plane, neighbors, and camera stay anchored."
        ),
        enabled=True,
        tags=("exterior", "development"),
        default_model_hint=DEFAULT_IMAGE_MODEL,
        show_simple_builder=True,
        allow_video_ref=True,
        notes="Site-anchored home visualization; still → video handoff supported.",
    ),
    "dehaze": ScenarioSpec(
        key="dehaze",
        label="Dehaze / Clear Air",
        description=(
            "Remove smoke, haze, fog, and smog from exteriors. "
            "Image tab → Generate Image → optional Send to Video. "
            "Also under Tools → Dehaze for a one-click utility."
        ),
        enabled=True,
        tags=("exterior", "cleanup"),
        default_model_hint=DEFAULT_IMAGE_MODEL,
        show_simple_builder=True,
        allow_video_ref=True,
        notes="Atmosphere-only clear; property geometry locked; optional V2V clear transfer.",
    ),
    "landscaper": ScenarioSpec(
        key="landscaper",
        label="Landscaper",
        description=(
            "Upgrade exterior softscape to a clean, manicured real-estate landscape "
            "(fresh lawn, neat foundation plantings, tasteful trees/shrubs). "
            "Image tab: density / trees / shrubs / lawn → Generate Image. "
            "Then Send to Video → upload source clip → Generate Video (camera-matched). "
            "Architecture and hardscape stay locked; only landscaping changes."
        ),
        enabled=True,
        tags=("exterior", "landscaping", "staging"),
        default_model_hint=DEFAULT_IMAGE_MODEL,
        show_simple_builder=True,
        allow_video_ref=True,
        notes="Manicured listing landscaping; still → video handoff supported.",
    ),
    "amenity_on": ScenarioSpec(
        key="amenity_on",
        label="Amenity On",
        description=(
            "Turn amenities on for listing appeal: pool with clear water/ripples, "
            "fireplace lit, interior or landscape lights glowing. "
            "Only the amenity changes — structure, camera, and the rest stay locked. "
            "Also under Tools → Amenity On."
        ),
        enabled=True,
        tags=("interior", "exterior", "amenity", "lifestyle"),
        default_model_hint=DEFAULT_IMAGE_MODEL,
        show_simple_builder=True,
        allow_video_ref=True,
        notes="Amenity activation only; architecture locked.",
    ),
    "season_change": ScenarioSpec(
        key="season_change",
        label="Season Change",
        description=(
            "Change season and landscape cues only: Spring / Summer / Fall / Winter, "
            "clear snow → green, or curb-appeal boost. "
            "House, hardscape layout, windows, and camera stay locked. "
            "Also under Tools → Season / Curb."
        ),
        enabled=True,
        tags=("exterior", "season", "landscaping", "curb-appeal"),
        default_model_hint=DEFAULT_IMAGE_MODEL,
        show_simple_builder=True,
        allow_video_ref=True,
        notes="Season/softscape only; structure and hardscape locked.",
    ),
}

# --- Simple-scenario option catalogs ---

DAY_NIGHT_SCOPE = ["Exterior", "Interior"]
DAY_NIGHT_INTENSITY = ["Soft", "Medium", "Dramatic"]

TWILIGHT_LIGHTS = ["Warm interior lights on", "Exterior only (no interior glow)", "Subtle porch/path lights"]
TWILIGHT_SKY = ["Soft blue hour", "Deep blue hour", "Purple-pink dusk"]

LOT_HOME_STYLES = [
    "Modern single-story",
    "Modern two-story",
    "Craftsman",
    "Farmhouse",
    "Traditional suburban",
    "Contemporary ranch",
]

DEHAZE_STRENGTH = ["Gentle", "Standard", "Strong"]

# Landscaper controls (defaults: Medium / Medium deciduous / Full foundation / Established manicured)
LANDSCAPER_DENSITY = ["Low", "Medium", "High"]
LANDSCAPER_TREE_STYLE = [
    "None",
    "Small ornamental",
    "Medium deciduous",
    "Evergreen",
]
LANDSCAPER_SHRUB_STYLE = [
    "Minimal foundation",
    "Full foundation",
    "Layered",
]
LANDSCAPER_LAWN = ["Fresh sod", "Established manicured"]

SKY_MOOD_TYPES = list(SKY_PRESETS.keys())


def scenario_choices() -> list[str]:
    """Labels for legacy dropdowns (excludes blank / custom)."""
    return [
        s.label
        for s in SCENARIOS.values()
        if s.enabled and s.key != BLANK_CANVAS_KEY
    ]


def app_scenario_items() -> list[tuple[str, str]]:
    """``(id, label)`` for the app-level scenario bar."""
    items: list[tuple[str, str]] = []
    for key in APP_SCENARIO_ORDER:
        s = SCENARIOS.get(key)
        if s and s.enabled:
            items.append((s.key, s.label))
    known = {k for k, _ in items}
    for s in SCENARIOS.values():
        if s.enabled and s.key not in known:
            items.append((s.key, s.label))
    return items


def image_workspace_items() -> list[tuple[str, str]]:
    """Back-compat: same ordered list as the app scenario bar."""
    return app_scenario_items()


def default_scenario() -> ScenarioSpec:
    return SCENARIOS["furniture_popin"]


def active_scenario_key() -> str:
    """Persisted app scenario if available; else default key."""
    try:
        from media_studio.ui_prefs import get_app_scenario

        key = get_app_scenario()
        if key in SCENARIOS and SCENARIOS[key].enabled:
            return key
    except Exception:
        pass
    return default_scenario().key


def get_scenario(key_or_label: str | None) -> ScenarioSpec | None:
    if not key_or_label:
        return default_scenario()
    raw = key_or_label.strip()
    low = raw.lower().replace(" (coming soon)", "")
    if low in (
        "blank",
        "blank canvas",
        "blank / custom",
        "blank/custom",
        "custom",
        "freeform",
        "free form",
    ):
        return SCENARIOS[BLANK_CANVAS_KEY]
    if low in SCENARIOS:
        return SCENARIOS[low]
    # aliases
    if low in ("furniture", "furniture / staging", "furniture staging"):
        return SCENARIOS["furniture_popin"]
    if low in ("furniture swap", "swap furniture", "restage", "restaging"):
        return SCENARIOS["furniture_swap"]
    if low in ("landscaper", "landscape", "landscaping", "yard", "lawn"):
        return SCENARIOS["landscaper"]
    if low in ("sky", "sky mood", "sky + mood"):
        return SCENARIOS["sky_mood"]
    if low in ("dehaze", "clear air", "dehaze / clear air"):
        return SCENARIOS["dehaze"]
    for s in SCENARIOS.values():
        if s.label.lower() == low or s.key == low:
            return s
    return default_scenario()


def tools_touched_by_scenario(key_or_label: str | None) -> tuple[str, ...]:
    """Tool ids that should receive soft defaults for this scenario."""
    s = get_scenario(key_or_label)
    if not s:
        return ()
    return SCENARIO_TOOL_DEFAULTS.get(s.key, ())


def prompt_is_scenario_defaultish(
    current: str | None,
    *,
    last_default: str | None,
    scenario_key: str | None = None,
) -> bool:
    """
    True when it is safe to replace the prompt on scenario switch.

    Empty, equal to the last loaded default, or very short freeform → replace.
    Long user-written text that differs from last_default → keep.
    """
    cur = " ".join((current or "").split()).strip()
    if not cur:
        return True
    prev = " ".join((last_default or "").split()).strip()
    if prev and cur == prev:
        return True
    # Blank scenario: anything non-empty is user content
    if scenario_key == BLANK_CANVAS_KEY or is_blank_canvas(scenario_key):
        return False
    # Short stubs only
    if len(cur) < 24:
        return True
    return False


def is_blank_canvas(key_or_label: str | None) -> bool:
    s = get_scenario(key_or_label)
    return bool(s and s.key == BLANK_CANVAS_KEY)


def is_scenario_enabled(key_or_label: str | None) -> bool:
    s = get_scenario(key_or_label)
    return bool(s and s.enabled)


def is_auto_model_choice(choice: str | None) -> bool:
    if not choice:
        return True
    return choice.strip().lower() in ("", "auto", "auto (default)", "default")


def is_following_scenario_defaults(model_choice: str | None) -> bool:
    """
    True when the dropdown is Auto or still on a known scenario default
    (not a user-locked manual pick like Nano Banana / Flux Flex / etc.).
    """
    if is_auto_model_choice(model_choice):
        return True
    raw = (model_choice or "").strip()
    return raw in _SCENARIO_DEFAULT_MODEL_SET


def scenario_default_model(
    scenario_key: str | None,
    *,
    has_video: bool = False,
) -> str:
    """
    Smart default for the model dropdown.

    - Image / staging scenarios → Flux 2 Pro (edit)
    - Video-heavy (Day → Night, Twilight) with a clip loaded → Kling V2V edit
    - Otherwise still Flux 2 Pro for still generation
    """
    s = get_scenario(scenario_key) or default_scenario()
    key = s.key
    if has_video and key in VIDEO_HEAVY_KEYS:
        return DEFAULT_VIDEO_EDIT_MODEL
    return s.default_model_hint or DEFAULT_IMAGE_MODEL


def resolve_model_for_scenario_switch(
    scenario_key: str | None,
    current_model: str | None,
    *,
    has_video: bool = False,
) -> str:
    """Apply scenario default only when the user has not manually chosen another model."""
    default = scenario_default_model(scenario_key, has_video=has_video)
    if is_following_scenario_defaults(current_model):
        return default
    return (current_model or default).strip() or default


def simple_control_schema(scenario_key: str) -> dict[str, Any]:
    """
    Labels + choices for the two simple dropdowns (opt_a, opt_b) and optional free text.
    """
    key = get_scenario(scenario_key).key if get_scenario(scenario_key) else scenario_key
    if key == "day_to_night":
        return {
            "opt_a_label": "Scope",
            "opt_a_choices": DAY_NIGHT_SCOPE,
            "opt_a_value": DAY_NIGHT_SCOPE[0],
            "opt_b_label": "Night intensity",
            "opt_b_choices": DAY_NIGHT_INTENSITY,
            "opt_b_value": "Medium",
            "note_label": "Optional notes",
            "note_placeholder": "e.g. keep landscape lights on, soft moonlight",
            "show_note": True,
            "show_opt_c": False,
            "show_opt_d": False,
        }
    if key == "twilight_exterior":
        return {
            "opt_a_label": "Property lights",
            "opt_a_choices": TWILIGHT_LIGHTS,
            "opt_a_value": TWILIGHT_LIGHTS[0],
            "opt_b_label": "Sky mood",
            "opt_b_choices": TWILIGHT_SKY,
            "opt_b_value": TWILIGHT_SKY[0],
            "note_label": "Optional notes",
            "note_placeholder": "e.g. warm living-room glow through front windows",
            "show_note": True,
            "show_opt_c": False,
            "show_opt_d": False,
        }
    if key == "sky_mood":
        return {
            "opt_a_label": "Sky type",
            "opt_a_choices": SKY_MOOD_TYPES,
            "opt_a_value": SKY_MOOD_TYPES[0],
            "opt_b_label": "Mood match",
            "opt_b_choices": ["Subtle ambient match", "Stronger warm/cool match", "Sky only (no recolor)"],
            "opt_b_value": "Subtle ambient match",
            "note_label": "Custom sky (optional)",
            "note_placeholder": "Overrides sky type if filled",
            "show_note": True,
            "show_opt_c": False,
            "show_opt_d": False,
        }
    if key == "lot_to_home":
        return {
            "opt_a_label": "Home style",
            "opt_a_choices": LOT_HOME_STYLES,
            "opt_a_value": LOT_HOME_STYLES[0],
            "opt_b_label": "Placement",
            "opt_b_choices": [
                "Centered on lot",
                "Set back from street",
                "Corner-lot orientation",
            ],
            "opt_b_value": "Centered on lot",
            "note_label": "Optional notes",
            "note_placeholder": "e.g. 3-car garage left, covered porch, light landscaping",
            "show_note": True,
            "show_opt_c": False,
            "show_opt_d": False,
        }
    if key == "dehaze":
        return {
            "opt_a_label": "Clear strength",
            "opt_a_choices": DEHAZE_STRENGTH,
            "opt_a_value": "Standard",
            "opt_b_label": "Focus",
            "opt_b_choices": [
                "Smoke / wildfire haze",
                "General atmospheric haze",
                "Fog / mist",
            ],
            "opt_b_value": "Smoke / wildfire haze",
            "note_label": "Optional notes",
            "note_placeholder": "Usually leave blank",
            "show_note": True,
            "show_opt_c": False,
            "show_opt_d": False,
        }
    if key == "landscaper":
        return {
            "opt_a_label": "Density",
            "opt_a_choices": LANDSCAPER_DENSITY,
            "opt_a_value": "Medium",
            "opt_b_label": "Tree style",
            "opt_b_choices": LANDSCAPER_TREE_STYLE,
            "opt_b_value": "Medium deciduous",
            "opt_c_label": "Shrub & bush style",
            "opt_c_choices": LANDSCAPER_SHRUB_STYLE,
            "opt_c_value": "Full foundation",
            "opt_d_label": "Lawn finish",
            "opt_d_choices": LANDSCAPER_LAWN,
            "opt_d_value": "Established manicured",
            "note_label": "Optional notes",
            "note_placeholder": "e.g. keep existing oak on left, mulch beds only",
            "show_note": True,
            "show_opt_c": True,
            "show_opt_d": True,
        }
    if key == "amenity_on":
        from media_studio.tools_registry import AMENITY_CHOICES

        return {
            "opt_a_label": "Amenity",
            "opt_a_choices": list(AMENITY_CHOICES),
            "opt_a_value": AMENITY_CHOICES[0],
            "opt_b_label": "Intensity",
            "opt_b_choices": ["Subtle", "Balanced", "Strong / inviting"],
            "opt_b_value": "Balanced",
            "note_label": "Optional notes",
            "note_placeholder": "e.g. keep pool furniture, soft fire glow only",
            "show_note": True,
            "show_opt_c": False,
            "show_opt_d": False,
        }
    if key == "season_change":
        from media_studio.tools_registry import SEASON_CHOICES

        return {
            "opt_a_label": "Target season",
            "opt_a_choices": list(SEASON_CHOICES),
            "opt_a_value": SEASON_CHOICES[0],
            "opt_b_label": "Curb emphasis",
            "opt_b_choices": [
                "Natural seasonal change",
                "Listing curb-appeal boost",
                "Minimal / subtle only",
            ],
            "opt_b_value": "Natural seasonal change",
            "note_label": "Optional notes",
            "note_placeholder": "e.g. keep mature oak, light snow on roof only",
            "show_note": True,
            "show_opt_c": False,
            "show_opt_d": False,
        }
    # furniture fallback (simple panel hidden)
    return {
        "opt_a_label": "Option A",
        "opt_a_choices": ["—"],
        "opt_a_value": "—",
        "opt_b_label": "Option B",
        "opt_b_choices": ["—"],
        "opt_b_value": "—",
        "note_label": "Notes",
        "note_placeholder": "",
        "show_note": False,
        "show_opt_c": False,
        "show_opt_d": False,
    }


# Shared soft shell (sky/mood and other lighter scenarios)
_PRESERVE_SHELL = (
    "Preserve exact wall colors, flooring, ceiling, trim, windows, doors, and existing light fixtures. "
    "Do not repaint, retexture, or redesign architecture. "
    "Keep camera position and framing identical."
)

# Strong architecture lock for Day→Night / Twilight (still + video ref)
ARCHITECTURE_LOCK = (
    "CRITICAL ARCHITECTURE LOCK — the property must not be redesigned: "
    "Preserve the exact building footprint, roofline, facade materials, siding/brick/stucco color and texture, "
    "window sizes and positions, doors, garage, porch, columns, railings, and all architectural details. "
    "Preserve landscape layout: trees, shrubs, lawn edges, hardscape, driveways, walkways, and fencing exactly. "
    "Do not add, remove, or reshape structures, rooms, or landscaping. "
    "Do not change camera position, lens, crop, or perspective. "
    "Only time-of-day lighting, sky, and light sources may change. "
    "Photorealistic real-estate photography quality, listing-ready."
)

# Intensity guidance for day→night stills
_NIGHT_INTENSITY = {
    "Soft": (
        "soft naturalistic night: gentle ambient fill, modest practicals, "
        "sky still readable with a hint of residual dusk light"
    ),
    "Medium": (
        "balanced listing night: clear deep-night sky, believable house and path lights, "
        "rich but not underexposed shadows"
    ),
    "Dramatic": (
        "cinematic night: deep blacks, strong contrast, bold practical pools of light, "
        "starry or inky sky — still photoreal, not fantasy"
    ),
}

_TWILIGHT_SKY_GUIDE = {
    "Soft blue hour": (
        "soft blue hour sky — cool cyan-blue gradient near the horizon, "
        "gentle residual daylight in the upper sky, no harsh sunset bands"
    ),
    "Deep blue hour": (
        "deep blue hour sky — rich saturated blue overhead fading to cooler horizon, "
        "clear post-sunset look, no daylight wash"
    ),
    "Purple-pink dusk": (
        "purple-pink dusk sky — warm magenta and soft pink near the horizon blending into cool blue aloft, "
        "premium listing twilight palette"
    ),
}

_TWILIGHT_LIGHTS_GUIDE = {
    "Warm interior lights on": (
        "turn on warm interior lights so every visible window and glass door shows a cozy golden glow "
        "(living areas, kitchen, bedrooms as appropriate); add subtle porch/entry lights if present"
    ),
    "Exterior only (no interior glow)": (
        "use exterior lighting only — porch, path, and facade accents if present; "
        "windows stay dark or neutrally lit with no warm interior glow"
    ),
    "Subtle porch/path lights": (
        "subtle porch, entry, and path lighting only; soft warm points of light, "
        "minimal interior window glow if any"
    ),
}


def build_scenario_prompt(
    scenario_key: str,
    *,
    # furniture builder (optional)
    room_type: str | None = None,
    style: str | None = None,
    furniture_density: str | None = None,
    decor_amount: str | None = None,
    plants: str | None = None,
    camera_feel: str | None = None,
    # simple builder
    opt_a: str | None = None,
    opt_b: str | None = None,
    opt_c: str | None = None,
    opt_d: str | None = None,
    note: str | None = None,
) -> str:
    s = get_scenario(scenario_key) or default_scenario()
    key = s.key
    note = (note or "").strip()

    if key == BLANK_CANVAS_KEY:
        return note  # freeform — no template

    if key == "furniture_popin":
        return build_scene_prompt(
            room_type=room_type or SCENE_DEFAULTS["room_type"],
            style=style or SCENE_DEFAULTS["style"],
            furniture_density=furniture_density or SCENE_DEFAULTS["furniture_density"],
            decor_amount=decor_amount or SCENE_DEFAULTS["decor_amount"],
            plants=plants or SCENE_DEFAULTS["plants"],
            camera_feel=camera_feel or SCENE_DEFAULTS["camera_feel"],
            mode="popin",
        )

    if key == "furniture_swap":
        return build_scene_prompt(
            room_type=room_type or SCENE_DEFAULTS["room_type"],
            style=style or SCENE_DEFAULTS["style"],
            furniture_density=furniture_density or SCENE_DEFAULTS["furniture_density"],
            decor_amount=decor_amount or SCENE_DEFAULTS["decor_amount"],
            plants=plants or SCENE_DEFAULTS["plants"],
            camera_feel=camera_feel or SCENE_DEFAULTS["camera_feel"],
            mode="swap",
        )

    if key == "day_to_night":
        return _build_day_to_night_still(opt_a=opt_a, opt_b=opt_b, note=note)

    if key == "twilight_exterior":
        return _build_twilight_still(opt_a=opt_a, opt_b=opt_b, note=note)

    if key == "sky_mood":
        return _build_sky_mood_still(opt_a=opt_a, opt_b=opt_b, note=note)

    if key == "lot_to_home":
        return _build_lot_to_home_still(opt_a=opt_a, opt_b=opt_b, note=note)

    if key == "dehaze":
        return _build_dehaze_still(opt_a=opt_a, opt_b=opt_b, note=note)

    if key == "landscaper":
        return _build_landscaper_still(
            opt_a=opt_a, opt_b=opt_b, opt_c=opt_c, opt_d=opt_d, note=note
        )

    if key == "amenity_on":
        from media_studio.tools_registry import amenity_prompt

        return amenity_prompt(opt_a, note)

    if key == "season_change":
        from media_studio.tools_registry import season_tool_prompt

        base = season_tool_prompt(opt_a, note)
        if opt_b and "curb" in (opt_b or "").lower():
            base = (
                f"{base.rstrip('.')} "
                "Emphasize listing curb appeal: healthy lawn, tidy beds, polished softscape."
            )
        elif opt_b and "minimal" in (opt_b or "").lower():
            base = f"{base.rstrip('.')} Keep changes subtle and photoreal."
        return base

    return build_scene_prompt(**SCENE_DEFAULTS)


# ---------------------------------------------------------------------------
# Still builders (Day → Night, Twilight, Sky, Lot, Dehaze)
# ---------------------------------------------------------------------------

# Property lock for sky / dehaze (sky or atmosphere only)
_PROPERTY_LOCK = (
    "CRITICAL PROPERTY LOCK: preserve exact building footprint, roofline, facade materials, "
    "colors, windows, doors, landscaping layout, hardscape, vehicles, and all permanent structure. "
    "Do not redesign, restage, or reframe. Keep camera position and crop identical."
)

# Architecture + hardscape lock for Landscaper (softscape may change)
_LANDSCAPE_SHELL_LOCK = (
    "CRITICAL ARCHITECTURE AND HARDSCAPE LOCK: preserve exact building footprint, roofline, "
    "facade materials, siding/brick/stucco color and texture, window sizes and positions, doors, "
    "garage, porch, columns, railings, and all architectural details. "
    "Preserve hardscape exactly: driveways, walkways, patios, decks, fencing, retaining walls, "
    "and paved surfaces. Preserve sky, sun direction, lighting, and shadows on the structure. "
    "Do not change camera position, lens, crop, or perspective. "
    "Only softscape may change: lawn, soil beds, mulch, foundation plantings, shrubs, trees, "
    "and ground cover. Plants must sit naturally on the ground plane with correct scale and "
    "contact shadows. Photorealistic real-estate marketing quality — clean and manicured, "
    "never overgrown, wild, jungle-like, or fantastical."
)

_LANDSCAPER_DENSITY = {
    "Low": (
        "sparse, restrained plantings — open lawn with a light foundation band and few accents; "
        "do not overcrowd beds"
    ),
    "Medium": (
        "balanced listing landscaping — full but orderly plant beds and a well-filled foundation "
        "without crowding the facade or walkways"
    ),
    "High": (
        "generous but still manicured plantings — fuller beds and more accents while remaining "
        "neat, controlled, and listing-ready (not wild or overgrown)"
    ),
}

_LANDSCAPER_TREES = {
    "None": "no new specimen trees; rely on lawn and foundation plantings only",
    "Small ornamental": (
        "one or two small ornamental trees (e.g. Japanese maple, flowering crabapple scale) "
        "tastefully placed, correct scale to the home"
    ),
    "Medium deciduous": (
        "medium deciduous shade/ornamental trees with seasonal canopy, "
        "natural placement flanking or framing the home without blocking windows"
    ),
    "Evergreen": (
        "neat evergreen trees (e.g. spruce/cedar scale) as structured accents, "
        "trimmed and listing-ready — not a dense forest wall"
    ),
}

_LANDSCAPER_SHRUBS = {
    "Minimal foundation": (
        "minimal foundation plantings — a simple neat row of low shrubs and tidy edges along "
        "the base of the home"
    ),
    "Full foundation": (
        "full foundation plantings — continuous, even shrubs and bushes along the foundation "
        "with clean edges and professional curb appeal"
    ),
    "Layered": (
        "layered foundation beds — low groundcover, mid shrubs, and taller accent bushes "
        "in depth, still manicured and ordered"
    ),
}

_LANDSCAPER_LAWN = {
    "Fresh sod": (
        "fresh green sod lawn — uniform color, tight seams, recently installed look, "
        "crisp edges against beds and hardscape"
    ),
    "Established manicured": (
        "established manicured lawn — healthy even green turf, clean mow lines, "
        "crisp bed edges, premium listing finish"
    ),
}

# Site lock for lot-to-home (keep lot context)
_SITE_LOCK = (
    "CRITICAL SITE LOCK: preserve the existing ground plane, lot shape, grade, horizon, "
    "neighboring context, street edge, camera position, lens, and framing. "
    "Do not invent a different street, parcel shape, or viewpoint. "
    "Only add the finished home and light supporting site elements (driveway/walk/landscaping as needed)."
)

_SKY_MOOD_MATCH = {
    "Subtle ambient match": (
        "Gently match ambient color temperature and soft bounce light on the property to the new sky "
        "without repainting walls or changing materials — subtle, photoreal listing grade."
    ),
    "Stronger warm/cool match": (
        "Apply a more noticeable warm/cool ambient match from the new sky onto exterior surfaces and "
        "landscape tones, still photoreal — do not repaint or retexture materials."
    ),
    "Sky only (no recolor)": (
        "Change the sky only; do not recolor the building, hardscape, or landscape."
    ),
}

_DEHAZE_FOCUS = {
    "Smoke / wildfire haze": (
        "Prioritize removing wildfire smoke, brown/gray atmospheric murk, and smoke plumes "
        "while restoring natural sky and distant detail."
    ),
    "General atmospheric haze": (
        "Clear general atmospheric haze and milky air for crisper distance and truer contrast."
    ),
    "Fog / mist": (
        "Reduce fog and mist for clearer visibility while keeping a natural outdoor look "
        "(do not invent a completely different weather system)."
    ),
}

_LOT_PLACEMENT = {
    "Centered on lot": "center the home on the lot with balanced side setbacks",
    "Set back from street": "set the home back from the street edge with a plausible front yard depth",
    "Corner-lot orientation": "orient the home naturally for a corner-lot presentation if the site suggests it",
}


def _note_suffix(note: str | None) -> str:
    n = (note or "").strip()
    return f" Additional notes: {n}." if n else ""


def _build_day_to_night_still(
    *,
    opt_a: str | None = None,
    opt_b: str | None = None,
    note: str | None = None,
) -> str:
    """Still prompt optimized for converting day photos to natural night."""
    scope = (opt_a or "Exterior").strip()
    intensity = (opt_b or "Medium").strip()
    intensity_guide = _NIGHT_INTENSITY.get(intensity, _NIGHT_INTENSITY["Medium"])
    extra = _note_suffix(note)

    if scope.lower().startswith("interior"):
        return (
            "Edit this daytime interior photo into a natural nighttime interior (real-estate quality). "
            f"Night intensity: {intensity.lower()} — {intensity_guide}. "
            "Use warm practical lamps and soft night ambient; windows show true night exterior. "
            "Do not move furniture or change wall/floor/ceiling/trim colors. "
            f"{ARCHITECTURE_LOCK} "
            "Only lighting, window night views, and night ambiance may change."
            f"{extra}"
        )

    return (
        "Edit this daytime exterior property photo into a natural nighttime exterior (real-estate quality). "
        f"Night intensity: {intensity.lower()} — {intensity_guide}. "
        "Deep night sky; realistic porch/path/street lights; soft warm window glow where windows show. "
        "Remove daytime sun and hard daylight shadows. "
        f"{ARCHITECTURE_LOCK} "
        "Only lighting and sky/time of day may change—not landscaping or materials."
        f"{extra}"
    )


def _build_twilight_still(
    *,
    opt_a: str | None = None,
    opt_b: str | None = None,
    note: str | None = None,
) -> str:
    """Still prompt for classic real-estate twilight (warm interiors + blue hour)."""
    lights = (opt_a or TWILIGHT_LIGHTS[0]).strip()
    sky = (opt_b or TWILIGHT_SKY[0]).strip()
    sky_guide = _TWILIGHT_SKY_GUIDE.get(sky, _TWILIGHT_SKY_GUIDE[TWILIGHT_SKY[0]])
    lights_guide = _TWILIGHT_LIGHTS_GUIDE.get(lights, _TWILIGHT_LIGHTS_GUIDE[TWILIGHT_LIGHTS[0]])
    extra = _note_suffix(note)

    return (
        "Edit this exterior property photo to a premium real-estate twilight / blue-hour look. "
        f"Sky: {sky.lower()} — {sky_guide}. "
        f"Lights: {lights.lower()} — {lights_guide}. "
        "Warm interiors + cool sky contrast; soft twilight ambient; listing-ready exposure. "
        "Remove harsh midday sun. "
        f"{ARCHITECTURE_LOCK} "
        "Only time-of-day lighting and sky may change."
        f"{extra}"
    )


def _build_sky_mood_still(
    *,
    opt_a: str | None = None,
    opt_b: str | None = None,
    note: str | None = None,
) -> str:
    """Still prompt: sky replacement + optional ambient mood match."""
    sky_type = (opt_a or SKY_MOOD_TYPES[0]).strip()
    mood = (opt_b or "Subtle ambient match").strip()
    custom = (note or "").strip()
    mood_bit = _SKY_MOOD_MATCH.get(mood, _SKY_MOOD_MATCH["Subtle ambient match"])

    if custom:
        sky_bit = (
            f"Replace only the sky with: {custom}. "
            "Seamlessly blend the new sky at the roofline and treeline with natural horizon haze."
        )
    else:
        preset = SKY_PRESETS.get(sky_type, SKY_PRESETS["Clear blue"])
        sky_bit = (
            f"{preset} "
            f"Sky preset intent: {sky_type}. "
            "Seamlessly blend at roof and tree edges; update window sky reflections subtly if visible."
        )

    return (
        "Edit this exterior photo: replace the sky for real-estate listing quality. "
        f"{sky_bit} "
        f"Mood match: {mood.lower()} — {mood_bit} "
        f"{_PROPERTY_LOCK} "
        f"{_PRESERVE_SHELL} "
        "Only the sky (and optional subtle ambient match) may change."
    )


def _build_lot_to_home_still(
    *,
    opt_a: str | None = None,
    opt_b: str | None = None,
    note: str | None = None,
) -> str:
    """Still prompt: finished home visualization on a vacant lot / pad / foundation."""
    home = (opt_a or LOT_HOME_STYLES[0]).strip()
    place = (opt_b or "Centered on lot").strip()
    place_guide = _LOT_PLACEMENT.get(place, _LOT_PLACEMENT["Centered on lot"])
    extra = _note_suffix(note)

    return (
        "Edit this vacant lot / pad / foundation photo: visualize a finished residential home. "
        f"Style: {home}. Placement: {place.lower()} — {place_guide}. "
        "Natural scale, driveway/walk if appropriate, light landscaping; match perspective and sun. "
        "Align to foundation/pad when visible. "
        f"{_SITE_LOCK} "
        "Photoreal development visualization, listing quality."
        f"{extra}"
    )


def _build_dehaze_still(
    *,
    opt_a: str | None = None,
    opt_b: str | None = None,
    note: str | None = None,
) -> str:
    """Still prompt: clear smoke / haze / fog while locking the property."""
    strength_map = {"Gentle": 0.4, "Standard": 0.75, "Strong": 0.9}
    strength_label = (opt_a or "Standard").strip()
    strength = strength_map.get(strength_label, 0.75)
    focus = (opt_b or "Smoke / wildfire haze").strip()
    focus_guide = _DEHAZE_FOCUS.get(focus, _DEHAZE_FOCUS["Smoke / wildfire haze"])
    custom = (note or "").strip()

    base = dehaze_prompt(custom or None, strength=strength)
    return (
        "Edit this exterior photo: clear the air for real-estate listing quality. "
        f"Strength: {strength_label.lower()}. Focus: {focus.lower()} — {focus_guide} "
        f"{base} "
        f"{_PROPERTY_LOCK} "
        "Atmosphere only—do not restage or invent objects."
    )


def _build_landscaper_still(
    *,
    opt_a: str | None = None,
    opt_b: str | None = None,
    opt_c: str | None = None,
    opt_d: str | None = None,
    note: str | None = None,
) -> str:
    """Still prompt: manicured real-estate landscaping on an exterior photo."""
    density = (opt_a or "Medium").strip()
    trees = (opt_b or "Medium deciduous").strip()
    shrubs = (opt_c or "Full foundation").strip()
    lawn = (opt_d or "Established manicured").strip()
    density_g = _LANDSCAPER_DENSITY.get(density, _LANDSCAPER_DENSITY["Medium"])
    trees_g = _LANDSCAPER_TREES.get(trees, _LANDSCAPER_TREES["Medium deciduous"])
    shrubs_g = _LANDSCAPER_SHRUBS.get(shrubs, _LANDSCAPER_SHRUBS["Full foundation"])
    lawn_g = _LANDSCAPER_LAWN.get(lawn, _LANDSCAPER_LAWN["Established manicured"])
    extra = _note_suffix(note)

    return (
        "Edit this exterior property photo: upgrade the landscaping to a clean, manicured "
        "real-estate listing look. "
        f"Plant density: {density.lower()} — {density_g}. "
        f"Tree style: {trees.lower()} — {trees_g}. "
        f"Shrub and bush style: {shrubs.lower()} — {shrubs_g}. "
        f"Lawn finish: {lawn.lower()} — {lawn_g}. "
        "Replace sparse, patchy, weedy, dead, or overgrown softscape with fresh healthy plants. "
        "Use neat bed edges, dark mulch or clean soil in beds, and natural ground contact. "
        "Avoid wild meadows, jungle density, exotic fantasy plants, or cluttered yard staging. "
        f"{_LANDSCAPE_SHELL_LOCK} "
        "Only lawn, plant beds, shrubs, and trees may change."
        f"{extra}"
    )


# ---------------------------------------------------------------------------
# Video tab prompts (Kling V2V) — camera match first, then content transfer
# ---------------------------------------------------------------------------

# Shared core: AI video must cut with original footage (no new camera motion)
CAMERA_MATCH_CORE = (
    "Apply the content from the reference image (@Image1) to this video (@Video1). "
    "Strictly preserve the original camera movement, framing, timing, and motion. "
    "Do not invent new camera movement. "
    "Keep architecture, lighting direction, and perspective consistent with the source video."
)

FURNITURE_VIDEO_REF_PROMPT = (
    f"{CAMERA_MATCH_CORE} "
    "Transfer furniture, textiles, decor, and plants from @Image1 into the room. "
    "Match placement and style from the still. Do not repaint walls or redesign architecture."
)

FURNITURE_SWAP_VIDEO_REF_PROMPT = (
    f"{CAMERA_MATCH_CORE} "
    "Replace the existing furniture in the video with the furniture and staging from @Image1. "
    "Match placement and style from the still; remove old furniture that conflicts with the new set. "
    "Do not repaint walls or redesign architecture—only movable furnishings and decor change."
)

DAY_TO_NIGHT_VIDEO_REF_PROMPT = (
    f"{CAMERA_MATCH_CORE} "
    "Transfer the nighttime lighting, sky, and ambiance from @Image1. "
    "Only time-of-day lighting and sky may change—property geometry stays locked."
)

TWILIGHT_VIDEO_REF_PROMPT = (
    f"{CAMERA_MATCH_CORE} "
    "Transfer the twilight look from @Image1: warm interior window glows, exterior lights, "
    "and blue-hour sky. Property geometry stays locked."
)

SKY_MOOD_VIDEO_REF_PROMPT = (
    f"{CAMERA_MATCH_CORE} "
    "Transfer the sky and ambient mood from @Image1. "
    "Only sky (and subtle ambient match) may change—building and landscape stay locked."
)

LOT_TO_HOME_VIDEO_REF_PROMPT = (
    f"{CAMERA_MATCH_CORE} "
    "Transfer the finished home from @Image1 onto the lot in the video. "
    "Match scale and placement; preserve lot ground plane and neighboring context."
)

DEHAZE_VIDEO_REF_PROMPT = (
    f"{CAMERA_MATCH_CORE} "
    "Transfer the clear-air look from @Image1—remove haze/smoke/fog to match the still. "
    "Only atmosphere/clarity may change; property stays locked."
)

LANDSCAPER_VIDEO_REF_PROMPT = (
    f"{CAMERA_MATCH_CORE} "
    "Transfer the manicured landscaping from @Image1 onto the property in the video: "
    "lawn, foundation plantings, shrubs, and trees. "
    "Match plant placement and density from the still. "
    "Keep architecture, hardscape, driveways, walkways, and camera motion locked—only softscape changes."
)


def build_video_ref_prompt(scenario_key: str | None = None) -> str:
    """Concise V2V prompt for the Video tab, keyed by active scenario."""
    s = get_scenario(scenario_key) if scenario_key else default_scenario()
    key = s.key if s else "furniture_popin"
    if key == BLANK_CANVAS_KEY:
        return (
            f"{CAMERA_MATCH_CORE} "
            "Apply the look from the reference still (@Image1) to this video (@Video1) "
            "while preserving camera motion and property geometry."
        )
    return {
        "day_to_night": DAY_TO_NIGHT_VIDEO_REF_PROMPT,
        "twilight_exterior": TWILIGHT_VIDEO_REF_PROMPT,
        "furniture_popin": FURNITURE_VIDEO_REF_PROMPT,
        "furniture_swap": FURNITURE_SWAP_VIDEO_REF_PROMPT,
        "sky_mood": SKY_MOOD_VIDEO_REF_PROMPT,
        "lot_to_home": LOT_TO_HOME_VIDEO_REF_PROMPT,
        "dehaze": DEHAZE_VIDEO_REF_PROMPT,
        "landscaper": LANDSCAPER_VIDEO_REF_PROMPT,
        "amenity_on": (
            f"{CAMERA_MATCH_CORE} "
            "Apply amenity activation from the reference still (@Image1) — "
            "pool water, fire, or lights on — while preserving camera motion and architecture."
        ),
        "season_change": (
            f"{CAMERA_MATCH_CORE} "
            "Apply seasonal landscape look from the reference still (@Image1) only; "
            "preserve house geometry, hardscape, and camera motion."
        ),
    }.get(key, FURNITURE_VIDEO_REF_PROMPT)


def video_ref_status_label(scenario_key: str | None = None) -> str:
    """Short label for status messages after Send to Video."""
    s = get_scenario(scenario_key) if scenario_key else default_scenario()
    key = s.key if s else "furniture_popin"
    return {
        "day_to_night": "night look transfer",
        "twilight_exterior": "twilight look transfer",
        "furniture_popin": "furniture transfer",
        "furniture_swap": "furniture swap transfer",
        "sky_mood": "sky/mood transfer",
        "lot_to_home": "home visualization transfer",
        "dehaze": "clear-air transfer",
        "landscaper": "landscaping transfer",
        "amenity_on": "amenity transfer",
        "season_change": "season transfer",
    }.get(key, "look transfer")
