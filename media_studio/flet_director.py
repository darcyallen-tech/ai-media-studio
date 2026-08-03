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
    AUDIO_STYLES,
    CAMERA_PRESETS,
    OUTPUT_MODES,
    STYLE_PACKS,
    TRANSITION_PREFS,
    DirectorPolish,
    DirectorShot,
    assemble_director_brief,
    default_director_model,
    director_model_labels,
    estimate_director_cost,
    find_director_model,
    format_director_cost,
    validate_shots,
)

# Ref-still thumbnail size on shot rows (px)
_REF_THUMB = 64
from media_studio.director_service import run_director
from media_studio.flet_enhance import make_enhance_button, run_prompt_enhance
from media_studio.flet_pickers import pick_image
from media_studio.flet_progress import JobProgress, classify_progress
from media_studio.flet_result_actions import make_result_action_row, show_result_actions
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
    dropdown_options,
    label,
    section_title,
    styled_dropdown,
)
from media_studio.flet_video_player import VideoResultPlayer
from media_studio.helper_none import HELPER_NONE

if TYPE_CHECKING:
    from media_studio.flet_app import StudioState


def _dd(dd: ft.Dropdown) -> str | None:
    return dd.value


class DirectorView:
    """Multi-shot Director workspace."""

    def __init__(self, page: ft.Page, state: StudioState) -> None:
        self.page = page
        self.state = state
        self._result_path: str | None = None
        self._shots: list[dict[str, Any]] = []  # row widgets + data

        spec0 = default_director_model()
        labels = director_model_labels()
        self.model_dd = styled_dropdown(
            label_text="Model (multi-shot only)",
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
        self.aspect_dd = styled_dropdown(
            label_text="Aspect",
            options=list(spec0.aspect_choices),
            value=spec0.default_aspect,
            on_select=self._refresh_cost,
            expand=True,
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
            on_change=self._on_polish_change,
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
        self.transition_dd = styled_dropdown(
            label_text="Transition",
            options=list(TRANSITION_PREFS),
            value="Hard cut",
            on_select=self._on_polish_change,
            expand=True,
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
        self.cost_text = ft.Text(
            self._cost_label(),
            size=FONT_SM,
            color=TEXT,
            weight=ft.FontWeight.W_600,
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
        )
        self._sync_audio_polish_visibility()

        self.shots_host = ft.Column(spacing=8, tight=True)
        self.btn_add_shot = ft.OutlinedButton(
            content="Add shot",
            icon=ft.Icons.ADD,
            on_click=self._add_shot,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
        )
        self.shots_meta = ft.Text(
            "",
            size=FONT_SM,
            color=TEXT_MUTED,
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

        self.state.on_keys_changed(self.apply_key_gates)
        # Seed 2 default shots for 10s total
        self._add_shot_row(start=0, end=5, camera="Push in")
        self._add_shot_row(start=5, end=10, camera="Orbit")
        self._sync_shots_meta()
        self._rebuild_assembled_text()
        self.apply_key_gates()

    # ----- layout -----

    def build(self) -> ft.Control:
        from media_studio.flet_layout import make_split_workspace
        from media_studio.flet_theme import RAIL_WIDTH

        left = [
            section_title("Director"),
            ft.Text(
                "Multi-shot generation — ordered shots, per-shot camera + action, "
                "one master brief. Not for editing existing plates (use Frame Editor).",
                size=FONT_SM,
                color=TEXT_MUTED,
            ),
            ft.Divider(height=1, color=BORDER),
            label("Master", muted=True),
            ft.Row([self.model_dd], spacing=0),
            self.model_best_for,
            self.model_notes,
            ft.Row([self.dur_dd, self.aspect_dd, self.style_dd], spacing=8),
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
            ft.Row([self.transition_dd, self.output_mode_dd], spacing=8),
            self.energy_curve,
            self.vision_notes,
            ft.Container(
                content=self.cost_text,
                bgcolor=PANEL_ELEVATED,
                border=ft.Border.all(1, BORDER),
                border_radius=6,
                padding=ft.Padding.symmetric(horizontal=10, vertical=6),
            ),
            self.master,
            ft.Divider(height=1, color=BORDER),
            label("Shots (ordered, non-overlapping)", muted=True),
            self.shots_meta,
            self.shots_host,
            ft.Row([self.btn_add_shot], spacing=8),
            label("Still refs for active shot (Previously used / From Resolve)", muted=True),
            self.prev_strip.root,
            self.resolve_strip.root,
            self.assembled,
            ft.Row([self.btn_rebuild, self.btn_enhance, self.btn_generate], spacing=8),
            self.job_progress.control,
            self.status,
        ]
        right = ft.Column(
            [
                section_title("Result"),
                ft.Text(
                    "Multi-shot clip (optional shot-list sidecar). "
                    "Library · Show in folder · Send to Resolve.",
                    size=FONT_SM,
                    color=TEXT_MUTED,
                ),
                self.player.control,
                self.result_actions_row,
            ],
            spacing=8,
            tight=True,
            expand=False,
        )
        return make_split_workspace(left, right, left_width=max(RAIL_WIDTH, 500))

    # ----- helpers -----

    def apply_key_gates(self) -> None:
        from media_studio.secrets_store import has_fal_key, has_xai_key

        ready = has_fal_key()
        if not self.state.is_busy("director"):
            self.btn_generate.disabled = not ready
            self.btn_generate.tooltip = (
                None if ready else "Add your FAL API key in Settings"
            )
            xai = has_xai_key()
            self.btn_enhance.disabled = not xai
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

    def _cost_label(self) -> str:
        try:
            spec = self._current_spec()
            audio = bool(self.gen_audio.value) if spec.supports_audio else False
            return format_director_cost(
                spec,
                duration_s=self._total_duration(),
                generate_audio=audio,
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
        self.aspect_dd.options = dropdown_options(list(spec.aspect_choices))
        if _dd(self.aspect_dd) not in spec.aspect_choices:
            self.aspect_dd.value = spec.default_aspect
        self.gen_audio.visible = bool(spec.supports_audio)
        self.gen_audio.value = bool(spec.default_generate_audio)
        self._sync_audio_polish_visibility()
        self._trim_shots_to_max()
        self._sync_shots_meta()
        self.cost_text.value = self._cost_label()
        self._rebuild_assembled_text()
        try:
            self.page.update()
        except Exception:
            pass

    async def _on_duration(self, e: ft.ControlEvent) -> None:
        self.cost_text.value = self._cost_label()
        self._sync_shots_meta()
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
        self._rebuild_assembled_text()
        try:
            self.page.update()
        except Exception:
            pass

    def _collect_polish(self) -> DirectorPolish:
        gen_audio = bool(self.gen_audio.value) if self.gen_audio.visible else False
        return DirectorPolish(
            audio_style=_dd(self.audio_style_dd) or "Soft bed only",
            sfx_note=(self.sfx_note.value or "").strip(),
            same_character=bool(self.cont_character.value),
            same_location=bool(self.cont_location.value),
            same_time_of_day=bool(self.cont_time.value),
            transition=_dd(self.transition_dd) or "Hard cut",
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
            out.append(
                DirectorShot(
                    start_s=start,
                    end_s=end,
                    camera=_dd(row["camera"]) or "Static",
                    action=(row["action"].value or "").strip(),
                    ref_path=row.get("ref_path"),
                )
            )
        return out

    def _trim_shots_to_max(self) -> None:
        cap = self._current_spec().max_shots
        while len(self._shots) > cap:
            removed = self._shots.pop()
            try:
                self.shots_host.controls.remove(removed["card"])
            except Exception:
                pass

    def _sync_shots_meta(self) -> None:
        spec = self._current_spec()
        n = len(self._shots)
        self.shots_meta.value = (
            f"{n} shot(s) · max {spec.max_shots} · total duration {self._total_duration():.0f}s "
            f"· times must stay inside 0–{self._total_duration():.0f}s, no overlap"
        )
        self.btn_add_shot.disabled = n >= spec.max_shots

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
            label="Per-shot action",
            value=action,
            hint_text="What happens in this shot",
            dense=True,
            filled=True,
            fill_color=PANEL_ELEVATED,
            border_color=BORDER,
            color=TEXT,
            text_size=FONT_SM,
            expand=True,
            on_change=self._on_shot_field,
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
            f"Shot {idx + 1}",
            size=FONT_SM,
            color=TEXT,
            weight=ft.FontWeight.W_700,
        )
        card = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [title, ft.Container(expand=True), btn_remove],
                        spacing=4,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Row([start_tf, end_tf, cam_dd], spacing=8),
                    action_tf,
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
        row = {
            "card": card,
            "start": start_tf,
            "end": end_tf,
            "camera": cam_dd,
            "action": action_tf,
            "ref_label": ref_label,
            "ref_thumb": ref_thumb,
            "ref_empty": ref_empty,
            "ref_path": None,
            "title": title,
            "btn_ref": btn_ref,
            "btn_clear_ref": btn_clear_ref,
            "btn_remove": btn_remove,
        }
        self._shots.append(row)
        self.shots_host.controls.append(card)
        self._reindex_shots()

    def _reindex_shots(self) -> None:
        for i, row in enumerate(self._shots):
            try:
                row["title"].value = f"Shot {i + 1}"
                row["btn_ref"].on_click = self._make_pick_ref(i)
                row["btn_clear_ref"].on_click = self._make_clear_ref(i)
                row["btn_remove"].on_click = self._make_remove_shot(i)
            except Exception:
                pass
        self._sync_shots_meta()

    async def _add_shot(self, e: ft.ControlEvent) -> None:
        spec = self._current_spec()
        if len(self._shots) >= spec.max_shots:
            self.status.value = f"Max {spec.max_shots} shots for {spec.label}."
            self.page.update()
            return
        # Default: continue after last end, 1/3 of remaining or 3s
        total = self._total_duration()
        if self._shots:
            try:
                last_end = float(self._shots[-1]["end"].value or 0)
            except (TypeError, ValueError):
                last_end = 0.0
        else:
            last_end = 0.0
        start = min(last_end, total - 1)
        end = min(total, start + max(3.0, (total - start) / 2))
        if end <= start:
            end = min(total, start + 1)
        self._add_shot_row(start=start, end=end)
        self._rebuild_assembled_text()
        self.page.update()

    def _make_remove_shot(self, index: int):
        async def _click(_e: ft.ControlEvent) -> None:
            if len(self._shots) <= 1:
                self.status.value = "Keep at least one shot."
                self.page.update()
                return
            if 0 <= index < len(self._shots):
                row = self._shots.pop(index)
                try:
                    self.shots_host.controls.remove(row["card"])
                except Exception:
                    pass
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

    def _set_shot_ref(self, index: int, path: str | None) -> None:
        if not (0 <= index < len(self._shots)):
            return
        row = self._shots[index]
        if path and Path(path).is_file():
            resolved = str(Path(path).resolve())
            name = Path(resolved).name
            row["ref_path"] = resolved
            row["ref_label"].value = name
            row["ref_label"].color = TEXT
            try:
                row["ref_label"].tooltip = resolved
            except Exception:
                pass
            thumb = row.get("ref_thumb")
            empty = row.get("ref_empty")
            if thumb is not None:
                try:
                    thumb.src = resolved
                    thumb.visible = True
                except Exception:
                    pass
            if empty is not None:
                try:
                    empty.visible = False
                except Exception:
                    pass
            try:
                self.prev_strip.record_and_refresh(resolved)
            except Exception:
                pass
        else:
            row["ref_path"] = None
            row["ref_label"].value = "No ref still"
            row["ref_label"].color = TEXT_MUTED
            try:
                row["ref_label"].tooltip = "No ref still"
            except Exception:
                pass
            thumb = row.get("ref_thumb")
            empty = row.get("ref_empty")
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

    async def _on_shot_field(self, e: ft.ControlEvent | None = None) -> None:
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
            return {
                "workspace": "director",
                "mode": "multi_shot",
                "model": _dd(self.model_dd),
                "total_duration_s": self._total_duration(),
                "style_pack": style,
                "master_brief": (self.master.value or "").strip(),
                "continuity": cont,
                "transition": polish.transition,
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
                        "has_ref": bool(s.ref_path),
                    }
                    for i, s in enumerate(shots)
                ],
                "guidance": (
                    "Rewrite for Kling multi-shot / director video generation. "
                    "Output should remain useful as: (1) a tightened master brief and "
                    "(2) clear per-shot action language with camera moves. "
                    "Preserve shot order and timing intent. "
                    f"Honor continuity flags: {cont} "
                    f"Transition preference: {polish.transition}. "
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
                ),
            }

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
        errs = validate_shots(
            shots,
            total_duration_s=total,
            max_shots=spec.max_shots,
            allow_overlap=False,
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

        # Cost guard optional
        try:
            from media_studio.flet_dialogs import confirm_cost_if_needed

            est = estimate_director_cost(
                spec,
                duration_s=total,
                generate_audio=bool(self.gen_audio.value),
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

        polish = self._collect_polish()
        try:
            from media_studio.job_context import to_thread_with_job

            result = await to_thread_with_job(
                self.state,
                run_director,
                master=master,
                shots=shots,
                model_label=_dd(self.model_dd),
                duration_s=total,
                aspect_ratio=_dd(self.aspect_dd),
                style_pack=_dd(self.style_dd),
                generate_audio=bool(self.gen_audio.value)
                if self.gen_audio.visible
                else None,
                polish=polish,
                output_dir=self.state.output_dir,
                on_progress=on_progress,
            )
            self.cost_text.value = result.cost_label or self._cost_label()
            if result.ok and result.path:
                self._result_path = result.path
                done = result.status or "OK"
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
            else:
                err = result.status or "Failed."
                self.job_progress.finish_error(err, self.page)
                self.status.value = err
        except Exception as exc:
            from media_studio.errors import friendly_error

            err = friendly_error(exc, context="Director")
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
