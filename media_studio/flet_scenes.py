"""
Scenes tab — local reusable location / establishing stills.

Parallel to Characters: Character = who; Scene = where (Director scene refs).
"""

from __future__ import annotations

import traceback
from pathlib import Path
from typing import TYPE_CHECKING, Any

import flet as ft

from media_studio.folder_util import show_in_folder
from media_studio.flet_dialogs import close_dialog, show_dialog
from media_studio.flet_enhance import make_enhance_button, run_prompt_enhance
from media_studio.flet_pickers import pick_image
from media_studio.flet_progress import JobProgress, classify_progress
from media_studio.flet_source_strip import PreviousSourcesStrip, ResolveSourcesStrip
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
    label,
    make_estimated_cost_box,
    section_title,
    styled_dropdown,
)
from media_studio.scene_store import (
    SavedScene,
    SceneHasChildrenError,
    add_scene,
    default_scene_quality,
    delete_scene,
    detect_still_aspect,
    estimate_scene_t2i_cost,
    list_base_scenes,
    list_scene_variations,
    load_scenes,
    normalize_scene_aspect,
    preferred_scene_edit_model,
    resolve_scene_t2i_args,
    scene_aspect_ui_options,
    scene_edit_model_labels,
    scene_quality_options,
    scene_t2i_prompt,
    scene_variation_prompt,
    set_scene_locked,
    t2i_scene_model_labels,
    update_scene,
)

if TYPE_CHECKING:
    from media_studio.flet_app import StudioState

_THUMB = 72
_PREVIEW = 160


