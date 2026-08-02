"""
Region edit UI — lightweight Stack overlays (instant) + export composite (Generate only).

Slider / drag updates only reposition Flet Containers. PIL annotation is deferred
to export_annotated_path() for Generate / Enhance upload.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import flet as ft

from media_studio.flet_theme import (
    ACCENT,
    ACCENT_BRIGHT,
    BORDER,
    FONT_SM,
    PANEL_ELEVATED,
    TEXT,
    TEXT_MUTED,
    label,
    section_title,
)
from media_studio.region_edit import (
    MAX_REGIONS,
    RegionBox,
    analyze_box_conflicts,
    build_region_prompt,
    draw_region_overlay,
    live_preview_path,
    make_box,
)


def _hex_to_rgba(hex_c: str, alpha: float) -> str:
    """Flet accepts #RRGGBB or #AARRGGBB."""
    h = (hex_c or "#E53935").lstrip("#")
    if len(h) != 6:
        h = "E53935"
    a = max(0, min(255, int(alpha * 255)))
    return f"#{a:02X}{h.upper()}"


def contain_content_rect(
    stack_w: float,
    stack_h: float,
    img_w: float,
    img_h: float,
) -> tuple[float, float, float, float]:
    """
    Letterbox rect for BoxFit.CONTAIN: (offset_x, offset_y, content_w, content_h).

    Single coordinate system for all region overlays: box L/T/W/H are fractions
    of this *image content* rectangle (not the letterboxed panel outer bounds).
    """
    sw, sh = max(float(stack_w), 1.0), max(float(stack_h), 1.0)
    iw, ih = float(img_w or 0), float(img_h or 0)
    if iw <= 0 or ih <= 0:
        return 0.0, 0.0, sw, sh
    scale = min(sw / iw, sh / ih)
    dw, dh = iw * scale, ih * scale
    ox = (sw - dw) / 2.0
    oy = (sh - dh) / 2.0
    return ox, oy, max(dw, 1.0), max(dh, 1.0)


def size_from_layout_event(e: Any) -> tuple[float, float]:
    """Extract (w, h) from LayoutSizeChangeEvent / ControlEvent / dict-like."""
    w = h = 0.0
    try:
        w = float(getattr(e, "width", None) or 0)
        h = float(getattr(e, "height", None) or 0)
    except (TypeError, ValueError):
        w = h = 0.0
    if w > 1 and h > 1:
        return w, h
    # Some Flet builds put size on e.data
    data = getattr(e, "data", None)
    if isinstance(data, str) and "," in data:
        try:
            parts = data.replace(" ", "").split(",")
            w, h = float(parts[0]), float(parts[1])
            if w > 1 and h > 1:
                return w, h
        except (TypeError, ValueError, IndexError):
            pass
    if isinstance(data, dict):
        try:
            w = float(data.get("width") or data.get("w") or 0)
            h = float(data.get("height") or data.get("h") or 0)
            if w > 1 and h > 1:
                return w, h
        except (TypeError, ValueError):
            pass
    ctrl = getattr(e, "control", None)
    if ctrl is not None:
        try:
            w = float(getattr(ctrl, "width", None) or 0)
            h = float(getattr(ctrl, "height", None) or 0)
            if w > 1 and h > 1:
                return w, h
        except (TypeError, ValueError):
            pass
    return 0.0, 0.0


