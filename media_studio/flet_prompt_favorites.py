"""
Light Prompt favorites strip: Star · Favorites ▾ · Apply · Export/Import pack.

Reuse across Studio, Creative Vision, Tools, Audio, Frame Editor.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import flet as ft

from media_studio.flet_pickers import pick_files, pick_save_path
from media_studio.flet_theme import (
    BORDER,
    FONT_SM,
    PANEL_ELEVATED,
    TEXT,
    TEXT_MUTED,
    dropdown_options,
    styled_dropdown,
)
from media_studio.prompt_favorites import (
    add_favorite,
    export_pack,
    favorite_choices,
    find_favorite,
    import_pack,
    read_pack_file,
    safe_pack_filename,
    write_pack_file,
)

GetText = Callable[[], str | None]
SetText = Callable[[str], None]
GetMeta = Callable[[], dict[str, str]]
StatusCb = Callable[[str], None]


class PromptFavoritesBar:
    """
    Compact row under a prompt field.

    - ★ Star: save current prompt text as favorite
    - Favorites dropdown + Apply: load into the bound prompt field
    - Export / Import: JSON prompt pack (app-data favorites; packs are user files)
    """

    def __init__(
        self,
        page: ft.Page,
        *,
        get_text: GetText,
        set_text: SetText,
        surface: str = "other",
        get_meta: GetMeta | None = None,
        on_status: StatusCb | None = None,
        show_pack_buttons: bool = True,
    ) -> None:
        self.page = page
        self.get_text = get_text
        self.set_text = set_text
        self.surface = surface
        self.get_meta = get_meta
        self.on_status = on_status
        self._none = "(Favorites)"

        # expand=False on Dropdown: inside ListView rails, expand=True was taken as
        # vertical flex and painted a tall empty PANEL_ELEVATED slab under ★ Star.
        self.fav_dd = styled_dropdown(
            label_text="Favorites",
            options=[self._none],
            value=self._none,
            expand=False,
        )
        self.btn_star = ft.OutlinedButton(
            content="★ Star",
            icon=ft.Icons.STAR_OUTLINE,
            on_click=self._on_star,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
            height=34,
            tooltip="Save current prompt as a favorite (user or enhanced text)",
        )
        self.btn_apply = ft.OutlinedButton(
            content="Apply",
            icon=ft.Icons.INPUT,
            on_click=self._on_apply,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
            height=34,
            tooltip="Load the selected favorite into the prompt box",
        )
        pack_btns: list[ft.Control] = []
        if show_pack_buttons:
            self.btn_export = ft.TextButton(
                content="Export pack",
                icon=ft.Icons.UPLOAD_FILE,
                on_click=self._on_export,
                style=ft.ButtonStyle(color=TEXT_MUTED),
                tooltip="Export favorites to a small JSON prompt pack",
            )
            self.btn_import = ft.TextButton(
                content="Import pack",
                icon=ft.Icons.DOWNLOAD,
                on_click=self._on_import,
                style=ft.ButtonStyle(color=TEXT_MUTED),
                tooltip="Import a JSON prompt pack into favorites",
            )
            pack_btns = [self.btn_export, self.btn_import]
        else:
            self.btn_export = None
            self.btn_import = None

        # Horizontal fill only: Container.expand in a Row; height-capped so it
        # cannot become a tall elevated void under Star.
        fav_slot = ft.Container(
            content=self.fav_dd,
            expand=True,
            height=40,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
            alignment=ft.Alignment.CENTER_LEFT,
        )
        self.root = ft.Container(
            content=ft.Row(
                [
                    self.btn_star,
                    fav_slot,
                    self.btn_apply,
                    *pack_btns,
                ],
                spacing=6,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                wrap=False,
                tight=True,
            ),
            padding=ft.Padding.only(top=2, bottom=2),
            expand=False,
            # No bgcolor — never an empty PANEL_ELEVATED spacer under Star
        )
        self.refresh()

    def _status(self, msg: str) -> None:
        if self.on_status:
            try:
                self.on_status(msg)
            except Exception:
                pass

    def _meta(self) -> dict[str, str]:
        if not self.get_meta:
            return {}
        try:
            m = self.get_meta() or {}
            return {str(k): str(v or "") for k, v in m.items()}
        except Exception:
            return {}

    def refresh(self) -> None:
        choices = favorite_choices()
        labels = [self._none] + [lab for lab, _ in choices]
        self.fav_dd.options = dropdown_options(labels)
        # Keep selection if still present
        cur = str(self.fav_dd.value or self._none)
        if cur not in labels:
            self.fav_dd.value = self._none
        # Map label → id for apply
        self._label_to_id = {lab: i for lab, i in choices}

    def _selected_id(self) -> str | None:
        lab = str(self.fav_dd.value or "").strip()
        if not lab or lab == self._none:
            return None
        return getattr(self, "_label_to_id", {}).get(lab)

    async def _on_star(self, _e: ft.ControlEvent) -> None:
        text = (self.get_text() or "").strip()
        if not text:
            self._status("Nothing to star — enter a prompt first.")
            try:
                self.page.update()
            except Exception:
                pass
            return
        meta = self._meta()
        # Heuristic: long enhanced-style rewrites still just "user" unless marked
        source = meta.get("source") or "user"
        fav = add_favorite(
            text,
            source=source,
            surface=self.surface or meta.get("surface") or "other",
            scenario=meta.get("scenario") or "",
            model=meta.get("model") or "",
            label=meta.get("label") or "",
        )
        self.refresh()
        if fav:
            self.fav_dd.value = fav.label
            self._status(f"Starred favorite: {fav.label}")
        else:
            self._status("Could not save favorite.")
        try:
            self.page.update()
        except Exception:
            pass

    async def _on_apply(self, _e: ft.ControlEvent) -> None:
        fid = self._selected_id()
        fav = find_favorite(fid) if fid else None
        if fav is None:
            # try by label
            fav = find_favorite(str(self.fav_dd.value or ""))
        if fav is None or not fav.text.strip():
            self._status("Pick a favorite first.")
            try:
                self.page.update()
            except Exception:
                pass
            return
        self.set_text(fav.text)
        self._status(f"Loaded favorite: {fav.label}")
        try:
            self.page.update()
        except Exception:
            pass

    async def _on_export(self, _e: ft.ControlEvent) -> None:
        choices = favorite_choices()
        if not choices:
            self._status("No favorites to export — star a prompt first.")
            try:
                self.page.update()
            except Exception:
                pass
            return
        pack = export_pack(name="AI Media Studio prompts", include_all=True)
        path = await pick_save_path(
            self.page,
            dialog_title="Export prompt pack",
            defaultextension=".json",
            initialfile=safe_pack_filename(pack.name),
            filetypes=[("JSON pack", "*.json"), ("All files", "*.*")],
        )
        if not path:
            self._status("Export cancelled.")
            return
        try:
            write_pack_file(pack, path)
            self._status(
                f"Exported {len(pack.prompts)} prompt(s) → {Path(path).name}"
            )
        except Exception as exc:
            self._status(f"Export failed: {exc}")
        try:
            self.page.update()
        except Exception:
            pass

    async def _on_import(self, _e: ft.ControlEvent) -> None:
        files = await pick_files(
            self.page,
            dialog_title="Import prompt pack",
            allowed_extensions=["json"],
            allow_multiple=False,
        )
        if not files or not files[0].path:
            self._status("Import cancelled.")
            return
        try:
            pack = read_pack_file(files[0].path)
            added, skipped = import_pack(pack, merge=True)
            self.refresh()
            self._status(
                f"Imported “{pack.name}”: {added} new, {skipped} already present."
            )
        except Exception as exc:
            self._status(f"Import failed: {exc}")
        try:
            self.page.update()
        except Exception:
            pass


def make_prompt_favorites_bar(
    page: ft.Page,
    *,
    get_text: GetText,
    set_text: SetText,
    surface: str = "other",
    get_meta: GetMeta | None = None,
    on_status: StatusCb | None = None,
    show_pack_buttons: bool = True,
) -> PromptFavoritesBar:
    return PromptFavoritesBar(
        page,
        get_text=get_text,
        set_text=set_text,
        surface=surface,
        get_meta=get_meta,
        on_status=on_status,
        show_pack_buttons=show_pack_buttons,
    )
