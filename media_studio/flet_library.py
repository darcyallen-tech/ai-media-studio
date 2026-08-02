"""Library tab — history of successful image and video generations."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

import flet as ft

from media_studio.folder_util import show_in_folder
from media_studio.flet_dialogs import close_dialog, show_dialog, show_snack
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
    panel,
    section_title,
    styled_dropdown,
)
from media_studio.history import (
    HistoryEntry,
    assign_entry_job,
    find_by_id,
    first_audio_path,
    first_image_path,
    first_video_path,
    format_timestamp,
    library_entries,
    list_job_names,
)
from media_studio.media import video_poster_path

if TYPE_CHECKING:
    from media_studio.flet_app import StudioState


# Filter ids for PillNav
_FILTER_ALL = "all"
_FILTER_IMAGE = "image"
_FILTER_VIDEO = "video"
_FILTER_AUDIO = "audio"
_FILTER_RESOLVE = "resolve"
_JOB_ALL = "(All jobs)"
_RESOLVE_BADGE = "#c4782a"  # warm amber — distinct from Image/Video/Audio


class LibraryView:
    """Scrollable history of successful generations with send actions."""

    def __init__(self, page: ft.Page, state: StudioState) -> None:
        self.page = page
        self.state = state
        # Scrollable results only — never a flex spacer between filters and cards
        self._list = ft.ListView(spacing=10, expand=True, padding=ft.Padding.only(top=4))
        self._status = ft.Text("", size=FONT_SM, color=TEXT_MUTED, max_lines=2)
        self._count = ft.Text("", size=FONT_SM, color=TEXT_MUTED)
        self.btn_refresh = ft.OutlinedButton(
            content="Refresh",
            icon=ft.Icons.REFRESH,
            on_click=self._on_refresh,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
        )
        # Session-remembered filter (All | Image | Video | Audio | From Resolve)
        last = getattr(state, "library_filter", None)
        if last not in (
            _FILTER_ALL,
            _FILTER_IMAGE,
            _FILTER_VIDEO,
            _FILTER_AUDIO,
            _FILTER_RESOLVE,
        ):
            last = _FILTER_ALL
        self._filter = last
        state.library_filter = self._filter
        self._filter_nav = PillNav(
            [
                (_FILTER_ALL, "All"),
                (_FILTER_IMAGE, "Image"),
                (_FILTER_VIDEO, "Video"),
                (_FILTER_AUDIO, "Audio"),
                (_FILTER_RESOLVE, "From Resolve"),
            ],
            selected=self._filter,
            on_change=self._on_filter_change,
        )
        # Job / Listing filter (All jobs + known labels from history)
        # expand=False: in a Column, expand=True steals vertical space (giant gap).
        # Horizontal fill via a tight Row below.
        self._job_filter = getattr(state, "library_job_filter", None) or ""
        state.library_job_filter = self._job_filter
        self.job_dd = styled_dropdown(
            label_text="Job / Listing",
            options=[_JOB_ALL],
            value=_JOB_ALL,
            on_select=self._on_job_filter,
            expand=True,  # only meaningful inside a Row (horizontal)
        )
        # Optional open-large dialog host
        self._lightbox_src = ft.Image(src="", fit=ft.BoxFit.CONTAIN, expand=True)
        # Local spend dashboard (history costs only)
        from media_studio.flet_spend import build_spend_panel

        self.spend_panel = build_spend_panel(
            page,
            state,
            compact=True,
            on_status=lambda m: setattr(self._status, "value", m),
        )
        # Multi-select for bulk Assign to Job / Listing
        self._selected_ids: set[str] = set()
        self._visible_ids: list[str] = []
        self._bulk_count = ft.Text(
            "0 selected",
            size=FONT_SM,
            color=TEXT,
            weight=ft.FontWeight.W_600,
        )
        self.btn_select_all = ft.TextButton(
            content="Select all",
            on_click=self._on_select_all_visible,
            style=ft.ButtonStyle(color=ACCENT_BRIGHT),
        )
        self.btn_clear_sel = ft.TextButton(
            content="Clear",
            on_click=self._on_clear_selection,
            style=ft.ButtonStyle(color=TEXT_MUTED),
        )
        self.btn_bulk_resolve = ft.OutlinedButton(
            content="Send to Resolve",
            icon=ft.Icons.SEND,
            on_click=self._on_bulk_send_resolve,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
            tooltip=(
                "Send each selected item to Resolve (Tier A: "
                "AI Media Studio / Job or date, optional V2 + marker)"
            ),
        )
        # Prefer Resolve logo when bundled
        try:
            from media_studio.resolve_export import resolve_icon_path

            icon_p = resolve_icon_path()
            if icon_p:
                self.btn_bulk_resolve.content = ft.Row(
                    [
                        ft.Image(
                            src=icon_p, width=16, height=16, fit=ft.BoxFit.CONTAIN
                        ),
                        ft.Text("Send to Resolve", size=FONT_SM, color=TEXT),
                    ],
                    spacing=6,
                    tight=True,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                )
                self.btn_bulk_resolve.icon = None
        except Exception:
            pass
        self._bulk_assign_host = ft.Container()  # rebuilt when selection changes
        self._bulk_bar = ft.Container(
            content=ft.Row(
                [
                    self._bulk_count,
                    self._bulk_assign_host,
                    self.btn_bulk_resolve,
                    self.btn_select_all,
                    self.btn_clear_sel,
                ],
                spacing=10,
                wrap=True,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor="#1a2230",
            border=ft.Border.all(1, ACCENT),
            border_radius=8,
            padding=ft.Padding.symmetric(horizontal=12, vertical=8),
            visible=False,
        )
        self._rebuild_bulk_assign_menu()

    def build(self) -> ft.Control:
        self.refresh()
        # Header is tight (intrinsic height). Only the ListView expands/scrolls —
        # no expand=True spacer between Job/Listing and cards.
        header = ft.Column(
            [
                ft.Row(
                    [
                        section_title("Library"),
                        ft.Container(expand=True),
                        self._count,
                        self.btn_refresh,
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Text(
                    "Successful generations (newest first). "
                    "Send assets back to Image / Video / Tools, or to Resolve. "
                    "Check cards to bulk Assign to a Job / Listing or Send to Resolve. "
                    "From Resolve shows handoff stills/clips; they also get a Resolve badge in All. "
                    "Filter by Job / Listing when you used that field on generate. "
                    "Missing media can be hidden in Settings → Storage.",
                    size=FONT_SM,
                    color=TEXT_MUTED,
                ),
                self.spend_panel,
                self._filter_nav.control,
                # Row so job_dd expand is horizontal only (not a tall empty band)
                ft.Row(
                    [self.job_dd],
                    spacing=0,
                    tight=True,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                self._bulk_bar,
                self._status,
            ],
            spacing=8,
            tight=True,
        )
        return panel(
            ft.Column(
                [
                    header,
                    self._list,
                ],
                expand=True,
                spacing=6,
            ),
            expand=True,
            padding=16,
        )

    def _on_filter_change(self, filter_id: str) -> None:
        self._filter = filter_id if filter_id in (
            _FILTER_ALL,
            _FILTER_IMAGE,
            _FILTER_VIDEO,
            _FILTER_AUDIO,
            _FILTER_RESOLVE,
        ) else _FILTER_ALL
        self.state.library_filter = self._filter
        self.refresh()
        try:
            self.page.update()
        except Exception:
            pass

    def _on_job_filter(self, e: ft.ControlEvent | None = None) -> None:
        raw = str(self.job_dd.value or _JOB_ALL).strip()
        self._job_filter = "" if raw in ("", _JOB_ALL) else raw
        self.state.library_job_filter = self._job_filter
        self.refresh()
        try:
            self.page.update()
        except Exception:
            pass

    def _sync_job_dropdown(self, job_names: list[str]) -> None:
        opts = [_JOB_ALL] + list(job_names)
        self.job_dd.options = dropdown_options(opts)
        cur = self._job_filter if self._job_filter in job_names else ""
        self.job_dd.value = cur if cur else _JOB_ALL
        self._job_filter = cur
        self.state.library_job_filter = cur

    def _matches_filter(self, entry: HistoryEntry) -> bool:
        if self._job_filter:
            if (entry.job or "").strip() != self._job_filter:
                return False
        if self._filter == _FILTER_ALL:
            return True
        if self._filter == _FILTER_RESOLVE:
            return bool(getattr(entry, "is_from_resolve", False) or (
                (entry.origin or "").strip().lower() == "resolve"
            ))
        media = entry.media_type  # "Image" | "Video" | "Audio"
        if self._filter == _FILTER_IMAGE:
            return media == "Image"
        if self._filter == _FILTER_VIDEO:
            return media == "Video"
        if self._filter == _FILTER_AUDIO:
            return media == "Audio"
        return True

    def _empty_message(self) -> str:
        if self._filter == _FILTER_IMAGE:
            return "No image generations yet. Run Studio → Image, then check back here."
        if self._filter == _FILTER_VIDEO:
            return "No video generations yet. Run Studio → Video, then check back here."
        if self._filter == _FILTER_AUDIO:
            return "No audio generations yet. Run Audio (music / SFX / VO), then check back here."
        if self._filter == _FILTER_RESOLVE:
            return (
                "No Resolve media yet. Use Import from Resolve or send a still/clip "
                "from the Resolve plugin."
            )
        return "No generations yet. Run Image, Video, or Audio, then check back here."

    def refresh(self) -> None:
        """Rebuild the list from history.json (newest first), applying filter."""
        from media_studio.ui_prefs import get_library_hide_missing

        hide_missing = get_library_hide_missing()
        # Full history (for count of hidden missing) when hide is on
        raw_total = len(library_entries(self.state.output_dir, existing_only=False))
        all_entries = library_entries(
            self.state.output_dir, existing_only=hide_missing
        )
        try:
            self._sync_job_dropdown(list_job_names(self.state.output_dir))
        except Exception:
            pass
        entries = [e for e in all_entries if self._matches_filter(e)]
        n = len(entries)
        total = len(all_entries)
        hidden = max(0, raw_total - total) if hide_missing else 0
        if self._filter == _FILTER_ALL and not self._job_filter:
            self._count.value = f"{n} item{'s' if n != 1 else ''}"
        else:
            if self._filter == _FILTER_RESOLVE:
                bits = [f"{n} from Resolve"]
            else:
                label = {
                    _FILTER_IMAGE: "image",
                    _FILTER_VIDEO: "video",
                    _FILTER_AUDIO: "audio",
                }.get(self._filter, "item")
                bits = [f"{n} {label}{'s' if n != 1 else ''}"]
            if total != n:
                bits.append(f"{total} total")
            if self._job_filter:
                bits.append(f"job “{self._job_filter}”")
            self._count.value = " · ".join(bits)
        if hidden:
            self._count.value += f" · {hidden} missing hidden"
        # Keep spend chips in sync when list reloads
        try:
            ref = getattr(self.spend_panel, "data", None) or {}
            fn = ref.get("refresh") if isinstance(ref, dict) else None
            if callable(fn):
                fn()
        except Exception:
            pass

        cards: list[ft.Control] = []
        # Drop selection ids that are no longer visible / in history
        visible_set = {e.id for e in entries if e.id}
        self._selected_ids = {i for i in self._selected_ids if i in visible_set}
        self._visible_ids = [e.id for e in entries if e.id]
        # Optional visual group headers by job when not filtering a single job
        last_job_header: str | None = None
        for entry in entries:
            j = (entry.job or "").strip() or "(No job)"
            if not self._job_filter and j != last_job_header:
                last_job_header = j
                cards.append(
                    ft.Text(
                        j if j != "(No job)" else "Ungrouped (no Job / Listing)",
                        size=FONT_SM,
                        color=ACCENT_BRIGHT,
                        weight=ft.FontWeight.W_700,
                    )
                )
            cards.append(self._card_for(entry))
        if not cards:
            cards = [
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Icon(ft.Icons.PHOTO_LIBRARY_OUTLINED, size=40, color=TEXT_MUTED),
                            ft.Text(
                                self._empty_message(),
                                color=TEXT_MUTED,
                                size=FONT_SM,
                                text_align=ft.TextAlign.CENTER,
                            ),
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=8,
                    ),
                    alignment=ft.Alignment.CENTER,
                    padding=40,
                )
            ]
        self._list.controls = cards
        self._sync_bulk_bar()

    async def _on_refresh(self, _e: ft.ControlEvent) -> None:
        self.refresh()
        try:
            ref = getattr(self.spend_panel, "data", None) or {}
            fn = ref.get("refresh") if isinstance(ref, dict) else None
            if callable(fn):
                fn()
        except Exception:
            pass
        self._status.value = "Library refreshed."
        self.page.update()

    def _thumb_for(self, entry: HistoryEntry) -> ft.Control:
        media = entry.media_type
        img = first_image_path(entry)
        vid = first_video_path(entry)
        src: str | None = img
        if not src and vid:
            try:
                src = video_poster_path(vid)
            except Exception:
                src = None
        if src and Path(src).is_file():
            return ft.Image(
                src=src,
                width=140,
                height=90,
                fit=ft.BoxFit.COVER,
                border_radius=6,
            )
        if media == "Video":
            icon = ft.Icons.MOVIE
        elif media == "Audio":
            icon = ft.Icons.AUDIO_FILE
        else:
            icon = ft.Icons.IMAGE
        return ft.Container(
            content=ft.Icon(icon, color=TEXT_MUTED, size=32),
            width=140,
            height=90,
            bgcolor=PANEL_ELEVATED,
            border_radius=6,
            border=ft.Border.all(1, BORDER),
            alignment=ft.Alignment.CENTER,
        )

    def _card_for(self, entry: HistoryEntry) -> ft.Control:
        media = entry.media_type
        ts = format_timestamp(entry.timestamp) or entry.timestamp
        model = entry.model or "—"
        scenario = entry.scenario or ""
        cost = entry.cost_estimate or ""
        prompt_short = " ".join((entry.prompt or "").split())
        if len(prompt_short) > 100:
            prompt_short = prompt_short[:97] + "…"

        if media == "Image":
            badge_color = ACCENT
        elif media == "Video":
            badge_color = "#6b4c9a"
        else:
            badge_color = "#2e7d6f"
        from_resolve = bool(
            getattr(entry, "is_from_resolve", False)
            or (entry.origin or "").strip().lower() == "resolve"
        )
        meta_bits = [media, model]
        job = (entry.job or "").strip()
        if job:
            meta_bits.append(f"Job: {job}")
        if scenario:
            meta_bits.append(scenario)
        if ts:
            meta_bits.append(ts)
        if cost:
            meta_bits.append(cost)

        primary = entry.primary_path()
        img_path = first_image_path(entry)
        vid_path = first_video_path(entry)
        aud_path = first_audio_path(entry)

        actions: list[ft.Control] = []

        # Assign to Job / Listing (all media types) — single-card (unchanged)
        assign_menu = self._make_assign_menu(entry)
        if assign_menu is not None:
            actions.append(assign_menu)

        # Audio: play in-app, folder, Resolve (no image/video Send-to tools)
        if media == "Audio" and aud_path:
            actions.append(
                ft.OutlinedButton(
                    content="Play",
                    icon=ft.Icons.PLAY_ARROW,
                    on_click=self._make_play_audio(aud_path),
                    style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
                )
            )
            actions.append(
                ft.OutlinedButton(
                    content="Show in folder",
                    icon=ft.Icons.FOLDER_OPEN,
                    on_click=self._make_show_folder(aud_path),
                    style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
                )
            )
            actions.append(
                ft.OutlinedButton(
                    content="Send to Resolve",
                    icon=ft.Icons.SEND,
                    on_click=self._make_send_resolve(aud_path),
                    style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
                )
            )
        else:
            # Single “Send to ▾” menu — destinations depend on media type
            send_menu = self._make_send_menu(img_path=img_path, vid_path=vid_path)
            if send_menu is not None:
                actions.append(send_menu)

            if primary:
                actions.append(
                    ft.OutlinedButton(
                        content="Show in folder",
                        icon=ft.Icons.FOLDER_OPEN,
                        on_click=self._make_show_folder(primary),
                        style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
                    )
                )

                if img_path or (vid_path and first_image_path(entry) is None):
                    open_path = img_path or video_poster_path(vid_path) or primary
                    if open_path:
                        actions.append(
                            ft.TextButton(
                                content="Open large",
                                icon=ft.Icons.OPEN_IN_FULL,
                                on_click=self._make_open_large(
                                    open_path, is_video=bool(vid_path and not img_path)
                                ),
                                style=ft.ButtonStyle(color=ACCENT_BRIGHT),
                            )
                        )

        badges: list[ft.Control] = [
            ft.Container(
                content=ft.Text(
                    media,
                    size=11,
                    color=TEXT,
                    weight=ft.FontWeight.W_700,
                ),
                bgcolor=badge_color,
                border_radius=4,
                padding=ft.Padding.symmetric(horizontal=8, vertical=2),
            ),
        ]
        if from_resolve:
            badges.append(
                ft.Container(
                    content=ft.Text(
                        "Resolve",
                        size=11,
                        color=TEXT,
                        weight=ft.FontWeight.W_700,
                    ),
                    bgcolor=_RESOLVE_BADGE,
                    border_radius=4,
                    padding=ft.Padding.symmetric(horizontal=8, vertical=2),
                    tooltip="Imported from Resolve handoff",
                )
            )

        eid = entry.id or ""
        selected = bool(eid and eid in self._selected_ids)
        check = ft.Checkbox(
            value=selected,
            on_change=self._make_toggle_select(eid) if eid else None,
            tooltip="Select for bulk Assign or Send to Resolve",
        )

        return ft.Container(
            content=ft.Row(
                [
                    check,
                    self._thumb_for(entry),
                    ft.Column(
                        [
                            ft.Row(
                                [
                                    *badges,
                                    ft.Text(
                                        " · ".join(meta_bits[1:]),
                                        size=FONT_SM,
                                        color=TEXT_MUTED,
                                        expand=True,
                                        max_lines=1,
                                        overflow=ft.TextOverflow.ELLIPSIS,
                                    ),
                                ],
                                spacing=8,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                            ft.Text(
                                prompt_short or "(no prompt)",
                                size=FONT_SM,
                                color=TEXT,
                                max_lines=2,
                                overflow=ft.TextOverflow.ELLIPSIS,
                            ),
                            ft.Row(actions, spacing=6, wrap=True),
                        ],
                        spacing=6,
                        expand=True,
                        tight=True,
                    ),
                ],
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.START,
            ),
            bgcolor="#1a2435" if selected else PANEL_ELEVATED,
            border=ft.Border.all(2 if selected else 1, ACCENT if selected else BORDER),
            border_radius=8,
            padding=12,
        )

    def _make_toggle_select(self, entry_id: str):
        def _on_change(e: ft.ControlEvent) -> None:
            if not entry_id:
                return
            checked = bool(getattr(e.control, "value", False))
            if checked:
                self._selected_ids.add(entry_id)
            else:
                self._selected_ids.discard(entry_id)
            self._sync_bulk_bar()
            # Light refresh of card borders without full history reload
            try:
                self.refresh()
                self.page.update()
            except Exception:
                pass

        return _on_change

    def _sync_bulk_bar(self) -> None:
        n = len(self._selected_ids)
        self._bulk_count.value = f"{n} selected"
        self._bulk_bar.visible = n > 0
        self._rebuild_bulk_assign_menu()

    def _rebuild_bulk_assign_menu(self) -> None:
        """Same menu shape as single-card Assign, applied to all selected ids."""
        items: list[ft.Control] = [
            ft.PopupMenuItem(
                content="New Job / Listing…",
                on_click=self._on_bulk_new_job_click,
            ),
        ]
        jobs = list_job_names(self.state.output_dir)
        if jobs:
            items.append(ft.PopupMenuItem())
            for name in jobs:
                items.append(
                    ft.PopupMenuItem(
                        content=name,
                        on_click=self._make_bulk_assign_to(name),
                    )
                )
        items.append(ft.PopupMenuItem())
        items.append(
            ft.PopupMenuItem(
                content="Clear job (Ungrouped)",
                on_click=self._make_bulk_assign_to(""),
            )
        )
        menu = ft.Container(
            content=ft.PopupMenuButton(
                content=ft.Row(
                    [
                        ft.Icon(ft.Icons.FOLDER_SPECIAL_OUTLINED, size=16, color=TEXT),
                        ft.Text("Assign to ▾", size=FONT_SM, color=TEXT),
                    ],
                    spacing=6,
                    tight=True,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                items=items,
                tooltip="Assign all selected items to a Job / Listing",
                menu_position=ft.PopupMenuPosition.UNDER,
            ),
            bgcolor=PANEL_ELEVATED,
            border=ft.Border.all(1, BORDER),
            border_radius=6,
            padding=ft.Padding.symmetric(horizontal=10, vertical=6),
        )
        self._bulk_assign_host.content = menu

    def _make_bulk_assign_to(self, job_name: str):
        async def _click(_e: ft.ControlEvent) -> None:
            await self._assign_jobs_bulk(job_name)

        return _click

    async def _on_bulk_new_job_click(self, _e: ft.ControlEvent) -> None:
        await self._prompt_new_job_bulk()

    async def _on_select_all_visible(self, _e: ft.ControlEvent) -> None:
        for eid in self._visible_ids:
            if eid:
                self._selected_ids.add(eid)
        self.refresh()
        try:
            self.page.update()
        except Exception:
            pass

    async def _on_clear_selection(self, _e: ft.ControlEvent) -> None:
        self._selected_ids.clear()
        self.refresh()
        try:
            self.page.update()
        except Exception:
            pass

    async def _on_bulk_send_resolve(self, _e: ft.ControlEvent) -> None:
        """Send each selected Library item to Resolve (Tier A); continue on failures."""
        ids = [i for i in self._selected_ids if i]
        if not ids:
            self._on_action_status("Select one or more Library items first.", True)
            return

        # Disable while running
        try:
            self.btn_bulk_resolve.disabled = True
            self.page.update()
        except Exception:
            pass

        sent = 0
        skipped = 0
        skip_reasons: list[str] = []

        job = getattr(self.state, "job_name", None) or None
        try:
            from media_studio.ui_prefs import get_job_name

            if not job:
                job = get_job_name() or None
        except Exception:
            pass

        def _send_one(entry: HistoryEntry) -> tuple[bool, str]:
            from media_studio.resolve_export import send_file_to_resolve

            path = entry.primary_path()
            if not path:
                # Prefer any existing file on the entry
                for f in entry.files or []:
                    try:
                        if f and Path(f).is_file():
                            path = f
                            break
                    except OSError:
                        continue
            if not path or not Path(path).is_file():
                return False, "missing file"
            # Prefer entry job for bin leaf when set; else app job
            entry_job = (entry.job or "").strip() or job
            result = send_file_to_resolve(
                path,
                job_name=entry_job,
                model=entry.model or None,
                scenario=entry.scenario or None,
                cost=entry.cost_estimate or None,
                output_dir=self.state.output_dir,
            )
            if result.ok:
                return True, result.message
            # Soft fail — still count as skipped for summary
            reason = result.message or "Resolve import failed"
            # Keep reason short for snack
            low = reason.lower()
            if (
                "not running" in low
                or "scripting" in low
                or "could not connect" in low
                or "unavailable" in low
            ):
                short = "Resolve unavailable"
            elif "no project" in low or "project open" in low:
                short = "no project open"
            elif "missing" in low or "not found" in low:
                short = "file missing"
            else:
                short = reason.split(".")[0][:48]
            return False, short

        # Failures that mean the rest of the batch will also fail — stop early
        _STOP_BULK = frozenset({"Resolve unavailable", "no project open"})

        aborted_rest = 0
        try:
            for eid in ids:
                entry = find_by_id(eid, self.state.output_dir)
                if entry is None:
                    skipped += 1
                    skip_reasons.append("not found")
                    continue
                try:
                    ok, detail = await asyncio.to_thread(_send_one, entry)
                except Exception as exc:
                    ok = False
                    detail = str(exc)[:48]
                if ok:
                    sent += 1
                else:
                    skipped += 1
                    if detail and detail not in skip_reasons:
                        skip_reasons.append(detail)
                    # Don't soft-fail every card when Resolve is closed / no project
                    if detail in _STOP_BULK:
                        rest = len(ids) - (sent + skipped)
                        if rest > 0:
                            aborted_rest = rest
                            skipped += rest
                        break
        finally:
            try:
                self.btn_bulk_resolve.disabled = False
            except Exception:
                pass

        total = len(ids)
        if aborted_rest and sent == 0:
            reason = skip_reasons[0] if skip_reasons else "Resolve unavailable"
            summary = (
                f"Stopped: {reason}. "
                f"0 sent · {total} selected (open Resolve with a project, then retry)."
            )
        elif aborted_rest and sent:
            reason = skip_reasons[0] if skip_reasons else "Resolve unavailable"
            summary = (
                f"{sent} sent, then stopped ({reason}). "
                f"{skipped} not sent of {total} selected."
            )
        elif sent and not skipped:
            summary = f"Sent {sent} item{'s' if sent != 1 else ''} to Resolve."
        elif sent and skipped:
            reason = skip_reasons[0] if skip_reasons else "error"
            summary = (
                f"{sent} sent to Resolve, {skipped} skipped"
                f" ({reason}"
                + (f" +{len(skip_reasons) - 1} more" if len(skip_reasons) > 1 else "")
                + ")."
            )
        else:
            reason = skip_reasons[0] if skip_reasons else "no media"
            summary = f"0 sent, {skipped}/{total} skipped ({reason})."

        self._on_action_status(summary, sent == 0)
        try:
            show_snack(self.page, summary)
        except Exception:
            pass
        # Keep selection so user can retry skipped items; clear only on full success
        if skipped == 0 and sent > 0:
            self._selected_ids.clear()
        self.refresh()
        try:
            self.page.update()
        except Exception:
            pass

    async def _assign_jobs_bulk(self, job_name: str) -> None:
        ids = [i for i in self._selected_ids if i]
        if not ids:
            self._on_action_status("Select one or more Library items first.", True)
            return
        ok = 0
        notes: list[str] = []
        for eid in ids:
            try:
                _entry, msg = assign_entry_job(
                    eid,
                    job_name or None,
                    output_dir=self.state.output_dir,
                    move_files=True,
                )
                if _entry is not None:
                    ok += 1
                if msg and "Already" not in msg:
                    notes.append(msg)
            except Exception as exc:
                notes.append(f"{eid}: {exc}")
        label = (job_name or "").strip()
        if label:
            summary = f"Assigned {ok}/{len(ids)} to job “{label}”."
        else:
            summary = f"Cleared job on {ok}/{len(ids)} item(s)."
        if notes and ok < len(ids):
            summary += " " + "; ".join(notes[:2])
        self._selected_ids.clear()
        self._on_action_status(summary, ok == 0)
        try:
            show_snack(self.page, summary)
        except Exception:
            pass
        self.refresh()
        try:
            self.page.update()
        except Exception:
            pass

    async def _prompt_new_job_bulk(self) -> None:
        n = len(self._selected_ids)
        if n < 1:
            self._on_action_status("Select items first.", True)
            return
        name_field = ft.TextField(
            label="Job / Listing name",
            hint_text="e.g. 123 Oak St · Smith · 2026-08-01",
            dense=True,
            filled=True,
            fill_color=PANEL_ELEVATED,
            border_color=BORDER,
            color=TEXT,
            text_size=FONT_SM,
            autofocus=True,
        )
        err = ft.Text("", size=FONT_SM, color="#e57373")

        async def _cancel(_e: ft.ControlEvent) -> None:
            close_dialog(self.page, dlg)

        async def _ok(_e: ft.ControlEvent) -> None:
            name = (name_field.value or "").strip()
            if not name:
                err.value = "Enter a name."
                try:
                    self.page.update()
                except Exception:
                    pass
                return
            close_dialog(self.page, dlg)
            await self._assign_jobs_bulk(name)

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("New Job / Listing", color=TEXT),
            content=ft.Column(
                [
                    ft.Text(
                        f"Assign {n} selected item(s) to a new job. Media under the "
                        "output folder moves into jobs/<name>/ when safe.",
                        size=FONT_SM,
                        color=TEXT_MUTED,
                    ),
                    name_field,
                    err,
                ],
                tight=True,
                spacing=10,
                width=400,
            ),
            actions=[
                ft.TextButton(content="Cancel", on_click=_cancel),
                ft.FilledButton(
                    content=f"Assign {n}",
                    on_click=_ok,
                    style=ft.ButtonStyle(bgcolor=ACCENT_BRIGHT, color=TEXT),
                ),
            ],
        )
        show_dialog(self.page, dlg)

    def _on_action_status(self, msg: str, is_err: bool = False) -> None:
        self._status.value = msg
        self._status.color = "#e57373" if is_err else TEXT_MUTED
        try:
            self.page.update()
        except Exception:
            pass

    def _make_assign_menu(self, entry: HistoryEntry) -> ft.Control | None:
        """Assign to Job / Listing — existing names, New…, Clear."""
        items: list[ft.Control] = [
            ft.PopupMenuItem(
                content="New Job / Listing…",
                on_click=self._make_new_job_assign(entry.id),
            ),
        ]
        jobs = list_job_names(self.state.output_dir)
        current = (entry.job or "").strip()
        if jobs:
            items.append(ft.PopupMenuItem())  # separator
            for name in jobs:
                label = f"✓ {name}" if name == current else name
                items.append(
                    ft.PopupMenuItem(
                        content=label,
                        on_click=self._make_assign_to(entry.id, name),
                    )
                )
        if current:
            items.append(ft.PopupMenuItem())
            items.append(
                ft.PopupMenuItem(
                    content="Clear job (Ungrouped)",
                    on_click=self._make_assign_to(entry.id, ""),
                )
            )
        return ft.Container(
            content=ft.PopupMenuButton(
                content=ft.Row(
                    [
                        ft.Icon(ft.Icons.FOLDER_SPECIAL_OUTLINED, size=16, color=TEXT),
                        ft.Text("Assign to ▾", size=FONT_SM, color=TEXT),
                    ],
                    spacing=6,
                    tight=True,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                items=items,
                tooltip="File this item under a Job / Listing (or create a new one)",
                menu_position=ft.PopupMenuPosition.UNDER,
            ),
            bgcolor=PANEL_ELEVATED,
            border=ft.Border.all(1, BORDER),
            border_radius=6,
            padding=ft.Padding.symmetric(horizontal=10, vertical=6),
        )

    def _make_assign_to(self, entry_id: str, job_name: str):
        async def _click(_e: ft.ControlEvent) -> None:
            await self._assign_job(entry_id, job_name)

        return _click

    def _make_new_job_assign(self, entry_id: str):
        async def _click(_e: ft.ControlEvent) -> None:
            await self._prompt_new_job(entry_id)

        return _click

    async def _assign_job(self, entry_id: str, job_name: str) -> None:
        try:
            _entry, msg = assign_entry_job(
                entry_id,
                job_name or None,
                output_dir=self.state.output_dir,
                move_files=True,
            )
            self._on_action_status(msg, False)
            try:
                show_snack(self.page, msg)
            except Exception:
                pass
        except Exception as exc:
            self._on_action_status(f"Assign failed: {exc}", True)
            return
        self.refresh()
        try:
            self.page.update()
        except Exception:
            pass

    async def _prompt_new_job(self, entry_id: str) -> None:
        name_field = ft.TextField(
            label="Job / Listing name",
            hint_text="e.g. 123 Oak St · Smith · 2026-08-01",
            dense=True,
            filled=True,
            fill_color=PANEL_ELEVATED,
            border_color=BORDER,
            color=TEXT,
            text_size=FONT_SM,
            autofocus=True,
        )
        err = ft.Text("", size=FONT_SM, color="#e57373")

        async def _cancel(_e: ft.ControlEvent) -> None:
            close_dialog(self.page, dlg)

        async def _ok(_e: ft.ControlEvent) -> None:
            name = (name_field.value or "").strip()
            if not name:
                err.value = "Enter a name."
                try:
                    self.page.update()
                except Exception:
                    pass
                return
            close_dialog(self.page, dlg)
            await self._assign_job(entry_id, name)

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("New Job / Listing", color=TEXT),
            content=ft.Column(
                [
                    ft.Text(
                        "Assign this Library item to a new job. Media under the "
                        "output folder moves into jobs/<name>/ when safe.",
                        size=FONT_SM,
                        color=TEXT_MUTED,
                    ),
                    name_field,
                    err,
                ],
                tight=True,
                spacing=10,
                width=400,
            ),
            actions=[
                ft.TextButton(content="Cancel", on_click=_cancel),
                ft.FilledButton(
                    content="Assign",
                    on_click=_ok,
                    style=ft.ButtonStyle(bgcolor=ACCENT_BRIGHT, color=TEXT),
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        show_dialog(self.page, dlg)

    def _make_send_menu(
        self,
        *,
        img_path: str | None,
        vid_path: str | None,
    ) -> ft.Control | None:
        """Shared destination matrix (Phase C)."""
        from media_studio.flet_send_to import (
            build_send_menu_items,
            make_send_menu_button,
        )

        items = build_send_menu_items(
            self.state,
            image_path=img_path,
            video_path=vid_path,
            status_cb=lambda m: self._on_action_status(m, False),
            status_cb_err=self._on_action_status,
        )
        btn = make_send_menu_button(items)
        if btn is None:
            return None
        return btn

    def _make_send_image(self, path: str) -> Callable:
        async def _click(_e: ft.ControlEvent) -> None:
            iv = getattr(self.state, "image_view", None)
            if iv is not None and hasattr(iv, "load_source_path"):
                ok = iv.load_source_path(
                    path, status=f"Library → Image source: {Path(path).name}"
                )
                if not ok:
                    self._on_action_status(f"Could not load image: {path}", True)
                    return
            else:
                self.state.source_path = str(Path(path).resolve())
            switch = getattr(self.state, "switch_to_image", None)
            if switch:
                switch()
            self._on_action_status(f"Sent to Image: {Path(path).name}")
            try:
                show_snack(self.page, f"Sent to Image: {Path(path).name}")
            except Exception:
                pass

        return _click

    def _make_send_video_ref(self, path: str) -> Callable:
        async def _click(_e: ft.ControlEvent) -> None:
            resolved = str(Path(path).resolve())
            self.state.video_ref_path = resolved
            vv = getattr(self.state, "video_view", None)
            if vv is not None:
                if hasattr(vv, "open_received"):
                    vv.open_received(
                        ref_path=resolved,
                        scenario_label=self.state.scenario_label,
                    )
                elif hasattr(vv, "receive_from_image"):
                    vv.receive_from_image(
                        ref_path=resolved,
                        scenario_label=self.state.scenario_label,
                    )
            switch = getattr(self.state, "switch_to_video", None)
            if switch:
                switch()
            self._on_action_status(f"Sent to Video → Received: {Path(path).name}")
            try:
                show_snack(self.page, f"Sent to Video (Received): {Path(path).name}")
            except Exception:
                pass

        return _click

    def _make_send_video_source(self, path: str) -> Callable:
        async def _click(_e: ft.ControlEvent) -> None:
            vv = getattr(self.state, "video_view", None)
            ok = False
            if vv is not None and hasattr(vv, "load_source_video"):
                ok = vv.load_source_video(
                    path,
                    clip_name=Path(path).name,
                    status=f"Library → Video source: {Path(path).name}",
                    record=False,
                )
            else:
                if Path(path).is_file():
                    self.state.video_source_path = str(Path(path).resolve())
                    ok = True
            switch = getattr(self.state, "switch_to_video", None)
            if switch:
                switch()
            if ok:
                self._on_action_status(f"Sent to Video as source: {Path(path).name}")
                try:
                    show_snack(self.page, f"Sent to Video (source): {Path(path).name}")
                except Exception:
                    pass
            else:
                self._on_action_status(f"Could not load video: {path}", True)

        return _click

    def _make_send_region(self, path: str) -> Callable:
        async def _click(_e: ft.ControlEvent) -> None:
            iv = getattr(self.state, "image_view", None)
            ok = False
            if iv is not None and hasattr(iv, "enter_region_mode"):
                ok = bool(iv.enter_region_mode(path))
            switch = getattr(self.state, "switch_to_image", None)
            if switch:
                try:
                    switch(modality="region")
                except TypeError:
                    switch()
            if ok:
                self._on_action_status(f"Sent to Region edit: {Path(path).name}")
                try:
                    show_snack(self.page, f"Region edit: {Path(path).name}")
                except Exception:
                    pass
            else:
                self._on_action_status(f"Could not open Region edit: {Path(path).name}", True)

        return _click

    def _make_send_tool(
        self, tool_id: str, path: str, *, as_video: bool = False
    ) -> Callable:
        async def _click(_e: ft.ControlEvent) -> None:
            tv = getattr(self.state, "tools_view", None)
            ok = False
            if tv is not None and hasattr(tv, "receive_media"):
                ok = bool(tv.receive_media(tool_id, path, as_video=as_video))
            switch = getattr(self.state, "switch_to_tools", None)
            if switch:
                switch(tool_id)
            labels = {
                "upscale": "Upscale",
                "cleanup": "Object Remove",
                "sky": "Sky / Weather",
                "dehaze": "Dehaze",
                "restore": "Sharpen / Restore",
                "blown_out": "Blown Out Repair",
                "mirror": "Mirror / Glass",
                "amenity": "Amenity On",
                "season": "Season / Curb",
                "match_look": "Match Source Look",
                "reaspect": "Re-Aspect",
            }
            label = labels.get(tool_id, tool_id)
            if ok:
                self._on_action_status(f"Sent to Tools → {label}: {Path(path).name}")
                try:
                    show_snack(self.page, f"Sent to {label}: {Path(path).name}")
                except Exception:
                    pass
            else:
                self._on_action_status(
                    f"Could not load into {label}: {Path(path).name}", True
                )

        return _click

    def _make_send_frame_editor(
        self, path: str, *, as_video: bool = False
    ) -> Callable:
        async def _click(_e: ft.ControlEvent) -> None:
            ctx = getattr(self.state, "frame_editor_return", None)
            switch = getattr(self.state, "switch_to_frame_editor", None)
            if switch:
                if as_video:
                    switch(video_path=path)
                else:
                    switch(keyframe_path=path)
            else:
                fe = getattr(self.state, "frame_editor_view", None)
                if fe is None:
                    self._on_action_status("Frame Editor not available", True)
                    return
                if as_video and hasattr(fe, "load_source"):
                    fe.load_source(path)
                elif hasattr(fe, "receive_keyframe"):
                    fe.receive_keyframe(path)
                elif hasattr(fe, "add_keyframe"):
                    fe.add_keyframe(path, pin="first")
            kind = "source video" if as_video else "keyframe"
            if not as_video and isinstance(ctx, dict) and ctx:
                pin = ctx.get("pin", "first")
                self._on_action_status(
                    f"Sent to Frame Editor ({kind}, pin={pin}): {Path(path).name}"
                )
            else:
                self._on_action_status(
                    f"Sent to Frame Editor ({kind}): {Path(path).name}"
                )
            try:
                show_snack(self.page, f"Frame Editor ← {Path(path).name}")
            except Exception:
                pass

        return _click

    def _make_send_resolve(self, path: str) -> Callable:
        async def _click(_e: ft.ControlEvent) -> None:
            try:
                from media_studio.resolve_export import send_file_to_resolve

                job = getattr(self.state, "job_name", None) or None
                result = await asyncio.to_thread(
                    send_file_to_resolve,
                    path,
                    job_name=job,
                    output_dir=self.state.output_dir,
                )
                msg = getattr(result, "message", None) or str(result)
                ok = bool(getattr(result, "ok", True))
                self._on_action_status(msg, not ok)
                try:
                    show_snack(self.page, msg)
                except Exception:
                    pass
            except Exception as exc:
                self._on_action_status(f"Send to Resolve failed: {exc}", True)

        return _click

    def _make_play_audio(self, path: str) -> Callable:
        async def _click(_e: ft.ControlEvent) -> None:
            try:
                from media_studio.flet_audio_player import mixer_play

                p = Path(path)
                if not p.is_file():
                    self._on_action_status(f"Missing: {path}", True)
                    return
                msg = mixer_play(str(p.resolve()))
                is_err = msg.lower().startswith(("play failed", "playback unavailable", "file not found"))
                self._on_action_status(msg, is_err)
                if not is_err:
                    try:
                        show_snack(self.page, msg)
                    except Exception:
                        pass
            except Exception as exc:
                self._on_action_status(f"Play failed: {exc}", True)

        return _click

    def _make_show_folder(self, path: str) -> Callable:
        async def _click(_e: ft.ControlEvent) -> None:
            msg = show_in_folder(path)
            self._on_action_status(msg)
            try:
                show_snack(self.page, msg)
            except Exception:
                pass

        return _click

    def _make_open_large(self, path: str, *, is_video: bool = False) -> Callable:
        async def _click(_e: ft.ControlEvent) -> None:
            from media_studio.flet_dialogs import show_dialog, close_dialog

            p = Path(path)
            if not p.is_file():
                self._on_action_status(f"Missing: {path}", True)
                return
            if is_video or p.suffix.lower() in {".mp4", ".mov", ".webm", ".m4v", ".avi", ".mkv"}:
                # Prefer in-app VideoResultPlayer dialog; folder is secondary
                try:
                    from media_studio.flet_video_player import VideoResultPlayer

                    player = VideoResultPlayer(self.page, height=480)
                    player.set_result(str(p.resolve()), note=p.name)
                    player.control.expand = False
                    player.control.height = 520

                    def _close(_ev: Any = None) -> None:
                        try:
                            player.clear()
                        except Exception:
                            pass
                        close_dialog(self.page, dlg)

                    dlg = ft.AlertDialog(
                        modal=True,
                        title=ft.Text(p.name, color=TEXT, size=FONT_SM),
                        bgcolor=PANEL,
                        content=ft.Container(
                            content=player.control,
                            width=960,
                            height=540,
                            bgcolor="#0a0c10",
                        ),
                        actions=[
                            ft.TextButton(
                                content="Show in folder",
                                on_click=self._make_show_folder(str(p)),
                                style=ft.ButtonStyle(color=TEXT_MUTED),
                            ),
                            ft.TextButton(
                                content="Close",
                                on_click=_close,
                                style=ft.ButtonStyle(color=ACCENT_BRIGHT),
                            ),
                        ],
                    )
                    show_dialog(self.page, dlg)
                    self._on_action_status(f"Playing: {p.name}")
                except Exception as exc:
                    self._on_action_status(
                        f"In-app play failed ({exc}) — use Show in folder", True
                    )
                return

            dlg = ft.AlertDialog(
                title=ft.Text(p.name, color=TEXT, size=FONT_SM),
                bgcolor=PANEL,
                content=ft.Container(
                    content=ft.Image(src=str(p.resolve()), fit=ft.BoxFit.CONTAIN),
                    width=900,
                    height=600,
                    bgcolor="#0a0c10",
                ),
                actions=[
                    ft.TextButton(
                        content="Close",
                        on_click=lambda e: self._close_dlg(dlg),
                        style=ft.ButtonStyle(color=ACCENT_BRIGHT),
                    )
                ],
            )
            self.page.overlay.append(dlg)
            dlg.open = True
            self.page.update()

        return _click

    def _close_dlg(self, dlg: ft.AlertDialog) -> None:
        dlg.open = False
        try:
            self.page.update()
        except Exception:
            pass
        try:
            if dlg in self.page.overlay:
                self.page.overlay.remove(dlg)
        except Exception:
            pass
