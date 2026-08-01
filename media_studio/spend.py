"""
Local spend dashboard from generation history (Phase 5).

Sums cost_estimate strings already logged per generate — no external billing APIs.
Missing / zero / unparseable costs are skipped (counted separately).
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from media_studio.history import HistoryEntry, load_history

# First $ amount after optional "Est. cost:" / "Cost:" / bare "$"
_COST_RE = re.compile(
    r"(?:est\.?\s*cost|cost)\s*:\s*\$?\s*([0-9]+(?:\.[0-9]+)?)"
    r"|\$\s*([0-9]+(?:\.[0-9]+)?)",
    re.IGNORECASE,
)


def parse_cost_usd(cost_text: str | None) -> float | None:
    """
    Extract a USD amount from history cost labels.

    Accepts ``Est. cost: $0.80``, ``Cost: $1.20 · 8s (… )``, metrics lines with
    ``$0.03``, etc. Returns None for empty, dash, or unparseable.
    """
    raw = (cost_text or "").strip()
    if not raw or raw in ("—", "-", "n/a", "N/A", "none"):
        return None
    # Prefer labeled cost first
    m = _COST_RE.search(raw)
    if not m:
        return None
    num = m.group(1) or m.group(2)
    try:
        val = float(num)
    except (TypeError, ValueError):
        return None
    if val < 0 or val > 1_000_000:
        return None
    # Treat pure zero as "no cost logged" for sums (still trackable if needed)
    if val == 0.0:
        return None
    return val


def parse_entry_date(entry: HistoryEntry) -> date | None:
    """YYYYMMDD from compact stamp, or date from ISO-ish timestamps."""
    ts = (entry.timestamp or entry.id or "").strip()
    if len(ts) >= 8 and ts[:8].isdigit():
        try:
            return datetime.strptime(ts[:8], "%Y%m%d").date()
        except ValueError:
            pass
    # Fallback: try ISO date prefix
    if len(ts) >= 10 and ts[4] == "-" and ts[7] == "-":
        try:
            return datetime.strptime(ts[:10], "%Y-%m-%d").date()
        except ValueError:
            pass
    return None


def infer_provider(model: str | None, job_kind: str | None = None) -> str:
    """Best-effort provider bucket from model label / kind (local only)."""
    m = (model or "").strip().lower()
    k = (job_kind or "").strip().lower()
    if "aleph" in m or "runware" in m or "aleph" in k:
        return "Runware"
    if "grok" in m or "xai" in m:
        return "xAI (fal)"
    if "eleven" in m or "elevenlabs" in m:
        return "ElevenLabs (fal)"
    if "minimax" in m or "hailuo" in m:
        return "MiniMax (fal)"
    if "luma" in m:
        return "Luma (fal)"
    if "bytedance" in m or "seedream" in m or "seedance" in m:
        return "ByteDance (fal)"
    if "kling" in m:
        return "Kling (fal)"
    if "veo" in m:
        return "Veo (fal)"
    if "flux" in m or "nano banana" in m or "recraft" in m or "mai-image" in m:
        return "fal.ai"
    if m or k:
        return "fal.ai"
    return "Unknown"


def short_model_name(model: str | None) -> str:
    m = (model or "").strip() or "Unknown"
    # Strip common UI prefixes
    for prefix in ("Image · ", "Video · ", "Audio · "):
        if m.startswith(prefix):
            m = m[len(prefix) :]
    return m


@dataclass
class SpendBucket:
    label: str
    total_usd: float = 0.0
    count: int = 0  # jobs with known cost
    skipped: int = 0  # missing/unparseable cost

    def add(self, amount: float | None) -> None:
        if amount is None:
            self.skipped += 1
            return
        self.total_usd += amount
        self.count += 1


@dataclass
class SpendReport:
    """Aggregated spend from local history."""

    today: SpendBucket = field(default_factory=lambda: SpendBucket("Today"))
    this_week: SpendBucket = field(default_factory=lambda: SpendBucket("This week"))
    this_month: SpendBucket = field(default_factory=lambda: SpendBucket("This month"))
    all_time: SpendBucket = field(default_factory=lambda: SpendBucket("All time"))
    by_model: list[SpendBucket] = field(default_factory=list)
    by_provider: list[SpendBucket] = field(default_factory=list)
    entries_total: int = 0
    entries_with_cost: int = 0
    entries_missing_cost: int = 0

    def summary_line(self) -> str:
        """One-line: This week: $X — top models …"""
        w = self.this_week.total_usd
        tops = self.by_model[:3]
        if not tops or self.entries_with_cost == 0:
            if self.entries_total == 0:
                return "No generations in history yet."
            return (
                f"This week: $0.00 · {self.entries_missing_cost} job(s) with no cost logged"
            )
        top_s = ", ".join(
            f"{b.label} ${b.total_usd:.2f}" for b in tops if b.total_usd > 0
        )
        parts = [f"This week: ${w:.2f}"]
        if top_s:
            parts.append(f"top: {top_s}")
        if self.entries_missing_cost:
            parts.append(f"{self.entries_missing_cost} without cost")
        return " — ".join(parts)


def _week_start(d: date) -> date:
    # Monday-start week (ISO)
    return d - timedelta(days=d.weekday())


def build_spend_report(
    output_dir: str | Path | None = None,
    *,
    entries: Iterable[HistoryEntry] | None = None,
    as_of: date | None = None,
) -> SpendReport:
    """
    Sum history costs by day / week / month and by model / provider.

    Only rows with a parseable non-zero cost contribute to totals.
    """
    today = as_of or date.today()
    week0 = _week_start(today)
    month0 = today.replace(day=1)

    report = SpendReport()
    model_map: dict[str, SpendBucket] = {}
    prov_map: dict[str, SpendBucket] = {}

    items = list(entries) if entries is not None else load_history(output_dir)
    report.entries_total = len(items)

    for e in items:
        amount = parse_cost_usd(e.cost_estimate)
        d = parse_entry_date(e)

        if amount is None:
            report.entries_missing_cost += 1
        else:
            report.entries_with_cost += 1

        # Period buckets (only if we have a date; undated still count all-time)
        report.all_time.add(amount)
        if d is not None:
            if d == today:
                report.today.add(amount)
            if d >= week0:
                report.this_week.add(amount)
            if d >= month0:
                report.this_month.add(amount)
        elif amount is not None:
            # Undated with cost: only all_time (already added)
            pass

        # Model / provider (all-time)
        mname = short_model_name(e.model)
        if mname not in model_map:
            model_map[mname] = SpendBucket(mname)
        model_map[mname].add(amount)

        pname = infer_provider(e.model, e.job_kind)
        if pname not in prov_map:
            prov_map[pname] = SpendBucket(pname)
        prov_map[pname].add(amount)

    report.by_model = sorted(
        model_map.values(), key=lambda b: (-b.total_usd, b.label.lower())
    )
    report.by_provider = sorted(
        prov_map.values(), key=lambda b: (-b.total_usd, b.label.lower())
    )
    return report


def format_usd(amount: float) -> str:
    if amount < 0.01 and amount > 0:
        return f"${amount:.3f}"
    return f"${amount:.2f}"


def report_as_lines(report: SpendReport, *, top_n: int = 5) -> list[str]:
    """Human lines for a simple text panel."""
    lines: list[str] = [
        f"Today: {format_usd(report.today.total_usd)} "
        f"({report.today.count} with cost"
        + (f", {report.today.skipped} missing" if report.today.skipped else "")
        + ")",
        f"This week: {format_usd(report.this_week.total_usd)} "
        f"({report.this_week.count} with cost)",
        f"This month: {format_usd(report.this_month.total_usd)} "
        f"({report.this_month.count} with cost)",
        f"All time: {format_usd(report.all_time.total_usd)} "
        f"({report.entries_with_cost}/{report.entries_total} jobs with cost)",
    ]
    if report.by_model:
        lines.append("Top models:")
        for b in report.by_model[:top_n]:
            if b.total_usd <= 0 and b.count == 0:
                continue
            lines.append(f"  · {b.label}: {format_usd(b.total_usd)} ({b.count})")
    if report.by_provider:
        lines.append("By provider:")
        for b in report.by_provider[:top_n]:
            if b.total_usd <= 0 and b.count == 0:
                continue
            lines.append(f"  · {b.label}: {format_usd(b.total_usd)} ({b.count})")
    if report.entries_missing_cost:
        lines.append(
            f"Note: {report.entries_missing_cost} history row(s) have no usable cost "
            "(zeros and “—” are skipped)."
        )
    return lines
