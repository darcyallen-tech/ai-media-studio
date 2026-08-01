"""Reusable result actions: Show in folder + Send to Resolve + before/after."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import flet as ft

from media_studio.folder_util import show_in_folder
from media_studio.flet_dialogs import show_snack
from media_studio.flet_resolve_button import make_send_to_resolve_button
from media_studio.flet_theme import BORDER, PANEL_ELEVATED, TEXT


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


def make_before_after_button(
    page: ft.Page,
    *,
    get_before: Callable[[], str | None],
    get_after: Callable[[], str | None],
    get_output_dir: Callable[[], str],
    on_status: Callable[[str, bool], None] | None = None,
    get_job_name: Callable[[], str | None] | None = None,
) -> ft.Control:
    """
    Export before/after still composite (side-by-side or vertical stack).

    Hidden until the caller sets ``visible=True`` when both source + result exist.
    """

    async def _export(layout: str) -> None:
        import asyncio

        before = get_before() if get_before else None
        after = get_after() if get_after else None
        if not before or not Path(before).is_file():
            msg = "Export before/after needs a source still."
            if on_status:
                on_status(msg, True)
            try:
                show_snack(page, msg)
            except Exception:
                pass
            return
        if not after or not Path(after).is_file():
            msg = "Export before/after needs a result still — generate first."
            if on_status:
                on_status(msg, True)
            try:
                show_snack(page, msg)
            except Exception:
                pass
            return
        out = get_output_dir() if get_output_dir else ""
        if not out:
            msg = "No output folder set."
            if on_status:
                on_status(msg, True)
            return
        job = None
        if get_job_name:
            try:
                job = get_job_name()
            except Exception:
                job = None

        def _run():
            from media_studio.before_after import export_before_after
            from media_studio.job_context import job_name_scope

            with job_name_scope(job):
                return export_before_after(
                    before,
                    after,
                    output_dir=out,
                    layout="stack" if layout == "stack" else "side_by_side",
                    labels=True,
                    job_name=job,
                )

        try:
            result = await asyncio.to_thread(_run)
        except Exception as exc:
            msg = f"Before/after export failed: {exc}"
            if on_status:
                on_status(msg, True)
            try:
                show_snack(page, msg)
            except Exception:
                pass
            return

        ok = bool(getattr(result, "ok", False))
        msg = getattr(result, "status", None) or ("Exported." if ok else "Export failed.")
        if on_status:
            on_status(msg, not ok)
        try:
            show_snack(page, msg)
        except Exception:
            pass
        if ok and getattr(result, "path", None):
            try:
                from media_studio.folder_util import show_in_folder

                # Soft reveal so user can grab the file
                show_in_folder(result.path)
            except Exception:
                pass
        try:
            page.update()
        except Exception:
            pass

    async def _side(_e: ft.ControlEvent) -> None:
        await _export("side_by_side")

    async def _stack(_e: ft.ControlEvent) -> None:
        await _export("stack")

    menu = ft.PopupMenuButton(
        content=ft.Row(
            [
                ft.Icon(ft.Icons.COMPARE, size=16, color=TEXT),
                ft.Text("Export before/after ▾", size=13, color=TEXT),
            ],
            spacing=6,
            tight=True,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        items=[
            ft.PopupMenuItem(content="Side-by-side (labeled)", on_click=_side),
            ft.PopupMenuItem(content="Vertical stack (phone)", on_click=_stack),
        ],
        tooltip="Save a labeled before/after still (needs source + result)",
        menu_position=ft.PopupMenuPosition.UNDER,
    )
    btn = ft.Container(
        content=menu,
        bgcolor=PANEL_ELEVATED,
        border=ft.Border.all(1, BORDER),
        border_radius=6,
        padding=ft.Padding.symmetric(horizontal=10, vertical=6),
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
    before_after_btn: ft.Control | None = None,
) -> tuple[ft.Row, ft.OutlinedButton, ft.Control]:
    """
    Build a standard result row: [optional leading] Show in folder + Send to Resolve
    (+ optional before/after export control).

    Returns ``(row, folder_btn, resolve_btn)``. Buttons start hidden unless
    ``start_visible``; call ``show_result_actions`` after a successful generate.
    """
    folder_btn = make_show_in_folder_button(page, get_path=get_path, on_status=on_status)
    resolve_btn = make_send_to_resolve_button(page, get_path=get_path, on_status=on_status)
    if start_visible:
        folder_btn.visible = True
        resolve_btn.visible = True
    controls: list[ft.Control] = list(extra_leading or [])
    if before_after_btn is not None:
        controls.append(before_after_btn)
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