class RegionBoxOverlay:
    """
    Lightweight colored rectangles in a Stack.

    Image previews use BoxFit.CONTAIN. Box L/T/W/H are normalized 0–1 of the
    *image content* area. The host is sized/positioned only to that content_rect
    (ox, oy, dw, dh) — never a full-stage pin over letterbox + image (full-panel
    transparent Containers can composite a grey veil on Flet desktop).

    Call set_stack_size() with the **panel** pixel size matching the CONTAIN
    image parent; set_image_size() with natural still WxH.
    """

    def __init__(
        self,
        *,
        on_select: Callable[[int], None] | None = None,
        on_geometry: Callable[[], None] | None = None,
        interactive: bool = True,
    ) -> None:
        self.on_select = on_select
        self.on_geometry = on_geometry
        self.interactive = interactive
        self._boxes: list[RegionBox] = []
        self._selected = 0
        self._stack_w: float = 400.0  # panel W
        self._stack_h: float = 300.0  # panel H
        self._img_w: float = 0.0
        self._img_h: float = 0.0
        self._drag_mode: str | None = None  # move | resize
        self._drag_index: int = -1
        self._host = ft.Stack(
            controls=[],
            fit=ft.StackFit.EXPAND,
        )
        # Content-rect only — NOT full-stage left/top/right/bottom pin
        self.root = ft.Container(
            content=self._host,
            left=0,
            top=0,
            width=100,
            height=100,
            expand=False,
            bgcolor=None,  # no paint; avoid TRANSPARENT full-layer scrims
            clip_behavior=ft.ClipBehavior.NONE,
            visible=False,
            opacity=1.0,
        )
        self._layout_host_to_content()

    def set_visible(self, visible: bool) -> None:
        self.root.visible = bool(visible)
        if visible:
            self._layout_host_to_content()

    def set_stack_size(self, w: float, h: float, *, reflow: bool = False) -> None:
        """Set *panel* size for CONTAIN letterbox math (must match image host)."""
        if w > 1 and h > 1:
            changed = abs(self._stack_w - float(w)) > 0.5 or abs(
                self._stack_h - float(h)
            ) > 0.5
            self._stack_w = float(w)
            self._stack_h = float(h)
            self._layout_host_to_content()
            if reflow and changed and self._boxes:
                self.sync(self._boxes, self._selected, full_rebuild=False)

    def set_image_size(self, img_w: float, img_h: float) -> None:
        """Natural pixel size of the source still (for CONTAIN letterboxing)."""
        self._img_w = float(img_w or 0)
        self._img_h = float(img_h or 0)
        self._layout_host_to_content()

    def content_rect(self) -> tuple[float, float, float, float]:
        return contain_content_rect(
            self._stack_w, self._stack_h, self._img_w, self._img_h
        )

    def stack_size(self) -> tuple[float, float]:
        return self._stack_w, self._stack_h

    def _layout_host_to_content(self) -> None:
        """
        Position/size root to the image content_rect only.

        Boxes are laid out in host-local coordinates (0..dw, 0..dh). Letterbox
        areas of the panel are not covered by this host — no full-stage veil.
        """
        ox, oy, dw, dh = self.content_rect()
        try:
            self.root.left = float(ox)
            self.root.top = float(oy)
            self.root.width = max(1.0, float(dw))
            self.root.height = max(1.0, float(dh))
            self.root.right = None
            self.root.bottom = None
            self.root.expand = False
            self.root.bgcolor = None
            self._host.width = max(1.0, float(dw))
            self._host.height = max(1.0, float(dh))
        except Exception:
            pass

    def sync(
        self,
        boxes: list[RegionBox],
        selected: int,
        *,
        full_rebuild: bool = False,
    ) -> None:
        """Update overlay geometry. Prefer in-place updates when box count unchanged."""
        self._boxes = boxes
        self._selected = max(0, selected) if boxes else 0
        self._layout_host_to_content()
        if full_rebuild or len(self._host.controls) != len(boxes):
            self._rebuild_controls()
        else:
            self._apply_geometry_only()

    def _rebuild_controls(self) -> None:
        controls: list[ft.Control] = []
        for i, b in enumerate(self._boxes):
            controls.append(self._make_box_control(i, b))
        self._host.controls = controls

    def _face_of(self, ctrl: ft.Control) -> ft.Container | None:
        """Inner visual container (colors/border)."""
        if isinstance(ctrl, ft.Container):
            # Positioned shell: content is GestureDetector or face itself
            if isinstance(ctrl.content, ft.GestureDetector) and isinstance(
                ctrl.content.content, ft.Container
            ):
                return ctrl.content.content
            if isinstance(ctrl.content, ft.Container):
                return ctrl.content
            return ctrl
        return None

    def _shell_of(self, ctrl: ft.Control) -> ft.Container | None:
        """Stack-positioned outer container (left/top/width/height)."""
        return ctrl if isinstance(ctrl, ft.Container) else None

    def _place(self, shell: ft.Container, b: RegionBox) -> None:
        """Map normalized box into host-local coords (host = content_rect)."""
        b.clamp()
        _ox, _oy, dw, dh = self.content_rect()
        # Host is already at (ox,oy); boxes are fractions of content only
        shell.left = b.left * dw
        shell.top = b.top * dh
        shell.width = max(12.0, b.width * dw)
        shell.height = max(12.0, b.height * dh)

    def _style_face(self, face: ft.Container, b: RegionBox, *, selected: bool) -> None:
        # Light fill only on the box — never a full-stage wash
        face.bgcolor = _hex_to_rgba(b.color_hex, 0.28 if selected else 0.16)
        face.border = ft.Border.all(3 if selected else 2, b.color_hex)
        try:
            if isinstance(face.content, ft.Container) and isinstance(
                face.content.content, ft.Text
            ):
                face.content.content.value = b.color_name.upper() + (
                    " ★" if selected else ""
                )
                face.content.bgcolor = _hex_to_rgba(b.color_hex, 0.9)
        except Exception:
            pass

    def _apply_geometry_only(self) -> None:
        for i, b in enumerate(self._boxes):
            if i >= len(self._host.controls):
                break
            shell = self._shell_of(self._host.controls[i])
            face = self._face_of(self._host.controls[i])
            if shell is None:
                continue
            selected = i == self._selected
            self._place(shell, b)
            if face is not None:
                self._style_face(face, b, selected=selected)

    def _make_box_control(self, index: int, b: RegionBox) -> ft.Control:
        is_sel = index == self._selected
        face = ft.Container(
            expand=True,
            bgcolor=_hex_to_rgba(b.color_hex, 0.28 if is_sel else 0.16),
            border=ft.Border.all(3 if is_sel else 2, b.color_hex),
            border_radius=2,
            content=ft.Container(
                content=ft.Text(
                    b.color_name.upper() + (" ★" if is_sel else ""),
                    size=11,
                    color=TEXT,
                    weight=ft.FontWeight.W_700,
                ),
                bgcolor=_hex_to_rgba(b.color_hex, 0.9),
                padding=ft.Padding.symmetric(horizontal=4, vertical=1),
                alignment=ft.Alignment(-1, -1),
            ),
            data=f"box:{index}",
        )
        # Shell: no fill — only the face paints (host is content-rect sized)
        shell = ft.Container(data=f"shell:{index}", bgcolor=None)
        self._place(shell, b)

        if not self.interactive:
            shell.content = face
            return shell

        def _on_tap(_e: ft.ControlEvent, *, idx: int = index) -> None:
            if self.on_select:
                self.on_select(idx)

        def _on_pan_start(_e: ft.DragStartEvent, *, idx: int = index) -> None:
            self._drag_index = idx
            self._drag_mode = "move"
            if self.on_select:
                self.on_select(idx)

        def _on_pan_update(e: ft.DragUpdateEvent, *, idx: int = index) -> None:
            if idx < 0 or idx >= len(self._boxes):
                return
            box_data = self._boxes[idx]
            _ox, _oy, dw, dh = self.content_rect()
            dw, dh = max(dw, 1.0), max(dh, 1.0)
            dx = dy = 0.0
            for attr in ("local_delta", "global_delta", "delta"):
                d = getattr(e, attr, None)
                if d is not None:
                    try:
                        dx = float(getattr(d, "x", 0) or 0)
                        dy = float(getattr(d, "y", 0) or 0)
                        if dx or dy:
                            break
                    except Exception:
                        pass
            if dx == 0 and dy == 0:
                dx = float(getattr(e, "delta_x", 0) or 0)
                dy = float(getattr(e, "delta_y", 0) or 0)
            # Delta relative to image content area (not full letterboxed panel)
            box_data.left += dx / dw
            box_data.top += dy / dh
            box_data.clamp()
            self._place(shell, box_data)
            self._style_face(face, box_data, selected=(idx == self._selected))
            if self.on_geometry:
                self.on_geometry()

        def _on_pan_end(_e: ft.DragEndEvent) -> None:
            self._drag_mode = None
            self._drag_index = -1

        shell.content = ft.GestureDetector(
            content=face,
            on_tap=_on_tap,
            on_pan_start=_on_pan_start,
            on_pan_update=_on_pan_update,
            on_pan_end=_on_pan_end,
            drag_interval=0,
            mouse_cursor=ft.MouseCursor.MOVE,
        )
        return shell


