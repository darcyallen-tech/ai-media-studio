"""
Flet desktop shell for AI Media Studio.

Tabs: Studio (Image/Video) · Tools · Creative Vision · Frame Editor · Audio · Library.
Providers: fal (main), xAI (Enhance), Runware (Frame Editor / Aleph).
"""

from __future__ import annotations

import asyncio
import json
import traceback
from pathlib import Path
from typing import Any, Callable

import flet as ft

from media_studio.config import (
    APP_TITLE,
    APP_VERSION,
    GITHUB_URL,
    MODEL_LABELS,
    OUTPUT_DIR,
    ensure_output_dir,
)
from media_studio.folder_util import open_folder
from media_studio.flet_theme import (
    ACCENT,
    ACCENT_BRIGHT,
    BG,
    BORDER,
    FONT_LG,
    FONT_MD,
    FONT_SM,
    FONT_XL,
    PANEL,
    PANEL_ELEVATED,
    PillNav,
    RAIL_WIDTH,
    SUCCESS,
    TEXT,
    TEXT_MUTED,
    label,
    page_theme,
    panel,
    section_title,
    styled_dropdown,
)
from media_studio.params_ui import build_parameters_dict, control_options, parameters_to_json
from media_studio.pricing import live_estimate_cost
from media_studio.scenarios import (
    BLANK_CANVAS_KEY,
    DEFAULT_IMAGE_MODEL,
    SCENE_DEFAULTS,
    build_scenario_prompt,
    default_scenario,
    get_scenario,
    is_blank_canvas,
    prompt_is_scenario_defaultish,
    simple_control_schema,
)
from media_studio.scene_builder import (
    CAMERA_FEEL,
    DECOR_AMOUNT,
    FURNITURE_DENSITY,
    PLANTS,
    ROOM_TYPES,
    styles_for_room,
)
from media_studio.flet_aleph import FrameEditorView
from media_studio.flet_audio import AudioView
from media_studio.flet_dialogs import close_dialog, show_dialog, show_snack
from media_studio.flet_library import LibraryView
from media_studio.flet_pickers import pick_image
from media_studio.flet_progress import CollapsibleJobLog, JobProgress, classify_progress
from media_studio.flet_tools import ToolsView
from media_studio.flet_video import StudioVideoView
from media_studio.flet_vision import CreativeVisionView
from media_studio.services import describe_job_kind, enhance_prompt, generate
from media_studio.flet_model_hint import make_best_for_line, update_best_for_line
from media_studio.flet_source_strip import ResolveSourcesStrip
from media_studio.source_history import gallery_value, record_source


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dd_value(dd: ft.Dropdown) -> str | None:
    return dd.value


def _safe_float(v: Any, default: float = 0.6) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


class StudioState:
    """Shared Studio session state (Image + Video handoff, busy lock, app scenario)."""

    def __init__(self) -> None:
        # Prefer persisted output folder (Phase E); fall back to project outputs/
        from media_studio.ui_prefs import get_output_dir_pref

        pref = get_output_dir_pref()
        if pref:
            try:
                self.output_dir = str(ensure_output_dir(Path(pref)))
            except OSError:
                self.output_dir = str(OUTPUT_DIR)
        else:
            self.output_dir = str(OUTPUT_DIR)
        self.source_path: str | None = None
        # App-level scenario (shared by Image / Video / Tools)
        from media_studio.ui_prefs import get_app_scenario

        sc = get_scenario(get_app_scenario()) or default_scenario()
        self.scenario_key: str = sc.key
        self.scenario_label: str = sc.label
        self.comparison: list[str] = []
        self.compare_index: int = 0
        # Global flag (any scope busy) kept for back-compat; prefer try_busy/is_busy
        self.busy: bool = False
        # Per-tab busy scopes so a long Vision job doesn't freeze Image/Audio/etc.
        self._busy_scopes: set[str] = set()
        # Video tab handoff
        self.video_ref_path: str | None = None
        self.video_source_path: str | None = None
        # Set by main() so Image / Library can switch tabs
        self.switch_to_video: Callable[[], None] | None = None
        self.switch_to_image: Callable[[], None] | None = None
        self.switch_to_tools: Callable[[str | None], None] | None = None
        self.video_view: Any = None
        self.image_view: Any = None
        self.library_view: Any = None
        self.tools_view: Any = None
        # Tools / Audio secondary pill selection (session memory)
        self.tools_selected_id: str = "upscale"
        self.audio_selected_id: str = "music"
        # Library media filter: all | image | video | audio
        self.library_filter: str = "all"
        # Library job filter: "" = all jobs
        self.library_job_filter: str = ""
        # Optional Job / Listing (address, client, shoot) — routes outputs under jobs/
        from media_studio.ui_prefs import get_job_name

        self.job_name: str = get_job_name()
        # Key-gate listeners (views refresh generate button enablement)
        self._key_listeners: list[Callable[[], None]] = []
        # App scenario change listeners: callback(scenario_key)
        self._scenario_listeners: list[Callable[[str], None]] = []
        # Frame Editor ↔ Studio round-trip: pin edited still back to same keyframe slot
        # Keys: slot_id, slot_index, pin, timestamp_s (all optional except when set)
        self.frame_editor_return: dict[str, Any] | None = None

    def on_keys_changed(self, callback: Callable[[], None]) -> None:
        self._key_listeners.append(callback)

    def notify_keys_changed(self) -> None:
        for cb in list(self._key_listeners):
            try:
                cb()
            except Exception:
                pass

    # ----- per-tab busy (Phase F) -----

    def try_busy(self, scope: str) -> bool:
        """
        Acquire busy for ``scope`` (e.g. ``image``, ``video``, ``vision``).

        Returns False if this scope is already busy. Other scopes may still run.
        """
        key = (scope or "global").strip() or "global"
        if key in self._busy_scopes:
            return False
        self._busy_scopes.add(key)
        self.busy = True
        return True

    def clear_busy(self, scope: str) -> None:
        """Release busy for ``scope``; ``self.busy`` stays true if any scope remains."""
        key = (scope or "global").strip() or "global"
        self._busy_scopes.discard(key)
        self.busy = bool(self._busy_scopes)

    def is_busy(self, scope: str | None = None) -> bool:
        """If ``scope`` is set, only that tab; otherwise any tab is busy."""
        if scope is None:
            return bool(self._busy_scopes)
        return (scope or "").strip() in self._busy_scopes

    def on_scenario_changed(self, callback: Callable[[str], None]) -> None:
        self._scenario_listeners.append(callback)

    def set_job_name(self, name: str | None, *, persist: bool = True) -> str:
        """Set Job / Listing label; empty clears. Returns stored value."""
        val = (name or "").strip()
        self.job_name = val
        if persist:
            try:
                from media_studio.ui_prefs import set_job_name as _save_job

                _save_job(val)
            except Exception:
                pass
        return val

    def set_scenario(self, key_or_label: str, *, notify: bool = True, persist: bool = True) -> str:
        """
        Set app-level scenario. Returns resolved scenario key.

        When ``notify`` is True, all registered views reconfigure for the scenario.
        """
        sc = get_scenario(key_or_label) or default_scenario()
        self.scenario_key = sc.key
        self.scenario_label = sc.label
        if persist:
            try:
                from media_studio.ui_prefs import set_app_scenario

                set_app_scenario(sc.key)
            except Exception:
                pass
        if notify:
            for cb in list(self._scenario_listeners):
                try:
                    cb(sc.key)
                except Exception:
                    traceback.print_exc()
        return sc.key


# ---------------------------------------------------------------------------
# Studio → Image view
# ---------------------------------------------------------------------------


