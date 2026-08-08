"""Tools tab — upscale, clutter remove, sky, dehaze, sharpen/restore."""

from __future__ import annotations

import asyncio
import traceback
from pathlib import Path
from typing import TYPE_CHECKING, Callable

import flet as ft

from media_studio.flet_theme import (
    ACCENT,
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
from media_studio.tools_registry import (
    AMENITY_CHOICES,
    AMENITY_MODELS,
    BLOWN_OUT_INTENSITY_LABELS,
    BLOWN_OUT_MODELS,
    BLOWN_OUT_PROMPT_CORE,
    CLEANUP_MODELS,
    DEHAZE_MODELS,
    DEHAZE_STRENGTH_LABELS,
    MATCH_LOOK_DEFAULT,
    MATCH_LOOK_MODELS,
    MIRROR_DEFAULT,
    MIRROR_MODELS,
    REASPECT_ASPECT_CHOICES,
    REASPECT_IMAGE_MODELS,
    REASPECT_PROMPT_CORE,
    REASPECT_VIDEO_MODELS,
    RESTORE_PROMPT_CORE,
    RESTORE_VIDEO_MODELS,
    SEASON_CHOICES,
    SEASON_MODELS,
    SKY_MODELS,
    SKY_PRESETS,
    SKY_TIME_OF_DAY,
    UPSCALERS,
    VIDEO_AMENITY_MODELS,
    VIDEO_CLEANUP_DEFAULT,
    VIDEO_CLEANUP_MODELS,
    VIDEO_MIRROR_MODELS,
    VIDEO_SKY_MODELS,
    VIDEO_UPSCALE_TARGETS,
    VIDEO_UPSCALERS,
    amenity_labels,
    blown_out_labels,
    blown_out_prompt,
    blown_out_strength_from_label,
    cleanup_labels,
    dehaze_labels,
    dehaze_strength_from_label,
    find_tool,
    format_tool_cost,
    format_video_upscale_cost,
    match_look_labels,
    mirror_labels,
    reaspect_image_labels,
    reaspect_prompt,
    reaspect_video_labels,
    restore_image_labels,
    restore_image_registry,
    restore_prompt,
    restore_video_labels,
    season_tool_labels,
    sky_labels,
    upscale_labels,
    video_amenity_labels,
    video_cleanup_labels,
    video_mirror_labels,
    video_sky_labels,
    video_upscale_labels,
)
from media_studio.flet_dual_tool import DualMediaToolCard
from media_studio.flet_enhance import make_enhance_button, run_prompt_enhance
from media_studio.flet_inpaint import InpaintCard
from media_studio.flet_pickers import pick_image, pick_video
from media_studio.flet_progress import JobProgress, classify_progress
from media_studio.flet_result_actions import make_result_action_row, show_result_actions
from media_studio.flet_source_strip import PreviousSourcesStrip, ResolveSourcesStrip
from media_studio.flet_tools_result import ToolsResultPane
from media_studio.flet_tools_video_extra import VideoDenoiseCard, VideoInterpolateCard
from media_studio.tools_service import (
    run_amenity,
    run_blown_out,
    run_cleanup,
    run_dehaze,
    run_match_look,
    run_mirror,
    run_reaspect,
    run_restore,
    run_season,
    run_sky,
    run_upscale,
    run_video_upscale,
)

if TYPE_CHECKING:
    from media_studio.flet_app import StudioState


def _dd_value(dd: ft.Dropdown) -> str | None:
    return dd.value


def _emit_tool_result(
    card: object,
    source_path: str | None,
    result_path: str,
    *,
    tool_label: str = "",
) -> None:
    """Notify ToolsResultPane (if wired) of a successful generation."""
    cb = getattr(card, "on_result", None)
    if not callable(cb):
        return
    try:
        cb(source_path, result_path, tool_label=tool_label or getattr(card, "tool_label", ""))
    except TypeError:
        try:
            cb(source_path, result_path)
        except Exception:
            pass
    except Exception:
        pass


class _ToolCard:
    """One minimal tool: upload → options → run → result + cost."""

    def __init__(
        self,
        page: ft.Page,
        state: StudioState,
        *,
        title: str,
        description: str,
        model_labels: list[str],
        model_registry: dict,
        run_fn: Callable,
        extra_controls: list[ft.Control] | None = None,
        get_extra_kwargs: Callable[[], dict] | None = None,
        default_prompt: str = "",
        show_prompt: bool = True,
        show_strength: bool = False,
        button_label: str = "Run",
        on_result: Callable | None = None,
    ) -> None:
        self.page = page
        self.state = state
        self.model_registry = model_registry
        self.run_fn = run_fn
        self.get_extra_kwargs = get_extra_kwargs or (lambda: {})
        self.show_prompt = show_prompt
        self.show_strength = show_strength
        self.on_result = on_result
        self.tool_label = title
        self.image_path: str | None = None

        self.preview = ft.Image(src="", fit=ft.BoxFit.CONTAIN, width=160, height=100, visible=False)
        self.placeholder = ft.Container(
            content=ft.Text("Upload image", color=TEXT_MUTED, size=FONT_SM),
            alignment=ft.Alignment.CENTER,
            width=160,
            height=100,
            bgcolor=PANEL_ELEVATED,
            border_radius=6,
            border=ft.Border.all(1, BORDER),
        )
        self.model_dd = styled_dropdown(
            label_text="Model",
            options=model_labels,
            value=model_labels[0] if model_labels else None,
            on_select=self._refresh_cost,
            expand=True,
        )
        self.prompt = ft.TextField(
            label="Prompt / note (optional)",
            value=default_prompt,
            multiline=True,
            min_lines=2,
            max_lines=3,
            dense=True,
            filled=True,
            fill_color=PANEL_ELEVATED,
            border_color=BORDER,
            color=TEXT,
            text_size=FONT_SM,
            visible=show_prompt,
        )
        self.prompt_favs = None
        if show_prompt:
            from media_studio.flet_prompt_favorites import make_prompt_favorites_bar

            self.prompt_favs = make_prompt_favorites_bar(
                page,
                get_text=lambda: self.prompt.value,
                set_text=lambda t: setattr(self.prompt, "value", t),
                surface="tools",
                get_meta=lambda: {
                    "model": _dd_value(self.model_dd) if hasattr(self, "model_dd") else "",
                    "source": "user",
                },
                on_status=lambda m: setattr(self.status, "value", m),
                show_pack_buttons=False,
            )
        self.strength = ft.Slider(
            min=0.2,
            max=1.0,
            divisions=16,
            value=0.75,
            label="Strength {value}",
            active_color=ACCENT,
            visible=show_strength,
        )
        self.extra = extra_controls or []
        self.cost_text, self.cost_box = make_estimated_cost_box(initial="Est. cost: —")
        self.cost_text.value = self._cost()
        self.status = ft.Text("", size=FONT_SM, color=TEXT_MUTED, max_lines=3)
        self.job_progress = JobProgress()
        self.result = ft.Image(src="", fit=ft.BoxFit.CONTAIN, width=220, height=140, visible=False)
        self._result_path: str | None = None
        self.btn = ft.FilledButton(
            content=button_label,
            on_click=self._run,
            style=ft.ButtonStyle(bgcolor=ACCENT_BRIGHT, color=TEXT),
            height=40,
        )
        self.btn_enhance = make_enhance_button(on_click=self._on_enhance)
        self.btn_enhance.visible = bool(show_prompt)
        self.state.on_keys_changed(self.apply_key_gates)
        self.apply_key_gates()
        self.btn_upload = ft.OutlinedButton(
            content="Upload",
            icon=ft.Icons.UPLOAD_FILE,
            on_click=self._pick,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
        )
        self.prev_strip = PreviousSourcesStrip(
            page,
            get_output_dir=lambda: self.state.output_dir,
            on_load=self._on_prev_source,
            media_kind="image",
        )
        self.resolve_strip = ResolveSourcesStrip(
            page,
            on_load=self._on_prev_source,
            media_kind="image",
        )
        (
            self.result_actions_row,
            self.btn_folder,
            self.btn_resolve,
        ) = make_result_action_row(
            page,
            get_path=lambda: self._result_path,
            on_status=lambda msg, err: self._set_tool_status(msg, err),
        )

        action_row = ft.Row(
            [self.btn_enhance, self.btn] if show_prompt else [self.btn],
            spacing=8,
        )
        # Large preview lives in ToolsResultPane (right stage)
        self.result.visible = False
        self.result_actions_row.visible = False

        self.root = ft.Container(
            bgcolor=PANEL,
            border=ft.Border.all(1, BORDER),
            border_radius=8,
            padding=12,
            content=ft.Column(
                [
                    section_title(title),
                    ft.Text(description, size=FONT_SM, color=TEXT_MUTED),
                    ft.Column(
                        [
                            ft.Stack(
                                [self.placeholder, self.preview],
                                width=160,
                                height=100,
                            ),
                            self.btn_upload,
                            self.prev_strip.root,
                            self.resolve_strip.root,
                        ],
                        spacing=4,
                        tight=True,
                    ),
                    ft.Row([self.model_dd], spacing=0),
                    self.prompt,
                    *(
                        [self.prompt_favs.root]
                        if self.prompt_favs is not None
                        else []
                    ),
                    *[ft.Row([ctrl], spacing=0) for ctrl in self.extra],
                    self.strength if show_strength else ft.Container(height=0),
                    action_row,
                    self.cost_box,
                    self.job_progress.control,
                    self.status,
                ],
                spacing=8,
                tight=True,
            ),
        )

    def _cost(self) -> str:
        spec = find_tool(_dd_value(self.model_dd), self.model_registry)
        return format_tool_cost(spec) if spec else "Est. cost: —"

    async def _refresh_cost(self, e: ft.ControlEvent) -> None:
        self.cost_text.value = self._cost()
        self.page.update()

    def apply_key_gates(self) -> None:
        from media_studio.secrets_store import has_fal_key, has_xai_key

        ready = has_fal_key()
        if not self.state.is_busy("tools"):
            self.btn.disabled = not ready
            self.btn.tooltip = (
                None if ready else "Add your FAL API key in Settings to run tools"
            )
            if self.show_prompt and getattr(self, "btn_enhance", None) is not None:
                xai = has_xai_key()
                self.btn_enhance.disabled = not xai
                self.btn_enhance.tooltip = (
                    "Rewrite prompt for the selected model (does not change model)"
                    if xai
                    else "Add your xAI API key in Settings to Enhance prompts"
                )

    def _set_tool_status(self, msg: str, is_error: bool = False) -> None:
        self.status.value = msg
        self.status.color = "#e57373" if is_error else TEXT_MUTED
        try:
            self.page.update()
        except Exception:
            pass

    async def _on_enhance(self, e: ft.ControlEvent) -> None:
        if not self.show_prompt:
            return
        await run_prompt_enhance(
            page=self.page,
            state=self.state,
            prompt_field=self.prompt,
            get_model=lambda: _dd_value(self.model_dd),
            get_image=lambda: self.image_path,
            get_scenario=lambda: getattr(self.state, "scenario_label", None),
            status_ctrl=self.status,
            job_progress=self.job_progress,
            enhance_btn=self.btn_enhance,
            busy_controls=[self.btn],
            context_label="prompt",
        )
        self.apply_key_gates()
        try:
            self.page.update()
        except Exception:
            pass

    def _on_prev_source(self, path: str) -> None:
        self.load_image(path, status=f"Previous: {Path(path).name}")
        try:
            self.page.update()
        except Exception:
            pass

    def load_image(self, path: str, *, status: str | None = None) -> bool:
        """Load a still as this tool's source (Library / handoff)."""
        try:
            p = Path(path)
            if not p.is_file():
                self.status.value = f"Missing: {path}"
                return False
            self.image_path = str(p.resolve())
        except OSError:
            return False
        self.preview.src = self.image_path
        self.preview.visible = True
        self.placeholder.visible = False
        self.status.value = status or f"Loaded {Path(self.image_path).name}"
        try:
            self.prev_strip.record_and_refresh(self.image_path)
        except Exception:
            pass
        return True

    async def _pick(self, e: ft.ControlEvent) -> None:
        try:
            files = await pick_image(self.page, dialog_title="Choose image")
        except Exception as exc:
            self.status.value = f"Picker error: {exc}"
            self.page.update()
            return
        if not files or not files[0].path:
            return
        self.load_image(files[0].path)
        self.page.update()

    async def _run(self, e: ft.ControlEvent) -> None:
        if self.state.is_busy("tools"):
            return
        from media_studio.secrets_store import has_fal_key

        if not has_fal_key():
            self.status.value = "FAL API key required — open Settings (gear icon)."
            self.page.update()
            return
        if not self.image_path or not Path(self.image_path).is_file():
            self.status.value = "Upload an image first."
            self.page.update()
            return
        if not self.state.try_busy("tools"):
            return
        self.btn.disabled = True
        self.job_progress.start("Uploading…", self.page)
        self.status.value = "Running…"
        self.page.update()

        def on_progress(msg: str) -> None:
            self.job_progress.set_message(classify_progress(msg), self.page)

        kwargs = {
            "image_path": self.image_path,
            "model_label": _dd_value(self.model_dd),
            "output_dir": self.state.output_dir,
            "on_progress": on_progress,
        }
        if self.show_prompt:
            kwargs["prompt"] = self.prompt.value
        if self.show_strength:
            kwargs["strength"] = float(self.strength.value or 0.75)
        kwargs.update(self.get_extra_kwargs())
        try:
            from media_studio.job_context import to_thread_with_job

            result = await to_thread_with_job(self.state, self.run_fn, **kwargs)
            if result.ok and result.path:
                self._result_path = result.path
                show_result_actions(self.btn_folder, self.btn_resolve, visible=True)
                self.cost_text.value = result.cost_label or self._cost()
                done = result.status or "OK"
                self.job_progress.finish_ok(done, self.page)
                self.status.value = done
                _emit_tool_result(self, self.image_path, result.path)
            else:
                err = result.status or "Failed."
                self.job_progress.finish_error(err, self.page)
                self.status.value = err
        except TypeError:
            # Adapt kwargs for upscale which doesn't take prompt
            try:
                from media_studio.job_context import to_thread_with_job

                clean = {
                    "image_path": self.image_path,
                    "model_label": _dd_value(self.model_dd),
                    "output_dir": self.state.output_dir,
                    "on_progress": on_progress,
                    **self.get_extra_kwargs(),
                }
                result = await to_thread_with_job(self.state, self.run_fn, **clean)
                if result.ok and result.path:
                    self._result_path = result.path
                    show_result_actions(self.btn_folder, self.btn_resolve, visible=True)
                    self.cost_text.value = result.cost_label or self._cost()
                    done = result.status or "OK"
                    self.job_progress.finish_ok(done, self.page)
                    self.status.value = done
                    _emit_tool_result(self, self.image_path, result.path)
                else:
                    err = result.status or "Failed."
                    self.job_progress.finish_error(err, self.page)
                    self.status.value = err
            except Exception as exc:
                self.job_progress.finish_error(f"Error: {exc}", self.page)
                self.status.value = f"Error: {exc}"
                traceback.print_exc()
        except Exception as exc:
            self.job_progress.finish_error(f"Error: {exc}", self.page)
            self.status.value = f"Error: {exc}"
            traceback.print_exc()
        finally:
            self.state.clear_busy("tools")
            self.apply_key_gates()
            self.page.update()


class _RestoreCard:
    """
    Sharpen / Restore — Image or Video.

    Soft source (required) + optional sharp identity reference.
    Auto-built prompt, strength/fidelity, model defaults per mode.
    """

    def __init__(self, page: ft.Page, state: StudioState) -> None:
        self.page = page
        self.state = state
        self.source_path: str | None = None
        self.ref_path: str | None = None
        self._result_path: str | None = None
        self._mode = "image"  # image | video

        self.mode_dd = styled_dropdown(
            label_text="Mode",
            options=["Image", "Video"],
            value="Image",
            on_select=self._on_mode,
            expand=True,
        )
        self.mode_dd.visible = False  # Image|Video Tools groups lock mode
        self._mode_locked = True
        self.on_result = None
        self.tool_label = "Sharpen / Restore"

        # Soft source preview
        self.src_preview = ft.Image(
            src="", fit=ft.BoxFit.CONTAIN, width=140, height=90, visible=False
        )
        self.src_placeholder = ft.Container(
            content=ft.Text("Soft source", color=TEXT_MUTED, size=FONT_SM),
            alignment=ft.Alignment.CENTER,
            width=140,
            height=90,
            bgcolor=PANEL_ELEVATED,
            border_radius=6,
            border=ft.Border.all(1, BORDER),
        )
        self.src_video_label = ft.Text(
            "",
            size=FONT_SM,
            color=TEXT,
            visible=False,
            max_lines=3,
            text_align=ft.TextAlign.CENTER,
        )
        self.btn_upload_src = ft.OutlinedButton(
            content="Upload soft source",
            icon=ft.Icons.UPLOAD_FILE,
            on_click=self._pick_source,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
        )

        # Reference still
        self.ref_preview = ft.Image(
            src="", fit=ft.BoxFit.CONTAIN, width=140, height=90, visible=False
        )
        self.ref_placeholder = ft.Container(
            content=ft.Text("Ref (optional)", color=TEXT_MUTED, size=FONT_SM),
            alignment=ft.Alignment.CENTER,
            width=140,
            height=90,
            bgcolor=PANEL_ELEVATED,
            border_radius=6,
            border=ft.Border.all(1, BORDER),
        )
        self.btn_upload_ref = ft.OutlinedButton(
            content="Upload ref still",
            icon=ft.Icons.FACE,
            on_click=self._pick_ref,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
        )
        self.btn_clear_ref = ft.TextButton(
            content="Clear ref",
            on_click=self._clear_ref,
            style=ft.ButtonStyle(color=TEXT_MUTED),
            visible=False,
        )

        labels = restore_image_labels(has_reference=False)
        self.model_dd = styled_dropdown(
            label_text="Model",
            options=labels,
            value=labels[0] if labels else None,
            on_select=self._refresh_cost,
            expand=True,
        )
        from media_studio.flet_model_hint import make_best_for_line, update_best_for_line

        self.model_best_for = make_best_for_line()
        update_best_for_line(
            self.model_best_for, labels[0] if labels else None, dropdown=self.model_dd
        )

        self.prompt = ft.TextField(
            label="Prompt (auto-built — edit freely)",
            value=restore_prompt(None, has_reference=False, strength=0.75, mode="image"),
            multiline=True,
            min_lines=3,
            max_lines=5,
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
            surface="tools",
            get_meta=lambda: {
                "model": _dd_value(self.model_dd) if hasattr(self, "model_dd") else "",
                "source": "user",
            },
            on_status=lambda m: setattr(self.status, "value", m),
            show_pack_buttons=False,
        )
        self.strength = ft.Slider(
            min=0.2,
            max=1.0,
            divisions=16,
            value=0.75,
            label="Fidelity / strength {value}",
            active_color=ACCENT,
            on_change=self._on_strength,
        )
        self.strength_hint = ft.Text(
            "CodeFormer: higher = closer to original identity. "
            "NAFNet: whole-frame deblur (strength unused). "
            "Edit / ref models: higher = stronger restore in the prompt.",
            size=FONT_SM,
            color=TEXT_MUTED,
        )

        self.cost_text, self.cost_box = make_estimated_cost_box(initial="Est. cost: —")
        self.cost_text.value = self._cost()
        self.status = ft.Text("", size=FONT_SM, color=TEXT_MUTED, max_lines=4)
        self.job_progress = JobProgress()

        self.result = ft.Image(
            src="", fit=ft.BoxFit.CONTAIN, width=220, height=140, visible=False
        )
        self.result_video_label = ft.Text(
            "",
            size=FONT_SM,
            color=TEXT,
            visible=False,
            max_lines=3,
            selectable=True,
        )
        self.btn = ft.FilledButton(
            content="Restore",
            on_click=self._run,
            style=ft.ButtonStyle(bgcolor=ACCENT_BRIGHT, color=TEXT),
            height=40,
        )
        self.btn_enhance = make_enhance_button(on_click=self._on_enhance)
        self.state.on_keys_changed(self.apply_key_gates)
        self.apply_key_gates()
        self.prev_strip = PreviousSourcesStrip(
            page,
            get_output_dir=lambda: self.state.output_dir,
            on_load=self._on_prev_source,
            media_kind="image",
        )
        self.resolve_strip = ResolveSourcesStrip(
            page,
            on_load=self._on_prev_source,
            media_kind="image",
        )

        (
            self.result_actions_row,
            self.btn_folder,
            self.btn_resolve,
        ) = make_result_action_row(
            page,
            get_path=lambda: self._result_path,
            on_status=lambda msg, err: self._set_status(msg, err),
        )
        self.result_actions_row.visible = False

        # Stack Soft source + Reference still vertically — side-by-side clips
        # labels/upload at Tools form width (no horizontal overflow, no grey voids).
        self.root = ft.Container(
            bgcolor=PANEL,
            border=ft.Border.all(1, BORDER),
            border_radius=8,
            padding=12,
            content=ft.Column(
                [
                    section_title("Sharpen / Restore"),
                    ft.Text(
                        "Recover soft or out-of-focus faces (realtor shots). "
                        "Optional sharp reference locks identity — pose, body, "
                        "clothing, and background stay unchanged.",
                        size=FONT_SM,
                        color=TEXT_MUTED,
                    ),
                    label("Soft source", muted=True),
                    ft.Stack(
                        [
                            self.src_placeholder,
                            self.src_preview,
                            ft.Container(
                                content=self.src_video_label,
                                width=140,
                                height=90,
                                alignment=ft.Alignment.CENTER,
                                padding=6,
                            ),
                        ],
                        width=140,
                        height=90,
                    ),
                    self.btn_upload_src,
                    self.prev_strip.root,
                    self.resolve_strip.root,
                    ft.Divider(height=1, color=BORDER),
                    label("Reference still", muted=True),
                    ft.Stack(
                        [self.ref_placeholder, self.ref_preview],
                        width=140,
                        height=90,
                    ),
                    ft.Row(
                        [self.btn_upload_ref, self.btn_clear_ref],
                        spacing=8,
                        wrap=True,
                        tight=True,
                    ),
                    ft.Row([self.model_dd], spacing=0),
                    self.model_best_for,
                    self.prompt,
                    self.prompt_favs.root,
                    self.strength,
                    self.strength_hint,
                    ft.Row([self.btn_enhance, self.btn], spacing=8, wrap=True),
                    self.cost_box,
                    self.job_progress.control,
                    self.status,
                ],
                spacing=8,
                tight=True,
            ),
        )

    def force_mode(self, mode: str, *, clear_source: bool = False) -> None:
        want = "video" if str(mode).lower() == "video" else "image"
        self._mode_locked = True
        try:
            self.mode_dd.visible = False
            self.mode_dd.value = "Video" if want == "video" else "Image"
        except Exception:
            pass
        prev = self._mode
        self._mode = want
        if prev != want:
            self.source_path = None
            self.src_preview.src = ""
            self.src_preview.visible = False
            self.src_video_label.value = ""
            self.src_video_label.visible = False
            self.src_placeholder.visible = True
        self.btn_upload_src.content = (
            "Upload soft video" if want == "video" else "Upload soft source"
        )
        try:
            self.prev_strip.set_media_kind(want)
            self.resolve_strip.set_media_kind(want)
        except Exception:
            pass
        self._refresh_models()
        self._rebuild_prompt(force=False)

    def _has_ref(self) -> bool:
        return bool(self.ref_path and Path(self.ref_path).is_file())

    def _registry(self) -> dict:
        if self._mode == "video":
            return RESTORE_VIDEO_MODELS
        return restore_image_registry(has_reference=self._has_ref())

    def _cost(self) -> str:
        spec = find_tool(_dd_value(self.model_dd), self._registry())
        return format_tool_cost(spec) if spec else "Est. cost: —"

    def _set_status(self, msg: str, is_error: bool = False) -> None:
        self.status.value = msg
        self.status.color = "#e57373" if is_error else TEXT_MUTED
        try:
            self.page.update()
        except Exception:
            pass

    def apply_key_gates(self) -> None:
        from media_studio.secrets_store import has_fal_key, has_xai_key

        ready = has_fal_key()
        if not self.state.is_busy("tools"):
            self.btn.disabled = not ready
            self.btn.tooltip = (
                None if ready else "Add your FAL API key in Settings to run tools"
            )
            xai = has_xai_key()
            self.btn_enhance.disabled = not xai
            self.btn_enhance.tooltip = (
                "Rewrite prompt for the selected model (does not change model)"
                if xai
                else "Add your xAI API key in Settings to Enhance prompts"
            )

    async def _on_enhance(self, e: ft.ControlEvent) -> None:
        await run_prompt_enhance(
            page=self.page,
            state=self.state,
            prompt_field=self.prompt,
            get_model=lambda: _dd_value(self.model_dd),
            get_image=lambda: self.source_path if self._mode != "video" else self.ref_path,
            get_video=lambda: self.source_path if self._mode == "video" else None,
            status_ctrl=self.status,
            job_progress=self.job_progress,
            enhance_btn=self.btn_enhance,
            busy_controls=[self.btn],
        )
        self.apply_key_gates()
        try:
            self.page.update()
        except Exception:
            pass

    def _rebuild_prompt(self, *, force: bool = False) -> None:
        """Refresh auto prompt when mode/ref/strength change, unless user heavily edited."""
        current = (self.prompt.value or "").strip()
        # Refresh if empty, still the stock core, or force
        stockish = (
            not current
            or RESTORE_PROMPT_CORE[:60] in current
            or current.startswith("Restore sharpness")
        )
        if force or stockish:
            self.prompt.value = restore_prompt(
                None if stockish else current,
                has_reference=self._has_ref(),
                strength=float(self.strength.value or 0.75),
                mode=self._mode,
            )

    def _refresh_models(self) -> None:
        if self._mode == "video":
            labels = restore_video_labels()
        else:
            labels = restore_image_labels(has_reference=self._has_ref())
        prev = _dd_value(self.model_dd)
        self.model_dd.options = dropdown_options(labels)
        if prev in labels:
            self.model_dd.value = prev
        else:
            self.model_dd.value = labels[0] if labels else None
        self.cost_text.value = self._cost()
        self._sync_restore_model_ui()

    async def _on_mode(self, e: ft.ControlEvent) -> None:
        self._mode = "video" if (_dd_value(self.mode_dd) or "").lower() == "video" else "image"
        # Clear source when switching modality (image vs video file)
        self.source_path = None
        self.src_preview.src = ""
        self.src_preview.visible = False
        self.src_video_label.value = ""
        self.src_video_label.visible = False
        self.src_placeholder.visible = True
        self.src_placeholder.content = ft.Text(
            "Soft video" if self._mode == "video" else "Soft source",
            color=TEXT_MUTED,
            size=FONT_SM,
        )
        self.btn_upload_src.content = (
            "Upload soft video" if self._mode == "video" else "Upload soft source"
        )
        try:
            kind = "video" if self._mode == "video" else "image"
            self.prev_strip.set_media_kind(kind)
            self.resolve_strip.set_media_kind(kind)
        except Exception:
            pass
        self._refresh_models()
        self._rebuild_prompt(force=True)
        self.page.update()

    async def _on_strength(self, e: ft.ControlEvent) -> None:
        self._rebuild_prompt(force=False)
        self.page.update()

    async def _refresh_cost(self, e: ft.ControlEvent) -> None:
        self.cost_text.value = self._cost()
        try:
            from media_studio.flet_model_hint import update_best_for_line

            update_best_for_line(
                self.model_best_for,
                _dd_value(self.model_dd),
                dropdown=self.model_dd,
            )
        except Exception:
            pass
        self._sync_restore_model_ui()
        self.page.update()

    def _sync_restore_model_ui(self) -> None:
        """Show/hide strength & prompt notes by model (ref still only when used)."""
        if self._mode == "video":
            try:
                self.strength.visible = True
                self.strength_hint.visible = True
                self.prompt.visible = True
                self.btn_enhance.visible = True
            except Exception:
                pass
            return
        spec = find_tool(_dd_value(self.model_dd), self._registry())
        ep = (spec.endpoint if spec else "") or ""
        is_naf = "nafnet" in ep
        is_cf = "codeformer" in ep
        try:
            # NAFNet: no prompt / fidelity; CodeFormer: fidelity slider, no prompt needed
            self.strength.visible = not is_naf
            self.strength_hint.visible = True
            if is_naf:
                self.strength_hint.value = (
                    "NAFNet deblur is whole-frame — no prompt, no ref still. "
                    f"{(spec.notes or '') if spec else ''}"
                )
            elif is_cf:
                self.strength_hint.value = (
                    "CodeFormer fidelity: higher = closer to original identity. "
                    "Reference still is not used by this model."
                )
            else:
                self.strength_hint.value = (
                    "Edit / ref-identity models: higher strength = stronger restore "
                    "in the auto-built prompt. Upload a sharp ref still for identity lock."
                )
            self.prompt.visible = not is_naf and not is_cf
            self.btn_enhance.visible = not is_naf and not is_cf
            if hasattr(self, "prompt_favs") and self.prompt_favs is not None:
                try:
                    self.prompt_favs.root.visible = not is_naf and not is_cf
                except Exception:
                    pass
        except Exception:
            pass

    def _on_prev_source(self, path: str) -> None:
        ext = Path(path).suffix.lower()
        as_vid = ext in {".mp4", ".mov", ".webm", ".m4v", ".avi", ".mkv"}
        self.load_source(path, as_video=as_vid, status=f"Previous: {Path(path).name}")
        try:
            self.page.update()
        except Exception:
            pass

    def load_source(self, path: str, *, as_video: bool = False, status: str | None = None) -> bool:
        """Load soft source still or video (Library handoff)."""
        try:
            p = Path(path)
            if not p.is_file():
                self.status.value = f"Missing: {path}"
                return False
            resolved = str(p.resolve())
        except OSError:
            return False
        self._mode = "video" if as_video else "image"
        try:
            self.mode_dd.value = "Video" if as_video else "Image"
        except Exception:
            pass
        self.source_path = resolved
        name = Path(resolved).name
        if as_video:
            self.src_preview.visible = False
            self.src_placeholder.visible = False
            self.src_video_label.value = name
            self.src_video_label.visible = True
            try:
                self.btn_upload_src.content = "Upload soft video"
            except Exception:
                pass
        else:
            self.src_video_label.visible = False
            self.src_preview.src = resolved
            self.src_preview.visible = True
            self.src_placeholder.visible = False
            try:
                self.btn_upload_src.content = "Upload soft source"
            except Exception:
                pass
        try:
            kind = "video" if as_video else "image"
            self.prev_strip.set_media_kind(kind)
            self.resolve_strip.set_media_kind(kind)
            self.prev_strip.record_and_refresh(resolved)
        except Exception:
            pass
        self._refresh_models()
        self._rebuild_prompt(force=False)
        self.status.value = status or f"Loaded source {name}"
        return True

    async def _pick_source(self, e: ft.ControlEvent) -> None:
        try:
            if self._mode == "video":
                files = await pick_video(self.page, dialog_title="Soft / out-of-focus video")
            else:
                files = await pick_image(self.page, dialog_title="Soft / out-of-focus image")
        except Exception as exc:
            self.status.value = f"Picker error: {exc}"
            self.page.update()
            return
        if not files or not files[0].path:
            return
        self.load_source(files[0].path, as_video=(self._mode == "video"))
        self.page.update()

    async def _pick_ref(self, e: ft.ControlEvent) -> None:
        try:
            files = await pick_image(
                self.page, dialog_title="Sharp reference of the same person"
            )
        except Exception as exc:
            self.status.value = f"Picker error: {exc}"
            self.page.update()
            return
        if not files or not files[0].path:
            return
        self.ref_path = str(Path(files[0].path).resolve())
        self.ref_preview.src = self.ref_path
        self.ref_preview.visible = True
        self.ref_placeholder.visible = False
        self.btn_clear_ref.visible = True
        self._refresh_models()
        self._rebuild_prompt(force=True)
        self.status.value = f"Reference {Path(self.ref_path).name} — identity lock enabled"
        self.page.update()

    async def _clear_ref(self, e: ft.ControlEvent) -> None:
        self.ref_path = None
        self.ref_preview.src = ""
        self.ref_preview.visible = False
        self.ref_placeholder.visible = True
        self.btn_clear_ref.visible = False
        self._refresh_models()
        self._rebuild_prompt(force=True)
        self.status.value = "Reference cleared"
        self.page.update()

    def apply_resolve_media(
        self,
        *,
        still_path: str | None = None,
        video_path: str | None = None,
        clip_name: str | None = None,
    ) -> None:
        """Optional pre-fill for Sharpen/Restore from Resolve handoff."""
        name = (clip_name or "Resolve clip").strip()
        if video_path and Path(video_path).is_file():
            self._mode = "video"
            self.mode_dd.value = "Video"
            self.source_path = str(Path(video_path).resolve())
            self.src_preview.visible = False
            self.src_placeholder.visible = False
            self.src_video_label.value = Path(self.source_path).name
            self.src_video_label.visible = True
            self.btn_upload_src.content = "Upload soft video"
            self.src_placeholder.content = ft.Text(
                "Soft video", color=TEXT_MUTED, size=FONT_SM
            )
        elif still_path and Path(still_path).is_file():
            self._mode = "image"
            self.mode_dd.value = "Image"
            self.source_path = str(Path(still_path).resolve())
            self.src_video_label.visible = False
            self.src_preview.src = self.source_path
            self.src_preview.visible = True
            self.src_placeholder.visible = False
            self.btn_upload_src.content = "Upload soft source"
        if still_path and Path(still_path).is_file() and self._mode == "video":
            # Use still as identity reference when video is the soft source
            self.ref_path = str(Path(still_path).resolve())
            self.ref_preview.src = self.ref_path
            self.ref_preview.visible = True
            self.ref_placeholder.visible = False
            self.btn_clear_ref.visible = True
        self._refresh_models()
        self._rebuild_prompt(force=True)
        self.status.value = f"From Resolve: {name}"
        try:
            self.page.update()
        except Exception:
            pass

    async def _run(self, e: ft.ControlEvent) -> None:
        if self.state.is_busy("tools"):
            return
        from media_studio.secrets_store import has_fal_key

        if not has_fal_key():
            self.status.value = "FAL API key required — open Settings (gear icon)."
            self.page.update()
            return
        if not self.source_path or not Path(self.source_path).is_file():
            self.status.value = (
                "Upload a soft source video first."
                if self._mode == "video"
                else "Upload a soft source image first."
            )
            self.page.update()
            return

        if not self.state.try_busy("tools"):
            return
        self.btn.disabled = True
        self.job_progress.start("Uploading…", self.page)
        self.status.value = "Running restore…"
        self.page.update()

        def on_progress(msg: str) -> None:
            self.job_progress.set_message(classify_progress(msg), self.page)

        try:
            from media_studio.job_context import to_thread_with_job

            result = await to_thread_with_job(
                self.state,
                run_restore,
                mode=self._mode,
                source_path=self.source_path,
                reference_path=self.ref_path,
                model_label=_dd_value(self.model_dd),
                prompt=self.prompt.value,
                strength=float(self.strength.value or 0.75),
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
                _emit_tool_result(self, self.source_path, result.path)
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


class _ReAspectCard:
    """Re-Aspect — Image or Video intelligent reframe / outpaint."""

    def __init__(self, page: ft.Page, state: StudioState) -> None:
        self.page = page
        self.state = state
        self.source_path: str | None = None
        self._result_path: str | None = None
        self._mode = "image"

        self.mode_dd = styled_dropdown(
            label_text="Mode",
            options=["Image", "Video"],
            value="Image",
            on_select=self._on_mode,
            expand=True,
        )
        self.mode_dd.visible = False
        self._mode_locked = True
        self.on_result = None
        self.tool_label = "Re-Aspect"
        self.aspect_dd = styled_dropdown(
            label_text="Target aspect",
            options=REASPECT_ASPECT_CHOICES,
            value="9:16 (Vertical / Reels)",
            on_select=self._on_aspect,
            expand=True,
        )

        self.src_preview = ft.Image(
            src="", fit=ft.BoxFit.CONTAIN, width=140, height=90, visible=False
        )
        self.src_placeholder = ft.Container(
            content=ft.Text("Source image", color=TEXT_MUTED, size=FONT_SM),
            alignment=ft.Alignment.CENTER,
            width=140,
            height=90,
            bgcolor=PANEL_ELEVATED,
            border_radius=6,
            border=ft.Border.all(1, BORDER),
        )
        self.src_video_label = ft.Text(
            "", size=FONT_SM, color=TEXT, visible=False, max_lines=3,
            text_align=ft.TextAlign.CENTER,
        )
        self.btn_upload = ft.OutlinedButton(
            content="Upload source",
            icon=ft.Icons.UPLOAD_FILE,
            on_click=self._pick_source,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
        )

        labels = reaspect_image_labels()
        self.model_dd = styled_dropdown(
            label_text="Model",
            options=labels,
            value=labels[0] if labels else None,
            on_select=self._refresh_cost,
            expand=True,
        )
        self.prompt = ft.TextField(
            label="Prompt (auto-built — edit freely)",
            value=reaspect_prompt(
                None, aspect_ratio="9:16 (Vertical / Reels)", mode="image"
            ),
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
        from media_studio.flet_prompt_favorites import make_prompt_favorites_bar

        self.prompt_favs = make_prompt_favorites_bar(
            page,
            get_text=lambda: self.prompt.value,
            set_text=lambda t: setattr(self.prompt, "value", t),
            surface="tools",
            get_meta=lambda: {
                "model": _dd_value(self.model_dd) if hasattr(self, "model_dd") else "",
                "source": "user",
            },
            on_status=lambda m: setattr(self.status, "value", m),
            show_pack_buttons=False,
        )
        self.cost_text, self.cost_box = make_estimated_cost_box(initial="Est. cost: —")
        self.cost_text.value = self._cost()
        self.status = ft.Text("", size=FONT_SM, color=TEXT_MUTED, max_lines=4)
        self.job_progress = JobProgress()
        self.result = ft.Image(
            src="", fit=ft.BoxFit.CONTAIN, width=220, height=140, visible=False
        )
        self.result_video_label = ft.Text(
            "", size=FONT_SM, color=TEXT, visible=False, max_lines=3, selectable=True
        )
        self.btn = ft.FilledButton(
            content="Re-aspect",
            on_click=self._run,
            style=ft.ButtonStyle(bgcolor=ACCENT_BRIGHT, color=TEXT),
            height=40,
        )
        self.btn_enhance = make_enhance_button(on_click=self._on_enhance)
        self.state.on_keys_changed(self.apply_key_gates)
        self.apply_key_gates()
        self.prev_strip = PreviousSourcesStrip(
            page,
            get_output_dir=lambda: self.state.output_dir,
            on_load=self._on_prev_source,
            media_kind="image",
        )
        self.resolve_strip = ResolveSourcesStrip(
            page,
            on_load=self._on_prev_source,
            media_kind="image",
        )
        (
            self.result_actions_row,
            self.btn_folder,
            self.btn_resolve,
        ) = make_result_action_row(
            page,
            get_path=lambda: self._result_path,
            on_status=lambda msg, err: self._set_status(msg, err),
        )
        self.result_actions_row.visible = False

        self.root = ft.Container(
            bgcolor=PANEL,
            border=ft.Border.all(1, BORDER),
            border_radius=8,
            padding=12,
            content=ft.Column(
                [
                    section_title("Re-Aspect"),
                    ft.Text(
                        "Change aspect ratio via intelligent reframe / outpaint "
                        "(e.g. Horizontal → Vertical 9:16 for Reels). "
                        "Preserves subject; fills new edges coherently.",
                        size=FONT_SM,
                        color=TEXT_MUTED,
                    ),
                    ft.Column(
                        [
                            label("Source", muted=True),
                            ft.Stack(
                                [
                                    self.src_placeholder,
                                    self.src_preview,
                                    ft.Container(
                                        content=self.src_video_label,
                                        width=140,
                                        height=90,
                                        alignment=ft.Alignment.CENTER,
                                        padding=6,
                                    ),
                                ],
                                width=140,
                                height=90,
                            ),
                            self.btn_upload,
                            self.prev_strip.root,
                            self.resolve_strip.root,
                        ],
                        spacing=4,
                        tight=True,
                    ),
                    ft.Row([self.aspect_dd], spacing=0),
                    ft.Row([self.model_dd], spacing=0),
                    self.prompt,
                    self.prompt_favs.root,
                    ft.Row([self.btn_enhance, self.btn], spacing=8, wrap=True),
                    self.cost_box,
                    self.job_progress.control,
                    self.status,
                ],
                spacing=8,
                tight=True,
            ),
        )

    def _registry(self) -> dict:
        return REASPECT_VIDEO_MODELS if self._mode == "video" else REASPECT_IMAGE_MODELS

    def _cost(self) -> str:
        spec = find_tool(_dd_value(self.model_dd), self._registry())
        return format_tool_cost(spec) if spec else "Est. cost: —"

    def _set_status(self, msg: str, is_error: bool = False) -> None:
        self.status.value = msg
        self.status.color = "#e57373" if is_error else TEXT_MUTED
        try:
            self.page.update()
        except Exception:
            pass

    def apply_key_gates(self) -> None:
        from media_studio.secrets_store import has_fal_key, has_xai_key

        ready = has_fal_key()
        if not self.state.is_busy("tools"):
            self.btn.disabled = not ready
            self.btn.tooltip = (
                None if ready else "Add your FAL API key in Settings to run tools"
            )
            xai = has_xai_key()
            self.btn_enhance.disabled = not xai
            self.btn_enhance.tooltip = (
                "Rewrite prompt for the selected model (does not change model)"
                if xai
                else "Add your xAI API key in Settings to Enhance prompts"
            )

    async def _on_enhance(self, e: ft.ControlEvent) -> None:
        await run_prompt_enhance(
            page=self.page,
            state=self.state,
            prompt_field=self.prompt,
            get_model=lambda: _dd_value(self.model_dd),
            get_image=lambda: self.source_path if self._mode != "video" else None,
            get_video=lambda: self.source_path if self._mode == "video" else None,
            status_ctrl=self.status,
            job_progress=self.job_progress,
            enhance_btn=self.btn_enhance,
            busy_controls=[self.btn],
        )
        self.apply_key_gates()
        try:
            self.page.update()
        except Exception:
            pass

    def force_mode(self, mode: str, *, clear_source: bool = False) -> None:
        want = "video" if str(mode).lower() == "video" else "image"
        self._mode_locked = True
        try:
            self.mode_dd.visible = False
            self.mode_dd.value = "Video" if want == "video" else "Image"
        except Exception:
            pass
        prev = self._mode
        self._mode = want
        if prev != want:
            self.source_path = None
            self.src_preview.src = ""
            self.src_preview.visible = False
            self.src_video_label.value = ""
            self.src_video_label.visible = False
            self.src_placeholder.visible = True
        self.src_placeholder.content = ft.Text(
            "Source video" if want == "video" else "Source image",
            color=TEXT_MUTED,
            size=FONT_SM,
        )
        self.btn_upload.content = (
            "Upload video" if want == "video" else "Upload source"
        )
        try:
            self.prev_strip.set_media_kind(want)
            self.resolve_strip.set_media_kind(want)
        except Exception:
            pass
        self._refresh_models()
        self._rebuild_prompt()

    def _rebuild_prompt(self) -> None:
        current = (self.prompt.value or "").strip()
        stockish = (
            not current
            or REASPECT_PROMPT_CORE[:40] in current
            or current.startswith("Reframe this")
        )
        if stockish:
            self.prompt.value = reaspect_prompt(
                None,
                aspect_ratio=_dd_value(self.aspect_dd) or "9:16",
                mode=self._mode,
            )

    def _refresh_models(self) -> None:
        labels = (
            reaspect_video_labels()
            if self._mode == "video"
            else reaspect_image_labels()
        )
        prev = _dd_value(self.model_dd)
        self.model_dd.options = dropdown_options(labels)
        self.model_dd.value = prev if prev in labels else (labels[0] if labels else None)
        self.cost_text.value = self._cost()

    async def _on_mode(self, e: ft.ControlEvent) -> None:
        if getattr(self, "_mode_locked", False):
            return
        self._mode = (
            "video" if (_dd_value(self.mode_dd) or "").lower() == "video" else "image"
        )
        self.source_path = None
        self.src_preview.src = ""
        self.src_preview.visible = False
        self.src_video_label.value = ""
        self.src_video_label.visible = False
        self.src_placeholder.visible = True
        self.src_placeholder.content = ft.Text(
            "Source video" if self._mode == "video" else "Source image",
            color=TEXT_MUTED,
            size=FONT_SM,
        )
        self.btn_upload.content = (
            "Upload video" if self._mode == "video" else "Upload source"
        )
        try:
            kind = "video" if self._mode == "video" else "image"
            self.prev_strip.set_media_kind(kind)
            self.resolve_strip.set_media_kind(kind)
        except Exception:
            pass
        self._refresh_models()
        self._rebuild_prompt()
        self.page.update()

    async def _on_aspect(self, e: ft.ControlEvent) -> None:
        self._rebuild_prompt()
        self.page.update()

    async def _refresh_cost(self, e: ft.ControlEvent) -> None:
        self.cost_text.value = self._cost()
        self.page.update()

    def _on_prev_source(self, path: str) -> None:
        ext = Path(path).suffix.lower()
        as_vid = ext in {".mp4", ".mov", ".webm", ".m4v", ".avi", ".mkv"}
        self.load_source(path, as_video=as_vid, status=f"Previous: {Path(path).name}")
        try:
            self.page.update()
        except Exception:
            pass

    def load_source(self, path: str, *, as_video: bool = False, status: str | None = None) -> bool:
        """Load image or video for re-aspect (Library handoff)."""
        try:
            p = Path(path)
            if not p.is_file():
                self.status.value = f"Missing: {path}"
                return False
            resolved = str(p.resolve())
        except OSError:
            return False
        self._mode = "video" if as_video else "image"
        try:
            self.mode_dd.value = "Video" if as_video else "Image"
        except Exception:
            pass
        self.source_path = resolved
        name = Path(resolved).name
        if as_video:
            self.src_preview.visible = False
            self.src_placeholder.visible = False
            self.src_video_label.value = name
            self.src_video_label.visible = True
            try:
                self.btn_upload.content = "Upload video"
            except Exception:
                pass
        else:
            self.src_video_label.visible = False
            self.src_preview.src = resolved
            self.src_preview.visible = True
            self.src_placeholder.visible = False
            try:
                self.btn_upload.content = "Upload source"
            except Exception:
                pass
        try:
            kind = "video" if as_video else "image"
            self.prev_strip.set_media_kind(kind)
            self.resolve_strip.set_media_kind(kind)
            self.prev_strip.record_and_refresh(resolved)
        except Exception:
            pass
        self._refresh_models()
        self._rebuild_prompt()
        self.status.value = status or f"Loaded {name}"
        return True

    async def _pick_source(self, e: ft.ControlEvent) -> None:
        try:
            if self._mode == "video":
                files = await pick_video(self.page, dialog_title="Video to re-aspect")
            else:
                files = await pick_image(self.page, dialog_title="Image to re-aspect")
        except Exception as exc:
            self.status.value = f"Picker error: {exc}"
            self.page.update()
            return
        if not files or not files[0].path:
            return
        self.load_source(files[0].path, as_video=(self._mode == "video"))
        self.page.update()

    async def _run(self, e: ft.ControlEvent) -> None:
        if self.state.is_busy("tools"):
            return
        from media_studio.secrets_store import has_fal_key

        if not has_fal_key():
            self.status.value = "FAL API key required — open Settings (gear icon)."
            self.page.update()
            return
        if not self.source_path or not Path(self.source_path).is_file():
            self.status.value = (
                "Upload a source video first."
                if self._mode == "video"
                else "Upload a source image first."
            )
            self.page.update()
            return

        if not self.state.try_busy("tools"):
            return
        self.btn.disabled = True
        self.job_progress.start("Uploading…", self.page)
        self.status.value = "Running re-aspect…"
        self.page.update()

        def on_progress(msg: str) -> None:
            self.job_progress.set_message(classify_progress(msg), self.page)

        try:
            from media_studio.job_context import to_thread_with_job

            result = await to_thread_with_job(
                self.state,
                run_reaspect,
                mode=self._mode,
                source_path=self.source_path,
                model_label=_dd_value(self.model_dd),
                aspect_ratio=_dd_value(self.aspect_dd),
                prompt=self.prompt.value,
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
                _emit_tool_result(self, self.source_path, result.path)
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


class _UpscaleCard:
    """Upscale — Image or Video mode with fal image / video upscalers."""

    def __init__(self, page: ft.Page, state: StudioState) -> None:
        self.page = page
        self.state = state
        self.source_path: str | None = None
        self._result_path: str | None = None
        self._mode = "image"  # image | video
        self._video_duration_s: float | None = None  # probed for video cost/run

        self.mode_dd = styled_dropdown(
            label_text="Mode",
            options=["Image", "Video"],
            value="Image",
            on_select=self._on_mode,
            expand=True,
        )
        self.mode_dd.visible = False
        self._mode_locked = True
        self.on_result = None
        self.tool_label = "Upscale"
        self.src_preview = ft.Image(
            src="", fit=ft.BoxFit.CONTAIN, width=140, height=90, visible=False
        )
        self.src_placeholder = ft.Container(
            content=ft.Text("Source image", color=TEXT_MUTED, size=FONT_SM),
            alignment=ft.Alignment.CENTER,
            width=140,
            height=90,
            bgcolor=PANEL_ELEVATED,
            border_radius=6,
            border=ft.Border.all(1, BORDER),
        )
        self.src_video_label = ft.Text(
            "",
            size=FONT_SM,
            color=TEXT,
            visible=False,
            max_lines=3,
            text_align=ft.TextAlign.CENTER,
        )
        self.btn_upload = ft.OutlinedButton(
            content="Upload image",
            icon=ft.Icons.UPLOAD_FILE,
            on_click=self._pick_source,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
        )

        img_labels = upscale_labels()
        self.model_dd = styled_dropdown(
            label_text="Model",
            options=img_labels,
            value=img_labels[0] if img_labels else None,
            on_select=self._refresh_cost,
            expand=True,
        )
        self.model_notes = ft.Text(
            "",
            size=FONT_SM,
            color=TEXT_MUTED,
            max_lines=3,
        )
        self.up_factor = styled_dropdown(
            label_text="Scale",
            options=["2", "3", "4"],
            value="2",
            on_select=self._refresh_cost,
            expand=True,
        )
        self.target_dd = styled_dropdown(
            label_text="Target",
            options=list(VIDEO_UPSCALE_TARGETS),
            value=VIDEO_UPSCALE_TARGETS[0],
            on_select=self._refresh_cost,
            expand=True,
        )
        self.target_dd.visible = False  # video mode only; toggled in _refresh_models
        self.cost_text, self.cost_box = make_estimated_cost_box(initial="Est. cost: —")
        self.cost_text.value = self._cost()
        self.status = ft.Text("", size=FONT_SM, color=TEXT_MUTED, max_lines=4)
        self.job_progress = JobProgress()
        self.btn = ft.FilledButton(
            content="Run upscale",
            on_click=self._run,
            style=ft.ButtonStyle(bgcolor=ACCENT_BRIGHT, color=TEXT),
        )
        self.result = ft.Image(
            src="", fit=ft.BoxFit.CONTAIN, width=220, height=160, visible=False
        )
        self.result_video_label = ft.Text(
            "", size=FONT_SM, color=TEXT, visible=False, max_lines=3
        )
        self.result_actions_row, self.btn_folder, self.btn_resolve = make_result_action_row(
            page,
            get_path=lambda: self._result_path,
            on_status=self._set_status,
        )
        show_result_actions(self.btn_folder, self.btn_resolve, visible=False)
        self.result_actions_row.visible = False
        self.state.on_keys_changed(self.apply_key_gates)
        self.apply_key_gates()
        self.prev_strip = PreviousSourcesStrip(
            page,
            get_output_dir=lambda: self.state.output_dir,
            on_load=self._on_prev_source,
            media_kind="image",
        )
        self.resolve_strip = ResolveSourcesStrip(
            page,
            on_load=self._on_prev_source,
            media_kind="image",
        )

        self.root = panel(
            ft.Column(
                [
                    section_title("Upscale"),
                    ft.Text(
                        "Image: Topaz / SeedVR / Recraft. "
                        "Video: SeedVR2 · Bytedance · Topaz families "
                        "(Proteus general · Artemis denoise+sharpen · Nyx denoise · "
                        "Starlight generative · Gaia renders) · RealESRGAN. "
                        "For high-ISO cleanup without a big scale-up, use Video Denoise.",
                        size=FONT_SM,
                        color=TEXT_MUTED,
                    ),
                    ft.Column(
                        [
                            self.src_preview,
                            self.src_placeholder,
                            self.src_video_label,
                            self.btn_upload,
                            self.prev_strip.root,
                            self.resolve_strip.root,
                        ],
                        spacing=6,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        tight=True,
                    ),
                    ft.Row([self.model_dd], spacing=0),
                    self.model_notes,
                    ft.Row([self.up_factor], spacing=0),
                    ft.Row([self.target_dd], spacing=0),
                    self.btn,
                    self.cost_box,
                    self.job_progress.control,
                    self.status,
                ],
                spacing=8,
                tight=True,
            ),
        )

    def _registry(self) -> dict:
        return VIDEO_UPSCALERS if self._mode == "video" else UPSCALERS

    def _cost(self) -> str:
        spec = find_tool(_dd_value(self.model_dd), self._registry())
        if not spec:
            return "Est. cost: —"
        if self._mode == "video":
            dur = float(self._video_duration_s or 8.0)
            if self._video_duration_s is None:
                return (
                    format_video_upscale_cost(
                        spec,
                        target_label=_dd_value(self.target_dd),
                        duration_s=dur,
                    )
                    + " · duration unknown (est. 8s)"
                )
            return format_video_upscale_cost(
                spec,
                target_label=_dd_value(self.target_dd),
                duration_s=dur,
            )
        return format_tool_cost(spec)

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
        if not self.state.is_busy("tools"):
            self.btn.disabled = not ready
            self.btn.tooltip = (
                None if ready else "Add your FAL API key in Settings to run tools"
            )

    def _refresh_models(self) -> None:
        labels = video_upscale_labels() if self._mode == "video" else upscale_labels()
        prev = _dd_value(self.model_dd)
        # Map legacy "Topaz Video Upscale" → Proteus family label
        if prev and "topaz" in prev.lower() and "proteus" not in prev.lower():
            if "legacy" in prev.lower() or prev == "Topaz Video Upscale":
                for lab in labels:
                    if "proteus" in lab.lower():
                        prev = lab
                        break
        self.model_dd.options = dropdown_options(labels)
        self.model_dd.value = prev if prev in labels else (labels[0] if labels else None)
        self.up_factor.visible = self._mode == "image"
        self.target_dd.visible = self._mode == "video"
        self.cost_text.value = self._cost()
        self._sync_model_notes()

    def _sync_model_notes(self) -> None:
        if not hasattr(self, "model_notes"):
            return
        spec = find_tool(_dd_value(self.model_dd), self._registry())
        self.model_notes.value = (spec.notes if spec else "") or ""

    def force_mode(self, mode: str, *, clear_source: bool = False) -> None:
        want = "video" if str(mode).lower() == "video" else "image"
        self._mode_locked = True
        try:
            self.mode_dd.visible = False
            self.mode_dd.value = "Video" if want == "video" else "Image"
        except Exception:
            pass
        prev = self._mode
        self._mode = want
        if prev != want:
            self.source_path = None
            self.src_preview.src = ""
            self.src_preview.visible = False
            self.src_video_label.value = ""
            self.src_video_label.visible = False
            self.src_placeholder.visible = True
        self.src_placeholder.content = ft.Text(
            "Source video" if want == "video" else "Source image",
            color=TEXT_MUTED,
            size=FONT_SM,
        )
        self.btn_upload.content = (
            "Upload video" if want == "video" else "Upload image"
        )
        try:
            self.prev_strip.set_media_kind(want)
            self.resolve_strip.set_media_kind(want)
        except Exception:
            pass
        self._refresh_models()

    async def _on_mode(self, e: ft.ControlEvent) -> None:
        if getattr(self, "_mode_locked", False):
            return
        self._mode = (
            "video" if (_dd_value(self.mode_dd) or "").lower() == "video" else "image"
        )
        self.source_path = None
        self.src_preview.src = ""
        self.src_preview.visible = False
        self.src_video_label.value = ""
        self.src_video_label.visible = False
        self.src_placeholder.visible = True
        self.src_placeholder.content = ft.Text(
            "Source video" if self._mode == "video" else "Source image",
            color=TEXT_MUTED,
            size=FONT_SM,
        )
        self.btn_upload.content = (
            "Upload video" if self._mode == "video" else "Upload image"
        )
        try:
            kind = "video" if self._mode == "video" else "image"
            self.prev_strip.set_media_kind(kind)
            self.resolve_strip.set_media_kind(kind)
        except Exception:
            pass
        self._refresh_models()
        self.page.update()

    async def _refresh_cost(self, e: ft.ControlEvent) -> None:
        self.cost_text.value = self._cost()
        self._sync_model_notes()
        self.page.update()

    def load_image(self, path: str, *, status: str | None = None) -> bool:
        return self.load_source(path, as_video=False, status=status)

    def _on_prev_source(self, path: str) -> None:
        ext = Path(path).suffix.lower()
        as_vid = ext in {".mp4", ".mov", ".webm", ".m4v", ".avi", ".mkv"}
        self.load_source(path, as_video=as_vid, status=f"Previous: {Path(path).name}")
        try:
            self.page.update()
        except Exception:
            pass

    def load_source(self, path: str, *, as_video: bool = False, status: str | None = None) -> bool:
        try:
            p = Path(path)
            if not p.is_file():
                self.status.value = f"Missing: {path}"
                return False
            resolved = str(p.resolve())
        except OSError:
            return False
        # Locked Image/Video tools group: reject wrong media type
        if getattr(self, "_mode_locked", False):
            want_video = self._mode == "video"
            if as_video != want_video:
                self.status.value = (
                    "This is a Video tool — upload a video clip."
                    if want_video
                    else "This is an Image tool — upload a still."
                )
                self.status.color = "#e57373"
                return False
        self._mode = "video" if as_video else "image"
        try:
            self.mode_dd.value = "Video" if as_video else "Image"
        except Exception:
            pass
        self.source_path = resolved
        self._video_duration_s = None
        name = Path(resolved).name
        if as_video:
            self.src_preview.visible = False
            self.src_placeholder.visible = False
            try:
                self.btn_upload.content = "Upload video"
            except Exception:
                pass
            # Probe real duration for cost + run (no more hard-coded 8s)
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
                if mb > 400:
                    status = (
                        status
                        or f"Loaded {name} ({mb:.0f} MB — huge master; prefer graded proxy)"
                    )
                elif mb > 150:
                    status = status or f"Loaded {name} ({mb:.0f} MB · {dur_note})"
            except OSError:
                self.src_video_label.value = f"{name} · {dur_note}"
            self.src_video_label.visible = True
        else:
            self.src_video_label.visible = False
            self.src_preview.src = resolved
            self.src_preview.visible = True
            self.src_placeholder.visible = False
            try:
                self.btn_upload.content = "Upload image"
            except Exception:
                pass
        try:
            kind = "video" if as_video else "image"
            self.prev_strip.set_media_kind(kind)
            self.resolve_strip.set_media_kind(kind)
            self.prev_strip.record_and_refresh(resolved)
        except Exception:
            pass
        self._refresh_models()
        self.status.value = status or f"Loaded {name}"
        self.status.color = TEXT_MUTED
        return True

    async def _pick_source(self, e: ft.ControlEvent) -> None:
        try:
            if self._mode == "video":
                files = await pick_video(self.page, dialog_title="Video to upscale")
            else:
                files = await pick_image(self.page, dialog_title="Image to upscale")
        except Exception as exc:
            self.status.value = f"Picker error: {exc}"
            self.page.update()
            return
        if not files or not files[0].path:
            return
        self.load_source(files[0].path, as_video=(self._mode == "video"))
        self.page.update()

    async def _run(self, e: ft.ControlEvent) -> None:
        if self.state.is_busy("tools"):
            return
        from media_studio.secrets_store import has_fal_key

        if not has_fal_key():
            self.status.value = "FAL API key required — open Settings (gear icon)."
            self.page.update()
            return
        if not self.source_path or not Path(self.source_path).is_file():
            self.status.value = (
                "Upload a video first." if self._mode == "video" else "Upload an image first."
            )
            self.page.update()
            return
        if not self.state.try_busy("tools"):
            return
        self.btn.disabled = True
        self.job_progress.start("Uploading…", self.page)
        self.status.value = "Running…"
        self.page.update()

        def on_progress(msg: str) -> None:
            self.job_progress.set_message(classify_progress(msg), self.page)

        try:
            if self._mode == "video":
                dur = float(self._video_duration_s or 8.0)
                if self._video_duration_s is None:
                    # Re-probe once at run time if load missed duration
                    try:
                        from media_studio.pricing import probe_video_duration

                        probed = await asyncio.to_thread(
                            probe_video_duration, self.source_path
                        )
                        if probed and float(probed) > 0:
                            self._video_duration_s = float(probed)
                            dur = self._video_duration_s
                    except Exception:
                        pass
                from media_studio.job_context import to_thread_with_job

                result = await to_thread_with_job(
                    self.state,
                    run_video_upscale,
                    video_path=self.source_path,
                    model_label=_dd_value(self.model_dd),
                    target_label=_dd_value(self.target_dd),
                    duration_s=dur,
                    output_dir=self.state.output_dir,
                    on_progress=on_progress,
                )
            else:
                from media_studio.job_context import to_thread_with_job

                result = await to_thread_with_job(
                    self.state,
                    run_upscale,
                    image_path=self.source_path,
                    model_label=_dd_value(self.model_dd),
                    upscale_factor=float(_dd_value(self.up_factor) or 2),
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
                _emit_tool_result(self, self.source_path, result.path)
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


class ToolsView:
    def __init__(self, page: ft.Page, state: StudioState) -> None:
        self.page = page
        self.state = state

        self.sky_preset = styled_dropdown(
            label_text="Sky type",
            options=list(SKY_PRESETS.keys()),
            value=list(SKY_PRESETS.keys())[0],
            expand=True,
        )
        self.sky_time = styled_dropdown(
            label_text="Time of day",
            options=list(SKY_TIME_OF_DAY),
            value=SKY_TIME_OF_DAY[0],
            expand=True,
        )
        self.dehaze_strength_dd = styled_dropdown(
            label_text="Dehaze strength",
            options=list(DEHAZE_STRENGTH_LABELS),
            value=DEHAZE_STRENGTH_LABELS[2],  # Strong default
            expand=True,
        )
        self.blown_intensity = styled_dropdown(
            label_text="Intensity",
            options=list(BLOWN_OUT_INTENSITY_LABELS),
            value=BLOWN_OUT_INTENSITY_LABELS[1],  # Balanced
            expand=True,
        )
        self.blown_windows_only = ft.Checkbox(
            label="Windows only (default)",
            value=True,
        )

        self.upscale = _UpscaleCard(page, state)
        self.denoise = VideoDenoiseCard(page, state)
        self.interpolate = VideoInterpolateCard(page, state)
        # Soft scenario defaults — never force-navigate
        state.on_scenario_changed(self.apply_app_scenario)
        self.cleanup = DualMediaToolCard(
            page,
            state,
            title="Object / Clutter Removal",
            description=(
                "Still or video: remove people, cars, bins, clutter. "
                "Architecture and camera motion stay locked."
            ),
            image_labels=cleanup_labels(),
            video_labels=video_cleanup_labels(),
            image_registry=CLEANUP_MODELS,
            video_registry=VIDEO_CLEANUP_MODELS,
            run_fn=run_cleanup,
            default_prompt=(
                "remove clutter and temporary objects, keep architecture "
                "and permanent fixtures"
            ),
            button_label="Remove objects",
        )
        self.sky = DualMediaToolCard(
            page,
            state,
            title="Sky / Weather",
            description=(
                "Still sky swap or V2V sky/weather on exterior clips. "
                "Optional sky reference still; roofline and architecture locked. "
                "Still result → Use for V2V sets that plate as sky ref."
            ),
            image_labels=sky_labels(),
            video_labels=video_sky_labels(),
            image_registry=SKY_MODELS,
            video_registry=VIDEO_SKY_MODELS,
            run_fn=run_sky,
            default_prompt="",
            extra_controls=[self.sky_preset, self.sky_time],
            get_extra_kwargs=lambda: {
                "sky_preset": self.sky_preset.value,
                "custom_prompt": self.sky.prompt.value,
                "time_of_day": self.sky_time.value,
            },
            button_label="Apply sky",
            enable_v2v_ref=True,
            v2v_ref_label="Sky reference",
            suggest_kling_on_video=True,
        )
        self.amenity_dd = styled_dropdown(
            label_text="Amenity",
            options=list(AMENITY_CHOICES),
            value=AMENITY_CHOICES[0],
            expand=True,
        )
        self.season_dd = styled_dropdown(
            label_text="Season / curb",
            options=list(SEASON_CHOICES),
            value=SEASON_CHOICES[0],
            expand=True,
        )
        self.dehaze = _ToolCard(
            page,
            state,
            title="Dehaze / Clear Air",
            description="Clear smoke, haze, smog on exteriors. Strength + free-text.",
            model_labels=dehaze_labels(),
            model_registry=DEHAZE_MODELS,
            run_fn=run_dehaze,
            show_prompt=True,
            show_strength=False,
            default_prompt="",
            extra_controls=[self.dehaze_strength_dd],
            get_extra_kwargs=lambda: {
                "strength": dehaze_strength_from_label(self.dehaze_strength_dd.value),
            },
            button_label="Clear smoke / haze",
        )

        # DualMedia sky passes prompt + sky_preset via get_extra_kwargs
        # (run_sky accepts custom_prompt separately — map in kwargs wrapper)
        _orig_sky_extra = self.sky.get_extra_kwargs

        def _sky_extra() -> dict:
            d = _orig_sky_extra()
            # DualMedia passes prompt= already; custom_prompt for still sky builder
            d["custom_prompt"] = self.sky.prompt.value
            return d

        self.sky.get_extra_kwargs = _sky_extra

        self.restore = _RestoreCard(page, state)

        self.blown_out = _ToolCard(
            page,
            state,
            title="Blown Out Repair",
            description=(
                "Fix overexposed / blown-out windows on interior real-estate shots. "
                "Intensity + windows-only default; free-text still allowed."
            ),
            model_labels=blown_out_labels(),
            model_registry=BLOWN_OUT_MODELS,
            run_fn=run_blown_out,
            show_prompt=True,
            show_strength=False,
            default_prompt=BLOWN_OUT_PROMPT_CORE,
            extra_controls=[self.blown_intensity, self.blown_windows_only],
            get_extra_kwargs=lambda: {
                "strength": blown_out_strength_from_label(self.blown_intensity.value),
                "windows_only": bool(self.blown_windows_only.value),
            },
            button_label="Repair windows",
        )

        self.reaspect = _ReAspectCard(page, state)

        self.mirror = DualMediaToolCard(
            page,
            state,
            title="Mirror / Glass Cleanup",
            description=(
                "Remove reflected person, cameraman, or tripod only. "
                "Keep mirror/glass frame, room geometry, and lighting."
            ),
            image_labels=mirror_labels(),
            video_labels=video_mirror_labels(),
            image_registry=MIRROR_MODELS,
            video_registry=VIDEO_MIRROR_MODELS,
            run_fn=run_mirror,
            default_prompt=MIRROR_DEFAULT,
            button_label="Clean reflection",
        )
        self.amenity = DualMediaToolCard(
            page,
            state,
            title="Amenity On",
            description=(
                "Pool water, fireplace lit, interior/landscape lights. "
                "Only the amenity changes; structure locked."
            ),
            image_labels=amenity_labels(),
            video_labels=video_amenity_labels(),
            image_registry=AMENITY_MODELS,
            video_registry=VIDEO_AMENITY_MODELS,
            run_fn=run_amenity,
            default_prompt="",
            extra_controls=[self.amenity_dd],
            get_extra_kwargs=lambda: {"amenity": self.amenity_dd.value},
            button_label="Turn amenity on",
        )
        self.season = DualMediaToolCard(
            page,
            state,
            title="Season / Curb Appeal",
            description=(
                "Season change or curb-appeal boost. Softscape only; "
                "house and hardscape locked. Still-first."
            ),
            image_labels=season_tool_labels(),
            video_labels=season_tool_labels(),  # still path only via image models
            image_registry=SEASON_MODELS,
            video_registry=SEASON_MODELS,
            run_fn=run_season,
            default_prompt="",
            extra_controls=[self.season_dd],
            get_extra_kwargs=lambda: {"season": self.season_dd.value},
            button_label="Apply season",
            allow_video=False,  # image-only; no fake video surface
        )
        # Match look: explicit AI plate + Source look (grade ref) — no silent state.source_path
        self.match_look = DualMediaToolCard(
            page,
            state,
            title="Match Source Look",
            description=(
                "Pull contrast, white balance, and grade of an AI plate toward a "
                "source-look still so it cuts in cleanly. Load both stills explicitly."
            ),
            image_labels=match_look_labels(),
            video_labels=match_look_labels(),
            image_registry=MATCH_LOOK_MODELS,
            video_registry=MATCH_LOOK_MODELS,
            run_fn=self._run_match_look_wrapper,
            default_prompt=MATCH_LOOK_DEFAULT,
            button_label="Match source look",
            allow_video=False,
            grade_ref_mode=True,
            primary_label="AI plate (to grade)",
            grade_label="Source look (grade ref)",
        )

        self.inpaint = InpaintCard(page, state)

        # One tool panel at a time. Key = stable id (Library / Send to).
        # Aleph lives in the top-level Frame Editor tab (not Tools).
        self._tool_panels: dict[str, ft.Control] = {
            "upscale": self.upscale.root,
            "denoise": self.denoise.root,
            "interpolate": self.interpolate.root,
            "cleanup": self.cleanup.root,
            "sky": self.sky.root,
            "dehaze": self.dehaze.root,
            "restore": self.restore.root,
            "inpaint": self.inpaint.root,
            "blown_out": self.blown_out.root,
            "reaspect": self.reaspect.root,
            "mirror": self.mirror.root,
            "amenity": self.amenity.root,
            "season": self.season.root,
            "match_look": self.match_look.root,
        }
        self._tool_ids = list(self._tool_panels.keys())

        # Media groups: still-capable vs V2V / video-capable tools
        self._IMAGE_TOOLS: list[tuple[str, str]] = [
            ("upscale", "Upscale"),
            ("cleanup", "Object Remove"),
            ("sky", "Sky / Weather"),
            ("dehaze", "Dehaze"),
            ("restore", "Sharpen / Restore"),
            ("inpaint", "Inpaint"),
            ("blown_out", "Blown Out"),
            ("mirror", "Mirror / Glass"),
            ("amenity", "Amenity On"),
            ("season", "Season / Curb"),
            ("match_look", "Match Look"),
            ("reaspect", "Re-Aspect"),
        ]
        self._VIDEO_TOOLS: list[tuple[str, str]] = [
            ("upscale", "Upscale"),
            ("denoise", "Denoise"),
            ("interpolate", "Slow Mo"),
            ("cleanup", "Object Remove"),
            ("sky", "Sky / Weather"),
            ("restore", "Sharpen / Restore"),
            ("mirror", "Mirror / Glass"),
            ("amenity", "Amenity On"),
            ("reaspect", "Re-Aspect"),
        ]
        self._IMAGE_TOOL_IDS = {t[0] for t in self._IMAGE_TOOLS}
        self._VIDEO_TOOL_IDS = {t[0] for t in self._VIDEO_TOOLS}
        self._DUAL_MODE_CARDS = (
            "upscale",
            "cleanup",
            "sky",
            "restore",
            "mirror",
            "amenity",
            "reaspect",
        )

        # Session: media group + selected tool
        last_group = getattr(state, "tools_media_group", None)
        if last_group not in ("image", "video"):
            last_group = "image"
        self._media_group = last_group
        state.tools_media_group = self._media_group

        last = getattr(state, "tools_selected_id", None)
        valid = (
            self._IMAGE_TOOL_IDS if self._media_group == "image" else self._VIDEO_TOOL_IDS
        )
        self._selected_tool = last if last in valid else (
            "upscale" if "upscale" in valid else next(iter(valid))
        )
        state.tools_selected_id = self._selected_tool

        # Shared status line (Send-to / run errors surface here)
        self.tools_status = ft.Text("", size=FONT_SM, color=TEXT_MUTED, max_lines=2)

        # Large result stage (Studio Comparison–style)
        self.result_pane = ToolsResultPane(
            page,
            state,
            on_status=self._on_result_status,
        )
        self._wire_result_callbacks()

        self._tool_host = ft.Container(expand=True)
        self._tool_form_scroll = ft.Container(
            content=None,
            expand=True,
            # left form column width — result pane takes the rest
        )
        self._media_nav = PillNav(
            [
                ("image", "Image tools"),
                ("video", "Video tools"),
            ],
            selected=self._media_group,
            on_change=self._on_media_group,
        )
        self._image_pills = PillNav(
            self._IMAGE_TOOLS,
            selected=(
                self._selected_tool
                if self._selected_tool in self._IMAGE_TOOL_IDS
                else self._IMAGE_TOOLS[0][0]
            ),
            on_change=self._on_tool_pill,
        )
        self._video_pills = PillNav(
            self._VIDEO_TOOLS,
            selected=(
                self._selected_tool
                if self._selected_tool in self._VIDEO_TOOL_IDS
                else self._VIDEO_TOOLS[0][0]
            ),
            on_change=self._on_tool_pill,
        )
        self._pill_host = ft.Container()
        self._group_hint = ft.Text(
            "",
            size=FONT_SM,
            color=TEXT_MUTED,
        )
        self._apply_media_group(self._media_group, select_if_invalid=True)
        self._apply_tool_visibility()

    def _on_result_status(self, msg: str, is_error: bool = False) -> None:
        """Surface result-pane / Send-to messages on the Tools status line."""
        try:
            self.tools_status.value = msg
            self.tools_status.color = "#e57373" if is_error else TEXT_MUTED
            self.page.update()
        except Exception:
            pass

    def _wire_result_callbacks(self) -> None:
        """Route every card's successful run into the large result pane."""
        labels = {
            "upscale": "Upscale",
            "denoise": "Video Denoise",
            "interpolate": "Frame Interpolate",
            "cleanup": "Object Remove",
            "sky": "Sky / Weather",
            "dehaze": "Dehaze",
            "restore": "Sharpen / Restore",
            "inpaint": "Inpaint (freehand)",
            "blown_out": "Blown Out",
            "mirror": "Mirror / Glass",
            "amenity": "Amenity On",
            "season": "Season / Curb",
            "match_look": "Match Look",
            "reaspect": "Re-Aspect",
        }
        for tid, lab in labels.items():
            card = getattr(self, tid, None)
            if card is None:
                continue
            card.tool_label = lab

            def _make_cb(label: str):
                def _cb(
                    source: str | None,
                    result: str,
                    *,
                    tool_label: str = "",
                ) -> None:
                    is_vid = False
                    try:
                        is_vid = Path(result).suffix.lower() in {
                            ".mp4",
                            ".mov",
                            ".webm",
                            ".m4v",
                            ".avi",
                            ".mkv",
                        }
                    except Exception:
                        is_vid = False
                    self.result_pane.show(
                        source,
                        result,
                        tool_label=tool_label or label,
                        # Soft “Upscale this clip?” after V2V / any video tool result
                        offer_upscale_prompt=is_vid,
                    )

                return _cb

            card.on_result = _make_cb(lab)

    def _run_match_look_wrapper(self, **kwargs):
        """Map DualMedia card fields → run_match_look(result_path, source_path)."""
        from media_studio.tools_service import ToolResult

        # AI plate = card source_path; grade ref = card.grade_path (required)
        result_path = kwargs.get("image_path") or getattr(
            self.match_look, "source_path", None
        )
        grade = getattr(self.match_look, "grade_path", None)
        if not grade or not Path(str(grade)).is_file():
            return ToolResult(
                ok=False,
                status=(
                    "Load Source look (grade reference) still — "
                    "both AI plate and source look are required."
                ),
            )
        return run_match_look(
            result_path=result_path,
            source_path=grade,
            model_label=kwargs.get("model_label"),
            prompt=kwargs.get("prompt"),
            output_dir=kwargs["output_dir"],
            on_progress=kwargs.get("on_progress"),
        )

    def _on_media_group(self, group_id: str) -> None:
        self._apply_media_group(group_id, select_if_invalid=True)
        try:
            self.page.update()
        except Exception:
            pass

    def _apply_media_group(
        self, group_id: str, *, select_if_invalid: bool = False
    ) -> None:
        group = "video" if group_id == "video" else "image"
        self._media_group = group
        self.state.tools_media_group = group
        try:
            self._media_nav.set_selected(group, notify=False)
        except Exception:
            pass

        if group == "video":
            self._pill_host.content = self._video_pills.control
            self._group_hint.value = (
                "Video tools — V2V paths (upscale, denoise, slow mo / interpolate, "
                "cleanup, sky, restore, mirror, amenity, re-aspect). Source is a clip."
            )
            allowed = self._VIDEO_TOOL_IDS
            pills = self._video_pills
        else:
            self._pill_host.content = self._image_pills.control
            self._group_hint.value = (
                "Image tools — still edits (upscale, cleanup, sky, dehaze, "
                "restore, blown out, mirror, amenity, season, match look, re-aspect)."
            )
            allowed = self._IMAGE_TOOL_IDS
            pills = self._image_pills

        # Lock dual cards to this media type
        for tid in self._DUAL_MODE_CARDS:
            card = getattr(self, tid, None)
            if card is not None and hasattr(card, "force_mode"):
                try:
                    card.force_mode(group)
                except Exception:
                    pass

        if select_if_invalid or self._selected_tool not in allowed:
            pick = (
                self._selected_tool
                if self._selected_tool in allowed
                else ("upscale" if "upscale" in allowed else next(iter(allowed)))
            )
            self._selected_tool = pick
            self.state.tools_selected_id = pick
        try:
            pills.set_selected(self._selected_tool, notify=False)
        except Exception:
            pass
        self._apply_tool_visibility()
        self._refresh_active_prev_strip()

    def _on_tool_pill(self, tool_id: str) -> None:
        self.select_tool(tool_id)

    def select_tool(self, tool_id: str, *, as_video: bool | None = None) -> None:
        """Show a tool panel by id (used by Library Send to)."""
        if tool_id not in self._tool_panels:
            return
        # Prefer matching media group when known
        if as_video is True and tool_id in self._VIDEO_TOOL_IDS:
            if self._media_group != "video":
                self._apply_media_group("video", select_if_invalid=False)
        elif as_video is False and tool_id in self._IMAGE_TOOL_IDS:
            if self._media_group != "image":
                self._apply_media_group("image", select_if_invalid=False)
        elif tool_id not in (
            self._IMAGE_TOOL_IDS
            if self._media_group == "image"
            else self._VIDEO_TOOL_IDS
        ):
            # Switch group so the tool is visible
            if tool_id in self._IMAGE_TOOL_IDS:
                self._apply_media_group("image", select_if_invalid=False)
            elif tool_id in self._VIDEO_TOOL_IDS:
                self._apply_media_group("video", select_if_invalid=False)

        self._selected_tool = tool_id
        self.state.tools_selected_id = tool_id
        try:
            pills = (
                self._video_pills if self._media_group == "video" else self._image_pills
            )
            pills.set_selected(tool_id, notify=False)
        except Exception:
            pass
        if tool_id in self._DUAL_MODE_CARDS:
            card = getattr(self, tool_id, None)
            if card is not None and hasattr(card, "force_mode"):
                try:
                    card.force_mode(self._media_group)
                except Exception:
                    pass
        self._apply_tool_visibility()
        self._refresh_active_prev_strip()
        try:
            self.page.update()
        except Exception:
            pass

    def _refresh_active_prev_strip(self) -> None:
        """Reload Previously used + From Resolve for the visible tool panel."""
        card = getattr(self, self._selected_tool, None)
        if card is None:
            return
        for attr in ("prev_strip", "resolve_strip"):
            strip = getattr(card, attr, None)
            if strip is None:
                continue
            try:
                strip.refresh()
            except Exception:
                pass

    def apply_app_scenario(self, key: str) -> None:
        """
        Soft-apply scenario defaults to tools that care (Sky, Dehaze).

        Does not switch the active tool or inject into Upscale / Re-Aspect / cleanup.
        User free-text on those tools is left alone unless empty / clearly stock.
        """
        from media_studio.scenarios import (
            get_scenario,
            is_blank_canvas,
            tools_touched_by_scenario,
        )
        from media_studio.tools_registry import (
            DEHAZE_STRENGTH_LABELS,
            SKY_PRESETS,
            SKY_TIME_OF_DAY,
            dehaze_prompt,
            sky_prompt,
        )

        if is_blank_canvas(key):
            return
        sc = get_scenario(key)
        if not sc:
            return
        touched = tools_touched_by_scenario(sc.key)

        if "sky" in touched and hasattr(self, "sky"):
            # Map scenario → sky type / time defaults
            if sc.key == "sky_mood":
                # Prefer Clear blue as stock; leave free-text empty so preset drives
                try:
                    if list(SKY_PRESETS.keys()):
                        self.sky_preset.value = list(SKY_PRESETS.keys())[0]
                except Exception:
                    pass
                try:
                    self.sky_time.value = SKY_TIME_OF_DAY[0]
                except Exception:
                    pass
            elif sc.key == "twilight_exterior":
                try:
                    if "Twilight" in SKY_PRESETS:
                        self.sky_preset.value = "Twilight"
                    elif "Golden hour / sunset" in SKY_PRESETS:
                        self.sky_preset.value = "Golden hour / sunset"
                except Exception:
                    pass
                try:
                    if "Blue hour / twilight" in SKY_TIME_OF_DAY:
                        self.sky_time.value = "Blue hour / twilight"
                except Exception:
                    pass
            # Only fill prompt if empty
            try:
                cur = (self.sky.prompt.value or "").strip()
                if not cur:
                    self.sky.prompt.value = sky_prompt(
                        self.sky_preset.value,
                        None,
                        time_of_day=self.sky_time.value,
                    )
            except Exception:
                pass

        if "dehaze" in touched and hasattr(self, "dehaze"):
            try:
                # Strong default for RE exteriors
                if DEHAZE_STRENGTH_LABELS:
                    self.dehaze_strength_dd.value = (
                        DEHAZE_STRENGTH_LABELS[2]
                        if len(DEHAZE_STRENGTH_LABELS) > 2
                        else DEHAZE_STRENGTH_LABELS[0]
                    )
            except Exception:
                pass
            try:
                cur = (self.dehaze.prompt.value or "").strip()
                if not cur:
                    from media_studio.tools_registry import dehaze_strength_from_label

                    self.dehaze.prompt.value = dehaze_prompt(
                        None,
                        strength=dehaze_strength_from_label(
                            self.dehaze_strength_dd.value
                        ),
                    )
            except Exception:
                pass

        if "amenity" in touched and hasattr(self, "amenity"):
            try:
                from media_studio.tools_registry import amenity_prompt

                cur = (self.amenity.prompt.value or "").strip()
                if not cur:
                    self.amenity.prompt.value = amenity_prompt(
                        getattr(self, "amenity_dd", None)
                        and self.amenity_dd.value
                    )
            except Exception:
                pass

        if "season" in touched and hasattr(self, "season"):
            try:
                from media_studio.tools_registry import season_tool_prompt

                cur = (self.season.prompt.value or "").strip()
                if not cur:
                    self.season.prompt.value = season_tool_prompt(
                        getattr(self, "season_dd", None) and self.season_dd.value
                    )
            except Exception:
                pass

        try:
            self.page.update()
        except Exception:
            pass

    def receive_media(
        self,
        tool_id: str,
        path: str,
        *,
        as_video: bool = False,
    ) -> bool:
        """
        Switch to ``tool_id`` and load ``path`` as that tool's source.

        Returns True if the asset was loaded.
        """
        self.select_tool(tool_id, as_video=as_video)
        name = Path(path).name
        status = f"Library → {name}"
        ok = False
        dual_ids = (
            "cleanup",
            "sky",
            "mirror",
            "amenity",
            "season",
            "match_look",
        )
        if tool_id == "upscale":
            if hasattr(self.upscale, "load_source"):
                ok = bool(
                    self.upscale.load_source(path, as_video=as_video, status=status)
                )
            elif hasattr(self.upscale, "load_image") and not as_video:
                ok = bool(self.upscale.load_image(path, status=status))
        elif tool_id in ("denoise", "interpolate"):
            card = getattr(self, tool_id, None)
            if card is not None and hasattr(card, "load_source") and as_video:
                ok = bool(card.load_source(path, status=status))
            elif card is not None and not as_video:
                self.tools_status.value = (
                    "Denoise / Slow Mo need a video clip — still ignored."
                )
                self.tools_status.color = "#e57373"
        elif tool_id in dual_ids:
            card = getattr(self, tool_id, None)
            if card is not None and hasattr(card, "load_source"):
                ok = bool(card.load_source(path, as_video=as_video, status=status))
            elif card is not None and hasattr(card, "load_image") and not as_video:
                ok = bool(card.load_image(path, status=status))
            # Match Look: path is AI plate; prefill grade ref from Studio source if set
            if (
                ok
                and tool_id == "match_look"
                and card is not None
                and getattr(card, "grade_ref_mode", False)
            ):
                src = getattr(self.state, "source_path", None)
                if src and Path(str(src)).is_file() and hasattr(card, "load_grade_ref"):
                    try:
                        card.load_grade_ref(
                            str(src),
                            status=f"Source look from Studio: {Path(str(src)).name}",
                        )
                    except Exception:
                        pass
        elif tool_id in ("dehaze", "blown_out"):
            card = getattr(self, tool_id, None)
            if card is not None and hasattr(card, "load_image") and not as_video:
                ok = bool(card.load_image(path, status=status))
        elif tool_id == "restore":
            ok = bool(
                self.restore.load_source(path, as_video=as_video, status=status)
            )
        elif tool_id == "inpaint":
            ok = bool(
                self.inpaint.load_source(path, as_video=as_video, status=status)
            )
        elif tool_id == "reaspect":
            ok = bool(
                self.reaspect.load_source(path, as_video=as_video, status=status)
            )
        try:
            self.page.update()
        except Exception:
            pass
        return ok

    def _apply_tool_visibility(self) -> None:
        """Show only the active tool form; result pane on the right.

        Inpaint uses a dedicated 3-column layout (controls | canvas | result).
        All other tools keep the standard 2-column FixedRail form + result.
        """
        active = (
            self._selected_tool if self._selected_tool in self._tool_panels else "upscale"
        )
        for tid, ctrl in self._tool_panels.items():
            try:
                ctrl.visible = tid == active
            except Exception:
                pass
        form = self._tool_panels[active]
        try:
            form.visible = True
        except Exception:
            pass

        from media_studio.flet_layout import make_left_rail, make_right_pane
        from media_studio.flet_theme import TOOLS_FORM_WIDTH

        # ----- Inpaint-only: controls | large canvas | result -----
        if active == "inpaint":
            card = getattr(self, "inpaint", None)
            if card is not None and getattr(card, "uses_three_column", False):
                try:
                    # Hide stacked fallback root; host uses columns directly
                    form.visible = False
                except Exception:
                    pass
                left = ft.Container(
                    content=card.controls_column,
                    width=320,
                    expand=False,
                )
                center = ft.Container(
                    content=card.canvas_column,
                    expand=True,
                )
                right = make_right_pane(
                    self.result_pane.root, padding=0, border=False, bgcolor=None
                )
                # Prefer 3-col; on very narrow width Flet will compress center
                self._tool_host.content = ft.Row(
                    [left, center, right],
                    spacing=10,
                    expand=True,
                    vertical_alignment=ft.CrossAxisAlignment.STRETCH,
                )
                return

        # ----- Default 2-column Tools layout -----
        try:
            # Strip nested form scroll if present
            inner = getattr(form, "content", None)
            if isinstance(inner, ft.Column):
                inner.scroll = None
                inner.expand = False
                inner.tight = True
        except Exception:
            pass
        left = make_left_rail(
            [form],
            width=TOOLS_FORM_WIDTH,
            padding=0,
            spacing=0,
            border=False,
            bgcolor=None,
        )
        right = make_right_pane(
            self.result_pane.root, padding=0, border=False, bgcolor=None
        )
        self._tool_host.content = ft.Row(
            [left, right],
            spacing=12,
            expand=True,
            vertical_alignment=ft.CrossAxisAlignment.STRETCH,
        )

    def build(self) -> ft.Control:
        self._apply_tool_visibility()
        return ft.Column(
            [
                # Image | Video tools toggle on the left (next to title)
                ft.Row(
                    [
                        section_title("Tools"),
                        self._media_nav.control,
                        ft.Container(expand=True),
                    ],
                    spacing=12,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Text(
                    "Supporting edits — same FAL key and output folder as Studio. "
                    "Image tools vs Video tools are separate lists. "
                    "Results open large on the right (Overlay / A/B for stills).",
                    size=FONT_SM,
                    color=TEXT_MUTED,
                ),
                self._group_hint,
                self._pill_host,
                self.tools_status,
                ft.Divider(height=1, color=BORDER),
                self._tool_host,  # sole vertical flex (form ListView + result)
            ],
            spacing=10,
            expand=True,
            alignment=ft.MainAxisAlignment.START,
        )
