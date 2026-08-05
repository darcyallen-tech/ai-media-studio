"""
Director tab — multi-shot video models and prompt assembly.

Kling V3 / O3 multi_prompt (customize): up to 6 shots, total ≤ 15s.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


# UI label when I2V multi-shot derives frame size from the start still (no aspect param)
ASPECT_AUTO_FROM_STILL = "Auto (from start still)"

# Labels that mean "omit aspect_ratio from the API payload"
_ASPECT_AUTO_LABELS = frozenset(
    {
        "auto",
        "auto (from start still)",
        "auto (from ref still)",
        "default",
        "—",
        "none",
        "",
    }
)


@dataclass(frozen=True)
class DirectorModelSpec:
    key: str
    label: str
    endpoint: str
    # image-to-video multi-shot when any shot has a still
    i2v_endpoint: str | None = None
    # Optional pure T2V when no shot refs (Grok Imagine)
    t2v_endpoint: str | None = None
    max_shots: int = 6
    min_duration_s: int = 3
    max_duration_s: int = 15
    allowed_durations: tuple[int, ...] = tuple(range(3, 16))
    default_duration_s: int = 10
    # Exact API enum strings for T2V / R2V (never invent values)
    aspect_choices: tuple[str, ...] = ("16:9", "9:16", "1:1")
    default_aspect: str = "16:9"
    # fal field name for aspect on T2V (None = endpoint has no aspect param)
    aspect_param: str | None = "aspect_ratio"
    # I2V: Kling O3/V3 have no aspect_ratio — frame follows the start image
    i2v_accepts_aspect: bool = False
    # I2V image field: V3 = start_image_url; O3 = image_url
    i2v_image_param: str = "start_image_url"
    cost_per_second: float = 0.112  # ballpark @ no-audio / standard
    cost_per_second_audio: float | None = 0.168
    cost_per_second_by_resolution: dict[str, float] = field(default_factory=dict)
    cost_fixed_per_ref: float = 0.0
    resolution_choices: tuple[str, ...] = ()
    default_resolution: str | None = None
    supports_audio: bool = True
    default_generate_audio: bool = True
    notes: str = ""
    # fal multi_prompt shot duration is integer seconds as string
    shot_min_s: int = 1
    shot_max_s: int = 15
    # Runtime multi_prompt.prompt cap (Kling enforces 512 even when OpenAPI omits maxLength)
    multi_prompt_max_chars: int | None = 512
    # V3 I2V supports elements[] for real character binding (frontal + side refs)
    supports_kling_elements: bool = False
    # Character + Scene both attach as real image refs (Grok R2V, Kling V3 elements+start)
    supports_scene_image_ref: bool = False
    # Unique-asset ref budget (elements + images, or bag-of-images)
    max_unique_refs: int = 7
    # "kling_element" = 1 per unique character + unique scenes; "image_bag" = each still file
    ref_budget_mode: str = "kling_element"
    # "kling_multi" = multi_prompt; "grok_imagine" = single clip from refs + brief
    engine: str = "kling_multi"


DIRECTOR_MODELS: dict[str, DirectorModelSpec] = {
    "kling v3 pro multi-shot": DirectorModelSpec(
        key="kling v3 pro multi-shot",
        label="Kling V3 Pro · Multi-Shot",
        endpoint="fal-ai/kling-video/v3/pro/text-to-video",
        i2v_endpoint="fal-ai/kling-video/v3/pro/image-to-video",
        max_shots=6,
        min_duration_s=3,
        max_duration_s=15,
        cost_per_second=0.112,
        cost_per_second_audio=0.168,
        multi_prompt_max_chars=512,
        supports_kling_elements=True,
        supports_scene_image_ref=True,  # character→elements, scene→start still
        max_unique_refs=7,
        ref_budget_mode="kling_element",
        notes=(
            "Kling V3 Pro multi-shot — ≤15s, multi_prompt ≤512/shot. "
            "Character + Scene as real image refs (elements + start). "
            "Est. ~$0.11–0.17/s."
        ),
    ),
    "kling v3 standard multi-shot": DirectorModelSpec(
        key="kling v3 standard multi-shot",
        label="Kling V3 Standard · Multi-Shot",
        endpoint="fal-ai/kling-video/v3/standard/text-to-video",
        i2v_endpoint="fal-ai/kling-video/v3/standard/image-to-video",
        max_shots=6,
        min_duration_s=3,
        max_duration_s=15,
        cost_per_second=0.084,
        cost_per_second_audio=0.126,
        multi_prompt_max_chars=512,
        supports_kling_elements=True,
        supports_scene_image_ref=True,
        max_unique_refs=7,
        ref_budget_mode="kling_element",
        notes=(
            "Kling V3 Standard multi-shot — cheaper than Pro. "
            "Character + Scene as real image refs. multi_prompt ≤512/shot."
        ),
    ),
    "kling o3 pro multi-shot": DirectorModelSpec(
        key="kling o3 pro multi-shot",
        label="Kling O3 Pro · Multi-Shot (Director)",
        endpoint="fal-ai/kling-video/o3/pro/text-to-video",
        i2v_endpoint="fal-ai/kling-video/o3/pro/image-to-video",
        max_shots=6,
        min_duration_s=3,
        max_duration_s=15,
        cost_per_second=0.112,
        cost_per_second_audio=0.168,
        default_generate_audio=False,
        # OpenAPI: I2V required field is image_url (not start_image_url); no aspect_ratio
        i2v_image_param="image_url",
        i2v_accepts_aspect=False,
        multi_prompt_max_chars=512,
        supports_kling_elements=False,
        supports_scene_image_ref=False,  # single image_url — scene in prompt only
        max_unique_refs=7,
        ref_budget_mode="kling_element",
        notes=(
            "Kling O3 Pro multi-shot — multi_prompt ≤512/shot. "
            "Single image_url (character pack = 1); Scene is text-only on this model."
        ),
    ),
    "kling o3 standard multi-shot": DirectorModelSpec(
        key="kling o3 standard multi-shot",
        label="Kling O3 Standard · Multi-Shot",
        endpoint="fal-ai/kling-video/o3/standard/text-to-video",
        i2v_endpoint="fal-ai/kling-video/o3/standard/image-to-video",
        max_shots=6,
        min_duration_s=3,
        max_duration_s=15,
        cost_per_second=0.084,
        cost_per_second_audio=0.126,
        default_generate_audio=False,
        i2v_image_param="image_url",
        i2v_accepts_aspect=False,
        multi_prompt_max_chars=512,
        supports_kling_elements=False,
        supports_scene_image_ref=False,
        max_unique_refs=7,
        ref_budget_mode="kling_element",
        notes=(
            "Kling O3 Standard multi-shot — single image_url; Scene text-only. "
            "multi_prompt ≤512/shot."
        ),
    ),
    "grok imagine 1.5 director": DirectorModelSpec(
        key="grok imagine 1.5 director",
        label="Grok Imagine 1.5 · Reference storyboard",
        endpoint="xai/grok-imagine-video/v1.5/reference-to-video",
        i2v_endpoint="xai/grok-imagine-video/v1.5/image-to-video",
        t2v_endpoint="xai/grok-imagine-video/v1.5/text-to-video",
        max_shots=7,
        min_duration_s=1,
        max_duration_s=15,
        allowed_durations=tuple(range(1, 16)),
        default_duration_s=8,
        aspect_choices=("16:9", "4:3", "3:2", "1:1", "2:3", "3:4", "9:16"),
        default_aspect="16:9",
        cost_per_second=0.08,
        cost_per_second_audio=None,
        cost_per_second_by_resolution={"480p": 0.08, "720p": 0.14, "1080p": 0.25},
        cost_fixed_per_ref=0.01,
        resolution_choices=("480p", "720p", "1080p"),
        default_resolution="720p",
        supports_audio=False,  # native audio always
        default_generate_audio=False,
        multi_prompt_max_chars=None,  # single prompt, not Kling multi_prompt
        supports_scene_image_ref=True,  # R2V multi refs — character + scene
        max_unique_refs=7,
        ref_budget_mode="image_bag",
        engine="grok_imagine",
        notes=(
            "Grok Imagine Video 1.5 — Character + Scene as real refs (<IMAGE_n>). "
            "0 refs → T2V; 1 ref → I2V; 2+ refs → R2V. "
            "Est. $0.08–0.25/s by resolution + $0.01/ref."
        ),
    ),
}

# Seedance / Wan / MiniMax H3 remain single-clip Vision/Studio models — they do not
# expose Kling-style multi_prompt storyboard APIs, so they stay out of DIRECTOR_MODELS.

CAMERA_PRESETS: tuple[str, ...] = (
    "Push in",
    "Pull out",
    "Orbit",
    "Crane up",
    "Crane down",
    "Static",
    "Pan left",
    "Pan right",
    "Tilt up",
    "Tilt down",
    "Handheld",
)

CAMERA_PROMPT_LANG: dict[str, str] = {
    "Push in": "slow push-in camera move",
    "Pull out": "slow pull-out / reveal camera move",
    "Orbit": "gentle orbit around the subject",
    "Crane up": "crane up rising camera move",
    "Crane down": "crane down descending camera move",
    "Static": "locked-off static camera",
    "Pan left": "smooth pan left",
    "Pan right": "smooth pan right",
    "Tilt up": "tilt up",
    "Tilt down": "tilt down",
    "Handheld": "subtle handheld camera energy",
}

STYLE_PACKS: dict[str, str] = {
    "None": "",
    "Cinematic": (
        "Cinematic grade, filmic contrast, shallow depth of field where appropriate, "
        "natural motion blur, production-quality lighting."
    ),
    "Marvel-style": (
        "Blockbuster comic-book cinematic style, bold color accents, dynamic framing, "
        "heroic energy, polished VFX-friendly lighting — not cartoon."
    ),
    "Documentary": (
        "Documentary observational style, natural light, restrained camera, "
        "authentic textures, real-world pacing."
    ),
    "Luxury RE": (
        "Luxury real-estate cinematic: clean architecture lock, warm premium grade, "
        "slow elegant camera, high-end property marketing tone."
    ),
}

# Phase 2 polish (prompt-level; model filter stays multi-shot only)
AUDIO_STYLES: tuple[str, ...] = ("No music", "Soft bed only", "Full score")
# Per-gap (or global default) between Shot N and Shot N+1
TRANSITION_PREFS: tuple[str, ...] = ("Hard cut", "Soft dissolve", "Continuous")
OUTPUT_MODES: tuple[str, ...] = (
    "Single multi-shot clip",
    "Clip pack + shot list",
)

AUDIO_STYLE_LANG: dict[str, str] = {
    "No music": (
        "Audio intent: no music bed — sparse diegetic sound only if needed; "
        "no score or melodic underscore."
    ),
    "Soft bed only": (
        "Audio intent: soft ambient music bed only — restrained, non-melodic-heavy, "
        "supports picture without competing with action."
    ),
    "Full score": (
        "Audio intent: full cinematic score that follows the energy of the shot list "
        "— clear motif, builds and resolves with the picture."
    ),
}

# Global summary language (when all gaps share one mode)
TRANSITION_LANG: dict[str, str] = {
    "Hard cut": "Transitions: hard cuts between shots — clean edit points, no dissolve.",
    "Soft dissolve": (
        "Transitions: soft dissolves / gentle blends between shots where natural."
    ),
    "Continuous": (
        "Transitions: continuous action across shot boundaries — no hard cut; "
        "treat ordered ref stills as motion keyframes through the sequence."
    ),
}

# Language for a single gap (Shot N → Shot N+1), used in brief + multi_prompt
GAP_TRANSITION_LANG: dict[str, str] = {
    "Hard cut": "hard cut — clean edit point into the next shot",
    "Soft dissolve": "soft dissolve / gentle blend into the next shot",
    "Continuous": (
        "continuous action (no cut) — seamless motion; prior and next ref stills "
        "act as motion keyframes"
    ),
}

# Incoming prompt language woven into shot N+1 when gap N→N+1 is set
GAP_INCOMING_PROMPT: dict[str, str] = {
    "Hard cut": "Hard cut from the previous shot — new clear edit beat.",
    "Soft dissolve": "Soft dissolve from the previous shot into this beat.",
    "Continuous": (
        "Continuous action from the previous shot with no cut — keep motion and "
        "subject continuity; use ref stills as motion keyframes into this beat."
    ),
}

ENERGY_CURVE_LANG = (
    "Energy arc: open restrained, build to a mid-piece peak, then resolve cleanly "
    "— do not stay at peak for the whole clip."
)


def normalize_transition(value: str | None) -> str:
    raw = (value or "Hard cut").strip()
    if raw in TRANSITION_PREFS:
        return raw
    # Legacy label from earlier Phase 2
    if raw.lower() in {"match cut", "match-cut"}:
        return "Hard cut"
    return "Hard cut"


# Injected when a character still is bound (image ref on the API request)
CHARACTER_IDENTITY_LOCK = (
    "Same person as the reference character image — identical face, hair, body, and outfit."
)
# Injected when a scene still is bound
SCENE_LOCATION_LOCK = (
    "Setting matches the reference location still — same place, architecture, and environment."
)

# Compact continuity for multi_prompt (fits 512 budget)
_CONT_COMPACT = "Lock: same person, place, time."
_CONTINUE_COMPACT = "Continue same person/place/time."


@dataclass
class DirectorShot:
    """One ordered shot row."""

    start_s: float = 0.0
    end_s: float = 5.0
    camera: str = "Push in"
    action: str = ""
    # Manual one-off still (optional; not a library Character/Scene)
    ref_path: str | None = None
    # Bound saved character still (real image ref — not text-only)
    character_path: str | None = None
    character_label: str | None = None
    character_id: str | None = None
    # Extra identity angles (Side / Close-up) when pack has them
    character_extra_paths: tuple[str, ...] = ()
    # Bound saved scene / variation still (location)
    scene_path: str | None = None
    scene_label: str | None = None
    scene_id: str | None = None
    # Extra scene angles (Angle B / C) when full scene pack is on
    scene_extra_paths: tuple[str, ...] = ()
    # Text location when model cannot take scene as image ref (e.g. Kling O3).
    # Keep separate from action (character action only).
    location_text: str = ""

    @property
    def duration_s(self) -> float:
        return max(0.0, float(self.end_s) - float(self.start_s))

    def has_character_bind(self) -> bool:
        p = (self.character_path or "").strip()
        return bool(p and Path(p).is_file())

    def has_scene_bind(self) -> bool:
        p = (self.scene_path or "").strip()
        return bool(p and Path(p).is_file())

    def has_scene_ref(self) -> bool:
        """Library scene bind or manual ref distinct from character."""
        if self.has_scene_bind():
            return True
        p = (self.ref_path or "").strip()
        if not p or not Path(p).is_file():
            return False
        if self.has_character_bind():
            try:
                return Path(p).resolve() != Path(self.character_path or "").resolve()
            except OSError:
                return p != self.character_path
        if self.has_scene_bind():
            try:
                return Path(p).resolve() != Path(self.scene_path or "").resolve()
            except OSError:
                return p != self.scene_path
        return True

    def has_any_still(self) -> bool:
        return (
            self.has_character_bind()
            or self.has_scene_bind()
            or bool(self.ref_path and Path(self.ref_path).is_file())
        )

    def location_still_path(self) -> str | None:
        """Best location plate: library scene, else manual ref if not the character."""
        if self.has_scene_bind():
            return str(Path(self.scene_path).resolve())  # type: ignore[arg-type]
        if self.has_scene_ref() and self.ref_path:
            try:
                return str(Path(self.ref_path).resolve())
            except OSError:
                return self.ref_path
        return None


@dataclass
class DirectorPolish:
    """Optional Director Phase 2 controls (prompt / Enhance context)."""

    audio_style: str = "Soft bed only"
    sfx_note: str = ""
    same_character: bool = True
    same_location: bool = True
    same_time_of_day: bool = True
    # Global default applied to new gaps / "apply to all"
    transition: str = "Hard cut"
    # Per-gap modes between Shot i and Shot i+1 (length = n_shots - 1)
    gap_transitions: list[str] = field(default_factory=list)
    energy_curve: bool = False
    vision_notes: str = ""  # Enhance-only creative notes
    output_mode: str = "Single multi-shot clip"

    def continuity_line(self) -> str:
        bits: list[str] = []
        if self.same_character:
            bits.append("same character(s) locked")
        if self.same_location:
            bits.append("same location / set")
        if self.same_time_of_day:
            bits.append("same time of day / lighting continuity")
        if not bits:
            return ""
        return "Continuity: " + ", ".join(bits) + "."

    def audio_lines(self, *, generate_audio: bool) -> list[str]:
        if not generate_audio:
            return []
        out: list[str] = []
        style = (self.audio_style or "Soft bed only").strip()
        lang = AUDIO_STYLE_LANG.get(style) or AUDIO_STYLE_LANG["Soft bed only"]
        out.append(lang)
        sfx = (self.sfx_note or "").strip()
        if sfx:
            out.append(f"SFX notes: {sfx}")
        return out

    def gap_at(self, gap_index: int) -> str:
        """Transition mode for gap after shot ``gap_index`` (0 = between 1 and 2)."""
        if 0 <= gap_index < len(self.gap_transitions):
            return normalize_transition(self.gap_transitions[gap_index])
        return normalize_transition(self.transition)

    def transition_line(self) -> str:
        """Single summary line (global or mixed per-gap)."""
        if not self.gap_transitions:
            key = normalize_transition(self.transition)
            return TRANSITION_LANG.get(key) or TRANSITION_LANG["Hard cut"]
        keys = [self.gap_at(i) for i in range(len(self.gap_transitions))]
        if keys and all(k == keys[0] for k in keys):
            return TRANSITION_LANG.get(keys[0]) or TRANSITION_LANG["Hard cut"]
        parts = [
            f"shots {i + 1}→{i + 2}: {self.gap_at(i)}"
            for i in range(len(self.gap_transitions))
        ]
        return "Transitions: " + "; ".join(parts) + "."

    def gap_lines(self) -> list[str]:
        """Per-gap lines for assembled brief / Enhance."""
        if not self.gap_transitions:
            key = normalize_transition(self.transition)
            short = GAP_TRANSITION_LANG.get(key) or GAP_TRANSITION_LANG["Hard cut"]
            return [f"Default transition (all gaps): {short}."]
        lines: list[str] = []
        for i in range(len(self.gap_transitions)):
            key = self.gap_at(i)
            short = GAP_TRANSITION_LANG.get(key) or GAP_TRANSITION_LANG["Hard cut"]
            lines.append(f"Between Shot {i + 1} and Shot {i + 2}: {short}.")
        return lines

    def prompt_blocks(self, *, generate_audio: bool = False) -> list[str]:
        """Blocks woven into master / multi_prompt (not raw vision notes)."""
        blocks: list[str] = []
        cont = self.continuity_line()
        if cont:
            blocks.append(cont)
        blocks.append(self.transition_line())
        if self.energy_curve:
            blocks.append(ENERGY_CURVE_LANG)
        blocks.extend(self.audio_lines(generate_audio=generate_audio))
        return blocks

    def wants_shot_list_sidecar(self) -> bool:
        return (self.output_mode or "").strip() == "Clip pack + shot list"


def director_model_labels() -> list[str]:
    return [s.label for s in DIRECTOR_MODELS.values()]


def find_director_model(label_or_key: str | None) -> DirectorModelSpec | None:
    if not label_or_key:
        return None
    raw = label_or_key.strip().lower()
    if raw in DIRECTOR_MODELS:
        return DIRECTOR_MODELS[raw]
    for spec in DIRECTOR_MODELS.values():
        if spec.label.lower() == raw or spec.key == raw:
            return spec
    return None


def default_director_model() -> DirectorModelSpec:
    return DIRECTOR_MODELS["kling v3 pro multi-shot"]


def coerce_director_aspect_token(raw: str | None) -> str | None:
    """
    Normalize UI aspect to an API enum token, or None for Auto/omit.

    Strips spaces, maps fullwidth colon, drops Auto labels.
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if s.lower() in _ASPECT_AUTO_LABELS or s.lower().startswith("auto"):
        return None
    s = s.replace("：", ":").replace("／", "/").replace(" ", "")
    # Some UIs use 16x9
    if "x" in s.lower() and ":" not in s:
        parts = s.lower().split("x", 1)
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            s = f"{parts[0]}:{parts[1]}"
    return s or None


