"""Dialog / snack helpers for Flet 0.86+ (no page.open)."""

from __future__ import annotations

import asyncio
import webbrowser
from typing import Any

import flet as ft

from media_studio.errors import CreditsErrorInfo, detect_credits_error
from media_studio.flet_theme import ACCENT_BRIGHT, FONT_SM, PANEL, TEXT, TEXT_MUTED


def show_dialog(page: ft.Page, dialog: ft.Control) -> None:
    """
    Open a DialogControl (AlertDialog, SnackBar, …) on Flet 0.86+.

    Uses page.show_dialog; falls back to overlay + open flag if needed.
    """
    show = getattr(page, "show_dialog", None)
    if callable(show):
        # Re-open: if still on the stack, close first
        try:
            show(dialog)
        except RuntimeError:
            pop = getattr(page, "pop_dialog", None)
            if callable(pop):
                try:
                    pop()
                except Exception:
                    pass
            try:
                if getattr(dialog, "open", False):
                    dialog.open = False
            except Exception:
                pass
            show(dialog)
    else:
        # Legacy / alternate: put on overlay and set open
        overlay = getattr(page, "overlay", None)
        if overlay is not None and dialog not in overlay:
            overlay.append(dialog)
        try:
            dialog.open = True
        except Exception:
            pass
    try:
        page.update()
    except Exception:
        pass


def close_dialog(page: ft.Page, dialog: ft.Control | None = None) -> None:
    """Close the top dialog (or a specific one)."""
    pop = getattr(page, "pop_dialog", None)
    if callable(pop):
        try:
            pop()
        except Exception:
            pass
    if dialog is not None:
        try:
            dialog.open = False
        except Exception:
            pass
    try:
        page.update()
    except Exception:
        pass


def show_snack(page: ft.Page, message: str, *, duration_ms: int = 3500) -> None:
    """Show a short SnackBar message (SnackBar is a DialogControl in Flet 0.86)."""
    bar = ft.SnackBar(
        content=ft.Text(message),
        duration=duration_ms,
        show_close_icon=True,
    )
    show_dialog(page, bar)


async def confirm_cost_if_needed(
    page: ft.Page,
    *,
    estimated_usd: float,
    job_label: str = "this generate",
) -> bool:
    """
    Optional cost guard (Phase F). Returns True to proceed, False if cancelled.

    Threshold comes from Settings (off / $2 / $5). Default is off.
    """
    try:
        from media_studio.ui_prefs import get_cost_confirm_usd

        threshold = get_cost_confirm_usd()
    except Exception:
        threshold = None
    if threshold is None:
        return True
    try:
        est = float(estimated_usd)
    except (TypeError, ValueError):
        return True
    if est < float(threshold):
        return True

    loop = asyncio.get_running_loop()
    fut: asyncio.Future[bool] = loop.create_future()

    async def _yes(_e: ft.ControlEvent) -> None:
        close_dialog(page, dialog)
        if not fut.done():
            fut.set_result(True)

    async def _no(_e: ft.ControlEvent) -> None:
        close_dialog(page, dialog)
        if not fut.done():
            fut.set_result(False)

    dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text("Confirm higher-cost generate?", color=TEXT),
        content=ft.Text(
            f"Estimated cost for {job_label} is about ${est:.2f} "
            f"(your warn threshold is ${float(threshold):.0f}+).\n\n"
            "Continue? You can turn this off in Settings → Storage.",
            size=FONT_SM,
            color=TEXT_MUTED,
        ),
        actions=[
            ft.TextButton(content="Cancel", on_click=_no),
            ft.FilledButton(
                content="Generate anyway",
                on_click=_yes,
                style=ft.ButtonStyle(bgcolor=ACCENT_BRIGHT, color=TEXT),
            ),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )
    show_dialog(page, dialog)
    try:
        return bool(await fut)
    except Exception:
        return True


def open_url_in_browser(url: str) -> None:
    """Open an https URL in the default browser (best-effort)."""
    u = (url or "").strip()
    if not u:
        return
    try:
        webbrowser.open(u)
    except Exception:
        pass


def maybe_show_credits_dialog(
    page: ft.Page | None,
    message: str | BaseException | None,
    *,
    context: str = "",
) -> bool:
    """
    If ``message`` is an insufficient-credits error, show the top-up modal.

    Returns True when a dialog was shown.
    """
    if page is None or message is None:
        return False
    info = detect_credits_error(message, context=context)
    if info is None:
        return False
    show_insufficient_credits_dialog(page, info)
    return True


def show_insufficient_credits_dialog(
    page: ft.Page,
    info: CreditsErrorInfo,
) -> None:
    """
    Modal: Insufficient credits + Top up [provider] + Dismiss.
    """

    def _close(_e: ft.ControlEvent | None = None) -> None:
        close_dialog(page, dlg)

    def _top_up(_e: ft.ControlEvent) -> None:
        open_url_in_browser(info.topup_url)
        close_dialog(page, dlg)
        try:
            show_snack(page, f"Opened {info.provider_label} billing in your browser.")
        except Exception:
            pass

    body = ft.Column(
        [
            ft.Text(
                info.message,
                size=FONT_SM,
                color=TEXT,
                selectable=True,
            ),
            ft.Text(
                "You can also review keys in Settings (gear icon).",
                size=FONT_SM,
                color=TEXT_MUTED,
            ),
        ],
        spacing=10,
        tight=True,
        width=420,
    )

    dlg = ft.AlertDialog(
        modal=True,
        bgcolor=PANEL,
        title=ft.Row(
            [
                ft.Icon(ft.Icons.ACCOUNT_BALANCE_WALLET, color="#ffb74d", size=24),
                ft.Text("Insufficient credits", color=TEXT, weight=ft.FontWeight.W_700),
            ],
            spacing=10,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        content=body,
        actions=[
            ft.TextButton(
                content="Dismiss",
                on_click=_close,
                style=ft.ButtonStyle(color=TEXT_MUTED),
            ),
            ft.FilledButton(
                content=info.topup_button_label,
                icon=ft.Icons.OPEN_IN_NEW,
                on_click=_top_up,
                style=ft.ButtonStyle(bgcolor=ACCENT_BRIGHT, color=TEXT),
            ),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
        shape=ft.RoundedRectangleBorder(radius=10),
    )
    show_dialog(page, dlg)
