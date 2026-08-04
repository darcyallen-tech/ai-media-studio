"""
Characters tab — local reusable character stills.

Phase 2: multi-angle (1–3), Generate variation (I2I), save-from-elsewhere shortcuts.
"""

from __future__ import annotations

import traceback
from pathlib import Path
from typing import TYPE_CHECKING

import flet as ft

from media_studio.character_store import (
    DEFAULT_VARIATION_MODEL,
    MAX_STILLS_PER_CHARACTER,
    VARIATION_PROMPT,
    SavedCharacter,
    add_character,
    add_character_angle,
    delete_character,
    load_characters,
    remove_character_angle,
    set_primary_angle,
    update_character,
)
from media_studio.folder_util import show_in_folder
from media_studio.flet_pickers import pick_image
from media_studio.flet_progress import JobProgress, classify_progress
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
_ANGLE_THUMB = 56


class CharactersView:
    """Save and reuse character stills (local store only)."""

    def __init__(self, page: ft.Page, state: StudioState) -> None:
        self.page = page
        self.state = state
        self._still_path: str | None = None
        self._editing_id: str | None = None
        self._edit_angles: list[str] = []  # when editing: all angle paths
        self._variation_path: str | None = None
        self._variation_source_id: str | None = None

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

        # Multi-angle row (edit mode)
        self.angles_label = ft.Text(
            "Angles (primary + optional extras, max 3)",
            size=FONT_SM,
            color=TEXT_MUTED,
            visible=False,
        )
        self.angles_row = ft.Row(spacing=8, wrap=True, visible=False)
        self.btn_add_angle = ft.OutlinedButton(
            content="Add angle still",
            icon=ft.Icons.ADD_PHOTO_ALTERNATE_OUTLINED,
            on_click=self._pick_extra_angle,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
            visible=False,
            height=36,
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
        self.status = ft.Text("", size=FONT_SM, color=TEXT_MUTED, max_lines=4)
        self.job_progress = JobProgress()

        # Variation result panel
        self.var_preview = ft.Image(
            src="",
            width=120,
            height=120,
            fit=ft.BoxFit.COVER,
            border_radius=6,
            visible=False,
        )
        self.var_label = ft.Text(
            "",
            size=FONT_SM,
            color=TEXT_MUTED,
            visible=False,
            max_lines=2,
        )
        self.btn_var_new = ft.FilledButton(
            content="Save as new character",
            on_click=self._variation_save_new,
            style=ft.ButtonStyle(bgcolor=ACCENT_BRIGHT, color=TEXT),
            height=36,
            visible=False,
        )
        self.btn_var_angle = ft.OutlinedButton(
            content="Add as angle",
            on_click=self._variation_add_angle,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
            height=36,
            visible=False,
        )
        self.btn_var_replace = ft.OutlinedButton(
            content="Replace primary",
            on_click=self._variation_replace_primary,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
            height=36,
            visible=False,
        )
        self.btn_var_dismiss = ft.TextButton(
            content="Dismiss",
            on_click=self._dismiss_variation,
            style=ft.ButtonStyle(color=TEXT_MUTED),
            visible=False,
        )
        self.variation_box = ft.Container(
            content=ft.Column(
                [
                    ft.Text(
                        "Variation result",
                        size=FONT_SM,
                        color=TEXT,
                        weight=ft.FontWeight.W_600,
                    ),
                    self.var_preview,
                    self.var_label,
                    ft.Row(
                        [
                            self.btn_var_new,
                            self.btn_var_angle,
                            self.btn_var_replace,
                            self.btn_var_dismiss,
                        ],
                        spacing=4,
                        wrap=True,
                    ),
                ],
                spacing=6,
                tight=True,
            ),
            bgcolor=PANEL_ELEVATED,
            border=ft.Border.all(1, ACCENT),
            border_radius=8,
            padding=10,
            visible=False,
        )

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
                "this is the short list for Motion Sync, Director, and Creative Vision. "
                "Up to 3 angles per character; optional I2I variation.",
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
            self.angles_label,
            self.angles_row,
            self.btn_add_angle,
            ft.Row([self.btn_save, self.btn_cancel_edit], spacing=8),
            self.variation_box,
            self.job_progress.control,
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

    # ----- shortcuts / public API -----

    def open_with_still(
        self,
        path: str,
        *,
        suggested_name: str = "",
        notes: str = "",
    ) -> bool:
        """
        Prefill Add form with a still (from Motion Sync / Director / Studio).
        User still enters/confirms name and Saves.
        """
        p = Path(path)
        if not p.is_file():
            self._set_status(f"Missing still: {path}", error=True)
            return False
        self._editing_id = None
        self._edit_angles = []
        self._sync_angle_ui()
        self.btn_save.content = "Save character"
        self.btn_cancel_edit.visible = False
        self.name_field.value = (suggested_name or "").strip()
        self.notes_field.value = (notes or "").strip()
        self._set_still(str(p.resolve()))
        self._set_status(
            f"Still ready — add a name and Save character: {p.name}"
        )
        return True

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

    def _sync_angle_ui(self) -> None:
        editing = bool(self._editing_id)
        self.angles_label.visible = editing
        self.angles_row.visible = editing
        self.btn_add_angle.visible = editing
        self.angles_row.controls.clear()
        if not editing:
            return
        for i, path in enumerate(self._edit_angles):
            ok = Path(path).is_file()
            is_primary = i == 0
            thumb: ft.Control
            if ok:
                thumb = ft.Image(
                    src=path,
                    width=_ANGLE_THUMB,
                    height=_ANGLE_THUMB,
                    fit=ft.BoxFit.COVER,
                    border_radius=4,
                )
            else:
                thumb = ft.Container(
                    width=_ANGLE_THUMB,
                    height=_ANGLE_THUMB,
                    bgcolor=PANEL,
                    border_radius=4,
                    content=ft.Icon(
                        ft.Icons.BROKEN_IMAGE_OUTLINED, size=18, color=TEXT_MUTED
                    ),
                    alignment=ft.Alignment.CENTER,
                )
            badge = "Primary" if is_primary else f"Angle {i + 1}"
            actions = [
                ft.TextButton(
                    content="Primary",
                    on_click=self._make_set_primary_local(path),
                    style=ft.ButtonStyle(color=ACCENT),
                    visible=not is_primary,
                    height=28,
                ),
                ft.TextButton(
                    content="Remove",
                    on_click=self._make_remove_angle_local(path),
                    style=ft.ButtonStyle(color="#e57373"),
                    visible=len(self._edit_angles) > 1,
                    height=28,
                ),
            ]
            self.angles_row.controls.append(
                ft.Container(
                    content=ft.Column(
                        [
                            thumb,
                            ft.Text(badge, size=11, color=TEXT_MUTED),
                            ft.Row(actions, spacing=0, tight=True),
                        ],
                        spacing=2,
                        tight=True,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    border=ft.Border.all(2 if is_primary else 1, ACCENT if is_primary else BORDER),
                    border_radius=6,
                    padding=6,
                )
            )
        n = len(self._edit_angles)
        self.btn_add_angle.disabled = n >= MAX_STILLS_PER_CHARACTER
        self.btn_add_angle.tooltip = (
            f"Max {MAX_STILLS_PER_CHARACTER} stills"
            if n >= MAX_STILLS_PER_CHARACTER
            else "Upload another angle for this character"
        )
        self.angles_label.value = (
            f"Angles ({n}/{MAX_STILLS_PER_CHARACTER}) — primary used in Motion Sync"
        )

    def _make_set_primary_local(self, path: str):
        async def _click(_e: ft.ControlEvent) -> None:
            if path not in self._edit_angles:
                return
            self._edit_angles = [path] + [p for p in self._edit_angles if p != path]
            self._set_still(path)
            self._sync_angle_ui()
            try:
                self.page.update()
            except Exception:
                pass

        return _click

    def _make_remove_angle_local(self, path: str):
        async def _click(_e: ft.ControlEvent) -> None:
            if len(self._edit_angles) <= 1:
                self._set_status("Keep at least one still.", error=True)
                return
            self._edit_angles = [p for p in self._edit_angles if p != path]
            if self._still_path == path or (
                self._edit_angles and self._still_path not in self._edit_angles
            ):
                self._set_still(self._edit_angles[0])
            self._sync_angle_ui()
            try:
                self.page.update()
            except Exception:
                pass

        return _click

    async def _pick_extra_angle(self, e: ft.ControlEvent) -> None:
        if not self._editing_id:
            return
        if len(self._edit_angles) >= MAX_STILLS_PER_CHARACTER:
            self._set_status(
                f"Max {MAX_STILLS_PER_CHARACTER} stills per character.",
                error=True,
            )
            return
        try:
            files = await pick_image(self.page, dialog_title="Extra angle still")
        except Exception as exc:
            self._set_status(f"Picker error: {exc}", error=True)
            return
        if not files or not files[0].path:
            return
        p = str(Path(files[0].path).resolve())
        if p not in self._edit_angles:
            self._edit_angles.append(p)
        self._sync_angle_ui()
        try:
            self.page.update()
        except Exception:
            pass

    def _cancel_edit(self, e: ft.ControlEvent | None = None) -> None:
        self._editing_id = None
        self._edit_angles = []
        self.name_field.value = ""
        self.notes_field.value = ""
        self.btn_save.content = "Save character"
        self.btn_cancel_edit.visible = False
        self._sync_angle_ui()
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
                paths = list(self._edit_angles) if self._edit_angles else None
                if paths is None and self._still_path:
                    paths = [self._still_path]
                if not paths:
                    self._set_status("At least one still is required.", error=True)
                    return
                updated = update_character(
                    self._editing_id,
                    name=name,
                    notes=notes,
                    still_paths=paths,
                )
                if not updated:
                    self._set_status("Character not found.", error=True)
                    return
                self._set_status(f"Updated: {updated.name} ({updated.angle_count()} angle(s))")
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
            self._edit_angles = []
            self.btn_save.content = "Save character"
            self.btn_cancel_edit.visible = False
            self.name_field.value = ""
            self.notes_field.value = ""
            self._sync_angle_ui()
            self._clear_still()
            self.refresh()
        except Exception as exc:
            self._set_status(str(exc), error=True)

    # ----- variation -----

    def _show_variation(self, path: str, *, source_id: str | None) -> None:
        self._variation_path = path
        self._variation_source_id = source_id
        self.var_preview.src = path
        self.var_preview.visible = True
        self.var_label.value = Path(path).name
        self.var_label.visible = True
        self.btn_var_new.visible = True
        self.btn_var_angle.visible = bool(source_id)
        self.btn_var_replace.visible = bool(source_id)
        self.btn_var_dismiss.visible = True
        self.variation_box.visible = True
        # Disable add-angle if source already at max
        if source_id:
            ch = next((c for c in load_characters() if c.id == source_id), None)
            if ch and ch.angle_count() >= MAX_STILLS_PER_CHARACTER:
                self.btn_var_angle.disabled = True
                self.btn_var_angle.tooltip = f"Max {MAX_STILLS_PER_CHARACTER} angles — remove one first"
            else:
                self.btn_var_angle.disabled = False
                self.btn_var_angle.tooltip = "Append variation as an extra angle"
        try:
            self.page.update()
        except Exception:
            pass

    def _dismiss_variation(self, e: ft.ControlEvent | None = None) -> None:
        self._variation_path = None
        self._variation_source_id = None
        self.var_preview.visible = False
        self.var_label.visible = False
        self.btn_var_new.visible = False
        self.btn_var_angle.visible = False
        self.btn_var_replace.visible = False
        self.btn_var_dismiss.visible = False
        self.variation_box.visible = False
        try:
            self.page.update()
        except Exception:
            pass

    async def _variation_save_new(self, e: ft.ControlEvent) -> None:
        if not self._variation_path or not Path(self._variation_path).is_file():
            self._set_status("No variation to save.", error=True)
            return
        src_id = self._variation_source_id
        base = ""
        if src_id:
            ch = next((c for c in load_characters() if c.id == src_id), None)
            if ch:
                base = ch.name
        name = (base + " · variation").strip(" ·") if base else "Character variation"
        notes = f"Variation of {base}" if base else "I2I variation"
        try:
            entry = add_character(
                name=name,
                still_path=self._variation_path,
                notes=notes,
            )
            self._dismiss_variation()
            self._set_status(f"Saved new character: {entry.name}")
            self.refresh()
        except Exception as exc:
            self._set_status(str(exc), error=True)

    async def _variation_add_angle(self, e: ft.ControlEvent) -> None:
        if not self._variation_path or not self._variation_source_id:
            return
        try:
            updated = add_character_angle(
                self._variation_source_id,
                self._variation_path,
                as_primary=False,
            )
            if updated:
                self._dismiss_variation()
                self._set_status(
                    f"Added angle on {updated.name} ({updated.angle_count()}/{MAX_STILLS_PER_CHARACTER})"
                )
                if self._editing_id == updated.id:
                    self._edit_angles = updated.all_stills()
                    self._sync_angle_ui()
                self.refresh()
            else:
                self._set_status("Character not found.", error=True)
        except Exception as exc:
            self._set_status(str(exc), error=True)

    async def _variation_replace_primary(self, e: ft.ControlEvent) -> None:
        if not self._variation_path or not self._variation_source_id:
            return
        try:
            updated = add_character_angle(
                self._variation_source_id,
                self._variation_path,
                as_primary=True,
            )
            # If already at max, as_primary still prepends — may exceed then trim in update
            if updated and updated.angle_count() > MAX_STILLS_PER_CHARACTER:
                # keep primary + next (max-1)
                update_character(
                    updated.id,
                    still_paths=updated.all_stills()[:MAX_STILLS_PER_CHARACTER],
                )
                updated = next(
                    (c for c in load_characters() if c.id == self._variation_source_id),
                    updated,
                )
            if updated:
                self._dismiss_variation()
                self._set_status(f"Primary replaced on {updated.name}")
                if self._editing_id == updated.id:
                    self._edit_angles = updated.all_stills()
                    self._set_still(updated.primary_still() or self._still_path or "")
                    self._sync_angle_ui()
                self.refresh()
            else:
                self._set_status("Character not found.", error=True)
        except Exception as exc:
            self._set_status(str(exc), error=True)

    def _make_generate_variation(self, c: SavedCharacter):
        async def _click(_e: ft.ControlEvent) -> None:
            await self._run_variation(c)

        return _click

    async def _run_variation(self, c: SavedCharacter) -> None:
        primary = c.primary_still()
        if not primary or not Path(primary).is_file():
            self._set_status("Still file missing — re-upload and save.", error=True)
            return
        from media_studio.secrets_store import has_fal_key

        if not has_fal_key():
            self._set_status("FAL API key required — open Settings.", error=True)
            return
        if self.state.is_busy("characters"):
            return
        if not self.state.try_busy("characters"):
            return

        self.job_progress.start("Generating variation…", self.page)
        self._set_status(f"I2I variation for {c.name}…")

        def on_progress(msg: str) -> None:
            self.job_progress.set_message(classify_progress(msg), self.page)

        try:
            from media_studio.job_context import to_thread_with_job
            from media_studio.services import generate

            result = await to_thread_with_job(
                self.state,
                generate,
                VARIATION_PROMPT,
                model_choice=DEFAULT_VARIATION_MODEL,
                image_file=primary,
                output_dir=self.state.output_dir,
                on_progress=on_progress,
                scenario="character-variation",
            )
            path = None
            if result.ok:
                path = getattr(result, "primary_image", None)
                if not path:
                    imgs = getattr(result, "image_paths", None) or []
                    path = imgs[0] if imgs else None
            if result.ok and path and Path(path).is_file():
                self.job_progress.finish_ok("Variation ready", self.page)
                self._show_variation(str(path), source_id=c.id)
                self._set_status(
                    f"Variation ready for {c.name} — save as new, add angle, or replace primary."
                )
            else:
                err = getattr(result, "status", None) or "Variation failed."
                self.job_progress.finish_error(err, self.page)
                self._set_status(err, error=True)
        except Exception as exc:
            self.job_progress.finish_error(str(exc), self.page)
            self._set_status(f"Variation error: {exc}", error=True)
            traceback.print_exc()
        finally:
            self.state.clear_busy("characters")
            try:
                self.page.update()
            except Exception:
                pass

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
        primary = c.primary_still()
        still_ok = bool(primary and Path(primary).is_file())
        thumb: ft.Control
        if still_ok and primary:
            thumb = ft.Image(
                src=primary,
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
                content=ft.Icon(
                    ft.Icons.BROKEN_IMAGE_OUTLINED, size=24, color=TEXT_MUTED
                ),
            )
        notes = c.display_notes() or "—"
        n_angles = c.angle_count()
        angle_note = (
            f" · {n_angles} angles" if n_angles > 1 else ""
        )
        name_txt = ft.Text(
            c.name,
            size=FONT_SM,
            color=TEXT,
            weight=ft.FontWeight.W_600,
            max_lines=1,
        )
        notes_txt = ft.Text(
            f"{notes}{angle_note}",
            size=FONT_SM,
            color=TEXT_MUTED,
            max_lines=2,
        )
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
            tooltip="Set primary still as Motion Sync character and open that tab",
        )
        btn_var = ft.OutlinedButton(
            content="Generate variation",
            on_click=self._make_generate_variation(c),
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
            height=36,
            disabled=not still_ok,
            tooltip="I2I face-lock variation (Flux 2 Pro) — save as new or add angle",
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
                                [btn_use, btn_var, btn_edit, btn_delete, btn_folder],
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
            self._edit_angles = list(c.all_stills())
            self.name_field.value = c.name
            self.notes_field.value = c.notes or ""
            self.btn_save.content = "Save changes"
            self.btn_cancel_edit.visible = True
            primary = c.primary_still()
            if primary and Path(primary).is_file():
                self._set_still(primary)
            else:
                self._clear_still()
            self._sync_angle_ui()
            self._set_status(f"Editing: {c.name}")
            try:
                self.page.update()
            except Exception:
                pass

        return _click

    def _make_delete(self, c: SavedCharacter):
        async def _click(_e: ft.ControlEvent) -> None:
            ok = delete_character(c.id)
            if ok:
                if self._editing_id == c.id:
                    self._cancel_edit()
                if self._variation_source_id == c.id:
                    self._dismiss_variation()
                self._set_status(f"Deleted: {c.name}")
                self.refresh()
            else:
                self._set_status("Delete failed.", error=True)

        return _click

    def _make_show_folder(self, c: SavedCharacter):
        async def _click(_e: ft.ControlEvent) -> None:
            path = c.primary_still() or c.still_path
            msg = show_in_folder(path)
            self._set_status(msg)

        return _click

    def _make_use_motion(self, c: SavedCharacter):
        async def _click(_e: ft.ControlEvent) -> None:
            primary = c.primary_still()
            if not primary or not Path(primary).is_file():
                self._set_status("Still file missing — re-upload and save.", error=True)
                return
            mv = getattr(self.state, "motion_sync_view", None)
            ok = False
            if mv is not None:
                if hasattr(mv, "receive_character"):
                    ok = bool(mv.receive_character(primary))
                elif hasattr(mv, "_set_character"):
                    ok = bool(mv._set_character(primary))
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
