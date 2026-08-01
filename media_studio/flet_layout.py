"""
Shared layout helpers — FixedRail + CapRightEmpty (LAYOUT_AUDIT_2026-08-01).

Left: fixed width, expand=False, ListView fills height only.
Right: expand=True horizontally; content Column is tight/content-sized when empty.
"""

from __future__ import annotations

from typing import Sequence

import flet as ft

from media_studio.flet_theme import BORDER, PANEL, RAIL_WIDTH


def make_left_rail(
    controls: Sequence[ft.Control],
    *,
    width: int | float = RAIL_WIDTH,
    bgcolor: str | None = PANEL,
    padding: int = 10,
    spacing: int = 8,
    border: bool = True,
) -> ft.Container:
    """
    Fixed-width controls rail. Horizontal expand is NEVER set on the rail.

    Only the inner ListView expands to fill the stretched row height so the
    user can scroll — empty PANEL is not created by Column(expand+scroll).
    """
    return ft.Container(
        width=float(width),
        expand=False,
        bgcolor=bgcolor,
        border=ft.Border.all(1, BORDER) if border else None,
        border_radius=8 if border else 0,
        padding=padding,
        content=ft.ListView(
            controls=list(controls),
            expand=True,
            spacing=spacing,
            padding=ft.Padding.only(right=4, bottom=16),
        ),
    )


def make_right_pane(
    content: ft.Control,
    *,
    padding: int = 10,
    bgcolor: str | None = PANEL,
    border: bool = True,
) -> ft.Container:
    """
    Flexible right pane. Host expands horizontally; pass a tight Column when
    empty so the pane does not paint a full-height void of nested expands.
    """
    return ft.Container(
        content=content,
        expand=True,
        alignment=ft.Alignment.TOP_LEFT,
        bgcolor=bgcolor,
        border=ft.Border.all(1, BORDER) if border else None,
        border_radius=8 if border else 0,
        padding=padding,
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
    )


def make_split_workspace(
    left_controls: Sequence[ft.Control],
    right_content: ft.Control,
    *,
    left_width: int | float = RAIL_WIDTH,
    left_bg: str = PANEL,
    left_padding: int = 10,
    left_spacing: int = 8,
    right_padding: int = 10,
    right_bg: str = PANEL,
    spacing: int = 12,
    left_border: bool = True,
    right_border: bool = True,
) -> ft.Row:
    """
    FixedRail + CapRightEmpty.

    ``right_content`` should be a Column with tight=True and expand=False when
    empty. When media is present, the caller may set expand=True on the stage
    (or rebuild right_content) so the preview fills remaining height.
    """
    left = make_left_rail(
        left_controls,
        width=left_width,
        bgcolor=left_bg,
        padding=left_padding,
        spacing=left_spacing,
        border=left_border,
    )
    right = make_right_pane(
        right_content,
        padding=right_padding,
        bgcolor=right_bg,
        border=right_border,
    )
    return ft.Row(
        [left, right],
        expand=True,
        spacing=spacing,
        vertical_alignment=ft.CrossAxisAlignment.STRETCH,
    )


def empty_preview_box(
    message: str = "Generate to preview",
    *,
    height: float | None = None,
) -> ft.Container:
    """Modest PANEL_ELEVATED placeholder — never expand."""
    from media_studio.flet_theme import EMPTY_PREVIEW_H, FONT_MD, PANEL_ELEVATED, TEXT_MUTED

    h = float(height if height is not None else EMPTY_PREVIEW_H)
    return ft.Container(
        content=ft.Text(
            message,
            size=FONT_MD,
            color=TEXT_MUTED,
            text_align=ft.TextAlign.CENTER,
        ),
        height=h,
        alignment=ft.Alignment.CENTER,
        bgcolor=PANEL_ELEVATED,
        border_radius=8,
        border=ft.Border.all(1, BORDER),
        expand=False,
    )
