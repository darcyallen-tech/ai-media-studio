"""Dark desktop theme tokens for the Flet AI Media Studio app."""

from __future__ import annotations

import flet as ft

# Backgrounds
BG = "#0f1115"
PANEL = "#171a21"
PANEL_ELEVATED = "#1c212b"
BORDER = "#2a2f3a"
BORDER_FOCUS = "#3a6ee0"

# Text
TEXT = "#f0f2f5"
TEXT_MUTED = "#9aa0a6"
TEXT_DIM = "#6b7280"

# Accents
ACCENT = "#3a6ee0"
ACCENT_BRIGHT = "#4a72e8"
SUCCESS = "#2d6a4f"
DANGER = "#b33a3a"

FONT_SM = 12
FONT_MD = 13
FONT_LG = 15
FONT_XL = 18

# Controls rails — fixed widths so empty result panes never starve the left side
RAIL_WIDTH = 460
TOOLS_FORM_WIDTH = 560
# Compact empty preview / result placeholders (not full-column stretch)
EMPTY_PREVIEW_H = 96


def page_theme() -> ft.Theme:
    return ft.Theme(
        color_scheme_seed=ACCENT,
        color_scheme=ft.ColorScheme(
            primary=ACCENT,
            on_primary=TEXT,
            surface=PANEL,
            on_surface=TEXT,
            surface_container_highest=PANEL_ELEVATED,
            outline=BORDER,
        ),
    )


def label(text: str, *, muted: bool = False) -> ft.Text:
    return ft.Text(
        text,
        size=FONT_SM,
        color=TEXT_MUTED if muted else TEXT,
        weight=ft.FontWeight.W_600,
    )


def section_title(text: str) -> ft.Text:
    return ft.Text(text, size=FONT_MD, color=TEXT, weight=ft.FontWeight.W_700)


def make_estimated_cost_box(
    cost_text: ft.Text | None = None,
    *,
    initial: str = "Est. cost: —",
) -> tuple[ft.Text, ft.Container]:
    """
    Studio-standard Estimated cost chrome.

    Place the returned box **directly under** the primary Generate button.
    Style: bordered ACCENT panel, "Estimated cost" caption, bold job-total line
    (``Est. cost: $X.XX · {summary} ({model})`` via format_job_cost).
    """
    if cost_text is None:
        cost_text = ft.Text(
            initial,
            size=FONT_LG,
            color=TEXT,
            weight=ft.FontWeight.W_700,
            text_align=ft.TextAlign.CENTER,
        )
    else:
        try:
            cost_text.size = FONT_LG
            cost_text.color = TEXT
            cost_text.weight = ft.FontWeight.W_700
            cost_text.text_align = ft.TextAlign.CENTER
            if not (cost_text.value or "").strip():
                cost_text.value = initial
        except Exception:
            pass
    box = ft.Container(
        content=ft.Column(
            [label("Estimated cost"), cost_text],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=2,
            tight=True,
        ),
        bgcolor=PANEL_ELEVATED,
        border=ft.Border.all(1, ACCENT),
        border_radius=6,
        padding=ft.Padding.symmetric(horizontal=10, vertical=8),
    )
    return cost_text, box


def panel(content: ft.Control, *, expand: bool | int | None = None, padding: int = 10) -> ft.Container:
    return ft.Container(
        content=content,
        bgcolor=PANEL,
        border=ft.Border.all(1, BORDER),
        border_radius=8,
        padding=padding,
        expand=expand,
    )


def dropdown_options(values: list[str]) -> list[ft.DropdownOption]:
    return [ft.DropdownOption(key=v, text=v) for v in values if v is not None]


def styled_dropdown(
    *,
    label_text: str,
    options: list[str],
    value: str | None,
    on_select=None,
    width: float | None = None,
    expand: bool = False,
) -> ft.Dropdown:
    opts = dropdown_options(options)
    val = value if value in options else (options[0] if options else None)
    return ft.Dropdown(
        label=label_text,
        options=opts,
        value=val,
        on_select=on_select,
        width=width,
        expand=expand,
        dense=True,
        filled=True,
        fill_color=PANEL_ELEVATED,
        border_color=BORDER,
        focused_border_color=ACCENT,
        color=TEXT,
        text_size=FONT_SM,
        content_padding=8,
    )


class PillNav:
    """
    Secondary pill/tab row — one active section at a time.

    ``items`` is a list of ``(id, label)``. ``on_change(id)`` fires when the
    user picks a different pill (not on initial build).
    """

    def __init__(
        self,
        items: list[tuple[str, str]],
        *,
        selected: str | None = None,
        on_change=None,
    ) -> None:
        if not items:
            raise ValueError("PillNav requires at least one item")
        self.items = list(items)
        self._ids = [i[0] for i in self.items]
        self.selected = selected if selected in self._ids else self._ids[0]
        self.on_change = on_change
        self._pills: dict[str, ft.Container] = {}
        self.row = ft.Row(
            controls=[self._make_pill(pid, label) for pid, label in self.items],
            spacing=6,
            scroll=ft.ScrollMode.AUTO,
            wrap=True,
            run_spacing=6,
        )

    def _make_pill(self, pid: str, label_text: str) -> ft.Container:
        active = pid == self.selected

        def _click(_e: ft.ControlEvent, *, _id: str = pid) -> None:
            if _id == self.selected:
                return
            self.set_selected(_id, notify=True)

        pill = ft.Container(
            content=ft.Text(
                label_text,
                size=FONT_SM,
                color=TEXT if active else TEXT_MUTED,
                weight=ft.FontWeight.W_600 if active else ft.FontWeight.W_400,
            ),
            bgcolor=ACCENT if active else PANEL_ELEVATED,
            border=ft.Border.all(1, ACCENT if active else BORDER),
            border_radius=16,
            padding=ft.Padding.symmetric(horizontal=12, vertical=7),
            on_click=_click,
            ink=True,
            tooltip=label_text,
        )
        self._pills[pid] = pill
        return pill

    def set_selected(self, pid: str, *, notify: bool = False) -> None:
        if pid not in self._ids:
            return
        self.selected = pid
        for i, lab in self.items:
            pill = self._pills.get(i)
            if pill is None:
                continue
            active = i == pid
            pill.bgcolor = ACCENT if active else PANEL_ELEVATED
            pill.border = ft.Border.all(1, ACCENT if active else BORDER)
            text = pill.content
            if isinstance(text, ft.Text):
                text.color = TEXT if active else TEXT_MUTED
                text.weight = ft.FontWeight.W_600 if active else ft.FontWeight.W_400
        if notify and self.on_change is not None:
            try:
                self.on_change(pid)
            except Exception:
                pass

    @property
    def control(self) -> ft.Control:
        return self.row
