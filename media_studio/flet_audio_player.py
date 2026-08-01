"""
In-app audio result player via pygame.mixer (no OS media window).

Play/Stop run in-process. \"Open externally\" remains optional for the system player.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import flet as ft

from media_studio.folder_util import show_in_folder
from media_studio.flet_result_actions import make_result_action_row, show_result_actions
from media_studio.flet_theme import ACCENT, ACCENT_BRIGHT, BORDER, FONT_SM, PANEL_ELEVATED, TEXT, TEXT_MUTED

# ---------------------------------------------------------------------------
# pygame.mixer backend (lazy init, thread-safe)
# ---------------------------------------------------------------------------

_mixer_lock = threading.Lock()
_mixer_ready = False
_mixer_error: str | None = None
_current_path: str | None = None
_playing = False


def _ensure_mixer() -> tuple[bool, str | None]:
    """Initialize pygame.mixer once. Returns (ok, error_message)."""
    global _mixer_ready, _mixer_error
    with _mixer_lock:
        if _mixer_ready:
            return True, None
        if _mixer_error is not None and not _mixer_ready:
            # Allow one retry after failed import only if still not ready
            pass
        try:
            # pygame-ce installs as `pygame` (use on Python 3.12+ when classic
            # pygame has no wheels). SDL audio only — no game window.
            os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
            import pygame

            if not pygame.get_init():
                pygame.init()
            if not pygame.mixer.get_init():
                # Stereo 44.1 kHz — typical for fal MP3/WAV outputs
                pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=2048)
            _mixer_ready = True
            _mixer_error = None
            return True, None
        except Exception as exc:
            _mixer_ready = False
            _mixer_error = (
                f"{exc}. Install with: pip install pygame-ce"
            )
            return False, _mixer_error


def mixer_stop() -> None:
    """Stop any current in-app playback and release the file handle."""
    global _playing, _current_path
    with _mixer_lock:
        if not _mixer_ready:
            return
        try:
            import pygame

            if pygame.mixer.get_init():
                pygame.mixer.music.stop()
                # unload() releases the file on Windows (WinError 32 otherwise)
                unload = getattr(pygame.mixer.music, "unload", None)
                if callable(unload):
                    try:
                        unload()
                    except Exception:
                        pass
        except Exception:
            pass
        _playing = False
        _current_path = None


def mixer_play(path: str, *, volume: float = 1.0) -> str:
    """
    Load and play a local audio file in-process.

    Stops any previous track first. Returns a short status string.
    """
    global _current_path, _playing
    ok, err = _ensure_mixer()
    if not ok:
        return f"Playback unavailable: {err or 'pygame.mixer failed to init'}. pip install pygame"

    p = Path(path).expanduser()
    try:
        p = p.resolve()
    except OSError:
        pass
    if not p.is_file():
        return f"File not found: {p}"

    with _mixer_lock:
        try:
            import pygame

            # Stop previous clip so only one plays
            if pygame.mixer.get_init():
                pygame.mixer.music.stop()
            pygame.mixer.music.load(str(p))
            vol = max(0.0, min(1.0, float(volume)))
            pygame.mixer.music.set_volume(vol)
            pygame.mixer.music.play()
            _current_path = str(p)
            _playing = True
            return f"Playing: {p.name}"
        except Exception as exc:
            _playing = False
            return f"Play failed: {exc}"


def mixer_pause() -> str:
    with _mixer_lock:
        if not _mixer_ready:
            return "Not playing."
        try:
            import pygame

            if not pygame.mixer.get_init():
                return "Not playing."
            if pygame.mixer.music.get_busy():
                pygame.mixer.music.pause()
                global _playing
                _playing = False
                return "Paused."
            return "Not playing."
        except Exception as exc:
            return f"Pause failed: {exc}"


def mixer_unpause() -> str:
    with _mixer_lock:
        if not _mixer_ready:
            return "Not playing."
        try:
            import pygame

            pygame.mixer.music.unpause()
            global _playing
            _playing = True
            return "Playing."
        except Exception as exc:
            return f"Resume failed: {exc}"


def mixer_is_busy() -> bool:
    with _mixer_lock:
        if not _mixer_ready:
            return False
        try:
            import pygame

            return bool(pygame.mixer.get_init() and pygame.mixer.music.get_busy())
        except Exception:
            return False


def mixer_set_volume(volume: float) -> None:
    with _mixer_lock:
        if not _mixer_ready:
            return
        try:
            import pygame

            if pygame.mixer.get_init():
                pygame.mixer.music.set_volume(max(0.0, min(1.0, float(volume))))
        except Exception:
            pass


def open_with_system_player(path: str | Path) -> str:
    """Optional: open in OS default app (external window)."""
    if not path or not str(path).strip():
        return "Open externally: path is empty."
    target = Path(path).expanduser()
    try:
        target = target.resolve()
    except OSError:
        pass
    if not target.is_file():
        return f"Open externally: not found — {target}"
    p = str(target)
    try:
        if sys.platform.startswith("win"):
            os.startfile(p)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", p], check=False)
        else:
            subprocess.run(["xdg-open", p], check=False)
    except OSError as exc:
        return f"Open externally failed: {exc}"
    return f"Opened externally: {target.name}"


# Compat no-ops for older imports / smoke
def ensure_shared_audio(page: Any = None) -> None:
    return None


def get_shared_audio(page: Any = None) -> None:
    return None


# ---------------------------------------------------------------------------
# Result UI
# ---------------------------------------------------------------------------


class AudioResultBar:
    """
    Result panel after successful audio generate:

    - Play / Stop (pygame.mixer, in-process, no extra window)
    - Volume
    - Show in folder
    - Open externally (OS player — secondary)
    """

    def __init__(self, page: ft.Page) -> None:
        self.page = page
        self.path: str | None = None
        self._playing = False
        self._paused = False

        self.path_text = ft.Text(
            "",
            size=FONT_SM,
            color=TEXT_MUTED,
            selectable=True,
            expand=True,
            max_lines=3,
        )
        self.status_text = ft.Text(
            "",
            size=FONT_SM,
            color=TEXT_MUTED,
            visible=False,
            max_lines=2,
        )
        self.btn_play = ft.FilledButton(
            content="Play",
            icon=ft.Icons.PLAY_ARROW,
            on_click=self._on_play,
            visible=False,
            style=ft.ButtonStyle(bgcolor=ACCENT_BRIGHT, color=TEXT),
        )
        self.btn_stop = ft.OutlinedButton(
            content="Stop",
            icon=ft.Icons.STOP,
            on_click=self._on_stop,
            visible=False,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
        )
        self.volume = ft.Slider(
            min=0,
            max=1,
            value=0.9,
            divisions=20,
            active_color=ACCENT,
            inactive_color=BORDER,
            width=110,
            on_change=self._on_volume,
            visible=False,
            tooltip="Volume",
        )
        self.btn_external = ft.TextButton(
            content="Open externally",
            on_click=self._on_external,
            visible=False,
            style=ft.ButtonStyle(color=TEXT_MUTED),
        )
        # Standard result actions (Show in folder + Send to Resolve) — same as Tools/Video
        (
            self.result_actions_row,
            self.btn_folder,
            self.btn_resolve,
        ) = make_result_action_row(
            page,
            get_path=lambda: self.path,
            on_status=lambda msg, err: self._set_status(msg, error=err),
            extra_leading=[self.btn_external],
        )

        self.control = ft.Container(
            content=ft.Column(
                [
                    self.path_text,
                    self.status_text,
                    ft.Row(
                        [
                            self.btn_play,
                            self.btn_stop,
                            ft.Icon(ft.Icons.VOLUME_UP, size=16, color=TEXT_MUTED),
                            self.volume,
                        ],
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    self.result_actions_row,
                ],
                spacing=6,
            ),
            bgcolor=PANEL_ELEVATED,
            border=ft.Border.all(1, BORDER),
            border_radius=8,
            padding=10,
            visible=False,
        )

    def _safe_update(self) -> None:
        try:
            schedule = getattr(self.page, "schedule_update", None)
            if callable(schedule):
                schedule()
                return
            self.page.update()
        except Exception:
            pass

    def _set_status(self, msg: str, *, error: bool = False) -> None:
        self.status_text.value = msg
        self.status_text.visible = bool(msg)
        self.status_text.color = "#e57373" if error else TEXT_MUTED

    def _sync_play_button(self) -> None:
        if self._playing and not self._paused:
            self.btn_play.content = "Pause"
            self.btn_play.icon = ft.Icons.PAUSE
        elif self._paused:
            self.btn_play.content = "Resume"
            self.btn_play.icon = ft.Icons.PLAY_ARROW
        else:
            self.btn_play.content = "Play"
            self.btn_play.icon = ft.Icons.PLAY_ARROW

    def clear(self) -> None:
        # Stop if this path was the active track
        if self.path and _current_path and Path(self.path).resolve() == Path(_current_path).resolve():
            mixer_stop()
        self.path = None
        self._playing = False
        self._paused = False
        self.path_text.value = ""
        self._set_status("")
        self.btn_play.visible = False
        self.btn_stop.visible = False
        self.volume.visible = False
        self.btn_external.visible = False
        show_result_actions(self.btn_folder, self.btn_resolve, visible=False)
        self.control.visible = False
        self._sync_play_button()

    def set_result(
        self,
        path: str | None,
        *,
        note: str | None = None,
        stop_current: bool = True,
    ) -> None:
        if not path or not Path(path).is_file():
            self.clear()
            return
        # New file: stop whatever was playing (optional for multi-result batches)
        if stop_current:
            mixer_stop()
        self.path = str(Path(path).resolve())
        self._playing = False
        self._paused = False
        self.path_text.value = note or f"Saved: {self.path}"
        self._set_status("")
        self.btn_play.visible = True
        self.btn_stop.visible = True
        self.volume.visible = True
        self.btn_external.visible = True
        show_result_actions(self.btn_folder, self.btn_resolve, visible=True)
        self.control.visible = True
        self._sync_play_button()
        # Warm up mixer so first Play is snappy
        _ensure_mixer()

    async def _on_play(self, e: ft.ControlEvent) -> None:
        if not self.path:
            return
        # Pause / resume toggle when this track is active
        if self._playing and not self._paused and mixer_is_busy():
            msg = mixer_pause()
            self._paused = True
            self._playing = False
            self._sync_play_button()
            self._set_status(msg)
            self._safe_update()
            return
        if self._paused and self.path:
            msg = mixer_unpause()
            if msg.startswith("Playing"):
                self._paused = False
                self._playing = True
                self._sync_play_button()
                self._set_status(msg)
                self._safe_update()
                return
            # Fall through to full play if unpause failed

        vol = float(self.volume.value or 0.9)
        msg = mixer_play(self.path, volume=vol)
        err = msg.lower().startswith("play failed") or msg.lower().startswith("playback unavailable") or "not found" in msg.lower()
        if err:
            self._playing = False
            self._paused = False
            self._set_status(msg, error=True)
        else:
            self._playing = True
            self._paused = False
            self._set_status(msg)
        self._sync_play_button()
        self._safe_update()

    async def _on_stop(self, e: ft.ControlEvent) -> None:
        mixer_stop()
        self._playing = False
        self._paused = False
        self._sync_play_button()
        self._set_status("Stopped.")
        self._safe_update()

    async def _on_volume(self, e: ft.ControlEvent) -> None:
        mixer_set_volume(float(self.volume.value or 0))

    async def _on_external(self, e: ft.ControlEvent) -> None:
        msg = open_with_system_player(self.path)
        self._set_status(msg, error=msg.lower().startswith("open externally failed"))
        self._safe_update()
        try:
            from media_studio.flet_dialogs import show_snack

            show_snack(self.page, msg)
        except Exception:
            pass

    async def _show_folder(self, e: ft.ControlEvent) -> None:
        from media_studio.flet_dialogs import show_snack

        msg = show_in_folder(self.path)
        try:
            show_snack(self.page, msg)
        except Exception:
            self._set_status(msg)
            self._safe_update()
