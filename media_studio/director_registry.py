"""
Director tab — multi-shot video models and prompt assembly.

Kling V3 / O3 multi_prompt (customize): up to 6 shots, total ≤ 15s.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


@dataclass(frozen=True)
class DirectorModelSpec:
    key: str
    label: str
    endpoint: str
    # image-to-video multi-shot uses start_image_url when any shot has a still
    i2v_endpoint: str | None = None
    max_shots: int = 6
    min_duration_s: int = 3
    max_duration_s: int = 15
    allowed_durations: tuple[int, ...] = tuple(range(3, 16))
    default_duration_s: int = 10
    aspect_choices: tuple[str, ...] = ("16:9", "9:16", "1:1")
    default_aspect: str = "16:9"
    cost_per_second: float = 0.112  # ballpark @ no-audio / standard
    cost_per_second_audio: float | None = 0.168
    supports_audio: bool = True
    default_generate_audio: bool = True
    notes: str = ""
    # fal multi_prompt shot duration is integer seconds as string
    shot_min_s: int = 1
    shot_max_s: int = 15


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
        notes=(
            "Kling V3 Pro multi-shot storyboard — up to 6 shots, total ≤15s. "
            "Each shot has its own prompt + duration. Est. ~$0.11–0.17/s."
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
        notes=(
            "Kling V3 Standard multi-shot — faster/cheaper than Pro. "
            "Up to 6 shots, total ≤15s. Est. ~$0.08–0.13/s."
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
        notes=(
            "Kling O3 Pro multi-shot / director — multi-prompt storyboard, "
            "optional native audio. Up to 6 shots, total ≤15s."
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
        notes=(
            "Kling O3 Standard multi-shot — multi_prompt storyboard, cheaper than Pro. "
            "Up to 6 shots, total ≤15s. Seedance / Wan / H3 are single-clip (not multi-shot)."
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


@dataclass
class DirectorShot:
    """One ordered shot row."""

    start_s: float = 0.0
    end_s: float = 5.0
    camera: str = "Push in"
    action: str = ""
    ref_path: str | None = None

    @property
    def duration_s(self) -> float:
        return max(0.0, float(self.end_s) - float(self.start_s))


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


def estimate_director_cost(
    spec: DirectorModelSpec,
    *,
    duration_s: float,
    generate_audio: bool = False,
) -> float:
    rate = spec.cost_per_second
    if generate_audio and spec.cost_per_second_audio is not None:
        rate = spec.cost_per_second_audio
    secs = max(1.0, float(duration_s or spec.default_duration_s))
    return round(rate * secs, 3)


def format_director_cost(
    spec: DirectorModelSpec,
    *,
    duration_s: float,
    generate_audio: bool = False,
) -> str:
    from media_studio.pricing import format_job_cost

    amt = estimate_director_cost(
        spec, duration_s=duration_s, generate_audio=generate_audio
    )
    secs = int(round(float(duration_s or 0)))
    return format_job_cost(amt, unit=f"{secs}s", model=spec.label)


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
    for i, sh in enumerate(shots):
        n = i + 1
        try:
            a = float(sh.start_s)
            b = float(sh.end_s)
        except (TypeError, ValueError):
            errors.append(f"Shot {n}: start/end must be numbers.")
            continue
        if a < -0.01:
            errors.append(f"Shot {n}: start time cannot be before 0.")
        if b > total + 0.01:
            errors.append(
                f"Shot {n}: end ({b:g}s) is past total duration ({total:g}s)."
            )
        if b <= a + 0.01:
            errors.append(f"Shot {n}: end must be after start.")
        if not (sh.action or "").strip():
            errors.append(f"Shot {n}: enter a per-shot action prompt.")
        # fal multi_prompt duration is integer seconds ≥1
        dur = b - a
        if dur < 0.99:
            errors.append(f"Shot {n}: duration must be at least 1s for the API.")
    if not allow_overlap and len(shots) >= 2:
        ordered = sorted(
            enumerate(shots),
            key=lambda pair: (float(pair[1].start_s), float(pair[1].end_s)),
        )
        for j in range(1, len(ordered)):
            i_prev, prev = ordered[j - 1]
            i_cur, cur = ordered[j]
            if float(cur.start_s) < float(prev.end_s) - 0.01:
                errors.append(
                    f"Shots {i_prev + 1} and {i_cur + 1} overlap "
                    f"({prev.start_s:g}–{prev.end_s:g}s vs {cur.start_s:g}–{cur.end_s:g}s). "
                    "Ranges must not overlap."
                )
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
            if not (a.ref_path and Path(a.ref_path).is_file()):
                errors.append(
                    f"Continuous between Shot {g + 1} and {g + 2}: "
                    f"assign a ref still on Shot {g + 1} (motion keyframe)."
                )
            if not (b.ref_path and Path(b.ref_path).is_file()):
                errors.append(
                    f"Continuous between Shot {g + 1} and {g + 2}: "
                    f"assign a ref still on Shot {g + 2} (motion keyframe)."
                )
    return errors


def assemble_shot_prompt(
    shot: DirectorShot,
    *,
    index: int,
    style_pack: str | None = None,
) -> str:
    """One multi_prompt element text (camera + action)."""
    cam = CAMERA_PROMPT_LANG.get(shot.camera, shot.camera or "camera move")
    action = (shot.action or "").strip()
    bits = [f"Camera: {cam}."]
    if action:
        bits.append(action if action.endswith(".") else f"{action}.")
    # Style pack is mainly on master; light echo only if set
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
        lines.append(
            f"Shot {i + 1} ({t0:g}–{t1:g}s, {cam}): {action}"
        )
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
) -> list[dict[str, str]]:
    """
    fal multi_prompt payload: [{prompt, duration}, …].

    Duration is integer seconds (shot length), string enum for API.
    Master + polish continuity is woven into shot 1; later shots get per-gap
    cut / dissolve / continuous language from polish.gap_transitions.
    """
    # Master expansion uses summary transition line (not every gap twice)
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
        body = assemble_shot_prompt(sh, index=i, style_pack=style_pack)
        if i == 0:
            if master_txt:
                prompt = f"{master_txt.rstrip('.')}. {cont_short} {body}"
            else:
                prompt = f"{cont_short} {body}" if cont_short else body
        else:
            gap_key = polish.gap_at(i - 1) if polish else "Hard cut"
            gap_lang = GAP_INCOMING_PROMPT.get(gap_key) or GAP_INCOMING_PROMPT["Hard cut"]
            # Continuous keeps stronger motion language; cut is a clear edit
            if gap_key == "Continuous":
                bridge = f"{gap_lang} {continue_line}"
            else:
                bridge = f"{gap_lang} {continue_line}"
            prompt = f"{bridge} {body}"
        dur = max(1, int(round(float(sh.end_s) - float(sh.start_s))))
        dur = min(15, max(1, dur))
        out.append({"prompt": prompt.strip(), "duration": str(dur)})
    return out


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
) -> tuple[str, dict[str, Any]]:
    """
    Returns (endpoint, arguments) for fal subscribe.

    Uses multi_prompt + shot_type=customize. Total duration = sum of shot durs
    (also sent as duration string for API).
    """
    use_audio = (
        bool(generate_audio)
        if generate_audio is not None
        else bool(spec.default_generate_audio)
    )
    if not spec.supports_audio:
        use_audio = False
    multi = multi_prompt_from_shots(
        shots,
        style_pack=style_pack,
        master=master,
        polish=polish,
        generate_audio=use_audio,
    )
    if not multi:
        raise ValueError("At least one shot is required.")
    total = sum(int(m["duration"]) for m in multi)
    total = max(spec.min_duration_s, min(spec.max_duration_s, total))
    # Prefer user total if valid and ≥ shot sum
    try:
        user_total = int(round(float(duration_s)))
    except (TypeError, ValueError):
        user_total = total
    if user_total >= total:
        total = max(spec.min_duration_s, min(spec.max_duration_s, user_total))

    args: dict[str, Any] = {
        "multi_prompt": multi,
        "shot_type": "customize",
        "duration": str(total),
        "aspect_ratio": (aspect_ratio or spec.default_aspect or "16:9").strip(),
    }
    if generate_audio is not None and spec.supports_audio:
        args["generate_audio"] = bool(generate_audio)
    elif spec.supports_audio:
        args["generate_audio"] = bool(spec.default_generate_audio)
    neg = (negative_prompt or "").strip()
    if neg:
        args["negative_prompt"] = neg

    endpoint = spec.endpoint
    if start_image_url and spec.i2v_endpoint:
        endpoint = spec.i2v_endpoint
        args["start_image_url"] = start_image_url
        # Some I2V multi-shot still need aspect omitted or kept — keep aspect

    return endpoint, args
