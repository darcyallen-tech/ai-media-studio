"""
Shared “None / Off” sentinel for prompt-builder helper dropdowns.

When selected, that dimension is omitted from Rebuild prompts and Enhance guidance.
"""

from __future__ import annotations

from typing import Any, Sequence

# Displayed in dropdowns (first option when offered)
HELPER_NONE = "(None)"

_NONE_ALIASES = frozenset(
    {
        "",
        "none",
        "(none)",
        "off",
        "(off)",
        "—",
        "-",
        "— none —",
        "(none / auto)",
        "none / auto",
        "auto",  # only treat bare auto as none for instrument-style fields
    }
)


def is_helper_none(value: Any) -> bool:
    """True when the helper should not inject text or Enhance guidance."""
    if value is None:
        return True
    s = str(value).strip()
    if not s:
        return True
    low = s.lower()
    if low in _NONE_ALIASES:
        return True
    # Exact UI sentinel
    if s == HELPER_NONE:
        return True
    return False


def with_none(options: Sequence[str], *, first: bool = True) -> list[str]:
    """Return options with HELPER_NONE prepended (no duplicate)."""
    out = [str(x) for x in options if str(x).strip() and str(x) != HELPER_NONE]
    if first:
        return [HELPER_NONE] + out
    return out + [HELPER_NONE]


def active_helper(value: Any) -> str | None:
    """Return stripped helper text, or None when silenced."""
    if is_helper_none(value):
        return None
    s = str(value).strip()
    return s or None
