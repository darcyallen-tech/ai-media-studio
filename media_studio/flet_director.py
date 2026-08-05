"""
Director tab — multi-shot generation with ordered shots and a master brief.

Peer to Studio / Creative Vision / Frame Editor. Not for editing existing plates.
"""

from __future__ import annotations

import traceback
from pathlib import Path
from typing import TYPE_CHECKING, Any

import flet as ft

from media_studio.director_registry import (
    ASPECT_AUTO_FROM_STILL,
    AUDIO_STYLES,
    CAMERA_PRESETS,
    OUTPUT_MODES,
    STYLE_PACKS,
    TRANSITION_PREFS,
    DirectorPolish,
    DirectorShot,
    assemble_director_brief,
    balance_shot_times,
    count_director_ref_budget,
    director_shows_pack_toggle,
    director_is_single_ref_model,
    default_director_model,
    director_aspect_ui_choices,
    director_model_labels,
    estimate_director_cost,
    find_director_model,
    format_director_cost,
    format_shot_length_label,
    location_text_from_scene,
    multi_prompt_char_counts,
    multi_prompt_from_shots,
    normalize_transition,
    per_shot_timing_errors,
    preferred_character_still_bundle,
    resolve_angle_mode,
    still_is_low_res,
    validate_multi_prompt_limits,
    validate_shots,
)
from media_studio.director_service import run_director
from media_studio.flet_character_picker import CharacterPicker
from media_studio.flet_scene_picker import ScenePicker
from media_studio.flet_enhance import make_enhance_button, run_prompt_enhance
from media_studio.flet_pickers import pick_image
from media_studio.flet_progress import JobProgress, classify_progress
from media_studio.flet_dialogs import close_dialog, show_dialog, show_snack
from media_studio.flet_result_actions import make_result_action_row, show_result_actions
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
    PillNav,
    dropdown_options,
    label,
    make_estimated_cost_box,
    section_title,
    styled_dropdown,
)
from media_studio.director_keyframes import (
    KEYFRAME_MAX_PINS,
    KeyframePin,
    auto_spread_pin_times,
    format_keyframe_take_cost,
    keyframe_duration_choices,
    run_keyframe_take,
    validate_keyframe_pins,
)
from media_studio.flet_video_player import VideoResultPlayer
from media_studio.helper_none import HELPER_NONE

if TYPE_CHECKING:
    from media_studio.flet_app import StudioState

# Ref-still thumbnail size on shot rows (px)
_REF_THUMB = 64


def _dd(dd: ft.Dropdown) -> str | None:
    return dd.value