def director_aspect_ui_choices(
    spec: DirectorModelSpec,
    *,
    has_start_image: bool,
) -> tuple[list[str], str]:
    """
    Dropdown options + default for the selected model / path.

    Kling multi-shot I2V (any shot ref): only Auto — API has no aspect_ratio.
    T2V / models that accept aspect: exact enum list from the model.
    """
    uses_i2v = bool(
        has_start_image
        and spec.i2v_endpoint
        and (getattr(spec, "engine", None) or "kling_multi") == "kling_multi"
    )
    if uses_i2v and not bool(getattr(spec, "i2v_accepts_aspect", False)):
        return [ASPECT_AUTO_FROM_STILL], ASPECT_AUTO_FROM_STILL
    choices = [c for c in (spec.aspect_choices or ()) if c]
    if not choices:
        choices = ["16:9"]
    default = (spec.default_aspect or choices[0]).strip()
    if default not in choices:
        default = choices[0]
    return list(choices), default


def resolve_director_aspect_for_api(
    spec: DirectorModelSpec,
    aspect_ratio: str | None,
    *,
    has_start_image: bool,
) -> tuple[str | None, str]:
    """
    Map UI aspect to API value (or None to omit).

    Returns (api_value_or_None, note).
    """
    uses_i2v = bool(has_start_image and spec.i2v_endpoint)
    is_kling = (getattr(spec, "engine", None) or "kling_multi") == "kling_multi"

    if uses_i2v and is_kling and not bool(getattr(spec, "i2v_accepts_aspect", False)):
        return None, "I2V multi-shot: aspect omitted (follows start still)."

    if uses_i2v and not is_kling and not bool(getattr(spec, "i2v_accepts_aspect", False)):
        # Grok I2V also has no aspect_ratio in schema
        return None, "I2V: aspect omitted (follows start still)."

    token = coerce_director_aspect_token(aspect_ratio)
    allowed = tuple(spec.aspect_choices or ())
    if not allowed:
        return None, "No aspect enum for this model; omitting aspect_ratio."

    if token is None:
        # Auto on T2V → model default
        chosen = (spec.default_aspect or allowed[0]).strip()
        if chosen not in allowed:
            chosen = allowed[0]
        return chosen, f"aspect_ratio Auto → {chosen} (model default)."

    if token in allowed:
        return token, f"aspect_ratio={token!r}."

    # Fuzzy match e.g. 16/9
    soft = token.replace("/", ":")
    if soft in allowed:
        return soft, f"aspect_ratio {token!r} → {soft}."

    # Fall back to default rather than send an invalid enum
    chosen = (spec.default_aspect or allowed[0]).strip()
    if chosen not in allowed:
        chosen = allowed[0]
    return (
        chosen,
        f"aspect_ratio {token!r} not in {list(allowed)}; using {chosen}.",
    )


