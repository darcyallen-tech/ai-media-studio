"""Reusable “Send to Resolve” control for result panels."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import flet as ft

from media_studio.flet_dialogs import show_snack
from media_studio.flet_theme import BORDER, FONT_SM, TEXT, TEXT_MUTED
from media_studio.resolve_export import resolve_icon_path, send_file_to_resolve


def make_send_to_resolve_button(
    page: ft.Page,
    *,
    get_path: Callable[[], str | None],
    on_status: Callable[[str, bool], None] | None = None,
) -> ft.OutlinedButton:
    """
    Build a Send to Resolve button.

    ``get_path`` returns the absolute media path (or None).
    ``on_status(message, is_error)`` optional UI callback.
    """
    icon_path = resolve_icon_path()

    async def _click(_e: ft.ControlEvent) -> None:
        path = get_path()
        if not path or not Path(path).is_file():
            msg = "Nothing to send — generate or select a result first."
            if on_status:
                on_status(msg, True)
            try:
                show_snack(page, msg)
            except Exception:
                pass
            return

        btn.disabled = True
        try:
            page.update()
        except Exception:
            pass

        import asyncio

        result = await asyncio.to_thread(send_file_to_resolve, path)
        btn.disabled = False
        if on_status:
            on_status(result.message, not result.ok)
        try:
            show_snack(page, result.message)
        except Exception:
            pass
        try:
            page.update()
        except Exception:
            pass

    # Prefer image icon if available; else a simple play-mark style icon
    if icon_path:
        content = ft.Row(
            [
                ft.Image(src=icon_path, width=18, height=18, fit=ft.BoxFit.CONTAIN),
                ft.Text("Send to Resolve", size=FONT_SM, color=TEXT),
            ],
            spacing=8,
            tight=True,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        btn = ft.OutlinedButton(
            content=content,
            on_click=_click,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
            tooltip="Import into DaVinci Resolve Media Pool (Resolve must be open)",
            visible=False,
        )
    else:
        btn = ft.OutlinedButton(
            content="Send to Resolve",
            icon=ft.Icons.MOVIE_FILTER,
            on_click=_click,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
            tooltip="Import into DaVinci Resolve Media Pool (Resolve must be open)",
            visible=False,
        )
    return btn
