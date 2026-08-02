"""
Tools → Inpaint (freehand): 3-column layout when active.

Left: controls · Center: large paint canvas · Right: Tools result pane (host).
Mask required before Run. Other Tools keep their 2-column layout.
"""

from __future__ import annotations

import asyncio
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import flet as ft
import flet.canvas as ftc
from PIL import Image, ImageDraw, ImageFilter, ImageOps

from media_studio.flet_enhance import make_enhance_button, run_prompt_enhance
from media_studio.flet_model_hint import make_best_for_line, update_best_for_line
from media_studio.flet_pickers import pick_image
from media_studio.flet_progress import JobProgress, classify_progress
from media_studio.flet_source_strip import PreviousSourcesStrip, ResolveSourcesStrip
from media_studio.flet_theme import (
    ACCENT,
    ACCENT_BRIGHT,
    BORDER,
    FONT_SM,
    PANEL,
    PANEL_ELEVATED,
    TEXT,
    TEXT_MUTED,
    label,
    section_title,
    styled_dropdown,
)
from media_studio.tools_registry import (
    INPAINT_MODELS,
    find_tool,
    format_tool_cost,
    inpaint_labels,
    inpaint_max_num,
    inpaint_requires_ref,
    inpaint_shows_ref,
    inpaint_supports_batch,
)
from media_studio.tools_service import run_inpaint

if TYPE_CHECKING:
    from media_studio.flet_app import StudioState

# Center canvas — large painting surface (center column owns this)
_CANVAS = 560
_SOURCE_THUMB = 120
_ZOOM_MIN = 1.0
_ZOOM_MAX = 6.0
_ZOOM_STEP = 1.25
_GROW_OPTIONS = ("0", "2", "4", "8")
_GROW_DEFAULT = "4"
# Live stroke: Canvas shapes only (no PNG). Commit overlay PNG only on stroke end.
_BRUSH_PAINT = None  # set after ft import in class init
_ERASER_PAINT = None

# Intent scaffolds — short; user can edit freely. Custom/None injects nothing.
_INTENT_NONE = "Custom (no inject)"
_INTENT_SCAFFOLDS: dict[str, str] = {
    _INTENT_NONE: "",
    "Change object": (
        "Replace the masked object with: [describe new object]. "
        "Match lighting, perspective, and scale of the scene. "
        "Keep everything outside the mask unchanged."
    ),
    "Add object": (
        "Add into the masked region: [describe object]. "
        "Place it naturally with correct lighting and contact shadows. "
        "Do not alter unmasked areas."
    ),
    "Remove object": (
        "Remove the content in the masked region and fill with natural background "
        "continuation. Match textures and lighting. No new objects."
    ),
    "Change sky / background": (
        "Replace only the masked sky or background with: [describe look]. "
        "Keep foreground architecture and subjects locked outside the mask."
    ),
    "Fix reflection / mirror": (
        "Fix or replace the reflection in the masked mirror/glass region: "
        "[describe intended reflection or clear glass]. "
        "Keep frame, room, and unmasked pixels unchanged."
    ),
}


def _dd_value(dd: ft.Dropdown) -> str | None:
    return dd.value


