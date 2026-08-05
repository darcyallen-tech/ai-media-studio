"""Studio → Video tab (Kling V2V / I2V)."""

from __future__ import annotations

import asyncio
import traceback
from pathlib import Path
from typing import TYPE_CHECKING, Any

import flet as ft

from media_studio.config import MODEL_LABELS
from media_studio.fal.models import resolve_video_model
from media_studio.flet_theme import (
    ACCENT,
    ACCENT_BRIGHT,
    BORDER,
    FONT_LG,
    FONT_SM,
    PANEL,
    PANEL_ELEVATED,
    PillNav,
    RAIL_WIDTH,
    TEXT,
    TEXT_MUTED,
    label,
    make_estimated_cost_box,
    panel,
    section_title,
    styled_dropdown,
)
from media_studio.params_ui import build_parameters_dict, control_options, parameters_to_json
from media_studio.pricing import live_estimate_cost, probe_video_duration
from media_studio.scenarios import (
    DEFAULT_VIDEO_EDIT_MODEL,
    VIDEO_WORKSPACE_ORDER,
    build_video_ref_prompt,
    get_scenario,
    video_ref_status_label,
)
from media_studio.ui_prefs import get_video_workspace, set_video_workspace
from media_studio.flet_enhance import make_enhance_button, run_prompt_enhance
from media_studio.flet_pickers import pick_image, pick_video
from media_studio.flet_progress import CollapsibleJobLog, JobProgress, classify_progress
from media_studio.flet_video_player import VideoResultPlayer
from media_studio.media import video_poster_path
from media_studio.resolve_import import (
    load_resolve_video_history,
    record_resolve_video,
)
from media_studio.services import describe_job_kind, generate

if TYPE_CHECKING:
    from media_studio.flet_app import StudioState


def _dd_value(dd: ft.Dropdown) -> str | None:
    return dd.value


def _video_models(modality: str = "i2v") -> list[str]:
    from media_studio.studio_modality import models_for_video_modality

    vids = models_for_video_modality(modality)
    if not vids:
        vids = [m for m in MODEL_LABELS if m.startswith("Video ·")]
    return vids or [DEFAULT_VIDEO_EDIT_MODEL]


