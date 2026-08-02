"""
Shared Send-to destination matrix (Phase C).

One logical menu across Library, Tools results, Creative Vision, etc.
Destinations appear only when the media type allows them.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

import flet as ft

from media_studio.flet_theme import BORDER, FONT_SM, PANEL_ELEVATED, TEXT

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


def _item(label: str, handler: Callable) -> ft.PopupMenuItem:
    return ft.PopupMenuItem(content=label, on_click=handler)


def _sep() -> ft.PopupMenuItem:
    return ft.PopupMenuItem()


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


# ---------------------------------------------------------------------------
# Build menu items
# ---------------------------------------------------------------------------


def vision_still_menu_items(
    state: Any,
    path: str,
    *,
    job_name: str | None = None,
    status_cb: Callable[[str], None] | None = None,
) -> list[ft.Control]:
    """Creative Vision still targets with clear labels."""
    return [
        _item(
            "Creative Vision · Image → Image (source)",
            send_to_vision(
                state, path, role="i2i", job_name=job_name, status_cb=status_cb
            ),
        ),
        _item(
            "Creative Vision · Image → Image (add as ref)",
            send_to_vision(
                state, path, role="i2i_ref", job_name=job_name, status_cb=status_cb
            ),
        ),
        _item(
            "Creative Vision · Start frame",
            send_to_vision(
                state, path, role="start", job_name=job_name, status_cb=status_cb
            ),
        ),
        _item(
            "Creative Vision · End frame",
            send_to_vision(
                state, path, role="end", job_name=job_name, status_cb=status_cb
            ),
        ),
        _item(
            "Creative Vision · I2V source",
            send_to_vision(
                state, path, role="i2v", job_name=job_name, status_cb=status_cb
            ),
        ),
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
) -> list[ft.Control]:
    """
    Destination matrix for a still and/or video path.

    Image still:
      Studio Image, Studio Video (ref), Region, Image tools,
      Frame Editor · keyframe, Creative Vision · Start/End/I2V, Resolve
    Video:
      Studio Video (source), Video tools, Frame Editor source, Creative Vision,
      Audio Video→SFX, Resolve
    """
    items: list[ft.Control] = []
    img = image_path if image_path and Path(image_path).is_file() else None
    vid = video_path if video_path and Path(video_path).is_file() else None

    def _ok(msg: str) -> None:
        if status_cb:
            status_cb(msg)

    def _err(msg: str, is_err: bool = True) -> None:
        if status_cb_err:
            status_cb_err(msg, is_err)
        elif status_cb:
            status_cb(msg)

    if img:
        items.append(_item("Studio Image (source)", send_to_image(state, img, status_cb=_ok)))
        items.append(
            _item("Studio Video (reference still)", send_to_video_ref(state, img, status_cb=_ok))
        )
        if include_region:
            items.append(_item("Region edit", send_to_region(state, img, status_cb=_ok)))
        if include_tools:
            items.append(_sep())
            for lab, tid in _IMAGE_TOOLS:
                items.append(
                    _item(
                        f"Tools · {lab}",
                        send_to_tool(state, tid, img, as_video=False, status_cb=_ok),
                    )
                )
        if include_frame_editor:
            items.append(_sep())
            items.append(
                _item(
                    "Frame Editor · keyframe",
                    send_to_frame_editor(state, img, as_video=False, status_cb=_ok),
                )
            )
        if include_vision:
            items.append(_sep())
            items.extend(vision_still_menu_items(state, img, status_cb=_ok))
        if include_resolve:
            items.append(_sep())
            items.append(
                _item(
                    "Resolve",
                    send_to_resolve(state, img, status_cb=status_cb_err or (lambda m, e: _ok(m))),
                )
            )

    if vid:
        if items:
            items.append(_sep())
        items.append(
            _item(
                "Studio Video (source clip)",
                send_to_video_source(state, vid, status_cb=_ok),
            )
        )
        if include_tools:
            items.append(_sep())
            for lab, tid in _VIDEO_TOOLS:
                items.append(
                    _item(
                        f"Tools · {lab}",
                        send_to_tool(state, tid, vid, as_video=True, status_cb=_ok),
                    )
                )
        if include_frame_editor:
            items.append(_sep())
            items.append(
                _item(
                    "Frame Editor (Aleph source)",
                    send_to_frame_editor(state, vid, as_video=True, status_cb=_ok),
                )
            )
        if include_vision:
            items.append(
                _item(
                    "Creative Vision",
                    send_to_vision(state, vid, as_video=True, status_cb=_ok),
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
            items.append(_sep())
            items.append(
                _item(
                    "Resolve",
                    send_to_resolve(state, vid, status_cb=status_cb_err or (lambda m, e: _ok(m))),
                )
            )

    return items


def make_send_menu_button(
    items: list[ft.Control],
    *,
    tooltip: str = "Send to Studio, Tools, Frame Editor, Audio, or Resolve",
) -> ft.Control | None:
    if not items:
        return None
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
            items=items,
            tooltip=tooltip,
            menu_position=ft.PopupMenuPosition.UNDER,
        ),
        bgcolor=PANEL_ELEVATED,
        border=ft.Border.all(1, BORDER),
        border_radius=6,
        padding=ft.Padding.symmetric(horizontal=10, vertical=6),
    )
