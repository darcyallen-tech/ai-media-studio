"""
fal.ai model registry — image edit, video-to-video edit, image-to-video.

UI labels are grouped for readability (Image · … / Video · …).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Sequence

TaskKind = Literal["image_edit", "video_edit", "image_to_video"]

# fal-ai/flux-pro/kontext (and similar Flux Kontext endpoints)
FLUX_KONTEXT_ASPECT_RATIOS: tuple[str, ...] = (
    "21:9",
    "16:9",
    "4:3",
    "3:2",
    "1:1",
    "2:3",
    "3:4",
    "9:16",
    "9:21",
)

# Values that must never be sent as aspect_ratio to strict enum APIs
_ASPECT_PLACEHOLDERS = frozenset(
    {
        "",
        "auto",
        "default",
        "none",
        "null",
        "—",
        "-",
        "n/a",
        "na",
        "auto (default)",
    }
)


# ---------------------------------------------------------------------------
# Aspect-ratio helpers (strict enum APIs e.g. Flux Kontext)
# ---------------------------------------------------------------------------


def _parse_ratio_token(token: str) -> float | None:
    """Parse '16:9' / '16/9' into float width/height; None if invalid."""
    t = (token or "").strip().lower().replace(" ", "")
    if not t:
        return None
    for sep in (":", "/", "x", "×"):
        if sep in t:
            a, _, b = t.partition(sep)
            try:
                w, h = float(a), float(b)
                if w > 0 and h > 0:
                    return w / h
            except (TypeError, ValueError):
                return None
    return None


def nearest_allowed_aspect_ratio(
    ratio: float,
    allowed: Sequence[str],
    *,
    fallback: str = "1:1",
) -> str:
    """Pick the allowed W:H whose numeric ratio is closest to ``ratio``."""
    if not allowed:
        return fallback
    scored: list[tuple[float, str]] = []
    for token in allowed:
        r = _parse_ratio_token(token)
        if r is None:
            continue
        scored.append((abs(r - ratio), token))
    if not scored:
        return fallback if fallback in allowed else str(allowed[0])
    scored.sort(key=lambda x: (x[0], x[1]))
    return scored[0][1]


def aspect_ratio_from_image(path: str | Path | None) -> float | None:
    """Return width/height of a local still, or None if unreadable."""
    if not path:
        return None
    try:
        p = Path(path)
        if not p.is_file():
            return None
        from PIL import Image

        with Image.open(p) as im:
            w, h = int(im.width), int(im.height)
        if w > 0 and h > 0:
            return w / h
    except Exception:
        return None
    return None


def aspect_hint_from_label(value: str | None) -> float | None:
    """
    Map UI resolution / aspect labels to a numeric ratio when possible.

    Examples: landscape_16_9 → 16/9, square_hd → 1.0, 4:3 → 4/3.
    """
    if value is None:
        return None
    raw = str(value).strip().lower().replace(" ", "").replace("-", "_")
    if not raw or raw in _ASPECT_PLACEHOLDERS:
        return None

    # Direct W:H / W/H (before alias table)
    direct = _parse_ratio_token(str(value).strip())
    if direct is not None:
        return direct

    aliases: dict[str, float] = {
        "square": 1.0,
        "square_hd": 1.0,
        "1_1": 1.0,
        "landscape_16_9": 16 / 9,
        "landscape16_9": 16 / 9,
        "16_9": 16 / 9,
        "portrait_16_9": 9 / 16,
        "portrait16_9": 9 / 16,
        "9_16": 9 / 16,
        "landscape_4_3": 4 / 3,
        "landscape4_3": 4 / 3,
        "4_3": 4 / 3,
        "portrait_4_3": 3 / 4,
        "portrait4_3": 3 / 4,
        "3_4": 3 / 4,
        "landscape_3_2": 3 / 2,
        "3_2": 3 / 2,
        "portrait_3_2": 2 / 3,
        "2_3": 2 / 3,
        "21_9": 21 / 9,
        "9_21": 9 / 21,
        "ultrawide": 21 / 9,
        "widescreen": 16 / 9,
        "portrait": 9 / 16,
        "landscape": 16 / 9,
    }
    if raw in aliases:
        return aliases[raw]
    # landscape_16_9 style already covered; try embedded W_H
    if "_" in raw:
        parts = raw.split("_")
        for i in range(len(parts) - 1):
            cand = f"{parts[i]}:{parts[i + 1]}"
            r = _parse_ratio_token(cand)
            if r is not None:
                return r
    return None


def resolve_enum_aspect_ratio(
    requested: str | None,
    *,
    allowed: Sequence[str],
    default: str = "1:1",
    source_image: str | Path | None = None,
    resolution_hint: str | None = None,
) -> tuple[str, str | None]:
    """
    Map UI / auto aspect into a strict API enum literal.

    Never returns placeholders like ``default`` or ``auto``.
    Preference order: exact allowed match → parse requested → resolution hint →
    source image → default (1:1 if allowed).
    """
    allowed_list = tuple(allowed) if allowed else FLUX_KONTEXT_ASPECT_RATIOS
    allowed_map = {a.lower(): a for a in allowed_list}
    fallback = default if default in allowed_list else (
        "1:1" if "1:1" in allowed_list else allowed_list[0]
    )

    raw = (str(requested).strip() if requested is not None else "") or ""
    raw_l = raw.lower()

    # Exact allowed literal
    if raw_l in allowed_map:
        return allowed_map[raw_l], None

    note: str | None = None
    ratio: float | None = None

    if raw and raw_l not in _ASPECT_PLACEHOLDERS:
        ratio = _parse_ratio_token(raw) or aspect_hint_from_label(raw)
        if ratio is not None:
            chosen = nearest_allowed_aspect_ratio(ratio, allowed_list, fallback=fallback)
            if chosen != raw:
                note = f"aspect_ratio {raw!r} → {chosen}."
            return chosen, note

    # Derive from resolution / image_size UI value
    ratio = aspect_hint_from_label(resolution_hint)
    if ratio is not None:
        chosen = nearest_allowed_aspect_ratio(ratio, allowed_list, fallback=fallback)
        note = f"aspect_ratio auto from resolution {resolution_hint!r} → {chosen}."
        return chosen, note

    # Derive from source still
    ratio = aspect_ratio_from_image(source_image)
    if ratio is not None:
        chosen = nearest_allowed_aspect_ratio(ratio, allowed_list, fallback=fallback)
        note = f"aspect_ratio auto from source still → {chosen}."
        return chosen, note

    # Last resort: never send "default"/"auto"
    if raw_l in _ASPECT_PLACEHOLDERS or not raw:
        note = f"aspect_ratio {raw or 'auto'!r} → {fallback} (safe default)."
    else:
        note = f"aspect_ratio {raw!r} unsupported; using {fallback}."
    return fallback, note


# ---------------------------------------------------------------------------
# Image edit models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ImageEditModelSpec:
    key: str
    label: str
    endpoint: str
    image_field: str = "image_urls"
    multi_image: bool = True
    # Max input stills (primary + optional refs). 1 = single-ref UI/path.
    max_ref_images: int = 1
    num_images_param: str = "num_images"
    max_num_images: int = 4
    aspect_ratio_param: str | None = "aspect_ratio"
    # When non-empty, aspect_ratio is a strict enum (never send auto/default)
    allowed_aspect_ratios: tuple[str, ...] = ()
    resolution_param: str | None = "resolution"
    # Some Flux models use image_size instead of resolution
    image_size_param: str | None = None
    allowed_resolutions: tuple[str, ...] = ("1K", "2K", "4K")
    max_resolution: str = "2K"
    default_resolution: str = "1K"
    default_aspect_ratio: str = "auto"
    output_format_param: str | None = "output_format"
    default_output_format: str = "png"
    cost_per_image: float | None = None  # base 1K estimate
    # resolution multipliers: 1K=1, 2K=1.5, 4K=2 (nano banana style)
    resolution_cost_mult: dict[str, float] = field(default_factory=dict)
    extra_defaults: dict[str, Any] = field(default_factory=dict)
    notes: str = ""

    def clamp_num_images(self, n: int | None) -> int:
        if n is None or n < 1:
            return 1
        return min(int(n), self.max_num_images)

    def clamp_ref_images(self, n: int | None) -> int:
        """How many input stills this model accepts (primary + optional refs)."""
        if not self.multi_image or self.image_field == "image_url":
            return 1
        cap = int(self.max_ref_images or 1)
        if cap < 1:
            return 1
        if n is None or n < 1:
            return 1
        return min(int(n), cap)

    def clamp_resolution(self, value: str | None) -> str | None:
        if not self.resolution_param and not self.image_size_param:
            return None
        if not value:
            return self.default_resolution
        original = str(value).strip()
        # Preserve exact casing for model-specific enums (e.g. Seedream auto_2K, square_hd)
        allowed_map = {a.lower(): a for a in self.allowed_resolutions}
        if original.lower() in allowed_map:
            res = allowed_map[original.lower()]
        else:
            raw = original.upper().replace(" ", "")
            aliases = {
                "0.5K": "0.5K",
                "512": "0.5K",
                "1K": "1K",
                "1024": "1K",
                "2K": "2K",
                "2048": "2K",
                "4K": "4K",
                "4096": "4K",
                "1080P": "1K",
                "720P": "1K",
                "AUTO": "auto",
                "AUTO_2K": "auto_2K",
                "AUTO_4K": "auto_4K",
                "SQUARE_HD": "square_hd",
                "SQUARE": "square",
                "PORTRAIT_4_3": "portrait_4_3",
                "PORTRAIT_16_9": "portrait_16_9",
                "LANDSCAPE_4_3": "landscape_4_3",
                "LANDSCAPE_16_9": "landscape_16_9",
            }
            mapped = aliases.get(raw)
            if mapped and mapped.lower() in allowed_map:
                res = allowed_map[mapped.lower()]
            elif mapped and mapped in self.allowed_resolutions:
                res = mapped
            else:
                res = self.default_resolution
        if res not in self.allowed_resolutions and res != "auto":
            # case-insensitive membership already handled; final fallback
            if res.lower() in allowed_map:
                res = allowed_map[res.lower()]
            else:
                res = self.default_resolution
        # Max resolution only applies to classic 1K/2K/4K ladders
        order = [r for r in self.allowed_resolutions if r in ("0.5K", "1K", "2K", "4K")]
        if self.max_resolution in order and res in order:
            if order.index(res) > order.index(self.max_resolution):
                res = self.max_resolution
        return res

    def estimate_cost(self, num_images: int = 1, resolution: str | None = None) -> float | None:
        """
        Total job estimate: per-image rate × selected count × resolution mult.

        Uses the **requested** batch count (not ``max_num_images``). Models that
        only accept 1 output per API call still sequential-batch in the app, so
        4 images must estimate as 4 × rate, not 1 × rate.
        """
        if self.cost_per_image is None:
            return None
        try:
            n = max(1, int(num_images or 1))
        except (TypeError, ValueError):
            n = 1
        mult = 1.0
        res = (resolution or self.default_resolution or "1K").upper()
        if self.resolution_cost_mult:
            mult = self.resolution_cost_mult.get(res, 1.0)
        return self.cost_per_image * n * mult


# ---------------------------------------------------------------------------
# Video models (v2v edit + i2v)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VideoModelSpec:
    key: str
    label: str
    endpoint: str
    task: TaskKind  # video_edit | image_to_video
    video_field: str = "video_url"
    image_field: str | None = "image_urls"  # v2v refs or i2v uses image_url
    i2v_image_field: str = "image_url"  # start frame for i2v
    multi_image: bool = True
    max_ref_images: int = 4
    # Omni / reference-to-video: optional motion + audio plates (MiniMax H3)
    max_ref_videos: int = 0
    max_ref_audios: int = 0
    max_total_refs: int = 0  # 0 = no combined cap; H3 uses 12
    # Field names for multi-ref endpoints (None → Seedance-style image_urls / video_urls)
    ref_image_field: str | None = None  # e.g. reference_image_urls
    ref_video_field: str | None = None  # e.g. reference_video_urls
    ref_audio_field: str | None = None  # e.g. reference_audio_urls
    # Prompt citation style for auto-inject: "at" → @Image1; "plain" → Image 1
    prompt_citation_style: str = "at"
    supports_end_frame: bool = False  # I2V optional last frame (end_image_url)
    # Native stereo always on output (no generate_audio toggle) — MiniMax H3
    native_stereo_audio: bool = False
    keep_audio_param: str | None = "keep_audio"
    default_keep_audio: bool = True
    generate_audio_param: str | None = None
    default_generate_audio: bool = False
    aspect_ratio_param: str | None = None
    default_aspect_ratio: str | None = None
    # When non-empty, aspect_ratio is a strict enum (never send auto/default)
    allowed_aspect_ratios: tuple[str, ...] = ()
    duration_param: str | None = None
    default_duration: str | None = "5"
    allowed_durations: tuple[str, ...] = (
        "3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13", "14", "15",
    )
    max_duration_seconds: float = 15.0
    min_duration_seconds: float = 3.0
    # Some APIs want integer duration (e.g. Grok Imagine); others want string enums.
    duration_as_int: bool = False
    # Optional output resolution (Grok edit-video / I2V, etc.)
    resolution_param: str | None = None
    allowed_resolutions: tuple[str, ...] = ()
    default_resolution: str | None = None
    cost_per_second: float | None = None
    cost_per_second_audio_on: float | None = None
    # e.g. {"480p": 0.06, "720p": 0.08}; keys lowercased at lookup
    cost_per_second_by_resolution: dict[str, float] = field(default_factory=dict)
    # Fixed add-on (e.g. $0.01 input image for Grok I2V)
    cost_fixed: float | None = None
    auto_image_refs_in_prompt: bool = True
    extra_defaults: dict[str, Any] = field(default_factory=dict)
    notes: str = ""

    def nearest_duration(self, value: Any) -> str:
        """
        Clamp to allowed durations for UI / cost estimates.

        Works even when the API has no duration param (V2V edit follows source
        length — we still surface a matched duration for cost + user feedback).
        """
        fallback = self.default_duration or str(int(self.min_duration_seconds) or 5)
        if value is None or value == "":
            return str(fallback)
        raw = str(value).strip().lower().replace("s", "").replace("seconds", "").strip()
        # Seedance (and similar) accept literal "auto"
        if raw == "auto" and (
            "auto" in self.allowed_durations
            or any(str(a).lower() == "auto" for a in self.allowed_durations)
        ):
            return "auto"
        try:
            n = int(round(float(raw)))
        except (TypeError, ValueError):
            return str(fallback)
        n = max(int(self.min_duration_seconds), min(n, int(self.max_duration_seconds)))
        s = str(n)
        allowed = tuple(self.allowed_durations) or tuple(
            str(i)
            for i in range(int(self.min_duration_seconds), int(self.max_duration_seconds) + 1)
        )
        if s not in allowed:
            nums = sorted(int(x) for x in allowed)
            closest = min(nums, key=lambda a: abs(a - n))
            s = str(closest)
        return s

    def clamp_duration(self, value: Any) -> str | None:
        """API duration value, or None if this model does not accept a duration param."""
        if not self.duration_param:
            return None
        return self.nearest_duration(value)

    def clamp_resolution(self, value: str | None) -> str | None:
        """Normalize video resolution against allowed list, or None if unused."""
        if not self.resolution_param:
            return None
        allowed = tuple(self.allowed_resolutions) if self.allowed_resolutions else ()
        fallback = self.default_resolution or (allowed[0] if allowed else None)
        if not value or not str(value).strip():
            return fallback
        raw = str(value).strip()
        if raw.lower().startswith("matches"):
            return fallback
        if not allowed:
            return raw
        amap = {a.lower(): a for a in allowed}
        if raw.lower() in amap:
            return amap[raw.lower()]
        return fallback

    def estimate_cost(
        self,
        duration_seconds: float | None = None,
        *,
        generate_audio: bool = False,
        resolution: str | None = None,
    ) -> float | None:
        rate = self.cost_per_second
        if generate_audio and self.cost_per_second_audio_on is not None:
            rate = self.cost_per_second_audio_on
        if self.cost_per_second_by_resolution:
            res = (resolution or self.default_resolution or "").strip().lower()
            if not res or res in ("auto", "default") or res.startswith("matches"):
                # Prefer default_resolution; if still auto, pick 720p then first key
                res = (self.default_resolution or "").strip().lower()
                if not res or res in ("auto", "default"):
                    res = (
                        "720p"
                        if "720p" in self.cost_per_second_by_resolution
                        else next(iter(self.cost_per_second_by_resolution), "")
                    )
            rate = self.cost_per_second_by_resolution.get(res, rate)
        if rate is None and self.cost_fixed is None:
            return None
        secs = duration_seconds
        if secs is None or secs <= 0:
            try:
                secs = float(self.default_duration or 5)
            except (TypeError, ValueError):
                secs = 5.0
        total = (rate or 0.0) * float(secs)
        if self.cost_fixed is not None:
            total += float(self.cost_fixed)
        return total


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

IMAGE_EDIT_MODELS: dict[str, ImageEditModelSpec] = {
    # Primary Studio image-edit options (real-estate friendly)
    "flux 2 pro": ImageEditModelSpec(
        key="flux 2 pro",
        label="Image · Flux 2 Pro (edit)",
        endpoint="fal-ai/flux-2-pro/edit",
        image_field="image_urls",
        multi_image=True,
        max_ref_images=4,
        max_num_images=1,
        resolution_param=None,
        image_size_param="image_size",
        default_resolution="auto",
        allowed_resolutions=("auto",),
        aspect_ratio_param=None,
        default_output_format="jpeg",
        cost_per_image=0.03,
        notes="Default. FLUX.2 Pro multi-ref edit (~$0.03 first MP). Strong for staging.",
    ),
    "flux 2 max": ImageEditModelSpec(
        key="flux 2 max",
        label="Image · Flux 2 Max (edit)",
        endpoint="fal-ai/flux-2-max/edit",
        image_field="image_urls",
        multi_image=True,
        max_ref_images=4,
        max_num_images=1,
        resolution_param=None,
        image_size_param="image_size",
        default_resolution="auto",
        allowed_resolutions=("auto",),
        aspect_ratio_param=None,
        default_output_format="jpeg",
        cost_per_image=0.07,
        notes=(
            "FLUX.2 Max edit — highest quality Flux edit. "
            "Est. $0.07 first processed MP, +$0.03 each additional MP (input counted)."
        ),
    ),
    "mai image 2.5 pro": ImageEditModelSpec(
        key="mai image 2.5 pro",
        label="Image · MAI-Image-2.5-Pro (edit)",
        endpoint="microsoft/mai-image-2.5-pro/edit",
        image_field="image_urls",
        multi_image=True,
        max_ref_images=1,
        max_num_images=1,
        resolution_param=None,
        image_size_param=None,
        default_resolution="auto",
        allowed_resolutions=("auto",),
        aspect_ratio_param=None,
        default_output_format="jpeg",
        cost_per_image=0.22,
        notes=(
            "Microsoft MAI-Image-2.5-Pro edit on fal. "
            "Est. ~$0.18–$0.27/image (token-billed: text + image in/out)."
        ),
    ),
    "mai image 2.5": ImageEditModelSpec(
        key="mai image 2.5",
        label="Image · MAI-Image-2.5 (edit)",
        endpoint="microsoft/mai-image-2.5/edit",
        image_field="image_urls",
        multi_image=True,
        max_ref_images=1,
        max_num_images=1,
        resolution_param=None,
        image_size_param=None,
        default_resolution="auto",
        allowed_resolutions=("auto",),
        aspect_ratio_param=None,
        default_output_format="jpeg",
        cost_per_image=0.06,
        notes=(
            "Microsoft MAI-Image-2.5 edit — lighter/faster than Pro. "
            "Est. ~$0.05–$0.08/image (token-billed)."
        ),
    ),
    "nano banana pro": ImageEditModelSpec(
        key="nano banana pro",
        label="Image · Nano Banana Pro (edit)",
        endpoint="fal-ai/nano-banana-pro/edit",
        multi_image=True,
        max_ref_images=4,
        max_num_images=4,
        max_resolution="2K",
        allowed_resolutions=("1K", "2K", "4K"),
        cost_per_image=0.15,
        resolution_cost_mult={"1K": 1.0, "2K": 1.0, "4K": 2.0},
        notes="Google Gemini image edit on fal — excellent prompt adherence. Up to 4 refs.",
    ),
    "nano banana 2": ImageEditModelSpec(
        key="nano banana 2",
        label="Image · Nano Banana 2 (edit)",
        endpoint="fal-ai/nano-banana-2/edit",
        multi_image=True,
        max_ref_images=4,
        max_num_images=4,
        max_resolution="2K",
        allowed_resolutions=("0.5K", "1K", "2K", "4K"),
        default_resolution="1K",
        cost_per_image=0.08,
        resolution_cost_mult={"0.5K": 0.75, "1K": 1.0, "2K": 1.5, "4K": 2.0},
        notes="Faster Nano Banana 2 edit — good cost/quality balance. Up to 4 refs.",
    ),
    "seedream 5 pro": ImageEditModelSpec(
        key="seedream 5 pro",
        label="Image · Seedream 5 Pro (edit)",
        # Seedream 5.0 Pro on fal — region-precise / annotation-box friendly
        endpoint="bytedance/seedream/v5/pro/edit",
        image_field="image_urls",
        multi_image=True,
        max_ref_images=10,
        max_num_images=10,
        resolution_param=None,
        image_size_param="image_size",
        default_resolution="auto_2K",
        allowed_resolutions=("auto_2K", "auto_4K", "square_hd", "landscape_16_9", "portrait_16_9"),
        aspect_ratio_param=None,
        output_format_param=None,  # Seedream schema has no output_format
        cost_per_image=0.0675,
        notes=(
            "ByteDance Seedream 5.0 Pro edit — grounded region-precise edits "
            "(colored-box / annotation workflows). Multi-ref up to 10. "
            "Est. ~$0.0675/image @≤1536."
        ),
        extra_defaults={"num_images": 1, "enable_safety_checker": True},
    ),
    # Extra practical options (still curated)
    "flux 2 flex": ImageEditModelSpec(
        key="flux 2 flex",
        label="Image · Flux 2 Flex (edit)",
        endpoint="fal-ai/flux-2-flex/edit",
        image_field="image_urls",
        multi_image=True,
        max_ref_images=4,
        max_num_images=1,
        resolution_param=None,
        image_size_param="image_size",
        default_resolution="auto",
        allowed_resolutions=("auto",),
        aspect_ratio_param=None,
        default_output_format="jpeg",
        cost_per_image=0.04,
        notes="FLUX.2 Flex multi-ref edit — flexible style control.",
    ),
    "flux kontext pro": ImageEditModelSpec(
        key="flux kontext pro",
        label="Image · Flux Kontext Pro",
        endpoint="fal-ai/flux-pro/kontext",
        image_field="image_url",
        multi_image=False,
        max_ref_images=1,
        max_num_images=1,
        resolution_param=None,
        aspect_ratio_param="aspect_ratio",
        allowed_aspect_ratios=FLUX_KONTEXT_ASPECT_RATIOS,
        # UI may show "auto"; build_edit_arguments maps to nearest enum (never "default")
        default_aspect_ratio="auto",
        cost_per_image=0.04,
        notes="FLUX Kontext Pro single-image edit. aspect_ratio is a strict enum.",
    ),
    # Grok Imagine (xAI on fal) — comparison testing
    "grok imagine edit": ImageEditModelSpec(
        key="grok imagine edit",
        label="Image · Grok Imagine Edit",
        endpoint="xai/grok-imagine-image/edit",
        image_field="image_urls",
        multi_image=True,
        max_ref_images=3,
        max_num_images=3,
        aspect_ratio_param="aspect_ratio",
        allowed_aspect_ratios=(
            "auto",
            "2:1",
            "20:9",
            "19.5:9",
            "16:9",
            "4:3",
            "3:2",
            "1:1",
            "2:3",
            "3:4",
            "9:16",
            "9:19.5",
            "9:20",
            "1:2",
        ),
        default_aspect_ratio="auto",
        resolution_param="resolution",
        allowed_resolutions=("1k", "2k"),
        default_resolution="1k",
        max_resolution="2k",
        default_output_format="jpeg",
        cost_per_image=0.022,
        resolution_cost_mult={"1K": 1.0, "2K": 1.0},
        notes=(
            "xAI Grok Imagine image edit (~$0.022/image: $0.02 out + $0.002 in). "
            "Up to 3 source images. Strength is optional if the API accepts it."
        ),
    ),
    "grok imagine quality edit": ImageEditModelSpec(
        key="grok imagine quality edit",
        label="Image · Grok Imagine Quality Edit",
        endpoint="xai/grok-imagine-image/quality/edit",
        image_field="image_urls",
        multi_image=True,
        max_ref_images=3,
        max_num_images=3,
        aspect_ratio_param="aspect_ratio",
        allowed_aspect_ratios=(
            "auto",
            "2:1",
            "20:9",
            "19.5:9",
            "16:9",
            "4:3",
            "3:2",
            "1:1",
            "2:3",
            "3:4",
            "9:16",
            "9:19.5",
            "9:20",
            "1:2",
        ),
        default_aspect_ratio="auto",
        resolution_param="resolution",
        allowed_resolutions=("1k", "2k"),
        default_resolution="1k",
        max_resolution="2k",
        default_output_format="jpeg",
        # ~$0.05 out + $0.01 in @1k; ~$0.07 out + $0.01 in @2k (one input image)
        cost_per_image=0.06,
        resolution_cost_mult={"1K": 1.0, "2K": 1.333},
        notes=(
            "xAI Grok Imagine Quality / Pro edit — stronger detail & text. "
            "Est. ~$0.06/image @1k, ~$0.08 @2k (includes one input). Up to 3 refs."
        ),
    ),
    # Kept for history / aliases only (not in primary dropdown)
    "nano banana": ImageEditModelSpec(
        key="nano banana",
        label="Image · Nano Banana (edit)",
        endpoint="fal-ai/nano-banana/edit",
        multi_image=True,
        max_ref_images=4,
        max_num_images=4,
        max_resolution="1K",
        allowed_resolutions=("1K",),
        cost_per_image=0.039,
        notes="Original Nano Banana edit (legacy). Up to 4 refs.",
    ),
}

VIDEO_MODELS: dict[str, VideoModelSpec] = {
    # --- Video-to-video edit (camera-lock / motion-preserving) ---
    "kling o3 standard edit": VideoModelSpec(
        key="kling o3 standard edit",
        label="Video · Kling O3 Standard – V2V Edit",
        endpoint="fal-ai/kling-video/o3/standard/video-to-video/edit",
        task="video_edit",
        keep_audio_param="keep_audio",
        default_keep_audio=True,
        # API follows source clip length (3–15s); no duration field on request.
        duration_param=None,
        min_duration_seconds=3.0,
        max_duration_seconds=15.0,
        allowed_durations=tuple(str(i) for i in range(3, 16)),
        cost_per_second=0.126,
        notes="Default. Kling O3 Standard V2V edit — motion-preserving; length matches source (3–15s).",
    ),
    "kling o3 pro edit": VideoModelSpec(
        key="kling o3 pro edit",
        label="Video · Kling O3 Pro – V2V Edit",
        endpoint="fal-ai/kling-video/o3/pro/video-to-video/edit",
        task="video_edit",
        keep_audio_param="keep_audio",
        default_keep_audio=True,
        duration_param=None,
        min_duration_seconds=3.0,
        max_duration_seconds=15.0,
        allowed_durations=tuple(str(i) for i in range(3, 16)),
        cost_per_second=0.168,
        notes="Kling O3 Pro V2V edit — higher quality; length matches source (3–15s).",
    ),
    "kling o1 standard edit": VideoModelSpec(
        key="kling o1 standard edit",
        label="Video · Kling O1 Standard – V2V Edit",
        endpoint="fal-ai/kling-video/o1/standard/video-to-video/edit",
        task="video_edit",
        keep_audio_param="keep_audio",
        default_keep_audio=True,
        duration_param=None,
        min_duration_seconds=3.0,
        max_duration_seconds=10.0,
        allowed_durations=tuple(str(i) for i in range(3, 11)),
        cost_per_second=0.126,
        notes="Kling O1 Standard V2V — natural-language edit, motion structure preserved.",
    ),
    "kling o1 pro edit": VideoModelSpec(
        key="kling o1 pro edit",
        label="Video · Kling O1 Pro – V2V Edit",
        endpoint="fal-ai/kling-video/o1/video-to-video/edit",
        task="video_edit",
        keep_audio_param="keep_audio",
        default_keep_audio=True,
        duration_param=None,
        min_duration_seconds=3.0,
        max_duration_seconds=10.0,
        allowed_durations=tuple(str(i) for i in range(3, 11)),
        cost_per_second=0.168,
        notes="Kling O1 Pro V2V — stronger semantic edits; motion-preserving.",
    ),
    "ltx retake": VideoModelSpec(
        key="ltx retake",
        label="Video · LTX 2.3 Retake",
        endpoint="fal-ai/ltx-2.3/retake-video",
        task="video_edit",
        keep_audio_param=None,
        image_field=None,  # retake is prompt + video segment, not multi-ref
        multi_image=False,
        duration_param="duration",
        default_duration="5",
        min_duration_seconds=2.0,
        max_duration_seconds=16.0,
        allowed_durations=tuple(str(i) for i in range(2, 17)),
        cost_per_second=0.10,
        auto_image_refs_in_prompt=False,
        extra_defaults={
            "start_time": 0.0,
            "retake_mode": "replace_audio_and_video",
        },
        notes=(
            "LTX 2.3 Retake — regenerate a 2–16s segment while locking surrounding motion. "
            "Best for local reshoots, not multi-image ref swaps."
        ),
    ),
    # Grok Imagine video (xAI on fal) — comparison testing
    "grok imagine edit video": VideoModelSpec(
        key="grok imagine edit video",
        label="Video · Grok Imagine Edit Video",
        endpoint="xai/grok-imagine-video/edit-video",
        task="video_edit",
        video_field="video_url",
        image_field=None,  # API is prompt + video only (no multi-ref stills)
        multi_image=False,
        keep_audio_param=None,
        duration_param=None,  # follows source, truncated to 8s by API
        min_duration_seconds=1.0,
        max_duration_seconds=8.0,
        allowed_durations=tuple(str(i) for i in range(1, 9)),
        default_duration="5",
        resolution_param="resolution",
        allowed_resolutions=("auto", "480p", "720p"),
        default_resolution="auto",
        # $0.05 out + $0.01 in @480p; $0.07 out + $0.01 in @720p (per second)
        cost_per_second=0.08,
        cost_per_second_by_resolution={"480p": 0.06, "720p": 0.08, "auto": 0.08},
        auto_image_refs_in_prompt=False,
        notes=(
            "xAI Grok Imagine video edit (prompt + source clip). "
            "API truncates to ~8s and resizes to max 854×480 area before edit. "
            "Optional resolution auto/480p/720p. Ref stills are not sent to the API."
        ),
    ),
    "grok imagine 1.5 i2v": VideoModelSpec(
        key="grok imagine 1.5 i2v",
        label="Video · Grok Imagine 1.5 – Image-to-Video",
        endpoint="xai/grok-imagine-video/v1.5/image-to-video",
        task="image_to_video",
        image_field=None,
        i2v_image_field="image_url",
        keep_audio_param=None,
        generate_audio_param=None,  # audio included when generated by model
        duration_param="duration",
        duration_as_int=True,
        default_duration="6",
        min_duration_seconds=1.0,
        max_duration_seconds=15.0,
        allowed_durations=tuple(str(i) for i in range(1, 16)),
        resolution_param="resolution",
        allowed_resolutions=("480p", "720p", "1080p"),
        default_resolution="720p",
        cost_per_second=0.14,
        cost_per_second_by_resolution={
            "480p": 0.08,
            "720p": 0.14,
            "1080p": 0.14,  # fal documents 480p/720p; 1080p uses 720p estimate
        },
        cost_fixed=0.01,  # per input image
        notes=(
            "xAI Grok Imagine 1.5 I2V — animate a staged still (optional comparison model). "
            "Est. $0.08/s @480p, $0.14/s @720p + $0.01 input image. Default 6s / 720p."
        ),
    ),
    # Legacy aliases kept for Enhance / old history
    "kling edit": VideoModelSpec(
        key="kling edit",
        label="Video · Kling O3 Standard – V2V Edit",
        endpoint="fal-ai/kling-video/o3/standard/video-to-video/edit",
        task="video_edit",
        keep_audio_param="keep_audio",
        default_keep_audio=True,
        min_duration_seconds=3.0,
        max_duration_seconds=15.0,
        allowed_durations=tuple(str(i) for i in range(3, 16)),
        cost_per_second=0.126,
        notes="Alias → Kling O3 Standard V2V edit.",
    ),
    # --- Image-to-video ---
    "kling o3 standard i2v": VideoModelSpec(
        key="kling o3 standard i2v",
        label="Video · Kling O3 Standard – Image-to-Video",
        endpoint="fal-ai/kling-video/o3/standard/image-to-video",
        task="image_to_video",
        image_field=None,
        keep_audio_param=None,
        generate_audio_param="generate_audio",
        duration_param="duration",
        default_duration="5",
        max_duration_seconds=15.0,
        cost_per_second=0.084,
        cost_per_second_audio_on=0.112,
        notes="Kling O3 Standard I2V. Needs a start-frame still.",
    ),
    "kling o3 pro i2v": VideoModelSpec(
        key="kling o3 pro i2v",
        label="Video · Kling O3 Pro – Image-to-Video",
        endpoint="fal-ai/kling-video/o3/pro/image-to-video",
        task="image_to_video",
        image_field=None,
        keep_audio_param=None,
        generate_audio_param="generate_audio",
        duration_param="duration",
        default_duration="5",
        max_duration_seconds=15.0,
        cost_per_second=0.14,
        cost_per_second_audio_on=0.14,
        notes="Kling O3 Pro I2V.",
    ),
    "kling v3 standard i2v": VideoModelSpec(
        key="kling v3 standard i2v",
        label="Video · Kling v3 / 3.0 Standard (I2V)",
        endpoint="fal-ai/kling-video/v3/standard/image-to-video",
        task="image_to_video",
        image_field=None,
        keep_audio_param=None,
        generate_audio_param="generate_audio",
        duration_param="duration",
        default_duration="5",
        max_duration_seconds=15.0,
        cost_per_second=0.112,
        notes="Kling 3.0 Standard image-to-video.",
    ),
    "kling v3 pro i2v": VideoModelSpec(
        key="kling v3 pro i2v",
        label="Video · Kling v3 / 3.0 Pro (I2V)",
        endpoint="fal-ai/kling-video/v3/pro/image-to-video",
        task="image_to_video",
        image_field=None,
        keep_audio_param=None,
        generate_audio_param="generate_audio",
        duration_param="duration",
        default_duration="5",
        max_duration_seconds=15.0,
        cost_per_second=0.14,
        notes="Kling 3.0 Pro image-to-video.",
    ),
    "kling 2.6 pro i2v": VideoModelSpec(
        key="kling 2.6 pro i2v",
        label="Video · Kling 2.6 Pro (I2V)",
        endpoint="fal-ai/kling-video/v2.6/pro/image-to-video",
        task="image_to_video",
        image_field=None,
        keep_audio_param=None,
        generate_audio_param="generate_audio",
        duration_param="duration",
        default_duration="5",
        max_duration_seconds=10.0,
        allowed_durations=("5", "10"),
        cost_per_second=0.07,
        notes="Kling 2.6 Pro image-to-video (native audio).",
    ),
    "kling 2.5 turbo pro i2v": VideoModelSpec(
        key="kling 2.5 turbo pro i2v",
        label="Video · Kling 2.5 Turbo Pro (I2V)",
        endpoint="fal-ai/kling-video/v2.5-turbo/pro/image-to-video",
        task="image_to_video",
        image_field=None,
        keep_audio_param=None,
        generate_audio_param=None,
        duration_param="duration",
        default_duration="5",
        max_duration_seconds=10.0,
        allowed_durations=("5", "10"),
        cost_per_second=0.07,
        notes="Kling 2.5 Turbo Pro — fast cinematic I2V.",
    ),
    # --- Seedance 2.0 (ByteDance on fal) — furniture motion / high-res I2V ---
    "seedance 2.0 i2v": VideoModelSpec(
        key="seedance 2.0 i2v",
        label="Video · Seedance 2.0 – Image-to-Video",
        endpoint="bytedance/seedance-2.0/image-to-video",
        task="image_to_video",
        image_field=None,
        i2v_image_field="image_url",
        keep_audio_param=None,
        generate_audio_param="generate_audio",
        default_generate_audio=True,
        duration_param="duration",
        duration_as_int=False,
        default_duration="5",
        min_duration_seconds=4.0,
        max_duration_seconds=15.0,
        allowed_durations=("auto",) + tuple(str(i) for i in range(4, 16)),
        resolution_param="resolution",
        allowed_resolutions=("480p", "720p", "1080p", "4k"),
        default_resolution="720p",
        aspect_ratio_param="aspect_ratio",
        allowed_aspect_ratios=("auto", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"),
        default_aspect_ratio="auto",
        # Est. from fal docs (~$3.02 / 10s @720p → ~$0.30/s); scale by resolution
        cost_per_second=0.30,
        cost_per_second_by_resolution={
            "480p": 0.18,
            "720p": 0.30,
            "1080p": 0.45,
            "4k": 0.90,
        },
        notes=(
            "ByteDance Seedance 2.0 I2V — strong furniture/product motion, up to 4K. "
            "Optional end frame via end_image_url. Duration 4–15s or auto. "
            "Est. ~$0.30/s @720p, higher at 1080p/4K."
        ),
    ),
    "seedance 2.0 fast i2v": VideoModelSpec(
        key="seedance 2.0 fast i2v",
        label="Video · Seedance 2.0 Fast – Image-to-Video",
        endpoint="bytedance/seedance-2.0/fast/image-to-video",
        task="image_to_video",
        image_field=None,
        i2v_image_field="image_url",
        keep_audio_param=None,
        generate_audio_param="generate_audio",
        default_generate_audio=True,
        duration_param="duration",
        duration_as_int=False,
        default_duration="5",
        min_duration_seconds=4.0,
        max_duration_seconds=15.0,
        allowed_durations=("auto",) + tuple(str(i) for i in range(4, 16)),
        resolution_param="resolution",
        allowed_resolutions=("480p", "720p"),
        default_resolution="720p",
        aspect_ratio_param="aspect_ratio",
        allowed_aspect_ratios=("auto", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"),
        default_aspect_ratio="auto",
        cost_per_second=0.15,
        cost_per_second_by_resolution={"480p": 0.10, "720p": 0.15},
        notes=(
            "Seedance 2.0 Fast I2V — cheaper/faster tests (up to 720p). "
            "Optional end frame. Est. ~$0.15/s @720p."
        ),
    ),
    "seedance 2.0 reference": VideoModelSpec(
        key="seedance 2.0 reference",
        label="Video · Seedance 2.0 – Reference-to-Video",
        endpoint="bytedance/seedance-2.0/reference-to-video",
        task="image_to_video",  # still-driven; optional video refs via parameters
        image_field="image_urls",
        multi_image=True,
        max_ref_images=9,
        i2v_image_field="image_urls",  # build_i2v special-cases list field
        keep_audio_param=None,
        generate_audio_param="generate_audio",
        default_generate_audio=True,
        duration_param="duration",
        duration_as_int=False,
        default_duration="5",
        min_duration_seconds=4.0,
        max_duration_seconds=15.0,
        allowed_durations=("auto",) + tuple(str(i) for i in range(4, 16)),
        resolution_param="resolution",
        allowed_resolutions=("480p", "720p", "1080p", "4k"),
        default_resolution="720p",
        aspect_ratio_param="aspect_ratio",
        allowed_aspect_ratios=("auto", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"),
        default_aspect_ratio="auto",
        auto_image_refs_in_prompt=True,
        cost_per_second=0.18,
        cost_per_second_by_resolution={
            "480p": 0.12,
            "720p": 0.18,
            "1080p": 0.28,
            "4k": 0.55,
        },
        notes=(
            "Seedance 2.0 Reference-to-Video — multi-ref from still(s) (+ optional video). "
            "Prompt: @Image1 / @Video1. Up to 4K on standard. Est. ~$0.18/s @720p."
        ),
    ),
    # Motion-preserving edits via reference-to-video (source clip as @Video1)
    "seedance 2.0 v2v": VideoModelSpec(
        key="seedance 2.0 v2v",
        label="Video · Seedance 2.0 – V2V / Ref Edit",
        endpoint="bytedance/seedance-2.0/reference-to-video",
        task="video_edit",
        video_field="video_urls",  # special-cased in build_video_edit_arguments
        image_field="image_urls",
        multi_image=True,
        max_ref_images=4,
        keep_audio_param=None,
        generate_audio_param="generate_audio",
        default_generate_audio=True,
        duration_param="duration",
        duration_as_int=False,
        default_duration="5",
        min_duration_seconds=4.0,
        max_duration_seconds=15.0,
        allowed_durations=("auto",) + tuple(str(i) for i in range(4, 16)),
        resolution_param="resolution",
        allowed_resolutions=("480p", "720p", "1080p", "4k"),
        default_resolution="720p",
        aspect_ratio_param="aspect_ratio",
        allowed_aspect_ratios=("auto", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"),
        default_aspect_ratio="auto",
        auto_image_refs_in_prompt=True,
        cost_per_second=0.30,
        cost_per_second_by_resolution={
            "480p": 0.18,
            "720p": 0.30,
            "1080p": 0.45,
            "4k": 0.90,
        },
        notes=(
            "Seedance 2.0 motion-preserving edit via reference-to-video: source clip as "
            "@Video1 + optional ref still as @Image1. Up to 4K. "
            "Strong alternative to Kling for furniture/product V2V. Est. ~$0.30/s @720p."
        ),
    ),
    "seedance 2.0 fast v2v": VideoModelSpec(
        key="seedance 2.0 fast v2v",
        label="Video · Seedance 2.0 Fast – V2V / Ref Edit",
        endpoint="bytedance/seedance-2.0/fast/reference-to-video",
        task="video_edit",
        video_field="video_urls",
        image_field="image_urls",
        multi_image=True,
        max_ref_images=4,
        keep_audio_param=None,
        generate_audio_param="generate_audio",
        default_generate_audio=True,
        duration_param="duration",
        duration_as_int=False,
        default_duration="5",
        min_duration_seconds=4.0,
        max_duration_seconds=15.0,
        allowed_durations=("auto",) + tuple(str(i) for i in range(4, 16)),
        resolution_param="resolution",
        allowed_resolutions=("480p", "720p"),
        default_resolution="720p",
        aspect_ratio_param="aspect_ratio",
        allowed_aspect_ratios=("auto", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"),
        default_aspect_ratio="auto",
        auto_image_refs_in_prompt=True,
        cost_per_second=0.15,
        cost_per_second_by_resolution={"480p": 0.10, "720p": 0.15},
        notes=(
            "Seedance 2.0 Fast V2V / ref edit — cheaper tests (up to 720p). "
            "Source clip @Video1 + optional still @Image1. Est. ~$0.15/s @720p."
        ),
    ),
    # --- MiniMax H3 (Hailuo-03) — multimodal T2V/I2V/omni reference ---
    "minimax h3 i2v": VideoModelSpec(
        key="minimax h3 i2v",
        label="Video · MiniMax H3 – Image-to-Video",
        endpoint="minimax/h3/image-to-video",
        task="image_to_video",
        image_field=None,
        i2v_image_field="image_url",
        multi_image=False,
        max_ref_images=1,
        keep_audio_param=None,
        generate_audio_param=None,
        native_stereo_audio=True,
        supports_end_frame=True,
        duration_param="duration",
        duration_as_int=True,
        default_duration="5",
        min_duration_seconds=5.0,
        max_duration_seconds=15.0,
        allowed_durations=tuple(str(i) for i in range(5, 16)),
        resolution_param="resolution",
        allowed_resolutions=("2K",),
        default_resolution="2K",
        aspect_ratio_param=None,  # aspect follows start frame
        cost_per_second=0.26,
        notes=(
            "MiniMax H3 (Hailuo-03) I2V — first frame still; optional end_image_url "
            "for first→last (day→night / porch→interior). Duration 5–15s · 2K. "
            "Native stereo audio on output. Est. ~$0.26/s @2K (+ ref surcharges per fal)."
        ),
    ),
    "minimax h3 reference": VideoModelSpec(
        key="minimax h3 reference",
        label="Video · MiniMax H3 – Omni Reference",
        endpoint="minimax/h3/reference-to-video",
        task="image_to_video",
        image_field="reference_image_urls",
        i2v_image_field="reference_image_urls",
        multi_image=True,
        max_ref_images=9,
        max_ref_videos=3,
        max_ref_audios=3,
        max_total_refs=12,
        ref_image_field="reference_image_urls",
        ref_video_field="reference_video_urls",
        ref_audio_field="reference_audio_urls",
        prompt_citation_style="plain",
        keep_audio_param=None,
        generate_audio_param=None,
        native_stereo_audio=True,
        duration_param="duration",
        duration_as_int=True,
        default_duration="5",
        min_duration_seconds=5.0,
        max_duration_seconds=15.0,
        allowed_durations=tuple(str(i) for i in range(5, 16)),
        resolution_param="resolution",
        allowed_resolutions=("2K",),
        default_resolution="2K",
        aspect_ratio_param="aspect_ratio",
        allowed_aspect_ratios=(
            "adaptive", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16",
        ),
        default_aspect_ratio="adaptive",
        auto_image_refs_in_prompt=True,
        cost_per_second=0.26,
        notes=(
            "MiniMax H3 omni reference-to-video — up to 9 images + 3 videos + 3 audio "
            "(≤12 files). Cite as Image 1 / Video 1 / Audio 1 in the prompt. "
            "Motion transfer + subject lock. Native stereo. 2K · 5–15s. "
            "Est. ~$0.26/s @2K (+ ref image/video surcharges per fal)."
        ),
    ),
}

# Back-compat name used by older code
VIDEO_EDIT_MODELS = {
    k: v for k, v in VIDEO_MODELS.items() if v.task == "video_edit"
}

# Aliases → registry key
_ALIASES: dict[str, str] = {
    # image
    "nano banana pro": "nano banana pro",
    "nano banana pro (edit)": "nano banana pro",
    "image · nano banana pro (edit)": "nano banana pro",
    "fal-ai/nano-banana-pro/edit": "nano banana pro",
    "nano banana 2": "nano banana 2",
    "nano banana 2 (edit)": "nano banana 2",
    "image · nano banana 2 (edit)": "nano banana 2",
    "fal-ai/nano-banana-2/edit": "nano banana 2",
    "nano banana": "nano banana",
    "image · nano banana (edit)": "nano banana",
    "flux 2 pro": "flux 2 pro",
    "flux 2 pro (edit)": "flux 2 pro",
    "image · flux 2 pro (edit)": "flux 2 pro",
    "fal-ai/flux-2-pro/edit": "flux 2 pro",
    "flux 2 max": "flux 2 max",
    "flux 2 max (edit)": "flux 2 max",
    "image · flux 2 max (edit)": "flux 2 max",
    "fal-ai/flux-2-max/edit": "flux 2 max",
    "mai image 2.5 pro": "mai image 2.5 pro",
    "mai-image-2.5-pro": "mai image 2.5 pro",
    "mai-image-2.5-pro edit": "mai image 2.5 pro",
    "image · mai-image-2.5-pro (edit)": "mai image 2.5 pro",
    "microsoft/mai-image-2.5-pro/edit": "mai image 2.5 pro",
    "mai image 2.5": "mai image 2.5",
    "mai-image-2.5": "mai image 2.5",
    "image · mai-image-2.5 (edit)": "mai image 2.5",
    "microsoft/mai-image-2.5/edit": "mai image 2.5",
    "flux 2 flex": "flux 2 flex",
    "flux 2 flex (edit)": "flux 2 flex",
    "image · flux 2 flex (edit)": "flux 2 flex",
    "fal-ai/flux-2-flex/edit": "flux 2 flex",
    "flux kontext": "flux kontext pro",
    "flux kontext pro": "flux kontext pro",
    "image · flux kontext pro": "flux kontext pro",
    "fal-ai/flux-pro/kontext": "flux kontext pro",
    "seedream": "seedream 5 pro",
    "seedream 5": "seedream 5 pro",
    "seedream 5.0": "seedream 5 pro",
    "seedream 5 pro": "seedream 5 pro",
    "seedream 5 pro (edit)": "seedream 5 pro",
    "seedream 5.0 pro": "seedream 5 pro",
    "seedream 4.5": "seedream 5 pro",
    "image · seedream 5 pro (edit)": "seedream 5 pro",
    "fal-ai/bytedance/seedream/v4.5/edit": "seedream 5 pro",
    "fal-ai/bytedance/seedream/v5/pro/edit": "seedream 5 pro",
    "bytedance/seedream/v5/pro/edit": "seedream 5 pro",
    "bytedance/seedream/v4.5/edit": "seedream 5 pro",
    # video
    "kling edit": "kling o3 standard edit",
    "kling o3 standard edit": "kling o3 standard edit",
    "kling o3 standard – v2v edit": "kling o3 standard edit",
    "kling o3 standard - v2v edit": "kling o3 standard edit",
    "video · kling o3 standard – v2v edit": "kling o3 standard edit",
    "video · kling o3 standard - v2v edit": "kling o3 standard edit",
    "fal-ai/kling-video/o3/standard/video-to-video/edit": "kling o3 standard edit",
    "kling o3 pro edit": "kling o3 pro edit",
    "kling o3 pro – v2v edit": "kling o3 pro edit",
    "video · kling o3 pro – v2v edit": "kling o3 pro edit",
    "fal-ai/kling-video/o3/pro/video-to-video/edit": "kling o3 pro edit",
    "kling o1": "kling o1 standard edit",
    "kling o1 edit": "kling o1 standard edit",
    "kling o1 standard edit": "kling o1 standard edit",
    "kling o1 standard – v2v edit": "kling o1 standard edit",
    "video · kling o1 standard – v2v edit": "kling o1 standard edit",
    "fal-ai/kling-video/o1/standard/video-to-video/edit": "kling o1 standard edit",
    "kling o1 pro": "kling o1 pro edit",
    "kling o1 pro edit": "kling o1 pro edit",
    "kling o1 pro – v2v edit": "kling o1 pro edit",
    "video · kling o1 pro – v2v edit": "kling o1 pro edit",
    "fal-ai/kling-video/o1/video-to-video/edit": "kling o1 pro edit",
    "ltx": "ltx retake",
    "ltx retake": "ltx retake",
    "ltx 2.3 retake": "ltx retake",
    "video · ltx 2.3 retake": "ltx retake",
    "fal-ai/ltx-2.3/retake-video": "ltx retake",
    # grok imagine
    "grok imagine": "grok imagine edit",
    "grok imagine edit": "grok imagine edit",
    "grok imagine (edit)": "grok imagine edit",
    "image · grok imagine edit": "grok imagine edit",
    "xai/grok-imagine-image/edit": "grok imagine edit",
    "grok imagine quality": "grok imagine quality edit",
    "grok imagine quality edit": "grok imagine quality edit",
    "grok imagine pro edit": "grok imagine quality edit",
    "image · grok imagine quality edit": "grok imagine quality edit",
    "xai/grok-imagine-image/quality/edit": "grok imagine quality edit",
    "grok imagine edit video": "grok imagine edit video",
    "grok imagine video edit": "grok imagine edit video",
    "grok edit video": "grok imagine edit video",
    "video · grok imagine edit video": "grok imagine edit video",
    "xai/grok-imagine-video/edit-video": "grok imagine edit video",
    "grok imagine 1.5 i2v": "grok imagine 1.5 i2v",
    "grok imagine 1.5": "grok imagine 1.5 i2v",
    "grok imagine 1.5 image-to-video": "grok imagine 1.5 i2v",
    "grok imagine 1.5 – image-to-video": "grok imagine 1.5 i2v",
    "video · grok imagine 1.5 – image-to-video": "grok imagine 1.5 i2v",
    "xai/grok-imagine-video/v1.5/image-to-video": "grok imagine 1.5 i2v",
    "kling o3 standard i2v": "kling o3 standard i2v",
    "kling o3 standard – image-to-video": "kling o3 standard i2v",
    "video · kling o3 standard – image-to-video": "kling o3 standard i2v",
    "fal-ai/kling-video/o3/standard/image-to-video": "kling o3 standard i2v",
    "kling o3 pro i2v": "kling o3 pro i2v",
    "kling o3 pro – image-to-video": "kling o3 pro i2v",
    "video · kling o3 pro – image-to-video": "kling o3 pro i2v",
    "fal-ai/kling-video/o3/pro/image-to-video": "kling o3 pro i2v",
    "kling v3 standard": "kling v3 standard i2v",
    "kling v3 / 3.0 standard": "kling v3 standard i2v",
    "kling v3 standard i2v": "kling v3 standard i2v",
    "video · kling v3 / 3.0 standard (i2v)": "kling v3 standard i2v",
    "fal-ai/kling-video/v3/standard/image-to-video": "kling v3 standard i2v",
    "kling v3 pro": "kling v3 pro i2v",
    "kling v3 / 3.0 pro": "kling v3 pro i2v",
    "kling v3 pro i2v": "kling v3 pro i2v",
    "video · kling v3 / 3.0 pro (i2v)": "kling v3 pro i2v",
    "fal-ai/kling-video/v3/pro/image-to-video": "kling v3 pro i2v",
    "kling 2.6 pro": "kling 2.6 pro i2v",
    "kling 2.6 pro i2v": "kling 2.6 pro i2v",
    "video · kling 2.6 pro (i2v)": "kling 2.6 pro i2v",
    "fal-ai/kling-video/v2.6/pro/image-to-video": "kling 2.6 pro i2v",
    "kling 2.5 turbo pro": "kling 2.5 turbo pro i2v",
    "kling 2.5 turbo pro i2v": "kling 2.5 turbo pro i2v",
    "video · kling 2.5 turbo pro (i2v)": "kling 2.5 turbo pro i2v",
    "fal-ai/kling-video/v2.5-turbo/pro/image-to-video": "kling 2.5 turbo pro i2v",
    "kling reference": "kling o3 standard edit",
    # Seedance 2.0
    "seedance 2.0": "seedance 2.0 i2v",
    "seedance 2.0 i2v": "seedance 2.0 i2v",
    "seedance 2.0 image-to-video": "seedance 2.0 i2v",
    "video · seedance 2.0 – image-to-video": "seedance 2.0 i2v",
    "bytedance/seedance-2.0/image-to-video": "seedance 2.0 i2v",
    "seedance 2.0 fast": "seedance 2.0 fast i2v",
    "seedance 2.0 fast i2v": "seedance 2.0 fast i2v",
    "video · seedance 2.0 fast – image-to-video": "seedance 2.0 fast i2v",
    "bytedance/seedance-2.0/fast/image-to-video": "seedance 2.0 fast i2v",
    "seedance 2.0 reference": "seedance 2.0 reference",
    "seedance 2.0 reference-to-video": "seedance 2.0 reference",
    "video · seedance 2.0 – reference-to-video": "seedance 2.0 reference",
    "bytedance/seedance-2.0/reference-to-video": "seedance 2.0 reference",
    "seedance 2.0 v2v": "seedance 2.0 v2v",
    "seedance 2.0 edit": "seedance 2.0 v2v",
    "video · seedance 2.0 – v2v / ref edit": "seedance 2.0 v2v",
    "seedance 2.0 fast v2v": "seedance 2.0 fast v2v",
    "video · seedance 2.0 fast – v2v / ref edit": "seedance 2.0 fast v2v",
    "bytedance/seedance-2.0/fast/reference-to-video": "seedance 2.0 fast v2v",
    # MiniMax H3 (Hailuo-03)
    "minimax h3": "minimax h3 i2v",
    "minimax h3 i2v": "minimax h3 i2v",
    "minimax h3 image-to-video": "minimax h3 i2v",
    "hailuo 03 i2v": "minimax h3 i2v",
    "hailuo-03 i2v": "minimax h3 i2v",
    "video · minimax h3 – image-to-video": "minimax h3 i2v",
    "minimax/h3/image-to-video": "minimax h3 i2v",
    "fal-ai/minimax/hailuo-03/image-to-video": "minimax h3 i2v",
    "minimax h3 reference": "minimax h3 reference",
    "minimax h3 omni": "minimax h3 reference",
    "minimax h3 omni reference": "minimax h3 reference",
    "hailuo 03 reference": "minimax h3 reference",
    "video · minimax h3 – omni reference": "minimax h3 reference",
    "minimax/h3/reference-to-video": "minimax h3 reference",
    "fal-ai/minimax/hailuo-03/reference-to-video": "minimax h3 reference",
}


def model_dropdown_choices() -> list[str]:
    """Ordered, grouped labels for the UI dropdown (curated — not the full fal catalog)."""
    labels = ["Auto (default)"]
    # Image group — practical staging defaults first (Flux 2 Pro remains default)
    for key in (
        "flux 2 pro",
        "flux 2 max",
        "mai image 2.5 pro",
        "mai image 2.5",
        "nano banana pro",
        "nano banana 2",
        "seedream 5 pro",
        "flux 2 flex",
        "flux kontext pro",
        "grok imagine edit",
        "grok imagine quality edit",
    ):
        if key in IMAGE_EDIT_MODELS:
            labels.append(IMAGE_EDIT_MODELS[key].label)
    # Video V2V edit (camera-lock workflow)
    for key in (
        "kling o3 standard edit",
        "kling o3 pro edit",
        "kling o1 standard edit",
        "kling o1 pro edit",
        "seedance 2.0 v2v",
        "seedance 2.0 fast v2v",
        "ltx retake",
        "grok imagine edit video",
    ):
        if key in VIDEO_MODELS:
            labels.append(VIDEO_MODELS[key].label)
    # Image-to-video (when starting from a still)
    for key in (
        "kling o3 standard i2v",
        "kling o3 pro i2v",
        "kling v3 standard i2v",
        "kling v3 pro i2v",
        "kling 2.6 pro i2v",
        "kling 2.5 turbo pro i2v",
        "grok imagine 1.5 i2v",
        "seedance 2.0 i2v",
        "seedance 2.0 fast i2v",
        "seedance 2.0 reference",
        "minimax h3 i2v",
        "minimax h3 reference",
    ):
        if key in VIDEO_MODELS:
            labels.append(VIDEO_MODELS[key].label)
    return labels


def _normalize_choice(choice: str | None) -> str:
    if not choice:
        return ""
    raw = choice.strip()
    # strip group prefix for matching
    lower = raw.lower()
    if lower.startswith("image · "):
        lower = lower[len("image · ") :]
    if lower.startswith("video · "):
        lower = lower[len("video · ") :]
    return lower


def resolve_image_edit_model(choice: str | None) -> ImageEditModelSpec | None:
    if not choice:
        return None
    raw = choice.strip()
    if not raw or raw.lower() in ("auto", "auto (default)", "default"):
        return None
    lower = raw.lower()
    if lower in IMAGE_EDIT_MODELS:
        return IMAGE_EDIT_MODELS[lower]
    if lower in _ALIASES and _ALIASES[lower] in IMAGE_EDIT_MODELS:
        return IMAGE_EDIT_MODELS[_ALIASES[lower]]
    norm = _normalize_choice(raw)
    if norm in IMAGE_EDIT_MODELS:
        return IMAGE_EDIT_MODELS[norm]
    if norm in _ALIASES and _ALIASES[norm] in IMAGE_EDIT_MODELS:
        return IMAGE_EDIT_MODELS[_ALIASES[norm]]
    for spec in IMAGE_EDIT_MODELS.values():
        if spec.label.lower() == lower or spec.endpoint.lower() == lower:
            return spec
        # Exact match on label without "Image · " prefix (avoid substring collisions)
        if norm and norm == _normalize_choice(spec.label):
            return spec
    return None


def max_ref_images_for_choice(choice: str | None) -> int:
    """
    How many input stills (primary + optional refs) the selected image model accepts.

    Auto / unknown → 1 (safe single-ref). Region / single-image models stay at 1.
    Single source of truth for Studio + Vision multi-ref caps.
    """
    spec = resolve_image_edit_model(choice)
    if spec is None:
        return 1
    return spec.clamp_ref_images(spec.max_ref_images or 1)


def max_extra_ref_images_for_choice(choice: str | None) -> int:
    """
    Max *extra* reference stills (excluding primary).

    Vision I2I UI/service should use this — not a parallel max_refs table.
    """
    return max(0, max_ref_images_for_choice(choice) - 1)


def resolve_video_model(choice: str | None) -> VideoModelSpec | None:
    if not choice:
        return None
    raw = choice.strip()
    if not raw or raw.lower() in ("auto", "auto (default)", "default"):
        return None
    lower = raw.lower()
    if lower in VIDEO_MODELS:
        return VIDEO_MODELS[lower]
    if lower in _ALIASES and _ALIASES[lower] in VIDEO_MODELS:
        return VIDEO_MODELS[_ALIASES[lower]]
    norm = _normalize_choice(raw)
    if norm in VIDEO_MODELS:
        return VIDEO_MODELS[norm]
    if norm in _ALIASES and _ALIASES[norm] in VIDEO_MODELS:
        return VIDEO_MODELS[_ALIASES[norm]]
    for key, spec in VIDEO_MODELS.items():
        if spec.label.lower() == lower or spec.endpoint.lower() == lower:
            return spec
        # Exact match only — "grok imagine edit" must not match "grok imagine edit video"
        if norm and (norm == key or norm == _normalize_choice(spec.label)):
            return spec
    return None


# Back-compat
def resolve_video_edit_model(choice: str | None) -> VideoModelSpec | None:
    spec = resolve_video_model(choice)
    if spec and spec.task == "video_edit":
        return spec
    # Old callers expecting any video model for "kling edit"
    if spec and spec.task == "image_to_video":
        return None
    return None


def default_image_edit_model() -> ImageEditModelSpec:
    """Auto + image-edit default: Flux 2 Pro (edit)."""
    return IMAGE_EDIT_MODELS["flux 2 pro"]


def default_video_edit_model() -> VideoModelSpec:
    """Auto + V2V default: Kling O3 Standard edit."""
    return VIDEO_MODELS["kling o3 standard edit"]


def default_i2v_model() -> VideoModelSpec:
    return VIDEO_MODELS["kling o3 standard i2v"]


def resolve_job_kind(
    model_choice: str | None,
    *,
    has_image: bool,
    has_video: bool,
) -> str:
    """
    Return: image | video | image_to_video
    """
    # Prefer modality from UI label prefix when present (avoids cross-group collisions)
    raw = (model_choice or "").strip().lower()
    if raw.startswith("image ·"):
        if resolve_image_edit_model(model_choice):
            return "image"
    if raw.startswith("video ·"):
        vspec = resolve_video_model(model_choice)
        if vspec:
            return "image_to_video" if vspec.task == "image_to_video" else "video"

    vspec = resolve_video_model(model_choice)
    if vspec:
        return "image_to_video" if vspec.task == "image_to_video" else "video"
    if resolve_image_edit_model(model_choice):
        return "image"
    # Auto
    if has_video:
        return "video"
    return "image"


def _apply_aspect_ratio_arg(
    args: dict[str, Any],
    notes: list[str],
    *,
    param_name: str | None,
    requested: Any,
    allowed: Sequence[str],
    default: str | None,
    source_image: str | Path | None = None,
    resolution_hint: str | None = None,
) -> None:
    """Set aspect_ratio on args with enum-safe mapping when allowed is non-empty."""
    if not param_name:
        return
    raw = str(requested).strip() if requested is not None and requested != "" else ""
    if allowed:
        ar, note = resolve_enum_aspect_ratio(
            raw or None,
            allowed=allowed,
            default=default if default and default.lower() not in _ASPECT_PLACEHOLDERS else "1:1",
            source_image=source_image,
            resolution_hint=resolution_hint,
        )
        args[param_name] = ar
        if note:
            notes.append(note)
        return
    # Freeform / optional: never send placeholder "default"/"auto"
    if not raw or raw.lower() in _ASPECT_PLACEHOLDERS:
        return
    args[param_name] = raw


def build_edit_arguments(
    spec: ImageEditModelSpec,
    *,
    prompt: str,
    image_urls: list[str],
    parameters: dict[str, Any] | None = None,
    source_image_path: str | Path | None = None,
) -> tuple[dict[str, Any], list[str]]:
    params = dict(parameters or {})
    notes: list[str] = []
    other = params.get("other") if isinstance(params.get("other"), dict) else {}

    num_raw = params.get("num_images")
    if num_raw is None and other:
        num_raw = other.get("num_images")
    try:
        num = int(num_raw) if num_raw is not None else 1
    except (TypeError, ValueError):
        num = 1
        notes.append(f"Invalid num_images={num_raw!r}; using 1.")
    clamped = spec.clamp_num_images(num)
    if clamped != num:
        notes.append(f"num_images clamped {num} → {clamped} (max {spec.max_num_images}).")
    num = clamped

    args: dict[str, Any] = {"prompt": prompt, **spec.extra_defaults}

    if not image_urls:
        raise ValueError("image_urls is required for image editing.")
    max_refs = spec.clamp_ref_images(len(image_urls))
    if len(image_urls) > max_refs:
        notes.append(
            f"Reference images truncated to {max_refs} "
            f"(model max_ref_images={spec.max_ref_images})."
        )
    urls = list(image_urls[:max_refs])
    if spec.image_field == "image_url":
        args["image_url"] = urls[0]
        if len(image_urls) > 1:
            notes.append("Model accepts a single image; using the first upload only.")
    elif spec.multi_image:
        args[spec.image_field] = urls
    else:
        args[spec.image_field] = [urls[0]]
        if len(image_urls) > 1:
            notes.append("Model accepts a single image; using the first upload only.")

    if spec.num_images_param and spec.max_num_images > 1:
        args[spec.num_images_param] = num

    if spec.aspect_ratio_param:
        ar_req = params.get("aspect_ratio")
        if ar_req is None:
            ar_req = other.get("aspect_ratio")
        if ar_req is None:
            ar_req = spec.default_aspect_ratio
        res_hint = (
            params.get("resolution")
            or params.get("image_size")
            or other.get("resolution")
            or other.get("image_size")
        )
        _apply_aspect_ratio_arg(
            args,
            notes,
            param_name=spec.aspect_ratio_param,
            requested=ar_req,
            allowed=spec.allowed_aspect_ratios,
            default=spec.default_aspect_ratio,
            source_image=source_image_path,
            resolution_hint=str(res_hint) if res_hint is not None else None,
        )

    if spec.resolution_param:
        res_in = params.get("resolution") or other.get("resolution")
        res = spec.clamp_resolution(str(res_in) if res_in else None)
        if (
            res_in
            and res
            and str(res_in).strip().lower() != str(res).strip().lower()
        ):
            notes.append(f"resolution normalized/clamped {res_in!r} → {res}.")
        if res:
            args[spec.resolution_param] = res

    if spec.image_size_param:
        size = params.get("image_size") or other.get("image_size") or params.get("resolution") or "auto"
        args[spec.image_size_param] = str(size) if size else "auto"

    if spec.output_format_param:
        fmt = (
            params.get("output_format")
            or other.get("output_format")
            or spec.default_output_format
        )
        if fmt:
            args[spec.output_format_param] = str(fmt).lower()

    seed = params.get("seed")
    if seed is None and other:
        seed = other.get("seed")
    if seed is not None and seed != "":
        try:
            args["seed"] = int(seed)
        except (TypeError, ValueError):
            notes.append(f"Ignoring non-integer seed={seed!r}.")

    strength = params.get("strength")
    if strength is None and other:
        strength = other.get("strength")
    if strength is not None and strength != "":
        try:
            args["strength"] = float(strength)
        except (TypeError, ValueError):
            notes.append(f"Ignoring non-numeric strength={strength!r}.")

    return args, notes


def build_video_edit_arguments(
    spec: VideoModelSpec,
    *,
    prompt: str,
    video_url: str,
    image_urls: list[str] | None = None,
    parameters: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    if spec.task != "video_edit":
        raise ValueError(f"Model {spec.key} is not a video_edit model.")
    params = dict(parameters or {})
    notes: list[str] = []
    other = params.get("other") if isinstance(params.get("other"), dict) else {}
    image_urls = list(image_urls or [])

    prompt_out = (prompt or "").strip()
    if not prompt_out:
        raise ValueError("prompt is required for video editing.")
    if not video_url:
        raise ValueError("video_url is required for video editing.")

    # LTX Retake: segment rewrite — different payload than Kling V2V
    if "ltx" in spec.endpoint and "retake" in spec.endpoint:
        dur_in = params.get("duration_seconds") or params.get("duration")
        if dur_in is None:
            dur_in = other.get("duration_seconds", other.get("duration"))
        dur = spec.clamp_duration(dur_in) or spec.default_duration or "5"
        start = params.get("start_time")
        if start is None:
            start = other.get("start_time", spec.extra_defaults.get("start_time", 0.0))
        try:
            start_f = float(start)
        except (TypeError, ValueError):
            start_f = 0.0
        args: dict[str, Any] = {
            "video_url": video_url,
            "prompt": prompt_out,
            "start_time": max(0.0, start_f),
            "duration": float(dur),
            "retake_mode": str(
                other.get("retake_mode")
                or spec.extra_defaults.get("retake_mode")
                or "replace_audio_and_video"
            ),
        }
        if image_urls:
            notes.append("LTX Retake ignores reference stills (prompt + video segment only).")
        return args, notes

    if image_urls and spec.auto_image_refs_in_prompt:
        missing_tags = []
        for i in range(1, min(len(image_urls), spec.max_ref_images) + 1):
            tag = f"@Image{i}"
            if tag.lower() not in prompt_out.lower():
                missing_tags.append(tag)
        if missing_tags:
            ref_hint = (
                f" Use {', '.join(missing_tags)} as visual reference "
                f"for appearance/style of the edited result."
            )
            prompt_out = prompt_out.rstrip(".") + "." + ref_hint
            notes.append(f"Injected reference tags into prompt: {', '.join(missing_tags)}.")

    # Seedance reference-to-video V2V: video_urls[] + optional image_urls[]
    if "seedance" in spec.key and "reference-to-video" in spec.endpoint:
        if "@video1" not in prompt_out.lower() and "[video1]" not in prompt_out.lower():
            prompt_out = (
                prompt_out.rstrip(".")
                + ". Preserve camera motion and timing from @Video1."
            )
            notes.append("Injected @Video1 motion-lock tag into Seedance prompt.")
        args = {
            "prompt": prompt_out,
            "video_urls": [video_url],
            **spec.extra_defaults,
        }
        if image_urls:
            refs = image_urls[: spec.max_ref_images]
            args["image_urls"] = refs
        # Duration / resolution / aspect below (shared)
    else:
        # O3 prompts often reference @Video1
        if "@video1" not in prompt_out.lower() and "video" in spec.endpoint:
            pass  # optional; don't force

        args = {
            "prompt": prompt_out,
            spec.video_field: video_url,
            **spec.extra_defaults,
        }

        if spec.image_field and image_urls:
            refs = image_urls[: spec.max_ref_images]
            if len(image_urls) > spec.max_ref_images:
                notes.append(f"Reference images truncated to {spec.max_ref_images}.")
            if spec.multi_image:
                args[spec.image_field] = refs
            else:
                args[spec.image_field] = refs[0]

    if spec.keep_audio_param:
        keep = params.get("keep_audio")
        if keep is None:
            keep = other.get("keep_audio", spec.default_keep_audio)
        args[spec.keep_audio_param] = bool(keep)

    if spec.aspect_ratio_param:
        ar_req = params.get("aspect_ratio")
        if ar_req is None:
            ar_req = other.get("aspect_ratio")
        if ar_req is None:
            ar_req = spec.default_aspect_ratio
        _apply_aspect_ratio_arg(
            args,
            notes,
            param_name=spec.aspect_ratio_param,
            requested=ar_req,
            allowed=spec.allowed_aspect_ratios,
            default=spec.default_aspect_ratio or "1:1",
            source_image=None,
            resolution_hint=None,
        )

    if spec.duration_param:
        dur_in = params.get("duration_seconds") or params.get("duration")
        if dur_in is None:
            dur_in = other.get("duration_seconds", other.get("duration"))
        raw_dur = str(dur_in).strip().lower() if dur_in is not None else ""
        if raw_dur == "auto" and any(
            str(a).lower() == "auto" for a in (spec.allowed_durations or ())
        ):
            args[spec.duration_param] = "auto"
        else:
            dur = spec.clamp_duration(dur_in)
            if dur is not None:
                if dur_in is not None and str(dur_in).strip() not in (dur, f"{dur}s"):
                    notes.append(f"duration normalized/clamped {dur_in!r} → {dur}s.")
                if spec.duration_as_int and dur != "auto":
                    try:
                        args[spec.duration_param] = int(dur)
                    except (TypeError, ValueError):
                        args[spec.duration_param] = dur
                else:
                    args[spec.duration_param] = dur

    if spec.generate_audio_param:
        gen = params.get("generate_audio")
        if gen is None:
            gen = other.get("generate_audio", spec.default_generate_audio)
        args[spec.generate_audio_param] = bool(gen)

    if spec.resolution_param:
        res_in = params.get("resolution") or other.get("resolution")
        res = spec.clamp_resolution(str(res_in) if res_in is not None else None)
        if res:
            if res.lower() == "4k":
                res = "4k"
            args[spec.resolution_param] = res
            if res_in and str(res_in).strip().lower() != str(res).lower():
                notes.append(f"resolution normalized {res_in!r} → {res}.")

    if image_urls and not spec.image_field:
        notes.append(
            f"{spec.label} uses prompt + video only; reference stills are not sent to the API."
        )

    return args, notes


def build_i2v_arguments(
    spec: VideoModelSpec,
    *,
    prompt: str,
    image_url: str,
    parameters: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    if spec.task != "image_to_video":
        raise ValueError(f"Model {spec.key} is not an image_to_video model.")
    params = dict(parameters or {})
    notes: list[str] = []
    other = params.get("other") if isinstance(params.get("other"), dict) else {}

    # MiniMax H3 omni can run image-only, video-only, or mixed (prompt required)
    is_h3_omni = bool(spec.ref_image_field) and "reference-to-video" in spec.endpoint
    if not image_url and not is_h3_omni:
        raise ValueError("Start-frame image is required for image-to-video.")

    # Extra image URLs (multi-ref) from parameters
    extra_imgs = params.get("image_urls") or other.get("image_urls") or []
    if isinstance(extra_imgs, str):
        extra_imgs = [extra_imgs]
    extra_imgs = [str(u) for u in extra_imgs if u]

    # --- Image field(s) ---
    if is_h3_omni:
        img_field = spec.ref_image_field or "reference_image_urls"
        all_imgs: list[str] = []
        if image_url:
            all_imgs.append(image_url)
        for u in extra_imgs:
            if u not in all_imgs:
                all_imgs.append(u)
        cap_i = max(1, int(spec.max_ref_images or 9))
        args: dict[str, Any] = {**spec.extra_defaults}
        if all_imgs:
            args[img_field] = all_imgs[:cap_i]
    elif spec.i2v_image_field in ("image_urls",) or (
        "reference-to-video" in spec.endpoint and spec.multi_image
    ):
        imgs = [image_url] if image_url else []
        for u in extra_imgs:
            if u not in imgs:
                imgs.append(u)
        args = {
            "image_urls": imgs[: max(1, int(spec.max_ref_images or 9))],
            **spec.extra_defaults,
        }
    else:
        args = {
            spec.i2v_image_field: image_url,
            **spec.extra_defaults,
        }

    prompt_out = (prompt or "").strip()
    if prompt_out:
        style = (spec.prompt_citation_style or "at").lower()
        # Inject citation for multi-ref / omni when missing
        if (
            spec.auto_image_refs_in_prompt
            and (
                is_h3_omni
                or ("seedance" in spec.key and "reference" in spec.key)
            )
        ):
            low = prompt_out.lower()
            if style == "plain":
                if "image 1" not in low and "video 1" not in low:
                    prompt_out = (
                        prompt_out.rstrip(".")
                        + ". Use Image 1 as the primary subject/style reference"
                        + (
                            "; Video 1 for camera path / motion only"
                            if (
                                params.get("video_urls")
                                or other.get("video_urls")
                                or params.get("reference_video_urls")
                                or other.get("reference_video_urls")
                            )
                            else ""
                        )
                        + "."
                    )
                    notes.append("Injected Image 1 citation into prompt.")
            elif (
                "@image1" not in low
                and "[image1]" not in low
            ):
                prompt_out = (
                    prompt_out.rstrip(".")
                    + ". Use @Image1 as the primary visual reference for appearance and layout."
                )
                notes.append("Injected @Image1 reference tag into prompt.")
        args["prompt"] = prompt_out
    elif is_h3_omni:
        raise ValueError("MiniMax H3 reference-to-video needs a prompt.")

    if spec.duration_param:
        dur_in = params.get("duration_seconds") or params.get("duration")
        if dur_in is None:
            dur_in = other.get("duration_seconds", other.get("duration"))
        # Pass through "auto" when allowed (Seedance)
        raw_dur = str(dur_in).strip().lower() if dur_in is not None else ""
        if raw_dur == "auto" and any(
            str(a).lower() == "auto" for a in (spec.allowed_durations or ())
        ):
            args[spec.duration_param] = "auto"
        else:
            dur = spec.clamp_duration(dur_in)
            if dur is not None:
                if spec.duration_as_int and dur != "auto":
                    try:
                        args[spec.duration_param] = int(dur)
                    except (TypeError, ValueError):
                        args[spec.duration_param] = dur
                else:
                    args[spec.duration_param] = dur

    if spec.generate_audio_param:
        gen = params.get("generate_audio")
        if gen is None:
            gen = other.get("generate_audio", spec.default_generate_audio)
        args[spec.generate_audio_param] = bool(gen)

    if spec.resolution_param:
        res_in = params.get("resolution") or other.get("resolution")
        res = spec.clamp_resolution(str(res_in) if res_in is not None else None)
        if res:
            # Normalize 4K casing for Seedance (API uses "4k"); H3 uses "2K"
            if res.lower() == "4k":
                res = "4k"
            elif res.lower() == "2k":
                res = "2K"
            args[spec.resolution_param] = res

    if spec.aspect_ratio_param:
        ar_req = params.get("aspect_ratio")
        if ar_req is None:
            ar_req = other.get("aspect_ratio")
        if ar_req is None:
            ar_req = spec.default_aspect_ratio
        ar_low = str(ar_req or "").strip().lower()
        allowed_low = {a.lower() for a in (spec.allowed_aspect_ratios or ())}
        # Seedance "auto" / H3 "adaptive"
        if ar_low in ("auto", "adaptive") and ar_low in allowed_low:
            # Preserve API casing from allowed list
            for a in spec.allowed_aspect_ratios or ():
                if a.lower() == ar_low:
                    args[spec.aspect_ratio_param] = a
                    break
            else:
                args[spec.aspect_ratio_param] = ar_req
        else:
            _apply_aspect_ratio_arg(
                args,
                notes,
                param_name=spec.aspect_ratio_param,
                requested=ar_req,
                allowed=spec.allowed_aspect_ratios,
                default=spec.default_aspect_ratio or "1:1",
                source_image=None,
                resolution_hint=None,
            )

    end = params.get("end_image_url") or other.get("end_image_url")
    if end and (spec.supports_end_frame or "hailuo" in spec.endpoint or "minimax/h3" in spec.endpoint):
        args["end_image_url"] = str(end)

    # Reference videos (Seedance video_urls or H3 reference_video_urls)
    vrefs = (
        params.get("reference_video_urls")
        or other.get("reference_video_urls")
        or params.get("video_urls")
        or other.get("video_urls")
    )
    if vrefs and "reference-to-video" in spec.endpoint:
        if isinstance(vrefs, str):
            vrefs = [vrefs]
        vlist = [str(u) for u in vrefs if u]
        cap_v = max(1, int(spec.max_ref_videos or 3))
        vfield = spec.ref_video_field or "video_urls"
        if vlist:
            args[vfield] = vlist[:cap_v]

    # Reference audio (H3 only)
    arefs = (
        params.get("reference_audio_urls")
        or other.get("reference_audio_urls")
        or params.get("audio_urls")
        or other.get("audio_urls")
    )
    if arefs and spec.ref_audio_field:
        if isinstance(arefs, str):
            arefs = [arefs]
        alist = [str(u) for u in arefs if u]
        cap_a = max(1, int(spec.max_ref_audios or 3))
        if alist:
            args[spec.ref_audio_field] = alist[:cap_a]

    # Combined file cap (H3: ≤12)
    if spec.max_total_refs and int(spec.max_total_refs) > 0:
        total = 0
        for fk in (
            spec.ref_image_field,
            spec.ref_video_field,
            spec.ref_audio_field,
            "image_urls",
            "video_urls",
        ):
            if fk and isinstance(args.get(fk), list):
                total += len(args[fk])
        if total > int(spec.max_total_refs):
            notes.append(
                f"Reference pack exceeds {spec.max_total_refs} files — trim images/videos/audio."
            )

    # H3 omni needs at least one image or video
    if is_h3_omni:
        has_i = bool(args.get(spec.ref_image_field or "reference_image_urls"))
        has_v = bool(args.get(spec.ref_video_field or "reference_video_urls"))
        if not has_i and not has_v:
            raise ValueError(
                "MiniMax H3 omni needs at least one reference image or video "
                "(audio cannot be the only reference)."
            )
        if args.get(spec.ref_audio_field) and not has_i and not has_v:
            raise ValueError(
                "Reference audio must accompany an image or video reference."
            )

    if getattr(spec, "native_stereo_audio", False):
        notes.append("Native stereo audio is always on H3 output (no toggle).")

    return args, notes


def catalog_for_enhance() -> dict[str, dict]:
    """MODEL_CATALOG-style dict for the Grok system prompt."""
    out: dict[str, dict] = {}
    for key, spec in IMAGE_EDIT_MODELS.items():
        out[key] = {
            "label": spec.label,
            "modality": "image",
            "provider": "fal.ai",
            "fal_endpoint": spec.endpoint,
            "tasks": ["image_edit"],
            "max_resolution": spec.max_resolution,
            "max_num_images": spec.max_num_images,
            "notes": spec.notes,
        }
    for key, spec in VIDEO_MODELS.items():
        if key == "kling edit":  # skip alias duplicate
            continue
        out[key] = {
            "label": spec.label,
            "modality": "video",
            "provider": "fal.ai",
            "fal_endpoint": spec.endpoint,
            "tasks": [spec.task],
            "max_duration_seconds": spec.max_duration_seconds,
            "notes": spec.notes,
        }
    return out
