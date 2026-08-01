"""
Reusable “Previously used” + “From Resolve” source strips for Studio / Tools.

Shows last ~5–8 thumbs; click loads the path via callback.
Tight rows only — no expand voids, no nested scroll layers beyond the strip Row.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Literal

import flet as ft

from media_studio.flet_theme import BORDER, FONT_SM, PANEL_ELEVATED, TEXT, TEXT_MUTED
from media_studio.source_history import (
    SOURCE_HISTORY_MAX,
    load_source_paths,
    record_source,
)

MediaKind = Literal["image", "video", "both"]

LoadCallback = Callable[[str], None]

_VIDEO_EXTS = {".mp4", ".mov", ".webm", ".m4v", ".avi", ".mkv"}


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


class ResolveSourcesStrip:
    """
    Compact “From Resolve” strip under Previously used.

    Image tools: stills from Resolve handoff JSON / video-history stills.
    Video tools: ``load_resolve_video_history()`` clips (same as Studio Video).
    Frame Editor: ``both`` — stills (→ pin) + clips (→ source video).
    """

    def __init__(
        self,
        page: ft.Page,
        *,
        on_load: LoadCallback,
        media_kind: MediaKind = "image",
        max_items: int = 8,
        empty_hint: str | None = None,
    ) -> None:
        self.page = page
        self.on_load = on_load
        if media_kind not in ("image", "video", "both"):
            media_kind = "image"
        self.media_kind: MediaKind = media_kind
        self.max_items = max_items
        self.empty_hint = empty_hint
        # Room for thumb + short label under it (tight — no flex voids)
        self.row = ft.Row(spacing=6, scroll=ft.ScrollMode.AUTO, height=68)
        self.label = ft.Text("From Resolve", size=FONT_SM, color=TEXT_MUTED)
        self.root = ft.Column(
            [self.label, self.row],
            spacing=2,
            tight=True,
        )
        self.refresh()

    def set_media_kind(self, kind: MediaKind) -> None:
        if kind not in ("image", "video", "both"):
            kind = "image"
        if kind == self.media_kind:
            return
        self.media_kind = kind
        self.refresh()

    def refresh(self) -> None:
        paths: list[tuple[str, str]] = []  # (path, label)
        try:
            if self.media_kind == "video":
                from media_studio.resolve_import import load_resolve_video_history

                for ent in load_resolve_video_history()[: self.max_items]:
                    paths.append((ent.path, ent.clip_name or Path(ent.path).name))
            elif self.media_kind == "both":
                # Stills + clips for Frame Editor; videos first (source), then stills (pins)
                from media_studio.resolve_import import (
                    load_resolve_still_history,
                    load_resolve_video_history,
                )

                seen: set[str] = set()
                half = max(2, self.max_items // 2)
                for ent in load_resolve_video_history()[:half]:
                    key = ent.path.lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    paths.append((ent.path, ent.clip_name or Path(ent.path).name))
                for ent in load_resolve_still_history(limit=self.max_items):
                    if len(paths) >= self.max_items:
                        break
                    key = ent.path.lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    paths.append((ent.path, ent.clip_name or Path(ent.path).name))
            else:
                from media_studio.resolve_import import load_resolve_still_history

                for ent in load_resolve_still_history(limit=self.max_items):
                    paths.append((ent.path, ent.clip_name or Path(ent.path).name))
        except Exception:
            paths = []

        if paths:
            self.row.controls = [self._thumb(p, lab) for p, lab in paths]
        else:
            if self.empty_hint:
                hint = self.empty_hint
            elif self.media_kind == "video":
                hint = "Import from Resolve or send a clip from the plugin"
            elif self.media_kind == "both":
                hint = "Import from Resolve or send from the plugin"
            else:
                hint = "Import from Resolve or send a still from the plugin"
            self.row.controls = [
                ft.Text(hint, size=FONT_SM, color=TEXT_MUTED, max_lines=2)
            ]

    def _thumb(self, path: str, label: str) -> ft.Control:
        is_video = Path(path).suffix.lower() in _VIDEO_EXTS
        content: ft.Control
        if is_video:
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
                    bgcolor=PANEL_ELEVATED,
                )
        else:
            content = ft.Image(src=path, fit=ft.BoxFit.COVER, width=48, height=48)

        short = label if len(label) <= 14 else label[:11] + "…"

        def make_handler(pp: str):
            async def _click(_e: ft.ControlEvent) -> None:
                try:
                    self.on_load(pp)
                except Exception:
                    pass

            return _click

        return ft.Container(
            content=ft.Column(
                [
                    content,
                    ft.Text(
                        short,
                        size=10,
                        color=TEXT,
                        max_lines=1,
                        overflow=ft.TextOverflow.ELLIPSIS,
                        width=48,
                        text_align=ft.TextAlign.CENTER,
                    ),
                ],
                spacing=1,
                tight=True,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            border_radius=4,
            border=ft.Border.all(1, BORDER),
            padding=2,
            on_click=make_handler(path),
            tooltip=f"From Resolve: {label}\n{path}",
            ink=True,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
        )
