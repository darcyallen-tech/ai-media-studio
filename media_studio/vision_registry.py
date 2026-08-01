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
    "text_to_video",
    "image_to_video",
    "bridge",
]


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
    # Reference stills (Veo reference-to-video)
    max_refs: int = 0
    # Bridge: first + last frame field names
    first_frame_field: str = "first_frame_url"
    last_frame_field: str = "last_frame_url"
    # I2V start frame / I2I source field
    image_field: str = "image_url"
    # I2V optional end frame (e.g. Hailuo) — hide UI when False
    supports_end_frame: bool = False
    # Image→Image: key into fal IMAGE_EDIT_MODELS for build_edit_arguments
    edit_model_key: str = ""
    # Show strength slider when True (passed if API accepts)
    supports_strength: bool = False
    extra_defaults: dict[str, Any] = field(default_factory=dict)


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
    raw = (aspect_label or "").strip().lower()
    if not raw:
        return "landscape_16_9"
    return _T2I_ASPECT_TO_IMAGE_SIZE.get(raw, "landscape_16_9")


def map_t2i_aspect_colon(aspect_label: str | None) -> str:
    """Map UI aspect label → '16:9' style string for Nano Banana / Recraft / Ultra."""
    raw = (aspect_label or "").strip().lower()
    if not raw:
        return "16:9"
    # Already colon form
    for tok in (
        "21:9",
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
        if tok in raw.replace(" ", ""):
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

I2I_MODELS: dict[str, VisionModelSpec] = {
    "flux 2 pro i2i": VisionModelSpec(
        key="flux 2 pro i2i",
        label="Flux 2 Pro (edit)",
        mode="image_to_image",
        endpoint="fal-ai/flux-2-pro/edit",
        cost_estimate_usd=0.03,
        notes=(
            "Default. Creative single-image edit via Flux 2 Pro. "
            "Ideal for Aleph plate edits (insert creature, giant prop, etc.). ~$0.03/image."
        ),
        duration_choices=(),
        default_duration="",
        aspect_choices=I2I_ASPECT_CHOICES,
        default_aspect="Match source",
        resolution_choices=(),
        default_resolution="",
        supports_audio=False,
        supports_negative=False,
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
        notes="Highest quality Flux edit. ~$0.07 first MP. Strong for detailed creative inserts.",
        duration_choices=(),
        default_duration="",
        aspect_choices=I2I_ASPECT_CHOICES,
        default_aspect="Match source",
        resolution_choices=(),
        default_resolution="",
        supports_audio=False,
        supports_negative=False,
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
        notes="Flux 2 Flex edit — flexible style control. ~$0.04/image.",
        duration_choices=(),
        default_duration="",
        aspect_choices=I2I_ASPECT_CHOICES,
        default_aspect="Match source",
        resolution_choices=(),
        default_resolution="",
        supports_audio=False,
        supports_negative=False,
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
        notes="Flux Kontext Pro single-image edit — strong subject/context preservation.",
        duration_choices=(),
        default_duration="",
        aspect_choices=("Match source", "16:9", "9:16", "4:3", "3:4", "1:1", "3:2", "2:3"),
        default_aspect="Match source",
        resolution_choices=(),
        default_resolution="",
        supports_audio=False,
        supports_negative=False,
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
        notes="Nano Banana Pro edit — excellent prompt adherence for creative inserts. 1K/2K/4K.",
        duration_choices=(),
        default_duration="",
        aspect_choices=("Match source",) + T2I_NANO_ASPECT_CHOICES,
        default_aspect="Match source",
        resolution_choices=T2I_NANO_PRO_RES_CHOICES,
        default_resolution="1K",
        supports_audio=False,
        supports_negative=False,
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
        notes="Nano Banana 2 edit — faster/cheaper creative still edits. 0.5K–4K.",
        duration_choices=(),
        default_duration="",
        aspect_choices=("Match source",) + T2I_NANO_ASPECT_CHOICES,
        default_aspect="Match source",
        resolution_choices=T2I_NANO2_RES_CHOICES,
        default_resolution="1K",
        supports_audio=False,
        supports_negative=False,
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
        notes="Original Nano Banana edit — solid general still edits.",
        duration_choices=(),
        default_duration="",
        aspect_choices=("Match source",) + T2I_NANO_ASPECT_CHOICES,
        default_aspect="Match source",
        resolution_choices=("1K",),
        default_resolution="1K",
        supports_audio=False,
        supports_negative=False,
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
            "Seedream 5 Pro edit — grounded still edits; listing-friendly detail. "
            "Same family as Studio Seedream (single source for Vision I2I v1)."
        ),
        duration_choices=(),
        default_duration="",
        aspect_choices=I2I_ASPECT_CHOICES + ("Auto 2K", "Auto 4K"),
        default_aspect="Match source",
        resolution_choices=(),
        default_resolution="",
        supports_audio=False,
        supports_negative=False,
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
    "veo 3.1 reference": VisionModelSpec(
        key="veo 3.1 reference",
        label="Veo 3.1 Reference pack",
        mode="text_to_video",
        endpoint="fal-ai/veo3.1/reference-to-video",
        # Same standard Veo rate until fal quotes otherwise
        cost_estimate_usd=3.20,  # 8s × $0.40
        cost_per_second=0.40,
        notes="T2V guided by 1–N reference stills. ~$0.40/s on fal (standard Veo family).",
        max_refs=8,
        duration_choices=("8s",),
        default_duration="8s",
        extra_defaults={"generate_audio": True, "auto_fix": False, "safety_tolerance": "4"},
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
}


def models_for_mode(mode: VisionMode) -> dict[str, VisionModelSpec]:
    if mode == "text_to_image":
        return T2I_MODELS
    if mode == "image_to_image":
        return I2I_MODELS
    if mode == "text_to_video":
        return T2V_MODELS
    if mode == "image_to_video":
        return I2V_MODELS
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
        else [T2I_MODELS, I2I_MODELS, T2V_MODELS, I2V_MODELS, BRIDGE_MODELS]
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
        "veo 3.1 fast",
        "veo 3.1 fast i2v",
        "veo 3.1 fast bridge",
    ):
        if key in reg:
            return reg[key]
    return next(iter(reg.values()))


def is_still_mode(mode: VisionMode | str | None) -> bool:
    """True for pure still modes (T2I / I2I) — no video duration / audio."""
    return mode in ("text_to_image", "image_to_image")


def duration_seconds(token: str | None) -> float:
    """
    Parse UI duration tokens to seconds.

    Accepts ``\"8s\"``, ``\"8\"``, ``\"10\"``, etc. Defaults to 8s when missing/invalid.
    """
    if not token:
        return 8.0
    t = str(token).strip().lower()
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


def estimate_vision_cost(
    spec: VisionModelSpec,
    *,
    duration_token: str | None = None,
    resolution: str | None = None,
    aspect_ratio: str | None = None,
    generate_audio: bool | None = None,
) -> float:
    """
    Conservative USD ballpark for UI (not billing).

    Video modes: **total job cost** = rate × selected duration (seconds), then
    resolution / audio multipliers. Never show a bare per-second rate as the total.
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
        return round(max(0.01, base), 3)

    # --- Video: total = per-second rate × duration ---
    dur_token = duration_token if duration_token not in (None, "") else spec.default_duration
    secs = duration_seconds(dur_token)
    default_secs = duration_seconds(spec.default_duration) or 8.0

    if spec.cost_per_second is not None and float(spec.cost_per_second) > 0:
        # Full job total — never return the bare $/s figure
        base = float(spec.cost_per_second) * secs
    else:
        # Flat estimate assumed for default_duration; scale linearly with selected length
        flat = float(spec.cost_estimate_usd or 0.0)
        base = flat * (secs / default_secs) if default_secs > 0 else flat

    # Resolution multipliers only when the model bills by res (not flat $/s Veo)
    ep = (spec.endpoint or "").lower()
    if "veo3.1" not in ep and "veo3" not in ep:
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
) -> str:
    """
    Human label for the **total** estimated job cost.

    Video: ``Est. cost: $X.XX · {duration}s ({model})``
    Still: ``Est. cost: $X.XX · 1 image ({model})``
    """
    from media_studio.pricing import format_job_cost

    amt = estimate_vision_cost(
        spec,
        duration_token=duration_token,
        resolution=resolution,
        aspect_ratio=aspect_ratio,
        generate_audio=generate_audio,
    )
    if is_still_mode(spec.mode):
        return format_job_cost(amt, unit="1 image", model=spec.label)
    dur_token = duration_token if duration_token not in (None, "") else spec.default_duration
    secs = duration_seconds(dur_token)
    dur_txt = f"{secs:.0f}" if abs(secs - round(secs)) < 1e-6 else f"{secs:.1f}"
    return format_job_cost(amt, unit=f"{dur_txt}s", model=spec.label)


def build_vision_arguments(
    spec: VisionModelSpec,
    *,
    prompt: str,
    image_url: str | None = None,
    first_frame_url: str | None = None,
    last_frame_url: str | None = None,
    ref_urls: list[str] | None = None,
    duration: str | None = None,
    aspect_ratio: str | None = None,
    resolution: str | None = None,
    negative_prompt: str | None = None,
    generate_audio: bool | None = None,
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

    dur = (duration or spec.default_duration or "").strip()
    if dur and spec.duration_param and spec.duration_choices:
        # Normalize: some models want "8s", others "8" / "5"
        if "veo" in spec.endpoint or "luma" in spec.endpoint:
            if not dur.endswith("s") and dur.isdigit():
                dur = f"{dur}s"
        elif "kling" in spec.endpoint or "seedance" in spec.endpoint or "hailuo" in spec.endpoint:
            dur = dur.replace("s", "")
        if spec.duration_choices and dur not in spec.duration_choices:
            # try closest allowed
            dur = spec.default_duration
        args[spec.duration_param] = dur

    aspect = (aspect_ratio or spec.default_aspect or "").strip()
    ep = spec.endpoint.lower()

    if "hailuo" in ep:
        res = resolution or spec.default_resolution
        if res:
            args["resolution"] = res
    elif "seedance" in ep:
        if aspect and aspect not in ("", "auto", "—"):
            args["aspect_ratio"] = aspect
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

    neg = (negative_prompt or "").strip()
    if neg and spec.supports_negative:
        args["negative_prompt"] = neg

    if spec.mode == "image_to_video":
        if not image_url:
            raise ValueError("Image→Video needs a start still.")
        args[spec.image_field] = image_url
        # Optional last frame for Hailuo when used as I2V with end
        if last_frame_url and "hailuo" in spec.endpoint:
            args["end_image_url"] = last_frame_url

    elif spec.mode == "bridge":
        if not first_frame_url or not last_frame_url:
            raise ValueError("Bridge needs both a start frame and an end frame.")
        args[spec.first_frame_field] = first_frame_url
        args[spec.last_frame_field] = last_frame_url

    elif spec.mode == "text_to_video":
        if spec.max_refs > 0:
            urls = [u for u in (ref_urls or []) if u]
            if not urls:
                raise ValueError(
                    "Reference pack model needs at least one reference still."
                )
            args["image_urls"] = urls[: max(1, spec.max_refs)]
        elif ref_urls and "reference-to-video" in spec.endpoint:
            args["image_urls"] = list(ref_urls)[:8]

    # Clean empty optionals
    for k in list(args.keys()):
        if args[k] is None or args[k] == "":
            args.pop(k, None)
    return args
