"""
Characters tab — local reusable character stills.

Identity pack (Front / Side / Close-up), costume swap, variation, shortcuts.
"""

from __future__ import annotations

import traceback
from pathlib import Path
from typing import TYPE_CHECKING, Any

import flet as ft

from media_studio.character_store import (
    CHAR_AGE_OPTS,
    CHAR_BUILD_OPTS,
    CHAR_FACIAL_HAIR_OPTS,
    CHAR_GENDER_OPTS,
    CHAR_HAIR_COLOR_OPTS,
    CHAR_HAIR_LENGTH_OPTS,
    CHAR_HAIR_STYLE_OPTS,
    CHAR_HEIGHT_OPTS,
    CHAR_SKIN_OPTS,
    DEFAULT_CLOTHES,
    DEFAULT_VARIATION_MODEL,
    HELPER_NONE,
    IDENTITY_SLOTS,
    MAX_STILLS_PER_CHARACTER,
    SLOT_LABELS,
    SLOT_SHORT,
    T2I_SEQ_ORDER,
    VARIATION_PROMPT,
    CharacterHasChildrenError,
    SavedCharacter,
    add_character,
    add_character_angle,
    assemble_character_t2i_description,
    character_t2i_i2i_prompt_for_slot,
    character_t2i_prompt_for_slot,
    costume_prompt_for_slot,
    default_practical_resolution,
    default_practical_t2i_resolution,
    delete_character,
    edit_params_json_for_resolution,
    edit_resolution_options,
    estimate_bg_remove_cost,
    estimate_costume_swap_cost,
    estimate_profile_cost,
    estimate_t2i_character_cost,
    list_base_characters,
    list_costume_children,
    load_characters,
    multi_ref_image_edit_labels,
    preferred_costume_model,
    profile_prompt_for_slot,
    run_background_remove,
    set_character_locked,
    set_character_slot,
    short_outfit_label,
    t2i_character_model_labels,
    t2i_resolution_options,
    update_character,
)
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
    section_title,
    styled_dropdown,
)

if TYPE_CHECKING:
    from media_studio.flet_app import StudioState

_THUMB = 72
_SLOT_THUMB = 88
_RESULT_THUMB = 120


