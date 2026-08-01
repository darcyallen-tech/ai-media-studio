"""
Creative Vision tab — T2I / I2I / T2V / I2V / bridge shots.

Separate from Studio listing camera-lock flows. Expensive models; cost shown
before generate. Same export habits: Library, folder, Resolve, Send to ▾.
"""

from __future__ import annotations

import asyncio
import traceback
from pathlib import Path
from typing import TYPE_CHECKING, Any

import flet as ft

from media_studio.flet_enhance import make_enhance_button, run_prompt_enhance
from media_studio.flet_pickers import pick_image
from media_studio.flet_progress import JobProgress, classify_progress
from media_studio.flet_source_strip import PreviousSourcesStrip
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


def _cost_box(text: ft.Text) -> ft.Container:
    return ft.Container(
        content=text,
        bgcolor=PANEL_ELEVATED,
        border=ft.Border.all(1, BORDER),
        border_radius=6,
        padding=ft.Padding.symmetric(horizontal=10, vertical=6),
    )


class CreativeVisionView:
    """Top-level Creative Vision workspace."""

    def __init__(self, page: ft.Page, state: StudioState) -> None:
        self.page = page
        self.state = state
        self._mode: VisionMode = "text_to_video"
        self.start_path: str | None = None
        self.end_path: str | None = None
        self.ref_paths: list[str] = []
        self._result_path: str | None = None

        # Mode nav (T2I / I2I first for still-then-Aleph / bridge workflows)
        self._mode_nav = PillNav(
            [
                ("text_to_image", "Text → Image"),
                ("image_to_image", "Image → Image"),
                ("text_to_video", "Text → Video"),
                ("image_to_video", "Image → Video"),
                ("bridge", "Bridge / Connect"),
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
        self.cost_text = ft.Text(
            self._cost_label(),
            size=FONT_SM,
            color=TEXT,
            weight=ft.FontWeight.W_600,
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
        self.gen_audio = ft.Checkbox(
            label="Generate audio (when supported)",
            value=True,
            on_change=self._refresh_cost,
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
        # Still preview for Text→Image results
        self.result_image = ft.Image(
            src="",
            fit=ft.BoxFit.CONTAIN,
            height=320,
            visible=False,
            gapless_playback=True,
        )
        self.send_host = ft.Container(visible=False)

        self.state.on_keys_changed(self.apply_key_gates)
        self.apply_key_gates()
        self._apply_mode_visibility()
        self._sync_model_ui()

    # ----- layout -----

    def build(self) -> ft.Control:
        left = ft.Container(
            width=520,
            content=ft.Column(
                [
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
                    self.model_dd,
                    self.model_notes,
                    ft.Row([self.dur_dd, self.aspect_dd, self.res_dd], spacing=8),
                    self.strength_label,
                    self.strength,
                    self.gen_audio,
                    _cost_box(self.cost_text),
                    ft.Divider(height=1, color=BORDER),
                    self.helpers_title,
                    ft.Row([self.shot_dd, self.lens_dd], spacing=8),
                    ft.Row([self.motion_dd, self.lighting_dd, self.style_dd], spacing=8),
                    ft.Row([self.rebuild_mode, self.btn_rebuild], spacing=8),
                    self.prompt,
                    self.creative_direction,
                    self.creative_direction_hint,
                    self.negative,
                    ft.Row([self.btn_enhance, self.btn_generate], spacing=8),
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
                            ),
                            ft.Column(
                                [self.end_ph, self.end_preview, self.btn_end],
                                spacing=4,
                                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                        ],
                        spacing=16,
                    ),
                    ft.Row([self.btn_refs, self.btn_clear_refs, self.refs_label], spacing=8),
                    self.prev_strip.root,
                    ft.Divider(height=1, color=BORDER),
                    # Collapsed by default to reduce left-column density (Phase F)
                    ft.ExpansionTile(
                        title=ft.Text("Subject library", size=FONT_SM, color=TEXT, weight=ft.FontWeight.W_600),
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
                                    self.subject_dd,
                                    ft.Row([self.subject_name, self.subject_notes], spacing=8),
                                    ft.Row([self.btn_save_subject, self.btn_del_subject], spacing=8),
                                ],
                                spacing=8,
                                tight=True,
                            )
                        ],
                    ),
                    ft.ExpansionTile(
                        title=ft.Text("Vision presets", size=FONT_SM, color=TEXT, weight=ft.FontWeight.W_600),
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
                                    self.preset_dd,
                                    ft.Row(
                                        [self.preset_name, self.btn_save_preset, self.btn_del_preset],
                                        spacing=8,
                                    ),
                                ],
                                spacing=8,
                                tight=True,
                            )
                        ],
                    ),
                ],
                spacing=8,
                scroll=ft.ScrollMode.AUTO,
                expand=True,
            ),
            bgcolor=PANEL,
            border=ft.Border.all(1, BORDER),
            border_radius=8,
            padding=12,
        )

        right = panel(
            ft.Column(
                [
                    section_title("Result"),
                    ft.Text(
                        "Still preview or video playback. "
                        "T2I / I2I: Send to Frame Editor keyframe, Start / End, or I2V. "
                        "Show in folder · Send to Resolve · Send to ▾",
                        size=FONT_SM,
                        color=TEXT_MUTED,
                    ),
                    self.result_image,
                    self.player.control,
                    self.send_host,
                ],
                spacing=8,
                expand=True,
            ),
        )

        return ft.Row(
            [left, ft.Container(content=right, expand=True)],
            spacing=12,
            expand=True,
            vertical_alignment=ft.CrossAxisAlignment.START,
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

    def _cost_label(self) -> str:
        try:
            spec = self._current_spec()
            audio = None
            if spec.supports_audio and not is_still_mode(self._mode):
                audio = bool(self.gen_audio.value)
            return format_vision_cost(
                spec,
                duration_token=self._duration_token_for_cost(spec),
                resolution=_dd(self.res_dd) if self.res_dd.visible else (
                    spec.default_resolution or None
                ),
                aspect_ratio=_dd(self.aspect_dd),
                generate_audio=audio,
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
        """Previously used still → I2I source (or start when in video modes)."""
        if self._mode == "image_to_image":
            self.receive_i2i_source(path, status=f"Previous: {Path(path).name}")
        else:
            self.receive_start_frame(path, status=f"Previous: {Path(path).name}")

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
        still = is_still_mode(self._mode)
        is_i2i = self._mode == "image_to_image"
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
        self.gen_audio.visible = bool(spec.supports_audio) and not still
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
            else:
                self.prompt.label = "Motion / shot prompt (editable — Enhance rewrites)"
                self.btn_generate.content = "Generate vision"
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

    def _apply_mode_visibility(self) -> None:
        is_t2i = self._mode == "text_to_image"
        is_i2i = self._mode == "image_to_image"
        is_i2v = self._mode == "image_to_video"
        is_bridge = self._mode == "bridge"
        still = is_still_mode(self._mode)
        show_start = is_i2v or is_bridge or is_i2i
        show_end = is_bridge or (is_i2v and self._supports_end_frame())
        # Source / start still picker
        self.btn_start.visible = show_start
        self.btn_end.visible = show_end
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
        # Refs: hide for pure T2I / single-source I2I v1
        try:
            self.btn_refs.visible = not still
            self.btn_clear_refs.visible = not still
            self.refs_label.visible = not still
        except Exception:
            pass
        # Previously used stills for I2I (and I2V/bridge start)
        try:
            self.prev_strip.root.visible = is_i2i or is_i2v or is_bridge
            if self.prev_strip.root.visible:
                self.prev_strip.refresh()
        except Exception:
            pass
        # Still vs video helpers (still modes never inject camera motion language)
        self._sync_helper_controls_for_mode(is_still=still)
        try:
            self.start_preview.visible = bool(self.start_path) and show_start
            self.end_preview.visible = bool(self.end_path) and show_end
        except Exception:
            pass

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
            snap["guidance"] = (
                "Rewrite for cinematic video generation. "
                "Use only the helper dimensions that are set (ignore None). "
                "For bridges: keep architecture consistent between start and end frames. "
                "Subject refs are consistency help, not perfect identity lock."
            )
        direction = (self.creative_direction.value or "").strip()
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
        # T2I: no source required; I2I: vision on source still
        img = None
        if self._mode != "text_to_image":
            img = self.start_path
            if not img and self.ref_paths:
                img = self.ref_paths[0]
            if not img and self.end_path:
                img = self.end_path

        await run_prompt_enhance(
            page=self.page,
            state=self.state,
            prompt_field=self.prompt,
            get_model=lambda: _dd(self.model_dd),
            get_image=lambda: img,
            get_scenario=lambda: "creative_vision",
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
        Receive a video from Send-to. Vision is still-driven; surface the path
        in status (use Studio Video / Tools for full clip workflows).
        """
        try:
            p = Path(path)
            if not p.is_file():
                self.status.value = f"Video missing: {path}"
                return False
            name = p.name
        except OSError as exc:
            self.status.value = f"Video error: {exc}"
            return False
        base = (
            f"Received video {name} — use Send to Studio Video or Tools for "
            "clip workflows; Vision is primarily still → video."
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
        try:
            files = await pick_image(
                self.page,
                dialog_title="Reference pack stills",
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
            p = str(Path(f.path).resolve())
            if p not in self.ref_paths:
                self.ref_paths.append(p)
        self.ref_paths = self.ref_paths[:8]
        self.refs_label.value = f"{len(self.ref_paths)} ref still(s)"
        self.status.value = f"Reference pack: {len(self.ref_paths)} still(s)"
        self.page.update()

    async def _clear_refs(self, e: ft.ControlEvent) -> None:
        self.ref_paths = []
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
        # Attach subject stills into ref pack (merge)
        for p in sub.existing_images():
            if p not in self.ref_paths:
                self.ref_paths.append(p)
        self.ref_paths = self.ref_paths[:8]
        self.refs_label.value = f"{len(self.ref_paths)} ref still(s) (subject: {sub.name})"
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

        # Merge subject refs (not required for pure still T2I / I2I v1)
        refs = list(self.ref_paths)
        if not is_still_mode(self._mode):
            sn = _dd(self.subject_dd)
            if sn and sn != "(none)":
                s = find_subject(sn, self.state.output_dir)
                if s:
                    for p in s.existing_images():
                        if p not in refs:
                            refs.append(p)

        # Reference model needs refs
        spec = self._current_spec()
        if spec.max_refs > 0 and not refs:
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
            self.result_image.visible = False
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
            result = await asyncio.to_thread(
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
                ref_paths=None if still_job else (refs or None),
                duration=None if still_job else _dd(self.dur_dd),
                aspect_ratio=_dd(self.aspect_dd),
                resolution=(
                    _dd(self.res_dd)
                    if still_job and getattr(self.res_dd, "visible", False)
                    else (None if still_job else _dd(self.res_dd))
                ),
                negative_prompt=self.negative.value,
                generate_audio=False if still_job else bool(self.gen_audio.value),
                strength=strength_val,
                output_dir=self.state.output_dir,
                on_progress=on_progress,
            )
            self.cost_text.value = result.cost_label or self._cost_label()
            if result.ok and result.path:
                self._result_path = result.path
                done = result.status or "OK"
                self.job_progress.finish_ok(done, self.page)
                self.status.value = done
                self._show_result(result.path)
                self._refresh_send_menu(result.path)
            else:
                err = result.status or "Failed."
                self.job_progress.finish_error(err, self.page)
                self.status.value = err
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
        if is_img:
            try:
                self.player.clear()
            except Exception:
                pass
            try:
                self.player.control.visible = False
            except Exception:
                pass
            self.result_image.src = path
            self.result_image.visible = True
        else:
            self.result_image.visible = False
            self.result_image.src = ""
            try:
                self.player.control.visible = True
            except Exception:
                pass
            self.player.set_result(path)

    def _refresh_send_menu(self, path: str) -> None:
        """Send-to matrix: stills get FE keyframe + Start/End/I2V + shared matrix."""
        from media_studio.flet_send_to import (
            build_send_menu_items,
            make_send_menu_button,
            send_to_frame_editor,
        )

        def _st(msg: str) -> None:
            try:
                self.status.value = msg
                self.page.update()
            except Exception:
                pass

        ext = Path(path).suffix.lower()
        is_img = ext in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
        job_name = self._active_job_name()

        if is_img:
            import flet as ft

            items: list = []
            # Primary Aleph / motion handoffs after creative I2I or T2I
            items.append(
                ft.PopupMenuItem(
                    content="Frame Editor · keyframe",
                    on_click=send_to_frame_editor(
                        self.state,
                        path,
                        as_video=False,
                        job_name=job_name,
                        status_cb=_st,
                    ),
                )
            )
            items.append(ft.PopupMenuItem())
            items.append(
                ft.PopupMenuItem(
                    content="→ Start frame (this Vision tab)",
                    on_click=self._apply_as_start(path),
                )
            )
            items.append(
                ft.PopupMenuItem(
                    content="→ End frame (this Vision tab)",
                    on_click=self._apply_as_end(path),
                )
            )
            items.append(
                ft.PopupMenuItem(
                    content="→ I2V source (this Vision tab)",
                    on_click=self._apply_as_i2v(path),
                )
            )
            items.append(
                ft.PopupMenuItem(
                    content="→ Image → Image source (this Vision tab)",
                    on_click=self._apply_as_i2i(path),
                )
            )
            # Shared matrix (Studio, Tools, Resolve, …) — skip vision + FE
            more = build_send_menu_items(
                self.state,
                image_path=path,
                status_cb=_st,
                include_vision=False,
                include_frame_editor=False,
            )
            if more:
                items.append(ft.PopupMenuItem())
                items.extend(more)
        else:
            items = build_send_menu_items(
                self.state,
                video_path=path,
                status_cb=_st,
            )

        btn = make_send_menu_button(
            items,
            tooltip="Send to Frame Editor, Vision slots, Studio, Tools, or Resolve",
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
