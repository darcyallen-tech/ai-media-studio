"""
First-run onboarding + Help → Quick Start (modal wizard).

No coach marks / spotlight tours — short multi-step dialog only.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Callable

import flet as ft

from media_studio.config import PROJECT_ROOT
from media_studio.flet_dialogs import close_dialog, open_url_in_browser, show_dialog, show_snack
from media_studio.flet_theme import (
    ACCENT_BRIGHT,
    BORDER,
    FONT_SM,
    PANEL_ELEVATED,
    TEXT,
    TEXT_MUTED,
)
from media_studio.ui_prefs import get_onboarding_done, set_onboarding_done

FAL_KEYS_URL = "https://fal.ai/dashboard/keys"
XAI_KEYS_URL = "https://console.x.ai/team/default/api-keys"
RUNWARE_KEYS_URL = "https://my.runware.ai/"

# (title, body markdown-ish plain text)
_STEPS: list[tuple[str, str]] = [
    (
        "Welcome",
        "AI Media Studio is a real-estate–focused AI workbench for listing stills, "
        "video, and audio — stage empties, clean clips, generate Foley, and ship "
        "results to DaVinci Resolve.\n\n"
        "Pay-per-use via fal.ai (and optional xAI / Runware). Nothing is billed "
        "until you hit Generate.",
    ),
    (
        "API keys",
        "Open Settings (gear) and paste keys for this machine only — never committed "
        "to the project folder.\n\n"
        "• fal — required for almost all generation (Studio, Tools, Vision, Audio, "
        "Frame Editor 1080p proxy). Get a key at fal.ai/dashboard/keys. "
        "Top-bar balance needs an Admin-scoped fal key; a normal key still generates.\n"
        "• xAI / Grok — optional, for Enhance Prompt and QC.\n"
        "• Runware — optional, Frame Editor / Aleph only (never fal Studio/Tools).\n\n"
        "Grok Imagine models on fal still use your fal key.",
    ),
    (
        "Studio",
        "Studio is the listing workflow: shared scenarios (furniture pop-in, "
        "day→night, twilight, …) plus Image and Video.\n\n"
        "Image — full-frame edit or Region boxes (Seedream annotation). "
        "Video — Received / Blank / Camera Lock for camera-locked moves. "
        "Generate, compare, then Send to Resolve or Library.",
    ),
    (
        "Tools",
        "Tools split into Image tools and Video tools with a large result pane.\n\n"
        "Still utilities: upscale, clutter remove, sky, dehaze, restore, blown-out "
        "windows, mirror/glass, amenity, season, match look, re-aspect.\n"
        "Video utilities: upscale (Topaz families), Denoise / Clean (Nyx / Artemis), "
        "Slow Mo / Interpolate (RIFE / FILM), V2V cleanup and more.",
    ),
    (
        "Frame Editor",
        "Keyframe-guided video edit with Aleph 2.0 via Runware (separate key).\n\n"
        "Load a clip → filmstrip samples frames → pin up to five keyframes → "
        "optionally send a frame to Studio for cleanup → Generate to propagate "
        "the look through the shot. Optional fal 1080p proxy before Aleph.",
    ),
    (
        "Resolve (optional)",
        "Studio → Resolve: Send to Resolve on results (bin AI Media Studio / Job or date; "
        "External scripting = Local).\n\n"
        "Resolve → Studio: install resolve_scripts/Send_to_AI_Media_Studio.py, "
        "open this app once so the studio path is registered, then "
        "Workspace → Scripts → Send_to_AI_Media_Studio. "
        "Prefer Render in Place before send. Details in README.md.",
    ),
]


def _open_features_txt(page: ft.Page | None = None) -> None:
    """Open FEATURES.txt with the OS default app."""
    path = PROJECT_ROOT / "FEATURES.txt"
    if not path.is_file():
        if page is not None:
            try:
                show_snack(page, "FEATURES.txt not found next to the app.")
            except Exception:
                pass
        return
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=False)
        else:
            subprocess.run(["xdg-open", str(path)], check=False)
        if page is not None:
            try:
                show_snack(page, f"Opened {path.name}")
            except Exception:
                pass
    except Exception as exc:
        if page is not None:
            try:
                show_snack(page, f"Could not open FEATURES.txt: {exc}")
            except Exception:
                pass


def open_onboarding_dialog(
    page: ft.Page,
    *,
    force: bool = False,
    on_open_settings: Callable[[], None] | None = None,
) -> None:
    """
    Multi-step Quick Start modal.

    Auto-shown when ``force`` is False and onboarding is not marked done.
    Help → Quick Start passes ``force=True``.
    """
    if not force and get_onboarding_done():
        return

    step_i = {"i": 0}
    title = ft.Text(_STEPS[0][0], color=TEXT, weight=ft.FontWeight.W_700)
    body = ft.Text(
        _STEPS[0][1],
        size=FONT_SM,
        color=TEXT_MUTED,
        selectable=True,
    )
    progress = ft.Text(
        f"Step 1 of {len(_STEPS)}",
        size=FONT_SM,
        color=TEXT_MUTED,
    )
    dont_show = ft.Checkbox(
        label="Don't show this again on launch",
        value=True,
    )

    def _render() -> None:
        i = step_i["i"]
        title.value = _STEPS[i][0]
        body.value = _STEPS[i][1]
        progress.value = f"Step {i + 1} of {len(_STEPS)}"
        btn_back.disabled = i <= 0
        btn_next.content = "Finish" if i >= len(_STEPS) - 1 else "Next"
        # Keys step: show provider links + Settings shortcut
        links_row.visible = i == 1
        try:
            page.update()
        except Exception:
            pass

    def _finish(*, mark_done: bool) -> None:
        if mark_done or bool(dont_show.value):
            try:
                set_onboarding_done(True)
            except Exception:
                pass
        close_dialog(page, dialog)

    async def _on_back(_e: ft.ControlEvent) -> None:
        if step_i["i"] > 0:
            step_i["i"] -= 1
            _render()

    async def _on_next(_e: ft.ControlEvent) -> None:
        if step_i["i"] >= len(_STEPS) - 1:
            # Finish always dismisses auto-show
            _finish(mark_done=True)
            return
        step_i["i"] += 1
        _render()

    async def _on_skip(_e: ft.ControlEvent) -> None:
        _finish(mark_done=bool(dont_show.value))

    async def _on_settings(_e: ft.ControlEvent) -> None:
        if on_open_settings:
            try:
                on_open_settings()
            except Exception:
                pass

    links_row = ft.Column(
        [
            ft.Row(
                [
                    ft.TextButton(
                        content="fal keys →",
                        on_click=lambda _e: open_url_in_browser(FAL_KEYS_URL),
                        style=ft.ButtonStyle(color=ACCENT_BRIGHT),
                    ),
                    ft.TextButton(
                        content="xAI keys →",
                        on_click=lambda _e: open_url_in_browser(XAI_KEYS_URL),
                        style=ft.ButtonStyle(color=ACCENT_BRIGHT),
                    ),
                    ft.TextButton(
                        content="Runware →",
                        on_click=lambda _e: open_url_in_browser(RUNWARE_KEYS_URL),
                        style=ft.ButtonStyle(color=ACCENT_BRIGHT),
                    ),
                ],
                wrap=True,
                spacing=4,
            ),
            ft.TextButton(
                content="Open Settings to paste keys…",
                icon=ft.Icons.SETTINGS,
                on_click=_on_settings,
                style=ft.ButtonStyle(color=ACCENT_BRIGHT),
            ),
        ],
        spacing=4,
        tight=True,
        visible=True,  # step 0 will hide via _render after dialog built
    )

    btn_back = ft.TextButton(content="Back", on_click=_on_back, disabled=True)
    btn_next = ft.FilledButton(
        content="Next",
        on_click=_on_next,
        style=ft.ButtonStyle(bgcolor=ACCENT_BRIGHT, color=TEXT),
    )

    content = ft.Container(
        content=ft.Column(
            [
                progress,
                title,
                body,
                links_row,
                ft.Divider(height=1, color=BORDER),
                dont_show,
            ],
            spacing=10,
            tight=True,
            scroll=ft.ScrollMode.AUTO,
            width=480,
        ),
        bgcolor=PANEL_ELEVATED,
        padding=4,
    )

    dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text("Quick Start", color=TEXT),
        content=content,
        actions=[
            ft.TextButton(content="Skip", on_click=_on_skip),
            btn_back,
            btn_next,
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )

    show_dialog(page, dialog)
    _render()


def maybe_show_first_run(
    page: ft.Page,
    *,
    on_open_settings: Callable[[], None] | None = None,
) -> None:
    """Call once after the main shell is mounted."""
    if get_onboarding_done():
        return
    open_onboarding_dialog(page, force=False, on_open_settings=on_open_settings)


def make_help_button(
    page: ft.Page,
    *,
    on_open_settings: Callable[[], None] | None = None,
    on_check_updates: Callable[[], None] | None = None,
) -> ft.Control:
    """Top-chrome Help control: Quick Start, FEATURES, update check."""

    def _quick(_e: ft.ControlEvent) -> None:
        open_onboarding_dialog(page, force=True, on_open_settings=on_open_settings)

    def _features(_e: ft.ControlEvent) -> None:
        _open_features_txt(page)

    def _readme(_e: ft.ControlEvent) -> None:
        path = PROJECT_ROOT / "README.md"
        if path.is_file():
            try:
                if sys.platform.startswith("win"):
                    os.startfile(str(path))  # type: ignore[attr-defined]
                elif sys.platform == "darwin":
                    subprocess.run(["open", str(path)], check=False)
                else:
                    subprocess.run(["xdg-open", str(path)], check=False)
            except Exception:
                pass

    def _updates(_e: ft.ControlEvent) -> None:
        if on_check_updates is not None:
            try:
                on_check_updates()
                return
            except Exception:
                pass
        # Fallback: run check inline
        try:
            from media_studio.update_check import check_github_update
            from media_studio.flet_dialogs import open_url_in_browser

            r = check_github_update(force=True)
            show_snack(page, r.message, duration_ms=5000)
            if r.update_available and r.remote_url:
                open_url_in_browser(r.remote_url)
        except Exception as exc:
            show_snack(page, f"Update check failed: {exc}")

    return ft.PopupMenuButton(
        icon=ft.Icons.HELP_OUTLINE,
        icon_color=TEXT,
        tooltip="Help — Quick Start, updates, FEATURES.txt",
        items=[
            ft.PopupMenuItem(
                content="Quick Start…",
                icon=ft.Icons.SCHOOL_OUTLINED,
                on_click=_quick,
            ),
            ft.PopupMenuItem(
                content="Check for updates…",
                icon=ft.Icons.SYSTEM_UPDATE_ALT,
                on_click=_updates,
            ),
            ft.PopupMenuItem(
                content="Open FEATURES.txt",
                icon=ft.Icons.DESCRIPTION_OUTLINED,
                on_click=_features,
            ),
            ft.PopupMenuItem(
                content="Open README.md",
                icon=ft.Icons.MENU_BOOK_OUTLINED,
                on_click=_readme,
            ),
        ],
    )
