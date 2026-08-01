"""In-app video result player (flet-video) + Show in folder."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import flet as ft

from media_studio.folder_util import show_in_folder
from media_studio.flet_result_actions import make_result_action_row, show_result_actions
from media_studio.flet_theme import (
    BORDER,
    EMPTY_PREVIEW_H,
    FONT_SM,
    PANEL_ELEVATED,
    TEXT,
    TEXT_MUTED,
)

try:
    import flet_video as ftv

    _HAS_VIDEO = True
except ImportError:  # pragma: no cover
    ftv = None  # type: ignore
    _HAS_VIDEO = False


class VideoResultPlayer:
    """
    Inline flet-video player for a successful generation.

    Visible only after ``set_result``; does not open the OS media player.
    Empty state is compact (no full-height grey expand void).
    """

    def __init__(self, page: ft.Page, *, height: float = 360) -> None:
        self.page = page
        self.path: str | None = None
        self._height = float(height)

        self.path_text = ft.Text(
            "No video result yet.",
            size=FONT_SM,
            color=TEXT_MUTED,
            selectable=True,
            max_lines=2,
        )
        self._resolve_status = ft.Text(
            "", size=FONT_SM, color=TEXT_MUTED, visible=False, max_lines=2
        )
        (
            self.result_actions_row,
            self.btn_folder,
            self.btn_resolve,
        ) = make_result_action_row(
            page,
            get_path=lambda: self.path,
            on_status=self._on_resolve_status,
        )
        # Content-sized empty state — never expand into a grey slab
        self._placeholder = ft.Column(
            [
                ft.Icon(ft.Icons.MOVIE, size=36, color=TEXT_MUTED),
                self.path_text,
                ft.Text(
                    "Generate a video to preview it here.",
                    size=FONT_SM,
                    color=TEXT_MUTED,
                    text_align=ft.TextAlign.CENTER,
                ),
            ],
            spacing=6,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            tight=True,
            expand=False,
        )

        self._video: Any = None
        self._error = ft.Text("", size=FONT_SM, color="#e57373", visible=False)

        if _HAS_VIDEO:
            self._video = ftv.Video(
                playlist=[],
                autoplay=False,
                volume=100,
                fit=ft.BoxFit.CONTAIN,
                fill_color="#0a0c10",
                aspect_ratio=16 / 9,
                expand=False,
                height=self._height - 48,
                visible=False,
                on_error=self._on_error,
            )
        else:
            self._error.value = (
                "flet-video is not installed. Run: pip install flet-video\n"
                "Linux may also need libmpv (see README / package notes)."
            )
            self._error.visible = True

        body_controls: list[ft.Control] = [self._placeholder]
        if self._video is not None:
            body_controls.append(self._video)
        body_controls.extend(
            [
                self._error,
                ft.Row(
                    [self.path_text],
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                self.result_actions_row,
                self._resolve_status,
            ]
        )

        # expand=False when empty — parent tabs must not inherit a full-height grey box
        self.control = ft.Container(
            content=ft.Column(
                body_controls,
                spacing=8,
                tight=True,
                expand=False,
                alignment=ft.MainAxisAlignment.START,
            ),
            expand=False,
            height=EMPTY_PREVIEW_H + 40,
            bgcolor=PANEL_ELEVATED,
            border=ft.Border.all(1, BORDER),
            border_radius=8,
            padding=10,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
            alignment=ft.Alignment.TOP_CENTER,
        )
        show_result_actions(self.btn_folder, self.btn_resolve, visible=False)

    def _safe_update(self) -> None:
        try:
            schedule = getattr(self.page, "schedule_update", None)
            if callable(schedule):
                schedule()
                return
            self.page.update()
        except Exception:
            pass

    def _on_error(self, e: Any) -> None:
        detail = getattr(e, "data", None) or getattr(e, "error", None) or str(e)
        self._error.value = f"Video play error: {detail}"
        self._error.visible = True
        self._safe_update()

    def _on_resolve_status(self, msg: str, is_error: bool) -> None:
        self._resolve_status.value = msg
        self._resolve_status.visible = True
        self._resolve_status.color = "#e57373" if is_error else TEXT_MUTED
        self._safe_update()

    def _set_empty_layout(self) -> None:
        try:
            self.control.expand = False
            self.control.height = EMPTY_PREVIEW_H + 40
        except Exception:
            pass

    def _set_result_layout(self) -> None:
        try:
            self.control.expand = False
            self.control.height = self._height + 56
            if self._video is not None:
                self._video.height = max(160.0, self._height - 48)
                self._video.expand = False
        except Exception:
            pass

    def clear(self) -> None:
        self.path = None
        self.path_text.value = "No video result yet."
        show_result_actions(self.btn_folder, self.btn_resolve, visible=False)
        self._resolve_status.visible = False
        self._placeholder.visible = True
        self._error.visible = not _HAS_VIDEO
        if self._video is not None:
            try:
                self._video.playlist = []
                self._video.visible = False
            except Exception:
                pass
        self._set_empty_layout()
        self._safe_update()

    def set_result(self, path: str | None, *, note: str | None = None) -> None:
        if not path or not Path(path).is_file():
            self.clear()
            return
        self.path = str(Path(path).resolve())
        self.path_text.value = note or f"Saved: {self.path}"
        show_result_actions(self.btn_folder, self.btn_resolve, visible=True)
        self._resolve_status.visible = False
        self._placeholder.visible = False
        self._error.visible = False
        self._set_result_layout()

        if self._video is None:
            self._error.value = (
                "flet-video is not installed — cannot preview in-app.\n"
                "Install: pip install flet-video  (Linux: also needs libmpv)"
            )
            self._error.visible = True
            self._safe_update()
            return

        try:
            media = ftv.VideoMedia(resource=self.path)
            self._video.playlist = [media]
            self._video.visible = True
            # Do not autoplay — user presses controls
        except Exception as exc:
            self._error.value = f"Could not load video: {exc}"
            self._error.visible = True
        self._safe_update()

    async def _show_folder(self, e: ft.ControlEvent) -> None:
        from media_studio.flet_dialogs import show_snack

        msg = show_in_folder(self.path)
        try:
            show_snack(self.page, msg)
        except Exception:
            self.path_text.value = msg
            self._safe_update()
