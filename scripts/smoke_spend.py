"""Smoke local spend parsing + aggregation."""
from __future__ import annotations

from media_studio.spend import build_spend_report, parse_cost_usd, report_as_lines


def main() -> None:
    assert abs((parse_cost_usd("Est. cost: $0.800") or 0) - 0.8) < 1e-9
    assert abs((parse_cost_usd("Est. cost: $0.046 · 1 image (Flux)") or 0) - 0.046) < 1e-9
    assert parse_cost_usd("—") is None
    assert parse_cost_usd("") is None
    assert parse_cost_usd("Est. cost: $0.00") is None
    assert parse_cost_usd("Done · Est. cost: $1.25") == 1.25

    r = build_spend_report("outputs")
    print(r.summary_line())
    print(
        "week",
        round(r.this_week.total_usd, 3),
        "all",
        round(r.all_time.total_usd, 3),
        "models",
        len(r.by_model),
    )
    for line in report_as_lines(r)[:6]:
        print(line)
    print("smoke_spend OK")


if __name__ == "__main__":
    main()
