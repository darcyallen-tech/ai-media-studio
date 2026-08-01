"""
Creative Vision model registry — text-to-video, image-to-video, bridge shots.

Cinematic invention only (not listing camera-lock staging). Costs are
intentionally conservative ballparks — show them before generate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

VisionMode = Literal["text_to_video", "image_to_video", "bridge"]


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
    # I2V start frame field
    image_field: str = "image_url"
    # I2V optional end frame (e.g. Hailuo) — hide UI when False
    supports_end_frame: bool = False
    extra_defaults: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Text → Video
# ---------------------------------------------------------------------------

T2V_MODELS: dict[str, VisionModelSpec] = {
    "veo 3.1": VisionModelSpec(
        key="veo 3.1",
        label="Veo 3.1",
        mode="text_to_video",
        endpoint="fal-ai/veo3.1",
        cost_estimate_usd=0.80,
        cost_per_second=0.10,
        notes="Highest quality T2V. Expensive. 4/6/8s · 16:9 or 9:16 · optional audio.",
        default_duration="8s",
        extra_defaults={"generate_audio": True, "auto_fix": True, "safety_tolerance": "4"},
    ),
    "veo 3.1 fast": VisionModelSpec(
        key="veo 3.1 fast",
        label="Veo 3.1 Fast",
        mode="text_to_video",
        endpoint="fal-ai/veo3.1/fast",
        cost_estimate_usd=0.40,
        cost_per_second=0.05,
        notes="Faster/cheaper Veo 3.1. Good default for exploration.",
        default_duration="6s",
        extra_defaults={"generate_audio": True, "auto_fix": True, "safety_tolerance": "4"},
    ),
    "veo 3.1 reference": VisionModelSpec(
        key="veo 3.1 reference",
        label="Veo 3.1 Reference pack",
        mode="text_to_video",
        endpoint="fal-ai/veo3.1/reference-to-video",
        cost_estimate_usd=0.85,
        cost_per_second=0.11,
        notes="T2V guided by 1–N reference stills (house / style / subject).",
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
        cost_estimate_usd=0.40,
        cost_per_second=0.05,
        notes="Faster still → move. Recommended default for I2V experiments.",
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
        cost_estimate_usd=0.80,
        cost_per_second=0.10,
        notes="Still → cinematic move. Expensive. Keep architecture in the prompt.",
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
        cost_estimate_usd=0.45,
        cost_per_second=0.055,
        notes="Faster bridge. Recommended default for connect shots.",
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
        cost_estimate_usd=0.85,
        cost_per_second=0.11,
        notes=(
            "Bridge two stills into a continuous move (e.g. upstairs → living room). "
            "Prompt: path, speed, keep architecture consistent."
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
        else [T2V_MODELS, I2V_MODELS, BRIDGE_MODELS]
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
    # Prefer Fast variants as practical defaults
    for key in (
        "veo 3.1 fast",
        "veo 3.1 fast i2v",
        "veo 3.1 fast bridge",
    ):
        if key in reg:
            return reg[key]
    return next(iter(reg.values()))


def duration_seconds(token: str | None) -> float:
    if not token:
        return 8.0
    t = str(token).strip().lower().replace("s", "")
    try:
        return float(t)
    except (TypeError, ValueError):
        return 8.0


def estimate_vision_cost(
    spec: VisionModelSpec,
    *,
    duration_token: str | None = None,
    resolution: str | None = None,
) -> float:
    """Conservative USD ballpark for UI (not billing)."""
    secs = duration_seconds(duration_token or spec.default_duration)
    base = spec.cost_estimate_usd
    if spec.cost_per_second is not None and secs > 0:
        base = max(0.05, round(secs * spec.cost_per_second, 3))
    res = (resolution or spec.default_resolution or "720p").lower()
    if "1080" in res or res == "1080p":
        base *= 1.35
    elif "4k" in res or "2160" in res:
        base *= 2.2
    elif "512" in res:
        base *= 0.75
    return round(base, 3)


def format_vision_cost(
    spec: VisionModelSpec,
    *,
    duration_token: str | None = None,
    resolution: str | None = None,
) -> str:
    amt = estimate_vision_cost(
        spec, duration_token=duration_token, resolution=resolution
    )
    secs = duration_seconds(duration_token or spec.default_duration)
    return f"Est. cost: ${amt:.2f} · ~{secs:.0f}s ({spec.label})"


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
        raise ValueError("Enter a motion / shot prompt.")
    args["prompt"] = text

    dur = (duration or spec.default_duration or "").strip()
    if dur and spec.duration_param:
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
