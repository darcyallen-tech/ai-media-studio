"""Phase G: Video Denoise / Clean + Frame Interpolate cards (Tools → Video)."""

from __future__ import annotations

import asyncio
import traceback
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

import flet as ft

from media_studio.flet_pickers import pick_video
from media_studio.flet_progress import JobProgress, classify_progress
from media_studio.flet_result_actions import make_result_action_row, show_result_actions
from media_studio.flet_source_strip import PreviousSourcesStrip
from media_studio.flet_theme import (
    ACCENT,
    ACCENT_BRIGHT,
    BORDER,
    FONT_SM,
    PANEL_ELEVATED,
    TEXT,
    TEXT_MUTED,
    dropdown_options,
    panel,
    section_title,
    styled_dropdown,
)
from media_studio.tools_registry import (
    INTERPOLATE_FACTOR_CHOICES,
    VIDEO_DENOISE_MODELS,
    VIDEO_INTERPOLATE_MODELS,
    find_tool,
    format_video_denoise_cost,
    format_video_interpolate_cost,
    video_denoise_labels,
    video_interpolate_labels,
)
from media_studio.tools_service import run_video_denoise, run_video_interpolate

if TYPE_CHECKING:
    from media_studio.flet_app import StudioState


def _dd(dd: ft.Dropdown) -> str | None:
    return dd.value


def _emit(card: Any, source: str | None, result: str) -> None:
    cb = getattr(card, "on_result", None)
    if callable(cb):
        try:
            cb(source, result, tool_label=getattr(card, "tool_label", "") or "")
        except TypeError:
            try:
                cb(source, result)
            except Exception:
                pass
        except Exception:
            pass