def director_accepted_aspects_label(
    spec: DirectorModelSpec,
    *,
    has_start_image: bool,
) -> str:
    """Human list of what this endpoint path accepts (for error text)."""
    uses_i2v = bool(has_start_image and spec.i2v_endpoint)
    is_kling = (getattr(spec, "engine", None) or "kling_multi") == "kling_multi"
    if uses_i2v and is_kling and not bool(getattr(spec, "i2v_accepts_aspect", False)):
        return "none (I2V derives frame size from the start still — do not send aspect_ratio)"
    if uses_i2v and not bool(getattr(spec, "i2v_accepts_aspect", False)):
        return "none (I2V derives frame size from the start still)"
    allowed = list(spec.aspect_choices or ())
    if not allowed:
        return "none"
    return ", ".join(allowed)


def estimate_director_cost(
    spec: DirectorModelSpec,
    *,
    duration_s: float,
    generate_audio: bool = False,
    resolution: str | None = None,
    num_refs: int = 0,
) -> float:
    rate = spec.cost_per_second
    if generate_audio and spec.cost_per_second_audio is not None:
        rate = spec.cost_per_second_audio
    by_res = getattr(spec, "cost_per_second_by_resolution", None) or {}
    if by_res:
        res = (resolution or spec.default_resolution or "720p").strip().lower()
        rate = by_res.get(res, rate)
    secs = max(1.0, float(duration_s or spec.default_duration_s))
    total = (rate or 0.0) * secs
    fixed = float(getattr(spec, "cost_fixed_per_ref", 0) or 0)
    if fixed and num_refs > 0:
        total += fixed * int(num_refs)
    return round(total, 3)


def format_director_cost(
    spec: DirectorModelSpec,
    *,
    duration_s: float,
    generate_audio: bool = False,
    resolution: str | None = None,
    num_refs: int = 0,
) -> str:
    from media_studio.pricing import format_job_cost

    amt = estimate_director_cost(
        spec,
        duration_s=duration_s,
        generate_audio=generate_audio,
        resolution=resolution,
        num_refs=num_refs,
    )
    secs = int(round(float(duration_s or 0)))
    unit = f"{secs}s"
    if num_refs:
        unit = f"{secs}s · {num_refs} ref"
    return format_job_cost(amt, unit=unit, model=spec.label)


def balance_shot_times(
    n_shots: int,
    total_duration_s: float,
) -> list[tuple[float, float]]:
    """
    Evenly split total duration into contiguous non-overlapping ranges.

    Prefer whole-second lengths (API multi_prompt uses integer seconds).
    e.g. 10s / 5 shots → (0,2), (2,4), (4,6), (6,8), (8,10).
    """
    n = max(1, int(n_shots))
    total = max(float(n), float(total_duration_s or 0))
    total_i = max(n, int(round(total)))
    base = total_i // n
    rem = total_i % n
    ranges: list[tuple[float, float]] = []
    t = 0
    for i in range(n):
        dur = base + (1 if i < rem else 0)
        if dur < 1:
            dur = 1
        ranges.append((float(t), float(t + dur)))
        t += dur
    # Ensure last end lands on total_i (contiguous cover)
    if ranges:
        s0, _ = ranges[-1]
        ranges[-1] = (s0, float(total_i))
    return ranges


def format_shot_length_label(index: int, start_s: float, end_s: float) -> str:
    """e.g. ``Shot 3 · 2.0s``."""
    try:
        dur = max(0.0, float(end_s) - float(start_s))
    except (TypeError, ValueError):
        dur = 0.0
    return f"Shot {int(index) + 1} · {dur:.1f}s"


