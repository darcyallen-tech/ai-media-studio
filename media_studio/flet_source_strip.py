"""
Reusable “Previously used” source strip for Studio Image and Tools panels.

Shows last ~5 thumbs; click loads the path via callback.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Literal

import flet as ft

from media_studio.flet_theme import BORDER, FONT_SM, TEXT_MUTED
from media_studio.source_history import (
    SOURCE_HISTORY_MAX,
    load_source_paths,
    record_source,
)

MediaKind = Literal["image", "video"]

LoadCallback = Callable[[str], None]


class PreviousSourcesStrip:
    """
    Compact horizontal strip of recent sources.

    ``media_kind`` filters images vs videos. ``on_load(path)`` is called when
    the user clicks a thumb (sync or async-safe — caller handles asyncio).
    """

    def __init__(
        self,
        page: ft.Page,
        *,
        get_output_dir: Callable[[], str],
        on_load: LoadCallback,
        media_kind: MediaKind = "image",
        max_items: int = SOURCE_HISTORY_MAX,
    ) -> None:
        self.page = page
        self.get_output_dir = get_output_dir
        self.on_load = on_load
        self.media_kind: MediaKind = media_kind
        self.max_items = max_items
        self.row = ft.Row(spacing=6, scroll=ft.ScrollMode.AUTO, height=52)
        self.label = ft.Text("Previously used", size=FONT_SM, color=TEXT_MUTED)
        self.root = ft.Column(
            [self.label, self.row],
            spacing=2,
            tight=True,
        )
        self.refresh()

    def set_media_kind(self, kind: MediaKind) -> None:
        if kind not in ("image", "video"):
            kind = "image"
        if kind == self.media_kind:
            return
        self.media_kind = kind
        self.refresh()

    def record_and_refresh(self, path: str | None) -> None:
        """Record a loaded source and rebuild thumbs."""
        if path:
            try:
                record_source(
                    path,
                    self.get_output_dir(),
                    media_kind=self.media_kind,
                )
            except Exception:
                pass
        self.refresh()

    def refresh(self) -> None:
        try:
            paths = load_source_paths(
                self.get_output_dir(),
                media_kind=self.media_kind,
                limit=self.max_items,
            )
        except Exception:
            paths = []
        thumbs: list[ft.Control] = []
        for p in paths:
            thumbs.append(self._thumb(p))
        if thumbs:
            self.row.controls = thumbs
        else:
            empty = (
                "No previous videos yet"
                if self.media_kind == "video"
                else "No previous sources yet"
            )
            self.row.controls = [
                ft.Text(empty, size=FONT_SM, color=TEXT_MUTED)
            ]

    def _thumb(self, path: str) -> ft.Control:
        is_video = Path(path).suffix.lower() in {
            ".mp4",
            ".mov",
            ".webm",
            ".m4v",
            ".avi",
            ".mkv",
        }
        content: ft.Control
        if is_video:
            # Prefer poster if available; else icon
            try:
                from media_studio.media import video_poster_path

                poster = video_poster_path(path)
            except Exception:
                poster = None
            if poster and Path(poster).is_file():
                content = ft.Image(
                    src=poster, fit=ft.BoxFit.COVER, width=48, height=48
                )
            else:
                content = ft.Container(
                    content=ft.Icon(ft.Icons.MOVIE, color=TEXT_MUTED, size=22),
                    width=48,
                    height=48,
                    alignment=ft.Alignment.CENTER,
                    bgcolor="#1a1d24",
                )
        else:
            content = ft.Image(src=path, fit=ft.BoxFit.COVER, width=48, height=48)

        def make_handler(pp: str):
            async def _click(_e: ft.ControlEvent) -> None:
                try:
                    self.on_load(pp)
                except Exception:
                    pass

            return _click

        return ft.Container(
            content=content,
            width=48,
            height=48,
            border_radius=4,
            border=ft.Border.all(1, BORDER),
            on_click=make_handler(path),
            tooltip=Path(path).name,
            ink=True,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
        )
