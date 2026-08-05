"""
In-app Model Guide — modal near Settings.

Lists registered models with modalities, Best for, strengths, limitations.
Filter / search; optional Open in Studio / Vision / Director.
"""

from __future__ import annotations

from typing import Any, Callable

import flet as ft

from media_studio.flet_dialogs import close_dialog, show_dialog, show_snack
from media_studio.flet_theme import (
    ACCENT,
    ACCENT_BRIGHT,
    BORDER,
    FONT_MD,
    FONT_SM,
    PANEL,
    PANEL_ELEVATED,
    TEXT,
    TEXT_MUTED,
)
from media_studio.model_guide import (
    GUIDE_FILTERS,
    GUIDE_FLAG_FILTERS,
    GuideEntry,
    collect_guide_entries,
    filter_guide_entries,
    open_target_label,
)

OpenTargetFn = Callable[[str, str], None]  # target, model_choice


def open_model_guide_dialog(
    page: ft.Page,
    *,
    state: Any | None = None,
    on_open_target: OpenTargetFn | None = None,
) -> None:
    """Show the Model Guide modal (non-blocking for generate flows)."""
    entries_all = collect_guide_entries()
    family = {"value": "all"}
    flag = {"value": None}
    query = {"value": ""}

    list_host = ft.Column(
        spacing=8,
        tight=True,
        scroll=ft.ScrollMode.AUTO,
        expand=True,
    )
    count_label = ft.Text("", size=FONT_SM, color=TEXT_MUTED)

    search_field = ft.TextField(
        label="Search models",
        hint_text="e.g. Kling, FLUX 3, H3, Seedance…",
        dense=True,
        filled=True,
        fill_color=PANEL,
        border_color=BORDER,
        color=TEXT,
        text_size=FONT_SM,
        expand=True,
        on_change=lambda e: _on_search(e),
    )

    filter_chips = ft.Row(spacing=6, wrap=True)
    flag_chips = ft.Row(spacing=6, wrap=True)

    def _rebuild_filter_chips() -> None:
        filter_chips.controls.clear()
        for key, lab in GUIDE_FILTERS:
            selected = family["value"] == key
            filter_chips.controls.append(
                ft.Container(
                    content=ft.Text(
                        lab,
                        size=FONT_SM,
                        color=TEXT if selected else TEXT_MUTED,
                        weight=ft.FontWeight.W_600 if selected else None,
                    ),
                    bgcolor=ACCENT if selected else PANEL_ELEVATED,
                    border=ft.Border.all(1, ACCENT if selected else BORDER),
                    border_radius=16,
                    padding=ft.Padding.symmetric(horizontal=12, vertical=6),
                    on_click=_make_family_click(key),
                    ink=True,
                )
            )
        flag_chips.controls.clear()
        # "Any" flag
        any_sel = flag["value"] is None
        flag_chips.controls.append(
            ft.Container(
                content=ft.Text(
                    "Any feature",
                    size=11,
                    color=TEXT if any_sel else TEXT_MUTED,
                ),
                bgcolor=PANEL_ELEVATED if any_sel else PANEL,
                border=ft.Border.all(1, ACCENT if any_sel else BORDER),
                border_radius=14,
                padding=ft.Padding.symmetric(horizontal=10, vertical=4),
                on_click=_make_flag_click(None),
                ink=True,
            )
        )
        for key, lab in GUIDE_FLAG_FILTERS:
            selected = flag["value"] == key
            flag_chips.controls.append(
                ft.Container(
                    content=ft.Text(
                        lab,
                        size=11,
                        color=TEXT if selected else TEXT_MUTED,
                    ),
                    bgcolor=ACCENT if selected else PANEL_ELEVATED,
                    border=ft.Border.all(1, ACCENT if selected else BORDER),
                    border_radius=14,
                    padding=ft.Padding.symmetric(horizontal=10, vertical=4),
                    on_click=_make_flag_click(key),
                    ink=True,
                )
            )

    def _make_family_click(key: str):
        async def _click(_e: ft.ControlEvent) -> None:
            family["value"] = key
            _rebuild_filter_chips()
            _refresh_list()
            try:
                page.update()
            except Exception:
                pass

        return _click

    def _make_flag_click(key: str | None):
        async def _click(_e: ft.ControlEvent) -> None:
            flag["value"] = key
            _rebuild_filter_chips()
            _refresh_list()
            try:
                page.update()
            except Exception:
                pass

        return _click

    def _on_search(e: ft.ControlEvent) -> None:
        query["value"] = (search_field.value or "").strip()
        _refresh_list()
        try:
            page.update()
        except Exception:
            pass

    def _mod_tags(mods: tuple[str, ...]) -> ft.Control:
        return ft.Row(
            [
                ft.Container(
                    content=ft.Text(m, size=10, color=TEXT),
                    bgcolor="#243044",
                    border_radius=4,
                    padding=ft.Padding.symmetric(horizontal=6, vertical=2),
                )
                for m in mods
            ],
            spacing=4,
            wrap=True,
        )

    def _flag_tags(flags: frozenset[str]) -> ft.Control | None:
        if not flags:
            return None
        labels = {
            "multi_char": "Multi-char",
            "native_audio": "Native audio",
            "draft": "Draft",
            "multi_ref": "Multi-ref",
        }
        return ft.Row(
            [
                ft.Text(
                    labels.get(f, f),
                    size=10,
                    color=ACCENT_BRIGHT,
                )
                for f in sorted(flags)
            ],
            spacing=8,
            wrap=True,
        )

    def _card(entry: GuideEntry) -> ft.Control:
        open_lab = open_target_label(entry.open_target)
        btn_open = None
        if entry.open_target and on_open_target:
            async def _open(_e: ft.ControlEvent, e=entry) -> None:
                try:
                    on_open_target(e.open_target or "", e.model_choice or e.name)
                    close_dialog(page, dialog)
                    show_snack(page, f"Opening {e.name}…")
                except Exception as exc:
                    show_snack(page, f"Open failed: {exc}")

            btn_open = ft.TextButton(
                content=open_lab,
                on_click=_open,
                style=ft.ButtonStyle(color=ACCENT_BRIGHT),
                height=32,
            )
        flag_row = _flag_tags(entry.flags)
        body: list[ft.Control] = [
            ft.Row(
                [
                    ft.Text(
                        entry.name,
                        size=FONT_SM,
                        color=TEXT,
                        weight=ft.FontWeight.W_700,
                        expand=True,
                        max_lines=2,
                    ),
                    ft.Text(
                        entry.family.replace("_", " ").title(),
                        size=10,
                        color=TEXT_MUTED,
                    ),
                ],
                spacing=8,
            ),
            _mod_tags(entry.modalities),
        ]
        if flag_row:
            body.append(flag_row)
        if entry.best_for:
            body.append(
                ft.Text(
                    f"Best for: {entry.best_for}",
                    size=FONT_SM,
                    color=ACCENT_BRIGHT,
                    max_lines=2,
                )
            )
        if entry.strengths:
            body.append(
                ft.Text(
                    entry.strengths,
                    size=FONT_SM,
                    color=TEXT,
                    max_lines=3,
                )
            )
        if entry.limitations:
            body.append(
                ft.Text(
                    f"Limits: {entry.limitations}",
                    size=11,
                    color=TEXT_MUTED,
                    max_lines=4,
                )
            )
        if btn_open:
            body.append(btn_open)
        return ft.Container(
            content=ft.Column(body, spacing=4, tight=True),
            bgcolor=PANEL_ELEVATED,
            border=ft.Border.all(1, BORDER),
            border_radius=8,
            padding=10,
        )

    def _refresh_list() -> None:
        filtered = filter_guide_entries(
            entries_all,
            family=family["value"],
            query=query["value"],
            flag=flag["value"],
        )
        list_host.controls.clear()
        if not filtered:
            list_host.controls.append(
                ft.Text(
                    "No models match. Clear search or change filters.",
                    size=FONT_SM,
                    color=TEXT_MUTED,
                )
            )
        else:
            for e in filtered:
                list_host.controls.append(_card(e))
        count_label.value = f"{len(filtered)} model(s)"

    async def _close(_e: ft.ControlEvent | None = None) -> None:
        close_dialog(page, dialog)

    _rebuild_filter_chips()
    _refresh_list()

    win_w = float(getattr(page.window, "width", None) or 1200)
    win_h = float(getattr(page.window, "height", None) or 800)
    body_w = int(min(max(win_w - 100, 640), 920))
    body_h = int(min(max(win_h - 120, 480), 720))

    dialog = ft.AlertDialog(
        modal=True,
        title=ft.Row(
            [
                ft.Icon(ft.Icons.MENU_BOOK_OUTLINED, color=ACCENT_BRIGHT, size=22),
                ft.Text(
                    "Model Guide",
                    size=FONT_MD,
                    color=TEXT,
                    weight=ft.FontWeight.W_700,
                    expand=True,
                ),
                ft.IconButton(
                    icon=ft.Icons.CLOSE,
                    icon_color=TEXT,
                    tooltip="Close (Esc)",
                    on_click=_close,
                ),
            ],
            spacing=8,
        ),
        content=ft.Container(
            width=body_w,
            height=body_h,
            content=ft.Column(
                [
                    ft.Text(
                        "Registered models — Best for, strengths, and limits. "
                        "Same sources as model pickers (stays in sync).",
                        size=FONT_SM,
                        color=TEXT_MUTED,
                        max_lines=2,
                    ),
                    ft.Row([search_field], spacing=0),
                    filter_chips,
                    flag_chips,
                    count_label,
                    ft.Container(
                        content=list_host,
                        expand=True,
                        bgcolor=PANEL,
                        border=ft.Border.all(1, BORDER),
                        border_radius=8,
                        padding=8,
                    ),
                ],
                spacing=8,
                expand=True,
            ),
        ),
        actions=[
            ft.TextButton(
                content="Close",
                on_click=_close,
                style=ft.ButtonStyle(color=TEXT_MUTED),
            ),
        ],
        bgcolor=PANEL_ELEVATED,
    )
    show_dialog(page, dialog)
