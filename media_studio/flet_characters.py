"""
Characters tab — local reusable character stills.

Curated subset for Motion Sync / Director / Creative Vision (not a Library replacement).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import flet as ft

from media_studio.character_store import (
    SavedCharacter,
    add_character,
    delete_character,
    load_characters,
    update_character,
)
from media_studio.folder_util import show_in_folder
from media_studio.flet_pickers import pick_image
from media_studio.flet_source_strip import PreviousSourcesStrip, ResolveSourcesStrip
from media_studio.flet_theme import (
    ACCENT,
    ACCENT_BRIGHT,
    BORDER,
    FONT_SM,
    PANEL,
    PANEL_ELEVATED,
    TEXT,
    TEXT_MUTED,
    label,
    section_title,
)

if TYPE_CHECKING:
    from media_studio.flet_app import StudioState

_THUMB = 72


class CharactersView:
    """Save and reuse character stills (local store only)."""

    def __init__(self, page: ft.Page, state: StudioState) -> None:
        self.page = page
        self.state = state
        self._still_path: str | None = None
        self._editing_id: str | None = None

        self.preview = ft.Image(
            src="",
            width=140,
            height=140,
            fit=ft.BoxFit.COVER,
            border_radius=6,
            visible=False,
        )
        self.preview_empty = ft.Container(
            width=140,
            height=140,
            bgcolor=PANEL,
            border=ft.Border.all(1, BORDER),
            border_radius=6,
            alignment=ft.Alignment.CENTER,
            content=ft.Icon(ft.Icons.PERSON_OUTLINE, size=36, color=TEXT_MUTED),
        )
        self.still_label = ft.Text(
            "No still selected",
            size=FONT_SM,
            color=TEXT_MUTED,
            max_lines=2,
        )
        self.btn_upload = ft.OutlinedButton(
            content="Upload still",
            icon=ft.Icons.IMAGE,
            on_click=self._pick_still,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
        )
        self.btn_clear_still = ft.TextButton(
            content="Clear still",
            on_click=self._clear_still,
            style=ft.ButtonStyle(color=TEXT_MUTED),
        )
        self.prev_strip = PreviousSourcesStrip(
            page,
            get_output_dir=lambda: self.state.output_dir,
            on_load=self._on_still_from_strip,
            media_kind="image",
        )
        self.resolve_strip = ResolveSourcesStrip(
            page,
            on_load=self._on_still_from_strip,
            media_kind="image",
        )
        self.btn_library = ft.TextButton(
            content="Open Library",
            icon=ft.Icons.PHOTO_LIBRARY_OUTLINED,
            on_click=self._open_library,
            style=ft.ButtonStyle(color=ACCENT),
            tooltip="Browse history — re-upload a still here, or use Previously used after opening it",
        )

        self.name_field = ft.TextField(
            label="Name (required)",
            hint_text="e.g. Sarah – blue blazer",
            value="",
            dense=True,
            filled=True,
            fill_color=PANEL_ELEVATED,
            border_color=BORDER,
            color=TEXT,
            text_size=FONT_SM,
        )
        self.notes_field = ft.TextField(
            label="Notes / tags (optional)",
            hint_text="e.g. Camera Man hero · outdoor listing",
            value="",
            dense=True,
            filled=True,
            fill_color=PANEL_ELEVATED,
            border_color=BORDER,
            color=TEXT,
            text_size=FONT_SM,
            multiline=True,
            min_lines=1,
            max_lines=3,
        )
        self.btn_save = ft.FilledButton(
            content="Save character",
            on_click=self._save,
            style=ft.ButtonStyle(bgcolor=ACCENT_BRIGHT, color=TEXT),
            height=40,
        )
        self.btn_cancel_edit = ft.TextButton(
            content="Cancel edit",
            on_click=self._cancel_edit,
            style=ft.ButtonStyle(color=TEXT_MUTED),
            visible=False,
        )
        self.status = ft.Text("", size=FONT_SM, color=TEXT_MUTED, max_lines=3)

        self.empty_state = ft.Text(
            "Save realtor or talent stills here for one-click use in "
            "Motion Sync, Director, and more.",
            size=FONT_SM,
            color=TEXT_MUTED,
            visible=True,
        )
        self.list_host = ft.Column(spacing=8, tight=True)
        self.list_count = ft.Text("", size=FONT_SM, color=TEXT_MUTED)

        self.refresh()

    # ----- layout -----

    def build(self) -> ft.Control:
        from media_studio.flet_layout import make_split_workspace
        from media_studio.flet_theme import RAIL_WIDTH

        left = [
            section_title("Characters"),
            ft.Text(
                "Curated character stills (local only). Library stays full history — "
                "this is the short list for Motion Sync, Director, and Creative Vision.",
                size=FONT_SM,
                color=TEXT_MUTED,
            ),
            ft.Divider(height=1, color=BORDER),
            label("Add / edit", muted=True),
            ft.Stack([self.preview_empty, self.preview], width=140, height=140),
            self.still_label,
            ft.Row(
                [self.btn_upload, self.btn_clear_still, self.btn_library],
                spacing=6,
                wrap=True,
            ),
            self.prev_strip.root,
            self.resolve_strip.root,
            self.name_field,
            self.notes_field,
            ft.Row([self.btn_save, self.btn_cancel_edit], spacing=8),
            self.status,
        ]
        right = ft.Column(
            [
                section_title("Saved characters"),
                self.list_count,
                self.empty_state,
                self.list_host,
            ],
            spacing=8,
            tight=True,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )
        return make_split_workspace(
            left,
            right,
            left_width=max(RAIL_WIDTH, 420),
        )

    # ----- form -----

    def _set_status(self, msg: str, *, error: bool = False) -> None:
        self.status.value = msg
        self.status.color = "#e57373" if error else TEXT_MUTED
        try:
            self.page.update()
        except Exception:
            pass

    async def _pick_still(self, e: ft.ControlEvent) -> None:
        try:
            files = await pick_image(self.page, dialog_title="Character still")
        except Exception as exc:
            self._set_status(f"Picker error: {exc}", error=True)
            return
        if not files or not files[0].path:
            return
        self._set_still(files[0].path)

    def _clear_still(self, e: ft.ControlEvent | None = None) -> None:
        self._still_path = None
        self.preview.src = ""
        self.preview.visible = False
        self.preview_empty.visible = True
        self.still_label.value = "No still selected"
        try:
            self.page.update()
        except Exception:
            pass

    def _on_still_from_strip(self, path: str) -> None:
        self._set_still(path)

    def _set_still(self, path: str) -> None:
        p = Path(path)
        if not p.is_file():
            self._set_status(f"Missing still: {path}", error=True)
            return
        self._still_path = str(p.resolve())
        self.preview.src = self._still_path
        self.preview.visible = True
        self.preview_empty.visible = False
        self.still_label.value = p.name
        try:
            self.prev_strip.record_and_refresh(self._still_path)
        except Exception:
            pass
        try:
            self.page.update()
        except Exception:
            pass

    async def _open_library(self, e: ft.ControlEvent) -> None:
        switch = getattr(self.state, "switch_to_library", None)
        if switch:
            switch()
        self._set_status(
            "Library open — after you view a still, it may appear under "
            "Previously used here, or re-upload it on this tab."
        )

    def _cancel_edit(self, e: ft.ControlEvent | None = None) -> None:
        self._editing_id = None
        self.name_field.value = ""
        self.notes_field.value = ""
        self.btn_save.content = "Save character"
        self.btn_cancel_edit.visible = False
        self._clear_still()
        self._set_status("Edit cancelled.")

    async def _save(self, e: ft.ControlEvent) -> None:
        name = (self.name_field.value or "").strip()
        notes = (self.notes_field.value or "").strip()
        if not name:
            self._set_status("Name is required.", error=True)
            return
        try:
            if self._editing_id:
                still = self._still_path
                updated = update_character(
                    self._editing_id,
                    name=name,
                    notes=notes,
                    still_path=still if still else None,
                )
                if not updated:
                    self._set_status("Character not found.", error=True)
                    return
                self._set_status(f"Updated: {updated.name}")
            else:
                if not self._still_path or not Path(self._still_path).is_file():
                    self._set_status("Upload or pick a still first.", error=True)
                    return
                entry = add_character(
                    name=name,
                    still_path=self._still_path,
                    notes=notes,
                )
                self._set_status(f"Saved: {entry.name}")
            self._editing_id = None
            self.btn_save.content = "Save character"
            self.btn_cancel_edit.visible = False
            self.name_field.value = ""
            self.notes_field.value = ""
            self._clear_still()
            self.refresh()
        except Exception as exc:
            self._set_status(str(exc), error=True)

    # ----- list -----

    def refresh(self) -> None:
        chars = load_characters()
        self.list_host.controls.clear()
        n = len(chars)
        self.list_count.value = f"{n} saved" if n else ""
        self.empty_state.visible = n == 0
        for c in chars:
            self.list_host.controls.append(self._card(c))
        try:
            self.page.update()
        except Exception:
            pass

    def _card(self, c: SavedCharacter) -> ft.Control:
        still_ok = Path(c.still_path).is_file() if c.still_path else False
        thumb: ft.Control
        if still_ok:
            thumb = ft.Image(
                src=c.still_path,
                width=_THUMB,
                height=_THUMB,
                fit=ft.BoxFit.COVER,
                border_radius=6,
            )
        else:
            thumb = ft.Container(
                width=_THUMB,
                height=_THUMB,
                bgcolor=PANEL,
                border=ft.Border.all(1, BORDER),
                border_radius=6,
                alignment=ft.Alignment.CENTER,
                content=ft.Icon(ft.Icons.BROKEN_IMAGE_OUTLINED, size=24, color=TEXT_MUTED),
            )
        notes = c.display_notes() or "—"
        name_txt = ft.Text(
            c.name,
            size=FONT_SM,
            color=TEXT,
            weight=ft.FontWeight.W_600,
            max_lines=1,
        )
        notes_txt = ft.Text(notes, size=FONT_SM, color=TEXT_MUTED, max_lines=2)
        missing = ft.Text(
            "Still file missing",
            size=FONT_SM,
            color="#e57373",
            visible=not still_ok,
        )

        btn_use = ft.FilledButton(
            content="Use in Motion Sync",
            on_click=self._make_use_motion(c),
            style=ft.ButtonStyle(bgcolor=ACCENT_BRIGHT, color=TEXT),
            height=36,
            disabled=not still_ok,
            tooltip="Set as Motion Sync character still and open that tab",
        )
        btn_edit = ft.OutlinedButton(
            content="Edit",
            on_click=self._make_edit(c),
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
            height=36,
        )
        btn_delete = ft.TextButton(
            content="Delete",
            on_click=self._make_delete(c),
            style=ft.ButtonStyle(color="#e57373"),
            height=36,
        )
        btn_folder = ft.TextButton(
            content="Show in folder",
            on_click=self._make_show_folder(c),
            style=ft.ButtonStyle(color=TEXT_MUTED),
            height=36,
            disabled=not still_ok,
        )

        return ft.Container(
            content=ft.Row(
                [
                    thumb,
                    ft.Column(
                        [
                            name_txt,
                            notes_txt,
                            missing,
                            ft.Row(
                                [btn_use, btn_edit, btn_delete, btn_folder],
                                spacing=4,
                                wrap=True,
                            ),
                        ],
                        spacing=4,
                        expand=True,
                        tight=True,
                    ),
                ],
                spacing=12,
                vertical_alignment=ft.CrossAxisAlignment.START,
            ),
            bgcolor=PANEL_ELEVATED,
            border=ft.Border.all(1, BORDER),
            border_radius=8,
            padding=10,
        )

    def _make_edit(self, c: SavedCharacter):
        async def _click(_e: ft.ControlEvent) -> None:
            self._editing_id = c.id
            self.name_field.value = c.name
            self.notes_field.value = c.notes or ""
            self.btn_save.content = "Save changes"
            self.btn_cancel_edit.visible = True
            if c.still_path and Path(c.still_path).is_file():
                self._set_still(c.still_path)
            else:
                self._clear_still()
            self._set_status(f"Editing: {c.name}")

        return _click

    def _make_delete(self, c: SavedCharacter):
        async def _click(_e: ft.ControlEvent) -> None:
            ok = delete_character(c.id)
            if ok:
                if self._editing_id == c.id:
                    self._cancel_edit()
                self._set_status(f"Deleted: {c.name}")
                self.refresh()
            else:
                self._set_status("Delete failed.", error=True)

        return _click

    def _make_show_folder(self, c: SavedCharacter):
        async def _click(_e: ft.ControlEvent) -> None:
            msg = show_in_folder(c.still_path)
            self._set_status(msg)

        return _click

    def _make_use_motion(self, c: SavedCharacter):
        async def _click(_e: ft.ControlEvent) -> None:
            if not c.still_path or not Path(c.still_path).is_file():
                self._set_status("Still file missing — re-upload and save.", error=True)
                return
            mv = getattr(self.state, "motion_sync_view", None)
            ok = False
            if mv is not None:
                if hasattr(mv, "receive_character"):
                    ok = bool(mv.receive_character(c.still_path))
                elif hasattr(mv, "_set_character"):
                    ok = bool(mv._set_character(c.still_path))
            switch = getattr(self.state, "switch_to_motion_sync", None)
            if switch:
                switch()
            if ok:
                self._set_status(f"Motion Sync ← {c.name}")
                try:
                    from media_studio.flet_dialogs import show_snack

                    show_snack(
                        self.page,
                        f"Motion Sync · Character: {c.name}",
                    )
                except Exception:
                    pass
            else:
                self._set_status(
                    f"Could not set Motion Sync character: {c.name}",
                    error=True,
                )

        return _click
