"""Dialog / snack helpers for Flet 0.86+ (no page.open)."""

from __future__ import annotations

import asyncio
import webbrowser
from typing import Any

import flet as ft

from media_studio.errors import (
    ContentPolicyInfo,
    CreditsErrorInfo,
    detect_content_policy_violation,
    detect_credits_error,
)
from media_studio.flet_theme import (
    ACCENT_BRIGHT,
    BORDER,
    FONT_SM,
    PANEL,
    PANEL_ELEVATED,
    TEXT,
    TEXT_DIM,
    TEXT_MUTED,
)


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


def maybe_show_generation_stopped_dialog(
    page: ft.Page | None,
    message: str | BaseException | None,
    *,
    context: str = "",
) -> ContentPolicyInfo | None:
    """
    If ``message`` is a content/policy rejection, show Generation stopped popup.

    Returns the structured info when a dialog was shown (also useful for status).
    Credits dialogs take precedence when both could match.
    """
    if page is None or message is None:
        return None
    # Don't steal the credits flow
    if detect_credits_error(message, context=context) is not None:
        return None
    info = detect_content_policy_violation(message, context=context)
    if info is None:
        return None
    show_generation_stopped_dialog(page, info)
    return info


def show_generation_stopped_dialog(
    page: ft.Page,
    info: ContentPolicyInfo,
) -> None:
    """
    Modal: Generation stopped — plain “because” reason + OK / Copy full error.
    Does not mark the job as success; caller keeps Est. cost / refs as-is.
    """

    def _close(_e: ft.ControlEvent | None = None) -> None:
        close_dialog(page, dlg)

    def _copy(_e: ft.ControlEvent) -> None:
        try:
            page.set_clipboard(info.full_error or info.short_reason)
            show_snack(page, "Full error copied.")
        except Exception:
            try:
                show_snack(page, "Could not copy to clipboard.")
            except Exception:
                pass

    body = ft.Column(
        [
            ft.Text(
                info.body,
                size=FONT_SM,
                color=TEXT,
                selectable=True,
            ),
            ft.Text(
                "This is a provider policy decision — not an app billing or bug issue.",
                size=FONT_SM,
                color=TEXT_MUTED,
            ),
        ],
        spacing=10,
        tight=True,
        width=440,
    )

    dlg = ft.AlertDialog(
        modal=True,
        bgcolor=PANEL,
        title=ft.Row(
            [
                ft.Icon(ft.Icons.BLOCK, color="#e57373", size=24),
                ft.Text("Generation stopped", color=TEXT, weight=ft.FontWeight.W_700),
            ],
            spacing=10,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        content=body,
        actions=[
            ft.TextButton(
                content="Copy full error",
                icon=ft.Icons.CONTENT_COPY,
                on_click=_copy,
                style=ft.ButtonStyle(color=TEXT_MUTED),
            ),
            ft.FilledButton(
                content="OK",
                on_click=_close,
                style=ft.ButtonStyle(bgcolor=ACCENT_BRIGHT, color=TEXT),
            ),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
        shape=ft.RoundedRectangleBorder(radius=10),
    )
    show_dialog(page, dlg)


def make_seedance_likeness_banner() -> ft.Container:
    """
    Short persistent hint under the model dropdown when Seedance R2V is selected.

    Not a blocking modal — toggle ``.visible`` from model/modality change.
    """
    return ft.Container(
        content=ft.Column(
            [
                ft.Row(
                    [
                        ft.Icon(ft.Icons.INFO_OUTLINE, size=16, color="#ffb74d"),
                        ft.Text(
                            "Seedance face filter",
                            size=FONT_SM,
                            color="#ffb74d",
                            weight=ft.FontWeight.W_600,
                        ),
                    ],
                    spacing=6,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Text(
                    "Seedance may reject photoreal people refs (partner face filter). "
                    "Stylized characters, costume plates, or character-sheet grids often "
                    "pass more reliably. Policy is on the provider side — not a bug in the app.",
                    size=FONT_SM,
                    color=TEXT_MUTED,
                ),
                ft.Text(
                    "Same filter can flag AI-generated faces that look like real photos.",
                    size=FONT_SM,
                    color=TEXT_DIM,
                    italic=True,
                    tooltip=(
                        "Partner face / likeness checks can also block AI-generated "
                        "stills that look photographic — not only real photos."
                    ),
                ),
            ],
            spacing=4,
            tight=True,
        ),
        visible=False,
        bgcolor=PANEL_ELEVATED,
        border=ft.Border.all(1, BORDER),
        border_radius=8,
        padding=ft.Padding.symmetric(horizontal=10, vertical=8),
        margin=ft.Margin.only(top=2, bottom=2),
    )


def set_seedance_likeness_banner_visible(
    banner: ft.Control | None,
    *,
    endpoint: str | None = None,
    model_choice: str | None = None,
) -> bool:
    """
    Show banner only for Seedance 2.0 reference-to-video models.
    Returns the new visibility.
    """
    if banner is None:
        return False
    show = False
    try:
        from media_studio.aspect_omit import is_seedance_reference_endpoint

        if is_seedance_reference_endpoint(endpoint):
            show = True
        elif model_choice:
            low = str(model_choice).lower()
            if "seedance" in low and (
                "reference" in low or "r2v" in low or "v2v" in low or "ref edit" in low
            ):
                show = True
    except Exception:
        show = False
    try:
        banner.visible = show
    except Exception:
        pass
    return show
