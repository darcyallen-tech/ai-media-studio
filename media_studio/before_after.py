"""
Before / after still export (Phase 6).

Side-by-side or vertical stack composites from a known source still + result.
Saves under the same job/dated folder as other media (via job_media_dir).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from media_studio.naming import job_media_dir, make_output_stem, timestamp_now, unique_path

LayoutKind = Literal["side_by_side", "stack"]

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tiff", ".tif"}


@dataclass
class BeforeAfterResult:
    ok: bool
    path: str | None = None
    status: str = ""
    notes: list[str] = field(default_factory=list)


def _is_image(path: str | Path | None) -> bool:
    if not path:
        return False
    try:
        p = Path(path)
        return p.is_file() and p.suffix.lower() in _IMAGE_EXTS
    except OSError:
        return False


def _open_rgb(path: str | Path):
    from PIL import Image

    im = Image.open(path)
    if im.mode in ("RGBA", "LA", "P"):
        bg = Image.new("RGB", im.size, (18, 20, 26))
        if im.mode == "P":
            im = im.convert("RGBA")
        if im.mode in ("RGBA", "LA"):
            alpha = im.split()[-1]
            bg.paste(im.convert("RGB"), mask=alpha)
            return bg
    return im.convert("RGB")


def _fit_height(im, target_h: int):
    from PIL import Image

    w, h = im.size
    if h <= 0:
        return im
    if h == target_h:
        return im
    nw = max(1, int(round(w * (target_h / h))))
    return im.resize((nw, target_h), Image.Resampling.LANCZOS)


def _fit_width(im, target_w: int):
    from PIL import Image

    w, h = im.size
    if w <= 0:
        return im
    if w == target_w:
        return im
    nh = max(1, int(round(h * (target_w / w))))
    return im.resize((target_w, nh), Image.Resampling.LANCZOS)


def _draw_label(im, text: str, *, corner: str = "tl") -> None:
    """Draw a small dark label bar with white text (optional dependency-free font)."""
    from PIL import ImageDraw, ImageFont

    draw = ImageDraw.Draw(im)
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None
    pad_x, pad_y = 8, 5
    # textbbox preferred
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    except Exception:
        tw, th = len(text) * 6, 11
    bar_w = tw + pad_x * 2
    bar_h = th + pad_y * 2
    w, h = im.size
    if corner == "tr":
        x0 = max(0, w - bar_w - 8)
    else:
        x0 = 8
    y0 = 8
    draw.rectangle([x0, y0, x0 + bar_w, y0 + bar_h], fill=(0, 0, 0, 180) if im.mode == "RGBA" else (20, 22, 28))
    # solid dark for RGB
    draw.rectangle([x0, y0, x0 + bar_w, y0 + bar_h], fill=(20, 22, 28))
    draw.text((x0 + pad_x, y0 + pad_y - 1), text, fill=(240, 242, 248), font=font)


def compose_before_after(
    before_path: str | Path,
    after_path: str | Path,
    *,
    layout: LayoutKind = "side_by_side",
    labels: bool = True,
    gap: int = 8,
    max_long_edge: int = 2400,
    bg: tuple[int, int, int] = (12, 14, 18),
):
    """
    Build a PIL Image composite. Caller is responsible for saving.

    side_by_side: before | after (same height)
    stack: before above after (same width) — phone-friendly vertical
    """
    from PIL import Image

    if not _is_image(before_path):
        raise FileNotFoundError(f"Before still missing: {before_path}")
    if not _is_image(after_path):
        raise FileNotFoundError(f"After still missing: {after_path}")

    before = _open_rgb(before_path)
    after = _open_rgb(after_path)

    if layout == "stack":
        # Match width to the narrower of the two (or average), then stack
        target_w = min(before.size[0], after.size[0])
        # Prefer a reasonable phone width if huge
        target_w = min(target_w, 1080)
        before = _fit_width(before, target_w)
        after = _fit_width(after, target_w)
        if labels:
            _draw_label(before, "BEFORE", corner="tl")
            _draw_label(after, "AFTER", corner="tl")
        canvas = Image.new(
            "RGB",
            (target_w, before.size[1] + after.size[1] + gap),
            bg,
        )
        canvas.paste(before, (0, 0))
        canvas.paste(after, (0, before.size[1] + gap))
    else:
        # Match height
        target_h = min(before.size[1], after.size[1])
        target_h = min(target_h, 1600)
        before = _fit_height(before, target_h)
        after = _fit_height(after, target_h)
        if labels:
            _draw_label(before, "BEFORE", corner="tl")
            _draw_label(after, "AFTER", corner="tl")
        canvas = Image.new(
            "RGB",
            (before.size[0] + after.size[0] + gap, target_h),
            bg,
        )
        canvas.paste(before, (0, 0))
        canvas.paste(after, (before.size[0] + gap, 0))

    # Cap long edge for file size
    w, h = canvas.size
    long_edge = max(w, h)
    if long_edge > max_long_edge:
        scale = max_long_edge / long_edge
        canvas = canvas.resize(
            (max(1, int(w * scale)), max(1, int(h * scale))),
            Image.Resampling.LANCZOS,
        )
    return canvas


def export_before_after(
    before_path: str | Path,
    after_path: str | Path,
    *,
    output_dir: str | Path,
    layout: LayoutKind = "side_by_side",
    labels: bool = True,
    job_name: str | None = None,
    prompt_hint: str = "before-after",
) -> BeforeAfterResult:
    """
    Compose and save a before/after still under the job/dated media folder.
    """
    try:
        img = compose_before_after(
            before_path,
            after_path,
            layout=layout,
            labels=labels,
        )
    except FileNotFoundError as exc:
        return BeforeAfterResult(ok=False, status=str(exc))
    except Exception as exc:
        return BeforeAfterResult(ok=False, status=f"Before/after compose failed: {exc}")

    stamp = timestamp_now()
    media_dir = job_media_dir(output_dir, stamp=stamp, job_name=job_name)
    kind = "ba-stack" if layout == "stack" else "ba-side"
    stem = make_output_stem(
        prompt_hint or "before-after",
        "before-after",
        stamp=stamp,
        kind=kind,
    )
    dest = unique_path(media_dir, stem, ".jpg")
    try:
        img.save(dest, format="JPEG", quality=92, optimize=True)
    except Exception as exc:
        return BeforeAfterResult(ok=False, status=f"Save failed: {exc}")

    layout_label = "vertical stack" if layout == "stack" else "side-by-side"
    return BeforeAfterResult(
        ok=True,
        path=str(dest.resolve()),
        status=f"Exported {layout_label} → {dest.name}",
        notes=[layout_label, Path(before_path).name, Path(after_path).name],
    )