class _VideoOnlyCardBase:
    """Shared source strip + video load for denoise / interpolate."""

    tool_label: str = "Video tool"
    empty_hint: str = "Upload a clip first."

    def __init__(self, page: ft.Page, state: StudioState) -> None:
        self.page = page
        self.state = state
        self.source_path: str | None = None
        self._result_path: str | None = None
        self._video_duration_s: float | None = None
        self.on_result: Callable[..., None] | None = None

        self.src_video_label = ft.Text(
            "",
            size=FONT_SM,
            color=TEXT,
            visible=False,
            max_lines=3,
            text_align=ft.TextAlign.CENTER,
        )
        self.src_placeholder = ft.Container(
            content=ft.Text("Source video", color=TEXT_MUTED, size=FONT_SM),
            alignment=ft.Alignment.CENTER,
            width=140,
            height=90,
            bgcolor=PANEL_ELEVATED,
            border_radius=6,
            border=ft.Border.all(1, BORDER),
        )
        self.btn_upload = ft.OutlinedButton(
            content="Upload video",
            icon=ft.Icons.VIDEO_FILE,
            on_click=self._pick_source,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
        )
        self.status = ft.Text("", size=FONT_SM, color=TEXT_MUTED, max_lines=4)
        self.job_progress = JobProgress()
        self.result_actions_row, self.btn_folder, self.btn_resolve = make_result_action_row(
            page,
            get_path=lambda: self._result_path,
            on_status=self._set_status,
        )
        show_result_actions(self.btn_folder, self.btn_resolve, visible=False)
        self.result_actions_row.visible = False
        self.prev_strip = PreviousSourcesStrip(
            page,
            get_output_dir=lambda: self.state.output_dir,
            on_load=self._on_prev_source,
            media_kind="video",
        )
        self.state.on_keys_changed(self.apply_key_gates)

    def _set_status(self, msg: str, is_error: bool = False) -> None:
        self.status.value = msg
        self.status.color = "#e57373" if is_error else TEXT_MUTED
        try:
            self.page.update()
        except Exception:
            pass

    def apply_key_gates(self) -> None:
        from media_studio.secrets_store import has_fal_key

        ready = has_fal_key()
        btn = getattr(self, "btn", None)
        if btn is None:
            return
        if not self.state.is_busy("tools"):
            btn.disabled = not ready
            btn.tooltip = (
                None if ready else "Add your FAL API key in Settings to run tools"
            )

    def force_mode(self, mode: str, *, clear_source: bool = False) -> None:
        # Video-only tools ignore image group (panel only shown under Video tools)
        if clear_source:
            self.source_path = None
            self.src_video_label.visible = False
            self.src_placeholder.visible = True

    def _on_prev_source(self, path: str) -> None:
        self.load_source(path, status=f"Previous: {Path(path).name}")
        try:
            self.page.update()
        except Exception:
            pass

    def load_source(self, path: str, *, status: str | None = None) -> bool:
        try:
            p = Path(path)
            if not p.is_file():
                self.status.value = f"Missing: {path}"
                return False
            resolved = str(p.resolve())
        except OSError:
            return False
        self.source_path = resolved
        self._video_duration_s = None
        name = Path(resolved).name
        self.src_placeholder.visible = False
        try:
            from media_studio.pricing import probe_video_duration

            self._video_duration_s = float(probe_video_duration(resolved) or 0) or None
        except Exception:
            self._video_duration_s = None
        dur_note = (
            f"{self._video_duration_s:.1f}s"
            if self._video_duration_s
            else "duration unknown"
        )
        try:
            mb = p.stat().st_size / (1024 * 1024)
            self.src_video_label.value = f"{name} · {dur_note} · {mb:.0f} MB"
        except OSError:
            self.src_video_label.value = f"{name} · {dur_note}"
        self.src_video_label.visible = True
        try:
            self.prev_strip.record_and_refresh(resolved)
        except Exception:
            pass
        self._refresh_cost_ui()
        self.status.value = status or f"Loaded {name}"
        self.status.color = TEXT_MUTED
        return True

    def load_image(self, path: str, *, status: str | None = None) -> bool:
        self.status.value = "This tool needs a video clip, not a still."
        self.status.color = "#e57373"
        return False

    async def _pick_source(self, e: ft.ControlEvent) -> None:
        try:
            files = await pick_video(self.page, dialog_title="Choose source video")
        except Exception as exc:
            self.status.value = f"Picker error: {exc}"
            self.page.update()
            return
        if not files or not files[0].path:
            return
        self.load_source(files[0].path)
        self.page.update()

    def _refresh_cost_ui(self) -> None:
        pass

    def _source_column(self) -> ft.Control:
        return ft.Column(
            [
                self.src_placeholder,
                self.src_video_label,
                self.btn_upload,
                self.prev_strip.root,
            ],
            spacing=6,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        )


