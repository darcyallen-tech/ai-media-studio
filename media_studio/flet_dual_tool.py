"""
Dual Image|Video tool card for Phase 5 RE tools.

Lightweight shared UI: mode toggle, upload, model, prompt, enhance, cost, run.
"""

from __future__ import annotations

import asyncio
import traceback
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

import flet as ft

from media_studio.flet_enhance import make_enhance_button, run_prompt_enhance
from media_studio.flet_pickers import pick_image, pick_video
from media_studio.flet_progress import JobProgress, classify_progress
from media_studio.flet_result_actions import make_result_action_row, show_result_actions
from media_studio.flet_source_strip import PreviousSourcesStrip, ResolveSourcesStrip
from media_studio.flet_theme import (
    ACCENT_BRIGHT,
    BORDER,
    FONT_SM,
    PANEL,
    PANEL_ELEVATED,
    TEXT,
    TEXT_MUTED,
    dropdown_options,
    label,
    panel,
    section_title,
    styled_dropdown,
)
from media_studio.tools_registry import find_tool, format_tool_cost

if TYPE_CHECKING:
    from media_studio.flet_app import StudioState


def _dd_value(dd: ft.Dropdown) -> str | None:
    return dd.value


class DualMediaToolCard:
    """Image | Video tool with prompt, enhance, cost, result actions."""

    def __init__(
        self,
        page: ft.Page,
        state: StudioState,
        *,
        title: str,
        description: str,
        image_labels: list[str],
        video_labels: list[str],
        image_registry: dict,
        video_registry: dict,
        run_fn: Callable[..., Any],
        default_prompt: str = "",
        button_label: str = "Run",
        extra_controls: list[ft.Control] | None = None,
        get_extra_kwargs: Callable[[], dict] | None = None,
        allow_video: bool = True,
        on_result: Callable[[str | None, str], None] | None = None,
        tool_label: str = "",
        # Match Look: two still pickers (AI plate + grade reference)
        grade_ref_mode: bool = False,
        primary_label: str = "Source",
        grade_label: str = "Source look (grade ref)",
    ) -> None:
        self.page = page
        self.state = state
        self.image_registry = image_registry
        self.video_registry = video_registry
        self.run_fn = run_fn
        self.get_extra_kwargs = get_extra_kwargs or (lambda: {})
        self.allow_video = allow_video
        self.on_result = on_result
        self.tool_label = tool_label or title
        self.grade_ref_mode = bool(grade_ref_mode)
        self._mode = "image"
        self._mode_locked = False
        self.source_path: str | None = None  # primary (AI plate when grade_ref_mode)
        self.grade_path: str | None = None  # grade reference still
        self._result_path: str | None = None

        self.mode_dd = styled_dropdown(
            label_text="Mode",
            options=["Image", "Video"] if allow_video else ["Image"],
            value="Image",
            on_select=self._on_mode,
            expand=True,
        )
        # Media group (Image tools | Video tools) owns mode; hide dual toggle
        self.mode_dd.visible = False
        self.preview = ft.Image(
            src="", fit=ft.BoxFit.CONTAIN, width=140, height=90, visible=False
        )
        self.placeholder = ft.Container(
            content=ft.Text(primary_label, color=TEXT_MUTED, size=FONT_SM),
            alignment=ft.Alignment.CENTER,
            width=140,
            height=90,
            bgcolor=PANEL_ELEVATED,
            border_radius=6,
            border=ft.Border.all(1, BORDER),
        )
        self.primary_caption = ft.Text(
            primary_label if grade_ref_mode else "",
            size=11,
            color=TEXT_MUTED,
            visible=grade_ref_mode,
        )
        self.video_label = ft.Text(
            "", size=FONT_SM, color=TEXT, visible=False, max_lines=3
        )
        self.btn_upload = ft.OutlinedButton(
            content="Upload AI plate" if grade_ref_mode else "Upload image",
            icon=ft.Icons.UPLOAD_FILE,
            on_click=self._pick,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
        )
        # Optional second still (grade reference) for Match Look
        self.grade_preview = ft.Image(
            src="", fit=ft.BoxFit.CONTAIN, width=140, height=90, visible=False
        )
        self.grade_placeholder = ft.Container(
            content=ft.Text(grade_label, color=TEXT_MUTED, size=FONT_SM, text_align=ft.TextAlign.CENTER),
            alignment=ft.Alignment.CENTER,
            width=140,
            height=90,
            bgcolor=PANEL_ELEVATED,
            border_radius=6,
            border=ft.Border.all(1, BORDER),
            visible=grade_ref_mode,
        )
        self.grade_caption = ft.Text(
            grade_label,
            size=11,
            color=TEXT_MUTED,
            visible=grade_ref_mode,
        )
        self.btn_upload_grade = ft.OutlinedButton(
            content="Upload source look",
            icon=ft.Icons.IMAGE_SEARCH,
            on_click=self._pick_grade,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
            visible=grade_ref_mode,
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
        labels = image_labels
        self._image_labels = image_labels
        self._video_labels = video_labels
        self.model_dd = styled_dropdown(
            label_text="Model",
            options=labels,
            value=labels[0] if labels else None,
            on_select=self._refresh_cost,
            expand=True,
        )
        self.prompt = ft.TextField(
            label="Prompt (editable)",
            value=default_prompt,
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
        self.extra = extra_controls or []
        self.cost_text = ft.Text(
            self._cost(), size=FONT_SM, color=TEXT, weight=ft.FontWeight.W_600
        )
        self.status = ft.Text("", size=FONT_SM, color=TEXT_MUTED, max_lines=4)
        self.job_progress = JobProgress()
        self.btn = ft.FilledButton(
            content=button_label,
            on_click=self._run,
            style=ft.ButtonStyle(bgcolor=ACCENT_BRIGHT, color=TEXT),
        )
        self.btn_enhance = make_enhance_button(on_click=self._on_enhance)
        self.result = ft.Image(
            src="", fit=ft.BoxFit.CONTAIN, width=220, height=140, visible=False
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
        # Inline result column retired — ToolsResultPane shows large preview
        self.result.visible = False
        self.result_video_label.visible = False
        self.result_actions_row.visible = False
        self.state.on_keys_changed(self.apply_key_gates)
        self.apply_key_gates()

        # Media thumbs side-by-side (fixed), then full-width controls below —
        # never 3-column crush of labels into a thin vertical strip.
        primary_col = ft.Column(
            [
                self.primary_caption,
                self.preview,
                self.placeholder,
                self.video_label,
                self.btn_upload,
                self.prev_strip.root,
                self.resolve_strip.root,
            ],
            spacing=6,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            tight=True,
        )
        grade_col = ft.Column(
            [
                self.grade_caption,
                self.grade_preview,
                self.grade_placeholder,
                self.btn_upload_grade,
            ],
            spacing=6,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            tight=True,
            visible=self.grade_ref_mode,
        )
        self.root = panel(
            ft.Column(
                [
                    section_title(title),
                    ft.Text(description, size=FONT_SM, color=TEXT_MUTED),
                    ft.Row(
                        [primary_col, grade_col],
                        spacing=16,
                        vertical_alignment=ft.CrossAxisAlignment.START,
                        tight=True,
                    ),
                    ft.Row([self.model_dd], spacing=0),
                    # Extra dropdowns: horizontal expand only (never vertical grey slabs)
                    *[ft.Row([ctrl], spacing=0) for ctrl in self.extra],
                    self.prompt,
                    self.prompt_favs.root,
                    self.cost_text,
                    ft.Row([self.btn_enhance, self.btn], spacing=8, wrap=True),
                    self.job_progress.control,
                    self.status,
                ],
                spacing=8,
                tight=True,
                # No form scroll — Tools host ListView is the only scroll
            ),
        )

    def _registry(self) -> dict:
        return self.video_registry if self._mode == "video" else self.image_registry

    def _cost(self) -> str:
        labels = self._video_labels if self._mode == "video" else self._image_labels
        reg = self._registry()
        spec = find_tool(_dd_value(self.model_dd), reg)
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
                "Rewrite prompt for the selected model"
                if xai
                else "Add your xAI API key in Settings to Enhance"
            )

    async def _on_enhance(self, e: ft.ControlEvent) -> None:
        await run_prompt_enhance(
            page=self.page,
            state=self.state,
            prompt_field=self.prompt,
            get_model=lambda: _dd_value(self.model_dd),
            get_image=lambda: self.source_path if self._mode != "video" else None,
            get_video=lambda: self.source_path if self._mode == "video" else None,
            get_scenario=lambda: getattr(self.state, "scenario_label", None),
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

    def _refresh_models(self) -> None:
        labels = self._video_labels if self._mode == "video" else self._image_labels
        prev = _dd_value(self.model_dd)
        self.model_dd.options = dropdown_options(labels)
        self.model_dd.value = prev if prev in labels else (labels[0] if labels else None)
        self.cost_text.value = self._cost()

    def force_mode(self, mode: str, *, clear_source: bool = False) -> None:
        """
        Lock card to image or video (driven by Tools Image|Video groups).

        Does not clear a compatible source; clears only when types conflict.
        """
        want = "video" if str(mode).lower() == "video" else "image"
        if not self.allow_video:
            want = "image"
        self._mode_locked = True
        try:
            self.mode_dd.visible = False
            self.mode_dd.value = "Video" if want == "video" else "Image"
        except Exception:
            pass
        prev = self._mode
        self._mode = want
        if clear_source or (prev != want and self.source_path):
            # Drop source only when switching media type
            if prev != want:
                self.source_path = None
                self.preview.src = ""
                self.preview.visible = False
                self.video_label.value = ""
                self.video_label.visible = False
                self.placeholder.visible = True
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

    def _emit_result(self, path: str) -> None:
        cb = self.on_result
        if not cb:
            return
        try:
            cb(self.source_path, path)
        except TypeError:
            try:
                cb(self.source_path, path, tool_label=self.tool_label)  # type: ignore[call-arg]
            except Exception:
                pass
        except Exception:
            pass

    async def _on_mode(self, e: ft.ControlEvent) -> None:
        if self._mode_locked:
            return
        self._mode = (
            "video" if (_dd_value(self.mode_dd) or "").lower() == "video" else "image"
        )
        self.source_path = None
        self.preview.src = ""
        self.preview.visible = False
        self.video_label.value = ""
        self.video_label.visible = False
        self.placeholder.visible = True
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

    def _on_prev_source(self, path: str) -> None:
        as_vid = self._mode == "video"
        # Auto-detect if path is clearly the other type
        ext = Path(path).suffix.lower()
        if ext in {".mp4", ".mov", ".webm", ".m4v", ".avi", ".mkv"}:
            as_vid = True
        elif ext in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}:
            as_vid = False
        self.load_source(path, as_video=as_vid, status=f"Previous: {Path(path).name}")
        try:
            self.page.update()
        except Exception:
            pass

    async def _refresh_cost(self, e: ft.ControlEvent) -> None:
        self.cost_text.value = self._cost()
        self.page.update()

    def load_image(self, path: str, *, status: str | None = None) -> bool:
        return self.load_source(path, as_video=False, status=status)

    def load_source(
        self, path: str, *, as_video: bool = False, status: str | None = None
    ) -> bool:
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
            if bool(as_video) != want_video:
                self.status.value = (
                    "This is a Video tool — drop a video clip, or switch to Image tools."
                    if want_video
                    else "This is an Image tool — drop a still, or switch to Video tools."
                )
                self.status.color = "#e57373"
                return False
        self._mode = "video" if as_video else "image"
        try:
            self.mode_dd.value = "Video" if as_video else "Image"
        except Exception:
            pass
        self.source_path = resolved
        name = Path(resolved).name
        if as_video:
            self.preview.visible = False
            self.placeholder.visible = False
            self.video_label.value = name
            self.video_label.visible = True
            self.btn_upload.content = "Upload video"
            try:
                self.prev_strip.set_media_kind("video")
                self.resolve_strip.set_media_kind("video")
            except Exception:
                pass
        else:
            self.video_label.visible = False
            self.preview.src = resolved
            self.preview.visible = True
            self.placeholder.visible = False
            self.btn_upload.content = (
                "Upload AI plate" if self.grade_ref_mode else "Upload image"
            )
            try:
                self.prev_strip.set_media_kind("image")
                self.resolve_strip.set_media_kind("image")
            except Exception:
                pass
        self._refresh_models()
        if self.grade_ref_mode:
            self.status.value = status or f"AI plate: {name}"
        else:
            self.status.value = status or f"Loaded {name}"
        try:
            self.prev_strip.record_and_refresh(resolved)
        except Exception:
            pass
        return True

    def load_grade_ref(self, path: str, *, status: str | None = None) -> bool:
        """Load grade-reference still (Match Look source look)."""
        try:
            p = Path(path)
            if not p.is_file():
                self.status.value = f"Grade ref missing: {path}"
                return False
            resolved = str(p.resolve())
        except OSError:
            return False
        self.grade_path = resolved
        self.grade_preview.src = resolved
        self.grade_preview.visible = True
        self.grade_placeholder.visible = False
        self.status.value = status or f"Source look: {Path(resolved).name}"
        try:
            self.page.update()
        except Exception:
            pass
        return True

    async def _pick(self, e: ft.ControlEvent) -> None:
        try:
            if self._mode == "video":
                files = await pick_video(self.page, dialog_title="Source video")
            else:
                title = "AI plate (result to grade)" if self.grade_ref_mode else "Source image"
                files = await pick_image(self.page, dialog_title=title)
        except Exception as exc:
            self.status.value = f"Picker error: {exc}"
            self.page.update()
            return
        if not files or not files[0].path:
            return
        self.load_source(files[0].path, as_video=(self._mode == "video"))
        self.page.update()

    async def _pick_grade(self, e: ft.ControlEvent) -> None:
        try:
            files = await pick_image(
                self.page, dialog_title="Source look (grade reference)"
            )
        except Exception as exc:
            self.status.value = f"Picker error: {exc}"
            self.page.update()
            return
        if not files or not files[0].path:
            return
        self.load_grade_ref(files[0].path)
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
                "Upload a video first."
                if self._mode == "video"
                else (
                    "Upload an AI plate first."
                    if self.grade_ref_mode
                    else "Upload an image first."
                )
            )
            self.page.update()
            return
        if self.grade_ref_mode and (
            not self.grade_path or not Path(self.grade_path).is_file()
        ):
            self.status.value = "Upload Source look (grade reference) still."
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

        kwargs: dict[str, Any] = {
            "model_label": _dd_value(self.model_dd),
            "prompt": self.prompt.value,
            "output_dir": self.state.output_dir,
            "on_progress": on_progress,
        }
        if self.allow_video:
            kwargs["mode"] = self._mode
            if self._mode == "video":
                kwargs["video_path"] = self.source_path
                kwargs["image_path"] = None
            else:
                kwargs["image_path"] = self.source_path
                kwargs["video_path"] = None
        else:
            kwargs["image_path"] = self.source_path
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
                self._emit_result(result.path)
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
