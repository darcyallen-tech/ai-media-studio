"""Shared job progress UI so Generate never looks frozen."""

from __future__ import annotations

from typing import Any

import flet as ft

from media_studio.flet_theme import ACCENT, FONT_SM, TEXT, TEXT_MUTED


class JobProgress:
    """
    Progress ring + bar + status line for long fal jobs.

    Usage:
        prog = JobProgress()
        # include prog.control in layout
        prog.start("Uploading…")
        prog.set_message("Generating…")
        prog.finish_ok("Done · Est. cost: $0.03")
        prog.finish_error("Failed: …")
    """

    def __init__(self, *, width: float | None = None) -> None:
        self.ring = ft.ProgressRing(
            width=22,
            height=22,
            stroke_width=3,
            color=ACCENT,
            visible=False,
        )
        self.bar = ft.ProgressBar(
            value=None,  # indeterminate
            color=ACCENT,
            bgcolor="#2a2f3a",
            height=4,
            visible=False,
            expand=True,  # horizontal only — lives inside a Row
        )
        self.message = ft.Text(
            "",
            size=FONT_SM,
            color=TEXT_MUTED,
            visible=False,
            max_lines=2,
        )
        # Bar in a Row so expand is horizontal only (not a tall slab in ListView)
        self.control = ft.Column(
            [
                ft.Row(
                    [self.ring, self.message],
                    spacing=10,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Row([self.bar], spacing=0),
            ],
            spacing=6,
            visible=True,
            tight=True,
            expand=False,
            width=width,
        )
        self._active = False

    @property
    def active(self) -> bool:
        return self._active

    def start(self, message: str = "Starting…", page: ft.Page | None = None) -> None:
        self._active = True
        self.ring.visible = True
        self.bar.visible = True
        self.bar.value = None  # indeterminate
        self.message.visible = True
        self.message.value = message
        self.message.color = TEXT_MUTED
        self._upd(page)

    def set_message(self, message: str, page: ft.Page | None = None) -> None:
        self.message.value = message
        self.message.visible = True
        if not self._active:
            self.start(message, page)
            return
        self._upd(page)

    def finish_ok(self, message: str = "Done.", page: ft.Page | None = None) -> None:
        self._active = False
        self.ring.visible = False
        self.bar.visible = False
        self.bar.value = 0
        self.message.visible = True
        self.message.value = message
        self.message.color = TEXT
        self._upd(page)

    def finish_error(self, message: str = "Failed.", page: ft.Page | None = None) -> None:
        self._active = False
        self.ring.visible = False
        self.bar.visible = False
        self.bar.value = 0
        self.message.visible = True
        self.message.value = message
        self.message.color = "#e57373"
        self._upd(page)
        # Credits / quota: helpful top-up modal (fal vs xAI)
        if page is not None and message:
            try:
                from media_studio.flet_dialogs import maybe_show_credits_dialog

                maybe_show_credits_dialog(page, message)
            except Exception:
                pass

    def hide(self, page: ft.Page | None = None) -> None:
        self._active = False
        self.ring.visible = False
        self.bar.visible = False
        self.message.visible = False
        self._upd(page)

    def _upd(self, page: ft.Page | None) -> None:
        """
        Refresh UI safely.

        Progress callbacks often fire from ``asyncio.to_thread`` workers.
        Prefer ``schedule_update`` (session queue) over raw ``page.update`` so
        Flet is not mutated from a non-UI thread.
        """
        if page is None:
            return
        try:
            schedule = getattr(page, "schedule_update", None)
            if callable(schedule):
                schedule()
                return
        except Exception:
            pass
        try:
            page.update()
        except Exception:
            pass


def classify_progress(msg: str) -> str:
    """Map fal progress lines to short user-facing phases."""
    m = (msg or "").lower()
    if any(k in m for k in ("upload", "uploading")):
        return "Uploading…"
    if any(k in m for k in ("queue", "queued", "waiting", "pending")):
        return "Queued…"
    if any(k in m for k in ("download", "saving", "saved", "writing")):
        return "Saving…"
    if any(k in m for k in ("generat", "infer", "running", "process", "edit", "render")):
        return "Generating…"
    if msg and len(msg.strip()) < 80:
        return msg.strip()
    return "Generating…"


class CollapsibleJobLog:
    """
    Raw fal log lines, collapsed by default.

    Short status stays on ``JobProgress`` / ``status_text``; this panel only
    shows detail when the user expands it, or automatically on error.
    """

    def __init__(self, *, max_lines: int = 40) -> None:
        self._lines: list[str] = []
        self._max_lines = max_lines
        self._expanded = False
        self._is_error = False

        self.detail = ft.Text(
            "",
            size=FONT_SM,
            color=TEXT_MUTED,
            selectable=True,
            max_lines=12,
            visible=False,
        )
        self.toggle = ft.TextButton(
            content="Show log",
            on_click=self._on_toggle,
            visible=False,
            style=ft.ButtonStyle(color=TEXT_MUTED),
        )
        self.control = ft.Column(
            [self.toggle, self.detail],
            spacing=2,
            tight=True,
        )
        self._page: ft.Page | None = None

    def bind_page(self, page: ft.Page | None) -> None:
        self._page = page

    def clear(self, page: ft.Page | None = None) -> None:
        self._lines.clear()
        self._expanded = False
        self._is_error = False
        self.detail.value = ""
        self.detail.visible = False
        self.detail.color = TEXT_MUTED
        self.toggle.visible = False
        self.toggle.content = "Show log"
        self._upd(page)

    def append(self, msg: str, page: ft.Page | None = None) -> None:
        s = (msg or "").strip()
        if not s:
            return
        self._lines.append(s)
        if len(self._lines) > self._max_lines:
            self._lines = self._lines[-self._max_lines :]
        # Keep collapsed during run — only offer toggle once we have lines
        if self._lines and not self._is_error:
            self.toggle.visible = True
            if not self._expanded:
                self.detail.visible = False
                self.toggle.content = "Show log"
            else:
                self._refresh_detail()
        self._upd(page)

    def finish_ok(self, page: ft.Page | None = None) -> None:
        """Keep log available but collapsed after success."""
        self._is_error = False
        self._expanded = False
        self.detail.visible = False
        self.detail.color = TEXT_MUTED
        if self._lines:
            self.toggle.visible = True
            self.toggle.content = "Show log"
        else:
            self.toggle.visible = False
        self._upd(page)

    def finish_error(self, detail: str = "", page: ft.Page | None = None) -> None:
        """Expand raw log + error so failures are diagnosable."""
        self._is_error = True
        d = (detail or "").strip()
        if d and (not self._lines or self._lines[-1] != d):
            self._lines.append(d)
        self._expanded = True
        self._refresh_detail()
        self.detail.color = "#e57373"
        self.detail.visible = True
        self.toggle.visible = True
        self.toggle.content = "Hide log"
        self._upd(page)
        # Credits modal is shown once from JobProgress.finish_error (not here).

    def _refresh_detail(self) -> None:
        self.detail.value = "\n".join(self._lines[-self._max_lines :])

    async def _on_toggle(self, _e: ft.ControlEvent) -> None:
        self._expanded = not self._expanded
        if self._expanded:
            self._refresh_detail()
            self.detail.visible = True
            self.toggle.content = "Hide log"
        else:
            self.detail.visible = False
            self.toggle.content = "Show log"
        self._upd(self._page)

    def _upd(self, page: ft.Page | None) -> None:
        p = page or self._page
        if p is None:
            return
        try:
            schedule = getattr(p, "schedule_update", None)
            if callable(schedule):
                schedule()
                return
        except Exception:
            pass
        try:
            p.update()
        except Exception:
            pass
