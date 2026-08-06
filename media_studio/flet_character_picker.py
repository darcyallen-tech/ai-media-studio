"""
App-wide Character picker — pick a saved character / costume still in one click.

Used by Motion Sync, Director, Creative Vision, Studio Image, etc.
Reads from local Characters store; refresh() reloads options when opened.

When a character has a saved Character Sheet composite, R2V prefers that single
image as the identity ref (citation: ``Camera Man sheet``) with an optional
toggle to use Front only.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import flet as ft

from media_studio.character_store import (
    CharacterPickerChoice,
    character_picker_choices,
    find_picker_choice,
)
from media_studio.flet_theme import (
    ACCENT,
    BORDER,
    FONT_SM,
    PANEL,
    PANEL_ELEVATED,
    TEXT,
    TEXT_MUTED,
    dropdown_options,
    styled_dropdown,
)

# Sentinel dropdown value for "no character selected"
_NONE = "— Character —"

OnSelectPath = Callable[[str, CharacterPickerChoice], None]
OnClear = Callable[[], None]


class CharacterPicker:
    """
    Compact Character dropdown + mini thumb + Clear.

    ``on_select(still_path, choice)`` when user picks a character with a still.
    Path is the **effective** R2V ref (sheet by default when available).
    ``on_clear()`` when cleared (optional).
    """

    def __init__(
        self,
        page: ft.Page,
        *,
        on_select: OnSelectPath,
        on_clear: OnClear | None = None,
        label_text: str = "Character",
        dense: bool = True,
        compact: bool = False,
        show_hint: bool | None = None,
    ) -> None:
        self.page = page
        self.on_select = on_select
        self.on_clear = on_clear
        self._choices: list[CharacterPickerChoice] = []
        self._selected_id: str | None = None
        self._compact = bool(compact)
        # Prefer composite sheet when present (R2V single identity ref)
        self._use_sheet: bool = True
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
                ft.Icons.PERSON_OUTLINE,
                size=16 if self._compact else 18,
                color=TEXT_MUTED,
            ),
            visible=True,
        )
        self.btn_clear = ft.TextButton(
            content="Clear" if self._compact else "Clear character",
            on_click=self._on_clear_click,
            style=ft.ButtonStyle(color=TEXT_MUTED),
            height=28 if self._compact else 32,
            visible=False,
        )
        self.hint = ft.Text(
            "Pick a saved character or costume",
            size=11,
            color=TEXT_MUTED,
            max_lines=1,
            visible=bool(show_hint),
        )
        # Sheet vs Front — only visible when selected character has a composite
        self.ref_mode = ft.RadioGroup(
            content=ft.Row(
                [
                    ft.Radio(
                        value="sheet",
                        label="Sheet (recommended)",
                        label_style=ft.TextStyle(size=11, color=TEXT_MUTED),
                    ),
                    ft.Radio(
                        value="front",
                        label="Front only",
                        label_style=ft.TextStyle(size=11, color=TEXT_MUTED),
                    ),
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
            ],
            spacing=2,
            tight=True,
        )
        self.refresh()

    # ----- public -----

    def refresh(self) -> None:
        """Reload characters from store (call when tab/panel opens)."""
        self._choices = character_picker_choices()
        labels = [_NONE] + [c.label for c in self._choices]
        self.dropdown.options = dropdown_options(labels)
        if self._selected_id:
            choice = find_picker_choice(self._selected_id)
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
        self.hint.value = "Pick a saved character or costume"
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

    def set_selection_silent(self, char_id: str | None) -> None:
        """Sync dropdown/thumb without firing on_select/on_clear (e.g. apply-to-all)."""
        if not char_id:
            self._selected_id = None
            self.dropdown.value = _NONE
            self.thumb.src = ""
            self.thumb.visible = False
            self.thumb_empty.visible = True
            self.btn_clear.visible = False
            self.ref_mode_row.visible = False
            return
        choice = find_picker_choice(char_id)
        if not choice or not choice.has_still:
            return
        self._selected_id = choice.id
        self.dropdown.value = choice.label
        self._apply_choice_ui(choice, notify=False)

    def select_by_id(self, char_id: str | None, *, notify: bool = False) -> bool:
        """Programmatically select a character (e.g. after external load)."""
        if not char_id:
            self.clear(notify=notify)
            return False
        choice = find_picker_choice(char_id)
        if not choice or not choice.has_still:
            return False
        self._selected_id = choice.id
        self.dropdown.value = choice.label
        self._apply_choice_ui(choice, notify=notify)
        try:
            self.page.update()
        except Exception:
            pass
        return True

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
        ch = find_picker_choice(self._selected_id)
        if not ch:
            return None
        return ch.ref_path(use_sheet=self._use_sheet)

    @property
    def selected_ref_label(self) -> str:
        if not self._selected_id:
            return ""
        ch = find_picker_choice(self._selected_id)
        if not ch:
            return ""
        return ch.ref_label(use_sheet=self._use_sheet)

    # ----- internal -----

    def _current_choice(self) -> CharacterPickerChoice | None:
        if not self._selected_id:
            return None
        return find_picker_choice(self._selected_id)

    def _apply_choice_ui(
        self, choice: CharacterPickerChoice, *, notify: bool
    ) -> None:
        """Update thumb, ref-mode row, hint; optionally fire on_select."""
        has_sheet = bool(choice.has_sheet)
        self.ref_mode_row.visible = has_sheet
        if has_sheet:
            # Default Sheet when available
            if self.ref_mode.value not in ("sheet", "front"):
                self.ref_mode.value = "sheet"
            self._use_sheet = self.ref_mode.value != "front"
        else:
            self._use_sheet = False
            try:
                self.ref_mode.value = "sheet"
            except Exception:
                pass
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

    def _choice_for_label(self, label: str | None) -> CharacterPickerChoice | None:
        if not label or label == _NONE:
            return None
        for c in self._choices:
            if c.label == label:
                return c
        self._choices = character_picker_choices()
        for c in self._choices:
            if c.label == label:
                return c
        return None

    async def _on_dropdown(self, e: ft.ControlEvent) -> None:
        label = self.dropdown.value
        if not label or label == _NONE:
            self.clear(notify=True)
            return
        choice = self._choice_for_label(label)
        if not choice or not choice.has_still:
            self.hint.value = "No still on that character"
            self.clear(notify=False)
            try:
                self.page.update()
            except Exception:
                pass
            return
        self._selected_id = choice.id
        # New pick: default to sheet when available
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
        self._use_sheet = val != "front"
        choice = self._current_choice()
        if choice is None:
            return
        self._apply_choice_ui(choice, notify=True)
        try:
            self.page.update()
        except Exception:
            pass

    async def _on_clear_click(self, e: ft.ControlEvent) -> None:
        self.clear(notify=True)