def per_shot_timing_errors(
    shots: list[DirectorShot],
    *,
    total_duration_s: float,
    allow_overlap: bool = False,
) -> list[list[str]]:
    """
    Per-shot timing issues for live UI (red on bad shot).

    Returns a list of error strings per shot index (empty = ok for that shot).
    Gaps between shots are allowed (user choice); overlaps and out-of-range warn.
    """
    total = float(total_duration_s or 0)
    n = len(shots)
    out: list[list[str]] = [[] for _ in range(n)]
    if total < 1 or n == 0:
        return out
    starts_ends: list[tuple[int, float, float] | None] = []
    for i, sh in enumerate(shots):
        try:
            a = float(sh.start_s)
            b = float(sh.end_s)
        except (TypeError, ValueError):
            out[i].append("start/end must be numbers")
            starts_ends.append(None)
            continue
        starts_ends.append((i, a, b))
        if a < -0.01:
            out[i].append("start before 0")
        if b > total + 0.01:
            out[i].append(f"end past total ({total:g}s)")
        if b <= a + 0.01:
            out[i].append("end must be after start")
        elif (b - a) < 0.99:
            out[i].append("need ≥1s")
    if not allow_overlap and n >= 2:
        ordered = sorted(
            [x for x in starts_ends if x is not None],
            key=lambda t: (t[1], t[2]),
        )
        for j in range(1, len(ordered)):
            i_prev, a0, b0 = ordered[j - 1]
            i_cur, a1, b1 = ordered[j]
            if a1 < b0 - 0.01:
                msg = f"overlaps Shot {i_prev + 1}"
                out[i_cur].append(msg)
                out[i_prev].append(f"overlaps Shot {i_cur + 1}")
    return out


def validate_shots(
    shots: list[DirectorShot],
    *,
    total_duration_s: float,
    max_shots: int = 6,
    allow_overlap: bool = False,
    polish: DirectorPolish | None = None,
) -> list[str]:
    """Return human-readable errors (empty = valid)."""
    errors: list[str] = []
    total = float(total_duration_s or 0)
    if total < 1:
        errors.append("Set total duration first (master block).")
        return errors
    if not shots:
        errors.append("Add at least one shot.")
        return errors
    if len(shots) > max_shots:
        errors.append(f"This model allows at most {max_shots} shots.")
    per = per_shot_timing_errors(
        shots, total_duration_s=total, allow_overlap=allow_overlap
    )
    for i, msgs in enumerate(per):
        n = i + 1
        for m in msgs:
            if m.startswith("overlaps"):
                # Deduplicate pair messages below
                continue
            errors.append(f"Shot {n}: {m}.")
    if not allow_overlap and len(shots) >= 2:
        ordered = sorted(
            enumerate(shots),
            key=lambda pair: (float(pair[1].start_s), float(pair[1].end_s)),
        )
        seen_pairs: set[tuple[int, int]] = set()
        for j in range(1, len(ordered)):
            i_prev, prev = ordered[j - 1]
            i_cur, cur = ordered[j]
            if float(cur.start_s) < float(prev.end_s) - 0.01:
                pair = (min(i_prev, i_cur), max(i_prev, i_cur))
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                errors.append(
                    f"Shots {i_prev + 1} and {i_cur + 1} overlap "
                    f"({prev.start_s:g}–{prev.end_s:g}s vs {cur.start_s:g}–{cur.end_s:g}s). "
                    "Ranges must not overlap."
                )
    for i, sh in enumerate(shots):
        n = i + 1
        if not (sh.action or "").strip():
            errors.append(f"Shot {n}: enter a per-shot action prompt.")
    # Sum of shot lengths should not exceed total (API multi_prompt durations sum)
    shot_sum = sum(max(0.0, float(s.end_s) - float(s.start_s)) for s in shots)
    if shot_sum > total + 0.51:
        errors.append(
            f"Shot lengths sum to {shot_sum:.0f}s but total duration is {total:.0f}s. "
            "Shorten shots or raise total duration."
        )
    # Continuous gaps: still need valid ordered times (above) + ref stills as keyframes
    if polish is not None and len(shots) >= 2:
        n_gaps = len(shots) - 1
        for g in range(n_gaps):
            mode = polish.gap_at(g)
            if mode != "Continuous":
                continue
            a, b = shots[g], shots[g + 1]
            if not a.has_any_still():
                errors.append(
                    f"Continuous between Shot {g + 1} and {g + 2}: "
                    f"assign a ref still or character on Shot {g + 1} (motion keyframe)."
                )
            if not b.has_any_still():
                errors.append(
                    f"Continuous between Shot {g + 1} and {g + 2}: "
                    f"assign a ref still or character on Shot {g + 2} (motion keyframe)."
                )
    return errors


def location_text_from_scene(
    *,
    scene_id: str | None = None,
    scene_label: str | None = None,
    notes: str | None = None,
) -> str:
    """
    Build editable location text from a saved scene (name + short notes).
    Used when the model cannot bind scene as an image ref.
    """
    name = (scene_label or "").strip()
    note = (notes or "").strip()
    # Prefer store lookup for fresh name/notes
    if scene_id:
        try:
            from media_studio.scene_store import find_scene

            s = find_scene(scene_id)
            if s is not None:
                name = (s.display_name() or s.name or name).strip()
                if not note:
                    note = (s.notes or "").strip()
        except Exception:
            pass
    # Drop huge T2I prompt dumps from notes
    if len(note) > 180:
        note = note[:177].rstrip() + "…"
    if name and note:
        # Avoid duplicating name if notes already start with it
        if note.lower().startswith(name.lower()[: min(20, len(name))]):
            return note
        return f"{name}. {note}"
    return name or note


def assemble_shot_prompt(
    shot: DirectorShot,
    *,
    index: int,
    style_pack: str | None = None,
    compact: bool = False,
    include_identity: bool = True,
    scene_as_image_ref: bool = True,
) -> str:
    """
    One multi_prompt element text (camera + action [+ identity/location]).

    Action stays character action only. Location comes from:
    - image lock language when scene is a real image ref, or
    - ``location_text`` when the model is single-ref (describe place in text).
    """
    cam = CAMERA_PROMPT_LANG.get(shot.camera, shot.camera or "camera move")
    action = (shot.action or "").strip()
    loc_text = (shot.location_text or "").strip()
    if compact:
        bits = [f"{cam}."]
    else:
        bits = [f"Camera: {cam}."]
    if action:
        bits.append(action if action.endswith(".") else f"{action}.")
    if include_identity and shot.has_character_bind():
        name = (shot.character_label or "").strip()
        if name:
            bits.append(
                f"Same person as {name} reference image — identical face, hair, body, and outfit."
            )
        else:
            bits.append(CHARACTER_IDENTITY_LOCK)
    has_scene_image = bool(
        scene_as_image_ref
        and (
            shot.has_scene_bind()
            or (shot.location_still_path() and shot.has_scene_ref())
        )
    )
    if has_scene_image:
        loc = (shot.scene_label or "").strip()
        if loc:
            bits.append(
                f"Location matches {loc} reference still — same place and environment."
            )
        else:
            bits.append(SCENE_LOCATION_LOCK)
    elif loc_text:
        # Text-only location (single-ref models) — not merged into action
        loc_clean = loc_text.rstrip().rstrip(".")
        if compact:
            if loc_clean.lower().startswith("at "):
                bits.append(f"{loc_clean}.")
            else:
                bits.append(f"At {loc_clean}.")
        else:
            bits.append(f"Location: {loc_clean}.")
    # Style pack is mainly on master; light echo only if set and not compact
    if not compact:
        style = (STYLE_PACKS.get(style_pack or "None") or "").strip()
        if style and index == 0:
            bits.append(style)
    return " ".join(bits).strip()


def expand_master_with_polish(
    master: str,
    polish: DirectorPolish | None = None,
    *,
    generate_audio: bool = False,
) -> str:
    """Master text + Phase 2 continuity / transition / energy / audio blocks."""
    m = (master or "").strip()
    if polish is None:
        return m
    blocks = polish.prompt_blocks(generate_audio=generate_audio)
    if not blocks:
        return m
    extra = " ".join(blocks)
    if not m:
        return extra
    return f"{m.rstrip('.')}. {extra}".strip()