class CharactersView:
    """Save and reuse character stills (local store only)."""

    def __init__(self, page: ft.Page, state: StudioState) -> None:
        self.page = page
        self.state = state
        self._still_path: str | None = None
        self._editing_id: str | None = None
        # Edit-time identity pack: slot -> path (may be empty string)
        self._edit_identity: dict[str, str] = {s: "" for s in IDENTITY_SLOTS}

        self._variation_path: str | None = None
        self._variation_source_id: str | None = None

        # Costume swap session
        self._costume_char_id: str | None = None
        self._costume_char_name: str = ""
        self._costume_outfit: str = ""
        self._costume_results: dict[str, str] = {}  # slot -> path
        self._costume_errors: dict[str, str] = {}  # slot -> error message
        self._costume_refs: list[str] = []  # identity stills for regen
        self._costume_model: str = preferred_costume_model()
        self._costume_busy = False
        self._costumes_expanded: set[str] = set()  # parent ids with Costumes open
        self._create_mode = False  # New character (upload) vs edit existing

        # Background remove preview (confirm before overwrite)
        self._bg_pending_path: str | None = None
        self._bg_pending_slot: str | None = None
        self._bg_pending_char_id: str | None = None
        self._bg_batch_results: dict[str, str] = {}

        # Generate missing profile session
        self._profile_busy = False
        self._profile_pending_path: str | None = None
        self._profile_pending_slot: str | None = None
        self._profile_char_id: str | None = None

        # Lightbox
        self._lightbox_dialog: ft.AlertDialog | None = None
        self._lightbox_img: ft.Image | None = None
        self._lightbox_title: ft.Text | None = None

        # ----- Add form -----
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
            "No still selected — use slot Upload buttons or pick a target slot below",
            size=FONT_SM,
            color=TEXT_MUTED,
            max_lines=3,
        )
        self.upload_slot_dd = styled_dropdown(
            label_text="Upload / strip target slot",
            options=[SLOT_SHORT[s] for s in IDENTITY_SLOTS],
            value=SLOT_SHORT["front"],
            expand=True,
        )
        self.btn_upload = ft.OutlinedButton(
            content="Upload into target slot",
            icon=ft.Icons.IMAGE,
            on_click=self._pick_still,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
        )
        self.btn_clear_still = ft.TextButton(
            content="Clear target slot",
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
        )

        self.name_field = ft.TextField(
            label="Name (required)",
            hint_text="e.g. Camera Man · Sarah – blue blazer",
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
            hint_text="e.g. realtor hero · outdoor listing",
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

        # Identity pack (edit mode)
        self.pack_label = ft.Text(
            "Identity pack — Front / Side / Close-up",
            size=FONT_SM,
            color=TEXT_MUTED,
            visible=False,
        )
        self.pack_row = ft.Row(spacing=10, wrap=True, visible=False)
        self._pack_slot_ui: dict[str, dict[str, Any]] = {}
        self._build_pack_slot_ui()

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
        self.status = ft.Text("", size=FONT_SM, color=TEXT_MUTED, max_lines=5)
        self.job_progress = JobProgress()

        # ----- Variation result (kept) -----
        self.var_preview = ft.Image(
            src="", width=100, height=100, fit=ft.BoxFit.COVER, border_radius=6, visible=False
        )
        self.var_label = ft.Text("", size=FONT_SM, color=TEXT_MUTED, visible=False, max_lines=2)
        self.btn_var_new = ft.FilledButton(
            content="Save as new character",
            on_click=self._variation_save_new,
            style=ft.ButtonStyle(bgcolor=ACCENT_BRIGHT, color=TEXT),
            height=36,
            visible=False,
        )
        self.btn_var_angle = ft.OutlinedButton(
            content="Add to empty slot",
            on_click=self._variation_add_angle,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
            height=36,
            visible=False,
        )
        self.btn_var_replace = ft.OutlinedButton(
            content="Replace Front",
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
                    ft.Text("Variation result", size=FONT_SM, color=TEXT, weight=ft.FontWeight.W_600),
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

        # ----- Costume swap panel -----
        self.costume_title = ft.Text(
            "Costume swap",
            size=FONT_SM,
            color=TEXT,
            weight=ft.FontWeight.W_700,
        )
        self.costume_char_label = ft.Text("", size=FONT_SM, color=TEXT_MUTED)
        _cos_models = multi_ref_image_edit_labels()
        from media_studio.fal.models import resolve_image_edit_model as _resolve_ie

        _cos_spec = _resolve_ie(preferred_costume_model())
        _cos_default = (
            _cos_spec.label
            if _cos_spec and _cos_spec.label in _cos_models
            else (_cos_models[0] if _cos_models else "Image · Flux 2 Pro (edit)")
        )
        self.costume_model_dd = styled_dropdown(
            label_text="Model (multi-ref)",
            options=_cos_models,
            value=_cos_default,
            on_select=self._on_costume_model_change,
            expand=True,
        )
        _cos_res = edit_resolution_options(_cos_default)
        self.costume_res_dd = styled_dropdown(
            label_text="Resolution",
            options=_cos_res or ["auto"],
            value=default_practical_resolution(_cos_res) if _cos_res else "auto",
            on_select=self._on_costume_model_change,
            expand=True,
        )
        self.costume_res_dd.visible = bool(_cos_res)
        self.costume_prompt = ft.TextField(
            label="New wardrobe / look",
            hint_text='e.g. navy suit and tie · astronaut suit · "listing open house" blazer',
            value="",
            dense=True,
            filled=True,
            fill_color=PANEL,
            border_color=BORDER,
            color=TEXT,
            text_size=FONT_SM,
            multiline=True,
            min_lines=2,
            max_lines=3,
            on_change=self._on_costume_prompt_change,
        )
        self.btn_costume_enhance = make_enhance_button(on_click=self._on_costume_enhance)
        self.costume_cost = ft.Text("Est. cost: —", size=FONT_SM, color=TEXT_MUTED)
        self.costume_progress_ring = ft.ProgressRing(
            width=28, height=28, stroke_width=3, color=ACCENT, visible=False
        )
        self.costume_busy_row = ft.Row(
            [
                self.costume_progress_ring,
                ft.Text(
                    "Generating costume…",
                    size=FONT_SM,
                    color=ACCENT,
                    weight=ft.FontWeight.W_600,
                ),
            ],
            spacing=10,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            visible=False,
        )
        self.costume_errors_text = ft.Text(
            "",
            size=FONT_SM,
            color="#e57373",
            max_lines=6,
            visible=False,
            selectable=True,
        )
        self.btn_costume_generate = ft.FilledButton(
            content="Generate costume swap",
            on_click=self._costume_generate_all,
            style=ft.ButtonStyle(bgcolor=ACCENT_BRIGHT, color=TEXT),
            height=40,
        )
        self.btn_costume_cancel = ft.TextButton(
            content="Close",
            on_click=self._costume_close,
            style=ft.ButtonStyle(color=TEXT_MUTED),
        )
        self.costume_results_row = ft.Row(spacing=12, wrap=True)
        self.costume_variant_name = ft.TextField(
            label="Costume name (shown in list)",
            hint_text="e.g. Red Dress · Navy Suit",
            value="",
            dense=True,
            filled=True,
            fill_color=PANEL,
            border_color=BORDER,
            color=TEXT,
            text_size=FONT_SM,
            visible=False,
        )
        self.btn_costume_save_new = ft.FilledButton(
            content="Save as costume variant",
            on_click=self._costume_save_new,
            style=ft.ButtonStyle(bgcolor=ACCENT_BRIGHT, color=TEXT),
            height=36,
            visible=False,
        )
        self.btn_costume_replace = ft.OutlinedButton(
            content="Replace current angles…",
            on_click=self._costume_replace_confirm,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
            height=36,
            visible=False,
        )
        self.btn_costume_discard = ft.TextButton(
            content="Discard results",
            on_click=self._costume_discard_results,
            style=ft.ButtonStyle(color=TEXT_MUTED),
            visible=False,
        )
        self.costume_box = ft.Container(
            content=ft.Column(
                [
                    self.costume_title,
                    self.costume_char_label,
                    ft.Text(
                        "Uses all identity stills as multi-ref. One generation per filled "
                        "slot (Front / Side / Close-up). Pure black clean plate. "
                        "Regenerate re-runs only that angle.",
                        size=FONT_SM,
                        color=TEXT_MUTED,
                    ),
                    ft.Row([self.costume_model_dd], spacing=0),
                    ft.Row([self.costume_res_dd], spacing=0),
                    self.costume_prompt,
                    ft.Row(
                        [
                            self.btn_costume_enhance,
                            self.btn_costume_generate,
                            self.btn_costume_cancel,
                        ],
                        spacing=8,
                        wrap=True,
                    ),
                    self.costume_cost,
                    self.costume_busy_row,
                    self.costume_errors_text,
                    self.costume_results_row,
                    self.costume_variant_name,
                    ft.Row(
                        [
                            self.btn_costume_save_new,
                            self.btn_costume_replace,
                            self.btn_costume_discard,
                        ],
                        spacing=6,
                        wrap=True,
                    ),
                ],
                spacing=8,
                tight=True,
            ),
            bgcolor=PANEL_ELEVATED,
            border=ft.Border.all(1, ACCENT),
            border_radius=8,
            padding=12,
            visible=False,
        )

        # ----- New character entry -----
        self.btn_new_character = ft.FilledButton(
            content="New character",
            icon=ft.Icons.PERSON_ADD_ALT_1,
            on_click=self._open_new_character,
            style=ft.ButtonStyle(bgcolor=ACCENT_BRIGHT, color=TEXT),
            height=42,
        )
        self.btn_new_upload = ft.OutlinedButton(
            content="1 · Upload photos (1–3 stills)",
            icon=ft.Icons.UPLOAD_FILE,
            on_click=self._start_new_upload,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
            height=40,
        )
        self.btn_new_generate = ft.OutlinedButton(
            content="2 · Generate character (T2I)",
            icon=ft.Icons.AUTO_AWESOME,
            on_click=self._start_new_generate,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
            height=40,
        )
        self.btn_new_cancel = ft.TextButton(
            content="Cancel",
            on_click=self._cancel_new_character,
            style=ft.ButtonStyle(color=TEXT_MUTED),
        )
        self.new_char_choice = ft.Container(
            content=ft.Column(
                [
                    ft.Text(
                        "Create a new character",
                        size=FONT_SM,
                        color=TEXT,
                        weight=ft.FontWeight.W_700,
                    ),
                    ft.Text(
                        "Upload 1–3 stills for Front / Side / Close-up, or start a "
                        "text-to-image character (helpers + prompt shell).",
                        size=FONT_SM,
                        color=TEXT_MUTED,
                    ),
                    self.btn_new_upload,
                    self.btn_new_generate,
                    self.btn_new_cancel,
                ],
                spacing=8,
                tight=True,
            ),
            bgcolor=PANEL_ELEVATED,
            border=ft.Border.all(1, ACCENT),
            border_radius=8,
            padding=12,
            visible=False,
        )
        # ----- T2I full character builder -----
        self._t2i_seq_confirmed: dict[str, str] = {}
        self._t2i_pending_path: str | None = None
        self._t2i_pending_slot: str | None = None
        self._t2i_busy = False
        self._t2i_model_label = "Flux 2 Pro (T2I)"

        def _h(label: str, opts: tuple[str, ...]) -> ft.Dropdown:
            return styled_dropdown(
                label_text=label,
                options=list(opts),
                value=opts[0],
                expand=True,
            )

        self.t2i_gender = _h("Gender", CHAR_GENDER_OPTS)
        self.t2i_age = _h("Age range", CHAR_AGE_OPTS)
        self.t2i_build = _h("Build", CHAR_BUILD_OPTS)
        self.t2i_height = _h("Height feel", CHAR_HEIGHT_OPTS)
        self.t2i_hair_color = _h("Hair color", CHAR_HAIR_COLOR_OPTS)
        self.t2i_hair_length = _h("Hair length", CHAR_HAIR_LENGTH_OPTS)
        self.t2i_hair_style = _h("Hair style", CHAR_HAIR_STYLE_OPTS)
        self.t2i_facial_hair = _h("Facial hair", CHAR_FACIAL_HAIR_OPTS)
        self.t2i_skin = _h("Skin / appearance", CHAR_SKIN_OPTS)
        self.t2i_skin_free = ft.TextField(
            label="Skin / appearance free text (optional)",
            hint_text="e.g. freckles, warm olive tone",
            value="",
            dense=True,
            filled=True,
            fill_color=PANEL,
            border_color=BORDER,
            color=TEXT,
            text_size=FONT_SM,
        )
        self.t2i_clothes = ft.TextField(
            label="Default clothes",
            value=DEFAULT_CLOTHES,
            dense=True,
            filled=True,
            fill_color=PANEL,
            border_color=BORDER,
            color=TEXT,
            text_size=FONT_SM,
            hint_text="Simple fitted neutral — costume swap later",
        )
        self.t2i_prompt = ft.TextField(
            label="Character description (main)",
            hint_text="e.g. professional realtor, confident smile, approachable",
            value="",
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
        self.t2i_insights = ft.TextField(
            label="Optional Enhance Insights (Enhance only — not raw Generate)",
            hint_text='e.g. "real estate agent you\'d trust" · warm personality · listing hero',
            value="",
            dense=True,
            filled=True,
            fill_color=PANEL,
            border_color=BORDER,
            color=TEXT,
            text_size=FONT_SM,
            multiline=True,
            min_lines=2,
            max_lines=3,
        )
        _t2i_labs = t2i_character_model_labels()
        self.t2i_model_dd = styled_dropdown(
            label_text="T2I model (Close-up plate)",
            options=_t2i_labs,
            value=_t2i_labs[0] if _t2i_labs else "Flux 2 Pro (T2I)",
            on_select=self._on_t2i_model_change,
            expand=True,
        )
        _t2i_res0 = t2i_resolution_options(_t2i_labs[0] if _t2i_labs else None)
        self.t2i_res_dd = styled_dropdown(
            label_text="Resolution / quality",
            options=_t2i_res0 or ["1:1 square HD"],
            value=default_practical_t2i_resolution(_t2i_res0),
            on_select=self._on_t2i_model_change,
            expand=True,
        )
        self.t2i_cost = ft.Text(
            estimate_t2i_character_cost(
                n_remaining=3,
                t2i_label=_t2i_labs[0] if _t2i_labs else None,
                resolution=default_practical_t2i_resolution(_t2i_res0),
            ),
            size=FONT_SM,
            color=TEXT_MUTED,
        )
        self.btn_t2i_enhance = make_enhance_button(
            on_click=self._on_t2i_enhance,
            tooltip="Rewrite helpers + description + insights into a strong T2I prompt",
        )
        self.btn_t2i_gen_next = ft.FilledButton(
            content="Generate next (Front first)",
            on_click=self._t2i_generate_next,
            style=ft.ButtonStyle(bgcolor=ACCENT_BRIGHT, color=TEXT),
            height=40,
        )
        self.t2i_progress_ring = ft.ProgressRing(
            width=28, height=28, stroke_width=3, color=ACCENT, visible=False
        )
        self.t2i_busy_row = ft.Row(
            [
                self.t2i_progress_ring,
                ft.Text(
                    "Generating…",
                    size=FONT_SM,
                    color=ACCENT,
                    weight=ft.FontWeight.W_600,
                ),
            ],
            spacing=10,
            visible=False,
        )
        self.t2i_seq_status = ft.Text(
            "Guided path: Front → Side → Close-up (identity lock). Confirm each plate.",
            size=FONT_SM,
            color=TEXT_MUTED,
            max_lines=3,
        )
        self.t2i_preview_img = ft.Image(
            src="", width=140, height=140, fit=ft.BoxFit.CONTAIN, border_radius=6, visible=False
        )
        self.t2i_preview_tap = ft.GestureDetector(
            content=self.t2i_preview_img,
            on_tap=self._on_t2i_preview_tap,
            visible=False,
        )
        self.t2i_preview_label = ft.Text("", size=FONT_SM, color=TEXT_MUTED, max_lines=3)
        self.btn_t2i_confirm = ft.FilledButton(
            content="Confirm plate",
            on_click=self._t2i_confirm_plate,
            style=ft.ButtonStyle(bgcolor=ACCENT_BRIGHT, color=TEXT),
            height=36,
            visible=False,
        )
        self.btn_t2i_regen = ft.OutlinedButton(
            content="Regenerate",
            on_click=self._t2i_regenerate_plate,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
            height=36,
            visible=False,
        )
        self.btn_t2i_dismiss = ft.TextButton(
            content="Dismiss preview",
            on_click=self._t2i_dismiss_preview,
            style=ft.ButtonStyle(color=TEXT_MUTED),
            visible=False,
        )
        self.btn_t2i_save = ft.FilledButton(
            content="Save character from plates",
            on_click=self._t2i_save_character,
            style=ft.ButtonStyle(bgcolor=ACCENT_BRIGHT, color=TEXT),
            height=40,
            visible=False,
        )
        self.t2i_name = ft.TextField(
            label="Name (required to save)",
            value="",
            dense=True,
            filled=True,
            fill_color=PANEL,
            border_color=BORDER,
            color=TEXT,
            text_size=FONT_SM,
        )
        self.t2i_notes = ft.TextField(
            label="Notes (optional)",
            value="",
            dense=True,
            filled=True,
            fill_color=PANEL,
            border_color=BORDER,
            color=TEXT,
            text_size=FONT_SM,
        )
        self.t2i_box = ft.Container(
            content=ft.Column(
                [
                    ft.Text(
                        "Generate character (T2I builder)",
                        size=FONT_SM,
                        color=TEXT,
                        weight=ft.FontWeight.W_700,
                    ),
                    ft.Text(
                        "Helpers are optional (None / skip). Sequential: Front first "
                        "(full-body), then Side, then Close-up with identity lock. "
                        "Pure black clean plate.",
                        size=FONT_SM,
                        color=TEXT_MUTED,
                    ),
                    ft.Row([self.t2i_gender, self.t2i_age], spacing=8),
                    ft.Row([self.t2i_build, self.t2i_height], spacing=8),
                    ft.Row(
                        [self.t2i_hair_color, self.t2i_hair_length, self.t2i_hair_style],
                        spacing=8,
                    ),
                    ft.Row([self.t2i_facial_hair, self.t2i_skin], spacing=8),
                    self.t2i_skin_free,
                    self.t2i_clothes,
                    self.t2i_prompt,
                    self.t2i_insights,
                    ft.Row([self.t2i_model_dd], spacing=0),
                    ft.Row([self.t2i_res_dd], spacing=0),
                    self.t2i_cost,
                    ft.Row(
                        [
                            self.btn_t2i_enhance,
                            self.btn_t2i_gen_next,
                            self.btn_new_cancel,
                        ],
                        spacing=8,
                        wrap=True,
                    ),
                    self.t2i_seq_status,
                    self.t2i_busy_row,
                    self.t2i_preview_label,
                    self.t2i_preview_tap,
                    ft.Row(
                        [
                            self.btn_t2i_confirm,
                            self.btn_t2i_regen,
                            self.btn_t2i_dismiss,
                        ],
                        spacing=6,
                        wrap=True,
                    ),
                    self.t2i_name,
                    self.t2i_notes,
                    self.btn_t2i_save,
                ],
                spacing=8,
                tight=True,
            ),
            bgcolor=PANEL_ELEVATED,
            border=ft.Border.all(1, ACCENT),
            border_radius=8,
            padding=12,
            visible=False,
        )

        # Background remove UI
        self.bg_cost_label = ft.Text(
            estimate_bg_remove_cost(1),
            size=FONT_SM,
            color=TEXT_MUTED,
            visible=False,
        )
        self.btn_bg_all = ft.OutlinedButton(
            content="Remove background on all angles",
            on_click=self._bg_remove_all,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
            visible=False,
            height=36,
        )
        self.bg_preview_img = ft.Image(
            src="",
            width=140,
            height=140,
            fit=ft.BoxFit.CONTAIN,
            border_radius=6,
            visible=False,
        )
        self.bg_preview_tap = ft.GestureDetector(
            content=self.bg_preview_img,
            on_tap=self._on_bg_preview_tap,
            visible=False,
        )
        self.bg_preview_label = ft.Text("", size=FONT_SM, color=TEXT_MUTED, max_lines=3)
        self.bg_progress_ring = ft.ProgressRing(
            width=28, height=28, stroke_width=3, color=ACCENT, visible=False
        )
        self.bg_busy_row = ft.Row(
            [
                self.bg_progress_ring,
                ft.Text(
                    "Removing background…",
                    size=FONT_SM,
                    color=ACCENT,
                    weight=ft.FontWeight.W_600,
                ),
            ],
            spacing=10,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            visible=False,
        )
        self.btn_bg_confirm = ft.FilledButton(
            content="Confirm replace",
            on_click=self._bg_confirm,
            style=ft.ButtonStyle(bgcolor=ACCENT_BRIGHT, color=TEXT),
            height=36,
            visible=False,
        )
        self.btn_bg_dismiss = ft.TextButton(
            content="Dismiss",
            on_click=self._bg_dismiss,
            style=ft.ButtonStyle(color=TEXT_MUTED),
            visible=False,
        )
        self._bg_busy = False
        self._bg_busy_slot: str | None = None
        self.bg_preview_hint = ft.Text(
            "Click preview to enlarge",
            size=11,
            color=TEXT_MUTED,
            visible=False,
        )
        self.bg_preview_box = ft.Container(
            content=ft.Column(
                [
                    ft.Text(
                        "Background remove",
                        size=FONT_SM,
                        color=TEXT,
                        weight=ft.FontWeight.W_600,
                    ),
                    self.bg_busy_row,
                    self.bg_preview_label,
                    self.bg_preview_tap,
                    self.bg_preview_hint,
                    ft.Row([self.btn_bg_confirm, self.btn_bg_dismiss], spacing=8),
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

        # ----- Generate missing profile panel -----
        _prof_models = multi_ref_image_edit_labels()
        _prof_default = preferred_costume_model()
        from media_studio.fal.models import resolve_image_edit_model

        _prof_spec = resolve_image_edit_model(_prof_default)
        _prof_default_label = (
            _prof_spec.label
            if _prof_spec and _prof_spec.label in _prof_models
            else (_prof_models[0] if _prof_models else "Image · Flux 2 Pro (edit)")
        )
        self.profile_target_dd = styled_dropdown(
            label_text="Target slot",
            options=[SLOT_SHORT[s] for s in IDENTITY_SLOTS],
            value=SLOT_SHORT["front"],
            on_select=self._on_profile_controls_change,
            expand=True,
        )
        self.profile_model_dd = styled_dropdown(
            label_text="Model (multi-ref)",
            options=_prof_models,
            value=_prof_default_label,
            on_select=self._on_profile_controls_change,
            expand=True,
        )
        _prof_res = edit_resolution_options(_prof_default_label)
        self.profile_res_dd = styled_dropdown(
            label_text="Resolution",
            options=_prof_res or ["auto"],
            value=default_practical_resolution(_prof_res) if _prof_res else "auto",
            on_select=self._on_profile_controls_change,
            expand=True,
        )
        self.profile_res_dd.visible = bool(_prof_res)
        self.profile_note = ft.TextField(
            label="Optional note (usually leave blank)",
            hint_text="e.g. outdoor light · same wardrobe as Front",
            value="",
            dense=True,
            filled=True,
            fill_color=PANEL,
            border_color=BORDER,
            color=TEXT,
            text_size=FONT_SM,
            max_lines=2,
            multiline=True,
        )
        self.btn_profile_enhance = make_enhance_button(
            on_click=self._on_profile_enhance,
            tooltip="Rewrite optional note for the profile model (Grok)",
        )
        self.profile_cost = ft.Text(
            estimate_profile_cost(),
            size=FONT_SM,
            color=TEXT_MUTED,
        )
        self.btn_profile_generate = ft.FilledButton(
            content="Generate profile",
            on_click=self._profile_generate,
            style=ft.ButtonStyle(bgcolor=ACCENT_BRIGHT, color=TEXT),
            height=40,
        )
        self.btn_profile_close = ft.TextButton(
            content="Close",
            on_click=self._profile_close,
            style=ft.ButtonStyle(color=TEXT_MUTED),
        )
        self.profile_progress_ring = ft.ProgressRing(
            width=28, height=28, stroke_width=3, color=ACCENT, visible=False
        )
        self.profile_busy_row = ft.Row(
            [
                self.profile_progress_ring,
                ft.Text(
                    "Generating profile…",
                    size=FONT_SM,
                    color=ACCENT,
                    weight=ft.FontWeight.W_600,
                ),
            ],
            spacing=10,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            visible=False,
        )
        self.profile_preview_img = ft.Image(
            src="",
            width=140,
            height=140,
            fit=ft.BoxFit.CONTAIN,
            border_radius=6,
            visible=False,
        )
        self.profile_preview_tap = ft.GestureDetector(
            content=self.profile_preview_img,
            on_tap=self._on_profile_preview_tap,
            visible=False,
        )
        self.profile_preview_label = ft.Text(
            "", size=FONT_SM, color=TEXT_MUTED, max_lines=3
        )
        self.profile_preview_hint = ft.Text(
            "Click preview to enlarge",
            size=11,
            color=TEXT_MUTED,
            visible=False,
        )
        self.btn_profile_confirm = ft.FilledButton(
            content="Confirm fill slot",
            on_click=self._profile_confirm,
            style=ft.ButtonStyle(bgcolor=ACCENT_BRIGHT, color=TEXT),
            height=36,
            visible=False,
        )
        self.btn_profile_regen = ft.OutlinedButton(
            content="Regenerate",
            on_click=self._profile_regenerate,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
            height=36,
            visible=False,
        )
        self.btn_profile_dismiss = ft.TextButton(
            content="Dismiss",
            on_click=self._profile_dismiss_result,
            style=ft.ButtonStyle(color=TEXT_MUTED),
            visible=False,
        )
        self.profile_box = ft.Container(
            content=ft.Column(
                [
                    ft.Text(
                        "Generate missing profile",
                        size=FONT_SM,
                        color=TEXT,
                        weight=ft.FontWeight.W_700,
                    ),
                    ft.Text(
                        "Fill Front / Side / Close-up from existing identity stills "
                        "(multi-ref I2I). Does not change wardrobe — use Costume swap for outfits.",
                        size=FONT_SM,
                        color=TEXT_MUTED,
                    ),
                    ft.Row([self.profile_target_dd], spacing=0),
                    ft.Row([self.profile_model_dd], spacing=0),
                    ft.Row([self.profile_res_dd], spacing=0),
                    self.profile_note,
                    ft.Row(
                        [
                            self.btn_profile_enhance,
                            self.btn_profile_generate,
                            self.btn_profile_close,
                        ],
                        spacing=8,
                        wrap=True,
                    ),
                    self.profile_cost,
                    self.profile_busy_row,
                    self.profile_preview_label,
                    self.profile_preview_tap,
                    self.profile_preview_hint,
                    ft.Row(
                        [
                            self.btn_profile_confirm,
                            self.btn_profile_regen,
                            self.btn_profile_dismiss,
                        ],
                        spacing=6,
                        wrap=True,
                    ),
                ],
                spacing=8,
                tight=True,
            ),
            bgcolor=PANEL_ELEVATED,
            border=ft.Border.all(1, ACCENT),
            border_radius=8,
            padding=12,
            visible=False,
        )

        self.empty_state = ft.Column(
            [
                ft.Text(
                    "No characters yet.",
                    size=FONT_SM,
                    color=TEXT,
                    weight=ft.FontWeight.W_600,
                ),
                ft.Text(
                    "Click New character to upload 1–3 stills (Front / Side / Close-up) "
                    "or start a T2I character description. Save realtor or talent stills "
                    "for one-click use in Motion Sync, Director, and more.",
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

        self.refresh()

    def _build_pack_slot_ui(self) -> None:
        self.pack_row.controls.clear()
        self._pack_slot_ui.clear()
        for slot in IDENTITY_SLOTS:
            img = ft.Image(
                src="",
                width=_SLOT_THUMB,
                height=_SLOT_THUMB,
                fit=ft.BoxFit.COVER,
                border_radius=6,
                visible=False,
            )
            empty = ft.Container(
                width=_SLOT_THUMB,
                height=_SLOT_THUMB,
                bgcolor=PANEL,
                border=ft.Border.all(1, BORDER),
                border_radius=6,
                alignment=ft.Alignment.CENTER,
                content=ft.Icon(ft.Icons.ADD_A_PHOTO_OUTLINED, size=22, color=TEXT_MUTED),
            )
            title = ft.Text(SLOT_SHORT[slot], size=FONT_SM, color=TEXT, weight=ft.FontWeight.W_600)
            hint = ft.Text(SLOT_LABELS[slot], size=11, color=TEXT_MUTED, max_lines=2)
            btn_up = ft.OutlinedButton(
                content="Upload",
                on_click=self._make_pack_upload(slot),
                style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
                height=32,
            )
            btn_clr = ft.TextButton(
                content="Clear",
                on_click=self._make_pack_clear(slot),
                style=ft.ButtonStyle(color=TEXT_MUTED),
                height=32,
            )
            btn_bg = ft.TextButton(
                content="Remove BG",
                on_click=self._make_pack_bg_remove(slot),
                style=ft.ButtonStyle(color=ACCENT),
                height=32,
                tooltip="Remove background (shows cost; confirm before replace)",
            )
            btn_gen = ft.TextButton(
                content="Generate profile",
                on_click=self._make_open_profile(slot),
                style=ft.ButtonStyle(color=ACCENT),
                height=32,
                tooltip="Fill this angle from existing identity stills (multi-ref I2I)",
            )
            thumb_btn = ft.GestureDetector(
                content=ft.Stack([empty, img], width=_SLOT_THUMB, height=_SLOT_THUMB),
                on_tap=self._make_preview_tap_slot(slot),
            )
            box = ft.Container(
                content=ft.Column(
                    [
                        title,
                        hint,
                        thumb_btn,
                        ft.Row([btn_up, btn_clr], spacing=2, wrap=True),
                        btn_bg,
                        btn_gen,
                    ],
                    spacing=4,
                    tight=True,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                border=ft.Border.all(1, BORDER),
                border_radius=8,
                padding=8,
                width=_SLOT_THUMB + 64,
            )
            self._pack_slot_ui[slot] = {
                "img": img,
                "empty": empty,
                "box": box,
                "btn_clear": btn_clr,
                "btn_bg": btn_bg,
                "btn_gen": btn_gen,
            }
            self.pack_row.controls.append(box)

    # ----- layout -----

    def build(self) -> ft.Control:
        from media_studio.flet_layout import make_split_workspace
        from media_studio.flet_theme import RAIL_WIDTH

        left = [
            section_title("Characters"),
            ft.Text(
                "Identity pack: Front / Side / Close-up. Costume swap changes wardrobe "
                "across filled angles (multi-ref I2I). Local store only.",
                size=FONT_SM,
                color=TEXT_MUTED,
            ),
            self.btn_new_character,
            self.new_char_choice,
            self.t2i_box,
            ft.Divider(height=1, color=BORDER),
            label("Add / edit", muted=True),
            ft.Stack([self.preview_empty, self.preview], width=140, height=140),
            self.still_label,
            ft.Row([self.upload_slot_dd], spacing=0),
            ft.Row(
                [self.btn_upload, self.btn_clear_still, self.btn_library],
                spacing=6,
                wrap=True,
            ),
            self.prev_strip.root,
            self.resolve_strip.root,
            self.name_field,
            self.notes_field,
            self.pack_label,
            self.pack_row,
            self.btn_bg_all,
            self.bg_cost_label,
            self.bg_preview_box,
            self.profile_box,
            ft.Row([self.btn_save, self.btn_cancel_edit], spacing=8),
            self.costume_box,
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
        return make_split_workspace(left, right, left_width=max(RAIL_WIDTH, 440))

    # ----- public -----

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
        self._editing_id = None
        self._edit_identity = {s: "" for s in IDENTITY_SLOTS}
        self._sync_pack_ui()
        self.btn_save.content = "Save character"
        self.btn_cancel_edit.visible = False
        self.name_field.value = (suggested_name or "").strip()
        self.notes_field.value = (notes or "").strip()
        self._set_still(str(p.resolve()))
        self._set_status(f"Still ready — add a name and Save (Front): {p.name}")
        return True

    # ----- form helpers -----

    def _set_status(self, msg: str, *, error: bool = False) -> None:
        self.status.value = msg
        self.status.color = "#e57373" if error else TEXT_MUTED
        try:
            self.page.update()
        except Exception:
            pass

    async def _pick_still(self, e: ft.ControlEvent) -> None:
        slot = self._upload_target_slot()
        short = SLOT_SHORT.get(slot, slot)
        try:
            files = await pick_image(
                self.page, dialog_title=f"Character still → {short}"
            )
        except Exception as exc:
            self._set_status(f"Picker error: {exc}", error=True)
            return
        if not files or not files[0].path:
            return
        self._set_still(files[0].path, slot=slot)

    def _upload_target_slot(self) -> str:
        raw = (self.upload_slot_dd.value or "Front").strip().lower()
        for s in IDENTITY_SLOTS:
            if SLOT_SHORT[s].lower() == raw or s == raw:
                return s
        if "side" in raw or "profile" in raw:
            return "side"
        if "close" in raw or "face" in raw:
            return "closeup"
        return "front"

    def _clear_still(self, e: ft.ControlEvent | None = None) -> None:
        slot = self._upload_target_slot()
        if self._editing_id or self._create_mode:
            self._edit_identity[slot] = ""
            # Preview shows primary available
            prim = next(
                (
                    self._edit_identity[s]
                    for s in IDENTITY_SLOTS
                    if self._edit_identity.get(s)
                ),
                None,
            )
            if prim and Path(prim).is_file():
                self._still_path = prim
                self.preview.src = prim
                self.preview.visible = True
                self.preview_empty.visible = False
                self.still_label.value = f"Preview: {Path(prim).name}"
            else:
                self._still_path = None
                self.preview.src = ""
                self.preview.visible = False
                self.preview_empty.visible = True
                self.still_label.value = (
                    "No still selected — upload into any slot (Front / Side / Close-up)"
                )
            self._sync_pack_ui()
        else:
            self._still_path = None
            self.preview.src = ""
            self.preview.visible = False
            self.preview_empty.visible = True
            self.still_label.value = (
                "No still selected — upload into any slot (Front / Side / Close-up)"
            )
        try:
            self.page.update()
        except Exception:
            pass

    def _on_still_from_strip(self, path: str) -> None:
        self._set_still(path, slot=self._upload_target_slot())

    def _set_still(self, path: str, *, slot: str | None = None) -> None:
        p = Path(path)
        if not p.is_file():
            self._set_status(f"Missing still: {path}", error=True)
            return
        resolved = str(p.resolve())
        target = slot or self._upload_target_slot()
        if target not in IDENTITY_SLOTS:
            target = "front"
        self._still_path = resolved
        self.preview.src = resolved
        self.preview.visible = True
        self.preview_empty.visible = False
        short = SLOT_SHORT.get(target, target)
        self.still_label.value = f"{short}: {p.name}"
        if self._editing_id or self._create_mode:
            self._edit_identity[target] = resolved
            self._sync_pack_ui()
        try:
            self.prev_strip.record_and_refresh(resolved)
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
        self._set_status("Library open — return here to save a still as a character.")

    def _sync_pack_ui(self) -> None:
        editing = bool(self._editing_id) or bool(self._create_mode)
        self.pack_label.visible = editing
        self.pack_row.visible = editing
        filled = sum(1 for s in IDENTITY_SLOTS if self._edit_identity.get(s))
        self.btn_bg_all.visible = editing and filled >= 2 and bool(self._editing_id)
        self.bg_cost_label.visible = editing and filled >= 1 and bool(self._editing_id)
        if editing and filled >= 1 and self._editing_id:
            self.bg_cost_label.value = (
                f"Remove BG cost: {estimate_bg_remove_cost(1)} per slot"
                + (
                    f" · all angles {estimate_bg_remove_cost(filled)}"
                    if filled >= 2
                    else ""
                )
            )
        if not editing:
            return
        mode = "New character" if self._create_mode and not self._editing_id else "Edit"
        self.pack_label.value = (
            f"{mode} · Identity pack ({filled}/{MAX_STILLS_PER_CHARACTER}) — "
            "Front preferred for Motion Sync · click thumb to enlarge"
        )
        for slot in IDENTITY_SLOTS:
            ui = self._pack_slot_ui[slot]
            path = (self._edit_identity.get(slot) or "").strip()
            ok = bool(path and Path(path).is_file())
            img: ft.Image = ui["img"]
            empty: ft.Container = ui["empty"]
            box: ft.Container = ui["box"]
            if ok:
                img.src = path
                img.visible = True
                empty.visible = False
                box.border = ft.Border.all(
                    2 if slot == "front" else 1,
                    ACCENT if slot == "front" else BORDER,
                )
            else:
                img.visible = False
                empty.visible = True
                box.border = ft.Border.all(1, BORDER)
            ui["btn_clear"].disabled = filled <= 1 and ok
            if "btn_bg" in ui:
                btn_bg = ui["btn_bg"]
                if self._bg_busy:
                    btn_bg.disabled = True
                    if self._bg_busy_slot == slot:
                        btn_bg.content = "Removing…"
                    else:
                        btn_bg.content = "Remove BG"
                    btn_bg.tooltip = "Background remove in progress…"
                else:
                    btn_bg.content = "Remove BG"
                    btn_bg.disabled = not ok or self._profile_busy
                    btn_bg.tooltip = (
                        f"Remove background · {estimate_bg_remove_cost(1)}"
                        if ok
                        else "Upload a still first"
                    )
            if "btn_gen" in ui:
                btn_gen = ui["btn_gen"]
                has_any = filled >= 1
                if self._profile_busy:
                    btn_gen.disabled = True
                    target = self._profile_slot_key()
                    btn_gen.content = (
                        "Generating…" if target == slot else "Generate profile"
                    )
                    btn_gen.tooltip = "Profile generate in progress…"
                elif self._bg_busy:
                    btn_gen.disabled = True
                    btn_gen.content = "Generate profile"
                    btn_gen.tooltip = "Wait for background remove to finish"
                else:
                    btn_gen.content = "Generate profile"
                    # Need at least one other still (or any still) as ref
                    btn_gen.disabled = not has_any
                    btn_gen.tooltip = (
                        f"Generate {SLOT_SHORT[slot]} from existing stills · "
                        f"{estimate_profile_cost()}"
                        if has_any
                        else "Need at least one identity still first"
                    )
        if self._bg_busy:
            self.btn_bg_all.disabled = True
            self.btn_bg_all.content = "Removing backgrounds…"
        else:
            self.btn_bg_all.disabled = self._profile_busy
            self.btn_bg_all.content = "Remove background on all angles"

    def _make_pack_upload(self, slot: str):
        async def _click(_e: ft.ControlEvent) -> None:
            if not self._editing_id and not self._create_mode:
                return
            try:
                files = await pick_image(
                    self.page, dialog_title=f"Identity · {SLOT_SHORT[slot]}"
                )
            except Exception as exc:
                self._set_status(f"Picker error: {exc}", error=True)
                return
            if not files or not files[0].path:
                return
            p = str(Path(files[0].path).resolve())
            self._edit_identity[slot] = p
            if slot == "front":
                self._set_still(p)
            self._sync_pack_ui()
            try:
                self.page.update()
            except Exception:
                pass

        return _click

    def _make_pack_clear(self, slot: str):
        async def _click(_e: ft.ControlEvent) -> None:
            if not self._editing_id and not self._create_mode:
                return
            filled = [s for s in IDENTITY_SLOTS if self._edit_identity.get(s)]
            if len(filled) <= 1 and self._edit_identity.get(slot):
                self._set_status("Keep at least one identity still.", error=True)
                return
            self._edit_identity[slot] = ""
            if slot == "front":
                # Promote first remaining to preview
                nxt = next(
                    (self._edit_identity[s] for s in IDENTITY_SLOTS if self._edit_identity.get(s)),
                    None,
                )
                if nxt:
                    self._set_still(nxt)
                else:
                    self._clear_still()
            self._sync_pack_ui()
            try:
                self.page.update()
            except Exception:
                pass

        return _click

    def _cancel_edit(self, e: ft.ControlEvent | None = None) -> None:
        self._editing_id = None
        self._create_mode = False
        self._edit_identity = {s: "" for s in IDENTITY_SLOTS}
        self.name_field.value = ""
        self.notes_field.value = ""
        self.btn_save.content = "Save character"
        self.btn_cancel_edit.visible = False
        self.new_char_choice.visible = False
        self.t2i_box.visible = False
        self._sync_pack_ui()
        self._clear_still()
        self._set_status("Edit cancelled.")

    async def _save(self, e: ft.ControlEvent) -> None:
        name = (self.name_field.value or "").strip()
        notes = (self.notes_field.value or "").strip()
        if not name:
            self._set_status("Name is required.", error=True)
            return
        try:
            pack = {
                s: p
                for s, p in self._edit_identity.items()
                if p and Path(p).is_file()
            }
            if not pack and self._still_path and Path(self._still_path).is_file():
                pack = {"front": self._still_path}
            if self._editing_id:
                if not pack:
                    self._set_status("At least one identity still is required.", error=True)
                    return
                updated = update_character(
                    self._editing_id,
                    name=name,
                    notes=notes,
                    identity=pack,
                )
                if not updated:
                    self._set_status("Character not found.", error=True)
                    return
                self._set_status(
                    f"Updated: {updated.name} ({updated.slot_summary()})"
                )
            else:
                # New character (create mode or simple front upload)
                if not pack:
                    self._set_status(
                        "Upload at least one still (Front / Side / Close-up).",
                        error=True,
                    )
                    return
                front = pack.get("front") or next(iter(pack.values()))
                entry = add_character(
                    name=name,
                    still_path=front,
                    notes=notes,
                    identity=pack,
                )
                self._set_status(
                    f"Saved new character: {entry.name} · {entry.slot_summary()}"
                )
            self._editing_id = None
            self._create_mode = False
            self._edit_identity = {s: "" for s in IDENTITY_SLOTS}
            self.btn_save.content = "Save character"
            self.btn_cancel_edit.visible = False
            self.new_char_choice.visible = False
            self.t2i_box.visible = False
            self.name_field.value = ""
            self.notes_field.value = ""
            self._sync_pack_ui()
            self._clear_still()
            self.refresh()
        except Exception as exc:
            self._set_status(str(exc), error=True)

    # ----- New character entry -----

    async def _open_new_character(self, e: ft.ControlEvent) -> None:
        self.costume_box.visible = False
        self.profile_box.visible = False
        self.t2i_box.visible = False
        self.new_char_choice.visible = True
        self._set_status("Choose how to create a new character.")
        try:
            self.page.update()
        except Exception:
            pass

    async def _start_new_upload(self, e: ft.ControlEvent) -> None:
        self._editing_id = None
        self._create_mode = True
        self._edit_identity = {s: "" for s in IDENTITY_SLOTS}
        self.name_field.value = ""
        self.notes_field.value = ""
        self.btn_save.content = "Save new character"
        self.btn_cancel_edit.visible = True
        self.new_char_choice.visible = False
        self.t2i_box.visible = False
        self._clear_still()
        self._sync_pack_ui()
        self._set_status(
            "New character — upload into any slot (Front / Side / Close-up). "
            "Only one still is required; Generate profile can fill the rest later."
        )
        try:
            self.page.update()
        except Exception:
            pass

    async def _start_new_generate(self, e: ft.ControlEvent) -> None:
        self.new_char_choice.visible = False
        self.t2i_box.visible = True
        self._create_mode = False
        self._t2i_seq_confirmed = {}
        self._t2i_pending_path = None
        self._t2i_pending_slot = None
        self._t2i_refresh_cost()
        self._t2i_update_seq_status()
        self._t2i_set_preview_ui(None)
        self.btn_t2i_save.visible = False
        self._set_status(
            "T2I builder — set helpers + description, Enhance optional, then "
            "Generate next (Front first → Side → Close-up)."
        )
        try:
            self.page.update()
        except Exception:
            pass

    async def _cancel_new_character(self, e: ft.ControlEvent | None = None) -> None:
        if self._t2i_busy:
            return
        self.new_char_choice.visible = False
        self.t2i_box.visible = False
        self._t2i_seq_confirmed = {}
        self._t2i_pending_path = None
        if self._create_mode and not self._editing_id:
            self._cancel_edit()
        try:
            self.page.update()
        except Exception:
            pass

    def _t2i_assembled_desc(self) -> str:
        return assemble_character_t2i_description(
            description=self.t2i_prompt.value or "",
            gender=self.t2i_gender.value,
            age=self.t2i_age.value,
            build=self.t2i_build.value,
            height=self.t2i_height.value,
            hair_color=self.t2i_hair_color.value,
            hair_length=self.t2i_hair_length.value,
            hair_style=self.t2i_hair_style.value,
            facial_hair=self.t2i_facial_hair.value,
            skin=self.t2i_skin.value,
            skin_free=self.t2i_skin_free.value,
            clothes=self.t2i_clothes.value,
        )

    def _t2i_next_missing_slot(self) -> str | None:
        for s in T2I_SEQ_ORDER:
            path = self._t2i_seq_confirmed.get(s)
            if not path or not Path(path).is_file():
                return s
        return None

    def _t2i_update_seq_status(self) -> None:
        parts = []
        for s in T2I_SEQ_ORDER:
            ok = bool(
                self._t2i_seq_confirmed.get(s)
                and Path(self._t2i_seq_confirmed[s]).is_file()
            )
            parts.append(f"{SLOT_SHORT[s]}{'✓' if ok else '·'}")
        nxt = self._t2i_next_missing_slot()
        nxt_lab = SLOT_SHORT[nxt] if nxt else "done"
        self.t2i_seq_status.value = (
            "Plates: " + "  ".join(parts) + f"  · next: {nxt_lab}"
        )
        self.btn_t2i_gen_next.content = (
            f"Generate next ({nxt_lab})" if nxt else "All plates confirmed"
        )
        self.btn_t2i_gen_next.disabled = nxt is None or self._t2i_busy
        n_ok = sum(
            1
            for s in T2I_SEQ_ORDER
            if self._t2i_seq_confirmed.get(s)
            and Path(self._t2i_seq_confirmed[s]).is_file()
        )
        self.btn_t2i_save.visible = n_ok >= 1 and not self._t2i_busy

    def _t2i_sync_res_options(self) -> None:
        opts = t2i_resolution_options(self.t2i_model_dd.value)
        if not opts:
            opts = ["1:1 square HD"]
        from media_studio.flet_theme import dropdown_options
        from media_studio.character_store import resolution_display_label

        self.t2i_res_dd.options = dropdown_options(opts)
        cur = self.t2i_res_dd.value
        if cur not in opts:
            self.t2i_res_dd.value = default_practical_t2i_resolution(opts)
        self.t2i_res_dd.visible = True
        if len(opts) == 1:
            self.t2i_res_dd.label = (
                f"Resolution · {resolution_display_label(opts[0])}"
            )
        else:
            self.t2i_res_dd.label = "Resolution / quality"

    def _t2i_refresh_cost(self) -> None:
        missing = sum(
            1
            for s in T2I_SEQ_ORDER
            if not (
                self._t2i_seq_confirmed.get(s)
                and Path(self._t2i_seq_confirmed[s]).is_file()
            )
        )
        self.t2i_cost.value = estimate_t2i_character_cost(
            t2i_label=self.t2i_model_dd.value,
            n_remaining=max(1, missing),
            resolution=self.t2i_res_dd.value,
        )

    async def _on_t2i_model_change(self, e: ft.ControlEvent | None = None) -> None:
        self._t2i_sync_res_options()
        self._t2i_refresh_cost()
        try:
            self.page.update()
        except Exception:
            pass

    def _t2i_set_busy(self, busy: bool, *, message: str = "") -> None:
        self._t2i_busy = busy
        self.t2i_busy_row.visible = busy
        self.t2i_progress_ring.visible = busy
        try:
            t = self.t2i_busy_row.controls[1]
            if isinstance(t, ft.Text):
                t.value = message or "Generating…"
        except Exception:
            pass
        self.btn_t2i_gen_next.disabled = busy or self._t2i_next_missing_slot() is None
        self.btn_t2i_enhance.disabled = busy
        self.btn_t2i_confirm.disabled = busy
        self.btn_t2i_regen.disabled = busy
        try:
            self.page.update()
        except Exception:
            pass

    def _t2i_set_preview_ui(self, path: str | None) -> None:
        if path and Path(path).is_file():
            self.t2i_preview_img.src = path
            self.t2i_preview_img.visible = True
            self.t2i_preview_tap.visible = True
            short = SLOT_SHORT.get(self._t2i_pending_slot or "closeup", "plate")
            self.t2i_preview_label.value = (
                f"{short} ready — Confirm to lock plate · Regenerate retries"
            )
            self.btn_t2i_confirm.visible = True
            self.btn_t2i_regen.visible = True
            self.btn_t2i_dismiss.visible = True
        else:
            self.t2i_preview_img.visible = False
            self.t2i_preview_tap.visible = False
            self.btn_t2i_confirm.visible = False
            self.btn_t2i_regen.visible = False
            self.btn_t2i_dismiss.visible = False
            if not self._t2i_busy:
                self.t2i_preview_label.value = ""

    async def _on_t2i_preview_tap(self, e: ft.ControlEvent) -> None:
        if self._t2i_pending_path and Path(self._t2i_pending_path).is_file():
            short = SLOT_SHORT.get(self._t2i_pending_slot or "closeup", "plate")
            self._open_preview(self._t2i_pending_path, title=f"T2I · {short}")

    async def _on_t2i_enhance(self, e: ft.ControlEvent) -> None:
        # Fold helpers into the description field via Enhance
        assembled = self._t2i_assembled_desc()
        if assembled and not (self.t2i_prompt.value or "").strip():
            self.t2i_prompt.value = assembled

        def _extra() -> dict[str, Any]:
            return {
                "workspace": "characters",
                "mode": "t2i_character",
                "helpers": self._t2i_assembled_desc(),
                "insights": (self.t2i_insights.value or "").strip(),
                "guidance": (
                    "Rewrite into a strong photoreal T2I character prompt for an adult "
                    "identity plate. Include wardrobe (default simple neutral if unset). "
                    "Pure black clean background, isolated subject. No children. "
                    "Do not invent unsupported camera tricks. Keep concise and model-ready. "
                    "Honor Enhance Insights as soft creative intent only."
                ),
            }

        await run_prompt_enhance(
            page=self.page,
            state=self.state,
            prompt_field=self.t2i_prompt,
            get_model=lambda: self.t2i_model_dd.value,
            get_extra_context=_extra,
            status_ctrl=self.status,
            job_progress=self.job_progress,
            enhance_btn=self.btn_t2i_enhance,
            busy_controls=[self.btn_t2i_gen_next],
            context_label="character description",
            allow_empty_with_context=True,
            busy_scope="characters",
        )
        self._t2i_refresh_cost()

    async def _t2i_generate_next(self, e: ft.ControlEvent | None = None) -> None:
        await self._t2i_run_slot(self._t2i_next_missing_slot(), regen=False)

    async def _t2i_regenerate_plate(self, e: ft.ControlEvent | None = None) -> None:
        slot = self._t2i_pending_slot or self._t2i_next_missing_slot()
        await self._t2i_run_slot(slot, regen=True)

    async def _t2i_run_slot(self, slot: str | None, *, regen: bool) -> None:
        if self._t2i_busy:
            return
        if not slot or slot not in IDENTITY_SLOTS:
            self._set_status("All plates already confirmed — Save character.", error=False)
            return
        from media_studio.secrets_store import has_fal_key

        if not has_fal_key():
            self._set_status("FAL API key required — open Settings.", error=True)
            return
        if self.state.is_busy("characters"):
            return
        if not self.state.try_busy("characters"):
            return

        short = SLOT_SHORT[slot]
        desc = self._t2i_assembled_desc() or (self.t2i_prompt.value or "").strip()
        insights = (self.t2i_insights.value or "").strip()
        if not desc and slot == "front" and not self._t2i_seq_confirmed:
            self.state.clear_busy("characters")
            self._set_status(
                "Add a character description (or helpers) before Front generate.",
                error=True,
            )
            return

        self._t2i_set_busy(True, message=f"Generating {short}…")
        self.job_progress.start(f"T2I character · {short}…", self.page)
        self._set_status(f"Generating {short} plate…")

        def on_progress(msg: str) -> None:
            self.job_progress.set_message(classify_progress(msg), self.page)
            try:
                t = self.t2i_busy_row.controls[1]
                if isinstance(t, ft.Text):
                    t.value = msg or f"Generating {short}…"
                self.page.update()
            except Exception:
                pass

        try:
            from media_studio.job_context import to_thread_with_job
            from media_studio.services import generate
            from media_studio.vision_service import run_vision

            path: str | None = None
            err: str | None = None
            confirmed_refs = [
                self._t2i_seq_confirmed[s]
                for s in T2I_SEQ_ORDER
                if s != slot
                and self._t2i_seq_confirmed.get(s)
                and Path(self._t2i_seq_confirmed[s]).is_file()
            ]

            if slot == "front" and not confirmed_refs:
                # Pure T2I first plate (Front full-body)
                prompt = character_t2i_prompt_for_slot(
                    slot, base_description=desc, insights=insights
                )
                res_ui = (self.t2i_res_dd.value or "").strip()
                # Nano-style models: resolution enum; Flux-style: aspect drives image_size
                from media_studio.vision_registry import find_vision_model

                tspec = find_vision_model(self.t2i_model_dd.value, "text_to_image")
                has_res = bool(
                    tspec and getattr(tspec, "resolution_choices", None)
                )
                aspect = "1:1 square HD" if "hd" in res_ui.lower() else "1:1 square"
                if has_res:
                    aspect = "1:1"
                result = await to_thread_with_job(
                    self.state,
                    run_vision,
                    mode="text_to_image",
                    prompt=prompt,
                    model_label=self.t2i_model_dd.value,
                    aspect_ratio=aspect if not has_res else "1:1",
                    resolution=res_ui if has_res else None,
                    num_images=1,
                    output_dir=self.state.output_dir,
                    on_progress=on_progress,
                )
                if result.ok:
                    path = result.path or (
                        result.paths[0] if result.paths else None
                    )
                else:
                    err = result.status or "T2I failed"
            else:
                # I2I multi-ref identity lock for Side / Close-up (or later Front with refs)
                if not confirmed_refs:
                    err = f"{short}: need at least one confirmed plate first"
                else:
                    prompt = character_t2i_i2i_prompt_for_slot(
                        slot, base_description=desc, insights=insights
                    )
                    primary = confirmed_refs[0]
                    extras = confirmed_refs[1:]
                    # Prefer multi-ref edit model for later angles
                    edit_model = preferred_costume_model()
                    from media_studio.fal.models import resolve_image_edit_model

                    es = resolve_image_edit_model(edit_model)
                    model_choice = es.label if es else edit_model
                    # Later angles: prefer edit model res when available
                    edit_res_opts = edit_resolution_options(model_choice)
                    edit_res = (
                        default_practical_resolution(edit_res_opts)
                        if edit_res_opts
                        else None
                    )
                    # Map T2I "2K-class" preference onto edit ladder
                    t2i_res = (self.t2i_res_dd.value or "").upper()
                    if edit_res_opts and "2K" in edit_res_opts and (
                        "2K" in t2i_res or "HD" in (self.t2i_res_dd.value or "").upper()
                    ):
                        edit_res = "2K"
                    elif edit_res_opts and "1K" in edit_res_opts and "1K" in t2i_res:
                        edit_res = "1K"
                    params_json = edit_params_json_for_resolution(edit_res)
                    result = await to_thread_with_job(
                        self.state,
                        generate,
                        prompt,
                        model_choice=model_choice,
                        image_file=primary,
                        extra_image_files=extras,
                        output_dir=self.state.output_dir,
                        on_progress=on_progress,
                        scenario="character-t2i-seq",
                        parameters_json=params_json,
                    )
                    if result.ok:
                        path = result.primary_image or (
                            result.image_paths[0] if result.image_paths else None
                        )
                    else:
                        err = result.status or "I2I failed"

            if path and Path(path).is_file():
                self._t2i_pending_path = str(path)
                self._t2i_pending_slot = slot
                self._t2i_set_busy(False)
                self._t2i_set_preview_ui(str(path))
                self.job_progress.finish_ok(
                    f"{short} ready — Confirm plate", self.page
                )
                self._set_status(
                    f"{short} ready — Confirm to lock"
                    + (" (regenerated)" if regen else "")
                    + "."
                )
            else:
                self._t2i_set_busy(False)
                self._t2i_set_preview_ui(None)
                msg = err or f"{short} generate failed"
                self.job_progress.finish_error(msg, self.page)
                self._set_status(msg, error=True)
        except Exception as exc:
            self._t2i_set_busy(False)
            self._t2i_set_preview_ui(None)
            self.job_progress.finish_error(str(exc), self.page)
            self._set_status(str(exc), error=True)
            traceback.print_exc()
        finally:
            self.state.clear_busy("characters")
            self._t2i_refresh_cost()
            self._t2i_update_seq_status()
            try:
                self.page.update()
            except Exception:
                pass

    async def _t2i_confirm_plate(self, e: ft.ControlEvent) -> None:
        if self._t2i_busy:
            return
        path = self._t2i_pending_path
        slot = self._t2i_pending_slot
        if not path or not slot or not Path(path).is_file():
            self._set_status("No plate to confirm.", error=True)
            return
        self._t2i_seq_confirmed[slot] = path
        self._t2i_pending_path = None
        self._t2i_pending_slot = None
        self._t2i_set_preview_ui(None)
        self._t2i_update_seq_status()
        self._t2i_refresh_cost()
        short = SLOT_SHORT[slot]
        nxt = self._t2i_next_missing_slot()
        if nxt:
            self._set_status(
                f"Confirmed {short}. Next: Generate {SLOT_SHORT[nxt]}."
            )
        else:
            self._set_status(
                f"Confirmed {short}. All plates ready — name and Save character."
            )
        try:
            self.page.update()
        except Exception:
            pass

    def _t2i_dismiss_preview(self, e: ft.ControlEvent | None = None) -> None:
        if self._t2i_busy:
            return
        self._t2i_pending_path = None
        self._t2i_pending_slot = None
        self._t2i_set_preview_ui(None)
        try:
            self.page.update()
        except Exception:
            pass

    async def _t2i_save_character(self, e: ft.ControlEvent) -> None:
        if self._t2i_busy:
            return
        name = (self.t2i_name.value or "").strip()
        if not name:
            self._set_status("Name is required to save.", error=True)
            return
        pack = {
            s: p
            for s, p in self._t2i_seq_confirmed.items()
            if p and Path(p).is_file()
        }
        if not pack:
            self._set_status("Confirm at least one plate before saving.", error=True)
            return
        front = pack.get("front") or next(iter(pack.values()))
        notes = (self.t2i_notes.value or "").strip()
        try:
            entry = add_character(
                name=name,
                still_path=front,
                notes=notes,
                identity=pack,
            )
            self._set_status(
                f"Saved: {entry.name} · {entry.slot_summary()}"
            )
            self.t2i_box.visible = False
            self._t2i_seq_confirmed = {}
            self._t2i_pending_path = None
            self.t2i_name.value = ""
            self.t2i_notes.value = ""
            self.refresh()
        except Exception as exc:
            self._set_status(str(exc), error=True)

    # ----- larger preview (lightbox) -----

    def _open_preview(self, path: str, *, title: str = "Still preview") -> None:
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

    def _make_preview_tap_slot(self, slot: str):
        async def _tap(_e: ft.ControlEvent) -> None:
            path = (self._edit_identity.get(slot) or "").strip()
            if path and Path(path).is_file():
                self._open_preview(path, title=f"{SLOT_SHORT.get(slot, slot)} · identity")

        return _tap

    def _make_preview_path(self, path: str, title: str):
        async def _click(_e: ft.ControlEvent) -> None:
            if path and Path(path).is_file():
                self._open_preview(path, title=title)

        return _click

    # ----- background remove -----

    def _set_bg_busy(self, busy: bool, *, slot: str | None = None, message: str = "") -> None:
        """Show spinner + disable Remove BG controls so the click is obvious."""
        self._bg_busy = busy
        self._bg_busy_slot = slot if busy else None
        if busy:
            self.bg_preview_box.visible = True
            self.bg_busy_row.visible = True
            self.bg_progress_ring.visible = True
            # Update busy label text (second control in bg_busy_row)
            try:
                busy_txt = self.bg_busy_row.controls[1]
                if isinstance(busy_txt, ft.Text):
                    busy_txt.value = message or "Removing background…"
            except Exception:
                pass
            self.bg_preview_label.value = message or "Removing background…"
            self.bg_preview_label.visible = True
            self.bg_preview_img.visible = False
            self.bg_preview_tap.visible = False
            self.bg_preview_hint.visible = False
            self.btn_bg_confirm.visible = False
            self.btn_bg_dismiss.visible = False
            self.btn_bg_confirm.disabled = True
            self.btn_bg_dismiss.disabled = True
        else:
            self.bg_busy_row.visible = False
            self.bg_progress_ring.visible = False
            self.btn_bg_confirm.disabled = False
            self.btn_bg_dismiss.disabled = False
        self._sync_pack_ui()
        try:
            self.page.update()
        except Exception:
            pass

    def _show_bg_preview_result(
        self,
        path: str,
        *,
        slot: str,
        label: str,
    ) -> None:
        self._bg_pending_path = path
        self._bg_pending_slot = slot
        self.bg_preview_box.visible = True
        self.bg_busy_row.visible = False
        self.bg_progress_ring.visible = False
        self.bg_preview_img.src = path
        self.bg_preview_img.visible = True
        self.bg_preview_tap.visible = True
        self.bg_preview_label.value = label
        self.bg_preview_label.visible = True
        self.bg_preview_hint.visible = True
        self.btn_bg_confirm.visible = True
        self.btn_bg_dismiss.visible = True
        self.btn_bg_confirm.disabled = False
        self.btn_bg_dismiss.disabled = False

    async def _on_bg_preview_tap(self, e: ft.ControlEvent) -> None:
        path = self._bg_pending_path
        if path and Path(path).is_file():
            slot = self._bg_pending_slot or "cutout"
            title = (
                "BG remove · batch preview"
                if slot == "batch"
                else f"BG remove · {SLOT_SHORT.get(slot, slot)}"
            )
            self._open_preview(path, title=title)

    def _make_pack_bg_remove(self, slot: str):
        async def _click(_e: ft.ControlEvent) -> None:
            if self._bg_busy or self.state.is_busy("characters"):
                return
            path = (self._edit_identity.get(slot) or "").strip()
            if not path or not Path(path).is_file():
                self._set_status("No still in this slot.", error=True)
                return
            await self._run_bg_remove_one(
                path,
                slot=slot,
                char_id=self._editing_id,
            )

        return _click

    async def _bg_remove_all(self, e: ft.ControlEvent) -> None:
        if self._bg_busy:
            return
        if not self._editing_id:
            return
        slots = [
            (s, p)
            for s, p in self._edit_identity.items()
            if p and Path(p).is_file()
        ]
        if len(slots) < 2:
            self._set_status("Need at least 2 filled angles for batch remove.", error=True)
            return
        from media_studio.secrets_store import has_fal_key

        if not has_fal_key():
            self._set_status("FAL API key required.", error=True)
            return
        if self.state.is_busy("characters"):
            return
        if not self.state.try_busy("characters"):
            return
        n = len(slots)
        self.bg_cost_label.visible = True
        self.bg_cost_label.value = f"Batch: {estimate_bg_remove_cost(n)}"
        self._bg_batch_results = {}
        self._set_bg_busy(
            True,
            slot=None,
            message=f"Removing background on {n} angles…",
        )
        self.job_progress.start(f"Remove BG · {n} angle(s)…", self.page)
        self._set_status(f"Removing backgrounds ({n})…")

        def on_progress(msg: str) -> None:
            self.job_progress.set_message(classify_progress(msg), self.page)
            try:
                busy_txt = self.bg_busy_row.controls[1]
                if isinstance(busy_txt, ft.Text):
                    busy_txt.value = msg or "Removing background…"
                self.bg_preview_label.value = msg
                self.page.update()
            except Exception:
                pass

        try:
            from media_studio.job_context import to_thread_with_job

            for i, (slot, path) in enumerate(slots, start=1):
                label = f"{SLOT_SHORT.get(slot, slot)} ({i}/{n})…"
                on_progress(label)
                self._bg_busy_slot = slot
                self._sync_pack_ui()
                try:
                    self.page.update()
                except Exception:
                    pass
                out = await to_thread_with_job(
                    self.state,
                    run_background_remove,
                    path,
                    output_dir=self.state.output_dir,
                    on_progress=on_progress,
                )
                if out and Path(out).is_file():
                    self._bg_batch_results[slot] = out
            if self._bg_batch_results:
                first = next(iter(self._bg_batch_results.values()))
                self._bg_pending_char_id = self._editing_id
                self._set_bg_busy(False)
                self._show_bg_preview_result(
                    first,
                    slot="batch",
                    label=(
                        f"Batch ready: {len(self._bg_batch_results)} cutout(s). "
                        "Click preview to enlarge · Confirm replaces all processed slots."
                    ),
                )
                self.job_progress.finish_ok(
                    "Batch cutouts ready — Confirm to apply", self.page
                )
                self._set_status("Review cutouts — Confirm replace or Dismiss.")
            else:
                self._set_bg_busy(False)
                self.bg_preview_box.visible = False
                self.job_progress.finish_error("Batch failed", self.page)
                self._set_status("Background remove failed.", error=True)
        except Exception as exc:
            self._set_bg_busy(False)
            self.bg_preview_box.visible = False
            self.job_progress.finish_error(str(exc), self.page)
            self._set_status(str(exc), error=True)
            traceback.print_exc()
        finally:
            self.state.clear_busy("characters")
            self._sync_pack_ui()
            try:
                self.page.update()
            except Exception:
                pass

    async def _run_bg_remove_one(
        self,
        path: str,
        *,
        slot: str,
        char_id: str | None,
    ) -> None:
        from media_studio.secrets_store import has_fal_key

        if not has_fal_key():
            self._set_status("FAL API key required.", error=True)
            return
        if self.state.is_busy("characters"):
            return
        if not self.state.try_busy("characters"):
            return
        self.bg_cost_label.visible = True
        self.bg_cost_label.value = estimate_bg_remove_cost(1)
        short = SLOT_SHORT.get(slot, slot)
        self._set_bg_busy(
            True,
            slot=slot,
            message=f"Removing background ({short})…",
        )
        self.job_progress.start(f"Removing background ({short})…", self.page)
        self._set_status(f"Removing background on {short}…")

        def on_progress(msg: str) -> None:
            self.job_progress.set_message(classify_progress(msg), self.page)
            try:
                busy_txt = self.bg_busy_row.controls[1]
                if isinstance(busy_txt, ft.Text):
                    busy_txt.value = msg or f"Removing background ({short})…"
                self.bg_preview_label.value = msg
                self.page.update()
            except Exception:
                pass

        try:
            from media_studio.job_context import to_thread_with_job

            out = await to_thread_with_job(
                self.state,
                run_background_remove,
                path,
                output_dir=self.state.output_dir,
                on_progress=on_progress,
            )
            if out and Path(out).is_file():
                self._bg_batch_results = {}
                self._bg_pending_char_id = char_id
                self._set_bg_busy(False)
                self._show_bg_preview_result(
                    out,
                    slot=slot,
                    label=(
                        f"{short} cutout ready — click preview to enlarge · "
                        "Confirm to replace slot"
                    ),
                )
                self.job_progress.finish_ok("Preview ready", self.page)
                self._set_status("Background removed — Confirm replace or Dismiss.")
            else:
                self._set_bg_busy(False)
                self.bg_preview_box.visible = False
                self.job_progress.finish_error("No result", self.page)
                self._set_status("Background remove failed.", error=True)
        except Exception as exc:
            self._set_bg_busy(False)
            self.bg_preview_box.visible = False
            self.job_progress.finish_error(str(exc), self.page)
            self._set_status(str(exc), error=True)
            traceback.print_exc()
        finally:
            self.state.clear_busy("characters")
            self._sync_pack_ui()
            try:
                self.page.update()
            except Exception:
                pass

    async def _bg_confirm(self, e: ft.ControlEvent) -> None:
        if self._bg_busy:
            return
        if self._bg_pending_slot == "batch" and self._bg_batch_results:
            for slot, path in self._bg_batch_results.items():
                self._edit_identity[slot] = path
                if self._editing_id:
                    try:
                        set_character_slot(self._editing_id, slot, path)
                    except Exception:
                        pass
            if self._edit_identity.get("front"):
                self._set_still(self._edit_identity["front"])
            self._sync_pack_ui()
            self._set_status(
                f"Replaced {len(self._bg_batch_results)} angle(s) with cutouts."
            )
            self._bg_dismiss()
            self.refresh()
            return
        if not self._bg_pending_path or not self._bg_pending_slot:
            self._bg_dismiss()
            return
        slot = self._bg_pending_slot
        path = self._bg_pending_path
        self._edit_identity[slot] = path
        if slot == "front":
            self._set_still(path)
        if self._bg_pending_char_id:
            try:
                set_character_slot(self._bg_pending_char_id, slot, path)
            except Exception as exc:
                self._set_status(str(exc), error=True)
                return
        self._sync_pack_ui()
        self._set_status(f"Replaced {SLOT_SHORT.get(slot, slot)} with cutout.")
        self._bg_dismiss()
        self.refresh()

    def _bg_dismiss(self, e: ft.ControlEvent | None = None) -> None:
        if self._bg_busy:
            return  # don't dismiss mid-run
        self._bg_pending_path = None
        self._bg_pending_slot = None
        self._bg_pending_char_id = None
        self._bg_batch_results = {}
        self.bg_preview_box.visible = False
        self.bg_preview_img.visible = False
        self.bg_preview_tap.visible = False
        self.bg_preview_hint.visible = False
        self.bg_busy_row.visible = False
        self.bg_progress_ring.visible = False
        self.btn_bg_confirm.visible = False
        self.btn_bg_dismiss.visible = False
        try:
            self.page.update()
        except Exception:
            pass

    # ----- generate missing profile -----

    def _profile_slot_key(self) -> str:
        raw = (self.profile_target_dd.value or "Front").strip().lower()
        for s in IDENTITY_SLOTS:
            if SLOT_SHORT[s].lower() == raw or s == raw:
                return s
        if "side" in raw or "profile" in raw:
            return "side"
        if "close" in raw or "face" in raw:
            return "closeup"
        return "front"

    def _profile_model_choice(self) -> str:
        return (self.profile_model_dd.value or preferred_costume_model()).strip()

    def _profile_resolution(self) -> str | None:
        if not getattr(self.profile_res_dd, "visible", True):
            return None
        return (self.profile_res_dd.value or "").strip() or None

    def _profile_sync_res_options(self) -> None:
        opts = edit_resolution_options(self._profile_model_choice())
        from media_studio.flet_theme import dropdown_options
        from media_studio.character_store import resolution_display_label

        if not opts:
            self.profile_res_dd.visible = False
            return
        self.profile_res_dd.visible = True
        # Show concrete labels; dropdown value stays API enum
        labels = [resolution_display_label(o) for o in opts]
        # Map display back: store display as value only when unique mapping
        # Prefer keeping raw enums as values for generate()
        self.profile_res_dd.options = dropdown_options(opts)
        if self.profile_res_dd.value not in opts:
            self.profile_res_dd.value = default_practical_resolution(opts)
        # Label hint in cost already includes size; single-option clarity
        if len(opts) == 1:
            self.profile_res_dd.label = f"Resolution · {resolution_display_label(opts[0])}"
        else:
            self.profile_res_dd.label = "Resolution"

    def _refresh_profile_cost(self) -> None:
        self.profile_cost.value = estimate_profile_cost(
            model_key=self._profile_model_choice(),
            resolution=self._profile_resolution(),
        )

    async def _on_profile_controls_change(self, e: ft.ControlEvent | None = None) -> None:
        self._profile_sync_res_options()
        self._refresh_profile_cost()
        try:
            self.page.update()
        except Exception:
            pass

    def _make_open_profile(self, slot: str):
        async def _click(_e: ft.ControlEvent) -> None:
            if self._profile_busy or self._bg_busy:
                return
            self._open_profile_panel(slot)

        return _click

    def _open_profile_panel(self, slot: str) -> None:
        if not self._editing_id and not self._create_mode:
            self._set_status("Open Edit or New character first.", error=True)
            return
        filled = [
            p for p in self._edit_identity.values() if p and Path(p).is_file()
        ]
        if not filled:
            self._set_status(
                "Need at least one identity still before generating a profile.",
                error=True,
            )
            return
        key = slot if slot in IDENTITY_SLOTS else "front"
        self.profile_target_dd.value = SLOT_SHORT[key]
        self._profile_char_id = self._editing_id
        self._profile_pending_path = None
        self._profile_pending_slot = None
        self._profile_set_result_ui(None)
        self._refresh_profile_cost()
        self.profile_box.visible = True
        self._set_status(
            f"Generate {SLOT_SHORT[key]} from {len(filled)} existing still(s)."
        )
        try:
            self.page.update()
        except Exception:
            pass

    def _profile_close(self, e: ft.ControlEvent | None = None) -> None:
        if self._profile_busy:
            return
        self.profile_box.visible = False
        self._profile_pending_path = None
        self._profile_pending_slot = None
        self._profile_set_result_ui(None)
        try:
            self.page.update()
        except Exception:
            pass

    def _profile_set_busy(self, busy: bool, *, message: str = "") -> None:
        self._profile_busy = busy
        self.profile_busy_row.visible = busy
        self.profile_progress_ring.visible = busy
        try:
            busy_txt = self.profile_busy_row.controls[1]
            if isinstance(busy_txt, ft.Text):
                busy_txt.value = message or "Generating profile…"
        except Exception:
            pass
        self.btn_profile_generate.disabled = busy
        self.btn_profile_enhance.disabled = busy
        self.btn_profile_close.disabled = busy
        self.profile_target_dd.disabled = busy
        self.profile_model_dd.disabled = busy
        if busy:
            self.btn_profile_confirm.visible = False
            self.btn_profile_regen.visible = False
            self.btn_profile_dismiss.visible = False
            self.profile_preview_tap.visible = False
            self.profile_preview_img.visible = False
            self.profile_preview_hint.visible = False
            self.profile_preview_label.value = message or "Generating profile…"
        self._sync_pack_ui()
        try:
            self.page.update()
        except Exception:
            pass

    def _profile_set_result_ui(self, path: str | None) -> None:
        if path and Path(path).is_file():
            self.profile_preview_img.src = path
            self.profile_preview_img.visible = True
            self.profile_preview_tap.visible = True
            self.profile_preview_hint.visible = True
            self.btn_profile_confirm.visible = True
            self.btn_profile_regen.visible = True
            self.btn_profile_dismiss.visible = True
            short = SLOT_SHORT.get(self._profile_pending_slot or "front", "slot")
            self.profile_preview_label.value = (
                f"{short} ready — click preview to enlarge · Confirm to fill slot"
            )
        else:
            self.profile_preview_img.visible = False
            self.profile_preview_tap.visible = False
            self.profile_preview_hint.visible = False
            self.btn_profile_confirm.visible = False
            self.btn_profile_regen.visible = False
            self.btn_profile_dismiss.visible = False
            if not self._profile_busy:
                self.profile_preview_label.value = ""

    async def _on_profile_preview_tap(self, e: ft.ControlEvent) -> None:
        path = self._profile_pending_path
        if path and Path(path).is_file():
            short = SLOT_SHORT.get(self._profile_pending_slot or "front", "Profile")
            self._open_preview(path, title=f"Profile · {short}")

    async def _on_profile_enhance(self, e: ft.ControlEvent) -> None:
        def _extra() -> dict[str, Any]:
            return {
                "workspace": "characters",
                "mode": "generate_profile",
                "target_slot": self._profile_slot_key(),
                "guidance": (
                    "Rewrite the optional note for identity-consistent profile "
                    "generation. Keep short. Do not invent a different person."
                ),
            }

        await run_prompt_enhance(
            page=self.page,
            state=self.state,
            prompt_field=self.profile_note,
            get_model=self._profile_model_choice,
            get_extra_context=_extra,
            status_ctrl=self.status,
            job_progress=self.job_progress,
            enhance_btn=self.btn_profile_enhance,
            busy_controls=[self.btn_profile_generate],
            context_label="profile note",
            allow_empty_with_context=True,
            busy_scope="characters",
        )

    def _profile_refs(self) -> list[str]:
        refs: list[str] = []
        for s in IDENTITY_SLOTS:
            p = (self._edit_identity.get(s) or "").strip()
            if p and Path(p).is_file() and p not in refs:
                refs.append(p)
        return refs

    async def _profile_generate(self, e: ft.ControlEvent | None = None) -> None:
        await self._run_profile_generate(regen=False)

    async def _profile_regenerate(self, e: ft.ControlEvent | None = None) -> None:
        await self._run_profile_generate(regen=True)

    async def _run_profile_generate(self, *, regen: bool) -> None:
        if self._profile_busy or self._bg_busy:
            return
        if not self._editing_id and not self._create_mode:
            self._set_status("Open Edit or New character first.", error=True)
            return
        refs = self._profile_refs()
        if not refs:
            self._set_status(
                "Need at least one identity still as reference.", error=True
            )
            return
        slot = self._profile_slot_key()
        short = SLOT_SHORT[slot]
        from media_studio.secrets_store import has_fal_key

        if not has_fal_key():
            self._set_status("FAL API key required — open Settings.", error=True)
            return
        if self.state.is_busy("characters"):
            return
        if not self.state.try_busy("characters"):
            return

        model = self._profile_model_choice()
        note = (self.profile_note.value or "").strip()
        prompt = profile_prompt_for_slot(slot, note=note)
        self._refresh_profile_cost()
        self._profile_set_busy(
            True,
            message=f"Generating {short} profile…",
        )
        self.job_progress.start(f"Generate {short} profile…", self.page)
        self._set_status(f"Generating {short} from {len(refs)} ref(s)…")

        def on_progress(msg: str) -> None:
            self.job_progress.set_message(classify_progress(msg), self.page)
            try:
                busy_txt = self.profile_busy_row.controls[1]
                if isinstance(busy_txt, ft.Text):
                    busy_txt.value = msg or f"Generating {short}…"
                self.profile_preview_label.value = msg
                self.page.update()
            except Exception:
                pass

        try:
            from media_studio.job_context import to_thread_with_job
            from media_studio.services import generate

            primary = refs[0]
            extras = refs[1:]
            params_json = edit_params_json_for_resolution(self._profile_resolution())
            result = await to_thread_with_job(
                self.state,
                generate,
                prompt,
                model_choice=model,
                image_file=primary,
                extra_image_files=extras,
                output_dir=self.state.output_dir,
                on_progress=on_progress,
                scenario="character-profile",
                parameters_json=params_json,
            )
            path = result.primary_image if result.ok else None
            if not path and result.ok:
                imgs = result.image_paths or []
                path = imgs[0] if imgs else None
            if result.ok and path and Path(path).is_file():
                self._profile_pending_path = str(path)
                self._profile_pending_slot = slot
                self._profile_char_id = self._editing_id
                self._profile_set_busy(False)
                self._profile_set_result_ui(str(path))
                self.job_progress.finish_ok(
                    f"{short} ready — Confirm to fill slot", self.page
                )
                self._set_status(
                    f"{short} profile ready — Confirm to fill slot"
                    + (" (regenerated)" if regen else "")
                    + "."
                )
            else:
                err = getattr(result, "status", None) or "Profile generate failed."
                self._profile_set_busy(False)
                self._profile_set_result_ui(None)
                self.job_progress.finish_error(err, self.page)
                self._set_status(err, error=True)
        except Exception as exc:
            self._profile_set_busy(False)
            self._profile_set_result_ui(None)
            self.job_progress.finish_error(str(exc), self.page)
            self._set_status(str(exc), error=True)
            traceback.print_exc()
        finally:
            self.state.clear_busy("characters")
            self._sync_pack_ui()
            try:
                self.page.update()
            except Exception:
                pass

    async def _profile_confirm(self, e: ft.ControlEvent) -> None:
        if self._profile_busy:
            return
        path = self._profile_pending_path
        slot = self._profile_pending_slot or self._profile_slot_key()
        if not path or not Path(path).is_file():
            self._set_status("No profile preview to confirm.", error=True)
            return
        self._edit_identity[slot] = path
        if slot == "front":
            self._set_still(path)
        char_id = self._profile_char_id or self._editing_id
        if char_id:
            try:
                set_character_slot(char_id, slot, path)
            except Exception as exc:
                self._set_status(str(exc), error=True)
                return
        self._sync_pack_ui()
        short = SLOT_SHORT.get(slot, slot)
        self._set_status(f"Filled {short} from generated profile.")
        self._profile_dismiss_result()
        self.refresh()

    def _profile_dismiss_result(self, e: ft.ControlEvent | None = None) -> None:
        if self._profile_busy:
            return
        self._profile_pending_path = None
        self._profile_pending_slot = None
        self._profile_set_result_ui(None)
        try:
            self.page.update()
        except Exception:
            pass

    # ----- costume swap -----

    def _costume_model_choice(self) -> str:
        return (self.costume_model_dd.value or preferred_costume_model()).strip()

    def _costume_resolution(self) -> str | None:
        if not getattr(self.costume_res_dd, "visible", True):
            return None
        return (self.costume_res_dd.value or "").strip() or None

    def _costume_sync_res_options(self) -> None:
        opts = edit_resolution_options(self._costume_model_choice())
        from media_studio.flet_theme import dropdown_options
        from media_studio.character_store import resolution_display_label

        if not opts:
            self.costume_res_dd.visible = False
            return
        self.costume_res_dd.visible = True
        self.costume_res_dd.options = dropdown_options(opts)
        if self.costume_res_dd.value not in opts:
            self.costume_res_dd.value = default_practical_resolution(opts)
        if len(opts) == 1:
            self.costume_res_dd.label = f"Resolution · {resolution_display_label(opts[0])}"
        else:
            self.costume_res_dd.label = "Resolution"

    def _set_costume_busy(self, busy: bool, *, message: str = "") -> None:
        self._costume_busy = busy
        self.costume_busy_row.visible = busy
        self.costume_progress_ring.visible = busy
        try:
            busy_txt = self.costume_busy_row.controls[1]
            if isinstance(busy_txt, ft.Text):
                busy_txt.value = message or "Generating costume…"
        except Exception:
            pass
        self.btn_costume_generate.disabled = busy
        self.btn_costume_enhance.disabled = busy
        self.btn_costume_cancel.disabled = busy
        try:
            self.costume_model_dd.disabled = busy
        except Exception:
            pass
        try:
            self.page.update()
        except Exception:
            pass

    def _show_costume_errors(self) -> None:
        if not self._costume_errors:
            self.costume_errors_text.value = ""
            self.costume_errors_text.visible = False
            return
        lines = [
            f"· {SLOT_SHORT.get(s, s)}: {err}"
            for s, err in self._costume_errors.items()
        ]
        self.costume_errors_text.value = "Failed slots:\n" + "\n".join(lines)
        self.costume_errors_text.visible = True

    def _open_costume(self, c: SavedCharacter) -> None:
        self._costume_char_id = c.id
        self._costume_char_name = c.name
        self._costume_outfit = ""
        self._costume_results = {}
        self._costume_errors = {}
        self._costume_refs = c.all_stills()
        self._costume_model = preferred_costume_model()
        # Sync dropdown label
        from media_studio.fal.models import resolve_image_edit_model

        spec = resolve_image_edit_model(self._costume_model)
        labs = multi_ref_image_edit_labels()
        if spec and spec.label in labs:
            self.costume_model_dd.value = spec.label
        elif labs:
            self.costume_model_dd.value = labs[0]
        self._costume_sync_res_options()
        self.costume_char_label.value = f"{c.name} · {c.slot_summary()}"
        self.costume_prompt.value = ""
        self.costume_variant_name.value = ""
        self.costume_variant_name.visible = False
        self.costume_errors_text.visible = False
        self.costume_errors_text.value = ""
        self.costume_busy_row.visible = False
        n = c.angle_count()
        self.costume_cost.value = estimate_costume_swap_cost(
            n,
            model_key=self._costume_model_choice(),
            resolution=self._costume_resolution(),
        )
        self.costume_results_row.controls.clear()
        self.btn_costume_save_new.visible = False
        self.btn_costume_replace.visible = False
        self.btn_costume_discard.visible = False
        self.costume_box.visible = True
        self._set_status(f"Costume swap ready for {c.name} ({n} angle(s)).")
        try:
            self.page.update()
        except Exception:
            pass

    def _costume_close(self, e: ft.ControlEvent | None = None) -> None:
        if self._costume_busy:
            return
        self.costume_box.visible = False
        self._costume_char_id = None
        self._costume_results = {}
        self._costume_errors = {}
        try:
            self.page.update()
        except Exception:
            pass

    async def _on_costume_prompt_change(self, e: ft.ControlEvent) -> None:
        self._refresh_costume_cost()

    async def _on_costume_model_change(self, e: ft.ControlEvent | None = None) -> None:
        self._costume_model = self._costume_model_choice()
        self._costume_sync_res_options()
        self._refresh_costume_cost()
        try:
            self.page.update()
        except Exception:
            pass

    def _refresh_costume_cost(self) -> None:
        if not self._costume_char_id:
            return
        ch = next(
            (c for c in load_characters() if c.id == self._costume_char_id),
            None,
        )
        n = ch.angle_count() if ch else 0
        model = self._costume_model_choice()
        self._costume_model = model
        self.costume_cost.value = estimate_costume_swap_cost(
            n, model_key=model, resolution=self._costume_resolution()
        )

    async def _on_costume_enhance(self, e: ft.ControlEvent) -> None:
        def _extra() -> dict[str, Any]:
            return {
                "workspace": "characters",
                "mode": "costume_swap",
                "character": self._costume_char_name,
                "guidance": (
                    "Rewrite the wardrobe/outfit description for an image-edit model. "
                    "Keep identity lock language out — only clothing, fabric, color, style. "
                    "Concise and concrete."
                ),
            }

        await run_prompt_enhance(
            page=self.page,
            state=self.state,
            prompt_field=self.costume_prompt,
            get_model=self._costume_model_choice,
            get_extra_context=_extra,
            status_ctrl=self.status,
            job_progress=self.job_progress,
            enhance_btn=self.btn_costume_enhance,
            busy_controls=[self.btn_costume_generate],
            context_label="costume outfit prompt",
            allow_empty_with_context=False,
            busy_scope="characters",
        )

    async def _costume_generate_all(self, e: ft.ControlEvent) -> None:
        if self._costume_busy:
            return
        outfit = (self.costume_prompt.value or "").strip()
        if not outfit:
            self._set_status("Describe the new wardrobe / look first.", error=True)
            return
        if not self._costume_char_id:
            return
        ch = next(
            (c for c in load_characters() if c.id == self._costume_char_id),
            None,
        )
        if not ch:
            self._set_status("Character not found.", error=True)
            return
        slots = ch.filled_slots()
        if not slots:
            self._set_status("No identity stills on this character.", error=True)
            return
        from media_studio.secrets_store import has_fal_key

        if not has_fal_key():
            self._set_status("FAL API key required — open Settings.", error=True)
            return
        if self.state.is_busy("characters"):
            return
        if not self.state.try_busy("characters"):
            return

        model = self._costume_model_choice()
        self._costume_model = model
        self._costume_outfit = outfit
        self._costume_refs = ch.all_stills()
        self._costume_results = {}
        self._costume_errors = {}
        n = len(slots)
        self._refresh_costume_cost()
        self._set_costume_busy(
            True, message=f"Generating costume · {n} angle(s)…"
        )
        self.job_progress.start(f"Costume swap · {n} image(s)…", self.page)
        self._set_status(f"Generating costume for {ch.name} ({n} angles)…")
        self.costume_errors_text.visible = False

        def on_progress(msg: str) -> None:
            self.job_progress.set_message(classify_progress(msg), self.page)
            try:
                busy_txt = self.costume_busy_row.controls[1]
                if isinstance(busy_txt, ft.Text):
                    busy_txt.value = msg or "Generating costume…"
                self.page.update()
            except Exception:
                pass

        try:
            for i, (slot, _path) in enumerate(slots, start=1):
                short = SLOT_SHORT.get(slot, slot)
                on_progress(f"{short} ({i}/{n})…")
                path, err = await self._run_costume_slot(
                    slot=slot,
                    outfit=outfit,
                    refs=self._costume_refs,
                    on_progress=on_progress,
                )
                if path:
                    self._costume_results[slot] = path
                    self._costume_errors.pop(slot, None)
                else:
                    self._costume_errors[slot] = err or "Unknown error (no image returned)"
                self._rebuild_costume_results_ui()
                self._show_costume_errors()
                try:
                    self.page.update()
                except Exception:
                    pass

            ok_n = len(self._costume_results)
            fail_n = len(self._costume_errors)
            if ok_n:
                self.job_progress.finish_ok(
                    f"Costume ready · {ok_n} ok"
                    + (f" · {fail_n} failed" if fail_n else ""),
                    self.page,
                )
                msg = (
                    f"Costume: {ok_n}/{n} angle(s) ready. "
                    "Name the costume, regenerate failed slots, then save under parent."
                )
                if fail_n:
                    fails = ", ".join(
                        f"{SLOT_SHORT.get(s, s)}: {e[:80]}"
                        for s, e in self._costume_errors.items()
                    )
                    msg += f" Failures — {fails}"
                    self._set_status(msg, error=True)
                else:
                    self._set_status(msg)
                # Prefill short costume name from outfit prompt (editable)
                outfit_txt = self._costume_outfit or (
                    self.costume_prompt.value or ""
                ).strip()
                self.costume_variant_name.value = short_outfit_label(outfit_txt)
                self.costume_variant_name.visible = True
                self.btn_costume_save_new.visible = True
                self.btn_costume_replace.visible = True
                self.btn_costume_discard.visible = True
            else:
                summary = "; ".join(
                    f"{SLOT_SHORT.get(s, s)}: {e}"
                    for s, e in self._costume_errors.items()
                )
                self.job_progress.finish_error(
                    summary or "Costume swap failed for all slots.",
                    self.page,
                )
                self._set_status(
                    f"Costume swap failed for all slots. {summary}",
                    error=True,
                )
                self._show_costume_errors()
        except Exception as exc:
            self.job_progress.finish_error(str(exc), self.page)
            self._set_status(f"Costume error: {exc}", error=True)
            traceback.print_exc()
        finally:
            self._set_costume_busy(False)
            self.state.clear_busy("characters")
            try:
                self.page.update()
            except Exception:
                pass

    async def _run_costume_slot(
        self,
        *,
        slot: str,
        outfit: str,
        refs: list[str],
        on_progress: Any,
    ) -> tuple[str | None, str | None]:
        """One I2I call for a single angle. Returns (path, error_message)."""
        from media_studio.job_context import to_thread_with_job
        from media_studio.services import generate

        short = SLOT_SHORT.get(slot, slot)
        ch = (
            next((c for c in load_characters() if c.id == self._costume_char_id), None)
            if self._costume_char_id
            else None
        )
        primary = ch.get_slot(slot) if ch else None
        if not primary or not Path(primary).is_file():
            primary = refs[0] if refs else None
        if not primary or not Path(primary).is_file():
            return None, f"{short}: no source still for this angle"
        extras = [r for r in refs if r != primary and Path(r).is_file()]
        prompt = costume_prompt_for_slot(outfit, slot)
        model = self._costume_model_choice()
        params_json = edit_params_json_for_resolution(self._costume_resolution())
        on_progress(f"{short}…")
        try:
            result = await to_thread_with_job(
                self.state,
                generate,
                prompt,
                model_choice=model,
                image_file=primary,
                extra_image_files=extras,
                output_dir=self.state.output_dir,
                on_progress=on_progress,
                scenario="character-costume",
                parameters_json=params_json,
            )
        except Exception as exc:
            return None, f"{short}: {exc}"
        if not result.ok:
            err = (result.status or "API returned not ok").strip()
            return None, f"{short}: {err}"
        path = result.primary_image
        if not path:
            imgs = result.image_paths or []
            path = imgs[0] if imgs else None
        if path and Path(path).is_file():
            return str(path), None
        return None, f"{short}: no image file in response"

    def _rebuild_costume_results_ui(self) -> None:
        self.costume_results_row.controls.clear()
        # Show successes in slot order; also show failed slots with regen
        shown: set[str] = set()
        for slot in IDENTITY_SLOTS:
            if slot in self._costume_results:
                path = self._costume_results[slot]
                img = ft.Image(
                    src=path,
                    width=_RESULT_THUMB,
                    height=_RESULT_THUMB,
                    fit=ft.BoxFit.COVER,
                    border_radius=6,
                )
                btn_regen = ft.OutlinedButton(
                    content="Regenerate",
                    on_click=self._make_costume_regen(slot),
                    style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
                    height=32,
                    disabled=self._costume_busy,
                    tooltip=f"Re-run only {SLOT_SHORT[slot]} (~1 image)",
                )
                self.costume_results_row.controls.append(
                    ft.Container(
                        content=ft.Column(
                            [
                                ft.Text(
                                    SLOT_SHORT[slot],
                                    size=FONT_SM,
                                    color=TEXT,
                                    weight=ft.FontWeight.W_600,
                                ),
                                ft.GestureDetector(
                                    content=img,
                                    on_tap=self._make_preview_path(
                                        path, f"Costume · {SLOT_SHORT[slot]}"
                                    ),
                                ),
                                btn_regen,
                            ],
                            spacing=4,
                            tight=True,
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        border=ft.Border.all(1, BORDER),
                        border_radius=8,
                        padding=8,
                    )
                )
                shown.add(slot)
            elif slot in self._costume_errors:
                err = self._costume_errors[slot]
                btn_regen = ft.OutlinedButton(
                    content="Retry",
                    on_click=self._make_costume_regen(slot),
                    style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
                    height=32,
                    disabled=self._costume_busy,
                    tooltip=f"Retry {SLOT_SHORT[slot]}",
                )
                self.costume_results_row.controls.append(
                    ft.Container(
                        content=ft.Column(
                            [
                                ft.Text(
                                    f"{SLOT_SHORT[slot]} · failed",
                                    size=FONT_SM,
                                    color="#e57373",
                                    weight=ft.FontWeight.W_600,
                                ),
                                ft.Text(
                                    err[:120],
                                    size=11,
                                    color=TEXT_MUTED,
                                    max_lines=4,
                                    width=_RESULT_THUMB + 20,
                                ),
                                btn_regen,
                            ],
                            spacing=4,
                            tight=True,
                        ),
                        border=ft.Border.all(1, "#e57373"),
                        border_radius=8,
                        padding=8,
                        width=_RESULT_THUMB + 40,
                    )
                )
                shown.add(slot)

    def _make_costume_regen(self, slot: str):
        async def _click(_e: ft.ControlEvent) -> None:
            await self._costume_regen_one(slot)

        return _click

    async def _costume_regen_one(self, slot: str) -> None:
        if self._costume_busy:
            return
        outfit = (self.costume_prompt.value or self._costume_outfit or "").strip()
        if not outfit:
            self._set_status("Outfit prompt missing.", error=True)
            return
        if not self._costume_refs:
            self._set_status("No identity refs for regenerate.", error=True)
            return
        from media_studio.secrets_store import has_fal_key

        if not has_fal_key():
            self._set_status("FAL API key required.", error=True)
            return
        if self.state.is_busy("characters"):
            return
        if not self.state.try_busy("characters"):
            return

        short = SLOT_SHORT.get(slot, slot)
        model = self._costume_model_choice()
        self.costume_cost.value = estimate_costume_swap_cost(1, model_key=model)
        self._set_costume_busy(True, message=f"Regenerating {short}…")
        self.job_progress.start(f"Regenerate {short}…", self.page)

        def on_progress(msg: str) -> None:
            self.job_progress.set_message(classify_progress(msg), self.page)
            try:
                busy_txt = self.costume_busy_row.controls[1]
                if isinstance(busy_txt, ft.Text):
                    busy_txt.value = msg or f"Regenerating {short}…"
                self.page.update()
            except Exception:
                pass

        try:
            path, err = await self._run_costume_slot(
                slot=slot,
                outfit=outfit,
                refs=self._costume_refs,
                on_progress=on_progress,
            )
            if path:
                self._costume_results[slot] = path
                self._costume_errors.pop(slot, None)
                self._rebuild_costume_results_ui()
                self._show_costume_errors()
                self.job_progress.finish_ok(f"{short} updated", self.page)
                self._set_status(f"Regenerated {short} only.")
                self.btn_costume_save_new.visible = True
                self.btn_costume_replace.visible = True
                self.btn_costume_discard.visible = True
            else:
                self._costume_errors[slot] = err or f"{short}: regenerate failed"
                self._rebuild_costume_results_ui()
                self._show_costume_errors()
                self.job_progress.finish_error(err or "Regenerate failed", self.page)
                self._set_status(err or "Regenerate failed.", error=True)
        except Exception as exc:
            self.job_progress.finish_error(str(exc), self.page)
            self._set_status(str(exc), error=True)
            traceback.print_exc()
        finally:
            self._set_costume_busy(False)
            self.state.clear_busy("characters")
            self._refresh_costume_cost()
            try:
                self.page.update()
            except Exception:
                pass

    async def _costume_save_new(self, e: ft.ControlEvent) -> None:
        if not self._costume_results:
            self._set_status("No costume results to save.", error=True)
            return
        outfit = self._costume_outfit or (self.costume_prompt.value or "").strip()
        name = (self.costume_variant_name.value or "").strip()
        if not name:
            name = short_outfit_label(outfit)
            self.costume_variant_name.value = name
        # Prefer front result as primary still for add_character
        identity: dict[str, str] = {}
        for slot in IDENTITY_SLOTS:
            if slot in self._costume_results and Path(
                self._costume_results[slot]
            ).is_file():
                identity[slot] = self._costume_results[slot]
        if not identity:
            self._set_status("No valid result stills.", error=True)
            return
        front = identity.get("front") or next(iter(identity.values()))
        parent = (self._costume_char_id or "").strip() or None
        if not parent:
            self._set_status(
                "No parent character for this costume — reopen Costume swap from a base.",
                error=True,
            )
            return
        notes = outfit if outfit else f"Costume of {self._costume_char_name or 'parent'}"
        try:
            entry = add_character(
                name=name,
                still_path=front,
                notes=notes,
                identity=identity,
                parent_id=parent,
            )
            if not entry.parent_id:
                # Should not happen if parent was valid; force link
                update_character(entry.id, parent_id=parent)
                entry = next(
                    (c for c in load_characters() if c.id == entry.id),
                    entry,
                )
            self._costumes_expanded.add(parent)
            self._set_status(f"Saved costume under parent: {entry.name}")
            self._costume_discard_results()
            self.refresh()
        except Exception as exc:
            self._set_status(str(exc), error=True)

    async def _costume_replace_confirm(self, e: ft.ControlEvent) -> None:
        if not self._costume_char_id or not self._costume_results:
            return
        from media_studio.flet_dialogs import show_dialog, close_dialog

        async def _yes(_e: ft.ControlEvent) -> None:
            close_dialog(self.page, dlg)
            await self._costume_replace_apply()

        async def _no(_e: ft.ControlEvent) -> None:
            close_dialog(self.page, dlg)

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Replace identity angles?"),
            content=ft.Text(
                f"Overwrite Front / Side / Close-up on “{self._costume_char_name}” "
                "with costume results? This cannot be undone.",
                size=FONT_SM,
                color=TEXT,
            ),
            actions=[
                ft.TextButton(content="Cancel", on_click=_no),
                ft.FilledButton(
                    content="Replace",
                    on_click=_yes,
                    style=ft.ButtonStyle(bgcolor=ACCENT_BRIGHT, color=TEXT),
                ),
            ],
        )
        show_dialog(self.page, dlg)

    async def _costume_replace_apply(self) -> None:
        if not self._costume_char_id or not self._costume_results:
            return
        identity = {
            s: p
            for s, p in self._costume_results.items()
            if p and Path(p).is_file()
        }
        # Keep any slots not regenerated
        ch = next(
            (c for c in load_characters() if c.id == self._costume_char_id),
            None,
        )
        if ch:
            for s, p in ch.normalized_identity().items():
                if s not in identity:
                    identity[s] = p
        try:
            updated = update_character(self._costume_char_id, identity=identity)
            if updated:
                self._set_status(f"Replaced angles on {updated.name}")
                self._costume_discard_results()
                if self._editing_id == updated.id:
                    self._edit_identity = {
                        s: updated.get_slot(s) or "" for s in IDENTITY_SLOTS
                    }
                    prim = updated.primary_still()
                    if prim:
                        self._set_still(prim)
                    self._sync_pack_ui()
                self.refresh()
            else:
                self._set_status("Replace failed.", error=True)
        except Exception as exc:
            self._set_status(str(exc), error=True)

    def _costume_discard_results(self, e: ft.ControlEvent | None = None) -> None:
        if self._costume_busy:
            return
        self._costume_results = {}
        self._costume_errors = {}
        self.costume_results_row.controls.clear()
        self.costume_errors_text.value = ""
        self.costume_errors_text.visible = False
        self.costume_variant_name.value = ""
        self.costume_variant_name.visible = False
        self.btn_costume_save_new.visible = False
        self.btn_costume_replace.visible = False
        self.btn_costume_discard.visible = False
        try:
            self.page.update()
        except Exception:
            pass

    # ----- variation (kept) -----

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
            return
        base = ""
        if self._variation_source_id:
            ch = next(
                (c for c in load_characters() if c.id == self._variation_source_id),
                None,
            )
            if ch:
                base = ch.name
        name = f"{base} · variation" if base else "Character variation"
        try:
            entry = add_character(
                name=name,
                still_path=self._variation_path,
                notes=f"Variation of {base}" if base else "I2I variation",
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
                self._variation_source_id, self._variation_path
            )
            if updated:
                self._dismiss_variation()
                self._set_status(
                    f"Filled empty slot on {updated.name} ({updated.slot_summary()})"
                )
                self.refresh()
            else:
                self._set_status("Character not found.", error=True)
        except Exception as exc:
            self._set_status(str(exc), error=True)

    async def _variation_replace_primary(self, e: ft.ControlEvent) -> None:
        if not self._variation_path or not self._variation_source_id:
            return
        try:
            updated = set_character_slot(
                self._variation_source_id, "front", self._variation_path
            )
            if updated:
                self._dismiss_variation()
                self._set_status(f"Front replaced on {updated.name}")
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
            self._set_status("Still file missing.", error=True)
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
            path = result.primary_image if result.ok else None
            if not path and result.ok:
                imgs = result.image_paths or []
                path = imgs[0] if imgs else None
            if result.ok and path and Path(path).is_file():
                self.job_progress.finish_ok("Variation ready", self.page)
                self._show_variation(str(path), source_id=c.id)
                self._set_status(f"Variation ready for {c.name}.")
            else:
                err = result.status or "Variation failed."
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
        bases = list_base_characters()
        self.list_host.controls.clear()
        n_base = len(bases)
        n_all = len(load_characters())
        self.list_count.value = (
            f"{n_base} character(s)"
            + (f" · {n_all - n_base} costume(s)" if n_all > n_base else "")
            if n_base
            else ""
        )
        self.empty_state.visible = n_base == 0
        for c in bases:
            kids = list_costume_children(c.id)
            self.list_host.controls.append(self._card(c, children=kids))
        try:
            self.page.update()
        except Exception:
            pass

    def _thumb_control(self, path: str | None, *, title: str) -> ft.Control:
        still_ok = bool(path and Path(path).is_file())
        if still_ok and path:
            img = ft.Image(
                src=path,
                width=_THUMB,
                height=_THUMB,
                fit=ft.BoxFit.COVER,
                border_radius=6,
            )
            return ft.GestureDetector(
                content=img,
                on_tap=self._make_preview_path(path, title),
            )
        return ft.Container(
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

    def _card(
        self,
        c: SavedCharacter,
        *,
        children: list[SavedCharacter] | None = None,
        nested: bool = False,
    ) -> ft.Control:
        primary = c.primary_still()
        still_ok = bool(primary and Path(primary).is_file())
        thumb = self._thumb_control(primary, title=c.name)
        notes = c.display_notes() or "—"
        pack = c.slot_summary()
        lock_icon = " 🔒" if c.locked else ""
        name_txt = ft.Text(
            f"{c.name}{lock_icon}",
            size=FONT_SM,
            color=TEXT,
            weight=ft.FontWeight.W_600,
            max_lines=1,
        )
        notes_txt = ft.Text(
            f"{notes} · {pack}", size=FONT_SM, color=TEXT_MUTED, max_lines=2
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
            tooltip="Sets Front (or first available) as Motion Sync character",
        )
        btn_costume = ft.OutlinedButton(
            content="Costume swap",
            on_click=self._make_open_costume(c),
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
            height=36,
            disabled=not still_ok or nested,
            visible=not nested,
            tooltip="Change outfit — saves under this character as a costume",
        )
        btn_var = ft.OutlinedButton(
            content="Generate variation",
            on_click=self._make_generate_variation(c),
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
            height=36,
            disabled=not still_ok,
            tooltip="Optional I2I variation",
        )
        btn_edit = ft.OutlinedButton(
            content="Edit",
            on_click=self._make_edit(c),
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
            height=36,
        )
        btn_lock = ft.TextButton(
            content="Unlock" if c.locked else "Lock",
            icon=ft.Icons.LOCK_OPEN if c.locked else ft.Icons.LOCK_OUTLINE,
            on_click=self._make_toggle_lock(c),
            style=ft.ButtonStyle(color=ACCENT if c.locked else TEXT_MUTED),
            height=36,
            tooltip="Protect from auto-delete when retention cleanup runs",
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

        actions = [
            btn_use,
            btn_costume,
            btn_var,
            btn_edit,
            btn_lock,
            btn_delete,
            btn_folder,
        ]

        kids = list(children) if children is not None else []
        costumes_col: ft.Control | None = None
        if not nested:
            # Always show Costumes row (collapsed by default)
            expanded = c.id in self._costumes_expanded
            n_kids = len(kids)
            count_label = f"{n_kids}" if n_kids else "none"
            toggle = ft.TextButton(
                content=(
                    f"▾ Costumes ({count_label})"
                    if expanded
                    else f"▸ Costumes ({count_label})"
                ),
                on_click=self._make_toggle_costumes(c.id),
                style=ft.ButtonStyle(color=ACCENT),
                tooltip="Costume variants saved under this character",
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
                    "No costumes yet — use Costume swap",
                    size=FONT_SM,
                    color=TEXT_MUTED,
                    visible=expanded,
                )
            costumes_col = ft.Column(
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
        if costumes_col is not None:
            body.controls.append(costumes_col)

        return ft.Container(
            content=ft.Row(
                [thumb, body],
                spacing=12,
                vertical_alignment=ft.CrossAxisAlignment.START,
            ),
            bgcolor=PANEL if nested else PANEL_ELEVATED,
            border=ft.Border.all(1, ACCENT if c.locked else BORDER),
            border_radius=8,
            padding=10 if not nested else 8,
            margin=ft.Margin.only(left=16) if nested else None,
        )

    def _make_toggle_costumes(self, parent_id: str):
        async def _click(_e: ft.ControlEvent) -> None:
            if parent_id in self._costumes_expanded:
                self._costumes_expanded.discard(parent_id)
            else:
                self._costumes_expanded.add(parent_id)
            self.refresh()

        return _click

    def _make_toggle_lock(self, c: SavedCharacter):
        async def _click(_e: ft.ControlEvent) -> None:
            updated = set_character_locked(c.id, not c.locked)
            if updated:
                self._set_status(
                    f"{'Locked' if updated.locked else 'Unlocked'}: {updated.name}"
                )
                self.refresh()
            else:
                self._set_status("Could not update lock.", error=True)

        return _click

    def _make_open_costume(self, c: SavedCharacter):
        async def _click(_e: ft.ControlEvent) -> None:
            self._open_costume(c)

        return _click

    def _make_edit(self, c: SavedCharacter):
        async def _click(_e: ft.ControlEvent) -> None:
            self._editing_id = c.id
            pack = c.normalized_identity()
            self._edit_identity = {s: pack.get(s, "") for s in IDENTITY_SLOTS}
            self.name_field.value = c.name
            self.notes_field.value = c.notes or ""
            self.btn_save.content = "Save changes"
            self.btn_cancel_edit.visible = True
            primary = c.primary_still()
            if primary and Path(primary).is_file():
                self._set_still(primary)
            else:
                self._clear_still()
            self._sync_pack_ui()
            self._set_status(f"Editing: {c.name} · {c.slot_summary()}")
            try:
                self.page.update()
            except Exception:
                pass

        return _click

    def _make_delete(self, c: SavedCharacter):
        async def _click(_e: ft.ControlEvent) -> None:
            try:
                ok = delete_character(c.id)
            except CharacterHasChildrenError as exc:
                await self._confirm_delete_with_children(c, exc.children)
                return
            if ok:
                self._after_delete(c)
            else:
                self._set_status("Delete failed.", error=True)

        return _click

    def _after_delete(self, c: SavedCharacter) -> None:
        if self._editing_id == c.id:
            self._cancel_edit()
        if self._costume_char_id == c.id:
            self._costume_close()
        if self._variation_source_id == c.id:
            self._dismiss_variation()
        self._set_status(f"Deleted: {c.name}")
        self.refresh()

    async def _confirm_delete_with_children(
        self, c: SavedCharacter, children: list[SavedCharacter]
    ) -> None:
        async def _yes(_e: ft.ControlEvent) -> None:
            close_dialog(self.page, dlg)
            ok = delete_character(c.id, delete_children=True)
            if ok:
                self._after_delete(c)
            else:
                self._set_status("Delete failed.", error=True)

        async def _no(_e: ft.ControlEvent) -> None:
            close_dialog(self.page, dlg)

        n = len(children)
        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Delete character and costumes?"),
            content=ft.Text(
                f"“{c.name}” has {n} costume variant(s). "
                "Delete parent and all costumes, or cancel and delete costumes first.",
                size=FONT_SM,
                color=TEXT,
            ),
            actions=[
                ft.TextButton(content="Cancel", on_click=_no),
                ft.FilledButton(
                    content="Delete all",
                    on_click=_yes,
                    style=ft.ButtonStyle(bgcolor="#c62828", color=TEXT),
                ),
            ],
        )
        show_dialog(self.page, dlg)

    def _make_show_folder(self, c: SavedCharacter):
        async def _click(_e: ft.ControlEvent) -> None:
            path = c.primary_still() or c.still_path
            self._set_status(show_in_folder(path))

        return _click

    def _make_use_motion(self, c: SavedCharacter):
        async def _click(_e: ft.ControlEvent) -> None:
            primary = c.primary_still()
            if not primary or not Path(primary).is_file():
                self._set_status("Still file missing.", error=True)
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
                self._set_status(f"Motion Sync ← {c.name} (Front/primary)")
                try:
                    from media_studio.flet_dialogs import show_snack

                    show_snack(self.page, f"Motion Sync · Character: {c.name}")
                except Exception:
                    pass
            else:
                self._set_status(
                    f"Could not set Motion Sync character: {c.name}", error=True
                )

        return _click
