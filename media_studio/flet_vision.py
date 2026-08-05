"""
Creative Vision tab — T2I / I2I / T2V / I2V / bridge / extend shots.

Separate from Studio listing camera-lock flows. Expensive models; cost shown
before generate. Same export habits: Library, folder, Resolve, Send to ▾.
"""

from __future__ import annotations

import asyncio
import traceback
from pathlib import Path
from typing import TYPE_CHECKING, Any

import flet as ft

from media_studio.flet_character_picker import CharacterPicker
from media_studio.flet_enhance import make_enhance_button, run_prompt_enhance
from media_studio.flet_pickers import pick_audio, pick_image, pick_video
from media_studio.flet_progress import JobProgress, classify_progress
from media_studio.flet_source_strip import PreviousSourcesStrip, ResolveSourcesStrip
from media_studio.flet_theme import (
    ACCENT_BRIGHT,
    BORDER,
    FONT_SM,
    PANEL,
    PANEL_ELEVATED,
    TEXT,
    TEXT_MUTED,
    PillNav,
    dropdown_options,
    label,
    make_estimated_cost_box,
    panel,
    section_title,
    styled_dropdown,
)
from media_studio.flet_video_player import VideoResultPlayer
from media_studio.helper_none import HELPER_NONE, active_helper, is_helper_none, with_none
from media_studio.vision_prompt import (
    LENS_FEELS,
    MOTIONS,
    SHOT_TYPES,
    STILL_FRAMINGS,
    STILL_LENS_LOOKS,
    STILL_LIGHTING,
    STILL_STYLE_PRESETS,
    STYLE_PRESETS,
    compile_still_prompt,
    compile_vision_prompt,
    default_bridge_prompt,
    default_i2i_prompt,
    default_still_prompt,
)
from media_studio.vision_registry import (
    I2I_MAX_EXTRA_REFS,
    VISION_BATCH_MAX,
    VisionMode,
    default_vision_model,
    find_vision_model,
    format_vision_cost,
    is_still_mode,
    vision_labels,
)
from media_studio.vision_service import run_vision
from media_studio.vision_store import (
    VisionPreset,
    add_or_update_subject,
    add_vision_preset,
    delete_subject,
    delete_vision_preset,
    find_subject,
    load_presets,
    preset_choice_labels,
    subject_choice_labels,
)

if TYPE_CHECKING:
    from media_studio.flet_app import StudioState


def _dd(dd: ft.Dropdown) -> str | None:
    return dd.value


# Studio-standard cost chrome (imported at use sites via make_estimated_cost_box)


