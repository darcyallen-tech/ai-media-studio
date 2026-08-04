"""
Motion Sync tab — character still + driving video → motion transfer.

Peer to Studio / Creative Vision / Director / VFX / Frame Editor.
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
    label,
    make_estimated_cost_box,
    section_title,
    styled_dropdown,
)
from media_studio.flet_video_player import VideoResultPlayer
from media_studio.motion_sync_registry import (
    PROMPT_HELPER_CHIPS,
    default_motion_sync_model,
    find_motion_sync_model,
    format_motion_sync_cost,
    motion_sync_model_labels,
    orientation_ui_labels,
    orientation_ui_to_api,
)
from media_studio.motion_sync_service import run_motion_sync
from media_studio.pricing import probe_video_duration

if TYPE_CHECKING:
    from media_studio.flet_app import StudioState


def _dd(dd: ft.Dropdown) -> str | None:
    return dd.value


class MotionSyncView:
    """Character still + motion reference → motion-control generate."""

    def __init__(self, page: ft.Page, state: StudioState) -> None:
        self.page = page
        self.state = state
        self._character_path: str | None = None
        self._motion_path: str | None = None
        self._motion_duration_s: float | None = None
        self._result_path: str | None = None

        spec0 = default_motion_sync_model()
        labels = motion_sync_model_labels()
        self.model_dd = styled_dropdown(
            label_text="Model (motion transfer only)",
            options=labels,
            value=spec0.label if spec0.label in labels else (labels[0] if labels else None),
            on_select=self._on_model,
            expand=True,
        )
        from media_studio.flet_model_hint import make_best_for_line, update_best_for_line

        self.model_best_for = make_best_for_line()
        update_best_for_line(
            self.model_best_for, self.model_dd.value, dropdown=self.model_dd
        )
        self.model_notes = ft.Text(
            spec0.notes or "",
            size=FONT_SM,
            color=TEXT_MUTED,
            max_lines=4,
        )

        self.keep_audio = ft.Checkbox(
            label="Keep original audio (when supported)",
            value=bool(spec0.default_keep_audio),
            on_change=self._refresh_cost,
        )
        orient_opts = orientation_ui_labels()
        self.orient_dd = styled_dropdown(
            label_text="Character orientation (Kling)",
            options=orient_opts,
            value=orient_opts[0],
            on_select=self._on_orient,
            expand=True,
        )
        self.orient_hint = ft.Text(
            "Match video: complex body motion (API up to 30s). "
            "Match image: follow camera/pose of the still (API ≤10s).",
            size=FONT_SM,
            color=TEXT_MUTED,
            max_lines=3,
        )
        # Wan-only toggles (labels/help only — behavior/defaults unchanged)
        self.adapt_motion = ft.Checkbox(
            label="Fit motion to this character's body",
            value=True,
            visible=False,
        )
        self.enhance_identity = ft.Checkbox(
            label="Sharpen face & identity",
            value=bool(getattr(spec0, "default_enhance_identity", False))
            if getattr(spec0, "supports_enhance_identity", False)
            else False,
            visible=False,
            tooltip="Extra pass to keep the person looking like the still",
            on_change=self._refresh_cost,
        )
        self.enhance_identity_hint = ft.Text(
            "Extra pass to keep the person looking like the still",
            size=FONT_SM,
            color=TEXT_MUTED,
            visible=False,
            max_lines=2,
        )
        self.wan_toggles_hint = ft.Text(
            "Wan can adjust the motion to your character's build and optionally "
            "lock the face more tightly.",
            size=FONT_SM,
            color=TEXT_MUTED,
            visible=False,
            max_lines=3,
        )
        self.accel_dd = styled_dropdown(
            label_text="Acceleration (Wan)",
            options=["regular", "none"],
            value="regular",
            expand=True,
        )
        self.accel_dd.visible = False

        self.prompt = ft.TextField(
            label="Optional prompt (environment, style, clothing)",
            hint_text="e.g. outdoor listing backdrop, navy blazer, natural daylight",
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
        self.prompt_chips = ft.Row(
            [
                ft.TextButton(
                    content=chip,
                    on_click=self._make_prompt_chip(chip),
                    style=ft.ButtonStyle(color=ACCENT),
                )
                for chip in PROMPT_HELPER_CHIPS
            ],
            spacing=2,
            wrap=True,
            run_spacing=0,
        )
        self.prompt_chip_hint = ft.Text(
            "Optional seeds — click to append to the prompt (safe to ignore)",
            size=FONT_SM,
            color=TEXT_MUTED,
        )

        # Always-visible best-practice tips
        self.tips_box = ft.Container(
            content=ft.Column(
                [
                    ft.Text(
                        "Best practices",
                        size=FONT_SM,
                        color=TEXT,
                        weight=ft.FontWeight.W_700,
                    ),
                    ft.Text(
                        "• Character still: full-body or clear upper body, good lighting, "
                        "simple background preferred; head visible and unobstructed.",
                        size=FONT_SM,
                        color=TEXT_MUTED,
                    ),
                    ft.Text(
                        "• Motion reference: clean single subject, 3–10s ideal for most "
                        "models; matching rough framing helps identity lock. "
                        "Long/large clips auto-proxy (original kept).",
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

        # Character still
        self.char_tip = ft.Text(
            "Full-body or clear upper body · good light · simple background",
            size=FONT_SM,
            color=TEXT_MUTED,
        )
        self.char_label = ft.Text(
            "No character still",
            size=FONT_SM,
            color=TEXT_MUTED,
            max_lines=2,
        )
        self.char_preview = ft.Image(
            src="",
            width=140,
            height=140,
            fit=ft.BoxFit.COVER,
            border_radius=6,
            visible=False,
        )
        self.char_empty = ft.Container(
            width=140,
            height=140,
            bgcolor=PANEL,
            border=ft.Border.all(1, BORDER),
            border_radius=6,
            alignment=ft.Alignment.CENTER,
            content=ft.Icon(ft.Icons.PERSON_OUTLINE, size=32, color=TEXT_MUTED),
        )
        self.btn_char = ft.OutlinedButton(
            content="Upload still",
            icon=ft.Icons.IMAGE,
            on_click=self._pick_character,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
        )
        self.btn_char_clear = ft.TextButton(
            content="Clear",
            on_click=self._clear_character,
            style=ft.ButtonStyle(color=TEXT_MUTED),
        )
        self.char_prev = PreviousSourcesStrip(
            page,
            get_output_dir=lambda: self.state.output_dir,
            on_load=self._on_char_from_strip,
            media_kind="image",
        )
        self.char_resolve = ResolveSourcesStrip(
            page,
            on_load=self._on_char_from_strip,
            media_kind="image",
        )

        # Motion reference
        self.motion_tip = ft.Text(
            "Clean single-subject motion · 3–10s ideal · matching framing helps",
            size=FONT_SM,
            color=TEXT_MUTED,
        )
        self.motion_label = ft.Text(
            "No motion reference",
            size=FONT_SM,
            color=TEXT_MUTED,
            max_lines=2,
        )
        self.motion_duration_text = ft.Text(
            "",
            size=FONT_SM,
            color=TEXT,
            weight=ft.FontWeight.W_600,
            visible=False,
        )
        self.motion_poster = ft.Image(
            src="",
            width=160,
            height=90,
            fit=ft.BoxFit.COVER,
            border_radius=6,
            visible=False,
        )
        self.motion_empty = ft.Container(
            width=160,
            height=90,
            bgcolor=PANEL,
            border=ft.Border.all(1, BORDER),
            border_radius=6,
            alignment=ft.Alignment.CENTER,
            content=ft.Icon(ft.Icons.MOVIE_OUTLINED, size=28, color=TEXT_MUTED),
        )
        self.btn_motion = ft.OutlinedButton(
            content="Upload video",
            icon=ft.Icons.MOVIE,
            on_click=self._pick_motion,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
        )
        self.btn_motion_clear = ft.TextButton(
            content="Clear",
            on_click=self._clear_motion,
            style=ft.ButtonStyle(color=TEXT_MUTED),
        )
        self.motion_resolve = ResolveSourcesStrip(
            page,
            on_load=self._on_motion_from_strip,
            media_kind="video",
        )

        # Non-blocking proxy status (large/long inputs) — near motion + under Generate
        self.proxy_note = ft.Text(
            "",
            size=FONT_SM,
            color=ACCENT_BRIGHT,
            weight=ft.FontWeight.W_600,
            visible=False,
            max_lines=2,
        )

        # Slot containers for Send-to highlight (character vs motion reference)
        self.char_slot = ft.Container(
            content=ft.Column(
                [
                    label("Character / subject", muted=True),
                    self.char_tip,
                    ft.Stack(
                        [self.char_empty, self.char_preview], width=140, height=140
                    ),
                    self.char_label,
                    ft.Row([self.btn_char, self.btn_char_clear], spacing=6),
                    self.char_prev.root,
                    self.char_resolve.root,
                ],
                spacing=6,
                tight=True,
            ),
            border=ft.Border.all(1, BORDER),
            border_radius=8,
            padding=10,
            bgcolor=PANEL_ELEVATED,
        )
        self.motion_slot = ft.Container(
            content=ft.Column(
                [
                    label("Motion reference", muted=True),
                    self.motion_tip,
                    ft.Stack(
                        [self.motion_empty, self.motion_poster], width=160, height=90
                    ),
                    self.motion_label,
                    self.motion_duration_text,
                    self.proxy_note,
                    ft.Row([self.btn_motion, self.btn_motion_clear], spacing=6),
                    self.motion_resolve.root,
                ],
                spacing=6,
                tight=True,
            ),
            border=ft.Border.all(1, BORDER),
            border_radius=8,
            padding=10,
            bgcolor=PANEL_ELEVATED,
        )

        self.cost_text, self.cost_box = make_estimated_cost_box(initial="Est. cost: —")
        self.btn_generate = ft.FilledButton(
            content="Generate motion sync",
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

        self.cost_text.value = self._cost_label()
        self._sync_model_controls()
        self.state.on_keys_changed(self.apply_key_gates)
        self.apply_key_gates()

    # ----- layout -----

    def build(self) -> ft.Control:
        from media_studio.flet_layout import make_split_workspace
        from media_studio.flet_theme import RAIL_WIDTH

        left = [
            section_title("Motion Sync"),
            ft.Text(
                "Transfer motion from a driving clip onto a character still while "
                "preserving identity — realtor hooks, trend actions, etc.",
                size=FONT_SM,
                color=TEXT_MUTED,
            ),
            self.tips_box,
            ft.Divider(height=1, color=BORDER),
            self.char_slot,
            self.motion_slot,
            ft.Divider(height=1, color=BORDER),
            ft.Row([self.model_dd], spacing=0),
            self.model_best_for,
            self.model_notes,
            self.keep_audio,
            ft.Row([self.orient_dd], spacing=0),
            self.orient_hint,
            self.adapt_motion,
            self.enhance_identity,
            self.enhance_identity_hint,
            self.wan_toggles_hint,
            self.accel_dd,
            self.prompt,
            self.prompt_chip_hint,
            self.prompt_chips,
            ft.Row([self.btn_enhance, self.btn_generate], spacing=8),
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

    # ----- helpers -----

    def apply_key_gates(self) -> None:
        from media_studio.secrets_store import has_fal_key, has_xai_key

        ready = has_fal_key()
        if not self.state.is_busy("motion_sync"):
            self.btn_generate.disabled = not ready
            self.btn_generate.tooltip = (
                None if ready else "Add your FAL API key in Settings"
            )
            xai = has_xai_key()
            self.btn_enhance.disabled = not xai
            self.btn_enhance.tooltip = (
                "Rewrite optional prompt for the motion-transfer model"
                if xai
                else "Add xAI API key for Enhance"
            )

    def _current_spec(self):
        return find_motion_sync_model(_dd(self.model_dd)) or default_motion_sync_model()

    def _duration_for_cost(self) -> float:
        if self._motion_duration_s and self._motion_duration_s > 0:
            return float(self._motion_duration_s)
        return 5.0

    def _cost_label(self) -> str:
        try:
            return format_motion_sync_cost(
                self._current_spec(),
                duration_s=self._duration_for_cost(),
            )
        except Exception:
            return "Est. cost: —"

    async def _refresh_cost(self, e: ft.ControlEvent | None = None) -> None:
        self.cost_text.value = self._cost_label()
        try:
            self.page.update()
        except Exception:
            pass

    def _sync_model_controls(self) -> None:
        spec = self._current_spec()
        is_wan = "wan" in (spec.key or "")
        self.keep_audio.visible = bool(spec.supports_keep_audio)
        if spec.supports_keep_audio:
            # Only reset default when switching onto a Kling-class model
            if self.keep_audio.value is None:
                self.keep_audio.value = bool(spec.default_keep_audio)
        self.orient_dd.visible = bool(spec.supports_character_orientation)
        self.orient_hint.visible = bool(spec.supports_character_orientation)
        self.adapt_motion.visible = bool(spec.supports_adapt_motion)
        was_identity = bool(self.enhance_identity.visible)
        self.enhance_identity.visible = bool(spec.supports_enhance_identity)
        # Helper lines track the Wan toggles (hide for Kling)
        show_wan_toggles = bool(
            spec.supports_adapt_motion or spec.supports_enhance_identity
        )
        self.enhance_identity_hint.visible = bool(spec.supports_enhance_identity)
        self.wan_toggles_hint.visible = show_wan_toggles
        # When switching onto Wan, seed default (off = current best practice);
        # hide entirely for Kling. Keep user choice while staying on Wan.
        if self.enhance_identity.visible and not was_identity:
            self.enhance_identity.value = bool(spec.default_enhance_identity)
        self.accel_dd.visible = is_wan
        if is_wan:
            self.adapt_motion.value = bool(spec.default_adapt_motion)

    def _orientation_api(self) -> str:
        if not self.orient_dd.visible:
            return "video"
        return orientation_ui_to_api(_dd(self.orient_dd))

    async def _on_orient(self, e: ft.ControlEvent | None = None) -> None:
        ori = self._orientation_api()
        if ori == "image":
            self.orient_hint.value = (
                "Match image: orientation follows the still — better for camera moves "
                "(API max ~10s). Long clips auto-proxy to ≤10s."
            )
        else:
            self.orient_hint.value = (
                "Match video: orientation follows the driving clip — better for complex "
                "body motion (API up to 30s). We still auto-proxy long/large clips to "
                "≤10s for reliability."
            )
        self.cost_text.value = self._cost_label()
        try:
            self.page.update()
        except Exception:
            pass

    def _make_prompt_chip(self, chip: str):
        async def _click(_e: ft.ControlEvent) -> None:
            cur = (self.prompt.value or "").strip()
            if chip.lower() in cur.lower():
                return
            self.prompt.value = f"{cur}, {chip}".lstrip(", ").strip()
            try:
                self.page.update()
            except Exception:
                pass

        return _click

    async def _on_model(self, e: ft.ControlEvent | None = None) -> None:
        spec = self._current_spec()
        self.model_notes.value = spec.notes or ""
        try:
            from media_studio.flet_model_hint import update_best_for_line

            update_best_for_line(
                self.model_best_for, spec.label, dropdown=self.model_dd
            )
        except Exception:
            pass
        # Apply model defaults for audio when switching models
        if spec.supports_keep_audio:
            self.keep_audio.value = bool(spec.default_keep_audio)
        self._sync_model_controls()
        self.cost_text.value = self._cost_label()
        try:
            self.page.update()
        except Exception:
            pass

    # ----- proxy status + slot highlight -----

    def _refresh_proxy_note(self, *, force_used: bool = False, note: str | None = None) -> None:
        """
        Show short non-blocking proxy tip near motion reference when large/long
        inputs will (or did) auto-proxy. Clears when neither slot needs it.
        """
        from media_studio.motion_sync_prep import (
            PROXY_NOTE,
            motion_will_need_proxy,
            still_will_need_proxy,
        )

        if force_used:
            text = (note or PROXY_NOTE).strip() or PROXY_NOTE
            self.proxy_note.value = text
            self.proxy_note.visible = True
            return

        needs = False
        if self._character_path:
            try:
                needs = needs or still_will_need_proxy(self._character_path)
            except Exception:
                pass
        if self._motion_path:
            try:
                needs = needs or motion_will_need_proxy(
                    self._motion_path, duration_s=self._motion_duration_s
                )
            except Exception:
                pass
        if needs:
            self.proxy_note.value = PROXY_NOTE
            self.proxy_note.visible = True
        else:
            self.proxy_note.value = ""
            self.proxy_note.visible = False

    def _clear_proxy_note(self) -> None:
        self.proxy_note.value = ""
        self.proxy_note.visible = False

    def _highlight_slot(self, slot: str) -> None:
        """Accent-border Character or Motion reference after Send-to."""
        for name, box in (("character", self.char_slot), ("motion", self.motion_slot)):
            try:
                if name == slot:
                    box.border = ft.Border.all(2, ACCENT)
                    box.bgcolor = PANEL
                else:
                    box.border = ft.Border.all(1, BORDER)
                    box.bgcolor = PANEL_ELEVATED
            except Exception:
                pass

    def receive_character(self, path: str) -> bool:
        """Library / Send-to: set character still and highlight the slot."""
        ok = self._set_character(path, update=False)
        if ok:
            self._highlight_slot("character")
            try:
                from media_studio.flet_dialogs import show_snack

                show_snack(
                    self.page, f"Motion Sync · Character: {Path(path).name}"
                )
            except Exception:
                pass
        try:
            self.page.update()
        except Exception:
            pass
        return ok

    def receive_motion(self, path: str) -> bool:
        """Library / Send-to: set driving video and highlight the slot."""
        ok = self._set_motion(path, update=False)
        if ok:
            self._highlight_slot("motion")
            try:
                from media_studio.flet_dialogs import show_snack

                show_snack(
                    self.page, f"Motion Sync · Motion reference: {Path(path).name}"
                )
            except Exception:
                pass
        try:
            self.page.update()
        except Exception:
            pass
        return ok

    # ----- character -----

    async def _pick_character(self, e: ft.ControlEvent) -> None:
        try:
            files = await pick_image(
                self.page, dialog_title="Character / subject still"
            )
        except Exception as exc:
            self.status.value = f"Picker error: {exc}"
            self.page.update()
            return
        if not files or not files[0].path:
            return
        self._set_character(files[0].path)

    async def _clear_character(self, e: ft.ControlEvent) -> None:
        self._character_path = None
        self.char_preview.src = ""
        self.char_preview.visible = False
        self.char_empty.visible = True
        self.char_label.value = "No character still"
        self._refresh_proxy_note()
        try:
            self.page.update()
        except Exception:
            pass

    def _on_char_from_strip(self, path: str) -> None:
        self._set_character(path)

    def _set_character(self, path: str, *, update: bool = True) -> bool:
        p = Path(path)
        if not p.is_file():
            self.status.value = f"Missing still: {path}"
            if update:
                try:
                    self.page.update()
                except Exception:
                    pass
            return False
        self._character_path = str(p.resolve())
        self.char_label.value = f"Character: {p.name}"
        self.char_preview.src = self._character_path
        self.char_preview.visible = True
        self.char_empty.visible = False
        try:
            self.char_prev.record_and_refresh(self._character_path)
        except Exception:
            pass
        self.status.value = f"Character loaded: {p.name}"
        self._refresh_proxy_note()
        if update:
            try:
                self.page.update()
            except Exception:
                pass
        return True

    # ----- motion -----

    async def _pick_motion(self, e: ft.ControlEvent) -> None:
        try:
            files = await pick_video(
                self.page, dialog_title="Motion reference (driving clip)"
            )
        except Exception as exc:
            self.status.value = f"Picker error: {exc}"
            self.page.update()
            return
        if not files or not files[0].path:
            return
        self._set_motion(files[0].path)

    async def _clear_motion(self, e: ft.ControlEvent) -> None:
        self._motion_path = None
        self._motion_duration_s = None
        self.motion_poster.src = ""
        self.motion_poster.visible = False
        self.motion_empty.visible = True
        self.motion_label.value = "No motion reference"
        self.motion_duration_text.value = ""
        self.motion_duration_text.visible = False
        self._refresh_proxy_note()
        self.cost_text.value = self._cost_label()
        try:
            self.page.update()
        except Exception:
            pass

    def _on_motion_from_strip(self, path: str) -> None:
        self._set_motion(path)

    def _set_motion(self, path: str, *, update: bool = True) -> bool:
        p = Path(path)
        if not p.is_file():
            self.status.value = f"Missing video: {path}"
            if update:
                try:
                    self.page.update()
                except Exception:
                    pass
            return False
        self._motion_path = str(p.resolve())
        self.motion_label.value = f"Motion: {p.name}"
        dur = probe_video_duration(self._motion_path)
        self._motion_duration_s = float(dur) if dur and dur > 0 else None
        if self._motion_duration_s:
            self.motion_duration_text.value = (
                f"Duration: {self._motion_duration_s:.1f}s"
            )
            self.motion_duration_text.visible = True
        else:
            self.motion_duration_text.value = "Duration: unknown (will estimate cost at 5s)"
            self.motion_duration_text.visible = True
        try:
            from media_studio.media import video_poster_path

            poster = video_poster_path(self._motion_path)
            if poster and Path(poster).is_file():
                self.motion_poster.src = poster
                self.motion_poster.visible = True
                self.motion_empty.visible = False
            else:
                self.motion_poster.visible = False
                self.motion_empty.visible = True
        except Exception:
            self.motion_poster.visible = False
            self.motion_empty.visible = True
        self.cost_text.value = self._cost_label()
        self.status.value = f"Motion loaded: {p.name}"
        self._refresh_proxy_note()
        if update:
            try:
                self.page.update()
            except Exception:
                pass
        return True

    # ----- enhance / generate -----

    async def _on_enhance(self, e: ft.ControlEvent) -> None:
        spec = self._current_spec()

        def _extra() -> dict[str, Any]:
            return {
                "workspace": "motion_sync",
                "mode": "motion_transfer",
                "model": spec.label,
                "endpoint": spec.endpoint,
                "has_character": bool(self._character_path),
                "has_motion": bool(self._motion_path),
                "motion_duration_s": self._motion_duration_s,
                "guidance": (
                    "Rewrite the optional prompt for Kling / Wan motion-control. "
                    "Focus on environment, wardrobe, lighting, and identity notes — "
                    "do not invent camera moves (motion comes from the driving clip). "
                    "Do not invent unsupported API fields. Keep concise and model-ready."
                ),
            }

        await run_prompt_enhance(
            page=self.page,
            state=self.state,
            prompt_field=self.prompt,
            get_model=lambda: _dd(self.model_dd),
            get_extra_context=_extra,
            status_ctrl=self.status,
            job_progress=self.job_progress,
            enhance_btn=self.btn_enhance,
            busy_controls=[self.btn_generate],
            context_label="motion sync prompt",
            allow_empty_with_context=True,
            busy_scope="motion_sync",
        )
        self.apply_key_gates()
        try:
            self.page.update()
        except Exception:
            pass

    async def _run(self, e: ft.ControlEvent) -> None:
        if self.state.is_busy("motion_sync"):
            return
        from media_studio.secrets_store import has_fal_key

        if not has_fal_key():
            self.status.value = "FAL API key required — open Settings (gear icon)."
            self.page.update()
            return

        if not self._character_path:
            self.status.value = (
                "Add a character still first (full-body or clear upper body works best)."
            )
            self.page.update()
            return
        if not self._motion_path:
            self.status.value = (
                "Add a motion reference video (clean subject motion, ~3–30s)."
            )
            self.page.update()
            return

        spec = self._current_spec()
        try:
            from media_studio.flet_dialogs import confirm_cost_if_needed
            from media_studio.motion_sync_registry import estimate_motion_sync_cost

            est = estimate_motion_sync_cost(
                spec, duration_s=self._duration_for_cost()
            )
            ok = await confirm_cost_if_needed(
                self.page,
                estimated_usd=float(est or 0),
                job_label=f"Motion Sync · {spec.label}",
            )
            if not ok:
                self.status.value = "Generate cancelled (cost guard)."
                self.page.update()
                return
        except Exception:
            pass

        if not self.state.try_busy("motion_sync"):
            return
        self.btn_generate.disabled = True
        try:
            self.player.clear()
        except Exception:
            pass
        self.job_progress.start("Starting Motion Sync…", self.page)
        self.status.value = f"Running {spec.label}…"
        self.page.update()

        def on_progress(msg: str) -> None:
            self.job_progress.set_message(classify_progress(msg), self.page)

        try:
            from media_studio.job_context import to_thread_with_job

            result = await to_thread_with_job(
                self.state,
                run_motion_sync,
                character_path=self._character_path,
                motion_path=self._motion_path,
                model_label=_dd(self.model_dd),
                prompt=(self.prompt.value or "").strip() or None,
                keep_original_sound=bool(self.keep_audio.value)
                if self.keep_audio.visible
                else None,
                character_orientation=self._orientation_api()
                if self.orient_dd.visible
                else None,
                adapt_motion=bool(self.adapt_motion.value)
                if self.adapt_motion.visible
                else None,
                enhance_identity=bool(self.enhance_identity.value)
                if self.enhance_identity.visible
                else None,
                acceleration=_dd(self.accel_dd) if self.accel_dd.visible else None,
                output_dir=self.state.output_dir,
                on_progress=on_progress,
            )
            self.cost_text.value = result.cost_label or self._cost_label()
            if getattr(result, "used_proxy", False):
                self._refresh_proxy_note(
                    force_used=True,
                    note=getattr(result, "proxy_note", None) or None,
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

            err = friendly_error(exc, context="Motion Sync")
            self.job_progress.finish_error(err, self.page)
            self.status.value = err
            traceback.print_exc()
        finally:
            self.state.clear_busy("motion_sync")
            self.apply_key_gates()
            try:
                self.page.update()
            except Exception:
                pass
