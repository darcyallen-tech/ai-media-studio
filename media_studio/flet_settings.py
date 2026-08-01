"""Settings dialog — API keys, storage path, caches, retention."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Callable

import flet as ft

from media_studio.billing import (
    fetch_fal_balance,
    fetch_runware_balance,
    xai_billing_label,
    xai_billing_url,
)
from media_studio.errors import FAL_TOPUP_URL
from media_studio.flet_dialogs import close_dialog, open_url_in_browser, show_dialog, show_snack
from media_studio.flet_theme import (
    ACCENT,
    ACCENT_BRIGHT,
    BORDER,
    FONT_SM,
    PANEL_ELEVATED,
    TEXT,
    TEXT_MUTED,
)
from media_studio.secrets_store import (
    apply_secrets_to_env,
    effective_fal_key,
    effective_runware_key,
    effective_xai_key,
    has_fal_key,
    has_runware_key,
    mask_key,
    save_secrets,
)
from media_studio.ui_prefs import (
    COST_CONFIRM_CHOICES,
    RETENTION_CHOICES,
    get_cost_confirm_usd,
    get_library_hide_missing,
    get_output_dir_pref,
    get_retention_days,
    set_cost_confirm_usd,
    set_library_hide_missing,
    set_output_dir_pref,
    set_retention_days,
)

_COST_CONFIRM_LABELS = {
    "off": "Off (no confirm)",
    "2": "Warn at ~$2+",
    "5": "Warn at ~$5+",
}

FAL_KEYS_URL = "https://fal.ai/dashboard/keys"
XAI_KEYS_URL = "https://console.x.ai/team/default/api-keys"
RUNWARE_KEYS_URL = "https://my.runware.ai/"
RUNWARE_BILLING_URL = "https://my.runware.ai/"

OnSaved = Callable[[], None]
OnOutputDirChanged = Callable[[str], None]

_RETENTION_LABELS = {
    "never": "Never (keep generation media)",
    "7": "7 days",
    "14": "14 days",
    "30": "30 days",
    "90": "90 days",
}


def _open_url(url: str) -> None:
    open_url_in_browser(url)


def _retention_value_to_key(days: int | None) -> str:
    if days is None:
        return "never"
    s = str(int(days))
    return s if s in RETENTION_CHOICES else "never"


def open_settings_dialog(
    page: ft.Page,
    *,
    on_saved: OnSaved | None = None,
    on_balance_refresh: Callable[[], None] | None = None,
    on_output_dir_changed: OnOutputDirChanged | None = None,
    current_output_dir: str | None = None,
    focus: str | None = None,
) -> None:
    """
    Settings modal: API keys, output folder, retention, clear caches.

    ``focus``: optional ``\"fal\"`` | ``\"xai\"`` | ``\"runware\"`` to highlight
    that provider's field (e.g. top-bar chip → Settings).
    """

    fal_set = has_fal_key()
    xai_set = bool(effective_xai_key())
    runware_set = has_runware_key()
    focus_key = (focus or "").strip().lower()

    fal_status = ft.Text(
        f"Status: saved · {mask_key(effective_fal_key())}" if fal_set else "Status: not set",
        size=FONT_SM,
        color=TEXT_MUTED,
    )
    xai_status = ft.Text(
        f"Status: saved · {mask_key(effective_xai_key())}" if xai_set else "Status: not set (optional)",
        size=FONT_SM,
        color=TEXT_MUTED,
    )
    runware_status = ft.Text(
        (
            f"Status: saved · {mask_key(effective_runware_key())}"
            if runware_set
            else "Status: not set (optional — Aleph only)"
        ),
        size=FONT_SM,
        color=TEXT_MUTED,
    )
    fal_balance_text = ft.Text("fal · …", size=FONT_SM, color=TEXT_MUTED)
    xai_balance_text = ft.Text(
        f"{xai_billing_label()} (no live balance via API key)",
        size=FONT_SM,
        color=TEXT_MUTED,
    )
    runware_balance_text = ft.Text(
        "Runware / Aleph · …",
        size=FONT_SM,
        color=TEXT_MUTED,
    )

    fal_field = ft.TextField(
        label="FAL API Key",
        hint_text="Paste key to set or replace" if fal_set else "Required — paste your fal key",
        password=True,
        can_reveal_password=True,
        dense=True,
        filled=True,
        fill_color=PANEL_ELEVATED,
        border_color=BORDER,
        color=TEXT,
        text_size=FONT_SM,
        autofocus=(focus_key == "fal") or (not fal_set and focus_key not in ("xai", "runware")),
    )
    xai_field = ft.TextField(
        label="xAI / Grok API Key (optional)",
        hint_text="Paste key to set or replace" if xai_set else "Optional — for Enhance / Grok text features",
        password=True,
        can_reveal_password=True,
        dense=True,
        filled=True,
        fill_color=PANEL_ELEVATED,
        border_color=BORDER,
        color=TEXT,
        text_size=FONT_SM,
        autofocus=(focus_key == "xai"),
    )
    runware_field = ft.TextField(
        label="Runware API Key (optional — Aleph 2.0 / Frame Editor)",
        hint_text=(
            "Paste key to set or replace"
            if runware_set
            else "Optional — only for Frame Editor / Aleph. Never used for fal Studio/Tools."
        ),
        password=True,
        can_reveal_password=True,
        dense=True,
        filled=True,
        fill_color=PANEL_ELEVATED,
        border_color=BORDER,
        color=TEXT,
        text_size=FONT_SM,
        autofocus=(focus_key == "runware"),
    )

    save_note = ft.Text(
        "Keys are stored only on this machine (local app data), not in the project folder. "
        "fal balance display needs an Admin-scoped fal key; generation works with a normal key.",
        size=FONT_SM,
        color=TEXT_MUTED,
    )
    error_text = ft.Text("", size=FONT_SM, color="#e57373", visible=False)
    handoff_status = ft.Text("", size=FONT_SM, color=TEXT_MUTED, max_lines=3)
    storage_status = ft.Text("", size=FONT_SM, color=TEXT_MUTED, max_lines=4)

    # --- Storage / disk safety (Phase E) ---
    from media_studio.config import OUTPUT_DIR

    initial_out = (
        (current_output_dir or "").strip()
        or (get_output_dir_pref() or "")
        or str(OUTPUT_DIR)
    )
    out_field = ft.TextField(
        label="Output folder",
        value=initial_out,
        hint_text="Where generations and caches are stored",
        dense=True,
        filled=True,
        fill_color=PANEL_ELEVATED,
        border_color=BORDER,
        color=TEXT,
        text_size=FONT_SM,
        expand=True,
    )
    ret_key = _retention_value_to_key(get_retention_days())
    retention_dd = ft.Dropdown(
        label="Library / outputs retention",
        value=ret_key,
        options=[
            ft.DropdownOption(key=k, text=_RETENTION_LABELS.get(k, k))
            for k in RETENTION_CHOICES
        ],
        dense=True,
        filled=True,
        fill_color=PANEL_ELEVATED,
        border_color=BORDER,
        color=TEXT,
        text_size=FONT_SM,
        width=280,
    )
    hide_missing_sw = ft.Switch(
        label="Hide missing media in Library",
        value=get_library_hide_missing(),
        active_color=ACCENT_BRIGHT,
    )
    _cost_pref = get_cost_confirm_usd()
    _cost_key = (
        "off"
        if _cost_pref is None
        else ("2" if abs(float(_cost_pref) - 2) < 0.01 else "5" if abs(float(_cost_pref) - 5) < 0.01 else "off")
    )
    if _cost_key not in COST_CONFIRM_CHOICES:
        _cost_key = "off"
    cost_confirm_dd = ft.Dropdown(
        label="Cost guard (expensive generates)",
        value=_cost_key,
        options=[
            ft.DropdownOption(key=k, text=_COST_CONFIRM_LABELS.get(k, k))
            for k in COST_CONFIRM_CHOICES
        ],
        dense=True,
        filled=True,
        fill_color=PANEL_ELEVATED,
        border_color=BORDER,
        color=TEXT,
        text_size=FONT_SM,
        width=280,
    )

    def _set_error(msg: str) -> None:
        error_text.value = msg
        error_text.visible = bool(msg)
        try:
            page.update()
        except Exception:
            pass

    def _persist_output_dir(path: str) -> None:
        p = (path or "").strip()
        if not p:
            return
        try:
            Path(p).mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        set_output_dir_pref(p)
        if on_output_dir_changed:
            try:
                on_output_dir_changed(p)
            except Exception:
                pass

    async def _browse_output(_e: ft.ControlEvent) -> None:
        from media_studio.flet_pickers import pick_folder

        chosen = await pick_folder(
            page,
            dialog_title="Choose output folder",
            initial_directory=out_field.value or initial_out,
        )
        if chosen:
            out_field.value = chosen
            _persist_output_dir(chosen)
            storage_status.value = f"Output folder saved: {chosen}"
            storage_status.color = TEXT_MUTED
            try:
                page.update()
            except Exception:
                pass

    def _on_out_blur(_e: ft.ControlEvent) -> None:
        _persist_output_dir(out_field.value or "")
        storage_status.value = "Output folder saved."
        storage_status.color = TEXT_MUTED
        try:
            page.update()
        except Exception:
            pass

    def _on_retention_change(_e: ft.ControlEvent) -> None:
        key = str(retention_dd.value or "never")
        set_retention_days(key)
        storage_status.value = f"Retention set to {_RETENTION_LABELS.get(key, key)}."
        storage_status.color = TEXT_MUTED
        try:
            page.update()
        except Exception:
            pass

    def _on_hide_missing_change(_e: ft.ControlEvent) -> None:
        set_library_hide_missing(bool(hide_missing_sw.value))
        storage_status.value = (
            "Library will hide missing media."
            if hide_missing_sw.value
            else "Library will show entries even if files are missing."
        )
        storage_status.color = TEXT_MUTED
        try:
            page.update()
        except Exception:
            pass

    def _on_cost_confirm_change(_e: ft.ControlEvent) -> None:
        key = str(cost_confirm_dd.value or "off")
        set_cost_confirm_usd(key)
        storage_status.value = f"Cost guard: {_COST_CONFIRM_LABELS.get(key, key)}."
        storage_status.color = TEXT_MUTED
        try:
            page.update()
        except Exception:
            pass

    async def _run_clear_caches() -> None:
        from media_studio.cache_prune import clear_app_caches

        storage_status.value = "Clearing caches…"
        storage_status.color = TEXT_MUTED
        try:
            page.update()
        except Exception:
            pass
        try:
            stats = await asyncio.to_thread(
                clear_app_caches, out_field.value or initial_out
            )
            storage_status.value = stats.summary() + " (app caches + handoff only)."
            storage_status.color = TEXT_MUTED
            try:
                show_snack(page, storage_status.value)
            except Exception:
                pass
        except Exception as exc:
            storage_status.value = f"Clear caches failed: {exc}"
            storage_status.color = "#e57373"
        try:
            page.update()
        except Exception:
            pass

    async def _confirm_clear_caches(_e: ft.ControlEvent) -> None:
        """Two-step confirm so we never wipe caches accidentally."""

        async def _yes(_ev: ft.ControlEvent) -> None:
            close_dialog(page, confirm)
            await _run_clear_caches()

        async def _no(_ev: ft.ControlEvent) -> None:
            close_dialog(page, confirm)

        confirm = ft.AlertDialog(
            modal=True,
            title=ft.Text("Clear caches?", color=TEXT),
            content=ft.Text(
                "This removes app-owned cache folders under your output root "
                "(_aleph_keyframes, _aleph_proxies, _region, _fal_upload, _previews) "
                "and Resolve handoff media under data/resolve_handoff/.\n\n"
                "Dated generation files (your outputs) are NOT deleted. "
                "Use retention policy for that.",
                size=FONT_SM,
                color=TEXT_MUTED,
            ),
            actions=[
                ft.TextButton(content="Cancel", on_click=_no),
                ft.FilledButton(
                    content="Clear caches",
                    on_click=_yes,
                    style=ft.ButtonStyle(bgcolor="#b33a3a", color=TEXT),
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        show_dialog(page, confirm)

    async def _apply_retention_now(_e: ft.ControlEvent) -> None:
        from media_studio.cache_prune import apply_retention

        storage_status.value = "Applying retention…"
        try:
            page.update()
        except Exception:
            pass
        try:
            days = get_retention_days()
            stats = await asyncio.to_thread(
                apply_retention,
                out_field.value or initial_out,
                retention_days=days,
            )
            storage_status.value = stats.summary()
            storage_status.color = TEXT_MUTED
            try:
                show_snack(page, storage_status.value)
            except Exception:
                pass
        except Exception as exc:
            storage_status.value = f"Retention failed: {exc}"
            storage_status.color = "#e57373"
        try:
            page.update()
        except Exception:
            pass

    async def _clear_handoff_cache(_e: ft.ControlEvent) -> None:
        """Delete only under data/resolve_handoff/ (never outside)."""
        try:
            from media_studio.resolve_import import (
                HANDOFF_DIR,
                purge_handoff_cache,
            )

            result = await asyncio.to_thread(
                lambda: purge_handoff_cache(force=True)
            )
            n = int(result.get("deleted") or 0)
            err = int(result.get("errors") or 0)
            handoff_status.value = (
                f"Cleared handoff cache: removed {n} file(s)"
                + (f", {err} error(s)" if err else "")
                + f" under {HANDOFF_DIR.name}/"
            )
            handoff_status.color = TEXT_MUTED
            try:
                show_snack(page, handoff_status.value)
            except Exception:
                pass
        except Exception as exc:
            handoff_status.value = f"Clear failed: {exc}"
            handoff_status.color = "#e57373"
        try:
            page.update()
        except Exception:
            pass

    out_field.on_blur = _on_out_blur
    retention_dd.on_change = _on_retention_change
    hide_missing_sw.on_change = _on_hide_missing_change
    cost_confirm_dd.on_change = _on_cost_confirm_change

    async def _refresh_fal_balance(_e: ft.ControlEvent | None = None) -> None:
        fal_balance_text.value = "fal · refreshing…"
        try:
            page.update()
        except Exception:
            pass
        bal = await asyncio.to_thread(fetch_fal_balance)
        fal_balance_text.value = bal.label
        fal_balance_text.tooltip = bal.detail or bal.label
        fal_balance_text.color = TEXT if bal.ok else TEXT_MUTED
        try:
            page.update()
        except Exception:
            pass
        if on_balance_refresh:
            try:
                on_balance_refresh()
            except Exception:
                pass

    async def _refresh_runware_balance(_e: ft.ControlEvent | None = None) -> None:
        runware_balance_text.value = "Runware · …"
        try:
            page.update()
        except Exception:
            pass
        bal = await asyncio.to_thread(fetch_runware_balance)
        runware_balance_text.value = bal.label
        runware_balance_text.tooltip = bal.detail or bal.label
        runware_balance_text.color = TEXT if bal.ok else TEXT_MUTED
        try:
            page.update()
        except Exception:
            pass
        if on_balance_refresh:
            try:
                on_balance_refresh()
            except Exception:
                pass

    async def _on_save(_e: ft.ControlEvent) -> None:
        fal_in = (fal_field.value or "").strip()
        xai_in = (xai_field.value or "").strip()
        runware_in = (runware_field.value or "").strip()

        # Empty fields keep existing keys; require FAL either already set or provided
        if not fal_in and not has_fal_key():
            _set_error("FAL API key is required. Paste your key from fal.ai to continue.")
            return

        try:
            save_secrets(
                fal_key=fal_in if fal_in else None,
                xai_api_key=xai_in if xai_in else None,
                runware_key=runware_in if runware_in else None,
            )
            apply_secrets_to_env()
        except OSError as exc:
            _set_error(f"Could not save keys: {exc}")
            return

        # Persist storage prefs as well (path / retention may have been typed without blur)
        _persist_output_dir(out_field.value or "")
        set_retention_days(str(retention_dd.value or "never"))
        set_library_hide_missing(bool(hide_missing_sw.value))
        set_cost_confirm_usd(str(cost_confirm_dd.value or "off"))

        # Clear fields so the full key is never left visible in the UI
        fal_field.value = ""
        xai_field.value = ""
        runware_field.value = ""
        fal_status.value = f"Status: saved · {mask_key(effective_fal_key())}"
        xai_status.value = (
            f"Status: saved · {mask_key(effective_xai_key())}"
            if effective_xai_key()
            else "Status: not set (optional)"
        )
        runware_status.value = (
            f"Status: saved · {mask_key(effective_runware_key())}"
            if effective_runware_key()
            else "Status: not set (optional — Aleph only)"
        )
        _set_error("")

        close_dialog(page, dialog)
        try:
            show_snack(page, "Settings saved on this machine.")
        except Exception:
            pass
        if on_saved:
            try:
                on_saved()
            except Exception:
                pass
        if on_balance_refresh:
            try:
                on_balance_refresh()
            except Exception:
                pass

    async def _on_close(_e: ft.ControlEvent) -> None:
        close_dialog(page, dialog)

    content = ft.Column(
        [
            ft.Text(
                "API keys for this machine only. Nothing is shipped with the app.",
                size=FONT_SM,
                color=TEXT_MUTED,
            ),
            ft.Divider(height=1, color=BORDER),
            # Credits (quiet)
            ft.Text("Credits", size=FONT_SM, weight=ft.FontWeight.W_700, color=TEXT),
            ft.Row(
                [
                    fal_balance_text,
                    ft.TextButton(
                        content="Refresh",
                        on_click=_refresh_fal_balance,
                        style=ft.ButtonStyle(color=ACCENT_BRIGHT),
                    ),
                    ft.TextButton(
                        content="Top up fal",
                        on_click=lambda _e: _open_url(FAL_TOPUP_URL),
                        style=ft.ButtonStyle(color=TEXT_MUTED),
                    ),
                ],
                spacing=4,
                wrap=True,
            ),
            ft.Row(
                [
                    xai_balance_text,
                    ft.TextButton(
                        content="xAI billing",
                        on_click=lambda _e: _open_url(xai_billing_url()),
                        style=ft.ButtonStyle(color=ACCENT_BRIGHT),
                    ),
                ],
                spacing=4,
                wrap=True,
            ),
            ft.Divider(height=1, color=BORDER),
            # FAL
            ft.Text("1. FAL API Key", size=FONT_SM, weight=ft.FontWeight.W_700, color=TEXT),
            ft.Text(
                "Required for image, video, tools, Creative Vision, and most audio. "
                "To show balance in the top bar, use an Admin-scoped fal key "
                "(generation works with a normal key).",
                size=FONT_SM,
                color=TEXT_MUTED,
            ),
            fal_field,
            fal_status,
            ft.TextButton(
                content="Get a fal key → fal.ai/dashboard/keys",
                on_click=lambda _e: _open_url(FAL_KEYS_URL),
                style=ft.ButtonStyle(color=ACCENT_BRIGHT),
            ),
            ft.Divider(height=1, color=BORDER),
            # xAI
            ft.Text("2. xAI / Grok API Key", size=FONT_SM, weight=ft.FontWeight.W_700, color=TEXT),
            ft.Text(
                "Optional. Only needed for Grok text features (e.g. Enhance Prompt). "
                "Grok Imagine / Grok TTS on fal use your FAL key.",
                size=FONT_SM,
                color=TEXT_MUTED,
            ),
            xai_field,
            xai_status,
            ft.TextButton(
                content="Get an xAI key → console.x.ai",
                on_click=lambda _e: _open_url(XAI_KEYS_URL),
                style=ft.ButtonStyle(color=ACCENT_BRIGHT),
            ),
            ft.Divider(height=1, color=BORDER),
            # Runware / Aleph (optional second provider)
            ft.Container(
                content=ft.Column(
                    [
                        ft.Text(
                            "3. Runware API Key (optional — Frame Editor / Aleph)",
                            size=FONT_SM,
                            weight=ft.FontWeight.W_700,
                            color=TEXT,
                        ),
                        ft.Text(
                            "Optional second provider. Only for Frame Editor (Aleph 2.0). "
                            "Never routes fal models. Normal Studio / Tools / Audio work without this key.",
                            size=FONT_SM,
                            color=TEXT_MUTED,
                        ),
                        runware_field,
                        runware_status,
                        ft.Row(
                            [
                                runware_balance_text,
                                ft.TextButton(
                                    content="Refresh",
                                    on_click=_refresh_runware_balance,
                                    style=ft.ButtonStyle(color=ACCENT_BRIGHT),
                                ),
                                ft.TextButton(
                                    content="Runware billing",
                                    on_click=lambda _e: _open_url(RUNWARE_BILLING_URL),
                                    style=ft.ButtonStyle(color=TEXT_MUTED),
                                ),
                            ],
                            spacing=4,
                            wrap=True,
                        ),
                        ft.TextButton(
                            content="Get a Runware key → my.runware.ai",
                            on_click=lambda _e: _open_url(RUNWARE_KEYS_URL),
                            style=ft.ButtonStyle(color=ACCENT_BRIGHT),
                        ),
                    ],
                    spacing=6,
                    tight=True,
                ),
                border=ft.Border.all(1, ACCENT if focus_key == "runware" else BORDER)
                if focus_key == "runware"
                else None,
                border_radius=8,
                padding=8 if focus_key == "runware" else 0,
            ),
            ft.Divider(height=1, color=BORDER),
            # Storage / disk safety (Phase E)
            ft.Text(
                "4. Storage & disk safety",
                size=FONT_SM,
                weight=ft.FontWeight.W_700,
                color=TEXT,
            ),
            ft.Text(
                "Output folder is remembered across sessions. Caches live under that "
                "folder (filmstrip, proxies, uploads). Retention only deletes old "
                "app outputs — never files outside the output/handoff roots.",
                size=FONT_SM,
                color=TEXT_MUTED,
            ),
            ft.Row(
                [
                    out_field,
                    ft.OutlinedButton(
                        content="Browse…",
                        on_click=_browse_output,
                        style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
                    ),
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            retention_dd,
            hide_missing_sw,
            cost_confirm_dd,
            ft.Text(
                "Cost guard asks before Creative Vision (and similar) when the "
                "estimate exceeds the threshold. Default off.",
                size=FONT_SM,
                color=TEXT_MUTED,
            ),
            storage_status,
            ft.Row(
                [
                    ft.OutlinedButton(
                        content="Clear caches…",
                        icon=ft.Icons.CLEANING_SERVICES_OUTLINED,
                        on_click=_confirm_clear_caches,
                        style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
                    ),
                    ft.TextButton(
                        content="Apply retention now",
                        on_click=_apply_retention_now,
                        style=ft.ButtonStyle(color=ACCENT_BRIGHT),
                    ),
                ],
                spacing=8,
                wrap=True,
            ),
            ft.Divider(height=1, color=BORDER),
            # Resolve handoff cache (Phase A retention)
            ft.Text(
                "Resolve handoff cache",
                size=FONT_SM,
                weight=ft.FontWeight.W_700,
                color=TEXT,
            ),
            ft.Text(
                "Stills/JSON from DaVinci “Send to AI Media Studio” live under "
                "data/resolve_handoff/. Old files auto-purge (7 days / max ~200). "
                "Clear only deletes inside that folder.",
                size=FONT_SM,
                color=TEXT_MUTED,
            ),
            handoff_status,
            ft.TextButton(
                content="Clear handoff cache",
                icon=ft.Icons.DELETE_OUTLINE,
                on_click=_clear_handoff_cache,
                style=ft.ButtonStyle(color=TEXT_MUTED),
            ),
            ft.Divider(height=1, color=BORDER),
            save_note,
            error_text,
        ],
        spacing=8,
        tight=True,
        scroll=ft.ScrollMode.AUTO,
        width=520,
    )

    dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text("Settings", color=TEXT),
        content=content,
        actions=[
            ft.TextButton(content="Close", on_click=_on_close),
            ft.FilledButton(
                content="Save keys",
                on_click=_on_save,
                style=ft.ButtonStyle(bgcolor=ACCENT_BRIGHT, color=TEXT),
            ),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )

    show_dialog(page, dialog)
    # Load fal balance quietly when the dialog opens
    try:
        page.run_task(_refresh_fal_balance)
    except Exception:
        try:
            asyncio.get_event_loop().create_task(_refresh_fal_balance())
        except Exception:
            pass
