"""Audio tab — Music, SFX, Ambience, Voiceover, Voice Clone."""

from __future__ import annotations

import asyncio
import traceback
from pathlib import Path
from typing import TYPE_CHECKING

import flet as ft

from media_studio.ambience_builder import (
    DENSITY as AMB_DENSITY,
    DURATIONS_S as AMB_DURATIONS,
    LAYER_LEVELS as AMB_LAYER_LEVELS,
    LAYERS as AMB_LAYERS,
    LOCATIONS as AMB_LOCATIONS,
    TIMES as AMB_TIMES,
    WEATHER as AMB_WEATHER,
    build_ambience_prompt,
    clear_ambience_values,
)
from media_studio.audio_registry import (
    AMBIENCE_MODELS,
    ELEVENLABS_VOICES,
    MUSIC_MODELS,
    SFX_MODELS,
    VIDEO_SFX_MODELS,
    VOICE_CLONE_MODELS,
    VOICEOVER_MODELS,
    VOICEOVER_TONES,
    ambience_labels,
    default_voices_for_model,
    find_audio,
    format_audio_cost,
    music_labels,
    sfx_labels,
    video_sfx_labels,
    voice_clone_labels,
    voiceover_labels,
)
from media_studio.audio_service import (
    run_ambience,
    run_music,
    run_sfx,
    run_video_sfx,
    run_voice_clone,
    run_voiceover,
)
from media_studio.flet_audio_player import AudioResultBar
from media_studio.flet_prompt_favorites import make_prompt_favorites_bar
from media_studio.flet_enhance import make_enhance_button, run_prompt_enhance
from media_studio.flet_pickers import pick_audio, pick_video
from media_studio.flet_progress import JobProgress, classify_progress
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
    label,
    section_title,
    styled_dropdown,
)
from media_studio.music_builder import (
    ENERGY as MUSIC_ENERGY,
    ERAS as MUSIC_ERAS,
    GENRES as MUSIC_GENRES,
    INSTRUMENTS as MUSIC_INSTRUMENTS,
    MOODS as MUSIC_MOODS,
    TEMPO_PRESETS as MUSIC_TEMPO,
    VOCALS as MUSIC_VOCALS,
    build_music_prompt,
    clear_builder_values,
    default_subgenre,
    subgenres_for,
    vocals_is_instrumental,
)
from media_studio.my_voices import (
    delete_voice,
    load_voices,
    my_voice_names,
    voice_choice_labels,
)
from media_studio.sfx_builder import (
    CATEGORIES as SFX_CATEGORIES,
    INTENSITIES as SFX_INTENSITIES,
    LENGTHS as SFX_LENGTHS,
    TEXTURES as SFX_TEXTURES,
    VS_EMPHASIS,
    VS_EXCLUDES,
    VS_PACES,
    VS_STYLES,
    build_sfx_prompt,
    build_video_sfx_prompt,
    clear_sfx_builder_values,
    clear_video_sfx_builder_values,
    duration_for_length,
)

if TYPE_CHECKING:
    from media_studio.flet_app import StudioState


def _dd_value(dd: ft.Dropdown) -> str | None:
    return dd.value


def _cost_box(text_ctrl: ft.Text) -> ft.Container:
    return ft.Container(
        content=text_ctrl,
        bgcolor=PANEL_ELEVATED,
        border=ft.Border.all(1, ACCENT),
        border_radius=6,
        padding=ft.Padding.symmetric(horizontal=10, vertical=6),
    )


