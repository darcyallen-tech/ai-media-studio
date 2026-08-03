"""
VFX tab — effect presets, model list, prompt helpers, cost.

Two workspaces:
  In-scene — effect integrated into a full plate (still or clip)
  Element plates — isolated effect on black / clean bg for Screen·Add in Resolve
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

VfxMode = Literal["in_scene", "element"]

# ---------------------------------------------------------------------------
# Preset packs (physics-aware prompt injectors)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VfxPreset:
    key: str
    label: str
    # Short chip / dropdown label
    inject_in_scene: str
    inject_element: str
    notes: str = ""


VFX_PRESETS: dict[str, VfxPreset] = {
    "fire": VfxPreset(
        key="fire",
        label="Fire / heat haze",
        inject_in_scene=(
            "Integrate realistic fire into the existing plate: orange–yellow flame "
            "tongues with blue-gas base where fuel is hot, rising convection, heat "
            "shimmer / heat haze distorting background detail above the fire, "
            "soot and ember particles, soft secondary bounce light on nearby surfaces. "
            "Match existing light direction and scale; do not replace the plate geometry."
        ),
        inject_element=(
            "Isolated fire element on pure black background for Screen/Add composite: "
            "clean flame silhouette with transparent-black void, heat haze only around "
            "flame tips, floating embers, no floor or environment, no vignette, "
            "high-contrast edges suitable for Screen blending in Resolve."
        ),
        notes="Temperature, convection, soot, heat shimmer.",
    ),
    "smoke": VfxPreset(
        key="smoke",
        label="Smoke / dust",
        inject_in_scene=(
            "Integrate volumetric smoke or dust into the plate: soft density gradients, "
            "slow turbulent rise or wind drift, particulate scattering, subtle shadowing "
            "where smoke occludes light. Match existing lighting direction and depth; "
            "preserve architecture and subjects underneath the volume."
        ),
        inject_element=(
            "Isolated smoke / dust volume on pure black for Screen/Add: soft wisps and "
            "dense core, no ground plane, no background plate, clean black void around "
            "the element, ready for soft-light or screen composite."
        ),
        notes="Density, drift, particulate scatter.",
    ),
    "energy": VfxPreset(
        key="energy",
        label="Energy / power surge",
        inject_in_scene=(
            "Integrate an energy / power-surge effect into the plate: electric arcs or "
            "plasma filaments with bright core and softer bloom, momentary over-bright "
            "highlights on conductive surfaces, residual glow and residual heat after "
            "the surge, subtle camera interaction with existing exposure. Keep set "
            "geometry locked; energy reads as diegetic light."
        ),
        inject_element=(
            "Isolated energy / power-surge element on pure black for Screen/Add: bright "
            "core with controlled bloom, arc filaments, no environment, pure black void, "
            "high-key centers suitable for Add blend in Resolve."
        ),
        notes="Arc velocity, bloom, residual glow.",
    ),
    "weather": VfxPreset(
        key="weather",
        label="Rain / snow / fog",
        inject_in_scene=(
            "Integrate weather into the plate: rain streaks or snow flakes with correct "
            "perspective scale and motion blur, wet speculars on hard surfaces, fog or "
            "mist softening distant contrast, matching ambient light temperature. "
            "Preserve the plate’s depth cues and architecture."
        ),
        inject_element=(
            "Isolated weather particles (rain streaks / snow / fog) on pure black for "
            "Screen composite: directional streaks or flakes with motion, pure black "
            "void, no ground plane, clean for soft-light or screen over live plates."
        ),
        notes="Perspective scale, wet speculars, depth fog.",
    ),
    "debris": VfxPreset(
        key="debris",
        label="Debris / impact",
        inject_in_scene=(
            "Integrate debris / impact FX into the plate: shattered fragments with "
            "plausible mass and velocity, dust burst at impact point, secondary bounce "
            "and settle, contact shadows under larger chunks, matching gravity and "
            "light direction. Do not invent a new set — keep the existing plate."
        ),
        inject_element=(
            "Isolated debris / impact burst on pure black for Screen/Add: fragments and "
            "dust cloud with clear silhouette, pure black void, no floor plane, ready "
            "for composite over action plates."
        ),
        notes="Mass, velocity, bounce, contact shadows.",
    ),
    "lens": VfxPreset(
        key="lens",
        label="Lens flare / light leak",
        inject_in_scene=(
            "Integrate optical lens flare or light leak into the plate: anamorphic or "
            "spherical flare streaks, aperture ghosts, soft veiling glare, optional "
            "warm light-leak wash along frame edge. Align flare source with existing "
            "bright light in the plate; keep subject readable."
        ),
        inject_element=(
            "Isolated lens flare / light leak on pure black for Screen/Add: streak, "
            "ghost orbs, and soft veil with pure black void, no scene content, "
            "high-key cores for Screen blending in Resolve."
        ),
        notes="Flare geometry, ghosts, veiling glare.",
    ),
}


def vfx_preset_labels() -> list[str]:
    return [p.label for p in VFX_PRESETS.values()]


def find_vfx_preset(label_or_key: str | None) -> VfxPreset | None:
    if not label_or_key:
        return None
    raw = label_or_key.strip().lower()
    if raw in VFX_PRESETS:
        return VFX_PRESETS[raw]
    for p in VFX_PRESETS.values():
        if p.label.lower() == raw or p.key == raw:
            return p
    return None


def default_vfx_preset() -> VfxPreset:
    return VFX_PRESETS["fire"]


# ---------------------------------------------------------------------------
# Models (video-capable, effects-friendly)
# ---------------------------------------------------------------------------

# Curated labels / keys for the VFX model picker (resolve via fal or vision)
VFX_MODEL_KEYS: tuple[str, ...] = (
    "grok imagine 1.5 i2v",
    "kling o3 pro i2v",
    "kling o3 standard i2v",
    "kling v3 pro i2v",
    "seedance 2.0 i2v",
    "minimax h3 i2v",
    "grok imagine 1.5 t2v",  # vision — element / no-plate
    "veo 3.1 fast",
    "grok imagine edit video",  # in-scene clip
    "kling o3 pro edit",
)


def vfx_model_labels() -> list[str]:
    """Human labels for the picker (from fal VIDEO + vision T2V)."""
    from media_studio.fal.models import VIDEO_MODELS, resolve_video_model
    from media_studio.vision_registry import T2V_MODELS, find_vision_model

    labels: list[str] = []
    seen: set[str] = set()
    for key in VFX_MODEL_KEYS:
        if key in VIDEO_MODELS:
            lab = VIDEO_MODELS[key].label
            if lab not in seen:
                labels.append(lab)
                seen.add(lab)
            continue
        # Vision T2V
        vs = find_vision_model(key, "text_to_video") or find_vision_model(
            key.replace(" t2v", ""), "text_to_video"
        )
        if vs is None:
            # try label match
            for s in T2V_MODELS.values():
                if s.key == key or key in s.key:
                    vs = s
                    break
        if vs is not None and vs.label not in seen:
            labels.append(vs.label)
            seen.add(vs.label)
    # Fallback scan if empty
    if not labels:
        for k in ("grok imagine 1.5 i2v", "kling o3 standard i2v"):
            sp = resolve_video_model(k)
            if sp:
                labels.append(sp.label)
    return labels


def default_vfx_model_label() -> str:
    labs = vfx_model_labels()
    for pref in (
        "Video · Grok Imagine 1.5 – Image-to-Video",
        "Grok Imagine 1.5 · Text→Video",
    ):
        if pref in labs:
            return pref
    return labs[0] if labs else "Video · Grok Imagine 1.5 – Image-to-Video"


def resolve_vfx_model(label: str | None) -> tuple[str, Any]:
    """
    Returns (``kind``, spec) where kind is ``video`` (fal VideoModelSpec)
    or ``vision`` (VisionModelSpec T2V).
    """
    from media_studio.fal.models import resolve_video_model
    from media_studio.vision_registry import find_vision_model

    if label:
        v = resolve_video_model(label)
        if v is not None:
            return "video", v
        vis = find_vision_model(label, "text_to_video")
        if vis is not None:
            return "vision", vis
        # I2V vision
        vis2 = find_vision_model(label, "image_to_video")
        if vis2 is not None:
            return "vision", vis2
    # default
    from media_studio.fal.models import resolve_video_model as rvm

    return "video", rvm(default_vfx_model_label()) or rvm("grok imagine 1.5 i2v")


# ---------------------------------------------------------------------------
# Prompt assembly
# ---------------------------------------------------------------------------

IN_SCENE_LOCK = (
    "In-scene VFX: keep source geometry, camera framing, and lighting direction "
    "consistent with the plate; integrate the effect as if photographed in-camera."
)

ELEMENT_LOCK = (
    "Element plate VFX for Resolve composite (Screen or Add blend mode): pure black "
    "background only, no environment, no floor, no vignette — clean isolated effect."
)


def assemble_vfx_prompt(
    *,
    mode: VfxMode,
    preset: VfxPreset | None,
    user_prompt: str,
    strength: float = 0.7,
    duration_s: float | None = None,
) -> str:
    """
    Build the full prompt. Preset inject is prepended; user text stays editable source.

    strength 0–1 → mild / medium / strong language.
    """
    bits: list[str] = []
    if mode == "element":
        bits.append(ELEMENT_LOCK)
    else:
        bits.append(IN_SCENE_LOCK)

    if preset is not None:
        inject = preset.inject_element if mode == "element" else preset.inject_in_scene
        bits.append(inject)

    # Strength language
    s = max(0.0, min(1.0, float(strength)))
    if s < 0.34:
        bits.append("Effect intensity: subtle / restrained — do not dominate the frame.")
    elif s < 0.67:
        bits.append("Effect intensity: medium — clearly readable, balanced with the plate.")
    else:
        bits.append("Effect intensity: strong / dramatic — bold but still photoreal.")

    if duration_s is not None and duration_s > 0:
        bits.append(f"Clip length about {int(round(duration_s))} seconds of continuous effect motion.")

    user = (user_prompt or "").strip()
    if user:
        bits.append(user)
    return " ".join(bits).strip()


def inject_preset_only(
    *,
    mode: VfxMode,
    preset: VfxPreset,
    existing_user: str = "",
) -> str:
    """
    When user picks a preset, rebuild prompt from preset + optional free notes.

    Strips previous auto injects by replacing with a clean composition:
    lock + preset + user freeform (if not already the inject text).
    """
    free = (existing_user or "").strip()
    # Drop if free is only prior inject noise — keep short custom notes
    for p in VFX_PRESETS.values():
        if free and (free == p.inject_in_scene or free == p.inject_element):
            free = ""
            break
    return assemble_vfx_prompt(
        mode=mode,
        preset=preset,
        user_prompt=free,
        strength=0.7,
    )


# ---------------------------------------------------------------------------
# Cost
# ---------------------------------------------------------------------------


def estimate_vfx_cost(
    model_label: str | None,
    *,
    duration_s: float = 5.0,
    resolution: str | None = None,
) -> float | None:
    kind, spec = resolve_vfx_model(model_label)
    if kind == "video" and spec is not None:
        return spec.estimate_cost(
            duration_seconds=duration_s,
            resolution=resolution,
        )
    if kind == "vision" and spec is not None:
        from media_studio.vision_registry import estimate_vision_cost

        return estimate_vision_cost(
            spec,
            duration_token=str(int(duration_s)),
            resolution=resolution,
        )
    return None


def format_vfx_cost(
    model_label: str | None,
    *,
    duration_s: float = 5.0,
    resolution: str | None = None,
) -> str:
    from media_studio.pricing import format_job_cost

    amt = estimate_vfx_cost(
        model_label, duration_s=duration_s, resolution=resolution
    )
    kind, spec = resolve_vfx_model(model_label)
    lab = getattr(spec, "label", None) or (model_label or "VFX")
    secs = int(round(float(duration_s or 0)))
    return format_job_cost(amt, unit=f"{secs}s", model=lab)


def model_is_video_edit(model_label: str | None) -> bool:
    kind, spec = resolve_vfx_model(model_label)
    return kind == "video" and getattr(spec, "task", None) == "video_edit"


def model_is_t2v(model_label: str | None) -> bool:
    kind, spec = resolve_vfx_model(model_label)
    if kind == "vision":
        return getattr(spec, "mode", None) == "text_to_video"
    return False


def model_notes(model_label: str | None) -> str:
    kind, spec = resolve_vfx_model(model_label)
    if spec is None:
        return ""
    return getattr(spec, "notes", "") or ""
