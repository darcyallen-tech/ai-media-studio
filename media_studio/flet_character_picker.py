"""
App-wide Character picker — pick a saved character / costume still in one click.

Used by Motion Sync, Director, Creative Vision, Studio Image, etc.
Reads from local Characters store; refresh() reloads options when opened.
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
        # Compact shot-row mode: hide long hint unless requested
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
            content=ft.Icon(ft.Icons.PERSON_OUTLINE, size=16 if self._compact else 18, color=TEXT_MUTED),
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
        if self._compact:
            # Single tight row for shot cards
            self.root = ft.Column([main_row], spacing=0, tight=True)
        else:
            self.root = ft.Column(
                [
                    main_row,
                    ft.Row(
                        [self.hint],
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
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
        # Restore selection if still valid
        if self._selected_id:
            choice = find_picker_choice(self._selected_id)
            if choice and choice.has_still:
                self.dropdown.value = choice.label
                self._show_thumb(choice.still_path)
                self.btn_clear.visible = True
                self.hint.value = choice.label
            else:
                self.clear(notify=False)
        else:
            self.dropdown.value = _NONE
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
            return
        choice = find_picker_choice(char_id)
        if not choice or not choice.has_still:
            return
        self._selected_id = choice.id
        self.dropdown.value = choice.label
        self._show_thumb(choice.still_path)
        self.btn_clear.visible = True
        self.hint.value = choice.label

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
        self._show_thumb(choice.still_path)
        self.btn_clear.visible = True
        self.hint.value = choice.label
        if notify and self.on_select:
            try:
                self.on_select(choice.still_path, choice)
            except Exception:
                pass
        try:
            self.page.update()
        except Exception:
            pass
        return True

    @property
    def selected_id(self) -> str | None:
        return self._selected_id

    @property
    def selected_path(self) -> str | None:
        if not self._selected_id:
            return None
        ch = find_picker_choice(self._selected_id)
        if ch and ch.has_still:
            return ch.still_path
        return None

    # ----- internal -----

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
        # Refresh once if label missing (store changed)
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
        self._show_thumb(choice.still_path)
        self.btn_clear.visible = True
        self.hint.value = choice.label
        try:
            self.on_select(choice.still_path, choice)
        except Exception:
            pass
        try:
            self.page.update()
        except Exception:
            pass

    async def _on_clear_click(self, e: ft.ControlEvent) -> None:
        self.clear(notify=True)
