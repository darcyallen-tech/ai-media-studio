"""Shared Enhance (Grok prompt rewrite) for Studio, Tools, and Audio."""

from __future__ import annotations

import asyncio
from typing import Any, Callable

import flet as ft

from media_studio.flet_progress import JobProgress, classify_progress
from media_studio.flet_theme import BORDER, TEXT
from media_studio.services import enhance_prompt

GetStr = Callable[[], str | None]
GetDict = Callable[[], dict[str, Any] | None]


def make_enhance_button(
    *,
    on_click,
    tooltip: str = "Rewrite the prompt for the selected model (Grok). Model is not changed.",
) -> ft.OutlinedButton:
    return ft.OutlinedButton(
        content="Enhance",
        icon=ft.Icons.AUTO_FIX_HIGH,
        on_click=on_click,
        style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
        tooltip=tooltip,
        height=40,
    )


async def run_prompt_enhance(
    *,
    page: ft.Page,
    state: Any,
    prompt_field: ft.TextField,
    get_model: GetStr,
    get_image: GetStr | None = None,
    get_video: GetStr | None = None,
    get_scenario: GetStr | None = None,
    get_extra_context: Callable[[], dict[str, Any] | None] | None = None,
    get_extra_images: Callable[[], list[str] | None] | None = None,
    status_ctrl: ft.Text | None = None,
    job_progress: JobProgress | None = None,
    enhance_btn: ft.Control | None = None,
    busy_controls: list[ft.Control] | None = None,
    context_label: str = "prompt",
    allow_empty_with_context: bool = False,
    busy_scope: str = "enhance",
) -> bool:
    """
    Rewrite ``prompt_field`` for the currently selected model.

    Does **not** change any model dropdown — only the text field.
    When a still is present, uses vision. Returns True if the prompt was updated.
    ``busy_scope`` isolates Enhance so other tabs can keep generating.
    """
    try_busy = getattr(state, "try_busy", None)
    is_busy = getattr(state, "is_busy", None)
    if callable(is_busy) and is_busy(busy_scope):
        return False
    if not callable(try_busy):
        if getattr(state, "busy", False):
            return False

    prompt = (prompt_field.value or "").strip()
    extra_ctx: dict[str, Any] | None = None
    try:
        if get_extra_context:
            extra_ctx = get_extra_context() or None
    except Exception:
        extra_ctx = None

    if not prompt and not (allow_empty_with_context and extra_ctx):
        msg = f"Enter a {context_label} to enhance."
        if status_ctrl is not None:
            status_ctrl.value = msg
            try:
                page.update()
            except Exception:
                pass
        return False

    from media_studio.secrets_store import has_xai_key

    if not has_xai_key():
        msg = (
            "xAI API key required for Enhance — open Settings (gear icon) "
            "and paste your key from console.x.ai."
        )
        if status_ctrl is not None:
            status_ctrl.value = msg
            try:
                page.update()
            except Exception:
                pass
        return False

    model = None
    try:
        model = get_model()
    except Exception:
        model = None

    image_file = None
    video_file = None
    extra_images: list[str] | None = None
    try:
        if get_image:
            image_file = get_image()
    except Exception:
        image_file = None
    try:
        if get_video:
            video_file = get_video()
    except Exception:
        video_file = None
    try:
        if get_extra_images:
            raw = get_extra_images() or []
            extra_images = [p for p in raw if p]
    except Exception:
        extra_images = None

    scenario = None
    try:
        if get_scenario:
            scenario = get_scenario()
    except Exception:
        scenario = None
    if not scenario:
        scenario = getattr(state, "scenario_key", None) or getattr(
            state, "scenario_label", None
        )

    if callable(try_busy):
        if not try_busy(busy_scope):
            return False
    else:
        state.busy = True
    controls = list(busy_controls or [])
    if enhance_btn is not None:
        controls.append(enhance_btn)
    for c in controls:
        try:
            c.disabled = True
        except Exception:
            pass

    if job_progress is not None:
        job_progress.start("Enhancing prompt…", page)
    if status_ctrl is not None:
        n_refs = len(extra_images or [])
        status_ctrl.value = (
            "Enhancing with Grok"
            + (" · vision" if image_file or video_file else "")
            + (f" · {n_refs} ref(s)" if n_refs else "")
            + " (model locked)…"
        )
    try:
        page.update()
    except Exception:
        pass

    def on_progress(msg: str) -> None:
        if job_progress is not None:
            job_progress.set_message(classify_progress(msg), page)

    ok = False
    try:
        # model_choice set → enhance_prompt locks the model (no auto-switch)
        result = await asyncio.to_thread(
            enhance_prompt,
            prompt=prompt or "",
            model_choice=model or "",
            image_file=image_file,
            video_file=video_file,
            parameters=None,
            output_dir=getattr(state, "output_dir", None),
            scenario=scenario,
            extra_context=extra_ctx,
            extra_image_files=extra_images or None,
        )
        if result.ok and (result.optimized_prompt or "").strip():
            prompt_field.value = result.optimized_prompt.strip()
            done = result.status or "Enhanced. Review the prompt, then generate."
            if job_progress is not None:
                job_progress.finish_ok("Enhanced.", page)
            if status_ctrl is not None:
                status_ctrl.value = done
            ok = True
        else:
            err = result.status or "Enhance failed."
            if job_progress is not None:
                job_progress.finish_error(err, page)
            if status_ctrl is not None:
                status_ctrl.value = err
    except Exception as exc:
        err = f"Enhance error: {exc}"
        if job_progress is not None:
            job_progress.finish_error(err, page)
        if status_ctrl is not None:
            status_ctrl.value = err
    finally:
        clear_busy = getattr(state, "clear_busy", None)
        if callable(clear_busy):
            clear_busy(busy_scope)
        else:
            state.busy = False
        for c in controls:
            try:
                c.disabled = False
            except Exception:
                pass
        # Re-apply key gates if present on parent views
        try:
            page.update()
        except Exception:
            pass
    return ok
