"""
Motion Sync — character still + driving video → motion transfer.

True motion-control endpoints only (image_url + video_url).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class MotionSyncModelSpec:
    key: str
    label: str
    endpoint: str
    # Cost estimate (output duration × rate)
    cost_per_second: float
    notes: str = ""
    # Kling: keep_original_sound; Wan: no native keep-audio (ignored)
    supports_keep_audio: bool = True
    default_keep_audio: bool = True
    # Kling character_orientation: image | video
    supports_character_orientation: bool = True
    default_character_orientation: str = "video"
    # Wan-only toggles
    supports_adapt_motion: bool = False
    default_adapt_motion: bool = True
    supports_enhance_identity: bool = False
    default_enhance_identity: bool = False
    # Soft duration guidance for UI tips (driving clip)
    min_duration_s: float = 3.0
    max_duration_s: float = 30.0
    best_for: str = ""
    extra_defaults: dict[str, Any] = field(default_factory=dict)


MOTION_SYNC_MODELS: dict[str, MotionSyncModelSpec] = {
    "kling motion control v3 pro": MotionSyncModelSpec(
        key="kling motion control v3 pro",
        label="Kling Motion Control V3 Pro",
        endpoint="fal-ai/kling-video/v3/pro/motion-control",
        cost_per_second=0.168,
        notes=(
            "Kling V3 Pro motion control — highest quality transfer of driving-clip "
            "motion onto a character still. Keep original audio when available. "
            "Est. ~$0.168/s of output."
        ),
        best_for="finished motion transfer, identity + motion quality",
        min_duration_s=3.0,
        max_duration_s=30.0,
    ),
    "kling motion control v3 standard": MotionSyncModelSpec(
        key="kling motion control v3 standard",
        label="Kling Motion Control V3 Standard",
        endpoint="fal-ai/kling-video/v3/standard/motion-control",
        cost_per_second=0.126,
        notes=(
            "Kling V3 Standard motion control — cost-effective motion transfer for "
            "portraits and simple full-body actions. Est. ~$0.126/s of output."
        ),
        best_for="iteration / simpler actions, lower cost",
        min_duration_s=3.0,
        max_duration_s=30.0,
    ),
    "kling 2.6 motion control": MotionSyncModelSpec(
        key="kling 2.6 motion control",
        label="Kling 2.6 Motion Control",
        endpoint="fal-ai/kling-video/v2.6/standard/motion-control",
        cost_per_second=0.07,
        notes=(
            "Kling 2.6 Standard motion control — budget motion transfer. "
            "Est. ~$0.07/s of output."
        ),
        best_for="budget drafts, short social hooks",
        min_duration_s=3.0,
        max_duration_s=30.0,
    ),
    "wan motion": MotionSyncModelSpec(
        key="wan motion",
        label="Wan Motion",
        endpoint="fal-ai/wan-motion",
        cost_per_second=0.08,  # ballpark; fal bills per output second
        notes=(
            "Wan Motion — driving video motion onto a reference still. "
            "Optional adapt-motion (body proportions) and enhance-identity. "
            "No keep-original-audio toggle. Est. ~$0.08/s (confirm on fal)."
        ),
        supports_keep_audio=False,
        default_keep_audio=False,
        supports_character_orientation=False,
        supports_adapt_motion=True,
        default_adapt_motion=True,
        supports_enhance_identity=True,
        default_enhance_identity=False,
        best_for="flexible proportions, optional identity boost",
        min_duration_s=2.0,
        max_duration_s=30.0,
        extra_defaults={"acceleration": "regular", "enable_safety_checker": True},
    ),
}


def motion_sync_model_labels() -> list[str]:
    return [s.label for s in MOTION_SYNC_MODELS.values()]


def find_motion_sync_model(label_or_key: str | None) -> MotionSyncModelSpec | None:
    if not label_or_key:
        return None
    raw = label_or_key.strip().lower()
    if raw in MOTION_SYNC_MODELS:
        return MOTION_SYNC_MODELS[raw]
    for spec in MOTION_SYNC_MODELS.values():
        if spec.label.lower() == raw or spec.key == raw:
            return spec
        if spec.endpoint.lower() == raw:
            return spec
    # loose contains
    for spec in MOTION_SYNC_MODELS.values():
        if raw in spec.label.lower() or raw in spec.key:
            return spec
    return None


def default_motion_sync_model() -> MotionSyncModelSpec:
    return MOTION_SYNC_MODELS["kling motion control v3 standard"]


def estimate_motion_sync_cost(
    spec: MotionSyncModelSpec,
    *,
    duration_s: float,
) -> float:
    secs = max(1.0, float(duration_s or 5.0))
    return round(float(spec.cost_per_second) * secs, 3)


def format_motion_sync_cost(
    spec: MotionSyncModelSpec,
    *,
    duration_s: float,
) -> str:
    from media_studio.pricing import format_job_cost

    amt = estimate_motion_sync_cost(spec, duration_s=duration_s)
    secs = int(round(float(duration_s or 0))) or 1
    return format_job_cost(amt, unit=f"{secs}s", model=spec.label)


def normalize_character_orientation(value: str | None) -> str:
    """Map UI labels / keys to API enum ``image`` | ``video``."""
    raw = (value or "video").strip().lower()
    if raw.startswith("image") or "match image" in raw:
        return "image"
    if raw.startswith("video") or "match video" in raw:
        return "video"
    if raw in ("image", "video"):
        return raw
    return "video"


def max_motion_duration_for_orientation(orientation: str | None) -> float:
    """
    Kling docs: orientation=video → up to 30s complex motion;
    orientation=image → up to 10s (camera follows image pose).
    Proxy prep prefers ≤10s for reliability; image ori hard-caps at 10s.
    """
    ori = normalize_character_orientation(orientation)
    if ori == "image":
        return 10.0
    return 10.0  # API allows 30s for video ori; we still prefer 10s for size/stability


def orientation_ui_labels() -> list[str]:
    return [
        "Match video (complex motion, ≤30s API)",
        "Match image (camera / pose lock, ≤10s)",
    ]


def orientation_ui_to_api(label: str | None) -> str:
    return normalize_character_orientation(label)


def build_motion_sync_arguments(
    spec: MotionSyncModelSpec,
    *,
    image_url: str,
    video_url: str,
    prompt: str | None = None,
    keep_original_sound: bool | None = None,
    character_orientation: str | None = None,
    adapt_motion: bool | None = None,
    enhance_identity: bool | None = None,
    acceleration: str | None = None,
) -> dict[str, Any]:
    """Build fal subscribe arguments for a motion-control endpoint."""
    if not image_url:
        raise ValueError("Character still is required (image_url).")
    if not video_url:
        raise ValueError("Motion reference video is required (video_url).")

    args: dict[str, Any] = {
        **(spec.extra_defaults or {}),
        "image_url": image_url,
        "video_url": video_url,
    }
    p = (prompt or "").strip()
    if p:
        args["prompt"] = p

    if spec.supports_keep_audio:
        keep = (
            bool(keep_original_sound)
            if keep_original_sound is not None
            else bool(spec.default_keep_audio)
        )
        args["keep_original_sound"] = keep

    if spec.supports_character_orientation:
        ori = normalize_character_orientation(
            character_orientation or spec.default_character_orientation
        )
        args["character_orientation"] = ori

    if spec.supports_adapt_motion:
        args["adapt_motion"] = (
            bool(adapt_motion)
            if adapt_motion is not None
            else bool(spec.default_adapt_motion)
        )

    if spec.supports_enhance_identity:
        args["enhance_identity"] = (
            bool(enhance_identity)
            if enhance_identity is not None
            else bool(spec.default_enhance_identity)
        )

    # Wan acceleration (none | regular) — only when endpoint is wan-motion
    if "wan-motion" in (spec.endpoint or "") and acceleration:
        acc = str(acceleration).strip().lower()
        if acc in ("none", "regular"):
            args["acceleration"] = acc

    return args


# Optional prompt seed chips (UI only — never required)
PROMPT_HELPER_CHIPS: tuple[str, ...] = (
    "modern porch exterior",
    "keep wardrobe",
    "photoreal natural light",
    "soft office interior",
    "listing outdoor walk-through",
)


def friendly_motion_sync_error(raw: str | Exception) -> str:
    """Map fal / prep errors to short user-facing copy."""
    msg = str(raw or "").strip()
    low = msg.lower()

    if not msg:
        return "Motion Sync failed."

    if "no person" in low or "person detected" in low or "no face" in low or "face not" in low:
        return (
            "No clear person detected in the character still or motion clip. "
            "Use a full-body or clear upper-body subject with the head visible and unobstructed."
        )
    if "too short" in low or "duration is too short" in low or "minimum duration" in low:
        return (
            "Motion reference is too short after prep. Use a driving clip of at least ~3s "
            "with clear subject motion."
        )
    if "too long" in low and "proxy" not in low:
        return (
            "Motion reference is still too long for this orientation/model. "
            "Try Match image (≤10s) or a shorter 3–10s clip."
        )
    if "unsupported" in low and ("format" in low or "codec" in low or "media" in low):
        return (
            "Unsupported media format. Use a common still (PNG/JPG) and video (MP4/MOV) "
            "and retry — or re-export a Render-in-Place proxy from Resolve."
        )
    if "file too large" in low or "too large for the api" in low:
        return (
            "File still too large for the API after auto-proxy. "
            "Export a shorter 3–8s 1080p (or 720p) Render-in-Place clip and retry."
        )
    if "ffmpeg" in low and ("not found" in low or "missing" in low):
        return (
            "Could not build an optimized proxy (ffmpeg not available). "
            "Install ffmpeg or export a shorter ≤10s / ≤100 MB motion clip yourself."
        )
    if "could not prepare" in low:
        return msg
    # Keep original if already friendly
    if msg.startswith("Motion Sync"):
        return msg
    return f"Motion Sync: {msg}"
