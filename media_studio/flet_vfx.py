"""
VFX tab — In-scene effects and Element plates for Resolve Screen/Add.

Peer to Studio / Creative Vision / Director / Frame Editor.
"""

from __future__ import annotations

import traceback
from pathlib import Path
from typing import TYPE_CHECKING, Any

import flet as ft

from media_studio.flet_enhance import make_enhance_button, run_prompt_enhance
from media_studio.flet_pickers import pick_image, pick_video
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
    PillNav,
    dropdown_options,
    label,
    make_estimated_cost_box,
    section_title,
    styled_dropdown,
)
from media_studio.flet_video_player import VideoResultPlayer
from media_studio.vfx_registry import (
    assemble_vfx_prompt,
    default_vfx_model_label,
    default_vfx_preset,
    find_vfx_preset,
    format_vfx_cost,
    is_custom_preset,
    model_is_t2v,
    model_is_video_edit,
    model_notes,
    vfx_model_labels,
    vfx_preset_labels,
)
from media_studio.vfx_service import run_vfx

if TYPE_CHECKING:
    from media_studio.flet_app import StudioState


def _dd(dd: ft.Dropdown) -> str | None:
    return dd.value


class VfxView:
    """In-scene + Element plates VFX workspace."""

    def __init__(self, page: ft.Page, state: StudioState) -> None:
        self.page = page
        self.state = state
        self._mode: str = "in_scene"  # in_scene | element
        self._source_path: str | None = None
        self._result_path: str | None = None
        self._last_preset_key: str | None = None

        preset0 = default_vfx_preset()
        self.preset_dd = styled_dropdown(
            label_text="Effect preset",
            options=vfx_preset_labels(),
            value=preset0.label,
            on_select=self._on_preset,
            expand=True,
        )
        self.preset_notes = ft.Text(
            preset0.notes or "",
            size=FONT_SM,
            color=TEXT_MUTED,
            max_lines=2,
        )

        models = vfx_model_labels()
        default_m = default_vfx_model_label()
        if default_m not in models and models:
            default_m = models[0]
        self.model_dd = styled_dropdown(
            label_text="Model",
            options=models,
            value=default_m if models else None,
            on_select=self._on_model,
            expand=True,
        )
        from media_studio.flet_model_hint import make_best_for_line, update_best_for_line

        self.model_best_for = make_best_for_line()
        update_best_for_line(self.model_best_for, self.model_dd.value, dropdown=self.model_dd)
        self.model_notes = ft.Text(
            model_notes(default_m),
            size=FONT_SM,
            color=TEXT_MUTED,
            max_lines=3,
        )

        self.strength = ft.Slider(
            min=0.1,
            max=1.0,
            divisions=9,
            value=0.7,
            label="Strength {value}",
            active_color=ACCENT,
            on_change=self._on_strength,
        )
        self.strength_label = ft.Text(
            "Intensity: medium",
            size=FONT_SM,
            color=TEXT_MUTED,
        )

        self.dur_dd = styled_dropdown(
            label_text="Duration (s)",
            options=[str(i) for i in range(3, 16)],
            value="5",
            on_select=self._refresh_cost,
            expand=True,
        )
        self.res_dd = styled_dropdown(
            label_text="Resolution",
            options=["480p", "720p", "1080p"],
            value="720p",
            on_select=self._refresh_cost,
            expand=True,
        )

        self.use_black = ft.Checkbox(
            label="Pure black / clean plate (Screen · Add in Resolve)",
            value=True,
            on_change=self._on_black_toggle,
        )
        self.element_tip = ft.Text(
            "Element plates: generate the effect alone on black. In Resolve, "
            "composite with Screen or Add over your live plate.",
            size=FONT_SM,
            color=TEXT_MUTED,
            max_lines=3,
        )
        self.in_scene_tip = ft.Text(
            "In-scene: effect is integrated into the full shot — keep source "
            "geometry and lighting direction where possible.",
            size=FONT_SM,
            color=TEXT_MUTED,
            max_lines=3,
        )

        self.prompt = ft.TextField(
            label="Prompt (editable — presets inject physics language)",
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
        self.btn_rebuild = ft.TextButton(
            content="Rebuild from preset",
            on_click=self._rebuild_prompt,
            style=ft.ButtonStyle(color=TEXT_MUTED),
            tooltip=(
                "Replace prompt with lock + preset inject + intensity language. "
                "Custom: leaves your prompt as-is (no template)."
            ),
        )

        self.source_label = ft.Text(
            "No source — upload a still or clip (In-scene)",
            size=FONT_SM,
            color=TEXT_MUTED,
            max_lines=2,
        )
        self.source_preview = ft.Image(
            src="",
            width=160,
            height=90,
            fit=ft.BoxFit.COVER,
            border_radius=6,
            visible=False,
        )
        self.source_ph = ft.Container(
            width=160,
            height=90,
            bgcolor=PANEL,
            border=ft.Border.all(1, BORDER),
            border_radius=6,
            alignment=ft.Alignment.CENTER,
            content=ft.Icon(ft.Icons.IMAGE_OUTLINED, size=28, color=TEXT_MUTED),
        )
        self.btn_still = ft.OutlinedButton(
            content="Upload still",
            icon=ft.Icons.IMAGE,
            on_click=self._pick_still,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
        )
        self.btn_clip = ft.OutlinedButton(
            content="Upload clip",
            icon=ft.Icons.MOVIE,
            on_click=self._pick_clip,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
        )
        self.btn_clear_src = ft.TextButton(
            content="Clear source",
            on_click=self._clear_source,
            style=ft.ButtonStyle(color=TEXT_MUTED),
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

        self.cost_text, self.cost_box = make_estimated_cost_box(initial="Est. cost: —")
        self.btn_generate = ft.FilledButton(
            content="Generate VFX",
            on_click=self._run,
            style=ft.ButtonStyle(bgcolor=ACCENT_BRIGHT, color=TEXT),
            height=42,
        )
        self.btn_enhance = make_enhance_button(on_click=self._on_enhance)
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
            on_status=lambda msg, err: setattr(self.status, "value", msg),
        )

        self.mode_nav = PillNav(
            [
                ("in_scene", "In-scene"),
                ("element", "Element plates"),
            ],
            selected="in_scene",
            on_change=self._on_mode,
        )

        # Seed prompt from default Fire preset
        self._apply_preset_to_prompt(preset0, force=True)
        self.cost_text.value = self._cost_label()
        self.state.on_keys_changed(self.apply_key_gates)
        self.apply_key_gates()
        self._sync_mode_visibility()

    # ----- layout -----

    def build(self) -> ft.Control:
        from media_studio.flet_layout import make_split_workspace
        from media_studio.flet_theme import RAIL_WIDTH

        left = [
            section_title("VFX"),
            ft.Text(
                "In-scene integrates effects into a full plate. Element plates "
                "are clean black / isolated elements for Screen or Add in Resolve.",
                size=FONT_SM,
                color=TEXT_MUTED,
            ),
            self.mode_nav.row,
            self.in_scene_tip,
            self.element_tip,
            ft.Divider(height=1, color=BORDER),
            label("Source", muted=True),
            ft.Stack([self.source_ph, self.source_preview], width=160, height=90),
            self.source_label,
            ft.Row(
                [self.btn_still, self.btn_clip, self.btn_clear_src],
                spacing=6,
                wrap=True,
            ),
            self.prev_strip.root,
            self.resolve_strip.root,
            self.use_black,
            ft.Divider(height=1, color=BORDER),
            ft.Row([self.preset_dd], spacing=0),
            self.preset_notes,
            ft.Row([self.model_dd], spacing=0),
            self.model_best_for,
            self.model_notes,
            ft.Row([self.dur_dd, self.res_dd], spacing=8),
            label("Strength / intensity", muted=True),
            self.strength,
            self.strength_label,
            self.prompt,
            ft.Row([self.btn_rebuild, self.btn_enhance, self.btn_generate], spacing=8),
            self.cost_box,
            self.job_progress.control,
            self.status,
        ]
        right = ft.Column(
            [
                section_title("Result"),
                ft.Text(
                    "Library · Show in folder · Send to Resolve",
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
        return make_split_workspace(left, right, left_width=max(RAIL_WIDTH, 480))

    # ----- gates / cost -----

    def apply_key_gates(self) -> None:
        from media_studio.secrets_store import has_fal_key, has_xai_key

        ready = has_fal_key()
        if not self.state.is_busy("vfx"):
            self.btn_generate.disabled = not ready
            self.btn_generate.tooltip = (
                None if ready else "Add your FAL API key in Settings"
            )
            xai = has_xai_key()
            self.btn_enhance.disabled = not xai
            self.btn_enhance.tooltip = (
                "Rewrite VFX prompt for the selected model"
                if xai
                else "Add xAI API key for Enhance"
            )

    def _cost_label(self) -> str:
        try:
            return format_vfx_cost(
                _dd(self.model_dd),
                duration_s=self._duration(),
                resolution=_dd(self.res_dd),
            )
        except Exception:
            return "Est. cost: —"

    def _duration(self) -> float:
        try:
            return float(_dd(self.dur_dd) or 5)
        except (TypeError, ValueError):
            return 5.0

    async def _refresh_cost(self, e: ft.ControlEvent | None = None) -> None:
        self.cost_text.value = self._cost_label()
        try:
            self.page.update()
        except Exception:
            pass

    # ----- mode / preset -----

    def _on_mode(self, mode_id: str) -> None:
        self._mode = mode_id if mode_id in ("in_scene", "element") else "in_scene"
        self._sync_mode_visibility()
        # Re-inject preset language for the new mode (Custom: leave user text alone)
        preset = find_vfx_preset(_dd(self.preset_dd)) or default_vfx_preset()
        if is_custom_preset(preset):
            self._last_preset_key = preset.key
        else:
            self._apply_preset_to_prompt(preset, force=True)
        self.cost_text.value = self._cost_label()
        try:
            self.page.update()
        except Exception:
            pass

    def _sync_mode_visibility(self) -> None:
        is_el = self._mode == "element"
        self.use_black.visible = is_el
        self.element_tip.visible = is_el
        self.in_scene_tip.visible = not is_el
        # Element can run without source; in-scene prefers source
        if is_el:
            self.source_label.value = (
                self.source_label.value
                if self._source_path
                else "Optional source — default pure black plate when checked"
            )

    async def _on_black_toggle(self, e: ft.ControlEvent | None = None) -> None:
        try:
            self.page.update()
        except Exception:
            pass

    async def _on_preset(self, e: ft.ControlEvent | None = None) -> None:
        preset = find_vfx_preset(_dd(self.preset_dd)) or default_vfx_preset()
        self.preset_notes.value = preset.notes or ""
        if is_custom_preset(preset):
            # Custom: empty / user-written only — do not wipe existing freeform text
            # with a template; clear only if current text looks like a pack inject.
            cur = (self.prompt.value or "").strip()
            if self._looks_like_preset_inject(cur):
                self.prompt.value = ""
            self._last_preset_key = "custom"
            self.status.value = "Custom — write your effect vision (no pack inject)."
        else:
            self._apply_preset_to_prompt(preset, force=True)
        try:
            self.page.update()
        except Exception:
            pass

    def _looks_like_preset_inject(self, text: str) -> bool:
        """True if prompt is mostly auto-generated pack language (safe to clear)."""
        if not text:
            return False
        markers = (
            "In-scene VFX:",
            "Element plate VFX",
            "Integrate realistic fire",
            "Isolated fire element",
            "Integrate volumetric smoke",
            "Isolated smoke / dust",
            "Integrate an energy",
            "Isolated energy / power-surge",
            "Integrate weather into the plate",
            "Isolated weather particles",
            "Integrate debris / impact",
            "Isolated debris / impact",
            "Integrate optical lens flare",
            "Isolated lens flare",
        )
        return any(m in text for m in markers)

    def _apply_preset_to_prompt(self, preset, *, force: bool = False) -> None:
        """Inject preset language; Custom leaves user text alone."""
        if is_custom_preset(preset):
            self._last_preset_key = "custom"
            return
        free = ""
        cur = (self.prompt.value or "").strip()
        # If user typed something beyond auto inject, try to preserve trailing notes
        if cur and not force:
            free = cur
        self.prompt.value = assemble_vfx_prompt(
            mode=self._mode,  # type: ignore[arg-type]
            preset=preset,
            user_prompt=free if not force else "",
            strength=float(self.strength.value or 0.7),
            duration_s=self._duration(),
        )
        self._last_preset_key = preset.key

    async def _rebuild_prompt(self, e: ft.ControlEvent | None = None) -> None:
        preset = find_vfx_preset(_dd(self.preset_dd)) or default_vfx_preset()
        if is_custom_preset(preset):
            # Leave as-is — no injected template
            self.status.value = "Custom — no pack template (prompt left as-is)."
            try:
                self.page.update()
            except Exception:
                pass
            return
        self._apply_preset_to_prompt(preset, force=True)
        self.status.value = f"Prompt rebuilt from {preset.label}."
        try:
            self.page.update()
        except Exception:
            pass

    async def _on_strength(self, e: ft.ControlEvent | None = None) -> None:
        s = float(self.strength.value or 0.7)
        if s < 0.34:
            self.strength_label.value = "Intensity: subtle"
        elif s < 0.67:
            self.strength_label.value = "Intensity: medium"
        else:
            self.strength_label.value = "Intensity: strong"
        try:
            self.page.update()
        except Exception:
            pass

    async def _on_model(self, e: ft.ControlEvent | None = None) -> None:
        lab = _dd(self.model_dd)
        self.model_notes.value = model_notes(lab)
        try:
            from media_studio.flet_model_hint import update_best_for_line

            update_best_for_line(self.model_best_for, lab, dropdown=self.model_dd)
        except Exception:
            pass
        self.cost_text.value = self._cost_label()
        try:
            self.page.update()
        except Exception:
            pass

    # ----- source -----

    async def _pick_still(self, e: ft.ControlEvent) -> None:
        try:
            files = await pick_image(self.page, dialog_title="VFX source still")
        except Exception as exc:
            self.status.value = f"Picker error: {exc}"
            self.page.update()
            return
        if not files or not files[0].path:
            return
        self._set_source(files[0].path)

    async def _pick_clip(self, e: ft.ControlEvent) -> None:
        try:
            files = await pick_video(self.page, dialog_title="VFX source clip")
        except Exception as exc:
            self.status.value = f"Picker error: {exc}"
            self.page.update()
            return
        if not files or not files[0].path:
            return
        self._set_source(files[0].path)

    async def _clear_source(self, e: ft.ControlEvent) -> None:
        self._source_path = None
        self.source_preview.src = ""
        self.source_preview.visible = False
        self.source_ph.visible = True
        self.source_label.value = (
            "Optional source — default pure black plate when checked"
            if self._mode == "element"
            else "No source — upload a still or clip (In-scene)"
        )
        try:
            self.page.update()
        except Exception:
            pass

    def _on_prev_source(self, path: str) -> None:
        self._set_source(path)

    def _set_source(self, path: str) -> None:
        p = Path(path)
        if not p.is_file():
            self.status.value = f"Missing file: {path}"
            try:
                self.page.update()
            except Exception:
                pass
            return
        self._source_path = str(p.resolve())
        name = p.name
        self.source_label.value = f"Source: {name}"
        ext = p.suffix.lower()
        if ext in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}:
            self.source_preview.src = self._source_path
            self.source_preview.visible = True
            self.source_ph.visible = False
        else:
            # clip — try poster
            try:
                from media_studio.media import video_poster_path

                poster = video_poster_path(self._source_path)
                if poster and Path(poster).is_file():
                    self.source_preview.src = poster
                    self.source_preview.visible = True
                    self.source_ph.visible = False
                else:
                    self.source_preview.visible = False
                    self.source_ph.visible = True
            except Exception:
                self.source_preview.visible = False
                self.source_ph.visible = True
        try:
            self.prev_strip.record_and_refresh(self._source_path)
        except Exception:
            pass
        self.status.value = f"Source loaded: {name}"
        try:
            self.page.update()
        except Exception:
            pass

    # ----- enhance / generate -----

    async def _on_enhance(self, e: ft.ControlEvent) -> None:
        mode = self._mode
        preset = find_vfx_preset(_dd(self.preset_dd))
        model = _dd(self.model_dd)
        custom = is_custom_preset(preset)

        def _extra() -> dict[str, Any]:
            if custom:
                guidance = (
                    "Custom VFX — treat the user prompt as the creative vision. "
                    "Rewrite for the selected fal video model with concrete physics "
                    "(mass, velocity, temperature, light interaction) where useful. "
                    "Do NOT force a named pack category (fire/smoke/energy/etc.) "
                    "unless the user already wrote it. "
                    + (
                        "Element plates: pure black / clean isolation for Screen or Add "
                        "composite in Resolve — no environment, no floor, no vignette."
                        if mode == "element"
                        else "In-scene: integrate into the existing plate; preserve "
                        "geometry and lighting direction."
                    )
                    + " Do not invent unsupported API fields."
                )
            else:
                guidance = (
                    "Rewrite for VFX generation on fal. "
                    + (
                        "Element plate: pure black background, isolated effect for "
                        "Screen/Add composite in Resolve — no environment."
                        if mode == "element"
                        else "In-scene: integrate the effect into the existing plate; "
                        "preserve geometry and lighting direction."
                    )
                    + " Keep physics-aware language (temperature, velocity, density). "
                    + (
                        f"Honor the selected pack ({preset.label}). "
                        if preset
                        else ""
                    )
                    + "Do not invent unsupported API fields."
                )
            return {
                "workspace": "vfx",
                "mode": mode,
                "preset": "custom" if custom else (preset.key if preset else None),
                "custom_vision": custom,
                "model": model,
                "strength": float(self.strength.value or 0.7),
                "duration_s": self._duration(),
                "has_source": bool(self._source_path),
                "element_black_plate": bool(self.use_black.value)
                if mode == "element"
                else False,
                "guidance": guidance,
            }

        await run_prompt_enhance(
            page=self.page,
            state=self.state,
            prompt_field=self.prompt,
            get_model=lambda: model,
            get_extra_context=_extra,
            status_ctrl=self.status,
            job_progress=self.job_progress,
            enhance_btn=self.btn_enhance,
            busy_controls=[self.btn_generate],
            context_label="vfx custom vision" if custom else "vfx prompt",
            allow_empty_with_context=True,
            busy_scope="vfx",
        )
        self.apply_key_gates()
        try:
            self.page.update()
        except Exception:
            pass

    async def _run(self, e: ft.ControlEvent) -> None:
        if self.state.is_busy("vfx"):
            return
        from media_studio.secrets_store import has_fal_key

        if not has_fal_key():
            self.status.value = "FAL API key required — open Settings (gear icon)."
            self.page.update()
            return

        mode = self._mode
        if mode == "in_scene" and not self._source_path:
            self.status.value = "In-scene needs a source still or clip."
            self.page.update()
            return
        if not (self.prompt.value or "").strip():
            preset = find_vfx_preset(_dd(self.preset_dd))
            self.status.value = (
                "Custom: type your effect vision first."
                if is_custom_preset(preset)
                else "Pick a preset or enter a prompt."
            )
            self.page.update()
            return

        # Cost guard
        try:
            from media_studio.flet_dialogs import confirm_cost_if_needed
            from media_studio.vfx_registry import estimate_vfx_cost

            est = estimate_vfx_cost(
                _dd(self.model_dd),
                duration_s=self._duration(),
                resolution=_dd(self.res_dd),
            )
            ok = await confirm_cost_if_needed(
                self.page,
                estimated_usd=float(est or 0),
                job_label=f"VFX · {mode}",
            )
            if not ok:
                self.status.value = "Generate cancelled (cost guard)."
                self.page.update()
                return
        except Exception:
            pass

        if not self.state.try_busy("vfx"):
            return
        self.btn_generate.disabled = True
        try:
            self.player.clear()
        except Exception:
            pass
        self.job_progress.start("Starting VFX…", self.page)
        self.status.value = f"Running VFX ({mode})…"
        self.page.update()

        def on_progress(msg: str) -> None:
            self.job_progress.set_message(classify_progress(msg), self.page)

        try:
            from media_studio.job_context import to_thread_with_job

            result = await to_thread_with_job(
                self.state,
                run_vfx,
                mode=mode,
                prompt=self.prompt.value or "",
                preset_label=_dd(self.preset_dd),
                model_label=_dd(self.model_dd),
                source_path=self._source_path,
                strength=float(self.strength.value or 0.7),
                duration_s=self._duration(),
                resolution=_dd(self.res_dd),
                use_black_plate=bool(self.use_black.value),
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
                        self.btn_folder, self.btn_resolve, visible=True
                    )
                    self.result_actions_row.visible = True
                except Exception:
                    pass
            else:
                err = result.status or "Failed."
                self.job_progress.finish_error(err, self.page)
                self.status.value = err
        except Exception as exc:
            from media_studio.errors import friendly_error

            err = friendly_error(exc, context="VFX")
            self.job_progress.finish_error(err, self.page)
            self.status.value = err
            traceback.print_exc()
        finally:
            self.state.clear_busy("vfx")
            self.apply_key_gates()
            try:
                self.page.update()
            except Exception:
                pass
