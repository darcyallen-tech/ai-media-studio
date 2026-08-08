"""
Model Guide — single catalog for the in-app Model Guide UI.

Aggregates fal / Vision / Director / Motion Sync / Audio / Tools registries
and Best For hints so the Guide stays aligned with model pickers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass(frozen=True)
class GuideEntry:
    """One model card in the Guide."""

    key: str
    name: str
    family: str  # image | video | audio | tools | director | motion_sync
    modalities: tuple[str, ...]
    best_for: str
    strengths: str
    limitations: str
    flags: frozenset[str] = field(default_factory=frozenset)
    # studio_image | studio_video | vision | director | tools | audio | motion_sync
    open_target: str | None = None
    model_choice: str = ""  # label/key for preselect when practical
    sort_group: int = 50

    @property
    def search_blob(self) -> str:
        parts = [
            self.key,
            self.name,
            self.family,
            " ".join(self.modalities),
            self.best_for,
            self.strengths,
            self.limitations,
            " ".join(sorted(self.flags)),
        ]
        return " ".join(parts).lower()


# Category filters for the UI
GUIDE_FILTERS: tuple[tuple[str, str], ...] = (
    ("all", "All"),
    ("image", "Image"),
    ("video", "Video"),
    ("audio", "Audio"),
    ("tools", "Tools"),
    ("director", "Director"),
    ("motion_sync", "Motion Sync"),
)

# Quick flag filters
GUIDE_FLAG_FILTERS: tuple[tuple[str, str], ...] = (
    ("multi_char", "Multi-character ref"),
    ("native_audio", "Native audio"),
    ("draft", "Draft available"),
    ("multi_ref", "Multi-ref stills"),
)


def _best(key: str, label: str = "") -> tuple[str, str]:
    """Return (short, detail) from model_hints."""
    try:
        from media_studio.model_hints import lookup_best_for

        bf = lookup_best_for(key) or lookup_best_for(label)
        if bf:
            return (bf.short or "").strip(), (bf.detail or "").strip()
    except Exception:
        pass
    return "", ""


def _join(*parts: str) -> str:
    return " ".join(p.strip() for p in parts if p and str(p).strip())


def _image_entries() -> list[GuideEntry]:
    from media_studio.fal.models import IMAGE_EDIT_MODELS

    out: list[GuideEntry] = []
    for key, spec in IMAGE_EDIT_MODELS.items():
        short, detail = _best(key, spec.label)
        multi = bool(getattr(spec, "multi_image", False)) and int(
            getattr(spec, "max_ref_images", 1) or 1
        ) >= 2
        flags: set[str] = set()
        if multi:
            flags.add("multi_ref")
        lims: list[str] = []
        if multi:
            lims.append(
                f"Multi-ref up to {int(getattr(spec, 'max_ref_images', 1) or 1)} stills"
            )
        else:
            lims.append("Single still input")
        ar = getattr(spec, "aspect_ratio_param", None)
        if not ar:
            lims.append("Aspect follows source / no aspect_ratio param")
        res = getattr(spec, "allowed_resolutions", ()) or ()
        if res:
            lims.append(f"Resolutions: {', '.join(str(r) for r in res[:6])}")
        cost = getattr(spec, "cost_per_image", None)
        if cost is not None:
            lims.append(f"Est. ~${float(cost):.3f}/image (tier depends on res)")
        notes = (getattr(spec, "notes", None) or "").strip()
        out.append(
            GuideEntry(
                key=key,
                name=spec.label,
                family="image",
                modalities=("I2I",),
                best_for=short or (notes[:80] if notes else "Still image edit"),
                strengths=detail or notes or short or "Image edit model",
                limitations=_join(*lims) or "See fal docs for current limits",
                flags=frozenset(flags),
                open_target="studio_image",
                model_choice=spec.label,
                sort_group=10,
            )
        )
    # Vision T2I / I2I
    try:
        from media_studio.vision_registry import I2I_MODELS, T2I_MODELS

        for reg, mods in ((T2I_MODELS, ("T2I",)), (I2I_MODELS, ("I2I",))):
            for key, spec in reg.items():
                short, detail = _best(key, spec.label)
                flags = set()
                mr = int(getattr(spec, "max_refs", 0) or 0)
                if mr > 1 or (mods == ("I2I",) and mr >= 1):
                    flags.add("multi_ref")
                lims = [getattr(spec, "notes", "") or ""]
                if mr:
                    lims.append(f"Max extra refs: {mr}")
                out.append(
                    GuideEntry(
                        key=f"vision:{key}",
                        name=spec.label,
                        family="image",
                        modalities=mods,
                        best_for=short or "Creative Vision stills",
                        strengths=detail or (getattr(spec, "notes", "") or short),
                        limitations=_join(*lims),
                        flags=frozenset(flags),
                        open_target="vision",
                        model_choice=spec.label,
                        sort_group=12,
                    )
                )
    except Exception:
        pass
    return out


def _video_entries() -> list[GuideEntry]:
    from media_studio.fal.models import VIDEO_MODELS
    from media_studio.flux3_draft import (
        is_flux3_i2v_endpoint,
        model_supports_draft,
    )

    out: list[GuideEntry] = []
    for key, spec in VIDEO_MODELS.items():
        short, detail = _best(key, spec.label)
        task = getattr(spec, "task", "") or ""
        mods: list[str] = []
        if task == "image_to_video":
            if "reference-to-video" in (spec.endpoint or ""):
                mods.append("R2V")
            elif "first-last" in (spec.endpoint or "") or getattr(
                spec, "requires_end_frame", False
            ):
                mods.append("First→Last")
            else:
                mods.append("I2V")
        elif task == "video_edit":
            if "extend" in key or "extend" in (spec.endpoint or ""):
                mods.append("Extend")
            else:
                mods.append("V2V")
        flags: set[str] = set()
        lims: list[str] = []
        strengths = detail or (getattr(spec, "notes", "") or "")

        # Aspect
        if not getattr(spec, "aspect_ratio_param", None) or is_flux3_i2v_endpoint(
            getattr(spec, "endpoint", None)
        ):
            lims.append("Aspect follows still — do not send aspect_ratio")
        elif getattr(spec, "allowed_aspect_ratios", ()):
            lims.append(
                "Aspect: "
                + ", ".join(str(a) for a in spec.allowed_aspect_ratios[:8])
            )

        # Duration
        dmin = getattr(spec, "min_duration_seconds", None)
        dmax = getattr(spec, "max_duration_seconds", None)
        if dmin is not None and dmax is not None:
            lims.append(f"Duration ~{dmin:g}–{dmax:g}s")
        allowed = getattr(spec, "allowed_durations", ()) or ()
        if allowed and len(allowed) <= 8:
            lims.append("Durations: " + ", ".join(str(a) for a in allowed))

        # Audio
        if getattr(spec, "generate_audio_param", None) or getattr(
            spec, "native_stereo_audio", False
        ):
            flags.add("native_audio")
            if getattr(spec, "native_stereo_audio", False):
                lims.append("Native stereo audio (always on)")
            else:
                lims.append("Optional generate_audio")
        elif getattr(spec, "keep_audio_param", None):
            lims.append("Can keep source audio")
        else:
            lims.append("No native generate_audio on this path")

        # Multi-ref / identity
        multi = bool(getattr(spec, "multi_image", False)) and int(
            getattr(spec, "max_ref_images", 1) or 1
        ) >= 2
        if multi or "reference-to-video" in (spec.endpoint or ""):
            flags.add("multi_ref")
            cap = int(getattr(spec, "max_ref_images", 1) or 1)
            lims.append(f"Multi-ref stills (max ~{cap})")
            if "h3" in key or "omni" in key or "reference-to-video" in (
                spec.endpoint or ""
            ):
                flags.add("multi_char")
                lims.append("Multi-character identity pack supported")
        if is_flux3_i2v_endpoint(getattr(spec, "endpoint", None)):
            lims.append(
                "FLUX 3 I2V: Start frame = layout lock; Character = single identity "
                "(no multi-char element API). Prefer Keyframe Take for multi-pose packs."
            )
            lims.append("Draft first available")
            flags.add("draft")
        elif model_supports_draft(spec):
            flags.add("draft")
            lims.append("Draft first → Enhance to full")

        # Cost tier
        cps = getattr(spec, "cost_per_second", None)
        by_res = getattr(spec, "cost_per_second_by_resolution", None) or {}
        if by_res:
            bits = [f"{k} ~${v}/s" for k, v in list(by_res.items())[:3]]
            lims.append("Est. " + ", ".join(bits))
        elif cps is not None:
            lims.append(f"Est. ~${float(cps):.3f}/s")

        notes = (getattr(spec, "notes", None) or "").strip()
        final_strengths = strengths or notes or short
        if "seedance" in key.lower() and "2.5" in key.lower():
            final_strengths = _join(
                short or "Long take + high ref count + action",
                "Up to 30s single-pass, multimodal refs (R2V), native audio, strong action.",
                detail or notes,
            )
            lims = [
                "Partner photoreal-face filter may reject people refs",
                "480p/720p; token billing $0.0214/1k tokens (video refs ×0.6)",
            ] + [x for x in lims if x]
            flags.add("native_audio")
            flags.add("multi_ref")
        out.append(
            GuideEntry(
                key=key,
                name=spec.label,
                family="video",
                modalities=tuple(mods) or ("Video",),
                best_for=short or "Video generation / edit",
                strengths=final_strengths,
                limitations=_join(*lims),
                flags=frozenset(flags),
                open_target="studio_video",
                model_choice=spec.label,
                sort_group=20,
            )
        )

    # Vision video models not only in VIDEO_MODELS
    try:
        from media_studio.vision_registry import (
            BRIDGE_MODELS,
            EXTEND_MODELS,
            I2V_MODELS,
            R2I_MODELS,
            R2V_MODELS,
            T2V_MODELS,
            V2V_MODELS,
        )

        for reg, default_mod in (
            (T2V_MODELS, "T2V"),
            (I2V_MODELS, "I2V"),
            (R2V_MODELS, "R2V"),
            (V2V_MODELS, "V2V"),
            (BRIDGE_MODELS, "First→Last"),
            (EXTEND_MODELS, "Extend"),
        ):
            for key, spec in reg.items():
                if any(e.key == key or e.name == spec.label for e in out):
                    continue
                short, detail = _best(key, spec.label)
                flags: set[str] = set()
                lims: list[str] = [getattr(spec, "notes", "") or ""]
                mods = [default_mod]
                if getattr(spec, "omni_reference", False) or default_mod == "R2V":
                    if "R2V" not in mods:
                        mods = ["R2V"] + [m for m in mods if m != "R2V"]
                    if getattr(spec, "omni_reference", False):
                        mods.append("Omni")
                    flags.add("multi_char")
                    flags.add("multi_ref")
                    lims.append(
                        f"Multi identity / refs (up to {getattr(spec, 'max_refs', 9)})"
                    )
                if getattr(spec, "native_stereo_audio", False) or getattr(
                    spec, "supports_audio", False
                ):
                    flags.add("native_audio")
                if getattr(spec, "draft_endpoint", None):
                    flags.add("draft")
                if getattr(spec, "omit_aspect_ratio", False):
                    lims.append("Aspect follows still (no aspect_ratio)")
                strengths = detail or (getattr(spec, "notes", "") or short)
                # Seedance 2.5: surface strengths / face-filter limitation for Guide
                if "seedance" in key.lower() and "2.5" in key.lower():
                    strengths = _join(
                        short or "Long take + high ref count + action",
                        "Up to 30s single-pass, up to 50 multimodal refs (R2V), "
                        "native audio, strong action / physics.",
                        detail,
                    )
                    lims = [
                        "Partner photoreal-face filter may reject people refs",
                        "480p/720p only on fal; token billing $0.0214/1k tokens",
                        "Video refs billed (×0.6); image/audio refs free",
                    ] + [x for x in lims if x]
                    flags.add("native_audio")
                    flags.add("multi_ref")
                out.append(
                    GuideEntry(
                        key=f"vision:{key}",
                        name=spec.label,
                        family="video",
                        modalities=tuple(mods),
                        best_for=short or default_mod,
                        strengths=strengths,
                        limitations=_join(*lims),
                        flags=frozenset(flags),
                        open_target="vision",
                        model_choice=spec.label,
                        sort_group=22,
                    )
                )
        for key, spec in R2I_MODELS.items():
            if any(e.name == spec.label for e in out):
                continue
            short, detail = _best(key, spec.label)
            out.append(
                GuideEntry(
                    key=f"vision:{key}",
                    name=spec.label,
                    family="image",
                    modalities=("R2I",),
                    best_for=short or "Build still from character/style refs",
                    strengths=detail or (getattr(spec, "notes", "") or short),
                    limitations=_join(
                        getattr(spec, "notes", "") or "",
                        f"Max {getattr(spec, 'max_refs', 3)} identity/style refs",
                    ),
                    flags=frozenset({"multi_ref", "multi_char"}),
                    open_target="vision",
                    model_choice=spec.label,
                    sort_group=12,
                )
            )
    except Exception:
        pass
    return out


def _director_entries() -> list[GuideEntry]:
    out: list[GuideEntry] = []
    try:
        from media_studio.director_registry import DIRECTOR_MODELS

        for key, spec in DIRECTOR_MODELS.items():
            short, detail = _best(key, spec.label)
            flags: set[str] = set()
            lims: list[str] = [getattr(spec, "notes", "") or ""]
            mods = ["Director"]
            eng = getattr(spec, "engine", "") or ""
            if eng == "kling_multi":
                mods.append("Multi-shot")
                lims.append("Kling multi_prompt / multi-shot cuts")
                if getattr(spec, "supports_kling_elements", False):
                    lims.append("Elements / multi identity packs on capable models")
                    flags.add("multi_char")
            elif eng == "flux3":
                mods.append("Continuous")
                if getattr(spec, "requires_end_frame", False):
                    mods.append("First→Last")
                else:
                    mods.append("I2V")
                if not getattr(spec, "i2v_accepts_aspect", True):
                    lims.append("Aspect follows still (no aspect_ratio)")
                if getattr(spec, "draft_endpoint", None) or "flux" in key:
                    flags.add("draft")
            elif eng == "grok_imagine":
                mods.append("Imagine")
            if getattr(spec, "supports_audio", False):
                flags.add("native_audio")
            # Keyframe Take is a mode not always in DIRECTOR_MODELS as separate
            out.append(
                GuideEntry(
                    key=f"director:{key}",
                    name=spec.label,
                    family="director",
                    modalities=tuple(mods),
                    best_for=short or "Director multi-shot / continuous take",
                    strengths=detail or (getattr(spec, "notes", "") or short),
                    limitations=_join(*lims),
                    flags=frozenset(flags),
                    open_target="director",
                    model_choice=spec.label,
                    sort_group=25,
                )
            )
        # Keyframe Take virtual entry
        short, detail = _best("flux 3 keyframe take", "FLUX 3 · Keyframe Take")
        out.append(
            GuideEntry(
                key="director:flux 3 keyframe take",
                name="FLUX 3 · Keyframe Take",
                family="director",
                modalities=("Director", "Keyframes"),
                best_for=short
                or "Ordered pose pins → continuous FLUX 3 keyframes-to-video",
                strengths=detail
                or "Multi pose plates at times; layout lock between pins; not multi-shot cuts.",
                limitations=_join(
                    "Max ~10 pins",
                    "Not Kling multi_prompt",
                    "Prefer for multi-pose continuous motion vs single I2V identity",
                    "Draft + Enhance to full when available",
                ),
                flags=frozenset({"draft"}),
                open_target="director",
                model_choice="keyframe_take",
                sort_group=26,
            )
        )
    except Exception:
        pass
    return out


def _motion_sync_entries() -> list[GuideEntry]:
    out: list[GuideEntry] = []
    try:
        from media_studio.motion_sync_registry import MOTION_SYNC_MODELS

        for key, spec in MOTION_SYNC_MODELS.items():
            short, detail = _best(key, spec.label)
            out.append(
                GuideEntry(
                    key=f"motion:{key}",
                    name=spec.label,
                    family="motion_sync",
                    modalities=("Motion Sync",),
                    best_for=short or "Character still + driving clip",
                    strengths=detail or (getattr(spec, "notes", "") or short),
                    limitations=_join(
                        getattr(spec, "notes", "") or "",
                        "Needs character still + motion reference clip",
                    ),
                    flags=frozenset(),
                    open_target="motion_sync",
                    model_choice=spec.label,
                    sort_group=30,
                )
            )
    except Exception:
        pass
    return out


def _audio_entries() -> list[GuideEntry]:
    out: list[GuideEntry] = []
    try:
        from media_studio.audio_registry import (
            AMBIENCE_MODELS,
            MUSIC_MODELS,
            SFX_MODELS,
            VIDEO_SFX_MODELS,
            VOICE_CLONE_MODELS,
            VOICEOVER_MODELS,
        )

        for reg, mod in (
            (MUSIC_MODELS, "Music"),
            (SFX_MODELS, "SFX"),
            (AMBIENCE_MODELS, "Ambience"),
            (VIDEO_SFX_MODELS, "Video→SFX"),
            (VOICEOVER_MODELS, "VO"),
            (VOICE_CLONE_MODELS, "Voice clone"),
        ):
            if not isinstance(reg, dict):
                continue
            for key, spec in reg.items():
                short, detail = _best(key, getattr(spec, "label", key))
                out.append(
                    GuideEntry(
                        key=f"audio:{key}",
                        name=getattr(spec, "label", key),
                        family="audio",
                        modalities=("Audio", mod),
                        best_for=short or mod,
                        strengths=detail
                        or (getattr(spec, "notes", "") or short or mod),
                        limitations=_join(
                            getattr(spec, "notes", "") or "",
                            (
                                f"Est. ~${float(spec.cost_estimate_usd):.2f}"
                                if getattr(spec, "cost_estimate_usd", None)
                                else ""
                            ),
                        ),
                        flags=frozenset(),
                        open_target="audio",
                        model_choice=getattr(spec, "label", key),
                        sort_group=40,
                    )
                )
    except Exception:
        # Fallback: iterate known dicts if names differ
        try:
            import media_studio.audio_registry as ar

            for name in dir(ar):
                if not name.endswith("_MODELS") and name not in (
                    "MUSIC",
                    "SFX",
                ):
                    continue
                reg = getattr(ar, name, None)
                if not isinstance(reg, dict):
                    continue
                for key, spec in reg.items():
                    if not hasattr(spec, "label"):
                        continue
                    out.append(
                        GuideEntry(
                            key=f"audio:{key}",
                            name=spec.label,
                            family="audio",
                            modalities=("Audio",),
                            best_for=getattr(spec, "notes", "")[:80]
                            or "Audio generation",
                            strengths=getattr(spec, "notes", "") or "Audio model",
                            limitations="",
                            open_target="audio",
                            model_choice=spec.label,
                            sort_group=40,
                        )
                    )
        except Exception:
            pass
    return out


def _tools_entries() -> list[GuideEntry]:
    out: list[GuideEntry] = []
    try:
        from media_studio import tools_registry as tr

        for name in dir(tr):
            reg = getattr(tr, name, None)
            if not isinstance(reg, dict):
                continue
            for key, spec in reg.items():
                if not hasattr(spec, "label") or not hasattr(spec, "category"):
                    continue
                short, detail = _best(key, spec.label)
                cat = getattr(spec, "category", "tool")
                out.append(
                    GuideEntry(
                        key=f"tools:{key}",
                        name=spec.label,
                        family="tools",
                        modalities=("Tools", str(cat).title()),
                        best_for=short or str(cat),
                        strengths=detail
                        or (getattr(spec, "notes", "") or short or cat),
                        limitations=_join(
                            getattr(spec, "notes", "") or "",
                            (
                                f"Est. ~${float(spec.cost_estimate_usd):.3f}"
                                if getattr(spec, "cost_estimate_usd", None)
                                is not None
                                else ""
                            ),
                        ),
                        flags=frozenset(),
                        open_target="tools",
                        model_choice=key,
                        sort_group=45,
                    )
                )
    except Exception:
        pass
    return out


def collect_guide_entries() -> list[GuideEntry]:
    """All Guide cards, de-duplicated by name, sorted for display."""
    raw: list[GuideEntry] = []
    raw.extend(_image_entries())
    raw.extend(_video_entries())
    raw.extend(_director_entries())
    raw.extend(_motion_sync_entries())
    raw.extend(_audio_entries())
    raw.extend(_tools_entries())

    # De-dupe by lowercase name (prefer earlier richer sort_group lower = first)
    seen: set[str] = set()
    uniq: list[GuideEntry] = []
    for e in sorted(raw, key=lambda x: (x.sort_group, x.name.lower())):
        nk = e.name.strip().lower()
        if not nk or nk in seen:
            continue
        seen.add(nk)
        uniq.append(e)
    return uniq


def filter_guide_entries(
    entries: Iterable[GuideEntry],
    *,
    family: str = "all",
    query: str = "",
    flag: str | None = None,
) -> list[GuideEntry]:
    q = (query or "").strip().lower()
    fam = (family or "all").strip().lower()
    fl = (flag or "").strip().lower() or None
    out: list[GuideEntry] = []
    for e in entries:
        if fam not in ("", "all") and e.family != fam:
            # Image filter includes T2I/I2I only (family image)
            # Video includes director continuous? User said Video = I2V/V2V/T2V/Keyframes/Extend
            if fam == "video" and e.family in ("director", "motion_sync"):
                # Include director keyframe / continuous in video filter for discovery
                if e.family == "motion_sync":
                    continue
                # keep director under Video chip for keyframes/continuous
            elif fam == "video" and e.family != "video":
                if e.family != "director":
                    continue
            else:
                continue
        if fl and fl not in e.flags:
            continue
        if q and q not in e.search_blob:
            continue
        out.append(e)
    return out


def open_target_label(target: str | None) -> str:
    return {
        "studio_image": "Open in Studio Image",
        "studio_video": "Open in Studio Video",
        "vision": "Open in Creative Vision",
        "director": "Open in Director",
        "tools": "Open in Tools",
        "audio": "Open in Audio",
        "motion_sync": "Open in Motion Sync",
    }.get(target or "", "Open")