class VideoDenoiseCard(_VideoOnlyCardBase):
    """Topaz Nyx / Artemis denoise-clean — no long prompt."""

    tool_label = "Video Denoise"
    empty_hint = "Upload a clip to denoise."

    def __init__(self, page: ft.Page, state: StudioState) -> None:
        super().__init__(page, state)
        labels = video_denoise_labels()
        default = next((x for x in labels if x.lower().startswith("nyx (")), labels[0] if labels else None)
        self.model_dd = styled_dropdown(
            label_text="Denoise model",
            options=labels,
            value=default,
            on_select=self._on_model,
            expand=True,
        )
        self.model_notes = ft.Text(
            "",
            size=FONT_SM,
            color=TEXT_MUTED,
            max_lines=3,
        )
        self.noise_sl = ft.Slider(
            min=0,
            max=1,
            divisions=20,
            value=0.35,
            label="Noise {value}",
            active_color=ACCENT,
            on_change=self._on_slider,
            expand=True,
        )
        self.comp_sl = ft.Slider(
            min=0,
            max=1,
            divisions=20,
            value=0.25,
            label="Compression {value}",
            active_color=ACCENT,
            on_change=self._on_slider,
            expand=True,
        )
        self.detail_sl = ft.Slider(
            min=0,
            max=1,
            divisions=20,
            value=0.2,
            label="Recover detail {value}",
            active_color=ACCENT,
            on_change=self._on_slider,
            expand=True,
        )
        self.halo_sl = ft.Slider(
            min=0,
            max=1,
            divisions=20,
            value=0.15,
            label="Halo {value}",
            active_color=ACCENT,
            on_change=self._on_slider,
            expand=True,
        )
        self.scale_dd = styled_dropdown(
            label_text="Optional scale",
            options=["1× (denoise only)", "1.5×", "2×"],
            value="1× (denoise only)",
            on_select=self._on_model,
            expand=True,
        )
        self.noise_val = ft.Text("0.35", size=FONT_SM, color=TEXT_MUTED, width=36)
        self.comp_val = ft.Text("0.25", size=FONT_SM, color=TEXT_MUTED, width=36)
        self.detail_val = ft.Text("0.20", size=FONT_SM, color=TEXT_MUTED, width=36)
        self.halo_val = ft.Text("0.15", size=FONT_SM, color=TEXT_MUTED, width=36)
        self.cost_text = ft.Text(
            self._cost(), size=FONT_SM, color=TEXT, weight=ft.FontWeight.W_600
        )
        self.btn = ft.FilledButton(
            content="Run denoise",
            on_click=self._run,
            style=ft.ButtonStyle(bgcolor=ACCENT_BRIGHT, color=TEXT),
        )
        self.apply_key_gates()
        self._sync_notes()

        self.root = panel(
            ft.Column(
                [
                    section_title("Video Denoise / Clean"),
                    ft.Text(
                        "One-click cleanup for underexposed / high-ISO interiors. "
                        "Topaz Nyx (denoise) or Artemis (denoise+sharpen). "
                        "Control-driven — no long prompt. Optional light scale-up.",
                        size=FONT_SM,
                        color=TEXT_MUTED,
                    ),
                    ft.Row(
                        [
                            self._source_column(),
                            ft.Column(
                                [
                                    self.model_dd,
                                    self.model_notes,
                                    self.scale_dd,
                                    ft.Row(
                                        [
                                            ft.Text("Noise", size=FONT_SM, color=TEXT, width=88),
                                            self.noise_sl,
                                            self.noise_val,
                                        ],
                                        spacing=4,
                                    ),
                                    ft.Row(
                                        [
                                            ft.Text("Compression", size=FONT_SM, color=TEXT, width=88),
                                            self.comp_sl,
                                            self.comp_val,
                                        ],
                                        spacing=4,
                                    ),
                                    ft.Row(
                                        [
                                            ft.Text("Recover detail", size=FONT_SM, color=TEXT, width=88),
                                            self.detail_sl,
                                            self.detail_val,
                                        ],
                                        spacing=4,
                                    ),
                                    ft.Row(
                                        [
                                            ft.Text("Halo", size=FONT_SM, color=TEXT, width=88),
                                            self.halo_sl,
                                            self.halo_val,
                                        ],
                                        spacing=4,
                                    ),
                                    self.cost_text,
                                    self.btn,
                                    self.job_progress.control,
                                    self.status,
                                ],
                                expand=True,
                                spacing=6,
                            ),
                        ],
                        spacing=12,
                        vertical_alignment=ft.CrossAxisAlignment.START,
                    ),
                ],
                spacing=8,
            ),
        )

    def _scale_factor(self) -> float:
        raw = (_dd(self.scale_dd) or "1").lower()
        if "1.5" in raw:
            return 1.5
        if raw.startswith("2"):
            return 2.0
        return 1.0

    def _cost(self) -> str:
        spec = find_tool(_dd(self.model_dd), VIDEO_DENOISE_MODELS)
        if not spec:
            return "Est. cost: —"
        dur = float(self._video_duration_s or 8.0)
        return format_video_denoise_cost(
            spec, duration_s=dur, upscale_factor=self._scale_factor()
        ) + ("" if self._video_duration_s else " · duration unknown (est. 8s)")

    def _sync_notes(self) -> None:
        spec = find_tool(_dd(self.model_dd), VIDEO_DENOISE_MODELS)
        self.model_notes.value = (spec.notes if spec else "") or ""

    def _refresh_cost_ui(self) -> None:
        self.cost_text.value = self._cost()
        self._sync_notes()

    async def _on_model(self, e: ft.ControlEvent) -> None:
        self._refresh_cost_ui()
        try:
            self.page.update()
        except Exception:
            pass

    async def _on_slider(self, e: ft.ControlEvent) -> None:
        self.noise_val.value = f"{float(self.noise_sl.value or 0):.2f}"
        self.comp_val.value = f"{float(self.comp_sl.value or 0):.2f}"
        self.detail_val.value = f"{float(self.detail_sl.value or 0):.2f}"
        self.halo_val.value = f"{float(self.halo_sl.value or 0):.2f}"
        try:
            self.page.update()
        except Exception:
            pass

    async def _run(self, e: ft.ControlEvent) -> None:
        if self.state.is_busy("tools"):
            return
        from media_studio.secrets_store import has_fal_key

        if not has_fal_key():
            self._set_status("FAL API key required — open Settings (gear icon).", True)
            return
        if not self.source_path or not Path(self.source_path).is_file():
            self._set_status(self.empty_hint, True)
            return
        if not self.state.try_busy("tools"):
            return
        self.btn.disabled = True
        self.job_progress.start("Uploading…", self.page)
        self.status.value = "Running denoise…"
        self.page.update()

        def on_progress(msg: str) -> None:
            self.job_progress.set_message(classify_progress(msg), self.page)

        dur = float(self._video_duration_s or 8.0)
        try:
            from media_studio.job_context import to_thread_with_job

            result = await to_thread_with_job(
                self.state,
                run_video_denoise,
                video_path=self.source_path,
                model_label=_dd(self.model_dd),
                noise=float(self.noise_sl.value or 0.35),
                compression=float(self.comp_sl.value or 0.25),
                recover_detail=float(self.detail_sl.value or 0.2),
                halo=float(self.halo_sl.value or 0.15),
                upscale_factor=self._scale_factor(),
                duration_s=dur,
                output_dir=self.state.output_dir,
                on_progress=on_progress,
            )
            if result.ok and result.path:
                self._result_path = result.path
                show_result_actions(self.btn_folder, self.btn_resolve, visible=True)
                self.cost_text.value = result.cost_label or self._cost()
                done = result.status or "OK"
                self.job_progress.finish_ok(done, self.page)
                self.status.value = done
                _emit(self, self.source_path, result.path)
            else:
                err = result.status or "Failed."
                self.job_progress.finish_error(err, self.page)
                self.status.value = err
        except Exception as exc:
            self.job_progress.finish_error(f"Error: {exc}", self.page)
            self.status.value = f"Error: {exc}"
            traceback.print_exc()
        finally:
            self.state.clear_busy("tools")
            self.apply_key_gates()
            self.page.update()


