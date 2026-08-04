"""
Frame Editor tab — Aleph 2.0 keyframe video edit.

Layout (rebuilt):
  Left  — fixed-width ListView of real controls (status → Generate).
  Right — large Preview + filmstrip.

No full-height grey rail, no empty expand panels. Runware only.
"""

from __future__ import annotations

import asyncio
import traceback
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import flet as ft

from media_studio.aleph_service import AlephKeyframe, run_aleph_keyframe_edit
from media_studio.flet_dialogs import open_url_in_browser
from media_studio.flet_enhance import make_enhance_button, run_prompt_enhance
from media_studio.flet_pickers import pick_image, pick_video
from media_studio.flet_progress import JobProgress, classify_progress
from media_studio.flet_result_actions import make_result_action_row, show_result_actions
from media_studio.flet_source_strip import PreviousSourcesStrip, ResolveSourcesStrip
from media_studio.flet_theme import (
    ACCENT,
    ACCENT_BRIGHT,
    BG,
    BORDER,
    FONT_MD,
    FONT_SM,
    PANEL,
    PANEL_ELEVATED,
    TEXT,
    TEXT_MUTED,
    PillNav,
    label,
    make_estimated_cost_box,
    section_title,
    styled_dropdown,
)
from media_studio.media import extract_frame_at, video_poster_path
from media_studio.pricing import probe_video_duration
from media_studio.runware_client import (
    ALEPH_MAX_DURATION_S,
    ALEPH_MAX_KEYFRAMES,
    ALEPH_MIN_DURATION_S,
    format_aleph_cost,
    has_runware_key,
)
from media_studio.ui_prefs import (
    get_frame_editor_auto_downscale,
    set_frame_editor_auto_downscale,
)
from media_studio.video_scale import (
    SCALE_COST_USD,
    needs_1080p_proxy,
    scale_video_to_1080p,
)
from media_studio.flet_video_player import VideoResultPlayer

if TYPE_CHECKING:
    from media_studio.flet_app import StudioState

_RUNWARE_KEYS_URL = "https://my.runware.ai/"
_RAIL_W = 460  # align with RAIL_WIDTH — never horizontal-expand in Row
# Right Preview / filmstrip (fixed sizes — never expand voids)
_PREVIEW_H = 440
_FILMSTRIP_H = 96
_FILMSTRIP_THUMB = 68
_MAX_FILE_MB = 200.0
# Filmstrip: denser on short clips; more samples + horizontal scroll on long
_STRIP_MIN = 12
_STRIP_MAX = 48

# Edit intent (UI only — maps to first/last/timestamp pins, not invented API fields)
_INTENT_APPLY = "apply"
_INTENT_TRANSITION = "transition"
_INTENT_CUSTOM = "custom"

_PROMPT_APPLY = (
    "Apply the edited look from the keyframe(s). "
    "Change only what the keyframe shows; keep motion, framing, "
    "lighting, and everything else exactly as in the source."
)
_PROMPT_TRANSITION = (
    "Transition the look from the first keyframe to the last keyframe over the clip. "
    "Interpolate only the guided change (e.g. day to night); keep camera motion, "
    "framing, architecture, and subject motion locked to the source."
)


@dataclass
class _KeyframeSlot:
    image_path: str
    pin: str = "first"  # first | last | timestamp
    timestamp_s: float = 0.0
    thumb_src: str = ""
    # Stable id so Studio round-trip can re-pin the same slot after edits
    slot_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])


@dataclass
class _StripFrame:
    timestamp_s: float
    path: str


def _probe_video_meta(path: str) -> dict[str, Any]:
    """Duration, size, resolution; never raises."""
    out: dict[str, Any] = {
        "duration_s": None,
        "size_mb": None,
        "width": None,
        "height": None,
        "error": None,
    }
    try:
        p = Path(path)
        if not p.is_file():
            out["error"] = "File not found"
            return out
        out["size_mb"] = p.stat().st_size / (1024 * 1024)
    except OSError as exc:
        out["error"] = f"Cannot read file: {exc}"
        return out

    try:
        out["duration_s"] = probe_video_duration(path)
    except Exception as exc:
        out["error"] = f"Duration probe failed: {exc}"

    try:
        import cv2

        cap = cv2.VideoCapture(str(path))
        try:
            if not cap.isOpened():
                out["error"] = out["error"] or "Could not open video (codec / path)"
            else:
                w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
                h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
                if w > 0 and h > 0:
                    out["width"] = w
                    out["height"] = h
                ok, frame = cap.read()
                if not ok or frame is None:
                    out["error"] = out["error"] or "Could not decode first frame"
        finally:
            cap.release()
    except Exception as exc:
        if not out["error"]:
            out["error"] = f"OpenCV error: {exc}"
    return out


def _frame_cache_dir(output_dir: str) -> Path:
    from media_studio.config import ensure_output_dir

    d = ensure_output_dir(Path(output_dir)) / "_aleph_keyframes"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _extract_still(
    video_path: str,
    seconds: float,
    output_dir: str,
    *,
    tag: str = "frame",
) -> tuple[str | None, str | None]:
    """
    Decode one still from video → absolute PNG path.

    Returns (path, error). Always prefers a fresh OpenCV extract under
    ``_aleph_keyframes`` so Flet Image gets a stable local file.
    """
    try:
        vp = Path(video_path)
        if not vp.is_file():
            return None, f"Video not found: {video_path}"
        out_dir = _frame_cache_dir(output_dir)
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in vp.stem)[:60]
        t_tag = f"{max(0.0, float(seconds)):.2f}".replace(".", "p")
        dest = out_dir / f"{safe}_{tag}_t{t_tag}.png"
        # Re-extract if missing or empty
        if not (dest.is_file() and dest.stat().st_size > 100):
            extract_frame_at(vp, float(seconds), dest)
        if dest.is_file() and dest.stat().st_size > 100:
            return str(dest.resolve()), None
        return None, "Frame extract produced an empty file"
    except Exception as exc:
        return None, str(exc)


def _ensure_poster(video_path: str, output_dir: str) -> tuple[str | None, str | None]:
    """Return (absolute still path for first frame, error)."""
    # Prefer dedicated extract (reliable for Flet Image)
    path, err = _extract_still(video_path, 0.0, output_dir, tag="poster")
    if path:
        return path, None
    # Fallback: shared poster cache
    try:
        poster = video_poster_path(video_path, force=True)
        if poster and Path(poster).is_file() and Path(poster).stat().st_size > 100:
            return str(Path(poster).resolve()), None
    except Exception as exc:
        err = err or str(exc)
    return None, err or "Could not extract a preview frame"


def _sample_timestamps(duration_s: float) -> list[float]:
    """
    Evenly spaced times across the clip for filmstrip thumbs.

    Short clips get denser samples so the strip is useful (not half-empty).
    Longer clips get more samples with horizontal scroll (cap ``_STRIP_MAX``).
    Exact timestamp pin remains available via Extract / Pin frame.
    """
    dur = max(0.05, float(duration_s or 1.0))
    # Target step by length — fill the row usefully, scroll when needed
    if dur <= 3.5:
        step = 0.15  # ~3s → ~20 thumbs
    elif dur <= 8.0:
        step = 0.22
    elif dur <= 16.0:
        step = 0.30
    else:
        step = 0.40  # 30s → ~75 raw, clamped to max
    n = int(round(dur / step)) + 1
    n = max(_STRIP_MIN, min(_STRIP_MAX, n))
    if n <= 1:
        return [0.0]
    # Always include endpoints; evenly space interior
    end = max(0.04, dur - 0.02)
    times = [i * end / (n - 1) for i in range(n)]
    return [round(max(0.0, min(t, end)), 2) for t in times]


