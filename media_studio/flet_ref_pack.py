"""
Character / Scene / Prop reference pack UI for R2V and R2I.

- Character slots: Character library dropdown (never OS folder)
- Scene slots: Scene library dropdown
- Prop slots: upload still
- Optional start frame is owned by the parent tab
- Live Image 1 / Image 2… citation map for Enhance + generate
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal

import flet as ft

from media_studio.flet_character_picker import CharacterPicker
from media_studio.flet_pickers import pick_image
from media_studio.flet_scene_picker import ScenePicker
from media_studio.flet_theme import (
    ACCENT,
    ACCENT_BRIGHT,
    BORDER,
    FONT_SM,
    PANEL,
    PANEL_ELEVATED,
    TEXT,
    TEXT_MUTED,
)

RefRole = Literal["character", "scene", "prop"]


@dataclass
class RefItem:
    role: RefRole
    path: str
    label: str
    source_id: str | None = None  # character or scene id


@dataclass
class CitationStyle:
    """How the model expects refs to be named in the prompt."""

    kind: str = "plain"  # plain | angle | at

    def tag(self, index: int) -> str:
        """1-based index → citation token."""
        i = max(1, int(index))
        if self.kind == "angle":
            return f"<IMAGE_{i - 1}>"
        if self.kind == "at":
            return f"@Image{i}"
        return f"Image {i}"


def citation_style_for_model(model_choice: str | None, *, mode: str = "") -> CitationStyle:
    raw = (model_choice or "").lower()
    m = (mode or "").lower()
    if "grok" in raw or "angle" in raw or "<image" in raw:
        return CitationStyle("angle")
    if "kling" in raw and "element" in raw:
        return CitationStyle("at")
    # H3 / Seedance / default Omni
    if "h3" in raw or "omni" in raw or "seedance" in raw or "r2v" in m or "r2i" in m:
        return CitationStyle("plain")
    return CitationStyle("plain")


def max_character_slots(model_choice: str | None, *, mode: str = "") -> int:
    """How many Character library slots to allow."""
    raw = (model_choice or "").lower()
    m = (mode or "").lower()
    if "flux 3" in raw and ("i2v" in raw or m in ("i2v", "image_to_video")):
        return 1
    if "flux 3" in raw and ("r2v" in raw or "identity" in raw):
        return 1
    if "omni" in raw or "h3" in raw:
        return 9
    if "seedance" in raw and "reference" in raw:
        return 9
    if "grok" in raw and "reference" in raw:
        return 7
    if "veo" in raw and "reference" in raw:
        return 8
    if m in ("r2i", "reference_to_image"):
        return 4
    if m in ("r2v", "reference_to_video"):
        return 4
    return 1


def max_scene_slots(model_choice: str | None, *, mode: str = "") -> int:
    raw = (model_choice or "").lower()
    m = (mode or "").lower()
    if "omni" in raw or "h3" in raw:
        return 3
    if "seedance" in raw and "reference" in raw:
        return 2
    if "grok" in raw and "reference" in raw:
        return 2
    if m in ("r2i", "reference_to_image", "r2v", "reference_to_video"):
        return 2
    return 1


def max_prop_slots(model_choice: str | None, *, mode: str = "") -> int:
    raw = (model_choice or "").lower()
    if "omni" in raw or "h3" in raw:
        return 4
    if m := (mode or "").lower():
        if m in ("r2i", "reference_to_image", "r2v", "reference_to_video"):
            return 3
    return 2


class RefPackPanel:
    """
    Simple Character / Scene / Prop pack with live Image-N mapping.

    Does **not** own Start frame — parent tab keeps that separate.
    """

    def __init__(
        self,
        page: ft.Page,
        *,
        on_change: Callable[[], None] | None = None,
        dense: bool = True,
    ) -> None:
        self.page = page
        self.on_change = on_change
        self._model_choice = ""
        self._mode = "r2v"
        self._chars: list[RefItem] = []
        self._scenes: list[RefItem] = []
        self._props: list[RefItem] = []

        self._char_pickers: list[CharacterPicker] = []
        self._scene_pickers: list[ScenePicker] = []

        self.title = ft.Text(
            "References (Character · Scene · Prop)",
            size=FONT_SM,
            color=TEXT,
            weight=ft.FontWeight.W_700,
        )
        self.hint = ft.Text(
            "Character/Scene = library dropdowns (not folders). Prop = upload still. "
            "Identity refs only — not Start frame / source unless parent opts in.",
            size=11,
            color=TEXT_MUTED,
            max_lines=3,
        )
        self.char_host = ft.Column(spacing=6, tight=True)
        self.scene_host = ft.Column(spacing=6, tight=True)
        self.prop_host = ft.Column(spacing=4, tight=True)
        self.btn_add_char = ft.OutlinedButton(
            content="Add another character",
            icon=ft.Icons.PERSON_ADD_ALT_1,
            on_click=self._on_add_character,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
            height=34,
            tooltip="Adds another Character library dropdown (not a folder picker)",
        )
        self.btn_add_scene = ft.OutlinedButton(
            content="Add another scene",
            icon=ft.Icons.LANDSCAPE_OUTLINED,
            on_click=self._on_add_scene,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
            height=34,
        )
        self.btn_add_prop = ft.OutlinedButton(
            content="Add prop",
            icon=ft.Icons.CATEGORY_OUTLINED,
            on_click=self._on_add_prop,
            style=ft.ButtonStyle(color=TEXT, side=ft.BorderSide(1, BORDER)),
            height=34,
            tooltip="Upload a prop / object still (Prop Gen tool later)",
        )
        self.mapping_label = ft.Text(
            "No refs yet",
            size=FONT_SM,
            color=ACCENT_BRIGHT,
            max_lines=6,
            selectable=True,
        )
        self.count_label = ft.Text("", size=11, color=TEXT_MUTED)

        # Seed first character + first scene pickers
        self._ensure_char_pickers(1)
        self._ensure_scene_pickers(1)

        self.root = ft.Container(
            content=ft.Column(
                [
                    self.title,
                    self.hint,
                    ft.Text("Character", size=FONT_SM, color=TEXT_MUTED, weight=ft.FontWeight.W_600),
                    self.char_host,
                    self.btn_add_char,
                    ft.Text("Scene", size=FONT_SM, color=TEXT_MUTED, weight=ft.FontWeight.W_600),
                    self.scene_host,
                    self.btn_add_scene,
                    ft.Text("Prop", size=FONT_SM, color=TEXT_MUTED, weight=ft.FontWeight.W_600),
                    self.prop_host,
                    self.btn_add_prop,
                    ft.Divider(height=1, color=BORDER),
                    ft.Text("Citation map", size=FONT_SM, color=TEXT, weight=ft.FontWeight.W_600),
                    self.mapping_label,
                    self.count_label,
                ],
                spacing=6,
                tight=True,
            ),
            bgcolor=PANEL_ELEVATED,
            border=ft.Border.all(1, BORDER),
            border_radius=8,
            padding=10,
            visible=False,
        )

    # ----- public API -----

    def set_context(self, *, model_choice: str | None, mode: str) -> None:
        self._model_choice = model_choice or ""
        self._mode = mode or "r2v"
        self.refresh()

    def refresh(self) -> None:
        for p in self._char_pickers:
            try:
                p.refresh()
            except Exception:
                pass
        for p in self._scene_pickers:
            try:
                p.refresh()
            except Exception:
                pass
        self._rebuild_lists()
        self._update_mapping()
        self._sync_add_buttons()

    def ordered_items(self) -> list[RefItem]:
        """Citation order: all characters, then scenes, then props."""
        out: list[RefItem] = []
        for it in self._chars:
            if it.path and Path(it.path).is_file():
                out.append(it)
        for it in self._scenes:
            if it.path and Path(it.path).is_file():
                out.append(it)
        for it in self._props:
            if it.path and Path(it.path).is_file():
                out.append(it)
        return out

    def ordered_paths(self) -> list[str]:
        return [it.path for it in self.ordered_items()]

    def mapping_text(self) -> str:
        style = citation_style_for_model(self._model_choice, mode=self._mode)
        items = self.ordered_items()
        if not items:
            return "No refs yet — add Character / Scene / Prop."
        bits = []
        for i, it in enumerate(items, start=1):
            bits.append(f"{style.tag(i)} = {it.label} ({it.role})")
        return " · ".join(bits)

    def enhance_guidance(self) -> str:
        """Text for Grok Enhance extra_context."""
        style = citation_style_for_model(self._model_choice, mode=self._mode)
        items = self.ordered_items()
        if not items:
            return ""
        lines = [
            "Reference pack (use these exact citations in the rewrite):",
            self.mapping_text(),
        ]
        for i, it in enumerate(items, start=1):
            tag = style.tag(i)
            if it.role == "character":
                lab = it.label or ""
                low = lab.lower()
                if low.startswith("character sheet") or low.endswith(" sheet"):
                    lines.append(
                        f"{tag} = {lab} — multi-angle identity/outfit pack as one ref "
                        "(do not invent extra angles; match person + wardrobe from the sheet)."
                    )
                else:
                    lines.append(
                        f"{tag} = character identity / likeness for “{lab}”."
                    )
            elif it.role == "scene":
                lab = it.label or ""
                if lab.lower().endswith(" sheet") or lab.lower().startswith(
                    "scene sheet"
                ):
                    lines.append(
                        f"{tag} = {lab} — multi-panel location-bible sheet as one ref "
                        "(match architecture/materials/lighting; do not invent a new place)."
                    )
                else:
                    lines.append(
                        f"{tag} = scene / location plate for “{lab}”."
                    )
            else:
                lines.append(f"{tag} = prop / object ref “{it.label}”.")
        lines.append(
            "Do not treat character refs as a locked start frame unless the user "
            "also attached a separate Start frame."
        )
        return " ".join(lines)

    def clear_all(self) -> None:
        self._chars.clear()
        self._scenes.clear()
        self._props.clear()
        for p in self._char_pickers:
            try:
                p.clear(notify=False)
            except Exception:
                pass
        for p in self._scene_pickers:
            try:
                p.clear(notify=False)
            except Exception:
                pass
        self._ensure_char_pickers(1)
        self._ensure_scene_pickers(1)
        self.refresh()
        self._notify()

    # ----- internals -----

    def _notify(self) -> None:
        if self.on_change:
            try:
                self.on_change()
            except Exception:
                pass

    def _cap_char(self) -> int:
        return max_character_slots(self._model_choice, mode=self._mode)

    def _cap_scene(self) -> int:
        return max_scene_slots(self._model_choice, mode=self._mode)

    def _cap_prop(self) -> int:
        return max_prop_slots(self._model_choice, mode=self._mode)

    def _ensure_char_pickers(self, n: int) -> None:
        n = max(1, min(n, self._cap_char()))
        while len(self._char_pickers) < n:
            idx = len(self._char_pickers)

            def _sel(path: str, choice: Any, *, i: int = idx) -> None:
                self._set_char(i, path, choice)

            def _clr(*, i: int = idx) -> None:
                self._clear_char(i)

            p = CharacterPicker(
                self.page,
                on_select=_sel,
                on_clear=_clr,
                label_text=f"Character {idx + 1}",
                compact=False,
            )
            self._char_pickers.append(p)
        self.char_host.controls = [p.root for p in self._char_pickers[:n]]
        for i, p in enumerate(self._char_pickers):
            try:
                p.root.visible = i < n
            except Exception:
                pass

    def _ensure_scene_pickers(self, n: int) -> None:
        n = max(1, min(n, self._cap_scene()))
        while len(self._scene_pickers) < n:
            idx = len(self._scene_pickers)

            def _sel(path: str, choice: Any, *, i: int = idx) -> None:
                self._set_scene(i, path, choice)

            def _clr(*, i: int = idx) -> None:
                self._clear_scene(i)

            p = ScenePicker(
                self.page,
                on_select=_sel,
                on_clear=_clr,
                label_text=f"Scene {idx + 1}",
                compact=False,
            )
            self._scene_pickers.append(p)
        self.scene_host.controls = [p.root for p in self._scene_pickers[:n]]
        for i, p in enumerate(self._scene_pickers):
            try:
                p.root.visible = i < n
            except Exception:
                pass

    def _set_char(self, index: int, path: str, choice: Any) -> None:
        """
        Store a single character identity image for R2V/R2I.

        Prefer path from CharacterPicker (sheet composite when selected).
        Citation label: ``Camera Man sheet`` or picker label (Front only).
        Never expands to all individual angle stills.
        """
        cid = getattr(choice, "id", None)
        use_sheet = True
        # Prefer picker path (already sheet-or-front resolved) when valid
        p = (path or "").strip()
        label = ""
        try:
            if hasattr(choice, "ref_path") and hasattr(choice, "ref_label"):
                # Read toggle from matching picker when available
                if 0 <= index < len(self._char_pickers):
                    pick = self._char_pickers[index]
                    use_sheet = bool(getattr(pick, "use_sheet", True))
                p = choice.ref_path(use_sheet=use_sheet) or p
                label = choice.ref_label(use_sheet=use_sheet)
        except Exception:
            pass
        if not label:
            label = getattr(choice, "label", None) or (
                Path(p).name if p else "Character"
            )
            # If path is the composite sheet file, force sheet citation
            try:
                sp = getattr(choice, "sheet_path", "") or ""
                if (
                    p
                    and sp
                    and Path(p).resolve() == Path(sp).resolve()
                ):
                    base = getattr(choice, "label", None) or "Character"
                    label = f"{base} sheet"
            except OSError:
                pass
        if p:
            try:
                p = str(Path(p).resolve())
            except OSError:
                pass
        while len(self._chars) <= index:
            self._chars.append(RefItem("character", "", "", None))
        self._chars[index] = RefItem("character", p, label, cid)
        self._update_mapping()
        self._sync_add_buttons()
        self._notify()
        try:
            self.page.update()
        except Exception:
            pass

    def _clear_char(self, index: int) -> None:
        if 0 <= index < len(self._chars):
            self._chars[index] = RefItem("character", "", "", None)
        self._update_mapping()
        self._notify()

    def _set_scene(self, index: int, path: str, choice: Any) -> None:
        """Single scene ref — prefer composite Scene sheet when picker selects it."""
        sid = getattr(choice, "id", None)
        p = (path or "").strip()
        label = ""
        try:
            if hasattr(choice, "ref_path") and hasattr(choice, "ref_label"):
                use_sheet = True
                if 0 <= index < len(self._scene_pickers):
                    pick = self._scene_pickers[index]
                    use_sheet = bool(getattr(pick, "use_sheet", True))
                p = choice.ref_path(use_sheet=use_sheet) or p
                label = choice.ref_label(use_sheet=use_sheet)
        except Exception:
            pass
        if not label:
            label = getattr(choice, "label", None) or (
                Path(p).name if p else "Scene"
            )
            try:
                sp = getattr(choice, "sheet_path", "") or ""
                if p and sp and Path(p).resolve() == Path(sp).resolve():
                    base = getattr(choice, "label", None) or "Scene"
                    label = f"{base} sheet"
            except OSError:
                pass
        if p:
            try:
                p = str(Path(p).resolve())
            except OSError:
                pass
        while len(self._scenes) <= index:
            self._scenes.append(RefItem("scene", "", "", None))
        self._scenes[index] = RefItem("scene", p, label, sid)
        self._update_mapping()
        self._sync_add_buttons()
        self._notify()
        try:
            self.page.update()
        except Exception:
            pass

    def _clear_scene(self, index: int) -> None:
        if 0 <= index < len(self._scenes):
            self._scenes[index] = RefItem("scene", "", "", None)
        self._update_mapping()
        self._notify()

    async def _on_add_character(self, e: ft.ControlEvent | None = None) -> None:
        """Add another Character **library** dropdown — never OS folder."""
        cap = self._cap_char()
        shown = len(self.char_host.controls) or 1
        if shown >= cap:
            return
        self._ensure_char_pickers(shown + 1)
        try:
            self._char_pickers[shown].refresh()
        except Exception:
            pass
        self._sync_add_buttons()
        try:
            self.page.update()
        except Exception:
            pass

    async def _on_add_scene(self, e: ft.ControlEvent | None = None) -> None:
        cap = self._cap_scene()
        shown = len(self.scene_host.controls) or 1
        if shown >= cap:
            return
        self._ensure_scene_pickers(shown + 1)
        try:
            self._scene_pickers[shown].refresh()
        except Exception:
            pass
        self._sync_add_buttons()
        try:
            self.page.update()
        except Exception:
            pass

    async def _on_add_prop(self, e: ft.ControlEvent | None = None) -> None:
        if len([p for p in self._props if p.path]) >= self._cap_prop():
            return
        try:
            files = await pick_image(
                self.page, dialog_title="Prop / object still"
            )
        except Exception:
            return
        if not files or not files[0].path:
            return
        p = str(Path(files[0].path).resolve())
        self._props.append(RefItem("prop", p, Path(p).name, None))
        self._rebuild_lists()
        self._update_mapping()
        self._sync_add_buttons()
        self._notify()
        try:
            self.page.update()
        except Exception:
            pass

    def _make_remove_prop(self, index: int):
        async def _click(_e: ft.ControlEvent) -> None:
            if 0 <= index < len(self._props):
                self._props.pop(index)
            self._rebuild_lists()
            self._update_mapping()
            self._sync_add_buttons()
            self._notify()
            try:
                self.page.update()
            except Exception:
                pass

        return _click

    def _rebuild_lists(self) -> None:
        self.prop_host.controls.clear()
        for i, it in enumerate(self._props):
            if not it.path:
                continue
            self.prop_host.controls.append(
                ft.Row(
                    [
                        ft.Text(
                            f"Prop {i + 1}: {it.label}",
                            size=FONT_SM,
                            color=TEXT,
                            expand=True,
                            max_lines=1,
                        ),
                        ft.IconButton(
                            icon=ft.Icons.CLOSE,
                            icon_size=16,
                            tooltip="Remove prop",
                            on_click=self._make_remove_prop(i),
                        ),
                    ],
                    spacing=4,
                )
            )

    def _update_mapping(self) -> None:
        self.mapping_label.value = self.mapping_text()
        n = len(self.ordered_items())
        self.count_label.value = (
            f"{n} ref(s) · Characters {self._cap_char()} max · "
            f"Scenes {self._cap_scene()} max · Props {self._cap_prop()} max"
        )

    def _sync_add_buttons(self) -> None:
        n_char_shown = len(self.char_host.controls) or 1
        n_scene_shown = len(self.scene_host.controls) or 1
        n_prop = len([p for p in self._props if p.path])
        self.btn_add_char.visible = n_char_shown < self._cap_char()
        self.btn_add_char.disabled = n_char_shown >= self._cap_char()
        self.btn_add_scene.visible = n_scene_shown < self._cap_scene()
        self.btn_add_scene.disabled = n_scene_shown >= self._cap_scene()
        self.btn_add_prop.visible = True
        self.btn_add_prop.disabled = n_prop >= self._cap_prop()

