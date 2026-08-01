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

    Video always uses BoxFit.CONTAIN (no crop). Play/pause via built-in controls.
    """

    def __init__(
        self,
        page: ft.Page,
        *,
        height: float = 360,
        embed_actions: bool = True,
        show_path_row: bool = True,
    ) -> None:
        self.page = page
        self.path: str | None = None
        self._height = float(height)
        self._embed_actions = bool(embed_actions)
        self._show_path_row = bool(show_path_row)

        self.path_text = ft.Text(
            "No video result yet.",
            size=FONT_SM,
            color=TEXT_MUTED,
            selectable=True,
            max_lines=2,
        )
        self._path_row = ft.Row(
            [self.path_text],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            visible=self._show_path_row,
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
        self.result_actions_row.visible = False
        # Content-sized empty state — never expand into a grey slab
        self._placeholder = ft.Column(
            [
                ft.Icon(ft.Icons.MOVIE, size=36, color=TEXT_MUTED),
                self.path_text if not self._show_path_row else ft.Container(height=0),
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
            kwargs: dict[str, Any] = dict(
                playlist=[],
                autoplay=False,
                volume=100,
                fit=ft.BoxFit.CONTAIN,
                fill_color="#0a0c10",
                expand=False,
                height=max(160.0, self._height - 8),
                visible=False,
                on_error=self._on_error,
            )
            # Play/pause + seek — prefer native controls when supported
            try:
                kwargs["show_controls"] = True
            except Exception:
                pass
            try:
                kwargs["filter_quality"] = ft.FilterQuality.MEDIUM
            except Exception:
                pass
            # Leave aspect free so CONTAIN letterboxes inside fixed height
            # (fixed 16:9 + short height was clipping controls)
            self._video = ftv.Video(**kwargs)
        else:
            self._error.value = (
                "flet-video is not installed. Run: pip install flet-video\n"
                "Linux may also need libmpv (see README / package notes)."
            )
            self._error.visible = True

        body_controls: list[ft.Control] = [self._placeholder]
        if self._video is not None:
            body_controls.append(self._video)
        body_controls.append(self._error)
        if self._show_path_row:
            body_controls.append(self._path_row)
        if self._embed_actions:
            body_controls.append(self.result_actions_row)
            body_controls.append(self._resolve_status)
        else:
            # Status still available for parent-driven Resolve feedback
            body_controls.append(self._resolve_status)

        # expand=False when empty — parent tabs must not inherit a full-height grey box
        # No HARD_EDGE on outer shell — it clipped player controls / bottom of frame
        self.control = ft.Container(
            content=ft.Column(
                body_controls,
                spacing=6,
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
            clip_behavior=ft.ClipBehavior.NONE,
            alignment=ft.Alignment.TOP_CENTER,
        )
        show_result_actions(self.btn_folder, self.btn_resolve, visible=False)

    def _chrome_h(self) -> float:
        """Path + actions + padding under the video."""
        h = 20.0  # padding
        if self._show_path_row:
            h += 28.0
        if self._embed_actions:
            h += 48.0
        h += 12.0  # error/status slack
        return h

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
        """
        Size the player for full CONTAIN playback (no crop).

        When parent sets control.expand=True (Tools/Vision wide pane), drop fixed
        height so the video fills the area. Otherwise use a fixed preview height
        large enough for the frame + native controls.
        """
        try:
            parent_expands = bool(getattr(self.control, "expand", False))
            vid_h = max(200.0, self._height - 4)
            if parent_expands:
                self.control.height = None  # type: ignore[assignment]
                if self._video is not None:
                    self._video.fit = ft.BoxFit.CONTAIN
                    self._video.expand = True
                    try:
                        self._video.height = None  # type: ignore[assignment]
                    except Exception:
                        pass
            else:
                self.control.expand = False
                # Video area + chrome (path/actions) so controls are not clipped
                self.control.height = vid_h + self._chrome_h()
                if self._video is not None:
                    self._video.fit = ft.BoxFit.CONTAIN
                    self._video.height = vid_h
                    self._video.expand = False
                    try:
                        self._video.show_controls = True
                    except Exception:
                        pass
        except Exception:
            pass

    def clear(self) -> None:
        self.path = None
        self.path_text.value = "No video result yet."
        show_result_actions(self.btn_folder, self.btn_resolve, visible=False)
        if self._embed_actions:
            try:
                self.result_actions_row.visible = False
            except Exception:
                pass
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
        self.path_text.value = note or f"Saved: {Path(self.path).name}"
        if self._embed_actions:
            show_result_actions(self.btn_folder, self.btn_resolve, visible=True)
            try:
                self.result_actions_row.visible = True
            except Exception:
                pass
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
            self._video.fit = ft.BoxFit.CONTAIN
            try:
                self._video.show_controls = True
            except Exception:
                pass
            # Do not autoplay — user presses play
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