def sample_filmstrip(
    video_path: str,
    duration_s: float,
    output_dir: str,
) -> tuple[list[_StripFrame], str | None]:
    """
    Sample thumbs across the clip into cached JPEGs (density scales with duration).

    Opens the video once (OpenCV) for speed. Returns (frames, error).
    """
    import cv2
    from PIL import Image

    vp = Path(video_path)
    if not vp.is_file():
        return [], f"Video not found: {video_path}"

    out_dir = _frame_cache_dir(output_dir) / "filmstrip"
    out_dir.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in vp.stem)[:50]
    # Cache key includes mtime so re-exports refresh
    try:
        mtime = int(vp.stat().st_mtime)
    except OSError:
        mtime = 0

    frames: list[_StripFrame] = []
    cap = cv2.VideoCapture(str(vp))
    try:
        if not cap.isOpened():
            return [], "Could not open video for filmstrip"

        # Prefer OpenCV duration when probe is missing/off
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        nframes = float(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)
        cv_dur = (nframes / fps) if fps > 1e-3 and nframes > 0 else 0.0
        dur = float(duration_s or 0.0)
        if cv_dur > 0.2:
            if dur <= 0 or abs(dur - cv_dur) / max(cv_dur, 0.1) > 0.35:
                dur = cv_dur
        if dur <= 0:
            dur = max(cv_dur, 1.0)

        times = _sample_timestamps(dur)

        def _write_thumb(t: float, bgr) -> Path | None:
            dest = out_dir / f"{safe}_{mtime}_t{str(t).replace('.', 'p')}.jpg"
            if dest.is_file() and dest.stat().st_size > 80:
                return dest
            try:
                rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                im = Image.fromarray(rgb)
                im.thumbnail(
                    (_FILMSTRIP_THUMB * 2, _FILMSTRIP_THUMB * 2),
                    Image.Resampling.LANCZOS,
                )
                im.save(dest, format="JPEG", quality=78)
                if dest.is_file() and dest.stat().st_size > 80:
                    return dest
            except Exception:
                return None
            return None

        # Pass 1: seek by time (fast when the container supports it)
        for t in times:
            dest = out_dir / f"{safe}_{mtime}_t{str(t).replace('.', 'p')}.jpg"
            if dest.is_file() and dest.stat().st_size > 80:
                frames.append(_StripFrame(timestamp_s=t, path=str(dest.resolve())))
                continue
            cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, t) * 1000.0)
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            written = _write_thumb(t, frame)
            if written:
                frames.append(
                    _StripFrame(timestamp_s=t, path=str(written.resolve()))
                )

        # Pass 2: sequential walk if seek dropped most samples
        if len(frames) < max(4, len(times) // 3) and fps > 1e-3:
            frames = []
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            target_set = list(times)
            ti = 0
            frame_i = 0
            while ti < len(target_set):
                ok, frame = cap.read()
                if not ok or frame is None:
                    break
                t_now = frame_i / fps
                frame_i += 1
                while ti < len(target_set) and t_now + (0.5 / fps) >= target_set[ti]:
                    t = target_set[ti]
                    written = _write_thumb(t, frame)
                    if written:
                        frames.append(
                            _StripFrame(timestamp_s=t, path=str(written.resolve()))
                        )
                    ti += 1
    finally:
        cap.release()

    if not frames:
        # Fallback: first frame only
        still, err = _extract_still(video_path, 0.0, output_dir, tag="strip0")
        if still:
            return [_StripFrame(timestamp_s=0.0, path=still)], (
                "Filmstrip sampling limited — showing first frame only. "
                "Use Extract at time for other moments."
            )
        return [], err or "Filmstrip sampling failed"
    return frames, None


class FrameEditorView:
    """Frame Editor — source + keyframes → Aleph. Compact, preview-first."""

    def __init__(self, page: ft.Page, state: StudioState) -> None:
        self.page = page
        self.state = state
        # video_path = path used for Aleph (proxy if scaled); original kept separately
        self.video_path: str | None = None
        self.original_video_path: str | None = None
        self.video_duration_s: float | None = None
        self.video_size_mb: float | None = None
        # Immutable master resolution — never overwrite with proxy dims
        self.original_wh: tuple[int, int] | None = None
        # Display / proxy resolution (may differ after scale)
        self.video_wh: tuple[int, int] | None = None
        self._proxy_path: str | None = None
        self._needs_proxy: bool = False
        self._proxy_ok: bool = True  # False if scale required but failed/pending
        self._proxy_busy: bool = False
        self._scale_status: str = ""
        self.keyframes: list[_KeyframeSlot] = []
        self._result_path: str | None = None
        self._source_poster: str | None = None
        self._selected_kf: int | None = None  # index to enlarge in preview
        self._preview_mode: str = "empty"  # empty | source | keyframe | result | progress
        # Last strip still path (for Pin without re-extract)
        self._pending_strip_still: str | None = None
        self._pending_strip_t: float = 0.0
        # Still staged from Creative Vision / Library when no source video yet
        self._handoff_still: str | None = None
        # Filmstrip: sampled thumbs across the clip (cached JPEGs)
        self._strip_frames: list[_StripFrame] = []
        self._selected_strip: int | None = None
        self._strip_source_path: str | None = None  # path last sampled from

        # ----- Provider strip -----
        self._key_banner_text = ft.Text(
            "", size=FONT_SM, color=TEXT, expand=True, max_lines=2
        )
        self.key_banner = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.KEY, size=16, color=TEXT_MUTED),
                    self._key_banner_text,
                    ft.TextButton(
                        content="Settings",
                        icon=ft.Icons.SETTINGS,
                        on_click=self._open_settings,
                        style=ft.ButtonStyle(color=ACCENT_BRIGHT),
                    ),
                ],
                spacing=6,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=PANEL_ELEVATED,
            border=ft.Border.all(1, BORDER),
            border_radius=6,
            padding=ft.Padding.symmetric(horizontal=10, vertical=6),
        )

        # ----- 1. Source -----
        self.src_thumb = ft.Image(
            src="", fit=ft.BoxFit.COVER, width=100, height=56, visible=False, border_radius=4
        )
        self.src_thumb_ph = ft.Container(
            content=ft.Icon(ft.Icons.MOVIE, size=22, color=TEXT_MUTED),
            width=100,
            height=56,
            alignment=ft.Alignment.CENTER,
            bgcolor="#1a1d24",
            border=ft.Border.all(1, BORDER),
            border_radius=4,
        )
        self.video_label = ft.Text(
            "No source yet",
            size=FONT_SM,
            color=TEXT_MUTED,
            max_lines=3,
            expand=True,
        )
        self.btn_upload = ft.OutlinedButton(
            content="Upload video",
            icon=ft.Icons.VIDEO_FILE,
            on_click=self._pick_video,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
            height=34,
        )
        self.auto_downscale = ft.Checkbox(
            label="Auto-downscale for Aleph (1080p proxy via fal)",
            value=get_frame_editor_auto_downscale(),
            on_change=self._on_auto_downscale_toggle,
        )
        self.proxy_line = ft.Text(
            "",
            size=11,
            color=TEXT_MUTED,
            max_lines=3,
            visible=False,
        )
        # Dual-key clarity when oversize / proxy path is active
        self.dual_key_banner = ft.Text(
            "Proxy = fal · Aleph = Runware — both keys needed for oversize sources.",
            size=11,
            color=TEXT_MUTED,
            max_lines=2,
            visible=False,
        )
        self.prev_strip = PreviousSourcesStrip(
            page,
            get_output_dir=lambda: self.state.output_dir,
            on_load=self._on_prev_video,
            media_kind="video",
        )
        self.resolve_strip = ResolveSourcesStrip(
            page,
            on_load=self._on_resolve_media,
            media_kind="both",
            empty_hint="Import from Resolve or send from the plugin",
        )

        # ----- 2. Keyframes -----
        # tight + no expand — never a blank flex region under the keyframe list
        self.kf_host = ft.Column(spacing=4, tight=True, expand=False)
        self.extract_time = ft.TextField(
            label="At (s)",
            value="0",
            dense=True,
            width=70,
            filled=True,
            fill_color=PANEL_ELEVATED,
            border_color=BORDER,
            color=TEXT,
            text_size=FONT_SM,
            content_padding=6,
        )
        self.default_pin = styled_dropdown(
            label_text="Pin",
            options=["first", "last", "timestamp"],
            value="first",
            expand=True,
        )
        self.btn_extract = ft.OutlinedButton(
            content="Extract at time",
            icon=ft.Icons.CONTENT_CUT,
            on_click=self._extract_frame,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
            height=34,
            tooltip="Decode a still at the time above and add as a keyframe",
        )
        self.btn_pin_strip = ft.FilledButton(
            content="Pin frame",
            icon=ft.Icons.PUSH_PIN,
            on_click=self._pin_selected_strip,
            style=ft.ButtonStyle(bgcolor=ACCENT, color=TEXT),
            height=34,
            tooltip=(
                "Add the selected filmstrip frame as a keyframe (timestamp pin). "
                "Clicking the strip only previews — it does not burn a slot."
            ),
        )
        self.btn_upload_kf = ft.OutlinedButton(
            content="Upload still",
            icon=ft.Icons.IMAGE,
            on_click=self._upload_keyframe,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
            height=34,
            tooltip="Upload a Studio-edited frame as a keyframe",
        )
        # Send to ▾ — Studio Image + Creative Vision Start/End/I2V
        self.send_host = ft.Container(visible=True)
        self._rebuild_send_menu()

        # ----- Prompt + generate (live in the left ListView stack) -----
        # Edit intent — UI helper only (Aleph still gets first/last/timestamp + prompt)
        self._edit_intent = _INTENT_APPLY
        self.intent_hint = ft.Text(
            "One keyframe ≈ apply that look through the clip. "
            "First + last (or two timestamps) ≈ transition between looks.",
            size=11,
            color=TEXT_MUTED,
            max_lines=3,
        )
        self.intent_nav = PillNav(
            [
                (_INTENT_APPLY, "Apply through clip"),
                (_INTENT_TRANSITION, "Transition first→last"),
                (_INTENT_CUSTOM, "Custom timestamps"),
            ],
            selected=_INTENT_APPLY,
            on_change=self._on_edit_intent,
        )
        self.prompt = ft.TextField(
            label="What to change",
            hint_text="Remove the person in the mirror. Change nothing else.",
            value=_PROMPT_APPLY,
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
            surface="frame_editor",
            get_meta=lambda: {"source": "user", "model": "aleph"},
            on_status=lambda m: setattr(self.status, "value", m),
            show_pack_buttons=False,
        )
        self.cost_text, self.cost_box = make_estimated_cost_box(
            initial=format_aleph_cost(None)
        )
        try:
            self.cost_text.max_lines = 3
        except Exception:
            pass
        self.btn_generate = ft.FilledButton(
            content="Generate (Aleph 2.0)",
            on_click=self._run,
            style=ft.ButtonStyle(bgcolor=ACCENT_BRIGHT, color=TEXT),
            height=40,
            width=_RAIL_W - 28,
        )
        self.btn_enhance = make_enhance_button(on_click=self._on_enhance)
        self.status = ft.Text("", size=FONT_SM, color=TEXT_MUTED, max_lines=2)
        self.job_progress = JobProgress(width=_RAIL_W - 28)
        try:
            self.job_progress.bar.expand = False
            self.job_progress.control.tight = True
            self.job_progress.control.expand = False
            self.job_progress.control.visible = False
        except Exception:
            pass

        # ----- Right: fixed Preview + filmstrip -----
        self.preview_caption = ft.Text(
            "Upload a source video to begin",
            size=FONT_SM,
            color=TEXT_MUTED,
            max_lines=2,
        )
        self._preview_img_src: str | None = None
        self._ftv: Any = None
        try:
            import flet_video as ftv

            self._ftv = ftv
        except Exception:
            self._ftv = None

        # Single Image control — content of preview_box is swapped (reliable paint)
        self.preview_image = ft.Image(
            src="",
            fit=ft.BoxFit.CONTAIN,
            width=900,
            height=_PREVIEW_H - 16,
            gapless_playback=False,
        )
        self.preview_box = ft.Container(
            content=self._empty_preview_content(),
            height=_PREVIEW_H,
            bgcolor="#111318",
            border=ft.Border.all(1, BORDER),
            border_radius=8,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
            alignment=ft.Alignment.CENTER,
        )
        # In-app result player — actions live in FE row under player (always reachable)
        self.result_player = VideoResultPlayer(
            page,
            height=_PREVIEW_H - 12,
            embed_actions=False,
            show_path_row=True,
        )
        try:
            from media_studio.flet_theme import EMPTY_PREVIEW_H

            self.result_player.control.visible = False
            self.result_player.control.height = EMPTY_PREVIEW_H + 40
            self.result_player.control.expand = False
        except Exception:
            pass

        self.filmstrip_caption = ft.Text(
            "Filmstrip · click = preview · Pin frame = keyframe · scroll when long",
            size=11,
            color=TEXT_MUTED,
            max_lines=1,
        )
        self.filmstrip_row = ft.Row(
            controls=[],
            spacing=6,
            scroll=ft.ScrollMode.AUTO,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )
        self.filmstrip_host = ft.Container(
            content=self.filmstrip_row,
            height=_FILMSTRIP_H + 8,
            bgcolor="#0d0f14",
            border=ft.Border.all(1, BORDER),
            border_radius=6,
            padding=ft.Padding.symmetric(horizontal=6, vertical=4),
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
        )

        # Result row: Send to ▾ (Vision / Studio) + Show in folder + Resolve
        self.result_send_host = ft.Container(visible=False)
        (
            self.result_actions_row,
            self.btn_folder,
            self.btn_resolve,
        ) = make_result_action_row(
            page,
            get_path=lambda: self._result_path,
            on_status=lambda msg, err: self._set_status(msg, err),
            extra_leading=[self.result_send_host],
        )
        show_result_actions(self.btn_folder, self.btn_resolve, visible=False)

        self.state.on_keys_changed(self.apply_key_gates)
        self.apply_key_gates()
        self._rebuild_kf_list()
        self._rebuild_filmstrip()
        self._set_preview_mode("empty")

        # Orientation only — does not change Generate, cost, or layout structure
        self.howto_box = ft.Container(
            content=ft.Column(
                [
                    ft.Text(
                        "How to use Frame Editor",
                        size=FONT_SM,
                        color=TEXT,
                        weight=ft.FontWeight.W_700,
                    ),
                    ft.Text(
                        "1. Upload or send a source video (auto-proxy available).\n"
                        "2. Pick edit intent: apply through clip, transition first→last, "
                        "or custom timestamps.\n"
                        "3. Pin keyframes on the filmstrip (or upload stills) — max 5.\n"
                        "4. Describe only what should change at those frames; "
                        "motion/framing stay locked.\n"
                        "5. Enhance if needed, then Generate (Aleph 2.0).",
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

    # ------------------------------------------------------------------ layout

    def _empty_preview_content(self) -> ft.Control:
        return ft.Column(
            [
                ft.Icon(ft.Icons.MOVIE_FILTER, size=36, color=TEXT_MUTED),
                ft.Text(
                    "Select a filmstrip frame or load a source",
                    size=FONT_SM,
                    color=TEXT_MUTED,
                    text_align=ft.TextAlign.CENTER,
                ),
                ft.Text(
                    "Day→night: pin day at first, night at last, then Generate",
                    size=11,
                    color=TEXT_MUTED,
                    text_align=ft.TextAlign.CENTER,
                ),
            ],
            spacing=8,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            tight=True,
            alignment=ft.MainAxisAlignment.CENTER,
        )

    def _progress_preview_content(self) -> ft.Control:
        return ft.Column(
            [
                ft.ProgressRing(width=36, height=36, color=ACCENT),
                ft.Text("Aleph is running…", size=FONT_SM, color=TEXT_MUTED),
            ],
            spacing=10,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            tight=True,
            alignment=ft.MainAxisAlignment.CENTER,
        )

    def build(self) -> ft.Control:
        """
        Full redesign — two columns, no legacy grey rail.

        LEFT (ListView of individual controls — every item is real UI):
          status → source → proxy → previous → keyframes → extract/upload
          → send Studio → prompt → enhance → cost → Generate

        RIGHT (flex, top-aligned):
          Preview (fixed height) + filmstrip
        """
        # ---- LEFT: scrollable main + sticky Generate footer ----
        left_scroll_items: list[ft.Control] = [
            section_title("Frame Editor"),
            self.howto_box,
            self.key_banner,
            label("Source video", muted=True),
            ft.Row(
                [
                    ft.Stack(
                        [self.src_thumb_ph, self.src_thumb],
                        width=100,
                        height=56,
                    ),
                    ft.Column(
                        [self.video_label, self.btn_upload],
                        spacing=2,
                        expand=True,
                        tight=True,
                    ),
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            self.auto_downscale,
            self.proxy_line,
            self.dual_key_banner,
            self.prev_strip.root,
            self.resolve_strip.root,
            ft.Divider(height=1, color=BORDER),
            label("Edit intent", muted=True),
            self.intent_nav.control,
            self.intent_hint,
            label(f"Keyframes (max {ALEPH_MAX_KEYFRAMES})", muted=True),
            self.kf_host,
            ft.Row([self.extract_time, self.default_pin], spacing=6),
            ft.Row(
                [self.btn_pin_strip, self.btn_extract, self.btn_upload_kf],
                spacing=6,
                wrap=True,
            ),
            self.send_host,
            ft.Divider(height=1, color=BORDER),
            label("Prompt", muted=True),
            self.prompt,
            self.prompt_favs.root,
            self.btn_enhance,
        ]
        # Sticky footer — Generate then Studio-standard Est. cost chrome
        left_footer = ft.Column(
            [
                ft.Divider(height=1, color=BORDER),
                self.btn_generate,
                self.cost_box,
                self.job_progress.control,
                self.status,
            ],
            spacing=6,
            tight=True,
            expand=False,
        )
        left = ft.Container(
            width=_RAIL_W,
            expand=False,
            bgcolor=BG,
            border=ft.Border.only(right=ft.BorderSide(1, BORDER)),
            padding=ft.Padding.only(right=10, top=4, bottom=4),
            content=ft.Column(
                [
                    ft.ListView(
                        controls=left_scroll_items,
                        expand=True,
                        spacing=6,
                        padding=ft.Padding.only(right=4, bottom=8),
                    ),
                    left_footer,
                ],
                spacing=4,
                expand=True,
            ),
        )

        # result_player only when there is a result (not forced full preview height)
        try:
            self.result_player.control.expand = False
            self.result_player.control.visible = False
            from media_studio.flet_theme import EMPTY_PREVIEW_H

            self.result_player.control.height = EMPTY_PREVIEW_H + 40
        except Exception:
            pass
        # Preview primary → actions under player (reachable) → filmstrip secondary
        right = ft.Container(
            expand=True,
            bgcolor=PANEL,
            border=ft.Border.all(1, BORDER),
            border_radius=8,
            padding=12,
            alignment=ft.Alignment.TOP_LEFT,
            content=ft.Column(
                [
                    section_title("Preview"),
                    self.preview_caption,
                    self.preview_box,
                    self.result_player.control,
                    self.result_actions_row,
                    self.filmstrip_caption,
                    self.filmstrip_host,
                    ft.Text(
                        f"{ALEPH_MIN_DURATION_S:.0f}–{ALEPH_MAX_DURATION_S:.0f}s · "
                        f"≤{ALEPH_MAX_KEYFRAMES} keyframes · ~1080p · Aleph 2.0",
                        size=11,
                        color=TEXT_MUTED,
                    ),
                ],
                spacing=8,
                tight=True,
                expand=False,
                alignment=ft.MainAxisAlignment.START,
            ),
        )

        return ft.Row(
            [left, right],
            spacing=12,
            expand=True,
            vertical_alignment=ft.CrossAxisAlignment.STRETCH,
        )

    # -------------------------------------------------------------- keys / status

    def _generate_block_reason(self) -> str | None:
        """Why Generate should stay disabled (or None if ready)."""
        if self.state.is_busy("frame_editor"):
            return "A job is already running."
        if not has_runware_key():
            return "Add Runware API key in Settings — fal does not cover Aleph."
        if not self.video_path or not Path(self.video_path).is_file():
            return "Upload a source video first."
        if self._proxy_busy:
            return "1080p proxy still in progress — wait for scale to finish."
        if self._needs_proxy and not self._proxy_ok:
            return (
                "Source is above 1080p-class and no proxy is ready. "
                "Enable Auto-downscale (needs FAL key) or load a smaller clip."
            )
        if self.video_duration_s is not None:
            if self.video_duration_s + 0.05 < ALEPH_MIN_DURATION_S:
                return (
                    f"Clip too short ({self.video_duration_s:.1f}s) — "
                    f"Aleph needs {ALEPH_MIN_DURATION_S:.0f}–{ALEPH_MAX_DURATION_S:.0f}s."
                )
            if self.video_duration_s > ALEPH_MAX_DURATION_S + 0.25:
                return (
                    f"Clip too long ({self.video_duration_s:.1f}s) — "
                    f"trim to ≤{ALEPH_MAX_DURATION_S:.0f}s."
                )
        return None

    def apply_key_gates(self) -> None:
        from media_studio.secrets_store import has_xai_key

        ready = has_runware_key()
        if ready:
            self._key_banner_text.value = (
                "Aleph ready — Runware key (separate from fal). "
                "fal alone is not enough for this tab."
            )
            self._key_banner_text.color = TEXT
            try:
                self.key_banner.border = ft.Border.all(1, ACCENT)
            except Exception:
                pass
        else:
            self._key_banner_text.value = (
                "Requires a separate API key (Runware / Aleph). "
                "Add it in Settings — fal alone is not enough."
            )
            self._key_banner_text.color = "#e57373"
            try:
                self.key_banner.border = ft.Border.all(1, "#e57373")
            except Exception:
                pass

        # Dual-key banner when oversize path is in play
        try:
            show_dual = bool(self._needs_proxy)
            self.dual_key_banner.visible = show_dual
            if show_dual:
                self.dual_key_banner.value = (
                    "Proxy = fal · Aleph = Runware — both keys needed for oversize sources."
                )
        except Exception:
            pass

        if not self.state.is_busy("frame_editor"):
            block = self._generate_block_reason()
            self.btn_generate.disabled = block is not None
            self.btn_generate.tooltip = block
            xai = has_xai_key()
            self.btn_enhance.disabled = not xai
            self.btn_enhance.tooltip = (
                "Rewrite prompt for Aleph (Grok)"
                if xai
                else "Add xAI key for Enhance"
            )

    async def _open_settings(self, _e: ft.ControlEvent) -> None:
        try:
            from media_studio.flet_settings import open_settings_dialog

            def _after_save() -> None:
                self.apply_key_gates()
                try:
                    self.page.update()
                except Exception:
                    pass

            open_settings_dialog(self.page, on_saved=_after_save, focus="runware")
        except Exception as exc:
            self._set_status(f"Settings: {exc}", True)

    def _set_status(self, msg: str, is_error: bool = False) -> None:
        self.status.value = msg
        self.status.color = "#e57373" if is_error else TEXT_MUTED
        try:
            self.page.update()
        except Exception:
            pass

    def _refresh_cost(self) -> None:
        self.cost_text.value = format_aleph_cost(self.video_duration_s)

    # ----------------------------------------------------------- preview modes

    def _paint_preview_image(self, path: str) -> bool:
        """
        Show ``path`` large in Preview.

        Rebuilds a fresh Image control and assigns it as preview_box.content
        so Flet always paints (avoids black / stale src issues).
        """
        try:
            p = Path(path)
            if not p.is_file() or p.stat().st_size < 32:
                return False
            abs_path = str(p.resolve()).replace("\\", "/")
        except OSError:
            return False

        self._preview_img_src = abs_path
        try:
            img = ft.Image(
                src=abs_path,
                fit=ft.BoxFit.CONTAIN,
                width=900,
                height=_PREVIEW_H - 16,
                gapless_playback=False,
            )
            self.preview_image = img
            self.preview_box.content = img
            self.preview_box.height = _PREVIEW_H
            self.preview_box.alignment = ft.Alignment.CENTER
        except Exception:
            return False
        return True

    def _hide_result_player(self) -> None:
        try:
            self.result_player.clear()
            self.result_player.control.visible = False
            self.preview_box.visible = True
        except Exception:
            pass

    def _set_preview_mode(
        self,
        mode: str,
        *,
        image_src: str | None = None,
        caption: str | None = None,
        video_path: str | None = None,
    ) -> None:
        """mode: empty | source | keyframe | result | progress"""
        self._preview_mode = mode

        if mode == "result" and video_path and Path(video_path).is_file():
            # In-app video play (CONTAIN + controls); poster fallback if unavailable
            poster, _ = _ensure_poster(video_path, self.state.output_dir)
            has_player = False
            try:
                # Fixed-height CONTAIN layout — never expand into a grey void
                self.result_player.control.expand = False
                self.result_player.set_result(
                    video_path,
                    note=caption or f"Result · {Path(video_path).name}",
                )
                self.result_player.control.visible = True
                has_player = getattr(self.result_player, "_video", None) is not None
            except Exception:
                has_player = False
                try:
                    self.result_player.control.visible = False
                except Exception:
                    pass
            # FE owns Show in folder / Resolve / Send — keep under player
            try:
                show_result_actions(self.btn_folder, self.btn_resolve, visible=True)
                self.result_actions_row.visible = True
            except Exception:
                pass
            if has_player:
                self.preview_box.visible = False
            elif poster and self._paint_preview_image(poster):
                self.preview_box.visible = True
            else:
                self.preview_box.content = self._empty_preview_content()
                self.preview_box.visible = True
                caption = (
                    caption or "Result ready — could not open player or poster"
                )
        elif mode == "progress":
            self._hide_result_player()
            self.preview_box.content = self._progress_preview_content()
            self.preview_box.visible = True
        elif mode in ("source", "keyframe"):
            self._hide_result_player()
            path = image_src
            if not (path and self._paint_preview_image(path)):
                self.preview_box.content = self._empty_preview_content()
                if path:
                    caption = caption or f"Preview file missing: {path}"
            self.preview_box.visible = True
        else:
            self._hide_result_player()
            self.preview_box.content = self._empty_preview_content()
            self.preview_box.visible = True
            if mode != "empty" and image_src and not Path(image_src).is_file():
                caption = caption or f"Preview file missing: {image_src}"

        try:
            self.preview_box.height = _PREVIEW_H
        except Exception:
            pass

        if caption is not None:
            self.preview_caption.value = caption
        elif mode == "empty":
            self.preview_caption.value = "Upload a source video to begin"
        elif mode == "progress":
            self.preview_caption.value = "Generating with Aleph 2.0…"

    # ----------------------------------------------------------- filmstrip

    def _clear_filmstrip(self, *, caption: str | None = None) -> None:
        self._strip_frames = []
        self._selected_strip = None
        self._strip_source_path = None
        self.filmstrip_caption.value = (
            caption or "Sampled frames appear here after a source is ready"
        )
        self.filmstrip_caption.color = TEXT_MUTED
        self._rebuild_filmstrip()

    def _rebuild_filmstrip(self) -> None:
        """Paint strip thumbs + time labels; highlight selected strip / matching keyframe."""
        if not self._strip_frames:
            self.filmstrip_row.controls = [
                ft.Container(
                    content=ft.Text(
                        "No strip yet",
                        size=11,
                        color=TEXT_MUTED,
                    ),
                    height=_FILMSTRIP_H - 4,
                    padding=ft.Padding.symmetric(horizontal=8),
                    alignment=ft.Alignment.CENTER_LEFT,
                )
            ]
            return

        # Timestamps already used as keyframes (timestamp pins + first/last endpoints)
        kf_times = {
            round(float(k.timestamp_s), 2)
            for k in self.keyframes
            if k.pin == "timestamp"
        }
        has_first = any(k.pin == "first" for k in self.keyframes)
        has_last = any(k.pin == "last" for k in self.keyframes)
        n_frames = len(self._strip_frames)
        dur = float(self.video_duration_s or 0.0)

        cells: list[ft.Control] = []
        for i, fr in enumerate(self._strip_frames):
            idx = i
            selected = self._selected_strip == i
            is_kf = round(fr.timestamp_s, 2) in kf_times
            # Highlight first/last strip ends when those pins are used
            if has_first and i == 0:
                is_kf = True
            if has_last and (i == n_frames - 1 or (dur > 0 and fr.timestamp_s >= dur - 0.08)):
                is_kf = True
            border_c = (
                ACCENT_BRIGHT
                if selected
                else (ACCENT if is_kf else BORDER)
            )
            border_w = 2 if selected or is_kf else 1
            t_label = f"{fr.timestamp_s:.2f}s"

            def make_click(ii: int):
                async def _clk(_e: ft.ControlEvent) -> None:
                    await self._on_strip_click(ii)

                return _clk

            cells.append(
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Image(
                                src=fr.path,
                                width=_FILMSTRIP_THUMB,
                                height=_FILMSTRIP_THUMB - 12,
                                fit=ft.BoxFit.COVER,
                                border_radius=3,
                                gapless_playback=False,
                            ),
                            ft.Text(
                                t_label,
                                size=10,
                                color=ACCENT_BRIGHT if selected else (
                                    ACCENT if is_kf else TEXT_MUTED
                                ),
                                text_align=ft.TextAlign.CENTER,
                            ),
                        ],
                        spacing=2,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        tight=True,
                    ),
                    width=_FILMSTRIP_THUMB + 4,
                    padding=2,
                    border=ft.Border.all(border_w, border_c),
                    border_radius=5,
                    bgcolor="#1a1d24" if selected else PANEL_ELEVATED,
                    on_click=make_click(idx),
                    ink=True,
                    tooltip=(
                        f"t={t_label} — click to preview"
                        + (" · keyframe" if is_kf else "")
                        + " · Pin frame to add slot"
                    ),
                )
            )
        self.filmstrip_row.controls = cells
        n = len(cells)
        try:
            self.filmstrip_caption.value = (
                f"Filmstrip · {n} frames · click = preview · Pin frame = keyframe"
                + (" · scroll →" if n > 14 else "")
            )
        except Exception:
            pass

    async def _on_strip_click(self, index: int) -> None:
        """Preview-only: show strip frame large. Does NOT add a keyframe slot."""
        if not (0 <= index < len(self._strip_frames)):
            return
        fr = self._strip_frames[index]
        self._selected_strip = index
        t = float(fr.timestamp_s)

        try:
            self.extract_time.value = f"{t:.2f}"
            self.default_pin.value = "timestamp"
        except Exception:
            pass

        # Paint thumb immediately so Preview is never black
        still_path = fr.path
        self._pending_strip_still = still_path
        self._pending_strip_t = t
        self._set_preview_mode(
            "source",
            image_src=still_path,
            caption=f"Preview · t={t:.2f}s · Pin frame to add keyframe",
        )
        try:
            self.page.update()
        except Exception:
            pass

        # Optional full-res upgrade for clearer preview (still no auto-pin)
        src_vid = self.video_path or self.original_video_path
        if src_vid and Path(src_vid).is_file():
            full, _err = await asyncio.to_thread(
                _extract_still,
                src_vid,
                t,
                self.state.output_dir,
                tag="strip_prev",
            )
            if full:
                still_path = full
                self._pending_strip_still = full
                self._set_preview_mode(
                    "source",
                    image_src=still_path,
                    caption=f"Preview · t={t:.2f}s · Pin frame to add keyframe",
                )

        # If a keyframe already exists at this time, highlight it (do not add)
        for i, kf in enumerate(self.keyframes):
            if kf.pin == "timestamp" and abs(float(kf.timestamp_s) - t) < 0.06:
                self._selected_kf = i
                break
        else:
            self._selected_kf = None

        self.status.value = (
            f"Preview t={t:.2f}s — click Pin frame to save as keyframe "
            f"({len(self.keyframes)}/{ALEPH_MAX_KEYFRAMES} used)"
        )
        self.status.color = TEXT_MUTED
        self._rebuild_kf_list()
        self._rebuild_filmstrip()
        try:
            self.page.update()
        except Exception:
            pass

    async def _pin_selected_strip(self, _e: ft.ControlEvent) -> None:
        """Explicit Pin — add/update keyframe at selected strip time."""
        if self._selected_strip is None or not (
            0 <= self._selected_strip < len(self._strip_frames)
        ):
            if self._pending_strip_still and Path(self._pending_strip_still).is_file():
                t = float(self._pending_strip_t)
                still = self._pending_strip_still
            else:
                self._set_status(
                    "Select a filmstrip frame first, then Pin frame.",
                    True,
                )
                return
        else:
            fr = self._strip_frames[self._selected_strip]
            t = float(fr.timestamp_s)
            still = self._pending_strip_still or fr.path
            src_vid = self.video_path or self.original_video_path
            if src_vid and Path(src_vid).is_file():
                full, err = await asyncio.to_thread(
                    _extract_still,
                    src_vid,
                    t,
                    self.state.output_dir,
                    tag="strip_kf",
                )
                if full:
                    still = full
                elif err and not Path(still).is_file():
                    self._set_status(f"Pin failed: {err}", True)
                    return

        # Update existing slot at this time, else add
        for i, kf in enumerate(self.keyframes):
            if kf.pin == "timestamp" and abs(float(kf.timestamp_s) - t) < 0.06:
                self.add_keyframe(
                    still,
                    pin="timestamp",
                    timestamp_s=t,
                    replace_index=i,
                    slot_id=kf.slot_id,
                    status=f"Updated keyframe #{i + 1} · t={t:.2f}s",
                )
                try:
                    self.page.update()
                except Exception:
                    pass
                return

        ok = self.add_keyframe(
            still,
            pin="timestamp",
            timestamp_s=t,
            status=f"Pinned keyframe · t={t:.2f}s",
        )
        if ok:
            try:
                self.default_pin.value = "timestamp"
            except Exception:
                pass
        try:
            self.page.update()
        except Exception:
            pass

    def _schedule_filmstrip(self, video_path: str | None = None) -> None:
        """Kick off background sampling when source (or proxy) is ready."""
        path = video_path or self.video_path or self.original_video_path
        if not path or not Path(path).is_file():
            return
        try:
            self.page.run_task(self._sample_filmstrip_async, path)
        except Exception:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(self._sample_filmstrip_async(path))
            except Exception:
                pass

    async def _sample_filmstrip_async(self, video_path: str) -> None:
        """Sample ~16–24 thumbs on a worker thread; cache under _aleph_keyframes/filmstrip."""
        if not video_path or not Path(video_path).is_file():
            return
        # Avoid double-sample of the same ready path
        if self._strip_source_path == video_path and self._strip_frames:
            return

        self.filmstrip_caption.value = "Sampling frames for filmstrip…"
        self.filmstrip_caption.color = TEXT_MUTED
        try:
            self.page.update()
        except Exception:
            pass

        dur = float(self.video_duration_s or 0.0)
        if dur <= 0:
            try:
                dur = float(probe_video_duration(video_path) or 1.0)
            except Exception:
                dur = 1.0

        try:
            frames, err = await asyncio.to_thread(
                sample_filmstrip,
                video_path,
                dur,
                self.state.output_dir,
            )
        except Exception as exc:
            frames, err = [], str(exc)

        # Phase E: bound filmstrip / proxy disk growth (app-owned dirs only)
        try:
            from media_studio.cache_prune import prune_aleph_side_files

            await asyncio.to_thread(prune_aleph_side_files, self.state.output_dir)
        except Exception:
            pass

        # Stale if source changed while we were sampling
        cur = self.video_path or self.original_video_path
        if cur and Path(video_path).resolve() != Path(cur).resolve():
            # Prefer current path; ignore this result if paths differ and current is proxy-related
            # Allow if video_path is the active Aleph path
            if Path(video_path).resolve() != Path(self.video_path or "").resolve():
                if Path(video_path).resolve() != Path(
                    self.original_video_path or ""
                ).resolve():
                    return

        self._strip_frames = frames or []
        self._strip_source_path = video_path if frames else None
        self._selected_strip = None

        if frames:
            n = len(frames)
            span = (
                f"{frames[0].timestamp_s:.2f}s–{frames[-1].timestamp_s:.2f}s"
                if n > 1
                else f"{frames[0].timestamp_s:.2f}s"
            )
            if err:
                self.filmstrip_caption.value = err
                self.filmstrip_caption.color = "#e57373"
            else:
                self.filmstrip_caption.value = (
                    f"{n} sampled frames · {span} · click to preview + pin"
                )
                self.filmstrip_caption.color = TEXT_MUTED
        else:
            self.filmstrip_caption.value = (
                err
                or "Filmstrip sampling failed. Use Extract at time for manual picks."
            )
            self.filmstrip_caption.color = "#e57373"
            # Fallback: try first-frame still already extracted
            if self._source_poster:
                self._strip_frames = [
                    _StripFrame(timestamp_s=0.0, path=self._source_poster)
                ]
                self._strip_source_path = video_path
                self.filmstrip_caption.value = (
                    "Sampling failed — showing first frame only. "
                    "Use Extract at time for other moments."
                )

        self._rebuild_filmstrip()
        try:
            self.page.update()
        except Exception:
            pass

    # ----------------------------------------------------------- load source

    def load_source(
        self, path: str, *, as_video: bool = True, status: str | None = None
    ) -> bool:
        try:
            p = Path(path)
            if not p.is_file():
                self._set_status(f"Video missing: {path}", True)
                self._set_preview_mode("empty", caption="Video file not found")
                return False
            ext = p.suffix.lower()
            if ext not in {".mp4", ".mov", ".webm", ".m4v", ".avi", ".mkv"}:
                self._set_status(
                    f"Unsupported format {ext or '(none)'} — use mp4 / mov / webm.",
                    True,
                )
                return False
            resolved = str(p.resolve())
        except OSError as exc:
            self._set_status(f"Could not open video: {exc}", True)
            return False

        self.original_video_path = resolved
        self.video_path = resolved
        self._proxy_path = None
        self._proxy_ok = True
        self._proxy_busy = False
        self._needs_proxy = False
        self._scale_status = ""
        self.proxy_line.value = ""
        self.proxy_line.visible = False
        self.dual_key_banner.visible = False
        self._result_path = None
        self._selected_kf = None
        self._pending_strip_still = None
        self._pending_strip_t = 0.0
        # Preserve staged handoff still from Vision/Library across video load
        handoff = self._handoff_still
        # New source — never carry keyframes/pins from the previous clip
        self.keyframes = []
        self._rebuild_kf_list()
        try:
            self.state.frame_editor_return = None
        except Exception:
            pass
        self._clear_filmstrip(caption="Loading source… sampling when ready")
        self._hide_result_player()
        show_result_actions(self.btn_folder, self.btn_resolve, visible=False)
        try:
            self.result_send_host.visible = False
        except Exception:
            pass

        meta = _probe_video_meta(resolved)
        self.video_duration_s = meta.get("duration_s")
        self.video_size_mb = meta.get("size_mb")
        if meta.get("width") and meta.get("height"):
            # Immutable master size for scale decisions
            self.original_wh = (int(meta["width"]), int(meta["height"]))
            self.video_wh = self.original_wh
        else:
            self.original_wh = None
            self.video_wh = None

        name = Path(resolved).name
        parts = [name]
        if self.video_duration_s is not None:
            parts.append(f"{self.video_duration_s:.1f}s")
        if self.original_wh:
            parts.append(f"{self.original_wh[0]}×{self.original_wh[1]}")
        if self.video_size_mb is not None:
            parts.append(f"{self.video_size_mb:.0f} MB")
        self.video_label.value = " · ".join(parts)
        self.video_label.color = TEXT

        # Hard limits messaging (duration / size / decode)
        err_bits: list[str] = []
        if meta.get("error"):
            err_bits.append(str(meta["error"]))
        if self.video_duration_s is not None:
            if self.video_duration_s + 0.05 < ALEPH_MIN_DURATION_S:
                err_bits.append(
                    f"Too short ({self.video_duration_s:.1f}s) — Aleph needs "
                    f"{ALEPH_MIN_DURATION_S:.0f}–{ALEPH_MAX_DURATION_S:.0f}s."
                )
            elif self.video_duration_s > ALEPH_MAX_DURATION_S + 0.25:
                err_bits.append(
                    f"Too long ({self.video_duration_s:.1f}s) — trim to ≤{ALEPH_MAX_DURATION_S:.0f}s."
                )
        if self.video_size_mb is not None and self.video_size_mb > _MAX_FILE_MB:
            err_bits.append(
                f"File is {self.video_size_mb:.0f} MB — prefer a shorter proxy "
                f"(≤{_MAX_FILE_MB:.0f} MB)."
            )

        # Resolution → proxy plan (always from original_wh, never proxy dims)
        if self.original_wh:
            need = needs_1080p_proxy(self.original_wh[0], self.original_wh[1])
            self._needs_proxy = bool(need.needs_scale)
            if need.needs_scale:
                self.dual_key_banner.visible = True
                if self.auto_downscale.value:
                    self.proxy_line.visible = True
                    self.proxy_line.value = (
                        f"Source {need.width}×{need.height} — creating 1080p proxy "
                        f"({need.target_w}×{need.target_h}) via fal… "
                        f"(~${SCALE_COST_USD:.2f})"
                    )
                    self.proxy_line.color = TEXT_MUTED
                    self._proxy_ok = False  # until scale succeeds
                    self._proxy_busy = True
                else:
                    self._proxy_ok = False
                    self._proxy_busy = False
                    self.proxy_line.visible = True
                    self.proxy_line.value = (
                        f"Source {need.width}×{need.height} is above 1080p-class. "
                        "Enable Auto-downscale or export a smaller proxy before Generate."
                    )
                    self.proxy_line.color = "#e57373"
                    err_bits.append(self.proxy_line.value)
            else:
                self._needs_proxy = False
                self._proxy_ok = True
                self._proxy_busy = False

        # Poster
        poster, poster_err = _ensure_poster(resolved, self.state.output_dir)
        if poster:
            self._source_poster = poster
            try:
                self.src_thumb.src = poster
                self.src_thumb.visible = True
                self.src_thumb_ph.visible = False
            except Exception:
                pass
            self._set_preview_mode(
                "source",
                image_src=poster,
                caption=f"Source · {' · '.join(parts[1:])}" if len(parts) > 1 else f"Source · {name}",
            )
        else:
            self._source_poster = None
            try:
                self.src_thumb.visible = False
                self.src_thumb_ph.visible = True
            except Exception:
                pass
            msg = poster_err or "Could not extract a preview frame"
            self._set_preview_mode(
                "empty",
                caption=f"Source loaded but preview failed: {msg}",
            )
            err_bits.append(msg)

        self._refresh_cost()
        try:
            self.prev_strip.set_media_kind("video")
            self.prev_strip.record_and_refresh(resolved)
        except Exception:
            pass

        if err_bits and not (self._needs_proxy and self.auto_downscale.value):
            self._set_status(" · ".join(err_bits), True)
        else:
            self.status.value = status or f"Loaded {name}"
            self.status.color = TEXT_MUTED

        self.apply_key_gates()

        # Pin staged Vision/Library still as keyframe #1 (only this slot)
        if handoff and Path(handoff).is_file():
            self._handoff_still = None
            self.add_keyframe(
                handoff,
                pin="first",
                timestamp_s=0.0,
                status=f"Pinned handoff still as keyframe #1: {Path(handoff).name}",
            )

        # Kick auto-downscale (async) when needed; else sample filmstrip now
        if (
            self._needs_proxy
            and self.auto_downscale.value
            and self.original_wh
        ):
            try:
                self.page.run_task(self._auto_downscale_async)
            except Exception:
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        loop.create_task(self._auto_downscale_async())
                except Exception:
                    pass
            # Sample original immediately so the strip is usable while proxy builds
            self._schedule_filmstrip(resolved)
        else:
            self._schedule_filmstrip(resolved)
        return True

    async def _on_auto_downscale_toggle(self, e: ft.ControlEvent) -> None:
        on = bool(self.auto_downscale.value)
        try:
            set_frame_editor_auto_downscale(on)
        except Exception:
            pass
        # Re-evaluate from immutable original_wh (never proxy dims)
        if self.original_video_path and Path(self.original_video_path).is_file():
            if self.original_wh:
                need = needs_1080p_proxy(self.original_wh[0], self.original_wh[1])
                self._needs_proxy = bool(need.needs_scale)
            if on and self._needs_proxy:
                self.proxy_line.visible = True
                self.proxy_line.color = TEXT_MUTED
                self.proxy_line.value = "Auto-downscale on — creating/using 1080p proxy…"
                self._proxy_ok = False
                self._proxy_busy = True
                self.dual_key_banner.visible = True
                self.apply_key_gates()
                try:
                    self.page.update()
                except Exception:
                    pass
                await self._auto_downscale_async()
            elif not on:
                if self.original_video_path:
                    self.video_path = self.original_video_path
                self._proxy_path = None
                self._proxy_busy = False
                # Restore display dims from master
                if self.original_wh:
                    self.video_wh = self.original_wh
                if self._needs_proxy:
                    self._proxy_ok = False
                    self.proxy_line.visible = True
                    self.proxy_line.color = "#e57373"
                    wh = (
                        f"{self.original_wh[0]}×{self.original_wh[1]}"
                        if self.original_wh
                        else "oversize"
                    )
                    self.proxy_line.value = (
                        f"Source {wh} is above 1080p-class. "
                        "Enable Auto-downscale or export a smaller proxy before Generate."
                    )
                    self.dual_key_banner.visible = True
                else:
                    self._proxy_ok = True
                    self.proxy_line.visible = False
                    self.dual_key_banner.visible = False
                self.apply_key_gates()
                try:
                    self.page.update()
                except Exception:
                    pass

    async def _auto_downscale_async(self) -> None:
        """Run fal scale-video (or use cache) on the original source; swap Aleph path."""
        src = self.original_video_path
        if not src or not Path(src).is_file():
            self._proxy_busy = False
            self.apply_key_gates()
            return
        # Always use immutable master resolution for need/scale
        ow_oh = self.original_wh
        if not ow_oh:
            self._proxy_busy = False
            self.apply_key_gates()
            return
        from media_studio.secrets_store import has_fal_key

        need = needs_1080p_proxy(ow_oh[0], ow_oh[1])
        self._needs_proxy = bool(need.needs_scale)
        if not need.needs_scale:
            self._proxy_ok = True
            self._proxy_busy = False
            self.dual_key_banner.visible = False
            self.apply_key_gates()
            return

        if not has_fal_key():
            self._proxy_ok = False
            self._proxy_busy = False
            self.proxy_line.visible = True
            self.proxy_line.color = "#e57373"
            self.proxy_line.value = (
                f"Source {ow_oh[0]}×{ow_oh[1]} needs a 1080p proxy, "
                "but no FAL key is set (scale uses fal). Add FAL key in Settings, or "
                "export a smaller clip."
            )
            self.dual_key_banner.visible = True
            self._set_status(self.proxy_line.value, True)
            self.apply_key_gates()
            try:
                self.page.update()
            except Exception:
                pass
            return

        self._proxy_busy = True
        self._proxy_ok = False
        self.proxy_line.visible = True
        self.proxy_line.color = TEXT_MUTED
        self.proxy_line.value = (
            f"Scaling {ow_oh[0]}×{ow_oh[1]} → 1080p proxy "
            f"(fal · ~${SCALE_COST_USD:.2f})…"
        )
        self.dual_key_banner.visible = True
        self.apply_key_gates()
        try:
            self.page.update()
        except Exception:
            pass

        def on_progress(msg: str) -> None:
            self.proxy_line.value = msg
            try:
                self.page.update()
            except Exception:
                pass

        try:
            result = await asyncio.to_thread(
                scale_video_to_1080p,
                src,
                output_dir=self.state.output_dir,
                width=ow_oh[0],
                height=ow_oh[1],
                on_progress=on_progress,
            )
        except Exception as exc:
            self._proxy_ok = False
            self._proxy_busy = False
            self.proxy_line.color = "#e57373"
            self.proxy_line.value = (
                f"Scale failed: {exc}. Export a 1080p proxy manually before Generate."
            )
            self._set_status(self.proxy_line.value, True)
            self.apply_key_gates()
            try:
                self.page.update()
            except Exception:
                pass
            return

        if not result.ok or not result.path:
            self._proxy_ok = False
            self._proxy_busy = False
            self.proxy_line.color = "#e57373"
            self.proxy_line.value = (
                result.status
                or "Scale failed. Export a 1080p proxy manually before Generate."
            )
            self._set_status(self.proxy_line.value, True)
            self.apply_key_gates()
            try:
                self.page.update()
            except Exception:
                pass
            return

        self._proxy_path = result.path
        self.video_path = result.path
        self._proxy_ok = True
        self._proxy_busy = False
        self._scale_status = result.status
        self.proxy_line.color = TEXT
        self.proxy_line.value = result.status
        # Label: master + proxy dims; never overwrite original_wh
        name = Path(src).name
        parts = [name]
        if self.video_duration_s is not None:
            parts.append(f"{self.video_duration_s:.1f}s")
        if self.original_wh:
            parts.append(f"src {self.original_wh[0]}×{self.original_wh[1]}")
        if result.scaled_w and result.scaled_h:
            parts.append(f"proxy {result.scaled_w}×{result.scaled_h}")
            self.video_wh = (result.scaled_w, result.scaled_h)
        self.video_label.value = " · ".join(parts)
        poster, perr = _ensure_poster(result.path, self.state.output_dir)
        if poster:
            self._source_poster = poster
            self.src_thumb.src = poster
            self.src_thumb.visible = True
            self.src_thumb_ph.visible = False
            self._set_preview_mode(
                "source",
                image_src=poster,
                caption=(
                    f"1080p proxy · {result.scaled_w}×{result.scaled_h} "
                    f"(original {self.original_wh[0]}×{self.original_wh[1]} kept)"
                    if self.original_wh
                    else f"1080p proxy · {result.scaled_w}×{result.scaled_h}"
                ),
            )
        else:
            self._set_preview_mode(
                "empty",
                caption=f"Proxy ready but preview failed: {perr or 'unknown'}",
            )
        self.status.value = result.status
        self.status.color = TEXT_MUTED
        base = format_aleph_cost(self.video_duration_s)
        self.cost_text.value = f"{base} + {result.cost_label}"
        # Re-sample strip from proxy path (matches Aleph)
        self._strip_source_path = None
        self._schedule_filmstrip(result.path)
        self.apply_key_gates()
        try:
            self.page.update()
        except Exception:
            pass

    def add_keyframe(
        self,
        path: str,
        *,
        pin: str = "first",
        timestamp_s: float = 0.0,
        status: str | None = None,
        replace_index: int | None = None,
        slot_id: str | None = None,
    ) -> bool:
        try:
            p = Path(path)
            if not p.is_file():
                self._set_status(f"Keyframe missing: {path}", True)
                return False
            resolved = str(p.resolve())
        except OSError as exc:
            self._set_status(f"Keyframe error: {exc}", True)
            return False
        pin = pin if pin in ("first", "last", "timestamp") else "first"
        thumb = str(Path(resolved).resolve())
        ts = float(timestamp_s or 0.0)

        # Replace existing slot (Studio round-trip)
        if replace_index is not None and 0 <= replace_index < len(self.keyframes):
            kf = self.keyframes[replace_index]
            kf.image_path = thumb
            kf.thumb_src = thumb
            if pin:
                kf.pin = pin
            kf.timestamp_s = ts if pin == "timestamp" else kf.timestamp_s
            if slot_id:
                kf.slot_id = slot_id
            self._selected_kf = replace_index
            self._rebuild_kf_list()
            self._rebuild_filmstrip()
            pin_note = (
                f" · t={kf.timestamp_s:.2f}s"
                if kf.pin == "timestamp"
                else f" · {Path(thumb).name}"
            )
            self._set_preview_mode(
                "keyframe",
                image_src=thumb,
                caption=f"Keyframe #{replace_index + 1} · pin={kf.pin}{pin_note}",
            )
            self.status.value = status or (
                f"Updated keyframe #{replace_index + 1} · {Path(resolved).name}"
            )
            self.status.color = TEXT_MUTED
            return True

        if slot_id:
            for i, kf in enumerate(self.keyframes):
                if kf.slot_id == slot_id:
                    return self.add_keyframe(
                        path,
                        pin=pin or kf.pin,
                        timestamp_s=ts if pin == "timestamp" else kf.timestamp_s,
                        status=status,
                        replace_index=i,
                        slot_id=slot_id,
                    )

        if len(self.keyframes) >= ALEPH_MAX_KEYFRAMES:
            self._set_status(f"Max {ALEPH_MAX_KEYFRAMES} keyframes.", True)
            return False

        self.keyframes.append(
            _KeyframeSlot(
                image_path=thumb,
                pin=pin,
                timestamp_s=ts,
                thumb_src=thumb,
                slot_id=slot_id or uuid.uuid4().hex[:12],
            )
        )
        self._selected_kf = len(self.keyframes) - 1
        self._rebuild_kf_list()
        self._rebuild_filmstrip()
        pin_note = (
            f" · t={ts:.2f}s" if pin == "timestamp" else f" · {Path(thumb).name}"
        )
        self._set_preview_mode(
            "keyframe",
            image_src=thumb,
            caption=f"Keyframe #{len(self.keyframes)} · pin={pin}{pin_note}",
        )
        self.status.value = status or (
            f"Keyframe #{len(self.keyframes)} · {Path(resolved).name} · {pin}"
        )
        self.status.color = TEXT_MUTED
        return True

    def receive_keyframe(
        self,
        path: str,
        *,
        pin: str | None = None,
        timestamp_s: float | None = None,
        status: str | None = None,
        job_name: str | None = None,
    ) -> bool:
        """
        Accept a still from Studio / Creative Vision / Library as a keyframe.

        - With source video: replace round-trip slot, else selected keyframe,
          else pin at selected filmstrip time, else append. Other slots stay.
        - Without source video: stage as handoff still (attach video next).
        Never clears the source video.
        """
        try:
            p = Path(path)
            if not p.is_file():
                self._set_status(f"Keyframe missing: {path}", True)
                return False
            resolved = str(p.resolve())
        except OSError as exc:
            self._set_status(f"Keyframe error: {exc}", True)
            return False

        name_note = f" · {job_name}" if (job_name or "").strip() else ""

        # No source clip yet — stage still for pin after video load
        if not self.video_path and not self.original_video_path:
            self._handoff_still = resolved
            self._set_preview_mode(
                "keyframe",
                image_src=resolved,
                caption=f"Handoff still · load source video to pin as keyframe",
            )
            self.status.value = status or (
                f"Staged still for Frame Editor{name_note}: {Path(resolved).name}. "
                "Load a source video — it will pin as keyframe #1 (other slots empty)."
            )
            self.status.color = TEXT_MUTED
            try:
                self.page.update()
            except Exception:
                pass
            return True

        ctx = getattr(self.state, "frame_editor_return", None)

        if isinstance(ctx, dict) and ctx:
            slot_id = ctx.get("slot_id")
            idx = ctx.get("slot_index")
            ctx_pin = str(ctx.get("pin") or "first")
            ctx_ts = float(ctx.get("timestamp_s") or 0.0)
            use_pin = pin if pin in ("first", "last", "timestamp") else ctx_pin
            use_ts = (
                float(timestamp_s)
                if timestamp_s is not None
                else ctx_ts
            )
            # Prefer stable slot_id, then index
            if slot_id:
                for i, kf in enumerate(self.keyframes):
                    if kf.slot_id == slot_id:
                        ok = self.add_keyframe(
                            resolved,
                            pin=use_pin if use_pin in ("first", "last", "timestamp") else kf.pin,
                            timestamp_s=use_ts if use_pin == "timestamp" else kf.timestamp_s,
                            status=status
                            or f"→ keyframe #{i + 1} (same slot · {use_pin}){name_note}",
                            replace_index=i,
                            slot_id=slot_id,
                        )
                        self.state.frame_editor_return = None
                        return ok
            if isinstance(idx, int) and 0 <= idx < len(self.keyframes):
                kf = self.keyframes[idx]
                ok = self.add_keyframe(
                    resolved,
                    pin=use_pin if use_pin in ("first", "last", "timestamp") else kf.pin,
                    timestamp_s=use_ts if use_pin == "timestamp" else kf.timestamp_s,
                    status=status
                    or f"→ keyframe #{idx + 1} (same slot · {use_pin}){name_note}",
                    replace_index=idx,
                    slot_id=kf.slot_id,
                )
                self.state.frame_editor_return = None
                return ok
            # Origin slot gone — add as new with remembered pin/time
            ok = self.add_keyframe(
                resolved,
                pin=use_pin if use_pin in ("first", "last", "timestamp") else "first",
                timestamp_s=use_ts,
                status=status
                or (
                    f"→ new keyframe · pin={use_pin}"
                    + (f" · t={use_ts:.2f}s" if use_pin == "timestamp" else "")
                    + name_note
                ),
            )
            self.state.frame_editor_return = None
            return ok

        # Explicit pin/time from caller
        if pin in ("first", "last", "timestamp") or timestamp_s is not None:
            use_pin = pin if pin in ("first", "last", "timestamp") else "first"
            use_ts = float(timestamp_s or 0.0)
            return self.add_keyframe(
                resolved,
                pin=use_pin,
                timestamp_s=use_ts,
                status=status or f"Keyframe: {Path(resolved).name}{name_note}",
            )

        # Selected keyframe → replace that slot only
        if self._selected_kf is not None and 0 <= self._selected_kf < len(
            self.keyframes
        ):
            kf = self.keyframes[self._selected_kf]
            return self.add_keyframe(
                resolved,
                pin=kf.pin,
                timestamp_s=float(kf.timestamp_s),
                status=status
                or f"→ keyframe #{self._selected_kf + 1} (replaced){name_note}",
                replace_index=self._selected_kf,
                slot_id=kf.slot_id,
            )

        # Selected filmstrip time → pin timestamp (add or update same time)
        if self._selected_strip is not None and 0 <= self._selected_strip < len(
            self._strip_frames
        ):
            t = float(self._strip_frames[self._selected_strip].timestamp_s)
            for i, kf in enumerate(self.keyframes):
                if kf.pin == "timestamp" and abs(float(kf.timestamp_s) - t) < 0.06:
                    return self.add_keyframe(
                        resolved,
                        pin="timestamp",
                        timestamp_s=t,
                        status=status
                        or f"→ keyframe #{i + 1} @ {t:.2f}s{name_note}",
                        replace_index=i,
                        slot_id=kf.slot_id,
                    )
            return self.add_keyframe(
                resolved,
                pin="timestamp",
                timestamp_s=t,
                status=status
                or f"Keyframe @ {t:.2f}s: {Path(resolved).name}{name_note}",
            )

        # Append new slot
        return self.add_keyframe(
            resolved,
            pin="first",
            timestamp_s=0.0,
            status=status or f"Keyframe: {Path(resolved).name}{name_note}",
        )

    def load_image(self, path: str, *, status: str | None = None) -> bool:
        return self.receive_keyframe(path, status=status)

    # ----------------------------------------------------------- Send to ▾

    def _rebuild_send_menu(self) -> None:
        """Left-rail Send to ▾ for selected filmstrip / keyframe still."""
        from media_studio.flet_send_to import make_send_menu_button

        items = [
            ft.PopupMenuItem(
                content="Studio Image (edit frame)",
                on_click=self._send_frame_to_studio,
            ),
            ft.PopupMenuItem(),
            ft.PopupMenuItem(
                content="Creative Vision · Image → Image (source)",
                on_click=self._make_send_vision("i2i"),
            ),
            ft.PopupMenuItem(
                content="Creative Vision · Start frame",
                on_click=self._make_send_vision("start"),
            ),
            ft.PopupMenuItem(
                content="Creative Vision · End frame",
                on_click=self._make_send_vision("end"),
            ),
            ft.PopupMenuItem(
                content="Creative Vision · I2V source",
                on_click=self._make_send_vision("i2v"),
            ),
        ]
        btn = make_send_menu_button(
            items,
            tooltip=(
                "Send selected filmstrip / keyframe still to Studio Image or "
                "Creative Vision (I2I / Start / End / I2V). Source video stays here."
            ),
        )
        if btn is not None:
            self.send_host.content = btn
            self.send_host.visible = True
        else:
            self.send_host.visible = False

    def _rebuild_result_send_menu(self, path: str | None = None) -> None:
        """Result-row Send to ▾ — still from selection, or poster of Aleph result."""
        from media_studio.flet_send_to import make_send_menu_button

        items = [
            ft.PopupMenuItem(
                content="Studio Image (edit frame)",
                on_click=self._send_frame_to_studio,
            ),
            ft.PopupMenuItem(),
            ft.PopupMenuItem(
                content="Creative Vision · Image → Image (source)",
                on_click=self._make_send_vision("i2i"),
            ),
            ft.PopupMenuItem(
                content="Creative Vision · Start frame",
                on_click=self._make_send_vision("start"),
            ),
            ft.PopupMenuItem(
                content="Creative Vision · End frame",
                on_click=self._make_send_vision("end"),
            ),
            ft.PopupMenuItem(
                content="Creative Vision · I2V source",
                on_click=self._make_send_vision("i2v"),
            ),
        ]
        # Also allow sending Aleph result video as Studio Video source if present
        if path and Path(path).is_file():
            ext = Path(path).suffix.lower()
            if ext in {".mp4", ".mov", ".webm", ".m4v", ".avi", ".mkv"}:
                items.append(ft.PopupMenuItem())
                items.append(
                    ft.PopupMenuItem(
                        content="Studio Video (source clip)",
                        on_click=self._send_result_video(path),
                    )
                )
        btn = make_send_menu_button(
            items,
            tooltip="Send still plate to Studio / Creative Vision",
        )
        if btn is not None:
            self.result_send_host.content = btn
            self.result_send_host.visible = True
        else:
            self.result_send_host.visible = False

    def _send_result_video(self, path: str):
        from media_studio.flet_send_to import send_to_video_source

        return send_to_video_source(
            self.state,
            path,
            status_cb=lambda m: self._set_status(m, False),
        )

    def _make_send_vision(self, role: str):
        async def _click(_e: ft.ControlEvent) -> None:
            await self._send_still_to_vision(role)

        return _click

    async def _send_still_to_vision(self, role: str) -> None:
        """
        Resolve selected filmstrip / keyframe / result plate and send to Vision.
        Does not run Enhance. Preserves optional job label in status only.
        """
        still, pin, ts, slot_index, _slot_id = await self._resolve_edit_still()
        if not still or not Path(still).is_file():
            # Fall back: result poster / extract t=0 from Aleph result
            still = await self._resolve_result_still()
        if not still or not Path(still).is_file():
            self._set_status(
                "Select a filmstrip frame, keyframe, or generate a result first.",
                True,
            )
            return

        job_name = None
        if slot_index is not None:
            job_name = f"FE keyframe #{slot_index + 1}"
            if pin == "timestamp":
                job_name = f"FE t={ts:.2f}s"
        elif pin == "timestamp":
            job_name = f"FE t={ts:.2f}s"

        from media_studio.flet_send_to import send_to_vision

        # Invoke the same handler used by menus (opens Vision + loads slot)
        handler = send_to_vision(
            self.state,
            still,
            role=role,
            job_name=job_name,
            status_cb=lambda m: self._set_status(m, False),
        )
        await handler(None)  # type: ignore[arg-type]
        try:
            self.page.update()
        except Exception:
            pass

    async def _resolve_result_still(self) -> str | None:
        """Still plate from Aleph result: selected strip, then poster, then t=0."""
        # Selected strip already covered by _resolve_edit_still when strip is
        # sampled from the result path after generate.
        if self._preview_img_src and Path(self._preview_img_src).is_file():
            ext = Path(self._preview_img_src).suffix.lower()
            if ext in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}:
                return str(Path(self._preview_img_src).resolve())
        if self._source_poster and Path(self._source_poster).is_file():
            # Prefer poster only when no video result; if result is video extract
            pass
        result = self._result_path
        if result and Path(result).is_file():
            ext = Path(result).suffix.lower()
            if ext in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}:
                return str(Path(result).resolve())
            if ext in {".mp4", ".mov", ".webm", ".m4v", ".avi", ".mkv"}:
                full, _ = await asyncio.to_thread(
                    _extract_still,
                    result,
                    0.0,
                    self.state.output_dir,
                    tag="fe_result_send",
                )
                if full:
                    return full
                poster, _ = await asyncio.to_thread(
                    _ensure_poster, result, self.state.output_dir
                )
                if poster:
                    return poster
        return None

    async def _send_frame_to_studio(self, _e: ft.ControlEvent) -> None:
        """
        Open selected filmstrip frame / active keyframe in Studio Image.

        Records round-trip context so “Send to Frame Editor as keyframe”
        updates the same slot. Source video stays loaded here.
        """
        if not self.video_path and not self.original_video_path:
            # Allow sending handoff still to Studio even without video
            still = self._handoff_still
            if still and Path(still).is_file():
                iv = getattr(self.state, "image_view", None)
                if iv is not None and hasattr(iv, "load_source_path"):
                    iv.load_source_path(still, status="Frame Editor handoff still")
                switch = getattr(self.state, "switch_to_image", None)
                if switch:
                    switch()
                self.status.value = f"Sent handoff still to Studio: {Path(still).name}"
                self.status.color = TEXT_MUTED
                try:
                    self.page.update()
                except Exception:
                    pass
                return
            self._set_status(
                "Load a source video (or stage a still) before sending to Studio.",
                True,
            )
            return
        still, pin, ts, slot_index, slot_id = await self._resolve_edit_still()
        if not still or not Path(still).is_file():
            still = await self._resolve_result_still()
        if not still or not Path(still).is_file():
            self._set_status(
                "Select a filmstrip frame or keyframe first, then Send to ▾.",
                True,
            )
            return

        # Ensure a keyframe slot exists so the return has somewhere to land
        if slot_index is None and (self.video_path or self.original_video_path):
            if len(self.keyframes) >= ALEPH_MAX_KEYFRAMES:
                self._set_status(
                    f"Max {ALEPH_MAX_KEYFRAMES} keyframes — select an existing "
                    "slot to edit in Studio, or remove one first.",
                    True,
                )
                return
            ok = self.add_keyframe(
                still,
                pin=pin,
                timestamp_s=ts,
                status=f"Reserved keyframe for Studio edit · pin={pin}"
                + (f" · t={ts:.2f}s" if pin == "timestamp" else ""),
            )
            if not ok:
                return
            slot_index = self._selected_kf
            if slot_index is not None and 0 <= slot_index < len(self.keyframes):
                slot_id = self.keyframes[slot_index].slot_id
                pin = self.keyframes[slot_index].pin
                ts = float(self.keyframes[slot_index].timestamp_s)

        if slot_index is not None and 0 <= slot_index < len(self.keyframes):
            kf = self.keyframes[slot_index]
            slot_id = kf.slot_id
            pin = kf.pin
            ts = float(kf.timestamp_s)

        # Remember where to pin the edited still when user returns
        self.state.frame_editor_return = {
            "slot_id": slot_id,
            "slot_index": slot_index,
            "pin": pin,
            "timestamp_s": ts,
            "source_video": self.original_video_path or self.video_path,
        }

        iv = getattr(self.state, "image_view", None)
        loaded = False
        if iv is not None and hasattr(iv, "load_source_path"):
            try:
                note = "Frame Editor frame"
                if pin == "timestamp":
                    note = f"Frame Editor · t={ts:.2f}s"
                elif slot_index is not None:
                    note = f"Frame Editor · keyframe #{slot_index + 1}"
                loaded = bool(iv.load_source_path(still, status=note))
            except Exception as exc:
                self._set_status(f"Studio load failed: {exc}", True)
                return

        switch = getattr(self.state, "switch_to_image", None)
        if switch:
            try:
                switch()
            except Exception:
                pass

        if loaded or switch:
            self.status.value = (
                f"Sent to Studio Image · keyframe #{(slot_index or 0) + 1} "
                f"({pin}"
                + (f" @ {ts:.2f}s" if pin == "timestamp" else "")
                + "). Edit freely — Send to Frame Editor · keyframe returns here."
            )
            self.status.color = TEXT_MUTED
        else:
            self._set_status("Could not open Studio Image.", True)
        try:
            self.page.update()
        except Exception:
            pass

    async def _resolve_edit_still(
        self,
    ) -> tuple[str | None, str, float, int | None, str | None]:
        """
        Still path + pin/time/slot for Studio send.

        Priority: active keyframe → selected strip (full extract) → preview src.
        Returns (path, pin, timestamp_s, slot_index, slot_id).
        """
        # 1) Active keyframe
        if self._selected_kf is not None and 0 <= self._selected_kf < len(
            self.keyframes
        ):
            kf = self.keyframes[self._selected_kf]
            path = kf.thumb_src or kf.image_path
            if path and Path(path).is_file():
                return (
                    str(Path(path).resolve()),
                    kf.pin,
                    float(kf.timestamp_s),
                    self._selected_kf,
                    kf.slot_id,
                )

        # 2) Selected filmstrip frame
        if self._selected_strip is not None and 0 <= self._selected_strip < len(
            self._strip_frames
        ):
            fr = self._strip_frames[self._selected_strip]
            t = float(fr.timestamp_s)
            still_path = fr.path
            src_vid = self.video_path or self.original_video_path
            if src_vid and Path(src_vid).is_file():
                full, _ = await asyncio.to_thread(
                    _extract_still,
                    src_vid,
                    t,
                    self.state.output_dir,
                    tag="studio_send",
                )
                if full:
                    still_path = full
            # Match existing keyframe at this time
            for i, kf in enumerate(self.keyframes):
                if kf.pin == "timestamp" and abs(float(kf.timestamp_s) - t) < 0.06:
                    return (
                        str(Path(still_path).resolve())
                        if Path(still_path).is_file()
                        else (kf.thumb_src or kf.image_path),
                        kf.pin,
                        float(kf.timestamp_s),
                        i,
                        kf.slot_id,
                    )
            if still_path and Path(still_path).is_file():
                return (
                    str(Path(still_path).resolve()),
                    "timestamp",
                    t,
                    None,
                    None,
                )

        # 3) Current preview image
        if self._preview_img_src and Path(self._preview_img_src).is_file():
            pin = "first"
            ts = 0.0
            try:
                ts = float(self.extract_time.value or 0)
                if ts > 0:
                    pin = "timestamp"
            except (TypeError, ValueError):
                pass
            return (
                str(Path(self._preview_img_src).resolve()),
                pin,
                ts,
                None,
                None,
            )

        return None, "first", 0.0, None, None

    def _on_prev_video(self, path: str) -> None:
        self.load_source(path, status=f"Previous: {Path(path).name}")
        try:
            self.page.update()
        except Exception:
            pass

    def _on_edit_intent(self, intent_id: str) -> None:
        """
        Edit intent helper — only changes UI defaults / prompt hints.

        Aleph API still receives frameImages with first|last|timestamp + positivePrompt.
        """
        if intent_id not in (_INTENT_APPLY, _INTENT_TRANSITION, _INTENT_CUSTOM):
            intent_id = _INTENT_APPLY
        self._edit_intent = intent_id
        cur = (self.prompt.value or "").strip()
        stock = {
            _PROMPT_APPLY.strip(),
            _PROMPT_TRANSITION.strip(),
            "",
        }

        if intent_id == _INTENT_TRANSITION:
            self.intent_hint.value = (
                "Transition: pin look A at first (or early time) and look B at last "
                "(or late time). Aleph interpolates between them. "
                "Day→night: day still @ first, night still @ last."
            )
            try:
                self.default_pin.value = "first"
            except Exception:
                pass
            if cur in stock or "Apply the edited look" in cur:
                self.prompt.value = _PROMPT_TRANSITION
            self.status.value = (
                "Transition mode — add two keyframes (first + last recommended)."
            )
            self.status.color = TEXT_MUTED
        elif intent_id == _INTENT_CUSTOM:
            self.intent_hint.value = (
                "Custom timestamps: pin up to 5 stills at exact times "
                "(filmstrip → Pin frame, or Extract at time). "
                "Order follows the timeline."
            )
            try:
                self.default_pin.value = "timestamp"
            except Exception:
                pass
        else:
            self.intent_hint.value = (
                "One keyframe ≈ apply that look through the whole clip. "
                "First + last (or two timestamps) ≈ transition between looks."
            )
            try:
                self.default_pin.value = "first"
            except Exception:
                pass
            if cur in stock or "Transition the look" in cur:
                self.prompt.value = _PROMPT_APPLY
        try:
            self.page.update()
        except Exception:
            pass

    def _pin_label(self, kf: _KeyframeSlot) -> str:
        """Human position for a keyframe: first / last / 1.61s."""
        if kf.pin == "last":
            return "last"
        if kf.pin == "timestamp":
            return f"{float(kf.timestamp_s):.2f}s"
        return "first"

    def _on_resolve_media(self, path: str) -> None:
        """
        From Resolve strip: clip → source video (proxy path); still → keyframe pin.
        """
        try:
            p = Path(path)
            if not p.is_file():
                self._set_status(f"Missing: {path}", True)
                return
            resolved = str(p.resolve())
        except OSError as exc:
            self._set_status(f"Resolve load error: {exc}", True)
            return
        is_video = p.suffix.lower() in {
            ".mp4",
            ".mov",
            ".webm",
            ".m4v",
            ".avi",
            ".mkv",
        }
        if is_video:
            self.load_source(resolved, status=f"From Resolve: {p.name}")
        else:
            pin = "first"
            try:
                pin = str(self.default_pin.value or "first")
            except Exception:
                pin = "first"
            if pin not in ("first", "last", "timestamp"):
                pin = "first"
            self.add_keyframe(
                resolved,
                pin=pin,
                timestamp_s=0.0,
                status=f"From Resolve pin: {p.name}",
            )
        try:
            self.resolve_strip.refresh()
        except Exception:
            pass
        try:
            self.page.update()
        except Exception:
            pass

    def refresh_resolve_strip(self) -> None:
        """Reload From Resolve thumbs (after handoff / Import from Resolve)."""
        try:
            self.resolve_strip.refresh()
        except Exception:
            pass

    # ----------------------------------------------------------- keyframe list

    def _rebuild_kf_list(self) -> None:
        rows: list[ft.Control] = []
        for i, kf in enumerate(self.keyframes):
            idx = i
            selected = self._selected_kf == i

            def make_remove(ii: int):
                async def _rm(_e: ft.ControlEvent) -> None:
                    if 0 <= ii < len(self.keyframes):
                        self.keyframes.pop(ii)
                        if self._selected_kf is not None:
                            if self._selected_kf == ii:
                                self._selected_kf = None
                                if self._source_poster:
                                    self._set_preview_mode(
                                        "source",
                                        image_src=self._source_poster,
                                        caption="Source",
                                    )
                                else:
                                    self._set_preview_mode("empty")
                            elif self._selected_kf > ii:
                                self._selected_kf -= 1
                        self._rebuild_kf_list()
                        self._rebuild_filmstrip()
                        try:
                            self.page.update()
                        except Exception:
                            pass

                return _rm

            def make_select(ii: int):
                async def _sel(_e: ft.ControlEvent) -> None:
                    if 0 <= ii < len(self.keyframes):
                        self._selected_kf = ii
                        k = self.keyframes[ii]
                        self._set_preview_mode(
                            "keyframe",
                            image_src=k.thumb_src or k.image_path,
                            caption=(
                                f"Keyframe #{ii + 1} · {self._pin_label(k)} · "
                                f"{Path(k.image_path).name}"
                            ),
                        )
                        # Mirror selection onto filmstrip when pin is a timestamp
                        self._selected_strip = None
                        if k.pin == "timestamp" and self._strip_frames:
                            for si, fr in enumerate(self._strip_frames):
                                if abs(fr.timestamp_s - float(k.timestamp_s)) < 0.08:
                                    self._selected_strip = si
                                    break
                        self._rebuild_kf_list()
                        self._rebuild_filmstrip()
                        try:
                            self.page.update()
                        except Exception:
                            pass

                return _sel

            ts_field = ft.TextField(
                label="t",
                value=str(kf.timestamp_s),
                dense=True,
                width=52,
                filled=True,
                fill_color=PANEL_ELEVATED,
                border_color=BORDER,
                color=TEXT,
                text_size=11,
                content_padding=4,
                visible=kf.pin == "timestamp",
            )

            async def on_pin(
                e: ft.ControlEvent, ii: int = idx, ts: ft.TextField = ts_field
            ):
                if 0 <= ii < len(self.keyframes):
                    val = str(getattr(e.control, "value", None) or "first")
                    self.keyframes[ii].pin = val
                    ts.visible = val == "timestamp"
                    try:
                        self.page.update()
                    except Exception:
                        pass

            async def on_ts(e: ft.ControlEvent, ii: int = idx):
                if 0 <= ii < len(self.keyframes):
                    try:
                        self.keyframes[ii].timestamp_s = float(
                            getattr(e.control, "value", 0) or 0
                        )
                    except (TypeError, ValueError):
                        self.keyframes[ii].timestamp_s = 0.0

            pin_dd = styled_dropdown(
                label_text="Pin",
                options=["first", "last", "timestamp"],
                value=kf.pin,
                on_select=on_pin,
                expand=True,
            )
            ts_field.on_change = on_ts

            thumb_src = kf.thumb_src or kf.image_path
            pin_note = self._pin_label(kf)
            name = Path(kf.image_path).name
            if len(name) > 28:
                name = name[:25] + "…"
            # Always show position + pinned image name (not only when selected)
            detail = ft.Text(
                f"#{i + 1} · {pin_note} · {name}",
                size=10,
                color=TEXT if selected else TEXT_MUTED,
                max_lines=1,
                overflow=ft.TextOverflow.ELLIPSIS,
            )
            pos_badge = ft.Container(
                content=ft.Text(
                    pin_note,
                    size=10,
                    color=TEXT,
                    weight=ft.FontWeight.W_700,
                ),
                bgcolor=ACCENT if selected else "#2a3140",
                border_radius=4,
                padding=ft.Padding.symmetric(horizontal=6, vertical=2),
                tooltip=f"Pinned at {pin_note}",
            )
            rows.append(
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Row(
                                [
                                    ft.Container(
                                        content=ft.Image(
                                            src=thumb_src,
                                            width=44,
                                            height=44,
                                            fit=ft.BoxFit.COVER,
                                            border_radius=4,
                                        ),
                                        on_click=make_select(idx),
                                        ink=True,
                                        tooltip="Show larger in preview",
                                    ),
                                    pos_badge,
                                    pin_dd,
                                    ts_field,
                                    ft.IconButton(
                                        icon=ft.Icons.CLOSE,
                                        icon_size=16,
                                        icon_color=TEXT_MUTED,
                                        tooltip="Remove",
                                        on_click=make_remove(idx),
                                        style=ft.ButtonStyle(padding=2),
                                    ),
                                ],
                                spacing=4,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                            detail,
                        ],
                        spacing=2,
                        tight=True,
                    ),
                    bgcolor=PANEL_ELEVATED if not selected else "#1e2430",
                    border=ft.Border.all(
                        2 if selected else 1, ACCENT if selected else BORDER
                    ),
                    border_radius=6,
                    padding=5,
                )
            )

        if not rows:
            rows = [
                ft.Column(
                    [
                        ft.Text(
                            "No keyframes yet — extract a frame, Pin filmstrip, or upload a still.",
                            size=FONT_SM,
                            color=TEXT_MUTED,
                        ),
                        ft.Text(
                            "Day→night: pin day at first, night at last, then Generate",
                            size=11,
                            color=TEXT_MUTED,
                        ),
                    ],
                    spacing=4,
                    tight=True,
                )
            ]
        self.kf_host.controls = rows

    # ---------------------------------------------------------------- pickers

    async def _pick_video(self, e: ft.ControlEvent) -> None:
        try:
            files = await pick_video(
                self.page, dialog_title="Source video for Frame Editor"
            )
        except Exception as exc:
            self._set_status(f"Picker error: {exc}", True)
            return
        if not files or not files[0].path:
            return
        self.load_source(files[0].path)
        try:
            self.page.update()
        except Exception:
            pass

    async def _extract_frame(self, e: ft.ControlEvent) -> None:
        if not self.video_path or not Path(self.video_path).is_file():
            self._set_status("Upload a source video first.", True)
            return
        try:
            t = float(self.extract_time.value or 0)
        except (TypeError, ValueError):
            t = 0.0
        if self.video_duration_s and t > self.video_duration_s:
            t = max(0.0, self.video_duration_s - 0.05)
            self.extract_time.value = f"{t:.2f}"
        try:
            # Extract still via OpenCV → absolute PNG under _aleph_keyframes
            still, err = await asyncio.to_thread(
                _extract_still,
                self.video_path,
                t,
                self.state.output_dir,
                tag="kf",
            )
            if not still:
                self._set_status(
                    f"Extract failed at t={t:.2f}s — {err or 'could not decode that frame.'}",
                    True,
                )
                try:
                    self.page.update()
                except Exception:
                    pass
                return
            pin = (self.default_pin.value or "first").lower()
            if pin == "timestamp":
                self.add_keyframe(still, pin="timestamp", timestamp_s=t)
            else:
                self.add_keyframe(
                    still, pin=pin if pin in ("first", "last") else "first"
                )
        except Exception as exc:
            self._set_status(f"Extract failed: {exc}", True)
        try:
            self.page.update()
        except Exception:
            pass

    async def _upload_keyframe(self, e: ft.ControlEvent) -> None:
        try:
            files = await pick_image(
                self.page, dialog_title="Keyframe still (edited frame)"
            )
        except Exception as exc:
            self._set_status(f"Picker error: {exc}", True)
            return
        if not files or not files[0].path:
            return
        pin = (self.default_pin.value or "first").lower()
        ts = 0.0
        if pin == "timestamp":
            try:
                ts = float(self.extract_time.value or 0)
            except (TypeError, ValueError):
                ts = 0.0
        self.add_keyframe(
            files[0].path,
            pin=pin if pin in ("first", "last", "timestamp") else "first",
            timestamp_s=ts,
        )
        try:
            self.page.update()
        except Exception:
            pass

    # --------------------------------------------------------------- enhance

    async def _on_enhance(self, e: ft.ControlEvent) -> None:
        img = None
        if self._selected_kf is not None and 0 <= self._selected_kf < len(self.keyframes):
            img = self.keyframes[self._selected_kf].image_path
        elif self.keyframes:
            img = self.keyframes[0].image_path

        def _extra() -> dict[str, Any]:
            pins = [self._pin_label(k) for k in self.keyframes]
            intent = getattr(self, "_edit_intent", _INTENT_APPLY)
            body = (self.prompt.value or "").lower()
            wants_transition = (
                intent == _INTENT_TRANSITION
                or "transition" in body
                or "day to night" in body
                or "day-to-night" in body
                or "day→night" in body
                or "dusk" in body
                or "nightfall" in body
            )
            if wants_transition:
                guidance = (
                    "Rewrite for Runway Aleph 2.0 dual-anchor transition. "
                    "Describe the change from the first keyframe look to the last "
                    "(e.g. daylight → night / golden hour). "
                    "State that the look interpolates over time between the two "
                    "guided frames. "
                    "Name ONLY what changes (lighting, grade, sky, time of day). "
                    "Explicitly keep camera motion, framing, architecture, "
                    "people/object motion, and composition locked to the source. "
                    "Do not invent API parameters — only positive change language."
                )
            else:
                guidance = (
                    "Rewrite for Runway Aleph 2.0. Lead with remove/change/replace. "
                    "Name only what changes; end with keep motion, framing, lighting, "
                    "architecture, and everything else locked to the source."
                )
            return {
                "workspace": "frame_editor",
                "edit_intent": intent,
                "guidance": guidance,
                "keyframe_count": len(self.keyframes),
                "keyframe_pins": pins,
                "transition": wants_transition,
            }

        await run_prompt_enhance(
            page=self.page,
            state=self.state,
            prompt_field=self.prompt,
            get_model=lambda: "Aleph 2.0",
            get_image=lambda: img,
            get_video=lambda: self.video_path,
            get_extra_context=_extra,
            status_ctrl=self.status,
            job_progress=self.job_progress,
            enhance_btn=self.btn_enhance,
            busy_controls=[self.btn_generate],
            context_label="Aleph prompt",
            allow_empty_with_context=True,
        )
        self.apply_key_gates()
        try:
            self.page.update()
        except Exception:
            pass

    # ---------------------------------------------------------------- generate

    async def _run(self, e: ft.ControlEvent) -> None:
        if self.state.is_busy("frame_editor"):
            return
        if not has_runware_key():
            self._set_status(
                "Runware / Aleph key required — open Settings. fal alone is not enough.",
                True,
            )
            return
        if not self.video_path:
            self._set_status("Upload a source video first.", True)
            return
        if self._needs_proxy and not self._proxy_ok:
            self._set_status(
                "Source is above 1080p-class and no proxy is ready. "
                "Wait for auto-downscale, enable Auto-downscale (needs FAL key), "
                "or load a smaller clip.",
                True,
            )
            return

        kfs = [
            AlephKeyframe(
                image_path=k.image_path,
                pin=k.pin if k.pin in ("first", "last", "timestamp") else "first",  # type: ignore[arg-type]
                timestamp_s=k.timestamp_s,
            )
            for k in self.keyframes
        ]

        # Soft guidance for transition intent (do not invent API fields)
        if getattr(self, "_edit_intent", _INTENT_APPLY) == _INTENT_TRANSITION:
            pins = {k.pin for k in self.keyframes}
            if len(self.keyframes) < 2:
                self._set_status(
                    "Transition works best with two keyframes "
                    "(e.g. day @ first + night @ last). Add another still, or Generate anyway.",
                    True,
                )
                # still allow run — user may continue
            elif not (
                ("first" in pins and "last" in pins)
                or sum(1 for k in self.keyframes if k.pin == "timestamp") >= 2
                or ("first" in pins and any(k.pin == "timestamp" for k in self.keyframes))
                or ("last" in pins and any(k.pin == "timestamp" for k in self.keyframes))
            ):
                self.status.value = (
                    "Tip: use first+last (or two timestamps) so Aleph can interpolate."
                )
                self.status.color = TEXT_MUTED

        if not self.state.try_busy("frame_editor"):
            return
        self.btn_generate.disabled = True
        self._refresh_cost()
        try:
            self.job_progress.control.visible = True
        except Exception:
            pass
        self.job_progress.start("Uploading to Runware…", self.page)
        self.status.value = "Aleph 2.0 running…"
        self.status.color = TEXT_MUTED
        self._set_preview_mode("progress", caption="Aleph is running…")
        self.page.update()

        def on_progress(msg: str) -> None:
            self.job_progress.set_message(classify_progress(msg), self.page)

        try:
            from media_studio.job_context import to_thread_with_job

            result = await to_thread_with_job(
                self.state,
                run_aleph_keyframe_edit,
                video_path=self.video_path,
                prompt=self.prompt.value,
                keyframes=kfs,
                output_dir=self.state.output_dir,
                on_progress=on_progress,
            )
            self.cost_text.value = result.cost_label or format_aleph_cost(
                self.video_duration_s
            )
            if result.ok and result.path:
                self._result_path = result.path
                show_result_actions(self.btn_folder, self.btn_resolve, visible=True)
                try:
                    self._rebuild_result_send_menu(result.path)
                except Exception:
                    pass
                done = result.status or "OK"
                self.job_progress.finish_ok(done, self.page)
                self.status.value = done
                self.status.color = TEXT_MUTED
                self._set_preview_mode(
                    "result",
                    video_path=result.path,
                    caption=f"Result · {Path(result.path).name}",
                )
            else:
                err = result.status or "Failed."
                self.job_progress.finish_error(err, self.page)
                self._set_status(err, True)
                # Restore source preview
                if self._source_poster:
                    self._set_preview_mode(
                        "source", image_src=self._source_poster, caption="Source"
                    )
                else:
                    self._set_preview_mode("empty")
        except Exception as exc:
            self.job_progress.finish_error(f"Error: {exc}", self.page)
            self._set_status(f"Error: {exc}", True)
            traceback.print_exc()
            if self._source_poster:
                self._set_preview_mode(
                    "source", image_src=self._source_poster, caption="Source"
                )
        finally:
            self.state.clear_busy("frame_editor")
            self.apply_key_gates()
            try:
                # Collapse progress chrome after job so footer stays compact
                if not self.job_progress.active:
                    pass
            except Exception:
                pass
            self.page.update()


# Back-compat
AlephKeyframeCard = FrameEditorView