class DirectorView:
    """Director workspace: Multi-shot (cuts) + Keyframe Take (FLUX 3 continuous)."""

    def __init__(self, page: ft.Page, state: StudioState) -> None:
        self.page = page
        self.state = state
        self._result_path: str | None = None
        self._shots: list[dict[str, Any]] = []  # row widgets + data
        self._director_mode: str = "multi_shot"  # multi_shot | keyframe_take
        self._kf_pins: list[dict[str, Any]] = []
        self._kf_draft_cache: str | None = None

        self._mode_nav = PillNav(
            [
                ("multi_shot", "Multi-shot"),
                ("keyframe_take", "Keyframe Take"),
            ],
            selected="multi_shot",
            on_change=self._on_director_mode,
        )

        spec0 = default_director_model()
        labels = director_model_labels()
        self.model_dd = styled_dropdown(
            label_text="Model (multi-shot)",
            options=labels,
            value=spec0.label if spec0.label in labels else (labels[0] if labels else None),
            on_select=self._on_model,
            expand=True,
        )
        from media_studio.flet_model_hint import make_best_for_line, update_best_for_line

        self.model_best_for = make_best_for_line()
        update_best_for_line(self.model_best_for, self.model_dd.value, dropdown=self.model_dd)
        self.model_notes = ft.Text(
            spec0.notes or "",
            size=FONT_SM,
            color=TEXT_MUTED,
            max_lines=3,
        )

        dur_opts = [str(i) for i in (spec0.allowed_durations or range(3, 16))]
        self.dur_dd = styled_dropdown(
            label_text="Total duration (s)",
            options=dur_opts,
            value=str(spec0.default_duration_s),
            on_select=self._on_duration,
            expand=True,
        )
        _res_opts0 = list(getattr(spec0, "resolution_choices", None) or ())
        self.res_dd = styled_dropdown(
            label_text="Resolution",
            options=_res_opts0 or ["—"],
            value=(
                spec0.default_resolution
                if _res_opts0 and spec0.default_resolution in _res_opts0
                else (_res_opts0[0] if _res_opts0 else "—")
            ),
            on_select=self._refresh_cost,
            expand=True,
        )
        self.res_dd.visible = bool(_res_opts0)
        _aspect_opts0, _aspect_def0 = director_aspect_ui_choices(
            spec0, has_start_image=False
        )
        self.aspect_dd = styled_dropdown(
            label_text="Aspect",
            options=_aspect_opts0,
            value=_aspect_def0,
            on_select=self._refresh_cost,
            expand=True,
        )
        self.aspect_hint = ft.Text(
            "",
            size=FONT_SM,
            color=TEXT_MUTED,
            max_lines=2,
            visible=False,
        )
        self.style_dd = styled_dropdown(
            label_text="Style / genre pack",
            options=list(STYLE_PACKS.keys()),
            value="None",
            on_select=self._refresh_cost,
            expand=True,
        )
        self.gen_audio = ft.Checkbox(
            label="Generate audio (when supported)",
            value=bool(spec0.default_generate_audio),
            on_change=self._on_audio_toggle,
        )
        self.audio_style_dd = styled_dropdown(
            label_text="Audio style",
            options=list(AUDIO_STYLES),
            value="Soft bed only",
            on_select=self._on_polish_change,
            expand=True,
        )
        self.sfx_note = ft.TextField(
            label="SFX notes (optional)",
            hint_text='e.g. "whoosh on cut 2", "impact on land"',
            value="",
            dense=True,
            filled=True,
            fill_color=PANEL_ELEVATED,
            border_color=BORDER,
            color=TEXT,
            text_size=FONT_SM,
            on_change=self._on_polish_change,
        )
        self.cont_character = ft.Checkbox(
            label="Same character",
            value=True,
            on_change=self._on_same_character_toggle,
        )
        self.cont_location = ft.Checkbox(
            label="Same location",
            value=True,
            on_change=self._on_polish_change,
        )
        self.cont_time = ft.Checkbox(
            label="Same time of day",
            value=True,
            on_change=self._on_polish_change,
        )
        self.btn_apply_char_all = ft.TextButton(
            content="Apply character to all shots",
            icon=ft.Icons.PERSON_ADD_ALT,
            on_click=self._apply_character_to_all_shots,
            style=ft.ButtonStyle(color=ACCENT),
            tooltip=(
                "Copy the first bound character onto every shot "
                "(when Same character is on)."
            ),
            visible=True,
        )
        self.btn_apply_scene_all = ft.TextButton(
            content="Apply scene to all shots",
            icon=ft.Icons.LANDSCAPE,
            on_click=self._apply_scene_to_all_shots,
            style=ft.ButtonStyle(color=ACCENT),
            tooltip=(
                "Copy the first bound scene onto every shot "
                "(when Same location is on)."
            ),
            visible=True,
        )
        self.same_char_hint = ft.Text(
            "Character = who · Scene = where · Action = what happens. "
            "Same character / location: Apply to all shots. "
            "Multi-ref models use both stills; single-ref models keep Scene as text.",
            size=FONT_SM,
            color=TEXT_MUTED,
            max_lines=3,
        )
        self.scene_model_hint = ft.Text(
            "",
            size=FONT_SM,
            color=TEXT_MUTED,
            max_lines=2,
            visible=False,
        )
        self.transition_dd = styled_dropdown(
            label_text="Default transition (all gaps)",
            options=list(TRANSITION_PREFS),
            value="Hard cut",
            on_select=self._on_global_transition,
            expand=True,
        )
        self.transition_hint = ft.Text(
            "Hard cut · Soft dissolve · Continuous (no cut — refs as motion keyframes). "
            "Per-gap control sits between shot rows; default applies to every gap.",
            size=FONT_SM,
            color=TEXT_MUTED,
        )
        self.energy_curve = ft.Checkbox(
            label="Energy curve (restrained → peak → resolve)",
            value=False,
            on_change=self._on_polish_change,
        )
        self.vision_notes = ft.TextField(
            label="Vision notes (Enhance only)",
            hint_text='Tone / references — e.g. "like a Marvel movie". Not dumped raw into the model prompt.',
            value="",
            multiline=True,
            min_lines=2,
            max_lines=3,
            dense=True,
            filled=True,
            fill_color=PANEL_ELEVATED,
            border_color=BORDER,
            color=TEXT,
            text_size=FONT_SM,
        )
        self.output_mode_dd = styled_dropdown(
            label_text="Output",
            options=list(OUTPUT_MODES),
            value=OUTPUT_MODES[0],
            on_select=self._on_polish_change,
            expand=True,
        )
        self.cost_text, self.cost_box = make_estimated_cost_box(
            initial="Est. cost: —"
        )

        self.master = ft.TextField(
            label="Master brief (story, location, character lock, overall tone)",
            hint_text="Shared across all shots — continuity and world rules.",
            value="",
            multiline=True,
            min_lines=3,
            max_lines=6,
            dense=True,
            filled=True,
            fill_color=PANEL_ELEVATED,
            border_color=BORDER,
            color=TEXT,
            text_size=FONT_SM,
            on_change=self._on_polish_change,
        )
        self.assembled = ft.TextField(
            label="Assembled brief (master + shots — editable / Enhance target)",
            value="",
            multiline=True,
            min_lines=4,
            max_lines=8,
            dense=True,
            filled=True,
            fill_color=PANEL_ELEVATED,
            border_color=BORDER,
            color=TEXT,
            text_size=FONT_SM,
            on_change=self._on_polish_change,
        )
        self.prompt_count_label = ft.Text(
            "",
            size=FONT_SM,
            color=TEXT_MUTED,
            max_lines=3,
            selectable=True,
        )
        self._sync_audio_polish_visibility()

        self.shots_host = ft.Column(spacing=8, tight=True)
        self.btn_add_shot = ft.OutlinedButton(
            content="Add shot",
            icon=ft.Icons.ADD,
            on_click=self._add_shot,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
        )
        self.btn_auto_balance = ft.OutlinedButton(
            content="Auto-balance shot times",
            icon=ft.Icons.LINEAR_SCALE,
            on_click=self._auto_balance_times,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
            tooltip=(
                "Evenly split total duration across shots "
                "(contiguous, non-overlapping). Manual start/end stay editable."
            ),
        )
        self.shots_meta = ft.Text(
            "",
            size=FONT_SM,
            color=TEXT_MUTED,
        )
        self.timing_warn = ft.Text(
            "",
            size=FONT_SM,
            color="#ef9a9a",
            max_lines=3,
            visible=False,
        )
        self.ref_budget_label = ft.Text(
            "",
            size=FONT_SM,
            color=TEXT_MUTED,
            weight=ft.FontWeight.W_600,
            max_lines=2,
        )
        self.ref_budget_detail = ft.Text(
            "",
            size=11,
            color=TEXT_MUTED,
            max_lines=2,
        )
        # Multi-ref packs: character Front + scene Hero only vs full angle packs
        self._angle_mode_user: str = "auto"  # auto | front_only | full_pack
        self.angle_mode_label = ft.Text(
            "Ref pack:", size=FONT_SM, color=TEXT_MUTED
        )
        self.btn_pack_hero = ft.TextButton(
            content="Hero only",
            on_click=lambda _e: self._set_angle_mode("front_only"),
            style=ft.ButtonStyle(color=ACCENT),
        )
        self.btn_pack_full = ft.TextButton(
            content="Full pack",
            on_click=lambda _e: self._set_angle_mode("full_pack"),
            style=ft.ButtonStyle(color=TEXT_MUTED),
        )
        self.angle_mode_row = ft.Row(
            [
                self.angle_mode_label,
                self.btn_pack_hero,
                self.btn_pack_full,
            ],
            spacing=4,
            wrap=True,
            visible=False,
        )
        self.angle_mode_hint = ft.Text(
            "",
            size=11,
            color=TEXT_MUTED,
            max_lines=3,
            visible=False,
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
        self._ref_target_index: int = 0  # which shot receives strip stills
        # Global picker kept as a quick “active shot / apply source” helper only
        self.char_picker = CharacterPicker(
            page,
            on_select=self._on_global_character_picked,
            on_clear=self._on_character_picker_clear,
            label_text="Quick character (active shot)",
            compact=True,
        )
        self.btn_save_character = ft.TextButton(
            content="Save current still as character",
            icon=ft.Icons.PERSON_ADD_ALT_1_OUTLINED,
            on_click=self._save_as_character,
            style=ft.ButtonStyle(color=ACCENT),
            tooltip="Open Characters with the active shot's ref still (or last strip still)",
        )

        self.btn_generate = ft.FilledButton(
            content="Generate multi-shot",
            on_click=self._run,
            style=ft.ButtonStyle(bgcolor=ACCENT_BRIGHT, color=TEXT),
            height=42,
        )
        self.btn_enhance = make_enhance_button(on_click=self._on_enhance)
        self.btn_rebuild = ft.TextButton(
            content="Rebuild assembled brief",
            on_click=self._rebuild_assembled,
            style=ft.ButtonStyle(color=TEXT_MUTED),
        )
        self.status = ft.Text("", size=FONT_SM, color=TEXT_MUTED, max_lines=5)
        self.job_progress = JobProgress()
        self.player = VideoResultPlayer(page, height=300)
        try:
            self.player.control.expand = False
        except Exception:
            pass
        (
            self.result_actions_row,
            self.btn_folder,
            self.btn_resolve,
        ) = make_result_action_row(
            page,
            get_path=lambda: self._result_path,
            on_status=lambda msg, err: setattr(
                self.status, "value", msg
            ),
        )
        self.send_host = ft.Container(visible=False)

        self.state.on_keys_changed(self.apply_key_gates)
        # Seed 2 default shots for 10s total
        self._add_shot_row(start=0, end=5, camera="Push in")
        self._add_shot_row(start=5, end=10, camera="Orbit")
        self._sync_shots_meta()
        self._sync_apply_char_visibility()
        self._sync_scene_pickers_for_model()
        self._rebuild_assembled_text()
        self.cost_text.value = self._cost_label()
        self.apply_key_gates()

        # Orientation only — does not change models, cost, or Generate
        self.howto_box = ft.Container(
            content=ft.Column(
                [
                    ft.Text(
                        "How to use Director",
                        size=FONT_SM,
                        color=TEXT,
                        weight=ft.FontWeight.W_700,
                    ),
                    ft.Text(
                        "Modes: Multi-shot = hard cuts / multi_prompt (Kling). "
                        "Keyframe Take = pose plates → one continuous FLUX 3 motion.\n"
                        "Multi-shot: duration + model → shots → Character/Scene → Generate.\n"
                        "Keyframe Take: ordered pins (still + time) + global prompt → "
                        "one continuous take (max 10 pins @ 24 fps).\n"
                        "Tip: Multi-shot = cuts; Keyframe Take = continuous motion.",
                        size=FONT_SM,
                        color=TEXT_MUTED,
                    ),
                ],
                spacing=4,
                tight=True,
            ),
            bgcolor=PANEL_ELEVATED,
            border=ft.Border.all(1, BORDER),
            border_radius=8,
            padding=10,
        )

        # ----- Keyframe Take controls -----
        self._init_keyframe_take_controls()

    def _init_keyframe_take_controls(self) -> None:
        """UI for FLUX 3 Keyframe Take (continuous shot)."""
        self.kf_dur_dd = styled_dropdown(
            label_text="Duration (s)",
            options=keyframe_duration_choices(),
            value="8",
            on_select=self._on_kf_duration,
            expand=True,
        )
        self.kf_res_dd = styled_dropdown(
            label_text="Resolution",
            options=["720p", "1080p"],
            value="720p",
            on_select=self._on_kf_cost_refresh,
            expand=True,
        )
        self.kf_aspect_dd = styled_dropdown(
            label_text="Aspect",
            options=[
                "auto", "21:9", "2:1", "16:9", "4:3", "1:1", "3:4", "9:16",
            ],
            value="auto",
            on_select=self._on_kf_cost_refresh,
            expand=True,
        )
        self.kf_audio = ft.Checkbox(
            label="Generate audio",
            value=True,
            on_change=self._on_kf_cost_refresh,
        )
        self.kf_draft = ft.Checkbox(
            label="Draft first (cheaper preview)",
            value=False,
            on_change=self._on_kf_cost_refresh,
        )
        self.kf_prompt = ft.TextField(
            label="Global motion prompt (continuous take)",
            multiline=True,
            min_lines=3,
            max_lines=8,
            dense=True,
            filled=True,
            fill_color=PANEL_ELEVATED,
            border_color=BORDER,
            color=TEXT,
            text_size=FONT_SM,
            hint_text=(
                "One continuous shot — layout lock from pins, then action + audio. "
                "No hard-cut multi-shot language."
            ),
        )
        self.kf_pins_host = ft.Column(spacing=6, tight=True)
        self.kf_pins_meta = ft.Text(
            "Pins 0 / 10", size=FONT_SM, color=TEXT_MUTED
        )
        self.btn_kf_add_pin = ft.OutlinedButton(
            content="Add from Library / disk",
            icon=ft.Icons.PHOTO_LIBRARY_OUTLINED,
            on_click=self._kf_add_pin_pick,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
            tooltip="Pick a still from disk (Library exports live under outputs/)",
        )
        self.btn_kf_auto_times = ft.TextButton(
            content="Auto-spread times",
            icon=ft.Icons.TIMELINE,
            on_click=self._kf_auto_spread,
            style=ft.ButtonStyle(color=ACCENT),
            tooltip="Evenly place pin times from 0s to duration",
        )
        self.kf_prev_strip = PreviousSourcesStrip(
            self.page,
            get_output_dir=lambda: self.state.output_dir,
            on_load=self._kf_on_prev_still,
            media_kind="image",
            max_items=8,
        )
        self.kf_prev_strip.label.value = "Previously used (click to add pin)"
        self.kf_resolve_strip = ResolveSourcesStrip(
            self.page,
            on_load=self._kf_on_prev_still,
            media_kind="image",
        )
        self._lightbox_dialog: ft.AlertDialog | None = None
        self._lightbox_img: ft.Image | None = None
        self._lightbox_title: ft.Text | None = None
        self.kf_char_picker = CharacterPicker(
            self.page,
            on_select=self._kf_on_character_add_pin,
            on_clear=None,
            label_text="Character → Add as pin",
            compact=True,
        )
        self.kf_scene_picker = None
        try:
            from media_studio.flet_scene_picker import ScenePicker

            self.kf_scene_picker = ScenePicker(
                self.page,
                on_select=self._kf_on_scene_add_pin,
                on_clear=None,
                label_text="Scene → Add as pin",
                compact=True,
            )
        except Exception:
            self.kf_scene_picker = None
        self.btn_kf_enhance = make_enhance_button(on_click=self._on_kf_enhance)
        self.btn_kf_generate = ft.FilledButton(
            content="Generate Keyframe Take",
            on_click=self._run_keyframe_take,
            style=ft.ButtonStyle(bgcolor=ACCENT_BRIGHT, color=TEXT),
            height=42,
        )
        self.btn_kf_enhance_full = ft.OutlinedButton(
            content="Enhance to full",
            icon=ft.Icons.AUTO_FIX_HIGH,
            on_click=self._on_kf_enhance_full,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
            disabled=True,
            tooltip="Promote draft_cache to full quality",
        )
        self.kf_cost_text, self.kf_cost_box = make_estimated_cost_box(
            initial=format_keyframe_take_cost(duration_s=8, resolution="720p")
        )
        self.kf_notes = ft.Text(
            "FLUX 3 keyframes-to-video — pose plates at times → one continuous take. "
            "Max 10 pins · 24 fps frame indices · 5–20s · 720p/1080p.",
            size=FONT_SM,
            color=TEXT_MUTED,
            max_lines=3,
        )

    # ----- layout -----

    def build(self) -> ft.Control:
        from media_studio.flet_layout import make_split_workspace
        from media_studio.flet_theme import RAIL_WIDTH

        multi_controls: list[ft.Control] = [
            label("Master", muted=True),
            ft.Row([self.model_dd], spacing=0),
            self.model_best_for,
            self.model_notes,
            ft.Row(
                [self.dur_dd, self.res_dd, self.aspect_dd, self.style_dd],
                spacing=8,
            ),
            self.aspect_hint,
            label("Audio intent", muted=True),
            self.gen_audio,
            self.audio_style_dd,
            self.sfx_note,
            label("Continuity", muted=True),
            ft.Row(
                [self.cont_character, self.cont_location, self.cont_time],
                spacing=8,
                wrap=True,
            ),
            ft.Row(
                [self.btn_apply_char_all, self.btn_apply_scene_all],
                spacing=8,
                wrap=True,
            ),
            self.same_char_hint,
            self.scene_model_hint,
            ft.Row([self.transition_dd, self.output_mode_dd], spacing=8),
            self.transition_hint,
            self.energy_curve,
            self.vision_notes,
            self.master,
            ft.Divider(height=1, color=BORDER),
            label("Shots (ordered, non-overlapping)", muted=True),
            self.shots_meta,
            self.ref_budget_label,
            self.ref_budget_detail,
            self.angle_mode_row,
            self.angle_mode_hint,
            self.timing_warn,
            self.shots_host,
            ft.Row(
                [self.btn_add_shot, self.btn_auto_balance],
                spacing=8,
                wrap=True,
            ),
            label(
                "Extra stills for active shot (Previously used / From Resolve) — "
                "Character is on each shot card",
                muted=True,
            ),
            self.char_picker.root,
            self.prev_strip.root,
            self.resolve_strip.root,
            self.btn_save_character,
            self.assembled,
            self.prompt_count_label,
            ft.Row([self.btn_rebuild, self.btn_enhance, self.btn_generate], spacing=8),
            self.cost_box,
        ]
        self.multi_shot_panel = ft.Column(
            multi_controls, spacing=8, tight=True, visible=True
        )

        kf_scene = (
            self.kf_scene_picker.root
            if self.kf_scene_picker is not None
            else ft.Container()
        )
        kf_controls: list[ft.Control] = [
            self.kf_notes,
            ft.Row(
                [self.kf_dur_dd, self.kf_res_dd, self.kf_aspect_dd],
                spacing=8,
            ),
            self.kf_audio,
            self.kf_draft,
            self.kf_prompt,
            ft.Divider(height=1, color=BORDER),
            label("Pins (still + time, max 10)", muted=True),
            self.kf_pins_meta,
            self.kf_pins_host,
            ft.Row(
                [self.btn_kf_add_pin, self.btn_kf_auto_times],
                spacing=8,
                wrap=True,
            ),
            self.kf_prev_strip.root,
            self.kf_resolve_strip.root,
            label("Add pin from Character / Scene", muted=True),
            self.kf_char_picker.root,
            kf_scene,
            ft.Row(
                [
                    self.btn_kf_enhance,
                    self.btn_kf_generate,
                    self.btn_kf_enhance_full,
                ],
                spacing=8,
            ),
            self.kf_cost_box,
        ]
        self.keyframe_panel = ft.Column(
            kf_controls, spacing=8, tight=True, visible=False
        )

        left = [
            section_title("Director"),
            ft.Text(
                "Multi-shot cuts or Keyframe Take continuous motion. "
                "Not for editing existing plates (use Frame Editor).",
                size=FONT_SM,
                color=TEXT_MUTED,
            ),
            self._mode_nav.row,
            self.howto_box,
            ft.Divider(height=1, color=BORDER),
            self.multi_shot_panel,
            self.keyframe_panel,
            self.job_progress.control,
            self.status,
        ]
        right = ft.Column(
            [
                section_title("Result"),
                ft.Text(
                    "Clip output · Library · Show in folder · Send to Resolve / Upscale.",
                    size=FONT_SM,
                    color=TEXT_MUTED,
                ),
                self.player.control,
                self.send_host,
                self.result_actions_row,
            ],
            spacing=8,
            tight=True,
            expand=False,
        )
        return make_split_workspace(left, right, left_width=max(RAIL_WIDTH, 500))

    def _on_director_mode(self, mode_id: str) -> None:
        self._director_mode = mode_id if mode_id in (
            "multi_shot",
            "keyframe_take",
        ) else "multi_shot"
        is_kf = self._director_mode == "keyframe_take"
        try:
            self.multi_shot_panel.visible = not is_kf
            self.keyframe_panel.visible = is_kf
        except Exception:
            pass
        if is_kf:
            self._kf_refresh_cost()
            self._kf_sync_pins_meta()
            try:
                self.kf_prev_strip.refresh()
                self.kf_resolve_strip.refresh()
            except Exception:
                pass
        try:
            self.page.update()
        except Exception:
            pass

    # ----- helpers -----

    def _refresh_send_menu(self, path: str | None) -> None:
        """Send to ▾ with Video Upscale for the Director result clip."""
        from media_studio.flet_send_to import (
            build_send_menu_items,
            make_send_menu_button,
        )

        if not path or not Path(path).is_file():
            try:
                self.send_host.visible = False
            except Exception:
                pass
            return

        def _st(msg: str) -> None:
            try:
                self.status.value = msg
                self.page.update()
            except Exception:
                pass

        items = build_send_menu_items(
            self.state, video_path=path, status_cb=_st
        )
        btn = make_send_menu_button(
            items,
            tooltip="Send to Studio, Video Upscale, Tools, Resolve…",
        )
        try:
            if btn is None:
                self.send_host.visible = False
            else:
                self.send_host.content = btn
                self.send_host.visible = True
        except Exception:
            pass

    def apply_key_gates(self) -> None:
        from media_studio.secrets_store import has_fal_key, has_xai_key

        ready = has_fal_key()
        if not self.state.is_busy("director"):
            self.btn_generate.disabled = not ready
            self.btn_generate.tooltip = (
                None if ready else "Add your FAL API key in Settings"
            )
            try:
                self.btn_kf_generate.disabled = not ready
                self.btn_kf_generate.tooltip = (
                    None if ready else "Add your FAL API key in Settings"
                )
            except Exception:
                pass
            xai = has_xai_key()
            self.btn_enhance.disabled = not xai
            try:
                self.btn_kf_enhance.disabled = not xai
            except Exception:
                pass
            self.btn_enhance.tooltip = (
                "Rewrite master + per-shot prompts for the Director model"
                if xai
                else "Add xAI API key for Enhance"
            )

    def _current_spec(self):
        return find_director_model(_dd(self.model_dd)) or default_director_model()

    def _total_duration(self) -> float:
        try:
            return float(_dd(self.dur_dd) or 10)
        except (TypeError, ValueError):
            return 10.0

    def _selected_resolution(self, spec=None) -> str | None:
        """UI resolution when the model exposes choices; else model default."""
        sp = spec or self._current_spec()
        choices = list(getattr(sp, "resolution_choices", None) or ())
        if not choices:
            return getattr(sp, "default_resolution", None)
        cur = _dd(self.res_dd) if getattr(self, "res_dd", None) else None
        if cur and cur in choices:
            return cur
        return getattr(sp, "default_resolution", None) or choices[0]

    def _cost_label(self) -> str:
        try:
            spec = self._current_spec()
            audio = bool(self.gen_audio.value) if spec.supports_audio else False
            seen_paths: set[str] = set()
            for row in self._shots:
                for key in ("character_path", "scene_path", "ref_path"):
                    p = row.get(key)
                    if p and Path(str(p)).is_file():
                        try:
                            seen_paths.add(str(Path(str(p)).resolve()))
                        except OSError:
                            seen_paths.add(str(p))
            n_refs = len(seen_paths)
            res = self._selected_resolution(spec)
            eng = getattr(spec, "engine", "") or ""
            return format_director_cost(
                spec,
                duration_s=self._total_duration(),
                generate_audio=audio,
                resolution=res,
                num_refs=n_refs if eng in ("grok_imagine",) else 0,
            )
        except Exception:
            return "Est. cost: —"

    async def _refresh_cost(self, e: ft.ControlEvent | None = None) -> None:
        self.cost_text.value = self._cost_label()
        try:
            self.page.update()
        except Exception:
            pass

    async def _on_model(self, e: ft.ControlEvent) -> None:
        spec = self._current_spec()
        self.model_notes.value = spec.notes or ""
        try:
            from media_studio.flet_model_hint import update_best_for_line

            update_best_for_line(
                self.model_best_for, spec.label, dropdown=self.model_dd
            )
        except Exception:
            pass
        # Clamp duration choices
        opts = [str(i) for i in (spec.allowed_durations or range(3, 16))]
        self.dur_dd.options = dropdown_options(opts)
        if _dd(self.dur_dd) not in opts:
            self.dur_dd.value = str(spec.default_duration_s)
        # Resolution (Grok / FLUX 3)
        res_opts = list(getattr(spec, "resolution_choices", None) or ())
        self.res_dd.visible = bool(res_opts)
        if res_opts:
            self.res_dd.options = dropdown_options(res_opts)
            if _dd(self.res_dd) not in res_opts:
                pref = getattr(spec, "default_resolution", None)
                self.res_dd.value = pref if pref in res_opts else res_opts[0]
        self._sync_aspect_options()
        self.gen_audio.visible = bool(spec.supports_audio)
        self.gen_audio.value = bool(spec.default_generate_audio)
        self._sync_audio_polish_visibility()
        self._sync_scene_pickers_for_model()
        self._sync_location_fields_for_model()
        self._trim_shots_to_max()
        self._sync_shots_meta()
        self.cost_text.value = self._cost_label()
        self._rebuild_assembled_text()  # also refreshes multi_prompt char counts
        try:
            self.page.update()
        except Exception:
            pass

    def _has_any_shot_ref(self) -> bool:
        for row in self._shots:
            rp = row.get("ref_path")
            if rp and Path(rp).is_file():
                return True
            cp = row.get("character_path")
            if cp and Path(cp).is_file():
                return True
            sp = row.get("scene_path")
            if sp and Path(sp).is_file():
                return True
        return False

    def _model_supports_scene_image(self) -> bool:
        spec = self._current_spec()
        return bool(getattr(spec, "supports_scene_image_ref", False))

    def _apply_scene_picker_gate(self, picker: ScenePicker) -> None:
        ok = self._model_supports_scene_image()
        picker.set_enabled(
            ok,
            reason=(
                ""
                if ok
                else "Not supported as image ref on this model — describe location in text."
            ),
        )

    def _sync_scene_pickers_for_model(self) -> None:
        """
        Multi-ref models: Scene stills attach as image refs — no single-ref warning.
        Single-ref models: keep “describe location in text” when a scene is bound
        (or always as a soft model note so users know before picking).
        """
        ok = self._model_supports_scene_image()
        any_scene = any(
            (row.get("scene_path") and Path(str(row["scene_path"])).is_file())
            or row.get("scene_id")
            for row in self._shots
        )
        # Multi-ref: never show the text-only warning
        # Single-ref: show note (stronger when a scene is already selected)
        if ok:
            self.scene_model_hint.visible = False
            self.scene_model_hint.value = ""
        else:
            self.scene_model_hint.visible = True
            self.scene_model_hint.value = (
                "Scene selected — this model is single image-ref: use Location (text) "
                "per shot (auto-filled from Scene; Action stays character-only). "
                "Prefer Kling V3 or Imagine 1.5 for Character + Scene multi-ref."
                if any_scene
                else (
                    "This model is single image-ref: Scene stills are not image refs — "
                    "use Location (text) per shot. Prefer Kling V3 or Imagine 1.5 for "
                    "Character + Scene multi-ref."
                )
            )
        for row in self._shots:
            sp = row.get("scene_picker")
            if sp is not None:
                try:
                    self._apply_scene_picker_gate(sp)
                except Exception:
                    pass

    def _sync_aspect_options(self) -> None:
        """Only list ratios the selected model/path accepts; Auto when I2V."""
        spec = self._current_spec()
        has_ref = self._has_any_shot_ref()
        opts, default = director_aspect_ui_choices(spec, has_start_image=has_ref)
        self.aspect_dd.options = dropdown_options(opts)
        cur = _dd(self.aspect_dd)
        if cur not in opts:
            self.aspect_dd.value = default
        uses_i2v_auto = (
            has_ref
            and bool(spec.i2v_endpoint)
            and (getattr(spec, "engine", None) or "kling_multi") == "kling_multi"
            and not bool(getattr(spec, "i2v_accepts_aspect", False))
        )
        if uses_i2v_auto:
            self.aspect_hint.value = (
                "Start still attached — output aspect follows that image "
                f"({ASPECT_AUTO_FROM_STILL}). T2V ratios apply only with no refs."
            )
            self.aspect_hint.visible = True
        else:
            allowed = ", ".join(spec.aspect_choices or ())
            self.aspect_hint.value = (
                f"Accepted for this model: {allowed or '—'}"
            )
            self.aspect_hint.visible = bool(allowed)

    async def _on_duration(self, e: ft.ControlEvent) -> None:
        self.cost_text.value = self._cost_label()
        self._sync_shots_meta()
        self._sync_shot_timing_ui()
        try:
            self.page.update()
        except Exception:
            pass

    def _sync_audio_polish_visibility(self) -> None:
        """Audio style / SFX only when model supports audio and generate is on."""
        spec = self._current_spec()
        show = bool(spec.supports_audio) and bool(self.gen_audio.value)
        self.audio_style_dd.visible = show
        self.sfx_note.visible = show
        # Parent gen_audio already gated by model; keep visible when supports
        self.gen_audio.visible = bool(spec.supports_audio)

    async def _on_audio_toggle(self, e: ft.ControlEvent | None = None) -> None:
        self._sync_audio_polish_visibility()
        self.cost_text.value = self._cost_label()
        self._rebuild_assembled_text()
        try:
            self.page.update()
        except Exception:
            pass

    async def _on_polish_change(self, e: ft.ControlEvent | None = None) -> None:
        try:
            self._sync_apply_char_visibility()
        except Exception:
            pass
        self._rebuild_assembled_text()
        try:
            self.page.update()
        except Exception:
            pass

    async def _on_global_transition(self, e: ft.ControlEvent | None = None) -> None:
        """Apply default transition to every per-gap control."""
        val = normalize_transition(_dd(self.transition_dd))
        for i, row in enumerate(self._shots[:-1]):
            gap_dd = row.get("gap_dd")
            if gap_dd is not None:
                try:
                    gap_dd.value = val
                except Exception:
                    pass
        self._rebuild_assembled_text()
        try:
            self.page.update()
        except Exception:
            pass

    def _collect_gap_transitions(self) -> list[str]:
        """Modes between Shot i and Shot i+1 (length n-1)."""
        default = normalize_transition(_dd(self.transition_dd))
        gaps: list[str] = []
        for row in self._shots[:-1]:
            gap_dd = row.get("gap_dd")
            if gap_dd is not None:
                gaps.append(normalize_transition(_dd(gap_dd)))
            else:
                gaps.append(default)
        return gaps

    def _collect_polish(self) -> DirectorPolish:
        return DirectorPolish(
            audio_style=_dd(self.audio_style_dd) or "Soft bed only",
            sfx_note=(self.sfx_note.value or "").strip(),
            same_character=bool(self.cont_character.value),
            same_location=bool(self.cont_location.value),
            same_time_of_day=bool(self.cont_time.value),
            transition=normalize_transition(_dd(self.transition_dd)),
            gap_transitions=self._collect_gap_transitions(),
            energy_curve=bool(self.energy_curve.value),
            vision_notes=(self.vision_notes.value or "").strip(),
            output_mode=_dd(self.output_mode_dd) or OUTPUT_MODES[0],
        )

    def _collect_shots(self) -> list[DirectorShot]:
        out: list[DirectorShot] = []
        for row in self._shots:
            try:
                start = float(row["start"].value or 0)
            except (TypeError, ValueError):
                start = 0.0
            try:
                end = float(row["end"].value or 0)
            except (TypeError, ValueError):
                end = 0.0
            extras = row.get("character_extra_paths") or ()
            if isinstance(extras, list):
                extras = tuple(extras)
            scene_extras = row.get("scene_extra_paths") or ()
            if isinstance(scene_extras, list):
                scene_extras = tuple(scene_extras)
            loc_tf = row.get("location")
            loc_val = ""
            if loc_tf is not None:
                try:
                    loc_val = (loc_tf.value or "").strip()
                except Exception:
                    loc_val = ""
            out.append(
                DirectorShot(
                    start_s=start,
                    end_s=end,
                    camera=_dd(row["camera"]) or "Static",
                    action=(row["action"].value or "").strip(),
                    ref_path=row.get("ref_path"),
                    character_path=row.get("character_path"),
                    character_label=row.get("character_label"),
                    character_id=row.get("character_id"),
                    character_extra_paths=tuple(extras) if extras else (),
                    scene_path=row.get("scene_path"),
                    scene_label=row.get("scene_label"),
                    scene_id=row.get("scene_id"),
                    scene_extra_paths=tuple(scene_extras) if scene_extras else (),
                    location_text=loc_val,
                )
            )
        return out

    def _trim_shots_to_max(self) -> None:
        cap = self._current_spec().max_shots
        changed = False
        while len(self._shots) > cap:
            self._shots.pop()
            changed = True
        if changed:
            self._reindex_shots()

    def _sync_shots_meta(self) -> None:
        spec = self._current_spec()
        n = len(self._shots)
        self.shots_meta.value = (
            f"Shots {n} / {spec.max_shots} · total {self._total_duration():.0f}s "
            f"· times inside 0–{self._total_duration():.0f}s, no overlap"
        )
        self.btn_add_shot.disabled = n >= spec.max_shots
        self._sync_ref_budget()

    def _current_angle_mode(self) -> str:
        shots = self._collect_shots()
        spec = self._current_spec()
        return resolve_angle_mode(
            shots, requested=self._angle_mode_user, spec=spec
        )

    def _set_angle_mode(self, mode: str) -> None:
        # Single-ref models cannot leave Front only
        if director_is_single_ref_model(self._current_spec()) or not (
            director_shows_pack_toggle(self._current_spec())
        ):
            self._angle_mode_user = "front_only"
        else:
            self._angle_mode_user = mode
        self._sync_ref_budget()
        try:
            self.page.update()
        except Exception:
            pass

    def _any_scene_angle_pack(self, shots: list | None = None) -> bool:
        """True if any shot has scene Angle B/C extras loaded."""
        for row in self._shots:
            ex = row.get("scene_extra_paths") or ()
            if ex:
                return True
        if shots:
            for sh in shots:
                if getattr(sh, "scene_extra_paths", None):
                    return True
        return False

    def _any_character_pack(self) -> bool:
        for row in self._shots:
            ex = row.get("character_extra_paths") or ()
            if ex:
                return True
        return False

    def _sync_ref_budget(self) -> None:
        """Unique-asset ref budget + Generate gate (blue / amber / red)."""
        try:
            spec = self._current_spec()
            shots = self._collect_shots()
            # Pack toggle only when model can use identity Full pack and/or scene angles
            show_pack = director_shows_pack_toggle(spec)
            single_ref = director_is_single_ref_model(spec)
            has_scene_pack = self._any_scene_angle_pack(shots)
            has_char_pack = self._any_character_pack()
            self.angle_mode_row.visible = show_pack
            self.angle_mode_hint.visible = show_pack or single_ref
            # Single-ref: force Front only (never Side/Close-up)
            if not show_pack:
                ang = "front_only"
                if self._angle_mode_user not in ("front_only", "auto"):
                    self._angle_mode_user = "front_only"
            else:
                ang = resolve_angle_mode(
                    shots, requested=self._angle_mode_user, spec=spec
                )
            # Full pack button only when identity or scene pack can apply
            try:
                self.btn_pack_full.visible = show_pack
                self.btn_pack_full.disabled = not show_pack
            except Exception:
                pass
            if show_pack:
                # Dynamic label when scene angles are available
                if has_scene_pack and not has_char_pack:
                    self.angle_mode_label.value = "Scene pack:"
                    self.btn_pack_hero.content = "Hero only"
                elif has_char_pack and not has_scene_pack:
                    self.angle_mode_label.value = "Identity pack:"
                    self.btn_pack_hero.content = "Front only"
                else:
                    self.angle_mode_label.value = "Ref pack:"
                    self.btn_pack_hero.content = "Hero / Front only"
                # Highlight active mode
                for btn, mode in (
                    (self.btn_pack_hero, "front_only"),
                    (self.btn_pack_full, "full_pack"),
                ):
                    try:
                        btn.style = ft.ButtonStyle(
                            color=ACCENT if ang == mode else TEXT_MUTED
                        )
                    except Exception:
                        pass
                auto = self._angle_mode_user == "auto"
                mode_name = "Hero only" if ang == "front_only" else "Full pack"
                bits = [f"Using {mode_name}" + (" (auto)" if auto else "")]
                if has_scene_pack:
                    bits.append(
                        "Full pack includes scene Angle B/C; Hero only = main plate."
                    )
                if has_char_pack:
                    bits.append(
                        "Full pack includes character Side/Close-up; Front only = primary."
                    )
                if auto:
                    bits.append(
                        "Auto defaults to Hero/Front only when a scene is bound "
                        "(and character is also bound)."
                    )
                self.angle_mode_hint.value = " ".join(bits)
            elif single_ref:
                self.angle_mode_hint.value = (
                    "Single-ref model — Front only (identity Side/Close-up not sent)."
                )
                self.angle_mode_hint.visible = True
            budget = count_director_ref_budget(
                spec,
                shots,
                angle_mode=ang,
            )
            self.ref_budget_label.value = (
                f"Refs {budget.used} / {budget.max_refs}  ·  "
                f"Shots {budget.shot_count} / {budget.max_shots}"
            )
            self.ref_budget_detail.value = budget.detail + (
                f" — {budget.reason_over}" if budget.over and budget.reason_over else ""
            )
            if budget.over:
                self.ref_budget_label.color = "#ef9a9a"  # red
                self.ref_budget_detail.color = "#ef9a9a"
            elif budget.near:
                self.ref_budget_label.color = "#ffb74d"  # amber
                self.ref_budget_detail.color = "#ffb74d"
            else:
                self.ref_budget_label.color = "#64b5f6"  # blue
                self.ref_budget_detail.color = TEXT_MUTED
            # Disable Generate when over budget
            over = budget.over
            try:
                self.btn_generate.disabled = bool(over) or bool(
                    self.state.is_busy("director")
                )
            except Exception:
                self.btn_generate.disabled = bool(over)
            self._last_ref_budget = budget
        except Exception:
            self.ref_budget_label.value = ""
            self.ref_budget_detail.value = ""

    def _rebuild_assembled_text(self) -> None:
        gen_audio = bool(self.gen_audio.value) if self.gen_audio.visible else False
        brief = assemble_director_brief(
            master=self.master.value or "",
            shots=self._collect_shots(),
            style_pack=_dd(self.style_dd),
            polish=self._collect_polish(),
            generate_audio=gen_audio,
        )
        self.assembled.value = brief
        self._sync_prompt_counts()

    def _sync_prompt_counts(self) -> None:
        """Live multi_prompt character counts when model has a hard limit."""
        try:
            spec = self._current_spec()
            max_c = getattr(spec, "multi_prompt_max_chars", None)
            if not max_c:
                self.prompt_count_label.value = ""
                self.prompt_count_label.visible = False
                return
            gen_audio = bool(self.gen_audio.value) if self.gen_audio.visible else False
            shots = self._collect_shots()
            counts = multi_prompt_char_counts(
                shots,
                master=self.master.value or "",
                style_pack=_dd(self.style_dd),
                polish=self._collect_polish(),
                generate_audio=gen_audio,
                max_chars=int(max_c),
                scene_as_image_ref=bool(
                    getattr(spec, "supports_scene_image_ref", False)
                ),
            )
            parts = [f"Shot {i + 1}: {n}/{max_c}" for i, (n, _, _) in enumerate(counts)]
            over = [i + 1 for i, (n, _, _) in enumerate(counts) if n > int(max_c)]
            line = " · ".join(parts) if parts else ""
            if over:
                self.prompt_count_label.value = (
                    f"multi_prompt (after compact): {line} — OVER limit on shot(s) "
                    f"{', '.join(str(x) for x in over)}. Shorten master/actions."
                )
                self.prompt_count_label.color = "#ef9a9a"
            else:
                self.prompt_count_label.value = (
                    f"multi_prompt (Kling ≤{max_c}/shot, auto-compacted): {line}"
                )
                self.prompt_count_label.color = TEXT_MUTED
            self.prompt_count_label.visible = True
        except Exception:
            try:
                self.prompt_count_label.visible = False
            except Exception:
                pass

    async def _rebuild_assembled(self, e: ft.ControlEvent | None = None) -> None:
        self._rebuild_assembled_text()
        try:
            self.page.update()
        except Exception:
            pass

    # ----- shot rows -----

    def _add_shot_row(
        self,
        *,
        start: float = 0,
        end: float = 5,
        camera: str = "Push in",
        action: str = "",
        location_text: str = "",
    ) -> None:
        idx = len(self._shots)
        start_tf = ft.TextField(
            label="Start (s)",
            value=str(int(start) if start == int(start) else start),
            dense=True,
            filled=True,
            fill_color=PANEL_ELEVATED,
            border_color=BORDER,
            color=TEXT,
            text_size=FONT_SM,
            width=90,
            on_change=self._on_shot_field,
        )
        end_tf = ft.TextField(
            label="End (s)",
            value=str(int(end) if end == int(end) else end),
            dense=True,
            filled=True,
            fill_color=PANEL_ELEVATED,
            border_color=BORDER,
            color=TEXT,
            text_size=FONT_SM,
            width=90,
            on_change=self._on_shot_field,
        )
        cam_dd = styled_dropdown(
            label_text="Camera",
            options=list(CAMERA_PRESETS),
            value=camera if camera in CAMERA_PRESETS else CAMERA_PRESETS[0],
            on_select=self._on_shot_field,
            expand=True,
        )
        action_tf = ft.TextField(
            label="Per-shot action (character)",
            value=action,
            hint_text="What the character does — not location",
            dense=True,
            filled=True,
            fill_color=PANEL_ELEVATED,
            border_color=BORDER,
            color=TEXT,
            text_size=FONT_SM,
            expand=True,
            on_change=self._on_shot_field,
        )
        # Visible when model cannot bind scene as image ref (e.g. Kling O3)
        show_loc = not self._model_supports_scene_image()
        location_tf = ft.TextField(
            label="Location (text)",
            value=location_text,
            hint_text="Where this shot is — auto-filled from Scene name + notes",
            dense=True,
            filled=True,
            fill_color=PANEL_ELEVATED,
            border_color=BORDER,
            color=TEXT,
            text_size=FONT_SM,
            expand=True,
            multiline=True,
            min_lines=1,
            max_lines=3,
            visible=show_loc,
            on_change=self._on_shot_field,
        )
        location_hint = ft.Text(
            "Single-ref model: describe place here (not in Action). "
            "Picking a Scene auto-fills name + notes.",
            size=11,
            color=TEXT_MUTED,
            max_lines=2,
            visible=show_loc,
        )
        timing_err = ft.Text(
            "",
            size=11,
            color="#ef9a9a",
            max_lines=2,
            visible=False,
        )
        ref_label = ft.Text(
            "No ref still",
            size=FONT_SM,
            color=TEXT_MUTED,
            expand=True,
            max_lines=2,
            overflow=ft.TextOverflow.ELLIPSIS,
            tooltip="No ref still",
        )
        ref_thumb = ft.Image(
            src="",
            width=_REF_THUMB,
            height=_REF_THUMB,
            fit=ft.BoxFit.COVER,
            border_radius=6,
            visible=False,
        )
        ref_empty = ft.Container(
            width=_REF_THUMB,
            height=_REF_THUMB,
            bgcolor=PANEL,
            border=ft.Border.all(1, BORDER),
            border_radius=6,
            alignment=ft.Alignment.CENTER,
            content=ft.Icon(
                ft.Icons.IMAGE_OUTLINED, size=22, color=TEXT_MUTED
            ),
            visible=True,
            tooltip="No ref still",
        )
        btn_ref = ft.OutlinedButton(
            content="Ref still",
            icon=ft.Icons.IMAGE,
            on_click=self._make_pick_ref(idx),
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
        )
        btn_clear_ref = ft.TextButton(
            content="Clear ref",
            on_click=self._make_clear_ref(idx),
            style=ft.ButtonStyle(color=TEXT_MUTED),
        )
        btn_remove = ft.IconButton(
            icon=ft.Icons.CLOSE,
            icon_size=18,
            icon_color=TEXT_MUTED,
            tooltip="Remove shot",
            on_click=self._make_remove_shot(idx),
        )
        title = ft.Text(
            format_shot_length_label(idx, start, end),
            size=FONT_SM,
            color=TEXT,
            weight=ft.FontWeight.W_700,
        )
        # Placeholder row dict first so handlers can close over it
        row: dict[str, Any] = {
            "start": start_tf,
            "end": end_tf,
            "camera": cam_dd,
            "action": action_tf,
            "location": location_tf,
            "location_hint": location_hint,
            "timing_err": timing_err,
            "ref_label": ref_label,
            "ref_thumb": ref_thumb,
            "ref_empty": ref_empty,
            "ref_path": None,
            "character_path": None,
            "character_label": None,
            "character_id": None,
            "character_extra_paths": (),
            "scene_path": None,
            "scene_label": None,
            "scene_id": None,
            "scene_extra_paths": (),
            "title": title,
            "btn_ref": btn_ref,
            "btn_clear_ref": btn_clear_ref,
            "btn_remove": btn_remove,
            "gap_dd": None,
            "gap_label": None,
            "gap_host": None,
        }
        char_picker = CharacterPicker(
            self.page,
            on_select=self._make_shot_char_select(row),
            on_clear=self._make_shot_char_clear(row),
            label_text="Character (this shot)",
            compact=True,
        )
        scene_picker = ScenePicker(
            self.page,
            on_select=self._make_shot_scene_select(row),
            on_clear=self._make_shot_scene_clear(row),
            label_text="Scene (this shot)",
            compact=True,
        )
        row["char_picker"] = char_picker
        row["scene_picker"] = scene_picker
        # Apply model gate for scene multi-ref
        try:
            self._apply_scene_picker_gate(scene_picker)
        except Exception:
            pass
        card = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [title, ft.Container(expand=True), btn_remove],
                        spacing=4,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Row([start_tf, end_tf, cam_dd], spacing=8),
                    timing_err,
                    action_tf,
                    location_tf,
                    location_hint,
                    label("Character (this shot) = who", muted=True),
                    char_picker.root,
                    label("Scene (this shot) = where", muted=True),
                    scene_picker.root,
                    ft.Row(
                        [
                            ft.Container(
                                content=ft.Stack([ref_empty, ref_thumb]),
                                width=_REF_THUMB,
                                height=_REF_THUMB,
                            ),
                            ft.Column(
                                [
                                    ref_label,
                                    ft.Row(
                                        [btn_ref, btn_clear_ref],
                                        spacing=4,
                                        tight=True,
                                        wrap=True,
                                    ),
                                ],
                                spacing=4,
                                tight=True,
                                expand=True,
                            ),
                        ],
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.START,
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
        row["card"] = card
        self._shots.append(row)
        self._reindex_shots()

    def _ensure_gap_control(self, row: dict[str, Any], after_index: int) -> None:
        """Gap control after shot ``after_index`` (between N and N+1)."""
        default = normalize_transition(_dd(self.transition_dd))
        if row.get("gap_dd") is None:
            gap_label = ft.Text(
                f"Between Shot {after_index + 1} → {after_index + 2}",
                size=FONT_SM,
                color=TEXT_MUTED,
                weight=ft.FontWeight.W_600,
            )
            gap_dd = styled_dropdown(
                label_text="Transition",
                options=list(TRANSITION_PREFS),
                value=default,
                on_select=self._on_polish_change,
                expand=True,
            )
            gap_host = ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(ft.Icons.SOUTH, size=16, color=TEXT_MUTED),
                        gap_label,
                        gap_dd,
                    ],
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                bgcolor=PANEL,
                border=ft.Border(
                    left=ft.BorderSide(3, ACCENT),
                    top=ft.BorderSide(1, BORDER),
                    right=ft.BorderSide(1, BORDER),
                    bottom=ft.BorderSide(1, BORDER),
                ),
                border_radius=6,
                padding=ft.Padding.symmetric(horizontal=10, vertical=6),
            )
            row["gap_dd"] = gap_dd
            row["gap_label"] = gap_label
            row["gap_host"] = gap_host
        else:
            try:
                row["gap_label"].value = (
                    f"Between Shot {after_index + 1} → {after_index + 2}"
                )
            except Exception:
                pass

    def _refresh_shots_host(self) -> None:
        """Rebuild shots column: Shot · gap · Shot · gap · Shot."""
        controls: list[ft.Control] = []
        n = len(self._shots)
        for i, row in enumerate(self._shots):
            controls.append(row["card"])
            if i < n - 1:
                self._ensure_gap_control(row, i)
                host = row.get("gap_host")
                if host is not None:
                    controls.append(host)
            else:
                # Last shot has no outgoing gap
                row["gap_dd"] = row.get("gap_dd")
                # Keep widgets if re-added later; just omit from host
        self.shots_host.controls = controls

    def _reindex_shots(self) -> None:
        for i, row in enumerate(self._shots):
            try:
                row["btn_ref"].on_click = self._make_pick_ref(i)
                row["btn_clear_ref"].on_click = self._make_clear_ref(i)
                row["btn_remove"].on_click = self._make_remove_shot(i)
            except Exception:
                pass
            if i < len(self._shots) - 1:
                self._ensure_gap_control(row, i)
        self._refresh_shots_host()
        self._sync_shots_meta()
        self._sync_shot_timing_ui()

    def _apply_balanced_times(self, *, announce: bool = True) -> None:
        """Evenly split total duration across current shots (contiguous)."""
        n = len(self._shots)
        if n < 1:
            return
        total = self._total_duration()
        ranges = balance_shot_times(n, total)
        for row, (a, b) in zip(self._shots, ranges):
            try:
                row["start"].value = str(int(a) if a == int(a) else a)
                row["end"].value = str(int(b) if b == int(b) else b)
            except Exception:
                pass
        self._sync_shot_timing_ui()
        if announce:
            self.status.value = (
                f"Auto-balanced {n} shot(s) across {total:.0f}s "
                f"({ranges[0][0]:g}–{ranges[0][1]:g}s … "
                f"{ranges[-1][0]:g}–{ranges[-1][1]:g}s)."
            )

    async def _auto_balance_times(self, e: ft.ControlEvent | None = None) -> None:
        self._apply_balanced_times(announce=True)
        self._rebuild_assembled_text()
        try:
            self.page.update()
        except Exception:
            pass

    def _sync_shot_timing_ui(self) -> None:
        """Refresh Shot N · Xs labels, red borders on invalid ranges, summary warn."""
        shots = self._collect_shots()
        total = self._total_duration()
        per = per_shot_timing_errors(shots, total_duration_s=total)
        summary: list[str] = []
        for i, row in enumerate(self._shots):
            try:
                a = float(row["start"].value or 0)
            except (TypeError, ValueError):
                a = 0.0
            try:
                b = float(row["end"].value or 0)
            except (TypeError, ValueError):
                b = 0.0
            try:
                row["title"].value = format_shot_length_label(i, a, b)
            except Exception:
                pass
            errs = per[i] if i < len(per) else []
            bad = bool(errs)
            color = "#ef9a9a" if bad else BORDER
            try:
                row["card"].border = ft.Border.all(1, color if bad else BORDER)
            except Exception:
                pass
            try:
                row["start"].border_color = color
                row["end"].border_color = color
            except Exception:
                pass
            try:
                te = row.get("timing_err")
                if te is not None:
                    if errs:
                        te.value = " · ".join(errs)
                        te.visible = True
                    else:
                        te.value = ""
                        te.visible = False
            except Exception:
                pass
            if errs:
                summary.append(f"Shot {i + 1}: {', '.join(errs)}")
        if summary:
            self.timing_warn.value = "Timing: " + " · ".join(summary[:4])
            self.timing_warn.visible = True
        else:
            self.timing_warn.value = ""
            self.timing_warn.visible = False

    def _sync_location_fields_for_model(self) -> None:
        """Show Location (text) only when scene is not an image ref on this model."""
        show = not self._model_supports_scene_image()
        for row in self._shots:
            for key in ("location", "location_hint"):
                ctl = row.get(key)
                if ctl is not None:
                    try:
                        ctl.visible = show
                    except Exception:
                        pass

    async def _add_shot(self, e: ft.ControlEvent) -> None:
        spec = self._current_spec()
        if len(self._shots) >= spec.max_shots:
            self.status.value = f"Max {spec.max_shots} shots for {spec.label}."
            self.page.update()
            return
        # Append a temporary range, then re-balance all shots evenly
        total = self._total_duration()
        n = len(self._shots) + 1
        ranges = balance_shot_times(n, total)
        # Create new row with last range; balance will overwrite all
        a, b = ranges[-1]
        self._add_shot_row(start=a, end=b)
        self._apply_balanced_times(announce=True)
        self.status.value = (
            f"Added shot {n}; times auto-balanced across {total:.0f}s. "
            "Edit start/end anytime, or Auto-balance again."
        )
        self._rebuild_assembled_text()
        self.page.update()

    def _make_remove_shot(self, index: int):
        async def _click(_e: ft.ControlEvent) -> None:
            if len(self._shots) <= 1:
                self.status.value = "Keep at least one shot."
                self.page.update()
                return
            if 0 <= index < len(self._shots):
                self._shots.pop(index)
            self._reindex_shots()
            self._rebuild_assembled_text()
            try:
                self.page.update()
            except Exception:
                pass

        return _click

    def _make_pick_ref(self, index: int):
        async def _click(_e: ft.ControlEvent) -> None:
            self._ref_target_index = index
            try:
                files = await pick_image(
                    self.page, dialog_title=f"Shot {index + 1} reference still"
                )
            except Exception as exc:
                self.status.value = f"Picker error: {exc}"
                self.page.update()
                return
            if not files or not files[0].path:
                return
            self._set_shot_ref(index, files[0].path)
            self.page.update()

        return _click

    def _make_clear_ref(self, index: int):
        async def _click(_e: ft.ControlEvent) -> None:
            self._set_shot_ref(index, None)
            try:
                self.page.update()
            except Exception:
                pass

        return _click

    def _refresh_shot_still_ui(self, row: dict[str, Any]) -> None:
        """Update main thumb / labels from character + scene + manual ref."""
        manual = row.get("ref_path")
        char = row.get("character_path")
        char_label = row.get("character_label")
        scene_p = row.get("scene_path")
        scene_label = row.get("scene_label")
        show_path = None
        parts: list[str] = []
        if char and Path(str(char)).is_file():
            show_path = str(char)
            parts.append(f"Who: {char_label or Path(str(char)).name}")
        if scene_p and Path(str(scene_p)).is_file():
            if show_path is None:
                show_path = str(scene_p)
            parts.append(f"Where: {scene_label or Path(str(scene_p)).name}")
        if manual and Path(str(manual)).is_file():
            try:
                same_char = (
                    char
                    and Path(str(manual)).resolve() == Path(str(char)).resolve()
                )
            except OSError:
                same_char = manual == char
            try:
                same_scene = (
                    scene_p
                    and Path(str(manual)).resolve() == Path(str(scene_p)).resolve()
                )
            except OSError:
                same_scene = manual == scene_p
            if not same_char and not same_scene:
                if show_path is None:
                    show_path = str(manual)
                parts.append(f"Manual: {Path(str(manual)).name}")
        if parts:
            row["ref_label"].value = " · ".join(parts)
            row["ref_label"].color = TEXT
        else:
            row["ref_label"].value = "No character / scene still"
            row["ref_label"].color = TEXT_MUTED
        thumb = row.get("ref_thumb")
        empty = row.get("ref_empty")
        if show_path:
            if thumb is not None:
                try:
                    thumb.src = show_path
                    thumb.visible = True
                except Exception:
                    pass
            if empty is not None:
                try:
                    empty.visible = False
                except Exception:
                    pass
        else:
            if thumb is not None:
                try:
                    thumb.src = ""
                    thumb.visible = False
                except Exception:
                    pass
            if empty is not None:
                try:
                    empty.visible = True
                except Exception:
                    pass

    def _sync_row_char_picker(self, row: dict[str, Any]) -> None:
        """Keep per-shot Character dropdown in sync with bound character_id."""
        picker = row.get("char_picker")
        if picker is None:
            return
        try:
            cid = row.get("character_id")
            picker.set_selection_silent(cid if cid else None)
        except Exception:
            pass

    def _make_shot_char_select(self, row: dict[str, Any]):
        def _on(path: str, choice) -> None:
            try:
                idx = self._shots.index(row)
            except ValueError:
                return
            self._ref_target_index = idx
            cid = getattr(choice, "id", None)
            label = getattr(choice, "label", None) or Path(path).name
            bundle = preferred_character_still_bundle(cid, still_path=path)
            still = bundle.get("path") or path
            extras = bundle.get("extras") or []
            self._set_shot_character(
                idx,
                still,
                label=bundle.get("label") or label,
                char_id=bundle.get("id") or cid,
                extras=extras,
                sync_picker=False,
            )
            self._highlight_shot(idx)
            warn = ""
            if bundle.get("low_res") or still_is_low_res(still):
                warn = " · low-res still — prefer 1K–2K Front"
            self.status.value = (
                f"Shot {idx + 1} · character: {bundle.get('label') or label}{warn}"
            )
            try:
                self.page.update()
            except Exception:
                pass

        return _on

    def _make_shot_char_clear(self, row: dict[str, Any]):
        def _on() -> None:
            try:
                idx = self._shots.index(row)
            except ValueError:
                return
            self._set_shot_character(idx, None, sync_picker=False)
            self.status.value = f"Shot {idx + 1} · character cleared"
            try:
                self.page.update()
            except Exception:
                pass

        return _on

    def _make_shot_scene_select(self, row: dict[str, Any]):
        def _on(path: str, choice) -> None:
            try:
                idx = self._shots.index(row)
            except ValueError:
                return
            label = getattr(choice, "label", None)
            scene_id = getattr(choice, "id", None)
            if not self._model_supports_scene_image():
                # Auto-fill Location (text) from scene name + notes; action stays separate
                loc = location_text_from_scene(
                    scene_id=scene_id,
                    scene_label=label,
                )
                loc_tf = row.get("location")
                if loc_tf is not None and loc:
                    try:
                        loc_tf.value = loc
                    except Exception:
                        pass
                self.status.value = (
                    f"Shot {idx + 1} · Location (text) filled from “{label or path}” "
                    "— this model cannot bind a second image ref. Edit freely."
                )
            self._ref_target_index = idx
            self._set_shot_scene(
                idx,
                path,
                label=label,
                scene_id=scene_id,
                aspect=getattr(choice, "aspect", None),
                sync_picker=False,
            )
            self._highlight_shot(idx)
            try:
                self.page.update()
            except Exception:
                pass

        return _on

    def _make_shot_scene_clear(self, row: dict[str, Any]):
        def _on() -> None:
            try:
                idx = self._shots.index(row)
            except ValueError:
                return
            self._set_shot_scene(idx, None, sync_picker=False)
            self.status.value = f"Shot {idx + 1} · scene cleared"
            try:
                self.page.update()
            except Exception:
                pass

        return _on

    def _sync_row_scene_picker(self, row: dict[str, Any]) -> None:
        picker = row.get("scene_picker")
        if picker is None:
            return
        try:
            picker.set_selection_silent(row.get("scene_id"))
        except Exception:
            pass

    def _set_shot_scene(
        self,
        index: int,
        path: str | None,
        *,
        label: str | None = None,
        scene_id: str | None = None,
        aspect: str | None = None,
        sync_picker: bool = True,
    ) -> None:
        """Bind (or clear) a saved scene still on a shot."""
        if not (0 <= index < len(self._shots)):
            return
        row = self._shots[index]
        if path and Path(path).is_file():
            resolved = str(Path(path).resolve())
            row["scene_path"] = resolved
            row["scene_label"] = label or Path(resolved).name
            row["scene_id"] = scene_id
            # Load multi-angle extras (B/C); hero stays scene_path for single-ref
            try:
                from media_studio.scene_store import preferred_scene_still_bundle

                bundle = preferred_scene_still_bundle(
                    scene_id, still_path=resolved
                )
                extras = bundle.get("extras") or []
                row["scene_extra_paths"] = tuple(extras)
                if bundle.get("label") and not label:
                    row["scene_label"] = bundle["label"]
            except Exception:
                row["scene_extra_paths"] = ()
            try:
                self.prev_strip.record_and_refresh(resolved)
            except Exception:
                pass
            # Single-ref: auto-fill Location (text) from scene name + notes
            if not self._model_supports_scene_image():
                loc_tf = row.get("location")
                if loc_tf is not None:
                    filled = location_text_from_scene(
                        scene_id=scene_id,
                        scene_label=row["scene_label"],
                    )
                    if filled:
                        try:
                            loc_tf.value = filled
                        except Exception:
                            pass
            # Soft aspect mismatch warning (multi-ref path)
            if self._model_supports_scene_image():
                try:
                    from media_studio.scene_store import (
                        detect_still_aspect,
                        normalize_scene_aspect,
                    )

                    scene_ar = normalize_scene_aspect(aspect) or detect_still_aspect(
                        resolved
                    )
                    dir_ar = normalize_scene_aspect(_dd(self.aspect_dd) or "")
                    n_ex = len(row.get("scene_extra_paths") or ())
                    pack = f" · +{n_ex} angle(s)" if n_ex else ""
                    if scene_ar and dir_ar and scene_ar != dir_ar and not str(
                        _dd(self.aspect_dd) or ""
                    ).lower().startswith("auto"):
                        self.status.value = (
                            f"Shot {index + 1} · scene: {row['scene_label']} "
                            f"({scene_ar}){pack} — Director aspect is {dir_ar} "
                            f"(soft warning; plate still bound)."
                        )
                    else:
                        self.status.value = (
                            f"Shot {index + 1} · scene: {row['scene_label']}{pack}"
                        )
                except Exception:
                    self.status.value = (
                        f"Shot {index + 1} · scene: {row['scene_label']}"
                    )
        else:
            row["scene_path"] = None
            row["scene_label"] = None
            row["scene_id"] = None
            row["scene_extra_paths"] = ()
        self._refresh_shot_still_ui(row)
        if sync_picker:
            self._sync_row_scene_picker(row)
        try:
            self._sync_aspect_options()
        except Exception:
            pass
        try:
            self.cost_text.value = self._cost_label()
        except Exception:
            pass
        try:
            self._sync_prompt_counts()
        except Exception:
            pass
        try:
            # Scene bind changes unique ref budget (and Imagine auto Front only)
            self._sync_ref_budget()
            self._sync_scene_pickers_for_model()
        except Exception:
            pass

    def _set_shot_ref(self, index: int, path: str | None) -> None:
        if not (0 <= index < len(self._shots)):
            return
        row = self._shots[index]
        if path and Path(path).is_file():
            resolved = str(Path(path).resolve())
            row["ref_path"] = resolved
            try:
                self.prev_strip.record_and_refresh(resolved)
            except Exception:
                pass
        else:
            row["ref_path"] = None
        self._refresh_shot_still_ui(row)
        # Aspect dropdown: Auto when any ref (Kling I2V path)
        try:
            self._sync_aspect_options()
        except Exception:
            pass
        try:
            self.cost_text.value = self._cost_label()
        except Exception:
            pass
        try:
            self._sync_prompt_counts()
        except Exception:
            pass
        try:
            self._sync_ref_budget()
        except Exception:
            pass

    def _set_shot_character(
        self,
        index: int,
        path: str | None,
        *,
        label: str | None = None,
        char_id: str | None = None,
        extras: list[str] | tuple[str, ...] | None = None,
        sync_picker: bool = True,
    ) -> None:
        """Bind (or clear) a saved character still on a shot — real image ref."""
        if not (0 <= index < len(self._shots)):
            return
        row = self._shots[index]
        if path and Path(path).is_file():
            resolved = str(Path(path).resolve())
            row["character_path"] = resolved
            row["character_label"] = label or Path(resolved).name
            row["character_id"] = char_id
            row["character_extra_paths"] = tuple(extras or ())
            # Selecting a character always binds preferred still as this shot's ref
            row["ref_path"] = resolved
            try:
                self.prev_strip.record_and_refresh(resolved)
            except Exception:
                pass
        else:
            # Clearing character: if ref_path was the character still, clear it too
            cp = row.get("character_path")
            rp = row.get("ref_path")
            if cp and rp:
                try:
                    if Path(str(cp)).resolve() == Path(str(rp)).resolve():
                        row["ref_path"] = None
                except OSError:
                    if cp == rp:
                        row["ref_path"] = None
            row["character_path"] = None
            row["character_label"] = None
            row["character_id"] = None
            row["character_extra_paths"] = ()
        self._refresh_shot_still_ui(row)
        if sync_picker:
            self._sync_row_char_picker(row)
        try:
            self._sync_aspect_options()
        except Exception:
            pass
        try:
            self.cost_text.value = self._cost_label()
        except Exception:
            pass
        try:
            self._sync_prompt_counts()
        except Exception:
            pass
        try:
            self._sync_ref_budget()
        except Exception:
            pass

    async def _save_as_character(self, e: ft.ControlEvent) -> None:
        """Shortcut: open Characters with active shot ref still prefilled."""
        path: str | None = None
        idx = int(getattr(self, "_ref_target_index", 0) or 0)
        if 0 <= idx < len(self._shots):
            path = self._shots[idx].get("ref_path")
        if not path or not Path(path).is_file():
            # Fall back to any shot with a ref
            for row in self._shots:
                rp = row.get("ref_path")
                if rp and Path(rp).is_file():
                    path = rp
                    break
        if not path or not Path(path).is_file():
            self.status.value = (
                "Set a ref still on a shot first, then Save as character."
            )
            try:
                self.page.update()
            except Exception:
                pass
            return
        cv = getattr(self.state, "characters_view", None)
        ok = False
        if cv is not None and hasattr(cv, "open_with_still"):
            ok = bool(
                cv.open_with_still(
                    path,
                    suggested_name=Path(path).stem.replace("_", " "),
                )
            )
        switch = getattr(self.state, "switch_to_characters", None)
        if switch:
            switch()
        self.status.value = (
            f"Characters ← {Path(path).name} — add a name and Save."
            if ok
            else "Could not open Characters with this still."
        )
        try:
            self.page.update()
        except Exception:
            pass

    def receive_shot_ref(self, index: int, path: str) -> int:
        """
        Library / Send-to handoff: assign ``path`` as the ref still for shot
        ``index`` (0-based). Creates Shot 1 if the list is empty. Highlights
        the row, focuses strip target, and shows a snack confirmation.

        Returns the actual 0-based index used.
        """
        if not path or not Path(path).is_file():
            self.status.value = "Director: still path missing or unreadable."
            try:
                self.page.update()
            except Exception:
                pass
            return max(0, index)

        if not self._shots:
            self._add_shot_row(start=0, end=5, camera="Push in")
            index = 0

        if index < 0:
            index = 0
        if index >= len(self._shots):
            # Menu should only list existing rows; clamp rather than invent.
            index = len(self._shots) - 1

        self._ref_target_index = index
        self._set_shot_ref(index, path)
        self._highlight_shot(index)
        name = Path(path).name
        self.status.value = f"Ref still → Shot {index + 1}: {name}"
        try:
            from media_studio.flet_dialogs import show_snack

            show_snack(self.page, f"Director · Shot {index + 1} ref: {name}")
        except Exception:
            pass
        try:
            self.page.update()
        except Exception:
            pass
        return index

    def _highlight_shot(self, index: int) -> None:
        """Clear visual selection, then accent-border the target shot card."""
        for i, row in enumerate(self._shots):
            card = row.get("card")
            if card is None:
                continue
            try:
                if i == index:
                    card.border = ft.Border.all(2, ACCENT)
                    card.bgcolor = PANEL
                else:
                    card.border = ft.Border.all(1, BORDER)
                    card.bgcolor = PANEL_ELEVATED
            except Exception:
                pass

    def _on_prev_still(self, path: str) -> None:
        self._set_shot_ref(self._ref_target_index, path)
        self.status.value = (
            f"Shot {self._ref_target_index + 1} ref: {Path(path).name}"
        )
        try:
            self.page.update()
        except Exception:
            pass

    def _on_resolve_still(self, path: str) -> None:
        self._set_shot_ref(self._ref_target_index, path)
        self.status.value = (
            f"From Resolve → Shot {self._ref_target_index + 1}: {Path(path).name}"
        )
        try:
            self.resolve_strip.refresh()
            self.page.update()
        except Exception:
            pass

    def _on_global_character_picked(self, path: str, choice) -> None:
        """Bottom quick picker → bind on active shot (each shot also has its own picker)."""
        idx = int(getattr(self, "_ref_target_index", 0) or 0)
        if not self._shots:
            self._add_shot_row(start=0, end=5, camera="Push in")
            idx = 0
            self._ref_target_index = 0
        if idx < 0 or idx >= len(self._shots):
            idx = max(0, len(self._shots) - 1)
            self._ref_target_index = idx
        cid = getattr(choice, "id", None)
        label = getattr(choice, "label", None) or Path(path).name
        bundle = preferred_character_still_bundle(cid, still_path=path)
        still = bundle.get("path") or path
        extras = bundle.get("extras") or []
        self._set_shot_character(
            idx,
            still,
            label=bundle.get("label") or label,
            char_id=bundle.get("id") or cid,
            extras=extras,
            sync_picker=True,
        )
        self._highlight_shot(idx)
        warn = ""
        if bundle.get("low_res") or still_is_low_res(still):
            warn = " · low-res still — prefer 1K–2K Front"
        self.status.value = (
            f"Shot {idx + 1} · character: {bundle.get('label') or label}{warn}"
        )
        try:
            self.page.update()
        except Exception:
            pass

    def _on_character_picker_clear(self) -> None:
        # Global quick picker cleared — does not wipe per-shot binds
        pass

    async def _on_same_character_toggle(self, e: ft.ControlEvent | None = None) -> None:
        self._sync_apply_char_visibility()
        await self._on_polish_change(e)

    def _sync_apply_char_visibility(self) -> None:
        on_c = bool(self.cont_character.value)
        on_s = bool(self.cont_location.value)
        self.btn_apply_char_all.visible = on_c
        self.btn_apply_scene_all.visible = on_s
        bits = []
        if on_c:
            bits.append("Same character: Apply character to all shots.")
        else:
            bits.append("Different characters per shot OK.")
        if on_s:
            bits.append("Same location: Apply scene to all shots.")
        else:
            bits.append("Different scenes per shot OK.")
        self.same_char_hint.value = " ".join(bits)

    async def _apply_character_to_all_shots(self, e: ft.ControlEvent) -> None:
        """Copy first bound character onto every shot (Same character workflow)."""
        if not self._shots:
            self.status.value = "Add a shot first."
            try:
                self.page.update()
            except Exception:
                pass
            return
        src: dict[str, Any] | None = None
        for row in self._shots:
            cp = row.get("character_path")
            if cp and Path(str(cp)).is_file():
                src = row
                break
        if src is None:
            self.status.value = (
                "Set a character on one shot first, then Apply to all shots."
            )
            try:
                self.page.update()
            except Exception:
                pass
            return
        label = src.get("character_label")
        cid = src.get("character_id")
        path = src.get("character_path")
        extras = src.get("character_extra_paths") or ()
        for i in range(len(self._shots)):
            self._set_shot_character(
                i,
                path,
                label=label,
                char_id=cid,
                extras=extras,
                sync_picker=True,
            )
        self.status.value = (
            f"Applied character “{label or Path(str(path)).name}” to all "
            f"{len(self._shots)} shot(s)."
        )
        try:
            self.page.update()
        except Exception:
            pass

    async def _apply_scene_to_all_shots(self, e: ft.ControlEvent) -> None:
        """Copy first bound scene onto every shot (Same location workflow)."""
        if not self._shots:
            self.status.value = "Add a shot first."
            try:
                self.page.update()
            except Exception:
                pass
            return
        src: dict[str, Any] | None = None
        for row in self._shots:
            sp = row.get("scene_path")
            if sp and Path(str(sp)).is_file():
                src = row
                break
        if src is None:
            self.status.value = (
                "Set a scene on one shot first, then Apply scene to all shots."
            )
            try:
                self.page.update()
            except Exception:
                pass
            return
        # Copy location text from source when single-ref (if present)
        src_loc = ""
        try:
            loc_tf = src.get("location")
            if loc_tf is not None:
                src_loc = (loc_tf.value or "").strip()
        except Exception:
            src_loc = ""
        if not src_loc and not self._model_supports_scene_image():
            src_loc = location_text_from_scene(
                scene_id=src.get("scene_id"),
                scene_label=src.get("scene_label"),
            )
        for i in range(len(self._shots)):
            self._set_shot_scene(
                i,
                src.get("scene_path"),
                label=src.get("scene_label"),
                scene_id=src.get("scene_id"),
                sync_picker=True,
            )
            if src_loc and not self._model_supports_scene_image():
                loc_tf = self._shots[i].get("location")
                if loc_tf is not None:
                    try:
                        loc_tf.value = src_loc
                    except Exception:
                        pass
        self.status.value = (
            f"Applied scene “{src.get('scene_label') or Path(str(src.get('scene_path'))).name}” "
            f"to all {len(self._shots)} shot(s)."
        )
        try:
            self.page.update()
        except Exception:
            pass

    def refresh_character_picker(self) -> None:
        """Refresh Character + Scene pickers (tab focus)."""
        try:
            self.char_picker.refresh()
        except Exception:
            pass
        for row in self._shots:
            picker = row.get("char_picker")
            if picker is not None:
                try:
                    picker.refresh()
                    self._sync_row_char_picker(row)
                except Exception:
                    pass
            sp = row.get("scene_picker")
            if sp is not None:
                try:
                    sp.refresh()
                    self._sync_row_scene_picker(row)
                    self._apply_scene_picker_gate(sp)
                except Exception:
                    pass
        try:
            self._sync_scene_pickers_for_model()
        except Exception:
            pass

    async def _on_shot_field(self, e: ft.ControlEvent | None = None) -> None:
        self._sync_shot_timing_ui()
        self._rebuild_assembled_text()
        try:
            self.page.update()
        except Exception:
            pass

    # ----- enhance / generate -----

    async def _on_enhance(self, e: ft.ControlEvent) -> None:
        self._rebuild_assembled_text()
        shots = self._collect_shots()
        style = _dd(self.style_dd) or "None"
        polish = self._collect_polish()
        gen_audio = bool(self.gen_audio.value) if self.gen_audio.visible else False

        def _extra() -> dict[str, Any]:
            cont = polish.continuity_line() or "Continuity toggles off — do not force locks."
            vision = (polish.vision_notes or "").strip()
            gap_plan = polish.gap_lines()
            gap_text = " ".join(gap_plan) if gap_plan else polish.transition_line()
            model = _dd(self.model_dd) or ""
            snap: dict[str, Any] = {
                "workspace": "director",
                "mode": "multi_shot",
                "model": model,
                "total_duration_s": self._total_duration(),
                "style_pack": style,
                "master_brief": (self.master.value or "").strip(),
                "continuity": cont,
                "transition_default": polish.transition,
                "gap_transitions": list(polish.gap_transitions),
                "transition_plan": gap_plan,
                "energy_curve": bool(polish.energy_curve),
                "audio_generate": gen_audio,
                "audio_style": polish.audio_style if gen_audio else None,
                "sfx_note": polish.sfx_note if gen_audio else None,
                "vision_notes": vision or None,
                "shots": [
                    {
                        "index": i + 1,
                        "start_s": s.start_s,
                        "end_s": s.end_s,
                        "camera": s.camera,
                        "action": s.action,
                        "location_text": s.location_text or None,
                        "has_ref": bool(s.ref_path or s.character_path),
                        "has_character": bool(s.character_path),
                        "character_label": s.character_label,
                        "transition_into_next": (
                            polish.gap_at(i) if i < len(shots) - 1 else None
                        ),
                    }
                    for i, s in enumerate(shots)
                ],
            }
            # FLUX 3 continuous/first→last vs Kling multi-shot
            flux3 = False
            try:
                from media_studio.flux3_draft import is_flux3_video_model_choice

                flux3 = is_flux3_video_model_choice(model)
            except Exception:
                flux3 = False
            if flux3:
                has_end = len(shots) >= 2 and any(
                    (s.character_path or s.scene_path or s.ref_path) for s in shots[1:]
                )
                snap["model_prompt_brief"] = "flux3_video"
                snap["modality"] = (
                    "first_last"
                    if "first" in model.lower() and "last" in model.lower()
                    else "i2v"
                )
                snap["has_start_still"] = any(
                    bool(s.character_path or s.ref_path or s.scene_path) for s in shots
                )
                snap["has_end_still"] = bool(has_end)
                snap["creative_direction"] = vision or None
                snap["guidance"] = (
                    "FLUX 3 Director: continuous take or first→last — NOT Kling multi_prompt. "
                    "Tighten master + action into one continuous motion prompt with format lead, "
                    "audio bed when relevant, layout lock if character/start still is bound. "
                    f"Continuity: {cont}. "
                    + (
                        f"Vision notes (Enhance only): {vision}. "
                        if vision
                        else ""
                    )
                )
            else:
                snap["guidance"] = (
                    "Rewrite for Kling multi-shot / director video generation. "
                    "Output should remain useful as: (1) a tightened master brief and "
                    "(2) clear per-shot action language with camera moves. "
                    "Keep action (character) separate from location_text when present. "
                    "Preserve shot order and timing intent. "
                    f"Honor continuity flags: {cont} "
                    f"Per-gap transitions (emit clear cut vs soft dissolve vs continuous "
                    f"action language): {gap_text} "
                    "Continuous = no cut, seamless motion, ref stills as motion keyframes; "
                    "Hard cut = clean edit; Soft dissolve = gentle blend. "
                    + (
                        "Include restrained→peak→resolve energy language in the master. "
                        if polish.energy_curve
                        else ""
                    )
                    + (
                        f"Audio style for generation: {polish.audio_style}. "
                        + (f"SFX notes: {polish.sfx_note}. " if polish.sfx_note else "")
                        if gen_audio
                        else "No generated audio. "
                    )
                    + (
                        f"Vision notes (Enhance creative direction only — weave into "
                        f"tone/language, do not dump raw unless useful): {vision}. "
                        if vision
                        else ""
                    )
                    + "Do not invent API fields. Prefer cinematic, concrete camera "
                    "language matching the presets."
                )
            return snap

        await run_prompt_enhance(
            page=self.page,
            state=self.state,
            prompt_field=self.assembled,
            get_model=lambda: _dd(self.model_dd),
            get_extra_context=_extra,
            status_ctrl=self.status,
            job_progress=self.job_progress,
            enhance_btn=self.btn_enhance,
            busy_controls=[self.btn_generate],
            context_label="director brief",
            allow_empty_with_context=True,
            busy_scope="director",
        )
        # Soft-split: if Enhance rewrote assembled, try to push first paragraph to master
        try:
            text = (self.assembled.value or "").strip()
            if text.lower().startswith("master:"):
                first, _, rest = text.partition("\n")
                master_line = first.split(":", 1)[-1].strip()
                if master_line and not (self.master.value or "").strip():
                    self.master.value = master_line
        except Exception:
            pass
        self.apply_key_gates()
        try:
            self.page.update()
        except Exception:
            pass

    async def _run(self, e: ft.ControlEvent) -> None:
        if self.state.is_busy("director"):
            return
        from media_studio.secrets_store import has_fal_key

        if not has_fal_key():
            self.status.value = "FAL API key required — open Settings (gear icon)."
            self.page.update()
            return

        spec = self._current_spec()
        shots = self._collect_shots()
        total = self._total_duration()
        polish = self._collect_polish()
        errs = validate_shots(
            shots,
            total_duration_s=total,
            max_shots=spec.max_shots,
            allow_overlap=False,
            polish=polish,
        )
        if errs:
            self.status.value = "Cannot Generate — " + " · ".join(errs)
            try:
                self.page.update()
            except Exception:
                pass
            return

        master = (self.master.value or "").strip()
        if not master:
            # Allow empty master if assembled has content, but prefer master
            if not (self.assembled.value or "").strip():
                self.status.value = "Enter a master brief (or fill shot actions)."
                self.page.update()
                return

        # Unique-asset ref budget — block Generate when over
        try:
            self._sync_ref_budget()
            budget = getattr(self, "_last_ref_budget", None)
            if budget is not None and budget.over:
                reason = budget.reason_over or (
                    f"Refs {budget.used}/{budget.max_refs} over budget."
                )
                self.status.value = f"Cannot Generate — {reason}"
                try:
                    self.page.update()
                except Exception:
                    pass
                return
        except Exception:
            pass

        # FLUX 3 continuous / first→last: still requirements before upload
        eng = getattr(spec, "engine", "") or ""
        if eng == "flux3":
            stills: list[str] = []
            for sh in shots:
                for cand in (
                    sh.character_path,
                    sh.scene_path,
                    sh.ref_path,
                ):
                    if cand and Path(str(cand)).is_file():
                        try:
                            p = str(Path(str(cand)).resolve())
                        except OSError:
                            p = str(cand)
                        if p not in stills:
                            stills.append(p)
                        break
            if getattr(spec, "requires_end_frame", False):
                if len(stills) < 2:
                    self.status.value = (
                        "Cannot Generate — FLUX 3 First→Last needs two stills "
                        "(Shot 1 = start, Shot 2 = end)."
                    )
                    try:
                        self.page.update()
                    except Exception:
                        pass
                    return
            elif not stills:
                self.status.value = (
                    "Cannot Generate — FLUX 3 Continuous I2V needs a character "
                    "or start still on Shot 1."
                )
                try:
                    self.page.update()
                except Exception:
                    pass
                return

        # Kling multi_prompt 512 hard limit — compact then block if still over
        max_c = getattr(spec, "multi_prompt_max_chars", None)
        if max_c:
            try:
                multi = multi_prompt_from_shots(
                    shots,
                    master=master,
                    style_pack=_dd(self.style_dd),
                    polish=polish,
                    generate_audio=bool(self.gen_audio.value)
                    if self.gen_audio.visible
                    else False,
                    max_chars=int(max_c),
                    scene_as_image_ref=bool(
                        getattr(spec, "supports_scene_image_ref", False)
                    ),
                )
                limit_errs = validate_multi_prompt_limits(multi, max_chars=int(max_c))
                if limit_errs:
                    self.status.value = "Cannot Generate — " + " · ".join(limit_errs)
                    self._sync_prompt_counts()
                    try:
                        self.page.update()
                    except Exception:
                        pass
                    return
            except Exception as exc:
                self.status.value = f"Cannot Generate — prompt check failed: {exc}"
                try:
                    self.page.update()
                except Exception:
                    pass
                return

        # Character bind must have a readable still file
        for i, sh in enumerate(shots):
            if sh.character_path and not Path(sh.character_path).is_file():
                self.status.value = (
                    f"Cannot Generate — Shot {i + 1} character still missing: "
                    f"{sh.character_path}"
                )
                try:
                    self.page.update()
                except Exception:
                    pass
                return

        # Cost guard optional
        try:
            from media_studio.flet_dialogs import confirm_cost_if_needed

            est = estimate_director_cost(
                spec,
                duration_s=total,
                generate_audio=bool(self.gen_audio.value),
                resolution=self._selected_resolution(spec),
            )
            ok = await confirm_cost_if_needed(
                self.page,
                estimated_usd=est,
                job_label=f"Director · {spec.label}",
            )
            if not ok:
                self.status.value = "Generate cancelled (cost guard)."
                self.page.update()
                return
        except Exception:
            pass

        if not self.state.try_busy("director"):
            return
        self.btn_generate.disabled = True
        try:
            self.player.clear()
        except Exception:
            pass
        self.job_progress.start("Starting Director…", self.page)
        self.status.value = f"Running {spec.label}…"
        self.page.update()

        def on_progress(msg: str) -> None:
            self.job_progress.set_message(classify_progress(msg), self.page)

        try:
            from media_studio.job_context import to_thread_with_job

            result = await to_thread_with_job(
                self.state,
                run_director,
                master=master,
                shots=shots,
                model_label=_dd(self.model_dd),
                duration_s=total,
                aspect_ratio=(
                    None
                    if (_dd(self.aspect_dd) or "").lower().startswith("auto")
                    else _dd(self.aspect_dd)
                ),
                style_pack=_dd(self.style_dd),
                generate_audio=bool(self.gen_audio.value)
                if self.gen_audio.visible
                else None,
                resolution=self._selected_resolution(spec),
                polish=polish,
                output_dir=self.state.output_dir,
                on_progress=on_progress,
                angle_mode=(
                    self._current_angle_mode()
                    if director_shows_pack_toggle(spec)
                    else "front_only"
                ),
            )
            self.cost_text.value = result.cost_label or self._cost_label()
            if result.ok and result.path:
                self._result_path = result.path
                done = result.status or "OK"
                # Surface auto-downscale note when proxies were used
                try:
                    proxy_notes = [
                        n
                        for n in (result.notes or [])
                        if "downscaled" in (n or "").lower()
                        or "still_proxy" in (n or "").lower()
                        or "using downscaled" in (n or "").lower()
                    ]
                    if proxy_notes and "downscaled" not in done.lower():
                        done = f"{done} · Using downscaled refs for API"
                except Exception:
                    pass
                self.job_progress.finish_ok(done, self.page)
                self.status.value = done
                try:
                    self.player.set_result(result.path)
                except Exception:
                    pass
                try:
                    show_result_actions(
                        self.btn_folder,
                        self.btn_resolve,
                        visible=True,
                    )
                    self.result_actions_row.visible = True
                except Exception:
                    try:
                        self.btn_folder.visible = True
                        self.btn_resolve.visible = True
                        self.result_actions_row.visible = True
                    except Exception:
                        pass
                try:
                    self._refresh_send_menu(result.path)
                except Exception:
                    pass
            else:
                err = result.status or "Failed."
                self.job_progress.finish_error(err, self.page)
                self.status.value = err
        except Exception as exc:
            from media_studio.errors import friendly_error

            err = friendly_error(exc, context="Director", media_kind="image")
            self.job_progress.finish_error(err, self.page)
            self.status.value = err
            traceback.print_exc()
        finally:
            self.state.clear_busy("director")
            self.apply_key_gates()
            try:
                self.page.update()
            except Exception:
                pass


    # =========================================================================
    # Keyframe Take (FLUX 3 continuous)
    # =========================================================================

    def _kf_duration(self) -> float:
        try:
            return float(_dd(self.kf_dur_dd) or 8)
        except (TypeError, ValueError):
            return 8.0

    def _kf_collect_pins(self) -> list:
        from media_studio.director_keyframes import KeyframePin

        out: list = []
        for row in self._kf_pins:
            path = row.get("path")
            if not path:
                continue
            try:
                t = float(row["time_field"].value or 0)
            except (TypeError, ValueError, AttributeError):
                t = float(row.get("time_s") or 0)
            out.append(
                KeyframePin(
                    path=str(path),
                    time_s=t,
                    label=str(row.get("label") or ""),
                )
            )
        return out

    def _kf_refresh_cost(self, e=None) -> None:
        try:
            self.kf_cost_text.value = format_keyframe_take_cost(
                duration_s=self._kf_duration(),
                resolution=_dd(self.kf_res_dd) or "720p",
                draft=bool(self.kf_draft.value),
            )
        except Exception:
            pass
        try:
            self.page.update()
        except Exception:
            pass

    async def _on_kf_duration(self, e) -> None:
        self._kf_refresh_cost()

    async def _on_kf_cost_refresh(self, e=None) -> None:
        self._kf_refresh_cost()

    def _kf_sync_pins_meta(self) -> None:
        n = len(self._kf_pins)
        self.kf_pins_meta.value = f"Pins {n} / {KEYFRAME_MAX_PINS}"
        try:
            self.btn_kf_add_pin.disabled = n >= KEYFRAME_MAX_PINS
        except Exception:
            pass

    def _kf_rebuild_pin_rows(self) -> None:
        rows: list = []
        for i, pin in enumerate(self._kf_pins):
            rows.append(self._kf_make_pin_row(i, pin))
        self.kf_pins_host.controls = rows
        self._kf_sync_pins_meta()

    def _kf_make_pin_row(self, index: int, pin: dict) -> ft.Control:
        path = pin.get("path") or ""
        name = Path(path).name if path else "—"
        has_file = bool(path and Path(path).is_file())
        thumb = ft.Image(
            src=path if has_file else "",
            width=48,
            height=48,
            fit=ft.BoxFit.COVER,
            visible=has_file,
            border_radius=4,
        )
        thumb_tap = ft.Container(
            content=thumb,
            on_click=self._kf_make_expand(index),
            ink=True,
            tooltip="Click to enlarge",
            border_radius=4,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
        )
        btn_expand = ft.IconButton(
            icon=ft.Icons.ZOOM_IN,
            icon_size=18,
            icon_color=TEXT_MUTED,
            tooltip="Enlarge pin still",
            on_click=self._kf_make_expand(index),
            disabled=not has_file,
        )
        time_field = ft.TextField(
            label="t (s)",
            value=str(pin.get("time_s", 0)),
            width=72,
            dense=True,
            filled=True,
            fill_color=PANEL_ELEVATED,
            border_color=BORDER,
            color=TEXT,
            text_size=FONT_SM,
            on_change=self._on_kf_cost_refresh,
        )
        pin["time_field"] = time_field
        lab = ft.Text(
            pin.get("label") or name,
            size=FONT_SM,
            color=TEXT,
            max_lines=1,
            expand=True,
        )
        btn_rm = ft.IconButton(
            icon=ft.Icons.CLOSE,
            icon_size=18,
            icon_color=TEXT_MUTED,
            tooltip="Remove pin",
            on_click=self._kf_make_remove(index),
        )
        btn_up = ft.IconButton(
            icon=ft.Icons.ARROW_UPWARD,
            icon_size=16,
            icon_color=TEXT_MUTED,
            tooltip="Move up",
            on_click=self._kf_make_move(index, -1),
            disabled=index <= 0,
        )
        btn_dn = ft.IconButton(
            icon=ft.Icons.ARROW_DOWNWARD,
            icon_size=16,
            icon_color=TEXT_MUTED,
            tooltip="Move down",
            on_click=self._kf_make_move(index, 1),
            disabled=index >= len(self._kf_pins) - 1,
        )
        return ft.Container(
            content=ft.Row(
                [
                    ft.Text(f"{index + 1}", size=FONT_SM, color=TEXT_MUTED, width=18),
                    thumb_tap,
                    lab,
                    time_field,
                    btn_expand,
                    btn_up,
                    btn_dn,
                    btn_rm,
                ],
                spacing=6,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=PANEL_ELEVATED,
            border=ft.Border.all(1, BORDER),
            border_radius=6,
            padding=6,
        )

    def _kf_make_expand(self, index: int):
        async def _click(_e: ft.ControlEvent) -> None:
            if 0 <= index < len(self._kf_pins):
                path = self._kf_pins[index].get("path") or ""
                if path and Path(path).is_file():
                    lab = self._kf_pins[index].get("label") or Path(path).name
                    self._open_preview(
                        path, title=f"Keyframe pin {index + 1} · {lab}"
                    )
                else:
                    self.status.value = "Pin still missing — cannot enlarge."
                    try:
                        self.page.update()
                    except Exception:
                        pass

        return _click

    def _open_preview(self, path: str, *, title: str = "Still preview") -> None:
        """Large still overlay (same pattern as Characters / Scenes)."""
        p = Path(path)
        if not p.is_file():
            self.status.value = f"Missing still: {path}"
            try:
                self.page.update()
            except Exception:
                pass
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

    def _kf_make_remove(self, index: int):
        async def _click(_e) -> None:
            if 0 <= index < len(self._kf_pins):
                self._kf_pins.pop(index)
                self._kf_rebuild_pin_rows()
                try:
                    self.page.update()
                except Exception:
                    pass

        return _click

    def _kf_make_move(self, index: int, delta: int):
        async def _click(_e) -> None:
            j = index + delta
            if 0 <= index < len(self._kf_pins) and 0 <= j < len(self._kf_pins):
                self._kf_pins[index], self._kf_pins[j] = (
                    self._kf_pins[j],
                    self._kf_pins[index],
                )
                self._kf_rebuild_pin_rows()
                try:
                    self.page.update()
                except Exception:
                    pass

        return _click

    def _kf_add_pin_data(self, path: str, label: str = "") -> int:
        """Append a pin; returns 0-based index or -1 on failure."""
        if len(self._kf_pins) >= KEYFRAME_MAX_PINS:
            self.status.value = f"Max {KEYFRAME_MAX_PINS} pins."
            return -1
        try:
            resolved = str(Path(path).resolve())
        except OSError:
            resolved = path
        if not Path(resolved).is_file():
            self.status.value = f"Still missing: {path}"
            return -1
        n = len(self._kf_pins)
        times = auto_spread_pin_times(n + 1, self._kf_duration())
        t = times[-1] if times else 0.0
        self._kf_pins.append(
            {"path": resolved, "time_s": t, "label": label or Path(resolved).name}
        )
        self._kf_apply_spread_times()
        self._kf_rebuild_pin_rows()
        try:
            self.kf_prev_strip.record_and_refresh(resolved)
        except Exception:
            pass
        self.status.value = f"Pin added: {Path(resolved).name}"
        return len(self._kf_pins) - 1

    def _kf_replace_pin(self, index: int, path: str, label: str = "") -> int:
        """Replace pin at index with a new still; keeps time. Returns index."""
        try:
            resolved = str(Path(path).resolve())
        except OSError:
            resolved = path
        if not Path(resolved).is_file():
            self.status.value = f"Still missing: {path}"
            return max(0, index)
        if index < 0 or index >= len(self._kf_pins):
            return self._kf_add_pin_data(resolved, label=label)
        pin = self._kf_pins[index]
        pin["path"] = resolved
        pin["label"] = label or Path(resolved).name
        self._kf_rebuild_pin_rows()
        try:
            self.kf_prev_strip.record_and_refresh(resolved)
        except Exception:
            pass
        self.status.value = f"Pin {index + 1} replaced: {Path(resolved).name}"
        return index

    def receive_keyframe_pin(
        self,
        path: str,
        *,
        pin_index: int | None = None,
        label: str = "",
    ) -> int:
        """
        Send-to handoff: add or replace a Keyframe Take pin.

        Switches to Keyframe Take mode, focuses Director, returns pin index used.
        """
        # Ensure Keyframe Take UI is visible
        try:
            self._mode_nav.set_selected("keyframe_take", notify=False)
        except Exception:
            pass
        self._on_director_mode("keyframe_take")
        if pin_index is not None:
            idx = self._kf_replace_pin(int(pin_index), path, label=label)
        else:
            idx = self._kf_add_pin_data(path, label=label)
            if idx < 0:
                idx = max(0, len(self._kf_pins) - 1)
        name = Path(path).name if path else "still"
        try:
            show_snack(self.page, f"Director · Keyframe Take · Pin {idx + 1}: {name}")
        except Exception:
            pass
        try:
            self.page.update()
        except Exception:
            pass
        return idx

    def _kf_on_prev_still(self, path: str) -> None:
        """Previously used / Resolve strip → add as new pin."""
        self._kf_add_pin_data(path)
        try:
            self.page.update()
        except Exception:
            pass

    def _kf_apply_spread_times(self) -> None:
        times = auto_spread_pin_times(len(self._kf_pins), self._kf_duration())
        for pin, t in zip(self._kf_pins, times):
            pin["time_s"] = t
            tf = pin.get("time_field")
            if tf is not None:
                try:
                    tf.value = str(t)
                except Exception:
                    pass

    async def _kf_auto_spread(self, e) -> None:
        self._kf_apply_spread_times()
        self._kf_rebuild_pin_rows()
        self.status.value = "Pin times auto-spread across duration."
        try:
            self.page.update()
        except Exception:
            pass

    async def _kf_add_pin_pick(self, e) -> None:
        try:
            files = await pick_image(self.page, dialog_title="Keyframe pin still")
        except Exception as exc:
            self.status.value = f"Picker error: {exc}"
            self.page.update()
            return
        if not files or not files[0].path:
            return
        self._kf_add_pin_data(str(files[0].path))
        try:
            self.page.update()
        except Exception:
            pass

    def _kf_on_character_add_pin(self, still_path: str, choice) -> None:
        # Prefer front/hero still
        path = still_path
        label = getattr(choice, "label", None) or getattr(choice, "name", None) or ""
        try:
            cid = getattr(choice, "character_id", None) or getattr(choice, "id", None)
            bundle = preferred_character_still_bundle(cid, still_path=still_path)
            if bundle.get("path"):
                path = bundle["path"]
            if bundle.get("label"):
                label = bundle["label"]
        except Exception:
            pass
        self._kf_add_pin_data(path, label=str(label or "Character"))
        try:
            self.page.update()
        except Exception:
            pass

    def _kf_on_scene_add_pin(self, still_path: str, choice) -> None:
        label = getattr(choice, "label", None) or getattr(choice, "name", None) or "Scene"
        # Prefer hero plate when available
        path = still_path
        try:
            hero = getattr(choice, "hero_path", None) or getattr(choice, "still_path", None)
            if hero and Path(str(hero)).is_file():
                path = str(hero)
        except Exception:
            pass
        self._kf_add_pin_data(path, label=str(label))
        try:
            self.page.update()
        except Exception:
            pass

    async def _on_kf_enhance(self, e) -> None:
        pins = self._kf_collect_pins()
        model = "FLUX 3 · Keyframe Take"

        def _extra() -> dict:
            return {
                "workspace": "director",
                "mode": "keyframe_take",
                "modality": "keyframes",
                "model_prompt_brief": "flux3_video",
                "has_start_still": bool(pins),
                "pin_count": len(pins),
                "pin_times": [p.time_s for p in pins],
                "duration_s": self._kf_duration(),
                "draft_first": bool(self.kf_draft.value),
                "guidance": (
                    "FLUX 3 Keyframe Take: one continuous motion prompt. "
                    "Pins are pose plates at times — layout lock between pins; "
                    "no hard-cut multi-shot language. Format first; audio first-class."
                ),
            }

        await run_prompt_enhance(
            page=self.page,
            state=self.state,
            prompt_field=self.kf_prompt,
            get_model=lambda: model,
            get_image=lambda: pins[0].path if pins else None,
            get_extra_context=_extra,
            status_ctrl=self.status,
            job_progress=self.job_progress,
            enhance_btn=self.btn_kf_enhance,
            busy_controls=[self.btn_kf_generate],
            context_label="keyframe take prompt",
            allow_empty_with_context=False,
            busy_scope="director",
        )
        self.apply_key_gates()
        try:
            self.page.update()
        except Exception:
            pass

    async def _run_keyframe_take(self, e) -> None:
        if self.state.is_busy("director"):
            return
        from media_studio.secrets_store import has_fal_key

        if not has_fal_key():
            self.status.value = "FAL API key required — open Settings (gear icon)."
            self.page.update()
            return

        pins = self._kf_collect_pins()
        dur = self._kf_duration()
        errs = validate_keyframe_pins(pins, duration_s=dur)
        if errs:
            self.status.value = "Cannot Generate — " + " · ".join(errs)
            self.page.update()
            return
        prompt = (self.kf_prompt.value or "").strip()
        if not prompt:
            self.status.value = "Enter a global motion prompt."
            self.page.update()
            return

        # Soft inject layout-lock when pins present
        if pins and "layout" not in prompt.lower() and "preserve" not in prompt.lower():
            # Don't mutate user field — only enhance service path; generate uses as-is
            # but add a note
            pass

        try:
            from media_studio.flet_dialogs import confirm_cost_if_needed
            from media_studio.director_keyframes import estimate_keyframe_take_cost

            est = estimate_keyframe_take_cost(
                duration_s=dur,
                resolution=_dd(self.kf_res_dd) or "720p",
                draft=bool(self.kf_draft.value),
            )
            ok = await confirm_cost_if_needed(
                self.page,
                estimated_usd=est,
                job_label="Director · Keyframe Take",
            )
            if not ok:
                self.status.value = "Generate cancelled (cost guard)."
                self.page.update()
                return
        except Exception:
            pass

        if not self.state.try_busy("director"):
            return
        self.btn_kf_generate.disabled = True
        self.job_progress.start("Starting Keyframe Take…", self.page)
        self.status.value = "Running FLUX 3 Keyframe Take…"
        self.page.update()

        def on_progress(msg: str) -> None:
            self.job_progress.set_message(classify_progress(msg), self.page)

        try:
            from media_studio.job_context import to_thread_with_job

            result = await to_thread_with_job(
                self.state,
                run_keyframe_take,
                prompt=prompt,
                pins=pins,
                duration_s=dur,
                aspect_ratio=_dd(self.kf_aspect_dd) or "auto",
                resolution=_dd(self.kf_res_dd) or "720p",
                generate_audio=bool(self.kf_audio.value),
                draft=bool(self.kf_draft.value),
                output_dir=self.state.output_dir,
                on_progress=on_progress,
            )
            self.kf_cost_text.value = result.cost_label or format_keyframe_take_cost(
                duration_s=dur,
                resolution=_dd(self.kf_res_dd) or "720p",
                draft=bool(self.kf_draft.value),
            )
            if result.ok and result.path:
                self._result_path = result.path
                done = result.status or "OK"
                self.job_progress.finish_ok(done, self.page)
                self.status.value = done
                try:
                    self.player.set_result(result.path)
                except Exception:
                    pass
                if result.is_draft and result.draft_cache_url:
                    self._kf_draft_cache = result.draft_cache_url
                    self.btn_kf_enhance_full.disabled = False
                else:
                    self._kf_draft_cache = None
                    self.btn_kf_enhance_full.disabled = True
                try:
                    show_result_actions(
                        self.btn_folder, self.btn_resolve, visible=True
                    )
                    self.result_actions_row.visible = True
                except Exception:
                    pass
                try:
                    self._refresh_send_menu(result.path)
                except Exception:
                    pass
            else:
                err = result.status or "Failed."
                self.job_progress.finish_error(err, self.page)
                self.status.value = err
        except Exception as exc:
            from media_studio.errors import friendly_error

            err = friendly_error(exc, context="Keyframe Take", media_kind="image")
            self.job_progress.finish_error(err, self.page)
            self.status.value = err
            traceback.print_exc()
        finally:
            self.state.clear_busy("director")
            self.apply_key_gates()
            try:
                self.btn_kf_generate.disabled = False
            except Exception:
                pass
            try:
                self.page.update()
            except Exception:
                pass

    async def _on_kf_enhance_full(self, e) -> None:
        if self.state.is_busy("director"):
            return
        cache = (self._kf_draft_cache or "").strip()
        if not cache:
            self.status.value = "Enhance to full needs a draft first."
            self.page.update()
            return
        from media_studio.secrets_store import has_fal_key

        if not has_fal_key():
            self.status.value = "FAL API key required."
            self.page.update()
            return
        if not self.state.try_busy("director"):
            return
        self.btn_kf_enhance_full.disabled = True
        self.job_progress.start("Enhancing draft to full…", self.page)
        self.page.update()

        def on_progress(msg: str) -> None:
            self.job_progress.set_message(classify_progress(msg), self.page)

        try:
            from media_studio.flux3_draft import (
                estimate_full_cost_usd,
                run_draft_enhance,
            )
            from media_studio.job_context import to_thread_with_job

            # Fake spec-like for full cost
            class _S:
                cost_per_second = 0.17
                cost_per_second_by_resolution = {"720p": 0.17, "1080p": 0.29}
                default_resolution = "720p"
                label = "FLUX 3 · Keyframe Take"

            dur = self._kf_duration()
            full_est = estimate_full_cost_usd(
                _S(),
                duration_s=dur,
                resolution=_dd(self.kf_res_dd) or "720p",
                generate_audio=bool(self.kf_audio.value),
            )
            result = await to_thread_with_job(
                self.state,
                run_draft_enhance,
                draft_cache_url=cache,
                output_dir=self.state.output_dir,
                prompt_hint=(self.kf_prompt.value or "keyframe")[:40],
                model_key="flux 3 keyframe take",
                on_progress=on_progress,
                duration_s=dur,
                full_cost_usd=full_est,
            )
            if result.ok and result.path:
                self._result_path = result.path
                self._kf_draft_cache = None
                self.btn_kf_enhance_full.disabled = True
                self.kf_cost_text.value = result.cost_estimate or self.kf_cost_text.value
                done = result.status or "Enhance to full OK"
                self.job_progress.finish_ok(done, self.page)
                self.status.value = done
                try:
                    self.player.set_result(result.path)
                except Exception:
                    pass
                try:
                    show_result_actions(
                        self.btn_folder, self.btn_resolve, visible=True
                    )
                    self._refresh_send_menu(result.path)
                except Exception:
                    pass
            else:
                err = result.status or "Enhance failed."
                self.job_progress.finish_error(err, self.page)
                self.status.value = err
                self.btn_kf_enhance_full.disabled = False
        except Exception as exc:
            from media_studio.errors import friendly_error

            err = friendly_error(exc, context="Keyframe enhance")
            self.job_progress.finish_error(err, self.page)
            self.status.value = err
            self.btn_kf_enhance_full.disabled = False
        finally:
            self.state.clear_busy("director")
            self.apply_key_gates()
            try:
                self.page.update()
            except Exception:
                pass
