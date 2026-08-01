"""
Supporting tools on fal.ai — upscale, cleanup, sky, dehaze, relight,
restore, blown-out repair, re-aspect.

Each entry is self-contained: endpoint, args builder, cost estimate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolSpec:
    key: str
    label: str
    category: str  # upscale | cleanup | sky | dehaze | relight | restore | blownout | reaspect
    endpoint: str
    cost_estimate_usd: float
    notes: str = ""
    # upscale_factor, etc.
    extra_defaults: dict[str, Any] = field(default_factory=dict)


# --- Upscalers (image) ---
UPSCALERS: dict[str, ToolSpec] = {
    "topaz": ToolSpec(
        key="topaz",
        label="Topaz Upscale",
        category="upscale",
        endpoint="fal-ai/topaz/upscale/image",
        cost_estimate_usd=0.08,
        notes="Professional Topaz image enhance (est. ~$0.08 up to 24MP).",
        extra_defaults={"model": "Standard V2", "upscale_factor": 2, "output_format": "png"},
    ),
    "seedvr": ToolSpec(
        key="seedvr",
        label="SeedVR Upscale",
        category="upscale",
        endpoint="fal-ai/seedvr/upscale/image",
        cost_estimate_usd=0.04,
        notes="SeedVR2 image upscale — sharp, balanced enhancement.",
        extra_defaults={"upscale_mode": "target", "upscale_factor": 2},
    ),
    "recraft crisp": ToolSpec(
        key="recraft crisp",
        label="Recraft Crisp Upscale",
        category="upscale",
        endpoint="fal-ai/recraft/upscale/crisp",
        cost_estimate_usd=0.004,
        notes="Recraft crisp upscale — detail/faces focus, low cost.",
        extra_defaults={},
    ),
}

# --- Video upscalers (V2V — not image-only endpoints) ---
# Cost estimates assume a short RE clip (~5–10s @30fps). UI can refine.
# Topaz families are explicit so denoise vs general vs generative is obvious.
VIDEO_UPSCALERS: dict[str, ToolSpec] = {
    "seedvr video": ToolSpec(
        key="seedvr video",
        label="SeedVR2 Video Upscale",
        category="upscale",
        endpoint="fal-ai/seedvr/upscale/video",
        cost_estimate_usd=0.50,
        notes=(
            "Default general upscale. SeedVR2 temporal — sharp, balanced. "
            "Not a dedicated denoise path (use Video Denoise for high-ISO). "
            "Targets: 720p / 1080p / 1440p / 2160p (4K)."
        ),
        extra_defaults={"upscale_mode": "target", "target_resolution": "1080p"},
    ),
    "bytedance video": ToolSpec(
        key="bytedance video",
        label="Bytedance Video Upscale",
        category="upscale",
        endpoint="fal-ai/bytedance-upscaler/upscale/video",
        cost_estimate_usd=0.07,
        notes=(
            "General temporal upscale — strong edge stability. "
            "Targets: 1080p / 2K / 4K. Est. ~$0.0072/s @1080p 30fps."
        ),
        extra_defaults={"target_resolution": "1080p"},
    ),
    "topaz proteus": ToolSpec(
        key="topaz proteus",
        label="Topaz · Proteus (general upscale)",
        category="upscale",
        endpoint="fal-ai/topaz/upscale/video",
        cost_estimate_usd=0.20,
        notes=(
            "Topaz Proteus — best default general upscale for most listing clips. "
            "Est. ~$0.01/s ≤720p, ~$0.02/s →1080p, ~$0.08/s above 1080p (60fps ×2)."
        ),
        extra_defaults={"model": "Proteus", "upscale_factor": 2},
    ),
    "topaz artemis hq": ToolSpec(
        key="topaz artemis hq",
        label="Topaz · Artemis HQ (denoise+sharpen)",
        category="upscale",
        endpoint="fal-ai/topaz/upscale/video",
        cost_estimate_usd=0.20,
        notes=(
            "Topaz Artemis HQ — denoise + sharpen for degraded / compressed sources. "
            "Prefer Video Denoise tool for pure noise cleanup without a big scale-up."
        ),
        extra_defaults={"model": "Artemis HQ", "upscale_factor": 2},
    ),
    "topaz nyx": ToolSpec(
        key="topaz nyx",
        label="Topaz · Nyx (dedicated denoise)",
        category="upscale",
        endpoint="fal-ai/topaz/upscale/video",
        cost_estimate_usd=0.20,
        notes=(
            "Topaz Nyx — dedicated denoise family. For one-click high-ISO cleanup "
            "with noise/compression sliders, use the Video Denoise tool."
        ),
        extra_defaults={"model": "Nyx", "upscale_factor": 2},
    ),
    "topaz starlight hq": ToolSpec(
        key="topaz starlight hq",
        label="Topaz · Starlight HQ (generative restore)",
        category="upscale",
        endpoint="fal-ai/topaz/upscale/video",
        cost_estimate_usd=0.25,
        notes=(
            "Topaz Starlight HQ — generative diffusion restore/upscale. "
            "Heavier; use when detail needs inventing, not just denoise."
        ),
        extra_defaults={"model": "Starlight HQ", "upscale_factor": 2},
    ),
    "topaz gaia hq": ToolSpec(
        key="topaz gaia hq",
        label="Topaz · Gaia HQ (renders / CG)",
        category="upscale",
        endpoint="fal-ai/topaz/upscale/video",
        cost_estimate_usd=0.20,
        notes=(
            "Topaz Gaia HQ — refined rendered / CG content. "
            "Gaia 2 is half price for animation/motion graphics at 2×."
        ),
        extra_defaults={"model": "Gaia HQ", "upscale_factor": 2},
    ),
    # Legacy key alias kept for sessions that still store "Topaz Video Upscale"
    "topaz video": ToolSpec(
        key="topaz video",
        label="Topaz · Proteus (legacy alias)",
        category="upscale",
        endpoint="fal-ai/topaz/upscale/video",
        cost_estimate_usd=0.20,
        notes="Alias of Proteus for older sessions. Prefer Topaz · Proteus.",
        extra_defaults={"model": "Proteus", "upscale_factor": 2},
    ),
    "realesrgan video": ToolSpec(
        key="realesrgan video",
        label="RealESRGAN Video Upscale",
        category="upscale",
        endpoint="fal-ai/video-upscaler",
        cost_estimate_usd=0.15,
        notes=(
            "Frame-wise RealESRGAN (cheapest). Scale 2×–4×. "
            "No temporal denoise — not ideal for high-ISO interiors."
        ),
        extra_defaults={"scale": 2},
    ),
}

# --- Video Denoise / Clean (Topaz Nyx / Artemis — control-driven) ---
# Same fal endpoint as Topaz upscale; presets + noise/compression for cleanup.
VIDEO_DENOISE_MODELS: dict[str, ToolSpec] = {
    "nyx": ToolSpec(
        key="nyx",
        label="Nyx (dedicated denoise)",
        category="denoise",
        endpoint="fal-ai/topaz/upscale/video",
        cost_estimate_usd=0.16,
        notes="Default. Dedicated Topaz denoise — high-ISO / underexposed interiors.",
        extra_defaults={"model": "Nyx", "upscale_factor": 1.0},
    ),
    "nyx fast": ToolSpec(
        key="nyx fast",
        label="Nyx Fast",
        category="denoise",
        endpoint="fal-ai/topaz/upscale/video",
        cost_estimate_usd=0.14,
        notes="Faster Nyx variant — good preview pass.",
        extra_defaults={"model": "Nyx Fast", "upscale_factor": 1.0},
    ),
    "nyx xl": ToolSpec(
        key="nyx xl",
        label="Nyx XL",
        category="denoise",
        endpoint="fal-ai/topaz/upscale/video",
        cost_estimate_usd=0.20,
        notes="Heavier Nyx — stubborn grain / long night interiors.",
        extra_defaults={"model": "Nyx XL", "upscale_factor": 1.0},
    ),
    "nyx hf": ToolSpec(
        key="nyx hf",
        label="Nyx HF",
        category="denoise",
        endpoint="fal-ai/topaz/upscale/video",
        cost_estimate_usd=0.20,
        notes="Nyx high-frequency variant for fine grain.",
        extra_defaults={"model": "Nyx HF", "upscale_factor": 1.0},
    ),
    "artemis hq": ToolSpec(
        key="artemis hq",
        label="Artemis HQ (denoise + sharpen)",
        category="denoise",
        endpoint="fal-ai/topaz/upscale/video",
        cost_estimate_usd=0.16,
        notes="Denoise + sharpen for compressed / soft listing clips.",
        extra_defaults={"model": "Artemis HQ", "upscale_factor": 1.0},
    ),
    "artemis mq": ToolSpec(
        key="artemis mq",
        label="Artemis MQ",
        category="denoise",
        endpoint="fal-ai/topaz/upscale/video",
        cost_estimate_usd=0.16,
        notes="Artemis medium quality — balance of speed and cleanup.",
        extra_defaults={"model": "Artemis MQ", "upscale_factor": 1.0},
    ),
    "artemis lq": ToolSpec(
        key="artemis lq",
        label="Artemis LQ",
        category="denoise",
        endpoint="fal-ai/topaz/upscale/video",
        cost_estimate_usd=0.14,
        notes="Artemis light / fast cleanup.",
        extra_defaults={"model": "Artemis LQ", "upscale_factor": 1.0},
    ),
}

# --- Frame interpolate / slow-mo ---
VIDEO_INTERPOLATE_MODELS: dict[str, ToolSpec] = {
    "rife": ToolSpec(
        key="rife",
        label="RIFE (fast / cheap)",
        category="interpolate",
        endpoint="fal-ai/rife/video",
        cost_estimate_usd=0.08,
        notes=(
            "Default. Real-Time Intermediate Flow Estimation — fast, cheap. "
            "Smooth 24/30 → 60 or short hero slow-mo. Est. ~$0.0013 / compute-s."
        ),
        extra_defaults={"num_frames": 1, "use_calculated_fps": True, "use_scene_detection": False},
    ),
    "film": ToolSpec(
        key="film",
        label="FILM (large motion)",
        category="interpolate",
        endpoint="fal-ai/film/video",
        cost_estimate_usd=0.15,
        notes=(
            "Frame Interpolation for Large Motion — better on big camera moves. "
            "Slower/costlier than RIFE; enable scene detection when cuts are present."
        ),
        extra_defaults={"num_frames": 1, "use_calculated_fps": True, "use_scene_detection": False},
    ),
}

# Slow-mo factor UI labels → RIFE/FILM num_frames (frames inserted between source frames)
INTERPOLATE_FACTOR_CHOICES: list[str] = [
    "2× (e.g. 30 → 60 fps)",
    "3×",
    "4× (hero slow-mo)",
    "5×",
]

# Common target labels shown in Video Upscale UI
VIDEO_UPSCALE_TARGETS: list[str] = [
    "1080p (Full HD)",
    "1440p (2K)",
    "2160p (4K)",
    "2× scale",
    "4× scale",
]

# Cleanup uses prompt-based edit (no mask required).
# Note: dedicated mask-based erasers (e.g. Bria Eraser) need a mask UI — not practical here.
CLEANUP_MODELS: dict[str, ToolSpec] = {
    "nano banana 2 clean": ToolSpec(
        key="nano banana 2 clean",
        label="Nano Banana 2 (prompt remove)",
        category="cleanup",
        endpoint="fal-ai/nano-banana-2/edit",
        cost_estimate_usd=0.08,
        notes="Default. Prompt-based clutter/object removal via image edit.",
        extra_defaults={"num_images": 1, "resolution": "1K", "output_format": "png"},
    ),
    "nano banana pro clean": ToolSpec(
        key="nano banana pro clean",
        label="Nano Banana Pro (prompt remove)",
        category="cleanup",
        endpoint="fal-ai/nano-banana-pro/edit",
        cost_estimate_usd=0.15,
        notes="Higher-adherence prompt removal for tricky clutter.",
        extra_defaults={"num_images": 1, "resolution": "1K", "output_format": "png"},
    ),
    "flux 2 pro clean": ToolSpec(
        key="flux 2 pro clean",
        label="Flux 2 Pro (prompt remove)",
        category="cleanup",
        endpoint="fal-ai/flux-2-pro/edit",
        cost_estimate_usd=0.03,
        notes="Flux 2 Pro edit for cleanup / background tidy — lower cost.",
        extra_defaults={"image_size": "auto", "output_format": "png"},
    ),
}

# Video object / people / car removal (V2V motion-preserving edit)
VIDEO_CLEANUP_MODELS: dict[str, ToolSpec] = {
    "kling o3 standard clean": ToolSpec(
        key="kling o3 standard clean",
        label="Kling O3 Standard (V2V remove)",
        category="cleanup",
        endpoint="fal-ai/kling-video/o3/standard/video-to-video/edit",
        cost_estimate_usd=0.63,
        notes="Default video. Motion-preserving remove people/cars/clutter (3–15s).",
        extra_defaults={"keep_audio": True},
    ),
    "kling o3 pro clean": ToolSpec(
        key="kling o3 pro clean",
        label="Kling O3 Pro (V2V remove)",
        category="cleanup",
        endpoint="fal-ai/kling-video/o3/pro/video-to-video/edit",
        cost_estimate_usd=0.84,
        notes="Higher-quality V2V object removal; length matches source.",
        extra_defaults={"keep_audio": True},
    ),
    "seedance v2v clean": ToolSpec(
        key="seedance v2v clean",
        label="Seedance 2.0 V2V (remove)",
        category="cleanup",
        endpoint="bytedance/seedance-2.0/reference-to-video",
        cost_estimate_usd=1.50,
        notes="Seedance motion-preserving cleanup via @Video1 (est. ~$0.30/s @720p).",
        extra_defaults={},
    ),
    "grok video clean": ToolSpec(
        key="grok video clean",
        label="Grok Imagine Edit Video (remove)",
        category="cleanup",
        endpoint="xai/grok-imagine-video/edit-video",
        cost_estimate_usd=0.40,
        notes="Grok video edit for remove-people/cars when Kling is unavailable.",
        extra_defaults={"resolution": "auto"},
    ),
}

# Mirror / TV / glass reflection cleanup (still + video)
MIRROR_MODELS: dict[str, ToolSpec] = {
    "nano banana 2 mirror": ToolSpec(
        key="nano banana 2 mirror",
        label="Nano Banana 2 (mirror/glass)",
        category="mirror",
        endpoint="fal-ai/nano-banana-2/edit",
        cost_estimate_usd=0.08,
        notes="Default still. Remove reflected person/tripod only; keep frame & room.",
        extra_defaults={"num_images": 1, "resolution": "1K", "output_format": "png"},
    ),
    "flux 2 pro mirror": ToolSpec(
        key="flux 2 pro mirror",
        label="Flux 2 Pro (mirror/glass)",
        category="mirror",
        endpoint="fal-ai/flux-2-pro/edit",
        cost_estimate_usd=0.03,
        notes="Economical mirror/glass reflection cleanup.",
        extra_defaults={"image_size": "auto", "output_format": "png"},
    ),
    "seedream mirror": ToolSpec(
        key="seedream mirror",
        label="Seedream 5 Pro (mirror/glass)",
        category="mirror",
        endpoint="bytedance/seedream/v5/pro/edit",
        cost_estimate_usd=0.07,
        notes="Strong localized reflection cleanup.",
        extra_defaults={"num_images": 1, "image_size": "auto_2K"},
    ),
}

VIDEO_MIRROR_MODELS: dict[str, ToolSpec] = {
    "kling o3 standard mirror": ToolSpec(
        key="kling o3 standard mirror",
        label="Kling O3 Standard (V2V mirror)",
        category="mirror",
        endpoint="fal-ai/kling-video/o3/standard/video-to-video/edit",
        cost_estimate_usd=0.63,
        notes="Default video. Remove operator reflection while preserving motion.",
        extra_defaults={"keep_audio": True},
    ),
    "kling o3 pro mirror": ToolSpec(
        key="kling o3 pro mirror",
        label="Kling O3 Pro (V2V mirror)",
        category="mirror",
        endpoint="fal-ai/kling-video/o3/pro/video-to-video/edit",
        cost_estimate_usd=0.84,
        notes="Higher-quality V2V mirror/glass cleanup.",
        extra_defaults={"keep_audio": True},
    ),
}

# Amenity “turn on” (pool, fireplace, lights)
AMENITY_MODELS: dict[str, ToolSpec] = {
    "flux 2 pro amenity": ToolSpec(
        key="flux 2 pro amenity",
        label="Flux 2 Pro (amenity on)",
        category="amenity",
        endpoint="fal-ai/flux-2-pro/edit",
        cost_estimate_usd=0.03,
        notes="Default. Activate pool/fire/lights only; structure locked.",
        extra_defaults={"image_size": "auto", "output_format": "png"},
    ),
    "nano banana 2 amenity": ToolSpec(
        key="nano banana 2 amenity",
        label="Nano Banana 2 (amenity on)",
        category="amenity",
        endpoint="fal-ai/nano-banana-2/edit",
        cost_estimate_usd=0.08,
        notes="Strong amenity activation adherence.",
        extra_defaults={"num_images": 1, "resolution": "1K", "output_format": "png"},
    ),
    "seedream amenity": ToolSpec(
        key="seedream amenity",
        label="Seedream 5 Pro (amenity on)",
        category="amenity",
        endpoint="bytedance/seedream/v5/pro/edit",
        cost_estimate_usd=0.07,
        notes="Detail-rich pool/fire/light activation.",
        extra_defaults={"num_images": 1, "image_size": "auto_2K"},
    ),
}

VIDEO_AMENITY_MODELS: dict[str, ToolSpec] = {
    "kling o3 standard amenity": ToolSpec(
        key="kling o3 standard amenity",
        label="Kling O3 Standard (V2V amenity)",
        category="amenity",
        endpoint="fal-ai/kling-video/o3/standard/video-to-video/edit",
        cost_estimate_usd=0.63,
        notes="Motion-preserving amenity activation on a clip.",
        extra_defaults={"keep_audio": True},
    ),
}

# Match AI plate grade to source look
MATCH_LOOK_MODELS: dict[str, ToolSpec] = {
    "flux 2 pro match": ToolSpec(
        key="flux 2 pro match",
        label="Flux 2 Pro (match source look)",
        category="match_look",
        endpoint="fal-ai/flux-2-pro/edit",
        cost_estimate_usd=0.03,
        notes="Default. Pull contrast/WB/grade toward source still.",
        extra_defaults={"image_size": "auto", "output_format": "png"},
    ),
    "nano banana 2 match": ToolSpec(
        key="nano banana 2 match",
        label="Nano Banana 2 (match source look)",
        category="match_look",
        endpoint="fal-ai/nano-banana-2/edit",
        cost_estimate_usd=0.08,
        notes="Strong color-match of AI plate to source.",
        extra_defaults={"num_images": 1, "resolution": "1K", "output_format": "png"},
    ),
    "seedream match": ToolSpec(
        key="seedream match",
        label="Seedream 5 Pro (match source look)",
        category="match_look",
        endpoint="bytedance/seedream/v5/pro/edit",
        cost_estimate_usd=0.07,
        notes="Multi-ref capable grade match when source is passed as ref.",
        extra_defaults={"num_images": 1, "image_size": "auto_2K"},
    ),
}

# Season / curb appeal (still)
SEASON_MODELS: dict[str, ToolSpec] = {
    "flux 2 pro season": ToolSpec(
        key="flux 2 pro season",
        label="Flux 2 Pro (season / curb)",
        category="season",
        endpoint="fal-ai/flux-2-pro/edit",
        cost_estimate_usd=0.03,
        notes="Default. Season/landscape cues only; house & hardscape locked.",
        extra_defaults={"image_size": "auto", "output_format": "png"},
    ),
    "nano banana 2 season": ToolSpec(
        key="nano banana 2 season",
        label="Nano Banana 2 (season / curb)",
        category="season",
        endpoint="fal-ai/nano-banana-2/edit",
        cost_estimate_usd=0.08,
        notes="Strong seasonal landscape change.",
        extra_defaults={"num_images": 1, "resolution": "1K", "output_format": "png"},
    ),
    "seedream season": ToolSpec(
        key="seedream season",
        label="Seedream 5 Pro (season / curb)",
        category="season",
        endpoint="bytedance/seedream/v5/pro/edit",
        cost_estimate_usd=0.07,
        notes="Detail-rich season/curb-appeal pass.",
        extra_defaults={"num_images": 1, "image_size": "auto_2K"},
    ),
}

SKY_MODELS: dict[str, ToolSpec] = {
    "nano banana 2 sky": ToolSpec(
        key="nano banana 2 sky",
        label="Nano Banana 2 Sky Replace",
        category="sky",
        endpoint="fal-ai/nano-banana-2/edit",
        cost_estimate_usd=0.08,
        notes="Default. Replace sky via natural-language edit; preserves architecture.",
        extra_defaults={"num_images": 1, "resolution": "1K", "output_format": "png"},
    ),
    "nano banana pro sky": ToolSpec(
        key="nano banana pro sky",
        label="Nano Banana Pro Sky Replace",
        category="sky",
        endpoint="fal-ai/nano-banana-pro/edit",
        cost_estimate_usd=0.15,
        notes="Higher-quality sky swap when lighting match matters.",
        extra_defaults={"num_images": 1, "resolution": "1K", "output_format": "png"},
    ),
    "flux 2 pro sky": ToolSpec(
        key="flux 2 pro sky",
        label="Flux 2 Pro Sky Replace",
        category="sky",
        endpoint="fal-ai/flux-2-pro/edit",
        cost_estimate_usd=0.03,
        notes="Flux 2 Pro sky pass — fast / economical.",
        extra_defaults={"image_size": "auto", "output_format": "png"},
    ),
}

# Video sky / weather V2V (motion-stable exterior sky)
VIDEO_SKY_MODELS: dict[str, ToolSpec] = {
    "kling o3 standard sky": ToolSpec(
        key="kling o3 standard sky",
        label="Kling O3 Standard (V2V sky)",
        category="sky",
        endpoint="fal-ai/kling-video/o3/standard/video-to-video/edit",
        cost_estimate_usd=0.63,
        notes="Default video. Sky/weather only under camera motion; architecture locked.",
        extra_defaults={"keep_audio": True},
    ),
    "kling o3 pro sky": ToolSpec(
        key="kling o3 pro sky",
        label="Kling O3 Pro (V2V sky)",
        category="sky",
        endpoint="fal-ai/kling-video/o3/pro/video-to-video/edit",
        cost_estimate_usd=0.84,
        notes="Higher-quality V2V sky/weather pass.",
        extra_defaults={"keep_audio": True},
    ),
    "seedance v2v sky": ToolSpec(
        key="seedance v2v sky",
        label="Seedance 2.0 V2V (sky)",
        category="sky",
        endpoint="bytedance/seedance-2.0/reference-to-video",
        cost_estimate_usd=1.50,
        notes="Seedance sky transfer via @Video1 (+ optional sky ref still).",
        extra_defaults={},
    ),
}

# No dedicated MixDehazer on fal — use strong prompt-driven edit models.
DEHAZE_MODELS: dict[str, ToolSpec] = {
    "nano banana 2 dehaze": ToolSpec(
        key="nano banana 2 dehaze",
        label="Nano Banana 2 Dehaze",
        category="dehaze",
        endpoint="fal-ai/nano-banana-2/edit",
        cost_estimate_usd=0.08,
        notes="Default. Clear smoke/haze/smog while keeping the property unchanged.",
        extra_defaults={"num_images": 1, "resolution": "1K", "output_format": "png"},
    ),
    "flux 2 pro dehaze": ToolSpec(
        key="flux 2 pro dehaze",
        label="Flux 2 Pro Dehaze",
        category="dehaze",
        endpoint="fal-ai/flux-2-pro/edit",
        cost_estimate_usd=0.03,
        notes="Flux 2 Pro clear-air fallback for exteriors.",
        extra_defaults={"image_size": "auto", "output_format": "png"},
    ),
    "nano banana pro dehaze": ToolSpec(
        key="nano banana pro dehaze",
        label="Nano Banana Pro Dehaze",
        category="dehaze",
        endpoint="fal-ai/nano-banana-pro/edit",
        cost_estimate_usd=0.15,
        notes="Stronger clear-air pass when haze is heavy.",
        extra_defaults={"num_images": 1, "resolution": "1K", "output_format": "png"},
    ),
}

RELIGHT_MODELS: dict[str, ToolSpec] = {
    "nano banana 2 relight": ToolSpec(
        key="nano banana 2 relight",
        label="Nano Banana 2 Relight",
        category="relight",
        endpoint="fal-ai/nano-banana-2/edit",
        cost_estimate_usd=0.08,
        notes="Relight interiors/exteriors while keeping geometry.",
        extra_defaults={"num_images": 1, "resolution": "1K", "output_format": "png"},
    ),
    "flux 2 pro relight": ToolSpec(
        key="flux 2 pro relight",
        label="Flux 2 Pro Relight",
        category="relight",
        endpoint="fal-ai/flux-2-pro/edit",
        cost_estimate_usd=0.03,
        notes="Flux 2 Pro lighting adjustment.",
        extra_defaults={"image_size": "auto", "output_format": "png"},
    ),
}

# --- Sharpen / Restore (face recovery, soft realtor shots) ---
# Without reference: CodeFormer (fidelity) default; NAFNet whole-frame deblur.
# With reference: multi-image identity lock default; specialized models still listed.
RESTORE_IMAGE_NO_REF: dict[str, ToolSpec] = {
    "codeformer": ToolSpec(
        key="codeformer",
        label="CodeFormer (face restore)",
        category="restore",
        endpoint="fal-ai/codeformer",
        cost_estimate_usd=0.01,
        notes=(
            "Default without reference. Face-first restore with fidelity control "
            "(higher = keep original identity closer). ~$0.002/MP on fal."
        ),
        extra_defaults={"fidelity": 0.7, "upscale_factor": 1, "face_upscale": True},
    ),
    "nafnet deblur": ToolSpec(
        key="nafnet deblur",
        label="NAFNet Deblur (whole frame)",
        category="restore",
        endpoint="fal-ai/nafnet/deblur",
        cost_estimate_usd=0.025,
        notes=(
            "Whole-frame soft/defocus/motion blur restore (no prompt, no ref still). "
            "~$0.0225 per megapixel on fal."
        ),
        extra_defaults={},
    ),
    "nano banana 2 restore": ToolSpec(
        key="nano banana 2 restore",
        label="Nano Banana 2 (prompt restore)",
        category="restore",
        endpoint="fal-ai/nano-banana-2/edit",
        cost_estimate_usd=0.08,
        notes="Prompt-based sharpen/restore without a reference still.",
        extra_defaults={"num_images": 1, "resolution": "1K", "output_format": "png"},
    ),
    "flux kontext restore": ToolSpec(
        key="flux kontext restore",
        label="Flux Kontext Pro (prompt restore)",
        category="restore",
        endpoint="fal-ai/flux-pro/kontext",
        cost_estimate_usd=0.04,
        notes="Single-image Flux Kontext sharpen — no multi-ref.",
        extra_defaults={},
    ),
    "grok imagine restore": ToolSpec(
        key="grok imagine restore",
        label="Grok Imagine Edit (prompt restore)",
        category="restore",
        endpoint="xai/grok-imagine-image/edit",
        cost_estimate_usd=0.022,
        notes="Grok Imagine single-source restore when CodeFormer is not enough.",
        extra_defaults={"num_images": 1, "resolution": "1k", "output_format": "jpeg"},
    ),
}

RESTORE_IMAGE_WITH_REF: dict[str, ToolSpec] = {
    "nano banana 2 restore ref": ToolSpec(
        key="nano banana 2 restore ref",
        label="Nano Banana 2 (ref identity)",
        category="restore",
        endpoint="fal-ai/nano-banana-2/edit",
        cost_estimate_usd=0.08,
        notes="Default with reference. Multi-image edit — soft source + sharp identity still.",
        extra_defaults={"num_images": 1, "resolution": "1K", "output_format": "png"},
    ),
    "nano banana pro restore ref": ToolSpec(
        key="nano banana pro restore ref",
        label="Nano Banana Pro (ref identity)",
        category="restore",
        endpoint="fal-ai/nano-banana-pro/edit",
        cost_estimate_usd=0.15,
        notes="Stronger identity lock from the reference still.",
        extra_defaults={"num_images": 1, "resolution": "1K", "output_format": "png"},
    ),
    "grok imagine restore ref": ToolSpec(
        key="grok imagine restore ref",
        label="Grok Imagine Edit (ref identity)",
        category="restore",
        endpoint="xai/grok-imagine-image/edit",
        cost_estimate_usd=0.022,
        notes="Grok multi-image edit — soft source + sharp person reference.",
        extra_defaults={"num_images": 1, "resolution": "1k", "output_format": "jpeg"},
    ),
    "seedream restore ref": ToolSpec(
        key="seedream restore ref",
        label="Seedream 5 Pro (ref identity)",
        category="restore",
        endpoint="fal-ai/bytedance/seedream/v4.5/edit",
        cost_estimate_usd=0.04,
        notes="Seedream multi-ref restore — good face/product detail.",
        extra_defaults={"num_images": 1, "image_size": "auto_2K", "enable_safety_checker": True},
    ),
    "flux 2 pro restore ref": ToolSpec(
        key="flux 2 pro restore ref",
        label="Flux 2 Pro (ref identity)",
        category="restore",
        endpoint="fal-ai/flux-2-pro/edit",
        cost_estimate_usd=0.03,
        notes="Flux 2 Pro multi-ref restore — economical.",
        extra_defaults={"image_size": "auto", "output_format": "png"},
    ),
    # Specialized (no multi-ref guidance — ref still ignored)
    "codeformer": ToolSpec(
        key="codeformer",
        label="CodeFormer (face restore)",
        category="restore",
        endpoint="fal-ai/codeformer",
        cost_estimate_usd=0.01,
        notes=(
            "Face-first restore with fidelity control. Reference still is not used "
            "by this model — clear ref or use a ref-identity model for guidance."
        ),
        extra_defaults={"fidelity": 0.7, "upscale_factor": 1, "face_upscale": True},
    ),
    "nafnet deblur": ToolSpec(
        key="nafnet deblur",
        label="NAFNet Deblur (whole frame)",
        category="restore",
        endpoint="fal-ai/nafnet/deblur",
        cost_estimate_usd=0.025,
        notes=(
            "Whole-frame soft/defocus/motion blur. Reference still is not used. "
            "~$0.0225/MP on fal."
        ),
        extra_defaults={},
    ),
}

RESTORE_VIDEO_MODELS: dict[str, ToolSpec] = {
    "kling o3 standard restore": ToolSpec(
        key="kling o3 standard restore",
        label="Kling O3 Standard (V2V)",
        category="restore",
        endpoint="fal-ai/kling-video/o3/standard/video-to-video/edit",
        cost_estimate_usd=0.63,  # ~5s @ $0.126/s
        notes="Default video. Motion-preserving face restore; accepts reference still.",
        extra_defaults={"keep_audio": True},
    ),
    "kling o3 pro restore": ToolSpec(
        key="kling o3 pro restore",
        label="Kling O3 Pro (V2V)",
        category="restore",
        endpoint="fal-ai/kling-video/o3/pro/video-to-video/edit",
        cost_estimate_usd=0.84,
        notes="Higher-quality V2V restore; length matches source (3–15s).",
        extra_defaults={"keep_audio": True},
    ),
    "grok imagine restore video": ToolSpec(
        key="grok imagine restore video",
        label="Grok Imagine Edit Video",
        category="restore",
        endpoint="xai/grok-imagine-video/edit-video",
        cost_estimate_usd=0.40,  # ~5s @ ~$0.08/s
        notes=(
            "Grok video edit (prompt + clip). Reference still is identity guidance in the "
            "prompt only — API does not take multi-ref images."
        ),
        extra_defaults={"resolution": "auto"},
    ),
}

RESTORE_PROMPT_CORE = (
    "Restore sharpness and clear facial detail on the subject. "
    "If a reference image is provided, match that person's exact identity and features. "
    "Do not invent a different face. "
    "Keep pose, body, clothing, camera movement, and background unchanged."
)

# --- Blown-out window repair (interior RE) ---
BLOWN_OUT_MODELS: dict[str, ToolSpec] = {
    "nano banana 2 blownout": ToolSpec(
        key="nano banana 2 blownout",
        label="Nano Banana 2 (window repair)",
        category="blownout",
        endpoint="fal-ai/nano-banana-2/edit",
        cost_estimate_usd=0.08,
        notes="Default. Localized window exposure repair with strong adherence.",
        extra_defaults={"num_images": 1, "resolution": "1K", "output_format": "png"},
    ),
    "nano banana pro blownout": ToolSpec(
        key="nano banana pro blownout",
        label="Nano Banana Pro (window repair)",
        category="blownout",
        endpoint="fal-ai/nano-banana-pro/edit",
        cost_estimate_usd=0.15,
        notes="Higher-adherence repair for stubborn blown highlights.",
        extra_defaults={"num_images": 1, "resolution": "1K", "output_format": "png"},
    ),
    "flux kontext blownout": ToolSpec(
        key="flux kontext blownout",
        label="Flux Kontext Pro (window repair)",
        category="blownout",
        endpoint="fal-ai/flux-pro/kontext",
        cost_estimate_usd=0.04,
        notes="Kontext single-image localized edit — good for window glass only.",
        extra_defaults={},
    ),
    "flux 2 pro blownout": ToolSpec(
        key="flux 2 pro blownout",
        label="Flux 2 Pro (window repair)",
        category="blownout",
        endpoint="fal-ai/flux-2-pro/edit",
        cost_estimate_usd=0.03,
        notes="Flux 2 Pro edit — economical window recovery.",
        extra_defaults={"image_size": "auto", "output_format": "png"},
    ),
    "seedream blownout": ToolSpec(
        key="seedream blownout",
        label="Seedream 5 Pro (window repair)",
        category="blownout",
        endpoint="fal-ai/bytedance/seedream/v4.5/edit",
        cost_estimate_usd=0.04,
        notes="Seedream multi-ref class edit for detail recovery.",
        extra_defaults={"num_images": 1, "image_size": "auto_2K", "enable_safety_checker": True},
    ),
    "grok imagine blownout": ToolSpec(
        key="grok imagine blownout",
        label="Grok Imagine Edit (window repair)",
        category="blownout",
        endpoint="xai/grok-imagine-image/edit",
        cost_estimate_usd=0.022,
        notes="Grok Imagine edit for blown-window recovery.",
        extra_defaults={"num_images": 1, "resolution": "1k", "output_format": "jpeg"},
    ),
}

BLOWN_OUT_PROMPT_CORE = (
    "Realistically repair the overexposed or blown-out window(s) only. "
    "Recover natural exterior detail and correct exposure through the glass. "
    "Do not change walls, furniture, flooring, lighting on interior surfaces, "
    "camera angle, or any other part of the image."
)

# --- Re-Aspect (image + video reframe / outpaint) ---
REASPECT_ASPECT_CHOICES = [
    "9:16 (Vertical / Reels)",
    "16:9 (Horizontal / landscape)",
    "1:1 (Square)",
    "4:5 (Portrait feed)",
    "4:3 (Classic)",
    "3:4 (Portrait)",
    "21:9 (Ultrawide)",
    "5:4",
]

REASPECT_IMAGE_MODELS: dict[str, ToolSpec] = {
    "image reframe": ToolSpec(
        key="image reframe",
        label="Image Reframe (fal)",
        category="reaspect",
        endpoint="fal-ai/image-editing/reframe",
        cost_estimate_usd=0.04,
        notes="Default. Intelligent reframe to target aspect — preserves subject.",
        extra_defaults={"output_format": "png"},
    ),
    "luma photon reframe": ToolSpec(
        key="luma photon reframe",
        label="Luma Photon Reframe",
        category="reaspect",
        endpoint="fal-ai/luma-photon/reframe",
        cost_estimate_usd=0.05,
        notes="Luma Photon generative reframe / outpaint to new aspect ratio.",
        extra_defaults={},
    ),
    "nano banana 2 reaspect": ToolSpec(
        key="nano banana 2 reaspect",
        label="Nano Banana 2 (outpaint prompt)",
        category="reaspect",
        endpoint="fal-ai/nano-banana-2/edit",
        cost_estimate_usd=0.08,
        notes="Prompt-based outpaint reframe when dedicated reframe fails.",
        extra_defaults={"num_images": 1, "resolution": "1K", "output_format": "png"},
    ),
    "flux 2 pro reaspect": ToolSpec(
        key="flux 2 pro reaspect",
        label="Flux 2 Pro (outpaint prompt)",
        category="reaspect",
        endpoint="fal-ai/flux-2-pro/edit",
        cost_estimate_usd=0.03,
        notes="Flux edit outpaint fallback for aspect change.",
        extra_defaults={"image_size": "auto", "output_format": "png"},
    ),
}

REASPECT_VIDEO_MODELS: dict[str, ToolSpec] = {
    "ltx reframe": ToolSpec(
        key="ltx reframe",
        label="LTX 2.3 Reframe",
        category="reaspect",
        endpoint="fal-ai/ltx-2.3/reframe",
        cost_estimate_usd=0.50,  # short clip ballpark
        notes=(
            "Default video. Generative reframe up to ~60s; 720p/1080p; "
            "1:1, 4:5, 5:4, 9:16, 16:9. Ideal for Horizontal → Vertical Reels."
        ),
        extra_defaults={"resolution": "1080p"},
    ),
    "luma ray reframe": ToolSpec(
        key="luma ray reframe",
        label="Luma Ray 2 Reframe",
        category="reaspect",
        endpoint="fal-ai/luma-dream-machine/ray-2/reframe",
        cost_estimate_usd=0.80,
        notes="Luma Ray 2 video reframe with coherent edge fill.",
        extra_defaults={},
    ),
}

REASPECT_PROMPT_CORE = (
    "Reframe this real-estate media to the target aspect ratio. "
    "Preserve the subject, composition, architecture, furniture, and style. "
    "Extend only the necessary edges to fill the new frame; match existing "
    "lighting, materials, and perspective. Do not crop away important content "
    "when generative fill can expand the frame instead."
)


def upscale_labels() -> list[str]:
    return [s.label for s in UPSCALERS.values()]


def video_upscale_labels() -> list[str]:
    # Prefer family-named Topaz entries; hide legacy alias from the picker
    out: list[str] = []
    for s in VIDEO_UPSCALERS.values():
        if s.key == "topaz video":
            continue
        out.append(s.label)
    return out


def video_denoise_labels() -> list[str]:
    return [s.label for s in VIDEO_DENOISE_MODELS.values()]


def video_interpolate_labels() -> list[str]:
    return [s.label for s in VIDEO_INTERPOLATE_MODELS.values()]


def cleanup_labels() -> list[str]:
    return [s.label for s in CLEANUP_MODELS.values()]


def video_cleanup_labels() -> list[str]:
    return [s.label for s in VIDEO_CLEANUP_MODELS.values()]


def sky_labels() -> list[str]:
    return [s.label for s in SKY_MODELS.values()]


def video_sky_labels() -> list[str]:
    return [s.label for s in VIDEO_SKY_MODELS.values()]


def mirror_labels() -> list[str]:
    return [s.label for s in MIRROR_MODELS.values()]


def video_mirror_labels() -> list[str]:
    return [s.label for s in VIDEO_MIRROR_MODELS.values()]


def amenity_labels() -> list[str]:
    return [s.label for s in AMENITY_MODELS.values()]


def video_amenity_labels() -> list[str]:
    return [s.label for s in VIDEO_AMENITY_MODELS.values()]


def match_look_labels() -> list[str]:
    return [s.label for s in MATCH_LOOK_MODELS.values()]


def season_tool_labels() -> list[str]:
    return [s.label for s in SEASON_MODELS.values()]


def dehaze_labels() -> list[str]:
    return [s.label for s in DEHAZE_MODELS.values()]


def relight_labels() -> list[str]:
    return [s.label for s in RELIGHT_MODELS.values()]


def restore_image_labels(*, has_reference: bool) -> list[str]:
    reg = RESTORE_IMAGE_WITH_REF if has_reference else RESTORE_IMAGE_NO_REF
    return [s.label for s in reg.values()]


def restore_video_labels() -> list[str]:
    return [s.label for s in RESTORE_VIDEO_MODELS.values()]


def restore_image_registry(*, has_reference: bool) -> dict[str, ToolSpec]:
    return RESTORE_IMAGE_WITH_REF if has_reference else RESTORE_IMAGE_NO_REF


def blown_out_labels() -> list[str]:
    return [s.label for s in BLOWN_OUT_MODELS.values()]


def reaspect_image_labels() -> list[str]:
    return [s.label for s in REASPECT_IMAGE_MODELS.values()]


def reaspect_video_labels() -> list[str]:
    return [s.label for s in REASPECT_VIDEO_MODELS.values()]


def parse_aspect_choice(label: str | None) -> str:
    """'9:16 (Vertical / Reels)' → '9:16'."""
    raw = (label or "").strip()
    if not raw:
        return "9:16"
    token = raw.split()[0].split("(")[0].strip()
    if ":" in token:
        return token
    return raw


def find_tool(label_or_key: str | None, registry: dict[str, ToolSpec]) -> ToolSpec | None:
    if not label_or_key:
        return None
    raw = label_or_key.strip().lower()
    if raw in registry:
        return registry[raw]
    for spec in registry.values():
        if spec.label.lower() == raw or spec.key == raw:
            return spec
    return None


def build_upscale_args(spec: ToolSpec, image_url: str, upscale_factor: float = 2.0) -> dict[str, Any]:
    args = dict(spec.extra_defaults)
    args["image_url"] = image_url
    # Topaz / SeedVR use upscale_factor; Recraft often just needs image_url
    if "upscale_factor" in args or "topaz" in spec.endpoint or "seedvr" in spec.endpoint:
        args["upscale_factor"] = float(upscale_factor)
    return args


def parse_video_upscale_target(label: str | None) -> dict[str, Any]:
    """
    Map UI target labels → API kwargs.

    Returns keys used by build_video_upscale_args:
      target_resolution (e.g. '1080p'), scale_factor (float), or empty.
    """
    raw = (label or "").strip().lower()
    if not raw:
        return {"target_resolution": "1080p"}
    if "4k" in raw or "2160" in raw:
        return {"target_resolution": "2160p"}
    if "1440" in raw or "2k" in raw:
        return {"target_resolution": "1440p"}
    if "1080" in raw:
        return {"target_resolution": "1080p"}
    if "720" in raw:
        return {"target_resolution": "720p"}
    if "4×" in raw or "4x" in raw or raw.startswith("4"):
        return {"scale_factor": 4.0}
    if "2×" in raw or "2x" in raw or raw.startswith("2"):
        return {"scale_factor": 2.0}
    return {"target_resolution": "1080p"}


def build_video_upscale_args(
    spec: ToolSpec,
    video_url: str,
    *,
    target_label: str | None = None,
    upscale_factor: float | None = None,
) -> dict[str, Any]:
    """Build fal args for a video upscaler endpoint."""
    args = dict(spec.extra_defaults)
    args["video_url"] = video_url
    parsed = parse_video_upscale_target(target_label)
    target_res = parsed.get("target_resolution")
    scale = parsed.get("scale_factor")
    if upscale_factor is not None:
        scale = float(upscale_factor)

    ep = spec.endpoint.lower()
    # SeedVR: upscale_mode target|factor + target_resolution | upscale_factor
    if "seedvr" in ep:
        if scale is not None and not target_res:
            args["upscale_mode"] = "factor"
            args["upscale_factor"] = float(scale)
            args.pop("target_resolution", None)
        else:
            args["upscale_mode"] = "target"
            # SeedVR accepts 720p, 1080p, 1440p, 2160p
            res = str(target_res or "1080p")
            if res == "2k":
                res = "1440p"
            if res in ("4k", "4K"):
                res = "2160p"
            args["target_resolution"] = res
            args.pop("upscale_factor", None)
    # Bytedance: target_resolution 1080p / 2k / 4k
    elif "bytedance-upscaler" in ep or "bytedance" in ep and "upscale" in ep:
        res = str(target_res or "1080p")
        if res in ("2160p", "4k", "4K"):
            res = "4k"
        elif res in ("1440p", "2k", "2K"):
            res = "2k"
        elif res == "720p":
            res = "1080p"  # bytedance starts at 1080p
        else:
            res = "1080p"
        args["target_resolution"] = res
        args.pop("upscale_factor", None)
        args.pop("scale", None)
    # Topaz video: model (from extra_defaults) + upscale_factor
    elif "topaz" in ep:
        factor = float(scale if scale is not None else args.get("upscale_factor") or 2.0)
        args["upscale_factor"] = max(1.0, min(4.0, factor))
        # Keep model from extra_defaults when present
        if "model" not in args:
            args["model"] = "Proteus"
        args.pop("target_resolution", None)
    # RealESRGAN fal-ai/video-upscaler: scale
    elif ep.endswith("video-upscaler") or "video-upscaler" in ep:
        args["scale"] = float(scale if scale is not None else 2.0)
        args.pop("target_resolution", None)
        args.pop("upscale_factor", None)
    else:
        if scale is not None:
            args["upscale_factor"] = float(scale)
        if target_res:
            args["target_resolution"] = target_res
    return args


def estimate_video_upscale_cost(
    spec: ToolSpec,
    *,
    target_label: str | None = None,
    duration_s: float = 8.0,
) -> float:
    """Rough pre-generate estimate for a short real-estate clip."""
    parsed = parse_video_upscale_target(target_label)
    res = str(parsed.get("target_resolution") or "")
    scale = parsed.get("scale_factor")
    dur = max(1.0, float(duration_s or 8.0))
    ep = spec.endpoint.lower()
    key = spec.key.lower()

    if "seedvr" in ep or "seedvr" in key:
        # ~$0.001 / MP of frames; assume 30fps, common targets
        mp_per_frame = {
            "720p": 0.92,
            "1080p": 2.07,
            "1440p": 3.69,
            "2160p": 8.29,
        }.get(res, 2.07)
        if scale:
            # unknown source — ballpark from 720p source
            mp_per_frame = 0.92 * (float(scale) ** 2)
        frames = dur * 30.0
        return max(0.05, frames * mp_per_frame * 0.001)

    if "bytedance" in ep or "bytedance" in key:
        per_s = {"1080p": 0.0072, "1440p": 0.0144, "2k": 0.0144, "2160p": 0.0288, "4k": 0.0288}
        rate = per_s.get(res, 0.0072)
        if scale and float(scale) >= 3.5:
            rate = 0.0288
        elif scale and float(scale) >= 1.5:
            rate = 0.0072
        return max(0.03, rate * dur)

    if "topaz" in ep or "topaz" in key:
        # $0.01/s ≤720, $0.02 720→1080, $0.08 above 1080
        if res in ("2160p", "4k", "1440p", "2k") or (scale and float(scale) >= 3):
            rate = 0.08
        elif res in ("1080p",) or (scale and float(scale) >= 1.5):
            rate = 0.02
        else:
            rate = 0.01
        return max(0.05, rate * dur)

    if "video-upscaler" in ep or "realesrgan" in key:
        # $0.0008 / MP; assume 720p source × scale
        sc = float(scale or 2.0)
        mp = 0.92 * (sc ** 2) * dur * 30.0
        return max(0.03, mp * 0.0008)

    return float(spec.cost_estimate_usd)


def format_video_upscale_cost(
    spec: ToolSpec,
    *,
    target_label: str | None = None,
    duration_s: float = 8.0,
) -> str:
    from media_studio.pricing import format_job_cost

    usd = estimate_video_upscale_cost(spec, target_label=target_label, duration_s=duration_s)
    dur = max(1, int(round(float(duration_s or 8.0))))
    tgt = (target_label or "").strip()
    unit = f"{dur}s" + (f" · {tgt}" if tgt else "")
    return format_job_cost(usd, unit=unit, model=spec.label)


def parse_interpolate_factor(label: str | None) -> int:
    """
    Map UI slow-mo factor → RIFE/FILM ``num_frames`` (frames inserted between).

    2× → 1 intermediate, 4× → 3 intermediates, etc.
    """
    raw = (label or "").strip().lower()
    mult = 2
    for n in (5, 4, 3, 2):
        if f"{n}×" in raw or f"{n}x" in raw or raw.startswith(str(n)):
            mult = n
            break
    # num_frames = multiplier - 1 (API inserts N frames between each pair)
    return max(1, min(4, mult - 1))


def build_video_denoise_args(
    spec: ToolSpec,
    video_url: str,
    *,
    noise: float | None = None,
    compression: float | None = None,
    recover_detail: float | None = None,
    halo: float | None = None,
    upscale_factor: float | None = None,
) -> dict[str, Any]:
    """Topaz video enhance args focused on denoise/cleanup (control-driven)."""
    args = dict(spec.extra_defaults)
    args["video_url"] = video_url
    if "model" not in args:
        args["model"] = "Nyx"
    factor = float(upscale_factor if upscale_factor is not None else args.get("upscale_factor") or 1.0)
    args["upscale_factor"] = max(1.0, min(4.0, factor))
    # Only send controls when set (API defaults vary by model)
    if noise is not None:
        args["noise"] = max(0.0, min(1.0, float(noise)))
    if compression is not None:
        args["compression"] = max(0.0, min(1.0, float(compression)))
    if recover_detail is not None:
        args["recover_detail"] = max(0.0, min(1.0, float(recover_detail)))
    if halo is not None:
        args["halo"] = max(0.0, min(1.0, float(halo)))
    return args


def estimate_video_denoise_cost(
    spec: ToolSpec,
    *,
    duration_s: float = 8.0,
    upscale_factor: float = 1.0,
) -> float:
    """Topaz pricing by output class — denoise often stays near source res (1×)."""
    dur = max(1.0, float(duration_s or 8.0))
    sc = float(upscale_factor or 1.0)
    # Same Topaz rate table as upscale; 1× ≈ ≤720p/source class → $0.01/s ballpark
    if sc >= 3.0:
        rate = 0.08
    elif sc >= 1.6:
        rate = 0.02
    else:
        rate = 0.01
    return max(0.05, rate * dur)


def format_video_denoise_cost(
    spec: ToolSpec,
    *,
    duration_s: float = 8.0,
    upscale_factor: float = 1.0,
) -> str:
    from media_studio.pricing import format_job_cost

    usd = estimate_video_denoise_cost(
        spec, duration_s=duration_s, upscale_factor=upscale_factor
    )
    dur = max(1, int(round(float(duration_s or 8.0))))
    sc = float(upscale_factor or 1.0)
    unit = f"{dur}s · {sc:g}× Topaz"
    return format_job_cost(usd, unit=unit, model=spec.label)


def build_video_interpolate_args(
    spec: ToolSpec,
    video_url: str,
    *,
    factor_label: str | None = None,
    num_frames: int | None = None,
    use_scene_detection: bool | None = None,
    use_calculated_fps: bool = True,
    fps: int | None = None,
) -> dict[str, Any]:
    """RIFE / FILM interpolate args."""
    args = dict(spec.extra_defaults)
    args["video_url"] = video_url
    n = int(num_frames) if num_frames is not None else parse_interpolate_factor(factor_label)
    args["num_frames"] = max(1, min(4, n))
    if use_scene_detection is not None:
        args["use_scene_detection"] = bool(use_scene_detection)
    args["use_calculated_fps"] = bool(use_calculated_fps)
    if not use_calculated_fps and fps is not None:
        args["fps"] = max(1, min(60, int(fps)))
    return args


def estimate_video_interpolate_cost(
    spec: ToolSpec,
    *,
    duration_s: float = 8.0,
    factor_label: str | None = None,
) -> float:
    """Rough interpolate cost (compute scales with output length)."""
    dur = max(1.0, float(duration_s or 8.0))
    n = parse_interpolate_factor(factor_label)
    mult = n + 1  # output length ≈ source * multiplier
    key = spec.key.lower()
    # RIFE advertised ~$0.0013 / compute-s — use duration * mult * rate
    if "film" in key:
        rate = 0.004  # heavier
    else:
        rate = 0.0015
    return max(0.03, rate * dur * mult * 8.0)  # fudge compute density


def format_video_interpolate_cost(
    spec: ToolSpec,
    *,
    duration_s: float = 8.0,
    factor_label: str | None = None,
) -> str:
    from media_studio.pricing import format_job_cost

    usd = estimate_video_interpolate_cost(
        spec, duration_s=duration_s, factor_label=factor_label
    )
    dur = max(1, int(round(float(duration_s or 8.0))))
    fac = (factor_label or "").strip() or "2×"
    # Short unit from factor label
    short = fac.split("(")[0].strip() or fac
    unit = f"{dur}s source · {short}"
    return format_job_cost(usd, unit=unit, model=spec.label)


def build_edit_args(
    spec: ToolSpec,
    image_url: str,
    prompt: str,
    *,
    strength: float | None = None,
    image_urls: list[str] | None = None,
) -> dict[str, Any]:
    args = dict(spec.extra_defaults)
    args["prompt"] = prompt
    urls = list(image_urls) if image_urls else [image_url]
    # Prefer image_urls list (nano banana / flux 2 / seedream / grok / mai) else image_url
    if any(
        k in spec.endpoint
        for k in (
            "flux-2",
            "nano-banana",
            "seedream",
            "grok-imagine-image",
            "mai-image",
        )
    ):
        args["image_urls"] = urls
    elif "codeformer" in spec.endpoint or "kontext" in spec.endpoint:
        args["image_url"] = urls[0]
    else:
        args["image_url"] = urls[0]
    # strength is applied via prompt wording for most edit tools, not API body
    _ = strength
    return args


def build_codeformer_args(
    image_url: str,
    *,
    fidelity: float = 0.7,
    upscale_factor: float = 1.0,
) -> dict[str, Any]:
    """fal-ai/codeformer: image_url + fidelity (0–1) + optional upscale."""
    fid = max(0.0, min(1.0, float(fidelity)))
    return {
        "image_url": image_url,
        "fidelity": fid,
        "upscale_factor": float(upscale_factor),
        "face_upscale": True,
    }


def build_nafnet_deblur_args(image_url: str, *, seed: int | None = None) -> dict[str, Any]:
    """fal-ai/nafnet/deblur: image_url (+ optional seed). No prompt / ref."""
    args: dict[str, Any] = {"image_url": image_url}
    if seed is not None:
        try:
            args["seed"] = int(seed)
        except (TypeError, ValueError):
            pass
    return args


SKY_PRESETS: dict[str, str] = {
    "Clear blue": (
        "Replace only the sky with a clear bright blue sky and soft white clouds. "
        "Keep the building, landscape, windows, and all non-sky elements identical. "
        "Match natural lighting on the structure; do not recolor walls or change architecture."
    ),
    "Dramatic clouds": (
        "Replace only the sky with a dramatic cloudy sky (deep blues and layered clouds). "
        "Preserve the exact building, trees, and ground. Do not alter architecture or materials."
    ),
    "Golden hour / sunset": (
        "Replace only the sky with a warm golden-hour sunset sky. Softly match ambient warmth "
        "on exterior surfaces without repainting walls. Keep all architecture identical."
    ),
    "Overcast soft": (
        "Replace only the sky with a soft overcast sky for even listing-friendly light. "
        "Do not change buildings, landscaping, or window reflections beyond subtle sky reflection."
    ),
    "Twilight": (
        "Replace only the sky with a blue-hour twilight sky. Preserve the property and landscape "
        "exactly; only the sky changes."
    ),
}


# Optional time-of-day chips for Sky (compose with preset / free text)
SKY_TIME_OF_DAY: list[str] = [
    "Match existing light",
    "Midday",
    "Golden hour",
    "Blue hour / twilight",
    "Overcast even light",
]


def sky_prompt(
    preset: str | None,
    custom: str | None,
    *,
    time_of_day: str | None = None,
) -> str:
    custom = (custom or "").strip()
    tod = (time_of_day or "").strip()
    tod_note = ""
    if tod and tod.lower() not in ("match existing light", "match existing", ""):
        tod_note = f" Time of day / lighting feel: {tod}."
    if custom:
        return (
            f"Replace only the sky: {custom}.{tod_note} "
            "Keep architecture, landscape, and all non-sky elements identical."
        )
    if preset and preset in SKY_PRESETS:
        base = SKY_PRESETS[preset]
        if tod_note:
            return f"{base.rstrip('.')}." + tod_note
        return base
    base = SKY_PRESETS["Clear blue"]
    if tod_note:
        return f"{base.rstrip('.')}." + tod_note
    return base


def cleanup_prompt(user_prompt: str | None, strength: float = 0.7) -> str:
    base = (user_prompt or "").strip()
    if not base:
        base = (
            "remove clutter and temporary objects, keep architecture "
            "and permanent fixtures"
        )
    strength_note = ""
    if strength < 0.4:
        strength_note = " Make only subtle, minimal removals."
    elif strength > 0.75:
        strength_note = " Be thorough but keep architecture, floors, and walls unchanged."
    return (
        f"{base.rstrip('.')}. "
        "Remove only the unwanted objects described. "
        "Preserve walls, floors, ceiling, windows, doors, trim, and camera framing exactly. "
        "Do not restage furniture unless asked."
        f"{strength_note}"
    )


def relight_prompt(user_prompt: str | None) -> str:
    base = (user_prompt or "").strip()
    if not base:
        base = (
            "Relight the scene with soft, even, listing-quality natural daylight through the windows"
        )
    return (
        f"{base.rstrip('.')}. "
        "Change lighting and soft shadows only. "
        "Do not move furniture, change wall color, flooring, architecture, or camera angle."
    )


DEHAZE_STRENGTH_LABELS: list[str] = [
    "Gentle",
    "Balanced",
    "Strong (default)",
    "Maximum clear air",
]


def dehaze_strength_from_label(label: str | None) -> float:
    raw = (label or "").strip().lower()
    if raw.startswith("gentle"):
        return 0.35
    if raw.startswith("balanced"):
        return 0.55
    if raw.startswith("maximum"):
        return 0.92
    return 0.82  # Strong default


def dehaze_prompt(user_prompt: str | None = None, strength: float = 0.75) -> str:
    """Strong default prompt for smoke / haze / smog removal (real estate exteriors)."""
    custom = (user_prompt or "").strip()
    if not custom:
        custom = (
            "Remove smoke, haze, smog, wildfire smoke, fog, and atmospheric murk from the scene. "
            "Restore clear air and natural color contrast"
        )
    strength_note = ""
    if strength < 0.45:
        strength_note = " Apply a gentle dehaze only; keep some atmospheric depth."
    elif strength > 0.8:
        strength_note = " Clear the air thoroughly while staying photorealistic."
    return (
        f"{custom.rstrip('.')}. "
        "Improve clarity and visibility through the atmosphere only. "
        "Do not change buildings, walls, roof, landscaping layout, windows, cars, or camera framing. "
        "Do not restage the property or invent new objects. "
        "Preserve true surface colors once haze is removed; avoid oversaturation."
        f"{strength_note}"
    )


# --- Phase 5 RE prompt defaults ---

VIDEO_CLEANUP_DEFAULT = (
    "Remove unwanted people, cars, bins, trash, and temporary clutter from this video. "
    "Preserve exact camera motion, architecture, landscaping layout, lighting, and all "
    "permanent property features. Do not restage or invent structures."
)

MIRROR_DEFAULT = (
    "Remove only the reflected person, cameraman, tripod, or equipment visible in the "
    "mirror, TV, window, or glass surface. Keep the mirror/glass frame, room geometry, "
    "wall color, fixtures, and lighting unchanged. Do not restage the room."
)

AMENITY_CHOICES: list[str] = [
    "Pool — clear water / gentle ripples",
    "Fireplace — lit, warm fire",
    "Interior lights on",
    "Landscape / path lights on",
    "Mixed amenities on",
]

AMENITY_DEFAULT = (
    "Activate the property amenity so it looks inviting and listing-ready. "
    "Only the amenity itself may change (water, flame, or lights). "
    "Preserve structure, materials, camera angle, furniture layout, and everything else."
)

MATCH_LOOK_DEFAULT = (
    "Match the overall look of the AI-edited result to the original source photograph: "
    "align white balance, contrast, exposure, saturation, and soft grade so the plate "
    "cuts in cleanly. Do not change geometry, furniture, architecture, or composition — "
    "color and tone only."
)

SEASON_CHOICES: list[str] = [
    "Spring",
    "Summer",
    "Fall / Autumn",
    "Winter",
    "Clear snow → green lawn",
    "Curb appeal boost (same season)",
]

SEASON_DEFAULT = (
    "Change season and landscape cues only (foliage, lawn, light snow, flower beds). "
    "Preserve the house, structure, windows, hardscape layout, driveways, and camera framing exactly."
)


def video_cleanup_prompt(user_prompt: str | None = None) -> str:
    base = (user_prompt or "").strip() or VIDEO_CLEANUP_DEFAULT
    return (
        f"{base.rstrip('.')}. "
        "Remove only the specified subjects. "
        "Preserve camera motion path, architecture, and permanent features."
    )


def mirror_prompt(user_prompt: str | None = None) -> str:
    base = (user_prompt or "").strip() or MIRROR_DEFAULT
    return (
        f"{base.rstrip('.')}. "
        "Edit reflections only; keep glass/mirror frame and room geometry locked."
    )


def amenity_prompt(amenity: str | None = None, user_prompt: str | None = None) -> str:
    custom = (user_prompt or "").strip()
    a = (amenity or AMENITY_CHOICES[0]).strip()
    if custom:
        core = custom
    elif "pool" in a.lower():
        core = (
            "Make the pool look active and inviting: clear clean water with gentle natural "
            "ripples and realistic reflections"
        )
    elif "fire" in a.lower():
        core = "Light the fireplace with a warm, realistic fire and soft glow on nearby surfaces"
    elif "interior" in a.lower():
        core = "Turn on warm interior lights so rooms feel lived-in and welcoming at dusk"
    elif "landscape" in a.lower() or "path" in a.lower():
        core = "Turn on landscape, path, and exterior accent lights for an evening listing look"
    else:
        core = AMENITY_DEFAULT
    return (
        f"{core.rstrip('.')}. "
        "Only the amenity state may change. "
        "Do not move walls, furniture, camera, or redesign the property."
    )


def match_look_prompt(user_prompt: str | None = None) -> str:
    base = (user_prompt or "").strip() or MATCH_LOOK_DEFAULT
    return (
        f"{base.rstrip('.')}. "
        "Tone and grade only — no geometry, layout, or content changes."
    )


def season_tool_prompt(season: str | None = None, user_prompt: str | None = None) -> str:
    custom = (user_prompt or "").strip()
    s = (season or SEASON_CHOICES[0]).strip()
    if custom:
        core = custom
    elif "snow" in s.lower() or "green" in s.lower():
        core = (
            "Clear residual snow and restore a healthy green lawn and tidy beds "
            "for curb-appeal listing photos"
        )
    elif "curb" in s.lower():
        core = (
            "Boost curb appeal: healthier lawn, neat foundation plantings, tidy beds, "
            "same season and architecture"
        )
    elif s.lower().startswith("winter"):
        core = "Convert the landscape to a clean winter look with light natural snow where appropriate"
    elif s.lower().startswith("fall"):
        core = "Convert the landscape to autumn: warm fall foliage, no structural change"
    elif s.lower().startswith("summer"):
        core = "Convert the landscape to full summer: lush green lawn and mature plantings"
    else:
        core = "Convert the landscape to spring: fresh green growth and light seasonal plantings"
    return (
        f"{core.rstrip('.')}. "
        "Change season and softscape only. "
        "Preserve house, structure, windows, hardscape layout, and camera framing."
    )


def video_sky_prompt(preset: str | None = None, user_prompt: str | None = None) -> str:
    custom = (user_prompt or "").strip()
    if custom:
        return (
            f"{custom.rstrip('.')}. "
            "Replace or enhance sky/weather only across the clip. "
            "Keep roofline, hard tree edges, building geometry, and camera motion stable."
        )
    p = (preset or "Clear blue").strip()
    return (
        f"Replace only the sky with a {p.lower()} look suitable for real-estate exteriors. "
        "Preserve architecture, roofline, trees, hardscape, and camera motion exactly. "
        "No restructuring of the property."
    )


def format_tool_cost(spec: ToolSpec) -> str:
    """Flat still-tool estimate (1 image / one job) — total, not a bare rate."""
    from media_studio.pricing import format_job_cost

    cat = (spec.category or "").lower()
    unit = "1 job"
    if cat in ("upscale", "cleanup", "sky", "dehaze", "relight", "restore", "blownout", "reaspect", "mirror", "amenity", "season", "match_look"):
        unit = "1 image"
    return format_job_cost(float(spec.cost_estimate_usd), unit=unit, model=spec.label)


BLOWN_OUT_INTENSITY_LABELS: list[str] = [
    "Gentle",
    "Balanced (default)",
    "Strong recovery",
]


def blown_out_strength_from_label(label: str | None) -> float:
    raw = (label or "").strip().lower()
    if raw.startswith("gentle"):
        return 0.4
    if raw.startswith("strong"):
        return 0.9
    return 0.75


def blown_out_prompt(
    user_prompt: str | None = None,
    *,
    strength: float = 0.75,
    windows_only: bool = True,
) -> str:
    custom = (user_prompt or "").strip()
    base = custom if custom else BLOWN_OUT_PROMPT_CORE
    if strength < 0.4:
        strength_note = " Apply a gentle exposure recovery only."
    elif strength > 0.8:
        strength_note = " Recover as much exterior detail as possible while staying photoreal."
    else:
        strength_note = ""
    scope = (
        " Only the overexposed window glass/exterior view may change; "
        "keep the full interior identical."
        if windows_only
        else " Prefer recovering blown highlights; minimize changes outside those regions."
    )
    if custom and custom.rstrip(".") == BLOWN_OUT_PROMPT_CORE.rstrip("."):
        return f"{BLOWN_OUT_PROMPT_CORE}{scope}{strength_note}"
    if custom:
        return f"{base.rstrip('.')}.{scope}{strength_note}"
    return f"{BLOWN_OUT_PROMPT_CORE}{scope}{strength_note}"


def reaspect_prompt(
    user_prompt: str | None = None,
    *,
    aspect_ratio: str = "9:16",
    mode: str = "image",
) -> str:
    custom = (user_prompt or "").strip()
    ar = parse_aspect_choice(aspect_ratio)
    mode_bit = (
        "video frames consistently across the clip"
        if mode == "video"
        else "the image"
    )
    if custom and "aspect" in custom.lower():
        return custom
    if custom:
        return (
            f"{custom.rstrip('.')}. Target aspect ratio {ar}. "
            f"Preserve subject and composition on {mode_bit}; "
            "extend edges coherently only as needed."
        )
    return (
        f"{REASPECT_PROMPT_CORE} "
        f"Target aspect ratio: {ar}."
    )


def restore_prompt(
    user_prompt: str | None = None,
    *,
    has_reference: bool = False,
    strength: float = 0.75,
    mode: str = "image",
) -> str:
    """
    Auto-built restore prompt. User text replaces or extends the core when provided.

    Soft source is always the primary subject; reference (if any) is identity-only.
    """
    custom = (user_prompt or "").strip()
    base = custom if custom else RESTORE_PROMPT_CORE

    # Strength wording for prompt-based models (CodeFormer uses API fidelity instead)
    if strength < 0.4:
        strength_note = " Apply a gentle restore only; keep natural softness where appropriate."
    elif strength > 0.8:
        strength_note = " Restore facial detail thoroughly while staying photorealistic."
    else:
        strength_note = ""

    ref_block = ""
    if has_reference:
        if mode == "video":
            ref_block = (
                " The soft source video is the clip to restore. "
                "Use the reference still only for the subject's exact face identity and features "
                "(@Image1 when available). Do not replace body pose, clothing, camera motion, "
                "or background from the reference."
            )
        else:
            ref_block = (
                " Image 1 is the soft/out-of-focus source to restore. "
                "Image 2 is a sharp reference of the same person — match that exact identity "
                "and facial features only. Do not copy pose, body, clothing, or background "
                "from the reference."
            )
    else:
        ref_block = (
            " Restore the existing subject's face and detail from the source only; "
            "do not invent a different person."
        )

    lock = (
        " Restore sharpness and facial detail only. "
        "Do not change pose, body proportions, clothing, styling, lighting geometry, "
        "or background layout."
    )
    if mode == "video":
        lock += " Preserve camera movement and temporal consistency across frames."

    # Avoid double-pasting the core if the user already left it as the field value
    if custom and custom.rstrip(".") == RESTORE_PROMPT_CORE.rstrip("."):
        return f"{RESTORE_PROMPT_CORE}{ref_block}{lock}{strength_note}"

    if custom:
        return f"{base.rstrip('.')}.{ref_block}{lock}{strength_note}"
    return f"{RESTORE_PROMPT_CORE}{ref_block}{lock}{strength_note}"
