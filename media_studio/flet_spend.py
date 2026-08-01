"""Simple local spend panel for Library / Settings."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

import flet as ft

from media_studio.flet_theme import (
    ACCENT,
    ACCENT_BRIGHT,
    BORDER,
    FONT_SM,
    PANEL_ELEVATED,
    TEXT,
    TEXT_MUTED,
)
from media_studio.spend import build_spend_report, format_usd, report_as_lines

if TYPE_CHECKING:
    from media_studio.flet_app import StudioState


def build_spend_panel(
    page: ft.Page,
    state: StudioState,
    *,
    compact: bool = True,
    on_status: Callable[[str], None] | None = None,
) -> ft.Control:
    """
    Local spend dashboard from history costs.

    ``compact=True``: one-line summary + expand for detail (Library).
    ``compact=False``: always-expanded block (Settings).
    """
    summary = ft.Text("", size=FONT_SM, color=TEXT, weight=ft.FontWeight.W_600)
    detail = ft.Text("", size=FONT_SM, color=TEXT_MUTED, selectable=True)
    detail_host = ft.Container(content=detail, visible=not compact)

    def _refresh(_e: ft.ControlEvent | None = None) -> None:
        try:
            report = build_spend_report(state.output_dir)
            summary.value = report.summary_line()
            detail.value = "\n".join(report_as_lines(report, top_n=6))
            if on_status:
                on_status("Spend refreshed from local history.")
        except Exception as exc:
            summary.value = f"Spend: could not load ({exc})"
            detail.value = ""
        try:
            page.update()
        except Exception:
            pass

    def _toggle(_e: ft.ControlEvent | None = None) -> None:
        detail_host.visible = not detail_host.visible
        btn_more.content = "Hide detail" if detail_host.visible else "Show detail"
        try:
            page.update()
        except Exception:
            pass

    btn_refresh = ft.TextButton(
        content="Refresh",
        icon=ft.Icons.REFRESH,
        on_click=_refresh,
        style=ft.ButtonStyle(color=TEXT_MUTED),
        tooltip="Recompute from generation history (no network)",
    )
    btn_more = ft.TextButton(
        content="Show detail" if compact else "Hide detail",
        on_click=_toggle,
        style=ft.ButtonStyle(color=ACCENT_BRIGHT),
        visible=compact,
    )

    # Period chips as a simple row of amounts
    period_row = ft.Row(spacing=8, wrap=True)
    model_row = ft.Text("", size=FONT_SM, color=TEXT_MUTED, max_lines=2)

    def _refresh_chips() -> None:
        try:
            report = build_spend_report(state.output_dir)
            summary.value = report.summary_line()
            detail.value = "\n".join(report_as_lines(report, top_n=6))
            chips: list[ft.Control] = []
            for bucket in (
                report.today,
                report.this_week,
                report.this_month,
                report.all_time,
            ):
                chips.append(
                    ft.Container(
                        content=ft.Column(
                            [
                                ft.Text(
                                    bucket.label,
                                    size=11,
                                    color=TEXT_MUTED,
                                ),
                                ft.Text(
                                    format_usd(bucket.total_usd),
                                    size=FONT_SM,
                                    color=TEXT,
                                    weight=ft.FontWeight.W_700,
                                ),
                            ],
                            spacing=2,
                            tight=True,
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        bgcolor=PANEL_ELEVATED,
                        border=ft.Border.all(1, BORDER),
                        border_radius=6,
                        padding=ft.Padding.symmetric(horizontal=10, vertical=6),
                    )
                )
            period_row.controls = chips
            tops = [
                f"{b.label} {format_usd(b.total_usd)}"
                for b in report.by_model[:3]
                if b.total_usd > 0
            ]
            model_row.value = (
                "Top models: " + " · ".join(tops) if tops else "Top models: —"
            )
        except Exception as exc:
            summary.value = f"Spend unavailable: {exc}"
            period_row.controls = []
            model_row.value = ""

    def refresh_public(_e: ft.ControlEvent | None = None) -> None:
        _refresh_chips()
        try:
            page.update()
        except Exception:
            pass

    # Initial fill
    _refresh_chips()

    # Expose refresh for Library.refresh()
    panel = ft.Container(
        content=ft.Column(
            [
                ft.Row(
                    [
                        ft.Icon(ft.Icons.PAYMENTS_OUTLINED, size=16, color=TEXT_MUTED),
                        ft.Text(
                            "Local spend",
                            size=FONT_SM,
                            color=TEXT,
                            weight=ft.FontWeight.W_700,
                        ),
                        ft.Container(expand=True),
                        btn_more,
                        btn_refresh,
                    ],
                    spacing=6,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                summary,
                period_row,
                model_row,
                detail_host,
                ft.Text(
                    "From Library history costs only — estimates/exact labels you already log. "
                    "No external billing API. Missing or $0 rows are skipped.",
                    size=11,
                    color=TEXT_MUTED,
                ),
            ],
            spacing=6,
            tight=True,
        ),
        bgcolor=PANEL_ELEVATED,
        border=ft.Border.all(1, BORDER),
        border_radius=8,
        padding=10,
    )
    # Attach refresh for callers
    panel.data = {"refresh": refresh_public}  # type: ignore[attr-defined]
    return panel
