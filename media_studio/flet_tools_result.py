"""
Large result viewer for the Tools tab (Studio Comparison–style).

Shows source + result, optional image Overlay / A/B, and result actions
without forcing the user into Library for a full-size preview.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

import flet as ft

from media_studio.flet_dialogs import close_dialog, show_dialog, show_snack
from media_studio.flet_result_actions import (
    make_before_after_button,
    make_result_action_row,
    show_result_actions,
)
from media_studio.flet_theme import (
    ACCENT,
    BORDER,
    FONT_MD,
    FONT_SM,
    PANEL,
    PANEL_ELEVATED,
    TEXT,
    TEXT_MUTED,
    label,
    panel,
    section_title,
)
from media_studio.flet_video_player import VideoResultPlayer

if TYPE_CHECKING:
    from media_studio.flet_app import StudioState

_VIDEO_EXTS = {".mp4", ".mov", ".webm", ".m4v", ".avi", ".mkv"}
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tiff"}


def _is_video(path: str | None) -> bool:
    if not path:
        return False
    return Path(path).suffix.lower() in _VIDEO_EXTS


def _is_image(path: str | None) -> bool:
    if not path:
        return False
    return Path(path).suffix.lower() in _IMAGE_EXTS


def _exists(path: str | None) -> str | None:
    if not path:
        return None
    try:
        p = Path(path).expanduser().resolve()
        if p.is_file() and p.stat().st_size > 0:
            return str(p)
    except OSError:
        return None
    return None


def _safe_float(v: Any, default: float = 0.5) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


class ToolsResultPane:
    """
    Shared large preview for the active Tools generation.

    Layout (Studio-like):
      left rail — source thumb + result label
      main stage — CONTAIN preview with Overlay / A/B when both are stills
      actions — Open large, Show in folder, Send to Resolve, Send to ▾
    """

    def __init__(
        self,
        page: ft.Page,
        state: StudioState,
        *,
        on_status: Callable[[str, bool], None] | None = None,
    ) -> None:
        self.page = page
        self.state = state
        self.on_status = on_status
        self.source_path: str | None = None
        self.result_path: str | None = None
        self.tool_label: str = ""

        self._overlay_opacity = 0.5
        self._ab_gen: bool | None = None  # None=slider, True=result, False=source

        # --- left rail ---
        self.src_thumb = ft.Image(
            src="",
            fit=ft.BoxFit.CONTAIN,
            width=140,
            height=88,
            visible=False,
            gapless_playback=True,
        )
        self.src_video_icon = ft.Container(
            content=ft.Column(
                [
                    ft.Icon(ft.Icons.MOVIE, color=TEXT_MUTED, size=28),
                    ft.Text("", size=10, color=TEXT_MUTED, max_lines=2, text_align=ft.TextAlign.CENTER),
                ],
                spacing=2,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                tight=True,
            ),
            width=140,
            height=88,
            alignment=ft.Alignment.CENTER,
            bgcolor="#1a1d24",
            visible=False,
        )
        self.src_card = ft.Container(
            content=ft.Column(
                [
                    ft.Text("SOURCE", size=11, color=TEXT_MUTED, weight=ft.FontWeight.W_700),
                    ft.Stack(
                        [self.src_thumb, self.src_video_icon],
                        width=140,
                        height=88,
                    ),
                    ft.Text(
                        "Click to open large",
                        size=10,
                        color=TEXT_MUTED,
                    ),
                ],
                spacing=4,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                tight=True,
            ),
            bgcolor=PANEL_ELEVATED,
            border=ft.Border.all(1, BORDER),
            border_radius=8,
            padding=8,
            on_click=self._open_source_lightbox,
            ink=True,
            tooltip="View source full size",
            visible=False,
        )
        self.result_meta = ft.Text(
            "Run a tool to preview the result here",
            size=FONT_SM,
            color=TEXT_MUTED,
            max_lines=4,
        )

        # --- stage (overlay for stills) ---
        # Non-positioned + BoxFit.CONTAIN: fit inside stage, preserve aspect,
        # letterbox/pillarbox on dark stage — never crop on wide windows.
        self.overlay_base = ft.Image(
            src="",
            fit=ft.BoxFit.CONTAIN,
            expand=True,
            visible=False,
            gapless_playback=True,
        )
        self.overlay_gen_img = ft.Image(
            src="",
            fit=ft.BoxFit.CONTAIN,
            expand=True,
            gapless_playback=True,
        )
        self.overlay_gen_layer = ft.Container(
            content=self.overlay_gen_img,
            opacity=0.5,
            expand=True,
            visible=False,
            alignment=ft.Alignment.CENTER,
            # No HARD_EDGE crop of letterboxed CONTAIN frames
            clip_behavior=ft.ClipBehavior.NONE,
        )
        # Single result image when no A/B pair
        self.single_result = ft.Image(
            src="",
            fit=ft.BoxFit.CONTAIN,
            expand=True,
            visible=False,
            gapless_playback=True,
        )
        self.video_poster = ft.Image(
            src="",
            fit=ft.BoxFit.CONTAIN,
            expand=True,
            visible=False,
            gapless_playback=True,
        )
        self.video_badge = ft.Container(
            content=ft.Column(
                [
                    ft.Icon(ft.Icons.PLAY_CIRCLE_OUTLINE, size=56, color=TEXT),
                    ft.Text(
                        "",
                        size=FONT_SM,
                        color=TEXT,
                        text_align=ft.TextAlign.CENTER,
                        max_lines=3,
                        selectable=True,
                    ),
                ],
                spacing=8,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                tight=True,
            ),
            alignment=ft.Alignment.CENTER,
            expand=True,
            visible=False,
        )
        # In-app video result (shared with Creative Vision / Frame Editor)
        self.video_player = VideoResultPlayer(page, height=360)
        try:
            self.video_player.control.visible = False
            self.video_player.control.expand = False
        except Exception:
            pass
        self.overlay_stack = ft.Stack(
            [
                self.overlay_base,
                self.overlay_gen_layer,
                self.single_result,
                self.video_poster,
                self.video_badge,
            ],
            expand=True,
            fit=ft.StackFit.EXPAND,
            alignment=ft.Alignment.CENTER,
        )
        # Compact empty state — never a full-window grey band
        self.placeholder = ft.Container(
            content=ft.Text(
                "Generate a result to preview full-size",
                size=FONT_MD,
                color=TEXT_MUTED,
                text_align=ft.TextAlign.CENTER,
            ),
            height=96,
            alignment=ft.Alignment.CENTER,
            bgcolor=PANEL_ELEVATED,
            border_radius=8,
            border=ft.Border.all(1, BORDER),
            visible=True,
        )
        # Dark letterbox stage: expands with pane; images CONTAIN inside
        self.stage = ft.Container(
            content=self.overlay_stack,
            expand=False,
            bgcolor="#111318",
            border_radius=8,
            border=ft.Border.all(1, BORDER),
            alignment=ft.Alignment.CENTER,
            clip_behavior=ft.ClipBehavior.NONE,
            visible=False,
        )

        self.overlay_slider = ft.Slider(
            min=0.0,
            max=1.0,
            divisions=100,
            value=0.5,
            label="Result {value}",
            on_change=self._on_overlay_slider,
            active_color=ACCENT,
            expand=True,
        )
        self.ab_switch = ft.Switch(
            label="A/B · Result 100%",
            value=False,
            active_color=ACCENT,
            on_change=self._on_ab_toggle,
        )
        self.overlay_mode_label = ft.Text(
            "Blend · 50% result",
            size=FONT_SM,
            color=TEXT_MUTED,
        )
        self.overlay_controls = ft.Column(
            [
                ft.Row(
                    [
                        label("Overlay / A/B", muted=True),
                        self.overlay_mode_label,
                        self.ab_switch,
                        ft.Container(expand=True),
                        ft.IconButton(
                            icon=ft.Icons.OPEN_IN_FULL,
                            icon_color=TEXT,
                            tooltip="Open result full size",
                            on_click=self._open_result_lightbox,
                        ),
                    ],
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Row(
                    [
                        ft.Text("Source", size=FONT_SM, color=TEXT_MUTED),
                        self.overlay_slider,
                        ft.Text("Result", size=FONT_SM, color=TEXT_MUTED),
                    ],
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
            ],
            spacing=4,
            tight=True,
            visible=False,
        )

        self.title = ft.Text("Result", size=FONT_MD, color=TEXT, weight=ft.FontWeight.W_700)
        self.subtitle = ft.Text("", size=FONT_SM, color=TEXT_MUTED)

        self.btn_open_large = ft.OutlinedButton(
            content="Open large",
            icon=ft.Icons.OPEN_IN_FULL,
            on_click=self._open_result_lightbox,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
            visible=False,
        )
        self.btn_before_after = make_before_after_button(
            page,
            get_before=lambda: self.source_path,
            get_after=lambda: self.result_path,
            get_output_dir=lambda: self.state.output_dir,
            get_job_name=lambda: getattr(self.state, "job_name", None),
            on_status=self._status,
        )
        (
            self.actions_row,
            self.btn_folder,
            self.btn_resolve,
        ) = make_result_action_row(
            page,
            get_path=lambda: self.result_path,
            on_status=self._status,
            extra_leading=[self.btn_open_large],
            before_after_btn=self.btn_before_after,
            start_visible=False,
        )
        self.send_host = ft.Container(visible=False)
        self.actions_wrap = ft.Row(
            [self.actions_row, self.send_host],
            spacing=8,
            wrap=True,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        # lightbox
        self._lightbox_dialog: ft.AlertDialog | None = None
        self._lightbox_img: ft.Image | None = None
        self._lightbox_title: ft.Text | None = None

        rail = ft.Container(
            width=168,
            content=ft.Column(
                [
                    self.src_card,
                    ft.Divider(height=1, color=BORDER),
                    ft.Text("RESULT", size=11, color=TEXT_MUTED, weight=ft.FontWeight.W_700),
                    self.result_meta,
                ],
                spacing=8,
                tight=True,
            ),
            padding=ft.Padding.only(right=4),
        )

        # CapRightEmpty: tight when empty; expand only with a result (_apply_visuals)
        self._workspace = ft.Column(
            [
                self.overlay_controls,
                self.placeholder,
                self.stage,
                self.video_player.control,
            ],
            spacing=8,
            tight=True,
            expand=False,
            alignment=ft.MainAxisAlignment.START,
        )
        self._body_row = ft.Row(
            [rail, self._workspace],
            spacing=10,
            expand=False,
            # STRETCH when result open so stage height grows with window
            vertical_alignment=ft.CrossAxisAlignment.START,
        )
        self._root_col = ft.Column(
            [
                ft.Row(
                    [
                        self.title,
                        self.subtitle,
                        ft.Container(expand=True),
                        ft.TextButton("Clear", on_click=self._clear),
                    ],
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                self._body_row,
                self.actions_wrap,
            ],
            spacing=8,
            tight=True,
            expand=False,
            alignment=ft.MainAxisAlignment.START,
        )
        self.root = panel(self._root_col, expand=True, padding=10)

    def _status(self, msg: str, is_error: bool = False) -> None:
        if self.on_status:
            try:
                self.on_status(msg, is_error)
            except Exception:
                pass
        try:
            show_snack(self.page, msg)
        except Exception:
            pass

    def show(
        self,
        source_path: str | None,
        result_path: str,
        *,
        tool_label: str = "",
        offer_upscale_prompt: bool = False,
    ) -> None:
        """Publish a successful tool result to the large viewer."""
        self.source_path = _exists(source_path)
        self.result_path = _exists(result_path)
        self.tool_label = tool_label or ""
        if not self.result_path:
            return
        self._ab_gen = None
        self._overlay_opacity = 0.5
        self._refresh_send_menu()
        self._apply_visuals()
        show_result_actions(self.btn_folder, self.btn_resolve, visible=True)
        self.btn_open_large.visible = True
        # Before/after only when both are still images
        try:
            ba_ok = bool(
                self.source_path
                and self.result_path
                and _is_image(self.source_path)
                and _is_image(self.result_path)
            )
            self.btn_before_after.visible = ba_ok
        except Exception:
            pass
        try:
            self.page.update()
        except Exception:
            pass
        # Soft prompt after V2V / video results (never auto-runs)
        if offer_upscale_prompt and _is_video(self.result_path):
            try:
                self._maybe_offer_upscale(self.result_path)
            except Exception:
                pass

    def _maybe_offer_upscale(self, video_path: str) -> None:
        """Optional soft dialog: Upscale this clip? → Tools Upscale preload."""
        from media_studio.flet_send_to import send_to_tool

        async def _yes(_e: ft.ControlEvent | None = None) -> None:
            close_dialog(self.page)
            handler = send_to_tool(
                self.state,
                "upscale",
                video_path,
                as_video=True,
                status_cb=lambda m: self._status(m),
            )
            await handler(_e)

        async def _no(_e: ft.ControlEvent | None = None) -> None:
            close_dialog(self.page)

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Upscale this clip?", color=TEXT),
            content=ft.Text(
                "Open Tools → Video → Upscale with this result pre-loaded. "
                "You choose model, target, and confirm cost — nothing runs automatically.",
                color=TEXT_MUTED,
                size=FONT_SM,
            ),
            actions=[
                ft.TextButton("Not now", on_click=_no),
                ft.FilledButton(
                    content="Send to Upscale",
                    on_click=_yes,
                    style=ft.ButtonStyle(bgcolor=ACCENT, color=TEXT),
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
            bgcolor=PANEL_ELEVATED,
        )
        show_dialog(self.page, dlg)

    def clear(self) -> None:
        self.source_path = None
        self.result_path = None
        self.tool_label = ""
        self._ab_gen = None
        self._overlay_opacity = 0.5
        show_result_actions(self.btn_folder, self.btn_resolve, visible=False)
        self.btn_open_large.visible = False
        try:
            self.btn_before_after.visible = False
        except Exception:
            pass
        self.send_host.content = None
        self.send_host.visible = False
        self._apply_visuals()

    async def _clear(self, _e: ft.ControlEvent) -> None:
        self.clear()
        try:
            self.page.update()
        except Exception:
            pass

    def _effective_opacity(self) -> float:
        if self._ab_gen is True:
            return 1.0
        if self._ab_gen is False:
            return 0.0
        return max(0.0, min(1.0, self._overlay_opacity))

    def _sync_labels(self) -> None:
        op = self._effective_opacity()
        if self._ab_gen is True:
            mode = "A/B · Result 100%"
            show_gen = True
        elif self._ab_gen is False:
            mode = "A/B · Source 100%"
            show_gen = False
        else:
            mode = f"Blend · {int(round(op * 100))}% result"
            show_gen = op >= 0.99
        self.overlay_mode_label.value = mode
        self.overlay_slider.value = op
        self.ab_switch.value = show_gen
        self.ab_switch.label = (
            "A/B · Result 100%" if show_gen else "A/B · Source 100%"
        )

    def _set_src_rail(self) -> None:
        src = self.source_path
        if not src:
            self.src_card.visible = False
            self.src_thumb.visible = False
            self.src_video_icon.visible = False
            return
        self.src_card.visible = True
        if _is_video(src):
            self.src_thumb.visible = False
            poster = None
            try:
                from media_studio.media import video_poster_path

                poster = video_poster_path(src)
            except Exception:
                poster = None
            if poster and Path(poster).is_file():
                self.src_thumb.src = poster
                self.src_thumb.visible = True
                self.src_video_icon.visible = False
            else:
                name_ctrl = self.src_video_icon.content
                if isinstance(name_ctrl, ft.Column) and len(name_ctrl.controls) > 1:
                    t = name_ctrl.controls[1]
                    if isinstance(t, ft.Text):
                        t.value = Path(src).name
                self.src_video_icon.visible = True
        elif _is_image(src):
            self.src_video_icon.visible = False
            self.src_thumb.src = src
            self.src_thumb.visible = True
        else:
            self.src_card.visible = False

    def _apply_visuals(self) -> None:
        src = self.source_path
        res = self.result_path
        self.subtitle.value = self.tool_label or ""

        if not res:
            self.placeholder.visible = True
            self.stage.visible = False
            try:
                self.stage.expand = False
            except Exception:
                pass
            self.overlay_controls.visible = False
            try:
                self.video_player.clear()
                self.video_player.control.visible = False
                self.video_player.control.expand = False
            except Exception:
                pass
            self.result_meta.value = "Run a tool to preview the result here"
            try:
                self._workspace.expand = False
                self._workspace.tight = True
                self._body_row.expand = False
                self._body_row.vertical_alignment = ft.CrossAxisAlignment.START
                self._root_col.expand = False
                self._root_col.tight = True
            except Exception:
                pass
            self._set_src_rail()
            self._sync_labels()
            return

        self.placeholder.visible = False
        name = Path(res).name
        self.result_meta.value = name
        self.title.value = "Result"
        try:
            self._workspace.expand = True
            self._workspace.tight = False
            self._body_row.expand = True
            # Stretch so stage height tracks window; width from CapRight expand
            self._body_row.vertical_alignment = ft.CrossAxisAlignment.STRETCH
            self._root_col.expand = True
            self._root_col.tight = False
        except Exception:
            pass
        self._set_src_rail()

        # Hide all stage layers first
        self.overlay_base.visible = False
        self.overlay_gen_layer.visible = False
        self.single_result.visible = False
        self.video_poster.visible = False
        self.video_badge.visible = False
        try:
            self.video_player.control.visible = False
            self.video_player.control.expand = False
        except Exception:
            pass
        try:
            self.overlay_base.fit = ft.BoxFit.CONTAIN
            self.overlay_gen_img.fit = ft.BoxFit.CONTAIN
            self.single_result.fit = ft.BoxFit.CONTAIN
            self.video_poster.fit = ft.BoxFit.CONTAIN
        except Exception:
            pass

        both_images = _is_image(src) and _is_image(res)
        if both_images:
            self.stage.visible = True
            try:
                self.stage.expand = True
            except Exception:
                pass
            self.overlay_controls.visible = True
            op = self._effective_opacity()
            self.overlay_base.src = src or ""
            self.overlay_base.visible = bool(src)
            self.overlay_gen_img.src = res
            self.overlay_gen_layer.visible = True
            self.overlay_gen_layer.opacity = op if src else 1.0
            self._sync_labels()
            return

        self.overlay_controls.visible = False
        if _is_image(res):
            self.stage.visible = True
            try:
                self.stage.expand = True
            except Exception:
                pass
            self.single_result.src = res
            self.single_result.visible = True
        elif _is_video(res):
            # Prefer in-app VideoResultPlayer; poster fallback if player missing
            has_player = False
            try:
                self.video_player.set_result(res, note=f"Tools · {name}")
                self.video_player.control.visible = True
                self.video_player.control.expand = True
                try:
                    self.video_player.control.height = None  # type: ignore[assignment]
                except Exception:
                    pass
                if getattr(self.video_player, "_video", None) is not None:
                    try:
                        self.video_player._video.fit = ft.BoxFit.CONTAIN
                        self.video_player._video.expand = True
                    except Exception:
                        pass
                has_player = getattr(self.video_player, "_video", None) is not None
            except Exception:
                has_player = False
            if has_player:
                self.stage.visible = False
                try:
                    self.stage.expand = False
                except Exception:
                    pass
            else:
                self.stage.visible = True
                try:
                    self.stage.expand = True
                except Exception:
                    pass
                try:
                    self.video_player.control.visible = False
                except Exception:
                    pass
                poster = None
                try:
                    from media_studio.media import video_poster_path

                    poster = video_poster_path(res)
                except Exception:
                    poster = None
                if poster and Path(poster).is_file():
                    self.video_poster.src = poster
                    self.video_poster.visible = True
                badge_col = self.video_badge.content
                if isinstance(badge_col, ft.Column) and len(badge_col.controls) > 1:
                    t = badge_col.controls[1]
                    if isinstance(t, ft.Text):
                        t.value = f"Video\n{name}"
                self.video_badge.visible = True
        else:
            self.stage.visible = True
            try:
                self.stage.expand = True
            except Exception:
                pass
            self.single_result.src = res
            self.single_result.visible = True
        self._sync_labels()

    async def _on_overlay_slider(self, e: ft.ControlEvent) -> None:
        self._ab_gen = None
        self._overlay_opacity = _safe_float(
            e.control.value if e and e.control is not None else self.overlay_slider.value,
            0.5,
        )
        self._apply_visuals()
        try:
            self.page.update()
        except Exception:
            pass

    async def _on_ab_toggle(self, e: ft.ControlEvent) -> None:
        show_gen = bool(e.control.value) if e and e.control is not None else False
        self._ab_gen = show_gen
        self._overlay_opacity = 1.0 if show_gen else 0.0
        self._apply_visuals()
        try:
            self.page.update()
        except Exception:
            pass

    def _refresh_send_menu(self) -> None:
        path = self.result_path
        if not path:
            self.send_host.content = None
            self.send_host.visible = False
            return
        from media_studio.flet_send_to import (
            build_send_menu_items,
            make_send_menu_button,
            send_to_tool,
        )

        img = path if _is_image(path) else None
        vid = path if _is_video(path) else None
        items = build_send_menu_items(
            self.state,
            image_path=img,
            video_path=vid,
            status_cb=lambda m: self._status(m),
        )
        # Explicit top-level Upscale for video results (same as Video Upscale)
        if vid:
            from media_studio.flet_send_to import _item

            # Prefer a dedicated leaf before the Send menu for one-click path
            up_handler = send_to_tool(
                self.state,
                "upscale",
                vid,
                as_video=True,
                status_cb=lambda m: self._status(m),
            )
            self.btn_send_upscale = ft.OutlinedButton(
                content="Send to Upscale",
                icon=ft.Icons.HIGH_QUALITY,
                on_click=up_handler,
                style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
                tooltip="Open Tools → Video → Upscale with this clip as source (confirm cost before run)",
            )
        else:
            self.btn_send_upscale = None
        btn = make_send_menu_button(items)
        row_controls: list[ft.Control] = []
        if getattr(self, "btn_send_upscale", None) is not None:
            row_controls.append(self.btn_send_upscale)
        if btn is not None:
            row_controls.append(btn)
        if not row_controls:
            self.send_host.visible = False
            return
        self.send_host.content = ft.Row(
            row_controls,
            spacing=8,
            wrap=True,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        self.send_host.visible = True

    def _send_image(self, path: str) -> Callable:
        async def _click(_e: ft.ControlEvent) -> None:
            iv = getattr(self.state, "image_view", None)
            if iv is not None and hasattr(iv, "load_source_path"):
                iv.load_source_path(path, status=f"Tools → Image: {Path(path).name}")
            switch = getattr(self.state, "switch_to_image", None)
            if switch:
                switch()
            self._status(f"Sent to Image: {Path(path).name}")

        return _click

    def _send_video_ref(self, path: str) -> Callable:
        async def _click(_e: ft.ControlEvent) -> None:
            resolved = str(Path(path).resolve())
            self.state.video_ref_path = resolved
            vv = getattr(self.state, "video_view", None)
            if vv is not None and hasattr(vv, "open_received"):
                vv.open_received(
                    ref_path=resolved,
                    scenario_label=getattr(self.state, "scenario_label", None),
                )
            switch = getattr(self.state, "switch_to_video", None)
            if switch:
                switch()
            self._status(f"Sent to Video (ref): {Path(path).name}")

        return _click

    def _send_video_source(self, path: str) -> Callable:
        async def _click(_e: ft.ControlEvent) -> None:
            vv = getattr(self.state, "video_view", None)
            if vv is not None and hasattr(vv, "load_source_video"):
                vv.load_source_video(
                    path,
                    clip_name=Path(path).name,
                    status=f"Tools → Video source: {Path(path).name}",
                    record=False,
                )
            switch = getattr(self.state, "switch_to_video", None)
            if switch:
                switch()
            self._status(f"Sent to Video (source): {Path(path).name}")

        return _click

    def _send_tool(self, tool_id: str, path: str, *, as_video: bool) -> Callable:
        async def _click(_e: ft.ControlEvent) -> None:
            tv = getattr(self.state, "tools_view", None)
            if tv is not None and hasattr(tv, "receive_media"):
                tv.receive_media(tool_id, path, as_video=as_video)
            switch = getattr(self.state, "switch_to_tools", None)
            if switch:
                switch(tool_id)
            self._status(f"Sent to tool {tool_id}: {Path(path).name}")

        return _click

    def _send_frame_editor(self, path: str, *, as_video: bool) -> Callable:
        async def _click(_e: ft.ControlEvent) -> None:
            switch = getattr(self.state, "switch_to_frame_editor", None)
            if switch:
                if as_video:
                    switch(video_path=path)
                else:
                    switch(keyframe_path=path)
            else:
                fe = getattr(self.state, "frame_editor_view", None)
                if fe is not None:
                    if as_video and hasattr(fe, "load_source"):
                        fe.load_source(path)
                    elif hasattr(fe, "receive_keyframe"):
                        fe.receive_keyframe(path)
                    elif hasattr(fe, "add_keyframe"):
                        fe.add_keyframe(path, pin="first")
            kind = "source" if as_video else "keyframe"
            self._status(f"Sent to Frame Editor ({kind}): {Path(path).name}")

        return _click

    async def _open_source_lightbox(self, _e: ft.ControlEvent) -> None:
        path = self.source_path
        if path and _is_image(path):
            await self._open_lightbox(path, title="Source")
        elif path and _is_video(path):
            self._status(f"Video source: {Path(path).name} — use Show in folder")

    async def _open_result_lightbox(self, _e: ft.ControlEvent) -> None:
        path = self.result_path
        if not path:
            return
        if _is_image(path):
            await self._open_lightbox(path, title="Result")
        elif _is_video(path):
            await self._open_video_dialog(path, title="Result video")
        else:
            from media_studio.folder_util import show_in_folder

            msg = show_in_folder(path)
            self._status(msg)

    async def _open_video_dialog(self, path: str, *, title: str = "Video") -> None:
        """In-app video dialog (shared VideoResultPlayer pattern)."""
        win_w = float(getattr(self.page.window, "width", None) or 1400)
        win_h = float(getattr(self.page.window, "height", None) or 900)
        body_w = int(min(max(win_w - 80, 700), win_w * 0.92))
        body_h = int(min(max(win_h - 160, 400), win_h * 0.8))

        player = VideoResultPlayer(self.page, height=body_h - 40)
        try:
            player.set_result(path, note=f"{title} · {Path(path).name}")
            player.control.expand = False
            player.control.height = body_h
        except Exception as exc:
            self._status(f"Player failed: {exc}", True)
            from media_studio.folder_util import show_in_folder

            self._status(show_in_folder(path))
            return

        def _close(_e: Any = None) -> None:
            try:
                player.clear()
            except Exception:
                pass
            close_dialog(self.page, dlg)

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text(
                f"{title} · {Path(path).name}",
                size=FONT_MD,
                color=TEXT,
                weight=ft.FontWeight.W_700,
            ),
            content=ft.Container(
                content=player.control,
                width=body_w,
                height=body_h,
                bgcolor="#0a0c10",
            ),
            actions=[
                ft.TextButton(
                    content="Show in folder",
                    on_click=lambda _e: self._status(
                        __import__(
                            "media_studio.folder_util", fromlist=["show_in_folder"]
                        ).show_in_folder(path)
                    ),
                ),
                ft.TextButton(content="Close", on_click=_close),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
            bgcolor=PANEL,
        )
        show_dialog(self.page, dlg)

    async def _open_lightbox(self, path: str, *, title: str = "Preview") -> None:
        win_w = float(getattr(self.page.window, "width", None) or 1400)
        win_h = float(getattr(self.page.window, "height", None) or 900)
        body_w = int(min(max(win_w - 80, 700), win_w * 0.92))
        body_h = int(min(max(win_h - 120, 400), win_h * 0.85))

        if self._lightbox_img is None:
            self._lightbox_img = ft.Image(src="", fit=ft.BoxFit.CONTAIN, expand=True)
        if self._lightbox_title is None:
            self._lightbox_title = ft.Text(title, size=FONT_MD, color=TEXT, weight=ft.FontWeight.W_700)

        self._lightbox_img.src = path
        self._lightbox_title.value = f"{title} · {Path(path).name}"

        def _close(_e: Any = None) -> None:
            close_dialog(self.page, self._lightbox_dialog)

        self._lightbox_dialog = ft.AlertDialog(
            modal=True,
            title=self._lightbox_title,
            content=ft.Container(
                content=self._lightbox_img,
                width=body_w,
                height=body_h,
                bgcolor="#0a0c10",
                alignment=ft.Alignment.CENTER,
                clip_behavior=ft.ClipBehavior.NONE,
            ),
            actions=[
                ft.TextButton("Close", on_click=_close),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
            bgcolor=PANEL,
        )
        show_dialog(self.page, self._lightbox_dialog)
