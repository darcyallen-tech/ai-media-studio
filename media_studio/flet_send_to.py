"""
Shared Send-to destination matrix (Phase C).

One logical menu across Library, Tools results, Creative Vision, etc.
Destinations appear only when the media type allows them.

Nested layout (desktop Flet MenuBar / SubmenuButton flyouts):
  Studio Image · Studio Video · Region · Director ▶ · Creative Vision ▶ ·
  Frame Editor · Tools ▶ · Motion Sync ▶ · Resolve
Director / Creative Vision / Tools / Motion Sync open a flyout to the right.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

import flet as ft

from media_studio.flet_theme import BORDER, FONT_SM, PANEL_ELEVATED, TEXT, TEXT_MUTED

if TYPE_CHECKING:
    pass

# Stable tool lists (label, tool_id)
_IMAGE_TOOLS: list[tuple[str, str]] = [
    ("Upscale", "upscale"),
    ("Object Remove", "cleanup"),
    ("Sky / Weather", "sky"),
    ("Dehaze", "dehaze"),
    ("Sharpen / Restore", "restore"),
    ("Inpaint (freehand)", "inpaint"),
    ("Blown Out", "blown_out"),
    ("Mirror / Glass", "mirror"),
    ("Amenity On", "amenity"),
    ("Season / Curb", "season"),
    ("Match Look", "match_look"),
    ("Re-Aspect", "reaspect"),
]

_VIDEO_TOOLS: list[tuple[str, str]] = [
    ("Upscale (video)", "upscale"),
    ("Denoise / Clean (video)", "denoise"),
    ("Slow Mo / Interpolate", "interpolate"),
    ("Object Remove (video)", "cleanup"),
    ("Sky / Weather (video)", "sky"),
    ("Mirror / Glass (video)", "mirror"),
    ("Amenity On (video)", "amenity"),
    ("Sharpen / Restore (video)", "restore"),
    ("Re-Aspect (video)", "reaspect"),
]


def _item(label: str, handler: Callable) -> ft.MenuItemButton:
    """Leaf menu entry (cascading MenuBar / SubmenuButton)."""
    return ft.MenuItemButton(
        content=ft.Text(label, size=FONT_SM, color=TEXT),
        on_click=handler,
        style=ft.ButtonStyle(color=TEXT),
    )


def _submenu(label: str, children: list[ft.Control]) -> ft.SubmenuButton:
    """Flyout that opens to the right (Director / Creative Vision / Tools)."""
    return ft.SubmenuButton(
        content=ft.Text(label, size=FONT_SM, color=TEXT),
        trailing=ft.Icon(ft.Icons.ARROW_RIGHT, size=16, color=TEXT_MUTED),
        controls=list(children),
        style=ft.ButtonStyle(color=TEXT),
        menu_style=ft.MenuStyle(
            bgcolor=PANEL_ELEVATED,
            elevation=4,
            side=ft.BorderSide(1, BORDER),
            padding=ft.Padding.symmetric(horizontal=4, vertical=4),
        ),
    )


# ---------------------------------------------------------------------------
# Handlers (shared)
# ---------------------------------------------------------------------------


def send_to_image(state: Any, path: str, *, status_cb: Callable[[str], None] | None = None) -> Callable:
    async def _click(_e: ft.ControlEvent) -> None:
        iv = getattr(state, "image_view", None)
        if iv is not None and hasattr(iv, "load_source_path"):
            iv.load_source_path(path, status=f"Send → Image: {Path(path).name}")
        switch = getattr(state, "switch_to_image", None)
        if switch:
            switch()
        if status_cb:
            status_cb(f"Sent to Studio Image: {Path(path).name}")

    return _click


def send_to_video_ref(state: Any, path: str, *, status_cb: Callable[[str], None] | None = None) -> Callable:
    async def _click(_e: ft.ControlEvent) -> None:
        state.video_ref_path = str(Path(path).resolve())
        vv = getattr(state, "video_view", None)
        if vv is not None:
            if hasattr(vv, "open_received"):
                vv.open_received(
                    ref_path=state.video_ref_path,
                    scenario_label=getattr(state, "scenario_label", None),
                )
            elif hasattr(vv, "receive_from_image"):
                vv.receive_from_image(
                    ref_path=state.video_ref_path,
                    scenario_label=getattr(state, "scenario_label", None),
                )
            elif hasattr(vv, "sync_from_state"):
                vv.sync_from_state()
        switch = getattr(state, "switch_to_video", None)
        if switch:
            switch()
        if status_cb:
            status_cb(f"Sent to Studio Video (ref): {Path(path).name}")

    return _click


def send_to_video_source(state: Any, path: str, *, status_cb: Callable[[str], None] | None = None) -> Callable:
    async def _click(_e: ft.ControlEvent) -> None:
        vv = getattr(state, "video_view", None)
        if vv is not None and hasattr(vv, "load_source_video"):
            vv.load_source_video(
                path,
                clip_name=Path(path).name,
                status=f"Send → Video: {Path(path).name}",
            )
        else:
            state.video_source_path = str(Path(path).resolve())
            if vv is not None and hasattr(vv, "sync_from_state"):
                vv.sync_from_state()
        switch = getattr(state, "switch_to_video", None)
        if switch:
            switch()
        if status_cb:
            status_cb(f"Sent to Studio Video (source): {Path(path).name}")

    return _click


def send_to_region(state: Any, path: str, *, status_cb: Callable[[str], None] | None = None) -> Callable:
    async def _click(_e: ft.ControlEvent) -> None:
        iv = getattr(state, "image_view", None)
        if iv is not None and hasattr(iv, "open_region_with_image"):
            iv.open_region_with_image(path)
        elif iv is not None and hasattr(iv, "load_source_path"):
            iv.load_source_path(path, status=f"Region ← {Path(path).name}")
            if hasattr(iv, "set_edit_mode"):
                try:
                    iv.set_edit_mode("region")
                except Exception:
                    pass
        switch = getattr(state, "switch_to_image", None)
        if switch:
            try:
                switch(modality="region")
            except TypeError:
                switch()
        if status_cb:
            status_cb(f"Sent to Region edit: {Path(path).name}")

    return _click


def send_to_tool(
    state: Any,
    tool_id: str,
    path: str,
    *,
    as_video: bool,
    status_cb: Callable[[str], None] | None = None,
) -> Callable:
    async def _click(_e: ft.ControlEvent) -> None:
        tv = getattr(state, "tools_view", None)
        if tv is not None and hasattr(tv, "receive_media"):
            tv.receive_media(tool_id, path, as_video=as_video)
        switch = getattr(state, "switch_to_tools", None)
        if switch:
            switch(tool_id)
        if status_cb:
            status_cb(f"Sent to Tools → {tool_id}: {Path(path).name}")

    return _click


def send_to_motion_sync(
    state: Any,
    path: str,
    *,
    role: str,
    status_cb: Callable[[str], None] | None = None,
) -> Callable:
    """
    Send media into Motion Sync.

    role:
      - ``character`` — still → character / subject slot
      - ``motion`` — video → motion reference (driving clip) slot
    Switches to the Motion Sync tab and highlights the target slot.
    """

    async def _click(_e: ft.ControlEvent) -> None:
        mv = getattr(state, "motion_sync_view", None)
        role_key = (role or "").strip().lower()
        ok = False
        if mv is not None:
            if role_key in ("character", "char", "still", "subject"):
                if hasattr(mv, "receive_character"):
                    ok = bool(mv.receive_character(path))
                elif hasattr(mv, "_set_character"):
                    ok = bool(mv._set_character(path))
            elif role_key in ("motion", "motion_ref", "driving", "video"):
                if hasattr(mv, "receive_motion"):
                    ok = bool(mv.receive_motion(path))
                elif hasattr(mv, "_set_motion"):
                    ok = bool(mv._set_motion(path))
        switch = getattr(state, "switch_to_motion_sync", None)
        if switch:
            switch()
        if status_cb:
            slot = (
                "Character"
                if role_key in ("character", "char", "still", "subject")
                else "Motion reference"
            )
            name = Path(path).name
            if ok:
                status_cb(f"Sent to Motion Sync → {slot}: {name}")
            else:
                status_cb(f"Motion Sync → {slot}: could not load {name}")

    return _click


def send_to_frame_editor(
    state: Any,
    path: str,
    *,
    as_video: bool = False,
    pin: str | None = None,
    timestamp_s: float | None = None,
    job_name: str | None = None,
    status_cb: Callable[[str], None] | None = None,
) -> Callable:
    """
    Send media to Frame Editor.

    Stills: pin as keyframe when a source video is loaded; otherwise stage as a
    handoff still (load video next). Never wipes other keyframes unless the FE
    round-trip context or selected-slot replace path applies.
    """

    async def _click(_e: ft.ControlEvent) -> None:
        switch = getattr(state, "switch_to_frame_editor", None)
        if switch:
            if as_video:
                switch(video_path=path)
            else:
                try:
                    switch(
                        keyframe_path=path,
                        pin=pin,
                        timestamp_s=timestamp_s,
                        job_name=job_name,
                    )
                except TypeError:
                    switch(keyframe_path=path)
        else:
            fe = getattr(state, "frame_editor_view", None)
            if fe is not None:
                if as_video and hasattr(fe, "load_source"):
                    fe.load_source(path)
                elif hasattr(fe, "receive_keyframe"):
                    fe.receive_keyframe(
                        path,
                        pin=pin,
                        timestamp_s=timestamp_s,
                        job_name=job_name,
                    )
        kind = "source video" if as_video else "keyframe"
        name_note = f" · {job_name}" if job_name else ""
        if status_cb:
            status_cb(
                f"Sent to Frame Editor ({kind}){name_note}: {Path(path).name}"
            )

    return _click


def send_to_vision(
    state: Any,
    path: str,
    *,
    role: str = "start",
    as_video: bool = False,
    as_end_frame: bool = False,
    job_name: str | None = None,
    status_cb: Callable[[str], None] | None = None,
) -> Callable:
    """
    Send a still (or video) into Creative Vision.

    ``role`` for stills:
      - ``start`` — Start frame (bridge / I2V)
      - ``end`` — End frame (bridge)
      - ``i2v`` — Image → Video primary source still
      - ``i2i`` — Image → Image edit source still
    ``as_end_frame`` kept for callers; maps to role=end.
    ``job_name`` optional label preserved in status (does not auto-Enhance).
    """

    async def _click(_e: ft.ControlEvent) -> None:
        use_role = "end" if as_end_frame else (role or "start")
        if as_video:
            use_role = "video"
        vv = getattr(state, "vision_view", None)
        if vv is not None:
            if use_role == "video" and hasattr(vv, "receive_video"):
                vv.receive_video(path, job_name=job_name)
            elif use_role == "end" and hasattr(vv, "receive_end_frame"):
                vv.receive_end_frame(path, job_name=job_name)
            elif use_role == "i2v" and hasattr(vv, "receive_i2v_source"):
                vv.receive_i2v_source(path, job_name=job_name)
            elif use_role == "i2i" and hasattr(vv, "receive_i2i_source"):
                vv.receive_i2i_source(path, job_name=job_name)
            elif use_role == "i2i_ref" and hasattr(vv, "receive_i2i_ref"):
                vv.receive_i2i_ref(path, job_name=job_name)
            elif hasattr(vv, "receive_start_frame"):
                vv.receive_start_frame(path, job_name=job_name)
            elif hasattr(vv, "load_start_image"):
                vv.load_start_image(path)
            elif hasattr(vv, "set_start_path"):
                vv.set_start_path(path)
        switch = getattr(state, "switch_to_vision", None)
        if switch:
            try:
                switch(role=use_role if use_role != "video" else None)
            except TypeError:
                switch()
        role_labels = {
            "start": "Start frame",
            "end": "End frame",
            "i2v": "I2V source",
            "i2i": "Image → Image source",
            "i2i_ref": "Image → Image ref",
            "video": "video",
        }
        label = role_labels.get(use_role, use_role)
        name_note = f" · {job_name}" if job_name else ""
        if status_cb:
            status_cb(
                f"Sent to Creative Vision ({label}){name_note}: {Path(path).name}"
            )

    return _click


def send_to_video_sfx(
    state: Any,
    path: str,
    *,
    status_cb: Callable[[str], None] | None = None,
) -> Callable:
    async def _click(_e: ft.ControlEvent) -> None:
        av = getattr(state, "audio_view", None)
        if av is not None and hasattr(av, "receive_video_for_sfx"):
            av.receive_video_for_sfx(path)
        switch = getattr(state, "switch_to_audio", None)
        if switch:
            switch("video_sfx")
        if status_cb:
            status_cb(f"Sent to Audio → Video→SFX: {Path(path).name}")

    return _click


def send_to_resolve(
    state: Any,
    path: str,
    *,
    status_cb: Callable[[str, bool], None] | None = None,
) -> Callable:
    async def _click(_e: ft.ControlEvent) -> None:
        import asyncio

        try:
            from media_studio.resolve_export import send_file_to_resolve

            job = getattr(state, "job_name", None) if state is not None else None
            result = await asyncio.to_thread(
                send_file_to_resolve, path, job_name=job
            )
            msg = getattr(result, "message", None) or str(result)
            ok = bool(getattr(result, "ok", True))
            if status_cb:
                status_cb(msg, not ok)
        except Exception as exc:
            if status_cb:
                status_cb(f"Send to Resolve failed: {exc}", True)

    return _click


def send_to_director(
    state: Any,
    path: str,
    *,
    shot_index: int = 0,
    status_cb: Callable[[str], None] | None = None,
) -> Callable:
    """
    Send a Library (or other) still into Director as Shot K ref still.

    Creates Shot 1 if the Director has no rows yet. Focuses the Director tab
    and highlights the target shot row.
    """

    async def _click(_e: ft.ControlEvent) -> None:
        dv = getattr(state, "director_view", None)
        assigned = shot_index
        if dv is not None and hasattr(dv, "receive_shot_ref"):
            assigned = int(dv.receive_shot_ref(shot_index, path) or shot_index)
        elif dv is not None and hasattr(dv, "_set_shot_ref"):
            # Fallback if receive API missing
            shots = getattr(dv, "_shots", None) or []
            if not shots and hasattr(dv, "_add_shot_row"):
                dv._add_shot_row(start=0, end=5)
            idx = max(0, min(shot_index, max(0, len(getattr(dv, "_shots", []) or []) - 1)))
            dv._set_shot_ref(idx, path)
            assigned = idx
        switch = getattr(state, "switch_to_director", None)
        if switch:
            switch()
        msg = f"Sent to Director · Shot {assigned + 1}: {Path(path).name}"
        if status_cb:
            status_cb(msg)

    return _click


def send_to_director_keyframe(
    state: Any,
    path: str,
    *,
    pin_index: int | None = None,
    status_cb: Callable[[str], None] | None = None,
) -> Callable:
    """
    Send a still into Director · Keyframe Take as a pin.

    ``pin_index`` None → append as next pin; int → replace that pin (0-based).
    Switches to Director and Keyframe Take mode.
    """

    async def _click(_e: ft.ControlEvent) -> None:
        dv = getattr(state, "director_view", None)
        assigned = 0
        if dv is not None and hasattr(dv, "receive_keyframe_pin"):
            assigned = int(
                dv.receive_keyframe_pin(path, pin_index=pin_index) or 0
            )
        elif dv is not None and hasattr(dv, "_kf_add_pin_data"):
            try:
                if hasattr(dv, "_on_director_mode"):
                    dv._on_director_mode("keyframe_take")
                try:
                    dv._mode_nav.set_selected("keyframe_take", notify=False)
                except Exception:
                    pass
            except Exception:
                pass
            if pin_index is not None and hasattr(dv, "_kf_replace_pin"):
                dv._kf_replace_pin(int(pin_index), path)
                assigned = int(pin_index)
            else:
                dv._kf_add_pin_data(path)
                assigned = max(0, len(getattr(dv, "_kf_pins", []) or []) - 1)
        switch = getattr(state, "switch_to_director", None)
        if switch:
            switch()
        msg = f"Sent to Director · Keyframe Take · Pin {assigned + 1}: {Path(path).name}"
        if status_cb:
            status_cb(msg)

    return _click


# ---------------------------------------------------------------------------
# Build menu items (nested flyouts)
# ---------------------------------------------------------------------------


def _director_shot_count(state: Any) -> int:
    """Number of currently defined Director shot rows (0 if no view)."""
    dv = getattr(state, "director_view", None)
    if dv is None:
        return 0
    shots = getattr(dv, "_shots", None)
    try:
        return len(shots) if shots is not None else 0
    except Exception:
        return 0


def _director_keyframe_pin_count(state: Any) -> int:
    dv = getattr(state, "director_view", None)
    if dv is None:
        return 0
    pins = getattr(dv, "_kf_pins", None)
    try:
        return len(pins) if pins is not None else 0
    except Exception:
        return 0


def vision_still_menu_items(
    state: Any,
    path: str,
    *,
    job_name: str | None = None,
    status_cb: Callable[[str], None] | None = None,
    short_labels: bool = True,
) -> list[ft.Control]:
    """Creative Vision still targets (for CV flyout or flat lists)."""
    if short_labels:
        labels = [
            ("Image → Image (source)", "i2i"),
            ("Image → Image (add as ref)", "i2i_ref"),
            ("Start frame", "start"),
            ("End frame", "end"),
            ("I2V source", "i2v"),
        ]
    else:
        labels = [
            ("Creative Vision · Image → Image (source)", "i2i"),
            ("Creative Vision · Image → Image (add as ref)", "i2i_ref"),
            ("Creative Vision · Start frame", "start"),
            ("Creative Vision · End frame", "end"),
            ("Creative Vision · I2V source", "i2v"),
        ]
    return [
        _item(
            lab,
            send_to_vision(
                state, path, role=role, job_name=job_name, status_cb=status_cb
            ),
        )
        for lab, role in labels
    ]


def director_shot_menu_items(
    state: Any,
    path: str,
    *,
    status_cb: Callable[[str], None] | None = None,
) -> list[ft.Control]:
    """
    Dynamic Director targets: Multi-shot Shot 1…N + Keyframe Take pin actions.
    If no multi-shot rows yet, offer Shot 1 (receive creates it).
    """
    n = _director_shot_count(state)
    if n <= 0:
        n = 1
    multi = [
        _item(
            f"Shot {i + 1}",
            send_to_director(state, path, shot_index=i, status_cb=status_cb),
        )
        for i in range(n)
    ]
    # Keyframe Take: add next pin + replace existing pins
    kf_items: list[ft.Control] = [
        _item(
            "Add as next pin",
            send_to_director_keyframe(state, path, pin_index=None, status_cb=status_cb),
        )
    ]
    n_pins = _director_keyframe_pin_count(state)
    for i in range(n_pins):
        kf_items.append(
            _item(
                f"Replace pin {i + 1}",
                send_to_director_keyframe(
                    state, path, pin_index=i, status_cb=status_cb
                ),
            )
        )
    return [
        _submenu("Multi-shot", multi),
        _submenu("Keyframe Take", kf_items),
    ]


def tools_menu_items(
    state: Any,
    path: str,
    *,
    as_video: bool,
    status_cb: Callable[[str], None] | None = None,
) -> list[ft.Control]:
    tools = _VIDEO_TOOLS if as_video else _IMAGE_TOOLS
    return [
        _item(
            lab,
            send_to_tool(state, tid, path, as_video=as_video, status_cb=status_cb),
        )
        for lab, tid in tools
    ]


def motion_sync_menu_items(
    state: Any,
    path: str,
    *,
    as_video: bool,
    status_cb: Callable[[str], None] | None = None,
) -> list[ft.Control]:
    """
    Nested Motion Sync targets:
      still → Character
      video → Motion reference
    """
    if as_video:
        return [
            _item(
                "Motion reference",
                send_to_motion_sync(
                    state, path, role="motion", status_cb=status_cb
                ),
            )
        ]
    return [
        _item(
            "Character",
            send_to_motion_sync(
                state, path, role="character", status_cb=status_cb
            ),
        )
    ]


def build_send_menu_items(
    state: Any,
    *,
    image_path: str | None = None,
    video_path: str | None = None,
    status_cb: Callable[[str], None] | None = None,
    status_cb_err: Callable[[str, bool], None] | None = None,
    include_tools: bool = True,
    include_vision: bool = True,
    include_frame_editor: bool = True,
    include_audio_vsfx: bool = True,
    include_resolve: bool = True,
    include_region: bool = True,
    include_director: bool = True,
) -> list[ft.Control]:
    """
    Nested destination matrix for a still and/or video path.

    Top-level (stills) stays short:
      Studio Image · Studio Video · Region · Director ▶ · Creative Vision ▶ ·
      Frame Editor · Tools ▶ · Motion Sync ▶ · Resolve

    Flyouts:
      Director → Shot 1…N (dynamic from Director rows)
      Creative Vision → I2I source / add ref / start / end / I2V
      Tools → Upscale, Object Remove, …
      Motion Sync → Character (still) or Motion reference (video)
    """
    items: list[ft.Control] = []
    img = image_path if image_path and Path(image_path).is_file() else None
    vid = video_path if video_path and Path(video_path).is_file() else None

    def _ok(msg: str) -> None:
        if status_cb:
            status_cb(msg)

    def _resolve_cb(msg: str, is_err: bool = True) -> None:
        if status_cb_err:
            status_cb_err(msg, is_err)
        elif status_cb:
            status_cb(msg)

    if img:
        items.append(_item("Studio Image", send_to_image(state, img, status_cb=_ok)))
        items.append(
            _item("Studio Video", send_to_video_ref(state, img, status_cb=_ok))
        )
        if include_region:
            items.append(_item("Region", send_to_region(state, img, status_cb=_ok)))
        if include_director:
            items.append(
                _submenu(
                    "Director",
                    director_shot_menu_items(state, img, status_cb=_ok),
                )
            )
        if include_vision:
            items.append(
                _submenu(
                    "Creative Vision",
                    vision_still_menu_items(state, img, status_cb=_ok),
                )
            )
        if include_frame_editor:
            items.append(
                _item(
                    "Frame Editor",
                    send_to_frame_editor(state, img, as_video=False, status_cb=_ok),
                )
            )
        if include_tools:
            items.append(
                _submenu(
                    "Tools",
                    tools_menu_items(state, img, as_video=False, status_cb=_ok),
                )
            )
        items.append(
            _submenu(
                "Motion Sync",
                motion_sync_menu_items(
                    state, img, as_video=False, status_cb=_ok
                ),
            )
        )
        if include_resolve:
            items.append(
                _item(
                    "Resolve",
                    send_to_resolve(state, img, status_cb=_resolve_cb),
                )
            )

    if vid:
        # Video destinations keep a short top-level list (no Director shot refs).
        items.append(
            _item(
                "Studio Video",
                send_to_video_source(state, vid, status_cb=_ok),
            )
        )
        # Primary video polish path — same friction as image "Send to Upscale"
        if include_tools:
            items.append(
                _item(
                    "Video Upscale",
                    send_to_tool(
                        state, "upscale", vid, as_video=True, status_cb=_ok
                    ),
                )
            )
        if include_vision:
            items.append(
                _item(
                    "Creative Vision",
                    send_to_vision(state, vid, as_video=True, status_cb=_ok),
                )
            )
        if include_frame_editor:
            items.append(
                _item(
                    "Frame Editor",
                    send_to_frame_editor(state, vid, as_video=True, status_cb=_ok),
                )
            )
        if include_tools:
            items.append(
                _submenu(
                    "Tools",
                    tools_menu_items(state, vid, as_video=True, status_cb=_ok),
                )
            )
        items.append(
            _submenu(
                "Motion Sync",
                motion_sync_menu_items(
                    state, vid, as_video=True, status_cb=_ok
                ),
            )
        )
        if include_audio_vsfx:
            items.append(
                _item(
                    "Audio · Video → SFX",
                    send_to_video_sfx(state, vid, status_cb=_ok),
                )
            )
        if include_resolve:
            items.append(
                _item(
                    "Resolve",
                    send_to_resolve(state, vid, status_cb=_resolve_cb),
                )
            )

    return items


def make_send_menu_button(
    items: list[ft.Control],
    *,
    tooltip: str = (
        "Send to Studio, Director, Creative Vision, Tools, Motion Sync, "
        "Frame Editor, or Resolve"
    ),
) -> ft.Control | None:
    """
    Build the Send to control.

    Prefer cascading MenuBar + SubmenuButton (hover/click flyouts to the right).
    Fall back to PopupMenuButton when callers pass only PopupMenuItem leaves
    (Frame Editor / Vision custom lists that have not migrated yet).
    """
    if not items:
        return None

    # Legacy path: pure PopupMenuItem list (no nested SubmenuButton).
    if all(isinstance(c, ft.PopupMenuItem) for c in items):
        return ft.Container(
            content=ft.PopupMenuButton(
                content=ft.Row(
                    [
                        ft.Icon(ft.Icons.SEND_OUTLINED, size=16, color=TEXT),
                        ft.Text("Send to ▾", size=FONT_SM, color=TEXT),
                    ],
                    spacing=6,
                    tight=True,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                items=list(items),  # type: ignore[arg-type]
                tooltip=tooltip,
                menu_position=ft.PopupMenuPosition.UNDER,
            ),
            bgcolor=PANEL_ELEVATED,
            border=ft.Border.all(1, BORDER),
            border_radius=6,
            padding=ft.Padding.symmetric(horizontal=10, vertical=6),
        )

    # Cascading menu: root SubmenuButton opens top-level destinations;
    # Director / Creative Vision / Tools are nested SubmenuButtons.
    root = ft.SubmenuButton(
        content=ft.Row(
            [
                ft.Icon(ft.Icons.SEND_OUTLINED, size=16, color=TEXT),
                ft.Text("Send to ▾", size=FONT_SM, color=TEXT),
            ],
            spacing=6,
            tight=True,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        controls=list(items),
        tooltip=tooltip,
        style=ft.ButtonStyle(color=TEXT, padding=ft.Padding.symmetric(horizontal=4, vertical=2)),
        menu_style=ft.MenuStyle(
            bgcolor=PANEL_ELEVATED,
            elevation=4,
            side=ft.BorderSide(1, BORDER),
            padding=ft.Padding.symmetric(horizontal=4, vertical=4),
            alignment=ft.Alignment.BOTTOM_LEFT,
        ),
    )
    bar = ft.MenuBar(
        expand=False,
        style=ft.MenuStyle(
            bgcolor=PANEL_ELEVATED,
            elevation=0,
            padding=ft.Padding.symmetric(horizontal=2, vertical=0),
            side=ft.BorderSide(0, BORDER),
        ),
        controls=[root],
    )
    return ft.Container(
        content=bar,
        bgcolor=PANEL_ELEVATED,
        border=ft.Border.all(1, BORDER),
        border_radius=6,
        padding=ft.Padding.symmetric(horizontal=6, vertical=2),
        tooltip=tooltip,
    )
