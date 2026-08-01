"""
Region edit — colored annotation boxes on a still for Seedream-style multi-region edits.

Boxes are normalized fractions of image width/height (0–1).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

# Up to 6 regions — high-contrast colors for model legibility
REGION_COLORS: list[tuple[str, str]] = [
    ("red", "#E53935"),
    ("blue", "#1E88E5"),
    ("green", "#43A047"),
    ("yellow", "#FDD835"),
    ("purple", "#8E24AA"),
    ("orange", "#FB8C00"),
]

MAX_REGIONS = len(REGION_COLORS)

REGION_DEFAULT_MODEL = "Image · Seedream 5 Pro (edit)"
REGION_DEFAULT_MODEL_KEY = "seedream 5 pro"

GLOBAL_LOCK_LINE = (
    "Remove all colored box markings, outlines, and labels from the final image. "
    "Change only what is described inside each colored box. "
    "Do not alter architecture, walls, floors, windows, camera framing, or anything "
    "outside the marked regions."
)


@dataclass
class RegionBox:
    """One annotation box on the source still."""

    id: str
    color_name: str  # red, blue, …
    color_hex: str
    prompt: str = ""
    # Normalized rect: left, top, width, height in 0–1
    left: float = 0.1
    top: float = 0.1
    width: float = 0.3
    height: float = 0.25

    def clamp(self) -> None:
        self.left = max(0.0, min(0.95, float(self.left)))
        self.top = max(0.0, min(0.95, float(self.top)))
        self.width = max(0.05, min(1.0 - self.left, float(self.width)))
        self.height = max(0.05, min(1.0 - self.top, float(self.height)))

    def pixel_rect(self, img_w: int, img_h: int) -> tuple[int, int, int, int]:
        self.clamp()
        x0 = int(self.left * img_w)
        y0 = int(self.top * img_h)
        x1 = int((self.left + self.width) * img_w)
        y1 = int((self.top + self.height) * img_h)
        x1 = max(x0 + 2, min(img_w, x1))
        y1 = max(y0 + 2, min(img_h, y1))
        return x0, y0, x1, y1

    def area(self) -> float:
        self.clamp()
        return max(0.0, self.width * self.height)

    def intersection_area(self, other: RegionBox) -> float:
        self.clamp()
        other.clamp()
        ax0, ay0 = self.left, self.top
        ax1, ay1 = self.left + self.width, self.top + self.height
        bx0, by0 = other.left, other.top
        bx1, by1 = other.left + other.width, other.top + other.height
        ix0, iy0 = max(ax0, bx0), max(ay0, by0)
        ix1, iy1 = min(ax1, bx1), min(ay1, by1)
        if ix1 <= ix0 or iy1 <= iy0:
            return 0.0
        return (ix1 - ix0) * (iy1 - iy0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "color_name": self.color_name,
            "color_hex": self.color_hex,
            "prompt": self.prompt,
            "left": self.left,
            "top": self.top,
            "width": self.width,
            "height": self.height,
        }


def next_color(used_names: set[str]) -> tuple[str, str]:
    for name, hex_c in REGION_COLORS:
        if name not in used_names:
            return name, hex_c
    return REGION_COLORS[0]


def make_box(
    *,
    index: int,
    used_names: set[str] | None = None,
    left: float | None = None,
    top: float | None = None,
) -> RegionBox:
    used = used_names or set()
    name, hex_c = next_color(used)
    # ~20% of frame, cascaded so new boxes are immediately visible and distinct
    offset = 0.08 * (index % 5)
    return RegionBox(
        id=f"box_{index}_{name}",
        color_name=name,
        color_hex=hex_c,
        prompt="",
        left=0.15 + offset if left is None else left,
        top=0.15 + (offset * 0.7) if top is None else top,
        width=0.22,
        height=0.20,
    )


# Soft keywords that imply furniture layering (compatible when overlapping)
_LAYER_SOFT = {
    "sofa",
    "couch",
    "table",
    "coffee",
    "chair",
    "stool",
    "rug",
    "lamp",
    "plant",
    "pillow",
    "ottoman",
    "desk",
    "bed",
    "cushion",
    "side table",
    "console",
}
# Same-role / contradictory intent pairs
_ROLE_KEYWORDS = {
    "sofa": {"sofa", "couch", "sectional", "loveseat"},
    "table": {"table", "desk", "console"},
    "chair": {"chair", "stool", "bench"},
    "lighting": {"lamp", "light", "sconce", "chandelier"},
    "floor": {"rug", "carpet", "flooring", "hardwood"},
    "wall": {"wall", "paint", "wallpaper", "art", "picture"},
    "sky": {"sky", "clouds", "sunset"},
    "window": {"window", "blinds", "curtains"},
}


def _roles_in_prompt(text: str) -> set[str]:
    low = (text or "").lower()
    roles: set[str] = set()
    for role, kws in _ROLE_KEYWORDS.items():
        if any(k in low for k in kws):
            roles.add(role)
    return roles


def _is_layering_compatible(a: str, b: str) -> bool:
    """True when two prompts look like stacked furniture, not same-role conflicts."""
    la, lb = (a or "").lower(), (b or "").lower()
    soft_a = any(w in la for w in _LAYER_SOFT)
    soft_b = any(w in lb for w in _LAYER_SOFT)
    if soft_a and soft_b:
        ra, rb = _roles_in_prompt(a), _roles_in_prompt(b)
        # Compatible if different primary furniture roles
        if ra and rb and ra.isdisjoint(rb):
            return True
        # sofa + coffee table pattern
        if ("sofa" in ra or "chair" in ra) and ("table" in rb or "rug" in rb):
            return True
        if ("sofa" in rb or "chair" in rb) and ("table" in ra or "rug" in ra):
            return True
    return False


@dataclass
class ConflictNote:
    kind: str  # composition | conflict
    message: str
    box_a: str
    box_b: str


def analyze_box_conflicts(boxes: list[RegionBox]) -> list[ConflictNote]:
    """
    Geometric overlap analysis.

    Compatible layering (sofa + table) → composition note.
    Same-role contradictions → conflict note (not silent-merged).
    """
    notes: list[ConflictNote] = []
    active = [b for b in boxes if (b.prompt or "").strip()]
    for i, a in enumerate(active):
        for b in active[i + 1 :]:
            inter = a.intersection_area(b)
            if inter <= 0:
                continue
            min_area = min(a.area(), b.area()) or 1e-6
            ratio = inter / min_area
            if ratio < 0.12:
                continue  # glancing overlap — ignore
            pa, pb = (a.prompt or "").strip(), (b.prompt or "").strip()
            if _is_layering_compatible(pa, pb):
                notes.append(
                    ConflictNote(
                        kind="composition",
                        message=(
                            f"{a.color_name.title()} + {b.color_name.title()}: "
                            "overlapping regions look like layered composition "
                            "(e.g. furniture stack) — OK if intentional."
                        ),
                        box_a=a.color_name,
                        box_b=b.color_name,
                    )
                )
                continue
            ra, rb = _roles_in_prompt(pa), _roles_in_prompt(pb)
            same = ra & rb
            if same or ratio > 0.35:
                role_bit = (
                    f" same role ({', '.join(sorted(same))})"
                    if same
                    else " heavy geometric overlap"
                )
                notes.append(
                    ConflictNote(
                        kind="conflict",
                        message=(
                            f"{a.color_name.title()} vs {b.color_name.title()}: "
                            f"possible contradictory instructions{role_bit}. "
                            "Review both prompts — they were not auto-merged."
                        ),
                        box_a=a.color_name,
                        box_b=b.color_name,
                    )
                )
            else:
                notes.append(
                    ConflictNote(
                        kind="composition",
                        message=(
                            f"{a.color_name.title()} + {b.color_name.title()}: "
                            "partial overlap — treat as composition if intents differ."
                        ),
                        box_a=a.color_name,
                        box_b=b.color_name,
                    )
                )
    return notes


def build_region_prompt(
    boxes: list[RegionBox],
    *,
    extra_global: str | None = None,
    include_lock_line: bool = True,
) -> str:
    """Color-keyed prompt for the annotated still."""
    parts: list[str] = []
    for b in boxes:
        text = (b.prompt or "").strip()
        if not text:
            continue
        parts.append(
            f"In the {b.color_name.upper()} box only: {text.rstrip('.')}."
        )
    if not parts:
        return ""
    body = " ".join(parts)
    if include_lock_line:
        body = f"{body} {GLOBAL_LOCK_LINE}"
    extra = (extra_global or "").strip()
    if extra:
        body = f"{body} Additional: {extra}"
    return body.strip()


def draw_region_overlay(
    source_path: str | Path,
    boxes: list[RegionBox],
    dest_path: str | Path,
    *,
    line_width: int | None = None,
    selected_index: int | None = None,
    selected_id: str | None = None,
) -> Path:
    """
    Composite colored boxes + labels onto a copy of the still.

    Empty boxes are still drawn so placement is visible before typing prompts.
    Selected box gets a thicker border and stronger fill.
    """
    src = Path(source_path)
    dest = Path(dest_path)
    dest.parent.mkdir(parents=True, exist_ok=True)

    with Image.open(src) as im:
        img = im.convert("RGBA")
        w, h = img.size
        overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        base_lw = line_width or max(4, min(w, h) // 160)

        try:
            font = ImageFont.truetype("arial.ttf", size=max(14, min(w, h) // 40))
        except OSError:
            try:
                font = ImageFont.load_default()
            except Exception:
                font = None

        for i, b in enumerate(boxes):
            x0, y0, x1, y1 = b.pixel_rect(w, h)
            hex_c = (b.color_hex or "#E53935").lstrip("#")
            if len(hex_c) == 6:
                r, g, bl = int(hex_c[0:2], 16), int(hex_c[2:4], 16), int(hex_c[4:6], 16)
            else:
                r, g, bl = 229, 57, 53
            is_sel = False
            if selected_id and b.id == selected_id:
                is_sel = True
            elif selected_index is not None and i == selected_index:
                is_sel = True
            lw = int(base_lw * 2.2) if is_sel else base_lw
            fill_a = 90 if is_sel else 55
            # Semi-transparent fill + strong outline (always, even without prompt)
            draw.rectangle([x0, y0, x1, y1], fill=(r, g, bl, fill_a))
            draw.rectangle([x0, y0, x1, y1], outline=(r, g, bl, 255), width=lw)
            # Inner white rim on selected for contrast on any house photo
            if is_sel and lw >= 4:
                inset = max(1, lw // 3)
                draw.rectangle(
                    [x0 + inset, y0 + inset, x1 - inset, y1 - inset],
                    outline=(255, 255, 255, 200),
                    width=max(1, inset),
                )
            label = b.color_name.upper() + (" ★" if is_sel else "")
            ty = max(0, y0 - (lw + 20))
            if font is not None:
                try:
                    bbox = draw.textbbox((x0, ty), label, font=font)
                    draw.rectangle(bbox, fill=(r, g, bl, 230))
                    draw.text((x0, ty), label, fill=(255, 255, 255, 255), font=font)
                except Exception:
                    draw.text((x0, ty), label, fill=(r, g, bl, 255))
            else:
                draw.text((x0, ty), label, fill=(r, g, bl, 255))

        out = Image.alpha_composite(img, overlay).convert("RGB")
        suffix = dest.suffix.lower()
        if suffix in (".jpg", ".jpeg"):
            out.save(dest, quality=92)
        else:
            if not suffix:
                dest = dest.with_suffix(".png")
            out.save(dest)

    return dest.resolve()


_live_preview_seq = 0


def live_preview_path(output_dir: str | Path | None = None) -> Path:
    """
    Path for the interactive region preview.

    Uses a rotating sequence so Flet reloads the image when boxes move
    (same-path overwrite is often cached by the UI).
    """
    global _live_preview_seq
    from media_studio.config import ensure_output_dir

    _live_preview_seq = (_live_preview_seq + 1) % 40
    root = ensure_output_dir(Path(output_dir) if output_dir else None)
    dest_dir = root / "_region"
    dest_dir.mkdir(parents=True, exist_ok=True)
    # Clean older previews occasionally
    if _live_preview_seq == 0:
        try:
            for old in dest_dir.glob("live_preview_*.jpg"):
                try:
                    old.unlink(missing_ok=True)  # type: ignore[call-arg]
                except TypeError:
                    try:
                        if old.is_file():
                            old.unlink()
                    except OSError:
                        pass
                except OSError:
                    pass
        except OSError:
            pass
    return dest_dir / f"live_preview_{_live_preview_seq:02d}.jpg"


# Models allowed in Region mode (annotation-box / Seedream workflow)
REGION_MODEL_KEYS: tuple[str, ...] = ("seedream 5 pro",)
REGION_MODEL_LABELS: tuple[str, ...] = (REGION_DEFAULT_MODEL,)


def enhance_region_user_payload(
    boxes: list[RegionBox],
    *,
    current_prompt: str | None = None,
) -> str:
    """JSON blob for Grok Enhance of region edits."""
    import json

    return json.dumps(
        {
            "mode": "region_edit",
            "boxes": [
                {
                    "color": b.color_name,
                    "prompt": (b.prompt or "").strip(),
                    "rect_norm": {
                        "left": b.left,
                        "top": b.top,
                        "width": b.width,
                        "height": b.height,
                    },
                }
                for b in boxes
                if (b.prompt or "").strip()
            ],
            "current_compiled_prompt": (current_prompt or "").strip(),
            "instructions": (
                "You are enhancing a REGION (annotation-box) edit. "
                "Use vision of the source still. "
                "Return optimized_prompt as a color-keyed full prompt: "
                "'In the RED box only: … In the BLUE box only: …' "
                "Append a line to remove box markings and change nothing outside boxes. "
                "Ground placements in real surfaces. Do not invent rooms. "
                "If two boxes conflict, note it in notes but do not silently merge."
            ),
        },
        indent=2,
    )


def sanitize_hex(color: str) -> str:
    c = (color or "").strip()
    if re.fullmatch(r"#[0-9A-Fa-f]{6}", c):
        return c.upper()
    return "#E53935"