class VideoInterpolateCard(_VideoOnlyCardBase):
    """RIFE / FILM frame interpolation — smooth fps or short slow-mo."""

    tool_label = "Frame Interpolate"
    empty_hint = "Upload a clip to interpolate."

    def __init__(self, page: ft.Page, state: StudioState) -> None:
        super().__init__(page, state)
        labels = video_interpolate_labels()
        default = next((x for x in labels if "rife" in x.lower()), labels[0] if labels else None)
        self.model_dd = styled_dropdown(
            label_text="Interpolate model",
            options=labels,
            value=default,
            on_select=self._on_model,
            expand=True,
        )
        self.model_notes = ft.Text("", size=FONT_SM, color=TEXT_MUTED, max_lines=3)
        self.factor_dd = styled_dropdown(
            label_text="Slow-mo / fps factor",
            options=list(INTERPOLATE_FACTOR_CHOICES),
            value=INTERPOLATE_FACTOR_CHOICES[0],
            on_select=self._on_model,
            expand=True,
        )
        self.scene_sw = ft.Switch(
            label="Scene detection (avoid smear across cuts)",
            value=False,
            active_color=ACCENT_BRIGHT,
        )
        self.cost_text = ft.Text(
            self._cost(), size=FONT_SM, color=TEXT, weight=ft.FontWeight.W_600
        )
        self.btn = ft.FilledButton(
            content="Run interpolate",
            on_click=self._run,
            style=ft.ButtonStyle(bgcolor=ACCENT_BRIGHT, color=TEXT),
        )
        self.apply_key_gates()
        self._sync_notes()

        self.root = panel(
            ft.Column(
                [
                    section_title("Frame Interpolate / Slow Mo"),
                    ft.Text(
                        "Smooth 24/30 → 60 fps, or short hero slow-mo without leaving the app. "
                        "RIFE is fast/cheap; FILM handles large motion better. "
                        "No prompt required.",
                        size=FONT_SM,
                        color=TEXT_MUTED,
                    ),
                    ft.Row(
                        [
                            self._source_column(),
                            ft.Column(
                                [
                                    self.model_dd,
                                    self.model_notes,
                                    self.factor_dd,
                                    self.scene_sw,
                                    self.cost_text,
                                    self.btn,
                                    self.job_progress.control,
                                    self.status,
                                ],
                                expand=True,
                                spacing=6,
                            ),
                        ],
                        spacing=12,
                        vertical_alignment=ft.CrossAxisAlignment.START,
                    ),
                ],
                spacing=8,
            ),
        )

    def _cost(self) -> str:
        spec = find_tool(_dd(self.model_dd), VIDEO_INTERPOLATE_MODELS)
        if not spec:
            return "Est. cost: —"
        dur = float(self._video_duration_s or 8.0)
        return format_video_interpolate_cost(
            spec, duration_s=dur, factor_label=_dd(self.factor_dd)
        ) + ("" if self._video_duration_s else " · duration unknown (est. 8s)")

    def _sync_notes(self) -> None:
        spec = find_tool(_dd(self.model_dd), VIDEO_INTERPOLATE_MODELS)
        self.model_notes.value = (spec.notes if spec else "") or ""
        # Scene detection is most useful for FILM; still available for RIFE
        is_film = bool(spec and "film" in spec.key.lower())
        self.scene_sw.label = (
            "Scene detection (recommended for FILM when cuts exist)"
            if is_film
            else "Scene detection (avoid smear across cuts)"
        )

    def _refresh_cost_ui(self) -> None:
        self.cost_text.value = self._cost()
        self._sync_notes()

    async def _on_model(self, e: ft.ControlEvent) -> None:
        self._refresh_cost_ui()
        try:
            self.page.update()
        except Exception:
            pass

    async def _run(self, e: ft.ControlEvent) -> None:
        if self.state.is_busy("tools"):
            return
        from media_studio.secrets_store import has_fal_key

        if not has_fal_key():
            self._set_status("FAL API key required — open Settings (gear icon).", True)
            return
        if not self.source_path or not Path(self.source_path).is_file():
            self._set_status(self.empty_hint, True)
            return
        if not self.state.try_busy("tools"):
            return
        self.btn.disabled = True
        self.job_progress.start("Uploading…", self.page)
        self.status.value = "Running interpolate…"
        self.page.update()

        def on_progress(msg: str) -> None:
            self.job_progress.set_message(classify_progress(msg), self.page)

        dur = float(self._video_duration_s or 8.0)
        try:
            from media_studio.job_context import to_thread_with_job

            result = await to_thread_with_job(
                self.state,
                run_video_interpolate,
                video_path=self.source_path,
                model_label=_dd(self.model_dd),
                factor_label=_dd(self.factor_dd),
                use_scene_detection=bool(self.scene_sw.value),
                duration_s=dur,
                output_dir=self.state.output_dir,
                on_progress=on_progress,
            )
            if result.ok and result.path:
                self._result_path = result.path
                show_result_actions(self.btn_folder, self.btn_resolve, visible=True)
                self.cost_text.value = result.cost_label or self._cost()
                done = result.status or "OK"
                self.job_progress.finish_ok(done, self.page)
                self.status.value = done
                _emit(self, self.source_path, result.path)
            else:
                err = result.status or "Failed."
                self.job_progress.finish_error(err, self.page)
                self.status.value = err
        except Exception as exc:
            self.job_progress.finish_error(f"Error: {exc}", self.page)
            self.status.value = f"Error: {exc}"
            traceback.print_exc()
        finally:
            self.state.clear_busy("tools")
            self.apply_key_gates()
            self.page.update()