class AudioView:
    def __init__(self, page: ft.Page, state: StudioState) -> None:
        self.page = page
        self.state = state
        self._build_music()
        self._build_sfx()
        self._build_ambience()
        self._build_voiceover()
        self._build_clone()
        self.state.on_keys_changed(self.apply_key_gates)
        self.apply_key_gates()

        # One audio panel at a time (pill nav) — Video→SFX is first-class
        self._audio_panels: dict[str, ft.Control] = {
            "music": self.music_card,
            "sfx": self.sfx_card,
            "video_sfx": self.vs_card,
            "ambience": self.ambience_card,
            "voiceover": self.voice_card,
            "clone": self.clone_card,
        }
        last = getattr(state, "audio_selected_id", None)
        # Migrate old sessions that only had "sfx" hosting Video→SFX
        if last == "sfx" and getattr(state, "_audio_wanted_vsfx", False):
            last = "video_sfx"
        self._selected_audio = last if last in self._audio_panels else "music"
        state.audio_selected_id = self._selected_audio

        self._audio_host = ft.Container(expand=True)
        self._pill_nav = PillNav(
            [
                ("music", "Music"),
                ("sfx", "SFX"),
                ("video_sfx", "Video → SFX"),
                ("ambience", "Ambience"),
                ("voiceover", "Voiceover"),
                ("clone", "Voice Clone"),
            ],
            selected=self._selected_audio,
            on_change=self._on_audio_pill,
        )
        self._apply_audio_visibility()

    def apply_key_gates(self) -> None:
        """Disable audio generate actions when FAL key is missing."""
        from media_studio.secrets_store import has_fal_key, has_xai_key

        ready = has_fal_key()
        tip = None if ready else "Add your FAL API key in Settings to generate"
        xai = has_xai_key()
        xai_tip = (
            "Rewrite prompt for the selected model (does not change model)"
            if xai
            else "Add your xAI API key in Settings to Enhance prompts"
        )
        if self.state.is_busy("audio"):
            return
        for btn in (
            getattr(self, "mu_btn", None),
            getattr(self, "sfx_btn", None),
            getattr(self, "vs_btn", None),
            getattr(self, "amb_btn", None),
            getattr(self, "vo_btn", None),
            getattr(self, "cl_btn", None),
        ):
            if btn is None:
                continue
            btn.disabled = not ready
            btn.tooltip = tip
        for enh in (
            getattr(self, "mu_enhance", None),
            getattr(self, "sfx_enhance", None),
            getattr(self, "vs_enhance", None),
            getattr(self, "amb_enhance", None),
            getattr(self, "vo_enhance", None),
            getattr(self, "cl_enhance", None),
        ):
            if enh is None:
                continue
            enh.disabled = not xai
            enh.tooltip = xai_tip

    def _require_fal(self, status_ctrl: ft.Text) -> bool:
        from media_studio.secrets_store import has_fal_key

        if has_fal_key():
            return True
        status_ctrl.value = "FAL API key required — open Settings (gear icon) to add your key."
        try:
            self.page.update()
        except Exception:
            pass
        return False

    async def _enhance_music(self, e: ft.ControlEvent) -> None:
        await run_prompt_enhance(
            page=self.page,
            state=self.state,
            prompt_field=self.mu_prompt,
            get_model=lambda: _dd_value(self.mu_model),
            status_ctrl=self.mu_status,
            job_progress=self.mu_progress,
            enhance_btn=self.mu_enhance,
            busy_controls=[self.mu_btn],
            context_label="music prompt",
        )
        self.apply_key_gates()
        try:
            self.page.update()
        except Exception:
            pass

    async def _enhance_sfx(self, e: ft.ControlEvent) -> None:
        await run_prompt_enhance(
            page=self.page,
            state=self.state,
            prompt_field=self.sfx_prompt,
            get_model=lambda: _dd_value(self.sfx_model),
            status_ctrl=self.sfx_status,
            job_progress=self.sfx_progress,
            enhance_btn=self.sfx_enhance,
            busy_controls=[self.sfx_btn],
            context_label="SFX prompt",
        )
        self.apply_key_gates()
        try:
            self.page.update()
        except Exception:
            pass

    async def _enhance_vs(self, e: ft.ControlEvent) -> None:
        # Rebuild from structured controls first, then let Grok polish
        try:
            self.vs_prompt.value = build_video_sfx_prompt(**self._vs_kwargs())
        except Exception:
            pass
        await run_prompt_enhance(
            page=self.page,
            state=self.state,
            prompt_field=self.vs_prompt,
            get_model=lambda: _dd_value(self.vs_model),
            get_video=lambda: self.vs_video_path,
            status_ctrl=self.vs_status,
            job_progress=self.vs_progress,
            enhance_btn=self.vs_enhance,
            busy_controls=[self.vs_btn],
            context_label="video SFX prompt",
        )
        self.apply_key_gates()
        try:
            self.page.update()
        except Exception:
            pass

    async def _enhance_ambience(self, e: ft.ControlEvent) -> None:
        await run_prompt_enhance(
            page=self.page,
            state=self.state,
            prompt_field=self.amb_prompt,
            get_model=lambda: _dd_value(self.amb_model),
            status_ctrl=self.amb_status,
            job_progress=self.amb_progress,
            enhance_btn=self.amb_enhance,
            busy_controls=[self.amb_btn],
            context_label="ambience prompt",
        )
        self.apply_key_gates()
        try:
            self.page.update()
        except Exception:
            pass

    async def _enhance_voiceover(self, e: ft.ControlEvent) -> None:
        await run_prompt_enhance(
            page=self.page,
            state=self.state,
            prompt_field=self.vo_script,
            get_model=lambda: _dd_value(self.vo_model),
            status_ctrl=self.vo_status,
            job_progress=self.vo_progress,
            enhance_btn=self.vo_enhance,
            busy_controls=[self.vo_btn],
            context_label="script",
        )
        self.apply_key_gates()
        try:
            self.page.update()
        except Exception:
            pass

    async def _enhance_clone(self, e: ft.ControlEvent) -> None:
        await run_prompt_enhance(
            page=self.page,
            state=self.state,
            prompt_field=self.cl_preview_text,
            get_model=lambda: _dd_value(self.cl_model),
            status_ctrl=self.cl_status,
            job_progress=self.cl_progress,
            enhance_btn=self.cl_enhance,
            busy_controls=[self.cl_btn],
            context_label="preview text",
        )
        self.apply_key_gates()
        try:
            self.page.update()
        except Exception:
            pass

    def _on_audio_pill(self, audio_id: str) -> None:
        self._selected_audio = audio_id
        self.state.audio_selected_id = audio_id
        self._apply_audio_visibility()
        try:
            self.page.update()
        except Exception:
            pass

    def _apply_audio_visibility(self) -> None:
        active = (
            self._selected_audio if self._selected_audio in self._audio_panels else "music"
        )
        for aid, ctrl in self._audio_panels.items():
            try:
                ctrl.visible = aid == active
            except Exception:
                pass
        panel = self._audio_panels[active]
        try:
            panel.visible = True
        except Exception:
            pass
        # Single scroll: ListView host only (no nested form scroll)
        self._audio_host.content = ft.ListView(
            controls=[
                ft.Container(
                    content=panel,
                    padding=ft.Padding.only(right=8, bottom=16),
                    # Cap card width on ultra-wide so empty margin isn't a grey slab
                    width=900,
                )
            ],
            expand=True,
            spacing=0,
            padding=ft.Padding.only(bottom=8),
        )

    def build(self) -> ft.Control:
        self._apply_audio_visibility()
        return ft.Column(
            [
                section_title("Audio"),
                ft.Text(
                    "Utility tools — not a DAW. Files save under the Studio output folder. "
                    "One tool at a time.",
                    size=FONT_SM,
                    color=TEXT_MUTED,
                ),
                self._pill_nav.control,
                ft.Divider(height=1, color=BORDER),
                self._audio_host,  # sole ListView scroll region
            ],
            spacing=10,
            expand=True,
            alignment=ft.MainAxisAlignment.START,
        )

    # ----- Music -----

    def _build_music(self) -> None:
        d = clear_builder_values()
        self.mu_genre = styled_dropdown(
            label_text="Genre",
            options=MUSIC_GENRES,
            value=d["genre"],
            on_select=self._music_genre_change,
            expand=True,
        )
        self.mu_sub = styled_dropdown(
            label_text="Sub-genre",
            options=subgenres_for(d["genre"]),
            value=d["subgenre"],
            on_select=self._music_rebuild,
            expand=True,
        )
        self.mu_era = styled_dropdown(
            label_text="Era", options=MUSIC_ERAS, value=d["era"], on_select=self._music_rebuild, expand=True
        )
        self.mu_tempo = styled_dropdown(
            label_text="Tempo", options=MUSIC_TEMPO, value=d["tempo"], on_select=self._music_rebuild, expand=True
        )
        self.mu_bpm = ft.TextField(
            label="Exact BPM (optional)",
            value="",
            dense=True,
            filled=True,
            fill_color=PANEL_ELEVATED,
            border_color=BORDER,
            color=TEXT,
            text_size=FONT_SM,
            width=120,
            on_change=self._music_rebuild,
        )
        self.mu_mood = styled_dropdown(
            label_text="Mood", options=MUSIC_MOODS, value=d["mood"], on_select=self._music_rebuild, expand=True
        )
        self.mu_energy = styled_dropdown(
            label_text="Energy", options=MUSIC_ENERGY, value=d["energy"], on_select=self._music_rebuild, expand=True
        )
        self.mu_vocals = styled_dropdown(
            label_text="Vocals",
            options=MUSIC_VOCALS,
            value=d.get("vocals") or "Instrumental only",
            on_select=self._music_rebuild,
            expand=True,
        )
        self.mu_instruments = styled_dropdown(
            label_text="Instruments focus",
            options=MUSIC_INSTRUMENTS,
            value=d.get("instruments") or MUSIC_INSTRUMENTS[0],
            on_select=self._music_rebuild,
            expand=True,
        )
        # High-contrast labels + full-width fields (Music polish)
        self.mu_lyrics_label = ft.Text(
            "Lyrics (optional)",
            size=FONT_SM,
            color=TEXT,
            weight=ft.FontWeight.W_700,
        )
        self.mu_lyrics = ft.TextField(
            hint_text="Only included when Vocals is not Instrumental — paste or type lyrics here",
            multiline=True,
            min_lines=3,
            max_lines=6,
            filled=True,
            fill_color=PANEL_ELEVATED,
            border_color=BORDER,
            focused_border_color=ACCENT,
            color=TEXT,
            text_size=FONT_SM,
            # no expand — content-sized height (avoid grey slab under prompt/star)
            on_change=self._music_rebuild,
        )
        # Persistent free-text fields — never overwritten by structured rebuild
        self.mu_exclude_label = ft.Text(
            "Exclude / Avoid (optional)",
            size=FONT_SM,
            color=TEXT,
            weight=ft.FontWeight.W_700,
        )
        self.mu_exclude = ft.TextField(
            hint_text='e.g. no choir, no spoken word, no harsh distortion',
            value=d.get("exclude") or "",
            dense=True,
            filled=True,
            fill_color=PANEL_ELEVATED,
            border_color=BORDER,
            focused_border_color=ACCENT,
            color=TEXT,
            text_size=FONT_SM,
            on_change=self._music_rebuild,
        )
        self.mu_notes_label = ft.Text(
            "Custom notes / extras",
            size=FONT_SM,
            color=TEXT,
            weight=ft.FontWeight.W_700,
        )
        self.mu_notes = ft.TextField(
            hint_text="Always kept when Genre/Mood/etc. change — appended to the prompt",
            value=d.get("custom_notes") or "",
            multiline=True,
            min_lines=2,
            max_lines=4,
            filled=True,
            fill_color=PANEL_ELEVATED,
            border_color=BORDER,
            focused_border_color=ACCENT,
            color=TEXT,
            text_size=FONT_SM,
            on_change=self._music_rebuild,
        )
        self.mu_prompt_label = ft.Text(
            "Music prompt (auto-built — editable)",
            size=FONT_SM,
            color=TEXT,
            weight=ft.FontWeight.W_700,
        )
        self.mu_prompt = ft.TextField(
            value=build_music_prompt(**self._music_prompt_kwargs_from_defaults(d)),
            hint_text="Structured block rebuilds from dropdowns; notes & exclude stay at the end",
            multiline=True,
            min_lines=5,
            max_lines=10,
            filled=True,
            fill_color=PANEL_ELEVATED,
            border_color=BORDER,
            focused_border_color=ACCENT,
            color=TEXT,
            text_size=FONT_SM,
        )
        self.mu_prompt_favs = make_prompt_favorites_bar(
            self.page,
            get_text=lambda: self.mu_prompt.value,
            set_text=lambda t: setattr(self.mu_prompt, "value", t),
            surface="audio",
            get_meta=lambda: {
                "model": _dd_value(self.mu_model) if hasattr(self, "mu_model") else "",
                "source": "user",
            },
            on_status=lambda m: setattr(self.mu_status, "value", m),
            show_pack_buttons=True,
        )
        self.mu_model = styled_dropdown(
            label_text="Model",
            options=music_labels(),
            value=music_labels()[0],
            on_select=self._music_cost_refresh,
            expand=True,
        )
        self.mu_dur = ft.Slider(
            min=3,
            max=120,
            divisions=117,
            value=30,
            label="Duration {value}s",
            active_color=ACCENT,
            on_change=self._music_cost_refresh,
        )
        self.mu_cost = ft.Text(self._music_cost(), size=FONT_SM, color=TEXT, weight=ft.FontWeight.W_600)
        self.mu_status = ft.Text("", size=FONT_SM, color=TEXT_MUTED, max_lines=3)
        self.mu_progress = JobProgress()
        self.mu_player = AudioResultBar(self.page)
        self.mu_btn = ft.FilledButton(
            content="Generate music",
            on_click=self._run_music,
            style=ft.ButtonStyle(bgcolor=ACCENT_BRIGHT, color=TEXT),
        )
        self.mu_enhance = make_enhance_button(on_click=self._enhance_music)

        self.music_card = ft.Container(
            bgcolor=PANEL,
            border=ft.Border.all(1, BORDER),
            border_radius=8,
            padding=12,
            content=ft.Column(
                [
                    section_title("1. Music"),
                    ft.Text("Structured builder → listing / background music.", size=FONT_SM, color=TEXT_MUTED),
                    ft.Row([self.mu_genre, self.mu_sub, self.mu_era], spacing=8),
                    ft.Row([self.mu_tempo, self.mu_bpm, self.mu_mood, self.mu_energy], spacing=8),
                    ft.Row([self.mu_vocals, self.mu_instruments], spacing=8),
                    # Persistent notes / exclude (never wiped by structured rebuild)
                    self.mu_notes_label,
                    self.mu_notes,
                    self.mu_exclude_label,
                    self.mu_exclude,
                    # Lyrics when vocals are on
                    self.mu_lyrics_label,
                    self.mu_lyrics,
                    self.mu_prompt_label,
                    self.mu_prompt,
                    self.mu_prompt_favs.root,
                    ft.Row([self.mu_model], spacing=8),
                    label("Duration (seconds) — used when model supports it", muted=True),
                    self.mu_dur,
                    _cost_box(self.mu_cost),
                    ft.Row([self.mu_enhance, self.mu_btn], spacing=8),
                    self.mu_progress.control,
                    self.mu_status,
                    self.mu_player.control,
                ],
                spacing=8,
                tight=True,
            ),
        )

    @staticmethod
    def _music_prompt_kwargs_from_defaults(d: dict) -> dict:
        return {
            "genre": d.get("genre"),
            "subgenre": d.get("subgenre"),
            "era": d.get("era"),
            "tempo": d.get("tempo"),
            "bpm": d.get("bpm"),
            "mood": d.get("mood"),
            "energy": d.get("energy"),
            "vocals": d.get("vocals") or "Instrumental only",
            "instruments": d.get("instruments"),
            "lyrics": d.get("lyrics") or "",
            "custom_notes": d.get("custom_notes") or "",
            "exclude": d.get("exclude") or "",
        }

    def _music_prompt_kwargs(self) -> dict:
        """Structured fields + persistent notes/exclude (never cleared by rebuild)."""
        bpm_raw = (self.mu_bpm.value or "").strip()
        bpm = None
        if bpm_raw:
            try:
                bpm = int(float(bpm_raw))
            except ValueError:
                bpm = None
        vocals = _dd_value(self.mu_vocals) or "Instrumental only"
        return {
            "genre": _dd_value(self.mu_genre),
            "subgenre": _dd_value(self.mu_sub),
            "era": _dd_value(self.mu_era),
            "tempo": _dd_value(self.mu_tempo),
            "bpm": bpm,
            "mood": _dd_value(self.mu_mood),
            "energy": _dd_value(self.mu_energy),
            "vocals": vocals,
            "instruments": _dd_value(self.mu_instruments),
            "lyrics": self.mu_lyrics.value or "",
            # Read live from notes/exclude fields — never reset on structured change
            "custom_notes": self.mu_notes.value or "",
            "exclude": self.mu_exclude.value or "",
        }

    def _music_is_instrumental(self) -> bool:
        return vocals_is_instrumental(_dd_value(self.mu_vocals))

    def _music_cost(self) -> str:
        spec = find_audio(_dd_value(self.mu_model), MUSIC_MODELS)
        if not spec:
            return "Est. cost: —"
        dur = float(self.mu_dur.value or 30)
        if not spec.supports_duration:
            dur = spec.fixed_duration_s or 30.0
        return format_audio_cost(spec, duration_s=dur)

    def _apply_music_prompt_rebuild(self) -> None:
        """
        Rebuild only the prompt text from structured controls + current notes/exclude.

        Does NOT clear or rewrite mu_notes / mu_exclude field values.
        """
        self.mu_prompt.value = build_music_prompt(**self._music_prompt_kwargs())
        self.mu_cost.value = self._music_cost()
        # Lyrics less relevant when instrumental — keep text, just leave visible

    async def _music_genre_change(self, e: ft.ControlEvent) -> None:
        g = _dd_value(self.mu_genre)
        subs = subgenres_for(g)
        self.mu_sub.options = [ft.DropdownOption(key=x, text=x) for x in subs]
        self.mu_sub.value = default_subgenre(g)
        self._apply_music_prompt_rebuild()
        self.page.update()

    async def _music_rebuild(self, e: ft.ControlEvent) -> None:
        self._apply_music_prompt_rebuild()
        self.page.update()

    async def _music_cost_refresh(self, e: ft.ControlEvent) -> None:
        self.mu_cost.value = self._music_cost()
        self.page.update()

    async def _run_music(self, e: ft.ControlEvent) -> None:
        if self.state.is_busy("audio"):
            return
        if not self._require_fal(self.mu_status):
            return
        if not self.state.try_busy("audio"):
            return
        self.mu_btn.disabled = True
        self.mu_player.clear()
        self.mu_progress.start("Queued…", self.page)
        self.mu_status.value = "Generating music…"
        self.page.update()

        def on_progress(msg: str) -> None:
            self.mu_progress.set_message(classify_progress(msg), self.page)

        try:
            from media_studio.job_context import to_thread_with_job

            r = await to_thread_with_job(
                self.state,
                run_music,
                prompt=self.mu_prompt.value,
                model_label=_dd_value(self.mu_model),
                duration_s=float(self.mu_dur.value or 30),
                instrumental=self._music_is_instrumental(),
                output_dir=self.state.output_dir,
                on_progress=on_progress,
            )
            self.mu_cost.value = r.cost_label or self._music_cost()
            if r.ok and r.path:
                done = r.status or "OK"
                self.mu_progress.finish_ok(done, self.page)
                self.mu_status.value = done
                self.mu_player.set_result(r.path)
            else:
                err = r.status or "Failed."
                self.mu_progress.finish_error(err, self.page)
                self.mu_status.value = err
        except Exception as exc:
            self.mu_progress.finish_error(f"Error: {exc}", self.page)
            self.mu_status.value = f"Error: {exc}"
            traceback.print_exc()
        finally:
            self.state.clear_busy("audio")
            self.apply_key_gates()
            self.page.update()

    # ----- SFX -----

    def _build_sfx(self) -> None:
        d = clear_sfx_builder_values()
        self.sfx_cat = styled_dropdown(
            label_text="Type / Category",
            options=SFX_CATEGORIES,
            value=d["category"],
            on_select=self._sfx_rebuild,
            expand=True,
        )
        self.sfx_inten = styled_dropdown(
            label_text="Intensity",
            options=SFX_INTENSITIES,
            value=d["intensity"],
            on_select=self._sfx_rebuild,
            expand=True,
        )
        self.sfx_len = styled_dropdown(
            label_text="Length",
            options=SFX_LENGTHS,
            value=d["length"],
            on_select=self._sfx_length_change,
            expand=True,
        )
        self.sfx_tex = styled_dropdown(
            label_text="Character / Texture",
            options=SFX_TEXTURES,
            value=d["texture"],
            on_select=self._sfx_rebuild,
            expand=True,
        )
        self.sfx_detail = ft.TextField(
            label="Free description (optional)",
            dense=True,
            filled=True,
            fill_color=PANEL_ELEVATED,
            border_color=BORDER,
            color=TEXT,
            text_size=FONT_SM,
            on_change=self._sfx_rebuild,
        )
        self.sfx_prompt = ft.TextField(
            label="SFX prompt (auto-built — editable)",
            value=build_sfx_prompt(**d),
            multiline=True,
            min_lines=3,
            max_lines=4,
            filled=True,
            fill_color=PANEL_ELEVATED,
            border_color=BORDER,
            color=TEXT,
            text_size=FONT_SM,
        )
        self.sfx_prompt_favs = make_prompt_favorites_bar(
            self.page,
            get_text=lambda: self.sfx_prompt.value,
            set_text=lambda t: setattr(self.sfx_prompt, "value", t),
            surface="audio",
            get_meta=lambda: {"source": "user"},
            on_status=lambda m: setattr(self.sfx_status, "value", m),
            show_pack_buttons=False,
        )
        self.sfx_model = styled_dropdown(
            label_text="Model",
            options=sfx_labels(),
            value=sfx_labels()[0],
            expand=True,
            on_select=self._sfx_cost_refresh,
        )
        self.sfx_dur = ft.Slider(
            min=0.5,
            max=22,
            divisions=43,
            value=duration_for_length(d["length"]),
            label="Duration {value}s",
            active_color=ACCENT,
            on_change=self._sfx_cost_refresh,
        )
        self.sfx_loop = ft.Checkbox(label="Seamless loop", value=False)
        self.sfx_count = styled_dropdown(
            label_text="Number of variations",
            options=["1", "2", "3", "4"],
            value="1",
            on_select=self._sfx_cost_refresh,
            expand=True,
        )
        self.sfx_cost = ft.Text(self._sfx_cost(), size=FONT_SM, color=TEXT, weight=ft.FontWeight.W_600)
        self.sfx_status = ft.Text("", size=FONT_SM, color=TEXT_MUTED, max_lines=4)
        self.sfx_progress = JobProgress()
        # Up to 4 result slots (each with Play / folder / external)
        self.sfx_result_bars: list[AudioResultBar] = [
            AudioResultBar(self.page) for _ in range(4)
        ]
        self.sfx_results_host = ft.Column(spacing=8)
        # Back-compat: first slot still reachable as sfx_player for smoke tests
        self.sfx_player = self.sfx_result_bars[0]
        self.sfx_btn = ft.FilledButton(
            content="Generate SFX",
            on_click=self._run_sfx,
            style=ft.ButtonStyle(bgcolor=ACCENT_BRIGHT, color=TEXT),
        )
        self.sfx_enhance = make_enhance_button(on_click=self._enhance_sfx)

        # Video-to-SFX (own panel) — multi-model; default audio-track when available
        vd = clear_video_sfx_builder_values()
        self.vs_video_path: str | None = None
        self.vs_duration_s: float | None = None
        self.vs_label = ft.Text("No video", size=FONT_SM, color=TEXT_MUTED)
        _vs_labels = video_sfx_labels()
        # Prefer Mirelo (audio track) as default when present
        _vs_default = next(
            (x for x in _vs_labels if "mirelo" in x.lower()),
            (_vs_labels[0] if _vs_labels else None),
        )
        self.vs_model = styled_dropdown(
            label_text="Video-to-SFX model",
            options=_vs_labels,
            value=_vs_default,
            on_select=self._vs_cost_refresh,
            expand=True,
        )
        self.vs_output_bias = styled_dropdown(
            label_text="Prefer output",
            options=["Audio track (Resolve A1)", "Muxed video"],
            value="Audio track (Resolve A1)",
            on_select=self._vs_cost_refresh,
            expand=True,
        )
        self.vs_model_notes = ft.Text(
            "",
            size=FONT_SM,
            color=TEXT_MUTED,
            max_lines=3,
        )
        self.vs_style = styled_dropdown(
            label_text="Style",
            options=list(VS_STYLES),
            value=vd["style"],
            on_select=self._vs_rebuild,
            expand=True,
        )
        self.vs_pace = styled_dropdown(
            label_text="Pace",
            options=list(VS_PACES),
            value=vd["pace"],
            on_select=self._vs_rebuild,
            expand=True,
        )
        self.vs_emphasis = styled_dropdown(
            label_text="Emphasis",
            options=list(VS_EMPHASIS),
            value=vd["emphasis"],
            on_select=self._vs_rebuild,
            expand=True,
        )
        # Exclude chips (multi-select via checkboxes)
        self.vs_exclude_checks: dict[str, ft.Checkbox] = {}
        default_ex = set(vd.get("excludes") or [])
        for chip in VS_EXCLUDES:
            self.vs_exclude_checks[chip] = ft.Checkbox(
                label=chip,
                value=chip in default_ex,
                on_change=self._vs_rebuild,
            )
        self.vs_note = ft.TextField(
            label="Optional free note",
            hint_text="e.g. soft door closes, kitchen practicals only",
            dense=True,
            filled=True,
            fill_color=PANEL_ELEVATED,
            border_color=BORDER,
            color=TEXT,
            text_size=FONT_SM,
            on_change=self._vs_rebuild,
        )
        self.vs_prompt = ft.TextField(
            label="Compiled prompt (editable — Enhance rewrites)",
            value=build_video_sfx_prompt(**vd),
            multiline=True,
            min_lines=3,
            max_lines=6,
            dense=True,
            filled=True,
            fill_color=PANEL_ELEVATED,
            border_color=BORDER,
            color=TEXT,
            text_size=FONT_SM,
            on_change=self._vs_prompt_changed,
        )
        self.vs_prompt_favs = make_prompt_favorites_bar(
            self.page,
            get_text=lambda: self.vs_prompt.value,
            set_text=lambda t: setattr(self.vs_prompt, "value", t),
            surface="audio",
            get_meta=lambda: {"source": "user"},
            on_status=lambda m: setattr(self.vs_status, "value", m),
            show_pack_buttons=False,
        )
        self.vs_char_hint = ft.Text(
            "",
            size=FONT_SM,
            color=TEXT_MUTED,
            max_lines=2,
        )
        self.vs_cost = ft.Text(
            self._vs_cost_text(),
            size=FONT_SM,
            color=TEXT,
            weight=ft.FontWeight.W_600,
        )
        self.vs_status = ft.Text("", size=FONT_SM, color=TEXT_MUTED, max_lines=4)
        self.vs_progress = JobProgress()
        self.vs_player = AudioResultBar(self.page)
        self.vs_btn = ft.FilledButton(
            content="Generate video SFX",
            on_click=self._run_video_sfx,
            style=ft.ButtonStyle(bgcolor=ACCENT_BRIGHT, color=TEXT),
        )
        self.vs_enhance = make_enhance_button(on_click=self._enhance_vs)
        self.vs_upload = ft.OutlinedButton(
            content="Upload video",
            icon=ft.Icons.VIDEO_FILE,
            on_click=self._pick_vs_video,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
        )
        self._vs_refresh_model_notes()
        self._vs_update_char_hint()

        self.sfx_card = ft.Container(
            bgcolor=PANEL,
            border=ft.Border.all(1, BORDER),
            border_radius=8,
            padding=12,
            content=ft.Column(
                [
                    section_title("2. Sound Effects (SFX)"),
                    ft.Text(
                        "Text → SFX builder. For clip Foley, use the Video → SFX pill.",
                        size=FONT_SM,
                        color=TEXT_MUTED,
                    ),
                    ft.Row([self.sfx_cat, self.sfx_inten, self.sfx_len, self.sfx_tex], spacing=8),
                    self.sfx_detail,
                    self.sfx_prompt,
                    self.sfx_prompt_favs.root,
                    ft.Row([self.sfx_model, self.sfx_count, self.sfx_loop], spacing=8),
                    self.sfx_dur,
                    _cost_box(self.sfx_cost),
                    ft.Row([self.sfx_enhance, self.sfx_btn], spacing=8),
                    self.sfx_progress.control,
                    self.sfx_status,
                    label("Results", muted=True),
                    self.sfx_results_host,
                ],
                spacing=8,
                tight=True,
            ),
        )

        self.vs_card = ft.Container(
            bgcolor=PANEL,
            border=ft.Border.all(1, BORDER),
            border_radius=8,
            padding=12,
            content=ft.Column(
                [
                    section_title("Video → SFX"),
                    ft.Text(
                        "Upload a clip → synced Foley/SFX. Style / Pace / Emphasis chips "
                        "compile a prompt (Enhance rewrites for the selected model). "
                        "Prefer Audio track for Resolve A1 when the model provides it.",
                        size=FONT_SM,
                        color=TEXT_MUTED,
                    ),
                    ft.Row([self.vs_upload, self.vs_label], spacing=8),
                    ft.Row([self.vs_model, self.vs_output_bias], spacing=8),
                    self.vs_model_notes,
                    ft.Row([self.vs_style, self.vs_pace, self.vs_emphasis], spacing=8),
                    label("Exclude", muted=True),
                    ft.Row(list(self.vs_exclude_checks.values()), spacing=8, wrap=True),
                    self.vs_note,
                    self.vs_prompt,
                    self.vs_prompt_favs.root,
                    self.vs_char_hint,
                    _cost_box(self.vs_cost),
                    ft.Row([self.vs_enhance, self.vs_btn], spacing=8),
                    self.vs_progress.control,
                    self.vs_status,
                    self.vs_player.control,
                ],
                spacing=8,
                tight=True,
            ),
        )

    def _sfx_kwargs(self) -> dict:
        return {
            "category": _dd_value(self.sfx_cat),
            "intensity": _dd_value(self.sfx_inten),
            "length": _dd_value(self.sfx_len),
            "texture": _dd_value(self.sfx_tex),
            "detail": self.sfx_detail.value or "",
        }

    def _sfx_variation_count(self) -> int:
        try:
            n = int(_dd_value(self.sfx_count) or "1")
        except (TypeError, ValueError):
            n = 1
        return max(1, min(4, n))

    def _sfx_cost(self) -> str:
        from media_studio.audio_registry import estimate_audio_cost
        from media_studio.pricing import format_job_cost

        spec = find_audio(_dd_value(self.sfx_model), SFX_MODELS)
        if not spec:
            return "Est. cost: —"
        dur = float(self.sfx_dur.value or 5)
        unit = estimate_audio_cost(spec, duration_s=dur)
        n = self._sfx_variation_count()
        total = unit * n
        if n <= 1:
            return format_audio_cost(spec, duration_s=dur)
        return format_job_cost(
            total,
            unit=f"{n} × {dur:.0f}s",
            model=spec.label,
        )

    def _sfx_clear_results(self) -> None:
        for bar in self.sfx_result_bars:
            bar.clear()
        self.sfx_results_host.controls = []

    async def _sfx_rebuild(self, e: ft.ControlEvent) -> None:
        self.sfx_prompt.value = build_sfx_prompt(**self._sfx_kwargs())
        self.sfx_cost.value = self._sfx_cost()
        self.page.update()

    async def _sfx_length_change(self, e: ft.ControlEvent) -> None:
        self.sfx_dur.value = duration_for_length(_dd_value(self.sfx_len))
        self.sfx_prompt.value = build_sfx_prompt(**self._sfx_kwargs())
        self.sfx_cost.value = self._sfx_cost()
        self.page.update()

    async def _sfx_cost_refresh(self, e: ft.ControlEvent) -> None:
        self.sfx_cost.value = self._sfx_cost()
        self.page.update()

    async def _run_sfx(self, e: ft.ControlEvent) -> None:
        if self.state.is_busy("audio"):
            return
        if not self._require_fal(self.sfx_status):
            return
        n = self._sfx_variation_count()
        if not self.state.try_busy("audio"):
            return
        self.sfx_btn.disabled = True
        self._sfx_clear_results()
        self.sfx_progress.start(f"Queued… 0/{n}", self.page)
        self.sfx_status.value = f"Generating SFX (1/{n})…" if n > 1 else "Generating SFX…"
        self.sfx_cost.value = self._sfx_cost()
        self.page.update()

        def on_progress(msg: str) -> None:
            self.sfx_progress.set_message(classify_progress(msg), self.page)

        import random
        import time as _time

        base_seed = random.randint(1, 2_000_000_000)
        ok_paths: list[str] = []
        fail_msgs: list[str] = []
        total_cost_notes: list[str] = []
        t0 = _time.perf_counter()

        try:
            for i in range(n):
                self.sfx_status.value = f"Generating SFX ({i + 1}/{n})…"
                self.sfx_progress.set_message(f"Generating… {i + 1}/{n}", self.page)
                self.page.update()
                seed = base_seed + i * 9973
                from media_studio.job_context import to_thread_with_job

                r = await to_thread_with_job(
                    self.state,
                    run_sfx,
                    prompt=self.sfx_prompt.value,
                    model_label=_dd_value(self.sfx_model),
                    duration_s=float(self.sfx_dur.value or 5),
                    loop=bool(self.sfx_loop.value),
                    output_dir=self.state.output_dir,
                    on_progress=on_progress if n == 1 else None,
                    seed=seed,
                    variation_index=i if n > 1 else None,
                )
                if r.cost_label:
                    total_cost_notes.append(r.cost_label)
                if r.ok and r.path:
                    ok_paths.append(r.path)
                    bar = self.sfx_result_bars[i]
                    label_note = (
                        f"Variation {i + 1}/{n} · {r.cost_label or ''} · {Path(r.path).name}"
                        if n > 1
                        else (r.cost_label or f"Saved: {r.path}")
                    )
                    bar.set_result(
                        r.path,
                        note=label_note.strip(" ·"),
                        stop_current=(i == 0),
                    )
                    if bar.control not in self.sfx_results_host.controls:
                        if n > 1:
                            self.sfx_results_host.controls.append(
                                ft.Text(
                                    f"Variation {i + 1}",
                                    size=FONT_SM,
                                    color=TEXT,
                                    weight=ft.FontWeight.W_600,
                                )
                            )
                        self.sfx_results_host.controls.append(bar.control)
                    self.page.update()
                else:
                    fail_msgs.append(r.status or f"Variation {i + 1} failed.")

            elapsed = _time.perf_counter() - t0
            if ok_paths:
                if n > 1:
                    summary = f"OK · {len(ok_paths)}/{n} variation(s) · {elapsed:.1f}s"
                else:
                    summary = f"OK · {elapsed:.1f}s"
                if fail_msgs:
                    summary += f" · {len(fail_msgs)} failed"
                self.sfx_cost.value = self._sfx_cost()
                if total_cost_notes:
                    self.sfx_cost.value = f"{self._sfx_cost()} · last: {total_cost_notes[-1]}"
                self.sfx_progress.finish_ok(summary, self.page)
                self.sfx_status.value = (
                    summary + ("\n" + "; ".join(fail_msgs[:3]) if fail_msgs else "")
                )
            else:
                err = "; ".join(fail_msgs) if fail_msgs else "SFX generate failed."
                self.sfx_progress.finish_error(err, self.page)
                self.sfx_status.value = err
        except Exception as exc:
            self.sfx_progress.finish_error(f"Error: {exc}", self.page)
            self.sfx_status.value = f"Error: {exc}"
            traceback.print_exc()
        finally:
            self.state.clear_busy("audio")
            self.apply_key_gates()
            self.page.update()

    def _vs_kwargs(self) -> dict:
        excludes = [
            chip for chip, cb in self.vs_exclude_checks.items() if bool(cb.value)
        ]
        return {
            "style": _dd_value(self.vs_style),
            "pace": _dd_value(self.vs_pace),
            "emphasis": _dd_value(self.vs_emphasis),
            "excludes": excludes,
            "note": self.vs_note.value or "",
        }

    def _vs_cost_text(self) -> str:
        labels = video_sfx_labels()
        if not labels:
            return "Est. cost: —"
        spec = find_audio(_dd_value(self.vs_model) if hasattr(self, "vs_model") else labels[0], VIDEO_SFX_MODELS)
        if not spec:
            spec = find_audio(labels[0], VIDEO_SFX_MODELS)
        if not spec:
            return "Est. cost: —"
        dur = getattr(self, "vs_duration_s", None) or 15.0
        base = format_audio_cost(spec, duration_s=float(dur))
        kind = (spec.extra_defaults or {}).get("_output_kind")
        if kind == "muxed":
            base = f"{base} · muxed video"
        elif kind == "audio":
            base = f"{base} · audio track"
        # Surface Prefer output choice in notes line
        try:
            pref = _dd_value(self.vs_output_bias) or ""
            if "muxed" in pref.lower() and kind == "audio":
                base = f"{base} · (model is audio-track; muxed not available)"
            elif "audio" in pref.lower() and kind == "muxed":
                base = f"{base} · (model is muxed video)"
        except Exception:
            pass
        if getattr(self, "vs_duration_s", None):
            return f"{base} · ~{float(self.vs_duration_s):.1f}s source"
        return f"{base} · (upload video for length-based estimate)"

    def _vs_refresh_model_notes(self) -> None:
        spec = find_audio(
            _dd_value(self.vs_model) if hasattr(self, "vs_model") else None,
            VIDEO_SFX_MODELS,
        )
        if not spec:
            labels = video_sfx_labels()
            spec = find_audio(labels[0], VIDEO_SFX_MODELS) if labels else None
        if hasattr(self, "vs_model_notes"):
            notes = (spec.notes if spec else "") or ""
            kind = (spec.extra_defaults or {}).get("_output_kind") if spec else None
            if kind == "muxed":
                notes = f"{notes} · Output: muxed video".strip(" ·")
            elif kind == "audio":
                notes = f"{notes} · Output: audio track".strip(" ·")
            self.vs_model_notes.value = notes
        self._vs_update_char_hint()

    def _vs_max_prompt_chars(self) -> int | None:
        spec = find_audio(_dd_value(self.vs_model), VIDEO_SFX_MODELS)
        if not spec:
            return None
        n = spec.max_prompt_chars
        return int(n) if n is not None and int(n) > 0 else None

    def _vs_update_char_hint(self) -> None:
        """Show n/max for Kling-style limits; warn before silent API truncate."""
        if not hasattr(self, "vs_char_hint"):
            return
        text = (self.vs_prompt.value or "") if hasattr(self, "vs_prompt") else ""
        n = len(text)
        max_c = self._vs_max_prompt_chars()
        if max_c is None:
            self.vs_char_hint.value = f"{n} chars · no hard limit for this model"
            self.vs_char_hint.color = TEXT_MUTED
            return
        self.vs_char_hint.value = f"{n}/{max_c} characters"
        if n > max_c:
            self.vs_char_hint.value = (
                f"{n}/{max_c} characters — over limit. "
                f"Generate will truncate to {max_c} with a status note (not silent)."
            )
            self.vs_char_hint.color = "#e57373"
        elif n >= int(max_c * 0.9):
            self.vs_char_hint.value = (
                f"{n}/{max_c} characters — approaching model limit "
                f"(e.g. Kling ~{max_c}). Shorten for best results."
            )
            self.vs_char_hint.color = "#ffb74d"
        else:
            self.vs_char_hint.color = TEXT_MUTED

    async def _vs_prompt_changed(self, e: ft.ControlEvent) -> None:
        self._vs_update_char_hint()
        try:
            self.page.update()
        except Exception:
            pass

    async def _vs_cost_refresh(self, e: ft.ControlEvent) -> None:
        self._vs_refresh_model_notes()
        self.vs_cost.value = self._vs_cost_text()
        self._vs_update_char_hint()
        try:
            self.page.update()
        except Exception:
            pass

    async def _vs_rebuild(self, e: ft.ControlEvent) -> None:
        # Keep free-edit path: only auto-rebuild if user hasn't heavily customized
        self.vs_prompt.value = build_video_sfx_prompt(**self._vs_kwargs())
        self.vs_cost.value = self._vs_cost_text()
        self._vs_update_char_hint()
        self.page.update()

    def receive_video_for_sfx(self, path: str, *, status: str | None = None) -> bool:
        """
        Load a video clip into Video→SFX (Send-to from Library / Tools / Vision / Video).

        Switches the Audio pill to SFX so the Video→SFX section is visible.
        """
        try:
            p = Path(path)
            if not p.is_file():
                self.vs_status.value = f"Video missing: {path}"
                return False
            resolved = str(p.resolve())
        except OSError as exc:
            self.vs_status.value = f"Video error: {exc}"
            return False

        # Show dedicated Video → SFX pill
        try:
            self._selected_audio = "video_sfx"
            self.state.audio_selected_id = "video_sfx"
            self._pill_nav.set_selected("video_sfx", notify=False)
            self._apply_audio_visibility()
        except Exception:
            pass

        self.vs_video_path = resolved
        name = Path(resolved).name
        self.vs_duration_s = None
        try:
            from media_studio.pricing import probe_video_duration

            self.vs_duration_s = probe_video_duration(resolved)
        except Exception:
            self.vs_duration_s = None
        if self.vs_duration_s:
            try:
                mb = Path(resolved).stat().st_size / (1024 * 1024)
                self.vs_label.value = f"{name} · {self.vs_duration_s:.1f}s · {mb:.0f} MB"
            except OSError:
                self.vs_label.value = f"{name} · {self.vs_duration_s:.1f}s"
        else:
            self.vs_label.value = name
        self.vs_cost.value = self._vs_cost_text()
        self.vs_status.value = status or f"Loaded for Video→SFX: {name}"
        self.vs_status.color = TEXT_MUTED
        # Source history (video) when strip is available
        try:
            from media_studio.source_history import record_source

            record_source(resolved, self.state.output_dir, media_kind="video")
        except Exception:
            pass
        try:
            self.page.update()
        except Exception:
            pass
        return True

    async def _pick_vs_video(self, e: ft.ControlEvent) -> None:
        try:
            files = await pick_video(self.page, dialog_title="Video for SFX")
        except Exception as exc:
            self.vs_status.value = f"Picker error: {exc}"
            self.page.update()
            return
        if not files or not files[0].path:
            return
        self.receive_video_for_sfx(files[0].path)
        self.page.update()

    async def _run_video_sfx(self, e: ft.ControlEvent) -> None:
        if self.state.is_busy("audio"):
            return
        if not self._require_fal(self.vs_status):
            return
        if not self.vs_video_path:
            self.vs_status.value = "Upload a video first."
            self.page.update()
            return
        if not self.state.try_busy("audio"):
            return
        self.vs_btn.disabled = True
        self.vs_player.clear()
        self.vs_progress.start("Uploading…", self.page)
        model_name = _dd_value(self.vs_model) or "Video-to-SFX"
        self.vs_status.value = f"Generating with {model_name}…"
        self.vs_cost.value = self._vs_cost_text()
        self.page.update()

        def on_progress(msg: str) -> None:
            self.vs_progress.set_message(classify_progress(msg), self.page)

        # Prefer the compiled/edited prompt field
        prompt = (self.vs_prompt.value or "").strip() or build_video_sfx_prompt(
            **self._vs_kwargs()
        )
        max_c = self._vs_max_prompt_chars()
        if max_c is not None and len(prompt) > max_c:
            self.vs_status.value = (
                f"Prompt is {len(prompt)} chars; {max_c} is the model max "
                f"(e.g. Kling). Continuing with truncation — shorten for full fidelity."
            )
            try:
                self.page.update()
            except Exception:
                pass
        try:
            from media_studio.job_context import to_thread_with_job

            r = await to_thread_with_job(
                self.state,
                run_video_sfx,
                video_path=self.vs_video_path,
                model_label=_dd_value(self.vs_model),
                prompt=prompt,
                output_dir=self.state.output_dir,
                on_progress=on_progress,
                duration_s=self.vs_duration_s,
            )
            self.vs_cost.value = r.cost_label or self._vs_cost_text()
            if r.ok and r.path:
                done = r.status or "OK"
                self.vs_progress.finish_ok(done, self.page)
                self.vs_status.value = done
                # Note when result is muxed video (MMAudio) vs pure audio
                ext = Path(r.path).suffix.lower()
                note = None
                if ext in {".mp4", ".mov", ".webm", ".mkv"}:
                    note = (
                        f"Saved video+audio: {r.path} — "
                        "in-app Play may not work on video; use Open externally / folder."
                    )
                self.vs_player.set_result(r.path, note=note)
            else:
                err = r.status or "Failed."
                self.vs_progress.finish_error(err, self.page)
                self.vs_status.value = err
        except Exception as exc:
            self.vs_progress.finish_error(f"Error: {exc}", self.page)
            self.vs_status.value = f"Error: {exc}"
            traceback.print_exc()
        finally:
            self.state.clear_busy("audio")
            self.apply_key_gates()
            self.page.update()

    # ----- Ambience -----

    def _build_ambience(self) -> None:
        d = clear_ambience_values()
        self.amb_location = styled_dropdown(
            label_text="Location / Setting",
            options=AMB_LOCATIONS,
            value=d["location"],
            on_select=self._ambience_location_change,
            expand=True,
        )
        self.amb_custom_loc = ft.TextField(
            label="Custom location",
            hint_text="Used when Location is Custom",
            value=d.get("custom_location") or "",
            dense=True,
            filled=True,
            fill_color=PANEL_ELEVATED,
            border_color=BORDER,
            color=TEXT,
            text_size=FONT_SM,
            visible=False,
            on_change=self._ambience_rebuild,
        )
        self.amb_time = styled_dropdown(
            label_text="Time of day",
            options=AMB_TIMES,
            value=d["time_of_day"],
            on_select=self._ambience_rebuild,
            expand=True,
        )
        self.amb_weather = styled_dropdown(
            label_text="Weather / air",
            options=AMB_WEATHER,
            value=d["weather"],
            on_select=self._ambience_rebuild,
            expand=True,
        )
        self.amb_density = styled_dropdown(
            label_text="Overall density",
            options=AMB_DENSITY,
            value=d["density"],
            on_select=self._ambience_rebuild,
            expand=True,
        )
        self.amb_duration = styled_dropdown(
            label_text="Duration",
            options=[f"{s}s" for s in AMB_DURATIONS],
            value=f"{int(d['duration_s'])}s",
            on_select=self._ambience_rebuild,
            expand=True,
        )

        # Layer dropdowns: Off / Light / Medium
        self.amb_layers: dict[str, ft.Dropdown] = {}
        layer_defaults = d.get("layers") or {}
        layer_rows: list[ft.Control] = []
        row_buf: list[ft.Control] = []
        for name in AMB_LAYERS:
            dd = styled_dropdown(
                label_text=name,
                options=AMB_LAYER_LEVELS,
                value=str(layer_defaults.get(name, "Off")),
                on_select=self._ambience_rebuild,
                expand=True,
            )
            self.amb_layers[name] = dd
            row_buf.append(dd)
            if len(row_buf) == 2:
                layer_rows.append(ft.Row(row_buf, spacing=8))
                row_buf = []
        if row_buf:
            layer_rows.append(ft.Row(row_buf, spacing=8))

        self.amb_notes_label = ft.Text(
            "Custom notes / extras",
            size=FONT_SM,
            color=TEXT,
            weight=ft.FontWeight.W_700,
        )
        self.amb_notes = ft.TextField(
            hint_text="Always kept when Location/layers change — appended to the prompt",
            value=d.get("custom_notes") or "",
            multiline=True,
            min_lines=2,
            max_lines=3,
            filled=True,
            fill_color=PANEL_ELEVATED,
            border_color=BORDER,
            focused_border_color=ACCENT,
            color=TEXT,
            text_size=FONT_SM,
            on_change=self._ambience_rebuild,
        )
        self.amb_prompt_label = ft.Text(
            "Ambience prompt (auto-built — editable)",
            size=FONT_SM,
            color=TEXT,
            weight=ft.FontWeight.W_700,
        )
        self.amb_prompt = ft.TextField(
            value=build_ambience_prompt(
                location=d["location"],
                custom_location=d.get("custom_location") or "",
                time_of_day=d["time_of_day"],
                weather=d["weather"],
                layers=d["layers"],
                density=d["density"],
                duration_s=d["duration_s"],
                custom_notes=d.get("custom_notes") or "",
            ),
            hint_text="Must stay pure ambience (no music). Notes append at the end.",
            multiline=True,
            min_lines=4,
            max_lines=8,
            filled=True,
            fill_color=PANEL_ELEVATED,
            border_color=BORDER,
            focused_border_color=ACCENT,
            color=TEXT,
            text_size=FONT_SM,
            on_change=self._ambience_cost_refresh,
        )
        self.amb_prompt_favs = make_prompt_favorites_bar(
            self.page,
            get_text=lambda: self.amb_prompt.value,
            set_text=lambda t: setattr(self.amb_prompt, "value", t),
            surface="audio",
            get_meta=lambda: {"source": "user"},
            on_status=lambda m: setattr(self.amb_status, "value", m),
            show_pack_buttons=False,
        )
        labels = ambience_labels()
        self.amb_model = styled_dropdown(
            label_text="Model",
            options=labels,
            value=labels[0] if labels else None,
            on_select=self._ambience_cost_refresh,
            expand=True,
        )
        self.amb_cost = ft.Text(self._ambience_cost(), size=FONT_SM, color=TEXT, weight=ft.FontWeight.W_600)
        self.amb_status = ft.Text("", size=FONT_SM, color=TEXT_MUTED, max_lines=3)
        self.amb_progress = JobProgress()
        self.amb_player = AudioResultBar(self.page)
        self.amb_btn = ft.FilledButton(
            content="Generate ambience",
            on_click=self._run_ambience,
            style=ft.ButtonStyle(bgcolor=ACCENT_BRIGHT, color=TEXT),
        )
        self.amb_enhance = make_enhance_button(on_click=self._enhance_ambience)

        self.ambience_card = ft.Container(
            bgcolor=PANEL,
            border=ft.Border.all(1, BORDER),
            border_radius=8,
            padding=12,
            content=ft.Column(
                [
                    section_title("3. Ambience"),
                    ft.Text(
                        "Environmental beds only (no music/melody) for listing / lifestyle video. "
                        "Default model: Stable Audio 2.5.",
                        size=FONT_SM,
                        color=TEXT_MUTED,
                    ),
                    ft.Row([self.amb_location], spacing=0),
                    self.amb_custom_loc,
                    ft.Row([self.amb_time, self.amb_weather, self.amb_density, self.amb_duration], spacing=8),
                    label("Layers (Off / Light / Medium)", muted=True),
                    *layer_rows,
                    self.amb_notes_label,
                    self.amb_notes,
                    self.amb_prompt_label,
                    self.amb_prompt,
                    self.amb_prompt_favs.root,
                    ft.Row([self.amb_model], spacing=8),
                    _cost_box(self.amb_cost),
                    ft.Row([self.amb_enhance, self.amb_btn], spacing=8),
                    self.amb_progress.control,
                    self.amb_status,
                    self.amb_player.control,
                ],
                spacing=8,
                tight=True,
            ),
        )

    def _ambience_layer_map(self) -> dict[str, str]:
        return {name: (_dd_value(dd) or "Off") for name, dd in self.amb_layers.items()}

    def _ambience_duration_s(self) -> float:
        raw = (_dd_value(self.amb_duration) or "30s").strip().lower().replace("s", "")
        try:
            return float(raw)
        except ValueError:
            return 30.0

    def _ambience_prompt_kwargs(self) -> dict:
        return {
            "location": _dd_value(self.amb_location),
            "custom_location": self.amb_custom_loc.value or "",
            "time_of_day": _dd_value(self.amb_time),
            "weather": _dd_value(self.amb_weather),
            "layers": self._ambience_layer_map(),
            "density": _dd_value(self.amb_density),
            "duration_s": self._ambience_duration_s(),
            "custom_notes": self.amb_notes.value or "",
        }

    def _ambience_cost(self) -> str:
        spec = find_audio(_dd_value(self.amb_model), AMBIENCE_MODELS)
        if not spec:
            return "Est. cost: —"
        dur = self._ambience_duration_s()
        if spec.supports_duration:
            dur = max(spec.duration_min_s, min(spec.duration_max_s, dur))
        base = format_audio_cost(spec, duration_s=dur)
        # Surface prompt-length constraint in the cost area when relevant
        limit = getattr(spec, "max_prompt_chars", None)
        prompt_len = len((self.amb_prompt.value or "").strip())
        if limit and prompt_len > limit:
            return f"{base} · Prompt {prompt_len}/{limit} chars (will auto-shorten)"
        if limit:
            return f"{base} · Prompt {prompt_len}/{limit} chars"
        return f"{base} · Prompt {prompt_len} chars"

    def _apply_ambience_prompt_rebuild(self) -> None:
        """Rebuild prompt from structured fields; does not clear amb_notes."""
        self.amb_prompt.value = build_ambience_prompt(**self._ambience_prompt_kwargs())
        self.amb_cost.value = self._ambience_cost()

    async def _ambience_location_change(self, e: ft.ControlEvent) -> None:
        loc = _dd_value(self.amb_location) or ""
        self.amb_custom_loc.visible = loc.startswith("Custom")
        self._apply_ambience_prompt_rebuild()
        self.page.update()

    async def _ambience_rebuild(self, e: ft.ControlEvent) -> None:
        self._apply_ambience_prompt_rebuild()
        self.page.update()

    async def _ambience_cost_refresh(self, e: ft.ControlEvent) -> None:
        self.amb_cost.value = self._ambience_cost()
        self.page.update()

    async def _run_ambience(self, e: ft.ControlEvent) -> None:
        if self.state.is_busy("audio"):
            return
        if not self._require_fal(self.amb_status):
            return
        if not self.state.try_busy("audio"):
            return
        self.amb_btn.disabled = True
        self.amb_player.clear()
        self.amb_progress.start("Queued…", self.page)
        self.amb_status.value = "Generating pure environmental ambience…"
        self.amb_cost.value = self._ambience_cost()
        self.page.update()

        def on_progress(msg: str) -> None:
            self.amb_progress.set_message(classify_progress(msg), self.page)

        try:
            from media_studio.job_context import to_thread_with_job

            r = await to_thread_with_job(
                self.state,
                run_ambience,
                prompt=self.amb_prompt.value,
                model_label=_dd_value(self.amb_model),
                duration_s=self._ambience_duration_s(),
                output_dir=self.state.output_dir,
                on_progress=on_progress,
                builder_kwargs=self._ambience_prompt_kwargs(),
            )
            self.amb_cost.value = r.cost_label or self._ambience_cost()
            if r.ok and r.path:
                done = r.status or "OK"
                self.amb_progress.finish_ok(done, self.page)
                self.amb_status.value = done
                self.amb_player.set_result(r.path)
            else:
                err = r.status or "Failed."
                # Keep cost visible on rejection
                if r.cost_label and "Est. cost" not in err:
                    err = f"{err}  ({r.cost_label})"
                self.amb_progress.finish_error(err, self.page)
                self.amb_status.value = err
        except Exception as exc:
            msg = f"Error: {exc}"
            low = str(exc).lower()
            if any(k in low for k in ("character", "too long", "prompt", "450", "validation")):
                msg = (
                    f"Model rejected the prompt (often length/validation). "
                    f"{self._ambience_cost()}. Details: {exc}"
                )
            self.amb_progress.finish_error(msg, self.page)
            self.amb_status.value = msg
            traceback.print_exc()
        finally:
            self.state.clear_busy("audio")
            self.apply_key_gates()
            self.page.update()

    # ----- Voiceover -----

    def _build_voiceover(self) -> None:
        labels = voiceover_labels()
        default_spec = find_audio(labels[0], VOICEOVER_MODELS) if labels else None
        default_voices = default_voices_for_model(default_spec)
        default_voice_name = (
            default_spec.default_voice if default_spec else (default_voices[0] if default_voices else "Rachel")
        )
        self.vo_model = styled_dropdown(
            label_text="Model",
            options=labels,
            value=labels[0] if labels else None,
            on_select=self._vo_model_change,
            expand=True,
        )
        self.vo_voice = styled_dropdown(
            label_text="Voice",
            options=voice_choice_labels(default_voices=default_voices),
            value=f"Default · {default_voice_name}",
            expand=True,
            on_select=self._vo_cost_refresh,
        )
        self.vo_script = ft.TextField(
            label="Script (spoken)",
            hint_text="Only the words that should be spoken…",
            multiline=True,
            min_lines=4,
            max_lines=7,
            filled=True,
            fill_color=PANEL_ELEVATED,
            border_color=BORDER,
            color=TEXT,
            text_size=FONT_SM,
            on_change=self._vo_cost_refresh,
        )
        self.vo_script_favs = make_prompt_favorites_bar(
            self.page,
            get_text=lambda: self.vo_script.value,
            set_text=lambda t: setattr(self.vo_script, "value", t),
            surface="audio",
            get_meta=lambda: {"source": "user"},
            on_status=lambda m: setattr(self.vo_status, "value", m),
            show_pack_buttons=False,
        )
        self.vo_delivery = ft.TextField(
            label="Delivery / Style notes (optional, not spoken)",
            hint_text=(
                "e.g. Speak slowly and warmly, with quiet authority, "
                "as a nature documentary narrator"
            ),
            multiline=True,
            min_lines=2,
            max_lines=3,
            filled=True,
            fill_color=PANEL_ELEVATED,
            border_color=BORDER,
            color=TEXT,
            text_size=FONT_SM,
        )
        self.vo_tone = styled_dropdown(
            label_text="Tone / Emotion",
            options=VOICEOVER_TONES,
            value="Neutral",
            expand=True,
        )
        self.vo_speed = ft.Slider(
            min=0.8,
            max=1.2,
            divisions=8,
            value=1.0,
            label="{value}×",
            active_color=ACCENT,
            on_change=self._vo_speed_label,
        )
        self.vo_speed_label = ft.Text(
            "Speed 1.0×",
            size=FONT_SM,
            color=TEXT_MUTED,
            width=88,
        )
        self.vo_cost = ft.Text(self._vo_cost(), size=FONT_SM, color=TEXT, weight=ft.FontWeight.W_600)
        self.vo_status = ft.Text("", size=FONT_SM, color=TEXT_MUTED, max_lines=3)
        self.vo_progress = JobProgress()
        self.vo_player = AudioResultBar(self.page)
        self.vo_btn = ft.FilledButton(
            content="Generate voiceover",
            on_click=self._run_voiceover,
            style=ft.ButtonStyle(bgcolor=ACCENT_BRIGHT, color=TEXT),
        )
        self.vo_enhance = make_enhance_button(
            on_click=self._enhance_voiceover,
            tooltip="Rewrite script for the selected voice model (does not change model)",
        )
        self.voice_card = ft.Container(
            bgcolor=PANEL,
            border=ft.Border.all(1, BORDER),
            border_radius=8,
            padding=12,
            content=ft.Column(
                [
                    section_title("4. Voiceover"),
                    ft.Text(
                        "Script is spoken aloud. Delivery notes set style only "
                        "(never read). Pick Default · or My · voices.",
                        size=FONT_SM,
                        color=TEXT_MUTED,
                    ),
                    self.vo_script,
                    self.vo_script_favs.root,
                    self.vo_delivery,
                    ft.Row([self.vo_model, self.vo_voice], spacing=8),
                    ft.Row(
                        [
                            self.vo_tone,
                            ft.Column(
                                [
                                    label("Speed", muted=True),
                                    ft.Row(
                                        [self.vo_speed, self.vo_speed_label],
                                        spacing=8,
                                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                    ),
                                ],
                                spacing=2,
                                expand=True,
                            ),
                        ],
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.END,
                    ),
                    _cost_box(self.vo_cost),
                    ft.Row([self.vo_enhance, self.vo_btn], spacing=8),
                    self.vo_progress.control,
                    self.vo_status,
                    self.vo_player.control,
                ],
                spacing=8,
                tight=True,
            ),
        )

    def _vo_cost(self) -> str:
        from media_studio.my_voices import is_my_voice_label

        voice = _dd_value(self.vo_voice)
        if is_my_voice_label(voice):
            spec = find_audio("minimax speech 02 hd", VOICEOVER_MODELS)
        else:
            spec = find_audio(_dd_value(self.vo_model), VOICEOVER_MODELS)
        if not spec:
            return "Est. cost: —"
        return format_audio_cost(spec, text=self.vo_script.value or "")

    def refresh_voices(self) -> None:
        """Reload voice dropdown after clone create/delete."""
        spec = find_audio(_dd_value(self.vo_model), VOICEOVER_MODELS)
        defaults = default_voices_for_model(spec) if spec else ELEVENLABS_VOICES
        choices = voice_choice_labels(default_voices=defaults)
        self.vo_voice.options = [ft.DropdownOption(key=x, text=x) for x in choices]
        if _dd_value(self.vo_voice) not in choices:
            self.vo_voice.value = choices[0] if choices else None

    async def _vo_model_change(self, e: ft.ControlEvent) -> None:
        self.refresh_voices()
        self.vo_cost.value = self._vo_cost()
        self.page.update()

    async def _vo_cost_refresh(self, e: ft.ControlEvent) -> None:
        self.vo_cost.value = self._vo_cost()
        self.page.update()

    async def _vo_speed_label(self, e: ft.ControlEvent) -> None:
        val = float(self.vo_speed.value or 1.0)
        self.vo_speed_label.value = f"Speed {val:.1f}×"
        self.page.update()

    async def _run_voiceover(self, e: ft.ControlEvent) -> None:
        if self.state.is_busy("audio"):
            return
        if not self._require_fal(self.vo_status):
            return
        if not self.state.try_busy("audio"):
            return
        self.vo_btn.disabled = True
        self.vo_player.clear()
        self.vo_progress.start("Queued…", self.page)
        self.vo_status.value = "Generating voiceover…"
        self.page.update()

        def on_progress(msg: str) -> None:
            self.vo_progress.set_message(classify_progress(msg), self.page)

        try:
            from media_studio.job_context import to_thread_with_job

            r = await to_thread_with_job(
                self.state,
                run_voiceover,
                text=self.vo_script.value,
                model_label=_dd_value(self.vo_model),
                voice=_dd_value(self.vo_voice),
                tone=_dd_value(self.vo_tone) or "Neutral",
                speed=float(self.vo_speed.value or 1.0),
                delivery_notes=self.vo_delivery.value,
                output_dir=self.state.output_dir,
                on_progress=on_progress,
            )
            self.vo_cost.value = r.cost_label or self._vo_cost()
            if r.ok and r.path:
                done = r.status or "OK"
                self.vo_progress.finish_ok(done, self.page)
                self.vo_status.value = done
                self.vo_player.set_result(r.path)
            else:
                err = r.status or "Failed."
                self.vo_progress.finish_error(err, self.page)
                self.vo_status.value = err
        except Exception as exc:
            self.vo_progress.finish_error(f"Error: {exc}", self.page)
            self.vo_status.value = f"Error: {exc}"
            traceback.print_exc()
        finally:
            self.state.clear_busy("audio")
            self.apply_key_gates()
            self.page.update()

    # ----- Voice clone -----

    def _build_clone(self) -> None:
        self.cl_sample_path: str | None = None
        self.cl_sample_label = ft.Text("No sample", size=FONT_SM, color=TEXT_MUTED)
        self.cl_name = ft.TextField(
            label="Voice name",
            dense=True,
            filled=True,
            fill_color=PANEL_ELEVATED,
            border_color=BORDER,
            color=TEXT,
            text_size=FONT_SM,
            hint_text="e.g. Realtor Jane",
        )
        self.cl_preview_text = ft.TextField(
            label="Preview text (optional)",
            value="Hello, this is a preview of your cloned voice for listing videos.",
            multiline=True,
            min_lines=2,
            max_lines=3,
            filled=True,
            fill_color=PANEL_ELEVATED,
            border_color=BORDER,
            color=TEXT,
            text_size=FONT_SM,
        )
        self.cl_noise = ft.Checkbox(label="Noise reduction", value=True)
        self.cl_model = styled_dropdown(
            label_text="Clone model",
            options=voice_clone_labels(),
            value=voice_clone_labels()[0] if voice_clone_labels() else None,
            expand=True,
        )
        cl_spec = find_audio(voice_clone_labels()[0], VOICE_CLONE_MODELS) if voice_clone_labels() else None
        self.cl_cost = ft.Text(
            format_audio_cost(cl_spec) if cl_spec else "Est. cost: $1.50",
            size=FONT_SM,
            color=TEXT,
            weight=ft.FontWeight.W_600,
        )
        self.cl_status = ft.Text("", size=FONT_SM, color=TEXT_MUTED, max_lines=4)
        self.cl_progress = JobProgress()
        self.cl_player = AudioResultBar(self.page)
        self.cl_list = ft.Text(self._voices_md(), size=FONT_SM, color=TEXT_MUTED)
        self.cl_delete_dd = styled_dropdown(
            label_text="Delete a saved voice",
            options=my_voice_names() or ["(none)"],
            value=None,
            expand=True,
        )
        self.cl_btn = ft.FilledButton(
            content="Create & save voice",
            on_click=self._run_clone,
            style=ft.ButtonStyle(bgcolor=ACCENT_BRIGHT, color=TEXT),
        )
        self.cl_enhance = make_enhance_button(
            on_click=self._enhance_clone,
            tooltip="Rewrite preview text for the selected clone model (does not change model)",
        )
        self.cl_upload = ft.OutlinedButton(
            content="Upload sample (≥10s)",
            icon=ft.Icons.MIC,
            on_click=self._pick_clone_sample,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
        )
        self.cl_del_btn = ft.OutlinedButton(
            content="Delete selected",
            on_click=self._delete_voice,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
        )

        self.clone_card = ft.Container(
            bgcolor=PANEL,
            border=ft.Border.all(1, BORDER),
            border_radius=8,
            padding=12,
            content=ft.Column(
                [
                    section_title("5. Voice Clone / Character Voices"),
                    ft.Text(
                        "Upload clean speech ≥10s → MiniMax clone → My Voices (for Voiceover).",
                        size=FONT_SM,
                        color=TEXT_MUTED,
                    ),
                    self.cl_list,
                    ft.Row([self.cl_upload, self.cl_sample_label], spacing=8),
                    self.cl_name,
                    self.cl_preview_text,
                    self.cl_noise,
                    ft.Row([self.cl_model], spacing=0),
                    _cost_box(self.cl_cost),
                    ft.Row([self.cl_enhance, self.cl_btn], spacing=8),
                    self.cl_progress.control,
                    self.cl_status,
                    self.cl_player.control,
                    ft.Row([self.cl_delete_dd, self.cl_del_btn], spacing=8),
                ],
                spacing=8,
                tight=True,
            ),
        )

    def _voices_md(self) -> str:
        voices = load_voices()
        if not voices:
            return "My Voices: (none yet)"
        lines = ["My Voices:"]
        for v in voices:
            lines.append(f"  • {v.name}  ({v.custom_voice_id[:14]}…)")
        return "\n".join(lines)

    async def _pick_clone_sample(self, e: ft.ControlEvent) -> None:
        try:
            files = await pick_audio(self.page, dialog_title="Voice sample (≥10s)")
        except Exception as exc:
            self.cl_status.value = f"Picker error: {exc}"
            self.page.update()
            return
        if not files or not files[0].path:
            return
        self.cl_sample_path = str(Path(files[0].path).resolve())
        self.cl_sample_label.value = Path(self.cl_sample_path).name
        self.page.update()

    async def _run_clone(self, e: ft.ControlEvent) -> None:
        if self.state.is_busy("audio"):
            return
        if not self._require_fal(self.cl_status):
            return
        if not self.state.try_busy("audio"):
            return
        self.cl_btn.disabled = True
        self.cl_player.clear()
        self.cl_progress.start("Uploading sample…", self.page)
        self.cl_status.value = "Cloning voice…"
        self.page.update()

        def on_progress(msg: str) -> None:
            self.cl_progress.set_message(classify_progress(msg), self.page)

        try:
            from media_studio.job_context import to_thread_with_job

            r = await to_thread_with_job(
                self.state,
                run_voice_clone,
                audio_path=self.cl_sample_path,
                voice_name=self.cl_name.value,
                preview_text=self.cl_preview_text.value,
                noise_reduction=bool(self.cl_noise.value),
                model_label=_dd_value(self.cl_model),
                output_dir=self.state.output_dir,
                on_progress=on_progress,
            )
            self.cl_cost.value = r.cost_label or self.cl_cost.value
            if r.ok:
                done = r.status or "Voice saved to My Voices."
                self.cl_progress.finish_ok(done, self.page)
                self.cl_status.value = done
                if r.path:
                    self.cl_player.set_result(r.path, note=f"Preview: {r.path}")
            else:
                err = r.status or "Clone failed."
                self.cl_progress.finish_error(err, self.page)
                self.cl_status.value = err
            self.cl_list.value = self._voices_md()
            names = my_voice_names() or ["(none)"]
            self.cl_delete_dd.options = [ft.DropdownOption(key=x, text=x) for x in names]
            self.refresh_voices_on_vo()
        except Exception as exc:
            self.cl_progress.finish_error(f"Error: {exc}", self.page)
            self.cl_status.value = f"Error: {exc}"
            traceback.print_exc()
        finally:
            self.state.clear_busy("audio")
            self.apply_key_gates()
            self.page.update()

    def refresh_voices_on_vo(self) -> None:
        try:
            self.refresh_voices()
        except Exception:
            pass

    async def _delete_voice(self, e: ft.ControlEvent) -> None:
        sel = _dd_value(self.cl_delete_dd)
        if not sel or sel == "(none)":
            self.cl_status.value = "Select a My Voice to delete."
            self.page.update()
            return
        ok = delete_voice(sel)
        self.cl_status.value = f"Deleted {sel}." if ok else f"Could not delete {sel}."
        self.cl_list.value = self._voices_md()
        names = my_voice_names() or ["(none)"]
        self.cl_delete_dd.options = [ft.DropdownOption(key=x, text=x) for x in names]
        self.cl_delete_dd.value = None
        self.refresh_voices()
        self.page.update()
