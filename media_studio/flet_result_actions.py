"""Reusable result actions: Show in folder + Send to Resolve."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import flet as ft

from media_studio.folder_util import show_in_folder
from media_studio.flet_dialogs import show_snack
from media_studio.flet_resolve_button import make_send_to_resolve_button
from media_studio.flet_theme import BORDER, TEXT


def make_show_in_folder_button(
    page: ft.Page,
    *,
    get_path: Callable[[], str | None],
    on_status: Callable[[str, bool], None] | None = None,
) -> ft.OutlinedButton:
    """
    Reveal the current result file in the OS file manager.

    ``get_path`` returns the absolute media path (or None).
    ``on_status(message, is_error)`` optional UI callback.
    """

    async def _click(_e: ft.ControlEvent) -> None:
        path = get_path()
        if not path or not str(path).strip():
            msg = "Nothing to show — generate a result first."
            if on_status:
                on_status(msg, True)
            try:
                show_snack(page, msg)
            except Exception:
                pass
            return
        msg = show_in_folder(path)
        is_err = msg.lower().startswith("show in folder failed") or "not found" in msg.lower()
        if on_status:
            on_status(msg, is_err)
        try:
            show_snack(page, msg)
        except Exception:
            pass
        try:
            page.update()
        except Exception:
            pass

    btn = ft.OutlinedButton(
        content="Show in folder",
        icon=ft.Icons.FOLDER_OPEN,
        on_click=_click,
        style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
        tooltip="Reveal this file in Explorer / Finder",
        visible=False,
    )
    return btn


def make_result_action_row(
    page: ft.Page,
    *,
    get_path: Callable[[], str | None],
    on_status: Callable[[str, bool], None] | None = None,
    extra_leading: list[ft.Control] | None = None,
    start_visible: bool = False,
) -> tuple[ft.Row, ft.OutlinedButton, ft.Control]:
    """
    Build a standard result row: [optional leading] Show in folder + Send to Resolve.

    Returns ``(row, folder_btn, resolve_btn)``. Buttons start hidden unless
    ``start_visible``; call ``show_result_actions`` after a successful generate.
    """
    folder_btn = make_show_in_folder_button(page, get_path=get_path, on_status=on_status)
    resolve_btn = make_send_to_resolve_button(page, get_path=get_path, on_status=on_status)
    if start_visible:
        folder_btn.visible = True
        resolve_btn.visible = True
    controls: list[ft.Control] = list(extra_leading or [])
    controls.extend([folder_btn, resolve_btn])
    row = ft.Row(
        controls,
        spacing=8,
        wrap=True,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )
    return row, folder_btn, resolve_btn


def show_result_actions(*buttons: ft.Control | None, visible: bool = True) -> None:
    """Toggle visibility on one or more result-action buttons."""
    for btn in buttons:
        if btn is None:
            continue
        try:
            btn.visible = visible
        except Exception:
            pass


def result_path_exists(path: str | None) -> bool:
    if not path or not str(path).strip():
        return False
    try:
        return Path(path).expanduser().is_file()
    except OSError:
        return False