class StudioVideoView:
    """Studio Video — modalities I2V | T2V | V2V | R2V."""

    def __init__(self, page: ft.Page, state: StudioState) -> None:
        self.page = page
        self.state = state
        self._modality = "i2v"  # i2v | t2v | v2v | r2v

        self.ref_preview = ft.Image(
            src="", fit=ft.BoxFit.CONTAIN, width=180, height=120, visible=False
        )
        self.ref_placeholder = ft.Container(
            content=ft.Column(
                [
                    ft.Icon(ft.Icons.IMAGE_OUTLINED, color=TEXT_MUTED, size=28),
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
            width=180,
            height=120,
            bgcolor=PANEL_ELEVATED,
            border_radius=6,
            border=ft.Border.all(1, BORDER),
        )
        self.video_label = ft.Text(
            "Upload or Import from Resolve",
            size=FONT_SM,
            color=TEXT_MUTED,
            max_lines=2,
            selectable=True,
            text_align=ft.TextAlign.CENTER,
        )
        self.video_preview = ft.Image(
            src="",
            fit=ft.BoxFit.COVER,
            width=180,
            height=120,
            border_radius=6,
            visible=False,
        )
        self.video_placeholder = ft.Container(
            content=ft.Column(
                [
                    ft.Icon(ft.Icons.MOVIE_OUTLINED, color=TEXT_MUTED, size=28),
                    self.video_label,
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=4,
                tight=True,
            ),
            alignment=ft.Alignment.CENTER,
            width=180,
            height=120,
            bgcolor=PANEL_ELEVATED,
            border_radius=6,
            border=ft.Border.all(1, BORDER),
            padding=6,
        )
        self.resolve_recent_row = ft.Row(spacing=6, scroll=ft.ScrollMode.AUTO, height=72)

        # Secondary workspace: Received | Blank Canvas | Camera Lock
        saved_ws = get_video_workspace()
        self._workspace_id = saved_ws if saved_ws in {k for k, _ in VIDEO_WORKSPACE_ORDER} else "camera_lock"
        self._workspace_nav = PillNav(
            list(VIDEO_WORKSPACE_ORDER),
            selected=self._workspace_id,
            on_change=self._on_workspace_pill,
        )
        self._workspace_title = ft.Text(
            "Video · Camera Lock",
            size=FONT_SM,
            color=TEXT,
            weight=ft.FontWeight.W_700,
        )
        self._workspace_desc = ft.Text(
            "Apply reference still look while locking motion to the source clip.",
            size=FONT_SM,
            color=TEXT_MUTED,
            max_lines=3,
        )

        _init_prompt = build_video_ref_prompt(state.scenario_key or state.scenario_label)
        self._last_scenario_default_prompt: str = _init_prompt
        self.prompt_field = ft.TextField(
            label="Video prompt",
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
            hint_text="Describe the video edit…",
        )
        self.btn_reset_scenario = ft.TextButton(
            content="Reset to scenario default",
            icon=ft.Icons.RESTART_ALT,
            on_click=self._on_reset_scenario_prompt,
            style=ft.ButtonStyle(color=ACCENT_BRIGHT),
            tooltip="Reload the camera-lock prompt for the active app scenario",
        )
        state.on_scenario_changed(self.apply_app_scenario)

        from media_studio.studio_modality import default_model_for_modality

        models = _video_models("i2v")
        _init_vid = default_model_for_modality("i2v")
        if _init_vid not in models and models:
            _init_vid = models[0]
        self.model_dd = styled_dropdown(
            label_text="Video model",
            options=models,
            value=_init_vid,
            on_select=self._on_params_change,
            expand=True,
        )
        from media_studio.flet_model_hint import make_best_for_line, update_best_for_line

        self.model_best_for = make_best_for_line()
        update_best_for_line(
            self.model_best_for, self.model_dd.value, dropdown=self.model_dd
        )
        opts = control_options(self.model_dd.value)
        # Optional last frame for I2V (MiniMax H3 first→last)
        self.end_path: str | None = None
        self.end_preview = ft.Image(
            src="", fit=ft.BoxFit.CONTAIN, width=90, height=60, visible=False
        )
        self.end_placeholder = ft.Container(
            content=ft.Text("End frame", size=FONT_SM, color=TEXT_MUTED),
            width=90,
            height=60,
            alignment=ft.Alignment.CENTER,
            bgcolor=PANEL_ELEVATED,
            border=ft.Border.all(1, BORDER),
            border_radius=6,
        )
        self.btn_pick_end = ft.OutlinedButton(
            content="End frame",
            icon=ft.Icons.IMAGE_OUTLINED,
            on_click=self._pick_end_frame,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
            visible=False,
        )
        self.end_frame_col = ft.Column(
            [
                label("End (optional)", muted=True),
                ft.Stack([self.end_placeholder, self.end_preview]),
                self.btn_pick_end,
            ],
            spacing=4,
            tight=True,
            visible=False,
        )
        self.native_stereo_note = ft.Text(
            "Native stereo audio on H3 output.",
            size=FONT_SM,
            color=TEXT_MUTED,
            visible=False,
        )
        self.dur_dd = styled_dropdown(
            label_text="Duration (s)",
            options=opts.get("duration_choices") or ["5"],
            value=opts.get("duration_value") or "5",
            on_select=self._on_params_change,
            expand=True,
        )
        self.res_dd = styled_dropdown(
            label_text="Resolution",
            options=opts.get("resolution_choices") or ["—"],
            value=opts.get("resolution_value") or "—",
            on_select=self._on_params_change,
            expand=True,
        )
        self.res_dd.visible = bool(opts.get("resolution_visible", False))
        self.aspect_dd = styled_dropdown(
            label_text="Aspect ratio",
            options=opts.get("aspect_choices") or ["—"],
            value=opts.get("aspect_value") or "—",
            on_select=self._on_params_change,
            expand=True,
        )
        self.aspect_dd.visible = bool(opts.get("aspect_visible", False))
        self.keep_audio = ft.Checkbox(
            label="Keep source audio",
            value=bool(opts.get("keep_audio_value", True)),
            on_change=self._on_params_change,
        )
        self.gen_audio = ft.Checkbox(
            label="Generate audio",
            value=bool(opts.get("generate_audio_value", False)),
            visible=bool(opts.get("generate_audio_visible", False)),
            on_change=self._on_params_change,
        )
        # LTX Retake only: segment start (seconds)
        self.start_time = ft.TextField(
            label="Retake start (s)",
            value=str(opts.get("start_time_value", 0.0)),
            dense=True,
            filled=True,
            fill_color=PANEL_ELEVATED,
            border_color=BORDER,
            color=TEXT,
            text_size=FONT_SM,
            width=120,
            visible=bool(opts.get("start_time_visible", False)),
            on_change=self._on_params_change,
            hint_text="0 = beginning",
        )

        self.cost_text, self.cost_box = make_estimated_cost_box(
            initial=self._estimate()
        )
        self.job_text = ft.Text(
            describe_job_kind(self.model_dd.value, None, None),
            size=FONT_SM,
            color=TEXT_MUTED,
        )
        self.status_text = ft.Text(
            "Upload or Import from Resolve (ref still + source clip), then Generate.",
            size=FONT_SM,
            color=TEXT_MUTED,
        )
        self.job_progress = JobProgress()
        self.job_log = CollapsibleJobLog()
        self.job_log.bind_page(page)
        self.progress_text = self.job_log.detail

        self.btn_generate = ft.FilledButton(
            content="Generate Video",
            icon=ft.Icons.MOVIE_CREATION,
            on_click=self._on_generate,
            style=ft.ButtonStyle(bgcolor=ACCENT_BRIGHT, color=TEXT, padding=14),
            height=44,
            expand=True,
        )
        self.btn_enhance = make_enhance_button(on_click=self._on_enhance)
        # FLUX 3 draft workflow
        self.draft_first = ft.Checkbox(
            label="Draft first (cheaper preview)",
            value=False,
            visible=False,
            on_change=lambda _e: self._refresh_cost_job(),
        )
        self.btn_enhance_full = ft.OutlinedButton(
            content="Enhance to full",
            icon=ft.Icons.AUTO_FIX_HIGH,
            on_click=self._on_enhance_to_full,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
            visible=False,
            disabled=True,
            tooltip="Promote FLUX 3 draft cache to full quality (uses draft_cache)",
        )
        self._draft_cache_url: str | None = None
        self._last_qc_fix: str = ""
        self.state.on_keys_changed(self.apply_key_gates)
        self.apply_key_gates()
        self.btn_pick_ref = ft.OutlinedButton(
            content="Upload ref",
            icon=ft.Icons.IMAGE,
            on_click=self._pick_ref,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
        )
        self.btn_pick_vid = ft.OutlinedButton(
            content="Upload video",
            icon=ft.Icons.VIDEO_FILE,
            on_click=self._pick_video,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
        )

        self.video_player = VideoResultPlayer(self.page, height=380)
        self._last_result_path: str | None = None
        self.btn_send_vsfx = ft.OutlinedButton(
            content="Send to Video → SFX",
            icon=ft.Icons.GRAPHIC_EQ,
            on_click=self._on_send_vsfx,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
            height=34,
            visible=False,
            tooltip="Open Audio → Video→SFX with this clip (or current source)",
        )
        # Originating Image scenario for Received workspace prompt
        self._received_scenario_label: str | None = state.scenario_label

        self._ref_col = ft.Column(
            [
                label("Reference still", muted=True),
                ft.Stack([self.ref_placeholder, self.ref_preview]),
                self.btn_pick_ref,
            ],
            spacing=4,
            tight=True,
        )
        self._vid_col = ft.Column(
            [
                label("Source video", muted=True),
                ft.Stack([self.video_placeholder, self.video_preview]),
                self.btn_pick_vid,
            ],
            spacing=4,
            tight=True,
        )
        self._media_row = ft.Row(
            [self._ref_col, self._vid_col, self.end_frame_col],
            spacing=12,
        )

        self._apply_handoff_from_state()
        self._refresh_resolve_recent()
        self._apply_workspace_ui(self._workspace_id, rebuild_prompt=True)
        try:
            self.set_modality("i2v", force_default_model=False, notify_shell=False)
        except Exception:
            pass

    def set_modality(
        self,
        mode_id: str,
        *,
        force_default_model: bool = False,
        notify_shell: bool = True,
    ) -> None:
        """Switch I2V / T2V / V2V / R2V — filter models + media UI."""
        from media_studio.flet_theme import dropdown_options
        from media_studio.studio_modality import (
            default_model_for_modality,
            models_for_video_modality,
            normalize_video_modality,
        )

        mode = normalize_video_modality(mode_id)
        prev = self._modality
        self._modality = mode
        if notify_shell:
            try:
                cb = getattr(self.state, "on_video_modality_changed", None)
                if cb:
                    cb(mode)
            except Exception:
                pass

        filtered = models_for_video_modality(mode)
        if not filtered:
            filtered = _video_models(mode)
        self.model_dd.options = dropdown_options(filtered)
        cur = _dd_value(self.model_dd)
        preferred = default_model_for_modality(mode)
        if force_default_model or not cur or cur not in filtered:
            self.model_dd.value = preferred if preferred in filtered else filtered[0]

        # Media visibility
        show_still = mode in ("i2v", "v2v", "r2v")
        show_video = mode in ("v2v", "r2v", "i2v")  # I2V clip optional
        # T2V: hide both required media
        if mode == "t2v":
            show_still = False
            show_video = False
        if mode == "i2v":
            show_video = False  # still-driven; clip optional later if needed
        try:
            self._ref_col.visible = show_still
            self._vid_col.visible = show_video or mode == "r2v"
            # R2V: still + motion plate
            if mode == "r2v":
                self._ref_col.visible = True
                self._vid_col.visible = True
                try:
                    # relabel for omni
                    pass
                except Exception:
                    pass
        except Exception:
            pass

        # End frame for H3 I2V
        show_end = False
        if mode == "i2v":
            try:
                spec = resolve_video_model(_dd_value(self.model_dd))
                show_end = bool(spec and getattr(spec, "supports_end_frame", False))
            except Exception:
                show_end = False
        try:
            self.end_frame_col.visible = show_end
            self.btn_pick_end.visible = show_end
        except Exception:
            pass

        # Native stereo note for H3
        try:
            spec = resolve_video_model(_dd_value(self.model_dd))
            self.native_stereo_note.visible = bool(
                spec and getattr(spec, "native_stereo_audio", False)
            )
        except Exception:
            self.native_stereo_note.visible = False

        # Prompt labels
        try:
            if mode == "t2v":
                self.prompt_field.label = "Video prompt (text → video)"
                self.status_text.value = "T2V — text only; no still or clip required."
            elif mode == "i2v":
                self.prompt_field.label = "Video prompt (image → video)"
                self.status_text.value = (
                    "I2V — start still required; optional end frame when supported."
                )
            elif mode == "v2v":
                self.prompt_field.label = "Video prompt (video → video)"
                self.status_text.value = "V2V — source clip required; ref still optional."
            else:
                self.prompt_field.label = (
                    "Video prompt — cite Image 1 / Video 1 (R2V)"
                )
                self.status_text.value = (
                    "R2V — one reference still + optional motion clip as Video 1 "
                    "(e.g. MiniMax H3 Omni / Seedance reference). "
                    "Full multi-image + audio omni: Creative Vision · Omni reference."
                )
        except Exception:
            pass

        # Refresh param controls for selected model
        try:
            # Fake a model change event
            class _E:
                control = self.model_dd

            import asyncio

            # sync path of params
            self._apply_model_params_sync()
        except Exception:
            pass
        self._refresh_cost_job()
        try:
            self.page.update()
        except Exception:
            pass
        _ = prev

    def _apply_model_params_sync(self) -> None:
        """Refresh duration/res/aspect/audio from current model (no async)."""
        model = _dd_value(self.model_dd) or DEFAULT_VIDEO_EDIT_MODEL
        try:
            from media_studio.flet_model_hint import update_best_for_line

            update_best_for_line(self.model_best_for, model, dropdown=self.model_dd)
        except Exception:
            pass
        opts = control_options(model)
        # Duration (required for T2V / I2V cost + API)
        dur_choices = list(opts.get("duration_choices") or ["5"])
        # Filter sentinel "—" for video duration
        dur_choices = [d for d in dur_choices if d and d != "—"] or ["5"]
        self.dur_dd.options = [ft.DropdownOption(key=x, text=x) for x in dur_choices]
        show_dur = bool(opts.get("duration_visible", True))
        self.dur_dd.visible = show_dur
        pref_dur = opts.get("duration_value") or dur_choices[0]
        if pref_dur not in dur_choices or pref_dur == "—":
            pref_dur = dur_choices[0]
        self.dur_dd.value = pref_dur

        res_choices = list(opts.get("resolution_choices") or ["—"])
        self.res_dd.options = [ft.DropdownOption(key=x, text=x) for x in res_choices]
        self.res_dd.value = opts.get("resolution_value") or res_choices[0]
        self.res_dd.visible = bool(opts.get("resolution_visible", False))
        ar_choices = list(opts.get("aspect_choices") or ["—"])
        self.aspect_dd.options = [ft.DropdownOption(key=x, text=x) for x in ar_choices]
        self.aspect_dd.value = opts.get("aspect_value") or ar_choices[0]
        self.aspect_dd.visible = bool(opts.get("aspect_visible", False))
        self.keep_audio.value = bool(opts.get("keep_audio_value", True))
        self.keep_audio.visible = bool(opts.get("keep_audio_visible", True))
        # Native stereo models (H3): no generate_audio toggle
        if opts.get("native_stereo"):
            self.gen_audio.visible = False
            self.native_stereo_note.visible = True
        else:
            self.gen_audio.value = bool(opts.get("generate_audio_value", False))
            self.gen_audio.visible = bool(opts.get("generate_audio_visible", False))
            try:
                spec = resolve_video_model(model)
                self.native_stereo_note.visible = bool(
                    spec and getattr(spec, "native_stereo_audio", False)
                )
            except Exception:
                self.native_stereo_note.visible = False
        self.start_time.visible = bool(opts.get("start_time_visible", False))
        # FLUX 3 draft toggle (Studio VIDEO_MODELS or Vision T2V labels)
        try:
            from media_studio.flux3_draft import model_supports_draft
            from media_studio.vision_registry import find_vision_model

            vspec = resolve_video_model(model)
            if vspec is None:
                vspec = find_vision_model(model, "text_to_video") or find_vision_model(
                    model
                )
            show_draft = bool(vspec and model_supports_draft(vspec))
            self.draft_first.visible = show_draft
            if not show_draft:
                self.draft_first.value = False
                self.btn_enhance_full.visible = False
                self.btn_enhance_full.disabled = True
                self._draft_cache_url = None
            else:
                self.btn_enhance_full.visible = True
                self.btn_enhance_full.disabled = not bool(self._draft_cache_url)
        except Exception:
            self.draft_first.visible = False

    async def _pick_end_frame(self, e: ft.ControlEvent) -> None:
        req = False
        try:
            vspec = resolve_video_model(_dd_value(self.model_dd))
            req = bool(
                vspec
                and (
                    getattr(vspec, "requires_end_frame", False)
                    or "first-last-frame" in (vspec.endpoint or "")
                )
            )
        except Exception:
            req = False
        title = "I2V end frame (required)" if req else "I2V end frame (optional)"
        try:
            files = await pick_image(self.page, dialog_title=title)
        except Exception as exc:
            self.status_text.value = f"Picker error: {exc}"
            self.page.update()
            return
        if not files or not files[0].path:
            return
        self.end_path = str(Path(files[0].path).resolve())
        self.end_preview.src = self.end_path
        self.end_preview.visible = True
        self.end_placeholder.visible = False
        self.status_text.value = f"End frame: {Path(self.end_path).name}"
        self.page.update()

    def build(self) -> ft.Control:
        from media_studio.flet_layout import make_split_workspace

        left_controls: list[ft.Control] = [
            section_title("Video workspace"),
            self._workspace_nav.control,
            self._workspace_title,
            self._workspace_desc,
            ft.Divider(height=1, color=BORDER),
            self._media_row,
            self.native_stereo_note,
            label("Recently from Resolve", muted=True),
            self.resolve_recent_row,
            self.prompt_field,
            self.btn_reset_scenario,
            ft.Row([self.model_dd], spacing=0),
            self.model_best_for,
            ft.Row(
                [self.dur_dd, self.res_dd, self.aspect_dd, self.start_time],
                spacing=8,
            ),
            self.keep_audio,
            self.gen_audio,
            self.draft_first,
            self.job_text,
            ft.Row(
                [self.btn_enhance, self.btn_generate, self.btn_enhance_full],
                spacing=8,
            ),
            self.cost_box,
            self.job_progress.control,
            self.status_text,
            self.job_log.control,
        ]
        # CapRightEmpty — player is non-expand when empty
        try:
            self.video_player.control.expand = False
        except Exception:
            pass
        self.send_host = ft.Container(visible=False)
        right = ft.Column(
            [
                section_title("Result preview"),
                self.video_player.control,
                self.send_host,
                self.btn_send_vsfx,
            ],
            spacing=8,
            tight=True,
            expand=False,
            alignment=ft.MainAxisAlignment.START,
        )
        return make_split_workspace(left_controls, right, left_width=RAIL_WIDTH)

    # ----- workspaces -----

    def _on_workspace_pill(self, workspace_id: str) -> None:
        self._apply_workspace_ui(workspace_id, rebuild_prompt=True)
        try:
            self.page.update()
        except Exception:
            pass

    def apply_app_scenario(self, key: str) -> None:
        """
        App-level scenario changed.

        - Blank Canvas video workspace: never inject scenario language
        - Camera Lock: refresh camera-lock prompt when safe (or leave edits)
        - Received: keep the handoff scenario unless none set
        """
        from media_studio.scenarios import is_blank_canvas, prompt_is_scenario_defaultish

        wid = self._workspace_id
        if wid == "blank":
            try:
                self.btn_reset_scenario.visible = False
            except Exception:
                pass
            return
        try:
            self.btn_reset_scenario.visible = True
        except Exception:
            pass

        if wid == "received":
            # Prefer originating Image scenario; fall back to app scenario
            sc = self._received_scenario_label or self.state.scenario_label or key
            new_default = build_video_ref_prompt(sc)
        else:
            # camera_lock
            new_default = build_video_ref_prompt(key or self.state.scenario_key)

        if is_blank_canvas(key) and wid == "camera_lock":
            # App Blank: freeform camera-lock still possible, clear template
            new_default = (
                "Preserve the exact camera motion and framing from the source clip. "
                "Apply the look of the reference still. Architecture and composition locked."
            )

        replace = prompt_is_scenario_defaultish(
            self.prompt_field.value,
            last_default=self._last_scenario_default_prompt,
            scenario_key=key,
        )
        if replace:
            self.prompt_field.value = new_default
            self._last_scenario_default_prompt = new_default
        self._refresh_cost_job()
        try:
            self.page.update()
        except Exception:
            pass

    async def _on_reset_scenario_prompt(self, e: ft.ControlEvent) -> None:
        if self._workspace_id == "blank":
            self.prompt_field.value = ""
            self._last_scenario_default_prompt = ""
        elif self._workspace_id == "received":
            sc = self._received_scenario_label or self.state.scenario_label
            built = build_video_ref_prompt(sc)
            self.prompt_field.value = built
            self._last_scenario_default_prompt = built
        else:
            built = build_video_ref_prompt(self.state.scenario_key or self.state.scenario_label)
            self.prompt_field.value = built
            self._last_scenario_default_prompt = built
        self.status_text.value = "Video prompt reset to scenario default."
        self._refresh_cost_job()
        try:
            self.page.update()
        except Exception:
            pass

    def _apply_workspace_ui(self, workspace_id: str, *, rebuild_prompt: bool = False) -> None:
        """Switch Received / Blank / Camera Lock copy + optional prompt defaults."""
        wid = (workspace_id or "camera_lock").strip().lower()
        if wid in ("blank_canvas",):
            wid = "blank"
        if wid not in ("received", "blank", "camera_lock"):
            wid = "camera_lock"
        self._workspace_id = wid
        try:
            set_video_workspace(wid)
        except Exception:
            pass

        # Map secondary workspace → modality (Received→I2V, Camera Lock→V2V)
        try:
            if wid == "camera_lock":
                self.set_modality("v2v", force_default_model=False, notify_shell=True)
            elif wid == "received":
                self.set_modality("i2v", force_default_model=False, notify_shell=True)
            # blank: leave current modality
        except Exception:
            pass

        if wid == "received":
            self._workspace_title.value = "Video · Received"
            self._workspace_desc.value = (
                "Stills sent from Image land here with a camera-lock prompt from that scenario. "
                "Add a source clip, edit the prompt, then Generate."
            )
            self.prompt_field.label = "Video prompt (from Image scenario)"
            self.status_text.value = (
                "Received workspace — Send to Video from Image, or upload ref + clip."
            )
            try:
                self.btn_reset_scenario.visible = True
            except Exception:
                pass
            if rebuild_prompt:
                sc_key = self._received_scenario_label or self.state.scenario_label
                built = build_video_ref_prompt(sc_key)
                self.prompt_field.value = built
                self._last_scenario_default_prompt = built
        elif wid == "blank":
            self._workspace_title.value = "Video · Blank Canvas"
            self._workspace_desc.value = (
                "Freeform I2V / V2V — no scenario template. "
                "Upload a reference still and/or source video, choose a model, write your prompt."
            )
            self.prompt_field.label = "Video prompt (freeform)"
            self.prompt_field.hint_text = "Describe the video you want…"
            self.status_text.value = (
                "Blank Canvas — upload media, write a prompt, Generate."
            )
            try:
                self.btn_reset_scenario.visible = False
            except Exception:
                pass
            if rebuild_prompt:
                self.prompt_field.value = ""
                self._last_scenario_default_prompt = ""
        else:
            self._workspace_title.value = "Video · Camera Lock"
            self._workspace_desc.value = (
                "Match motion to the source clip while applying the reference still look "
                "(camera-locked V2V). Uses the active app scenario for default wording."
            )
            self.prompt_field.label = "Video prompt (camera-lock)"
            self.status_text.value = (
                "Camera Lock — set reference still + source clip, then Generate."
            )
            try:
                self.btn_reset_scenario.visible = True
            except Exception:
                pass
            if rebuild_prompt:
                built = build_video_ref_prompt(
                    self.state.scenario_key or self.state.scenario_label
                )
                self.prompt_field.value = built
                self._last_scenario_default_prompt = built
        self._refresh_cost_job()

    # ----- public handoff -----

    def open_received(
        self,
        *,
        ref_path: str | None,
        scenario_label: str | None,
        video_path: str | None = None,
    ) -> None:
        """Image → Send to Video: open Received workspace and load assets."""
        self._received_scenario_label = scenario_label or self.state.scenario_label
        self.receive_from_image(
            ref_path=ref_path,
            scenario_label=scenario_label,
            switch_workspace=False,
        )
        if video_path:
            self.load_source_video(
                video_path,
                clip_name=Path(str(video_path)).name,
                status=None,
                record=False,
            )
        self._workspace_nav.set_selected("received", notify=False)
        self._apply_workspace_ui("received", rebuild_prompt=True)
        try:
            self.page.update()
        except Exception:
            pass

    def receive_from_image(
        self,
        *,
        ref_path: str | None,
        scenario_label: str | None,
        switch_workspace: bool = True,
    ) -> None:
        """Called after Image → Send to Video (or Library send as ref)."""
        if scenario_label:
            self._received_scenario_label = scenario_label
            self.state.scenario_label = scenario_label
        if ref_path and Path(ref_path).is_file():
            self.state.video_ref_path = str(Path(ref_path).resolve())
            self.ref_preview.src = self.state.video_ref_path
            self.ref_preview.visible = True
            self.ref_placeholder.visible = False
        sc = get_scenario(scenario_label or self.state.scenario_label)
        key = sc.key if sc else None
        kind = video_ref_status_label(key)
        if switch_workspace:
            self._workspace_nav.set_selected("received", notify=False)
            self._apply_workspace_ui("received", rebuild_prompt=True)
            self.status_text.value = (
                f"Received · {kind}: {Path(ref_path).name if ref_path else 'still'}. "
                "Upload a source clip if needed, then Generate."
            )
        else:
            built = build_video_ref_prompt(key)
            self.prompt_field.value = built
            self._last_scenario_default_prompt = built
            self.status_text.value = (
                f"Reference loaded for {kind}. Upload a source clip, then Generate Video."
            )
        self._refresh_cost_job()
        try:
            self.page.update()
        except Exception:
            pass

    def receive_from_resolve(
        self,
        *,
        video_path: str | None,
        still_path: str | None,
        clip_name: str | None = None,
        handoff_id: str | None = None,
    ) -> bool:
        """
        Load source clip (+ optional still as ref) from Resolve handoff.

        Returns True if a source video was loaded successfully.
        """
        name = (clip_name or "Resolve clip").strip() or "Resolve clip"
        loaded_video = False

        if still_path and Path(still_path).is_file():
            self.state.video_ref_path = str(Path(still_path).resolve())
            self.ref_preview.src = self.state.video_ref_path
            self.ref_preview.visible = True
            self.ref_placeholder.visible = False

        if video_path:
            loaded_video = self.load_source_video(
                video_path,
                clip_name=name,
                status=None,
                record=True,
                still_path=still_path,
                handoff_id=handoff_id,
            )

        has_still = bool(still_path and Path(str(still_path)).is_file())
        if loaded_video and self.state.video_source_path:
            src_name = Path(self.state.video_source_path).name
            if has_still:
                self.status_text.value = (
                    f"Imported still + video from Resolve: {name} · source {src_name}"
                )
            else:
                self.status_text.value = (
                    f"Imported video from Resolve: {name} · source {src_name}"
                )
        elif has_still:
            if video_path:
                self.status_text.value = (
                    f"Imported still from Resolve: {name} "
                    f"(video not found: {Path(str(video_path)).name})"
                )
            else:
                self.status_text.value = (
                    f"Imported still from Resolve: {name} (no video_path in handoff)"
                )
        else:
            self.status_text.value = f"Resolve import for {name}: no media loaded."

        self._refresh_cost_job()
        self._refresh_resolve_recent()
        self.sync_from_state()
        return loaded_video

    def load_source_video(
        self,
        path: str | Path,
        *,
        clip_name: str | None = None,
        status: str | None = None,
        record: bool = False,
        still_path: str | None = None,
        handoff_id: str | None = None,
    ) -> bool:
        """Set Studio Video source clip; update label + state + poster."""
        try:
            p = Path(str(path).strip().strip('"'))
        except (TypeError, ValueError):
            return False
        if not p.is_file():
            self.video_label.value = f"Missing: {Path(str(path)).name}"
            self.video_label.color = "#e57373"
            self.video_label.tooltip = str(path)
            self._set_video_poster(None)
            return False
        try:
            resolved = str(p.resolve())
        except OSError:
            resolved = str(p)
        self.state.video_source_path = resolved
        display = clip_name or Path(resolved).name
        self.video_label.value = display
        self.video_label.color = TEXT
        self.video_label.tooltip = resolved
        self._set_video_poster(resolved)
        if record:
            try:
                record_resolve_video(
                    video_path=resolved,
                    clip_name=clip_name or Path(resolved).name,
                    still_path=still_path,
                    handoff_id=handoff_id,
                )
            except Exception:
                pass
        size_note = ""
        try:
            sz = Path(resolved).stat().st_size
            if sz > 200 * 1024 * 1024:
                mb = sz / (1024 * 1024)
                size_note = (
                    f" Large source ({mb:.0f} MB) — fal may fail to re-download; "
                    "prefer a 3–10s mp4 proxy from Resolve if generate errors."
                )
        except OSError:
            pass
        if status:
            self.status_text.value = status + size_note
        elif size_note:
            self.status_text.value = f"Source: {display}.{size_note}"
        self._refresh_cost_job()
        return True

    def _set_video_poster(self, video_path: str | None) -> None:
        """Show poster frame for source video, or fall back to placeholder."""
        poster: str | None = None
        if video_path and Path(video_path).is_file():
            try:
                poster = video_poster_path(video_path)
            except Exception:
                poster = None
        if poster and Path(poster).is_file():
            self.video_preview.src = poster
            self.video_preview.visible = True
            self.video_placeholder.visible = False
            self.video_preview.tooltip = video_path
        else:
            self.video_preview.src = ""
            self.video_preview.visible = False
            self.video_placeholder.visible = True
            # Keep filename under the icon when no poster yet
            if video_path and Path(video_path).is_file():
                self.video_label.value = Path(video_path).name
                self.video_label.color = TEXT

    def _refresh_resolve_recent(self) -> None:
        """Chip list of recent Resolve video imports (re-selectable) with posters."""
        entries = load_resolve_video_history()
        chips: list[ft.Control] = []
        for ent in entries:
            path = ent.path
            label_text = ent.clip_name or Path(path).name
            if len(label_text) > 22:
                label_text = label_text[:19] + "…"

            poster = None
            try:
                poster = video_poster_path(path)
            except Exception:
                poster = None

            def make_handler(pp: str, sn: str | None, cn: str):
                async def _click(_e: ft.ControlEvent) -> None:
                    # Always treat as local path — load_source_video → generate re-uploads
                    ok = self.load_source_video(
                        pp, clip_name=cn, status=f"Source video: {cn}", record=False
                    )
                    if sn and Path(sn).is_file():
                        self.state.video_ref_path = str(Path(sn).resolve())
                        self.ref_preview.src = self.state.video_ref_path
                        self.ref_preview.visible = True
                        self.ref_placeholder.visible = False
                    if not ok:
                        self.status_text.value = f"Missing video: {cn}"
                    self.page.update()

                return _click

            if poster and Path(poster).is_file():
                thumb: ft.Control = ft.Image(
                    src=poster,
                    width=96,
                    height=54,
                    fit=ft.BoxFit.COVER,
                    border_radius=4,
                )
            else:
                thumb = ft.Container(
                    content=ft.Icon(ft.Icons.MOVIE, color=TEXT_MUTED, size=22),
                    width=96,
                    height=54,
                    bgcolor=PANEL_ELEVATED,
                    border_radius=4,
                    alignment=ft.Alignment.CENTER,
                )

            chips.append(
                ft.Container(
                    content=ft.Column(
                        [
                            thumb,
                            ft.Text(
                                label_text,
                                size=11,
                                color=TEXT,
                                max_lines=1,
                                overflow=ft.TextOverflow.ELLIPSIS,
                                width=96,
                            ),
                        ],
                        spacing=2,
                        tight=True,
                    ),
                    bgcolor=PANEL_ELEVATED,
                    border=ft.Border.all(1, BORDER),
                    border_radius=8,
                    padding=4,
                    on_click=make_handler(path, ent.still_path, ent.clip_name),
                    tooltip=path,
                    ink=True,
                )
            )
        if not chips:
            chips = [
                ft.Text(
                    "No Resolve clips yet — use Import from Resolve",
                    size=FONT_SM,
                    color=TEXT_MUTED,
                )
            ]
        self.resolve_recent_row.controls = chips

    def sync_from_state(self) -> None:
        """Re-apply state paths to visible controls (tab switch / import)."""
        self._apply_handoff_from_state()
        try:
            self.page.update()
        except Exception:
            pass

    def _apply_handoff_from_state(self) -> None:
        if self.state.video_ref_path and Path(self.state.video_ref_path).is_file():
            self.ref_preview.src = self.state.video_ref_path
            self.ref_preview.visible = True
            self.ref_placeholder.visible = False
        if self.state.video_source_path and Path(self.state.video_source_path).is_file():
            self.video_label.value = Path(self.state.video_source_path).name
            self.video_label.color = TEXT
            self.video_label.tooltip = self.state.video_source_path
            self._set_video_poster(self.state.video_source_path)
        elif self.state.video_source_path:
            self.video_label.value = f"Missing: {Path(self.state.video_source_path).name}"
            self.video_label.color = "#e57373"
            self._set_video_poster(None)
        else:
            self._set_video_poster(None)

    def _params_json(self) -> str:
        start: float | None = None
        if self.start_time.visible:
            try:
                start = max(0.0, float(self.start_time.value or 0))
            except (TypeError, ValueError):
                start = 0.0
        return parameters_to_json(
            build_parameters_dict(
                duration=_dd_value(self.dur_dd),
                resolution=_dd_value(self.res_dd),
                aspect_ratio=_dd_value(self.aspect_dd),
                keep_audio=bool(self.keep_audio.value),
                generate_audio=bool(self.gen_audio.value),
                start_time=start,
            )
        )

    def _estimate(self) -> str:
        model = _dd_value(self.model_dd) or DEFAULT_VIDEO_EDIT_MODEL
        try:
            from media_studio.flux3_draft import (
                format_draft_vs_full_cost,
                model_supports_draft,
            )
            from media_studio.vision_registry import find_vision_model

            spec = resolve_video_model(model)
            if spec is None:
                spec = find_vision_model(model, "text_to_video") or find_vision_model(
                    model
                )
            if spec and model_supports_draft(spec):
                try:
                    dur = float(str(_dd_value(self.dur_dd) or "8").replace("s", "") or 8)
                except (TypeError, ValueError):
                    dur = 8.0
                if str(_dd_value(self.dur_dd) or "").lower() == "auto":
                    dur = 8.0
                return format_draft_vs_full_cost(
                    spec,
                    duration_s=dur,
                    resolution=_dd_value(self.res_dd),
                    generate_audio=bool(self.gen_audio.value)
                    if getattr(self.gen_audio, "visible", False)
                    else False,
                    draft_mode=bool(self.draft_first.value)
                    if getattr(self.draft_first, "visible", False)
                    else False,
                )
        except Exception:
            pass
        return live_estimate_cost(
            model_choice=model,
            image_file=self.state.video_ref_path,
            video_file=self.state.video_source_path,
            parameters_json=self._params_json(),
            probe_video=False,
        )

    def _refresh_cost_job(self) -> None:
        model = _dd_value(self.model_dd) or DEFAULT_VIDEO_EDIT_MODEL
        self.cost_text.value = self._estimate()
        self.job_text.value = describe_job_kind(
            model, self.state.video_ref_path, self.state.video_source_path
        )
        # Hint empty-state for I2V vs V2V
        try:
            if self._is_i2v_model(model):
                has_still = bool(
                    self.state.video_ref_path
                    and Path(self.state.video_ref_path).is_file()
                )
                if not has_still:
                    self.job_text.value = (
                        (self.job_text.value or "")
                        + " · I2V needs a reference still"
                    ).strip(" ·")
        except Exception:
            pass

    async def _on_params_change(self, e: ft.ControlEvent) -> None:
        model = _dd_value(self.model_dd) or DEFAULT_VIDEO_EDIT_MODEL
        if e.control is self.model_dd:
            try:
                from media_studio.flet_model_hint import update_best_for_line

                update_best_for_line(
                    self.model_best_for, model, dropdown=self.model_dd
                )
            except Exception:
                pass
            opts = control_options(model)
            self.dur_dd.options = [
                ft.DropdownOption(key=x, text=x) for x in (opts.get("duration_choices") or ["5"])
            ]
            if _dd_value(self.dur_dd) not in (opts.get("duration_choices") or []):
                self.dur_dd.value = opts.get("duration_value") or "5"
            res_choices = opts.get("resolution_choices") or ["—"]
            self.res_dd.options = [ft.DropdownOption(key=x, text=x) for x in res_choices]
            self.res_dd.value = opts.get("resolution_value") or res_choices[0]
            self.res_dd.visible = bool(opts.get("resolution_visible", False))
            ar_choices = opts.get("aspect_choices") or ["—"]
            self.aspect_dd.options = [
                ft.DropdownOption(key=x, text=x) for x in ar_choices
            ]
            self.aspect_dd.value = opts.get("aspect_value") or ar_choices[0]
            self.aspect_dd.visible = bool(opts.get("aspect_visible", False))
            self.keep_audio.value = bool(opts.get("keep_audio_value", True))
            self.keep_audio.visible = bool(opts.get("keep_audio_visible", True))
            self.gen_audio.value = bool(opts.get("generate_audio_value", False))
            self.gen_audio.visible = bool(opts.get("generate_audio_visible", False))
            self.start_time.visible = bool(opts.get("start_time_visible", False))
            if not self.start_time.value:
                self.start_time.value = str(opts.get("start_time_value", 0.0))
        self._refresh_cost_job()
        self.page.update()

    async def _pick_ref(self, e: ft.ControlEvent) -> None:
        try:
            files = await pick_image(self.page, dialog_title="Reference still")
        except Exception as exc:
            self.status_text.value = f"Picker error: {exc}"
            self.page.update()
            return
        if not files or not files[0].path:
            return
        path = str(Path(files[0].path).resolve())
        self.state.video_ref_path = path
        self.ref_preview.src = path
        self.ref_preview.visible = True
        self.ref_placeholder.visible = False
        self._refresh_cost_job()
        self.status_text.value = f"Reference: {Path(path).name}"
        self.page.update()

    async def _pick_video(self, e: ft.ControlEvent) -> None:
        try:
            files = await pick_video(self.page, dialog_title="Source video")
        except Exception as exc:
            self.status_text.value = f"Picker error: {exc}"
            self.page.update()
            return
        if not files or not files[0].path:
            return
        path = str(Path(files[0].path).resolve())
        self.load_source_video(path, status=None, record=False)
        # Default duration to source length when possible
        secs = await asyncio.to_thread(probe_video_duration, path)
        if secs and secs > 0:
            model = _dd_value(self.model_dd) or DEFAULT_VIDEO_EDIT_MODEL
            vspec = resolve_video_model(model)
            if vspec:
                matched = vspec.nearest_duration(secs)
                self.dur_dd.value = matched
                self.status_text.value = (
                    f"Source: {Path(path).name} ({secs:.1f}s) → duration {matched}s"
                )
            else:
                self.status_text.value = f"Source: {Path(path).name} ({secs:.1f}s)"
        else:
            self.status_text.value = f"Source: {Path(path).name}"
        self._refresh_cost_job()
        self.page.update()

    def apply_key_gates(self) -> None:
        from media_studio.secrets_store import has_fal_key, has_xai_key

        ready = has_fal_key()
        if not self.state.is_busy("video"):
            self.btn_generate.disabled = not ready
            self.btn_generate.tooltip = (
                None if ready else "Add your FAL API key in Settings to generate"
            )
            xai = has_xai_key()
            self.btn_enhance.disabled = not xai
            self.btn_enhance.tooltip = (
                "Rewrite video prompt for the selected model "
                "(uses reference still vision when present; model unchanged)"
                if xai
                else "Add your xAI API key in Settings to Enhance prompts"
            )

    async def _on_enhance(self, e: ft.ControlEvent) -> None:
        """Vision-aware prompt rewrite for the selected video model (all workspaces)."""
        from media_studio.studio_modality import normalize_video_modality

        modality = normalize_video_modality(getattr(self, "_modality", "i2v"))

        def _extra() -> dict[str, Any]:
            model = _dd_value(self.model_dd) or ""
            has_end = bool(
                getattr(self, "end_path", None)
                and Path(self.end_path).is_file()  # type: ignore[arg-type]
            )
            has_still = bool(
                self.state.video_ref_path
                and Path(self.state.video_ref_path).is_file()
            )
            has_clip = bool(
                self.state.video_source_path
                and Path(self.state.video_source_path).is_file()
            )
            draft_on = bool(
                getattr(self, "draft_first", None)
                and self.draft_first.visible
                and self.draft_first.value
            )
            snap: dict[str, Any] = {
                "workspace": "studio_video",
                "modality": modality,
                "has_start_still": has_still,
                "has_end_still": has_end,
                "has_source_video": has_clip and modality in ("v2v", "r2v"),
                "draft_first": draft_on,
            }
            # FLUX 3 Video — full crash course injected in enhance_prompt; set flags here
            try:
                from media_studio.flux3_draft import is_flux3_video_model_choice

                if is_flux3_video_model_choice(model):
                    snap["model_prompt_brief"] = "flux3_video"
                    # Modality mapping for flux3_enhance_mode_hint
                    if modality == "t2v":
                        snap["modality"] = "t2v"
                    elif modality == "i2v":
                        snap["modality"] = (
                            "first_last" if has_end else "i2v"
                        )
                    elif modality == "v2v":
                        snap["modality"] = "extend"
                    return snap
            except Exception:
                pass
            if modality == "t2v":
                snap["guidance"] = (
                    "Rewrite for text-to-video. Cinematic motion language. "
                    "No invented API params."
                )
            elif modality == "i2v":
                snap["guidance"] = (
                    "Rewrite for image-to-video. Start still is the first frame."
                    + (
                        " End still is the last frame — describe the transition."
                        if has_end
                        else ""
                    )
                )
            elif modality == "r2v":
                snap["guidance"] = (
                    "Rewrite for reference-to-video (R2V / omni). "
                    "Cite Image 1, Video 1, Audio 1 by role "
                    "(subject lock, camera path, timed bed). No invented API params."
                )
            else:
                snap["guidance"] = (
                    "Rewrite for video-to-video edit. Preserve motion / camera lock; "
                    "apply look from the reference still when present."
                )
            return snap

        await run_prompt_enhance(
            page=self.page,
            state=self.state,
            prompt_field=self.prompt_field,
            get_model=lambda: _dd_value(self.model_dd),
            get_image=lambda: (
                None if modality == "t2v" else self.state.video_ref_path
            ),
            get_video=lambda: (
                None if modality in ("t2v", "i2v") else self.state.video_source_path
            ),
            get_scenario=lambda: (
                self._received_scenario_label
                if self._workspace_id == "received"
                else self.state.scenario_label
            ),
            get_extra_context=_extra,
            status_ctrl=self.status_text,
            job_progress=self.job_progress,
            enhance_btn=self.btn_enhance,
            busy_controls=[self.btn_generate],
            context_label="video prompt",
        )
        self.apply_key_gates()
        try:
            self.page.update()
        except Exception:
            pass

    def _is_i2v_model(self, model_choice: str | None) -> bool:
        from media_studio.fal.models import resolve_job_kind, resolve_video_model

        spec = resolve_video_model(model_choice)
        if spec is not None:
            return spec.task == "image_to_video"
        kind = resolve_job_kind(
            model_choice,
            has_image=bool(
                self.state.video_ref_path and Path(self.state.video_ref_path).is_file()
            ),
            has_video=bool(
                self.state.video_source_path
                and Path(self.state.video_source_path).is_file()
            ),
        )
        return kind == "image_to_video"

    async def _on_send_vsfx(self, _e: ft.ControlEvent) -> None:
        """Send last result or current source clip to Audio → Video→SFX."""
        path = self._last_result_path or self.state.video_source_path
        if not path or not Path(path).is_file():
            self.status_text.value = "No video to send — generate or upload a clip first."
            try:
                self.page.update()
            except Exception:
                pass
            return
        from media_studio.flet_send_to import send_to_video_sfx

        handler = send_to_video_sfx(
            self.state,
            path,
            status_cb=lambda m: setattr(self.status_text, "value", m),
        )
        await handler(_e)  # type: ignore[arg-type]
        try:
            self.page.update()
        except Exception:
            pass

    def _refresh_send_menu(self, path: str | None) -> None:
        """Send to ▾ including Video Upscale for the result clip."""
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
                self.status_text.value = msg
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

    async def _on_enhance_to_full(self, e: ft.ControlEvent) -> None:
        """FLUX 3 draft-enhance: promote draft_cache to full quality."""
        if self.state.is_busy("video"):
            return
        cache = (self._draft_cache_url or "").strip()
        if not cache:
            self.status_text.value = (
                "Enhance to full needs a draft first (enable Draft first + Generate)."
            )
            self.page.update()
            return
        from media_studio.secrets_store import has_fal_key

        if not has_fal_key():
            self.status_text.value = "FAL API key required — open Settings."
            self.page.update()
            return
        if not self.state.try_busy("video"):
            return
        self.btn_enhance_full.disabled = True
        self.btn_generate.disabled = True
        self.job_progress.start("Enhancing draft to full…", self.page)
        self.status_text.value = "FLUX 3 draft-enhance…"
        self.page.update()

        def on_progress(msg: str) -> None:
            self.job_log.append(msg, self.page)
            self.job_progress.set_message(classify_progress(msg), self.page)

        try:
            from media_studio.flux3_draft import (
                estimate_full_cost_usd,
                run_draft_enhance,
            )
            from media_studio.job_context import to_thread_with_job

            model = _dd_value(self.model_dd) or ""
            spec = resolve_video_model(model)
            try:
                dur = float(str(_dd_value(self.dur_dd) or "8").replace("s", "") or 8)
            except (TypeError, ValueError):
                dur = 8.0
            full_est = (
                estimate_full_cost_usd(
                    spec,
                    duration_s=dur,
                    resolution=_dd_value(self.res_dd),
                    generate_audio=bool(self.gen_audio.value),
                )
                if spec
                else None
            )
            result = await to_thread_with_job(
                self.state,
                run_draft_enhance,
                draft_cache_url=cache,
                output_dir=self.state.output_dir,
                prompt_hint=(self.prompt_field.value or "flux3")[:40],
                model_key=getattr(spec, "key", None) or "flux 3 enhance",
                on_progress=on_progress,
                duration_s=dur,
                full_cost_usd=full_est,
            )
            if result.ok and result.path:
                self._last_result_path = result.path
                self.video_player.set_result(result.path)
                self._draft_cache_url = None
                self.btn_enhance_full.disabled = True
                self._refresh_send_menu(result.path)
                self.cost_text.value = result.cost_estimate or self._estimate()
                done = result.status or "Enhance to full OK"
                self.job_progress.finish_ok(done, self.page)
                self.job_log.finish_ok(self.page)
                self.status_text.value = done
            else:
                err = result.status or "Enhance to full failed."
                self.job_progress.finish_error(err, self.page)
                self.job_log.finish_error(err, self.page)
                self.status_text.value = err
                self.btn_enhance_full.disabled = False
        except Exception as exc:
            from media_studio.errors import friendly_error

            err = friendly_error(exc, context="Enhance to full")
            self.job_progress.finish_error(err, self.page)
            self.status_text.value = err
            self.btn_enhance_full.disabled = False
        finally:
            self.state.clear_busy("video")
            self.apply_key_gates()
            self._refresh_cost_job()
            self.page.update()

    async def _on_generate(self, e: ft.ControlEvent) -> None:
        if self.state.is_busy("video"):
            return
        from media_studio.secrets_store import has_fal_key

        if not has_fal_key():
            self.status_text.value = (
                "FAL API key required — open Settings (gear icon) to add your key."
            )
            self.page.update()
            return

        from media_studio.studio_modality import normalize_video_modality

        model = _dd_value(self.model_dd) or DEFAULT_VIDEO_EDIT_MODEL
        modality = normalize_video_modality(getattr(self, "_modality", None))
        # Align modality with model if user picked across groups
        i2v = self._is_i2v_model(model) or modality in ("i2v", "r2v", "t2v")
        has_still = bool(
            self.state.video_ref_path and Path(self.state.video_ref_path).is_file()
        )
        has_clip = bool(
            self.state.video_source_path and Path(self.state.video_source_path).is_file()
        )

        if modality == "t2v":
            pass  # text only
        elif modality == "r2v":
            if not has_still and not has_clip:
                self.status_text.value = (
                    "R2V needs at least one reference still or motion clip "
                    "(cite Image 1 / Video 1 in the prompt)."
                )
                self.page.update()
                return
        elif modality == "i2v":
            if not has_still:
                self.status_text.value = (
                    "I2V needs a start still — upload a reference image "
                    "or send a still from Studio Image."
                )
                self.page.update()
                return
            # FLUX 3 first→last (and similar) require both stills
            try:
                vspec = resolve_video_model(model)
                needs_end = bool(
                    vspec
                    and (
                        getattr(vspec, "requires_end_frame", False)
                        or "first-last-frame" in (vspec.endpoint or "")
                    )
                )
                has_end = bool(
                    getattr(self, "end_path", None)
                    and Path(self.end_path).is_file()  # type: ignore[arg-type]
                )
                if needs_end and not has_end:
                    self.status_text.value = (
                        f"{vspec.label if vspec else 'This model'} needs start + end "
                        "stills (first→last frame)."
                    )
                    self.page.update()
                    return
            except Exception:
                pass
        elif modality == "v2v":
            if not has_clip:
                self.status_text.value = (
                    "V2V needs a source clip — upload or Import from Resolve."
                )
                self.page.update()
                return
        else:
            # Fallback legacy
            if i2v and not has_still:
                self.status_text.value = "Image-to-video needs a start still."
                self.page.update()
                return
            if not i2v and not has_clip:
                self.status_text.value = "Video-to-video needs a source clip."
                self.page.update()
                return

        prompt = (self.prompt_field.value or "").strip()
        if not prompt:
            self.status_text.value = "Enter a video prompt."
            self.page.update()
            return

        if not self.state.try_busy("video"):
            return
        self.btn_generate.disabled = True
        self.job_progress.start(
            "Starting…" if modality == "t2v" else "Uploading…", self.page
        )
        self.status_text.value = {
            "t2v": "Starting text-to-video job…",
            "i2v": "Starting image-to-video job…",
            "r2v": "Starting reference-to-video job…",
            "v2v": "Starting video edit job…",
        }.get(modality, "Starting video job…")
        self.job_log.clear(self.page)
        self.video_player.clear()
        self.page.update()

        params = {}
        try:
            import json as _json

            params = _json.loads(self._params_json() or "{}")
        except Exception:
            params = {}
        # Optional I2V end frame (local path → upload in run_image_to_video)
        if (
            modality == "i2v"
            and getattr(self, "end_path", None)
            and Path(self.end_path).is_file()  # type: ignore[arg-type]
        ):
            params["end_image_path"] = self.end_path
        # FLUX 3 draft first
        if (
            getattr(self, "draft_first", None) is not None
            and self.draft_first.visible
            and self.draft_first.value
        ):
            params["draft"] = True
            params["draft_first"] = True
        params_json = self._params_json()
        try:
            import json as _json

            base = _json.loads(params_json or "{}")
            if params.get("end_image_path"):
                base["end_image_path"] = params["end_image_path"]
            if params.get("draft"):
                base["draft"] = True
                base["draft_first"] = True
            params_json = _json.dumps(base)
        except Exception:
            pass

        # Naming: Received uses originating Image scenario; Camera Lock uses state; Blank = none
        if self._workspace_id == "received":
            sc = get_scenario(self._received_scenario_label or self.state.scenario_label)
            scenario_key = sc.key if sc else None
        elif self._workspace_id == "blank":
            scenario_key = None
        else:
            sc = get_scenario(self.state.scenario_label)
            scenario_key = sc.key if sc else None

        def on_progress(msg: str) -> None:
            self.job_log.append(msg, self.page)
            self.job_progress.set_message(classify_progress(msg), self.page)

        try:
            from media_studio.job_context import to_thread_with_job

            if modality == "t2v":
                from media_studio.vision_service import run_vision
                from media_studio.services import GenerateResult

                vres = await to_thread_with_job(
                    self.state,
                    run_vision,
                    mode="text_to_video",
                    prompt=prompt,
                    model_label=model,
                    duration=_dd_value(self.dur_dd),
                    aspect_ratio=_dd_value(self.aspect_dd),
                    resolution=_dd_value(self.res_dd),
                    generate_audio=bool(self.gen_audio.value)
                    if self.gen_audio.visible
                    else None,
                    draft=bool(
                        self.draft_first.visible and self.draft_first.value
                    ),
                    output_dir=self.state.output_dir,
                    on_progress=on_progress,
                )
                result = GenerateResult(
                    ok=bool(vres.ok and vres.path),
                    video_path=vres.path,
                    status=vres.status or "",
                    model=vres.model_key or model,
                    job_kind="video",
                    cost_estimate=vres.cost_label or "",
                    notes=list(getattr(vres, "notes", None) or []),
                    metrics_line=vres.metrics_line or vres.cost_label or "",
                    is_draft=bool(getattr(vres, "is_draft", False)),
                    draft_cache_url=getattr(vres, "draft_cache_url", None),
                )
            else:
                # I2V: still only (optional clip ignored unless R2V)
                # V2V: clip required; still optional ref
                # R2V: still and/or clip (clip → motion ref for H3 omni)
                img = self.state.video_ref_path if has_still else None
                vid = None
                if modality == "v2v" and has_clip:
                    vid = self.state.video_source_path
                elif modality == "r2v" and has_clip:
                    vid = self.state.video_source_path
                result = await to_thread_with_job(
                    self.state,
                    generate,
                    prompt=prompt,
                    model_choice=model,
                    image_file=img,
                    video_file=vid,
                    output_dir=self.state.output_dir,
                    parameters_json=params_json,
                    on_progress=on_progress,
                    scenario=scenario_key,
                )
            if result.ok and result.video_path:
                vp = result.video_path
                self._last_result_path = vp
                self.video_player.set_result(vp)
                try:
                    self.btn_send_vsfx.visible = True
                except Exception:
                    pass
                # Draft cache for Enhance to full
                cache = getattr(result, "draft_cache_url", None)
                is_draft = bool(getattr(result, "is_draft", False))
                if is_draft and cache:
                    self._draft_cache_url = cache
                    self.btn_enhance_full.visible = True
                    self.btn_enhance_full.disabled = False
                elif not is_draft:
                    # Full quality run clears draft gate
                    self._draft_cache_url = None
                    if getattr(self, "draft_first", None) and self.draft_first.visible:
                        self.btn_enhance_full.visible = True
                        self.btn_enhance_full.disabled = True
                self._refresh_send_menu(vp)
                self.cost_text.value = result.cost_estimate or self._estimate()
                done = f"OK · {result.metrics_line or result.cost_estimate or 'done'}"
                if is_draft:
                    done = f"Draft OK · {result.cost_estimate or 'preview ready'}"
                self.job_progress.finish_ok(done, self.page)
                self.job_log.finish_ok(self.page)
                self.status_text.value = done
                # Compact post-gen QC (poster frame) when xAI key present
                try:
                    from media_studio.secrets_store import has_xai_key
                    from media_studio.grok_layer import critique_generation

                    if has_xai_key() and result.path:
                        qc = await asyncio.to_thread(
                            critique_generation,
                            result_path=result.path,
                            source_path=self.state.video_ref_path
                            or self.state.video_source_path,
                            prompt=(self.prompt_field.value or "").strip(),
                            job_kind="video",
                        )
                        if qc.ok and qc.summary:
                            bits = [f"QC [{qc.score}] {qc.summary}"]
                            if qc.issues:
                                bits.append(" · ".join(qc.issues[:3]))
                            self.status_text.value = f"{done}  ·  {' '.join(bits)}"
                            if qc.fix_prompt:
                                # Store for optional re-use; keep status compact
                                self._last_qc_fix = qc.fix_prompt
                except Exception:
                    pass
            else:
                from media_studio.errors import friendly_error

                err = friendly_error(
                    result.status or "Video generate failed.", context="Generate"
                )
                self.job_progress.finish_error(err, self.page)
                self.job_log.finish_error(err, self.page)
                self.status_text.value = err
        except Exception as exc:
            from media_studio.errors import friendly_error

            err = friendly_error(exc, context="Generate")
            self.job_progress.finish_error(err, self.page)
            self.job_log.finish_error(err, self.page)
            self.status_text.value = err
            traceback.print_exc()
        finally:
            self.state.clear_busy("video")
            self.apply_key_gates()
            self._refresh_cost_job()
            self.page.update()
