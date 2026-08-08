"""
Creative Vision model registry — T2I, I2I, T2V, I2V, bridge.

Cinematic invention only (not listing camera-lock staging). Costs are
intentionally conservative ballparks — show them before generate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

VisionMode = Literal[
    "text_to_image",
    "image_to_image",
    "reference_to_image",  # R2I — build still from identity/style/prop refs
    "text_to_video",
    "image_to_video",
    "reference_to_video",  # R2V — multi identity / omni refs (not start-frame lock)
    "video_to_video",  # V2V — source clip + prompt (align with Studio)
    "bridge",
    "extend",
]

# UI pill rows (aligned with Studio naming: T2I/I2I/R2I · I2V/T2V/R2V/V2V)
VISION_IMAGE_PILLS: tuple[tuple[str, str], ...] = (
    ("text_to_image", "Text→Image"),
    ("image_to_image", "Image→Image"),
    ("reference_to_image", "R2I"),
)
VISION_VIDEO_PILLS: tuple[tuple[str, str], ...] = (
    ("text_to_video", "Text→Video"),
    ("image_to_video", "Image→Video"),
    ("reference_to_video", "R2V"),
    ("video_to_video", "V2V"),
    ("bridge", "Bridge/Connect"),
    ("extend", "Extend Video"),
)


@dataclass(frozen=True)
class VisionModelSpec:
    key: str
    label: str
    mode: VisionMode
    endpoint: str
    # Flat estimate for default duration (shown when no length yet)
    cost_estimate_usd: float
    notes: str = ""
    cost_per_second: float | None = None
    # e.g. {"720p": 0.17, "1080p": 0.29} — overrides flat cost_per_second by res
    cost_per_second_by_resolution: dict[str, float] = field(default_factory=dict)
    # FLUX 3 draft workflow
    draft_endpoint: str | None = None
    enhance_endpoint: str | None = None
    cost_per_second_draft: float | None = None
    # Duration API shape
    duration_param: str = "duration"
    duration_choices: tuple[str, ...] = ("4s", "6s", "8s")
    default_duration: str = "8s"
    # Aspect
    aspect_choices: tuple[str, ...] = ("16:9", "9:16")
    default_aspect: str = "16:9"
    resolution_choices: tuple[str, ...] = ("720p", "1080p")
    default_resolution: str = "720p"
    supports_audio: bool = True
    supports_negative: bool = True
    # Reference stills: T2V reference pack size, or I2I max *extra* refs (0 = primary only)
    max_refs: int = 0
    # Bridge: first + last frame field names
    first_frame_field: str = "first_frame_url"
    last_frame_field: str = "last_frame_url"
    # I2V start frame / I2I source field
    image_field: str = "image_url"
    # Extend / V2V-style: source clip field
    video_field: str = "video_url"
    # I2V optional end frame (e.g. Hailuo / MiniMax H3) — hide UI when False
    supports_end_frame: bool = False
    # Dedicated first→last endpoints require both frames
    requires_end_frame: bool = False
    # Omni reference-to-video (MiniMax H3): images + videos + audio
    omni_reference: bool = False
    max_ref_videos: int = 0
    max_ref_audios: int = 0
    max_total_refs: int = 0  # 0 = no combined cap; H3 = 12
    # Duration sent as integer seconds (H3) vs string enums
    duration_as_int: bool = False
    # Native stereo always on output — hide generate_audio; show note in UI
    native_stereo_audio: bool = False
    # Prompt citation: "plain" → Image 1 / Video 1; "at" → @Image1
    prompt_citation_style: str = ""
    # Image→Image: key into fal IMAGE_EDIT_MODELS for build_edit_arguments
    edit_model_key: str = ""
    # Show strength slider when True (passed if API accepts)
    supports_strength: bool = False
    # Max images per single fal call (T2I multi-variant). UI may request more
    # and vision_service will run sequential calls when needed.
    max_num_images: int = 1
    # Never send aspect_ratio (e.g. FLUX 3 I2V — frame follows the still)
    omit_aspect_ratio: bool = False
    extra_defaults: dict[str, Any] = field(default_factory=dict)


# UI sentinel when aspect follows the still (disabled control)
ASPECT_FOLLOWS_STILL = "Follows still"


# UI batch cap for still multi-variant generate (Phase 2)
VISION_BATCH_MAX = 4


# Friendly aspect labels for Flux / Seedream image_size enums
T2I_ASPECT_CHOICES: tuple[str, ...] = (
    "16:9 landscape",
    "9:16 portrait",
    "4:3 landscape",
    "3:4 portrait",
    "1:1 square",
    "1:1 square HD",
)

# Nano Banana family uses colon aspect ratios (+ resolution on 2/Pro)
T2I_NANO_ASPECT_CHOICES: tuple[str, ...] = (
    "16:9",
    "9:16",
    "4:3",
    "3:4",
    "1:1",
    "3:2",
    "2:3",
    "21:9",
)

T2I_NANO2_RES_CHOICES: tuple[str, ...] = ("0.5K", "1K", "2K", "4K")
T2I_NANO_PRO_RES_CHOICES: tuple[str, ...] = ("1K", "2K", "4K")

# Seedream: image_size presets (+ auto 2K/4K where supported)
T2I_SEEDREAM_ASPECT_CHOICES: tuple[str, ...] = (
    "16:9 landscape",
    "9:16 portrait",
    "4:3 landscape",
    "3:4 portrait",
    "1:1 square",
    "1:1 square HD",
    "Auto 2K",
    "Auto 4K",
)

_T2I_ASPECT_TO_IMAGE_SIZE: dict[str, str] = {
    "16:9 landscape": "landscape_16_9",
    "9:16 portrait": "portrait_16_9",
    "4:3 landscape": "landscape_4_3",
    "3:4 portrait": "portrait_4_3",
    "1:1 square": "square",
    "1:1 square hd": "square_hd",
    "landscape_16_9": "landscape_16_9",
    "portrait_16_9": "portrait_16_9",
    "landscape_4_3": "landscape_4_3",
    "portrait_4_3": "portrait_4_3",
    "square": "square",
    "square_hd": "square_hd",
    "auto 2k": "auto_2K",
    "auto 4k": "auto_4K",
    "auto 1k": "auto_1K",
    "auto_2k": "auto_2K",
    "auto_4k": "auto_4K",
    "auto_1k": "auto_1K",
}


def map_t2i_image_size(aspect_label: str | None) -> str:
    """Map UI aspect label → fal image_size enum (Flux / Seedream)."""
    raw = (aspect_label or "").strip().lower()
    if not raw:
        return "landscape_16_9"
    if raw in _T2I_ASPECT_TO_IMAGE_SIZE:
        return _T2I_ASPECT_TO_IMAGE_SIZE[raw]
    # Bare ratios (Scenes / simple pickers) + HD square
    bare = raw.replace(" ", "")
    if "hd" in raw and ("1:1" in bare or "square" in raw):
        return "square_hd"
    bare_map = {
        "16:9": "landscape_16_9",
        "9:16": "portrait_16_9",
        "4:3": "landscape_4_3",
        "3:4": "portrait_4_3",
        "1:1": "square",
        "3:2": "landscape_16_9",
        "2:3": "portrait_16_9",
        "21:9": "landscape_16_9",
        "9:21": "portrait_16_9",
    }
    if bare in bare_map:
        return bare_map[bare]
    # Substring fallback (e.g. "Horizontal · 16:9")
    for tok, size in (
        ("9:16", "portrait_16_9"),
        ("16:9", "landscape_16_9"),
        ("3:4", "portrait_4_3"),
        ("4:3", "landscape_4_3"),
        ("1:1", "square"),
    ):
        if tok in bare:
            if tok == "1:1" and "hd" in raw:
                return "square_hd"
            return size
    return "landscape_16_9"


def map_t2i_aspect_colon(aspect_label: str | None) -> str:
    """Map UI aspect label → '16:9' style string for Nano Banana / Recraft / Ultra."""
    raw = (aspect_label or "").strip().lower()
    if not raw:
        return "16:9"
    bare = raw.replace(" ", "")
    # Prefer longer tokens first so 9:16 wins over 16:9 substring false positives
    for tok in (
        "21:9",
        "9:21",
        "16:9",
        "9:16",
        "4:3",
        "3:4",
        "3:2",
        "2:3",
        "5:4",
        "4:5",
        "1:1",
    ):
        if tok in bare:
            return tok
    size = map_t2i_image_size(aspect_label)
    return {
        "landscape_16_9": "16:9",
        "portrait_16_9": "9:16",
        "landscape_4_3": "4:3",
        "portrait_4_3": "3:4",
        "square": "1:1",
        "square_hd": "1:1",
    }.get(size, "16:9")


# ---------------------------------------------------------------------------
# Text → Image (pure T2I — no source still required)
# ---------------------------------------------------------------------------

T2I_MODELS: dict[str, VisionModelSpec] = {
    "flux 2 pro t2i": VisionModelSpec(
        key="flux 2 pro t2i",
        label="Flux 2 Pro (T2I)",
        mode="text_to_image",
        endpoint="fal-ai/flux-2-pro",
        cost_estimate_usd=0.04,
        notes=(
            "Default. Studio-grade Flux 2 Pro text→image. Nail an end/start still "
            "cheaply before expensive Veo bridge. ~$0.03–0.05 / image."
        ),
        duration_choices=(),
        default_duration="",
        aspect_choices=T2I_ASPECT_CHOICES,
        default_aspect="16:9 landscape",
        resolution_choices=(),
        default_resolution="",
        supports_audio=False,
        supports_negative=False,
        max_num_images=4,
        extra_defaults={"num_images": 1, "output_format": "jpeg", "safety_tolerance": "4"},
    ),
    "flux 2 t2i": VisionModelSpec(
        key="flux 2 t2i",
        label="Flux 2 (T2I · cheaper)",
        mode="text_to_image",
        endpoint="fal-ai/flux-2",
        cost_estimate_usd=0.02,
        notes="Flux 2 [dev] text→image — faster/cheaper iteration. ~$0.012/MP.",
        duration_choices=(),
        default_duration="",
        aspect_choices=T2I_ASPECT_CHOICES,
        default_aspect="16:9 landscape",
        resolution_choices=(),
        default_resolution="",
        supports_audio=False,
        supports_negative=False,
        max_num_images=4,
        extra_defaults={"num_images": 1, "output_format": "jpeg"},
    ),
    "flux 2 flex t2i": VisionModelSpec(
        key="flux 2 flex t2i",
        label="Flux 2 Flex (T2I)",
        mode="text_to_image",
        endpoint="fal-ai/flux-2-flex",
        cost_estimate_usd=0.05,
        notes="Flux 2 Flex — more control / quality tradeoff. ~$0.05/MP.",
        duration_choices=(),
        default_duration="",
        aspect_choices=T2I_ASPECT_CHOICES,
        default_aspect="16:9 landscape",
        resolution_choices=(),
        default_resolution="",
        supports_audio=False,
        supports_negative=False,
        max_num_images=4,
        extra_defaults={"num_images": 1, "output_format": "jpeg"},
    ),
    "flux 1.1 pro ultra t2i": VisionModelSpec(
        key="flux 1.1 pro ultra t2i",
        label="Flux 1.1 Pro Ultra (T2I)",
        mode="text_to_image",
        endpoint="fal-ai/flux-pro/v1.1-ultra",
        cost_estimate_usd=0.06,
        notes="Flux 1.1 Pro Ultra — high-res photoreal stills (up to ~2K).",
        duration_choices=(),
        default_duration="",
        aspect_choices=T2I_ASPECT_CHOICES,
        default_aspect="16:9 landscape",
        resolution_choices=(),
        default_resolution="",
        supports_audio=False,
        supports_negative=False,
        max_num_images=4,
        extra_defaults={"num_images": 1, "output_format": "jpeg", "safety_tolerance": "2"},
    ),
    "recraft v3 t2i": VisionModelSpec(
        key="recraft v3 t2i",
        label="Recraft V3 (T2I)",
        mode="text_to_image",
        endpoint="fal-ai/recraft/v3/text-to-image",
        cost_estimate_usd=0.04,
        notes="Recraft V3 text→image — strong design/illustration alternative.",
        duration_choices=(),
        default_duration="",
        aspect_choices=("16:9 landscape", "9:16 portrait", "1:1 square", "4:3 landscape"),
        default_aspect="16:9 landscape",
        resolution_choices=(),
        default_resolution="",
        supports_audio=False,
        supports_negative=False,
        max_num_images=1,
        extra_defaults={},
    ),
    # --- Nano Banana family ---
    "nano banana t2i": VisionModelSpec(
        key="nano banana t2i",
        label="Nano Banana (T2I)",
        mode="text_to_image",
        endpoint="fal-ai/nano-banana",
        cost_estimate_usd=0.04,
        notes="Nano Banana text→image — solid general stills, many aspect ratios.",
        duration_choices=(),
        default_duration="",
        aspect_choices=T2I_NANO_ASPECT_CHOICES,
        default_aspect="16:9",
        resolution_choices=(),
        default_resolution="",
        supports_audio=False,
        supports_negative=False,
        max_num_images=4,
        extra_defaults={"num_images": 1, "output_format": "jpeg", "safety_tolerance": "4"},
    ),
    "nano banana 2 t2i": VisionModelSpec(
        key="nano banana 2 t2i",
        label="Nano Banana 2 (T2I · fast)",
        mode="text_to_image",
        endpoint="fal-ai/nano-banana-2",
        cost_estimate_usd=0.06,
        notes=(
            "Nano Banana 2 — faster T2I with resolution control (0.5K–4K). "
            "Good for quick end-frame exploration before video."
        ),
        duration_choices=(),
        default_duration="",
        aspect_choices=T2I_NANO_ASPECT_CHOICES,
        default_aspect="16:9",
        resolution_choices=T2I_NANO2_RES_CHOICES,
        default_resolution="1K",
        supports_audio=False,
        supports_negative=False,
        max_num_images=4,
        extra_defaults={"num_images": 1, "output_format": "jpeg", "safety_tolerance": "4"},
    ),
    "nano banana pro t2i": VisionModelSpec(
        key="nano banana pro t2i",
        label="Nano Banana Pro (T2I)",
        mode="text_to_image",
        endpoint="fal-ai/nano-banana-pro",
        cost_estimate_usd=0.12,
        notes=(
            "Nano Banana Pro — higher adherence T2I; resolution 1K/2K/4K. "
            "Pricier stills; great when prompt fidelity matters."
        ),
        duration_choices=(),
        default_duration="",
        aspect_choices=T2I_NANO_ASPECT_CHOICES,
        default_aspect="16:9",
        resolution_choices=T2I_NANO_PRO_RES_CHOICES,
        default_resolution="1K",
        supports_audio=False,
        supports_negative=False,
        max_num_images=4,
        extra_defaults={"num_images": 1, "output_format": "jpeg", "safety_tolerance": "4"},
    ),
    # --- Seedream family ---
    "seedream 4.5 t2i": VisionModelSpec(
        key="seedream 4.5 t2i",
        label="Seedream 4.5 (T2I)",
        mode="text_to_image",
        endpoint="fal-ai/bytedance/seedream/v4.5/text-to-image",
        cost_estimate_usd=0.05,
        notes="ByteDance Seedream 4.5 text→image — strong detail / listing-friendly stills.",
        duration_choices=(),
        default_duration="",
        aspect_choices=T2I_SEEDREAM_ASPECT_CHOICES,
        default_aspect="16:9 landscape",
        resolution_choices=(),
        default_resolution="",
        supports_audio=False,
        supports_negative=False,
        max_num_images=4,
        extra_defaults={"num_images": 1, "enable_safety_checker": True},
    ),
    "seedream 5 lite t2i": VisionModelSpec(
        key="seedream 5 lite t2i",
        label="Seedream 5.0 Lite (T2I · cheaper)",
        mode="text_to_image",
        endpoint="fal-ai/bytedance/seedream/v5/lite/text-to-image",
        cost_estimate_usd=0.03,
        notes="Seedream 5 Lite — cheaper/faster Seedream 5 T2I for iteration.",
        duration_choices=(),
        default_duration="",
        aspect_choices=T2I_SEEDREAM_ASPECT_CHOICES,
        default_aspect="16:9 landscape",
        resolution_choices=(),
        default_resolution="",
        supports_audio=False,
        supports_negative=False,
        max_num_images=4,
        extra_defaults={"num_images": 1, "enable_safety_checker": True},
    ),
    "seedream 5 pro t2i": VisionModelSpec(
        key="seedream 5 pro t2i",
        label="Seedream 5.0 Pro (T2I)",
        mode="text_to_image",
        endpoint="bytedance/seedream/v5/pro/text-to-image",
        cost_estimate_usd=0.07,
        notes=(
            "Seedream 5 Pro text→image — highest Seedream T2I quality on fal "
            "(stable pro T2I endpoint)."
        ),
        duration_choices=(),
        default_duration="",
        # Pro image_size: no auto_4K; keep Auto 2K + presets
        aspect_choices=(
            "16:9 landscape",
            "9:16 portrait",
            "4:3 landscape",
            "3:4 portrait",
            "1:1 square",
            "1:1 square HD",
            "Auto 2K",
        ),
        default_aspect="16:9 landscape",
        resolution_choices=(),
        default_resolution="",
        supports_audio=False,
        supports_negative=False,
        max_num_images=4,
        extra_defaults={
            "num_images": 1,
            "enable_safety_checker": True,
            "output_format": "jpeg",
        },
    ),
}

# ---------------------------------------------------------------------------
# Image → Image (creative still edit — Aleph plate / source still)
# Endpoints mirror Studio image-edit models via edit_model_key.
# ---------------------------------------------------------------------------

I2I_ASPECT_CHOICES: tuple[str, ...] = (
    "Match source",
    "16:9 landscape",
    "9:16 portrait",
    "4:3 landscape",
    "3:4 portrait",
    "1:1 square",
    "1:1 square HD",
)

# I2I multi-ref: max_refs = max *extra* reference stills (primary is separate).
# Cap extras at 3 in UI even when the edit model allows more inputs.
I2I_MAX_EXTRA_REFS = 3

I2I_MODELS: dict[str, VisionModelSpec] = {
    "flux 2 pro i2i": VisionModelSpec(
        key="flux 2 pro i2i",
        label="Flux 2 Pro (edit)",
        mode="image_to_image",
        endpoint="fal-ai/flux-2-pro/edit",
        cost_estimate_usd=0.03,
        notes=(
            "Default. Creative edit via Flux 2 Pro. Multi-ref: primary + up to 3 refs "
            "(identity / material / furniture). ~$0.03/image."
        ),
        duration_choices=(),
        default_duration="",
        aspect_choices=I2I_ASPECT_CHOICES,
        default_aspect="Match source",
        resolution_choices=(),
        default_resolution="",
        supports_audio=False,
        supports_negative=False,
        max_refs=3,
        image_field="image_urls",
        edit_model_key="flux 2 pro",
        supports_strength=True,
        extra_defaults={"num_images": 1, "output_format": "jpeg", "safety_tolerance": "4"},
    ),
    "flux 2 max i2i": VisionModelSpec(
        key="flux 2 max i2i",
        label="Flux 2 Max (edit)",
        mode="image_to_image",
        endpoint="fal-ai/flux-2-max/edit",
        cost_estimate_usd=0.07,
        notes=(
            "Highest quality Flux edit. Multi-ref supported (primary + up to 3). "
            "~$0.07 first MP."
        ),
        duration_choices=(),
        default_duration="",
        aspect_choices=I2I_ASPECT_CHOICES,
        default_aspect="Match source",
        resolution_choices=(),
        default_resolution="",
        supports_audio=False,
        supports_negative=False,
        max_refs=3,
        image_field="image_urls",
        edit_model_key="flux 2 max",
        supports_strength=True,
        extra_defaults={"num_images": 1, "output_format": "jpeg"},
    ),
    "flux 2 flex i2i": VisionModelSpec(
        key="flux 2 flex i2i",
        label="Flux 2 Flex (edit)",
        mode="image_to_image",
        endpoint="fal-ai/flux-2-flex/edit",
        cost_estimate_usd=0.04,
        notes="Flux 2 Flex edit. Multi-ref (primary + up to 3). ~$0.04/image.",
        duration_choices=(),
        default_duration="",
        aspect_choices=I2I_ASPECT_CHOICES,
        default_aspect="Match source",
        resolution_choices=(),
        default_resolution="",
        supports_audio=False,
        supports_negative=False,
        max_refs=3,
        image_field="image_urls",
        edit_model_key="flux 2 flex",
        supports_strength=True,
        extra_defaults={"num_images": 1, "output_format": "jpeg"},
    ),
    "flux kontext pro i2i": VisionModelSpec(
        key="flux kontext pro i2i",
        label="Flux Kontext Pro (edit)",
        mode="image_to_image",
        endpoint="fal-ai/flux-pro/kontext",
        cost_estimate_usd=0.04,
        notes=(
            "Flux Kontext Pro — single-image only (extra refs hidden). "
            "Strong subject/context preservation."
        ),
        duration_choices=(),
        default_duration="",
        aspect_choices=("Match source", "16:9", "9:16", "4:3", "3:4", "1:1", "3:2", "2:3"),
        default_aspect="Match source",
        resolution_choices=(),
        default_resolution="",
        supports_audio=False,
        supports_negative=False,
        max_refs=0,
        image_field="image_url",
        edit_model_key="flux kontext pro",
        supports_strength=True,
        extra_defaults={},
    ),
    "nano banana pro i2i": VisionModelSpec(
        key="nano banana pro i2i",
        label="Nano Banana Pro (edit)",
        mode="image_to_image",
        endpoint="fal-ai/nano-banana-pro/edit",
        cost_estimate_usd=0.15,
        notes=(
            "Nano Banana Pro edit — multi-ref (primary + up to 3). "
            "Excellent prompt adherence. 1K/2K/4K."
        ),
        duration_choices=(),
        default_duration="",
        aspect_choices=("Match source",) + T2I_NANO_ASPECT_CHOICES,
        default_aspect="Match source",
        resolution_choices=T2I_NANO_PRO_RES_CHOICES,
        default_resolution="1K",
        supports_audio=False,
        supports_negative=False,
        max_refs=3,
        image_field="image_urls",
        edit_model_key="nano banana pro",
        supports_strength=False,
        extra_defaults={"num_images": 1},
    ),
    "nano banana 2 i2i": VisionModelSpec(
        key="nano banana 2 i2i",
        label="Nano Banana 2 (edit · fast)",
        mode="image_to_image",
        endpoint="fal-ai/nano-banana-2/edit",
        cost_estimate_usd=0.08,
        notes="Nano Banana 2 edit — multi-ref (primary + up to 3). Faster/cheaper. 0.5K–4K.",
        duration_choices=(),
        default_duration="",
        aspect_choices=("Match source",) + T2I_NANO_ASPECT_CHOICES,
        default_aspect="Match source",
        resolution_choices=T2I_NANO2_RES_CHOICES,
        default_resolution="1K",
        supports_audio=False,
        supports_negative=False,
        max_refs=3,
        image_field="image_urls",
        edit_model_key="nano banana 2",
        supports_strength=False,
        extra_defaults={"num_images": 1},
    ),
    "nano banana i2i": VisionModelSpec(
        key="nano banana i2i",
        label="Nano Banana (edit)",
        mode="image_to_image",
        endpoint="fal-ai/nano-banana/edit",
        cost_estimate_usd=0.04,
        notes="Original Nano Banana edit — multi-ref (primary + up to 3).",
        duration_choices=(),
        default_duration="",
        aspect_choices=("Match source",) + T2I_NANO_ASPECT_CHOICES,
        default_aspect="Match source",
        resolution_choices=("1K",),
        default_resolution="1K",
        supports_audio=False,
        supports_negative=False,
        max_refs=3,
        image_field="image_urls",
        edit_model_key="nano banana",
        supports_strength=False,
        extra_defaults={"num_images": 1},
    ),
    "seedream 5 pro i2i": VisionModelSpec(
        key="seedream 5 pro i2i",
        label="Seedream 5.0 Pro (edit)",
        mode="image_to_image",
        endpoint="bytedance/seedream/v5/pro/edit",
        cost_estimate_usd=0.07,
        notes=(
            "Seedream 5 Pro edit — multi-ref (primary + up to 3). "
            "Grounded still edits; listing-friendly detail."
        ),
        duration_choices=(),
        default_duration="",
        aspect_choices=I2I_ASPECT_CHOICES + ("Auto 2K", "Auto 4K"),
        default_aspect="Match source",
        resolution_choices=(),
        default_resolution="",
        supports_audio=False,
        supports_negative=False,
        max_refs=3,
        image_field="image_urls",
        edit_model_key="seedream 5 pro",
        supports_strength=False,
        extra_defaults={"num_images": 1, "enable_safety_checker": True},
    ),
}

# ---------------------------------------------------------------------------
# Text → Video
# ---------------------------------------------------------------------------

T2V_MODELS: dict[str, VisionModelSpec] = {
    "veo 3.1": VisionModelSpec(
        key="veo 3.1",
        label="Veo 3.1",
        mode="text_to_video",
        endpoint="fal-ai/veo3.1",
        # fal billing: $0.40/s (user invoice)
        cost_estimate_usd=3.20,  # 8s × $0.40
        cost_per_second=0.40,
        notes="Highest quality T2V. ~$0.40/s on fal. 4/6/8s · 16:9 or 9:16 · optional audio.",
        default_duration="8s",
        extra_defaults={"generate_audio": True, "auto_fix": True, "safety_tolerance": "4"},
    ),
    "veo 3.1 fast": VisionModelSpec(
        key="veo 3.1 fast",
        label="Veo 3.1 Fast",
        mode="text_to_video",
        endpoint="fal-ai/veo3.1/fast",
        # fal billing: $0.15/s (fast family)
        cost_estimate_usd=0.90,  # 6s × $0.15
        cost_per_second=0.15,
        notes="Faster/cheaper Veo 3.1. ~$0.15/s on fal. Good default for exploration.",
        default_duration="6s",
        extra_defaults={"generate_audio": True, "auto_fix": True, "safety_tolerance": "4"},
    ),
    "luma ray 2": VisionModelSpec(
        key="luma ray 2",
        label="Luma Ray 2",
        mode="text_to_video",
        endpoint="fal-ai/luma-dream-machine/ray-2",
        cost_estimate_usd=0.35,
        cost_per_second=0.06,
        notes="Strong cinematic T2V alternative. Duration/aspect per Luma API.",
        duration_choices=("5s", "9s"),
        default_duration="5s",
        aspect_choices=("16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "9:21"),
        supports_audio=False,
        supports_negative=False,
        resolution_choices=("540p", "720p", "1080p"),
        default_resolution="720p",
        extra_defaults={"loop": False},
    ),
    "minimax h3 t2v": VisionModelSpec(
        key="minimax h3 t2v",
        label="MiniMax H3 · Text→Video",
        mode="text_to_video",
        endpoint="minimax/h3/text-to-video",
        cost_estimate_usd=1.30,  # 5s × $0.26
        cost_per_second=0.26,
        notes=(
            "MiniMax H3 (Hailuo-03) T2V — 5–15s · 2K · native stereo audio. "
            "Est. ~$0.26/s @2K. Prefer Omni when you have stills/motion/audio refs."
        ),
        duration_choices=tuple(str(i) for i in range(5, 16)),
        default_duration="5",
        aspect_choices=("21:9", "16:9", "4:3", "1:1", "3:4", "9:16"),
        default_aspect="16:9",
        resolution_choices=("2K",),
        default_resolution="2K",
        supports_audio=False,  # native stereo always; no toggle
        supports_negative=False,
        duration_as_int=True,
        native_stereo_audio=True,
    ),
    "grok imagine 1.5 t2v": VisionModelSpec(
        key="grok imagine 1.5 t2v",
        label="Grok Imagine 1.5 · Text→Video",
        mode="text_to_video",
        endpoint="xai/grok-imagine-video/v1.5/text-to-video",
        cost_estimate_usd=0.84,  # 6s × $0.14 @720p
        cost_per_second=0.14,
        notes=(
            "xAI Grok Imagine Video 1.5 T2V — strong motion quality + native audio. "
            "1–15s · 480p/720p/1080p. Est. $0.08/s @480p, $0.14/s @720p, $0.25/s @1080p."
        ),
        duration_choices=tuple(str(i) for i in range(1, 16)),
        default_duration="6",
        aspect_choices=("16:9", "4:3", "3:2", "1:1", "2:3", "3:4", "9:16"),
        default_aspect="16:9",
        resolution_choices=("480p", "720p", "1080p"),
        default_resolution="720p",
        supports_audio=False,  # native audio always
        supports_negative=False,
        duration_as_int=True,
        native_stereo_audio=True,
    ),
    "flux 3 t2v": VisionModelSpec(
        key="flux 3 t2v",
        label="FLUX 3 · Text→Video",
        mode="text_to_video",
        endpoint="blackforestlabs/flux-3/text-to-video",
        cost_estimate_usd=1.36,  # 8s × $0.17 @720p
        cost_per_second=0.17,
        cost_per_second_by_resolution={"720p": 0.17, "1080p": 0.29},
        draft_endpoint="blackforestlabs/flux-3/text-to-video/draft",
        enhance_endpoint="blackforestlabs/flux-3/draft-enhance",
        cost_per_second_draft=0.06,
        notes=(
            "FLUX 3 (BFL on fal) T2V — full quality with optional native audio. "
            "5–20s or auto · 720p/1080p. Draft first → Enhance to full. "
            "Est. ~$0.17/s @720p · ~$0.29/s @1080p · draft ~$0.06/s."
        ),
        duration_choices=("auto",) + tuple(str(i) for i in range(5, 21)),
        default_duration="8",
        aspect_choices=(
            "auto", "21:9", "2:1", "16:9", "4:3", "1:1", "3:4", "9:16",
        ),
        default_aspect="auto",
        resolution_choices=("720p", "1080p"),
        default_resolution="720p",
        supports_audio=True,
        supports_negative=False,
        duration_as_int=True,
        extra_defaults={"generate_audio": True, "safety_tolerance": 2},
    ),
    "seedance 2.5 t2v": VisionModelSpec(
        key="seedance 2.5 t2v",
        label="Seedance 2.5 · Text→Video",
        mode="text_to_video",
        endpoint="bytedance/seedance-2.5/text-to-video",
        # 5s @720p 16:9 ≈ $2.31 (token formula); UI scales by duration
        cost_estimate_usd=2.31,
        cost_per_second=0.473,  # approx 16:9 720p; estimate_vision_cost uses tokens
        cost_per_second_by_resolution={"480p": 0.2205, "720p": 0.473},
        notes=(
            "ByteDance Seedance 2.5 T2V — up to 30s single-pass with native audio. "
            "480p/720p · duration auto or 4–30s · aspect auto|ratios. "
            "Token billing ~$0.0214/1k tokens (≈$0.47/s @720p 16:9). "
            "Partner photoreal-face filter may reject some people prompts."
        ),
        duration_choices=("auto",) + tuple(str(i) for i in range(4, 31)),
        default_duration="5",
        aspect_choices=(
            "auto",
            "21:9",
            "16:9",
            "4:3",
            "1:1",
            "3:4",
            "9:16",
        ),
        default_aspect="auto",
        resolution_choices=("480p", "720p"),
        default_resolution="720p",
        supports_audio=True,
        supports_negative=False,
        duration_as_int=False,
        extra_defaults={"generate_audio": True},
    ),
}

# ---------------------------------------------------------------------------
# Image → Video
# ---------------------------------------------------------------------------

I2V_MODELS: dict[str, VisionModelSpec] = {
    "veo 3.1 fast i2v": VisionModelSpec(
        key="veo 3.1 fast i2v",
        label="Veo 3.1 Fast · Image→Video",
        mode="image_to_video",
        endpoint="fal-ai/veo3.1/fast/image-to-video",
        # fal billing: $0.15/s
        cost_estimate_usd=0.90,  # 6s × $0.15
        cost_per_second=0.15,
        notes="Faster still → move. ~$0.15/s on fal. Recommended default for I2V experiments.",
        default_duration="6s",
        aspect_choices=("auto", "16:9", "9:16"),
        default_aspect="auto",
        extra_defaults={"generate_audio": True, "auto_fix": False, "safety_tolerance": "4"},
    ),
    "veo 3.1 i2v": VisionModelSpec(
        key="veo 3.1 i2v",
        label="Veo 3.1 · Image→Video",
        mode="image_to_video",
        endpoint="fal-ai/veo3.1/image-to-video",
        # fal billing: $0.40/s (user invoice)
        cost_estimate_usd=3.20,  # 8s × $0.40
        cost_per_second=0.40,
        notes="Still → cinematic move. ~$0.40/s on fal. Keep architecture in the prompt.",
        aspect_choices=("auto", "16:9", "9:16"),
        default_aspect="auto",
        extra_defaults={"generate_audio": True, "auto_fix": False, "safety_tolerance": "4"},
    ),
    "kling o3 pro i2v": VisionModelSpec(
        key="kling o3 pro i2v",
        label="Kling O3 Pro · Image→Video",
        mode="image_to_video",
        endpoint="fal-ai/kling-video/o3/pro/image-to-video",
        cost_estimate_usd=0.45,
        cost_per_second=0.07,
        notes="Strong motion from a still. Uses existing Studio I2V family pricing ballpark.",
        duration_choices=("5", "10"),
        default_duration="5",
        aspect_choices=("16:9", "9:16", "1:1"),
        supports_audio=False,
        resolution_choices=(),
        extra_defaults={},
    ),
    "seedance 2.0 i2v": VisionModelSpec(
        key="seedance 2.0 i2v",
        label="Seedance 2.0 · Image→Video",
        mode="image_to_video",
        endpoint="bytedance/seedance-2.0/image-to-video",
        cost_estimate_usd=0.30,
        cost_per_second=0.05,
        notes="ByteDance I2V. Good motion value.",
        duration_choices=("5", "8", "10"),
        default_duration="5",
        supports_audio=False,
        resolution_choices=(),
        extra_defaults={},
    ),
    "seedance 2.5 i2v": VisionModelSpec(
        key="seedance 2.5 i2v",
        label="Seedance 2.5 · Image→Video",
        mode="image_to_video",
        endpoint="bytedance/seedance-2.5/image-to-video",
        cost_estimate_usd=2.31,
        cost_per_second=0.473,
        cost_per_second_by_resolution={"480p": 0.2205, "720p": 0.473},
        notes=(
            "Seedance 2.5 I2V — animate a still up to 30s with native audio. "
            "Optional end frame. 480p/720p · duration auto|4–30. "
            "Token est. ~$0.0214/1k tokens (image refs not billed). "
            "Partner photoreal-face filter may reject photoreal people stills."
        ),
        duration_choices=("auto",) + tuple(str(i) for i in range(4, 31)),
        default_duration="5",
        aspect_choices=(
            "auto",
            "21:9",
            "16:9",
            "4:3",
            "1:1",
            "3:4",
            "9:16",
        ),
        default_aspect="auto",
        resolution_choices=("480p", "720p"),
        default_resolution="720p",
        supports_audio=True,
        supports_negative=False,
        supports_end_frame=True,
        duration_as_int=False,
        image_field="image_url",
        extra_defaults={"generate_audio": True},
    ),
    "hailuo 02 i2v": VisionModelSpec(
        key="hailuo 02 i2v",
        label="MiniMax Hailuo 02 · Image→Video",
        mode="image_to_video",
        endpoint="fal-ai/minimax/hailuo-02/standard/image-to-video",
        cost_estimate_usd=0.28,
        cost_per_second=0.04,
        notes="I2V with optional end frame (also listed under Bridge).",
        duration_choices=("6", "10"),
        default_duration="6",
        supports_audio=False,
        supports_negative=False,
        supports_end_frame=True,
        resolution_choices=("512P", "768P"),
        default_resolution="768P",
        extra_defaults={"prompt_optimizer": True},
    ),
    "minimax h3 i2v": VisionModelSpec(
        key="minimax h3 i2v",
        label="MiniMax H3 · Image→Video",
        mode="image_to_video",
        endpoint="minimax/h3/image-to-video",
        cost_estimate_usd=1.30,
        cost_per_second=0.26,
        notes=(
            "H3 I2V — start still as first frame; optional end still for first→last "
            "(day→night / porch→interior). 5–15s · 2K · native stereo. "
            "Est. ~$0.26/s @2K. Aspect follows the start image."
        ),
        duration_choices=tuple(str(i) for i in range(5, 16)),
        default_duration="5",
        aspect_choices=("auto",),
        default_aspect="auto",
        resolution_choices=("2K",),
        default_resolution="2K",
        supports_audio=False,
        supports_negative=False,
        supports_end_frame=True,
        duration_as_int=True,
        native_stereo_audio=True,
    ),
    "grok imagine 1.5 i2v": VisionModelSpec(
        key="grok imagine 1.5 i2v",
        label="Grok Imagine 1.5 · Image→Video",
        mode="image_to_video",
        endpoint="xai/grok-imagine-video/v1.5/image-to-video",
        cost_estimate_usd=0.85,  # 6s × 0.14 + 0.01
        cost_per_second=0.14,
        notes=(
            "xAI Grok Imagine Video 1.5 I2V — animate a still with strong motion + native audio. "
            "1–15s · 480p/720p/1080p. Est. $0.08/s @480p, $0.14/s @720p, $0.25/s @1080p + $0.01 image."
        ),
        duration_choices=tuple(str(i) for i in range(1, 16)),
        default_duration="6",
        aspect_choices=("auto",),
        default_aspect="auto",
        resolution_choices=("480p", "720p", "1080p"),
        default_resolution="720p",
        supports_audio=False,
        supports_negative=False,
        supports_end_frame=False,
        duration_as_int=True,
        native_stereo_audio=True,
        image_field="image_url",
    ),
    "flux 3 i2v": VisionModelSpec(
        key="flux 3 i2v",
        label="FLUX 3 · Image→Video",
        mode="image_to_video",
        endpoint="blackforestlabs/flux-3/image-to-video",
        cost_estimate_usd=1.36,  # 8s × $0.17
        cost_per_second=0.17,
        cost_per_second_by_resolution={"720p": 0.17, "1080p": 0.29},
        draft_endpoint="blackforestlabs/flux-3/image-to-video/draft",
        enhance_endpoint="blackforestlabs/flux-3/draft-enhance",
        cost_per_second_draft=0.06,
        notes=(
            "FLUX 3 I2V (BFL on fal) — animate a still with optional native audio. "
            "Aspect follows the still (no aspect_ratio). "
            "Start frame = layout lock; Character = identity ref (freer framing). "
            "5–20s or auto · 720p/1080p. Draft first → Enhance to full. "
            "Est. ~$0.17/s @720p · ~$0.29/s @1080p · draft ~$0.06/s."
        ),
        duration_choices=("auto",) + tuple(str(i) for i in range(5, 21)),
        default_duration="8",
        aspect_choices=(ASPECT_FOLLOWS_STILL,),
        default_aspect=ASPECT_FOLLOWS_STILL,
        omit_aspect_ratio=True,
        resolution_choices=("720p", "1080p"),
        default_resolution="720p",
        supports_audio=True,
        supports_negative=False,
        supports_end_frame=False,
        duration_as_int=True,
        image_field="image_url",
        extra_defaults={"generate_audio": True, "safety_tolerance": 2},
    ),
}

# ---------------------------------------------------------------------------
# R2I — Reference → Image (build still from identity/style/prop refs, not plate edit)
# ---------------------------------------------------------------------------

R2I_MODELS: dict[str, VisionModelSpec] = {
    # Multi-ref edit endpoints — tab intent: build still from refs (not plate-edit I2I)
    "flux 2 pro r2i": VisionModelSpec(
        key="flux 2 pro r2i",
        label="Flux 2 Pro · R2I",
        mode="reference_to_image",
        endpoint="fal-ai/flux-2-pro/edit",
        cost_estimate_usd=0.03,
        notes=(
            "Build a still from Character / style / prop refs (multi-ref). "
            "Not plate-edit I2I — freer composition from identity pack. ~$0.03/image."
        ),
        duration_choices=(),
        default_duration="",
        aspect_choices=I2I_ASPECT_CHOICES,
        default_aspect="Match source",
        resolution_choices=(),
        supports_audio=False,
        supports_negative=False,
        max_refs=3,
        image_field="image_urls",
        edit_model_key="flux 2 pro",
        supports_strength=False,
        extra_defaults={"num_images": 1, "output_format": "jpeg", "safety_tolerance": "4"},
    ),
    "flux 2 max r2i": VisionModelSpec(
        key="flux 2 max r2i",
        label="Flux 2 Max · R2I",
        mode="reference_to_image",
        endpoint="fal-ai/flux-2-max/edit",
        cost_estimate_usd=0.07,
        notes="Highest-quality multi-ref still from character/style refs.",
        duration_choices=(),
        default_duration="",
        aspect_choices=I2I_ASPECT_CHOICES,
        default_aspect="Match source",
        supports_audio=False,
        max_refs=3,
        image_field="image_urls",
        edit_model_key="flux 2 max",
        extra_defaults={"num_images": 1, "output_format": "jpeg", "safety_tolerance": "4"},
    ),
    "nano banana pro r2i": VisionModelSpec(
        key="nano banana pro r2i",
        label="Nano Banana Pro · R2I",
        mode="reference_to_image",
        endpoint="fal-ai/nano-banana-pro/edit",
        cost_estimate_usd=0.08,
        notes="Creative multi-ref still from identity/style refs.",
        duration_choices=(),
        default_duration="",
        aspect_choices=I2I_ASPECT_CHOICES,
        default_aspect="Match source",
        supports_audio=False,
        max_refs=3,
        image_field="image_urls",
        edit_model_key="nano banana pro",
        extra_defaults={"num_images": 1},
    ),
    "seedream 5 pro r2i": VisionModelSpec(
        key="seedream 5 pro r2i",
        label="Seedream 5 Pro · R2I",
        mode="reference_to_image",
        endpoint="bytedance/seedream/v5/pro/edit",
        cost_estimate_usd=0.07,
        notes="Grounded multi-ref still from character/style refs.",
        duration_choices=(),
        default_duration="",
        aspect_choices=I2I_ASPECT_CHOICES,
        default_aspect="Match source",
        supports_audio=False,
        max_refs=3,
        image_field="image_urls",
        edit_model_key="seedream 5 pro",
        extra_defaults={"num_images": 1},
    ),
}

# ---------------------------------------------------------------------------
# R2V — Reference → Video (multi identity / omni; freer framing)
# ---------------------------------------------------------------------------

R2V_MODELS: dict[str, VisionModelSpec] = {
    "minimax h3 omni": VisionModelSpec(
        key="minimax h3 omni",
        label="MiniMax H3 · Omni reference",
        mode="reference_to_video",
        endpoint="minimax/h3/reference-to-video",
        cost_estimate_usd=1.30,
        cost_per_second=0.26,
        notes=(
            "H3 omni R2V — Character-first multi identity (up to 9 images) + optional "
            "video/audio advanced refs. Cite Image 1 / Video 1 / Audio 1. "
            "Native stereo · 2K · 5–15s. Default R2V model. Also Studio Video → R2V."
        ),
        duration_choices=tuple(str(i) for i in range(5, 16)),
        default_duration="5",
        aspect_choices=(
            "adaptive", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16",
        ),
        default_aspect="adaptive",
        resolution_choices=("2K",),
        default_resolution="2K",
        supports_audio=False,
        supports_negative=False,
        max_refs=9,
        max_ref_videos=3,
        max_ref_audios=3,
        max_total_refs=12,
        omni_reference=True,
        duration_as_int=True,
        native_stereo_audio=True,
        prompt_citation_style="plain",
    ),
    "grok imagine 1.5 reference": VisionModelSpec(
        key="grok imagine 1.5 reference",
        label="Grok Imagine 1.5 · Reference pack",
        mode="reference_to_video",
        endpoint="xai/grok-imagine-video/v1.5/reference-to-video",
        cost_estimate_usd=0.66,
        cost_per_second=0.08,
        notes=(
            "Grok Imagine 1.5 R2V — 1–7 reference stills; tag <IMAGE_0>… in the prompt. "
            "Native audio. 1–15s · 480p/720p. Also Studio Video → R2V."
        ),
        duration_choices=tuple(str(i) for i in range(1, 16)),
        default_duration="8",
        aspect_choices=("16:9", "4:3", "3:2", "1:1", "2:3", "3:4", "9:16"),
        default_aspect="16:9",
        resolution_choices=("480p", "720p"),
        default_resolution="480p",
        supports_audio=False,
        supports_negative=False,
        max_refs=7,
        duration_as_int=True,
        native_stereo_audio=True,
        prompt_citation_style="angle",
        image_field="reference_image_urls",
    ),
    "veo 3.1 reference": VisionModelSpec(
        key="veo 3.1 reference",
        label="Veo 3.1 Reference pack",
        mode="reference_to_video",
        endpoint="fal-ai/veo3.1/reference-to-video",
        cost_estimate_usd=3.20,
        cost_per_second=0.40,
        notes="R2V guided by 1–N reference stills. ~$0.40/s on fal (standard Veo family).",
        max_refs=8,
        duration_choices=("8s",),
        default_duration="8s",
        extra_defaults={"generate_audio": True, "auto_fix": False, "safety_tolerance": "4"},
    ),
    "seedance 2.0 reference": VisionModelSpec(
        key="seedance 2.0 reference",
        label="Seedance 2.0 · Reference-to-Video",
        mode="reference_to_video",
        endpoint="bytedance/seedance-2.0/reference-to-video",
        cost_estimate_usd=1.50,
        cost_per_second=0.30,
        notes=(
            "Seedance 2.0 R2V — multi reference stills (identity/style). "
            "aspect_ratio: auto | 21:9 | 16:9 | 4:3 | 1:1 | 3:4 | 9:16 (default auto). "
            "Not I2V start-frame lock. Also Studio Video → R2V."
        ),
        duration_choices=("auto",) + tuple(str(i) for i in range(4, 16)),
        default_duration="5",
        aspect_choices=(
            "auto",
            "21:9",
            "16:9",
            "4:3",
            "1:1",
            "3:4",
            "9:16",
        ),
        default_aspect="auto",
        omit_aspect_ratio=False,
        resolution_choices=("480p", "720p"),  # fal R2V schema (not 1080p)
        default_resolution="720p",
        supports_audio=True,
        supports_negative=False,  # never send negative_prompt
        max_refs=9,
        duration_as_int=False,  # API expects string "15" / "auto", not int
        image_field="image_urls",
        extra_defaults={"generate_audio": True},
    ),
    "seedance 2.5 reference": VisionModelSpec(
        key="seedance 2.5 reference",
        label="Seedance 2.5 · Reference-to-Video",
        mode="reference_to_video",
        endpoint="bytedance/seedance-2.5/reference-to-video",
        cost_estimate_usd=2.31,
        cost_per_second=0.473,
        cost_per_second_by_resolution={"480p": 0.2205, "720p": 0.473},
        notes=(
            "Seedance 2.5 R2V — up to 50 multimodal refs (images/video/audio), "
            "up to 30s single-pass, native audio. Cite [Image1] / [Video1] / [Audio1]. "
            "Character/Scene sheets bind as real image_urls. "
            "Token est. $0.0214/1k tokens; video refs ×0.6 (image/audio refs free). "
            "Limitation: partner photoreal-face filter. Strengths: long take, high ref count, action."
        ),
        duration_choices=("auto",) + tuple(str(i) for i in range(4, 31)),
        default_duration="5",
        aspect_choices=(
            "auto",
            "21:9",
            "16:9",
            "4:3",
            "1:1",
            "3:4",
            "9:16",
        ),
        default_aspect="auto",
        omit_aspect_ratio=False,
        resolution_choices=("480p", "720p"),
        default_resolution="720p",
        supports_audio=True,
        supports_negative=False,
        max_refs=30,  # images; total multimodal cap 50 with video/audio
        max_ref_videos=10,
        max_ref_audios=10,
        max_total_refs=50,
        duration_as_int=False,
        image_field="image_urls",
        prompt_citation_style="plain",
        extra_defaults={"generate_audio": True},
    ),
    # FLUX 3 listed under R2V as identity-ref emphasis (still single-image API)
    "flux 3 r2v": VisionModelSpec(
        key="flux 3 r2v",
        label="FLUX 3 · Identity ref (R2V)",
        mode="reference_to_video",
        endpoint="blackforestlabs/flux-3/image-to-video",
        cost_estimate_usd=1.36,
        cost_per_second=0.17,
        cost_per_second_by_resolution={"720p": 0.17, "1080p": 0.29},
        draft_endpoint="blackforestlabs/flux-3/image-to-video/draft",
        enhance_endpoint="blackforestlabs/flux-3/draft-enhance",
        cost_per_second_draft=0.06,
        notes=(
            "FLUX 3 with Character as identity ref (freer framing). "
            "Single still only — no multi-char element API. "
            "For multi-pose timed pins use Director · Keyframe Take. "
            "Aspect follows still (no aspect_ratio)."
        ),
        duration_choices=("auto",) + tuple(str(i) for i in range(5, 21)),
        default_duration="8",
        aspect_choices=(ASPECT_FOLLOWS_STILL,),
        default_aspect=ASPECT_FOLLOWS_STILL,
        omit_aspect_ratio=True,
        resolution_choices=("720p", "1080p"),
        default_resolution="720p",
        supports_audio=True,
        supports_negative=False,
        max_refs=1,
        duration_as_int=True,
        image_field="image_url",
        extra_defaults={"generate_audio": True, "safety_tolerance": 2},
    ),
}

# ---------------------------------------------------------------------------
# V2V — Video → Video (source clip + prompt; align with Studio V2V)
# ---------------------------------------------------------------------------

V2V_MODELS: dict[str, VisionModelSpec] = {
    "flux 3 extend v2v": VisionModelSpec(
        key="flux 3 extend v2v",
        label="FLUX 3 · Extend (V2V)",
        mode="video_to_video",
        endpoint="blackforestlabs/flux-3/extend-video",
        cost_estimate_usd=1.36,
        cost_per_second=0.17,
        cost_per_second_by_resolution={"720p": 0.17, "1080p": 0.29},
        draft_endpoint="blackforestlabs/flux-3/extend-video/draft",
        enhance_endpoint="blackforestlabs/flux-3/draft-enhance",
        cost_per_second_draft=0.06,
        notes=(
            "Continue a clip with prompt + optional native audio. "
            "Same family as Extend Video tab; listed here for Studio-aligned V2V."
        ),
        duration_choices=("auto",) + tuple(str(i) for i in range(5, 21)),
        default_duration="8",
        resolution_choices=("720p", "1080p"),
        default_resolution="720p",
        supports_audio=True,
        duration_as_int=True,
        video_field="video_url",
        extra_defaults={"generate_audio": True, "safety_tolerance": 2},
    ),
}

# ---------------------------------------------------------------------------
# Bridge / connect shots (start + end frame)
# ---------------------------------------------------------------------------

BRIDGE_MODELS: dict[str, VisionModelSpec] = {
    "veo 3.1 fast bridge": VisionModelSpec(
        key="veo 3.1 fast bridge",
        label="Veo 3.1 Fast · First→Last frame",
        mode="bridge",
        endpoint="fal-ai/veo3.1/fast/first-last-frame-to-video",
        # fal billing: $0.15/s
        cost_estimate_usd=0.90,  # 6s × $0.15
        cost_per_second=0.15,
        notes="Faster bridge. ~$0.15/s on fal. Recommended default for connect shots.",
        default_duration="6s",
        aspect_choices=("auto", "16:9", "9:16"),
        default_aspect="auto",
        extra_defaults={"generate_audio": True, "auto_fix": False, "safety_tolerance": "4"},
    ),
    "veo 3.1 bridge": VisionModelSpec(
        key="veo 3.1 bridge",
        label="Veo 3.1 · First→Last frame",
        mode="bridge",
        endpoint="fal-ai/veo3.1/first-last-frame-to-video",
        # fal billing: $0.40/s (user invoice)
        cost_estimate_usd=3.20,  # 8s × $0.40
        cost_per_second=0.40,
        notes=(
            "Bridge two stills into a continuous move (e.g. upstairs → living room). "
            "~$0.40/s on fal. Prompt: path, speed, keep architecture consistent."
        ),
        aspect_choices=("auto", "16:9", "9:16"),
        default_aspect="auto",
        extra_defaults={"generate_audio": True, "auto_fix": False, "safety_tolerance": "4"},
    ),
    "hailuo 02 bridge": VisionModelSpec(
        key="hailuo 02 bridge",
        label="Hailuo 02 · Start+End frame",
        mode="bridge",
        endpoint="fal-ai/minimax/hailuo-02/standard/image-to-video",
        cost_estimate_usd=0.30,
        cost_per_second=0.04,
        notes="Uses image_url + end_image_url. Cheaper bridge alternative.",
        duration_choices=("6", "10"),
        default_duration="6",
        supports_audio=False,
        supports_negative=False,
        first_frame_field="image_url",
        last_frame_field="end_image_url",
        resolution_choices=("512P", "768P"),
        default_resolution="768P",
        extra_defaults={"prompt_optimizer": True},
    ),
    "flux 3 bridge": VisionModelSpec(
        key="flux 3 bridge",
        label="FLUX 3 · First→Last frame",
        mode="bridge",
        endpoint="blackforestlabs/flux-3/first-last-frame-to-video",
        cost_estimate_usd=1.36,  # 8s × $0.17
        cost_per_second=0.17,
        cost_per_second_by_resolution={"720p": 0.17, "1080p": 0.29},
        draft_endpoint="blackforestlabs/flux-3/first-last-frame-to-video/draft",
        enhance_endpoint="blackforestlabs/flux-3/draft-enhance",
        cost_per_second_draft=0.06,
        notes=(
            "FLUX 3 first→last (BFL on fal) — bridge two stills (day→night, porch→interior). "
            "Requires start + end. 5–20s · 720p/1080p · optional native audio. "
            "Draft first → Enhance to full. "
            "Est. ~$0.17/s @720p · ~$0.29/s @1080p · draft ~$0.06/s."
        ),
        duration_choices=tuple(str(i) for i in range(5, 21)),
        default_duration="8",
        aspect_choices=(
            "auto", "21:9", "2:1", "16:9", "4:3", "1:1", "3:4", "9:16",
        ),
        default_aspect="auto",
        resolution_choices=("720p", "1080p"),
        default_resolution="720p",
        supports_audio=True,
        supports_negative=False,
        first_frame_field="start_image_url",
        last_frame_field="end_image_url",
        requires_end_frame=True,
        duration_as_int=True,
        extra_defaults={"generate_audio": True, "safety_tolerance": 2},
    ),
}

# ---------------------------------------------------------------------------
# Extend video (source clip + prompt)
# ---------------------------------------------------------------------------

EXTEND_MODELS: dict[str, VisionModelSpec] = {
    "flux 3 extend": VisionModelSpec(
        key="flux 3 extend",
        label="FLUX 3 · Extend Video",
        mode="extend",
        endpoint="blackforestlabs/flux-3/extend-video",
        cost_estimate_usd=1.36,  # 8s × $0.17
        cost_per_second=0.17,
        cost_per_second_by_resolution={"720p": 0.17, "1080p": 0.29},
        draft_endpoint="blackforestlabs/flux-3/extend-video/draft",
        enhance_endpoint="blackforestlabs/flux-3/draft-enhance",
        cost_per_second_draft=0.06,
        notes=(
            "FLUX 3 extend (BFL on fal) — continue an existing clip with a prompt. "
            "Source video under 50 MB / 15s. 5–20s or auto · 720p/1080p · optional audio. "
            "Draft first → Enhance to full. "
            "Est. ~$0.17/s @720p · ~$0.29/s @1080p · draft ~$0.06/s. Also Studio V2V."
        ),
        duration_choices=("auto",) + tuple(str(i) for i in range(5, 21)),
        default_duration="8",
        aspect_choices=(
            "auto", "21:9", "2:1", "16:9", "4:3", "1:1", "3:4", "9:16",
        ),
        default_aspect="auto",
        resolution_choices=("720p", "1080p"),
        default_resolution="720p",
        supports_audio=True,
        supports_negative=False,
        duration_as_int=True,
        video_field="video_url",
        extra_defaults={"generate_audio": True, "safety_tolerance": 2},
    ),
}


def models_for_mode(mode: VisionMode) -> dict[str, VisionModelSpec]:
    if mode == "text_to_image":
        return T2I_MODELS
    if mode == "image_to_image":
        return I2I_MODELS
    if mode == "reference_to_image":
        return R2I_MODELS
    if mode == "text_to_video":
        return T2V_MODELS
    if mode == "image_to_video":
        return I2V_MODELS
    if mode == "reference_to_video":
        return R2V_MODELS
    if mode == "video_to_video":
        return V2V_MODELS
    if mode == "extend":
        return EXTEND_MODELS
    return BRIDGE_MODELS


def vision_labels(mode: VisionMode) -> list[str]:
    return [s.label for s in models_for_mode(mode).values()]


def find_vision_model(
    label_or_key: str | None,
    mode: VisionMode | None = None,
) -> VisionModelSpec | None:
    if not label_or_key:
        return None
    raw = label_or_key.strip().lower()
    registries = (
        [models_for_mode(mode)]
        if mode
        else [
            T2I_MODELS,
            I2I_MODELS,
            R2I_MODELS,
            T2V_MODELS,
            I2V_MODELS,
            R2V_MODELS,
            V2V_MODELS,
            BRIDGE_MODELS,
            EXTEND_MODELS,
        ]
    )
    for reg in registries:
        if raw in reg:
            return reg[raw]
        for spec in reg.values():
            if spec.label.lower() == raw or spec.key == raw:
                return spec
    return None


def default_vision_model(mode: VisionMode) -> VisionModelSpec:
    reg = models_for_mode(mode)
    # Prefer practical defaults per mode
    for key in (
        "flux 2 pro t2i",
        "flux 2 pro i2i",
        "flux 2 pro r2i",
        "veo 3.1 fast",
        "veo 3.1 fast i2v",
        "flux 3 i2v",
        "minimax h3 omni",
        "flux 3 extend v2v",
        "veo 3.1 fast bridge",
        "flux 3 extend",
    ):
        if key in reg:
            return reg[key]
    return next(iter(reg.values()))


def is_still_mode(mode: VisionMode | str | None) -> bool:
    """True for pure still modes (T2I / I2I / R2I) — no video duration / audio."""
    return mode in ("text_to_image", "image_to_image", "reference_to_image")


def is_r2v_mode(mode: VisionMode | str | None) -> bool:
    return mode == "reference_to_video"


def is_r2i_mode(mode: VisionMode | str | None) -> bool:
    return mode == "reference_to_image"


def duration_seconds(token: str | None) -> float:
    """
    Parse UI duration tokens to seconds.

    Accepts ``\"8s\"``, ``\"8\"``, ``\"10\"``, etc. Defaults to 8s when missing/invalid.
    """
    if not token:
        return 8.0
    t = str(token).strip().lower()
    # FLUX 3 / Seedance-style "auto" — use a mid ballpark for cost UI
    if t in ("auto", "default"):
        return 8.0
    # Keep only leading number (handles "8s", "8 sec", "10")
    num = ""
    for ch in t:
        if ch.isdigit() or ch == ".":
            num += ch
        elif num:
            break
    try:
        secs = float(num) if num else 8.0
    except (TypeError, ValueError):
        secs = 8.0
    return max(0.5, secs)


# fal Seedance 2.5 supported frame sizes (authoritative for token cost)
_SEEDANCE_25_FRAMES: dict[tuple[str, str], tuple[int, int]] = {
    ("480p", "21:9"): (992, 432),
    ("480p", "16:9"): (864, 496),
    ("480p", "4:3"): (752, 560),
    ("480p", "1:1"): (640, 640),
    ("480p", "3:4"): (560, 752),
    ("480p", "9:16"): (496, 864),
    ("720p", "21:9"): (1470, 630),
    ("720p", "16:9"): (1280, 720),
    ("720p", "4:3"): (1112, 834),
    ("720p", "1:1"): (960, 960),
    ("720p", "3:4"): (834, 1112),
    ("720p", "9:16"): (720, 1280),
}
SEEDANCE_25_TOKEN_USD_PER_1K = 0.0214
SEEDANCE_25_VIDEO_REF_MULTIPLIER = 0.6


def is_seedance_25_endpoint(endpoint: str | None) -> bool:
    ep = (endpoint or "").strip().lower()
    return "seedance-2.5" in ep or "seedance/2.5" in ep


def is_seedance_25_spec(spec: VisionModelSpec | None) -> bool:
    if spec is None:
        return False
    if is_seedance_25_endpoint(spec.endpoint):
        return True
    return "2.5" in (spec.key or "").lower() and "seedance" in (spec.key or "").lower()


def estimate_seedance_25_cost(
    *,
    duration_s: float,
    resolution: str | None = "720p",
    aspect_ratio: str | None = "16:9",
    has_video_refs: bool = False,
    input_video_duration_s: float = 0.0,
) -> float:
    """
    Seedance 2.5 fal token formula (authoritative).

    tokens = (height * width * (input_video_duration + output_duration) * 24) / 1024
    cost = tokens / 1000 * $0.0214  (same rate at 480p and 720p)
    If any video references: cost × 0.6 (input + output seconds both count).
    Image and audio references are not billed.
    """
    res = (resolution or "720p").strip().lower()
    if res not in ("480p", "720p"):
        res = "720p"
    ar = (aspect_ratio or "16:9").strip().lower()
    if ar in ("auto", "default", "", "—", "none", "follows still"):
        ar = "16:9"
    wh = _SEEDANCE_25_FRAMES.get((res, ar)) or _SEEDANCE_25_FRAMES[(res, "16:9")]
    w, h = wh
    out_dur = max(0.5, float(duration_s or 5.0))
    in_dur = 0.0
    if has_video_refs:
        in_dur = max(0.0, float(input_video_duration_s or 0.0))
    tokens = (h * w * (in_dur + out_dur) * 24.0) / 1024.0
    cost = (tokens / 1000.0) * SEEDANCE_25_TOKEN_USD_PER_1K
    if has_video_refs:
        cost *= SEEDANCE_25_VIDEO_REF_MULTIPLIER
    return round(max(0.05, cost), 3)


def clamp_vision_num_images(spec: VisionModelSpec, n: int | None) -> int:
    """UI batch count for stills: 1..VISION_BATCH_MAX (sequential if API is 1-at-a-time)."""
    try:
        want = int(n) if n is not None else 1
    except (TypeError, ValueError):
        want = 1
    want = max(1, want)
    if is_still_mode(spec.mode):
        return min(want, VISION_BATCH_MAX)
    return 1


def estimate_vision_cost(
    spec: VisionModelSpec,
    *,
    duration_token: str | None = None,
    resolution: str | None = None,
    aspect_ratio: str | None = None,
    generate_audio: bool | None = None,
    num_images: int | None = None,
    has_video_refs: bool = False,
    input_video_duration_s: float = 0.0,
) -> float:
    """
    Conservative USD ballpark for UI (not billing).

    Video modes: **total job cost** = rate × selected duration (seconds), then
    resolution / audio multipliers. Never show a bare per-second rate as the total.
    Still modes: per-image × count (multi-variant batch).

    Seedance 2.5 uses fal's token formula ($0.0214/1k tokens; video refs ×0.6).
    """
    if is_still_mode(spec.mode):
        # Flat per-image estimates; bump for large aspect / higher resolution
        base = float(spec.cost_estimate_usd)
        asp = (aspect_ratio or spec.default_aspect or "").lower()
        if "match" in asp:
            pass  # source-sized edit — no bump
        elif "16:9" in asp or "9:16" in asp or "hd" in asp or "auto 4" in asp:
            base *= 1.15
        if "auto 4" in asp or "auto_4" in asp:
            base *= 1.35
        res = (resolution or spec.default_resolution or "").lower()
        if res in ("4k", "4K".lower()):
            base *= 2.4
        elif res in ("2k", "2K".lower()):
            base *= 1.55
        elif res in ("0.5k", "0.5K".lower()):
            base *= 0.7
        # Nano Banana Pro is steeper at high res
        if "nano-banana-pro" in spec.endpoint and res in ("2k", "4k"):
            base *= 1.15
        n = clamp_vision_num_images(spec, num_images)
        return round(max(0.01, base * n), 3)

    # --- Video: total = per-second rate × duration ---
    dur_token = duration_token if duration_token not in (None, "") else spec.default_duration
    secs = duration_seconds(dur_token)
    default_secs = duration_seconds(spec.default_duration) or 8.0

    # Seedance 2.5 — token formula (prefer over flat $/s tables)
    if is_seedance_25_spec(spec):
        return estimate_seedance_25_cost(
            duration_s=secs,
            resolution=resolution or spec.default_resolution or "720p",
            aspect_ratio=aspect_ratio or spec.default_aspect or "16:9",
            has_video_refs=bool(has_video_refs),
            input_video_duration_s=float(input_video_duration_s or 0.0),
        )

    by_res = getattr(spec, "cost_per_second_by_resolution", None) or {}
    rate: float | None = None
    if by_res:
        res_key = (resolution or spec.default_resolution or "720p").strip().lower()
        if not res_key or res_key in ("auto", "default"):
            res_key = (spec.default_resolution or "720p").strip().lower()
        # Match keys case-insensitively
        amap = {str(k).lower(): float(v) for k, v in by_res.items()}
        rate = amap.get(res_key) or amap.get("720p") or next(iter(amap.values()), None)

    if rate is None and spec.cost_per_second is not None and float(spec.cost_per_second) > 0:
        rate = float(spec.cost_per_second)

    if rate is not None and rate > 0:
        # Full job total — never return the bare $/s figure
        base = float(rate) * secs
    else:
        # Flat estimate assumed for default_duration; scale linearly with selected length
        flat = float(spec.cost_estimate_usd or 0.0)
        base = flat * (secs / default_secs) if default_secs > 0 else flat

    # Resolution multipliers only when the model bills by res (not flat $/s Veo/H3/FLUX table)
    ep = (spec.endpoint or "").lower()
    is_flat_rate = (
        "veo3.1" in ep
        or "veo3" in ep
        or "minimax/h3" in ep
        or "hailuo-03" in ep
        or "flux-3" in ep
        or bool(by_res)
        or (spec.cost_per_second is not None and "2k" in (spec.default_resolution or "").lower())
    )
    if not is_flat_rate:
        res = (resolution or spec.default_resolution or "720p").lower()
        if "1080" in res or res == "1080p":
            base *= 1.35
        elif "4k" in res or "2160" in res:
            base *= 2.2
        elif "512" in res:
            base *= 0.75

    # No invented audio multiplier unless fal quotes a separate audio rate.
    _ = generate_audio

    return round(max(0.05, base), 3)


def format_vision_cost(
    spec: VisionModelSpec,
    *,
    duration_token: str | None = None,
    resolution: str | None = None,
    aspect_ratio: str | None = None,
    generate_audio: bool | None = None,
    num_images: int | None = None,
    has_video_refs: bool = False,
    input_video_duration_s: float = 0.0,
) -> str:
    """
    Human label for the **total** estimated job cost.

    Video: ``Est. cost: $X.XX · {duration}s ({model})``
    Still: ``Est. cost: $X.XX · N image(s) ({model})`` — per-image × count
    Seedance 2.5 with video refs notes the ×0.6 video-ref flag.
    """
    from media_studio.pricing import format_job_cost

    amt = estimate_vision_cost(
        spec,
        duration_token=duration_token,
        resolution=resolution,
        aspect_ratio=aspect_ratio,
        generate_audio=generate_audio,
        num_images=num_images,
        has_video_refs=has_video_refs,
        input_video_duration_s=input_video_duration_s,
    )
    if is_still_mode(spec.mode):
        n = clamp_vision_num_images(spec, num_images)
        unit = "1 image" if n == 1 else f"{n} images"
        api_max = max(1, int(getattr(spec, "max_num_images", 1) or 1))
        if n > api_max:
            unit = f"{unit} · {n} sequential runs"
        return format_job_cost(amt, unit=unit, model=spec.label)
    dur_token = duration_token if duration_token not in (None, "") else spec.default_duration
    secs = duration_seconds(dur_token)
    dur_txt = f"{secs:.0f}" if abs(secs - round(secs)) < 1e-6 else f"{secs:.1f}"
    unit = f"{dur_txt}s"
    if is_seedance_25_spec(spec) and has_video_refs:
        unit = f"{dur_txt}s · video-ref ×0.6"
    return format_job_cost(amt, unit=unit, model=spec.label)


def build_vision_arguments(
    spec: VisionModelSpec,
    *,
    prompt: str,
    image_url: str | None = None,
    first_frame_url: str | None = None,
    last_frame_url: str | None = None,
    ref_urls: list[str] | None = None,
    ref_video_urls: list[str] | None = None,
    ref_audio_urls: list[str] | None = None,
    source_video_url: str | None = None,
    duration: str | None = None,
    aspect_ratio: str | None = None,
    resolution: str | None = None,
    negative_prompt: str | None = None,
    generate_audio: bool | None = None,
    num_images: int | None = None,
) -> dict[str, Any]:
    """Map UI fields → fal payload for the selected Vision model."""
    args: dict[str, Any] = dict(spec.extra_defaults)
    text = (prompt or "").strip()
    if not text:
        raise ValueError(
            "Enter a prompt."
            if is_still_mode(spec.mode)
            else "Enter a motion / shot prompt."
        )
    args["prompt"] = text

    # --- Text → Image (no media uploads) ---
    if spec.mode == "text_to_image":
        ep = spec.endpoint.lower()
        size = map_t2i_image_size(aspect_ratio or spec.default_aspect)
        colon_ar = map_t2i_aspect_colon(aspect_ratio or spec.default_aspect)
        res = (resolution or spec.default_resolution or "").strip()
        # Batch size for this API call (caller may loop for sequential variants)
        n = clamp_vision_num_images(spec, num_images)
        api_max = max(1, int(spec.max_num_images or 1))
        args["num_images"] = min(n, api_max)

        if "nano-banana" in ep:
            # Nano Banana / 2 / Pro: aspect_ratio "16:9"; 2+Pro also resolution
            args["aspect_ratio"] = colon_ar
            if spec.resolution_choices:
                # Map loose UI value to API enum (0.5K, 1K, 2K, 4K)
                picked = None
                for a in spec.resolution_choices:
                    if str(a).lower() == res.lower():
                        picked = str(a)
                        break
                args["resolution"] = picked or (spec.default_resolution or "1K")
        elif "seedream" in ep or "bytedance" in ep:
            # Seedream T2I: image_size preset or auto_2K / auto_4K
            args["image_size"] = size
        elif "recraft" in ep:
            args["aspect_ratio"] = colon_ar
        elif "flux-pro/v1.1-ultra" in ep or "flux-pro/v1.1" in ep:
            args["aspect_ratio"] = colon_ar
        else:
            # Flux 2 family: image_size enum
            args["image_size"] = size

        neg = (negative_prompt or "").strip()
        if neg and spec.supports_negative:
            args["negative_prompt"] = neg
        for k in list(args.keys()):
            if args[k] is None or args[k] == "":
                args.pop(k, None)
        return args

    # --- Image → Image is built via fal build_edit_arguments in vision_service ---
    if spec.mode == "image_to_image":
        raise ValueError(
            "Image→Image uses build_edit_arguments in vision_service (not this path)."
        )

    ep = spec.endpoint.lower()
    is_h3 = "minimax/h3" in ep or "hailuo-03" in ep
    is_flux3 = "flux-3" in ep or "blackforestlabs/flux-3" in ep

    dur = (duration or spec.default_duration or "").strip()
    if dur and spec.duration_param and spec.duration_choices:
        # Normalize: some models want "8s", others "8" / "5" / "auto"
        if "veo" in ep or "luma" in ep:
            if not dur.endswith("s") and dur.isdigit():
                dur = f"{dur}s"
        elif (
            "kling" in ep
            or "seedance" in ep
            or "hailuo" in ep
            or is_h3
            or is_flux3
            or "grok-imagine-video" in ep
            or getattr(spec, "duration_as_int", False)
        ):
            dur = dur.replace("s", "").strip()
        if str(dur).lower() == "auto" and any(
            str(c).lower() == "auto" for c in (spec.duration_choices or ())
        ):
            args[spec.duration_param] = "auto"
        else:
            if spec.duration_choices and dur not in spec.duration_choices:
                # try closest allowed (skip auto)
                dur = spec.default_duration
            if str(dur).lower() == "auto":
                args[spec.duration_param] = "auto"
            elif getattr(spec, "duration_as_int", False) or is_h3 or is_flux3:
                try:
                    args[spec.duration_param] = int(str(dur).replace("s", ""))
                except (TypeError, ValueError):
                    args[spec.duration_param] = dur
            else:
                # Seedance (and similar): string enum "15" / "auto", not int
                args[spec.duration_param] = str(dur).replace("s", "").strip()

    aspect = (aspect_ratio or spec.default_aspect or "").strip()
    is_grok_v = "grok-imagine-video" in ep

    if is_h3:
        res = resolution or spec.default_resolution or "2K"
        # API expects "2K"
        if str(res).lower() == "2k":
            res = "2K"
        args["resolution"] = res
        # I2V: aspect follows start image (no aspect_ratio param)
        # T2V / omni: send aspect including "adaptive"
        if "image-to-video" not in ep:
            if aspect and aspect not in ("", "—"):
                args["aspect_ratio"] = aspect
    elif is_flux3:
        res = resolution or spec.default_resolution or "720p"
        if res and spec.resolution_choices:
            # Prefer exact allowed casing
            picked = None
            for a in spec.resolution_choices:
                if str(a).lower() == str(res).lower():
                    picked = str(a)
                    break
            args["resolution"] = picked or str(res)
        # FLUX 3 I2V + central omit list (aspect_omit.py)
        from media_studio.aspect_omit import (
            endpoint_omits_aspect_ratio,
            is_aspect_omit_ui_sentinel,
        )

        omit_ar = (
            bool(getattr(spec, "omit_aspect_ratio", False))
            or endpoint_omits_aspect_ratio(ep)
            or ("image-to-video" in ep and "first-last" not in ep)
        )
        if omit_ar:
            args.pop("aspect_ratio", None)
        elif aspect and not is_aspect_omit_ui_sentinel(aspect):
            al = aspect.strip().lower()
            if al not in ("", "—", "none"):
                args["aspect_ratio"] = aspect
    elif is_grok_v:
        res = resolution or spec.default_resolution
        if res and spec.resolution_choices:
            args["resolution"] = res
        # I2V: no aspect_ratio; T2V / R2V: send aspect
        if "image-to-video" not in ep and aspect and aspect not in ("", "auto", "—"):
            args["aspect_ratio"] = aspect
    elif "hailuo" in ep:
        res = resolution or spec.default_resolution
        if res:
            args["resolution"] = res
    elif "seedance" in ep:
        from media_studio.aspect_omit import is_aspect_omit_ui_sentinel

        # R2V accepts aspect including "auto"; I2V same enum family
        if aspect and not is_aspect_omit_ui_sentinel(aspect):
            args["aspect_ratio"] = aspect
        elif "reference-to-video" in ep:
            args["aspect_ratio"] = "auto"
        res = resolution or spec.default_resolution or "720p"
        res_l = str(res).strip().lower()
        if "reference-to-video" in ep and res_l in ("1080p", "4k", "2k"):
            res = "720p"
        if res and spec.resolution_choices:
            picked = None
            for a in spec.resolution_choices:
                if str(a).lower() == str(res).lower():
                    picked = str(a)
                    break
            args["resolution"] = picked or str(res)
        else:
            args["resolution"] = str(res)
    elif "kling-video" in ep:
        args.pop("resolution", None)
        if aspect and aspect not in ("", "auto", "—"):
            args["aspect_ratio"] = aspect
    else:
        # Veo / Luma / reference
        if aspect and aspect not in ("", "—"):
            args["aspect_ratio"] = aspect
        res = resolution or spec.default_resolution
        if res and spec.resolution_choices:
            args["resolution"] = res

    if generate_audio is not None and spec.supports_audio:
        args["generate_audio"] = bool(generate_audio)
    elif is_flux3 and "generate_audio" not in args and spec.supports_audio:
        # Prefer explicit UI value; fall back to extra_defaults already merged
        pass

    neg = (negative_prompt or "").strip()
    if neg and spec.supports_negative:
        args["negative_prompt"] = neg

    if spec.mode == "image_to_video":
        if not image_url:
            raise ValueError("Image→Video needs a start still.")
        args[spec.image_field] = image_url
        # Optional last frame for Hailuo / H3 I2V
        if last_frame_url and (
            "hailuo" in ep or is_h3 or getattr(spec, "supports_end_frame", False)
        ):
            args["end_image_url"] = last_frame_url

    elif spec.mode == "reference_to_video":
        # R2V: multi-ref / omni / single identity — freer framing (not start-frame lock)
        imgs = [u for u in (ref_urls or []) if u]
        if image_url and image_url not in imgs:
            imgs = [image_url] + imgs
        vids = [u for u in (ref_video_urls or []) if u]
        auds = [u for u in (ref_audio_urls or []) if u]
        if not imgs and not vids:
            raise ValueError(
                "R2V needs Character 1 / identity refs (or a motion clip)."
            )
        if getattr(spec, "omni_reference", False) or (
            is_h3 and "reference-to-video" in ep
        ):
            cap_i = max(1, int(spec.max_refs or 9))
            cap_v = max(0, int(getattr(spec, "max_ref_videos", 0) or 0)) or 3
            cap_a = max(0, int(getattr(spec, "max_ref_audios", 0) or 0)) or 3
            total_cap = int(getattr(spec, "max_total_refs", 0) or 0) or 12
            imgs, vids, auds = imgs[:cap_i], vids[:cap_v], auds[:cap_a]
            while len(imgs) + len(vids) + len(auds) > total_cap:
                if auds:
                    auds.pop()
                elif imgs and len(imgs) > 1:
                    imgs.pop()
                elif vids:
                    vids.pop()
                else:
                    break
            if imgs:
                args["reference_image_urls"] = imgs
            if vids:
                args["reference_video_urls"] = vids
            if auds:
                args["reference_audio_urls"] = auds
        elif "image_urls" in (spec.image_field or "") or "seedance" in ep:
            # Seedance 2.0/2.5 R2V: image_urls + optional video_urls / audio_urls
            cap_i = max(1, int(spec.max_refs or 9))
            cap_v = max(0, int(getattr(spec, "max_ref_videos", 0) or 0))
            cap_a = max(0, int(getattr(spec, "max_ref_audios", 0) or 0))
            total_cap = int(getattr(spec, "max_total_refs", 0) or 0) or 0
            if not cap_v and "seedance" in ep:
                cap_v = 3 if "2.5" not in ep else 10
            if not cap_a and "seedance" in ep:
                cap_a = 3 if "2.5" not in ep else 10
            if not total_cap and "seedance-2.5" in ep:
                total_cap = 50
            use_imgs = imgs[:cap_i]
            use_vids = vids[:cap_v] if cap_v else []
            use_auds = auds[:cap_a] if cap_a else []
            if total_cap > 0:
                while len(use_imgs) + len(use_vids) + len(use_auds) > total_cap:
                    if use_auds:
                        use_auds.pop()
                    elif use_imgs and len(use_imgs) > 1:
                        use_imgs.pop()
                    elif use_vids:
                        use_vids.pop()
                    else:
                        break
            if use_imgs:
                args["image_urls"] = use_imgs
            if use_vids:
                args["video_urls"] = use_vids
            if use_auds:
                args["audio_urls"] = use_auds
        elif "reference_image" in (spec.image_field or ""):
            field = spec.image_field or "reference_image_urls"
            args[field] = imgs[: max(1, int(spec.max_refs or 7))]
        else:
            # Single-image R2V (e.g. FLUX 3 identity) — first ref as image_url
            field = (spec.image_field or "image_url").strip() or "image_url"
            args[field] = imgs[0]
        # Soft-inject citation if missing
        if imgs and (getattr(spec, "omni_reference", False) or int(spec.max_refs or 0) > 1):
            low = text.lower()
            style = (spec.prompt_citation_style or "plain").lower()
            if style == "angle" and "<image_0>" not in low and "<image0>" not in low:
                tags = ", ".join(f"<IMAGE_{i}>" for i in range(min(len(imgs), 7)))
                args["prompt"] = (
                    text.rstrip(".")
                    + f". Use {tags} as visual reference(s) for subject and style."
                )
            elif style == "plain" and "image 1" not in low:
                args["prompt"] = (
                    text.rstrip(".")
                    + ". Use Image 1 (and Image 2…) as character identity reference(s)."
                )

    elif spec.mode == "bridge":
        if not first_frame_url or not last_frame_url:
            raise ValueError("Bridge needs both a start frame and an end frame.")
        args[spec.first_frame_field] = first_frame_url
        args[spec.last_frame_field] = last_frame_url

    elif spec.mode in ("extend", "video_to_video"):
        vid = (source_video_url or "").strip()
        if not vid and ref_video_urls:
            vid = str(ref_video_urls[0] or "").strip()
        if not vid:
            raise ValueError(
                "V2V needs a source video clip."
                if spec.mode == "video_to_video"
                else "Extend needs a source video clip."
            )
        vfield = (getattr(spec, "video_field", None) or "video_url").strip() or "video_url"
        args[vfield] = vid

    elif spec.mode == "text_to_video":
        if getattr(spec, "omni_reference", False) or (
            is_h3 and "reference-to-video" in ep
        ):
            # Legacy path if omni still tagged text_to_video
            imgs = [u for u in (ref_urls or []) if u]
            vids = [u for u in (ref_video_urls or []) if u]
            auds = [u for u in (ref_audio_urls or []) if u]
            if not imgs and not vids:
                raise ValueError(
                    "Omni reference needs at least one still or motion clip "
                    "(audio cannot be the only reference)."
                )
            if auds and not imgs and not vids:
                raise ValueError(
                    "Reference audio must accompany an image or video reference."
                )
            cap_i = max(1, int(spec.max_refs or 9))
            cap_v = max(0, int(getattr(spec, "max_ref_videos", 0) or 0)) or 3
            cap_a = max(0, int(getattr(spec, "max_ref_audios", 0) or 0)) or 3
            total_cap = int(getattr(spec, "max_total_refs", 0) or 0) or 12
            imgs = imgs[:cap_i]
            vids = vids[:cap_v]
            auds = auds[:cap_a]
            while len(imgs) + len(vids) + len(auds) > total_cap:
                if auds:
                    auds.pop()
                elif imgs and len(imgs) > 1:
                    imgs.pop()
                elif vids:
                    vids.pop()
                else:
                    break
            if imgs:
                args["reference_image_urls"] = imgs
            if vids:
                args["reference_video_urls"] = vids
            if auds:
                args["reference_audio_urls"] = auds
            # Soft-inject citation language if missing
            style = (getattr(spec, "prompt_citation_style", None) or "plain").lower()
            low = text.lower()
            if style == "plain" and "image 1" not in low and "video 1" not in low:
                cite_bits: list[str] = []
                if imgs:
                    cite_bits.append("Image 1 as subject/style lock")
                if vids:
                    cite_bits.append("Video 1 as camera path / motion only")
                if auds:
                    cite_bits.append("Audio 1 as timed bed")
                if cite_bits:
                    args["prompt"] = (
                        text.rstrip(".") + ". Use " + "; ".join(cite_bits) + "."
                    )
        elif spec.max_refs > 0:
            urls = [u for u in (ref_urls or []) if u]
            if not urls:
                raise ValueError(
                    "Reference pack model needs at least one reference still."
                )
            field = (spec.image_field or "image_urls").strip() or "image_urls"
            # Grok Imagine 1.5 R2V uses reference_image_urls + <IMAGE_n> tags
            if "reference-to-video" in ep and "image_url" not in field:
                field = "reference_image_urls"
            args[field] = urls[: max(1, spec.max_refs)]
            style = (getattr(spec, "prompt_citation_style", None) or "").lower()
            low = text.lower()
            if style == "angle" and "<image_0>" not in low:
                n = min(len(args[field]), 7)
                tags = ", ".join(f"<IMAGE_{i}>" for i in range(n))
                args["prompt"] = (
                    text.rstrip(".")
                    + f". Use {tags} as visual reference(s) for subject and style."
                )
        elif ref_urls and "reference-to-video" in spec.endpoint:
            if "grok-imagine-video" in ep:
                args["reference_image_urls"] = list(ref_urls)[:7]
            else:
                args["image_urls"] = list(ref_urls)[:8]

    # Clean empty optionals
    for k in list(args.keys()):
        if args[k] is None or args[k] == "":
            args.pop(k, None)

    # Single durable aspect policy (omit list + send enums) — last word before return
    from media_studio.aspect_omit import apply_aspect_policy

    req = aspect_ratio
    if req is None and "aspect_ratio" in args:
        req = args.get("aspect_ratio")
    args = apply_aspect_policy(
        args,
        endpoint=spec.endpoint,
        mode=getattr(spec, "mode", None),
        requested=req,
    )
    # Seedance R2V: strict allowlist (no negative_prompt), duration str, res 480p/720p
    from media_studio.aspect_omit import sanitize_seedance_r2v_arguments

    args = sanitize_seedance_r2v_arguments(args, endpoint=spec.endpoint)
    return args
