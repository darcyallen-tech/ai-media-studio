"""
Studio Image / Video modality sub-tabs and model filtering.

Image: I2I | T2I | R2I | Region
Video: I2V | T2V | V2V | R2V
"""

from __future__ import annotations

from typing import Literal

from media_studio.config import MODEL_LABELS
from media_studio.fal.models import (
    IMAGE_EDIT_MODELS,
    VIDEO_MODELS,
    resolve_image_edit_model,
    resolve_video_model,
)
from media_studio.scenarios import DEFAULT_IMAGE_MODEL, DEFAULT_VIDEO_EDIT_MODEL

ImageModality = Literal["i2i", "t2i", "r2i", "region"]
VideoModality = Literal["i2v", "t2v", "v2v", "r2v"]

IMAGE_MODALITY_PILLS: list[tuple[str, str]] = [
    ("i2i", "I2I"),
    ("t2i", "T2I"),
    ("r2i", "R2I"),
    ("region", "Region"),
]
VIDEO_MODALITY_PILLS: list[tuple[str, str]] = [
    ("i2v", "I2V"),
    ("t2v", "T2V"),
    ("v2v", "V2V"),
    ("r2v", "R2V"),
]

DEFAULT_IMAGE_MODALITY: ImageModality = "i2i"
DEFAULT_VIDEO_MODALITY: VideoModality = "i2v"

# Default model labels per modality (must exist in filtered lists when possible)
_DEFAULTS: dict[str, str] = {
    "i2i": DEFAULT_IMAGE_MODEL,
    "t2i": "Flux 2 Pro (T2I)",
    "r2i": DEFAULT_IMAGE_MODEL,
    "region": "Image · Seedream 5 Pro (edit)",
    "i2v": "Video · Kling O3 Standard – Image-to-Video",
    "t2v": "Veo 3.1 Fast",
    "v2v": DEFAULT_VIDEO_EDIT_MODEL,
    "r2v": "Video · MiniMax H3 – Omni Reference",
}


def normalize_image_modality(raw: str | None) -> ImageModality:
    m = (raw or "").strip().lower()
    if m in ("standard", "full", "edit"):
        return "i2i"
    if m in ("i2i", "t2i", "r2i", "region"):
        return m  # type: ignore[return-value]
    return DEFAULT_IMAGE_MODALITY


def normalize_video_modality(raw: str | None) -> VideoModality:
    m = (raw or "").strip().lower()
    if m in ("i2v", "t2v", "v2v", "r2v"):
        return m  # type: ignore[return-value]
    if m in ("camera_lock", "edit", "v2v_edit"):
        return "v2v"
    return DEFAULT_VIDEO_MODALITY


def _image_edit_labels(*, multi_ref_only: bool = False) -> list[str]:
    out: list[str] = []
    for label in MODEL_LABELS:
        if not label.startswith("Image ·"):
            continue
        if multi_ref_only:
            spec = resolve_image_edit_model(label)
            if spec is None or int(spec.max_ref_images or 1) <= 1:
                continue
        out.append(label)
    # Fallback from registry if MODEL_LABELS empty of image entries
    if not out:
        for spec in IMAGE_EDIT_MODELS.values():
            if multi_ref_only and int(spec.max_ref_images or 1) <= 1:
                continue
            out.append(spec.label)
    return out


def _t2i_labels() -> list[str]:
    from media_studio.vision_registry import T2I_MODELS

    return [s.label for s in T2I_MODELS.values()]


def _region_labels() -> list[str]:
    try:
        from media_studio.region_edit import REGION_DEFAULT_MODEL, REGION_MODEL_LABELS

        labels = [m for m in REGION_MODEL_LABELS if m]
        if REGION_DEFAULT_MODEL and REGION_DEFAULT_MODEL not in labels:
            labels = [REGION_DEFAULT_MODEL] + labels
        return labels or [REGION_DEFAULT_MODEL]
    except Exception:
        return ["Image · Seedream 5 Pro (edit)"]


def _is_r2v_video_spec(spec) -> bool:
    """True for multi-ref / omni reference-to-video (not V2V edit)."""
    if getattr(spec, "task", None) == "video_edit":
        return False
    if getattr(spec, "ref_image_field", None):
        return True
    key = (spec.key or "").lower()
    ep = (spec.endpoint or "").lower()
    if "reference-to-video" in ep and spec.task == "image_to_video":
        return True
    if "reference" in key and "v2v" not in key and "edit" not in key:
        return True
    return False


def _video_labels_for(modality: VideoModality) -> list[str]:
    out: list[str] = []
    if modality == "t2v":
        from media_studio.vision_registry import T2V_MODELS

        for spec in T2V_MODELS.values():
            if getattr(spec, "omni_reference", False):
                continue
            # Pure text — exclude reference-pack models that require stills
            if int(getattr(spec, "max_refs", 0) or 0) > 0:
                continue
            out.append(spec.label)
        return out

    for label in MODEL_LABELS:
        if not label.startswith("Video ·"):
            continue
        spec = resolve_video_model(label)
        if spec is None:
            continue
        if modality == "v2v":
            if spec.task == "video_edit":
                out.append(label)
        elif modality == "i2v":
            if (
                spec.task == "image_to_video"
                and not _is_r2v_video_spec(spec)
            ):
                out.append(label)
        elif modality == "r2v":
            if _is_r2v_video_spec(spec):
                out.append(label)

    if not out:
        # Registry fallback (keys not in curated MODEL_LABELS order)
        for spec in VIDEO_MODELS.values():
            if modality == "v2v" and spec.task == "video_edit":
                out.append(spec.label)
            elif modality == "i2v" and spec.task == "image_to_video" and not _is_r2v_video_spec(spec):
                out.append(spec.label)
            elif modality == "r2v" and _is_r2v_video_spec(spec):
                out.append(spec.label)
    # de-dupe preserve order
    seen: set[str] = set()
    uniq: list[str] = []
    for x in out:
        if x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq


def models_for_image_modality(modality: str | None) -> list[str]:
    m = normalize_image_modality(modality)
    if m == "t2i":
        return _t2i_labels()
    if m == "r2i":
        return _image_edit_labels(multi_ref_only=True)
    if m == "region":
        return _region_labels()
    # i2i — all image-edit models
    return _image_edit_labels(multi_ref_only=False)


def models_for_video_modality(modality: str | None) -> list[str]:
    return _video_labels_for(normalize_video_modality(modality))


def default_model_for_modality(modality: str | None) -> str:
    m = (modality or "").strip().lower()
    if m == "standard":
        m = "i2i"
    preferred = _DEFAULTS.get(m, "")
    if m in ("i2i", "t2i", "r2i", "region"):
        opts = models_for_image_modality(m)
    else:
        opts = models_for_video_modality(m)
    if preferred and preferred in opts:
        return preferred
    return opts[0] if opts else preferred or ""


def is_t2i_model_label(label: str | None) -> bool:
    if not label:
        return False
    from media_studio.vision_registry import find_vision_model

    spec = find_vision_model(label, "text_to_image")
    return bool(spec and spec.mode == "text_to_image")


def is_t2v_model_label(label: str | None) -> bool:
    if not label:
        return False
    from media_studio.vision_registry import find_vision_model

    spec = find_vision_model(label, "text_to_video")
    return bool(spec and spec.mode == "text_to_video" and not getattr(spec, "omni_reference", False))
