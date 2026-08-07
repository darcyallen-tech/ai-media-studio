"""
App-wide Scene picker — pick a saved location / establishing still in one click.

Used by Director (per-shot scene ref), and later Motion Sync / Creative Vision.
Reads from local Scenes store; refresh() reloads options when opened.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import flet as ft

from media_studio.flet_theme import (
    BORDER,
    PANEL,
    TEXT_MUTED,
    dropdown_options,
    styled_dropdown,
)
from media_studio.scene_store import (
    ScenePickerChoice,
    find_scene_picker_choice,
    scene_picker_choices,
)

# Sentinel dropdown value for "no scene selected"
_NONE = "— Scene —"

OnSelectPath = Callable[[str, ScenePickerChoice], None]
OnClear = Callable[[], None]


class ScenePicker:
    """
    Compact Scene dropdown + mini thumb + Clear.

    ``on_select(still_path, choice)`` when user picks a scene with a still.
    ``on_clear()`` when cleared (optional).
    """

    def __init__(
        self,
        page: ft.Page,
        *,
        on_select: OnSelectPath,
        on_clear: OnClear | None = None,
        label_text: str = "Scene",
        dense: bool = True,
        compact: bool = False,
        show_hint: bool | None = None,
    ) -> None:
        self.page = page
        self.on_select = on_select
        self.on_clear = on_clear
        self._choices: list[ScenePickerChoice] = []
        self._selected_id: str | None = None
        self._compact = bool(compact)
        self._enabled = True
        self._use_sheet: bool = True  # prefer Scene sheet composite when present
        if show_hint is None:
            show_hint = not self._compact

        thumb_sz = 32 if self._compact else 40
        self.dropdown = styled_dropdown(
            label_text=label_text,
            options=[_NONE],
            value=_NONE,
            on_select=self._on_dropdown,
            expand=True,
        )
        self.thumb = ft.Image(
            src="",
            width=thumb_sz,
            height=thumb_sz,
            fit=ft.BoxFit.COVER,
            border_radius=4,
            visible=False,
        )
        self.thumb_empty = ft.Container(
            width=thumb_sz,
            height=thumb_sz,
            bgcolor=PANEL,
            border=ft.Border.all(1, BORDER),
            border_radius=4,
            alignment=ft.Alignment.CENTER,
            content=ft.Icon(
                ft.Icons.LANDSCAPE_OUTLINED,
                size=16 if self._compact else 18,
                color=TEXT_MUTED,
            ),
            visible=True,
        )
        self.btn_clear = ft.TextButton(
            content="Clear" if self._compact else "Clear scene",
            on_click=self._on_clear_click,
            style=ft.ButtonStyle(color=TEXT_MUTED),
            height=28 if self._compact else 32,
            visible=False,
        )
        self.hint = ft.Text(
            "Pick a saved scene or variation",
            size=11,
            color=TEXT_MUTED,
            max_lines=1,
            visible=bool(show_hint),
        )
        self.disabled_note = ft.Text(
            "",
            size=11,
            color=TEXT_MUTED,
            max_lines=2,
            visible=False,
        )
        self.ref_mode = ft.RadioGroup(
            content=ft.Row(
                [
                    ft.Radio(value="sheet", label="Sheet (recommended)"),
                    ft.Radio(value="hero", label="Hero only"),
                ],
                spacing=8,
                wrap=True,
            ),
            value="sheet",
            on_change=self._on_ref_mode_change,
        )
        self.ref_mode_row = ft.Row(
            [
                ft.Text("Ref:", size=11, color=TEXT_MUTED, weight=ft.FontWeight.W_600),
                self.ref_mode,
            ],
            spacing=6,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            visible=False,
        )
        main_row = ft.Row(
            [
                ft.Stack(
                    [self.thumb_empty, self.thumb],
                    width=thumb_sz,
                    height=thumb_sz,
                ),
                ft.Container(content=self.dropdown, expand=True),
                self.btn_clear,
            ],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        self.root = ft.Column(
            [
                main_row,
                self.ref_mode_row,
                ft.Row(
                    [self.hint],
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                )
                if show_hint
                else ft.Container(height=0, visible=False),
                self.disabled_note,
            ],
            spacing=2,
            tight=True,
        )
        self.refresh()

    def refresh(self) -> None:
        """Reload scenes from store (call when tab/panel opens)."""
        self._choices = scene_picker_choices()
        labels = [_NONE] + [c.label for c in self._choices]
        self.dropdown.options = dropdown_options(labels)
        if self._selected_id:
            choice = find_scene_picker_choice(self._selected_id)
            if choice and choice.has_still:
                self.dropdown.value = choice.label
                self._apply_choice_ui(choice, notify=False)
            else:
                self.clear(notify=False)
        else:
            self.dropdown.value = _NONE
            self.ref_mode_row.visible = False
        try:
            self.page.update()
        except Exception:
            pass

    def clear(self, *, notify: bool = True) -> None:
        self._selected_id = None
        self.dropdown.value = _NONE
        self.thumb.src = ""
        self.thumb.visible = False
        self.thumb_empty.visible = True
        self.btn_clear.visible = False
        self.hint.value = "Pick a saved scene or variation"
        self.ref_mode_row.visible = False
        self._use_sheet = True
        try:
            self.ref_mode.value = "sheet"
        except Exception:
            pass
        if notify and self.on_clear:
            try:
                self.on_clear()
            except Exception:
                pass
        try:
            self.page.update()
        except Exception:
            pass

    def set_selection_silent(self, scene_id: str | None) -> None:
        """Sync dropdown/thumb without firing callbacks."""
        if not scene_id:
            self._selected_id = None
            self.dropdown.value = _NONE
            self.thumb.src = ""
            self.thumb.visible = False
            self.thumb_empty.visible = True
            self.btn_clear.visible = False
            self.ref_mode_row.visible = False
            return
        choice = find_scene_picker_choice(scene_id)
        if not choice or not choice.has_still:
            return
        self._selected_id = choice.id
        self.dropdown.value = choice.label
        self._apply_choice_ui(choice, notify=False)

    def set_enabled(self, enabled: bool, *, reason: str = "") -> None:
        """Enable/disable for single-ref models."""
        self._enabled = bool(enabled)
        try:
            self.dropdown.disabled = not self._enabled
            self.btn_clear.disabled = not self._enabled
        except Exception:
            pass
        if self._enabled:
            self.disabled_note.value = ""
            self.disabled_note.visible = False
        else:
            self.disabled_note.value = reason or (
                "Scene image ref not supported on this model — describe location in text."
            )
            self.disabled_note.visible = True
        try:
            self.page.update()
        except Exception:
            pass

    @property
    def selected_id(self) -> str | None:
        return self._selected_id

    @property
    def use_sheet(self) -> bool:
        return bool(self._use_sheet)

    @property
    def selected_path(self) -> str | None:
        if not self._selected_id:
            return None
        ch = find_scene_picker_choice(self._selected_id)
        if not ch:
            return None
        return ch.ref_path(use_sheet=self._use_sheet)

    def _apply_choice_ui(
        self, choice: ScenePickerChoice, *, notify: bool
    ) -> None:
        has_sheet = bool(choice.has_sheet)
        self.ref_mode_row.visible = has_sheet
        if has_sheet:
            if self.ref_mode.value not in ("sheet", "hero"):
                self.ref_mode.value = "sheet"
            self._use_sheet = self.ref_mode.value != "hero"
        else:
            self._use_sheet = False
        path = choice.ref_path(use_sheet=self._use_sheet) or choice.still_path
        label = choice.ref_label(use_sheet=self._use_sheet)
        self._show_thumb(path or "")
        self.btn_clear.visible = True
        self.hint.value = label
        if notify and self.on_select and path:
            try:
                self.on_select(path, choice)
            except Exception:
                pass

    def _show_thumb(self, path: str) -> None:
        if path and Path(path).is_file():
            self.thumb.src = path
            self.thumb.visible = True
            self.thumb_empty.visible = False
        else:
            self.thumb.visible = False
            self.thumb_empty.visible = True

    def _choice_for_label(self, label: str | None) -> ScenePickerChoice | None:
        if not label or label == _NONE:
            return None
        for c in self._choices:
            if c.label == label:
                return c
        self._choices = scene_picker_choices()
        for c in self._choices:
            if c.label == label:
                return c
        return None

    async def _on_dropdown(self, e: ft.ControlEvent) -> None:
        if not self._enabled:
            return
        label = self.dropdown.value
        if not label or label == _NONE:
            self.clear(notify=True)
            return
        choice = self._choice_for_label(label)
        if not choice or not choice.has_still:
            self.hint.value = "No still on that scene"
            self.clear(notify=False)
            try:
                self.page.update()
            except Exception:
                pass
            return
        self._selected_id = choice.id
        if choice.has_sheet:
            self.ref_mode.value = "sheet"
            self._use_sheet = True
        self._apply_choice_ui(choice, notify=True)
        try:
            self.page.update()
        except Exception:
            pass

    async def _on_ref_mode_change(self, e: ft.ControlEvent) -> None:
        val = (self.ref_mode.value or "sheet").strip().lower()
        self._use_sheet = val != "hero"
        if not self._selected_id:
            return
        choice = find_scene_picker_choice(self._selected_id)
        if choice is None:
            return
        self._apply_choice_ui(choice, notify=True)
        try:
            self.page.update()
        except Exception:
            pass

    async def _on_clear_click(self, e: ft.ControlEvent) -> None:
        if not self._enabled:
            return
        self.clear(notify=True)