class ScenesView:
    """Save and reuse location stills (local store only)."""

    def __init__(self, page: ft.Page, state: StudioState) -> None:
        self.page = page
        self.state = state
        self._still_path: str | None = None
        self._edit_id: str | None = None
        self._t2i_pending_path: str | None = None
        self._pending_aspect: str = "16:9"  # last generate / detected still aspect
        self._variations_expanded: set[str] = set()
        # Variation transform state
        self._var_parent_id: str | None = None
        self._var_parent_name: str = ""
        self._var_parent_path: str | None = None
        self._var_pending_path: str | None = None

        # Lightbox (Characters-style enlarge)
        self._lightbox_dialog: ft.AlertDialog | None = None
        self._lightbox_img: ft.Image | None = None
        self._lightbox_title: ft.Text | None = None

        self.preview = ft.Image(
            src="",
            width=_PREVIEW,
            height=_PREVIEW,
            fit=ft.BoxFit.COVER,
            border_radius=8,
            visible=False,
        )
        self.preview_empty = ft.Container(
            width=_PREVIEW,
            height=_PREVIEW,
            bgcolor=PANEL_ELEVATED,
            border=ft.Border.all(1, BORDER),
            border_radius=8,
            alignment=ft.Alignment.CENTER,
            content=ft.Column(
                [
                    ft.Icon(ft.Icons.LANDSCAPE_OUTLINED, size=32, color=TEXT_MUTED),
                    ft.Text("No still", size=FONT_SM, color=TEXT_MUTED),
                ],
                tight=True,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=4,
            ),
        )
        self.still_label = ft.Text(
            "Upload a location still or Generate one",
            size=FONT_SM,
            color=TEXT_MUTED,
            max_lines=2,
        )
        self.btn_upload = ft.OutlinedButton(
            content="Upload still",
            icon=ft.Icons.UPLOAD_FILE,
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
            on_load=self._on_prev_still,
            media_kind="image",
        )
        self.resolve_strip = ResolveSourcesStrip(
            page,
            on_load=self._on_resolve_still,
            media_kind="image",
        )

        self.name_field = ft.TextField(
            label="Name (required)",
            hint_text='e.g. "Modern Gym", "Downtown street day"',
            dense=True,
            filled=True,
            fill_color=PANEL_ELEVATED,
            border_color=BORDER,
            color=TEXT,
            text_size=FONT_SM,
        )
        self.notes_field = ft.TextField(
            label="Notes (optional)",
            hint_text="Lighting, time of day, use-case…",
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
            content="Save scene",
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

        # --- Generate (T2I) ---
        t2i_labs = t2i_scene_model_labels()
        self.t2i_desc = ft.TextField(
            label="Location description",
            hint_text='e.g. "empty downtown street daytime, soft sun, no people"',
            dense=True,
            filled=True,
            fill_color=PANEL_ELEVATED,
            border_color=BORDER,
            color=TEXT,
            text_size=FONT_SM,
            multiline=True,
            min_lines=5,
            max_lines=12,
        )
        self.t2i_model_dd = styled_dropdown(
            label_text="T2I model",
            options=t2i_labs,
            value=t2i_labs[0] if t2i_labs else None,
            on_select=self._on_t2i_model,
            expand=True,
        )
        aspect0 = scene_aspect_ui_options(t2i_labs[0] if t2i_labs else None)
        self.t2i_aspect_dd = styled_dropdown(
            label_text="Aspect",
            options=aspect0,
            value=aspect0[0] if aspect0 else "16:9 · Horizontal",
            on_select=self._refresh_t2i_cost,
            expand=True,
        )
        qual0 = scene_quality_options(t2i_labs[0] if t2i_labs else None)
        self.t2i_quality_dd = styled_dropdown(
            label_text="Quality",
            options=qual0 or ["Standard", "HD"],
            value=default_scene_quality(qual0),
            on_select=self._refresh_t2i_cost,
            expand=True,
        )
        self.t2i_cost_text, self.t2i_cost_box = make_estimated_cost_box(
            initial="Est. cost: —"
        )
        self.btn_t2i_enhance = make_enhance_button(on_click=self._on_t2i_enhance)
        self.btn_t2i_gen = ft.FilledButton(
            content="Generate plate",
            icon=ft.Icons.AUTO_AWESOME,
            on_click=self._run_t2i,
            style=ft.ButtonStyle(bgcolor=ACCENT, color=TEXT),
            height=40,
        )
        self.t2i_preview = ft.Image(
            src="",
            width=120,
            height=90,
            fit=ft.BoxFit.COVER,
            border_radius=6,
            visible=False,
        )
        self.t2i_aspect_badge = ft.Container(
            content=ft.Text("16:9", size=11, color=TEXT, weight=ft.FontWeight.W_700),
            bgcolor="#c62828",
            border_radius=4,
            padding=ft.Padding.symmetric(horizontal=6, vertical=2),
            visible=False,
            left=4,
            top=4,
        )
        self.btn_t2i_use = ft.OutlinedButton(
            content="Use as scene still",
            on_click=self._use_t2i_result,
            style=ft.ButtonStyle(color=ACCENT, side=ft.BorderSide(1, ACCENT)),
            visible=False,
        )
        self.t2i_preview_tap = ft.GestureDetector(
            content=ft.Stack(
                [self.t2i_preview, self.t2i_aspect_badge],
                width=120,
                height=90,
            ),
            on_tap=self._on_tap_t2i_preview,
        )
        self.t2i_box = ft.Container(
            content=ft.Column(
                [
                    ft.Text(
                        "Generate location plate (T2I)",
                        size=FONT_SM,
                        color=TEXT,
                        weight=ft.FontWeight.W_600,
                    ),
                    ft.Text(
                        "Establishing bias — empty or lightly populated; no hero talent "
                        "unless you ask for people. Aspect and quality are separate. "
                        "Click the result thumb to enlarge.",
                        size=FONT_SM,
                        color=TEXT_MUTED,
                    ),
                    self.t2i_desc,
                    ft.Row([self.t2i_model_dd], spacing=0),
                    ft.Row(
                        [self.t2i_aspect_dd, self.t2i_quality_dd],
                        spacing=8,
                    ),
                    ft.Row(
                        [self.btn_t2i_enhance, self.btn_t2i_gen],
                        spacing=8,
                    ),
                    self.t2i_cost_box,
                    ft.Row(
                        [self.t2i_preview_tap, self.btn_t2i_use],
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ],
                spacing=6,
                tight=True,
            ),
            bgcolor=PANEL_ELEVATED,
            border=ft.Border.all(1, BORDER),
            border_radius=8,
            padding=10,
        )

        # --- Variation transform (I2I) ---
        edit_labs = scene_edit_model_labels()
        pref_edit = preferred_scene_edit_model()
        # Prefer label match if available
        edit_default = edit_labs[0] if edit_labs else pref_edit
        for lab in edit_labs:
            if pref_edit.lower() in lab.lower() or lab.lower() in pref_edit.lower():
                edit_default = lab
                break
        self.var_parent_label = ft.Text("", size=FONT_SM, color=TEXT_MUTED)
        self.var_prompt = ft.TextField(
            label="Transform (season, time of day, weather, era…)",
            hint_text='e.g. "winter snow, overcast afternoon" or "post-apocalyptic ruin"',
            dense=True,
            filled=True,
            fill_color=PANEL_ELEVATED,
            border_color=BORDER,
            color=TEXT,
            text_size=FONT_SM,
            multiline=True,
            min_lines=3,
            max_lines=8,
        )
        self.var_name = ft.TextField(
            label="Variation name (required to save)",
            hint_text='e.g. "Neighborhood Park – Winter"',
            dense=True,
            filled=True,
            fill_color=PANEL_ELEVATED,
            border_color=BORDER,
            color=TEXT,
            text_size=FONT_SM,
        )
        self.var_model_dd = styled_dropdown(
            label_text="Edit model",
            options=edit_labs or [pref_edit],
            value=edit_default,
            on_select=self._refresh_var_cost,
            expand=True,
        )
        self.var_cost_text, self.var_cost_box = make_estimated_cost_box(
            initial="Est. cost: —"
        )
        self.btn_var_enhance = make_enhance_button(on_click=self._on_var_enhance)
        self.btn_var_gen = ft.FilledButton(
            content="Generate variation",
            icon=ft.Icons.AUTO_FIX_HIGH,
            on_click=self._run_variation,
            style=ft.ButtonStyle(bgcolor=ACCENT, color=TEXT),
            height=40,
        )
        self.btn_var_save = ft.FilledButton(
            content="Confirm & save variation",
            on_click=self._save_variation,
            style=ft.ButtonStyle(bgcolor=ACCENT_BRIGHT, color=TEXT),
            height=40,
            visible=False,
        )
        self.btn_var_close = ft.TextButton(
            content="Close",
            on_click=self._close_variation_panel,
            style=ft.ButtonStyle(color=TEXT_MUTED),
        )
        self.var_preview = ft.Image(
            src="",
            width=140,
            height=100,
            fit=ft.BoxFit.COVER,
            border_radius=6,
            visible=False,
        )
        self.var_preview_tap = ft.GestureDetector(
            content=self.var_preview,
            on_tap=self._on_tap_var_preview,
        )
        self.var_box = ft.Container(
            content=ft.Column(
                [
                    ft.Text(
                        "Create variation (I2I)",
                        size=FONT_SM,
                        color=TEXT,
                        weight=ft.FontWeight.W_600,
                    ),
                    self.var_parent_label,
                    ft.Text(
                        "Keeps the same place; changes season, weather, time, era, etc. "
                        "Click preview to enlarge.",
                        size=FONT_SM,
                        color=TEXT_MUTED,
                    ),
                    self.var_prompt,
                    self.var_name,
                    ft.Row([self.var_model_dd], spacing=0),
                    ft.Row(
                        [self.btn_var_enhance, self.btn_var_gen],
                        spacing=8,
                    ),
                    self.var_cost_box,
                    ft.Row(
                        [self.var_preview_tap, self.btn_var_save, self.btn_var_close],
                        spacing=8,
                        wrap=True,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
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

        self.status = ft.Text("", size=FONT_SM, color=TEXT_MUTED, max_lines=4)
        self.job_progress = JobProgress()

        self.empty_state = ft.Column(
            [
                ft.Text(
                    "No scenes yet.",
                    size=FONT_SM,
                    color=TEXT,
                    weight=ft.FontWeight.W_600,
                ),
                ft.Text(
                    "Save gym, street, living room plates here for Director scene refs.",
                    size=FONT_SM,
                    color=TEXT_MUTED,
                ),
            ],
            spacing=4,
            tight=True,
            visible=True,
        )
        self.list_host = ft.Column(spacing=8, tight=True)
        self.list_count = ft.Text("", size=FONT_SM, color=TEXT_MUTED)

        self._refresh_t2i_cost_sync()
        self.refresh()

    # ----- layout -----

    def build(self) -> ft.Control:
        from media_studio.flet_layout import make_split_workspace
        from media_studio.flet_theme import RAIL_WIDTH

        left = [
            section_title("Scenes"),
            ft.Text(
                "Location / establishing stills — where the action happens. "
                "Local store only (like Characters). Use in Director as scene refs.",
                size=FONT_SM,
                color=TEXT_MUTED,
            ),
            ft.Divider(height=1, color=BORDER),
            label("Add / edit scene", muted=True),
            ft.GestureDetector(
                content=ft.Stack(
                    [self.preview_empty, self.preview],
                    width=_PREVIEW,
                    height=_PREVIEW,
                ),
                on_tap=self._on_tap_form_preview,
            ),
            ft.Text("Click still to enlarge", size=11, color=TEXT_MUTED),
            self.still_label,
            ft.Row(
                [self.btn_upload, self.btn_clear_still],
                spacing=6,
                wrap=True,
            ),
            self.prev_strip.root,
            self.resolve_strip.root,
            self.name_field,
            self.notes_field,
            ft.Row([self.btn_save, self.btn_cancel_edit], spacing=8),
            ft.Divider(height=1, color=BORDER),
            self.t2i_box,
            self.var_box,
            self.job_progress.control,
            self.status,
        ]
        right = ft.Column(
            [
                section_title("Saved scenes"),
                self.list_count,
                self.empty_state,
                self.list_host,
            ],
            spacing=8,
            tight=True,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )
        return make_split_workspace(left, right, left_width=max(RAIL_WIDTH, 420))

    # ----- public -----

    def refresh(self) -> None:
        bases = list_base_scenes()
        self.list_host.controls.clear()
        n_base = len(bases)
        n_all = len(load_scenes())
        n_var = max(0, n_all - n_base)
        self.list_count.value = (
            f"{n_base} scene(s)"
            + (f" · {n_var} variation(s)" if n_var else "")
            if n_base
            else ""
        )
        self.empty_state.visible = n_base == 0
        for s in bases:
            kids = list_scene_variations(s.id)
            self.list_host.controls.append(self._card(s, children=kids))
        try:
            self.page.update()
        except Exception:
            pass

    def open_with_still(
        self,
        path: str,
        *,
        suggested_name: str = "",
        notes: str = "",
    ) -> bool:
        p = Path(path)
        if not p.is_file():
            self._set_status(f"Missing still: {path}", error=True)
            return False
        self._set_still(str(p.resolve()))
        if suggested_name and not (self.name_field.value or "").strip():
            self.name_field.value = suggested_name
        if notes and not (self.notes_field.value or "").strip():
            self.notes_field.value = notes
        self._set_status(f"Still ready: {p.name} — add a name and Save.")
        try:
            self.page.update()
        except Exception:
            pass
        return True

    # ----- still / form -----

    def _set_status(self, msg: str, *, error: bool = False) -> None:
        self.status.value = msg
        self.status.color = "#ef9a9a" if error else TEXT_MUTED
        try:
            self.page.update()
        except Exception:
            pass

    def _set_still(self, path: str | None, *, aspect: str | None = None) -> None:
        if path and Path(path).is_file():
            self._still_path = str(Path(path).resolve())
            self.preview.src = self._still_path
            self.preview.visible = True
            self.preview_empty.visible = False
            ar = normalize_scene_aspect(aspect) or detect_still_aspect(self._still_path)
            if ar:
                self._pending_aspect = ar
            badge = f" · {ar}" if ar else ""
            self.still_label.value = f"{Path(self._still_path).name}{badge}"
            self.still_label.color = TEXT
            try:
                self.prev_strip.record_and_refresh(self._still_path)
            except Exception:
                pass
        else:
            self._still_path = None
            self.preview.src = ""
            self.preview.visible = False
            self.preview_empty.visible = True
            self.still_label.value = "Upload a location still or Generate one"
            self.still_label.color = TEXT_MUTED

    def _reset_form(self) -> None:
        self._edit_id = None
        self._set_still(None)
        self.name_field.value = ""
        self.notes_field.value = ""
        self.btn_save.content = "Save scene"
        self.btn_cancel_edit.visible = False
        self._t2i_pending_path = None
        self._pending_aspect = normalize_scene_aspect(self.t2i_aspect_dd.value) or "16:9"
        self.t2i_preview.visible = False
        self.t2i_aspect_badge.visible = False
        self.btn_t2i_use.visible = False

    async def _pick_still(self, e: ft.ControlEvent) -> None:
        try:
            files = await pick_image(self.page, dialog_title="Scene still")
        except Exception as exc:
            self._set_status(f"Picker error: {exc}", error=True)
            return
        if not files or not files[0].path:
            return
        self._set_still(files[0].path)
        self._set_status(f"Still: {Path(files[0].path).name}")
        try:
            self.page.update()
        except Exception:
            pass

    async def _clear_still(self, e: ft.ControlEvent) -> None:
        self._set_still(None)
        try:
            self.page.update()
        except Exception:
            pass

    def _on_prev_still(self, path: str) -> None:
        self._set_still(path)
        self._set_status(f"Previous: {Path(path).name}")
        try:
            self.page.update()
        except Exception:
            pass

    def _on_resolve_still(self, path: str) -> None:
        self._set_still(path)
        self._set_status(f"From Resolve: {Path(path).name}")
        try:
            self.resolve_strip.refresh()
            self.page.update()
        except Exception:
            pass

    async def _save(self, e: ft.ControlEvent) -> None:
        name = (self.name_field.value or "").strip()
        notes = (self.notes_field.value or "").strip()
        if not name:
            self._set_status("Name is required.", error=True)
            return
        if not self._still_path or not Path(self._still_path).is_file():
            self._set_status("Add a still (upload or generate) before Save.", error=True)
            return
        try:
            ar = (
                self._pending_aspect
                or detect_still_aspect(self._still_path)
                or normalize_scene_aspect(self.t2i_aspect_dd.value)
                or ""
            )
            if self._edit_id:
                updated = update_scene(
                    self._edit_id,
                    name=name,
                    notes=notes,
                    still_path=self._still_path,
                    aspect=ar,
                )
                if not updated:
                    self._set_status("Scene not found.", error=True)
                    return
                badge = f" · {updated.aspect}" if updated.aspect else ""
                self._set_status(f"Updated: {updated.name}{badge}")
            else:
                entry = add_scene(
                    name=name,
                    still_path=self._still_path,
                    notes=notes,
                    aspect=ar,
                )
                badge = f" · {entry.aspect}" if entry.aspect else ""
                self._set_status(f"Saved scene: {entry.name}{badge}")
            self._reset_form()
            self.refresh()
        except Exception as exc:
            self._set_status(str(exc), error=True)

    async def _cancel_edit(self, e: ft.ControlEvent) -> None:
        self._reset_form()
        self._set_status("Edit cancelled.")
        try:
            self.page.update()
        except Exception:
            pass

    # ----- T2I -----

    def _refresh_t2i_cost_sync(self) -> None:
        try:
            self.t2i_cost_text.value = estimate_scene_t2i_cost(
                t2i_label=self.t2i_model_dd.value,
                quality=self.t2i_quality_dd.value,
                aspect=self.t2i_aspect_dd.value,
            )
        except Exception:
            self.t2i_cost_text.value = "Est. cost: —"

    async def _refresh_t2i_cost(self, e: ft.ControlEvent | None = None) -> None:
        self._refresh_t2i_cost_sync()
        try:
            self.page.update()
        except Exception:
            pass

    async def _on_t2i_model(self, e: ft.ControlEvent | None = None) -> None:
        from media_studio.flet_theme import dropdown_options

        model = self.t2i_model_dd.value
        aspects = scene_aspect_ui_options(model)
        self.t2i_aspect_dd.options = dropdown_options(aspects)
        cur_a = self.t2i_aspect_dd.value
        if cur_a not in aspects:
            # Keep same ratio if possible
            ar = normalize_scene_aspect(cur_a) or "16:9"
            match = next(
                (a for a in aspects if normalize_scene_aspect(a) == ar),
                aspects[0] if aspects else "16:9 · Horizontal",
            )
            self.t2i_aspect_dd.value = match
        quals = scene_quality_options(model)
        self.t2i_quality_dd.options = dropdown_options(quals or ["Standard", "HD"])
        if self.t2i_quality_dd.value not in (quals or []):
            self.t2i_quality_dd.value = default_scene_quality(quals)
        self._refresh_t2i_cost_sync()
        try:
            self.page.update()
        except Exception:
            pass

    async def _on_t2i_enhance(self, e: ft.ControlEvent) -> None:
        ar = normalize_scene_aspect(self.t2i_aspect_dd.value) or "16:9"
        frame = {
            "16:9": "wide horizontal establishing",
            "9:16": "tall vertical establishing",
            "1:1": "square establishing",
            "4:3": "classic horizontal establishing",
            "3:4": "tall classic establishing",
        }.get(ar, "establishing")

        def _extra() -> dict[str, Any]:
            return {
                "workspace": "scenes",
                "mode": "text_to_image",
                "aspect": ar,
                "guidance": (
                    "Rewrite as a photoreal establishing / location plate prompt. "
                    f"Framing: {frame} ({ar}). "
                    "Environment and architecture primary; empty or lightly populated; "
                    "no hero talent or portrait subject unless the user asked for people. "
                    "No text/logo/watermark. Keep the user's location intent."
                ),
            }

        await run_prompt_enhance(
            page=self.page,
            state=self.state,
            prompt_field=self.t2i_desc,
            get_model=lambda: self.t2i_model_dd.value,
            get_extra_context=_extra,
            status_ctrl=self.status,
            job_progress=self.job_progress,
            enhance_btn=self.btn_t2i_enhance,
            busy_controls=[self.btn_t2i_gen, self.btn_save],
            context_label="scene plate",
            allow_empty_with_context=True,
            busy_scope="scenes",
        )

    async def _run_t2i(self, e: ft.ControlEvent) -> None:
        from media_studio.secrets_store import has_fal_key

        if not has_fal_key():
            self._set_status("FAL API key required — open Settings.", error=True)
            return
        desc = (self.t2i_desc.value or "").strip()
        if not desc:
            self._set_status("Enter a location description to generate.", error=True)
            return
        if not self.state.try_busy("scenes"):
            return
        self.btn_t2i_gen.disabled = True
        self.job_progress.start("Generating scene plate…", self.page)
        self._set_status("Generating location plate…")
        try:
            self.page.update()
        except Exception:
            pass

        def on_progress(msg: str) -> None:
            self.job_progress.set_message(classify_progress(msg), self.page)

        try:
            from media_studio.job_context import to_thread_with_job
            from media_studio.vision_service import run_vision

            aspect_arg, resolution, ar_canon = resolve_scene_t2i_args(
                model_label=self.t2i_model_dd.value,
                aspect_ui=self.t2i_aspect_dd.value,
                quality=self.t2i_quality_dd.value,
            )
            prompt = scene_t2i_prompt(desc, aspect=ar_canon)
            self._pending_aspect = ar_canon
            result = await to_thread_with_job(
                self.state,
                run_vision,
                mode="text_to_image",
                prompt=prompt,
                model_label=self.t2i_model_dd.value,
                aspect_ratio=aspect_arg,
                resolution=resolution,
                num_images=1,
                output_dir=self.state.output_dir,
                on_progress=on_progress,
            )
            path = None
            err = None
            if result.ok:
                path = result.path or (result.paths[0] if result.paths else None)
            else:
                err = result.status or "T2I failed"

            if path and Path(path).is_file():
                self._t2i_pending_path = str(Path(path).resolve())
                # Prefer detected aspect from result if available
                det = detect_still_aspect(self._t2i_pending_path) or ar_canon
                self._pending_aspect = det
                self.t2i_preview.src = self._t2i_pending_path
                self.t2i_preview.visible = True
                self.t2i_aspect_badge.content = ft.Text(
                    det, size=11, color=TEXT, weight=ft.FontWeight.W_700
                )
                self.t2i_aspect_badge.visible = True
                self.btn_t2i_use.visible = True
                self.job_progress.finish_ok(
                    f"Plate ready ({det}) — Use as scene still", self.page
                )
                self._set_status(
                    f"Plate ready ({det}): {Path(path).name} — Use as scene still, then Save."
                )
            else:
                msg = err or "Generate failed"
                self.job_progress.finish_error(msg, self.page)
                self._set_status(msg, error=True)
        except Exception as exc:
            tb = traceback.format_exc()
            msg = f"Generate error: {exc}"
            self.job_progress.finish_error(msg, self.page)
            self._set_status(msg, error=True)
            try:
                print(tb)
            except Exception:
                pass
        finally:
            self.btn_t2i_gen.disabled = False
            try:
                self.state.clear_busy("scenes")
            except Exception:
                pass
            try:
                self.page.update()
            except Exception:
                pass

    async def _use_t2i_result(self, e: ft.ControlEvent) -> None:
        if not self._t2i_pending_path or not Path(self._t2i_pending_path).is_file():
            self._set_status("No generated plate to use.", error=True)
            return
        self._set_still(self._t2i_pending_path, aspect=self._pending_aspect)
        # Do NOT dump the full T2I/Enhance prompt into Name — user names the plate
        ar = self._pending_aspect or detect_still_aspect(self._t2i_pending_path)
        self._set_status(
            f"Still set from generate ({ar or '?'}) — enter a short Name and Save."
        )
        try:
            self.page.update()
        except Exception:
            pass

    # ----- lightbox -----

    def _open_preview(self, path: str, *, title: str = "Scene preview") -> None:
        p = Path(path)
        if not p.is_file():
            self._set_status(f"Missing still: {path}", error=True)
            return
        win_w = float(getattr(self.page.window, "width", None) or 1400)
        win_h = float(getattr(self.page.window, "height", None) or 900)
        body_w = int(min(max(win_w - 80, 640), win_w * 0.9))
        body_h = int(min(max(win_h - 100, 480), win_h * 0.88))

        if self._lightbox_img is None:
            self._lightbox_img = ft.Image(
                src="",
                fit=ft.BoxFit.CONTAIN,
                expand=True,
                gapless_playback=True,
            )
        if self._lightbox_title is None:
            self._lightbox_title = ft.Text(
                title,
                size=FONT_MD,
                color=TEXT,
                weight=ft.FontWeight.W_700,
                expand=True,
                max_lines=1,
                overflow=ft.TextOverflow.ELLIPSIS,
            )
        self._lightbox_img.src = str(p.resolve())
        self._lightbox_title.value = title

        async def _close(_e: ft.ControlEvent) -> None:
            close_dialog(self.page, self._lightbox_dialog)

        body = ft.Container(
            width=body_w,
            height=body_h,
            content=ft.Column(
                [
                    ft.Row(
                        [
                            self._lightbox_title,
                            ft.IconButton(
                                icon=ft.Icons.CLOSE,
                                icon_color=TEXT,
                                on_click=_close,
                                tooltip="Close",
                            ),
                        ],
                        spacing=8,
                    ),
                    ft.Container(
                        content=self._lightbox_img,
                        expand=True,
                        bgcolor="#0a0c10",
                        border_radius=8,
                        border=ft.Border.all(1, BORDER),
                        alignment=ft.Alignment.CENTER,
                        clip_behavior=ft.ClipBehavior.HARD_EDGE,
                    ),
                ],
                spacing=8,
                expand=True,
            ),
        )
        self._lightbox_dialog = ft.AlertDialog(
            modal=True,
            content=body,
            actions=[],
        )
        show_dialog(self.page, self._lightbox_dialog)

    async def _on_tap_form_preview(self, e: ft.ControlEvent) -> None:
        if self._still_path and Path(self._still_path).is_file():
            ar = self._pending_aspect or detect_still_aspect(self._still_path)
            name = (self.name_field.value or "").strip() or "Scene still"
            self._open_preview(
                self._still_path,
                title=f"{name}" + (f" · {ar}" if ar else ""),
            )

    async def _on_tap_t2i_preview(self, e: ft.ControlEvent) -> None:
        if self._t2i_pending_path and Path(self._t2i_pending_path).is_file():
            ar = self._pending_aspect or detect_still_aspect(self._t2i_pending_path)
            self._open_preview(
                self._t2i_pending_path,
                title="Generated plate" + (f" · {ar}" if ar else ""),
            )

    async def _on_tap_var_preview(self, e: ft.ControlEvent) -> None:
        if self._var_pending_path and Path(self._var_pending_path).is_file():
            self._open_preview(self._var_pending_path, title="Variation preview")

    def _make_preview_path(self, path: str, title: str):
        async def _tap(_e: ft.ControlEvent) -> None:
            if path and Path(path).is_file():
                self._open_preview(path, title=title)

        return _tap

    # ----- list cards -----

    def _card(
        self,
        s: SavedScene,
        *,
        children: list[SavedScene] | None = None,
        nested: bool = False,
    ) -> ft.Control:
        still_ok = s.has_still()
        badge_txt = s.aspect_badge()
        if still_ok:
            img = ft.Image(
                src=s.still_path,
                width=_THUMB,
                height=_THUMB,
                fit=ft.BoxFit.COVER,
                border_radius=6,
            )
            badge = ft.Container(
                content=ft.Text(
                    badge_txt or "?",
                    size=10,
                    color=TEXT,
                    weight=ft.FontWeight.W_700,
                ),
                bgcolor="#c62828" if badge_txt else TEXT_MUTED,
                border_radius=3,
                padding=ft.Padding.symmetric(horizontal=4, vertical=1),
                left=3,
                top=3,
                visible=bool(badge_txt),
            )
            thumb: ft.Control = ft.GestureDetector(
                content=ft.Stack(
                    [img, badge],
                    width=_THUMB,
                    height=_THUMB,
                ),
                on_tap=self._make_preview_path(
                    s.still_path,
                    f"{s.name}" + (f" · {badge_txt}" if badge_txt else ""),
                ),
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
        lock_icon = " 🔒" if s.locked else ""
        notes = s.display_notes()
        # Primary = user Name; secondary = short notes only (never bury name under prompt)
        name_txt = ft.Text(
            f"{s.name}{lock_icon}",
            size=FONT_SM,
            color=TEXT,
            weight=ft.FontWeight.W_700,
            max_lines=1,
            overflow=ft.TextOverflow.ELLIPSIS,
        )
        notes_txt = ft.Text(
            notes if notes else ("—" if nested else "No notes"),
            size=FONT_SM,
            color=TEXT_MUTED,
            max_lines=2,
            overflow=ft.TextOverflow.ELLIPSIS,
        )
        missing = ft.Text(
            "Still file missing",
            size=FONT_SM,
            color="#e57373",
            visible=not still_ok,
        )

        btn_edit = ft.OutlinedButton(
            content="Edit",
            on_click=self._make_edit(s),
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
            height=36,
        )
        btn_lock = ft.TextButton(
            content="Unlock" if s.locked else "Lock",
            icon=ft.Icons.LOCK_OPEN if s.locked else ft.Icons.LOCK_OUTLINE,
            on_click=self._make_toggle_lock(s),
            style=ft.ButtonStyle(color=ACCENT if s.locked else TEXT_MUTED),
            height=36,
        )
        btn_folder = ft.TextButton(
            content="Show in folder",
            icon=ft.Icons.FOLDER_OPEN,
            on_click=self._make_show_folder(s),
            style=ft.ButtonStyle(color=TEXT_MUTED),
            height=36,
            disabled=not still_ok,
        )
        btn_delete = ft.TextButton(
            content="Delete",
            icon=ft.Icons.DELETE_OUTLINE,
            on_click=self._make_delete(s),
            style=ft.ButtonStyle(color="#ef9a9a"),
            height=36,
        )
        btn_var = ft.OutlinedButton(
            content="Create variation",
            icon=ft.Icons.AUTO_FIX_HIGH,
            on_click=self._make_open_variation(s),
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
            height=36,
            disabled=not still_ok or nested,
            visible=not nested,
            tooltip="Season / weather / era transform from this plate (I2I)",
        )

        actions = [btn_var, btn_edit, btn_lock, btn_folder, btn_delete]
        if nested:
            actions = [btn_edit, btn_lock, btn_folder, btn_delete]

        kids = list(children) if children is not None else []
        variations_col: ft.Control | None = None
        if not nested:
            expanded = s.id in self._variations_expanded
            n_kids = len(kids)
            count_label = f"{n_kids}" if n_kids else "none"
            toggle = ft.TextButton(
                content=(
                    f"▾ Variations ({count_label})"
                    if expanded
                    else f"▸ Variations ({count_label})"
                ),
                on_click=self._make_toggle_variations(s.id),
                style=ft.ButtonStyle(color=ACCENT),
                tooltip="Season / weather / style variants under this scene",
            )
            if n_kids:
                expanded_body: ft.Control = ft.Column(
                    [self._card(k, nested=True) for k in kids],
                    spacing=6,
                    tight=True,
                    visible=expanded,
                )
            else:
                expanded_body = ft.Text(
                    "No variations yet — use Create variation",
                    size=FONT_SM,
                    color=TEXT_MUTED,
                    visible=expanded,
                )
            variations_col = ft.Column(
                [toggle, expanded_body],
                spacing=4,
                tight=True,
            )

        body = ft.Column(
            [
                name_txt,
                notes_txt,
                missing,
                ft.Row(actions, spacing=4, wrap=True),
            ],
            spacing=4,
            expand=True,
            tight=True,
        )
        if variations_col is not None:
            body.controls.append(variations_col)

        return ft.Container(
            content=ft.Row(
                [thumb, body],
                spacing=12,
                vertical_alignment=ft.CrossAxisAlignment.START,
            ),
            bgcolor=PANEL if nested else PANEL_ELEVATED,
            border=ft.Border.all(1, ACCENT if s.locked else BORDER),
            border_radius=8,
            padding=10 if not nested else 8,
            margin=ft.Margin.only(left=16) if nested else None,
        )

    def _make_toggle_variations(self, parent_id: str):
        async def _click(_e: ft.ControlEvent) -> None:
            if parent_id in self._variations_expanded:
                self._variations_expanded.discard(parent_id)
            else:
                self._variations_expanded.add(parent_id)
            self.refresh()

        return _click

    def _make_open_variation(self, s: SavedScene):
        async def _click(_e: ft.ControlEvent) -> None:
            self._open_variation_panel(s)

        return _click

    def _make_edit(self, s: SavedScene):
        async def _click(_e: ft.ControlEvent) -> None:
            self._edit_id = s.id
            self.name_field.value = s.name
            self.notes_field.value = s.notes or ""
            if s.has_still():
                self._set_still(s.still_path, aspect=s.aspect)
            else:
                self._set_still(None)
            self.btn_save.content = "Save changes"
            self.btn_cancel_edit.visible = True
            ar = s.aspect_badge()
            self._set_status(f"Editing: {s.name}" + (f" · {ar}" if ar else ""))
            try:
                self.page.update()
            except Exception:
                pass

        return _click

    def _make_toggle_lock(self, s: SavedScene):
        async def _click(_e: ft.ControlEvent) -> None:
            try:
                updated = set_scene_locked(s.id, not s.locked)
                if updated:
                    self._set_status(
                        f"{'Locked' if updated.locked else 'Unlocked'}: {updated.name}"
                    )
                    self.refresh()
            except Exception as exc:
                self._set_status(str(exc), error=True)

        return _click

    def _make_show_folder(self, s: SavedScene):
        async def _click(_e: ft.ControlEvent) -> None:
            if not s.has_still():
                self._set_status("Still missing.", error=True)
                return
            msg = show_in_folder(s.still_path)
            self._set_status(msg)

        return _click

    def _make_delete(self, s: SavedScene):
        async def _click(_e: ft.ControlEvent) -> None:
            if s.locked:
                self._set_status(
                    f"“{s.name}” is locked — unlock before delete.",
                    error=True,
                )
                return

            kids = list_scene_variations(s.id) if s.is_base() else []
            n_kids = len(kids)

            async def _do_delete(
                _e: ft.ControlEvent,
                *,
                delete_children: bool = False,
            ) -> None:
                close_dialog(self.page, dlg)
                try:
                    delete_scene(
                        s.id,
                        delete_children=delete_children,
                        force_children_check=not delete_children,
                    )
                    kid_ids = {k.id for k in kids}
                    if self._edit_id == s.id or (
                        delete_children and self._edit_id in kid_ids
                    ):
                        self._reset_form()
                    msg = f"Deleted: {s.name}"
                    if delete_children and n_kids:
                        msg += f" (+ {n_kids} variation(s))"
                    self._set_status(msg)
                    self.refresh()
                except SceneHasChildrenError as exc:
                    self._set_status(str(exc), error=True)
                except Exception as exc:
                    self._set_status(str(exc), error=True)

            async def _delete_all(_e: ft.ControlEvent) -> None:
                await _do_delete(_e, delete_children=True)

            async def _delete_one(_e: ft.ControlEvent) -> None:
                await _do_delete(_e, delete_children=False)

            if n_kids:
                body = (
                    f"“{s.name}” has {n_kids} variation(s). "
                    "Delete all (parent + variations), or cancel and remove "
                    "variations individually first."
                )
                actions = [
                    ft.TextButton(
                        content="Cancel",
                        on_click=lambda _e: close_dialog(self.page, dlg),
                    ),
                    ft.TextButton(
                        content="Delete all (parent + variations)",
                        on_click=_delete_all,
                        style=ft.ButtonStyle(color="#ef9a9a"),
                    ),
                ]
            else:
                body = f"Delete “{s.name}” and its local still? This cannot be undone."
                actions = [
                    ft.TextButton(
                        content="Cancel",
                        on_click=lambda _e: close_dialog(self.page, dlg),
                    ),
                    ft.FilledButton(
                        content="Delete",
                        on_click=_delete_one,
                        style=ft.ButtonStyle(bgcolor="#c62828", color=TEXT),
                    ),
                ]

            dlg = ft.AlertDialog(
                title=ft.Text("Delete scene?"),
                content=ft.Text(body),
                actions=actions,
            )
            show_dialog(self.page, dlg)

        return _click

    # ----- variations (I2I) -----

    def _open_variation_panel(self, s: SavedScene) -> None:
        if not s.has_still():
            self._set_status("Base scene still missing.", error=True)
            return
        self._var_parent_id = s.id
        self._var_parent_name = s.name
        self._var_parent_path = s.still_path
        self._var_pending_path = None
        self.var_parent_label.value = f"Base: {s.name}" + (
            f" · {s.aspect_badge()}" if s.aspect_badge() else ""
        )
        self.var_prompt.value = ""
        self.var_name.value = f"{s.name} – "
        self.var_preview.src = ""
        self.var_preview.visible = False
        self.btn_var_save.visible = False
        self.var_box.visible = True
        self._variations_expanded.add(s.id)
        self._refresh_var_cost_sync()
        self._set_status(f"Create variation under “{s.name}”.")
        try:
            self.page.update()
        except Exception:
            pass

    async def _close_variation_panel(self, e: ft.ControlEvent | None = None) -> None:
        self.var_box.visible = False
        self._var_parent_id = None
        self._var_parent_path = None
        self._var_pending_path = None
        self.var_preview.visible = False
        self.btn_var_save.visible = False
        try:
            self.page.update()
        except Exception:
            pass

    def _refresh_var_cost_sync(self) -> None:
        try:
            from media_studio.pricing import format_job_cost
            from media_studio.fal.models import resolve_image_edit_model

            lab = self.var_model_dd.value
            es = resolve_image_edit_model(lab)
            per = float(getattr(es, "cost_estimate_usd", 0) or 0.04) if es else 0.04
            model = es.label if es else (lab or "I2I")
            self.var_cost_text.value = format_job_cost(per, unit="1 edit", model=model)
        except Exception:
            try:
                self.var_cost_text.value = estimate_scene_t2i_cost(
                    t2i_label=None, quality="Standard"
                )
            except Exception:
                self.var_cost_text.value = "Est. cost: —"

    async def _refresh_var_cost(self, e: ft.ControlEvent | None = None) -> None:
        self._refresh_var_cost_sync()
        try:
            self.page.update()
        except Exception:
            pass

    async def _on_var_enhance(self, e: ft.ControlEvent) -> None:
        parent = self._var_parent_name or "location plate"

        def _extra() -> dict[str, Any]:
            return {
                "workspace": "scenes",
                "mode": "image_to_image",
                "guidance": (
                    f"Rewrite as an image-edit prompt for transforming the location "
                    f"“{parent}”. Keep the same place, camera, and layout; change only "
                    "season / weather / time of day / era as requested. No new hero talent. "
                    "Photoreal, no text/logo."
                ),
            }

        await run_prompt_enhance(
            page=self.page,
            state=self.state,
            prompt_field=self.var_prompt,
            get_model=lambda: self.var_model_dd.value,
            get_extra_context=_extra,
            status_ctrl=self.status,
            job_progress=self.job_progress,
            enhance_btn=self.btn_var_enhance,
            busy_controls=[self.btn_var_gen, self.btn_var_save],
            context_label="scene variation",
            allow_empty_with_context=True,
            busy_scope="scenes",
        )

    async def _run_variation(self, e: ft.ControlEvent) -> None:
        from media_studio.secrets_store import has_fal_key

        if not has_fal_key():
            self._set_status("FAL API key required — open Settings.", error=True)
            return
        if not self._var_parent_path or not Path(self._var_parent_path).is_file():
            self._set_status("Base scene still missing.", error=True)
            return
        transform = (self.var_prompt.value or "").strip()
        if not transform:
            self._set_status("Describe the transform (e.g. winter snow).", error=True)
            return
        if not self.state.try_busy("scenes"):
            return
        self.btn_var_gen.disabled = True
        self.job_progress.start("Generating scene variation…", self.page)
        self._set_status("Running variation (I2I)…")
        try:
            self.page.update()
        except Exception:
            pass

        def on_progress(msg: str) -> None:
            self.job_progress.set_message(classify_progress(msg), self.page)

        try:
            from media_studio.character_store import (
                default_practical_resolution,
                edit_params_json_for_resolution,
                edit_resolution_options,
            )
            from media_studio.job_context import to_thread_with_job
            from media_studio.services import generate

            prompt = scene_variation_prompt(
                transform,
                base_name=self._var_parent_name,
            )
            model_choice = self.var_model_dd.value or preferred_scene_edit_model()
            res_opts = edit_resolution_options(model_choice)
            edit_res = default_practical_resolution(res_opts) if res_opts else None
            params_json = edit_params_json_for_resolution(edit_res)
            result = await to_thread_with_job(
                self.state,
                generate,
                prompt,
                model_choice=model_choice,
                image_file=self._var_parent_path,
                extra_image_files=None,
                output_dir=self.state.output_dir,
                on_progress=on_progress,
                scenario="scene-variation",
                parameters_json=params_json,
            )
            path = None
            err = None
            if result.ok:
                path = result.primary_image or (
                    result.image_paths[0] if result.image_paths else None
                )
            else:
                err = result.status or "Variation failed"

            if path and Path(path).is_file():
                self._var_pending_path = str(Path(path).resolve())
                self.var_preview.src = self._var_pending_path
                self.var_preview.visible = True
                self.btn_var_save.visible = True
                # Soft name if empty suffix only
                if not (self.var_name.value or "").strip() or (
                    self.var_name.value or ""
                ).strip().endswith("–"):
                    short = transform[:32].rstrip(" .,;")
                    self.var_name.value = f"{self._var_parent_name} – {short}"
                self.job_progress.finish_ok(
                    "Variation ready — Confirm & save", self.page
                )
                self._set_status(
                    "Variation ready — click preview to enlarge, then Confirm & save."
                )
            else:
                msg = err or "Variation generate failed"
                self.job_progress.finish_error(msg, self.page)
                self._set_status(msg, error=True)
        except Exception as exc:
            msg = f"Variation error: {exc}"
            self.job_progress.finish_error(msg, self.page)
            self._set_status(msg, error=True)
            try:
                print(traceback.format_exc())
            except Exception:
                pass
        finally:
            self.btn_var_gen.disabled = False
            try:
                self.state.clear_busy("scenes")
            except Exception:
                pass
            try:
                self.page.update()
            except Exception:
                pass

    async def _save_variation(self, e: ft.ControlEvent) -> None:
        if not self._var_parent_id:
            self._set_status("No base scene selected.", error=True)
            return
        if not self._var_pending_path or not Path(self._var_pending_path).is_file():
            self._set_status("Generate a variation first.", error=True)
            return
        name = (self.var_name.value or "").strip()
        if not name:
            self._set_status("Variation name is required.", error=True)
            return
        try:
            from media_studio.scene_store import find_scene as _find

            base = _find(self._var_parent_id)
            ar = (base.aspect if base else "") or detect_still_aspect(
                self._var_pending_path
            )
            notes = (self.var_prompt.value or "").strip()
            if len(notes) > 200:
                notes = notes[:197].rstrip() + "…"
            entry = add_scene(
                name=name,
                still_path=self._var_pending_path,
                notes=notes,
                aspect=ar,
                parent_id=self._var_parent_id,
            )
            self._variations_expanded.add(self._var_parent_id)
            self._set_status(f"Saved variation: {entry.name}")
            await self._close_variation_panel()
            self.refresh()
        except Exception as exc:
            self._set_status(str(exc), error=True)
