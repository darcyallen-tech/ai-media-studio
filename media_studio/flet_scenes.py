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
from media_studio.helper_none import HELPER_NONE
from media_studio.scene_store import (
    PLATE_ACTIVITY,
    PLATE_SETTINGS,
    PLATE_TIMES,
    PLATE_TYPES,
    PLATE_WEATHER,
    SCENE_ANGLE_LABELS,
    SHEET_CAMERA_LANG,
    SHEET_CONDITIONS,
    SHEET_DENSITY_OPTS,
    SHEET_HELPER_NONE,
    SHEET_LOCATION_TYPES,
    SHEET_TIME_LIGHT,
    VARIATION_CHIPS,
    SavedScene,
    SceneHasChildrenError,
    add_scene,
    assemble_plate_description,
    assemble_scene_sheet_prompt,
    default_scene_quality,
    delete_scene,
    detect_still_aspect,
    estimate_scene_sheet_cost,
    estimate_scene_t2i_cost,
    find_scene,
    list_base_scenes,
    list_scene_variations,
    load_scenes,
    normalize_scene_aspect,
    preferred_scene_edit_model,
    preferred_scene_sheet_model,
    resolve_scene_t2i_args,
    scene_angle_prompt,
    scene_aspect_ui_options,
    scene_edit_model_labels,
    scene_quality_options,
    scene_sheet_enhance_guidance,
    scene_sheet_max_images,
    scene_sheet_model_labels,
    scene_t2i_prompt,
    scene_variation_prompt,
    set_scene_angle,
    set_scene_locked,
    set_scene_sheet,
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
        # Scene reference sheet (single-shot)
        self._sheet_busy = False
        self._sheet_scene_id: str | None = None
        self._sheet_scene_name: str = ""
        self._sheet_pending_path: str | None = None
        self._sheet_pending_paths: list[str] = []  # multi-gen batch
        self._sheet_source_path: str | None = None  # lock still for I2I
        # "form" = add/edit + T2I; "variation" = I2I panel only; "sheet" = make scene sheet
        self._ui_mode: str = "form"
        # Library selection highlight (parent scene during variation)
        self._selected_scene_id: str | None = None
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
        self.btn_scene_placer = ft.OutlinedButton(
            content="Scene Placer",
            icon=ft.Icons.PERSON_PIN_CIRCLE_OUTLINED,
            on_click=self._open_scene_placer_blank,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
            height=42,
            tooltip="Place a character into a scene (opens Characters · Scene Placer)",
        )
        self.btn_new_scene = ft.FilledButton(
            content="New scene",
            icon=ft.Icons.ADD,
            on_click=self._open_new_scene,
            style=ft.ButtonStyle(bgcolor=ACCENT_BRIGHT, color=TEXT),
            height=40,
        )
        self.btn_save = ft.FilledButton(
            content="Save scene",
            on_click=self._save,
            style=ft.ButtonStyle(bgcolor=ACCENT, color=TEXT),
            height=40,
        )
        self.btn_cancel_edit = ft.TextButton(
            content="Cancel",
            on_click=self._cancel_edit,
            style=ft.ButtonStyle(color=TEXT_MUTED),
            visible=False,
        )
        self.form_heading = ft.Text(
            "Add / edit scene",
            size=FONT_SM,
            color=TEXT_MUTED,
            weight=ft.FontWeight.W_600,
        )

        # --- Generate (T2I) + plate builder helpers ---
        t2i_labs = t2i_scene_model_labels()
        self.t2i_setting_dd = styled_dropdown(
            label_text="Setting",
            options=list(PLATE_SETTINGS),
            value=HELPER_NONE,
            on_select=self._on_plate_helper,
            expand=True,
        )
        self.t2i_type_dd = styled_dropdown(
            label_text="Type",
            options=list(PLATE_TYPES),
            value=HELPER_NONE,
            on_select=self._on_plate_helper,
            expand=True,
        )
        self.t2i_time_dd = styled_dropdown(
            label_text="Time of day",
            options=list(PLATE_TIMES),
            value=HELPER_NONE,
            on_select=self._on_plate_helper,
            expand=True,
        )
        self.t2i_weather_dd = styled_dropdown(
            label_text="Weather",
            options=list(PLATE_WEATHER),
            value=HELPER_NONE,
            on_select=self._on_plate_helper,
            expand=True,
        )
        self.t2i_activity_dd = styled_dropdown(
            label_text="Activity",
            options=list(PLATE_ACTIVITY),
            value=HELPER_NONE,
            on_select=self._on_plate_helper,
            expand=True,
        )
        self.t2i_helper_notes = ft.TextField(
            label="Optional notes (appended on rebuild)",
            hint_text="e.g. brick facade, autumn trees, glass curtain wall…",
            dense=True,
            filled=True,
            fill_color=PANEL_ELEVATED,
            border_color=BORDER,
            color=TEXT,
            text_size=FONT_SM,
            on_change=self._on_plate_helper,
        )
        self.t2i_desc = ft.TextField(
            label="Location description",
            hint_text="Filled by helpers — edit freely or Enhance",
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
                        "Helpers rebuild the description (like Music/Studio builders). "
                        "Establishing bias: empty or light activity, no hero talent "
                        "unless you ask for people. Enhance rewrites the full prompt.",
                        size=FONT_SM,
                        color=TEXT_MUTED,
                    ),
                    ft.Row(
                        [self.t2i_setting_dd, self.t2i_type_dd],
                        spacing=8,
                    ),
                    ft.Row(
                        [self.t2i_time_dd, self.t2i_weather_dd],
                        spacing=8,
                    ),
                    ft.Row([self.t2i_activity_dd], spacing=0),
                    self.t2i_helper_notes,
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
        # --- Variation I2I fields (always real controls; mounted by replacing work_host) ---
        self.var_title = ft.Text(
            "Create variation (I2I)",
            size=FONT_MD,
            color=TEXT,
            weight=ft.FontWeight.W_700,
        )
        self.var_parent_label = ft.Text(
            "Parent: —",
            size=FONT_SM,
            color=TEXT,
            weight=ft.FontWeight.W_600,
            max_lines=2,
        )
        self.var_parent_sub = ft.Text(
            "Reference still for I2I",
            size=11,
            color=TEXT_MUTED,
            max_lines=2,
        )
        self.var_error = ft.Text(
            "",
            size=FONT_SM,
            color="#ef9a9a",
            max_lines=4,
            visible=False,
        )
        # Fixed-size parent thumb (never expand inside ListView)
        _VAR_THUMB_W, _VAR_THUMB_H = 120, 90
        self.var_parent_thumb = ft.Image(
            src="",
            width=_VAR_THUMB_W,
            height=_VAR_THUMB_H,
            fit=ft.BoxFit.COVER,
            border_radius=6,
            visible=True,
        )
        self.var_parent_thumb_empty = ft.Container(
            width=_VAR_THUMB_W,
            height=_VAR_THUMB_H,
            bgcolor=PANEL,
            border=ft.Border.all(1, BORDER),
            border_radius=6,
            alignment=ft.Alignment.CENTER,
            content=ft.Column(
                [
                    ft.Icon(ft.Icons.BROKEN_IMAGE_OUTLINED, size=28, color=TEXT_MUTED),
                    ft.Text("No still", size=11, color=TEXT_MUTED),
                ],
                tight=True,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=2,
            ),
            visible=True,
        )
        self.var_parent_thumb_host = ft.Container(
            width=_VAR_THUMB_W,
            height=_VAR_THUMB_H,
            content=self.var_parent_thumb_empty,
        )
        self.var_prompt = ft.TextField(
            label="Transform prompt (season, weather, time of day, style…)",
            hint_text='e.g. "winter snow, overcast afternoon" or "golden hour sunset"',
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
        self.var_name = ft.TextField(
            label="Variation name",
            hint_text='e.g. "Winter" or "Modern Gym – Winter"',
            dense=True,
            filled=True,
            fill_color=PANEL_ELEVATED,
            border_color=BORDER,
            color=TEXT,
            text_size=FONT_SM,
        )
        self.var_model_dd = styled_dropdown(
            label_text="Model",
            options=edit_labs or [pref_edit],
            value=edit_default,
            on_select=self._on_var_model,
            expand=True,
        )
        try:
            from media_studio.character_store import (
                default_practical_resolution,
                edit_resolution_options,
            )

            _vres = edit_resolution_options(edit_default) or ["1K", "2K"]
            _vdef = default_practical_resolution(_vres) if _vres else "1K"
        except Exception:
            _vres, _vdef = ["1K", "2K"], "1K"
        self.var_quality_dd = styled_dropdown(
            label_text="Quality",
            options=list(_vres),
            value=_vdef,
            on_select=self._refresh_var_cost,
            expand=True,
        )
        self.var_cost_text, self.var_cost_box = make_estimated_cost_box(
            initial="Est. cost: —"
        )
        self.btn_var_enhance = make_enhance_button(on_click=self._on_var_enhance)
        self.btn_var_gen = ft.FilledButton(
            content="Generate",
            icon=ft.Icons.AUTO_FIX_HIGH,
            on_click=self._run_variation,
            style=ft.ButtonStyle(bgcolor=ACCENT, color=TEXT),
            height=42,
        )
        self.btn_var_save = ft.FilledButton(
            content="Confirm & save",
            on_click=self._save_variation,
            style=ft.ButtonStyle(bgcolor=ACCENT_BRIGHT, color=TEXT),
            height=42,
            visible=False,
        )
        self.btn_var_close = ft.OutlinedButton(
            content="Cancel",
            on_click=self._close_variation_panel,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
            height=42,
        )
        self.var_preview = ft.Image(
            src="",
            width=160,
            height=120,
            fit=ft.BoxFit.COVER,
            border_radius=6,
            visible=False,
        )
        self.var_preview_empty = ft.Container(
            width=160,
            height=120,
            bgcolor=PANEL,
            border=ft.Border.all(1, BORDER),
            border_radius=6,
            alignment=ft.Alignment.CENTER,
            content=ft.Text("Preview", size=FONT_SM, color=TEXT_MUTED),
            visible=True,
        )
        self.var_preview_host = ft.Container(
            width=160,
            height=120,
            content=self.var_preview_empty,
        )
        self.var_preview_tap = ft.GestureDetector(
            content=self.var_preview_host,
            on_tap=self._on_tap_var_preview,
        )
        # Quick chips append transform language (optional QoL)
        self.var_chip_row = ft.Row(
            [
                ft.Text("Quick:", size=11, color=TEXT_MUTED),
                *[
                    ft.TextButton(
                        content=chip,
                        on_click=self._make_var_chip(chip),
                        style=ft.ButtonStyle(color=ACCENT),
                    )
                    for chip in VARIATION_CHIPS
                ],
            ],
            spacing=2,
            wrap=True,
        )
        # Built fresh each open via _assemble_variation_panel() — not empty toggles
        self._var_panel_shell: ft.Container | None = None

        # --- Multi-angle pack (Hero / B / C) + one-click Generate angle ---
        self._angle_gen_target: str | None = None  # left | right | reverse
        self._angle_gen_slot: str | None = None  # angle_b | angle_c
        self._angle_pending_path: str | None = None
        self._angle_pack_scene_id: str | None = None
        _ANG = 64
        self.angle_hero_img = ft.Image(
            src="", width=_ANG, height=_ANG, fit=ft.BoxFit.COVER, border_radius=6
        )
        self.angle_b_img = ft.Image(
            src="", width=_ANG, height=_ANG, fit=ft.BoxFit.COVER, border_radius=6
        )
        self.angle_c_img = ft.Image(
            src="", width=_ANG, height=_ANG, fit=ft.BoxFit.COVER, border_radius=6
        )
        self.angle_hero_empty = ft.Container(
            width=_ANG,
            height=_ANG,
            bgcolor=PANEL,
            border=ft.Border.all(1, BORDER),
            border_radius=6,
            alignment=ft.Alignment.CENTER,
            content=ft.Text("Hero", size=10, color=TEXT_MUTED),
        )
        self.angle_b_empty = ft.Container(
            width=_ANG,
            height=_ANG,
            bgcolor=PANEL,
            border=ft.Border.all(1, BORDER),
            border_radius=6,
            alignment=ft.Alignment.CENTER,
            content=ft.Text("B", size=10, color=TEXT_MUTED),
        )
        self.angle_c_empty = ft.Container(
            width=_ANG,
            height=_ANG,
            bgcolor=PANEL,
            border=ft.Border.all(1, BORDER),
            border_radius=6,
            alignment=ft.Alignment.CENTER,
            content=ft.Text("C", size=10, color=TEXT_MUTED),
        )
        self.angle_hero_host = ft.Container(width=_ANG, height=_ANG, content=self.angle_hero_empty)
        self.angle_b_host = ft.Container(width=_ANG, height=_ANG, content=self.angle_b_empty)
        self.angle_c_host = ft.Container(width=_ANG, height=_ANG, content=self.angle_c_empty)
        self.btn_gen_left = ft.OutlinedButton(
            content="Generate Left",
            on_click=self._make_gen_angle("left"),
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
            height=32,
        )
        self.btn_gen_right = ft.OutlinedButton(
            content="Generate Right",
            on_click=self._make_gen_angle("right"),
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
            height=32,
        )
        self.btn_gen_reverse = ft.OutlinedButton(
            content="Generate Reverse",
            on_click=self._make_gen_angle("reverse"),
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
            height=32,
        )
        # Angle I2I model + quality (cost tracks these like Create variation)
        _ang_labs = scene_edit_model_labels()
        _ang_pref = preferred_scene_edit_model()
        _ang_def = _ang_labs[0] if _ang_labs else _ang_pref
        for lab in _ang_labs or []:
            if _ang_pref.lower() in lab.lower() or lab.lower() in _ang_pref.lower():
                _ang_def = lab
                break
        self.angle_model_dd = styled_dropdown(
            label_text="Angle model",
            options=_ang_labs or [_ang_pref],
            value=_ang_def,
            on_select=self._on_angle_model_or_quality,
            expand=True,
        )
        try:
            from media_studio.character_store import (
                default_practical_resolution,
                edit_resolution_options,
            )

            _ares = edit_resolution_options(_ang_def) or ["1K", "2K"]
            _adef = default_practical_resolution(_ares) if _ares else "1K"
        except Exception:
            _ares, _adef = ["1K", "2K"], "1K"
        self.angle_quality_dd = styled_dropdown(
            label_text="Quality",
            options=list(_ares),
            value=_adef,
            on_select=self._on_angle_model_or_quality,
            expand=True,
        )
        self.angle_cost_text, self.angle_cost_box = make_estimated_cost_box(
            initial="Est. cost: —"
        )
        self.angle_note = ft.TextField(
            label="Optional note (appended to angle prompt)",
            hint_text="e.g. show the windows on the left wall",
            dense=True,
            filled=True,
            fill_color=PANEL_ELEVATED,
            border_color=BORDER,
            color=TEXT,
            text_size=FONT_SM,
        )
        self.angle_pending_img = ft.Image(
            src="",
            width=120,
            height=90,
            fit=ft.BoxFit.COVER,
            border_radius=6,
            visible=False,
        )
        self.angle_pending_empty = ft.Container(
            width=120,
            height=90,
            bgcolor=PANEL_ELEVATED,
            border=ft.Border.all(1, BORDER),
            border_radius=6,
            alignment=ft.Alignment.CENTER,
            content=ft.Text("Preview", size=11, color=TEXT_MUTED),
            visible=True,
        )
        self.angle_pending_host = ft.Container(
            width=120,
            height=90,
            content=self.angle_pending_empty,
            tooltip="Click to enlarge",
        )
        self.angle_pack_hint = ft.Text(
            "Hero stays locked. Left → B, Right → C, Reverse → first empty. "
            "Lateral moves force a real camera shift (not a crop). Click preview to enlarge.",
            size=11,
            color=TEXT_MUTED,
            max_lines=3,
        )
        self.angle_slot_hero_lab = ft.Text("Hero", size=10, color=TEXT_MUTED)
        self.angle_slot_b_lab = ft.Text("Left (B)", size=10, color=TEXT_MUTED)
        self.angle_slot_c_lab = ft.Text("Right (C)", size=10, color=TEXT_MUTED)
        self.btn_clear_b = ft.TextButton(
            content="Clear B",
            on_click=self._make_clear_angle("angle_b"),
            style=ft.ButtonStyle(color=TEXT_MUTED),
            height=28,
            visible=False,
        )
        self.btn_clear_c = ft.TextButton(
            content="Clear C",
            on_click=self._make_clear_angle("angle_c"),
            style=ft.ButtonStyle(color=TEXT_MUTED),
            height=28,
            visible=False,
        )
        self.angle_pending_label = ft.Text(
            "",
            size=FONT_SM,
            color=ACCENT,
            weight=ft.FontWeight.W_600,
            visible=False,
            max_lines=2,
        )
        self.angle_pending_tap = ft.GestureDetector(
            content=self.angle_pending_host,
            on_tap=self._on_tap_angle_pending,
        )
        self.btn_angle_confirm = ft.FilledButton(
            content="Confirm angle",
            on_click=self._confirm_angle,
            style=ft.ButtonStyle(bgcolor=ACCENT_BRIGHT, color=TEXT),
            height=36,
            visible=False,
        )
        self.btn_angle_regen = ft.OutlinedButton(
            content="Regenerate",
            on_click=self._regen_angle,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
            height=36,
            visible=False,
        )
        self.btn_angle_dismiss = ft.TextButton(
            content="Dismiss",
            on_click=self._dismiss_angle_preview,
            style=ft.ButtonStyle(color=TEXT_MUTED),
            visible=False,
        )
        self.angle_pack_box = ft.Container(
            content=ft.Column(
                [
                    ft.Text(
                        "Angle pack",
                        size=FONT_SM,
                        color=TEXT,
                        weight=ft.FontWeight.W_600,
                    ),
                    self.angle_pack_hint,
                    ft.Row(
                        [
                            ft.Column(
                                [
                                    ft.GestureDetector(
                                        content=self.angle_hero_host,
                                        on_tap=self._make_angle_preview("hero"),
                                    ),
                                    self.angle_slot_hero_lab,
                                ],
                                spacing=2,
                                tight=True,
                                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                            ft.Column(
                                [
                                    ft.GestureDetector(
                                        content=self.angle_b_host,
                                        on_tap=self._make_angle_preview("angle_b"),
                                    ),
                                    self.angle_slot_b_lab,
                                    self.btn_clear_b,
                                ],
                                spacing=2,
                                tight=True,
                                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                            ft.Column(
                                [
                                    ft.GestureDetector(
                                        content=self.angle_c_host,
                                        on_tap=self._make_angle_preview("angle_c"),
                                    ),
                                    self.angle_slot_c_lab,
                                    self.btn_clear_c,
                                ],
                                spacing=2,
                                tight=True,
                                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                        ],
                        spacing=12,
                    ),
                    ft.Row(
                        [self.angle_model_dd, self.angle_quality_dd],
                        spacing=8,
                    ),
                    self.angle_note,
                    ft.Row(
                        [self.btn_gen_left, self.btn_gen_right, self.btn_gen_reverse],
                        spacing=6,
                        wrap=True,
                    ),
                    self.angle_cost_box,
                    self.angle_pending_label,
                    ft.Text(
                        "Click preview to enlarge before Confirm",
                        size=11,
                        color=TEXT_MUTED,
                    ),
                    ft.Row(
                        [
                            self.angle_pending_tap,
                            self.btn_angle_confirm,
                            self.btn_angle_regen,
                            self.btn_angle_dismiss,
                        ],
                        spacing=8,
                        wrap=True,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ],
                spacing=6,
                tight=True,
            ),
            bgcolor=PANEL,
            border=ft.Border.all(1, BORDER),
            border_radius=8,
            padding=8,
            visible=False,
        )

        # --- Make scene sheet (single-shot location bible) ---
        self.sheet_title = ft.Text(
            "Make scene sheet",
            size=FONT_SM,
            color=TEXT,
            weight=ft.FontWeight.W_700,
        )
        self.sheet_scene_label = ft.Text("", size=FONT_SM, color=TEXT_MUTED)
        self.sheet_mode = ft.RadioGroup(
            content=ft.Column(
                [
                    ft.Radio(
                        value="t2i",
                        label="From description (T2I)",
                    ),
                    ft.Radio(
                        value="i2i",
                        label="From this still (I2I)",
                    ),
                ],
                spacing=2,
                tight=True,
            ),
            value="t2i",
            on_change=self._on_sheet_mode_change,
        )
        self.sheet_loc_dd = styled_dropdown(
            label_text="Location type",
            options=list(SHEET_LOCATION_TYPES),
            value=SHEET_HELPER_NONE,
            on_select=self._on_sheet_loc_change,
            expand=True,
        )
        self.sheet_custom_loc = ft.TextField(
            label="Custom location (free text)",
            hint_text="Required when Location type = Custom — e.g. flooded subway platform",
            dense=True,
            filled=True,
            fill_color=PANEL,
            border_color=BORDER,
            color=TEXT,
            text_size=FONT_SM,
            visible=False,
        )
        self.sheet_cond_dd = styled_dropdown(
            label_text="Condition",
            options=list(SHEET_CONDITIONS),
            value=SHEET_HELPER_NONE,
            on_select=self._on_sheet_controls_change,
            expand=True,
        )
        self.sheet_time_dd = styled_dropdown(
            label_text="Time / light",
            options=list(SHEET_TIME_LIGHT),
            value=SHEET_HELPER_NONE,
            on_select=self._on_sheet_controls_change,
            expand=True,
        )
        self.sheet_cam_dd = styled_dropdown(
            label_text="Camera language",
            options=list(SHEET_CAMERA_LANG),
            value=SHEET_HELPER_NONE,
            on_select=self._on_sheet_controls_change,
            expand=True,
        )
        self.sheet_cam_hint = ft.Text(
            "Default: production design / location bible (no real-estate tone). "
            "Pick Documentary/real-estate only if you want that look.",
            size=11,
            color=TEXT_MUTED,
            max_lines=2,
        )
        self.sheet_density_dd = styled_dropdown(
            label_text="Sheet density",
            options=list(SHEET_DENSITY_OPTS),
            value="Standard",
            on_select=self._on_sheet_controls_change,
            expand=True,
        )
        self.sheet_notes = ft.TextField(
            label="Key landmarks / materials / damage",
            hint_text=(
                "e.g. scorched brick walls, overturned cars, fog between towers — "
                "not listing amenities"
            ),
            dense=True,
            filled=True,
            fill_color=PANEL,
            border_color=BORDER,
            color=TEXT,
            text_size=FONT_SM,
            multiline=True,
            min_lines=2,
            max_lines=4,
        )
        self.sheet_include_exterior = ft.Checkbox(
            label="Include exterior / entrance elevation",
            value=False,
            fill_color=ACCENT,
            tooltip="Off for pure interiors; on when you want street-facing or entry panel",
        )
        self.sheet_no_people = ft.Checkbox(
            label="No people",
            value=True,
            fill_color=ACCENT,
        )
        self.sheet_no_logos = ft.Checkbox(
            label="No readable logos/text",
            value=True,
            fill_color=ACCENT,
        )
        self.sheet_creative_direction = ft.TextField(
            label="Creative direction for Enhance (optional)",
            hint_text=(
                "Intent only for Grok Enhance — not sent to Generate as-is. "
                "e.g. “marvel-cinematic ruined street, wet asphalt, smoke columns”"
            ),
            value="",
            multiline=True,
            min_lines=2,
            max_lines=4,
            dense=True,
            filled=True,
            fill_color=PANEL_ELEVATED,
            border_color=BORDER,
            color=TEXT,
            text_size=FONT_SM,
        )
        self.sheet_creative_hint = ft.Text(
            "Enhance-only: steers Grok when you hit Enhance. Empty = helpers + sheet "
            "prompt only. Never injected into Generate as-is.",
            size=FONT_SM,
            color=TEXT_MUTED,
            max_lines=2,
        )
        self.sheet_prompt = ft.TextField(
            label="Sheet prompt (Enhance rewrites)",
            hint_text="Filled from helpers if empty; long text stays collapsed below",
            value="",
            multiline=True,
            min_lines=2,
            max_lines=5,
            dense=True,
            filled=True,
            fill_color=PANEL,
            border_color=BORDER,
            color=TEXT,
            text_size=FONT_SM,
        )
        self.sheet_prompt_tile = ft.ExpansionTile(
            title=ft.Text(
                "Sheet prompt (optional edit)",
                size=FONT_SM,
                color=TEXT,
                weight=ft.FontWeight.W_600,
            ),
            subtitle=ft.Text(
                "Collapsed by default so Generate stays on screen",
                size=11,
                color=TEXT_MUTED,
            ),
            expanded=False,
            affinity=ft.TileAffinity.LEADING,
            controls=[self.sheet_prompt],
        )
        _sh_labs = scene_sheet_model_labels(mode="t2i")
        _sh_def = preferred_scene_sheet_model(mode="t2i")
        if _sh_def not in _sh_labs and _sh_labs:
            _sh_def = _sh_labs[0]
        self.sheet_model_dd = styled_dropdown(
            label_text="Model",
            options=_sh_labs,
            value=_sh_def,
            on_select=self._on_sheet_controls_change,
            expand=True,
        )
        _nmax = scene_sheet_max_images(_sh_def, mode="t2i")
        self.sheet_num_dd = styled_dropdown(
            label_text="# sheets",
            options=[str(i) for i in range(1, max(2, _nmax) + 1)],
            value="1",
            on_select=self._on_sheet_controls_change,
            expand=True,
        )
        self.sheet_num_dd.visible = _nmax > 1
        self.sheet_cost = ft.Text(
            estimate_scene_sheet_cost(model_label=_sh_def, mode="t2i"),
            size=FONT_SM,
            color=TEXT_MUTED,
        )
        self.btn_sheet_enhance = make_enhance_button(
            on_click=self._on_sheet_enhance,
            tooltip=(
                "Rewrite the full sheet prompt for the selected model (Grok). "
                "Uses helpers + creative direction. Model is not changed."
            ),
        )
        self.btn_sheet_generate = ft.FilledButton(
            content="Generate sheet",
            icon=ft.Icons.GRID_VIEW,
            on_click=self._sheet_generate,
            style=ft.ButtonStyle(bgcolor=ACCENT_BRIGHT, color=TEXT),
            height=40,
        )
        self.btn_sheet_close = ft.TextButton(
            content="Close",
            on_click=self._sheet_close,
            style=ft.ButtonStyle(color=TEXT_MUTED),
        )
        self.sheet_progress_ring = ft.ProgressRing(
            width=28, height=28, stroke_width=3, color=ACCENT, visible=False
        )
        self.sheet_busy_row = ft.Row(
            [
                self.sheet_progress_ring,
                ft.Text(
                    "Generating scene sheet…",
                    size=FONT_SM,
                    color=ACCENT,
                    weight=ft.FontWeight.W_600,
                ),
            ],
            spacing=10,
            visible=False,
        )
        self.sheet_results_host = ft.Column(spacing=8, tight=True, visible=False)
        self.sheet_preview_label = ft.Text("", size=FONT_SM, color=TEXT_MUTED)
        # Primary controls first so Generate stays above the fold; prompt is collapsible
        self.sheet_box = ft.Container(
            content=ft.Column(
                [
                    self.sheet_title,
                    self.sheet_scene_label,
                    ft.Text(
                        "One-shot location bible. Primary sheet or save gens as "
                        "variations under this scene (not new top-level scenes).",
                        size=FONT_SM,
                        color=TEXT_MUTED,
                    ),
                    label("Mode", muted=True),
                    self.sheet_mode,
                    ft.Row([self.sheet_loc_dd, self.sheet_cond_dd], spacing=8),
                    self.sheet_custom_loc,
                    ft.Row([self.sheet_time_dd, self.sheet_cam_dd], spacing=8),
                    self.sheet_cam_hint,
                    ft.Row([self.sheet_density_dd], spacing=0),
                    self.sheet_notes,
                    ft.Row(
                        [
                            self.sheet_include_exterior,
                            self.sheet_no_people,
                            self.sheet_no_logos,
                        ],
                        spacing=12,
                        wrap=True,
                    ),
                    self.sheet_creative_direction,
                    self.sheet_creative_hint,
                    ft.Row(
                        [self.sheet_model_dd, self.sheet_num_dd],
                        spacing=8,
                    ),
                    self.sheet_cost,
                    ft.Row(
                        [
                            self.btn_sheet_enhance,
                            self.btn_sheet_generate,
                            self.btn_sheet_close,
                        ],
                        spacing=8,
                        wrap=True,
                    ),
                    self.sheet_busy_row,
                    self.sheet_prompt_tile,
                    self.sheet_preview_label,
                    self.sheet_results_host,
                ],
                spacing=6,
                tight=True,
                scroll=ft.ScrollMode.AUTO,
            ),
            bgcolor=PANEL_ELEVATED,
            border=ft.Border.all(2, ACCENT),
            border_radius=8,
            padding=12,
            height=620,
        )

        # Dynamic left workspace — form OR variation OR sheet (swap .controls)
        self.work_host = ft.Column(spacing=8, tight=True)

        self.status = ft.Text("", size=FONT_SM, color=TEXT_MUTED, max_lines=4)
        self.job_progress = JobProgress()

        self.btn_empty_new = ft.FilledButton(
            content="New scene",
            icon=ft.Icons.ADD,
            on_click=self._open_new_scene,
            style=ft.ButtonStyle(bgcolor=ACCENT_BRIGHT, color=TEXT),
            height=40,
        )
        self.empty_state = ft.Column(
            [
                ft.Text(
                    "No scenes yet.",
                    size=FONT_SM,
                    color=TEXT,
                    weight=ft.FontWeight.W_600,
                ),
                ft.Text(
                    "Click New scene to upload or generate a location plate "
                    "(gym, street, park…) for Director scene refs.",
                    size=FONT_SM,
                    color=TEXT_MUTED,
                ),
                self.btn_empty_new,
            ],
            spacing=8,
            tight=True,
            visible=True,
        )
        self.list_host = ft.Column(spacing=8, tight=True)
        self.list_count = ft.Text("", size=FONT_SM, color=TEXT_MUTED)

        self._refresh_t2i_cost_sync()
        self._mount_form_workspace()
        self.refresh()

    # ----- layout / modes -----

    def _form_workspace_controls(self) -> list[ft.Control]:
        """Add/edit + T2I controls (New Scene path). Never used for Create variation."""
        return [
            self.form_heading,
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
            self.angle_pack_box,
            ft.Divider(height=1, color=BORDER),
            self.t2i_box,
        ]

    def _set_var_parent_thumb(self, still: str | None) -> None:
        """Show parent plate or fixed-size placeholder (never zero-height)."""
        if still and Path(still).is_file():
            try:
                self.var_parent_thumb.src = str(Path(still).resolve())
            except Exception:
                self.var_parent_thumb.src = still
            self.var_parent_thumb_host.content = self.var_parent_thumb
        else:
            self.var_parent_thumb.src = ""
            self.var_parent_thumb_host.content = self.var_parent_thumb_empty

    def _set_var_result_preview(self, path: str | None) -> None:
        if path and Path(path).is_file():
            try:
                self.var_preview.src = str(Path(path).resolve())
            except Exception:
                self.var_preview.src = path
            self.var_preview.visible = True
            self.var_preview_host.content = self.var_preview
        else:
            self.var_preview.src = ""
            self.var_preview.visible = False
            self.var_preview_host.content = self.var_preview_empty

    def _assemble_variation_panel(self) -> ft.Container:
        """
        Full I2I variation form with real controls and forced min height.

        Built every open so ListView never keeps an empty/zero-height shell.
        No expand=True children (that collapses height inside left-rail ListView).
        """
        parent_row = ft.Row(
            [
                self.var_parent_thumb_host,
                ft.Column(
                    [self.var_parent_label, self.var_parent_sub, self.var_error],
                    spacing=4,
                    tight=True,
                ),
            ],
            spacing=12,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )
        body = ft.Column(
            [
                self.var_title,
                ft.Text(
                    "Parent still is the I2I reference. Change season / weather / "
                    "time / style only. Cancel returns to Scenes form (no New Scene wipe).",
                    size=FONT_SM,
                    color=TEXT_MUTED,
                ),
                parent_row,
                self.var_name,
                self.var_prompt,
                self.var_chip_row,
                ft.Row(
                    [self.var_model_dd, self.var_quality_dd],
                    spacing=8,
                ),
                ft.Row(
                    [self.btn_var_enhance, self.btn_var_gen, self.btn_var_close],
                    spacing=8,
                    wrap=True,
                ),
                self.var_cost_box,
                ft.Text("Result preview (click to enlarge)", size=11, color=TEXT_MUTED),
                ft.Row(
                    [self.var_preview_tap, self.btn_var_save],
                    spacing=10,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    wrap=True,
                ),
            ],
            spacing=8,
            tight=True,
            scroll=ft.ScrollMode.AUTO,
            # expand only within fixed-height shell below — NOT as ListView direct child
            expand=True,
        )
        return ft.Container(
            content=body,
            bgcolor=PANEL_ELEVATED,
            border=ft.Border.all(2, ACCENT),
            border_radius=8,
            padding=12,
            # Force ListView to reserve vertical space (prevents empty collapse)
            height=580,
        )

    def _mount_form_workspace(self) -> None:
        self._ui_mode = "form"
        self.t2i_box.visible = True
        # Replace controls list entirely (Flet: assign new list, then update)
        self.work_host.controls = list(self._form_workspace_controls())

    def _mount_variation_workspace(self) -> None:
        """
        Install a full I2I variation panel into the left work area.

        Does NOT call _reset_form. Uses a fixed-height shell so ListView
        cannot collapse to blank.
        """
        self._ui_mode = "variation"
        panel = self._assemble_variation_panel()
        self._var_panel_shell = panel
        self.work_host.controls = [panel]

    def _mount_sheet_workspace(self) -> None:
        """Install Make scene sheet panel (single-shot composite)."""
        self._ui_mode = "sheet"
        self.work_host.controls = [self.sheet_box]

    def build(self) -> ft.Control:
        from media_studio.flet_layout import make_split_workspace
        from media_studio.flet_theme import RAIL_WIDTH

        left = [
            section_title("Scenes"),
            ft.Text(
                "Location / establishing stills — where the action happens. "
                "Make scene sheet = one-shot location bible (no multi-step angles). "
                "Local store only. Director / R2V scene refs; Scene Placer for characters.",
                size=FONT_SM,
                color=TEXT_MUTED,
            ),
            ft.Row(
                [self.btn_new_scene, self.btn_scene_placer],
                spacing=8,
                wrap=True,
            ),
            ft.Divider(height=1, color=BORDER),
            self.work_host,
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
        """Full add/edit reset — still, name, notes, T2I prompt + generate preview.

        Used only by New Scene / cancel / after save — NEVER by Create variation.
        """
        self._edit_id = None
        self._selected_scene_id = None
        self._set_still(None)
        self.name_field.value = ""
        self.notes_field.value = ""
        # Location description / T2I prompt + plate helpers
        try:
            self.t2i_desc.value = ""
        except Exception:
            pass
        try:
            self._reset_plate_helpers()
        except Exception:
            pass
        self.btn_save.content = "Save scene"
        self.btn_cancel_edit.visible = False
        self.form_heading.value = "Add / edit scene"
        self._t2i_pending_path = None
        self._pending_aspect = normalize_scene_aspect(self.t2i_aspect_dd.value) or "16:9"
        try:
            self.t2i_preview.src = ""
        except Exception:
            pass
        self.t2i_preview.visible = False
        self.t2i_aspect_badge.visible = False
        self.btn_t2i_use.visible = False
        self.t2i_box.visible = True
        self.angle_pack_box.visible = False
        self._angle_pack_scene_id = None
        self._angle_pending_path = None
        self.btn_angle_confirm.visible = False
        try:
            self.btn_angle_regen.visible = False
        except Exception:
            pass
        self.btn_angle_dismiss.visible = False
        self.angle_pending_img.visible = False
        try:
            self.angle_pending_host.content = self.angle_pending_empty
            self.angle_pending_label.visible = False
            self.btn_clear_b.visible = False
            self.btn_clear_c.visible = False
            if hasattr(self, "angle_note"):
                self.angle_note.value = ""
        except Exception:
            pass

    async def _open_new_scene(self, e: ft.ControlEvent | None = None) -> None:
        """Primary entry: fully clear form, focus name + still/generate."""
        # Exit variation mode without treating it as “discard parent” wipe of library
        self._var_parent_id = None
        self._var_parent_path = None
        self._var_pending_path = None
        self._reset_form()
        self._mount_form_workspace()
        self.btn_cancel_edit.visible = True
        self.form_heading.value = "New scene"
        self.btn_save.content = "Save scene"
        self.refresh()  # clear selection highlight
        self._set_status(
            "New scene — enter a short Name, upload a still or Generate a plate, then Save."
        )
        try:
            self.name_field.focus()
        except Exception:
            pass
        try:
            self.page.update()
        except Exception:
            pass

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
                entry = updated
            else:
                entry = add_scene(
                    name=name,
                    still_path=self._still_path,
                    notes=notes,
                    aspect=ar,
                )
                badge = f" · {entry.aspect}" if entry.aspect else ""
                self._set_status(f"Saved scene: {entry.name}{badge}")
            # Stay in edit so user can Generate Left/Right angles
            self._edit_id = entry.id
            self._selected_scene_id = entry.id
            self.btn_save.content = "Save changes"
            self.btn_cancel_edit.visible = True
            self.form_heading.value = f"Edit · {entry.display_name()}"
            self._sync_angle_pack_ui(entry)
            self._mount_form_workspace()
            self.refresh()
        except Exception as exc:
            self._set_status(str(exc), error=True)

    async def _cancel_edit(self, e: ft.ControlEvent) -> None:
        self._exit_variation_mode(clear_parent=True)
        self._reset_form()
        self._mount_form_workspace()
        self.refresh()
        self._set_status("Edit cancelled.")
        try:
            self.page.update()
        except Exception:
            pass

    # ----- T2I + plate helpers -----

    def _dd_val(self, dd: ft.Control | None) -> str:
        try:
            return str(getattr(dd, "value", None) or "").strip()
        except Exception:
            return ""

    def _reset_plate_helpers(self) -> None:
        for dd in (
            self.t2i_setting_dd,
            self.t2i_type_dd,
            self.t2i_time_dd,
            self.t2i_weather_dd,
            self.t2i_activity_dd,
        ):
            try:
                dd.value = HELPER_NONE
            except Exception:
                pass
        try:
            self.t2i_helper_notes.value = ""
        except Exception:
            pass

    def _apply_plate_description_rebuild(self) -> None:
        """Rebuild location description from helpers + optional notes (music-builder pattern)."""
        try:
            notes = (self.t2i_helper_notes.value or "").strip()
        except Exception:
            notes = ""
        self.t2i_desc.value = assemble_plate_description(
            setting=self._dd_val(self.t2i_setting_dd),
            place_type=self._dd_val(self.t2i_type_dd),
            time_of_day=self._dd_val(self.t2i_time_dd),
            weather=self._dd_val(self.t2i_weather_dd),
            activity=self._dd_val(self.t2i_activity_dd),
            notes=notes,
        )

    async def _on_plate_helper(self, e: ft.ControlEvent | None = None) -> None:
        try:
            self._apply_plate_description_rebuild()
        except Exception as exc:
            self._set_status(f"Plate helper rebuild: {exc}", error=True)
            return
        try:
            self.page.update()
        except Exception:
            pass

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

    def _open_preview(
        self,
        path: str,
        *,
        title: str = "Scene preview",
        compare_path: str | None = None,
    ) -> None:
        p = Path(path)
        if not p.is_file():
            self._set_status(f"Missing still: {path}", error=True)
            return
        win_w = float(getattr(self.page.window, "width", None) or 1400)
        win_h = float(getattr(self.page.window, "height", None) or 900)
        body_w = int(min(max(win_w - 80, 640), win_w * 0.9))
        body_h = int(min(max(win_h - 100, 480), win_h * 0.88))

        main_img = ft.Image(
            src=str(p.resolve()),
            fit=ft.BoxFit.CONTAIN,
            expand=True,
            gapless_playback=True,
        )
        title_txt = ft.Text(
            title,
            size=FONT_MD,
            color=TEXT,
            weight=ft.FontWeight.W_700,
            expand=True,
            max_lines=1,
            overflow=ft.TextOverflow.ELLIPSIS,
        )

        async def _close(_e: ft.ControlEvent) -> None:
            close_dialog(self.page, self._lightbox_dialog)

        cmp = (compare_path or "").strip()
        has_cmp = bool(cmp and Path(cmp).is_file())
        if has_cmp:
            # Stack: source under, result on top — opacity slider on result
            under = ft.Image(
                src=str(Path(cmp).resolve()),
                fit=ft.BoxFit.CONTAIN,
                expand=True,
                gapless_playback=True,
            )
            over = ft.Image(
                src=str(p.resolve()),
                fit=ft.BoxFit.CONTAIN,
                expand=True,
                gapless_playback=True,
                opacity=1.0,
            )
            opac_label = ft.Text(
                "Opacity: sheet over source (1.0 = sheet only)",
                size=FONT_SM,
                color=TEXT_MUTED,
            )

            def _on_opac(e: ft.ControlEvent) -> None:
                try:
                    over.opacity = float(e.control.value)
                    self.page.update()
                except Exception:
                    pass

            slider = ft.Slider(
                min=0,
                max=1,
                divisions=20,
                value=1.0,
                on_change=_on_opac,
                active_color=ACCENT,
            )
            stage = ft.Column(
                [
                    ft.Stack(
                        [under, over],
                        expand=True,
                    ),
                    opac_label,
                    slider,
                ],
                spacing=6,
                expand=True,
            )
        else:
            stage = ft.Container(
                content=main_img,
                expand=True,
                bgcolor="#0a0c10",
                border_radius=8,
                border=ft.Border.all(1, BORDER),
                alignment=ft.Alignment.CENTER,
                clip_behavior=ft.ClipBehavior.HARD_EDGE,
            )

        header = ft.Row(
            [
                title_txt,
                ft.IconButton(
                    icon=ft.Icons.CLOSE,
                    icon_color=TEXT,
                    on_click=_close,
                    tooltip="Close",
                ),
            ],
            spacing=8,
        )
        if has_cmp:
            stage_wrap: ft.Control = ft.Container(
                content=stage,
                expand=True,
                bgcolor="#0a0c10",
                border_radius=8,
                border=ft.Border.all(1, BORDER),
                padding=8,
            )
        else:
            stage_wrap = stage
        body = ft.Container(
            width=body_w,
            height=body_h,
            content=ft.Column(
                [header, stage_wrap],
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

    def _make_preview_path(
        self,
        path: str,
        title: str,
        *,
        compare_path: str | None = None,
    ):
        async def _tap(_e: ft.ControlEvent) -> None:
            if path and Path(path).is_file():
                self._open_preview(
                    path, title=title, compare_path=compare_path
                )

        return _tap

    # ----- list cards -----

    def _card(
        self,
        s: SavedScene,
        *,
        children: list[SavedScene] | None = None,
        nested: bool = False,
    ) -> ft.Control:
        still_src = s.resolved_still_path()
        still_ok = bool(still_src)
        badge_txt = s.aspect_badge()
        title = s.display_name()
        if still_ok and still_src:
            # Absolute path — avoids blank/green thumbs when relative path is stale
            img = ft.Image(
                src=str(Path(still_src).resolve()),
                width=_THUMB,
                height=_THUMB,
                fit=ft.BoxFit.COVER,
                border_radius=6,
                gapless_playback=True,
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
                    still_src,
                    f"{title}" + (f" · {badge_txt}" if badge_txt else ""),
                ),
            )
        else:
            # Broken path / missing still — placeholder (not a green blank Image)
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
        # Primary = user Name; angle pack badge when B/C filled
        n_angles = 1 if still_ok else 0
        if still_ok:
            n_angles += len(s.angle_extra_paths())
        pack_badge = ""
        if n_angles >= 2:
            pack_badge = f" · {n_angles} angles"
        if s.has_sheet():
            pack_badge += " · sheet ✓"
        name_txt = ft.Text(
            f"{title}{lock_icon}{pack_badge}",
            size=FONT_SM,
            color=TEXT,
            weight=ft.FontWeight.W_700,
            max_lines=1,
            overflow=ft.TextOverflow.ELLIPSIS,
        )
        secondary = notes if notes else ("Variation" if nested else "No notes")
        if n_angles >= 2 and notes:
            secondary = f"{secondary} · pack: hero" + (
                "+left" if s.resolved_angle_path("angle_b") else ""
            ) + (
                "+right" if s.resolved_angle_path("angle_c") else ""
            )
        notes_txt = ft.Text(
            secondary,
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
        # In-tab Scene sheet thumb + expand
        sheet_path = s.sheet_file()
        sheet_thumb: ft.Control | None = None
        if sheet_path and Path(sheet_path).is_file():
            sh_img = ft.Image(
                src=sheet_path,
                width=_THUMB,
                height=_THUMB,
                fit=ft.BoxFit.COVER,
                border_radius=6,
            )
            sheet_thumb = ft.Column(
                [
                    ft.Text("Sheet", size=10, color=TEXT_MUTED),
                    ft.GestureDetector(
                        content=sh_img,
                        on_tap=self._make_preview_path(
                            sheet_path,
                            f"{title} · Scene sheet",
                            compare_path=still_src if still_ok else None,
                        ),
                    ),
                    ft.TextButton(
                        content="Expand",
                        on_click=self._make_preview_path(
                            sheet_path,
                            f"{title} · Scene sheet",
                            compare_path=still_src if still_ok else None,
                        ),
                        style=ft.ButtonStyle(color=ACCENT),
                        height=28,
                    ),
                ],
                spacing=2,
                tight=True,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
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
        # Always clickable on base scenes (open panel even if still missing — show error)
        btn_var = ft.OutlinedButton(
            content="Create variation",
            icon=ft.Icons.AUTO_FIX_HIGH,
            on_click=self._make_open_variation(s.id),
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
            height=36,
            disabled=nested,
            visible=not nested,
            tooltip="Season / weather / era transform from this plate (I2I)",
        )
        has_sheet = bool(s.has_sheet())
        btn_sheet = ft.OutlinedButton(
            content="Make scene sheet" + (" ✓" if has_sheet else ""),
            icon=ft.Icons.GRID_ON,
            on_click=self._make_open_sheet(s),
            style=ft.ButtonStyle(
                color=ACCENT if has_sheet else TEXT,
                side=ft.BorderSide(1, ACCENT if has_sheet else BORDER),
            ),
            height=36,
            tooltip=(
                "One-shot location-bible grid (T2I or I2I from this still)"
                + (" · sheet saved" if has_sheet else "")
            ),
        )
        btn_placer = ft.OutlinedButton(
            content="Place character",
            icon=ft.Icons.PERSON_PIN_CIRCLE_OUTLINED,
            on_click=self._make_open_scene_placer(s),
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
            height=36,
            disabled=not still_ok,
            tooltip="Open Scene Placer with this plate (Characters tab)",
        )

        actions = [
            btn_sheet,
            btn_var,
            btn_placer,
            btn_edit,
            btn_lock,
            btn_folder,
            btn_delete,
        ]
        if nested:
            actions = [
                btn_sheet,
                btn_placer,
                btn_edit,
                btn_lock,
                btn_folder,
                btn_delete,
            ]

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

        selected = (not nested) and self._selected_scene_id == s.id
        border_col = (
            ACCENT_BRIGHT
            if selected
            else (ACCENT if s.locked else BORDER)
        )
        left_thumbs: list[ft.Control] = [thumb]
        if sheet_thumb is not None:
            left_thumbs.append(sheet_thumb)
        return ft.Container(
            content=ft.Row(
                [
                    ft.Row(left_thumbs, spacing=8),
                    body,
                ],
                spacing=12,
                vertical_alignment=ft.CrossAxisAlignment.START,
            ),
            bgcolor=PANEL if nested else PANEL_ELEVATED,
            border=ft.Border.all(2 if selected else 1, border_col),
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

    # ----- Make scene sheet (single-shot) -----

    def _sheet_mode_value(self) -> str:
        v = (self.sheet_mode.value or "t2i").strip().lower()
        return "i2i" if v in ("i2i", "from_still", "from this still") else "t2i"

    def _sheet_model_choice(self) -> str:
        return (
            self.sheet_model_dd.value
            or preferred_scene_sheet_model(mode=self._sheet_mode_value())
        ).strip()

    def _refresh_sheet_cost(self) -> None:
        mode = self._sheet_mode_value()
        n = 1
        try:
            n = int(self.sheet_num_dd.value or "1")
        except (TypeError, ValueError):
            n = 1
        base = estimate_scene_sheet_cost(
            model_label=self._sheet_model_choice(),
            mode=mode,
        )
        if n > 1:
            self.sheet_cost.value = f"{base} × {n}"
        else:
            self.sheet_cost.value = base

    def _sync_sheet_models_for_mode(self) -> None:
        mode = self._sheet_mode_value()
        labs = scene_sheet_model_labels(mode=mode)
        pref = preferred_scene_sheet_model(mode=mode)
        from media_studio.flet_theme import dropdown_options

        self.sheet_model_dd.options = dropdown_options(labs)
        if self.sheet_model_dd.value not in labs:
            self.sheet_model_dd.value = pref if pref in labs else (labs[0] if labs else None)
        nmax = scene_sheet_max_images(self.sheet_model_dd.value, mode=mode)
        opts = [str(i) for i in range(1, nmax + 1)]
        self.sheet_num_dd.options = dropdown_options(opts)
        if (self.sheet_num_dd.value or "1") not in opts:
            self.sheet_num_dd.value = "1"
        self.sheet_num_dd.visible = nmax > 1
        self._refresh_sheet_cost()

    def _sheet_num_requested(self) -> int:
        try:
            n = int(self.sheet_num_dd.value or "1")
        except (TypeError, ValueError):
            n = 1
        mode = self._sheet_mode_value()
        nmax = scene_sheet_max_images(self._sheet_model_choice(), mode=mode)
        return max(1, min(n, nmax))

    async def _on_sheet_mode_change(self, e: ft.ControlEvent | None = None) -> None:
        self._sync_sheet_models_for_mode()
        try:
            self.page.update()
        except Exception:
            pass

    async def _on_sheet_loc_change(self, e: ft.ControlEvent | None = None) -> None:
        loc = (self.sheet_loc_dd.value or "").strip()
        self.sheet_custom_loc.visible = loc.lower() == "custom"
        self._refresh_sheet_cost()
        try:
            self.page.update()
        except Exception:
            pass

    async def _on_sheet_controls_change(
        self, e: ft.ControlEvent | None = None
    ) -> None:
        self._refresh_sheet_cost()
        try:
            self.page.update()
        except Exception:
            pass

    def _assemble_sheet_prompt_from_helpers(self) -> str:
        return assemble_scene_sheet_prompt(
            mode=self._sheet_mode_value(),
            location_type=self.sheet_loc_dd.value,
            condition=self.sheet_cond_dd.value,
            time_light=self.sheet_time_dd.value,
            camera_lang=self.sheet_cam_dd.value,
            density=self.sheet_density_dd.value,
            landmarks=self.sheet_notes.value,
            custom_location=self.sheet_custom_loc.value,
            include_exterior_entrance=bool(self.sheet_include_exterior.value),
            no_people=bool(self.sheet_no_people.value),
            no_logos=bool(self.sheet_no_logos.value),
            scene_name=self._sheet_scene_name,
        )

    def _sheet_enhance_extra(self) -> dict[str, Any]:
        """Helpers + creative direction for Enhance — never sent to Generate as-is."""
        from media_studio.helper_none import active_helper

        snap: dict[str, Any] = {
            "workspace": "scenes",
            "mode": "scene_sheet",
            "sheet_mode": self._sheet_mode_value(),
            "guidance": scene_sheet_enhance_guidance(
                camera_lang=self.sheet_cam_dd.value,
                mode=self._sheet_mode_value(),
            ),
        }
        for key, val in (
            ("location_type", self.sheet_loc_dd.value),
            ("condition", self.sheet_cond_dd.value),
            ("time_light", self.sheet_time_dd.value),
            ("camera_lang", self.sheet_cam_dd.value),
            ("density", self.sheet_density_dd.value),
        ):
            a = active_helper(val)
            if a:
                snap[key] = a
        note = (self.sheet_notes.value or "").strip()
        if note:
            snap["landmarks"] = note
        custom = (self.sheet_custom_loc.value or "").strip()
        if custom:
            snap["custom_location"] = custom
        if bool(self.sheet_include_exterior.value):
            snap["include_exterior_entrance"] = True
        snap["no_people"] = bool(self.sheet_no_people.value)
        snap["no_logos"] = bool(self.sheet_no_logos.value)
        direction = (self.sheet_creative_direction.value or "").strip()
        if direction:
            snap["creative_direction"] = direction
            snap["creative_direction_note"] = (
                "creative_direction is Enhance-only user intent — weave into "
                "optimized_prompt; do not leave it as a separate field. "
                "Never treat it as a raw Generate injection."
            )
        # Seed draft structure so Enhance has a base to rewrite
        snap["base_sheet_structure"] = self._assemble_sheet_prompt_from_helpers()
        return snap

    def _make_open_sheet(self, s: SavedScene):
        async def _click(_e: ft.ControlEvent) -> None:
            self._open_sheet(s)

        return _click

    def _open_sheet(self, s: SavedScene) -> None:
        if self._sheet_busy:
            return
        self._sheet_scene_id = s.id
        self._sheet_scene_name = s.display_name()
        self._sheet_pending_path = None
        hero = s.resolved_still_path()
        # Variation selected still can be hero of variation
        self._sheet_source_path = hero
        has_still = bool(hero and Path(hero).is_file())
        # Default mode: T2I when no still, else still allow both — prefer I2I if still
        self.sheet_mode.value = "i2i" if has_still else "t2i"
        self.sheet_scene_label.value = (
            f"{s.display_name()}"
            + (" · has hero still" if has_still else " · no still yet (T2I invents location)")
            + (" · sheet saved" if s.has_sheet() else "")
        )
        # Prefill model-ready prompt from helpers; creative direction stays empty
        try:
            self.sheet_prompt.value = self._assemble_sheet_prompt_from_helpers()
        except Exception:
            self.sheet_prompt.value = ""
        self.sheet_creative_direction.value = ""
        loc = (self.sheet_loc_dd.value or "").strip()
        self.sheet_custom_loc.visible = loc.lower() == "custom"
        self._sheet_pending_paths = []
        self._sheet_set_result_ui(None)
        self._sync_sheet_models_for_mode()
        self._mount_sheet_workspace()
        self._set_status(
            f"Make scene sheet · {s.display_name()}: helpers + optional Enhance "
            "direction, then Generate (creative direction is Enhance-only)."
        )
        try:
            self.page.update()
        except Exception:
            pass

    def _sheet_close(self, e: ft.ControlEvent | None = None) -> None:
        if self._sheet_busy:
            return
        self._sheet_pending_path = None
        self._sheet_set_result_ui(None)
        self._mount_form_workspace()
        try:
            self.page.update()
        except Exception:
            pass

    def _set_sheet_busy(self, busy: bool, *, message: str = "") -> None:
        self._sheet_busy = busy
        self.sheet_busy_row.visible = busy
        self.sheet_progress_ring.visible = busy
        try:
            t = self.sheet_busy_row.controls[1]
            if isinstance(t, ft.Text):
                t.value = message or "Generating scene sheet…"
        except Exception:
            pass
        self.btn_sheet_generate.disabled = busy
        self.btn_sheet_enhance.disabled = busy
        self.btn_sheet_close.disabled = busy
        if busy:
            self.sheet_results_host.visible = False
        try:
            self.page.update()
        except Exception:
            pass

    def _sheet_set_result_ui(self, paths: list[str] | str | None) -> None:
        """Show multi-gen results: each enlargeable; Accept primary / as variation / Discard."""
        self.sheet_results_host.controls.clear()
        if isinstance(paths, str):
            paths = [paths] if paths else []
        paths = [p for p in (paths or []) if p and Path(p).is_file()]
        self._sheet_pending_paths = list(paths)
        self._sheet_pending_path = paths[0] if paths else None
        if not paths:
            self.sheet_results_host.visible = False
            if not self._sheet_busy:
                self.sheet_preview_label.value = ""
            return
        self.sheet_results_host.visible = True
        n = len(paths)
        self.sheet_preview_label.value = (
            f"{n} sheet result(s) — expand each; set primary or save as variation"
        )
        src = self._sheet_source_path
        for i, path in enumerate(paths):
            img = ft.Image(
                src=path,
                width=140,
                height=100,
                fit=ft.BoxFit.CONTAIN,
                border_radius=6,
            )
            tap = ft.GestureDetector(
                content=img,
                on_tap=self._make_sheet_result_preview(path, i),
            )
            btn_primary = ft.FilledButton(
                content="Set as primary sheet",
                on_click=self._make_sheet_accept_primary(path),
                style=ft.ButtonStyle(bgcolor=ACCENT_BRIGHT, color=TEXT),
                height=32,
            )
            btn_var = ft.OutlinedButton(
                content="Save as variation",
                on_click=self._make_sheet_accept_variation(path, i),
                style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
                height=32,
                tooltip="Child under this scene — not a new top-level scene",
            )
            btn_disc = ft.TextButton(
                content="Discard",
                on_click=self._make_sheet_discard_one(path),
                style=ft.ButtonStyle(color=TEXT_MUTED),
                height=32,
            )
            card = ft.Container(
                content=ft.Column(
                    [
                        ft.Text(
                            f"Result {i + 1}/{n}",
                            size=FONT_SM,
                            color=TEXT,
                            weight=ft.FontWeight.W_600,
                        ),
                        tap,
                        ft.Text("Click to enlarge", size=11, color=TEXT_MUTED),
                        ft.Row(
                            [btn_primary, btn_var, btn_disc],
                            spacing=4,
                            wrap=True,
                        ),
                    ],
                    spacing=4,
                    tight=True,
                ),
                border=ft.Border.all(1, BORDER),
                border_radius=8,
                padding=8,
            )
            self.sheet_results_host.controls.append(card)
        _ = src  # compare available in expand via _make_sheet_result_preview

    def _make_sheet_result_preview(self, path: str, index: int):
        async def _tap(_e: ft.ControlEvent) -> None:
            src = self._sheet_source_path
            title = f"Scene sheet · {self._sheet_scene_name} · {index + 1}"
            self._open_preview(
                path,
                title=title,
                compare_path=src if src and Path(src).is_file() else None,
            )

        return _tap

    def _make_sheet_accept_primary(self, path: str):
        async def _click(_e: ft.ControlEvent) -> None:
            await self._sheet_accept_path(path, as_variation=False)

        return _click

    def _make_sheet_accept_variation(self, path: str, index: int):
        async def _click(_e: ft.ControlEvent) -> None:
            await self._sheet_accept_path(
                path, as_variation=True, variant_index=index + 1
            )

        return _click

    def _make_sheet_discard_one(self, path: str):
        async def _click(_e: ft.ControlEvent) -> None:
            self._sheet_pending_paths = [
                p for p in self._sheet_pending_paths if p != path
            ]
            self._sheet_set_result_ui(self._sheet_pending_paths)
            try:
                self.page.update()
            except Exception:
                pass

        return _click

    async def _on_sheet_enhance(self, e: ft.ControlEvent) -> None:
        # Seed sheet_prompt from helpers when empty so Enhance has a base
        if not (self.sheet_prompt.value or "").strip():
            try:
                self.sheet_prompt.value = self._assemble_sheet_prompt_from_helpers()
            except Exception:
                pass

        await run_prompt_enhance(
            page=self.page,
            state=self.state,
            prompt_field=self.sheet_prompt,
            get_model=self._sheet_model_choice,
            get_image=lambda: self._sheet_source_path
            if self._sheet_mode_value() == "i2i"
            else None,
            get_extra_context=self._sheet_enhance_extra,
            status_ctrl=self.status,
            job_progress=self.job_progress,
            enhance_btn=self.btn_sheet_enhance,
            busy_controls=[self.btn_sheet_generate],
            context_label="scene sheet prompt",
            allow_empty_with_context=True,
            busy_scope="scenes",
        )

    async def _sheet_generate(self, e: ft.ControlEvent | None = None) -> None:
        await self._run_sheet_generate(regen=False)

    async def _sheet_regenerate(self, e: ft.ControlEvent | None = None) -> None:
        await self._run_sheet_generate(regen=True)

    async def _run_sheet_generate(self, *, regen: bool) -> None:
        if self._sheet_busy:
            return
        if not self._sheet_scene_id:
            self._set_status("Open Make scene sheet from a scene card first.", error=True)
            return
        from media_studio.secrets_store import has_fal_key

        if not has_fal_key():
            self._set_status("FAL API key required — open Settings.", error=True)
            return
        mode = self._sheet_mode_value()
        source = self._sheet_source_path
        if mode == "i2i":
            if not source or not Path(source).is_file():
                self._set_status(
                    "I2I mode needs a hero still on this scene — upload/generate first "
                    "or switch to From description (T2I).",
                    error=True,
                )
                return
        if not self.state.try_busy("scenes"):
            return

        # Generate uses sheet_prompt (or fresh assemble) — NEVER creative_direction
        prompt = (self.sheet_prompt.value or "").strip()
        if not prompt:
            prompt = self._assemble_sheet_prompt_from_helpers()
            self.sheet_prompt.value = prompt
        model = self._sheet_model_choice()
        n_req = self._sheet_num_requested()
        self._refresh_sheet_cost()
        self._set_sheet_busy(
            True,
            message=f"Generating {n_req} scene sheet(s)…",
        )
        self.job_progress.start("Make scene sheet…", self.page)
        self._set_status(
            f"Generating scene sheet ×{n_req} ({mode.upper()})"
            + (" · regen" if regen else "")
            + "…"
        )

        def on_progress(msg: str) -> None:
            self.job_progress.set_message(classify_progress(msg), self.page)
            try:
                t = self.sheet_busy_row.controls[1]
                if isinstance(t, ft.Text):
                    t.value = msg or "Generating scene sheet…"
                self.page.update()
            except Exception:
                pass

        try:
            import json

            from media_studio.job_context import to_thread_with_job
            from media_studio.services import generate
            from media_studio.vision_service import run_vision

            out_paths: list[str] = []
            err = None
            if mode == "i2i":
                params = json.dumps({"num_images": n_req})
                result = await to_thread_with_job(
                    self.state,
                    generate,
                    prompt,
                    model_choice=model,
                    image_file=source,
                    output_dir=self.state.output_dir,
                    on_progress=on_progress,
                    scenario="scene-sheet",
                    parameters_json=params,
                )
                if result.ok:
                    imgs = list(result.image_paths or [])
                    if not imgs and result.primary_image:
                        imgs = [result.primary_image]
                    out_paths = [str(Path(p).resolve()) for p in imgs if p and Path(p).is_file()]
                else:
                    err = result.status or "Sheet generate failed."
            else:
                aspect_arg, resolution, ar_canon = resolve_scene_t2i_args(
                    model_label=model,
                    aspect_ui="16:9 · Horizontal",
                    quality="2K",
                )
                vres = await to_thread_with_job(
                    self.state,
                    run_vision,
                    mode="text_to_image",
                    prompt=prompt,
                    model_label=model,
                    aspect_ratio=aspect_arg,
                    resolution=resolution,
                    num_images=n_req,
                    output_dir=self.state.output_dir,
                    on_progress=on_progress,
                )
                if vres.ok:
                    paths = list(vres.paths or [])
                    if not paths and vres.path:
                        paths = [vres.path]
                    out_paths = [
                        str(Path(p).resolve()) for p in paths if p and Path(p).is_file()
                    ]
                else:
                    err = vres.status or "Sheet T2I failed."

            if out_paths:
                self._set_sheet_busy(False)
                self._sheet_set_result_ui(out_paths)
                self.job_progress.finish_ok(
                    f"{len(out_paths)} sheet(s) ready — set primary or save variation",
                    self.page,
                )
                self._set_status(
                    f"{len(out_paths)} scene sheet(s) ready — Set as primary · "
                    "Save as variation · Discard."
                )
            else:
                msg = err or "Sheet generate failed."
                self._set_sheet_busy(False)
                self._sheet_set_result_ui(None)
                self.job_progress.finish_error(msg, self.page)
                self._set_status(msg, error=True)
        except Exception as exc:
            self._set_sheet_busy(False)
            self._sheet_set_result_ui(None)
            self.job_progress.finish_error(str(exc), self.page)
            self._set_status(str(exc), error=True)
            traceback.print_exc()
        finally:
            self.state.clear_busy("scenes")
            try:
                self.page.update()
            except Exception:
                pass

    async def _sheet_accept_path(
        self,
        path: str,
        *,
        as_variation: bool = False,
        variant_index: int = 1,
    ) -> None:
        if self._sheet_busy:
            return
        sid = self._sheet_scene_id
        if not path or not Path(path).is_file() or not sid:
            self._set_status("No sheet to accept.", error=True)
            return
        parent = find_scene(sid)
        if parent is None:
            self._set_status("Scene not found.", error=True)
            return
        try:
            if as_variation:
                # Child under this scene — not a new top-level row
                name = f"{parent.display_name()} · sheet var {variant_index}"
                entry = add_scene(
                    name=name,
                    still_path=path,
                    notes=f"Scene sheet variation of {parent.display_name()}",
                    parent_id=parent.id,
                    aspect=parent.aspect or "16:9",
                )
                # Also mark as sheet on the variation for preferred-ref consistency
                try:
                    set_scene_sheet(entry.id, path)
                except Exception:
                    pass
                self._set_status(
                    f"Saved variation under {parent.display_name()}: {entry.display_name()}"
                )
            else:
                updated = set_scene_sheet(sid, path)
                if not updated:
                    self._set_status("Accept failed — scene not found.", error=True)
                    return
                try:
                    from media_studio.history import append_history

                    cite = f"Scene sheet: {updated.display_name()}"
                    append_history(
                        job_kind="scene_sheet",
                        model=self._sheet_model_choice(),
                        prompt=cite,
                        files=[updated.sheet_file() or path],
                        cost_estimate=estimate_scene_sheet_cost(
                            model_label=self._sheet_model_choice(),
                            mode=self._sheet_mode_value(),
                        ),
                        notes=["scene-sheet-primary", cite],
                        output_dir=self.state.output_dir,
                        scenario="scene-sheet",
                    )
                except Exception:
                    pass
                self.sheet_scene_label.value = (
                    f"{updated.display_name()} · primary sheet: "
                    f"{Path(updated.sheet_file() or path).name}"
                )
                self._set_status(
                    f"Primary Scene sheet set on {updated.display_name()} "
                    "(preferred R2V/Director ref)."
                )
            # Drop accepted path from pending batch
            self._sheet_pending_paths = [
                p for p in self._sheet_pending_paths if p != path
            ]
            self._sheet_set_result_ui(self._sheet_pending_paths)
            self.refresh()
        except Exception as exc:
            self._set_status(str(exc), error=True)
            return
        try:
            self.page.update()
        except Exception:
            pass

    def _sheet_dismiss_result(self, e: ft.ControlEvent | None = None) -> None:
        if self._sheet_busy:
            return
        self._sheet_pending_path = None
        self._sheet_pending_paths = []
        self._sheet_set_result_ui(None)
        try:
            self.page.update()
        except Exception:
            pass

    # ----- multi-angle pack -----

    def _make_gen_angle(self, target: str):
        async def _click(_e: ft.ControlEvent) -> None:
            await self._run_generate_angle(target)

        return _click

    def _make_angle_preview(self, slot: str):
        async def _tap(_e: ft.ControlEvent) -> None:
            sid = self._angle_pack_scene_id or self._edit_id
            if not sid:
                return
            s = find_scene(sid)
            if not s:
                return
            path = s.resolved_angle_path(slot)
            if path:
                self._open_preview(
                    path,
                    title=f"{s.display_name()} · {SCENE_ANGLE_LABELS.get(slot, slot)}",
                )

        return _tap

    def _sync_angle_pack_ui(self, scene: SavedScene | None = None) -> None:
        """Show Hero / Left(B) / Right(C) thumbs when editing a saved scene with hero."""
        s = scene
        if s is None and self._edit_id:
            s = find_scene(self._edit_id)
        if s is None and self._angle_pack_scene_id:
            s = find_scene(self._angle_pack_scene_id)
        show = bool(s and s.resolved_still_path())
        self.angle_pack_box.visible = show
        if not show or s is None:
            self._angle_pack_scene_id = None
            return
        self._angle_pack_scene_id = s.id
        hero = s.resolved_still_path()
        b = s.resolved_angle_path("angle_b")
        c = s.resolved_angle_path("angle_c")
        if hero:
            try:
                self.angle_hero_img.src = str(Path(hero).resolve())
            except Exception:
                self.angle_hero_img.src = hero
            self.angle_hero_host.content = self.angle_hero_img
            self.angle_slot_hero_lab.value = "Hero · set"
            self.angle_slot_hero_lab.color = TEXT
        else:
            self.angle_hero_host.content = self.angle_hero_empty
            self.angle_slot_hero_lab.value = "Hero · empty"
            self.angle_slot_hero_lab.color = TEXT_MUTED
        if b:
            try:
                self.angle_b_img.src = str(Path(b).resolve())
            except Exception:
                self.angle_b_img.src = b
            self.angle_b_host.content = self.angle_b_img
            self.angle_slot_b_lab.value = "Left (B) · set"
            self.angle_slot_b_lab.color = TEXT
            self.btn_clear_b.visible = True
            self.btn_gen_left.content = "Replace Left"
        else:
            self.angle_b_host.content = self.angle_b_empty
            self.angle_slot_b_lab.value = "Left (B) · empty"
            self.angle_slot_b_lab.color = TEXT_MUTED
            self.btn_clear_b.visible = False
            self.btn_gen_left.content = "Generate Left"
        if c:
            try:
                self.angle_c_img.src = str(Path(c).resolve())
            except Exception:
                self.angle_c_img.src = c
            self.angle_c_host.content = self.angle_c_img
            self.angle_slot_c_lab.value = "Right (C) · set"
            self.angle_slot_c_lab.color = TEXT
            self.btn_clear_c.visible = True
            self.btn_gen_right.content = "Replace Right"
        else:
            self.angle_c_host.content = self.angle_c_empty
            self.angle_slot_c_lab.value = "Right (C) · empty"
            self.angle_slot_c_lab.color = TEXT_MUTED
            self.btn_clear_c.visible = False
            self.btn_gen_right.content = "Generate Right"
        # Reverse label: show destination slot
        if not b:
            self.btn_gen_reverse.content = "Generate Reverse → B"
        elif not c:
            self.btn_gen_reverse.content = "Generate Reverse → C"
        else:
            self.btn_gen_reverse.content = "Replace Reverse → B"
        has_hero = bool(hero)
        self.btn_gen_left.disabled = not has_hero
        self.btn_gen_right.disabled = not has_hero
        self.btn_gen_reverse.disabled = not has_hero
        self._refresh_angle_cost_sync()

    def _refresh_angle_cost_sync(self) -> None:
        """Est. cost under Generate Left/Right/Reverse — tracks model + quality."""
        try:
            from media_studio.pricing import format_job_cost
            from media_studio.fal.models import resolve_image_edit_model

            lab = self._dd_val(self.angle_model_dd) or preferred_scene_edit_model()
            es = resolve_image_edit_model(lab)
            per = float(getattr(es, "cost_estimate_usd", 0) or 0.04) if es else 0.04
            model = es.label if es else lab
            q = self._dd_val(self.angle_quality_dd)
            unit = f"1 angle · {q}" if q else "1 angle I2I"
            self.angle_cost_text.value = format_job_cost(per, unit=unit, model=model)
        except Exception:
            try:
                self.angle_cost_text.value = "Est. cost: ~$0.04 / angle"
            except Exception:
                pass

    async def _on_angle_model_or_quality(
        self, e: ft.ControlEvent | None = None
    ) -> None:
        try:
            from media_studio.character_store import (
                default_practical_resolution,
                edit_resolution_options,
            )
            from media_studio.flet_theme import dropdown_options

            labs = edit_resolution_options(self.angle_model_dd.value) or ["1K", "2K"]
            self.angle_quality_dd.options = dropdown_options(labs)
            if self.angle_quality_dd.value not in labs:
                self.angle_quality_dd.value = (
                    default_practical_resolution(labs) or labs[0]
                )
        except Exception:
            pass
        self._refresh_angle_cost_sync()
        try:
            self.page.update()
        except Exception:
            pass

    def _target_slot(self, target: str, scene: SavedScene) -> str:
        t = (target or "left").lower()
        if t == "right":
            return "angle_c"
        if t == "reverse":
            if not scene.resolved_angle_path("angle_b"):
                return "angle_b"
            if not scene.resolved_angle_path("angle_c"):
                return "angle_c"
            return "angle_b"  # both filled → replace B
        return "angle_b"  # left

    def _make_clear_angle(self, slot: str):
        async def _click(_e: ft.ControlEvent) -> None:
            sid = self._angle_pack_scene_id or self._edit_id
            if not sid:
                return
            try:
                updated = set_scene_angle(sid, slot, None)
                if updated:
                    self._sync_angle_pack_ui(updated)
                    self.refresh()
                    self._set_status(
                        f"Cleared {SCENE_ANGLE_LABELS.get(slot, slot)} "
                        f"on “{updated.display_name()}”."
                    )
                    try:
                        self.page.update()
                    except Exception:
                        pass
            except Exception as exc:
                self._set_status(str(exc), error=True)

        return _click

    async def _on_tap_angle_pending(self, e: ft.ControlEvent) -> None:
        """Lightbox enlarge of generated angle before Confirm (same as other stills)."""
        if self._angle_pending_path and Path(self._angle_pending_path).is_file():
            lab = SCENE_ANGLE_LABELS.get(self._angle_gen_slot or "", "Angle preview")
            tgt = (self._angle_gen_target or "").title() or "Angle"
            self._open_preview(
                self._angle_pending_path,
                title=f"{tgt} preview · {lab} (click Confirm to save)",
            )
        else:
            self._set_status("Generate an angle first, then click preview to enlarge.")

    async def _regen_angle(self, e: ft.ControlEvent) -> None:
        """Regenerate with same target (Left/Right/Reverse)."""
        tgt = self._angle_gen_target
        if not tgt:
            self._set_status("No previous angle target — use Generate Left/Right/Reverse.")
            return
        await self._run_generate_angle(tgt)

    async def _run_generate_angle(self, target: str) -> None:
        from media_studio.secrets_store import has_fal_key

        sid = self._angle_pack_scene_id or self._edit_id
        if not sid:
            self._set_status("Save the scene first, then generate angles.", error=True)
            return
        scene = find_scene(sid)
        if scene is None:
            self._set_status("Scene not found.", error=True)
            return
        hero = scene.resolved_still_path()
        if not hero:
            self._set_status("Hero still missing — cannot generate angle.", error=True)
            return
        if not has_fal_key():
            self._set_status("FAL API key required — open Settings.", error=True)
            return
        if not self.state.try_busy("scenes"):
            return
        slot = self._target_slot(target, scene)
        existing = scene.resolved_angle_path(slot)
        self._angle_gen_target = target
        self._angle_gen_slot = slot
        self._angle_pending_path = None
        self.btn_angle_confirm.visible = False
        self.btn_angle_regen.visible = False
        self.btn_angle_dismiss.visible = False
        self.angle_pending_img.visible = False
        self.angle_pending_host.content = self.angle_pending_empty
        self.angle_pending_label.visible = False
        label = {"left": "Left", "right": "Right", "reverse": "Reverse"}.get(
            target, target
        )
        slot_lab = SCENE_ANGLE_LABELS.get(slot, slot)
        overwrite = " (will replace existing)" if existing else ""
        self.job_progress.start(f"Generating {label} angle…", self.page)
        self._set_status(
            f"I2I {label} → {slot_lab}{overwrite}. Strong viewpoint change; hero locked."
        )
        for b in (self.btn_gen_left, self.btn_gen_right, self.btn_gen_reverse):
            b.disabled = True
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

            try:
                note = (self.angle_note.value or "").strip()
            except Exception:
                note = ""
            prompt = scene_angle_prompt(
                target,
                base_name=scene.display_name(),
                notes=note,
            )
            model_choice = (
                self._dd_val(self.angle_model_dd) or preferred_scene_edit_model()
            )
            res_opts = edit_resolution_options(model_choice)
            ui_q = self._dd_val(self.angle_quality_dd)
            if ui_q and res_opts and ui_q in res_opts:
                edit_res = ui_q
            else:
                edit_res = default_practical_resolution(res_opts) if res_opts else None
            params_json = edit_params_json_for_resolution(edit_res)
            result = await to_thread_with_job(
                self.state,
                generate,
                prompt,
                model_choice=model_choice,
                image_file=hero,
                extra_image_files=None,
                output_dir=self.state.output_dir,
                on_progress=on_progress,
                scenario="scene-angle",
                parameters_json=params_json,
            )
            path = None
            err = None
            if result.ok:
                path = getattr(result, "primary_image", None) or (
                    result.image_paths[0]
                    if getattr(result, "image_paths", None)
                    else None
                )
                if not path and getattr(result, "path", None):
                    path = result.path
            else:
                err = result.status or "Angle generate failed"

            if path and Path(path).is_file():
                self._angle_pending_path = str(Path(path).resolve())
                self.angle_pending_img.src = self._angle_pending_path
                self.angle_pending_img.visible = True
                self.angle_pending_host.content = self.angle_pending_img
                self.btn_angle_confirm.visible = True
                self.btn_angle_regen.visible = True
                self.btn_angle_dismiss.visible = True
                self.angle_pending_label.visible = True
                self.angle_pending_label.value = (
                    f"Preview (click to enlarge) → Confirm → {slot_lab}"
                    + (" (replaces current)" if existing else "")
                )
                self.btn_angle_confirm.content = f"Confirm → {slot_lab}"
                self.job_progress.finish_ok(
                    f"{label} ready — enlarge preview or Confirm → {slot_lab}",
                    self.page,
                )
                self._set_status(
                    f"{label} ready — click preview to enlarge, Confirm → {slot_lab}, "
                    f"Regenerate, or Dismiss (hero unchanged)."
                )
            else:
                msg = err or "Angle generate failed"
                self.job_progress.finish_error(msg, self.page)
                self._set_status(msg, error=True)
        except Exception as exc:
            msg = f"Angle error: {exc}"
            self.job_progress.finish_error(msg, self.page)
            self._set_status(msg, error=True)
            try:
                print(traceback.format_exc())
            except Exception:
                pass
        finally:
            try:
                self._sync_angle_pack_ui(find_scene(sid))
            except Exception:
                for b in (self.btn_gen_left, self.btn_gen_right, self.btn_gen_reverse):
                    b.disabled = False
            try:
                self.state.clear_busy("scenes")
            except Exception:
                pass
            try:
                self.page.update()
            except Exception:
                pass

    async def _confirm_angle(self, e: ft.ControlEvent) -> None:
        sid = self._angle_pack_scene_id or self._edit_id
        slot = self._angle_gen_slot
        path = self._angle_pending_path
        if not sid or not slot or not path or not Path(path).is_file():
            self._set_status("Generate an angle first.", error=True)
            return
        try:
            updated = set_scene_angle(sid, slot, path)
            if not updated:
                self._set_status("Could not save angle.", error=True)
                return
            self._angle_pending_path = None
            self.angle_pending_img.visible = False
            self.angle_pending_host.content = self.angle_pending_empty
            self.btn_angle_confirm.visible = False
            self.btn_angle_regen.visible = False
            self.btn_angle_dismiss.visible = False
            self.angle_pending_label.visible = False
            self._sync_angle_pack_ui(updated)
            self.refresh()
            self._set_status(
                f"Saved {SCENE_ANGLE_LABELS.get(slot, slot)} on "
                f"“{updated.display_name()}”. Hero unchanged."
            )
            try:
                self.page.update()
            except Exception:
                pass
        except Exception as exc:
            self._set_status(str(exc), error=True)

    async def _dismiss_angle_preview(self, e: ft.ControlEvent) -> None:
        self._angle_pending_path = None
        self._angle_gen_target = None
        self._angle_gen_slot = None
        self.angle_pending_img.visible = False
        self.angle_pending_host.content = self.angle_pending_empty
        self.btn_angle_confirm.visible = False
        self.btn_angle_regen.visible = False
        self.btn_angle_dismiss.visible = False
        self.angle_pending_label.visible = False
        try:
            self.page.update()
        except Exception:
            pass

    def _make_var_chip(self, chip: str):
        """Append a quick transform chip to the variation prompt."""

        def _click(_e: ft.ControlEvent) -> None:
            try:
                cur = (self.var_prompt.value or "").strip()
                bit = chip.strip()
                if not bit:
                    return
                if bit.lower() in cur.lower():
                    return
                self.var_prompt.value = f"{cur}, {bit}".lstrip(", ").strip()
                try:
                    self.page.update()
                except Exception:
                    pass
            except Exception as exc:
                self._set_status(f"Chip failed: {exc}", error=True)

        return _click

    async def _open_scene_placer_blank(self, e: ft.ControlEvent | None = None) -> None:
        """Handoff to Characters · Scene Placer (no scene prefill)."""
        self._handoff_scene_placer()

    def _make_open_scene_placer(self, s: SavedScene):
        async def _click(_e: ft.ControlEvent) -> None:
            self._handoff_scene_placer(scene_id=s.id)

        return _click

    def _handoff_scene_placer(self, *, scene_id: str | None = None) -> None:
        """Switch to Characters tab and open Scene Placer with optional scene."""
        cv = getattr(self.state, "characters_view", None)
        if cv is None or not hasattr(cv, "open_scene_placer"):
            self._set_status("Characters · Scene Placer not available.", error=True)
            return
        try:
            cv.open_scene_placer(scene_id=scene_id)
        except Exception as exc:
            self._set_status(f"Scene Placer open failed: {exc}", error=True)
            traceback.print_exc()
            return
        switch = getattr(self.state, "switch_to_characters", None)
        if switch:
            try:
                switch()
            except Exception:
                pass
        label = "scene prefilled" if scene_id else "pick character + scene"
        self._set_status(f"Opened Scene Placer ({label}).")

    def _make_open_variation(self, scene_id: str):
        """Open I2I variation panel for scene id — must never call New Scene / _reset_form."""

        def _click(_e: ft.ControlEvent) -> None:
            try:
                print(f"[Scenes] Create variation click id={scene_id!r}")
            except Exception:
                pass
            try:
                from media_studio.scene_store import find_scene

                scene = find_scene(scene_id)
                if scene is None:
                    self._set_status(
                        "Scene not found — refresh the list and try again.",
                        error=True,
                    )
                    return
                # Critical: only open variation — never _open_new_scene / _reset_form
                self._open_variation_panel(scene)
            except Exception as exc:
                try:
                    print(traceback.format_exc())
                except Exception:
                    pass
                self._set_status(f"Create variation failed: {exc}", error=True)

        return _click

    def _make_edit(self, s: SavedScene):
        async def _click(_e: ft.ControlEvent) -> None:
            # Leave variation mode without wiping form first, then load this scene
            self._exit_variation_mode(clear_parent=True)
            self._mount_form_workspace()
            self._edit_id = s.id
            self._selected_scene_id = s.id
            self.name_field.value = s.name
            self.notes_field.value = s.notes or ""
            still = s.resolved_still_path()
            if still:
                self._set_still(still, aspect=s.aspect)
            else:
                self._set_still(None)
            self.btn_save.content = "Save changes"
            self.btn_cancel_edit.visible = True
            self.form_heading.value = f"Edit · {s.display_name()}"
            self.t2i_box.visible = True
            self._sync_angle_pack_ui(s)
            ar = s.aspect_badge()
            self.refresh()
            self._set_status(
                f"Editing: {s.display_name()}" + (f" · {ar}" if ar else "")
            )
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
            still = s.resolved_still_path()
            if not still:
                self._set_status("Still missing.", error=True)
                return
            msg = show_in_folder(still)
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

    def _exit_variation_mode(self, *, clear_parent: bool = True) -> None:
        """Leave variation UI without calling New Scene reset."""
        if clear_parent:
            self._var_parent_id = None
            self._var_parent_name = ""
            self._var_parent_path = None
        self._var_pending_path = None
        try:
            self._set_var_result_preview(None)
        except Exception:
            pass
        self.btn_var_save.visible = False
        self.btn_var_gen.content = "Generate"
        self.btn_var_gen.disabled = False
        self._var_panel_shell = None

    def _open_variation_panel(self, s: SavedScene) -> None:
        """
        Open I2I variation editor for parent scene.

        MUST NOT call _reset_form / _open_new_scene. Parent stays selected in the
        library list; left work_host is replaced with a full fixed-height form.
        """
        try:
            title = s.display_name()
            still = None
            try:
                still = s.resolved_still_path()
            except Exception:
                still = None
            if not still:
                raw = (s.still_path or "").strip()
                if raw and Path(raw).is_file():
                    still = str(Path(raw).resolve())

            # Bind parent (library selection) — never New Scene reset
            self._var_parent_id = s.id
            self._var_parent_name = title
            self._var_parent_path = still
            self._var_pending_path = None
            self._selected_scene_id = s.id
            self._variations_expanded.add(s.id)
            self._edit_id = None

            badge = s.aspect_badge()
            self.var_parent_label.value = (
                f"Parent: {title}" + (f" · {badge}" if badge else "")
            )
            self.var_parent_sub.value = (
                f"I2I reference · {Path(still).name}"
                if still
                else "I2I reference · (still missing)"
            )
            self._set_var_parent_thumb(still)

            if still:
                self.var_error.value = ""
                self.var_error.visible = False
                self.btn_var_gen.disabled = False
                status_msg = (
                    f"Create variation under “{title}” — transform, Generate, Confirm."
                )
                status_err = False
            else:
                self.var_error.value = (
                    "Parent still file is missing. Re-upload or re-generate the plate "
                    "on Edit, then try Create variation again. Panel stays open."
                )
                self.var_error.visible = True
                self.btn_var_gen.disabled = True
                status_msg = self.var_error.value
                status_err = True

            self.var_prompt.value = ""
            self.var_name.value = f"{title} – "
            self._set_var_result_preview(None)
            self.btn_var_save.visible = False
            self.btn_var_gen.content = "Generate"

            try:
                self._sync_var_quality_options()
            except Exception as exc:
                print(f"[Scenes] var quality sync: {exc}")
                self._set_status(f"Variation quality setup: {exc}", error=True)
            try:
                self._refresh_var_cost_sync()
            except Exception as exc:
                print(f"[Scenes] var cost sync: {exc}")

            # Replace left work area with full panel (fixed height — no blank ListView)
            self._mount_variation_workspace()
            # List selection highlight only (does not remount form)
            self.refresh()
            self._set_status(status_msg, error=status_err)
            print(
                f"[Scenes] variation panel open parent={title!r} still={still!r} "
                f"mode={self._ui_mode} work_host_n={len(self.work_host.controls)}"
            )
        except Exception as exc:
            try:
                print(traceback.format_exc())
            except Exception:
                pass
            self._set_status(f"Create variation failed: {exc}", error=True)
            # Always try to show something non-blank
            try:
                self.work_host.controls = [
                    ft.Container(
                        content=ft.Column(
                            [
                                ft.Text(
                                    "Create variation failed",
                                    color="#ef9a9a",
                                    weight=ft.FontWeight.W_700,
                                ),
                                ft.Text(str(exc), color=TEXT_MUTED, size=FONT_SM),
                                ft.OutlinedButton(
                                    content="Back to form",
                                    on_click=self._close_variation_panel,
                                ),
                            ],
                            tight=True,
                            spacing=8,
                        ),
                        padding=12,
                        height=200,
                        border=ft.Border.all(1, "#ef9a9a"),
                        border_radius=8,
                    )
                ]
                self.page.update()
            except Exception:
                pass

    async def _close_variation_panel(self, e: ft.ControlEvent | None = None) -> None:
        """Cancel variation — restore form workspace; do not wipe parent library selection."""
        try:
            parent_id = self._var_parent_id
            self._exit_variation_mode(clear_parent=True)
            if parent_id:
                self._selected_scene_id = parent_id
            self._mount_form_workspace()
            self.refresh()
            self._set_status(
                "Variation cancelled — form restored. Parent still selected in library."
            )
            try:
                self.page.update()
            except Exception:
                pass
        except Exception as exc:
            self._set_status(f"Cancel variation failed: {exc}", error=True)

    def _sync_var_quality_options(self) -> None:
        try:
            from media_studio.character_store import (
                default_practical_resolution,
                edit_resolution_options,
            )
            from media_studio.flet_theme import dropdown_options

            labs = edit_resolution_options(self.var_model_dd.value) or ["1K", "2K"]
            self.var_quality_dd.options = dropdown_options(labs)
            if self.var_quality_dd.value not in labs:
                self.var_quality_dd.value = default_practical_resolution(labs) or labs[0]
        except Exception:
            pass

    async def _on_var_model(self, e: ft.ControlEvent | None = None) -> None:
        self._sync_var_quality_options()
        self._refresh_var_cost_sync()
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
            q = (self.var_quality_dd.value or "").strip()
            unit = f"1 edit · {q}" if q else "1 edit"
            self.var_cost_text.value = format_job_cost(per, unit=unit, model=model)
        except Exception:
            try:
                self.var_cost_text.value = estimate_scene_t2i_cost(
                    t2i_label=None, quality=self.var_quality_dd.value or "Standard"
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
        parent_path = self._var_parent_path
        if parent_path and not Path(parent_path).is_file():
            # Retry resolve from store (path repair)
            try:
                from media_studio.scene_store import find_scene as _find

                base = _find(self._var_parent_id)
                if base is not None:
                    parent_path = base.resolved_still_path()
                    self._var_parent_path = parent_path
            except Exception:
                pass
        if not parent_path or not Path(parent_path).is_file():
            self._set_status(
                "Parent still missing — cannot run I2I. Re-upload the base plate "
                "or pick another scene.",
                error=True,
            )
            return
        transform = (self.var_prompt.value or "").strip()
        if not transform:
            self._set_status(
                "Describe the transform (e.g. winter snow, golden hour).",
                error=True,
            )
            return
        if not self.state.try_busy("scenes"):
            return
        self.btn_var_gen.disabled = True
        self.btn_var_save.disabled = True
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
            ui_q = (self.var_quality_dd.value or "").strip()
            if ui_q and res_opts and ui_q in res_opts:
                edit_res = ui_q
            else:
                edit_res = default_practical_resolution(res_opts) if res_opts else None
            params_json = edit_params_json_for_resolution(edit_res)
            result = await to_thread_with_job(
                self.state,
                generate,
                prompt,
                model_choice=model_choice,
                image_file=str(parent_path),
                extra_image_files=None,
                output_dir=self.state.output_dir,
                on_progress=on_progress,
                scenario="scene-variation",
                parameters_json=params_json,
            )
            path = None
            err = None
            if result.ok:
                path = getattr(result, "primary_image", None) or (
                    result.image_paths[0] if getattr(result, "image_paths", None) else None
                )
                if not path and getattr(result, "path", None):
                    path = result.path
            else:
                err = result.status or "Variation failed"

            if path and Path(path).is_file():
                self._var_pending_path = str(Path(path).resolve())
                self._set_var_result_preview(self._var_pending_path)
                self.btn_var_save.visible = True
                self.btn_var_gen.content = "Regenerate"
                # Soft name if empty / trailing dash only
                cur_name = (self.var_name.value or "").strip()
                if (
                    not cur_name
                    or cur_name.endswith("–")
                    or cur_name.endswith("-")
                    or cur_name == f"{self._var_parent_name} –"
                ):
                    short = transform.split(",")[0].strip()[:36].rstrip(" .,;")
                    self.var_name.value = f"{self._var_parent_name} – {short}"
                self.job_progress.finish_ok(
                    "Variation ready — Confirm & save", self.page
                )
                self._set_status(
                    "Variation ready — enlarge preview, Confirm & save, "
                    "Regenerate, or Cancel."
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
            self.btn_var_save.disabled = False
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
        if not name or name.endswith("–") or name.endswith("-"):
            self._set_status(
                "Enter a variation name (e.g. Winter).",
                error=True,
            )
            return
        try:
            from media_studio.scene_store import find_scene as _find

            base = _find(self._var_parent_id)
            ar = (base.aspect if base else "") or detect_still_aspect(
                self._var_pending_path
            )
            notes = (self.var_prompt.value or "").strip()
            if len(notes) > 160:
                notes = notes[:157].rstrip() + "…"
            parent_id = self._var_parent_id
            entry = add_scene(
                name=name,
                still_path=self._var_pending_path,
                notes=notes,
                aspect=ar,
                parent_id=parent_id,
            )
            if parent_id:
                self._variations_expanded.add(parent_id)
                self._selected_scene_id = parent_id
            self._set_status(
                f"Saved variation: {entry.display_name()} under parent Variations."
            )
            # Return to form workspace; keep parent selected / expanded
            self._exit_variation_mode(clear_parent=True)
            self._mount_form_workspace()
            self.refresh()
        except Exception as exc:
            self._set_status(str(exc), error=True)