class StudioImageView:
    """Left controls + right comparison for still generation."""

    def __init__(self, page: ft.Page, state: StudioState) -> None:
        self.page = page
        self.state = state

        # --- left controls ---
        self.source_preview = ft.Image(
            src="",
            fit=ft.BoxFit.CONTAIN,  # never stretch — letterbox if needed
            width=RAIL_WIDTH - 40,
            height=120,
            border_radius=6,
            visible=False,
            gapless_playback=True,
        )
        self.source_placeholder = ft.Container(
            content=ft.Column(
                [
                    ft.Icon(ft.Icons.IMAGE_OUTLINED, color=TEXT_MUTED, size=32),
                    ft.Text(
                        "Upload or Import from Resolve",
                        color=TEXT_MUTED,
                        size=FONT_SM,
                        text_align=ft.TextAlign.CENTER,
                    ),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=4,
            ),
            alignment=ft.Alignment.CENTER,
            height=120,
            bgcolor=PANEL_ELEVATED,
            border_radius=6,
            border=ft.Border.all(1, BORDER),
        )

        self.prev_row = ft.Row(spacing=6, scroll=ft.ScrollMode.AUTO, height=56)
        self.resolve_strip = ResolveSourcesStrip(
            page,
            on_load=self._on_resolve_still,
            media_kind="image",
        )

        # Optional multi-reference stills (primary is source_path; extras when model allows)
        self._extra_ref_paths: list[str] = []
        self.refs_hint = ft.Text(
            "",
            size=FONT_SM,
            color=TEXT_MUTED,
            max_lines=2,
        )
        self.refs_chips = ft.Column(spacing=4, tight=True)
        self.btn_add_ref = ft.OutlinedButton(
            content="Add reference",
            icon=ft.Icons.ADD_PHOTO_ALTERNATE_OUTLINED,
            on_click=self._on_pick_extra_ref,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
            tooltip="Add another reference still (style / product / look). Model max applies.",
        )
        self.refs_panel = ft.Column(
            [
                ft.Row(
                    [
                        section_title("Reference stills"),
                        ft.Container(expand=True),
                        self.btn_add_ref,
                    ],
                    spacing=6,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                self.refs_hint,
                self.refs_chips,
            ],
            spacing=4,
            tight=True,
            visible=False,
        )

        # Scenario is app-level (top bar). Image reacts via apply_app_scenario.
        sc0 = get_scenario(self.state.scenario_key) or default_scenario()
        self._workspace_id = sc0.key
        self._last_scenario_default_prompt: str = ""
        self._workspace_desc = ft.Text(
            sc0.description,
            size=FONT_SM,
            color=TEXT_MUTED,
            max_lines=4,
        )
        self.btn_reset_scenario = ft.TextButton(
            content="Reset to scenario default",
            icon=ft.Icons.RESTART_ALT,
            on_click=self._on_reset_scenario_prompt,
            style=ft.ButtonStyle(color=ACCENT_BRIGHT),
            tooltip="Reload the default prompt/builder values for the active scenario",
        )
        self._scenario_badge = ft.Container(
            content=ft.Text(
                f"Scenario · {sc0.label}",
                size=11,
                color=TEXT,
                weight=ft.FontWeight.W_700,
            ),
            bgcolor=ACCENT,
            border_radius=4,
            padding=ft.Padding.symmetric(horizontal=8, vertical=3),
        )
        self.state.on_scenario_changed(self.apply_app_scenario)

        # Precision mode: Standard (full-frame) | Region (annotation boxes)
        self._edit_mode = "standard"  # standard | region
        self._pre_region_model: str | None = None
        self._mode_nav = PillNav(
            [("standard", "Standard"), ("region", "Region")],
            selected="standard",
            on_change=self._on_edit_mode,
        )
        from media_studio.flet_region import RegionBoxOverlay, RegionEditorPanel

        self.region_panel = RegionEditorPanel(
            page,
            on_change=self._on_region_boxes_changed,
            on_geometry=self._on_region_geometry,
        )
        # Lightweight boxes on the large Comparison stage (no PIL on slider ticks)
        self.region_stage_overlay = RegionBoxOverlay(
            on_select=self._on_region_stage_select,
            on_geometry=self._on_region_geometry,
            interactive=True,
        )
        # Small source still overlay (left rail)
        self.region_source_overlay = RegionBoxOverlay(
            on_select=self._on_region_stage_select,
            on_geometry=self._on_region_geometry,
            interactive=False,
        )
        # Panel size for letterbox math; host lays out to content_rect only
        self.region_source_overlay.set_stack_size(RAIL_WIDTH - 40, 120)
        self.region_stage_overlay.set_stack_size(800, 500)

        # Scene builder (furniture)
        self.room_dd = styled_dropdown(
            label_text="Room",
            options=ROOM_TYPES,
            value=SCENE_DEFAULTS["room_type"],
            on_select=self._on_scene_changed,
            expand=True,
        )
        self.style_dd = styled_dropdown(
            label_text="Style",
            options=styles_for_room(SCENE_DEFAULTS["room_type"]),
            value=SCENE_DEFAULTS["style"],
            on_select=self._on_scene_changed,
            expand=True,
        )
        self.density_dd = styled_dropdown(
            label_text="Density",
            options=FURNITURE_DENSITY,
            value=SCENE_DEFAULTS["furniture_density"],
            on_select=self._on_scene_changed,
            expand=True,
        )
        self.decor_dd = styled_dropdown(
            label_text="Decor",
            options=DECOR_AMOUNT,
            value=SCENE_DEFAULTS["decor_amount"],
            on_select=self._on_scene_changed,
            expand=True,
        )
        self.plants_dd = styled_dropdown(
            label_text="Plants",
            options=PLANTS,
            value=SCENE_DEFAULTS["plants"],
            on_select=self._on_scene_changed,
            expand=True,
        )
        self.camera_dd = styled_dropdown(
            label_text="Camera",
            options=CAMERA_FEEL,
            value=SCENE_DEFAULTS["camera_feel"],
            on_select=self._on_scene_changed,
            expand=True,
        )

        self.furniture_builder = ft.Column(
            [
                section_title("Scene Builder"),
                ft.Row([self.room_dd, self.style_dd], spacing=8),
                ft.Row([self.density_dd, self.decor_dd], spacing=8),
                ft.Row([self.plants_dd, self.camera_dd], spacing=8),
                ft.Row(
                    [
                        ft.TextButton("Reset builder", on_click=self._on_scene_clear),
                    ]
                ),
            ],
            spacing=6,
            visible=True,
        )

        # Simple builder (day/night, landscaper, etc.)
        schema0 = simple_control_schema(default_scenario().key)
        self.opt_a_dd = styled_dropdown(
            label_text=schema0["opt_a_label"],
            options=schema0["opt_a_choices"],
            value=schema0["opt_a_value"],
            on_select=self._on_simple_changed,
            expand=True,
        )
        self.opt_b_dd = styled_dropdown(
            label_text=schema0["opt_b_label"],
            options=schema0["opt_b_choices"],
            value=schema0["opt_b_value"],
            on_select=self._on_simple_changed,
            expand=True,
        )
        self.opt_c_dd = styled_dropdown(
            label_text=schema0.get("opt_c_label") or "Option C",
            options=schema0.get("opt_c_choices") or ["—"],
            value=schema0.get("opt_c_value") or "—",
            on_select=self._on_simple_changed,
            expand=True,
        )
        self.opt_d_dd = styled_dropdown(
            label_text=schema0.get("opt_d_label") or "Option D",
            options=schema0.get("opt_d_choices") or ["—"],
            value=schema0.get("opt_d_value") or "—",
            on_select=self._on_simple_changed,
            expand=True,
        )
        self.opt_c_dd.visible = bool(schema0.get("show_opt_c"))
        self.opt_d_dd.visible = bool(schema0.get("show_opt_d"))
        self.simple_note = ft.TextField(
            label=schema0["note_label"],
            value="",
            multiline=False,
            dense=True,
            filled=True,
            fill_color=PANEL_ELEVATED,
            border_color=BORDER,
            color=TEXT,
            text_size=FONT_SM,
            on_change=self._on_simple_changed,
            visible=schema0["show_note"],
        )
        self.simple_row_cd = ft.Row(
            [self.opt_c_dd, self.opt_d_dd],
            spacing=8,
            visible=bool(schema0.get("show_opt_c") or schema0.get("show_opt_d")),
        )
        self.simple_builder = ft.Column(
            [
                section_title("Scenario options"),
                ft.Row([self.opt_a_dd, self.opt_b_dd], spacing=8),
                self.simple_row_cd,
                self.simple_note,
            ],
            spacing=6,
            visible=False,
        )

        # sc0 comes from app-level prefs (state.scenario_key) — never use bare `saved`
        _init_prompt = (
            ""
            if is_blank_canvas(sc0.key)
            else build_scenario_prompt(
                sc0.key if sc0.key != BLANK_CANVAS_KEY else "furniture_popin",
                **SCENE_DEFAULTS,
            )
        )
        from media_studio.flet_prompt_favorites import make_prompt_favorites_bar

        self.prompt_field = ft.TextField(
            label="Image prompt",
            value=_init_prompt,
            multiline=True,
            min_lines=4,
            max_lines=6,
            filled=True,
            fill_color=PANEL_ELEVATED,
            border_color=BORDER,
            focused_border_color=ACCENT,
            color=TEXT,
            text_size=FONT_SM,
            hint_text="Describe the edit you want…",
        )
        self.prompt_favs = make_prompt_favorites_bar(
            page,
            get_text=lambda: self.prompt_field.value,
            set_text=lambda t: setattr(self.prompt_field, "value", t),
            surface="studio_image",
            get_meta=lambda: {
                "scenario": getattr(self.state, "scenario_key", "") or "",
                "model": _dd_value(self.model_dd) if hasattr(self, "model_dd") else "",
                "source": "user",
            },
            on_status=lambda m: self._set_status(m) if hasattr(self, "status_text") else None,
            show_pack_buttons=True,
        )

        image_models = [m for m in MODEL_LABELS if m.startswith("Image ·") or m.startswith("Auto")]
        if DEFAULT_IMAGE_MODEL not in image_models:
            image_models = [DEFAULT_IMAGE_MODEL] + image_models
        self._all_image_models: list[str] = list(image_models or MODEL_LABELS)
        if DEFAULT_IMAGE_MODEL not in self._all_image_models:
            self._all_image_models = [DEFAULT_IMAGE_MODEL] + self._all_image_models
        self.model_dd = styled_dropdown(
            label_text="Model",
            options=self._all_image_models,
            value=DEFAULT_IMAGE_MODEL,
            on_select=self._on_model_or_params,
            expand=True,
        )
        self.model_best_for = make_best_for_line()
        update_best_for_line(
            self.model_best_for, DEFAULT_IMAGE_MODEL, dropdown=self.model_dd
        )

        opts = control_options(DEFAULT_IMAGE_MODEL)
        self.res_dd = styled_dropdown(
            label_text="Resolution",
            options=opts["resolution_choices"],
            value=opts["resolution_value"],
            on_select=self._on_model_or_params,
            expand=True,
        )
        self.num_dd = styled_dropdown(
            label_text="# Images",
            options=opts["num_images_choices"],
            value=opts["num_images_value"],
            on_select=self._on_model_or_params,
            expand=True,
        )
        self.strength = ft.Slider(
            min=0.0,
            max=1.0,
            divisions=20,
            value=float(opts.get("strength_value") or 0.6),
            label="{value}",
            on_change=self._on_model_or_params,
            active_color=ACCENT,
        )
        self.job_text = ft.Text(
            describe_job_kind(DEFAULT_IMAGE_MODEL, None, None),
            size=FONT_SM,
            color=TEXT_MUTED,
        )
        self.cost_text = ft.Text(
            self._estimate(),
            size=FONT_LG,
            color=TEXT,
            weight=ft.FontWeight.W_700,
            text_align=ft.TextAlign.CENTER,
        )
        self.cost_box = ft.Container(
            content=ft.Column(
                [label("Estimated cost"), self.cost_text],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=2,
            ),
            bgcolor=PANEL_ELEVATED,
            border=ft.Border.all(1, ACCENT),
            border_radius=6,
            padding=ft.Padding.symmetric(horizontal=10, vertical=8),
        )

        self.status_text = ft.Text(
            "Upload or Import from Resolve, then Generate.",
            size=FONT_SM,
            color=TEXT_MUTED,
        )
        self.job_progress = JobProgress()
        self.job_log = CollapsibleJobLog()
        self.job_log.bind_page(page)
        # Back-compat alias used by a few helpers
        self.progress_text = self.job_log.detail

        self.btn_generate = ft.FilledButton(
            content="Generate Image",
            icon=ft.Icons.AUTO_AWESOME,
            on_click=self._on_generate,
            style=ft.ButtonStyle(
                bgcolor=ACCENT_BRIGHT,
                color=TEXT,
                padding=14,
            ),
            height=44,
            expand=True,
        )
        self.btn_enhance = ft.OutlinedButton(
            content="Enhance",
            on_click=self._on_enhance,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
            tooltip="Vision-aware rewrite for the selected model (Grok)",
        )
        # Natural-language local edit → grounded full prompt
        self.local_edit_field = ft.TextField(
            label="Quick local edit",
            hint_text='e.g. "add 3 stools at the island"',
            dense=True,
            filled=True,
            fill_color=PANEL_ELEVATED,
            border_color=BORDER,
            color=TEXT,
            text_size=FONT_SM,
        )
        self.btn_local_edit = ft.OutlinedButton(
            content="Write prompt",
            icon=ft.Icons.EDIT_NOTE,
            on_click=self._on_local_edit,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
            tooltip="Grok turns a short request into a full grounded edit prompt",
        )
        # Scenario suggest banner (on import)
        self._suggest_key: str | None = None
        self._suggest_tool_id: str | None = None
        self.suggest_text = ft.Text("", size=FONT_SM, color=TEXT, expand=True, max_lines=2)
        self.btn_suggest_apply = ft.TextButton(
            content="Switch",
            on_click=self._on_apply_suggest,
            style=ft.ButtonStyle(color=ACCENT_BRIGHT),
        )
        self.btn_suggest_dismiss = ft.TextButton(
            content="Dismiss",
            on_click=self._on_dismiss_suggest,
            style=ft.ButtonStyle(color=TEXT_MUTED),
        )
        self.suggest_banner = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.LIGHTBULB_OUTLINE, color="#ffb74d", size=18),
                    self.suggest_text,
                    self.btn_suggest_apply,
                    self.btn_suggest_dismiss,
                ],
                spacing=6,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor="#2a2418",
            border=ft.Border.all(1, "#5c4a1f"),
            border_radius=6,
            padding=ft.Padding.symmetric(horizontal=8, vertical=6),
            visible=False,
        )
        self.advisor_text = ft.Text("", size=FONT_SM, color=TEXT_MUTED, max_lines=2)
        # Post-gen QC
        self.qc_text = ft.Text("", size=FONT_SM, color=TEXT_MUTED, max_lines=4, selectable=True)
        self.btn_qc = ft.OutlinedButton(
            content="Run QC",
            icon=ft.Icons.FACT_CHECK,
            on_click=self._on_run_qc,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
            visible=False,
        )
        self.btn_qc_fix = ft.FilledButton(
            content="Suggest fix prompt",
            on_click=self._on_suggest_fix,
            style=ft.ButtonStyle(bgcolor=ACCENT, color=TEXT),
            visible=False,
        )
        self.btn_match_look = ft.OutlinedButton(
            content="Match source look",
            icon=ft.Icons.COMPARE,
            on_click=self._on_match_source_look,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
            visible=False,
            tooltip=(
                "Optional: open Tools → Match Look with this AI result + source still "
                "to pull grade/WB/contrast toward the original."
            ),
        )
        self._qc_fix_prompt: str = ""
        self.qc_row = ft.Column(
            [
                ft.Row(
                    [self.btn_qc, self.btn_qc_fix, self.btn_match_look],
                    spacing=8,
                    wrap=True,
                ),
                self.qc_text,
            ],
            spacing=4,
            visible=False,
        )
        self.state.on_keys_changed(self.apply_key_gates)
        self.apply_key_gates()
        self.btn_send_video = ft.FilledButton(
            content="Send to Video →",
            icon=ft.Icons.MOVIE,
            on_click=self._on_send_to_video,
            style=ft.ButtonStyle(bgcolor=SUCCESS, color=TEXT, padding=12),
            height=40,
            visible=False,
        )
        self.btn_send_aleph = ft.OutlinedButton(
            content="Send to Frame Editor as keyframe",
            icon=ft.Icons.MOVIE_FILTER,
            on_click=self._on_send_to_aleph,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
            height=40,
            visible=False,
            tooltip=(
                "Return this still to Frame Editor as a keyframe. "
                "If you sent a frame from Frame Editor, it re-pins the same slot/time."
            ),
        )
        from media_studio.flet_result_actions import (
            make_before_after_button,
            make_result_action_row,
            show_result_actions,
        )

        def _image_result_path() -> str | None:
            gen = self._selected_gen()
            if gen:
                return gen
            if self.state.comparison:
                return self.state.comparison[-1]
            return None

        self.btn_before_after = make_before_after_button(
            page,
            get_before=lambda: self.state.source_path,
            get_after=_image_result_path,
            get_output_dir=lambda: self.state.output_dir,
            get_job_name=lambda: getattr(self.state, "job_name", None),
            on_status=lambda msg, err: self._set_status(msg),
        )
        (
            self.result_actions_row,
            self.btn_show_folder,
            self.btn_send_resolve,
        ) = make_result_action_row(
            page,
            get_path=_image_result_path,
            on_status=lambda msg, err: self._set_status(msg),
            before_after_btn=self.btn_before_after,
        )
        self.btn_pick = ft.OutlinedButton(
            content="Upload source",
            icon=ft.Icons.UPLOAD_FILE,
            on_click=self._on_pick_source,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
        )

        # --- comparison workspace (inline: left rail + large smooth overlay) ---
        self.compare_label = ft.Text("Generate to compare versions", size=FONT_SM, color=TEXT_MUTED)
        self.live_metrics = ft.Text("", size=FONT_SM, color=TEXT_MUTED)

        # Left rail: source pin + vertical generation list
        self._compare_src_thumb = ft.Image(
            src="",
            fit=ft.BoxFit.CONTAIN,  # preserve aspect; no stretch
            width=168,
            height=100,
            visible=False,
            border_radius=6,
            gapless_playback=True,
        )
        self._compare_src_card = ft.Container(
            content=ft.Column(
                [
                    ft.Text("SOURCE", size=11, color=TEXT_MUTED, weight=ft.FontWeight.W_700),
                    self._compare_src_thumb,
                    ft.Text(
                        "Click to open large",
                        size=10,
                        color=TEXT_MUTED,
                    ),
                ],
                spacing=4,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                tight=True,
            ),
            bgcolor=PANEL_ELEVATED,
            border=ft.Border.all(1, BORDER),
            border_radius=8,
            padding=8,
            on_click=self._open_source_lightbox,
            ink=True,
            tooltip="View source full size",
        )
        self._versions_col = ft.Column(
            spacing=8,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )
        self._versions_rail_label = ft.Text(
            "Versions",
            size=FONT_SM,
            color=TEXT,
            weight=ft.FontWeight.W_700,
        )

        # Instant overlay: Stack source under generation + Container.opacity
        # (no PIL re-blend on slider — stays smooth).
        # CONTAIN + expand (not edge-pinned) so wide windows letterbox, never crop.
        self._overlay_opacity = 0.5
        self._ab_gen: bool | None = None  # None = slider; True/False = force gen/source
        # Pin images to full stage so CONTAIN letterboxes inside the same
        # bounds as region boxes (not a non-positioned expand child).
        self.overlay_base = ft.Image(
            src="",
            fit=ft.BoxFit.CONTAIN,
            left=0,
            top=0,
            right=0,
            bottom=0,
            visible=False,
            gapless_playback=True,
            opacity=1.0,
        )
        self.overlay_gen_img = ft.Image(
            src="",
            fit=ft.BoxFit.CONTAIN,
            left=0,
            top=0,
            right=0,
            bottom=0,
            gapless_playback=True,
            opacity=1.0,
        )
        self.overlay_gen_layer = ft.Container(
            content=self.overlay_gen_img,
            opacity=0.0,
            left=0,
            top=0,
            right=0,
            bottom=0,
            visible=False,
            alignment=ft.Alignment.CENTER,
            clip_behavior=ft.ClipBehavior.NONE,
            bgcolor=ft.Colors.TRANSPARENT,
        )
        # Stack rebuilt by _rebuild_overlay_stack — region placement omits gen.
        self.overlay_stack = ft.Stack(
            [
                self.overlay_base,
                self.region_stage_overlay.root,
            ],
            expand=True,
            fit=ft.StackFit.EXPAND,
            alignment=ft.Alignment.CENTER,
        )
        # Compact empty state — not a giant grey expand void
        self.overlay_placeholder = ft.Container(
            content=ft.Text(
                "Generate to compare",
                size=FONT_MD,
                color=TEXT_MUTED,
                text_align=ft.TextAlign.CENTER,
            ),
            height=96,
            alignment=ft.Alignment.CENTER,
            bgcolor=PANEL_ELEVATED,
            border_radius=8,
            border=ft.Border.all(1, BORDER),
            visible=True,
        )
        # Fills remaining right-pane height only when a comparison exists
        # (expand=False while empty — avoids a full-window grey void)
        self._stage_layout_w: float = 0.0
        self._stage_layout_h: float = 0.0
        self.overlay_stage = ft.Container(
            content=self.overlay_stack,
            expand=False,
            bgcolor="#111318",
            border_radius=8,
            border=ft.Border.all(1, BORDER),
            alignment=ft.Alignment.CENTER,
            clip_behavior=ft.ClipBehavior.NONE,
            visible=False,
            # Real panel size → region box letterbox math (not window guess)
            on_size_change=self._on_overlay_stage_size,
        )

        self.overlay_slider = ft.Slider(
            min=0.0,
            max=1.0,
            divisions=100,
            value=0.5,
            label="Gen {value}",
            on_change=self._on_overlay_slider,
            active_color=ACCENT,
            expand=True,
        )
        self.ab_switch = ft.Switch(
            label="A/B · Generation 100%",
            value=False,
            active_color=ACCENT,
            on_change=self._on_ab_toggle,
        )
        self.overlay_mode_label = ft.Text(
            "Blend · 50% generation",
            size=FONT_SM,
            color=TEXT_MUTED,
        )

        # Single-still lightbox (no overlay / A/B — inspect one photo large)
        self._lightbox_dialog: ft.AlertDialog | None = None
        self._lightbox_img: ft.Image | None = None
        self._lightbox_title: ft.Text | None = None
        self._lightbox_zoom_label: ft.Text | None = None
        self._lightbox_zoom: float = 1.0
        self._lightbox_path: str = ""

        self._refresh_previous()
        self._apply_scenario_ui(self._workspace_id)
        self._sync_refs_panel()

    # ----- public root control -----

    def build(self) -> ft.Control:
        """FixedRail + CapRightEmpty (LAYOUT_AUDIT_2026-08-01)."""
        from media_studio.flet_layout import make_split_workspace

        left_controls: list[ft.Control] = [
            section_title("Image workspace"),
            ft.Row(
                [self._scenario_badge, ft.Container(expand=True)],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            self._workspace_desc,
            ft.Row(
                [label("Edit mode", muted=True), self._mode_nav.control],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            ft.Divider(height=1, color=BORDER),
            ft.Row(
                [section_title("Source still"), self.btn_pick],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            ft.Stack(
                [
                    self.source_placeholder,
                    self.source_preview,
                    self.region_source_overlay.root,
                ],
                height=120,
                width=RAIL_WIDTH - 40,
            ),
            self.refs_panel,
            label("Previously used", muted=True),
            self.prev_row,
            self.resolve_strip.root,
            self.suggest_banner,
            self.furniture_builder,
            self.simple_builder,
            self.region_panel.root,
            ft.Row([self.btn_reset_scenario], spacing=4),
            self.prompt_field,
            self.prompt_favs.root,
            ft.Row(
                [self.local_edit_field, self.btn_local_edit],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.END,
            ),
            ft.Row([self.model_dd], spacing=0),
            self.model_best_for,
            self.advisor_text,
            ft.Row([self.res_dd, self.num_dd], spacing=8),
            label("Strength (edit / denoise)", muted=True),
            self.strength,
            self.job_text,
            ft.Row([self.btn_enhance, self.btn_generate], spacing=8),
            self.job_progress.control,
            self.cost_box,
            self.btn_send_video,
            self.btn_send_aleph,
            self.result_actions_row,
            self.qc_row,
            self.status_text,
            self.job_log.control,
        ]

        # Compare rail — fixed width; only shown when there is media
        self._compare_rail = ft.Container(
            width=196,
            content=ft.Column(
                [
                    self._compare_src_card,
                    ft.Divider(height=1, color=BORDER),
                    self._versions_rail_label,
                    self._versions_col,
                ],
                spacing=8,
                tight=True,
                expand=False,
            ),
            padding=ft.Padding.only(right=4),
            visible=False,
        )
        self._versions_col.expand = False

        workspace_header = ft.Column(
            [
                ft.Row(
                    [
                        label("Overlay / A/B", muted=True),
                        self.overlay_mode_label,
                        self.ab_switch,
                        ft.Container(expand=True),
                        ft.IconButton(
                            icon=ft.Icons.OPEN_IN_FULL,
                            icon_color=TEXT,
                            tooltip="Open selected still full size",
                            on_click=self._open_selected_lightbox,
                        ),
                    ],
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Row(
                    [
                        ft.Text("Source", size=FONT_SM, color=TEXT_MUTED),
                        self.overlay_slider,
                        ft.Text("Gen", size=FONT_SM, color=TEXT_MUTED),
                    ],
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
            ],
            spacing=4,
            tight=True,
        )
        # Tight when empty; stage expand toggled in _apply_overlay_visuals
        self._workspace_col = ft.Column(
            [
                workspace_header,
                self.overlay_placeholder,
                self.overlay_stage,
            ],
            spacing=8,
            tight=True,
            expand=False,
            alignment=ft.MainAxisAlignment.START,
        )
        self._compare_body_row = ft.Row(
            [self._compare_rail, self._workspace_col],
            spacing=12,
            expand=False,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )
        # When media is present, STRETCH so stage height grows with window (CONTAIN letterbox)
        self._right_col = ft.Column(
            [
                ft.Row(
                    [
                        section_title("Comparison"),
                        self.compare_label,
                        self.live_metrics,
                        ft.IconButton(
                            icon=ft.Icons.CHEVRON_LEFT,
                            icon_color=TEXT,
                            tooltip="Previous version",
                            on_click=lambda e: self._step_compare(-1),
                        ),
                        ft.IconButton(
                            icon=ft.Icons.CHEVRON_RIGHT,
                            icon_color=TEXT,
                            tooltip="Next version",
                            on_click=lambda e: self._step_compare(1),
                        ),
                        ft.TextButton("Clear", on_click=self._clear_compare),
                    ],
                    alignment=ft.MainAxisAlignment.START,
                    spacing=4,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                self._compare_body_row,
            ],
            spacing=6,
            tight=True,
            expand=False,
            alignment=ft.MainAxisAlignment.START,
        )
        return make_split_workspace(
            left_controls,
            self._right_col,
            left_width=RAIL_WIDTH,
        )

    # ----- estimates / params -----

    def _params_json(self) -> str:
        return parameters_to_json(
            build_parameters_dict(
                resolution=_dd_value(self.res_dd),
                num_images=_dd_value(self.num_dd),
                strength=_safe_float(self.strength.value, 0.6),
            )
        )

    def _estimate(self) -> str:
        return live_estimate_cost(
            model_choice=_dd_value(self.model_dd) or DEFAULT_IMAGE_MODEL,
            image_file=self.state.source_path,
            parameters_json=self._params_json(),
        )

    def _refresh_cost_job(self) -> None:
        model = _dd_value(self.model_dd) or DEFAULT_IMAGE_MODEL
        self.cost_text.value = self._estimate()
        self.job_text.value = describe_job_kind(model, self.state.source_path, None)
        try:
            from media_studio.grok_layer import advise_model

            tip = advise_model(
                task="image edit",
                has_image=bool(self.state.source_path),
                scenario_label=self.state.scenario_label,
            )
            if tip.ok and tip.model_label and tip.model_label != model:
                self.advisor_text.value = (
                    f"Tip: {tip.model_label} · {tip.cost_hint} — {tip.reason}"
                )
            else:
                self.advisor_text.value = tip.cost_hint if tip.ok else ""
        except Exception:
            self.advisor_text.value = ""

    def _set_status(self, msg: str) -> None:
        self.status_text.value = msg
        self.page.update()

    def _set_progress(self, msg: str) -> None:
        """Append raw fal line to collapsible log (not shown unless expanded/error)."""
        if msg:
            self.job_log.append(msg, self.page)
        elif not msg:
            self.job_log.clear(self.page)
        try:
            self.page.update()
        except Exception:
            pass

    def apply_key_gates(self) -> None:
        """Disable Generate / Grok actions when keys are missing."""
        from media_studio.secrets_store import has_fal_key, has_xai_key

        ready = has_fal_key()
        xai = has_xai_key()
        xai_tip = "Add xAI key in Settings for Grok features"
        if not self.state.is_busy("image"):
            self.btn_generate.disabled = not ready
            self.btn_generate.tooltip = (
                None if ready else "Add your FAL API key in Settings to generate"
            )
            # Grok-only: Enhance, Local Edit, QC (match Video gating)
            self.btn_enhance.disabled = not xai
            self.btn_enhance.tooltip = (
                "Rewrite prompt for the selected model (Grok)"
                if xai
                else xai_tip
            )
            try:
                self.btn_local_edit.disabled = not xai
                self.btn_local_edit.tooltip = (
                    "Grounded local edit (Grok)" if xai else xai_tip
                )
            except Exception:
                pass
            try:
                self.btn_qc.disabled = not xai
                self.btn_qc.tooltip = "Run QC (Grok)" if xai else xai_tip
            except Exception:
                pass
            try:
                self.btn_qc_fix.disabled = not xai
                self.btn_qc_fix.tooltip = (
                    "Suggest fix prompt (Grok)" if xai else xai_tip
                )
            except Exception:
                pass

    # ----- previous sources -----

    def _refresh_previous(self) -> None:
        paths = gallery_value(self.state.output_dir)
        thumbs: list[ft.Control] = []
        for p in paths:
            path = p

            def make_handler(pp: str) -> Callable:
                async def _click(e: ft.ControlEvent) -> None:
                    await self._load_source(pp)

                return _click

            thumbs.append(
                ft.Container(
                    content=ft.Image(src=path, fit=ft.BoxFit.COVER, width=52, height=52),
                    width=52,
                    height=52,
                    border_radius=4,
                    border=ft.Border.all(1, BORDER),
                    on_click=make_handler(path),
                    tooltip=Path(path).name,
                    ink=True,
                )
            )
        self.prev_row.controls = thumbs or [
            ft.Text("No previous sources yet", size=FONT_SM, color=TEXT_MUTED)
        ]
        try:
            self.resolve_strip.refresh()
        except Exception:
            pass

    def _on_resolve_still(self, path: str) -> None:
        """From Resolve still → Image source (same path as previous/upload)."""
        self.load_source_path(path, status=f"From Resolve: {Path(path).name}")
        try:
            asyncio.get_event_loop().create_task(self._maybe_suggest_scenario(path))
        except Exception:
            pass
        try:
            self.page.update()
        except Exception:
            pass

    async def _load_source(self, path: str) -> None:
        self.load_source_path(path)
        await self._maybe_suggest_scenario(path)

    async def _maybe_suggest_scenario(self, path: str) -> None:
        """Optional Grok scenario suggestion when a new still is loaded."""
        from media_studio.secrets_store import has_xai_key

        if not has_xai_key():
            return
        try:
            from media_studio.grok_layer import suggest_scenario_for_still

            sug = await asyncio.to_thread(suggest_scenario_for_still, path)
            if not sug.ok:
                return
            # Don't nag if already on that scenario (and no special tool)
            if (
                sug.scenario_key == getattr(self, "_workspace_id", None)
                and not getattr(sug, "tool_id", None)
            ):
                return
            self._suggest_key = sug.scenario_key or "blank_canvas"
            self._suggest_tool_id = getattr(sug, "tool_id", None) or None
            conf = f" ({sug.confidence})" if sug.confidence else ""
            self.suggest_text.value = (
                f"Suggested: {sug.scenario_label}{conf}"
                + (f" — {sug.reason}" if sug.reason else "")
            )
            self.suggest_banner.visible = True
            self.page.update()
        except Exception:
            pass

    async def _on_apply_suggest(self, e: ft.ControlEvent) -> None:
        key = self._suggest_key
        tool_id = self._suggest_tool_id
        self.suggest_banner.visible = False
        if tool_id and self.state.source_path:
            # Tool-only handoff (e.g. Blown Out)
            switch = getattr(self.state, "switch_to_tools", None)
            tv = getattr(self.state, "tools_view", None)
            if tv is not None and hasattr(tv, "receive_media"):
                try:
                    tv.receive_media(tool_id, self.state.source_path, as_video=False)
                except Exception:
                    pass
            if switch:
                switch(tool_id)
            self._set_status(f"Suggested tool → {tool_id}. Loaded source still.")
        elif key:
            self.state.set_scenario(key, notify=True, persist=True)
            self._apply_scenario_ui(key, force_prompt=True)
            self._set_status(f"Switched to suggested scenario: {self.state.scenario_label}")
        self._suggest_key = None
        self._suggest_tool_id = None
        try:
            self.page.update()
        except Exception:
            pass

    async def _on_dismiss_suggest(self, e: ft.ControlEvent) -> None:
        self.suggest_banner.visible = False
        self._suggest_key = None
        self._suggest_tool_id = None
        try:
            self.page.update()
        except Exception:
            pass

    # ----- Standard | Region precision mode -----

    def _on_edit_mode(self, mode_id: str) -> None:
        self.set_edit_mode(mode_id)

    def set_edit_mode(self, mode_id: str, *, force_seedream: bool = True) -> None:
        """Switch Standard (full-frame) vs Region (annotation boxes)."""
        mode = (mode_id or "standard").strip().lower()
        if mode not in ("standard", "region"):
            mode = "standard"
        prev = self._edit_mode
        self._edit_mode = mode
        try:
            self._mode_nav.set_selected(mode, notify=False)
        except Exception:
            pass

        is_region = mode == "region"
        self.region_panel.set_visible(is_region)
        # Hide scenario builders in region mode (region uses its own prompts)
        if is_region:
            # Default to Source 100% — never open Region on a 50% blend veil
            self._ab_gen = False
            self._overlay_opacity = 0.0
            self.furniture_builder.visible = False
            self.simple_builder.visible = False
            if prev != "region":
                self._pre_region_model = _dd_value(self.model_dd)
            self._apply_region_model_filter(force_seedream=force_seedream)
            self.region_panel.set_source(
                self.state.source_path, output_dir=self.state.output_dir
            )
            self.region_panel.ensure_one_box()  # places a visible default box
            self.prompt_field.label = "Region prompt (color-keyed — editable)"
            self.prompt_field.hint_text = (
                "Compiled from boxes, or write freely. Enhance uses vision + box texts."
            )
            # Sync compiled prompt if empty
            if not (self.prompt_field.value or "").strip():
                compiled = self.region_panel.compiled_prompt()
                if compiled:
                    self.prompt_field.value = compiled
            self._refresh_region_overlays()
            self._set_status(
                "Region mode — Seedream / annotation-model only. "
                "Source shown clear for box placement; L/T/W/H for precision. "
                "Generate composites boxes onto the still (fails hard if composite fails)."
            )
            self._sync_refs_panel()
        else:
            # Restore full model list + previous selection
            self._restore_standard_models()
            sc = get_scenario(self._workspace_id) or default_scenario()
            blank = is_blank_canvas(sc.key)
            self.furniture_builder.visible = bool(sc.show_furniture_builder) and not blank
            self.simple_builder.visible = bool(sc.show_simple_builder) and not blank
            self._sync_refs_panel()
            self.prompt_field.label = (
                "Image prompt (freeform)" if blank else "Image prompt"
            )
            self._set_status("Standard mode — full-frame prompt edit.")
            # Clear annotated preview on left rail / stage base
            self._refresh_region_overlays()
            self._update_compare_pane()
        self._refresh_cost_job()
        try:
            self.page.update()
        except Exception:
            pass

    def _apply_region_model_filter(self, *, force_seedream: bool = True) -> None:
        """Region mode: only annotation-box models (Seedream 5 Pro)."""
        from media_studio.flet_theme import dropdown_options
        from media_studio.region_edit import REGION_DEFAULT_MODEL, REGION_MODEL_LABELS

        labels = [m for m in REGION_MODEL_LABELS if m]
        if not labels:
            labels = [REGION_DEFAULT_MODEL]
        # Prefer labels that exist in the full catalog; always include Seedream
        full = set(self._all_image_models)
        filtered = [m for m in labels if m in full] or list(labels)
        if REGION_DEFAULT_MODEL not in filtered:
            filtered = [REGION_DEFAULT_MODEL] + filtered
        self.model_dd.options = dropdown_options(filtered)
        if force_seedream or _dd_value(self.model_dd) not in filtered:
            self.model_dd.value = filtered[0]
        try:
            self._on_model_or_params_sync()
        except Exception:
            pass

    def _restore_standard_models(self) -> None:
        """Leave Region mode: full image model list again."""
        from media_studio.flet_theme import dropdown_options

        self.model_dd.options = dropdown_options(self._all_image_models)
        prev = self._pre_region_model
        if prev and prev in self._all_image_models:
            self.model_dd.value = prev
        elif _dd_value(self.model_dd) not in self._all_image_models:
            self.model_dd.value = DEFAULT_IMAGE_MODEL
        self._pre_region_model = None
        try:
            self._on_model_or_params_sync()
        except Exception:
            pass

    def enter_region_mode(self, path: str | None = None) -> bool:
        """Library / Send to Region edit — load still and open Region mode."""
        if path:
            ok = self.load_source_path(path, status=f"Region edit ← {Path(path).name}")
            if not ok:
                return False
        self.set_edit_mode("region", force_seedream=True)
        return True

    def _on_region_boxes_changed(self) -> None:
        """Structure change (add/remove/select/prompt) — sync overlays + prompt."""
        compiled = self.region_panel.compiled_prompt()
        cur = (self.prompt_field.value or "").strip()
        if not cur or cur.startswith("In the ") or "box only:" in cur.lower():
            if compiled:
                self.prompt_field.value = compiled
        self._refresh_region_overlays(full_rebuild=True)
        self._refresh_cost_job()

    def _on_region_geometry(self) -> None:
        """Slider/drag geometry — instant overlay update only (no PIL, no list rebuild)."""
        if self._edit_mode != "region":
            return
        try:
            # Keep stage size current before reflow
            self._apply_region_viewport_sizes()
            self.region_panel.sync_main_overlay(
                self.region_stage_overlay, full_rebuild=False
            )
            self.region_panel.sync_main_overlay(
                self.region_source_overlay, full_rebuild=False
            )
            self.region_panel._sync_overlays(full_rebuild=False)
            # Keep precision sliders in sync when dragging on the large image
            self.region_panel._sync_sliders()
        except Exception:
            pass
        try:
            self.page.update()
        except Exception:
            pass

    def _on_region_stage_select(self, index: int) -> None:
        try:
            self.region_panel._select_index(index)
        except Exception:
            pass

    def _on_overlay_stage_size(self, e: Any) -> None:
        """Comparison stage layout size — source of truth for large box letterbox."""
        from media_studio.flet_region import size_from_layout_event

        try:
            w, h = size_from_layout_event(e)
            if w > 1 and h > 1:
                self._stage_layout_w = w
                self._stage_layout_h = h
                if getattr(self, "_edit_mode", "standard") == "region":
                    self.region_stage_overlay.set_stack_size(w, h, reflow=True)
                    try:
                        self.page.update()
                    except Exception:
                        pass
        except Exception:
            pass

    def _estimate_stage_size(self) -> tuple[float, float]:
        """
        Fallback when layout size is not yet known.

        Must subtract left rail + versions rail so letterbox matches CONTAIN.
        """
        try:
            pw = float(getattr(self.page, "width", None) or 1200)
            ph = float(getattr(self.page, "height", None) or 800)
        except Exception:
            pw, ph = 1200.0, 800.0
        # Fixed left rail + split spacing/padding
        left_take = float(RAIL_WIDTH) + 40.0
        # Versions rail is ~196 wide when visible
        compare_take = 0.0
        try:
            if getattr(self._compare_rail, "visible", False):
                compare_take = 196.0 + 12.0
        except Exception:
            pass
        # Header / chrome above the stage
        chrome_h = 220.0
        sw = max(200.0, pw - left_take - compare_take - 24.0)
        sh = max(200.0, ph - chrome_h)
        return sw, sh

    def _apply_region_viewport_sizes(self) -> None:
        """
        Push the same image WxH into both overlays; panel sizes are the real
        host bounds (measured stage, fixed left source stack).
        """
        iw, ih = self.region_panel.image_size()
        self.region_stage_overlay.set_image_size(iw, ih)
        self.region_source_overlay.set_image_size(iw, ih)
        # Small left source stack is fixed (matches Stack width/height)
        src_w = float(RAIL_WIDTH - 40)
        src_h = 120.0
        self.region_source_overlay.set_stack_size(src_w, src_h)
        # Large stage: prefer measured layout size
        if self._stage_layout_w > 1 and self._stage_layout_h > 1:
            sw, sh = self._stage_layout_w, self._stage_layout_h
        else:
            sw, sh = self._estimate_stage_size()
        self.region_stage_overlay.set_stack_size(sw, sh)

    def _region_source_only(self) -> bool:
        """
        True when Region placement should force Source 100% / Gen hidden.

        Blend is allowed only when the user explicitly toggles A/B to Generation
        *and* a real generation path exists.
        """
        if getattr(self, "_edit_mode", "standard") != "region":
            return False
        # Explicit A/B → gen review after generate
        if self._ab_gen is True and self._resolve_local_image(self._selected_gen()):
            return False
        return True

    def _rebuild_overlay_stack(self, *, include_gen: bool, include_boxes: bool) -> bool:
        """
        Rebuild Comparison Stack children.

        Region source-only omits gen so a blend layer cannot grey-wash the photo.
        Returns True on success. Does not swallow errors (caller may status-report).
        """
        layers: list[ft.Control] = [self.overlay_base]
        if include_gen:
            layers.append(self.overlay_gen_layer)
        if include_boxes:
            layers.append(self.region_stage_overlay.root)
        self.overlay_stack.controls = layers
        # Assert: source-only never leaves gen in the tree
        if not include_gen:
            for c in self.overlay_stack.controls:
                if c is self.overlay_gen_layer:
                    raise RuntimeError(
                        "Region source-only: gen layer still in overlay_stack"
                    )
        return True

    def _log_region_stage_layers(self, *, where: str = "") -> None:
        """Debug which layers are live (status line when REGION_STAGE_DEBUG=1)."""
        import os

        if os.environ.get("REGION_STAGE_DEBUG", "").strip() not in ("1", "true", "yes"):
            return
        try:
            gen_vis = bool(getattr(self.overlay_gen_layer, "visible", False))
            gen_op = float(getattr(self.overlay_gen_layer, "opacity", 0) or 0)
            base_vis = bool(getattr(self.overlay_base, "visible", False))
            base_op = float(getattr(self.overlay_base, "opacity", 1) or 1)
            box_vis = bool(getattr(self.region_stage_overlay.root, "visible", False))
            ctrls = list(getattr(self.overlay_stack, "controls", []) or [])
            n_stack = len(ctrls)
            gen_in = any(c is self.overlay_gen_layer for c in ctrls)
            ox = oy = dw = dh = 0.0
            try:
                ox, oy, dw, dh = self.region_stage_overlay.content_rect()
            except Exception:
                pass
            msg = (
                f"[region-stage {where}] base vis={base_vis} op={base_op:.2f} · "
                f"gen vis={gen_vis} op={gen_op:.2f} in_stack={gen_in} · "
                f"boxes={box_vis} host=({ox:.0f},{oy:.0f} {dw:.0f}x{dh:.0f}) · "
                f"stack_n={n_stack} · ab={self._ab_gen} blend={self._overlay_opacity:.2f}"
            )
            print(msg, flush=True)
            try:
                self._set_status(msg)
            except Exception:
                pass
        except Exception:
            pass

    def _set_region_stage_layers(self, *, src_visible: bool = True) -> None:
        """
        Region placement: source at full brightness; gen out of the stack.

        Box host is content_rect-sized only (not full-stage) — see RegionBoxOverlay.
        """
        src_s = self._resolve_local_image(self.state.source_path) or ""
        show_src = bool(src_visible) and bool(src_s)
        try:
            if show_src:
                self.overlay_base.src = src_s
                self.overlay_base.visible = True
                self.overlay_base.opacity = 1.0
                self.overlay_base.fit = ft.BoxFit.CONTAIN
            else:
                self.overlay_base.visible = False

            if self._region_source_only():
                self._ab_gen = False
                self._overlay_opacity = 0.0
                try:
                    self.overlay_slider.value = 0.0
                    self.ab_switch.value = False
                    self.ab_switch.label = "A/B · Source 100%"
                    self.overlay_mode_label.value = "Region · Source only (place boxes)"
                except Exception:
                    pass
                try:
                    self.overlay_gen_img.src = ""
                except Exception:
                    pass
                self.overlay_gen_layer.visible = False
                self.overlay_gen_layer.opacity = 0.0
                try:
                    self._rebuild_overlay_stack(include_gen=False, include_boxes=True)
                except Exception as exc:
                    # Never leave a Standard (base+gen) stack under Region
                    try:
                        self.overlay_stack.controls = [
                            self.overlay_base,
                            self.region_stage_overlay.root,
                        ]
                    except Exception:
                        pass
                    try:
                        self._set_status(
                            f"Region stage rebuild failed (source-only forced): {exc}"
                        )
                    except Exception:
                        pass
            else:
                # Explicit gen review in Region (A/B Generation on)
                gen_s = self._resolve_local_image(self._selected_gen()) or ""
                if gen_s:
                    self.overlay_gen_img.src = gen_s
                    self.overlay_gen_layer.visible = True
                    self.overlay_gen_layer.opacity = 1.0
                    try:
                        self._rebuild_overlay_stack(
                            include_gen=True, include_boxes=True
                        )
                    except Exception as exc:
                        try:
                            self._set_status(f"Region gen stack rebuild failed: {exc}")
                        except Exception:
                            pass
                else:
                    self.overlay_gen_layer.visible = False
                    self.overlay_gen_layer.opacity = 0.0
                    try:
                        self._rebuild_overlay_stack(
                            include_gen=False, include_boxes=True
                        )
                    except Exception as exc:
                        try:
                            self.overlay_stack.controls = [
                                self.overlay_base,
                                self.region_stage_overlay.root,
                            ]
                        except Exception:
                            pass
                        try:
                            self._set_status(
                                f"Region stage rebuild failed (source-only): {exc}"
                            )
                        except Exception:
                            pass

            try:
                self.region_stage_overlay.root.bgcolor = None
                self.region_stage_overlay.root.opacity = 1.0
            except Exception:
                pass
            self._log_region_stage_layers(where="set_region_layers")
        except Exception as exc:
            try:
                self._set_status(f"Region stage layer error: {exc}")
            except Exception:
                pass

    def _refresh_region_overlays(self, *, full_rebuild: bool = False) -> None:
        """
        Lightweight overlays on static source image — no PIL re-encode.

        Region placement: full-brightness source only + colored boxes (no blend).
        Images always use CONTAIN; boxes map to the letterboxed content rect.
        """
        # Always preserve aspect on previews
        try:
            self.overlay_base.fit = ft.BoxFit.CONTAIN
            self.source_preview.fit = ft.BoxFit.CONTAIN
            self.overlay_gen_img.fit = ft.BoxFit.CONTAIN
            self._compare_src_thumb.fit = ft.BoxFit.CONTAIN
        except Exception:
            pass

        if self._edit_mode != "region":
            self.region_stage_overlay.set_visible(False)
            self.region_source_overlay.set_visible(False)
            src = self.state.source_path
            if src and Path(src).is_file():
                self.source_preview.src = src
                self.source_preview.visible = True
                self.source_placeholder.visible = False
            # Restore standard stack (base + gen + no boxes)
            try:
                self._rebuild_overlay_stack(include_gen=True, include_boxes=False)
            except Exception as exc:
                try:
                    self._set_status(f"Compare stack rebuild failed: {exc}")
                except Exception:
                    pass
            return

        src = self.state.source_path
        if not src or not Path(src).is_file():
            self.region_stage_overlay.set_visible(False)
            self.region_source_overlay.set_visible(False)
            return

        # Left rail: full-brightness source + boxes
        self.source_preview.src = src
        self.source_preview.visible = True
        self.source_preview.opacity = 1.0
        self.source_placeholder.visible = False

        # Large stage: expand, source-only path
        self.overlay_placeholder.visible = False
        self.overlay_stage.visible = True
        try:
            self.overlay_stage.expand = True
            self._workspace_col.expand = True
            self._workspace_col.tight = False
            self._compare_body_row.expand = True
            self._compare_body_row.vertical_alignment = ft.CrossAxisAlignment.STRETCH
            self._right_col.expand = True
            self._right_col.tight = False
            self._compare_rail.visible = True
        except Exception:
            pass

        # Force Source 100% / Gen out of tree (unless user A/B'd to a real gen)
        self._set_region_stage_layers(src_visible=True)

        self.region_stage_overlay.set_visible(True)
        self.region_source_overlay.set_visible(True)

        self._apply_region_viewport_sizes()

        self.region_panel.set_output_dir(self.state.output_dir)
        self.region_panel.sync_main_overlay(
            self.region_stage_overlay, full_rebuild=full_rebuild
        )
        self.region_panel.sync_main_overlay(
            self.region_source_overlay, full_rebuild=full_rebuild
        )
        self.region_panel.refresh_live_preview()

        try:
            self._compare_src_thumb.src = src
            self._compare_src_thumb.visible = True
            self._compare_src_card.visible = True
        except Exception:
            pass
        self._sync_overlay_labels()
        self._log_region_stage_layers(where="refresh_region")

    def _on_model_or_params_sync(self) -> None:
        """Synchronous model options refresh (region mode Seedream switch)."""
        model = _dd_value(self.model_dd) or DEFAULT_IMAGE_MODEL
        opts = control_options(model)
        self.res_dd.options = [
            ft.DropdownOption(key=x, text=x) for x in opts["resolution_choices"]
        ]
        self.res_dd.value = opts["resolution_value"]
        self.num_dd.options = [
            ft.DropdownOption(key=x, text=x) for x in opts["num_images_choices"]
        ]
        self.num_dd.value = opts["num_images_value"]
        self.strength.value = float(opts.get("strength_value") or 0.6)
        self._refresh_cost_job()

    async def _on_local_edit(self, e: ft.ControlEvent) -> None:
        if self.state.is_busy("image"):
            return
        req = (self.local_edit_field.value or "").strip()
        if not req:
            self._set_status('Type a short edit, e.g. "add 3 stools at the island".')
            return
        from media_studio.secrets_store import has_xai_key

        if not has_xai_key():
            self._set_status("xAI key required for local edit helper — open Settings.")
            return
        if not self.state.try_busy("image"):
            return
        self.btn_local_edit.disabled = True
        self.job_progress.start("Writing grounded prompt…", self.page)
        try:
            from media_studio.grok_layer import grounded_local_edit

            res = await asyncio.to_thread(
                grounded_local_edit,
                request=req,
                image_path=self.state.source_path,
                scenario_label=self.state.scenario_label,
            )
            if res.ok and res.edit_prompt:
                self.prompt_field.value = res.edit_prompt
                self.job_progress.finish_ok("Prompt ready — review, then Generate.", self.page)
                self._set_status(res.status)
            else:
                self.job_progress.finish_error(res.status or "Local edit failed.", self.page)
                self._set_status(res.status or "Local edit failed.")
        except Exception as exc:
            self.job_progress.finish_error(str(exc), self.page)
            self._set_status(f"Local edit error: {exc}")
        finally:
            self.state.clear_busy("image")
            self.btn_local_edit.disabled = False
            self.apply_key_gates()
            self.page.update()

    async def _on_run_qc(self, e: ft.ControlEvent) -> None:
        gen = self._selected_gen()
        if not gen:
            self._set_status("Generate a result first, then Run QC.")
            return
        await self._run_qc_async(
            result_path=gen,
            source_path=self.state.source_path,
            prompt=(self.prompt_field.value or "").strip(),
        )

    async def _run_qc_async(
        self,
        *,
        result_path: str,
        source_path: str | None,
        prompt: str,
    ) -> None:
        from media_studio.secrets_store import has_xai_key

        if not has_xai_key():
            self.qc_text.value = "QC needs an xAI key in Settings."
            self.qc_row.visible = True
            self.page.update()
            return
        self.qc_row.visible = True
        self.qc_text.value = "Running QC…"
        self.btn_qc_fix.visible = False
        self.page.update()
        try:
            from media_studio.grok_layer import critique_generation

            qc = await asyncio.to_thread(
                critique_generation,
                result_path=result_path,
                source_path=source_path,
                prompt=prompt,
                job_kind="image",
            )
            if qc.ok:
                bits = [f"[{qc.score}] {qc.summary}"] if qc.summary else [f"Score: {qc.score}"]
                if qc.issues:
                    bits.append(" · ".join(qc.issues[:4]))
                self.qc_text.value = " ".join(bits)
                self._qc_fix_prompt = qc.fix_prompt or ""
                self.btn_qc_fix.visible = bool(self._qc_fix_prompt)
            else:
                self.qc_text.value = qc.status or "QC failed."
                self.btn_qc_fix.visible = False
        except Exception as exc:
            self.qc_text.value = f"QC error: {exc}"
            self.btn_qc_fix.visible = False
        try:
            self.page.update()
        except Exception:
            pass

    async def _on_suggest_fix(self, e: ft.ControlEvent) -> None:
        if not self._qc_fix_prompt:
            self._set_status("No fix prompt available — run QC first.")
            return
        self.prompt_field.value = self._qc_fix_prompt
        self._set_status("Fix prompt loaded — review, then Generate.")
        try:
            self.page.update()
        except Exception:
            pass

    async def _on_match_source_look(self, e: ft.ControlEvent) -> None:
        """Optional handoff: AI result → Tools Match Look (+ Studio source as grade ref)."""
        gen = self._selected_gen()
        if not gen or not Path(gen).is_file():
            self._set_status("Generate a result first, then Match source look.")
            return
        from media_studio.tools_registry import MATCH_LOOK_DEFAULT

        # Soft prompt helper also available in-place
        if not (self.prompt_field.value or "").strip():
            self.prompt_field.value = MATCH_LOOK_DEFAULT
        tv = getattr(self.state, "tools_view", None)
        ok = False
        if tv is not None and hasattr(tv, "receive_media"):
            ok = bool(tv.receive_media("match_look", gen, as_video=False))
        switch = getattr(self.state, "switch_to_tools", None)
        if switch:
            switch("match_look")
        self._set_status(
            f"Match Look ← {Path(gen).name}"
            + (" · source still attached as grade ref" if self.state.source_path else "")
            if ok
            else "Opened Match Look — load the AI result if needed."
        )
        try:
            self.page.update()
        except Exception:
            pass

    def load_source_path(self, path: str, *, status: str | None = None) -> bool:
        """Sync load of a still as Image source (upload, previous, Resolve import)."""
        p = Path(path)
        if not p.is_file():
            self._set_status(f"Source missing: {path}")
            return False
        self.state.source_path = str(p.resolve())
        try:
            record_source(self.state.source_path, self.state.output_dir)
        except Exception:
            pass
        # Drop any extra ref that matches the new primary
        self._extra_ref_paths = [
            r
            for r in self._extra_ref_paths
            if Path(r).resolve() != Path(self.state.source_path).resolve()
        ]
        self._refresh_previous()
        self.source_preview.src = self.state.source_path
        self.source_preview.visible = True
        self.source_placeholder.visible = False
        try:
            self.region_panel.set_source(
                self.state.source_path, output_dir=self.state.output_dir
            )
            if self._edit_mode == "region":
                self._refresh_region_overlays()
        except Exception:
            pass
        self._sync_refs_panel()
        self._refresh_cost_job()
        self._update_compare_pane()
        self._set_status(status or f"Source still: {p.name}")
        return True

    def _model_max_refs(self) -> int:
        from media_studio.fal.models import max_ref_images_for_choice

        model = _dd_value(self.model_dd) or DEFAULT_IMAGE_MODEL
        return max_ref_images_for_choice(model)

    def _trim_extra_refs_to_model(self) -> None:
        """Keep extras within model max (primary counts as 1)."""
        max_refs = self._model_max_refs()
        extra_cap = max(0, max_refs - 1)
        if len(self._extra_ref_paths) > extra_cap:
            self._extra_ref_paths = self._extra_ref_paths[:extra_cap]

    def _sync_refs_panel(self) -> None:
        """Show/hide multi-ref UI; rebuild chips. Hidden in Region mode."""
        max_refs = self._model_max_refs()
        is_region = getattr(self, "_edit_mode", "standard") == "region"
        show = (not is_region) and max_refs > 1
        self.refs_panel.visible = show
        if not show:
            return
        self._trim_extra_refs_to_model()
        extra_cap = max(0, max_refs - 1)
        n = len(self._extra_ref_paths)
        self.refs_hint.value = (
            f"Primary source + up to {extra_cap} extra ref"
            f"{'s' if extra_cap != 1 else ''} "
            f"(model max {max_refs}). {n}/{extra_cap} used."
        )
        self.btn_add_ref.disabled = n >= extra_cap
        chips: list[ft.Control] = []
        for i, path in enumerate(list(self._extra_ref_paths)):
            name = Path(path).name
            chips.append(
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Image(
                                src=path if Path(path).is_file() else "",
                                width=40,
                                height=40,
                                fit=ft.BoxFit.COVER,
                                border_radius=4,
                                visible=Path(path).is_file(),
                            ),
                            ft.Text(
                                name,
                                size=FONT_SM,
                                color=TEXT,
                                expand=True,
                                max_lines=1,
                                overflow=ft.TextOverflow.ELLIPSIS,
                            ),
                            ft.IconButton(
                                icon=ft.Icons.CLOSE,
                                icon_size=16,
                                icon_color=TEXT_MUTED,
                                tooltip="Remove reference",
                                on_click=self._make_remove_extra_ref(i),
                            ),
                        ],
                        spacing=6,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    bgcolor=PANEL_ELEVATED,
                    border=ft.Border.all(1, BORDER),
                    border_radius=6,
                    padding=ft.Padding.symmetric(horizontal=6, vertical=4),
                )
            )
        self.refs_chips.controls = chips

    def _make_remove_extra_ref(self, index: int):
        async def _click(_e: ft.ControlEvent) -> None:
            if 0 <= index < len(self._extra_ref_paths):
                removed = self._extra_ref_paths.pop(index)
                self._set_status(f"Removed ref: {Path(removed).name}")
            self._sync_refs_panel()
            try:
                self.page.update()
            except Exception:
                pass

        return _click

    async def _on_pick_extra_ref(self, e: ft.ControlEvent) -> None:
        max_refs = self._model_max_refs()
        extra_cap = max(0, max_refs - 1)
        if len(self._extra_ref_paths) >= extra_cap:
            self._set_status(f"Model allows at most {max_refs} stills (including primary).")
            return
        try:
            files = await pick_image(
                self.page,
                dialog_title="Choose reference still",
                allow_multiple=True,
            )
        except Exception as exc:
            self._set_status(f"File picker error: {exc}")
            return
        if not files:
            return
        primary = None
        if self.state.source_path:
            try:
                primary = Path(self.state.source_path).resolve()
            except OSError:
                primary = None
        added = 0
        for f in files:
            if len(self._extra_ref_paths) >= extra_cap:
                break
            path = f.path
            if not path:
                continue
            p = Path(path)
            if not p.is_file():
                continue
            try:
                resolved = str(p.resolve())
            except OSError:
                resolved = str(p)
            if primary and Path(resolved).resolve() == primary:
                continue
            if resolved in self._extra_ref_paths:
                continue
            self._extra_ref_paths.append(resolved)
            try:
                record_source(resolved, self.state.output_dir)
            except Exception:
                pass
            added += 1
        self._sync_refs_panel()
        if added:
            self._set_status(f"Added {added} reference still(s).")
        else:
            self._set_status("No new reference stills added.")
        try:
            self.page.update()
        except Exception:
            pass

    async def _on_pick_source(self, e: ft.ControlEvent) -> None:
        try:
            files = await pick_image(self.page, dialog_title="Choose source still")
        except Exception as exc:
            self._set_status(f"File picker error: {exc}")
            return
        if not files:
            return
        path = files[0].path
        if path:
            await self._load_source(path)

    # ----- scenario / scene builder -----

    def _scenario_key(self) -> str:
        s = get_scenario(self._workspace_id or self.state.scenario_label)
        return s.key if s else "furniture_popin"

    def _rebuild_prompt_from_builders(self) -> str:
        key = self._scenario_key()
        s = get_scenario(key) or default_scenario()
        if s.key == BLANK_CANVAS_KEY or is_blank_canvas(s.key):
            return (self.prompt_field.value or "").strip()
        if s.show_furniture_builder:
            return build_scenario_prompt(
                key,
                room_type=_dd_value(self.room_dd),
                style=_dd_value(self.style_dd),
                furniture_density=_dd_value(self.density_dd),
                decor_amount=_dd_value(self.decor_dd),
                plants=_dd_value(self.plants_dd),
                camera_feel=_dd_value(self.camera_dd),
            )
        return build_scenario_prompt(
            key,
            opt_a=_dd_value(self.opt_a_dd),
            opt_b=_dd_value(self.opt_b_dd),
            opt_c=_dd_value(self.opt_c_dd),
            opt_d=_dd_value(self.opt_d_dd),
            note=self.simple_note.value or "",
        )

    def apply_app_scenario(self, key: str) -> None:
        """App-level scenario bar changed — reconfigure Image workspace."""
        self._apply_scenario_ui(key, force_prompt=False)
        try:
            self.page.update()
        except Exception:
            pass

    def _apply_scenario_ui(self, label_or_key: str, *, force_prompt: bool = True) -> None:
        """
        Configure Image builders + prompt for a scenario.

        When ``force_prompt`` is False (app scenario switch), keep heavy user
        edits and offer Reset. Initial load / explicit Reset use force_prompt=True.
        """
        s = get_scenario(label_or_key) or default_scenario()
        self._workspace_id = s.key
        # Keep state in sync without re-notifying (avoids loop)
        self.state.scenario_key = s.key
        self.state.scenario_label = s.label
        try:
            self._scenario_badge.content = ft.Text(
                f"Scenario · {s.label}",
                size=11,
                color=TEXT,
                weight=ft.FontWeight.W_700,
            )
        except Exception:
            pass
        self._workspace_desc.value = s.description or ""
        blank = s.key == BLANK_CANVAS_KEY or is_blank_canvas(s.key)
        self.furniture_builder.visible = bool(s.show_furniture_builder) and not blank
        self.simple_builder.visible = bool(s.show_simple_builder) and not blank
        # Reset control visible when a template exists OR user may want blank clear
        try:
            self.btn_reset_scenario.visible = True
            self.btn_reset_scenario.content = (
                "Clear prompt" if blank else "Reset to scenario default"
            )
        except Exception:
            pass

        keep_prompt = False
        if not force_prompt:
            keep_prompt = not prompt_is_scenario_defaultish(
                self.prompt_field.value,
                last_default=self._last_scenario_default_prompt,
                scenario_key=s.key,
            )

        if blank:
            if not keep_prompt:
                self.prompt_field.value = ""
                self._last_scenario_default_prompt = ""
            self.prompt_field.label = "Image prompt (freeform)"
            self.prompt_field.hint_text = "Describe the edit — no scenario template."
            if keep_prompt:
                self._set_status(
                    f"Scenario → {s.label}. Kept your prompt — use Clear prompt to empty it."
                )
            else:
                self._set_status(f"Scenario → {s.label} (freeform).")
            self._refresh_cost_job()
            return

        self.prompt_field.label = "Image prompt"
        self.prompt_field.hint_text = "Describe the edit you want… (editable default)"
        if s.show_simple_builder:
            schema = simple_control_schema(s.key)
            self.opt_a_dd.label = schema["opt_a_label"]
            self.opt_a_dd.options = [ft.DropdownOption(key=x, text=x) for x in schema["opt_a_choices"]]
            self.opt_a_dd.value = schema["opt_a_value"]
            self.opt_b_dd.label = schema["opt_b_label"]
            self.opt_b_dd.options = [ft.DropdownOption(key=x, text=x) for x in schema["opt_b_choices"]]
            self.opt_b_dd.value = schema["opt_b_value"]
            show_c = bool(schema.get("show_opt_c"))
            show_d = bool(schema.get("show_opt_d"))
            self.opt_c_dd.visible = show_c
            self.opt_d_dd.visible = show_d
            self.simple_row_cd.visible = show_c or show_d
            if show_c:
                self.opt_c_dd.label = schema.get("opt_c_label") or "Option C"
                self.opt_c_dd.options = [
                    ft.DropdownOption(key=x, text=x)
                    for x in (schema.get("opt_c_choices") or ["—"])
                ]
                self.opt_c_dd.value = schema.get("opt_c_value")
            if show_d:
                self.opt_d_dd.label = schema.get("opt_d_label") or "Option D"
                self.opt_d_dd.options = [
                    ft.DropdownOption(key=x, text=x)
                    for x in (schema.get("opt_d_choices") or ["—"])
                ]
                self.opt_d_dd.value = schema.get("opt_d_value")
            self.simple_note.label = schema["note_label"]
            self.simple_note.visible = schema["show_note"]
            if not keep_prompt:
                self.simple_note.value = ""

        new_default = self._rebuild_prompt_from_builders()
        if keep_prompt:
            self._set_status(
                f"Scenario → {s.label}. Kept your edited prompt — "
                "use Reset to scenario default to reload the template."
            )
        else:
            self.prompt_field.value = new_default
            self._last_scenario_default_prompt = new_default
            self._set_status(f"Scenario → {s.label}")
        self._refresh_cost_job()

    async def _on_reset_scenario_prompt(self, e: ft.ControlEvent) -> None:
        """Force-reload default prompt (and builder values) for active scenario."""
        self._apply_scenario_ui(self._workspace_id or self.state.scenario_key, force_prompt=True)
        self._set_status(f"Prompt reset to {self.state.scenario_label} default.")
        try:
            self.page.update()
        except Exception:
            pass

    async def _on_scenario(self, e: ft.ControlEvent) -> None:
        # Legacy hook
        self._apply_scenario_ui(self._workspace_id or self.state.scenario_key, force_prompt=False)

    async def _on_scene_changed(self, e: ft.ControlEvent) -> None:
        # Filter styles when room changes
        if e.control is self.room_dd:
            styles = styles_for_room(_dd_value(self.room_dd))
            self.style_dd.options = [ft.DropdownOption(key=x, text=x) for x in styles]
            if _dd_value(self.style_dd) not in styles:
                self.style_dd.value = styles[0] if styles else None
        built = self._rebuild_prompt_from_builders()
        self.prompt_field.value = built
        self._last_scenario_default_prompt = built
        self.page.update()

    async def _on_scene_clear(self, e: ft.ControlEvent) -> None:
        self.room_dd.value = SCENE_DEFAULTS["room_type"]
        styles = styles_for_room(SCENE_DEFAULTS["room_type"])
        self.style_dd.options = [ft.DropdownOption(key=x, text=x) for x in styles]
        self.style_dd.value = SCENE_DEFAULTS["style"]
        self.density_dd.value = SCENE_DEFAULTS["furniture_density"]
        self.decor_dd.value = SCENE_DEFAULTS["decor_amount"]
        self.plants_dd.value = SCENE_DEFAULTS["plants"]
        self.camera_dd.value = SCENE_DEFAULTS["camera_feel"]
        built = self._rebuild_prompt_from_builders()
        self.prompt_field.value = built
        self._last_scenario_default_prompt = built
        self._set_status("Scene Builder reset.")

    async def _on_simple_changed(self, e: ft.ControlEvent) -> None:
        built = self._rebuild_prompt_from_builders()
        self.prompt_field.value = built
        self._last_scenario_default_prompt = built
        self.page.update()

    async def _on_model_or_params(self, e: ft.ControlEvent) -> None:
        model = _dd_value(self.model_dd) or DEFAULT_IMAGE_MODEL
        opts = control_options(model)
        # Refresh resolution / count choices if model changed
        if e.control is self.model_dd:
            self.res_dd.options = [
                ft.DropdownOption(key=x, text=x) for x in opts["resolution_choices"]
            ]
            self.res_dd.value = opts["resolution_value"]
            self.num_dd.options = [
                ft.DropdownOption(key=x, text=x) for x in opts["num_images_choices"]
            ]
            self.num_dd.value = opts["num_images_value"]
            self.strength.value = float(opts.get("strength_value") or 0.6)
            self._trim_extra_refs_to_model()
            self._sync_refs_panel()
            try:
                update_best_for_line(
                    self.model_best_for, model, dropdown=self.model_dd
                )
            except Exception:
                pass
        self._refresh_cost_job()
        self.page.update()

    # ----- compare -----

    def _selected_gen(self) -> str | None:
        if not self.state.comparison:
            return None
        i = max(0, min(self.state.compare_index, len(self.state.comparison) - 1))
        return self.state.comparison[i]

    def _effective_overlay_opacity(self) -> float:
        """A/B forces 0 or 1; otherwise use slider (instant, no re-encode)."""
        # Region placement: never report a mid blend (would re-open gen veil)
        if self._region_source_only():
            return 0.0
        if self._ab_gen is True:
            return 1.0
        if self._ab_gen is False:
            return 0.0
        return max(0.0, min(1.0, _safe_float(self._overlay_opacity, 0.5)))

    def _sync_overlay_labels(self) -> None:
        if self._region_source_only():
            self.overlay_mode_label.value = "Region · Source only (place boxes)"
            self.overlay_slider.value = 0.0
            self.ab_switch.value = False
            self.ab_switch.label = "A/B · Source 100%"
            return
        op = self._effective_overlay_opacity()
        if self._ab_gen is True:
            mode = "A/B · Generation 100%"
            show_gen = True
        elif self._ab_gen is False:
            mode = "A/B · Source 100%"
            show_gen = False
        else:
            mode = f"Blend · {int(round(op * 100))}% generation"
            show_gen = op >= 0.99
        self.overlay_mode_label.value = mode
        self.overlay_slider.value = op
        self.ab_switch.value = show_gen
        self.ab_switch.label = (
            "A/B · Generation 100%" if show_gen else "A/B · Source 100%"
        )

    def _apply_overlay_visuals(self) -> None:
        """
        Instant local compositing: source under, generation opacity on top.
        No PIL / disk write on slider or A/B flip — stays smooth.

        Region placement forces source-only (gen removed from stack). Boxes are
        a separate Stack layer (region_stage_overlay), not baked in.
        """
        src_s = self._resolve_local_image(self.state.source_path) or ""
        gen_s = self._resolve_local_image(self._selected_gen()) or ""
        has_src = bool(src_s)
        has_gen = bool(gen_s)
        op = self._effective_overlay_opacity()
        is_region = getattr(self, "_edit_mode", "standard") == "region"

        if not has_src and not has_gen:
            self.overlay_placeholder.visible = True
            self.overlay_stage.visible = False
            try:
                self.overlay_stage.expand = False
            except Exception:
                pass
            self.overlay_base.visible = False
            self.overlay_gen_layer.visible = False
            try:
                self.region_stage_overlay.set_visible(False)
            except Exception:
                pass
            # CapRightEmpty — no expand chain when empty
            try:
                self._workspace_col.expand = False
                self._workspace_col.tight = True
                self._compare_body_row.expand = False
                self._compare_body_row.vertical_alignment = ft.CrossAxisAlignment.START
                self._right_col.expand = False
                self._right_col.tight = True
                self._compare_rail.visible = False
            except Exception:
                pass
            self._sync_overlay_labels()
            return

        # Real comparison fills the right pane under the compact header
        self.overlay_placeholder.visible = False
        self.overlay_stage.visible = True
        try:
            self.overlay_stage.expand = True
            self._workspace_col.expand = True
            self._workspace_col.tight = False
            self._compare_body_row.expand = True
            self._compare_body_row.vertical_alignment = ft.CrossAxisAlignment.STRETCH
            self._right_col.expand = True
            self._right_col.tight = False
            self._compare_rail.visible = True
            self.overlay_base.fit = ft.BoxFit.CONTAIN
            self.overlay_gen_img.fit = ft.BoxFit.CONTAIN
        except Exception:
            pass

        # Always CONTAIN — never stretch house photos
        try:
            self.overlay_base.fit = ft.BoxFit.CONTAIN
            self.overlay_gen_img.fit = ft.BoxFit.CONTAIN
            self.source_preview.fit = ft.BoxFit.CONTAIN
        except Exception:
            pass

        if is_region and has_src:
            # Source-only placement (or explicit A/B gen) — never 50% blank blend
            self._set_region_stage_layers(src_visible=True)
            try:
                self._apply_region_viewport_sizes()
                self.region_stage_overlay.set_visible(True)
                self.region_source_overlay.set_visible(True)
                self.region_panel.sync_main_overlay(
                    self.region_stage_overlay, full_rebuild=False
                )
                self.region_panel.sync_main_overlay(
                    self.region_source_overlay, full_rebuild=False
                )
            except Exception:
                pass
            self._sync_overlay_labels()
            self._log_region_stage_layers(where="apply_overlay_region")
            return

        # --- Standard compare path ---
        if has_src:
            self.overlay_base.src = src_s
            self.overlay_base.visible = True
            self.overlay_base.opacity = 1.0
        else:
            self.overlay_base.visible = False

        if has_gen:
            self.overlay_gen_img.src = gen_s
            self.overlay_gen_layer.visible = True
            # Gen-only: full opacity so the stage is never empty grey
            self.overlay_gen_layer.opacity = op if has_src else 1.0
            try:
                self._rebuild_overlay_stack(include_gen=True, include_boxes=False)
            except Exception as exc:
                try:
                    self._set_status(f"Compare stack rebuild failed: {exc}")
                except Exception:
                    pass
        else:
            self.overlay_gen_layer.visible = False
            self.overlay_gen_layer.opacity = 0.0
            try:
                self._rebuild_overlay_stack(include_gen=False, include_boxes=False)
            except Exception as exc:
                try:
                    self._set_status(f"Compare stack rebuild failed: {exc}")
                except Exception:
                    pass

        try:
            self.region_stage_overlay.set_visible(False)
        except Exception:
            pass

        self._sync_overlay_labels()

    @staticmethod
    def _resolve_local_image(path: str | None) -> str | None:
        """Return absolute path if file exists and is readable; else None."""
        if not path:
            return None
        try:
            p = Path(path).expanduser().resolve()
            if not p.is_file() or p.stat().st_size <= 0:
                return None
            with p.open("rb") as fh:
                head = fh.read(16)
            if not head:
                return None
            return str(p)
        except OSError:
            return None

    def _update_compare_pane(self) -> None:
        """Refresh left version rail + large overlay for the selected generation."""
        self._apply_overlay_visuals()
        self._refresh_compare_rail()

        n = len(self.state.comparison)
        if n:
            self.compare_label.value = f"Version {self.state.compare_index + 1} / {n}"
        else:
            self.compare_label.value = "Generate to compare versions"
        # Before/after when source + selected result exist
        try:
            has_src = bool(
                self.state.source_path and Path(self.state.source_path).is_file()
            )
            has_gen = bool(self._selected_gen())
            if hasattr(self, "btn_before_after"):
                self.btn_before_after.visible = has_src and has_gen
        except Exception:
            pass

    def _refresh_compare_rail(self) -> None:
        """Rebuild left-rail source pin + version thumbnails."""
        src = self._resolve_local_image(self.state.source_path)
        if src:
            self._compare_src_thumb.src = src
            self._compare_src_thumb.visible = True
            self._compare_src_card.visible = True
        else:
            self._compare_src_thumb.visible = False
            self._compare_src_card.visible = False

        n = len(self.state.comparison)
        self._versions_rail_label.value = f"Versions ({n})" if n else "Versions (none yet)"

        thumbs: list[ft.Control] = []
        for i, p in enumerate(self.state.comparison):
            selected = i == self.state.compare_index
            idx = i
            path = p

            def make_select(ii: int):
                def _click(_e: ft.ControlEvent) -> None:
                    self.state.compare_index = ii
                    self._update_compare_pane()
                    self.page.update()

                return _click

            def make_lightbox(pp: str):
                async def _click(_e: ft.ControlEvent) -> None:
                    await self._open_lightbox(pp)

                return _click

            border_c = ACCENT if selected else BORDER
            border_w = 3 if selected else 1
            thumbs.append(
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Image(
                                src=path,
                                fit=ft.BoxFit.COVER,
                                width=168,
                                height=96,
                                border_radius=4,
                            ),
                            ft.Row(
                                [
                                    ft.Text(
                                        f"v{i + 1}" + (" · selected" if selected else ""),
                                        size=11,
                                        color=TEXT if selected else TEXT_MUTED,
                                        weight=ft.FontWeight.W_700 if selected else ft.FontWeight.W_400,
                                        expand=True,
                                    ),
                                    ft.IconButton(
                                        icon=ft.Icons.OPEN_IN_FULL,
                                        icon_size=16,
                                        icon_color=TEXT_MUTED,
                                        tooltip="View full size",
                                        on_click=make_lightbox(path),
                                        style=ft.ButtonStyle(padding=2),
                                    ),
                                ],
                                spacing=0,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                        ],
                        spacing=4,
                        tight=True,
                    ),
                    width=180,
                    padding=6,
                    bgcolor=PANEL_ELEVATED if selected else BG,
                    border=ft.Border.all(border_w, border_c),
                    border_radius=8,
                    on_click=make_select(idx),
                    ink=True,
                    tooltip=Path(path).name,
                )
            )

        if not thumbs:
            thumbs = [
                ft.Text(
                    "Generate to fill versions",
                    size=FONT_SM,
                    color=TEXT_MUTED,
                )
            ]
        self._versions_col.controls = thumbs

    def _step_compare(self, delta: int) -> None:
        if not self.state.comparison:
            return
        self.state.compare_index = (self.state.compare_index + delta) % len(self.state.comparison)
        self._update_compare_pane()
        self.page.update()

    async def _clear_compare(self, e: ft.ControlEvent) -> None:
        self.state.comparison = []
        self.state.compare_index = 0
        self.live_metrics.value = ""
        self._ab_gen = None
        self._overlay_opacity = 0.5
        self._update_compare_pane()
        self.page.update()

    async def _on_overlay_slider(self, e: ft.ControlEvent) -> None:
        """Slider drag: only change layer opacity (no re-render / disk I/O)."""
        # Region placement ignores blend — keep source-only
        if self._region_source_only() or (
            getattr(self, "_edit_mode", "standard") == "region"
            and self._ab_gen is not True
        ):
            self._ab_gen = False
            self._overlay_opacity = 0.0
            try:
                self.overlay_slider.value = 0.0
            except Exception:
                pass
            self._apply_overlay_visuals()
            self.page.update()
            return
        self._ab_gen = None
        val = _safe_float(
            e.control.value if e and e.control is not None else self.overlay_slider.value,
            0.5,
        )
        self._overlay_opacity = val
        self._apply_overlay_visuals()
        self.page.update()

    async def _on_ab_toggle(self, e: ft.ControlEvent) -> None:
        """Instant A/B: ON = gen 100%, OFF = source 100%."""
        show_gen = bool(e.control.value) if e and e.control is not None else False
        self._ab_gen = show_gen
        self._overlay_opacity = 1.0 if show_gen else 0.0
        # Region + Source: force clear photo; Region + Gen only if a result exists
        if getattr(self, "_edit_mode", "standard") == "region" and not show_gen:
            self._ab_gen = False
            self._overlay_opacity = 0.0
        self._apply_overlay_visuals()
        self.page.update()

    # ----- single-still lightbox (inspect only; no overlay) -----

    def _close_lightbox(self, _e: Any = None) -> None:
        close_dialog(self.page, self._lightbox_dialog)

    def _set_lightbox_zoom(self, zoom: float) -> None:
        self._lightbox_zoom = max(0.5, min(6.0, float(zoom)))
        if self._lightbox_img is not None:
            self._lightbox_img.scale = ft.Scale(self._lightbox_zoom)
        if self._lightbox_zoom_label is not None:
            self._lightbox_zoom_label.value = f"{int(round(self._lightbox_zoom * 100))}%"
        try:
            if self._lightbox_img is not None and getattr(self._lightbox_img, "page", None):
                self._lightbox_img.update()
            if self._lightbox_zoom_label is not None and getattr(
                self._lightbox_zoom_label, "page", None
            ):
                self._lightbox_zoom_label.update()
        except Exception:
            pass

    def _lightbox_zoom_by(self, delta: float) -> None:
        self._set_lightbox_zoom(self._lightbox_zoom + delta)

    def _on_lightbox_scroll(self, e: ft.ScrollEvent) -> None:
        """Mouse wheel over image: zoom in/out."""
        dy = 0.0
        try:
            delta = getattr(e, "scroll_delta", None)
            if delta is not None:
                dy = float(getattr(delta, "y", 0) or 0)
        except (TypeError, ValueError):
            dy = 0.0
        if dy == 0:
            return
        # Wheel up (negative dy on many platforms) → zoom in
        step = 0.12 if dy < 0 else -0.12
        self._lightbox_zoom_by(step)

    def _ensure_lightbox(self) -> ft.AlertDialog:
        """Simple full-preview dialog for one still (no A/B / slider)."""
        if self._lightbox_dialog is not None:
            return self._lightbox_dialog

        win_w = float(getattr(self.page.window, "width", None) or 1600)
        win_h = float(getattr(self.page.window, "height", None) or 960)
        body_w = int(min(max(win_w - 48, 800), win_w * 0.96))
        body_h = int(min(max(win_h - 48, 500), win_h * 0.92))

        self._lightbox_title = ft.Text(
            "Still preview",
            size=FONT_MD,
            color=TEXT,
            weight=ft.FontWeight.W_700,
            expand=True,
            max_lines=1,
            overflow=ft.TextOverflow.ELLIPSIS,
        )
        self._lightbox_zoom_label = ft.Text("100%", size=FONT_SM, color=TEXT_MUTED, width=48)
        self._lightbox_img = ft.Image(
            src="",
            fit=ft.BoxFit.CONTAIN,
            expand=True,
            gapless_playback=True,
            scale=ft.Scale(1.0),
        )

        async def _close(_e: ft.ControlEvent) -> None:
            self._close_lightbox()

        stage = ft.Container(
            content=ft.GestureDetector(
                content=self._lightbox_img,
                on_scroll=self._on_lightbox_scroll,
                expand=True,
            ),
            expand=True,
            bgcolor="#0a0c10",
            border_radius=8,
            border=ft.Border.all(1, BORDER),
            alignment=ft.Alignment.CENTER,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
        )

        body = ft.Container(
            width=body_w,
            height=body_h,
            content=ft.Column(
                [
                    ft.Row(
                        [
                            self._lightbox_title,
                            ft.IconButton(
                                icon=ft.Icons.ZOOM_OUT,
                                icon_color=TEXT,
                                tooltip="Zoom out",
                                on_click=lambda _e: self._lightbox_zoom_by(-0.25),
                            ),
                            self._lightbox_zoom_label,
                            ft.IconButton(
                                icon=ft.Icons.ZOOM_IN,
                                icon_color=TEXT,
                                tooltip="Zoom in",
                                on_click=lambda _e: self._lightbox_zoom_by(0.25),
                            ),
                            ft.IconButton(
                                icon=ft.Icons.FIT_SCREEN,
                                icon_color=TEXT,
                                tooltip="Reset zoom",
                                on_click=lambda _e: self._set_lightbox_zoom(1.0),
                            ),
                            ft.FilledButton(
                                content="Close",
                                on_click=_close,
                                style=ft.ButtonStyle(bgcolor=PANEL_ELEVATED, color=TEXT),
                            ),
                        ],
                        spacing=4,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    stage,
                    ft.Text(
                        "Scroll wheel or +/− to zoom · Close when done",
                        size=FONT_SM,
                        color=TEXT_MUTED,
                    ),
                ],
                expand=True,
                spacing=8,
            ),
        )

        self._lightbox_dialog = ft.AlertDialog(
            modal=True,
            bgcolor=PANEL,
            title=None,
            content=body,
            actions=[],
            inset_padding=8,
            content_padding=12,
            on_dismiss=lambda _e: None,
        )
        return self._lightbox_dialog

    async def _open_lightbox(self, path: str | None) -> None:
        """Open a single still full size (no overlay)."""
        resolved = self._resolve_local_image(path)
        if not resolved:
            self._set_status("No still to preview.")
            return
        dialog = self._ensure_lightbox()
        self._lightbox_path = resolved
        self._lightbox_zoom = 1.0
        if self._lightbox_img is not None:
            self._lightbox_img.src = resolved
            self._lightbox_img.scale = ft.Scale(1.0)
        if self._lightbox_title is not None:
            self._lightbox_title.value = Path(resolved).name
        if self._lightbox_zoom_label is not None:
            self._lightbox_zoom_label.value = "100%"
        if getattr(dialog, "open", False):
            self.page.update()
            return
        show_dialog(self.page, dialog)
        self.page.update()

    async def _open_selected_lightbox(self, _e: ft.ControlEvent = None) -> None:
        await self._open_lightbox(self._selected_gen())

    async def _open_source_lightbox(self, _e: ft.ControlEvent = None) -> None:
        await self._open_lightbox(self.state.source_path)

    # ----- generate / enhance -----

    async def _on_enhance(self, e: ft.ControlEvent) -> None:
        if self.state.is_busy("image"):
            return
        prompt = (self.prompt_field.value or "").strip()
        extra = None
        if self._edit_mode == "region":
            extra = self.region_panel.enhance_extra_context()
            if not prompt and not self.region_panel.has_boxes_with_prompts():
                self._set_status("Add region box prompts (or a main prompt) to enhance.")
                return
        elif not prompt:
            self._set_status("Enter a prompt to enhance.")
            return
        if not self.state.try_busy("image"):
            return
        self.btn_enhance.disabled = True
        self.btn_generate.disabled = True
        self.job_progress.start("Enhancing prompt…", self.page)
        extra_refs = (
            []
            if self._edit_mode == "region"
            else list(getattr(self, "_extra_ref_paths", None) or [])
        )
        self._set_status(
            "Enhancing with Grok · vision"
            + (" · region" if self._edit_mode == "region" else "")
            + (f" · {len(extra_refs)} ref(s)" if extra_refs else "")
            + "…"
        )
        model = _dd_value(self.model_dd) or DEFAULT_IMAGE_MODEL
        try:
            result = await asyncio.to_thread(
                enhance_prompt,
                prompt=prompt or "",
                model_choice=model,
                image_file=self.state.source_path,
                video_file=None,
                parameters=json.loads(self._params_json()),
                output_dir=self.state.output_dir,
                scenario=self.state.scenario_key or self.state.scenario_label,
                extra_context=extra,
                extra_image_files=extra_refs or None,
            )
            if result.ok and result.optimized_prompt:
                self.prompt_field.value = result.optimized_prompt
                self.job_progress.finish_ok("Enhanced — review, then Generate.", self.page)
                self._set_status(result.status or "Enhanced. Review the prompt, then Generate.")
            else:
                from media_studio.errors import friendly_error

                err = friendly_error(result.status or "Enhance failed.", context="Enhance")
                self.job_progress.finish_error(err, self.page)
                self._set_status(err)
        except Exception as exc:
            from media_studio.errors import friendly_error

            err = friendly_error(exc, context="Enhance")
            self.job_progress.finish_error(err, self.page)
            self._set_status(err)
        finally:
            self.state.clear_busy("image")
            self.btn_enhance.disabled = False
            self.apply_key_gates()
            self.page.update()

    async def _on_generate(self, e: ft.ControlEvent) -> None:
        if self.state.is_busy("image"):
            return
        from media_studio.secrets_store import has_fal_key

        if not has_fal_key():
            self._set_status("FAL API key required — open Settings (gear icon) to add your key.")
            return
        if not self.state.source_path or not Path(self.state.source_path).is_file():
            self._set_status("Upload or Import from Resolve first.")
            return

        # Region mode: composite boxes → annotated still + color-keyed prompt
        image_path_for_job = self.state.source_path
        prompt = (self.prompt_field.value or "").strip()
        if self._edit_mode == "region":
            if not self.region_panel.has_boxes_with_prompts() and not prompt:
                self._set_status("Region mode: add at least one box prompt.")
                return
            if not prompt:
                prompt = self.region_panel.compiled_prompt()
            if not prompt:
                self._set_status("Region mode: compiled prompt is empty.")
                return
            try:
                from media_studio.config import ensure_output_dir
                from media_studio.naming import timestamp_now

                out_dir = ensure_output_dir(Path(self.state.output_dir)) / "_region"
                out_dir.mkdir(parents=True, exist_ok=True)
                dest = out_dir / f"annotated_{timestamp_now()}.png"
                # Expensive PIL composite only at Generate time (not on sliders)
                annotated = self.region_panel.export_annotated_path(dest)
                if not annotated or not Path(annotated).is_file():
                    self._set_status(
                        "Region composite failed — cannot send a raw still with "
                        "color-box prompts. Check the source image and try again, "
                        "or switch to Standard mode."
                    )
                    return
                # Hard-fail if we would upload the unannotated source with box prompts
                try:
                    same = Path(annotated).resolve() == Path(self.state.source_path).resolve()
                except OSError:
                    same = annotated == self.state.source_path
                if same and self.region_panel.boxes:
                    self._set_status(
                        "Region composite did not produce an annotated still. "
                        "Generate aborted (raw still would ignore box marks)."
                    )
                    return
                image_path_for_job = str(annotated)
            except Exception as exc:
                from media_studio.errors import friendly_error

                self._set_status(friendly_error(exc, context="Region composite"))
                return
        elif not prompt:
            self._set_status("Enter an image prompt.")
            return

        if not self.state.try_busy("image"):
            return
        self.btn_generate.disabled = True
        self.btn_enhance.disabled = True
        self.job_progress.start("Uploading…", self.page)
        self._set_status("Starting…")
        self.job_log.clear(self.page)
        if self._edit_mode == "region" and image_path_for_job != self.state.source_path:
            self.job_log.append(
                f"Region composite → {Path(image_path_for_job).name}", self.page
            )
        self.live_metrics.value = ""
        self.page.update()

        model = _dd_value(self.model_dd) or DEFAULT_IMAGE_MODEL
        if self._edit_mode == "region":
            from media_studio.region_edit import REGION_DEFAULT_MODEL

            # Prefer Seedream if still on a generic default
            from media_studio.scenarios import is_following_scenario_defaults

            if is_following_scenario_defaults(model) or "Flux 2 Pro" in (model or ""):
                model = REGION_DEFAULT_MODEL
        params_json = self._params_json()
        # Region is still-only precision mode; keep active scenario for naming context
        scenario_key = self._scenario_key()

        def on_progress(msg: str) -> None:
            self.job_log.append(msg, self.page)
            self.job_progress.set_message(classify_progress(msg), self.page)

        # Multi-ref only in Standard mode; Region ships the annotated primary alone
        extra_refs = (
            []
            if self._edit_mode == "region"
            else list(getattr(self, "_extra_ref_paths", None) or [])
        )

        try:
            from media_studio.job_context import to_thread_with_job

            result = await to_thread_with_job(
                self.state,
                generate,
                prompt=prompt,
                model_choice=model,
                image_file=image_path_for_job,
                video_file=None,
                output_dir=self.state.output_dir,
                parameters_json=params_json,
                on_progress=on_progress,
                scenario=scenario_key,
                extra_image_files=extra_refs or None,
            )
            if result.ok and result.image_paths:
                for p in result.image_paths:
                    if p not in self.state.comparison:
                        self.state.comparison.append(p)
                self.state.compare_index = len(self.state.comparison) - 1
                self.live_metrics.value = result.metrics_line or result.cost_estimate or "Done"
                self.cost_text.value = result.cost_estimate or self._estimate()
                self._update_compare_pane()
                self.btn_send_video.visible = True
                self.btn_send_aleph.visible = True
                self.btn_show_folder.visible = True
                self.btn_send_resolve.visible = True
                try:
                    has_src = bool(
                        self.state.source_path and Path(self.state.source_path).is_file()
                    )
                    self.btn_before_after.visible = has_src
                except Exception:
                    pass
                done = (
                    f"OK · {len(result.image_paths)} image(s) · "
                    f"{result.metrics_line or result.cost_estimate or 'done'}"
                )
                self.job_progress.finish_ok(done, self.page)
                self.job_log.finish_ok(self.page)
                self._set_status(done)
                self.qc_row.visible = True
                self.btn_qc.visible = True
                self.btn_qc_fix.visible = False
                self.btn_match_look.visible = True
                self.qc_text.value = (
                    "Optional: Run QC, Suggest fix, or Match source look (grade toward original)."
                )
                # Non-blocking auto-QC when xAI key is present
                try:
                    from media_studio.secrets_store import has_xai_key

                    if has_xai_key():
                        await self._run_qc_async(
                            result_path=result.image_paths[-1],
                            source_path=self.state.source_path,
                            prompt=prompt,
                        )
                except Exception:
                    pass
            else:
                from media_studio.errors import friendly_error

                err = friendly_error(result.status or "Generate failed.", context="Generate")
                self.job_progress.finish_error(err, self.page)
                self.job_log.finish_error(err, self.page)
                # Keep technical text secondary in the collapsible log
                if result.status and result.status != err:
                    self.job_log.append(f"Details: {result.status}", self.page)
                self._set_status(err)
        except Exception as exc:
            err = f"Generate error: {exc}"
            self.job_progress.finish_error(err, self.page)
            self.job_log.finish_error(err, self.page)
            self._set_status(err)
            traceback.print_exc()
        finally:
            self.state.clear_busy("image")
            self.btn_enhance.disabled = False
            self.apply_key_gates()
            self._refresh_cost_job()
            self.page.update()

    async def _on_send_to_video(self, e: ft.ControlEvent) -> None:
        """Hand latest still (or source) to Video → Received workspace."""
        ref = self._selected_gen() or self.state.source_path
        if not ref or not Path(ref).is_file():
            self._set_status("No still to send — generate or upload a source first.")
            return
        self.state.video_ref_path = str(Path(ref).resolve())
        sc = get_scenario(self._workspace_id or self.state.scenario_label)
        self.state.scenario_label = sc.label if sc else self.state.scenario_label
        vv = getattr(self.state, "video_view", None)
        if vv is not None:
            if hasattr(vv, "open_received"):
                vv.open_received(
                    ref_path=self.state.video_ref_path,
                    scenario_label=self.state.scenario_label,
                )
            else:
                vv.receive_from_image(
                    ref_path=self.state.video_ref_path,
                    scenario_label=self.state.scenario_label,
                )
        if self.state.switch_to_video:
            self.state.switch_to_video()
        self._set_status(
            f"Sent to Video → Received: {Path(ref).name}. "
            "Add a source clip if needed, then Generate."
        )

    async def _on_send_to_aleph(self, e: ft.ControlEvent) -> None:
        """
        Pin the selected still as a Frame Editor keyframe.

        Round-trip: if the still originated from Frame Editor (Send frame to
        Studio), replace that same slot / timestamp. Source video stays put.
        """
        still = self._selected_gen() or self.state.source_path
        if not still or not Path(still).is_file():
            self._set_status("No still to send — generate or upload first.")
            return
        resolved = str(Path(still).resolve())
        ctx = getattr(self.state, "frame_editor_return", None)
        switch = getattr(self.state, "switch_to_frame_editor", None)
        if switch:
            switch(keyframe_path=resolved)
        else:
            fe = getattr(self.state, "frame_editor_view", None)
            if fe is not None:
                if hasattr(fe, "receive_keyframe"):
                    fe.receive_keyframe(resolved)
                elif hasattr(fe, "add_keyframe"):
                    fe.add_keyframe(resolved, pin="first")
        if isinstance(ctx, dict) and ctx:
            pin = ctx.get("pin", "first")
            ts = ctx.get("timestamp_s")
            idx = ctx.get("slot_index")
            slot_note = (
                f"slot #{int(idx) + 1}" if isinstance(idx, int) else "same slot"
            )
            time_note = f" · t={float(ts):.2f}s" if pin == "timestamp" and ts is not None else ""
            self._set_status(
                f"Sent to Frame Editor as keyframe ({slot_note} · pin={pin}{time_note}): "
                f"{Path(still).name}."
            )
        else:
            self._set_status(
                f"Sent to Frame Editor as keyframe: {Path(still).name}. "
                "Pin first / last / time if needed, then Generate."
            )


# ---------------------------------------------------------------------------
# Scaffold tabs
# ---------------------------------------------------------------------------


def _placeholder_tab(title: str, body: str) -> ft.Control:
    return panel(
        ft.Column(
            [
                section_title(title),
                ft.Text(body, color=TEXT_MUTED, size=FONT_MD),
                ft.Text(
                    "Studio → Image is fully wired. This section lands next.",
                    color=TEXT_MUTED,
                    size=FONT_SM,
                ),
            ],
            spacing=10,
        ),
        expand=True,
        padding=20,
    )


def build_tabs(
    items: list[tuple[str, Any, ft.Control]],
    *,
    selected_index: int = 0,
) -> ft.Tabs:
    """
    Flet 0.86+ Tabs API: Tab has no ``content`` kwarg.

    Structure::

        Tabs(length=N, content=Column([TabBar(tabs=[Tab...]), TabBarView(controls=[...])]))
    """
    tab_headers = [
        ft.Tab(label=label_text, icon=icon) for label_text, icon, _ in items
    ]
    views = [body for _, _, body in items]
    return ft.Tabs(
        length=len(items),
        selected_index=selected_index,
        expand=True,
        content=ft.Column(
            expand=True,
            spacing=0,
            controls=[
                ft.TabBar(
                    tabs=tab_headers,
                    label_color=TEXT,
                    unselected_label_color=TEXT_MUTED,
                    indicator_color=ACCENT,
                    divider_color=BORDER,
                ),
                ft.TabBarView(
                    expand=True,
                    controls=views,
                ),
            ],
        ),
    )


# ---------------------------------------------------------------------------
# App entry
# ---------------------------------------------------------------------------


def main(page: ft.Page) -> None:
    ensure_output_dir()
    page.title = APP_TITLE
    page.theme_mode = ft.ThemeMode.DARK
    page.theme = page_theme()
    page.bgcolor = BG
    page.padding = 12
    page.window.width = 1600
    page.window.height = 960
    page.window.min_width = 1200
    page.window.min_height = 720

    # File picking uses native OS dialogs (see flet_pickers) — no Flet FilePicker
    # control is mounted, which avoids "Unknown control: FilePicker" on Flet 0.86.

    # Audio Play uses the OS default player (see flet_audio_player) — no flet-audio Service.

    state = StudioState()
    studio_image = StudioImageView(page, state)
    studio_video = StudioVideoView(page, state)
    tools_view = ToolsView(page, state)
    vision_view = CreativeVisionView(page, state)
    frame_editor_view = FrameEditorView(page, state)
    audio_view = AudioView(page, state)
    library_view = LibraryView(page, state)
    state.video_view = studio_video
    state.image_view = studio_image
    state.library_view = library_view
    state.tools_view = tools_view
    state.vision_view = vision_view  # type: ignore[attr-defined]
    state.frame_editor_view = frame_editor_view  # type: ignore[attr-defined]
    # Soft tool defaults for the restored app scenario (no tool auto-switch)
    try:
        tools_view.apply_app_scenario(state.scenario_key)
    except Exception:
        pass

    # Keep output_dir in sync for all views (+ persist last path — Phase E)
    def _sync_output(path: str) -> None:
        from media_studio.ui_prefs import set_output_dir_pref

        p = (path or state.output_dir or "").strip() or state.output_dir
        state.output_dir = p
        try:
            ensure_output_dir(Path(p))
        except OSError:
            pass
        set_output_dir_pref(p)

    # Top chrome
    out_field = ft.TextField(
        label="Output folder",
        value=state.output_dir,
        dense=True,
        filled=True,
        fill_color=PANEL_ELEVATED,
        border_color=BORDER,
        color=TEXT,
        text_size=FONT_SM,
        expand=True,
        on_change=lambda e: _sync_output(e.control.value or state.output_dir),
        on_blur=lambda e: _sync_output(e.control.value or state.output_dir),
    )

    async def _open_out(e: ft.ControlEvent) -> None:
        msg = open_folder(state.output_dir)
        show_snack(page, msg)

    from media_studio.flet_settings import open_settings_dialog
    from media_studio.secrets_store import has_fal_key
    from media_studio.resolve_import import (
        ensure_handoff_dir,
        format_import_status,
        maybe_purge_handoff_cache,
        poll_new_handoff,
        read_latest_handoff,
        set_last_imported_id,
        write_studio_root_marker,
    )

    ensure_handoff_dir()
    write_studio_root_marker()
    try:
        maybe_purge_handoff_cache()
    except Exception:
        pass

    # Phase E: apply retention / cache bounds once at startup (background)
    async def _startup_disk_hygiene() -> None:
        try:
            from media_studio.cache_prune import apply_retention
            from media_studio.ui_prefs import get_retention_days

            await asyncio.to_thread(
                apply_retention,
                state.output_dir,
                retention_days=get_retention_days(),
            )
        except Exception:
            pass

    try:
        page.run_task(_startup_disk_hygiene)
    except Exception:
        pass

    def _apply_resolve_handoff(h, *, force: bool = False) -> str:
        """Load Resolve still + video into Image / Video / Tools. Returns status text."""
        if not h or not h.ok:
            return (
                "No Resolve handoff found. "
                "In Resolve: Workspace → Scripts → Send_to_AI_Media_Studio first."
            )
        # Always pass paths when present — loaders validate is_file and surface errors.
        if h.still_path:
            studio_image.load_source_path(
                h.still_path,
                status=format_import_status(h),
            )
            # Optional Grok scenario suggest (non-blocking)
            try:
                asyncio.get_event_loop().create_task(
                    studio_image._maybe_suggest_scenario(h.still_path)
                )
            except Exception:
                pass
        loaded_vid = studio_video.receive_from_resolve(
            video_path=h.video_path,
            still_path=h.still_path,
            clip_name=h.clip_name,
            handoff_id=h.handoff_id,
        )
        restore = getattr(tools_view, "restore", None)
        if restore is not None:
            try:
                restore.apply_resolve_media(
                    still_path=h.still_path if h.has_still else None,
                    video_path=h.video_path if h.has_video else None,
                    clip_name=h.clip_name,
                )
            except Exception:
                pass
        # Library: origin=resolve so All can badge and From Resolve filter works
        try:
            from media_studio.history import record_resolve_library

            record_resolve_library(
                still_path=h.still_path if h.has_still else None,
                video_path=h.video_path if h.has_video else None,
                clip_name=h.clip_name,
                handoff_id=h.handoff_id,
                output_dir=state.output_dir,
            )
        except Exception:
            pass
        # Refresh From Resolve strips everywhere media can load
        try:
            studio_image.resolve_strip.refresh()
        except Exception:
            pass
        try:
            studio_video._refresh_resolve_recent()
        except Exception:
            pass
        try:
            frame_editor_view.refresh_resolve_strip()
        except Exception:
            pass
        try:
            tools_view._refresh_active_prev_strip()
        except Exception:
            pass
        try:
            rs = getattr(vision_view, "resolve_strip", None)
            if rs is not None:
                rs.refresh()
        except Exception:
            pass
        try:
            library_view.refresh()
        except Exception:
            pass
        set_last_imported_id(h.handoff_id)
        msg = format_import_status(h)
        # Prefer Video tab when a clip was loaded so Source video is visible
        if loaded_vid or h.has_video:
            if state.switch_to_video:
                state.switch_to_video()
            studio_video.sync_from_state()
        try:
            studio_image._set_status(msg)
        except Exception:
            pass
        return msg

    keys_banner = ft.Container(
        content=ft.Row(
            [
                ft.Icon(ft.Icons.WARNING_AMBER_ROUNDED, color="#ffb74d", size=20),
                ft.Text(
                    "FAL API key required — open Settings to add your key before generating.",
                    size=FONT_SM,
                    color=TEXT,
                    expand=True,
                ),
                ft.TextButton(
                    content="Open Settings",
                    on_click=lambda _e: _open_settings(),
                    style=ft.ButtonStyle(color=ACCENT_BRIGHT),
                ),
            ],
            spacing=10,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        bgcolor="#3d2e12",
        border=ft.Border.all(1, "#ffb74d"),
        border_radius=8,
        padding=ft.Padding.symmetric(horizontal=12, vertical=8),
        visible=not has_fal_key(),
    )

    # Quiet credit status: fal balance · Runware (Aleph only) · xAI billing link
    from media_studio.billing import (
        fetch_fal_balance,
        fetch_runware_balance,
        xai_billing_url,
    )
    from media_studio.errors import FAL_TOPUP_URL
    from media_studio.flet_dialogs import open_url_in_browser

    fal_credits_label = ft.Text(
        "fal · …",
        size=FONT_SM,
        color=TEXT_MUTED,
        tooltip="fal credit balance",
    )
    btn_fal_credits = ft.TextButton(
        content=fal_credits_label,
        on_click=lambda _e: open_url_in_browser(FAL_TOPUP_URL),
        style=ft.ButtonStyle(color=TEXT_MUTED, padding=ft.Padding.symmetric(horizontal=4, vertical=2)),
        tooltip="fal credits — click to open billing",
    )
    runware_credits_label = ft.Text(
        "Runware · …",
        size=FONT_SM,
        color=TEXT_MUTED,
        tooltip="Runware credits (Frame Editor / Aleph only)",
    )
    btn_runware_credits = ft.TextButton(
        content=runware_credits_label,
        on_click=None,  # opens Settings focused on Runware — set below
        style=ft.ButtonStyle(
            color=TEXT_MUTED, padding=ft.Padding.symmetric(horizontal=4, vertical=2)
        ),
        tooltip=(
            "Runware / Aleph — optional. Only for Frame Editor. "
            "Click to open Settings for this key."
        ),
    )
    btn_xai_billing = ft.TextButton(
        content="xAI billing",
        on_click=None,  # Settings focus xai — set below
        style=ft.ButtonStyle(color=TEXT_MUTED, padding=ft.Padding.symmetric(horizontal=4, vertical=2)),
        tooltip="xAI console billing (no live balance via standard API key). Click for Settings.",
    )
    btn_refresh_credits = ft.IconButton(
        icon=ft.Icons.REFRESH,
        icon_size=16,
        icon_color=TEXT_MUTED,
        tooltip="Refresh fal + Runware balances",
        on_click=None,  # set below
        style=ft.ButtonStyle(padding=4),
    )

    def _schedule_coro(coro_fn) -> None:
        """Run an async callable without nested asyncio imports (avoids free-var crash)."""
        try:
            page.run_task(coro_fn)
            return
        except Exception:
            pass
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(coro_fn())
            else:
                asyncio.run(coro_fn())
        except Exception:
            pass

    async def _refresh_credits_ui(_e: ft.ControlEvent | None = None) -> None:
        """Fetch fal + Runware balances in worker threads; never crash the UI."""
        try:
            fal_credits_label.value = "fal · …"
            fal_credits_label.color = TEXT_MUTED
            runware_credits_label.value = "Runware · …"
            runware_credits_label.color = TEXT_MUTED
            try:
                page.update()
            except Exception:
                pass

            # fal
            try:
                bal = await asyncio.to_thread(fetch_fal_balance)
            except Exception as exc:
                from media_studio.billing import FalBalance

                bal = FalBalance(
                    ok=False,
                    label="fal · check billing",
                    check_billing=True,
                    detail=f"Balance refresh failed: {exc}",
                )
            fal_credits_label.value = bal.label
            fal_credits_label.color = TEXT if bal.ok else TEXT_MUTED
            tip = bal.detail or bal.label
            fal_credits_label.tooltip = tip
            btn_fal_credits.tooltip = tip

            # Runware (Frame Editor / Aleph only — never required for fal work)
            try:
                rbal = await asyncio.to_thread(fetch_runware_balance)
            except Exception as exc:
                from media_studio.billing import RunwareBalance

                rbal = RunwareBalance(
                    ok=False,
                    label="Runware · …",
                    check_billing=True,
                    detail=f"Balance refresh failed: {exc}",
                )
            runware_credits_label.value = rbal.label
            runware_credits_label.color = TEXT if rbal.ok else TEXT_MUTED
            rtip = rbal.detail or rbal.label
            runware_credits_label.tooltip = rtip
            btn_runware_credits.tooltip = rtip

            try:
                page.update()
            except Exception:
                pass
        except Exception:
            # Absolute last resort — keep UI alive
            try:
                fal_credits_label.value = "fal · check billing"
                fal_credits_label.color = TEXT_MUTED
                runware_credits_label.value = "Runware · …"
                runware_credits_label.color = TEXT_MUTED
                page.update()
            except Exception:
                pass

    btn_refresh_credits.on_click = _refresh_credits_ui

    def _refresh_keys_ui() -> None:
        keys_banner.visible = not has_fal_key()
        state.notify_keys_changed()
        try:
            page.update()
        except Exception:
            pass
        # Refresh balances after key save
        _schedule_coro(_refresh_credits_ui)

    def _on_settings_output_dir(path: str) -> None:
        """Settings → top chrome / StudioState (persisted path)."""
        if not path:
            return
        state.output_dir = path
        out_field.value = path
        try:
            ensure_output_dir(Path(path))
        except OSError:
            pass
        try:
            page.update()
        except Exception:
            pass
        # Refresh library if open so hide-missing / path stay consistent
        try:
            if state.library_view is not None:
                state.library_view.refresh()
        except Exception:
            pass

    def _open_settings(
        _e: ft.ControlEvent | None = None,
        *,
        focus: str | None = None,
    ) -> None:
        open_settings_dialog(
            page,
            on_saved=_refresh_keys_ui,
            on_balance_refresh=lambda: _schedule_coro(_refresh_credits_ui),
            on_output_dir_changed=_on_settings_output_dir,
            current_output_dir=state.output_dir,
            focus=focus,
        )

    def _open_settings_runware(_e: ft.ControlEvent | None = None) -> None:
        _open_settings(focus="runware")

    def _open_settings_xai(_e: ft.ControlEvent | None = None) -> None:
        _open_settings(focus="xai")

    def _open_settings_fal(_e: ft.ControlEvent | None = None) -> None:
        # Keep fal chip → billing URL (existing habit); gear still opens full Settings
        open_url_in_browser(FAL_TOPUP_URL)

    btn_fal_credits.on_click = _open_settings_fal
    btn_runware_credits.on_click = _open_settings_runware
    btn_xai_billing.on_click = _open_settings_xai

    btn_settings = ft.IconButton(
        icon=ft.Icons.SETTINGS,
        icon_color=TEXT,
        tooltip="Settings — keys, output folder, caches, retention",
        on_click=lambda e: _open_settings(e),
    )

    from media_studio.flet_onboarding import make_help_button, maybe_show_first_run
    from media_studio.flet_dialogs import open_url_in_browser

    # Quiet update banner (shown only when GitHub is newer)
    update_banner_text = ft.Text(
        "",
        size=FONT_SM,
        color=TEXT,
        expand=True,
        max_lines=2,
    )
    update_banner = ft.Container(
        content=ft.Row(
            [
                ft.Icon(ft.Icons.SYSTEM_UPDATE_ALT, color=ACCENT_BRIGHT, size=18),
                update_banner_text,
                ft.TextButton(
                    content="Open GitHub",
                    on_click=lambda _e: open_url_in_browser(
                        getattr(page, "_update_remote_url", None) or GITHUB_URL
                    ),
                    style=ft.ButtonStyle(color=ACCENT_BRIGHT),
                ),
                ft.IconButton(
                    icon=ft.Icons.CLOSE,
                    icon_size=16,
                    icon_color=TEXT_MUTED,
                    tooltip="Dismiss",
                    on_click=lambda _e: _dismiss_update_banner(),
                ),
            ],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        bgcolor="#1a2438",
        border=ft.Border.all(1, ACCENT),
        border_radius=6,
        padding=ft.Padding.symmetric(horizontal=10, vertical=6),
        visible=False,
    )

    def _dismiss_update_banner() -> None:
        update_banner.visible = False
        try:
            page.update()
        except Exception:
            pass

    def _show_update_available(message: str, remote_url: str) -> None:
        page._update_remote_url = remote_url or GITHUB_URL  # type: ignore[attr-defined]
        update_banner_text.value = message
        update_banner.visible = True
        try:
            page.update()
        except Exception:
            pass

    async def _run_update_check(*, force: bool = False, quiet_if_current: bool = True) -> None:
        """Background-friendly update check; never blocks generate."""
        try:
            from media_studio.ui_prefs import get_check_updates
            from media_studio.update_check import check_github_update

            if not force and not get_check_updates():
                return
            result = await asyncio.to_thread(check_github_update, force=force)
            if not result.ok:
                if force:
                    show_snack(page, result.message, duration_ms=4000)
                return
            if result.update_available:
                _show_update_available(result.message, result.remote_url)
                try:
                    show_snack(page, result.message, duration_ms=5500)
                except Exception:
                    pass
            elif force or not quiet_if_current:
                show_snack(page, result.message, duration_ms=3500)
        except Exception:
            if force:
                try:
                    show_snack(page, "Could not check for updates (offline?).")
                except Exception:
                    pass

    async def _update_check_manual() -> None:
        await _run_update_check(force=True, quiet_if_current=False)

    async def _update_check_startup() -> None:
        await _run_update_check(force=False, quiet_if_current=True)

    def _check_updates_now() -> None:
        _schedule_coro(_update_check_manual)

    btn_help = make_help_button(
        page,
        on_open_settings=lambda: _open_settings(),
        on_check_updates=_check_updates_now,
    )

    async def _import_from_resolve(e: ft.ControlEvent) -> None:
        h = read_latest_handoff()
        msg = _apply_resolve_handoff(h, force=True)
        is_err = h is None or not h.ok
        studio_image._set_status(msg)
        try:
            show_snack(page, msg)
        except Exception:
            pass
        try:
            page.update()
        except Exception:
            pass
        _ = is_err

    btn_import_resolve = ft.OutlinedButton(
        content="Import from Resolve",
        icon=ft.Icons.INPUT,
        on_click=_import_from_resolve,
        style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
        tooltip=(
            "Load the latest Resolve handoff (still + clip). "
            "In Resolve: Workspace → Scripts → Send_to_AI_Media_Studio"
        ),
    )

    header = ft.Row(
        [
            btn_settings,
            btn_help,
            ft.Text(APP_TITLE, size=FONT_XL, weight=ft.FontWeight.W_700, color=TEXT),
            ft.Container(expand=True),
            btn_fal_credits,
            btn_runware_credits,
            btn_xai_billing,
            btn_refresh_credits,
            btn_import_resolve,
            ft.Container(content=out_field, width=340),
            ft.OutlinedButton(
                content="Open folder",
                on_click=_open_out,
                style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
            ),
        ],
        alignment=ft.MainAxisAlignment.START,
        spacing=8,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )

    # ----- App-level scenario bar (configures Image / Video / Tools) -----
    from media_studio.scenarios import app_scenario_items
    from media_studio.ui_prefs import get_studio_mode, set_studio_mode

    _scenario_items = app_scenario_items()
    _scenario_ids = [i[0] for i in _scenario_items]
    if state.scenario_key not in _scenario_ids:
        state.set_scenario(default_scenario().key, notify=False, persist=True)

    scenario_active_label = ft.Text(
        f"Active · {state.scenario_label}",
        size=FONT_SM,
        color=TEXT,
        weight=ft.FontWeight.W_700,
    )
    scenario_desc = ft.Text(
        (get_scenario(state.scenario_key) or default_scenario()).description or "",
        size=FONT_SM,
        color=TEXT_MUTED,
        max_lines=2,
        expand=True,
    )

    def _on_app_scenario_pill(scenario_id: str) -> None:
        state.set_scenario(scenario_id, notify=True, persist=True)
        sc = get_scenario(scenario_id) or default_scenario()
        scenario_active_label.value = f"Active · {sc.label}"
        scenario_desc.value = sc.description or ""
        try:
            page.update()
        except Exception:
            pass

    scenario_nav = PillNav(
        _scenario_items,
        selected=state.scenario_key,
        on_change=_on_app_scenario_pill,
    )

    # Keep bar in sync when scenario set programmatically (suggest, etc.)
    def _sync_scenario_bar(key: str) -> None:
        sc = get_scenario(key) or default_scenario()
        try:
            scenario_nav.set_selected(sc.key, notify=False)
        except Exception:
            pass
        scenario_active_label.value = f"Active · {sc.label}"
        scenario_desc.value = sc.description or ""

    state.on_scenario_changed(_sync_scenario_bar)

    # Job / Listing — shared across Studio, Vision, Tools, Frame Editor, Audio
    job_name_field = ft.TextField(
        label="Job / Listing (optional)",
        hint_text="e.g. 123 Oak St · Smith · 2026-08-01 — empty = dated folder only",
        value=state.job_name or "",
        dense=True,
        filled=True,
        fill_color=PANEL_ELEVATED,
        border_color=BORDER,
        color=TEXT,
        text_size=FONT_SM,
        expand=True,
    )

    def _sync_job_name_live(_e: ft.ControlEvent | None = None) -> None:
        # Live for generate; disk only on blur/submit
        state.job_name = (job_name_field.value or "").strip()

    def _persist_job_name(_e: ft.ControlEvent | None = None) -> None:
        state.set_job_name(job_name_field.value or "", persist=True)

    job_name_field.on_change = _sync_job_name_live
    job_name_field.on_blur = _persist_job_name
    job_name_field.on_submit = _persist_job_name

    scenario_bar = ft.Container(
        content=ft.Column(
            [
                ft.Row(
                    [
                        ft.Text(
                            "Scenario",
                            size=FONT_SM,
                            color=TEXT,
                            weight=ft.FontWeight.W_700,
                        ),
                        ft.Container(
                            content=scenario_active_label,
                            bgcolor=ACCENT,
                            border_radius=4,
                            padding=ft.Padding.symmetric(horizontal=8, vertical=3),
                        ),
                        scenario_desc,
                    ],
                    spacing=10,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                scenario_nav.control,
                ft.Row(
                    [
                        job_name_field,
                        ft.Text(
                            "When set, media saves under outputs/jobs/<name>/…",
                            size=11,
                            color=TEXT_MUTED,
                        ),
                    ],
                    spacing=10,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
            ],
            spacing=6,
        ),
        bgcolor=PANEL,
        border=ft.Border.all(1, BORDER),
        border_radius=8,
        padding=ft.Padding.symmetric(horizontal=12, vertical=8),
    )

    # Restore last Studio mode (Image vs Video)
    _studio_mode = get_studio_mode()
    _studio_idx = 1 if _studio_mode == "video" else 0

    def _tab_body(control: ft.Control) -> ft.Control:
        """One expand layer into the tab body (no nested expand wrappers)."""
        return ft.Container(
            content=control,
            expand=True,
            padding=ft.Padding.only(top=8),
        )

    # Flet 0.86: TabBar + TabBarView inside Tabs.content
    # Studio sub-tabs: body already expands; single wrapper only
    studio_tabs = build_tabs(
        [
            ("Image", ft.Icons.IMAGE, _tab_body(studio_image.build())),
            ("Video", ft.Icons.MOVIE, _tab_body(studio_video.build())),
        ],
        selected_index=_studio_idx,
    )

    # Tab order: Studio · Tools · Creative Vision · Frame Editor · Audio · Library
    main_tabs = build_tabs(
        [
            ("Studio", ft.Icons.DASHBOARD, studio_tabs),
            ("Tools", ft.Icons.HANDYMAN, _tab_body(tools_view.build())),
            (
                "Creative Vision",
                ft.Icons.AUTO_AWESOME,
                _tab_body(vision_view.build()),
            ),
            (
                "Frame Editor",
                ft.Icons.MOVIE_FILTER,
                _tab_body(frame_editor_view.build()),
            ),
            ("Audio", ft.Icons.GRAPHIC_EQ, _tab_body(audio_view.build())),
            ("Library", ft.Icons.PHOTO_LIBRARY, _tab_body(library_view.build())),
        ]
    )

    def switch_to_video() -> None:
        """Select Studio → Video (outer tab 0, inner tab 1)."""
        try:
            main_tabs.selected_index = 0
            studio_tabs.selected_index = 1
            try:
                main_tabs.move_to(0)
            except Exception:
                pass
            try:
                studio_tabs.move_to(1)
            except Exception:
                pass
            try:
                set_studio_mode("video")
            except Exception:
                pass
            # Re-bind Source video label after tab becomes active
            studio_video.sync_from_state()
            page.update()
        except Exception:
            pass

    def switch_to_image() -> None:
        """Select Studio → Image (outer tab 0, inner tab 0)."""
        try:
            main_tabs.selected_index = 0
            studio_tabs.selected_index = 0
            try:
                main_tabs.move_to(0)
            except Exception:
                pass
            try:
                studio_tabs.move_to(0)
            except Exception:
                pass
            try:
                set_studio_mode("image")
            except Exception:
                pass
            page.update()
        except Exception:
            pass

    def switch_to_library() -> None:
        """Select Library tab and refresh list."""
        try:
            main_tabs.selected_index = 5
            try:
                main_tabs.move_to(5)
            except Exception:
                pass
            library_view.refresh()
            page.update()
        except Exception:
            pass

    def switch_to_tools(tool_id: str | None = None) -> None:
        """Select Tools tab; optionally open a tool pill (e.g. restore)."""
        try:
            main_tabs.selected_index = 1
            try:
                main_tabs.move_to(1)
            except Exception:
                pass
            if tool_id:
                try:
                    tools_view.select_tool(tool_id)
                except Exception:
                    pass
            page.update()
        except Exception:
            pass

    def switch_to_vision(role: str | None = None) -> None:
        """Select Creative Vision tab (optional role hint: start / end / i2v)."""
        try:
            main_tabs.selected_index = 2
            try:
                main_tabs.move_to(2)
            except Exception:
                pass
            # Role is applied by receive_* before switch; no mode wipe here
            _ = role
            page.update()
        except Exception:
            pass

    def switch_to_audio(panel_id: str | None = None) -> None:
        """Select Audio tab; optionally open a pill (music / sfx / …)."""
        try:
            main_tabs.selected_index = 4
            try:
                main_tabs.move_to(4)
            except Exception:
                pass
            if panel_id:
                try:
                    if hasattr(audio_view, "_on_audio_pill"):
                        audio_view._on_audio_pill(panel_id)
                    else:
                        audio_view._selected_audio = panel_id
                        state.audio_selected_id = panel_id
                        audio_view._apply_audio_visibility()
                except Exception:
                    pass
            page.update()
        except Exception:
            pass

    def switch_to_frame_editor(
        *,
        video_path: str | None = None,
        keyframe_path: str | None = None,
        pin: str | None = None,
        timestamp_s: float | None = None,
        job_name: str | None = None,
    ) -> None:
        """
        Select Frame Editor; optionally load source video and/or keyframe still.

        Keyframes honor ``state.frame_editor_return`` (Studio round-trip) so an
        edited still re-pins the same slot / timestamp when set. Without a
        source video, stills stage as handoff (load clip next).
        """
        try:
            main_tabs.selected_index = 3
            try:
                main_tabs.move_to(3)
            except Exception:
                pass
            fe = frame_editor_view
            if video_path:
                try:
                    fe.load_source(video_path, status=f"Loaded: {Path(video_path).name}")
                except Exception:
                    pass
            if keyframe_path:
                try:
                    # Prefer round-trip receive (keeps pin/time/slot from context)
                    if hasattr(fe, "receive_keyframe"):
                        ok = fe.receive_keyframe(
                            keyframe_path,
                            pin=pin,
                            timestamp_s=timestamp_s,
                            job_name=job_name,
                            status=f"Keyframe: {Path(keyframe_path).name}",
                        )
                        if not ok and not getattr(fe, "video_path", None):
                            # receive_keyframe already set a clear status
                            pass
                    else:
                        fe.add_keyframe(
                            keyframe_path,
                            pin=pin or "first",
                            timestamp_s=float(timestamp_s or 0.0),
                            status=f"Keyframe: {Path(keyframe_path).name}",
                        )
                except Exception:
                    pass
            try:
                fe.apply_key_gates()
            except Exception:
                pass
            page.update()
        except Exception:
            pass

    def _on_studio_tab_change(e: ft.ControlEvent) -> None:
        # When user opens Video tab, re-apply paths (TabBarView can lag off-screen updates)
        try:
            idx = getattr(studio_tabs, "selected_index", None)
            if idx == 1:
                try:
                    set_studio_mode("video")
                except Exception:
                    pass
                studio_video.sync_from_state()
                studio_video._refresh_resolve_recent()
                page.update()
            elif idx == 0:
                try:
                    set_studio_mode("image")
                except Exception:
                    pass
        except Exception:
            pass

    def _on_main_tab_change(e: ft.ControlEvent) -> None:
        try:
            idx = getattr(main_tabs, "selected_index", None)
            if idx == 5:  # Library
                library_view.refresh()
                page.update()
            elif idx == 3:  # Frame Editor — key banner + From Resolve strip
                try:
                    frame_editor_view.apply_key_gates()
                    frame_editor_view.refresh_resolve_strip()
                    page.update()
                except Exception:
                    pass
        except Exception:
            pass

    try:
        studio_tabs.on_change = _on_studio_tab_change
    except Exception:
        pass
    try:
        main_tabs.on_change = _on_main_tab_change
    except Exception:
        pass

    state.switch_to_video = switch_to_video
    state.switch_to_image = switch_to_image
    state.switch_to_library = switch_to_library  # type: ignore[attr-defined]
    state.switch_to_tools = switch_to_tools
    state.switch_to_vision = switch_to_vision  # type: ignore[attr-defined]
    state.switch_to_audio = switch_to_audio  # type: ignore[attr-defined]
    state.switch_to_frame_editor = switch_to_frame_editor  # type: ignore[attr-defined]
    state.audio_view = audio_view  # type: ignore[attr-defined]

    page.add(
        ft.Column(
            [
                header,
                update_banner,
                scenario_bar,
                keys_banner,
                ft.Divider(height=1, color=BORDER),
                main_tabs,
            ],
            expand=True,
            spacing=10,
        )
    )

    # First-run Quick Start (once; Help → Quick Start anytime)
    try:
        maybe_show_first_run(
            page,
            on_open_settings=lambda: _open_settings(),
        )
    except Exception:
        pass

    # Quiet fal balance on startup
    _schedule_coro(_refresh_credits_ui)

    # Quiet GitHub update check (Settings toggle; default on) — no auto-download
    try:
        from media_studio.ui_prefs import get_check_updates

        if get_check_updates():
            _schedule_coro(_update_check_startup)
    except Exception:
        pass

    # Watch Resolve handoff folder (poll) — reverse of Send to Resolve.
    # Also reacts to single-instance wake file when a second launch exits.
    async def _watch_resolve_handoff() -> None:
        from media_studio.single_instance import (
            bring_app_window_to_front,
            consume_wake_signal,
        )

        while True:
            try:
                # Faster when woken by a second instance; otherwise 2s
                woke = False
                try:
                    woke = consume_wake_signal()
                except Exception:
                    woke = False
                await asyncio.sleep(0.35 if woke else 2.0)
                # Re-check wake after sleep (Resolve may write handoff then launch)
                try:
                    if consume_wake_signal():
                        woke = True
                except Exception:
                    pass
                h = poll_new_handoff(mark=False)
                if h is None and not woke:
                    continue
                if h is None:
                    # Wake without new id — re-read latest once
                    try:
                        h = read_latest_handoff()
                    except Exception:
                        h = None
                if h is None:
                    continue
                msg = _apply_resolve_handoff(h)
                studio_image._set_status(msg)
                try:
                    show_snack(page, msg)
                except Exception:
                    pass
                try:
                    bring_app_window_to_front(page)
                except Exception:
                    pass
                try:
                    page.update()
                except Exception:
                    pass
            except asyncio.CancelledError:
                break
            except Exception:
                # Never crash the UI loop on watch errors
                continue

    _schedule_coro(_watch_resolve_handoff)


def run() -> None:
    ft.app(target=main)


if __name__ == "__main__":
    run()
