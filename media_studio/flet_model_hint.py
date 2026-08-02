"""UI helper: “Best for: …” line under model dropdowns."""

from __future__ import annotations

from typing import Any

import flet as ft

from media_studio.flet_theme import FONT_SM, TEXT_MUTED
from media_studio.model_hints import lookup_best_for


def make_best_for_line() -> ft.Text:
    """Empty / hidden until update_best_for_line is called with a known model."""
    return ft.Text(
        "",
        size=FONT_SM,
        color=TEXT_MUTED,
        max_lines=1,
        overflow=ft.TextOverflow.ELLIPSIS,
        visible=False,
    )


def update_best_for_line(
    line: ft.Text | None,
    model_choice: str | None,
    *,
    dropdown: Any | None = None,
) -> None:
    """
    Set under-dropdown line + optional dropdown tooltip from registry.

    Missing entry → hide line (no empty “Best for:”).
    """
    if line is None:
        return
    bf = lookup_best_for(model_choice)
    if bf is None or not (bf.short or "").strip():
        line.value = ""
        line.visible = False
        line.tooltip = None
        if dropdown is not None:
            try:
                # Keep original tooltip if any; only clear our detail if we set it
                if getattr(dropdown, "data", None) == "best_for":
                    dropdown.tooltip = None
                    dropdown.data = None
            except Exception:
                pass
        return
    short = " ".join(bf.short.split())
    # Soft cap ~12 words for the under-line
    words = short.split()
    if len(words) > 14:
        short = " ".join(words[:12]) + "…"
    line.value = f"Best for: {short}"
    line.visible = True
    detail = " ".join((bf.detail or "").split())
    line.tooltip = detail or short
    if dropdown is not None and detail:
        try:
            dropdown.tooltip = detail
            dropdown.data = "best_for"
        except Exception:
            pass