class RegionEditorPanel:
    """
    Still-only region editor controls (list, sliders, mini preview).

    Expensive annotated export is only via export_annotated_path().
    """

    def __init__(
        self,
        page: ft.Page,
        *,
        on_change: Callable[[], None] | None = None,
        on_geometry: Callable[[], None] | None = None,
    ) -> None:
        self.page = page
        self.on_change = on_change
        # Geometry-only (sliders/drag) — parent refreshes lightweight overlays
        self.on_geometry = on_geometry
        self.boxes: list[RegionBox] = []
        self._selected = 0
        self._source_path: str | None = None
        self._output_dir: str | None = None
        self._img_w: int = 0
        self._img_h: int = 0

        # Mini preview: CONTAIN (correct aspect) + letterbox-aware overlay
        self.mini_image = ft.Image(
            src="",
            fit=ft.BoxFit.CONTAIN,
            width=280,
            height=180,
            visible=False,
            gapless_playback=True,
        )
        self.mini_overlay = RegionBoxOverlay(
            on_select=self._select_index,
            on_geometry=self._on_drag_geometry,
            interactive=True,
        )
        # Panel = mini preview size; host lays out to content_rect only
        self.mini_overlay.set_stack_size(280, 180)
        self.preview_placeholder = ft.Container(
            content=ft.Text(
                "Upload a still to place region boxes",
                color=TEXT_MUTED,
                size=FONT_SM,
                text_align=ft.TextAlign.CENTER,
            ),
            alignment=ft.Alignment.CENTER,
            width=280,
            height=180,
            bgcolor=PANEL_ELEVATED,
            border_radius=6,
            border=ft.Border.all(1, BORDER),
        )
        self.mini_stack = ft.Stack(
            [
                self.preview_placeholder,
                self.mini_image,
                self.mini_overlay.root,
            ],
            width=280,
            height=180,
        )

        self.box_list = ft.Column(spacing=6)
        self.conflict_text = ft.Text(
            "",
            size=FONT_SM,
            color="#ffb74d",
            max_lines=4,
            selectable=True,
        )
        self.btn_add = ft.OutlinedButton(
            content="Add box",
            icon=ft.Icons.CROP_FREE,
            on_click=self._on_add,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
        )
        self.btn_clear = ft.TextButton(
            content="Clear boxes",
            on_click=self._on_clear,
            style=ft.ButtonStyle(color=TEXT_MUTED),
        )
        self.compiled_hint = ft.Text(
            "Region is Seedream / annotation-model only — not Flux or other full-frame "
            "editors. Draw boxes on the large image (or use L/T/W/H). Generate paints "
            "color boxes onto a composite still + a color-keyed prompt "
            "(\"In the RED box only: …\"). If composite fails, Generate hard-stops "
            "(never sends the raw still with box prompts).",
            size=FONT_SM,
            color=TEXT_MUTED,
            max_lines=5,
        )

        self.sel_label = ft.Text("Selected: —", size=FONT_SM, color=TEXT)
        # Precision sliders with clear names + live numeric readout
        self.val_left = ft.Text("0%", size=FONT_SM, color=TEXT_MUTED, width=40)
        self.val_top = ft.Text("0%", size=FONT_SM, color=TEXT_MUTED, width=40)
        self.val_w = ft.Text("0%", size=FONT_SM, color=TEXT_MUTED, width=40)
        self.val_h = ft.Text("0%", size=FONT_SM, color=TEXT_MUTED, width=40)

        self.sl_left = ft.Slider(
            min=0, max=0.9, divisions=90, value=0.1,
            active_color=ACCENT, on_change=self._on_slider, expand=True,
        )
        self.sl_top = ft.Slider(
            min=0, max=0.9, divisions=90, value=0.1,
            active_color=ACCENT, on_change=self._on_slider, expand=True,
        )
        self.sl_w = ft.Slider(
            min=0.05, max=0.9, divisions=85, value=0.22,
            active_color=ACCENT, on_change=self._on_slider, expand=True,
        )
        self.sl_h = ft.Slider(
            min=0.05, max=0.9, divisions=85, value=0.20,
            active_color=ACCENT, on_change=self._on_slider, expand=True,
        )

        def _slider_row(name: str, slider: ft.Slider, val: ft.Text) -> ft.Control:
            return ft.Row(
                [
                    ft.Text(name, size=FONT_SM, color=TEXT, width=52, weight=ft.FontWeight.W_600),
                    slider,
                    val,
                ],
                spacing=6,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )

        self.root = ft.Column(
            [
                section_title("Region boxes"),
                self.compiled_hint,
                self.mini_stack,
                ft.Row([self.btn_add, self.btn_clear], spacing=8),
                self.box_list,
                self.sel_label,
                label("Place selected box (precision)", muted=True),
                _slider_row("Left", self.sl_left, self.val_left),
                _slider_row("Top", self.sl_top, self.val_top),
                _slider_row("Width", self.sl_w, self.val_w),
                _slider_row("Height", self.sl_h, self.val_h),
                self.conflict_text,
            ],
            spacing=6,
            visible=False,
        )

    # ----- public API -----

    def set_source(self, path: str | None, *, output_dir: str | None = None) -> None:
        self._source_path = path
        if output_dir:
            self._output_dir = output_dir
        if path and Path(path).is_file():
            try:
                from PIL import Image

                with Image.open(path) as im:
                    self._img_w, self._img_h = im.size
            except Exception:
                self._img_w, self._img_h = 0, 0
            self.mini_overlay.set_image_size(self._img_w, self._img_h)
            self.mini_image.src = path
            self.mini_image.fit = ft.BoxFit.CONTAIN
            self.mini_image.visible = True
            self.preview_placeholder.visible = False
            self.mini_overlay.set_visible(True)
        else:
            self._img_w, self._img_h = 0, 0
            self.mini_overlay.set_image_size(0, 0)
            self.mini_image.visible = False
            self.preview_placeholder.visible = True
            self.mini_overlay.set_visible(False)
        self._sync_overlays(full_rebuild=True)

    def image_size(self) -> tuple[int, int]:
        return int(self._img_w or 0), int(self._img_h or 0)

    def set_output_dir(self, path: str | None) -> None:
        self._output_dir = path

    def set_visible(self, visible: bool) -> None:
        self.root.visible = bool(visible)
        self.mini_overlay.set_visible(bool(visible) and bool(self._source_path))

    @property
    def selected_index(self) -> int:
        if not self.boxes:
            return 0
        return max(0, min(self._selected, len(self.boxes) - 1))

    def source_path(self) -> str | None:
        return self._source_path

    def live_preview_src(self) -> str | None:
        """Raw source for UI (overlays drawn separately). Never a slow composite."""
        return self._source_path

    def refresh_live_preview(self) -> str | None:
        """
        Cheap path: only refresh lightweight overlays + static image src.
        Does NOT run PIL composite.
        """
        if self._source_path and Path(self._source_path).is_file():
            if self.mini_image.src != self._source_path:
                self.mini_image.src = self._source_path
            self.mini_image.visible = True
            self.preview_placeholder.visible = False
            self.mini_overlay.set_visible(True)
            self._sync_overlays(full_rebuild=False)
            return self._source_path
        self.mini_image.visible = False
        self.preview_placeholder.visible = True
        self.mini_overlay.set_visible(False)
        return None

    def export_annotated_path(self, dest: str | Path | None = None) -> str | None:
        """
        Build annotated still for Generate/Enhance upload only (expensive, intentional).

        Returns None on failure — never silently falls back to the raw source when
        boxes exist (sending raw + \"In the RED box…\" prompts is a known foot-gun).
        """
        src = self._source_path
        if not src or not Path(src).is_file():
            return None
        if not self.boxes:
            return src
        try:
            out = Path(dest) if dest else live_preview_path(self._output_dir)
            result = draw_region_overlay(
                src,
                self.boxes,
                out,
                selected_index=self.selected_index,
            )
            if result and Path(result).is_file() and Path(result).stat().st_size > 100:
                # Refuse raw source path when boxes need annotations
                try:
                    if Path(result).resolve() == Path(src).resolve():
                        return None
                except OSError:
                    pass
                return str(result)
            return None
        except Exception:
            return None

    def has_boxes_with_prompts(self) -> bool:
        return any((b.prompt or "").strip() for b in self.boxes)

    def compiled_prompt(self) -> str:
        return build_region_prompt(self.boxes)

    def boxes_payload(self) -> list[dict[str, Any]]:
        return [
            {
                "color": b.color_name,
                "prompt": (b.prompt or "").strip(),
                "left": b.left,
                "top": b.top,
                "width": b.width,
                "height": b.height,
            }
            for b in self.boxes
            if (b.prompt or "").strip()
        ]

    def enhance_extra_context(self) -> dict[str, Any]:
        return {
            "mode": "region_edit",
            "boxes": self.boxes_payload(),
        }

    def sync_main_overlay(self, overlay: RegionBoxOverlay, *, full_rebuild: bool = False) -> None:
        """Push current boxes onto the large Comparison overlay layer."""
        overlay.set_image_size(self._img_w, self._img_h)
        overlay.sync(self.boxes, self.selected_index, full_rebuild=full_rebuild)

    # ----- internal -----

    def _select_index(self, index: int) -> None:
        if index < 0 or index >= len(self.boxes):
            return
        if index == self._selected:
            self._sync_overlays(full_rebuild=False)
            return
        self._selected = index
        self._rebuild_list()
        self._sync_overlays(full_rebuild=False)
        self._notify_structure()
        try:
            self.page.update()
        except Exception:
            pass

    def _on_drag_geometry(self) -> None:
        """Drag moved a box — sync sliders + parent overlay without list rebuild."""
        self._sync_sliders()
        self._sync_overlays(full_rebuild=False)
        if self.on_geometry:
            try:
                self.on_geometry()
            except Exception:
                pass
        try:
            self.page.update()
        except Exception:
            pass

    def _sync_overlays(self, *, full_rebuild: bool = False) -> None:
        self.mini_overlay.sync(self.boxes, self.selected_index, full_rebuild=full_rebuild)

    def _notify_structure(self) -> None:
        """Add/remove/select/prompt — full parent refresh."""
        self._refresh_conflicts()
        if self.on_change:
            try:
                self.on_change()
            except Exception:
                pass

    def _notify_geometry(self) -> None:
        """Slider tick — geometry only (no list rebuild, no PIL)."""
        self._sync_overlays(full_rebuild=False)
        if self.on_geometry:
            try:
                self.on_geometry()
            except Exception:
                pass
        elif self.on_change:
            try:
                self.on_change()
            except Exception:
                pass

    def _refresh_conflicts(self) -> None:
        notes = analyze_box_conflicts(self.boxes)
        conflicts = [n for n in notes if n.kind == "conflict"]
        comps = [n for n in notes if n.kind == "composition"]
        bits: list[str] = []
        for n in conflicts[:3]:
            bits.append(f"⚠ {n.message}")
        for n in comps[:2]:
            bits.append(f"· {n.message}")
        self.conflict_text.value = "\n".join(bits)
        self.conflict_text.color = "#e57373" if conflicts else "#ffb74d"

    def _rebuild_list(self) -> None:
        rows: list[ft.Control] = []
        for i, b in enumerate(self.boxes):
            swatch = ft.Container(
                width=18,
                height=18,
                bgcolor=b.color_hex,
                border_radius=4,
                border=ft.Border.all(2, ACCENT if i == self._selected else BORDER),
                tooltip=f"{b.color_name.title()} box",
            )
            tf = ft.TextField(
                label=f"{b.color_name.title()} box prompt",
                value=b.prompt,
                dense=True,
                filled=True,
                fill_color=PANEL_ELEVATED,
                border_color=ACCENT if i == self._selected else BORDER,
                focused_border_color=ACCENT,
                color=TEXT,
                text_size=FONT_SM,
                expand=True,
                on_change=self._make_prompt_handler(i),
            )
            sel_btn = ft.TextButton(
                content="Select",
                on_click=self._make_select_handler(i),
                style=ft.ButtonStyle(
                    color=ACCENT_BRIGHT if i == self._selected else TEXT_MUTED
                ),
            )
            rm = ft.IconButton(
                icon=ft.Icons.CLOSE,
                icon_size=16,
                icon_color=TEXT_MUTED,
                on_click=self._make_remove_handler(i),
                tooltip="Remove box",
            )
            rows.append(
                ft.Container(
                    content=ft.Row(
                        [swatch, tf, sel_btn, rm],
                        spacing=6,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    border=ft.Border.all(1, ACCENT if i == self._selected else BORDER),
                    border_radius=6,
                    padding=6,
                    bgcolor=PANEL_ELEVATED,
                )
            )
        self.box_list.controls = rows
        self._sync_sliders()
        self._refresh_conflicts()

    def _make_prompt_handler(self, index: int):
        def _h(e: ft.ControlEvent) -> None:
            if 0 <= index < len(self.boxes):
                self.boxes[index].prompt = e.control.value or ""
                # Prompt text only — no geometry work
                self._refresh_conflicts()
                if self.on_change:
                    try:
                        self.on_change()
                    except Exception:
                        pass

        return _h

    def _make_select_handler(self, index: int):
        async def _h(_e: ft.ControlEvent) -> None:
            self._select_index(index)

        return _h

    def _make_remove_handler(self, index: int):
        async def _h(_e: ft.ControlEvent) -> None:
            if 0 <= index < len(self.boxes):
                self.boxes.pop(index)
                self._selected = min(self._selected, max(0, len(self.boxes) - 1))
                self._rebuild_list()
                self._sync_overlays(full_rebuild=True)
                self._notify_structure()
                try:
                    self.page.update()
                except Exception:
                    pass

        return _h

    def _pct(self, v: float) -> str:
        return f"{int(round(float(v) * 100))}%"

    def _sync_sliders(self) -> None:
        if not self.boxes:
            self.sel_label.value = "Selected: —"
            self.val_left.value = self.val_top.value = self.val_w.value = self.val_h.value = "—"
            return
        i = self.selected_index
        self._selected = i
        b = self.boxes[i]
        self.sel_label.value = f"Selected: {b.color_name.title()} box"
        self.sl_left.value = b.left
        self.sl_top.value = b.top
        self.sl_w.value = b.width
        self.sl_h.value = b.height
        self.val_left.value = self._pct(b.left)
        self.val_top.value = self._pct(b.top)
        self.val_w.value = self._pct(b.width)
        self.val_h.value = self._pct(b.height)

    async def _on_slider(self, e: ft.ControlEvent) -> None:
        if not self.boxes:
            return
        i = self.selected_index
        b = self.boxes[i]
        b.left = float(self.sl_left.value or 0)
        b.top = float(self.sl_top.value or 0)
        b.width = float(self.sl_w.value or 0.1)
        b.height = float(self.sl_h.value or 0.1)
        b.clamp()
        self.val_left.value = self._pct(b.left)
        self.val_top.value = self._pct(b.top)
        self.val_w.value = self._pct(b.width)
        self.val_h.value = self._pct(b.height)
        # Instant geometry — no list rebuild, no PIL
        self._notify_geometry()
        try:
            self.page.update()
        except Exception:
            pass

    async def _on_add(self, e: ft.ControlEvent) -> None:
        if len(self.boxes) >= MAX_REGIONS:
            return
        used = {b.color_name for b in self.boxes}
        box = make_box(index=len(self.boxes), used_names=used)
        self.boxes.append(box)
        self._selected = len(self.boxes) - 1
        self._rebuild_list()
        self._sync_overlays(full_rebuild=True)
        self._notify_structure()
        try:
            self.page.update()
        except Exception:
            pass

    async def _on_clear(self, e: ft.ControlEvent) -> None:
        self.boxes.clear()
        self._selected = 0
        self._rebuild_list()
        self._sync_overlays(full_rebuild=True)
        self._notify_structure()
        try:
            self.page.update()
        except Exception:
            pass

    def ensure_one_box(self) -> None:
        if not self.boxes:
            self.boxes.append(make_box(index=0))
            self._selected = 0
            self._rebuild_list()
            self._sync_overlays(full_rebuild=True)
            self._notify_structure()
