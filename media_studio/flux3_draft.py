"""
FLUX 3 draft workflow + Enhance brief helpers (fal).

Draft endpoints: ``blackforestlabs/flux-3/<mode>/draft``
Enhance: ``blackforestlabs/flux-3/draft-enhance`` with ``draft_cache_url``.
Prompt Enhance: model-specific FLUX 3 Video rewrite rules (not Kling multi-shot).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from media_studio.errors import friendly_error
from media_studio.fal.client import (
    FalClientError,
    download_url,
    extract_draft_cache_url,
    extract_video_url,
    subscribe,
)
from media_studio.naming import job_media_dir, make_output_stem, timestamp_now, unique_path
from media_studio.pricing import format_job_cost, format_render_metrics

ProgressCallback = Callable[[str], None]

FLUX3_DRAFT_ENHANCE = "blackforestlabs/flux-3/draft-enhance"
# Ballpark when model omits cost_per_second_draft
DEFAULT_DRAFT_RATE = 0.06

_FLUX3_ENHANCE_BRIEF_PATH = (
    Path(__file__).resolve().parent / "prompts" / "flux3_video_enhance.txt"
)


def is_flux3_video_model_choice(model_choice: str | None) -> bool:
    """
    True when the UI/model key is any FLUX 3 *video* path
    (T2V / I2V / first→last / extend / keyframes / draft / Director continuous).
    """
    raw = (model_choice or "").strip().lower()
    if not raw:
        return False
    # Flux 2 image edit must not match
    if "flux 2" in raw or "flux-2" in raw or "flux.1" in raw or "flux1" in raw:
        return False
    if "blackforestlabs/flux-3" in raw or "flux-3/" in raw:
        return True
    if "flux 3" in raw or "flux3" in raw:
        # Exclude pure image if ever named that way
        if any(x in raw for x in ("edit", "fill", "inpaint", "kontext")):
            return False
        return True
    # Resolved fal keys / endpoints
    try:
        from media_studio.fal.models import resolve_video_model

        v = resolve_video_model(model_choice)
        if v and "flux-3" in (v.endpoint or ""):
            return True
    except Exception:
        pass
    try:
        from media_studio.vision_registry import find_vision_model

        for mode in (
            "text_to_video",
            "image_to_video",
            "bridge",
            "extend",
        ):
            vs = find_vision_model(model_choice, mode)  # type: ignore[arg-type]
            if vs and "flux-3" in (vs.endpoint or ""):
                return True
    except Exception:
        pass
    try:
        from media_studio.director_registry import find_director_model

        d = find_director_model(model_choice)
        if d and (
            (getattr(d, "engine", None) or "") == "flux3"
            or "flux-3" in (d.endpoint or "")
            or "flux-3" in (getattr(d, "i2v_endpoint", None) or "")
        ):
            return True
    except Exception:
        pass
    return False


def load_flux3_video_enhance_brief() -> str:
    """Full crash-course brief from prompts/flux3_video_enhance.txt."""
    try:
        if _FLUX3_ENHANCE_BRIEF_PATH.is_file():
            return _FLUX3_ENHANCE_BRIEF_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        pass
    return (
        "FLUX 3 Video: format-first continuous take; layout lock for I2V; "
        "audio first-class; setup→turn→payoff for 10–20s; no Kling multi_prompt."
    )


def flux3_enhance_mode_hint(
    *,
    modality: str | None = None,
    has_start_still: bool = False,
    has_end_still: bool = False,
    has_source_video: bool = False,
    draft_mode: bool = False,
) -> str:
    """Short mode-specific add-on for the Enhance user payload."""
    bits: list[str] = []
    m = (modality or "").strip().lower()
    if draft_mode or "draft" in m:
        bits.append(
            "Draft path: keep the rewrite lean and cinematic; same FLUX 3 biases "
            "(format first, audio, layout lock if still) — draft is preview quality only."
        )
    if has_end_still or m in ("bridge", "first_last", "first-last", "flf"):
        bits.append(
            "First→last / bridge: continuous transition between start and end stills; "
            "pins define endpoints, not hard cuts."
        )
    elif has_source_video or m in ("extend", "v2v", "video_edit"):
        bits.append(
            "Extend: continue from the source clip’s final frames; do not reset geography."
        )
    elif has_start_still or m in ("i2v", "image_to_video", "image-to-video"):
        bits.append(
            "I2V: open with layout lock from the start still, then action-only motion."
        )
    elif m in ("t2v", "text_to_video", "text-to-video"):
        bits.append(
            "T2V: format-first continuous shot; duration as setup→turn→payoff when length allows."
        )
    elif m in ("keyframes", "keyframe"):
        bits.append(
            "Keyframes: global continuous motion prompt; pins are structure — not multi-shot cuts."
        )
    return " ".join(bits)


def flux3_video_enhance_guidance(
    *,
    modality: str | None = None,
    has_start_still: bool = False,
    has_end_still: bool = False,
    has_source_video: bool = False,
    draft_mode: bool = False,
    creative_direction: str | None = None,
    lean: bool = False,
) -> str:
    """
    Guidance string for Enhance extra_context when FLUX 3 Video is selected.

    Intended for Studio / Vision / Director — overrides Kling multi-shot language.
    """
    brief = load_flux3_video_enhance_brief()
    mode_hint = flux3_enhance_mode_hint(
        modality=modality,
        has_start_still=has_start_still,
        has_end_still=has_end_still,
        has_source_video=has_source_video,
        draft_mode=draft_mode,
    )
    parts = [
        "CRITICAL — locked target is FLUX 3 Video (not Kling multi-shot, not Imagine, "
        "not Seedance, not Flux 2 image). Apply the FLUX 3 Video crash course fully. "
        "chosen_model must remain the locked FLUX 3 model.",
        mode_hint,
    ]
    if lean:
        parts.append(
            "User wants minimal direction: lean rewrite — format lead + beats + "
            "layout lock (if I2V) + essential audio only."
        )
    cd = (creative_direction or "").strip()
    if cd:
        parts.append(
            f"Creative direction for Enhance only (fold into tone/beats, do not dump raw): {cd}"
        )
    parts.append("Full brief follows:\n" + brief)
    return "\n".join(p for p in parts if p)


def model_supports_draft(spec: Any) -> bool:
    return bool(getattr(spec, "draft_endpoint", None))


def draft_endpoint_for(spec: Any) -> str | None:
    ep = (getattr(spec, "draft_endpoint", None) or "").strip()
    return ep or None


def enhance_endpoint_for(spec: Any) -> str:
    ep = (getattr(spec, "enhance_endpoint", None) or "").strip()
    return ep or FLUX3_DRAFT_ENHANCE


def estimate_draft_cost_usd(spec: Any, *, duration_s: float) -> float | None:
    rate = getattr(spec, "cost_per_second_draft", None)
    if rate is None:
        if not model_supports_draft(spec):
            return None
        rate = DEFAULT_DRAFT_RATE
    secs = max(1.0, float(duration_s or 8))
    return round(float(rate) * secs, 3)


def estimate_full_cost_usd(
    spec: Any,
    *,
    duration_s: float,
    resolution: str | None = None,
    generate_audio: bool = False,
) -> float | None:
    """Full-quality estimate (same as normal generate)."""
    if hasattr(spec, "estimate_cost"):
        try:
            return spec.estimate_cost(
                duration_s,
                generate_audio=generate_audio,
                resolution=resolution,
            )
        except TypeError:
            pass
    rate = getattr(spec, "cost_per_second", None)
    by_res = getattr(spec, "cost_per_second_by_resolution", None) or {}
    if by_res:
        res = (resolution or getattr(spec, "default_resolution", None) or "720p")
        res = str(res).strip().lower()
        rate = by_res.get(res, rate)
    if rate is None:
        return None
    secs = max(1.0, float(duration_s or 8))
    return round(float(rate) * secs, 3)


def format_draft_vs_full_cost(
    spec: Any,
    *,
    duration_s: float,
    resolution: str | None = None,
    generate_audio: bool = False,
    draft_mode: bool = False,
) -> str:
    """Human cost line: draft vs full (or both)."""
    label = getattr(spec, "label", None) or getattr(spec, "key", "FLUX 3")
    secs = max(1.0, float(duration_s or 8))
    draft = estimate_draft_cost_usd(spec, duration_s=secs)
    full = estimate_full_cost_usd(
        spec, duration_s=secs, resolution=resolution, generate_audio=generate_audio
    )
    if draft_mode and draft is not None:
        unit = f"{int(round(secs))}s draft"
        return format_job_cost(draft, unit=unit, model=str(label))
    if full is not None:
        res = (resolution or getattr(spec, "default_resolution", None) or "").strip()
        unit = f"{int(round(secs))}s"
        if res:
            unit = f"{unit} · {res}"
        base = format_job_cost(full, unit=unit, model=str(label))
        if draft is not None and model_supports_draft(spec):
            return f"{base} · draft ~${draft:.2f}"
        return base
    if draft is not None:
        return format_job_cost(draft, unit=f"{int(round(secs))}s draft", model=str(label))
    return "Est. cost: —"


def strip_resolution_for_draft(arguments: dict[str, Any]) -> dict[str, Any]:
    """Draft OpenAPI has no resolution field."""
    out = dict(arguments)
    out.pop("resolution", None)
    return out


@dataclass
class DraftEnhanceResult:
    ok: bool
    path: str | None = None
    endpoint: str = FLUX3_DRAFT_ENHANCE
    status: str = ""
    notes: list[str] = field(default_factory=list)
    cost_estimate: str = ""
    metrics_line: str = ""
    timestamp: str = ""


def run_draft_enhance(
    *,
    draft_cache_url: str,
    output_dir: str | Path,
    prompt_hint: str = "flux3-enhance",
    model_key: str = "flux 3 enhance",
    safety_tolerance: int = 2,
    on_progress: ProgressCallback | None = None,
    duration_s: float | None = None,
    full_cost_usd: float | None = None,
) -> DraftEnhanceResult:
    """Run FLUX 3 draft-enhance from a stored draft_cache URL."""
    url = (draft_cache_url or "").strip()
    if not url:
        return DraftEnhanceResult(
            ok=False,
            status="Enhance to full needs a draft cache (run Draft first).",
        )

    def progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    endpoint = FLUX3_DRAFT_ENHANCE
    args = {
        "draft_cache_url": url,
        "safety_tolerance": int(safety_tolerance),
    }
    progress(f"FLUX 3 draft-enhance · {endpoint}")
    t0 = time.perf_counter()
    try:
        result = subscribe(endpoint, args, on_progress=progress)
    except FalClientError as exc:
        render_s = time.perf_counter() - t0
        return DraftEnhanceResult(
            ok=False,
            status=friendly_error(exc, context="FLUX 3 enhance"),
            metrics_line=format_render_metrics(render_s, None, cost_is_estimate=True),
        )
    except Exception as exc:
        return DraftEnhanceResult(
            ok=False,
            status=friendly_error(exc, context="FLUX 3 enhance"),
        )
    render_s = time.perf_counter() - t0
    out_url = extract_video_url(result)
    if not out_url:
        return DraftEnhanceResult(
            ok=False,
            status="draft-enhance returned no video.",
            metrics_line=format_render_metrics(render_s, None, cost_is_estimate=True),
        )

    stamp = timestamp_now()
    media_dir = job_media_dir(output_dir, stamp=stamp)
    stem = make_output_stem(prompt_hint, model_key, stamp=stamp, kind="video")
    dest = unique_path(media_dir, stem, ".mp4")
    try:
        download_url(out_url, dest, on_progress=progress, timeout=600.0)
    except FalClientError as exc:
        return DraftEnhanceResult(
            ok=False,
            status=str(exc),
            metrics_line=format_render_metrics(render_s, None, cost_is_estimate=True),
        )

    cost_usd = full_cost_usd
    metrics = format_render_metrics(render_s, cost_usd, cost_is_estimate=cost_usd is not None)
    cost_str = ""
    if cost_usd is not None:
        unit = f"{int(round(duration_s or 8))}s full" if duration_s else "full"
        cost_str = format_job_cost(cost_usd, unit=unit, model="FLUX 3 enhance")
    return DraftEnhanceResult(
        ok=True,
        path=str(dest.resolve()),
        endpoint=endpoint,
        status=f"Enhance to full OK — saved {Path(dest).name}.",
        cost_estimate=cost_str,
        metrics_line=metrics,
        timestamp=stamp,
        notes=["Used draft_cache → draft-enhance (full quality)."],
    )


def pick_draft_cache_from_result(result: dict[str, Any]) -> str | None:
    return extract_draft_cache_url(result)