def _squash_ws(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def clamp_prompt_chars(text: str, max_chars: int) -> str:
    """Hard clamp to max_chars (ellipsis if truncated)."""
    t = _squash_ws(text)
    if max_chars <= 0:
        return ""
    if len(t) <= max_chars:
        return t
    if max_chars <= 1:
        return t[:max_chars]
    return t[: max_chars - 1].rstrip(" .,;:") + "…"


def compact_master_for_multi(master: str, *, budget: int = 160) -> str:
    """
    Strip fluff from master for multi_prompt shot 0.
    Keep identity + location + core story; drop long style essays.
    """
    m = _squash_ws(master)
    if not m:
        return ""
    # Drop common verbose lead-ins
    m = re.sub(
        r"^(please |make sure |ensure that |the video should |create a )+",
        "",
        m,
        flags=re.I,
    )
    # Prefer first 1–2 sentences within budget
    parts = re.split(r"(?<=[.!?])\s+", m)
    out: list[str] = []
    for p in parts:
        cand = _squash_ws(" ".join(out + [p]))
        if len(cand) <= budget:
            out.append(p)
        else:
            break
    if out:
        return clamp_prompt_chars(" ".join(out), budget)
    return clamp_prompt_chars(m, budget)


def still_image_size(path: str | Path | None) -> tuple[int, int] | None:
    """(width, height) or None if unreadable."""
    if not path:
        return None
    try:
        p = Path(path)
        if not p.is_file():
            return None
        from PIL import Image

        with Image.open(p) as im:
            w, h = im.size
            return int(w), int(h)
    except Exception:
        return None


def still_is_low_res(path: str | Path | None, *, min_edge: int = 512) -> bool:
    """True if shortest edge is below min_edge (or unreadable treated as not low)."""
    sz = still_image_size(path)
    if not sz:
        return False
    return min(sz) < min_edge


def preferred_character_still_bundle(
    char_id: str | None = None,
    *,
    still_path: str | None = None,
) -> dict[str, Any]:
    """
    Resolve best character still for Director binding.

    Front preferred; among pack, prefer higher-res Front if multiple paths.
    Returns keys: path, label, id, extras (other angles), low_res (bool).
    """
    out: dict[str, Any] = {
        "path": None,
        "label": None,
        "id": char_id,
        "extras": [],
        "low_res": False,
    }
    try:
        from media_studio.character_store import find_picker_choice, load_characters
    except Exception:
        if still_path and Path(still_path).is_file():
            out["path"] = str(Path(still_path).resolve())
            out["low_res"] = still_is_low_res(out["path"])
        return out

    entry = None
    if char_id:
        for c in load_characters():
            if c.id == char_id:
                entry = c
                break
    if entry is None and still_path:
        # Match by primary path
        try:
            target = str(Path(still_path).resolve())
        except OSError:
            target = still_path
        for c in load_characters():
            for s in c.all_stills():
                try:
                    if str(Path(s).resolve()) == target:
                        entry = c
                        break
                except OSError:
                    if s == still_path:
                        entry = c
                        break
            if entry:
                break

    if entry is not None:
        primary = entry.primary_still()
        # Prefer highest-res Front if pack has front; else largest available
        pack = entry.normalized_identity()
        front = pack.get("front") or primary
        chosen = front or primary
        # If front missing, pick largest still
        if not chosen:
            best_px = -1
            for s in entry.all_stills():
                sz = still_image_size(s)
                px = (sz[0] * sz[1]) if sz else 0
                if px > best_px and Path(s).is_file():
                    best_px = px
                    chosen = s
        extras: list[str] = []
        for s in entry.all_stills():
            if not s or not Path(s).is_file():
                continue
            try:
                if chosen and Path(s).resolve() == Path(chosen).resolve():
                    continue
            except OSError:
                if s == chosen:
                    continue
            extras.append(str(Path(s).resolve()))
        # Prefer parent name / costume label via picker
        label = entry.name
        try:
            ch = find_picker_choice(entry.id)
            if ch:
                label = ch.label
        except Exception:
            pass
        out["path"] = str(Path(chosen).resolve()) if chosen and Path(chosen).is_file() else None
        out["label"] = label
        out["id"] = entry.id
        out["extras"] = extras[:3]
        out["low_res"] = still_is_low_res(out["path"])
        return out

    if still_path and Path(still_path).is_file():
        out["path"] = str(Path(still_path).resolve())
        out["low_res"] = still_is_low_res(out["path"])
    return out


def assemble_director_brief(
    *,
    master: str,
    shots: list[DirectorShot],
    style_pack: str | None = None,
    polish: DirectorPolish | None = None,
    generate_audio: bool = False,
) -> str:
    """
    Human-readable assembled brief (Enhance / history / display).

    Master context + ordered Shot N (t0–t1, camera): …
    """
    lines: list[str] = []
    m = (master or "").strip()
    if m:
        lines.append(f"Master: {m}")
    style = (STYLE_PACKS.get(style_pack or "None") or "").strip()
    if style:
        lines.append(f"Style pack: {style}")
    if polish is not None:
        # Continuity / energy / audio without repeating every gap (gaps sit between shots)
        cont = polish.continuity_line()
        if cont:
            lines.append(cont)
        if polish.energy_curve:
            lines.append(ENERGY_CURVE_LANG)
        for al in polish.audio_lines(generate_audio=generate_audio):
            lines.append(al)
        vn = (polish.vision_notes or "").strip()
        if vn:
            lines.append(f"Vision notes (Enhance): {vn}")
        # If only one shot, still note default transition once
        if len(shots) < 2:
            lines.append(polish.transition_line())
    for i, sh in enumerate(shots):
        cam = sh.camera or "Static"
        t0 = float(sh.start_s)
        t1 = float(sh.end_s)
        action = (sh.action or "").strip() or "(no action)"
        loc = (sh.location_text or "").strip()
        line = f"Shot {i + 1} ({t0:g}–{t1:g}s, {cam}): {action}"
        if loc:
            line += f" | Location: {loc}"
        lines.append(line)
        # Per-gap transition line after each shot except the last
        if polish is not None and i < len(shots) - 1:
            key = polish.gap_at(i)
            short = GAP_TRANSITION_LANG.get(key) or GAP_TRANSITION_LANG["Hard cut"]
            lines.append(f"  → {key} into Shot {i + 2}: {short}")
    return "\n".join(lines).strip()


def multi_prompt_from_shots(
    shots: list[DirectorShot],
    *,
    style_pack: str | None = None,
    master: str | None = None,
    polish: DirectorPolish | None = None,
    generate_audio: bool = False,
    max_chars: int | None = 512,
    force_compact: bool | None = None,
    scene_as_image_ref: bool = True,
) -> list[dict[str, str]]:
    """
    fal multi_prompt payload: [{prompt, duration}, …].

    Duration is integer seconds (shot length), string enum for API.
    When ``max_chars`` is set (Kling 512), uses compact continuity + short master
    and clamps each prompt. Character-bound shots get identity lock language.
    ``scene_as_image_ref=False`` (e.g. Kling O3): use location_text, not image lock.
    """
    limit = int(max_chars) if max_chars and max_chars > 0 else None
    # Auto-compact whenever a hard limit exists
    compact = bool(force_compact) if force_compact is not None else bool(limit)

    if compact:
        master_txt = compact_master_for_multi(master or "", budget=160)
        # Respect Same character / location / time toggles (multi-character across shots)
        lock_bits: list[str] = []
        cont_bits2: list[str] = []
        if polish is None or polish.same_character:
            lock_bits.append("person")
            cont_bits2.append("person")
        if polish is None or polish.same_location:
            lock_bits.append("place")
            cont_bits2.append("place")
        if polish is None or polish.same_time_of_day:
            lock_bits.append("time")
            cont_bits2.append("time")
        if lock_bits:
            cont_short = f"Lock: same {'/'.join(lock_bits)}."
            continue_line = f"Continue same {'/'.join(cont_bits2)}."
        else:
            cont_short = "New setup."
            continue_line = "Next shot."
        # Light audio hint only if generating and room exists later
        if generate_audio and polish is not None:
            style = (polish.audio_style or "").strip()
            if style and style.lower() not in ("no music", "none"):
                # Keep very short — may be dropped by clamp
                master_txt = clamp_prompt_chars(
                    f"{master_txt} Audio: {style}.".strip(), 180
                )
    else:
        master_txt = expand_master_with_polish(
            master or "", polish, generate_audio=generate_audio
        )
        cont = (
            polish.continuity_line()
            if polish
            else "Continuity: same location, characters, and overall tone across all shots."
        )
        cont_short = cont or "Keep overall tone continuous across shots."
        cont_bits: list[str] = []
        if polish is None or polish.same_character:
            cont_bits.append("characters")
        if polish is None or polish.same_location:
            cont_bits.append("scene")
        if polish is None or polish.same_time_of_day:
            cont_bits.append("time of day")
        continue_line = (
            f"Continue the same {' / '.join(cont_bits)}."
            if cont_bits
            else "Continue the sequence."
        )

    out: list[dict[str, str]] = []
    for i, sh in enumerate(shots):
        body = assemble_shot_prompt(
            sh,
            index=i,
            style_pack=style_pack,
            compact=compact,
            include_identity=True,
            scene_as_image_ref=scene_as_image_ref,
        )
        if i == 0:
            if master_txt:
                prompt = f"{master_txt.rstrip('.')}. {cont_short} {body}"
            else:
                prompt = f"{cont_short} {body}" if cont_short else body
        else:
            gap_key = polish.gap_at(i - 1) if polish else "Hard cut"
            gap_lang = GAP_INCOMING_PROMPT.get(gap_key) or GAP_INCOMING_PROMPT["Hard cut"]
            if compact:
                # Shorter gap bridge
                short_gap = {
                    "Hard cut": "Cut.",
                    "Soft dissolve": "Soft dissolve.",
                    "Continuous": "Continuous action.",
                }.get(gap_key, "Cut.")
                bridge = f"{short_gap} {continue_line}"
            else:
                bridge = f"{gap_lang} {continue_line}"
            prompt = f"{bridge} {body}"
        prompt = _squash_ws(prompt)
        if limit:
            # Prioritize action + identity: if over, rebuild with tiny master
            if len(prompt) > limit:
                core = assemble_shot_prompt(
                    sh,
                    index=i,
                    style_pack=None,
                    compact=True,
                    include_identity=True,
                    scene_as_image_ref=scene_as_image_ref,
                )
                if i == 0:
                    tiny_m = compact_master_for_multi(master or "", budget=80)
                    prompt = _squash_ws(
                        f"{tiny_m} {_CONT_COMPACT} {core}" if tiny_m else f"{_CONT_COMPACT} {core}"
                    )
                else:
                    prompt = _squash_ws(f"{_CONTINUE_COMPACT} {core}")
            # Last resort: drop identity line then clamp
            if len(prompt) > limit:
                core2 = assemble_shot_prompt(
                    sh,
                    index=i,
                    style_pack=None,
                    compact=True,
                    include_identity=False,
                    scene_as_image_ref=scene_as_image_ref,
                )
                # Keep a short identity tag if character bound
                id_tag = " Same person as ref image." if sh.has_character_bind() else ""
                prompt = clamp_prompt_chars(f"{core2}{id_tag}", limit)
            else:
                prompt = clamp_prompt_chars(prompt, limit)
        dur = max(1, int(round(float(sh.end_s) - float(sh.start_s))))
        dur = min(15, max(1, dur))
        out.append({"prompt": prompt.strip(), "duration": str(dur)})
    return out


def multi_prompt_char_counts(
    shots: list[DirectorShot],
    *,
    master: str | None = None,
    style_pack: str | None = None,
    polish: DirectorPolish | None = None,
    generate_audio: bool = False,
    max_chars: int | None = 512,
    scene_as_image_ref: bool = True,
) -> list[tuple[int, int | None, str]]:
    """
    Per-shot (length, max_or_None, prompt_preview) after compaction rules.
    """
    multi = multi_prompt_from_shots(
        shots,
        style_pack=style_pack,
        master=master,
        polish=polish,
        generate_audio=generate_audio,
        max_chars=max_chars,
        scene_as_image_ref=scene_as_image_ref,
    )
    out: list[tuple[int, int | None, str]] = []
    for m in multi:
        p = m.get("prompt") or ""
        out.append((len(p), max_chars, p[:80]))
    return out


def validate_multi_prompt_limits(
    multi: list[dict[str, str]],
    *,
    max_chars: int | None,
) -> list[str]:
    """Return human errors if any multi_prompt entry exceeds max_chars."""
    if not max_chars or max_chars <= 0:
        return []
    errs: list[str] = []
    for i, m in enumerate(multi):
        p = m.get("prompt") or ""
        n = len(p)
        if n > max_chars:
            errs.append(
                f"Shot {i + 1} prompt is {n} chars (max {max_chars}). "
                "Shorten the master brief or per-shot action."
            )
    return errs


def format_shot_list_text(
    *,
    master: str,
    shots: list[DirectorShot],
    model_label: str | None = None,
    duration_s: float | None = None,
    aspect_ratio: str | None = None,
    polish: DirectorPolish | None = None,
    video_name: str | None = None,
) -> str:
    """Simple shot-list sidecar for Resolve / offline edit."""
    lines: list[str] = [
        "AI Media Studio — Director shot list",
        f"Video: {video_name or '(pending)'}",
    ]
    if model_label:
        lines.append(f"Model: {model_label}")
    if duration_s is not None:
        lines.append(f"Total duration: {float(duration_s):g}s")
    if aspect_ratio:
        lines.append(f"Aspect: {aspect_ratio}")
    if polish is not None:
        lines.append(f"Default transition: {normalize_transition(polish.transition)}")
        lines.append(f"Output mode: {polish.output_mode}")
        cont = polish.continuity_line()
        if cont:
            lines.append(cont)
    lines.append("")
    m = (master or "").strip()
    if m:
        lines.append(f"Master: {m}")
        lines.append("")
    for i, sh in enumerate(shots):
        t0 = float(sh.start_s)
        t1 = float(sh.end_s)
        cam = sh.camera or "Static"
        action = (sh.action or "").strip() or "(no action)"
        ref = Path(sh.ref_path).name if sh.ref_path else "—"
        lines.append(f"Shot {i + 1} ({t0:g}–{t1:g}s) · {cam}")
        lines.append(f"  Action: {action}")
        lines.append(f"  Ref still: {ref}")
        if polish is not None and i < len(shots) - 1:
            lines.append(f"  → Transition into Shot {i + 2}: {polish.gap_at(i)}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_shot_list_sidecar(
    video_path: str | Path,
    *,
    master: str,
    shots: list[DirectorShot],
    model_label: str | None = None,
    duration_s: float | None = None,
    aspect_ratio: str | None = None,
    polish: DirectorPolish | None = None,
) -> str | None:
    """
    Write ``<video_stem>_shots.txt`` next to the multi-shot clip.
    Returns path on success, None on failure.
    """
    vp = Path(video_path)
    if not vp.is_file():
        return None
    text = format_shot_list_text(
        master=master,
        shots=shots,
        model_label=model_label,
        duration_s=duration_s,
        aspect_ratio=aspect_ratio,
        polish=polish,
        video_name=vp.name,
    )
    dest = vp.with_name(f"{vp.stem}_shots.txt")
    try:
        dest.write_text(text, encoding="utf-8")
        return str(dest.resolve())
    except OSError:
        return None


def build_grok_imagine_director_arguments(
    spec: DirectorModelSpec,
    *,
    master: str,
    shots: list[DirectorShot],
    duration_s: int | float,
    aspect_ratio: str | None = None,
    style_pack: str | None = None,
    polish: DirectorPolish | None = None,
    ref_image_urls: list[str] | None = None,
    resolution: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """
    Grok Imagine Video 1.5 Director path: one clip from brief + ordered refs.

    0 refs → T2V · 1 ref → I2V · 2+ refs → R2V with <IMAGE_n> tags.
    """
    brief = assemble_director_brief(
        master=master or "",
        shots=shots,
        style_pack=style_pack,
        polish=polish,
        generate_audio=False,
    )
    prompt = expand_master_with_polish(
        master or "", polish, generate_audio=False
    )
    if brief:
        # Prefer full assembled brief for a single-pass model
        prompt = brief if not prompt else f"{prompt}\n{brief}"
    # Real image refs: identity + location lock language (not text-only "character/scene")
    char_labels = [
        (sh.character_label or "character").strip()
        for sh in shots
        if sh.has_character_bind()
    ]
    scene_labels = [
        (sh.scene_label or "location").strip()
        for sh in shots
        if sh.has_scene_bind()
    ]
    lock_lines: list[str] = []
    if char_labels or any(sh.has_character_bind() for sh in shots):
        names = ", ".join(dict.fromkeys(char_labels)) or "the bound character"
        lock_lines.append(
            f"{CHARACTER_IDENTITY_LOCK} "
            f"Match reference image(s) for {names}; preserve hair, face, body, outfit."
        )
    if scene_labels or any(sh.has_scene_bind() for sh in shots):
        places = ", ".join(dict.fromkeys(scene_labels)) or "the bound location"
        lock_lines.append(
            f"{SCENE_LOCATION_LOCK} "
            f"Match location reference(s) for {places}."
        )
    # Cite ordered refs when multi-image
    urls = [u for u in (ref_image_urls or []) if u]
    if len(urls) >= 2:
        tags = ", ".join(f"<IMAGE_{i}>" for i in range(len(urls)))
        lock_lines.append(
            f"Use {tags} as ordered visual refs (character identity and/or location plates)."
        )
    if lock_lines:
        prompt = f"{(prompt or '').rstrip()}\n" + "\n".join(lock_lines)
    prompt = (prompt or "").strip()
    if not prompt:
        raise ValueError("Enter a master brief or shot actions for Grok Imagine Director.")

    try:
        total = int(round(float(duration_s)))
    except (TypeError, ValueError):
        total = int(spec.default_duration_s)
    total = max(spec.min_duration_s, min(spec.max_duration_s, total))

    urls = [u for u in (ref_image_urls or []) if u][: max(1, int(spec.max_shots or 7))]
    res = (resolution or spec.default_resolution or "720p").strip()
    if spec.resolution_choices and res not in spec.resolution_choices:
        res = spec.default_resolution or "720p"

    if len(urls) >= 2:
        endpoint = spec.endpoint  # reference-to-video
        # R2V: 480p/720p only on fal
        if res not in ("480p", "720p"):
            res = "720p" if res == "1080p" else (spec.default_resolution or "480p")
            if res not in ("480p", "720p"):
                res = "480p"
        tags = ", ".join(f"<IMAGE_{i}>" for i in range(len(urls)))
        if "<image_0>" not in prompt.lower():
            prompt = (
                prompt.rstrip(".")
                + f". Use {tags} as ordered visual keyframes / style refs "
                f"matching Shot 1…{len(urls)}."
            )
        ar, _note = resolve_director_aspect_for_api(
            spec, aspect_ratio, has_start_image=False
        )
        args: dict[str, Any] = {
            "prompt": prompt,
            "reference_image_urls": urls,
            "duration": total,
            "resolution": res,
        }
        if ar and (spec.aspect_param or "aspect_ratio"):
            args[spec.aspect_param or "aspect_ratio"] = ar
        return endpoint, args

    if len(urls) == 1:
        endpoint = spec.i2v_endpoint or spec.endpoint
        # Grok I2V: image_url only — no aspect_ratio in OpenAPI
        args = {
            "prompt": prompt,
            "image_url": urls[0],
            "duration": total,
            "resolution": res if res in ("480p", "720p", "1080p") else "720p",
        }
        return endpoint, args

    # No refs — pure T2V
    endpoint = spec.t2v_endpoint or spec.endpoint
    ar, _note = resolve_director_aspect_for_api(
        spec, aspect_ratio, has_start_image=False
    )
    args = {
        "prompt": prompt,
        "duration": total,
        "resolution": res if res in ("480p", "720p", "1080p") else "720p",
    }
    if ar and (spec.aspect_param or "aspect_ratio"):
        args[spec.aspect_param or "aspect_ratio"] = ar
    return endpoint, args


def build_director_arguments(
    spec: DirectorModelSpec,
    *,
    master: str,
    shots: list[DirectorShot],
    duration_s: int | float,
    aspect_ratio: str | None = None,
    style_pack: str | None = None,
    generate_audio: bool | None = None,
    start_image_url: str | None = None,
    negative_prompt: str | None = None,
    polish: DirectorPolish | None = None,
    ref_image_urls: list[str] | None = None,
    resolution: str | None = None,
    # Kling V3 I2V character binding
    elements: list[dict[str, Any]] | None = None,
) -> tuple[str, dict[str, Any]]:
    """
    Returns (endpoint, arguments) for fal subscribe.

    Kling: multi_prompt + shot_type=customize (≤512 chars/shot when limited).
    Grok Imagine: single clip T2V / I2V / R2V from shot refs.

    Kling I2V OpenAPI has no aspect_ratio (frame follows start still).
    O3 I2V uses image_url; V3 I2V uses start_image_url + optional elements.
    """
    if (getattr(spec, "engine", None) or "kling_multi") == "grok_imagine":
        return build_grok_imagine_director_arguments(
            spec,
            master=master,
            shots=shots,
            duration_s=duration_s,
            aspect_ratio=aspect_ratio,
            style_pack=style_pack,
            polish=polish,
            ref_image_urls=ref_image_urls,
            resolution=resolution,
        )

    use_audio = (
        bool(generate_audio)
        if generate_audio is not None
        else bool(spec.default_generate_audio)
    )
    if not spec.supports_audio:
        use_audio = False
    max_chars = getattr(spec, "multi_prompt_max_chars", None)
    multi = multi_prompt_from_shots(
        shots,
        style_pack=style_pack,
        master=master,
        polish=polish,
        generate_audio=use_audio,
        max_chars=max_chars,
        scene_as_image_ref=bool(getattr(spec, "supports_scene_image_ref", False)),
    )
    if not multi:
        raise ValueError("At least one shot is required.")
    limit_errs = validate_multi_prompt_limits(multi, max_chars=max_chars)
    if limit_errs:
        raise ValueError(" · ".join(limit_errs))

    total = sum(int(m["duration"]) for m in multi)
    total = max(spec.min_duration_s, min(spec.max_duration_s, total))
    # Prefer user total if valid and ≥ shot sum
    try:
        user_total = int(round(float(duration_s)))
    except (TypeError, ValueError):
        user_total = total
    if user_total >= total:
        total = max(spec.min_duration_s, min(spec.max_duration_s, user_total))

    # I2V when we have a start still OR character elements need I2V endpoint
    use_elements = bool(
        elements
        and getattr(spec, "supports_kling_elements", False)
        and spec.i2v_endpoint
    )
    has_start = bool(start_image_url and spec.i2v_endpoint) or use_elements
    # elements-only still requires I2V; if no start_image, reuse character frontal as start
    if use_elements and not start_image_url:
        try:
            frontal = (elements[0] or {}).get("frontal_image_url")
            if frontal:
                start_image_url = frontal
                has_start = True
        except Exception:
            pass

    ar, ar_note = resolve_director_aspect_for_api(
        spec, aspect_ratio, has_start_image=has_start
    )

    args: dict[str, Any] = {
        "multi_prompt": multi,
        "shot_type": "customize",
        "duration": str(total),
    }
    # Only send aspect_ratio when this path accepts it (T2V enums)
    if ar and (spec.aspect_param or "aspect_ratio"):
        args[spec.aspect_param or "aspect_ratio"] = ar

    if generate_audio is not None and spec.supports_audio:
        args["generate_audio"] = bool(generate_audio)
    elif spec.supports_audio:
        args["generate_audio"] = bool(spec.default_generate_audio)
    neg = (negative_prompt or "").strip()
    if neg:
        # Kling negative max ~2500; keep modest
        args["negative_prompt"] = clamp_prompt_chars(neg, 500)

    endpoint = spec.endpoint
    if has_start and spec.i2v_endpoint:
        endpoint = spec.i2v_endpoint
        img_param = (getattr(spec, "i2v_image_param", None) or "start_image_url").strip()
        if start_image_url:
            args[img_param] = start_image_url
        for other in ("start_image_url", "image_url"):
            if other != img_param and other in args:
                del args[other]
        if use_elements and elements:
            args["elements"] = elements

    # Stash resolve note for callers that log payload details (not sent to API)
    if ar_note:
        args["_aspect_note"] = ar_note
    if max_chars:
        args["_multi_prompt_max_chars"] = max_chars

    return endpoint, args


def strip_director_internal_args(arguments: dict[str, Any]) -> dict[str, Any]:
    """Remove client-only keys before fal subscribe."""
    return {k: v for k, v in arguments.items() if not str(k).startswith("_")}


@dataclass(frozen=True)
class DirectorRefBudget:
    """Unique-asset ref budget across the whole Director job."""

    used: int
    max_refs: int
    shot_count: int
    max_shots: int
    mode: str  # kling_element | image_bag
    angle_mode: str  # front_only | full_pack | n/a
    n_characters: int
    n_scenes: int
    n_images: int  # bag-of-images unique files (Imagine)
    detail: str
    reason_over: str = ""

    @property
    def over(self) -> bool:
        return self.used > self.max_refs or self.shot_count > self.max_shots

    @property
    def near(self) -> bool:
        if self.max_refs <= 0:
            return False
        return (not self.over) and self.used >= int(self.max_refs * 0.8)

    @property
    def shots_over(self) -> bool:
        return self.shot_count > self.max_shots


def resolve_angle_mode(
    shots: list[DirectorShot],
    *,
    requested: str | None = None,
) -> str:
    """
    Imagine bag-of-images / multi-ref angle mode (characters + optional scene pack).

    ``front_only`` | ``full_pack``. Default: Front only if any scene is bound,
    else Full pack. ``front_only`` = character primary + scene hero only;
    ``full_pack`` = character identity extras + scene Angle B/C.
    """
    req = (requested or "auto").strip().lower()
    if req in ("front_only", "front", "primary", "hero_only", "hero"):
        return "front_only"
    if req in ("full_pack", "full", "all", "pack"):
        return "full_pack"
    any_scene = any(sh.has_scene_bind() or sh.has_scene_ref() for sh in shots)
    return "front_only" if any_scene else "full_pack"


def count_director_ref_budget(
    spec: DirectorModelSpec,
    shots: list[DirectorShot],
    *,
    angle_mode: str | None = None,
) -> DirectorRefBudget:
    """
    Count UNIQUE assets for the job (not per-shot duplicates).

    Kling element-style: 1 per unique character (Front+Side+Close-up = 1 element)
    + 1 per unique scene/start image when the model accepts scene image refs.

    Imagine image-bag: each selected still file once. ``front_only`` uses only
    character primary; ``full_pack`` includes identity extras.
    """
    mode = (getattr(spec, "ref_budget_mode", None) or "kling_element").strip()
    max_refs = int(getattr(spec, "max_unique_refs", None) or 7)
    max_shots = int(spec.max_shots or 6)
    n_shots = len(shots)
    ang = resolve_angle_mode(shots, requested=angle_mode)

    # Unique characters by primary path
    char_keys: dict[str, DirectorShot] = {}
    for sh in shots:
        if not sh.has_character_bind():
            continue
        try:
            key = str(Path(sh.character_path or "").resolve())
        except OSError:
            key = (sh.character_path or "").strip()
        if key and key not in char_keys:
            char_keys[key] = sh

    # Unique location plates (hero). Full pack adds angle extras as unique stills.
    scene_keys: set[str] = set()
    scene_extra_keys: set[str] = set()
    for sh in shots:
        loc = sh.location_still_path()
        if not loc:
            continue
        try:
            key = str(Path(loc).resolve())
        except OSError:
            key = loc
        # Don't count character path as a scene
        if key in char_keys:
            continue
        if Path(key).is_file():
            scene_keys.add(key)
        if ang == "full_pack":
            for ex in sh.scene_extra_paths or ():
                try:
                    ep = str(Path(ex).resolve())
                except OSError:
                    ep = (ex or "").strip()
                if ep and ep not in char_keys and Path(ep).is_file():
                    scene_extra_keys.add(ep)

    n_chars = len(char_keys)
    n_scenes = len(scene_keys)
    supports_scene_img = bool(getattr(spec, "supports_scene_image_ref", False))

    if mode == "image_bag":
        files: set[str] = set()
        for key, sh in char_keys.items():
            if ang == "full_pack":
                files.add(key)
                for ex in sh.character_extra_paths or ():
                    try:
                        ep = str(Path(ex).resolve())
                    except OSError:
                        ep = (ex or "").strip()
                    if ep and Path(ep).is_file():
                        files.add(ep)
            else:
                files.add(key)
        if supports_scene_img:
            files |= scene_keys
            if ang == "full_pack":
                files |= scene_extra_keys
        used = len(files)
        n_images = used
        detail_bits = []
        if n_chars:
            detail_bits.append(
                f"{n_chars} character{'s' if n_chars != 1 else ''}"
                + (" (full pack)" if ang == "full_pack" else " (front only)")
            )
        if n_scenes and supports_scene_img:
            detail_bits.append(
                f"{n_scenes} scene{'s' if n_scenes != 1 else ''}"
            )
        detail = " + ".join(detail_bits) if detail_bits else "no refs"
        reason = ""
        if used > max_refs:
            tip = "remove a scene or use Front only" if ang == "full_pack" else (
                "remove a scene or character"
            )
            reason = f"{detail} = {used}/{max_refs} — {tip}."
        return DirectorRefBudget(
            used=used,
            max_refs=max_refs,
            shot_count=n_shots,
            max_shots=max_shots,
            mode=mode,
            angle_mode=ang,
            n_characters=n_chars,
            n_scenes=n_scenes if supports_scene_img else 0,
            n_images=n_images,
            detail=detail,
            reason_over=reason,
        )

    # kling_element: elements (unique chars as 1 each) + unique scene image urls
    # Full pack: each extra scene angle still counts as an image_url (not elements API)
    n_elements = n_chars
    n_img = 0
    if supports_scene_img:
        n_img = n_scenes
        if ang == "full_pack":
            n_img += len(scene_extra_keys)
    used = n_elements + n_img
    detail_bits = []
    if n_elements:
        detail_bits.append(
            f"{n_elements} character{'s' if n_elements != 1 else ''} (pack = 1 each)"
        )
    if n_img:
        pack_note = ""
        if ang == "full_pack" and scene_extra_keys:
            pack_note = f" incl. {len(scene_extra_keys)} angle still(s)"
        detail_bits.append(
            f"{n_img} scene image{'s' if n_img != 1 else ''}{pack_note}"
        )
    elif n_scenes and not supports_scene_img:
        detail_bits.append(
            f"{n_scenes} scene{'s' if n_scenes != 1 else ''} (text only)"
        )
    detail = " + ".join(detail_bits) if detail_bits else "no refs"
    reason = ""
    if used > max_refs:
        reason = (
            f"{n_elements} character{'s' if n_elements != 1 else ''} + "
            f"{n_img} scene{'s' if n_img != 1 else ''} = {used}/{max_refs} "
            f"— remove a character or scene."
        )
    return DirectorRefBudget(
        used=used,
        max_refs=max_refs,
        shot_count=n_shots,
        max_shots=max_shots,
        mode=mode,
        angle_mode="n/a",
        n_characters=n_chars,
        n_scenes=n_scenes if supports_scene_img else 0,
        n_images=n_img,
        detail=detail,
        reason_over=reason,
    )


def collect_director_image_plan(
    shots: list[DirectorShot],
    *,
    angle_mode: str | None = None,
) -> dict[str, Any]:
    """
    Plan which stills bind as character vs scene for API upload.

    Multi-character and multi-scene across shots supported.
    Order for Grok: per shot, character then location (when distinct).
    ``angle_mode``: front_only | full_pack (image_bag models).

    Returns:
      character_primary, characters, character_extras, character_labels
      scene_start: first location plate (library scene preferred)
      scenes: list[{path, label, id}] unique location plates
      scene_labels
      all_ref_paths: ordered unique paths (char then scene per shot)
      per_shot_paths: primary path per shot (character preferred)
      per_shot_pairs: list of (char_path|None, scene_path|None)
      angle_mode: resolved front_only | full_pack
    """
    ang = resolve_angle_mode(shots, requested=angle_mode)
    char_primary: str | None = None
    char_extras: list[str] = []
    char_labels: list[str] = []
    characters: list[dict[str, Any]] = []
    char_seen: set[str] = set()
    scene_start: str | None = None
    scenes: list[dict[str, Any]] = []
    scene_labels: list[str] = []
    scene_seen: set[str] = set()
    ordered: list[str] = []
    seen: set[str] = set()
    per_shot: list[str | None] = []
    per_shot_pairs: list[tuple[str | None, str | None]] = []

    def _add(path: str | None) -> None:
        if not path:
            return
        try:
            p = str(Path(path).resolve())
        except OSError:
            p = path
        if not Path(p).is_file():
            return
        if p in seen:
            return
        seen.add(p)
        ordered.append(p)

    def _norm(path: str | None) -> str | None:
        if not path:
            return None
        try:
            p = str(Path(path).resolve())
        except OSError:
            p = path
        return p if Path(p).is_file() else None

    for sh in shots:
        char_p = _norm(sh.character_path) if sh.has_character_bind() else None
        loc_p = _norm(sh.location_still_path())
        # Don't double-count character as location
        if char_p and loc_p and char_p == loc_p:
            loc_p = None

        if char_p:
            if char_primary is None:
                char_primary = char_p
            _add(char_p)
            if sh.character_label:
                char_labels.append(str(sh.character_label))
            if char_p not in char_seen:
                char_seen.add(char_p)
                extras_list = [
                    str(Path(ex).resolve())
                    for ex in (sh.character_extra_paths or ())
                    if ex and Path(ex).is_file()
                ][:4]
                # front_only: do not attach side/close-up stills to the bag
                if ang == "front_only":
                    extras_list = []
                characters.append(
                    {
                        "path": char_p,
                        "label": sh.character_label,
                        "id": sh.character_id,
                        "extras": extras_list,
                    }
                )
            if ang != "front_only":
                for ex in sh.character_extra_paths or ():
                    if not ex:
                        continue
                    try:
                        exr = str(Path(ex).resolve())
                    except OSError:
                        exr = ex
                    if char_p and exr == char_p:
                        continue
                    if exr not in char_extras:
                        char_extras.append(exr)
                    _add(exr)

        if loc_p:
            if scene_start is None:
                scene_start = loc_p
            _add(loc_p)
            lab = (sh.scene_label or Path(loc_p).name).strip()
            if lab:
                scene_labels.append(lab)
            if loc_p not in scene_seen:
                scene_seen.add(loc_p)
                scenes.append(
                    {
                        "path": loc_p,
                        "label": sh.scene_label,
                        "id": sh.scene_id,
                    }
                )
            # Full pack: attach Angle B/C as additional refs (multi-ref models)
            if ang != "front_only":
                for ex in sh.scene_extra_paths or ():
                    if not ex:
                        continue
                    try:
                        exr = str(Path(ex).resolve())
                    except OSError:
                        exr = ex
                    if loc_p and exr == loc_p:
                        continue
                    if char_p and exr == char_p:
                        continue
                    _add(exr)

        per_shot.append(char_p or loc_p)
        per_shot_pairs.append((char_p, loc_p))

    return {
        "character_primary": char_primary,
        "characters": characters,
        "character_extras": char_extras[:4] if ang != "front_only" else [],
        "character_labels": char_labels,
        "scene_start": scene_start,
        "scenes": scenes,
        "scene_labels": scene_labels,
        "all_ref_paths": ordered,
        "per_shot_paths": per_shot,
        "per_shot_pairs": per_shot_pairs,
        "angle_mode": ang,
    }
