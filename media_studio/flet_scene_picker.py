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
            self.root = ft.Column(
                [main_row, self.disabled_note],
                spacing=2,
                tight=True,
            )
        else:
            self.root = ft.Column(
                [
                    main_row,
                    ft.Row(
                        [self.hint],
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
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
        self.hint.value = "Pick a saved scene or variation"
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
            return
        choice = find_scene_picker_choice(scene_id)
        if not choice or not choice.has_still:
            return
        self._selected_id = choice.id
        self.dropdown.value = choice.label
        self._show_thumb(choice.still_path)
        self.btn_clear.visible = True
        self.hint.value = choice.label

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
    def selected_path(self) -> str | None:
        if not self._selected_id:
            return None
        ch = find_scene_picker_choice(self._selected_id)
        if ch and ch.has_still:
            return ch.still_path
        return None

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
        if not self._enabled:
            return
        self.clear(notify=True)