class InpaintCard:
    """
    Freehand mask inpaint.

    Exposes ``controls_column`` (left) + ``canvas_column`` (center) for the
    Tools host 3-column layout. ``root`` is a stacked fallback for narrow use.
    """

    def __init__(self, page: ft.Page, state: StudioState) -> None:
        self.page = page
        self.state = state
        self.source_path: str | None = None
        self.ref_path: str | None = None
        self._result_path: str | None = None
        self._result_paths: list[str] = []
        self.on_result = None
        self.tool_label = "Inpaint (freehand)"

        # Full-resolution mask (must match source image WxH for fal)
        self._mask_full: Image.Image | None = None  # L, white=edit, source size
        self._src_size: tuple[int, int] | None = None  # (w, h) of normalized source
        # Letterbox of still inside the base canvas: (ox, oy, disp_w, disp_h)
        self._view_rect: tuple[int, int, int, int] | None = None
        self._src_display: Image.Image | None = None  # RGB base canvas (zoom=1 bake)
        # Full-res RGB PNG for fal (EXIF-normalized; same pixels as mask size)
        self._src_export_path: str | None = None
        # Viewport zoom/pan over base canvas (fit = zoom 1, origin 0)
        self._zoom = _ZOOM_MIN
        self._view_ox = 0.0  # top-left of viewport in base-canvas coords
        self._view_oy = 0.0
        self._pan_mode = False
        self._panning = False
        self._pan_last: tuple[float, float] | None = None
        self._last_view_refresh = 0.0
        self._brush = 22  # screen pixels (constant under zoom)
        self._tool = "brush"  # brush | eraser
        self._drawing = False
        self._last_xy: tuple[float, float] | None = None
        self._undo_stack: list[Image.Image] = []
        self._grow_px = int(_GROW_DEFAULT)
        self._tmp_dir = Path(tempfile.gettempdir()) / "ams_inpaint"
        try:
            self._tmp_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        self._overlay_file = self._tmp_dir / "mask_overlay_commit.png"
        self._src_file = self._tmp_dir / "src_display_live.png"
        # Live stroke paints (GPU canvas shapes — no disk I/O while drawing)
        self._brush_paint = ft.Paint(
            color="#e63c3c",
            style=ft.PaintingStyle.FILL,
            # ~55% opacity for live preview
            blend_mode=ft.BlendMode.SRC_OVER,
        )
        try:
            # Prefer with_opacity when available
            self._brush_paint = ft.Paint(
                color=ft.Colors.with_opacity(0.55, "#e63c3c"),
                style=ft.PaintingStyle.FILL,
            )
            self._eraser_paint = ft.Paint(
                color=ft.Colors.with_opacity(0.45, "#90caf9"),
                style=ft.PaintingStyle.FILL,
            )
        except Exception:
            self._eraser_paint = ft.Paint(
                color="#90caf9", style=ft.PaintingStyle.FILL
            )

        # ----- Source thumb (left rail) -----
        self.src_thumb = ft.Image(
            src="",
            width=_SOURCE_THUMB,
            height=_SOURCE_THUMB,
            fit=ft.BoxFit.CONTAIN,
            visible=False,
            border_radius=4,
        )
        self.src_thumb_ph = ft.Container(
            content=ft.Text("No source", size=FONT_SM, color=TEXT_MUTED),
            width=_SOURCE_THUMB,
            height=_SOURCE_THUMB,
            alignment=ft.Alignment.CENTER,
            bgcolor=PANEL_ELEVATED,
            border=ft.Border.all(1, BORDER),
            border_radius=4,
        )
        self.btn_upload = ft.OutlinedButton(
            content="Upload still",
            icon=ft.Icons.UPLOAD_FILE,
            on_click=self._pick_source,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
        )
        self.prev_strip = PreviousSourcesStrip(
            page,
            get_output_dir=lambda: self.state.output_dir,
            on_load=self._on_prev,
            media_kind="image",
        )
        self.resolve_strip = ResolveSourcesStrip(
            page, on_load=self._on_prev, media_kind="image"
        )

        labels = inpaint_labels()
        self.model_dd = styled_dropdown(
            label_text="Model",
            options=labels,
            value=labels[0] if labels else None,
            on_select=self._refresh_cost,
            expand=True,
        )
        self.model_best_for = make_best_for_line()
        update_best_for_line(
            self.model_best_for, labels[0] if labels else None, dropdown=self.model_dd
        )

        # Intent helpers
        intent_keys = list(_INTENT_SCAFFOLDS.keys())
        self.intent_dd = styled_dropdown(
            label_text="Intent helper",
            options=intent_keys,
            value=_INTENT_NONE,
            on_select=self._on_intent,
            expand=True,
        )
        self.intent_hint = ft.Text(
            "Optional scaffold — edit freely. Custom leaves prompt alone.",
            size=11,
            color=TEXT_MUTED,
            max_lines=2,
        )

        self.prompt = ft.TextField(
            label="What to put in the masked region",
            hint_text="e.g. modern oak coffee table, matching room lighting",
            multiline=True,
            min_lines=3,
            max_lines=5,
            dense=True,
            filled=True,
            fill_color=PANEL_ELEVATED,
            border_color=BORDER,
            color=TEXT,
            text_size=FONT_SM,
        )
        self.negative = ft.TextField(
            label="Negative (optional)",
            dense=True,
            filled=True,
            fill_color=PANEL_ELEVATED,
            border_color=BORDER,
            color=TEXT,
            text_size=FONT_SM,
        )
        self.grow_dd = styled_dropdown(
            label_text="Grow mask",
            options=list(_GROW_OPTIONS),
            value=_GROW_DEFAULT,
            on_select=self._on_grow,
            expand=True,
        )
        self.grow_hint = ft.Text(
            "Expand mask so fill blends at edges (export only).",
            size=11,
            color=TEXT_MUTED,
            max_lines=2,
        )
        # Batch count — only when model.max_num_images > 1
        self.num_dd = styled_dropdown(
            label_text="# Images",
            options=["1", "2", "3", "4"],
            value="1",
            on_select=self._refresh_cost,
            expand=True,
        )
        self.num_dd.visible = True
        self.strength = ft.Slider(
            min=0.2,
            max=1.0,
            divisions=16,
            value=0.85,
            label="Strength {value}",
            active_color=ACCENT,
            visible=False,
        )
        # Optional / required reference still (model-gated)
        self.ref_thumb = ft.Image(
            src="",
            width=_SOURCE_THUMB,
            height=_SOURCE_THUMB,
            fit=ft.BoxFit.CONTAIN,
            visible=False,
            border_radius=4,
        )
        self.ref_thumb_ph = ft.Container(
            content=ft.Text("No ref", size=FONT_SM, color=TEXT_MUTED),
            width=_SOURCE_THUMB,
            height=_SOURCE_THUMB,
            alignment=ft.Alignment.CENTER,
            bgcolor=PANEL_ELEVATED,
            border=ft.Border.all(1, BORDER),
            border_radius=4,
        )
        self.btn_upload_ref = ft.OutlinedButton(
            content="Upload ref still",
            icon=ft.Icons.FACE,
            on_click=self._pick_ref,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
        )
        self.btn_clear_ref = ft.TextButton(
            content="Clear ref",
            on_click=self._clear_ref,
            style=ft.ButtonStyle(color=TEXT_MUTED),
            visible=False,
        )
        self.ref_prev_strip = PreviousSourcesStrip(
            page,
            get_output_dir=lambda: self.state.output_dir,
            on_load=self._on_ref_prev,
            media_kind="image",
        )
        self.ref_resolve_strip = ResolveSourcesStrip(
            page, on_load=self._on_ref_prev, media_kind="image"
        )
        self.ref_hint = ft.Text(
            "Optional reference for fill content / identity.",
            size=11,
            color=TEXT_MUTED,
            max_lines=2,
        )
        self.ref_section = ft.Column(
            [
                label("Reference still", muted=True),
                self.ref_hint,
                ft.Stack(
                    [self.ref_thumb_ph, self.ref_thumb],
                    width=_SOURCE_THUMB,
                    height=_SOURCE_THUMB,
                ),
                ft.Row(
                    [self.btn_upload_ref, self.btn_clear_ref],
                    spacing=8,
                    wrap=True,
                    tight=True,
                ),
                self.ref_prev_strip.root,
                self.ref_resolve_strip.root,
            ],
            spacing=6,
            tight=True,
            visible=False,
        )
        self.cost_text = ft.Text(
            self._cost(), size=FONT_SM, color=TEXT, weight=ft.FontWeight.W_600
        )
        self.status = ft.Text("", size=FONT_SM, color=TEXT_MUTED, max_lines=4)
        self.job_progress = JobProgress()
        self.btn = ft.FilledButton(
            content="Run inpaint",
            on_click=self._run,
            style=ft.ButtonStyle(bgcolor=ACCENT_BRIGHT, color=TEXT),
            height=40,
        )
        self.btn_enhance = make_enhance_button(on_click=self._on_enhance)
        self.state.on_keys_changed(self.apply_key_gates)
        self.apply_key_gates()

        # ----- Center canvas -----
        self.canvas_src = ft.Image(
            src="",
            width=_CANVAS,
            height=_CANVAS,
            fit=ft.BoxFit.FILL,
            visible=False,
            gapless_playback=True,
        )
        self.canvas_overlay = ft.Image(
            src="",
            width=_CANVAS,
            height=_CANVAS,
            fit=ft.BoxFit.FILL,
            visible=False,
            gapless_playback=True,
            opacity=0.5,
        )
        self.canvas_ph = ft.Container(
            content=ft.Column(
                [
                    ft.Icon(ft.Icons.BRUSH, size=40, color=TEXT_MUTED),
                    ft.Text(
                        "Upload a still, then paint the region to change",
                        size=FONT_SM,
                        color=TEXT_MUTED,
                        text_align=ft.TextAlign.CENTER,
                    ),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=8,
                tight=True,
            ),
            width=_CANVAS,
            height=_CANVAS,
            alignment=ft.Alignment.CENTER,
            bgcolor="#111318",
            border=ft.Border.all(1, BORDER),
            border_radius=8,
        )

        def _xy(e: Any) -> tuple[float, float]:
            pos = getattr(e, "local_position", None)
            if pos is not None:
                return float(getattr(pos, "x", 0) or 0), float(
                    getattr(pos, "y", 0) or 0
                )
            return float(getattr(e, "local_x", 0) or 0), float(
                getattr(e, "local_y", 0) or 0
            )

        def _pan_start(e: ft.DragStartEvent) -> None:
            if not self._can_paint():
                return
            x, y = _xy(e)
            if self._pan_mode:
                self._panning = True
                self._drawing = False
                self._pan_last = (x, y)
                return
            self._panning = False
            self._drawing = True
            self._push_undo()
            # Clear live stroke layer for this gesture
            self.live_canvas.shapes = []
            self._last_xy = (x, y)
            self._paint_at(x, y, live=True)
            self._flush_live_canvas()

        def _pan_update(e: ft.DragUpdateEvent) -> None:
            if not self._can_paint():
                return
            x, y = _xy(e)
            if self._panning or self._pan_mode:
                if self._pan_last is None:
                    self._pan_last = (x, y)
                    return
                lx, ly = self._pan_last
                # Drag content with pointer: move view origin opposite direction
                z = max(self._zoom, 0.01)
                self._view_ox -= (x - lx) / z
                self._view_oy -= (y - ly) / z
                self._pan_last = (x, y)
                self._clamp_view()
                # Throttle re-bake while dragging (~20 fps)
                now = time.time()
                if now - self._last_view_refresh >= 0.05:
                    self._last_view_refresh = now
                    self._refresh_viewport(rebuild_overlay=True)
                return
            if not self._drawing:
                return
            if self._last_xy:
                self._paint_line(
                    self._last_xy[0], self._last_xy[1], x, y, live=True
                )
            else:
                self._paint_at(x, y, live=True)
            self._last_xy = (x, y)
            # Canvas-only update — no PNG, no full page rebuild
            self._flush_live_canvas()

        def _pan_end(_e: ft.DragEndEvent) -> None:
            was_panning = self._panning
            self._drawing = False
            self._panning = False
            self._last_xy = None
            self._pan_last = None
            if not self._can_paint():
                return
            if was_panning:
                self._refresh_viewport(rebuild_overlay=True)
                return
            # Bake mask → committed overlay once; clear live strokes
            self.live_canvas.shapes = []
            self._flush_live_canvas()
            self._write_overlay(force=True)

        def _on_scroll(e: Any) -> None:
            if not self._can_paint():
                return
            # Scroll delta: negative = zoom in (typical wheel up)
            dy = float(getattr(e, "scroll_delta_y", 0) or 0)
            if dy == 0:
                dy = float(getattr(e, "dy", 0) or 0)
            if dy == 0:
                return
            factor = _ZOOM_STEP if dy < 0 else (1.0 / _ZOOM_STEP)
            # Zoom toward pointer if available
            sx, sy = _xy(e)
            self._zoom_by(factor, anchor_sx=sx, anchor_sy=sy)

        # Live stroke layer (instant) + committed overlay Image (baked on stroke end)
        self.live_canvas = ftc.Canvas(
            shapes=[],
            width=_CANVAS,
            height=_CANVAS,
        )
        # Stack: placeholder, source still, committed mask PNG, live stroke canvas
        self.canvas_stack = ft.Stack(
            [
                self.canvas_ph,
                self.canvas_src,
                self.canvas_overlay,
                self.live_canvas,
            ],
            width=_CANVAS,
            height=_CANVAS,
        )
        self.gesture = ft.GestureDetector(
            content=self.canvas_stack,
            on_pan_start=_pan_start,
            on_pan_update=_pan_update,
            on_pan_end=_pan_end,
            on_scroll=_on_scroll,
            # Low interval = more points = smoother lines (cheap with Canvas shapes)
            drag_interval=0,
        )

        self.brush_slider = ft.Slider(
            min=4,
            max=80,
            divisions=38,
            value=22,
            label="Brush {value}px (screen)",
            active_color=ACCENT,
            on_change=self._on_brush,
        )
        self.btn_brush = ft.FilledButton(
            content="Brush",
            on_click=lambda _e: self._set_tool("brush"),
            style=ft.ButtonStyle(bgcolor=ACCENT_BRIGHT, color=TEXT),
            height=34,
        )
        self.btn_eraser = ft.OutlinedButton(
            content="Eraser",
            on_click=lambda _e: self._set_tool("eraser"),
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
            height=34,
        )
        self.btn_pan = ft.OutlinedButton(
            content="Pan",
            on_click=lambda _e: self._set_pan_mode(not self._pan_mode),
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
            height=34,
            tooltip="Drag to pan when zoomed",
        )
        self.btn_zoom_out = ft.IconButton(
            icon=ft.Icons.ZOOM_OUT,
            icon_color=TEXT,
            tooltip="Zoom out",
            on_click=lambda _e: self._zoom_by(1.0 / _ZOOM_STEP),
            icon_size=20,
        )
        self.btn_zoom_in = ft.IconButton(
            icon=ft.Icons.ZOOM_IN,
            icon_color=TEXT,
            tooltip="Zoom in",
            on_click=lambda _e: self._zoom_by(_ZOOM_STEP),
            icon_size=20,
        )
        self.btn_zoom_fit = ft.TextButton(
            content="Fit",
            on_click=lambda _e: self._zoom_fit(),
            style=ft.ButtonStyle(color=TEXT_MUTED),
            tooltip="Reset zoom to fit whole image",
        )
        self.zoom_label = ft.Text(
            "100%",
            size=FONT_SM,
            color=TEXT_MUTED,
            width=44,
            text_align=ft.TextAlign.CENTER,
        )
        self.btn_clear_mask = ft.TextButton(
            content="Clear mask",
            on_click=self._clear_mask,
            style=ft.ButtonStyle(color=TEXT_MUTED),
        )
        self.btn_undo = ft.TextButton(
            content="Undo",
            on_click=self._undo_mask,
            style=ft.ButtonStyle(color=TEXT_MUTED),
        )
        self.canvas_caption = ft.Text(
            "Paint = edit region · Brush is screen-px (constant under zoom) · "
            "Pan when zoomed · Scroll wheel zooms",
            size=11,
            color=TEXT_MUTED,
        )

        # ----- Public layout parts -----
        self.controls_column = ft.Container(
            content=ft.Column(
                [
                    section_title("Inpaint"),
                    ft.Text(
                        "Paint the region to change. Unmasked pixels stay locked.",
                        size=FONT_SM,
                        color=TEXT_MUTED,
                    ),
                    label("Source still", muted=True),
                    ft.Stack(
                        [self.src_thumb_ph, self.src_thumb],
                        width=_SOURCE_THUMB,
                        height=_SOURCE_THUMB,
                    ),
                    self.btn_upload,
                    self.prev_strip.root,
                    self.resolve_strip.root,
                    ft.Divider(height=1, color=BORDER),
                    ft.Row([self.model_dd], spacing=0),
                    self.model_best_for,
                    label("Intent helper", muted=True),
                    self.intent_dd,
                    self.intent_hint,
                    self.prompt,
                    self.negative,
                    label("Grow mask", muted=True),
                    self.grow_dd,
                    self.grow_hint,
                    self.num_dd,
                    self.strength,
                    self.ref_section,
                    self.cost_text,
                    ft.Row([self.btn_enhance, self.btn], spacing=8, wrap=True),
                    self.job_progress.control,
                    self.status,
                ],
                spacing=8,
                tight=True,
                scroll=ft.ScrollMode.AUTO,
            ),
            expand=True,
            bgcolor=PANEL,
            border=ft.Border.all(1, BORDER),
            border_radius=8,
            padding=12,
        )

        self.canvas_column = ft.Container(
            content=ft.Column(
                [
                    label("Paint mask", muted=True),
                    self.canvas_caption,
                    ft.Container(
                        content=self.gesture,
                        alignment=ft.Alignment.CENTER,
                        expand=True,
                        clip_behavior=ft.ClipBehavior.HARD_EDGE,
                    ),
                    ft.Row(
                        [
                            self.btn_zoom_out,
                            self.zoom_label,
                            self.btn_zoom_in,
                            self.btn_zoom_fit,
                            self.btn_pan,
                        ],
                        spacing=4,
                        wrap=True,
                        alignment=ft.MainAxisAlignment.CENTER,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Row(
                        [
                            self.btn_brush,
                            self.btn_eraser,
                            self.btn_undo,
                            self.btn_clear_mask,
                        ],
                        spacing=8,
                        wrap=True,
                        alignment=ft.MainAxisAlignment.CENTER,
                    ),
                    self.brush_slider,
                ],
                spacing=8,
                tight=True,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                expand=True,
            ),
            expand=True,
            bgcolor=PANEL,
            border=ft.Border.all(1, BORDER),
            border_radius=8,
            padding=12,
            alignment=ft.Alignment.TOP_CENTER,
        )

        # Fallback single root (stacked) if host doesn't use 3-col
        self.root = ft.Container(
            content=ft.Column(
                [self.controls_column, self.canvas_column],
                spacing=10,
                tight=True,
                expand=True,
            ),
            expand=True,
        )
        # Sync batch / strength / ref visibility for default model
        self._sync_model_ui()

    # ----- layout flag for Tools host -----
    @property
    def uses_three_column(self) -> bool:
        return True

    def _num_images(self) -> int:
        try:
            n = int(_dd_value(self.num_dd) or "1")
        except (TypeError, ValueError):
            n = 1
        spec = find_tool(_dd_value(self.model_dd), INPAINT_MODELS)
        return max(1, min(inpaint_max_num(spec), n))

    def _cost(self) -> str:
        spec = find_tool(_dd_value(self.model_dd), INPAINT_MODELS)
        if not spec:
            return "Est. cost: —"
        return format_tool_cost(spec, num_images=self._num_images())

    def _sync_model_ui(self) -> None:
        """Show/hide batch, strength, ref based on selected model."""
        spec = find_tool(_dd_value(self.model_dd), INPAINT_MODELS)
        # Batch
        batch = inpaint_supports_batch(spec)
        try:
            self.num_dd.visible = batch
            if batch:
                max_n = inpaint_max_num(spec)
                opts = [str(i) for i in range(1, max_n + 1)]
                # Rebuild options if needed
                try:
                    cur = _dd_value(self.num_dd) or "1"
                    if int(cur) > max_n:
                        self.num_dd.value = "1"
                except (TypeError, ValueError):
                    self.num_dd.value = "1"
                # Keep simple fixed 1–4 options; clamp on read
                _ = opts
            else:
                self.num_dd.value = "1"
        except Exception:
            pass
        # Strength for inpainting endpoints (not fill)
        ep = ((spec.endpoint if spec else "") or "").lower()
        show_strength = bool(
            spec
            and (
                ep.endswith("/inpainting")
                or ep.endswith("/inpaint")
                or "/inpainting" in ep
            )
        )
        try:
            self.strength.visible = show_strength
        except Exception:
            pass
        # Reference still
        show_ref = inpaint_shows_ref(spec)
        req_ref = inpaint_requires_ref(spec)
        try:
            self.ref_section.visible = show_ref
            if show_ref:
                if req_ref:
                    self.ref_hint.value = (
                        "Required — reference identity/style into the mask."
                    )
                    self.ref_thumb_ph.content = ft.Text(
                        "Ref required", size=FONT_SM, color=TEXT_MUTED
                    )
                else:
                    self.ref_hint.value = (
                        "Optional fill/reference still for mask content."
                    )
                    self.ref_thumb_ph.content = ft.Text(
                        "No ref", size=FONT_SM, color=TEXT_MUTED
                    )
            elif self.ref_path:
                # Keep path but hidden — won't be sent for non-ref models
                pass
        except Exception:
            pass
        self.cost_text.value = self._cost()
        update_best_for_line(
            self.model_best_for, _dd_value(self.model_dd), dropdown=self.model_dd
        )

    def apply_key_gates(self) -> None:
        from media_studio.secrets_store import has_fal_key, has_xai_key

        ready = has_fal_key()
        if not self.state.is_busy("tools"):
            self.btn.disabled = not ready
            self.btn.tooltip = (
                None if ready else "Add your FAL API key in Settings to run tools"
            )
            xai = has_xai_key()
            self.btn_enhance.disabled = not xai

    def force_mode(self, mode: str, *, clear_source: bool = False) -> None:
        if clear_source:
            self.source_path = None
            self._reset_mask_state()

    def load_source(
        self, path: str, *, as_video: bool = False, status: str | None = None
    ) -> bool:
        if as_video:
            self.status.value = "Inpaint needs a still, not a video."
            self.status.color = "#e57373"
            return False
        return self._load_still(path, status=status)

    def load_image(self, path: str, *, status: str | None = None) -> bool:
        return self._load_still(path, status=status)

    def _on_prev(self, path: str) -> None:
        self._load_still(path, status=f"Previous: {Path(path).name}")
        try:
            self.page.update()
        except Exception:
            pass

    def _can_paint(self) -> bool:
        return bool(
            self.source_path
            and self._mask_full is not None
            and self._src_size is not None
            and self._view_rect is not None
            and self._src_display is not None
            and Path(self.source_path).is_file()
        )

    def _viewport_to_base(self, sx: float, sy: float) -> tuple[float, float]:
        """Map viewport (on-screen) pointer → base canvas coords (fit / zoom=1 space)."""
        z = max(float(self._zoom), 0.01)
        return self._view_ox + sx / z, self._view_oy + sy / z

    def _visible_base_size(self) -> tuple[float, float]:
        z = max(float(self._zoom), 0.01)
        return float(_CANVAS) / z, float(_CANVAS) / z

    def _clamp_view(self) -> None:
        """Keep viewport inside the base canvas."""
        vw, vh = self._visible_base_size()
        max_ox = max(0.0, float(_CANVAS) - vw)
        max_oy = max(0.0, float(_CANVAS) - vh)
        self._view_ox = max(0.0, min(max_ox, float(self._view_ox)))
        self._view_oy = max(0.0, min(max_oy, float(self._view_oy)))

    def _update_zoom_label(self) -> None:
        try:
            self.zoom_label.value = f"{int(round(self._zoom * 100))}%"
        except Exception:
            pass

    def _zoom_fit(self) -> None:
        self._zoom = _ZOOM_MIN
        self._view_ox = 0.0
        self._view_oy = 0.0
        try:
            self.live_canvas.shapes = []
        except Exception:
            pass
        self._update_zoom_label()
        self._refresh_viewport(rebuild_overlay=True)
        try:
            self.page.update()
        except Exception:
            pass

    def _zoom_by(
        self,
        factor: float,
        *,
        anchor_sx: float | None = None,
        anchor_sy: float | None = None,
    ) -> None:
        if not self._can_paint() and self._src_display is None:
            return
        old_z = max(float(self._zoom), 0.01)
        new_z = max(_ZOOM_MIN, min(_ZOOM_MAX, old_z * float(factor)))
        if abs(new_z - old_z) < 1e-6:
            self._update_zoom_label()
            return
        # Keep point under cursor (or viewport center) stable
        if anchor_sx is None:
            anchor_sx = _CANVAS * 0.5
        if anchor_sy is None:
            anchor_sy = _CANVAS * 0.5
        bx = self._view_ox + float(anchor_sx) / old_z
        by = self._view_oy + float(anchor_sy) / old_z
        self._zoom = new_z
        self._view_ox = bx - float(anchor_sx) / new_z
        self._view_oy = by - float(anchor_sy) / new_z
        self._clamp_view()
        try:
            self.live_canvas.shapes = []
        except Exception:
            pass
        self._update_zoom_label()
        self._refresh_viewport(rebuild_overlay=True)
        try:
            self.page.update()
        except Exception:
            pass

    def _set_pan_mode(self, on: bool) -> None:
        self._pan_mode = bool(on)
        try:
            if self._pan_mode:
                self.btn_pan.style = ft.ButtonStyle(
                    bgcolor=ACCENT, color=TEXT
                )
                self.canvas_caption.value = (
                    "Pan mode · drag to move · Fit resets · brush is screen-px"
                )
            else:
                self.btn_pan.style = ft.ButtonStyle(
                    color=TEXT, side=ft.BorderSide(1, BORDER)
                )
                self._set_tool(self._tool)  # restore brush/eraser caption
                return
            self.page.update()
        except Exception:
            pass

    def _refresh_viewport(self, *, rebuild_overlay: bool = False) -> None:
        """
        Re-render source (and optionally mask overlay) for current zoom/pan.

        Base image stays letterboxed CONTAIN at zoom=1; zoom crops that bake
        and upscales into the fixed viewport — aspect and 3-col layout unchanged.
        """
        if self._src_display is None:
            return
        try:
            self._clamp_view()
            z = max(float(self._zoom), 0.01)
            vw = max(1.0, float(_CANVAS) / z)
            vh = max(1.0, float(_CANVAS) / z)
            ox = float(self._view_ox)
            oy = float(self._view_oy)
            # Float crop box clamped to base pixels
            x0 = max(0.0, min(float(_CANVAS) - 1.0, ox))
            y0 = max(0.0, min(float(_CANVAS) - 1.0, oy))
            x1 = max(x0 + 1.0, min(float(_CANVAS), ox + vw))
            y1 = max(y0 + 1.0, min(float(_CANVAS), oy + vh))
            crop = self._src_display.crop(
                (int(x0), int(y0), int(round(x1)), int(round(y1)))
            )
            view = crop.resize((_CANVAS, _CANVAS), Image.Resampling.BILINEAR)
            stamp = int(time.time() * 1000)
            src_path = self._tmp_dir / f"src_view_{stamp}.png"
            view.save(src_path, format="PNG")
            abs_path = str(src_path.resolve())
            try:
                self.canvas_src.src = abs_path
                self.canvas_src.visible = True
                self.canvas_src.update()
            except Exception:
                self.canvas_src = self._make_canvas_image(abs_path)
                self._rebuild_canvas_stack()
            try:
                for old in self._tmp_dir.glob("src_view_*.png"):
                    if old != src_path and old.stat().st_mtime < time.time() - 60:
                        old.unlink(missing_ok=True)
            except OSError:
                pass
            if rebuild_overlay:
                self._write_overlay(force=True)
        except Exception:
            pass

    def _canvas_to_full(
        self, sx: float, sy: float
    ) -> tuple[float, float, float] | None:
        """
        Map viewport pointer → full-res mask coords + brush→full scale factor.

        Brush is constant screen pixels: full-res radius uses scale / zoom.
        Returns (fx, fy, scale_screen_to_full) or None outside the image area.
        """
        if not self._src_size or not self._view_rect:
            return None
        # Viewport → base (fit) canvas
        cx, cy = self._viewport_to_base(sx, sy)
        ox, oy, dw, dh = self._view_rect
        sw, sh = self._src_size
        if dw < 1 or dh < 1:
            return None
        z = max(float(self._zoom), 0.01)
        # Soft margin in base units (brush half-width in base space)
        margin = max(2.0, (self._brush * 0.5) / z)
        if (
            cx < ox - margin
            or cy < oy - margin
            or cx > ox + dw + margin
            or cy > oy + dh + margin
        ):
            return None
        sx_f = sw / float(dw)
        sy_f = sh / float(dh)
        # base→full, then /zoom so screen-px brush stays constant under zoom
        scale = ((sx_f + sy_f) * 0.5) / z
        fx = (cx - ox) * sx_f
        fy = (cy - oy) * sy_f
        fx = max(0.0, min(float(sw - 1), fx))
        fy = max(0.0, min(float(sh - 1), fy))
        return fx, fy, scale

    def _show_canvas_error(self, msg: str) -> None:
        """Replace placeholder with an error message (never blank silent panel)."""
        try:
            self.canvas_ph.content = ft.Column(
                [
                    ft.Icon(ft.Icons.BROKEN_IMAGE_OUTLINED, size=40, color="#e57373"),
                    ft.Text(
                        msg,
                        size=FONT_SM,
                        color="#e57373",
                        text_align=ft.TextAlign.CENTER,
                        max_lines=4,
                    ),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=8,
                tight=True,
            )
            self.canvas_ph.visible = True
            self.canvas_src.visible = False
            self.canvas_overlay.visible = False
            self._rebuild_canvas_stack()
        except Exception:
            pass

    def _rebuild_canvas_stack(self) -> None:
        """Keep Stack order: placeholder, source still, committed overlay, live canvas."""
        try:
            self.canvas_stack.controls = [
                self.canvas_ph,
                self.canvas_src,
                self.canvas_overlay,
                self.live_canvas,
            ]
            self.gesture.content = self.canvas_stack
        except Exception:
            pass

    def _make_canvas_image(self, src: str, *, opacity: float = 1.0) -> ft.Image:
        """Fresh Image control so Flet always repaints local files.

        FILL: source/overlay PNGs are already letterboxed to _CANVAS×_CANVAS
        so pointer coords map 1:1 to the bake buffer (no second CONTAIN scale).
        """
        return ft.Image(
            src=src,
            width=_CANVAS,
            height=_CANVAS,
            fit=ft.BoxFit.FILL,
            visible=True,
            gapless_playback=False,
            opacity=opacity,
        )

    def _load_still(self, path: str, *, status: str | None = None) -> bool:
        try:
            p = Path(path)
            if not p.is_file():
                self.status.value = f"Missing: {path}"
                self.status.color = "#e57373"
                self._show_canvas_error("Could not load still — file missing")
                return False
            resolved = str(p.resolve())
            # EXIF-transpose so PIL size matches what fal typically decodes
            with Image.open(p) as raw:
                im = ImageOps.exif_transpose(raw)
                if im is None:
                    im = raw.copy()
                im = im.convert("RGB")
        except Exception as exc:
            self.status.value = f"Load failed: {exc}"
            self.status.color = "#e57373"
            self._show_canvas_error(f"Could not load still: {exc}")
            self.source_path = None
            self._mask_full = None
            self._src_size = None
            self._view_rect = None
            self._src_display = None
            self._src_export_path = None
            return False

        # Fit CONTAIN into canvas, letterbox on dark ground (aspect preserved)
        try:
            sw, sh = im.size
            self._src_size = (int(sw), int(sh))
            # Full-res mask for fal — exact source pixel size (1:1 with export)
            self._mask_full = Image.new("L", (int(sw), int(sh)), 0)

            stamp = int(time.time() * 1000)
            # Normalized full-res PNG for fal upload (no EXIF orientation surprises)
            export_path = self._tmp_dir / f"src_export_{sw}x{sh}_{stamp}.png"
            im.save(export_path, format="PNG")
            self._src_export_path = str(export_path.resolve())

            im_fit = im.copy()
            im_fit.thumbnail((_CANVAS, _CANVAS), Image.Resampling.LANCZOS)
            dw, dh = im_fit.size
            ox = (_CANVAS - dw) // 2
            oy = (_CANVAS - dh) // 2
            self._view_rect = (int(ox), int(oy), int(dw), int(dh))

            canvas = Image.new("RGB", (_CANVAS, _CANVAS), (17, 19, 24))
            canvas.paste(im_fit, (ox, oy))
            self._src_display = canvas
            self._undo_stack = []
            self.source_path = resolved
            # Reset viewport to fit whole image
            self._zoom = _ZOOM_MIN
            self._view_ox = 0.0
            self._view_oy = 0.0
            self._pan_mode = False
            self._panning = False
            self._update_zoom_label()
            try:
                self.btn_pan.style = ft.ButtonStyle(
                    color=TEXT, side=ft.BorderSide(1, BORDER)
                )
            except Exception:
                pass
            try:
                self.live_canvas.shapes = []
            except Exception:
                pass

            # Unique files — never append ?query to local paths (breaks Flet Image)
            src_path = self._tmp_dir / f"src_display_{stamp}.png"
            canvas.save(src_path, format="PNG")
            self._src_file = src_path

            # Rebuild Image controls (reliable paint vs mutating empty src)
            # FILL: display PNG is already letterboxed to full canvas
            self.canvas_src = self._make_canvas_image(str(src_path.resolve()))
            self.canvas_overlay = self._make_canvas_image("", opacity=0.55)
            self.canvas_overlay.visible = False
            self.canvas_ph.visible = False
            # Restore default placeholder content for next clear
            self.canvas_ph.content = ft.Column(
                [
                    ft.Icon(ft.Icons.BRUSH, size=40, color=TEXT_MUTED),
                    ft.Text(
                        "Upload a still, then paint the region to change",
                        size=FONT_SM,
                        color=TEXT_MUTED,
                        text_align=ft.TextAlign.CENTER,
                    ),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=8,
                tight=True,
            )
            self._rebuild_canvas_stack()

            # Left thumb (separate file)
            thumb = canvas.copy()
            thumb.thumbnail((_SOURCE_THUMB, _SOURCE_THUMB), Image.Resampling.LANCZOS)
            tpath = self._tmp_dir / f"src_thumb_{stamp}.png"
            thumb.save(tpath, format="PNG")
            self.src_thumb.src = str(tpath.resolve())
            self.src_thumb.visible = True
            self.src_thumb_ph.visible = False
            # Prune old exports
            try:
                for old in self._tmp_dir.glob("src_export_*.png"):
                    if old.resolve() != export_path.resolve() and (
                        old.stat().st_mtime < time.time() - 600
                    ):
                        old.unlink(missing_ok=True)
            except OSError:
                pass
        except Exception as exc:
            self.status.value = f"Could not load still: {exc}"
            self.status.color = "#e57373"
            self._show_canvas_error(f"Could not load still: {exc}")
            self.source_path = None
            self._mask_full = None
            self._src_size = None
            self._view_rect = None
            self._src_display = None
            self._src_export_path = None
            return False

        # Clear mask overlay (still visible underneath)
        self._write_overlay(force=True)
        try:
            self.prev_strip.record_and_refresh(resolved)
        except Exception:
            pass
        sw, sh = self._src_size or (0, 0)
        self.status.value = status or (
            f"Source: {Path(resolved).name} · {sw}×{sh} — paint mask"
        )
        self.status.color = TEXT_MUTED
        try:
            self.page.update()
        except Exception:
            pass
        return True

    def _reset_mask_state(self) -> None:
        self._mask_full = None
        self._src_size = None
        self._view_rect = None
        self._src_display = None
        self._src_export_path = None
        self.source_path = None
        self._zoom = _ZOOM_MIN
        self._view_ox = 0.0
        self._view_oy = 0.0
        self._pan_mode = False
        self._panning = False
        self._update_zoom_label()
        self.canvas_src.visible = False
        self.canvas_overlay.visible = False
        self.canvas_ph.visible = True
        self.src_thumb.visible = False
        self.src_thumb_ph.visible = True
        try:
            self.canvas_ph.content = ft.Column(
                [
                    ft.Icon(ft.Icons.BRUSH, size=40, color=TEXT_MUTED),
                    ft.Text(
                        "Upload a still, then paint the region to change",
                        size=FONT_SM,
                        color=TEXT_MUTED,
                        text_align=ft.TextAlign.CENTER,
                    ),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=8,
                tight=True,
            )
            self._rebuild_canvas_stack()
        except Exception:
            pass

    def _set_tool(self, mode: str) -> None:
        self._tool = mode if mode in ("brush", "eraser") else "brush"
        # Leaving pan when picking brush/eraser
        if self._pan_mode:
            self._pan_mode = False
            try:
                self.btn_pan.style = ft.ButtonStyle(
                    color=TEXT, side=ft.BorderSide(1, BORDER)
                )
            except Exception:
                pass
        try:
            if self._tool == "brush":
                self.btn_brush.style = ft.ButtonStyle(
                    bgcolor=ACCENT_BRIGHT, color=TEXT
                )
                self.btn_eraser.style = ft.ButtonStyle(
                    color=TEXT, side=ft.BorderSide(1, BORDER)
                )
                self.canvas_caption.value = (
                    "Brush · red = edit region · screen-px brush · "
                    f"zoom {int(round(self._zoom * 100))}%"
                )
            else:
                self.btn_eraser.style = ft.ButtonStyle(bgcolor=ACCENT, color=TEXT)
                self.btn_brush.style = ft.ButtonStyle(
                    color=TEXT, side=ft.BorderSide(1, BORDER)
                )
                self.canvas_caption.value = (
                    "Eraser · clears mask · screen-px · "
                    f"zoom {int(round(self._zoom * 100))}%"
                )
            self.page.update()
        except Exception:
            pass

    def _on_brush(self, e: ft.ControlEvent) -> None:
        try:
            self._brush = int(float(self.brush_slider.value or 22))
        except (TypeError, ValueError):
            self._brush = 22

    def _on_grow(self, e: ft.ControlEvent) -> None:
        raw = _dd_value(self.grow_dd) or _GROW_DEFAULT
        try:
            self._grow_px = int(raw)
        except (TypeError, ValueError):
            self._grow_px = int(_GROW_DEFAULT)
        if self._grow_px not in (0, 2, 4, 8):
            self._grow_px = int(_GROW_DEFAULT)
        try:
            self.page.update()
        except Exception:
            pass

    def _grow_mask_export(self, mask: Image.Image, grow: int) -> Image.Image:
        """
        Dilate white edit region by ``grow`` full-res pixels (export only).

        Uses MaxFilter so edges stay hard (no soft blur). Output size unchanged.
        """
        if grow <= 0:
            return mask
        # MaxFilter size must be odd; radius ≈ grow
        size = int(grow) * 2 + 1
        # PIL MaxFilter max size is typically large enough for 8→17
        out = mask.filter(ImageFilter.MaxFilter(size))
        # Hard binary for fal fill
        return out.point(lambda v: 255 if v > 16 else 0)

    async def _on_intent(self, e: ft.ControlEvent) -> None:
        key = _dd_value(self.intent_dd) or _INTENT_NONE
        scaffold = _INTENT_SCAFFOLDS.get(key, "")
        if not scaffold:
            # Custom — leave prompt alone
            try:
                self.page.update()
            except Exception:
                pass
            return
        cur = (self.prompt.value or "").strip()
        # Replace if empty or still looks like a previous scaffold
        stockish = (
            not cur
            or cur in _INTENT_SCAFFOLDS.values()
            or any(
                cur.startswith(s[:40])
                for s in _INTENT_SCAFFOLDS.values()
                if s
            )
        )
        if stockish:
            self.prompt.value = scaffold
            self.status.value = f"Intent: {key} — edit the [brackets] as needed."
            self.status.color = TEXT_MUTED
        else:
            self.status.value = (
                f"Prompt looks custom — intent “{key}” not applied. "
                "Clear prompt or pick intent first."
            )
            self.status.color = TEXT_MUTED
        try:
            self.page.update()
        except Exception:
            pass

    def _push_undo(self) -> None:
        if self._mask_full is None:
            return
        try:
            self._undo_stack.append(self._mask_full.copy())
            if len(self._undo_stack) > 24:
                self._undo_stack = self._undo_stack[-24:]
        except Exception:
            pass

    def _paint_at(self, x: float, y: float, *, live: bool = False) -> None:
        """Paint in full-res mask; live preview uses canvas coords."""
        if self._mask_full is None:
            return
        mapped = self._canvas_to_full(x, y)
        if mapped is None:
            # Still show live feedback at canvas point when near edge
            if live:
                r = max(2, self._brush // 2)
                paint = (
                    self._eraser_paint if self._tool == "eraser" else self._brush_paint
                )
                self.live_canvas.shapes.append(
                    ftc.Circle(x=x, y=y, radius=float(r), paint=paint)
                )
            return
        fx, fy, scale = mapped
        draw = ImageDraw.Draw(self._mask_full)
        r_full = max(1.0, (self._brush * 0.5) * scale)
        fill = 0 if self._tool == "eraser" else 255
        draw.ellipse(
            (fx - r_full, fy - r_full, fx + r_full, fy + r_full), fill=fill
        )
        if live:
            r = max(2, self._brush // 2)
            paint = self._eraser_paint if self._tool == "eraser" else self._brush_paint
            self.live_canvas.shapes.append(
                ftc.Circle(x=x, y=y, radius=float(r), paint=paint)
            )

    def _paint_line(
        self, x0: float, y0: float, x1: float, y1: float, *, live: bool = False
    ) -> None:
        if self._mask_full is None:
            return
        m0 = self._canvas_to_full(x0, y0)
        m1 = self._canvas_to_full(x1, y1)
        if m0 is not None and m1 is not None:
            fx0, fy0, scale = m0
            fx1, fy1, _ = m1
            draw = ImageDraw.Draw(self._mask_full)
            fill = 0 if self._tool == "eraser" else 255
            w_full = max(2.0, float(self._brush) * scale)
            draw.line((fx0, fy0, fx1, fy1), fill=fill, width=int(round(w_full)))
            r_full = w_full * 0.5
            draw.ellipse(
                (fx1 - r_full, fy1 - r_full, fx1 + r_full, fy1 + r_full), fill=fill
            )
        elif m1 is not None:
            # Start outside, end inside
            self._paint_at(x1, y1, live=False)
        if live:
            paint = self._eraser_paint if self._tool == "eraser" else self._brush_paint
            w = max(2, self._brush)
            r = w // 2
            try:
                self.live_canvas.shapes.append(
                    ftc.Line(
                        x1=x0,
                        y1=y0,
                        x2=x1,
                        y2=y1,
                        paint=ft.Paint(
                            color=paint.color,
                            stroke_width=float(w),
                            style=ft.PaintingStyle.STROKE,
                            stroke_cap=ft.StrokeCap.ROUND,
                            stroke_join=ft.StrokeJoin.ROUND,
                        ),
                    )
                )
            except Exception:
                pass
            self.live_canvas.shapes.append(
                ftc.Circle(x=x1, y=y1, radius=float(r), paint=paint)
            )

    def _flush_live_canvas(self) -> None:
        """Update only the live stroke canvas (instant path)."""
        try:
            self.live_canvas.update()
        except Exception:
            try:
                self.page.update()
            except Exception:
                pass

    def _write_overlay(self, *, force: bool = False) -> None:
        """
        Bake full-res mask → viewport preview (letterbox + current zoom/pan).

        Preview only — fal export uses full-res mask via _export_mask_file.
        Grow dilation is export-only and is NOT shown here.
        """
        if (
            self._mask_full is None
            or self._src_display is None
            or self._view_rect is None
        ):
            return
        try:
            lox, loy, dw, dh = self._view_rect
            # Full-res → base letterbox with NEAREST (hard edges)
            preview = self._mask_full.resize((dw, dh), Image.Resampling.NEAREST)
            base_mask = Image.new("L", (_CANVAS, _CANVAS), 0)
            base_mask.paste(preview, (lox, loy))
            # Crop base to current viewport and upscale (same as source view)
            self._clamp_view()
            z = max(float(self._zoom), 0.01)
            vw = max(1.0, float(_CANVAS) / z)
            vh = max(1.0, float(_CANVAS) / z)
            ox = float(self._view_ox)
            oy = float(self._view_oy)
            x0 = max(0.0, min(float(_CANVAS) - 1.0, ox))
            y0 = max(0.0, min(float(_CANVAS) - 1.0, oy))
            x1 = max(x0 + 1.0, min(float(_CANVAS), ox + vw))
            y1 = max(y0 + 1.0, min(float(_CANVAS), oy + vh))
            crop = base_mask.crop(
                (int(x0), int(y0), int(round(x1)), int(round(y1)))
            )
            view_mask = crop.resize((_CANVAS, _CANVAS), Image.Resampling.NEAREST)
            gray = view_mask.point(lambda v: 150 if v > 16 else 0)
            rgba = Image.merge(
                "RGBA",
                (
                    Image.new("L", gray.size, 230),
                    Image.new("L", gray.size, 55),
                    Image.new("L", gray.size, 55),
                    gray,
                ),
            )
            path = self._tmp_dir / f"mask_commit_{int(time.time() * 1000)}.png"
            rgba.save(path, format="PNG")
            self._overlay_file = path
            abs_path = str(path.resolve())
            try:
                has_paint = False
                ext = self._mask_full.getextrema()
                has_paint = bool(ext and ext[1] > 16)
            except Exception:
                has_paint = True
            if has_paint:
                try:
                    self.canvas_overlay.src = abs_path
                    self.canvas_overlay.visible = True
                    self.canvas_overlay.update()
                except Exception:
                    self.canvas_overlay = self._make_canvas_image(
                        abs_path, opacity=0.55
                    )
                    self._rebuild_canvas_stack()
                    try:
                        self.page.update()
                    except Exception:
                        pass
            else:
                self.canvas_overlay.visible = False
                try:
                    self.canvas_overlay.update()
                except Exception:
                    try:
                        self.page.update()
                    except Exception:
                        pass
            try:
                for old in self._tmp_dir.glob("mask_commit_*.png"):
                    if old != path and old.stat().st_mtime < time.time() - 120:
                        old.unlink(missing_ok=True)
            except OSError:
                pass
        except Exception:
            pass

    async def _clear_mask(self, _e: ft.ControlEvent) -> None:
        if self._mask_full is None or self._src_display is None or not self._src_size:
            return
        self._push_undo()
        sw, sh = self._src_size
        self._mask_full = Image.new("L", (sw, sh), 0)
        self.live_canvas.shapes = []
        self._flush_live_canvas()
        # Clear committed overlay only — source still stays visible
        try:
            self.canvas_overlay.visible = False
            self.canvas_overlay.src = ""
            self.canvas_overlay.update()
        except Exception:
            self._write_overlay(force=True)
        self.status.value = "Mask cleared (source still kept)."
        try:
            self.page.update()
        except Exception:
            pass

    async def _undo_mask(self, _e: ft.ControlEvent) -> None:
        if not self._undo_stack:
            self.status.value = "Nothing to undo."
            try:
                self.page.update()
            except Exception:
                pass
            return
        self._mask_full = self._undo_stack.pop()
        self.live_canvas.shapes = []
        self._flush_live_canvas()
        self._write_overlay(force=True)
        self.status.value = "Undo."
        try:
            self.page.update()
        except Exception:
            pass

    async def _pick_source(self, e: ft.ControlEvent) -> None:
        try:
            files = await pick_image(self.page, dialog_title="Inpaint source still")
        except Exception as exc:
            self.status.value = f"Picker error: {exc}"
            self.page.update()
            return
        if not files or not files[0].path:
            return
        self._load_still(files[0].path)
        self.page.update()

    async def _refresh_cost(self, e: ft.ControlEvent) -> None:
        self._sync_model_ui()
        try:
            self.page.update()
        except Exception:
            pass

    async def _pick_ref(self, e: ft.ControlEvent) -> None:
        try:
            files = await pick_image(self.page, dialog_title="Inpaint reference still")
        except Exception as exc:
            self.status.value = f"Picker error: {exc}"
            self.page.update()
            return
        if not files or not files[0].path:
            return
        self._set_ref(files[0].path)
        self.page.update()

    def _on_ref_prev(self, path: str) -> None:
        self._set_ref(path, status=f"Ref: {Path(path).name}")
        try:
            self.page.update()
        except Exception:
            pass

    def _set_ref(self, path: str, *, status: str | None = None) -> None:
        try:
            p = Path(path)
            if not p.is_file():
                self.status.value = f"Missing ref: {path}"
                self.status.color = "#e57373"
                return
            resolved = str(p.resolve())
            self.ref_path = resolved
            self.ref_thumb.src = resolved
            self.ref_thumb.visible = True
            self.ref_thumb_ph.visible = False
            self.btn_clear_ref.visible = True
            try:
                self.ref_prev_strip.record_and_refresh(resolved)
            except Exception:
                pass
            self.status.value = status or f"Reference {Path(resolved).name}"
            self.status.color = TEXT_MUTED
        except Exception as exc:
            self.status.value = f"Ref load failed: {exc}"
            self.status.color = "#e57373"

    async def _clear_ref(self, _e: ft.ControlEvent) -> None:
        self.ref_path = None
        self.ref_thumb.src = ""
        self.ref_thumb.visible = False
        self.ref_thumb_ph.visible = True
        self.btn_clear_ref.visible = False
        self.status.value = "Reference cleared."
        self.status.color = TEXT_MUTED
        try:
            self.page.update()
        except Exception:
            pass

    async def _on_enhance(self, e: ft.ControlEvent) -> None:
        await run_prompt_enhance(
            page=self.page,
            state=self.state,
            prompt_field=self.prompt,
            get_model=lambda: _dd_value(self.model_dd),
            get_image=lambda: self.source_path,
            get_extra_context=lambda: {
                "workspace": "inpaint",
                "guidance": (
                    "Rewrite for masked inpaint: describe only what should appear "
                    "in the painted region; keep surrounding content locked."
                ),
            },
            status_ctrl=self.status,
            job_progress=self.job_progress,
            enhance_btn=self.btn_enhance,
            busy_controls=[self.btn],
            context_label="inpaint prompt",
            allow_empty_with_context=True,
        )
        self.apply_key_gates()
        try:
            self.page.update()
        except Exception:
            pass

    def _export_mask_file(self) -> tuple[str | None, str | None]:
        """
        Export full-res mask matching the fal source image WxH exactly.

        Uses the EXIF-normalized ``_src_export_path`` (not on-screen canvas size).
        Returns (path, error_message).
        """
        if self._mask_full is None or not self._src_size or not self.source_path:
            return None, "Paint a mask on the region to change, then Run."
        try:
            sw, sh = self._src_size
            # Guarantee size match vs in-memory source size (defensive NEAREST)
            if self._mask_full.size != (sw, sh):
                self._mask_full = self._mask_full.resize(
                    (sw, sh), Image.Resampling.NEAREST
                )

            # Canonical fal image = normalized export PNG (same pixels as mask)
            export = self._src_export_path
            if not export or not Path(export).is_file():
                # Rebuild export from original with EXIF transpose
                with Image.open(self.source_path) as raw:
                    im = ImageOps.exif_transpose(raw)
                    if im is None:
                        im = raw.copy()
                    im = im.convert("RGB")
                iw, ih = im.size
                export_path = (
                    self._tmp_dir
                    / f"src_export_{iw}x{ih}_{int(time.time() * 1000)}.png"
                )
                im.save(export_path, format="PNG")
                self._src_export_path = str(export_path.resolve())
                self._src_size = (iw, ih)
                sw, sh = iw, ih
                if self._mask_full.size != (sw, sh):
                    self._mask_full = self._mask_full.resize(
                        (sw, sh), Image.Resampling.NEAREST
                    )
            else:
                with Image.open(export) as im:
                    iw, ih = im.size

            if (sw, sh) != (iw, ih):
                # Prefer export dimensions for fal; hard resize mask NEAREST
                self._mask_full = self._mask_full.resize(
                    (iw, ih), Image.Resampling.NEAREST
                )
                self._src_size = (iw, ih)
                sw, sh = iw, ih

            if self._mask_full.size != (iw, ih):
                return None, (
                    f"Mask/image size mismatch — image {iw}×{ih}, "
                    f"mask {self._mask_full.size[0]}×{self._mask_full.size[1]}"
                )

            # Sync grow from dropdown (export-only dilation; strokes stay raw)
            try:
                raw = _dd_value(self.grow_dd) or _GROW_DEFAULT
                grow = int(raw)
            except (TypeError, ValueError):
                grow = int(self._grow_px or 0)
            if grow not in (0, 2, 4, 8):
                grow = int(_GROW_DEFAULT)
            self._grow_px = grow
            export_mask = self._mask_full.copy()
            if grow > 0:
                export_mask = self._grow_mask_export(export_mask, grow)
            # Ensure hard binary + size lock
            if export_mask.size != (iw, ih):
                export_mask = export_mask.resize(
                    (iw, ih), Image.Resampling.NEAREST
                )
            export_mask = export_mask.point(lambda v: 255 if v > 16 else 0)

            path = self._tmp_dir / f"mask_export_{sw}x{sh}_{int(time.time() * 1000)}.png"
            # Binary mask for fal: white = edit, black = keep
            export_mask.save(path, format="PNG")
            # Final assert after write (disk truth)
            with Image.open(path) as mchk:
                mw, mh = mchk.size
            if (mw, mh) != (iw, ih):
                return None, (
                    f"Mask/image size mismatch after export — "
                    f"image {iw}×{ih}, mask {mw}×{mh}"
                )
            return str(path), None
        except Exception as exc:
            return None, f"Mask export failed: {exc}"

    async def _run(self, e: ft.ControlEvent) -> None:
        if self.state.is_busy("tools"):
            return
        from media_studio.secrets_store import has_fal_key

        if not has_fal_key():
            self.status.value = "FAL API key required — open Settings."
            self.page.update()
            return
        if not self.source_path or not Path(self.source_path).is_file():
            self.status.value = "Upload a source still first."
            self.status.color = "#e57373"
            self.page.update()
            return
        spec = find_tool(_dd_value(self.model_dd), INPAINT_MODELS)
        if inpaint_requires_ref(spec):
            if not self.ref_path or not Path(self.ref_path).is_file():
                self.status.value = (
                    f"{(spec.label if spec else 'Model')} needs a reference still — "
                    "upload Ref still, then Run."
                )
                self.status.color = "#e57373"
                self.page.update()
                return
        # Flush live stroke into full-res mask; export 1:1 with fal source
        self._write_overlay(force=True)
        mask_path, mask_err = self._export_mask_file()
        # Prefer EXIF-normalized export for fal (same WxH as mask)
        image_for_fal = self._src_export_path or self.source_path
        if not mask_path:
            # Include sizes when known for debugging fal mismatches
            iw = ih = mw = mh = 0
            try:
                src_chk = image_for_fal or self.source_path
                if src_chk and Path(src_chk).is_file():
                    with Image.open(src_chk) as im:
                        iw, ih = im.size
            except Exception:
                pass
            if self._mask_full is not None:
                mw, mh = self._mask_full.size
            detail = mask_err or "Paint a mask on the region to change, then Run."
            self.status.value = f"{detail} · image {iw}×{ih}, mask {mw}×{mh}"
            self.status.color = "#e57373"
            self.page.update()
            return

        # Pre-submit assert: never send mismatched shapes
        try:
            with Image.open(image_for_fal) as im:
                iw, ih = im.size
            with Image.open(mask_path) as mm:
                mw, mh = mm.size
            size_note = f"image {iw}×{ih}, mask {mw}×{mh}"
            if (iw, ih) != (mw, mh):
                self.status.value = (
                    f"Mask/image size mismatch — will not submit. {size_note}"
                )
                self.status.color = "#e57373"
                self.page.update()
                return
        except Exception as exc:
            size_note = ""
            self.status.value = f"Could not verify image/mask sizes: {exc}"
            self.status.color = "#e57373"
            self.page.update()
            return

        if not self.state.try_busy("tools"):
            return
        self.btn.disabled = True
        grow = int(self._grow_px or 0)
        self.job_progress.start("Running inpaint…", self.page)
        grow_note = f", grow {grow}px" if grow else ", grow 0"
        self.status.value = f"Inpaint running… ({size_note}{grow_note})"
        self.status.color = TEXT_MUTED
        self.page.update()

        def on_progress(msg: str) -> None:
            self.job_progress.set_message(classify_progress(msg), self.page)

        try:
            from media_studio.job_context import to_thread_with_job

            strength = None
            if self.strength.visible:
                try:
                    strength = float(self.strength.value or 0.85)
                except (TypeError, ValueError):
                    strength = 0.85
            ref_for_run = None
            if inpaint_shows_ref(spec) and self.ref_path and Path(self.ref_path).is_file():
                ref_for_run = self.ref_path
            result = await to_thread_with_job(
                self.state,
                run_inpaint,
                image_path=image_for_fal,
                mask_path=mask_path,
                prompt=self.prompt.value,
                negative_prompt=self.negative.value,
                model_label=_dd_value(self.model_dd),
                strength=strength,
                num_images=self._num_images(),
                reference_path=ref_for_run,
                output_dir=self.state.output_dir,
                on_progress=on_progress,
            )
            self.cost_text.value = result.cost_label or self._cost()
            if result.ok and result.path:
                self._result_path = result.path
                self._result_paths = list(getattr(result, "paths", None) or [result.path])
                self.job_progress.finish_ok(result.status or "OK", self.page)
                self.status.value = result.status or "OK"
                self.status.color = TEXT_MUTED
                if callable(self.on_result):
                    # Show first still in result pane; all paths in Library via history
                    try:
                        self.on_result(
                            self.source_path,
                            result.path,
                            tool_label=self.tool_label,
                        )
                    except TypeError:
                        try:
                            self.on_result(self.source_path, result.path)
                        except Exception:
                            pass
                    except Exception:
                        pass
            else:
                err = result.status or "Inpaint failed."
                low = err.lower()
                if "size" in low or "dimension" in low or "match" in low:
                    err = f"{err} · {size_note}"
                self.job_progress.finish_error(err, self.page)
                self.status.value = err
                self.status.color = "#e57373"
        except Exception as exc:
            msg = str(exc)
            low = msg.lower()
            if "size" in low or "dimension" in low or "match" in low:
                msg = f"{msg} · {size_note}"
            self.job_progress.finish_error(msg, self.page)
            self.status.value = f"Error: {msg}"
            self.status.color = "#e57373"
        finally:
            self.state.clear_busy("tools")
            self.apply_key_gates()
            self.page.update()