class CreativeVisionView:
    """Top-level Creative Vision workspace."""

    def __init__(self, page: ft.Page, state: StudioState) -> None:
        self.page = page
        self.state = state
        self._mode: VisionMode = "text_to_video"
        self.start_path: str | None = None
        self.end_path: str | None = None
        self.extend_path: str | None = None
        self.ref_paths: list[str] = []
        # MiniMax H3 omni: motion + audio plates (stills use ref_paths)
        self.ref_video_paths: list[str] = []
        self.ref_audio_paths: list[str] = []
        self._result_path: str | None = None

        # Mode nav (T2I / I2I first for still-then-Aleph / bridge workflows)
        self._mode_nav = PillNav(
            [
                ("text_to_image", "Text → Image"),
                ("image_to_image", "Image → Image"),
                ("text_to_video", "Text → Video"),
                ("image_to_video", "Image → Video"),
                ("bridge", "Bridge / Connect"),
                ("extend", "Extend Video"),
            ],
            selected=self._mode,
            on_change=self._on_mode,
        )

        # Model + cost
        labels = vision_labels(self._mode)
        self.model_dd = styled_dropdown(
            label_text="Model",
            options=labels,
            value=labels[0] if labels else None,
            on_select=self._on_model,
            expand=True,
        )
        self.model_notes = ft.Text("", size=FONT_SM, color=TEXT_MUTED, max_lines=3)
        from media_studio.flet_model_hint import make_best_for_line, update_best_for_line

        self.model_best_for = make_best_for_line()
        update_best_for_line(
            self.model_best_for,
            self.model_dd.value if hasattr(self, "model_dd") else None,
            dropdown=self.model_dd,
        )
        self.cost_text, self.cost_box = make_estimated_cost_box(
            initial="Est. cost: —"
        )

        # Duration / aspect / resolution
        spec0 = default_vision_model(self._mode)
        self.dur_dd = styled_dropdown(
            label_text="Duration",
            options=list(spec0.duration_choices),
            value=spec0.default_duration,
            on_select=self._refresh_cost,
            expand=True,
        )
        self.aspect_dd = styled_dropdown(
            label_text="Aspect",
            options=list(spec0.aspect_choices),
            value=spec0.default_aspect,
            on_select=self._refresh_cost,
            expand=True,
        )
        self.res_dd = styled_dropdown(
            label_text="Resolution",
            options=list(spec0.resolution_choices) or ["720p"],
            value=spec0.default_resolution or "720p",
            on_select=self._refresh_cost,
            expand=True,
        )
        # T2I multi-variant batch (1–4); sequential when API is one-at-a-time
        self.num_dd = styled_dropdown(
            label_text="# Images",
            options=[str(i) for i in range(1, VISION_BATCH_MAX + 1)],
            value="1",
            on_select=self._refresh_cost,
            expand=True,
        )
        self.num_dd.visible = False
        self.draft_first = ft.Checkbox(
            label="Draft first (cheaper preview)",
            value=False,
            visible=False,
            on_change=lambda _e: self._refresh_cost_only(),
        )
        self.btn_enhance_full = ft.OutlinedButton(
            content="Enhance to full",
            icon=ft.Icons.AUTO_FIX_HIGH,
            on_click=self._on_enhance_to_full,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
            visible=False,
            disabled=True,
            tooltip="Promote FLUX 3 draft cache to full quality",
        )
        self._draft_cache_url: str | None = None
        self.gen_audio = ft.Checkbox(
            label="Generate audio (when supported)",
            value=True,
            on_change=self._refresh_cost,
        )
        self._result_paths: list[str] = []
        self.variant_host = ft.Container(visible=False)
        self.variant_row = ft.Row(
            controls=[],
            spacing=6,
            scroll=ft.ScrollMode.AUTO,
            wrap=True,
        )
        self.variant_host.content = ft.Column(
            [
                ft.Text("Variants (click to select)", size=FONT_SM, color=TEXT_MUTED),
                self.variant_row,
            ],
            spacing=4,
            tight=True,
        )

        # Helpers: video uses shot/motion; T2I swaps to still framing/lighting (no motion)
        self.helpers_title = ft.Text(
            "Camera / shot helpers",
            size=FONT_SM,
            color=TEXT_MUTED,
            weight=ft.FontWeight.W_600,
        )
        self.shot_dd = styled_dropdown(
            label_text="Shot type",
            options=with_none(SHOT_TYPES),
            value=SHOT_TYPES[1],
            on_select=self._rebuild_prompt,
            expand=True,
        )
        self.lens_dd = styled_dropdown(
            label_text="Lens feel",
            options=with_none(LENS_FEELS),
            value=LENS_FEELS[1],
            on_select=self._rebuild_prompt,
            expand=True,
        )
        self.motion_dd = styled_dropdown(
            label_text="Motion",
            options=with_none(MOTIONS),
            value=MOTIONS[3],
            on_select=self._rebuild_prompt,
            expand=True,
        )
        self.lighting_dd = styled_dropdown(
            label_text="Lighting",
            options=with_none(STILL_LIGHTING),
            value=STILL_LIGHTING[0],
            on_select=self._rebuild_prompt,
            expand=True,
        )
        self.lighting_dd.visible = False
        self.style_dd = styled_dropdown(
            label_text="Style preset",
            options=with_none(list(STYLE_PRESETS.keys())),
            value="Clean modern day",
            on_select=self._on_style_preset,
            expand=True,
        )

        self.prompt = ft.TextField(
            label="Motion / shot prompt (editable — Enhance rewrites)",
            value=compile_vision_prompt(
                shot_type=SHOT_TYPES[1],
                lens=LENS_FEELS[1],
                motion=MOTIONS[3],
                style_preset="Clean modern day",
            ),
            multiline=True,
            min_lines=4,
            max_lines=8,
            dense=True,
            filled=True,
            fill_color=PANEL_ELEVATED,
            border_color=BORDER,
            color=TEXT,
            text_size=FONT_SM,
        )
        from media_studio.flet_prompt_favorites import make_prompt_favorites_bar

        self.prompt_favs = make_prompt_favorites_bar(
            page,
            get_text=lambda: self.prompt.value,
            set_text=lambda t: setattr(self.prompt, "value", t),
            surface="vision",
            get_meta=lambda: {
                "scenario": "creative_vision",
                "model": _dd(self.model_dd) or "",
                "source": "user",
            },
            on_status=lambda m: setattr(self.status, "value", m),
            show_pack_buttons=False,
        )
        self.creative_direction = ft.TextField(
            label="Creative direction for Enhance (optional)",
            hint_text=(
                "Intent only for Grok Enhance — not sent to the model. "
                "e.g. “epic Earth from orbit, cold blue grade, minimal stars”"
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
        self.creative_direction_hint = ft.Text(
            "Enhance-only: steers Grok when you hit Enhance. Empty = helpers + prompt only. "
            "Never injected into Generate as-is.",
            size=FONT_SM,
            color=TEXT_MUTED,
            max_lines=2,
        )
        self.negative = ft.TextField(
            label="Negative prompt (optional)",
            value="text overlay, watermark, morphing architecture, deformed rooms",
            dense=True,
            filled=True,
            fill_color=PANEL_ELEVATED,
            border_color=BORDER,
            color=TEXT,
            text_size=FONT_SM,
        )

        # Media pickers
        self.start_preview = ft.Image(
            src="", fit=ft.BoxFit.CONTAIN, width=120, height=80, visible=False
        )
        self.start_ph = ft.Container(
            content=ft.Text("Start still", size=FONT_SM, color=TEXT_MUTED),
            width=120,
            height=80,
            alignment=ft.Alignment.CENTER,
            bgcolor=PANEL_ELEVATED,
            border=ft.Border.all(1, BORDER),
            border_radius=6,
        )
        self.end_preview = ft.Image(
            src="", fit=ft.BoxFit.CONTAIN, width=120, height=80, visible=False
        )
        self.end_ph = ft.Container(
            content=ft.Text("End still", size=FONT_SM, color=TEXT_MUTED),
            width=120,
            height=80,
            alignment=ft.Alignment.CENTER,
            bgcolor=PANEL_ELEVATED,
            border=ft.Border.all(1, BORDER),
            border_radius=6,
        )
        self.btn_start = ft.OutlinedButton(
            content="Start frame",
            icon=ft.Icons.IMAGE,
            on_click=self._pick_start,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
        )
        self.btn_end = ft.OutlinedButton(
            content="End frame",
            icon=ft.Icons.IMAGE_OUTLINED,
            on_click=self._pick_end,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
        )
        self.extend_label = ft.Text(
            "No source clip", size=FONT_SM, color=TEXT_MUTED, max_lines=2
        )
        self.btn_extend = ft.OutlinedButton(
            content="Source clip",
            icon=ft.Icons.VIDEO_FILE_OUTLINED,
            on_click=self._pick_extend_video,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
        )
        self.extend_col = ft.Column(
            [self.extend_label, self.btn_extend],
            spacing=4,
            tight=True,
            visible=False,
        )
        self.char_picker = CharacterPicker(
            page,
            on_select=self._on_character_picked,
            on_clear=self._on_character_picker_clear,
            label_text="Saved character",
        )
        # Strength for Image→Image when model supports it
        self.strength_label = ft.Text(
            "Strength 0.60",
            size=FONT_SM,
            color=TEXT_MUTED,
            visible=False,
        )
        self.strength = ft.Slider(
            min=0.15,
            max=1.0,
            divisions=17,
            value=0.60,
            label="{value}",
            on_change=self._on_strength,
            visible=False,
        )
        self.prev_strip = PreviousSourcesStrip(
            page,
            get_output_dir=lambda: self.state.output_dir,
            on_load=self._on_prev_still,
            media_kind="image",
        )
        self.prev_strip.root.visible = False
        self.resolve_strip = ResolveSourcesStrip(
            page,
            on_load=self._on_resolve_still,
            media_kind="image",
        )
        self.resolve_strip.root.visible = False
        self.btn_refs = ft.OutlinedButton(
            content="Add reference stills",
            icon=ft.Icons.COLLECTIONS,
            on_click=self._pick_refs,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
        )
        self.btn_clear_refs = ft.TextButton(
            content="Clear refs",
            on_click=self._clear_refs,
            style=ft.ButtonStyle(color=TEXT_MUTED),
        )
        self.refs_label = ft.Text("No reference pack", size=FONT_SM, color=TEXT_MUTED)
        # I2I multi-ref chips (primary is start_path; extras in ref_paths, max 3)
        self.refs_hint = ft.Text(
            "",
            size=FONT_SM,
            color=TEXT_MUTED,
            max_lines=2,
            visible=False,
        )
        self.refs_chips = ft.Column(spacing=4, tight=True)
        self._strip_load_as_ref = False  # False = load strip → primary source
        self.strip_target_label = ft.Text(
            "Strip loads → Source still",
            size=11,
            color=TEXT_MUTED,
            visible=False,
        )
        self.btn_strip_as_source = ft.TextButton(
            content="Source",
            on_click=self._set_strip_target_source,
            style=ft.ButtonStyle(color=ACCENT_BRIGHT),
            visible=False,
        )
        self.btn_strip_as_ref = ft.TextButton(
            content="Add as ref",
            on_click=self._set_strip_target_ref,
            style=ft.ButtonStyle(color=TEXT_MUTED),
            visible=False,
        )
        # Shared Add/Clear row (video ref pack or I2I multi-ref) — one place only
        self.refs_actions_row = ft.Row(
            [self.btn_refs, self.btn_clear_refs, self.refs_label],
            spacing=8,
            wrap=True,
        )
        self.i2i_refs_panel = ft.Column(
            [
                self.refs_hint,
                self.refs_chips,
            ],
            spacing=4,
            tight=True,
            visible=False,
        )

        # MiniMax H3 omni reference panel (images / videos / audio + intent chips)
        self.omni_helper = ft.Text(
            "Cite each as Image 1, Video 1, Audio 1 in the prompt. "
            "Empty slots OK. Max 9 stills + 3 clips + 3 audio (≤12 files). "
            "Native stereo always on output.",
            size=FONT_SM,
            color=TEXT_MUTED,
            max_lines=3,
            visible=False,
        )
        self.omni_images_label = ft.Text(
            "Images 0/9", size=FONT_SM, color=TEXT_MUTED, visible=False
        )
        self.omni_videos_label = ft.Text(
            "Videos 0/3", size=FONT_SM, color=TEXT_MUTED, visible=False
        )
        self.omni_audio_label = ft.Text(
            "Audio 0/3", size=FONT_SM, color=TEXT_MUTED, visible=False
        )
        self.omni_images_chips = ft.Column(spacing=4, tight=True, visible=False)
        self.omni_videos_chips = ft.Column(spacing=4, tight=True, visible=False)
        self.omni_audio_chips = ft.Column(spacing=4, tight=True, visible=False)
        self.btn_omni_img = ft.OutlinedButton(
            content="Add image",
            icon=ft.Icons.IMAGE,
            on_click=self._pick_omni_images,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
            visible=False,
        )
        self.btn_omni_vid = ft.OutlinedButton(
            content="Add video",
            icon=ft.Icons.MOVIE,
            on_click=self._pick_omni_videos,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
            visible=False,
        )
        self.btn_omni_aud = ft.OutlinedButton(
            content="Add audio",
            icon=ft.Icons.AUDIO_FILE,
            on_click=self._pick_omni_audio,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
            visible=False,
        )
        self.btn_omni_clear = ft.TextButton(
            content="Clear omni refs",
            on_click=self._clear_omni_refs,
            style=ft.ButtonStyle(color=TEXT_MUTED),
            visible=False,
        )
        self.native_stereo_note = ft.Text(
            "Native stereo audio always on H3 output — Send to Resolve / Library as video+audio.",
            size=FONT_SM,
            color=TEXT_MUTED,
            max_lines=2,
            visible=False,
        )
        # Intent chips insert citation language into the prompt
        self._omni_chip_defs = (
            ("Image 1 = subject lock", "Image 1 = subject lock"),
            ("Video 1 = camera path only", "Video 1 = camera path / motion only"),
            ("Audio 1 = timed bed", "Audio 1 = timed bed / VO"),
            ("Image 2 = style", "Image 2 = style / material reference"),
        )
        self.omni_intent_row = ft.Row(spacing=6, wrap=True, visible=False)
        for chip_label, insert in self._omni_chip_defs:
            self.omni_intent_row.controls.append(
                ft.TextButton(
                    content=chip_label,
                    on_click=self._make_omni_intent_insert(insert),
                    style=ft.ButtonStyle(color=ACCENT_BRIGHT),
                )
            )
        self.omni_panel = ft.Column(
            [
                label("Omni reference (MiniMax H3)", muted=True),
                self.omni_helper,
                ft.Row(
                    [self.btn_omni_img, self.btn_omni_vid, self.btn_omni_aud, self.btn_omni_clear],
                    spacing=8,
                    wrap=True,
                ),
                self.omni_images_label,
                self.omni_images_chips,
                self.omni_videos_label,
                self.omni_videos_chips,
                self.omni_audio_label,
                self.omni_audio_chips,
                ft.Text("Intent chips (insert citation language)", size=FONT_SM, color=TEXT_MUTED),
                self.omni_intent_row,
            ],
            spacing=6,
            tight=True,
            visible=False,
        )

        # Subject library
        self.subject_dd = styled_dropdown(
            label_text="Use subject",
            options=subject_choice_labels(state.output_dir),
            value="(none)",
            on_select=self._on_subject,
            expand=True,
        )
        self.subject_name = ft.TextField(
            label="New subject name",
            hint_text="e.g. Realtor Jane",
            dense=True,
            filled=True,
            fill_color=PANEL_ELEVATED,
            border_color=BORDER,
            color=TEXT,
            text_size=FONT_SM,
            expand=True,
        )
        self.subject_notes = ft.TextField(
            label="Subject notes (optional)",
            hint_text="warm, navy blazer — consistency help, not a perfect lock",
            dense=True,
            filled=True,
            fill_color=PANEL_ELEVATED,
            border_color=BORDER,
            color=TEXT,
            text_size=FONT_SM,
            expand=True,
        )
        self.btn_save_subject = ft.OutlinedButton(
            content="Save subject from refs",
            icon=ft.Icons.PERSON_ADD,
            on_click=self._save_subject,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
        )
        self.btn_del_subject = ft.TextButton(
            content="Delete subject",
            on_click=self._delete_subject,
            style=ft.ButtonStyle(color=TEXT_MUTED),
        )

        # Vision presets
        self.preset_dd = styled_dropdown(
            label_text="Vision preset",
            options=preset_choice_labels(state.output_dir),
            value="(none)",
            on_select=self._on_load_preset,
            expand=True,
        )
        self.preset_name = ft.TextField(
            label="Preset name",
            hint_text="e.g. Twilight drone rise",
            dense=True,
            filled=True,
            fill_color=PANEL_ELEVATED,
            border_color=BORDER,
            color=TEXT,
            text_size=FONT_SM,
            expand=True,
        )
        self.btn_save_preset = ft.OutlinedButton(
            content="Save vision preset",
            icon=ft.Icons.BOOKMARK_ADD,
            on_click=self._save_preset,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
        )
        self.btn_del_preset = ft.TextButton(
            content="Delete preset",
            on_click=self._delete_preset,
            style=ft.ButtonStyle(color=TEXT_MUTED),
        )

        # Actions
        self.btn_generate = ft.FilledButton(
            content="Generate vision",
            on_click=self._run,
            style=ft.ButtonStyle(bgcolor=ACCENT_BRIGHT, color=TEXT),
            height=42,
        )
        self.btn_enhance = make_enhance_button(on_click=self._on_enhance)
        self.rebuild_mode = styled_dropdown(
            label_text="Rebuild mode",
            options=["Replace", "Append"],
            value="Replace",
            expand=True,
        )
        self.btn_rebuild = ft.TextButton(
            content="Rebuild prompt from helpers",
            on_click=self._rebuild_prompt,
            style=ft.ButtonStyle(color=TEXT_MUTED),
            tooltip=(
                "Replace: overwrite prompt with helpers. "
                "Append: prepend helpers to your text. "
                "Helper dropdowns only auto-update while the prompt still looks stock."
            ),
        )
        self.status = ft.Text("", size=FONT_SM, color=TEXT_MUTED, max_lines=5)
        self.job_progress = JobProgress()
        self.player = VideoResultPlayer(page, height=320)
        try:
            self.player.control.expand = False
        except Exception:
            pass
        # Still preview: CONTAIN inside dark frame — letterbox, never crop on wide panes
        self.result_image = ft.Image(
            src="",
            fit=ft.BoxFit.CONTAIN,
            expand=True,
            visible=True,
            gapless_playback=True,
        )
        self._result_frame = ft.Container(
            content=self.result_image,
            expand=False,
            height=280,
            bgcolor="#111318",
            border_radius=8,
            border=ft.Border.all(1, BORDER),
            alignment=ft.Alignment.CENTER,
            clip_behavior=ft.ClipBehavior.NONE,
            visible=False,
        )
        self.send_host = ft.Container(visible=False)

        self.state.on_keys_changed(self.apply_key_gates)
        self.cost_text.value = self._cost_label()
        self.apply_key_gates()
        self._apply_mode_visibility()
        self._sync_model_ui()

    # ----- layout -----

    def build(self) -> ft.Control:
        from media_studio.flet_layout import make_split_workspace
        from media_studio.flet_theme import RAIL_WIDTH

        left_controls: list[ft.Control] = [
            section_title("Creative Vision"),
            ft.Text(
                "Cinematic invention — text→image, image→image (creative still "
                "edit / Aleph plates), text/image→video, and bridge shots. "
                "Not listing camera-lock staging (use Studio for that). "
                "Video models are expensive — check Est. cost before Generate.",
                size=FONT_SM,
                color=TEXT_MUTED,
            ),
            self._mode_nav.control,
            ft.Divider(height=1, color=BORDER),
            ft.Row([self.model_dd], spacing=0),
            self.model_best_for,
            self.model_notes,
            ft.Row(
                [self.dur_dd, self.aspect_dd, self.res_dd, self.num_dd],
                spacing=8,
            ),
            self.strength_label,
            self.strength,
            self.gen_audio,
            self.draft_first,
            self.native_stereo_note,
            ft.Divider(height=1, color=BORDER),
            self.helpers_title,
            ft.Row([self.shot_dd, self.lens_dd], spacing=8),
            ft.Row([self.motion_dd, self.lighting_dd, self.style_dd], spacing=8),
            ft.Row([self.rebuild_mode, self.btn_rebuild], spacing=8),
            self.prompt,
            self.prompt_favs.root,
            self.creative_direction,
            self.creative_direction_hint,
            self.negative,
            # Generate then Est. cost chrome (Studio pattern)
            ft.Row(
                [self.btn_enhance, self.btn_generate, self.btn_enhance_full],
                spacing=8,
            ),
            self.cost_box,
            self.job_progress.control,
            self.status,
            ft.Divider(height=1, color=BORDER),
            label("Frames & reference pack", muted=True),
            ft.Row(
                [
                    ft.Column(
                        [self.start_ph, self.start_preview, self.btn_start],
                        spacing=4,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        tight=True,
                    ),
                    ft.Column(
                        [self.end_ph, self.end_preview, self.btn_end],
                        spacing=4,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        tight=True,
                    ),
                ],
                spacing=16,
                tight=True,
            ),
            self.extend_col,
            self.char_picker.root,
            self.refs_hint,
            self.refs_actions_row,
            self.refs_chips,
            self.omni_panel,
            ft.Row(
                [
                    self.strip_target_label,
                    self.btn_strip_as_source,
                    self.btn_strip_as_ref,
                ],
                spacing=4,
                wrap=True,
            ),
            self.prev_strip.root,
            self.resolve_strip.root,
            ft.Divider(height=1, color=BORDER),
            ft.ExpansionTile(
                title=ft.Text(
                    "Subject library",
                    size=FONT_SM,
                    color=TEXT,
                    weight=ft.FontWeight.W_600,
                ),
                subtitle=ft.Text(
                    "Optional — person/pet/car refs (not identity lock)",
                    size=FONT_SM,
                    color=TEXT_MUTED,
                ),
                expanded=False,
                affinity=ft.TileAffinity.LEADING,
                controls=[
                    ft.Column(
                        [
                            ft.Text(
                                "Save 3–8 stills of a person/pet/car. “Use subject” attaches refs. "
                                "Consistency help — not a perfect identity lock.",
                                size=FONT_SM,
                                color=TEXT_MUTED,
                            ),
                            ft.Row([self.subject_dd], spacing=0),
                            ft.Row([self.subject_name, self.subject_notes], spacing=8),
                            ft.Row(
                                [self.btn_save_subject, self.btn_del_subject],
                                spacing=8,
                            ),
                        ],
                        spacing=8,
                        tight=True,
                    )
                ],
            ),
            ft.ExpansionTile(
                title=ft.Text(
                    "Vision presets",
                    size=FONT_SM,
                    color=TEXT,
                    weight=ft.FontWeight.W_600,
                ),
                subtitle=ft.Text(
                    "Save / load full helper + prompt setups",
                    size=FONT_SM,
                    color=TEXT_MUTED,
                ),
                expanded=False,
                affinity=ft.TileAffinity.LEADING,
                controls=[
                    ft.Column(
                        [
                            ft.Row([self.preset_dd], spacing=0),
                            ft.Row(
                                [
                                    self.preset_name,
                                    self.btn_save_preset,
                                    self.btn_del_preset,
                                ],
                                spacing=8,
                            ),
                        ],
                        spacing=8,
                        tight=True,
                    )
                ],
            ),
        ]
        try:
            self.player.control.expand = False
        except Exception:
            pass
        # CapRightEmpty — tight until a still/video is shown
        self._right_col = ft.Column(
            [
                section_title("Result"),
                ft.Text(
                    "Still preview or video playback. "
                    "T2I / I2I: Send to Frame Editor keyframe, Start / End, or I2V. "
                    "Show in folder · Send to Resolve · Send to ▾",
                    size=FONT_SM,
                    color=TEXT_MUTED,
                ),
                self._result_frame,
                self.player.control,
                self.variant_host,
                self.send_host,
            ],
            spacing=8,
            tight=True,
            expand=False,
            alignment=ft.MainAxisAlignment.START,
        )
        return make_split_workspace(
            left_controls,
            self._right_col,
            left_width=max(RAIL_WIDTH, 480),
        )

    # ----- key gates / cost -----

    def apply_key_gates(self) -> None:
        from media_studio.secrets_store import has_fal_key, has_xai_key

        ready = has_fal_key()
        if not self.state.is_busy("vision"):
            self.btn_generate.disabled = not ready
            self.btn_generate.tooltip = (
                None if ready else "Add your FAL API key in Settings"
            )
            xai = has_xai_key()
            self.btn_enhance.disabled = not xai
            self.btn_enhance.tooltip = (
                "Rewrite prompt for the selected Vision model"
                if xai
                else "Add xAI API key for Enhance"
            )

    def _current_spec(self):
        return (
            find_vision_model(_dd(self.model_dd), self._mode)
            or default_vision_model(self._mode)
        )

    def _duration_token_for_cost(self, spec=None) -> str | None:
        """Selected duration for estimates — falls back to model default."""
        spec = spec or self._current_spec()
        if is_still_mode(self._mode):
            return None
        raw = _dd(self.dur_dd)
        choices = list(spec.duration_choices or ())
        if raw and (not choices or raw in choices):
            return raw
        return spec.default_duration or "8s"

    def _num_images_for_cost(self) -> int:
        if self._mode != "text_to_image":
            return 1
        try:
            return max(1, min(VISION_BATCH_MAX, int(_dd(self.num_dd) or 1)))
        except (TypeError, ValueError):
            return 1

    def _refresh_cost_only(self) -> None:
        try:
            self.cost_text.value = self._cost_label()
            self.page.update()
        except Exception:
            pass

    def _cost_label(self) -> str:
        try:
            spec = self._current_spec()
            audio = None
            if spec.supports_audio and not is_still_mode(self._mode):
                audio = bool(self.gen_audio.value)
            # FLUX 3 draft cost when toggle on
            from media_studio.flux3_draft import (
                format_draft_vs_full_cost,
                model_supports_draft,
            )
            from media_studio.vision_registry import duration_seconds

            if (
                not is_still_mode(self._mode)
                and model_supports_draft(spec)
                and getattr(self, "draft_first", None) is not None
            ):
                draft_on = bool(self.draft_first.value and self.draft_first.visible)
                dur = duration_seconds(self._duration_token_for_cost(spec))
                return format_draft_vs_full_cost(
                    spec,
                    duration_s=dur,
                    resolution=_dd(self.res_dd) if self.res_dd.visible else (
                        spec.default_resolution or None
                    ),
                    generate_audio=bool(audio) if audio is not None else False,
                    draft_mode=draft_on,
                )
            return format_vision_cost(
                spec,
                duration_token=self._duration_token_for_cost(spec),
                resolution=_dd(self.res_dd) if self.res_dd.visible else (
                    spec.default_resolution or None
                ),
                aspect_ratio=_dd(self.aspect_dd),
                generate_audio=audio,
                num_images=self._num_images_for_cost(),
            )
        except Exception:
            return "Est. cost: —"

    def _on_strength(self, e: ft.ControlEvent | None = None) -> None:
        try:
            v = float(self.strength.value or 0.6)
        except (TypeError, ValueError):
            v = 0.6
        self.strength_label.value = f"Strength {v:.2f}"
        try:
            self.page.update()
        except Exception:
            pass

    def _on_prev_still(self, path: str) -> None:
        """Previously used still → I2I source/ref, omni Image N, or video start."""
        if self._mode == "image_to_image":
            if self._strip_load_as_ref and self._i2i_extra_ref_cap() > 0:
                self.receive_i2i_ref(path, status=f"Previous ref: {Path(path).name}")
            else:
                self.receive_i2i_source(path, status=f"Previous: {Path(path).name}")
        elif self._is_omni_model():
            try:
                p = str(Path(path).resolve())
            except OSError:
                return
            mi, _, _, _ = self._omni_caps()
            if p not in self.ref_paths and len(self.ref_paths) < mi:
                self.ref_paths.append(p)
                self._sync_omni_panel()
                self.status.value = f"Omni Image {len(self.ref_paths)}: {Path(p).name}"
            try:
                self.page.update()
            except Exception:
                pass
        else:
            self.receive_start_frame(path, status=f"Previous: {Path(path).name}")

    def _on_resolve_still(self, path: str) -> None:
        """From Resolve still → I2I source/ref, omni Image N, or start frame."""
        if self._mode == "image_to_image":
            if self._strip_load_as_ref and self._i2i_extra_ref_cap() > 0:
                self.receive_i2i_ref(
                    path, status=f"From Resolve ref: {Path(path).name}"
                )
            else:
                self.receive_i2i_source(
                    path, status=f"From Resolve: {Path(path).name}"
                )
        elif self._is_omni_model():
            try:
                p = str(Path(path).resolve())
            except OSError:
                return
            mi, _, _, _ = self._omni_caps()
            if p not in self.ref_paths and len(self.ref_paths) < mi:
                self.ref_paths.append(p)
                self._sync_omni_panel()
                self.status.value = (
                    f"From Resolve → Omni Image {len(self.ref_paths)}: {Path(p).name}"
                )
            try:
                self.page.update()
            except Exception:
                pass
        else:
            self.receive_start_frame(path, status=f"From Resolve: {Path(path).name}")
        try:
            self.resolve_strip.refresh()
        except Exception:
            pass

    def _set_strip_target_source(self, _e: ft.ControlEvent | None = None) -> None:
        self._strip_load_as_ref = False
        self.strip_target_label.value = "Strip loads → Source still"
        try:
            self.btn_strip_as_source.style = ft.ButtonStyle(color=ACCENT_BRIGHT)
            self.btn_strip_as_ref.style = ft.ButtonStyle(color=TEXT_MUTED)
        except Exception:
            pass
        try:
            self.page.update()
        except Exception:
            pass

    def _set_strip_target_ref(self, _e: ft.ControlEvent | None = None) -> None:
        self._strip_load_as_ref = True
        self.strip_target_label.value = "Strip loads → Add as ref"
        try:
            self.btn_strip_as_source.style = ft.ButtonStyle(color=TEXT_MUTED)
            self.btn_strip_as_ref.style = ft.ButtonStyle(color=ACCENT_BRIGHT)
        except Exception:
            pass
        try:
            self.page.update()
        except Exception:
            pass

    def _i2i_extra_ref_cap(self) -> int:
        """
        Max extra refs for current I2I model (0 = single-image).

        Source of truth: fal.models max_ref_images (via edit_model_key), not a
        separate vision max_refs table (avoids dual drift).
        """
        if self._mode != "image_to_image":
            return 0
        try:
            from media_studio.fal.models import max_extra_ref_images_for_choice

            spec = self._current_spec()
            key = (getattr(spec, "edit_model_key", None) or "").strip()
            if not key:
                key = (getattr(spec, "label", None) or "").strip()
            extras = max_extra_ref_images_for_choice(key)
            return min(I2I_MAX_EXTRA_REFS, max(0, int(extras)))
        except Exception:
            return 0

    def _trim_i2i_refs(self) -> None:
        cap = self._i2i_extra_ref_cap()
        if len(self.ref_paths) > cap:
            self.ref_paths = self.ref_paths[:cap]

    def _sync_i2i_refs_panel(self) -> None:
        """Show I2I multi-ref UI when model allows extras; chips for each ref."""
        is_i2i = self._mode == "image_to_image"
        is_t2i = self._mode == "text_to_image"
        is_video = not is_still_mode(self._mode)
        cap = self._i2i_extra_ref_cap() if is_i2i else 0
        show_multi = is_i2i and cap > 0

        if is_t2i:
            try:
                self.refs_hint.visible = False
                self.refs_actions_row.visible = False
                self.refs_chips.visible = False
                self.strip_target_label.visible = False
                self.btn_strip_as_source.visible = False
                self.btn_strip_as_ref.visible = False
            except Exception:
                pass
            return

        if is_video:
            try:
                self.refs_hint.visible = False
                self.refs_actions_row.visible = True
                self.refs_chips.visible = False
                self.refs_chips.controls = []
                self.strip_target_label.visible = False
                self.btn_strip_as_source.visible = False
                self.btn_strip_as_ref.visible = False
                self.btn_refs.content = "Add reference stills"
                self.btn_refs.disabled = False
                self.btn_clear_refs.visible = True
                self.refs_label.value = (
                    f"{len(self.ref_paths)} ref still(s)"
                    if self.ref_paths
                    else "No reference pack"
                )
            except Exception:
                pass
            return

        # Image → Image
        self._trim_i2i_refs()
        n = len(self.ref_paths)
        try:
            self.refs_actions_row.visible = True
            self.strip_target_label.visible = show_multi
            self.btn_strip_as_source.visible = show_multi
            self.btn_strip_as_ref.visible = show_multi
            self.refs_hint.visible = True
        except Exception:
            pass

        if cap <= 0:
            self.refs_hint.value = (
                "This model is single-image only — extra reference stills are disabled."
            )
            self.btn_refs.disabled = True
            self.btn_clear_refs.visible = False
            self.refs_label.value = "Single-image model"
            self.refs_chips.controls = []
            self.refs_chips.visible = False
            return

        self.refs_hint.value = (
            f"Primary source + up to {cap} reference still(s) "
            f"(identity, material, furniture, sky…). {n}/{cap} used."
        )
        self.btn_refs.content = "Add ref"
        self.btn_refs.disabled = n >= cap
        self.btn_clear_refs.visible = True
        self.refs_label.value = (
            f"{n} ref still(s)" if n else "No reference stills"
        )
        chips: list[ft.Control] = []
        for i, path in enumerate(list(self.ref_paths)):
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
                                f"Ref {i + 1} · {name}",
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
                                on_click=self._make_remove_i2i_ref(i),
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
        self.refs_chips.visible = True

    def _make_remove_i2i_ref(self, index: int):
        async def _click(_e: ft.ControlEvent) -> None:
            if 0 <= index < len(self.ref_paths):
                removed = self.ref_paths.pop(index)
                self.status.value = f"Removed ref: {Path(removed).name}"
            self._sync_i2i_refs_panel()
            try:
                self.page.update()
            except Exception:
                pass

        return _click

    async def _refresh_cost(self, e: ft.ControlEvent | None = None) -> None:
        """Recompute total est. cost when duration / resolution / audio / model change."""
        self.cost_text.value = self._cost_label()
        try:
            self.page.update()
        except Exception:
            pass

    def _sync_model_ui(self) -> None:
        spec = self._current_spec()
        self.model_notes.value = spec.notes or ""
        try:
            from media_studio.flet_model_hint import update_best_for_line

            update_best_for_line(
                self.model_best_for, spec.label, dropdown=self.model_dd
            )
        except Exception:
            pass
        still = is_still_mode(self._mode)
        is_i2i = self._mode == "image_to_image"
        is_t2i = self._mode == "text_to_image"
        # Trim I2I refs when switching to a lower-cap model
        try:
            if is_i2i:
                self._sync_i2i_refs_panel()
        except Exception:
            pass
        # Multi-variant only for Text → Image
        try:
            self.num_dd.visible = is_t2i
        except Exception:
            pass
        # Duration (video only) — always offer choices for T2V/I2V/Bridge
        if still:
            self.dur_dd.visible = False
        else:
            choices = list(spec.duration_choices) if spec.duration_choices else [
                "4s",
                "6s",
                "8s",
            ]
            self.dur_dd.options = dropdown_options(choices)
            self.dur_dd.visible = True
            if _dd(self.dur_dd) not in choices:
                pref = spec.default_duration or choices[-1]
                self.dur_dd.value = pref if pref in choices else choices[0]
        # Aspect (still size presets or video aspect)
        self.aspect_dd.options = dropdown_options(list(spec.aspect_choices))
        if _dd(self.aspect_dd) not in spec.aspect_choices:
            self.aspect_dd.value = spec.default_aspect
        self.aspect_dd.label = "Size / aspect" if still else "Aspect"
        if spec.resolution_choices:
            self.res_dd.options = dropdown_options(list(spec.resolution_choices))
            self.res_dd.visible = True
            if _dd(self.res_dd) not in spec.resolution_choices:
                self.res_dd.value = spec.default_resolution
        else:
            self.res_dd.visible = False
        native = bool(getattr(spec, "native_stereo_audio", False))
        self.gen_audio.visible = bool(spec.supports_audio) and not still and not native
        try:
            self.native_stereo_note.visible = native and not still
        except Exception:
            pass
        # FLUX 3 draft
        try:
            from media_studio.flux3_draft import model_supports_draft

            show_draft = (not still) and model_supports_draft(spec)
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
        self.negative.visible = bool(spec.supports_negative) or still
        # Strength (I2I when model supports)
        show_str = is_i2i and bool(getattr(spec, "supports_strength", False))
        self.strength.visible = show_str
        self.strength_label.visible = show_str
        if show_str:
            self._on_strength(None)
        # Prompt label
        try:
            if is_i2i:
                self.prompt.label = "Edit prompt (editable — Enhance rewrites)"
                self.btn_generate.content = "Generate edit"
            elif still:
                self.prompt.label = "Image prompt (editable — Enhance rewrites)"
                self.btn_generate.content = "Generate still"
            elif getattr(spec, "omni_reference", False):
                self.prompt.label = (
                    "Motion prompt — cite Image 1 / Video 1 / Audio 1 (Enhance rewrites)"
                )
                self.btn_generate.content = "Generate vision"
            else:
                self.prompt.label = "Motion / shot prompt (editable — Enhance rewrites)"
                self.btn_generate.content = "Generate vision"
        except Exception:
            pass
        # Omni panel + cost
        try:
            self._sync_omni_panel()
        except Exception:
            pass
        # Total job cost for current duration / res / audio
        self.cost_text.value = self._cost_label()

    # ----- mode / model -----

    def _on_mode(self, mode_id: str) -> None:
        if mode_id not in (
            "text_to_image",
            "image_to_image",
            "text_to_video",
            "image_to_video",
            "bridge",
            "extend",
        ):
            return
        self._mode = mode_id  # type: ignore[assignment]
        labels = vision_labels(self._mode)
        self.model_dd.options = dropdown_options(labels)
        try:
            self.model_dd.value = default_vision_model(self._mode).label
        except Exception:
            self.model_dd.value = labels[0] if labels else None
        self._apply_mode_visibility()
        self._sync_model_ui()
        if self._mode == "bridge":
            # Soft default bridge language if prompt is empty/stock
            cur = (self.prompt.value or "").strip()
            if not cur or "Bridge the start frame" not in cur:
                self.prompt.value = default_bridge_prompt()
        elif self._mode == "extend":
            cur = (self.prompt.value or "").strip()
            if not cur or "Bridge the start frame" in cur.lower():
                self.prompt.value = (
                    "Continue the motion from the final frames of the source clip. "
                    "Keep subject identity and camera language consistent."
                )
        elif self._mode == "image_to_image":
            cur = (self.prompt.value or "").strip()
            low = cur.lower()
            video_stock = (
                not cur
                or "camera motion:" in low
                or "camera —" in low
                or "push in" in low
                or "slow push-in" in low
                or "bridge the start frame" in low
            )
            if video_stock:
                self.prompt.value = default_i2i_prompt()
        elif self._mode == "text_to_image":
            # Soft-switch to still helpers when prompt still looks like video stock
            cur = (self.prompt.value or "").strip()
            low = cur.lower()
            video_stock = (
                not cur
                or "camera motion:" in low
                or "camera —" in low
                or "push in" in low
                or "slow push-in" in low
            )
            if video_stock:
                self.prompt.value = default_still_prompt()
        try:
            self.page.update()
        except Exception:
            pass

    def _supports_end_frame(self) -> bool:
        """End-frame UI only for bridge modes or I2V models that declare support."""
        if self._mode == "bridge":
            return True
        if self._mode != "image_to_video":
            return False
        try:
            spec = self._current_spec()
            return bool(getattr(spec, "supports_end_frame", False))
        except Exception:
            return False

    def _is_omni_model(self) -> bool:
        try:
            return bool(getattr(self._current_spec(), "omni_reference", False))
        except Exception:
            return False

    def _is_native_stereo(self) -> bool:
        try:
            return bool(getattr(self._current_spec(), "native_stereo_audio", False))
        except Exception:
            return False

    def _omni_caps(self) -> tuple[int, int, int, int]:
        """max images, videos, audio, total."""
        try:
            spec = self._current_spec()
            mi = max(1, int(getattr(spec, "max_refs", 9) or 9))
            mv = max(0, int(getattr(spec, "max_ref_videos", 3) or 3))
            ma = max(0, int(getattr(spec, "max_ref_audios", 3) or 3))
            mt = max(0, int(getattr(spec, "max_total_refs", 12) or 12)) or 12
            return mi, mv, ma, mt
        except Exception:
            return 9, 3, 3, 12

    def _trim_omni_refs(self) -> None:
        mi, mv, ma, mt = self._omni_caps()
        self.ref_paths = list(self.ref_paths)[:mi]
        self.ref_video_paths = list(self.ref_video_paths)[:mv]
        self.ref_audio_paths = list(self.ref_audio_paths)[:ma]
        # Combined cap: drop audio first, then extra images
        while (
            len(self.ref_paths)
            + len(self.ref_video_paths)
            + len(self.ref_audio_paths)
            > mt
        ):
            if self.ref_audio_paths:
                self.ref_audio_paths.pop()
            elif len(self.ref_paths) > 1:
                self.ref_paths.pop()
            elif self.ref_video_paths:
                self.ref_video_paths.pop()
            else:
                break

    def _make_omni_intent_insert(self, phrase: str):
        async def _click(_e: ft.ControlEvent) -> None:
            cur = (self.prompt.value or "").strip()
            if phrase.lower() in cur.lower():
                self.status.value = f"Already in prompt: {phrase}"
            else:
                self.prompt.value = (cur + (" " if cur else "") + phrase + ".").strip()
                self.status.value = f"Inserted: {phrase}"
            try:
                self.page.update()
            except Exception:
                pass

        return _click

    def _sync_omni_panel(self) -> None:
        """Show/hide MiniMax H3 omni multi-modal ref UI."""
        show = self._is_omni_model()
        try:
            self.omni_panel.visible = show
            self.omni_helper.visible = show
            self.omni_images_label.visible = show
            self.omni_videos_label.visible = show
            self.omni_audio_label.visible = show
            self.omni_images_chips.visible = show
            self.omni_videos_chips.visible = show
            self.omni_audio_chips.visible = show
            self.btn_omni_img.visible = show
            self.btn_omni_vid.visible = show
            self.btn_omni_aud.visible = show
            self.btn_omni_clear.visible = show
            self.omni_intent_row.visible = show
        except Exception:
            pass
        if not show:
            return
        self._trim_omni_refs()
        mi, mv, ma, _mt = self._omni_caps()
        ni, nv, na = (
            len(self.ref_paths),
            len(self.ref_video_paths),
            len(self.ref_audio_paths),
        )
        self.omni_images_label.value = f"Images {ni}/{mi}"
        self.omni_videos_label.value = f"Videos {nv}/{mv}"
        self.omni_audio_label.value = f"Audio {na}/{ma}"
        self.btn_omni_img.disabled = ni >= mi
        self.btn_omni_vid.disabled = nv >= mv
        self.btn_omni_aud.disabled = na >= ma

        def _chip_row(
            paths: list[str], prefix: str, remove_fn
        ) -> list[ft.Control]:
            chips: list[ft.Control] = []
            for i, path in enumerate(list(paths)):
                name = Path(path).name
                is_img = prefix == "Image"
                chips.append(
                    ft.Container(
                        content=ft.Row(
                            [
                                ft.Image(
                                    src=path if is_img and Path(path).is_file() else "",
                                    width=40,
                                    height=40,
                                    fit=ft.BoxFit.COVER,
                                    border_radius=4,
                                    visible=is_img and Path(path).is_file(),
                                )
                                if is_img
                                else ft.Icon(
                                    ft.Icons.MOVIE if prefix == "Video" else ft.Icons.AUDIO_FILE,
                                    size=28,
                                    color=TEXT_MUTED,
                                ),
                                ft.Text(
                                    f"{prefix} {i + 1} · {name}",
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
                                    tooltip=f"Remove {prefix} {i + 1}",
                                    on_click=remove_fn(i),
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
            return chips

        self.omni_images_chips.controls = _chip_row(
            self.ref_paths, "Image", self._make_remove_omni_image
        )
        self.omni_videos_chips.controls = _chip_row(
            self.ref_video_paths, "Video", self._make_remove_omni_video
        )
        self.omni_audio_chips.controls = _chip_row(
            self.ref_audio_paths, "Audio", self._make_remove_omni_audio
        )

    def _make_remove_omni_image(self, index: int):
        async def _click(_e: ft.ControlEvent) -> None:
            if 0 <= index < len(self.ref_paths):
                removed = self.ref_paths.pop(index)
                self.status.value = f"Removed Image: {Path(removed).name}"
            self._sync_omni_panel()
            try:
                self.page.update()
            except Exception:
                pass

        return _click

    def _make_remove_omni_video(self, index: int):
        async def _click(_e: ft.ControlEvent) -> None:
            if 0 <= index < len(self.ref_video_paths):
                removed = self.ref_video_paths.pop(index)
                self.status.value = f"Removed Video: {Path(removed).name}"
            self._sync_omni_panel()
            try:
                self.page.update()
            except Exception:
                pass

        return _click

    def _make_remove_omni_audio(self, index: int):
        async def _click(_e: ft.ControlEvent) -> None:
            if 0 <= index < len(self.ref_audio_paths):
                removed = self.ref_audio_paths.pop(index)
                self.status.value = f"Removed Audio: {Path(removed).name}"
            self._sync_omni_panel()
            try:
                self.page.update()
            except Exception:
                pass

        return _click

    async def _pick_omni_images(self, e: ft.ControlEvent) -> None:
        mi, _, _, _ = self._omni_caps()
        room = mi - len(self.ref_paths)
        if room <= 0:
            self.status.value = f"Max {mi} reference images."
            self.page.update()
            return
        try:
            files = await pick_image(
                self.page,
                dialog_title="Omni reference stills (Image 1, Image 2…)",
                allow_multiple=True,
            )
        except Exception as exc:
            self.status.value = f"Picker error: {exc}"
            self.page.update()
            return
        for f in files or []:
            if not f.path or len(self.ref_paths) >= mi:
                break
            try:
                p = str(Path(f.path).resolve())
            except OSError:
                continue
            if p not in self.ref_paths:
                self.ref_paths.append(p)
        self._trim_omni_refs()
        self._sync_omni_panel()
        self.status.value = f"Omni images: {len(self.ref_paths)}"
        self.page.update()

    async def _pick_omni_videos(self, e: ft.ControlEvent) -> None:
        _, mv, _, _ = self._omni_caps()
        if len(self.ref_video_paths) >= mv:
            self.status.value = f"Max {mv} reference videos."
            self.page.update()
            return
        try:
            files = await pick_video(
                self.page,
                dialog_title="Omni motion ref (Video 1…) — 2–15s each, ≤15s total",
                allow_multiple=True,
            )
        except Exception as exc:
            self.status.value = f"Picker error: {exc}"
            self.page.update()
            return
        for f in files or []:
            if not f.path or len(self.ref_video_paths) >= mv:
                break
            try:
                p = str(Path(f.path).resolve())
            except OSError:
                continue
            if p not in self.ref_video_paths:
                self.ref_video_paths.append(p)
        self._trim_omni_refs()
        self._sync_omni_panel()
        self.status.value = f"Omni videos: {len(self.ref_video_paths)}"
        self.page.update()

    async def _pick_omni_audio(self, e: ft.ControlEvent) -> None:
        _, _, ma, _ = self._omni_caps()
        if len(self.ref_audio_paths) >= ma:
            self.status.value = f"Max {ma} reference audio clips."
            self.page.update()
            return
        try:
            files = await pick_audio(
                self.page,
                dialog_title="Omni audio ref (Audio 1…) — must accompany image/video",
                allow_multiple=True,
            )
        except Exception as exc:
            self.status.value = f"Picker error: {exc}"
            self.page.update()
            return
        for f in files or []:
            if not f.path or len(self.ref_audio_paths) >= ma:
                break
            try:
                p = str(Path(f.path).resolve())
            except OSError:
                continue
            if p not in self.ref_audio_paths:
                self.ref_audio_paths.append(p)
        self._trim_omni_refs()
        self._sync_omni_panel()
        self.status.value = f"Omni audio: {len(self.ref_audio_paths)}"
        self.page.update()

    async def _clear_omni_refs(self, e: ft.ControlEvent) -> None:
        self.ref_paths = []
        self.ref_video_paths = []
        self.ref_audio_paths = []
        self._sync_omni_panel()
        self.refs_label.value = "No reference pack"
        self.status.value = "Cleared omni references."
        self.page.update()

    def _apply_mode_visibility(self) -> None:
        is_t2i = self._mode == "text_to_image"
        is_i2i = self._mode == "image_to_image"
        is_i2v = self._mode == "image_to_video"
        is_bridge = self._mode == "bridge"
        is_extend = self._mode == "extend"
        is_omni = self._is_omni_model()
        still = is_still_mode(self._mode)
        show_start = (is_i2v or is_bridge or is_i2i) and not is_omni and not is_extend
        show_end = (
            (is_bridge or (is_i2v and self._supports_end_frame()))
            and not is_omni
            and not is_extend
        )
        # Source / start still picker
        self.btn_start.visible = show_start
        self.btn_end.visible = show_end
        try:
            self.extend_col.visible = is_extend
            if is_extend and self.extend_path:
                self.extend_label.value = f"Source: {Path(self.extend_path).name}"
            elif is_extend:
                self.extend_label.value = "No source clip (required)"
        except Exception:
            pass
        try:
            if is_i2i:
                self.btn_start.content = "Source still"
                self.start_ph.content = ft.Text(
                    "Source still", size=FONT_SM, color=TEXT_MUTED
                )
            else:
                self.btn_start.content = "Start frame"
                self.start_ph.content = ft.Text(
                    "Start still", size=FONT_SM, color=TEXT_MUTED
                )
        except Exception:
            pass
        self.start_ph.visible = show_start and not self.start_path
        self.end_ph.visible = show_end and not self.end_path
        # Refs / I2I multi-ref panel (tight; no voids)
        try:
            self._sync_i2i_refs_panel()
        except Exception:
            pass
        try:
            self._sync_omni_panel()
        except Exception:
            pass
        # Hide generic video ref pack row when omni panel owns refs
        try:
            if is_omni or is_extend:
                self.refs_actions_row.visible = False
                self.refs_hint.visible = False
                self.refs_chips.visible = False
        except Exception:
            pass
        # Previously used + From Resolve stills for I2I (and I2V/bridge start) + omni
        try:
            show_src_strips = is_i2i or is_i2v or is_bridge or is_omni or is_extend
            self.prev_strip.root.visible = show_src_strips
            self.resolve_strip.root.visible = show_src_strips
            if show_src_strips:
                self.prev_strip.refresh()
                self.resolve_strip.refresh()
        except Exception:
            pass
        # Still vs video helpers (still modes never inject camera motion language)
        self._sync_helper_controls_for_mode(is_still=still)
        try:
            self.start_preview.visible = bool(self.start_path) and show_start
            self.end_preview.visible = bool(self.end_path) and show_end
        except Exception:
            pass

    async def _pick_extend_video(self, e: ft.ControlEvent) -> None:
        try:
            files = await pick_video(self.page, dialog_title="Source clip to extend")
        except Exception as exc:
            self.status.value = f"Picker error: {exc}"
            self.page.update()
            return
        if not files or not files[0].path:
            return
        self.extend_path = str(Path(files[0].path).resolve())
        self.extend_label.value = f"Source: {Path(self.extend_path).name}"
        self.status.value = f"Extend source: {Path(self.extend_path).name}"
        self.page.update()

    def _sync_helper_controls_for_mode(self, *, is_still: bool = False, is_t2i: bool = False) -> None:
        """
        Still modes (T2I / I2I): framing / lens look / lighting / still styles — no motion.
        Video modes: shot type / lens / motion / video styles.
        Every helper list starts with (None) so dimensions can be silenced.
        """
        use_still = is_still or is_t2i
        try:
            if use_still:
                self.helpers_title.value = "Still photography helpers (None = skip)"
                # Framing replaces video shot types (no push-in / orbit / pan)
                self.shot_dd.label = "Framing / composition"
                opts = with_none(STILL_FRAMINGS)
                self.shot_dd.options = dropdown_options(opts)
                if _dd(self.shot_dd) not in opts:
                    self.shot_dd.value = STILL_FRAMINGS[0]
                self.lens_dd.label = "Lens look"
                lopts = with_none(STILL_LENS_LOOKS)
                self.lens_dd.options = dropdown_options(lopts)
                if _dd(self.lens_dd) not in lopts:
                    self.lens_dd.value = STILL_LENS_LOOKS[1]
                self.motion_dd.visible = False
                self.lighting_dd.visible = True
                light_opts = with_none(STILL_LIGHTING)
                self.lighting_dd.options = dropdown_options(light_opts)
                if _dd(self.lighting_dd) not in light_opts:
                    self.lighting_dd.value = STILL_LIGHTING[0]
                sopts = with_none(list(STILL_STYLE_PRESETS.keys()))
                self.style_dd.options = dropdown_options(sopts)
                if _dd(self.style_dd) not in sopts:
                    self.style_dd.value = "Clean modern day"
            else:
                self.helpers_title.value = "Camera / shot helpers (None = skip)"
                self.shot_dd.label = "Shot type"
                opts = with_none(SHOT_TYPES)
                self.shot_dd.options = dropdown_options(opts)
                if _dd(self.shot_dd) not in opts:
                    self.shot_dd.value = SHOT_TYPES[1]
                self.lens_dd.label = "Lens feel"
                lopts = with_none(LENS_FEELS)
                self.lens_dd.options = dropdown_options(lopts)
                if _dd(self.lens_dd) not in lopts:
                    self.lens_dd.value = LENS_FEELS[1]
                self.motion_dd.visible = True
                mopts = with_none(MOTIONS)
                self.motion_dd.options = dropdown_options(mopts)
                if _dd(self.motion_dd) not in mopts:
                    self.motion_dd.value = MOTIONS[3]
                self.lighting_dd.visible = False
                sopts = with_none(list(STYLE_PRESETS.keys()))
                self.style_dd.options = dropdown_options(sopts)
                if _dd(self.style_dd) not in sopts:
                    self.style_dd.value = "Clean modern day"
        except Exception:
            pass

    async def _on_model(self, e: ft.ControlEvent) -> None:
        self._sync_model_ui()
        self._apply_mode_visibility()
        try:
            self.page.update()
        except Exception:
            pass

    # ----- prompt helpers -----

    async def _on_style_preset(self, e: ft.ControlEvent) -> None:
        await self._rebuild_prompt(e)

    def _active_subject_notes(self) -> str | None:
        name = _dd(self.subject_dd)
        if not name or is_helper_none(name) or name == "(none)":
            return None
        s = find_subject(name, self.state.output_dir)
        if s:
            return s.notes or s.name
        return None

    def _helper_snapshot_for_enhance(self) -> dict[str, Any]:
        """Only non-None helpers (+ optional creative direction) for Enhance."""
        snap: dict[str, Any] = {
            "workspace": "creative_vision",
            "mode": self._mode,
        }
        direction = (self.creative_direction.value or "").strip()
        if is_still_mode(self._mode):
            for key, val in (
                ("framing", _dd(self.shot_dd)),
                ("lens_look", _dd(self.lens_dd)),
                ("lighting", _dd(self.lighting_dd)),
                ("style", _dd(self.style_dd)),
            ):
                a = active_helper(val)
                if a:
                    snap[key] = a
            if self._mode == "image_to_image":
                n_refs = len(
                    [p for p in self.ref_paths if p and Path(p).is_file()]
                )
                cap = self._i2i_extra_ref_cap()
                if n_refs > 0 and cap > 0:
                    snap["guidance"] = (
                        "Rewrite for a multi-reference image edit (image-to-image). "
                        "Image 1 is the primary still to edit. Additional images are "
                        "references (identity, material, furniture, sky, style). "
                        "In the optimized_prompt, name how each reference should guide "
                        "the edit (e.g. 'preserve identity from reference 1', "
                        "'match material/finish from reference 2') without inventing "
                        "API parameters — only natural language. "
                        "Preserve camera, framing, and architecture unless the edit "
                        "requires change. Still photography language only from helpers "
                        "that are set. No invented camera motion. Locked frame."
                    )
                    snap["reference_still_count"] = n_refs
                    snap["reference_roles_hint"] = (
                        "refs after primary: identity / material / product / sky / look"
                    )
                else:
                    snap["guidance"] = (
                        "Rewrite for a single-image edit (image-to-image). "
                        "Preserve camera, framing, architecture, and identity unless the "
                        "edit requires change. Use still photography language only from "
                        "helpers that are set. Do NOT invent camera motion "
                        "(no push-in, pan, tilt, orbit, tracking) unless the user prompt "
                        "or creative_direction already asks for it. Locked frame. "
                        "Vision is on the source still — describe the creative change clearly."
                    )
                snap["has_source_still"] = bool(
                    self.start_path and Path(self.start_path).is_file()
                )
            else:
                snap["guidance"] = (
                    "Rewrite for a single still photograph (text-to-image). "
                    "Use still photography language only from the helpers that are set "
                    "(skip any missing dimensions). Do NOT invent camera motion "
                    "(no push-in, pan, tilt, orbit, tracking) unless the user prompt "
                    "or creative_direction already asks for it. Locked frame."
                )
        else:
            for key, val in (
                ("shot_type", _dd(self.shot_dd)),
                ("lens", _dd(self.lens_dd)),
                ("motion", _dd(self.motion_dd)),
                ("style", _dd(self.style_dd)),
            ):
                a = active_helper(val)
                if a:
                    snap[key] = a
            try:
                spec = self._current_spec()
            except Exception:
                spec = None
            # FLUX 3 Video — crash course (central enhance_prompt also injects full brief)
            try:
                from media_studio.flux3_draft import is_flux3_video_model_choice

                model_lab = _dd(self.model_dd) or (
                    getattr(spec, "label", None) or getattr(spec, "key", "") or ""
                )
                if is_flux3_video_model_choice(model_lab) or (
                    spec and "flux-3" in (getattr(spec, "endpoint", "") or "")
                ):
                    snap["model_prompt_brief"] = "flux3_video"
                    snap["modality"] = self._mode
                    snap["vision_mode"] = self._mode
                    snap["has_start_still"] = bool(
                        self.start_path and Path(self.start_path).is_file()
                    )
                    snap["has_end_still"] = bool(
                        self.end_path and Path(self.end_path).is_file()
                    )
                    snap["has_source_video"] = bool(
                        getattr(self, "extend_path", None)
                        and Path(self.extend_path).is_file()  # type: ignore[arg-type]
                    )
                    snap["draft_first"] = bool(
                        getattr(self, "draft_first", None)
                        and self.draft_first.visible
                        and self.draft_first.value
                    )
                    # Skip H3/Veo generic guidance — services inject FLUX 3 brief
                    if direction:
                        snap["creative_direction"] = direction
                    sub = self._active_subject_notes()
                    if sub:
                        snap["subject_notes"] = sub
                    return snap
            except Exception:
                pass
            is_omni = bool(spec and getattr(spec, "omni_reference", False))
            n_img = len([p for p in self.ref_paths if p and Path(p).is_file()])
            n_vid = len(
                [p for p in self.ref_video_paths if p and Path(p).is_file()]
            )
            n_aud = len(
                [p for p in self.ref_audio_paths if p and Path(p).is_file()]
            )
            if is_omni and (n_img or n_vid or n_aud):
                snap["guidance"] = (
                    "Rewrite for MiniMax H3 omni reference-to-video. "
                    "Attached assets must be cited by modality and order: "
                    "Image 1, Image 2, … Video 1, … Audio 1, … "
                    f"(currently {n_img} image(s), {n_vid} video(s), {n_aud} audio). "
                    "Describe how each plate should guide the shot "
                    "(e.g. 'Image 1 = subject lock', 'Video 1 = camera path only', "
                    "'Audio 1 = timed bed'). Do NOT invent API parameters or unsupported "
                    "flags. Use only helper dimensions that are set. "
                    "Native stereo is always on — do not add generate_audio toggles."
                )
                snap["reference_image_count"] = n_img
                snap["reference_video_count"] = n_vid
                snap["reference_audio_count"] = n_aud
                snap["citation_style"] = "Image N / Video N / Audio N"
            elif (
                self._mode == "image_to_video"
                and spec
                and getattr(spec, "supports_end_frame", False)
                and self.end_path
                and Path(self.end_path).is_file()
            ):
                snap["guidance"] = (
                    "Rewrite for MiniMax H3 (or Hailuo) first→last image-to-video. "
                    "Start still is the first frame; end still is the last frame. "
                    "Describe the transition (day→night, porch→interior, etc.) while "
                    "keeping architecture consistent. No invented API params. "
                    "Native stereo is always on H3 output."
                )
            else:
                snap["guidance"] = (
                    "Rewrite for cinematic video generation. "
                    "Use only the helper dimensions that are set (ignore None). "
                    "For bridges: keep architecture consistent between start and end frames. "
                    "Subject refs are consistency help, not perfect identity lock."
                )
            if spec and getattr(spec, "native_stereo_audio", False):
                snap["native_stereo_audio"] = True
        if direction:
            snap["creative_direction"] = direction
            snap["creative_direction_note"] = (
                "creative_direction is the user's intent for Enhance only — "
                "combine it with non-None helpers and the current prompt, then write "
                "one model-ready prompt. Do not leave creative_direction as a separate "
                "section in the output; fold intent into the final prompt language."
            )
        sub = self._active_subject_notes()
        if sub:
            snap["subject_notes"] = sub
        return snap

    def _compiled_helpers(self) -> str:
        style_key = _dd(self.style_dd)
        sub = self._active_subject_notes()
        if is_still_mode(self._mode):
            # Still-only: never inject camera motion language; skip (None) helpers
            base = ""
            if self._mode == "image_to_image":
                base = (
                    "Edit only what the prompt asks for. Keep camera, framing, "
                    "architecture, and identity consistent unless the edit requires change."
                )
            return compile_still_prompt(
                base_prompt=base,
                framing=active_helper(_dd(self.shot_dd)),
                lens_look=active_helper(_dd(self.lens_dd)),
                lighting=active_helper(_dd(self.lighting_dd)),
                style_preset=active_helper(style_key),
                subject_notes=sub,
            )
        return compile_vision_prompt(
            base_prompt="",
            shot_type=active_helper(_dd(self.shot_dd)),
            lens=active_helper(_dd(self.lens_dd)),
            motion=active_helper(_dd(self.motion_dd)),
            style_preset=active_helper(style_key),
            bridge=(self._mode == "bridge"),
            subject_notes=sub,
        )

    def _prompt_looks_stock(self, text: str) -> bool:
        """True when the field is empty or still matches a pure helper compile."""
        cur = (text or "").strip()
        if not cur:
            return True
        stock = self._compiled_helpers().strip()
        if cur == stock:
            return True
        low = cur.lower()
        if is_still_mode(self._mode):
            if "still photography —" in low and len(cur) < 500:
                return True
            if "single still image, locked frame" in low and len(cur) < 500:
                return True
            if "edit only what the prompt asks" in low and len(cur) < 700:
                return True
            return False
        # Soft stock: mostly camera helper language without freeform body
        if low.startswith("bridge the start frame") and len(cur) < 280:
            return True
        if "camera —" in low and "shot:" in low and len(cur) < 400:
            return True
        return False

    async def _rebuild_prompt(self, e: ft.ControlEvent | None = None) -> None:
        """
        Rebuild from mode-appropriate helpers (still vs video).

        - Helper dropdowns: only rewrite when the prompt still looks stock
          (never clobber freeform).
        - Rebuild button + Replace: full overwrite.
        - Rebuild button + Append: prepend helpers to current text.
        - T2I rebuild never adds push-in / pan / motion language.
        """
        compiled = self._compiled_helpers()
        mode = (_dd(self.rebuild_mode) or "Replace").strip().lower()
        cur = (self.prompt.value or "").strip()
        from_button = False
        try:
            from_button = e is not None and getattr(e, "control", None) is self.btn_rebuild
        except Exception:
            from_button = False

        if from_button:
            if mode.startswith("append"):
                if not cur:
                    self.prompt.value = compiled
                elif compiled and compiled.strip() not in cur:
                    self.prompt.value = f"{compiled}\n\n{cur}"
            else:
                self.prompt.value = compiled
        else:
            # Dropdown / style change — soft only
            if self._prompt_looks_stock(cur):
                self.prompt.value = compiled
        try:
            self.page.update()
        except Exception:
            pass

    async def _on_enhance(self, e: ft.ControlEvent) -> None:
        def _extra() -> dict[str, Any]:
            return self._helper_snapshot_for_enhance()

        # Multi-image: enhance uses primary image; pass start/source or first ref
        # T2I: no source required; I2I: vision on source still + optional refs
        img = None
        if self._mode != "text_to_image":
            img = self.start_path
            if not img and self.ref_paths:
                img = self.ref_paths[0]
            if not img and self.end_path:
                img = self.end_path

        def _extra_imgs() -> list[str] | None:
            if self._mode != "image_to_image":
                return None
            if self._i2i_extra_ref_cap() <= 0:
                return None
            out = [
                p
                for p in self.ref_paths
                if p and Path(p).is_file() and p != self.start_path
            ]
            return out[: self._i2i_extra_ref_cap()] or None

        await run_prompt_enhance(
            page=self.page,
            state=self.state,
            prompt_field=self.prompt,
            get_model=lambda: _dd(self.model_dd),
            get_image=lambda: img,
            get_scenario=lambda: "creative_vision",
            get_extra_images=_extra_imgs,
            get_extra_context=_extra,
            status_ctrl=self.status,
            job_progress=self.job_progress,
            enhance_btn=self.btn_enhance,
            busy_controls=[self.btn_generate],
            context_label="vision prompt",
            # Allow Enhance from creative direction alone (optional field + helpers)
            allow_empty_with_context=True,
            busy_scope="vision",
        )
        self.apply_key_gates()
        try:
            self.page.update()
        except Exception:
            pass

    # ----- pickers -----

    def _job_status(self, base: str, *, job_name: str | None = None) -> str:
        name = (job_name or "").strip()
        return f"{base} · {name}" if name else base

    def receive_start_frame(
        self,
        path: str,
        *,
        status: str | None = None,
        job_name: str | None = None,
    ) -> bool:
        """Load a still as bridge/I2V start frame (does not wipe prompt or preset)."""
        try:
            p = Path(path)
            if not p.is_file():
                self.status.value = f"Start frame missing: {path}"
                return False
            resolved = str(p.resolve())
        except OSError as exc:
            self.status.value = f"Start frame error: {exc}"
            return False
        self.start_path = resolved
        self.start_preview.src = resolved
        self.start_preview.visible = True
        self.start_ph.visible = False
        # Prefer bridge when end already set; else I2V from text-only modes.
        # Stay in Image→Image when that mode is active (source still).
        try:
            if self._mode == "image_to_image":
                pass
            elif self.end_path and Path(self.end_path).is_file():
                if self._mode != "bridge":
                    self._on_mode("bridge")
            elif self._mode in ("text_to_video", "text_to_image"):
                self._on_mode("image_to_video")
        except Exception:
            pass
        role = "Source still" if self._mode == "image_to_image" else "Start frame"
        self.status.value = status or self._job_status(
            f"{role}: {Path(resolved).name}", job_name=job_name
        )
        try:
            self.page.update()
        except Exception:
            pass
        return True

    def receive_end_frame(
        self,
        path: str,
        *,
        status: str | None = None,
        job_name: str | None = None,
    ) -> bool:
        """Load a still as bridge end frame (e.g. from T2I / Frame Editor)."""
        try:
            p = Path(path)
            if not p.is_file():
                self.status.value = f"End frame missing: {path}"
                return False
            resolved = str(p.resolve())
        except OSError as exc:
            self.status.value = f"End frame error: {exc}"
            return False
        self.end_path = resolved
        self.end_preview.src = resolved
        self.end_preview.visible = True
        self.end_ph.visible = False
        try:
            if self._mode != "bridge":
                self._on_mode("bridge")
        except Exception:
            pass
        self.status.value = status or self._job_status(
            f"End frame: {Path(resolved).name}", job_name=job_name
        )
        try:
            self.page.update()
        except Exception:
            pass
        return True

    def receive_i2v_source(
        self,
        path: str,
        *,
        status: str | None = None,
        job_name: str | None = None,
    ) -> bool:
        """
        Load primary still for Image → Video. Forces I2V mode; does not clear
        end frame (user can still switch to bridge later).
        """
        try:
            p = Path(path)
            if not p.is_file():
                self.status.value = f"I2V source missing: {path}"
                return False
            resolved = str(p.resolve())
        except OSError as exc:
            self.status.value = f"I2V source error: {exc}"
            return False
        self.start_path = resolved
        self.start_preview.src = resolved
        self.start_preview.visible = True
        self.start_ph.visible = False
        try:
            if self._mode != "image_to_video":
                self._on_mode("image_to_video")
        except Exception:
            pass
        self.status.value = status or self._job_status(
            f"I2V source: {Path(resolved).name}", job_name=job_name
        )
        try:
            self.page.update()
        except Exception:
            pass
        return True

    def receive_i2i_source(
        self,
        path: str,
        *,
        status: str | None = None,
        job_name: str | None = None,
    ) -> bool:
        """
        Load source still for Image → Image creative edit (Aleph plate round-trip).
        Forces I2I mode. Does not wipe prompt or other keyframes elsewhere.
        """
        try:
            p = Path(path)
            if not p.is_file():
                self.status.value = f"I2I source missing: {path}"
                return False
            resolved = str(p.resolve())
        except OSError as exc:
            self.status.value = f"I2I source error: {exc}"
            return False
        # Switch mode first so UI labels update, then set still
        try:
            if self._mode != "image_to_image":
                self._on_mode("image_to_image")
        except Exception:
            pass
        self.start_path = resolved
        self.start_preview.src = resolved
        self.start_preview.visible = True
        self.start_ph.visible = False
        try:
            self.prev_strip.record_and_refresh(resolved)
        except Exception:
            pass
        self.status.value = status or self._job_status(
            f"I2I source: {Path(resolved).name}", job_name=job_name
        )
        try:
            self._sync_i2i_refs_panel()
        except Exception:
            pass
        try:
            self.page.update()
        except Exception:
            pass
        return True

    def receive_i2i_ref(
        self,
        path: str,
        *,
        status: str | None = None,
        job_name: str | None = None,
    ) -> bool:
        """
        Add a reference still for Image → Image multi-ref.
        Forces I2I mode. Caps at model max (≤3 extras).
        """
        try:
            p = Path(path)
            if not p.is_file():
                self.status.value = f"I2I ref missing: {path}"
                return False
            resolved = str(p.resolve())
        except OSError as exc:
            self.status.value = f"I2I ref error: {exc}"
            return False
        try:
            if self._mode != "image_to_image":
                self._on_mode("image_to_image")
        except Exception:
            pass
        cap = self._i2i_extra_ref_cap()
        if cap <= 0:
            self.status.value = (
                "Current model is single-image only — pick a multi-ref edit model "
                "to attach reference stills."
            )
            try:
                self.page.update()
            except Exception:
                pass
            return False
        if self.start_path and resolved == str(Path(self.start_path).resolve()):
            self.status.value = "That still is already the primary source."
            try:
                self.page.update()
            except Exception:
                pass
            return False
        if resolved in self.ref_paths:
            self.status.value = f"Already a ref: {Path(resolved).name}"
            try:
                self.page.update()
            except Exception:
                pass
            return True
        if len(self.ref_paths) >= cap:
            self.status.value = f"Max {cap} reference still(s) for this model."
            try:
                self.page.update()
            except Exception:
                pass
            return False
        self.ref_paths.append(resolved)
        try:
            self.prev_strip.record_and_refresh(resolved)
        except Exception:
            pass
        self._sync_i2i_refs_panel()
        self.status.value = status or self._job_status(
            f"I2I ref {len(self.ref_paths)}: {Path(resolved).name}",
            job_name=job_name,
        )
        try:
            self.page.update()
        except Exception:
            pass
        return True

    def receive_video(
        self,
        path: str,
        *,
        status: str | None = None,
        job_name: str | None = None,
    ) -> bool:
        """
        Receive a video from Send-to.

        Extend mode: set as source clip.
        Omni (MiniMax H3): attach as Video N motion plate.
        Otherwise: surface status (Studio Video / Tools for full clip workflows).
        """
        try:
            p = Path(path)
            if not p.is_file():
                self.status.value = f"Video missing: {path}"
                return False
            resolved = str(p.resolve())
            name = p.name
        except OSError as exc:
            self.status.value = f"Video error: {exc}"
            return False
        # Prefer Extend when already in extend mode or model is an extend model
        try:
            lab = (_dd(self.model_dd) or "").lower()
            if self._mode == "extend" or "extend" in lab:
                if self._mode != "extend":
                    self._on_mode("extend")
                self.extend_path = resolved
                self.extend_label.value = f"Source: {name}"
                self.extend_col.visible = True
                self.status.value = status or f"Extend source: {name}"
                try:
                    self.page.update()
                except Exception:
                    pass
                return True
        except Exception:
            pass
        if self._is_omni_model() or (
            self._mode == "text_to_video"
            and "omni" in (( _dd(self.model_dd) or "").lower())
        ):
            # Prefer switching to Omni model if available in T2V list
            try:
                if not self._is_omni_model() and self._mode == "text_to_video":
                    labels = vision_labels("text_to_video")
                    for lab in labels:
                        if "omni" in lab.lower() and "h3" in lab.lower():
                            self.model_dd.value = lab
                            self._sync_model_ui()
                            break
            except Exception:
                pass
            _, mv, _, _ = self._omni_caps()
            if resolved not in self.ref_video_paths and len(self.ref_video_paths) < mv:
                self.ref_video_paths.append(resolved)
            self._sync_omni_panel()
            self.status.value = status or self._job_status(
                f"Omni Video {len(self.ref_video_paths)}: {name}",
                job_name=job_name,
            )
            try:
                self.page.update()
            except Exception:
                pass
            return True
        base = (
            f"Received video {name} — use Send to Studio Video or Tools for "
            "clip workflows; or pick MiniMax H3 · Omni reference for motion plates."
        )
        self.status.value = status or self._job_status(base, job_name=job_name)
        try:
            self.page.update()
        except Exception:
            pass
        return True

    async def _pick_start(self, e: ft.ControlEvent) -> None:
        title = (
            "Source still (Image → Image)"
            if self._mode == "image_to_image"
            else "Start frame / I2V still"
        )
        try:
            files = await pick_image(self.page, dialog_title=title)
        except Exception as exc:
            self.status.value = f"Picker error: {exc}"
            self.page.update()
            return
        if not files or not files[0].path:
            return
        if self._mode == "image_to_image":
            self.receive_i2i_source(files[0].path)
        else:
            self.receive_start_frame(files[0].path)
        self.page.update()

    def _on_character_picked(self, path: str, choice) -> None:
        """Character picker → fill source / start still (Front preferred)."""
        label = getattr(choice, "label", None) or Path(path).name
        status = f"Character: {label}"
        if self._mode == "image_to_image":
            ok = self.receive_i2i_source(path, status=status)
        else:
            ok = self.receive_start_frame(path, status=status)
        if ok:
            try:
                self.page.update()
            except Exception:
                pass

    def _on_character_picker_clear(self) -> None:
        # Unlink picker only — keep manual / strip stills
        pass

    def refresh_character_picker(self) -> None:
        try:
            self.char_picker.refresh()
        except Exception:
            pass

    async def _pick_end(self, e: ft.ControlEvent) -> None:
        try:
            files = await pick_image(self.page, dialog_title="End frame (bridge)")
        except Exception as exc:
            self.status.value = f"Picker error: {exc}"
            self.page.update()
            return
        if not files or not files[0].path:
            return
        self.end_path = str(Path(files[0].path).resolve())
        self.end_preview.src = self.end_path
        self.end_preview.visible = True
        self.end_ph.visible = False
        self.status.value = f"End: {Path(self.end_path).name}"
        self.page.update()

    async def _pick_refs(self, e: ft.ControlEvent) -> None:
        is_i2i = self._mode == "image_to_image"
        cap = self._i2i_extra_ref_cap() if is_i2i else 8
        if is_i2i and cap <= 0:
            self.status.value = (
                "This model is single-image only — switch to a multi-ref edit model "
                "to attach reference stills."
            )
            self.page.update()
            return
        try:
            files = await pick_image(
                self.page,
                dialog_title=(
                    "I2I reference stills (identity / material / furniture)"
                    if is_i2i
                    else "Reference pack stills"
                ),
                allow_multiple=True,
            )
        except Exception as exc:
            self.status.value = f"Picker error: {exc}"
            self.page.update()
            return
        if not files:
            return
        for f in files:
            if not f.path:
                continue
            try:
                p = str(Path(f.path).resolve())
            except OSError:
                continue
            if is_i2i and self.start_path and p == str(Path(self.start_path).resolve()):
                continue
            if p not in self.ref_paths:
                self.ref_paths.append(p)
            if is_i2i and len(self.ref_paths) >= cap:
                break
        if is_i2i:
            self._trim_i2i_refs()
            self._sync_i2i_refs_panel()
        else:
            self.ref_paths = self.ref_paths[:8]
            self.refs_label.value = f"{len(self.ref_paths)} ref still(s)"
        self.status.value = f"Reference stills: {len(self.ref_paths)}"
        self.page.update()

    async def _clear_refs(self, e: ft.ControlEvent) -> None:
        self.ref_paths = []
        if self._mode == "image_to_image":
            self._sync_i2i_refs_panel()
        else:
            self.refs_label.value = "No reference pack"
        self.page.update()

    # ----- subjects -----

    def _refresh_subject_dd(self, *, select: str | None = None) -> None:
        labels = subject_choice_labels(self.state.output_dir)
        self.subject_dd.options = dropdown_options(labels)
        self.subject_dd.value = select if select in labels else "(none)"

    async def _on_subject(self, e: ft.ControlEvent) -> None:
        name = _dd(self.subject_dd)
        if not name or name == "(none)":
            return
        sub = find_subject(name, self.state.output_dir)
        if not sub:
            return
        # Attach subject stills into ref pack (merge); I2I respects multi-ref cap
        cap = self._i2i_extra_ref_cap() if self._mode == "image_to_image" else 8
        for p in sub.existing_images():
            if cap and len(self.ref_paths) >= cap:
                break
            if p not in self.ref_paths:
                self.ref_paths.append(p)
        if self._mode == "image_to_image":
            self._trim_i2i_refs()
            self._sync_i2i_refs_panel()
        else:
            self.ref_paths = self.ref_paths[:8]
            self.refs_label.value = (
                f"{len(self.ref_paths)} ref still(s) (subject: {sub.name})"
            )
        if sub.notes:
            self.subject_notes.value = sub.notes
        self.status.value = (
            f"Using subject “{sub.name}” — {len(sub.existing_images())} refs "
            "(consistency help, not a perfect lock)."
        )
        try:
            self.page.update()
        except Exception:
            pass

    async def _save_subject(self, e: ft.ControlEvent) -> None:
        name = (self.subject_name.value or "").strip()
        if not name:
            self.status.value = "Enter a subject name."
            self.page.update()
            return
        paths = list(self.ref_paths)
        if self.start_path:
            paths = [self.start_path] + paths
        # de-dupe
        seen: set[str] = set()
        uniq: list[str] = []
        for p in paths:
            if p not in seen:
                seen.add(p)
                uniq.append(p)
        if len(uniq) < 1:
            self.status.value = "Add reference stills (or a start frame) before saving a subject."
            self.page.update()
            return
        try:
            sub = add_or_update_subject(
                name=name,
                image_paths=uniq[:8],
                notes=self.subject_notes.value or "",
                output_dir=self.state.output_dir,
            )
            self._refresh_subject_dd(select=sub.name)
            self.status.value = (
                f"Saved subject “{sub.name}” with {len(sub.image_paths)} still(s). "
                "Identity is consistency help — not a perfect lock."
            )
        except Exception as exc:
            self.status.value = f"Save subject failed: {exc}"
        self.page.update()

    async def _delete_subject(self, e: ft.ControlEvent) -> None:
        name = _dd(self.subject_dd)
        if not name or name == "(none)":
            return
        sub = find_subject(name, self.state.output_dir)
        if not sub:
            return
        delete_subject(sub.id, self.state.output_dir)
        self._refresh_subject_dd()
        self.status.value = f"Deleted subject “{name}”."
        self.page.update()

    # ----- presets -----

    def _refresh_preset_dd(self, *, select: str | None = None) -> None:
        labels = preset_choice_labels(self.state.output_dir)
        self.preset_dd.options = dropdown_options(labels)
        self.preset_dd.value = select if select in labels else "(none)"

    async def _on_load_preset(self, e: ft.ControlEvent) -> None:
        name = _dd(self.preset_dd)
        if not name or name == "(none)":
            return
        for p in load_presets(self.state.output_dir):
            if p.name == name:
                self._apply_preset(p)
                break
        try:
            self.page.update()
        except Exception:
            pass

    def _apply_preset(self, p: VisionPreset) -> None:
        if p.mode in (
            "text_to_image",
            "image_to_image",
            "text_to_video",
            "image_to_video",
            "bridge",
            "extend",
        ):
            self._mode = p.mode  # type: ignore[assignment]
            try:
                self._mode_nav.set_selected(p.mode, notify=False)
            except Exception:
                pass
            labels = vision_labels(self._mode)
            self.model_dd.options = dropdown_options(labels)
            if p.model_label and p.model_label in labels:
                self.model_dd.value = p.model_label
            elif labels:
                self.model_dd.value = labels[0]
        if p.shot_type:
            self.shot_dd.value = p.shot_type
        if p.lens:
            self.lens_dd.value = p.lens
        if p.motion:
            self.motion_dd.value = p.motion
        if p.style_preset:
            if is_still_mode(self._mode) and p.style_preset in STILL_STYLE_PRESETS:
                self.style_dd.value = p.style_preset
            elif p.style_preset in STYLE_PRESETS:
                self.style_dd.value = p.style_preset
        if p.prompt:
            self.prompt.value = p.prompt
        if p.duration:
            self.dur_dd.value = p.duration
        if p.aspect:
            self.aspect_dd.value = p.aspect
        if p.resolution:
            self.res_dd.value = p.resolution
        if p.ref_paths:
            self.ref_paths = [x for x in p.ref_paths if Path(x).is_file()][:8]
            self.refs_label.value = f"{len(self.ref_paths)} ref still(s) (from preset)"
        self._apply_mode_visibility()
        self._sync_model_ui()
        self.status.value = f"Loaded vision preset “{p.name}”."

    async def _save_preset(self, e: ft.ControlEvent) -> None:
        name = (self.preset_name.value or "").strip()
        if not name:
            self.status.value = "Enter a preset name."
            self.page.update()
            return
        sub_id = ""
        sn = _dd(self.subject_dd)
        if sn and sn != "(none)":
            s = find_subject(sn, self.state.output_dir)
            if s:
                sub_id = s.id
        preset = VisionPreset(
            id="",
            name=name,
            prompt=self.prompt.value or "",
            mode=self._mode,
            model_label=_dd(self.model_dd) or "",
            shot_type=_dd(self.shot_dd) or "",
            lens=_dd(self.lens_dd) or "",
            motion=_dd(self.motion_dd) or "",
            style_preset=_dd(self.style_dd) or "",
            duration=_dd(self.dur_dd) or "8s",
            aspect=_dd(self.aspect_dd) or "16:9",
            resolution=_dd(self.res_dd) or "720p",
            ref_paths=list(self.ref_paths),
            subject_id=sub_id,
        )
        add_vision_preset(preset, self.state.output_dir)
        self._refresh_preset_dd(select=name)
        self.status.value = f"Saved vision preset “{name}”."
        self.page.update()

    async def _delete_preset(self, e: ft.ControlEvent) -> None:
        name = _dd(self.preset_dd)
        if not name or name == "(none)":
            return
        for p in load_presets(self.state.output_dir):
            if p.name == name:
                delete_vision_preset(p.id, self.state.output_dir)
                break
        self._refresh_preset_dd()
        self.status.value = f"Deleted preset “{name}”."
        self.page.update()

    # ----- generate -----

    async def _run(self, e: ft.ControlEvent) -> None:
        if self.state.is_busy("vision"):
            return
        from media_studio.secrets_store import has_fal_key

        if not has_fal_key():
            self.status.value = "FAL API key required — open Settings (gear icon)."
            self.page.update()
            return

        prompt = (self.prompt.value or "").strip()
        if not prompt:
            self.status.value = (
                "Enter an image / edit prompt."
                if is_still_mode(self._mode)
                else "Enter a motion / shot prompt."
            )
            self.page.update()
            return

        if self._mode == "image_to_image" and not (
            self.start_path and Path(self.start_path).is_file()
        ):
            self.status.value = "Image→Image needs a source still."
            self.page.update()
            return
        if self._mode == "image_to_video" and not (
            self.start_path and Path(self.start_path).is_file()
        ):
            self.status.value = "Image→Video needs a start still."
            self.page.update()
            return
        if self._mode == "bridge":
            if not (
                self.start_path
                and Path(self.start_path).is_file()
                and self.end_path
                and Path(self.end_path).is_file()
            ):
                self.status.value = "Bridge needs both start and end stills."
                self.page.update()
                return
        if self._mode == "extend":
            if not (self.extend_path and Path(self.extend_path).is_file()):
                self.status.value = "Extend needs a source video clip."
                self.page.update()
                return

        # I2I: optional multi-ref extras; video: subject + ref pack
        refs = list(self.ref_paths)
        if self._mode == "image_to_image":
            self._trim_i2i_refs()
            refs = list(self.ref_paths)
        elif not is_still_mode(self._mode):
            sn = _dd(self.subject_dd)
            if sn and sn != "(none)":
                s = find_subject(sn, self.state.output_dir)
                if s:
                    for p in s.existing_images():
                        if p not in refs:
                            refs.append(p)

        # Reference-to-video / omni models need refs
        spec = self._current_spec()
        is_omni = bool(getattr(spec, "omni_reference", False))
        if is_omni:
            has_omni = bool(refs or self.ref_video_paths)
            if not has_omni:
                self.status.value = (
                    f"{spec.label} needs at least one still or motion clip "
                    "(Audio alone is not enough)."
                )
                self.page.update()
                return
            if self.ref_audio_paths and not refs and not self.ref_video_paths:
                self.status.value = (
                    "Reference audio must accompany an image or video reference."
                )
                self.page.update()
                return
        elif (
            self._mode == "text_to_video"
            and spec.max_refs > 0
            and not refs
        ):
            self.status.value = (
                f"{spec.label} needs a reference pack — add stills or pick a subject."
            )
            self.page.update()
            return

        # Optional cost guard (Settings — default off)
        try:
            from media_studio.flet_dialogs import confirm_cost_if_needed
            from media_studio.vision_registry import estimate_vision_cost

            audio = None
            if spec.supports_audio and not is_still_mode(self._mode):
                audio = bool(self.gen_audio.value)
            est = estimate_vision_cost(
                spec,
                duration_token=self._duration_token_for_cost(spec),
                resolution=_dd(self.res_dd) if getattr(self.res_dd, "visible", True) else (
                    spec.default_resolution or None
                ),
                aspect_ratio=_dd(self.aspect_dd),
                generate_audio=audio,
                num_images=self._num_images_for_cost(),
            )
            ok = await confirm_cost_if_needed(
                self.page,
                estimated_usd=est,
                job_label=f"Creative Vision · {spec.label}",
            )
            if not ok:
                self.status.value = "Generate cancelled (cost guard)."
                self.page.update()
                return
        except Exception:
            pass

        if not self.state.try_busy("vision"):
            return
        self.btn_generate.disabled = True
        try:
            self.player.clear()
        except Exception:
            pass
        try:
            self.result_image.src = ""
            self._result_frame.visible = False
            self._result_frame.expand = False
            self._result_frame.height = 280
        except Exception:
            pass
        self.send_host.visible = False
        self.cost_text.value = self._cost_label()
        still_job = is_still_mode(self._mode)
        self.job_progress.start(
            "Generating still…" if still_job else "Uploading…", self.page
        )
        self.status.value = (
            f"Running {spec.label}…"
            if still_job
            else f"Running {spec.label}… (can take several minutes)"
        )
        self.page.update()

        def on_progress(msg: str) -> None:
            self.job_progress.set_message(classify_progress(msg), self.page)

        strength_val = None
        if self._mode == "image_to_image" and getattr(spec, "supports_strength", False):
            try:
                strength_val = float(self.strength.value or 0.6)
            except (TypeError, ValueError):
                strength_val = 0.6

        try:
            # Record I2I source for Previously used
            if self._mode == "image_to_image" and self.start_path:
                try:
                    self.prev_strip.record_and_refresh(self.start_path)
                except Exception:
                    pass
            from media_studio.job_context import to_thread_with_job

            result = await to_thread_with_job(
                self.state,
                run_vision,
                mode=self._mode,
                prompt=prompt,
                model_label=_dd(self.model_dd),
                image_path=(
                    self.start_path
                    if self._mode in ("image_to_video", "image_to_image")
                    else None
                ),
                first_frame_path=self.start_path if self._mode == "bridge" else None,
                last_frame_path=(
                    self.end_path
                    if self._mode == "bridge"
                    else (self.end_path if self._mode == "image_to_video" else None)
                ),
                source_video_path=(
                    self.extend_path if self._mode == "extend" else None
                ),
                ref_paths=(
                    (refs or None)
                    if (
                        self._mode == "image_to_image"
                        or (not still_job and self._mode != "extend")
                    )
                    else None
                ),
                ref_video_paths=(
                    list(self.ref_video_paths)
                    if (not still_job and getattr(spec, "omni_reference", False))
                    else None
                ),
                ref_audio_paths=(
                    list(self.ref_audio_paths)
                    if (not still_job and getattr(spec, "omni_reference", False))
                    else None
                ),
                duration=None if still_job else _dd(self.dur_dd),
                aspect_ratio=_dd(self.aspect_dd),
                resolution=(
                    _dd(self.res_dd)
                    if still_job and getattr(self.res_dd, "visible", False)
                    else (None if still_job else _dd(self.res_dd))
                ),
                negative_prompt=self.negative.value,
                generate_audio=(
                    False
                    if still_job
                    else (
                        None
                        if getattr(spec, "native_stereo_audio", False)
                        else bool(self.gen_audio.value)
                    )
                ),
                strength=strength_val,
                num_images=self._num_images_for_cost(),
                draft=bool(
                    (not still_job)
                    and self.draft_first.visible
                    and self.draft_first.value
                ),
                output_dir=self.state.output_dir,
                on_progress=on_progress,
            )
            self.cost_text.value = result.cost_label or self._cost_label()
            paths = list(getattr(result, "paths", None) or [])
            if result.ok and result.path and not paths:
                paths = [result.path]
            if result.ok and paths:
                self._result_path = paths[-1]
                self._result_paths = paths
                done = result.status or "OK"
                if getattr(result, "is_draft", False):
                    done = f"Draft · {result.cost_label or done}"
                    cache = getattr(result, "draft_cache_url", None)
                    if cache:
                        self._draft_cache_url = cache
                        self.btn_enhance_full.visible = True
                        self.btn_enhance_full.disabled = False
                elif not getattr(result, "is_draft", False):
                    self._draft_cache_url = None
                    if self.draft_first.visible:
                        self.btn_enhance_full.disabled = True
                self.job_progress.finish_ok(done, self.page)
                self.status.value = done
                self._show_result(paths[-1])
                self._show_variants(paths)
                self._refresh_send_menu(paths[-1])
            else:
                err = result.status or "Failed."
                self.job_progress.finish_error(err, self.page)
                self.status.value = err
                self._result_paths = []
                try:
                    self.variant_host.visible = False
                except Exception:
                    pass
        except Exception as exc:
            self.job_progress.finish_error(f"Error: {exc}", self.page)
            self.status.value = f"Error: {exc}"
            traceback.print_exc()
        finally:
            self.state.clear_busy("vision")
            self.apply_key_gates()
            self.page.update()

    def _show_result(self, path: str) -> None:
        """Show still or video result in the right pane."""
        ext = Path(path).suffix.lower()
        is_img = ext in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
        try:
            self._right_col.expand = True
            self._right_col.tight = False
        except Exception:
            pass
        if is_img:
            try:
                self.player.clear()
            except Exception:
                pass
            try:
                self.player.control.visible = False
                self.player.control.expand = False
            except Exception:
                pass
            self.result_image.src = path
            self.result_image.fit = ft.BoxFit.CONTAIN
            self._result_frame.visible = True
            try:
                self._result_frame.expand = True
                self._result_frame.height = None  # type: ignore[assignment]
            except Exception:
                self._result_frame.height = 480
        else:
            self._result_frame.visible = False
            self.result_image.src = ""
            try:
                self.player.control.visible = True
                self.player.control.expand = True
                self.player.control.height = None  # type: ignore[assignment]
                if getattr(self.player, "_video", None) is not None:
                    self.player._video.fit = ft.BoxFit.CONTAIN
                    self.player._video.expand = True
            except Exception:
                pass
            self.player.set_result(path)
            try:
                self.variant_host.visible = False
            except Exception:
                pass

    def _show_variants(self, paths: list[str]) -> None:
        """Thumb strip for multi-variant T2I; click selects Send-to target."""
        if len(paths) <= 1:
            try:
                self.variant_host.visible = False
                self.variant_row.controls = []
            except Exception:
                pass
            return
        cells: list[ft.Control] = []
        for i, p in enumerate(paths):
            if not p or not Path(p).is_file():
                continue
            idx = i

            def make_click(path: str = p, ii: int = idx):
                async def _click(_e: ft.ControlEvent) -> None:
                    self._result_path = path
                    self._show_result(path)
                    self._refresh_send_menu(path)
                    self.status.value = (
                        f"Selected variant {ii + 1}/{len(paths)}: {Path(path).name}"
                    )
                    try:
                        self.page.update()
                    except Exception:
                        pass

                return _click

            cells.append(
                ft.Container(
                    content=ft.Image(
                        src=p,
                        width=72,
                        height=54,
                        fit=ft.BoxFit.COVER,
                        gapless_playback=True,
                    ),
                    width=76,
                    height=58,
                    border=ft.Border.all(1, BORDER),
                    border_radius=4,
                    clip_behavior=ft.ClipBehavior.HARD_EDGE,
                    on_click=make_click(),
                    ink=True,
                    tooltip=f"Variant {i + 1} — click to select for Send to ▾",
                )
            )
        self.variant_row.controls = cells
        self.variant_host.visible = bool(cells)

    async def _on_enhance_to_full(self, e: ft.ControlEvent) -> None:
        """FLUX 3 draft-enhance from stored draft_cache_url."""
        if self.state.is_busy("vision"):
            return
        cache = (self._draft_cache_url or "").strip()
        if not cache:
            self.status.value = "Enhance to full needs a draft first."
            self.page.update()
            return
        from media_studio.secrets_store import has_fal_key

        if not has_fal_key():
            self.status.value = "FAL API key required — open Settings."
            self.page.update()
            return
        if not self.state.try_busy("vision"):
            return
        self.btn_enhance_full.disabled = True
        self.btn_generate.disabled = True
        self.job_progress.start("Enhancing draft to full…", self.page)
        self.status.value = "FLUX 3 draft-enhance…"
        self.page.update()

        def on_progress(msg: str) -> None:
            self.job_progress.set_message(classify_progress(msg), self.page)

        try:
            from media_studio.flux3_draft import (
                estimate_full_cost_usd,
                run_draft_enhance,
            )
            from media_studio.job_context import to_thread_with_job
            from media_studio.vision_registry import duration_seconds

            spec = self._current_spec()
            dur = duration_seconds(self._duration_token_for_cost(spec))
            full_est = estimate_full_cost_usd(
                spec,
                duration_s=dur,
                resolution=_dd(self.res_dd) if self.res_dd.visible else None,
                generate_audio=bool(self.gen_audio.value)
                if self.gen_audio.visible
                else False,
            )
            result = await to_thread_with_job(
                self.state,
                run_draft_enhance,
                draft_cache_url=cache,
                output_dir=self.state.output_dir,
                prompt_hint=(self.prompt.value or "flux3")[:40],
                model_key=spec.key,
                on_progress=on_progress,
                duration_s=dur,
                full_cost_usd=full_est,
            )
            if result.ok and result.path:
                self._result_path = result.path
                self._draft_cache_url = None
                self.btn_enhance_full.disabled = True
                self.cost_text.value = result.cost_estimate or self._cost_label()
                done = result.status or "Enhance to full OK"
                self.job_progress.finish_ok(done, self.page)
                self.status.value = done
                self._show_result(result.path)
                self._refresh_send_menu(result.path)
            else:
                err = result.status or "Enhance failed."
                self.job_progress.finish_error(err, self.page)
                self.status.value = err
                self.btn_enhance_full.disabled = False
        except Exception as exc:
            from media_studio.errors import friendly_error

            err = friendly_error(exc, context="Enhance to full")
            self.job_progress.finish_error(err, self.page)
            self.status.value = err
            self.btn_enhance_full.disabled = False
        finally:
            self.state.clear_busy("vision")
            self.apply_key_gates()
            try:
                self.page.update()
            except Exception:
                pass

    def _refresh_send_menu(self, path: str) -> None:
        """Send-to matrix: stills get FE keyframe + Start/End/I2V + shared matrix."""
        from media_studio.flet_send_to import (
            build_send_menu_items,
            make_send_menu_button,
            send_to_frame_editor,
        )
        from media_studio.flet_theme import FONT_SM, TEXT

        def _st(msg: str) -> None:
            try:
                self.status.value = msg
                self.page.update()
            except Exception:
                pass

        def _leaf(label: str, handler) -> ft.MenuItemButton:
            return ft.MenuItemButton(
                content=ft.Text(label, size=FONT_SM, color=TEXT),
                on_click=handler,
                style=ft.ButtonStyle(color=TEXT),
            )

        ext = Path(path).suffix.lower()
        is_img = ext in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
        job_name = self._active_job_name()

        if is_img:
            items: list = []
            # Primary Aleph / motion handoffs after creative I2I or T2I
            items.append(
                _leaf(
                    "Frame Editor · keyframe",
                    send_to_frame_editor(
                        self.state,
                        path,
                        as_video=False,
                        job_name=job_name,
                        status_cb=_st,
                    ),
                )
            )
            items.append(
                _leaf("→ Start frame (this Vision tab)", self._apply_as_start(path))
            )
            items.append(
                _leaf("→ End frame (this Vision tab)", self._apply_as_end(path))
            )
            items.append(
                _leaf("→ I2V source (this Vision tab)", self._apply_as_i2v(path))
            )
            items.append(
                _leaf(
                    "→ Image → Image source (this Vision tab)",
                    self._apply_as_i2i(path),
                )
            )
            # Shared matrix (Studio, Director, Tools, Resolve, …) — skip vision + FE
            more = build_send_menu_items(
                self.state,
                image_path=path,
                status_cb=_st,
                include_vision=False,
                include_frame_editor=False,
            )
            if more:
                items.extend(more)
        else:
            items = build_send_menu_items(
                self.state,
                video_path=path,
                status_cb=_st,
            )

        btn = make_send_menu_button(
            items,
            tooltip="Send to Frame Editor, Vision slots, Studio, Director, Tools, or Resolve",
        )
        if btn is None:
            self.send_host.visible = False
            return
        self.send_host.content = btn
        self.send_host.visible = True

    def _active_job_name(self) -> str | None:
        """Optional label from preset name if the user set one (not auto-cleared)."""
        try:
            name = (self.preset_name.value or "").strip()
            return name or None
        except Exception:
            return None

    def _apply_as_start(self, path: str):
        async def _click(_e: ft.ControlEvent) -> None:
            self.receive_start_frame(
                path, status=f"Still → Start frame: {Path(path).name}"
            )
            if self.end_path and Path(self.end_path).is_file():
                try:
                    self._on_mode("bridge")
                except Exception:
                    pass
            try:
                self.page.update()
            except Exception:
                pass

        return _click

    def _apply_as_end(self, path: str):
        async def _click(_e: ft.ControlEvent) -> None:
            self.receive_end_frame(path, status=f"Still → End frame: {Path(path).name}")
            try:
                self.page.update()
            except Exception:
                pass

        return _click

    def _apply_as_i2v(self, path: str):
        async def _click(_e: ft.ControlEvent) -> None:
            self.receive_i2v_source(path, status=f"Still → I2V: {Path(path).name}")
            try:
                self.page.update()
            except Exception:
                pass

        return _click

    def _apply_as_i2i(self, path: str):
        async def _click(_e: ft.ControlEvent) -> None:
            self.receive_i2i_source(
                path, status=f"Still → I2I source: {Path(path).name}"
            )
            try:
                self.page.update()
            except Exception:
                pass

        return _click

    def _send_video_source(self, path: str):
        async def _click(_e: ft.ControlEvent) -> None:
            vv = getattr(self.state, "video_view", None)
            if vv is not None and hasattr(vv, "load_source_video"):
                vv.load_source_video(
                    path,
                    clip_name=Path(path).name,
                    status=f"Vision → Video: {Path(path).name}",
                    record=False,
                )
            switch = getattr(self.state, "switch_to_video", None)
            if switch:
                switch()
            self.status.value = f"Sent to Video: {Path(path).name}"
            try:
                self.page.update()
            except Exception:
                pass

        return _click

    def _send_tool(self, tool_id: str, path: str):
        async def _click(_e: ft.ControlEvent) -> None:
            tv = getattr(self.state, "tools_view", None)
            if tv is not None and hasattr(tv, "receive_media"):
                tv.receive_media(tool_id, path, as_video=True)
            switch = getattr(self.state, "switch_to_tools", None)
            if switch:
                switch(tool_id)
            self.status.value = f"Sent to {tool_id}: {Path(path).name}"

        return _click

    def _send_resolve(self, path: str):
        async def _click(_e: ft.ControlEvent) -> None:
            from media_studio.resolve_export import send_file_to_resolve

            try:
                result = await asyncio.to_thread(send_file_to_resolve, path)
                self.status.value = result.message if hasattr(result, "message") else str(result)
            except Exception as exc:
                self.status.value = f"Resolve: {exc}"
            try:
                self.page.update()
            except Exception:
                pass

        return _click
