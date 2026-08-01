"""
Quiet credit / billing status for the top bar and Settings.

fal: GET /v1/account/billing?expand=credits when the key allows it (Admin scope).
xAI: no reliable balance from a standard API key — link only.
Runware: accountManagement getDetails → balance.amount (Aleph / Frame Editor only).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import httpx

from media_studio.errors import FAL_BILLING_URL, FAL_TOPUP_URL, XAI_TOPUP_URL

# Platform API (account-level) — requires Admin-scoped key for credits
FAL_BILLING_API = "https://api.fal.ai/v1/account/billing"
RUNWARE_API_URL = "https://api.runware.ai/v1"
RUNWARE_BILLING_URL = "https://my.runware.ai/"


@dataclass(frozen=True)
class FalBalance:
    """Result of a fal billing probe."""

    ok: bool
    # Human compact label, e.g. "fal $12.40" or "fal · check billing"
    label: str
    amount: float | None = None
    currency: str = "USD"
    # True when we could not read balance (no key / no permission) — not a hard error
    check_billing: bool = False
    detail: str = ""
    topup_url: str = FAL_TOPUP_URL
    billing_url: str = FAL_BILLING_URL


def format_money(amount: float, currency: str = "USD") -> str:
    cur = (currency or "USD").upper()
    if cur == "USD":
        return f"${amount:,.2f}"
    return f"{amount:,.2f} {cur}"


def fetch_fal_balance(*, timeout: float = 12.0) -> FalBalance:
    """
    Query fal account credits with the effective FAL key.

    Never raises — returns a soft “check billing” state on failure.
    Success path parses ``credits.current_balance`` → ``fal $12.40``.
    """
    try:
        from media_studio.secrets_store import effective_fal_key

        key = (effective_fal_key() or "").strip()
    except Exception:
        key = ""

    if not key:
        return FalBalance(
            ok=False,
            label="fal · no key",
            check_billing=True,
            detail="Add a FAL API key in Settings.",
        )

    headers = {
        "Authorization": f"Key {key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    # Official: expand=credits includes credits.current_balance
    url = f"{FAL_BILLING_API}?expand=credits"

    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            resp = client.get(url, headers=headers)
    except Exception as exc:
        return FalBalance(
            ok=False,
            label="fal · check billing",
            check_billing=True,
            detail=f"Could not reach fal billing API ({type(exc).__name__}).",
        )

    if resp.status_code in (401, 403):
        # Platform billing needs Admin-scoped key; regular API keys get 403
        return FalBalance(
            ok=False,
            label="fal · check billing",
            check_billing=True,
            detail=(
                "This key cannot read balance (Admin scope required for billing API). "
                "Create an Admin key at fal.ai/dashboard/keys, or open billing to check credits."
            ),
        )
    if resp.status_code >= 400:
        body = ""
        try:
            body = (resp.text or "")[:160]
        except Exception:
            pass
        return FalBalance(
            ok=False,
            label="fal · check billing",
            check_billing=True,
            detail=f"fal billing HTTP {resp.status_code}. {body}".strip(),
        )

    try:
        data = resp.json()
    except Exception:
        return FalBalance(
            ok=False,
            label="fal · check billing",
            check_billing=True,
            detail="Unexpected billing response (not JSON).",
        )

    amount, currency = _extract_credits(data)
    if amount is None:
        # Help debugging unexpected shapes without crashing
        keys = list(data.keys()) if isinstance(data, dict) else type(data).__name__
        return FalBalance(
            ok=False,
            label="fal · check billing",
            check_billing=True,
            detail=f"No credit balance in response (keys: {keys}). Open fal billing.",
        )

    money = format_money(float(amount), currency)
    return FalBalance(
        ok=True,
        label=f"fal {money}",
        amount=float(amount),
        currency=currency,
        check_billing=False,
        detail=f"Balance {money}",
    )


def _coerce_amount(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        s = value.strip().replace(",", "").replace("$", "")
        if not s:
            return None
        try:
            return float(s)
        except ValueError:
            return None
    if isinstance(value, dict):
        for k in ("current_balance", "balance", "available", "amount", "value"):
            if k in value:
                a = _coerce_amount(value.get(k))
                if a is not None:
                    return a
    return None


def _extract_credits(data: Any) -> tuple[float | None, str]:
    """Parse fal billing payloads — prefer credits.current_balance."""
    if not isinstance(data, dict):
        return None, "USD"

    # Nested under data / account
    for wrapper in (None, "data", "account", "result"):
        root = data if wrapper is None else data.get(wrapper)
        if not isinstance(root, dict):
            continue

        credits = root.get("credits")
        currency = "USD"
        if isinstance(credits, dict):
            currency = str(
                credits.get("currency")
                or root.get("currency")
                or "USD"
            )
            for key in (
                "current_balance",
                "balance",
                "available",
                "available_balance",
                "remaining",
                "amount",
            ):
                amt = _coerce_amount(credits.get(key))
                if amt is not None:
                    return amt, currency
            # Nested { "usd": 12.4 } or single numeric leaf
            for k, v in credits.items():
                if str(k).lower() in ("currency", "unit"):
                    continue
                amt = _coerce_amount(v)
                if amt is not None:
                    cur = str(k).upper() if len(str(k)) == 3 else currency
                    return amt, cur
        elif credits is not None:
            amt = _coerce_amount(credits)
            if amt is not None:
                return amt, str(root.get("currency") or "USD")

        # Top-level on this root
        for key in ("current_balance", "balance", "credit_balance", "available_balance"):
            amt = _coerce_amount(root.get(key))
            if amt is not None:
                return amt, str(root.get("currency") or "USD")

    return None, "USD"


def xai_billing_label() -> str:
    """Compact xAI status (link only — no live balance)."""
    return "xAI billing"


def xai_billing_url() -> str:
    return XAI_TOPUP_URL


@dataclass(frozen=True)
class RunwareBalance:
    """Result of a Runware account balance probe (Frame Editor / Aleph only)."""

    ok: bool
    label: str
    amount: float | None = None
    currency: str = "USD"
    check_billing: bool = False
    detail: str = ""
    billing_url: str = RUNWARE_BILLING_URL


def fetch_runware_balance(*, timeout: float = 12.0) -> RunwareBalance:
    """
    Query Runware account balance via accountManagement / getDetails.

    Never raises. Missing key → “Add key”; API without balance → “connected”.
    """
    try:
        from media_studio.secrets_store import effective_runware_key

        key = (effective_runware_key() or "").strip()
    except Exception:
        key = ""

    if not key:
        return RunwareBalance(
            ok=False,
            label="Runware · Add key",
            check_billing=True,
            detail=(
                "Optional — only for Frame Editor / Aleph. "
                "Add a Runware key in Settings. fal alone covers Studio and Tools."
            ),
        )

    task = {
        "taskType": "accountManagement",
        "taskUUID": str(uuid.uuid4()),
        "operation": "getDetails",
    }
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            resp = client.post(RUNWARE_API_URL, headers=headers, json=[task])
    except Exception as exc:
        return RunwareBalance(
            ok=False,
            label="Runware · …",
            check_billing=True,
            detail=f"Could not reach Runware ({type(exc).__name__}). Key may still work for Aleph.",
        )

    if resp.status_code in (401, 403):
        return RunwareBalance(
            ok=False,
            label="Runware · check key",
            check_billing=True,
            detail="Runware key rejected. Open Settings and paste a valid key from my.runware.ai.",
        )
    if resp.status_code >= 400:
        body = ""
        try:
            body = (resp.text or "")[:120]
        except Exception:
            pass
        return RunwareBalance(
            ok=False,
            label="Runware · connected",
            check_billing=True,
            detail=f"Balance API HTTP {resp.status_code}. {body}".strip()
            or "Key present; balance not readable — open my.runware.ai for credits.",
        )

    try:
        payload = resp.json()
    except Exception:
        return RunwareBalance(
            ok=False,
            label="Runware · connected",
            check_billing=True,
            detail="Unexpected balance response. Key may still work for Frame Editor.",
        )

    # Shape: { "data": [ { "balance": { "amount": … }, … } ] } or list
    rows: list[Any] = []
    if isinstance(payload, dict):
        if payload.get("errors"):
            return RunwareBalance(
                ok=False,
                label="Runware · connected",
                check_billing=True,
                detail=f"Runware error: {payload.get('errors')}",
            )
        data = payload.get("data")
        if isinstance(data, list):
            rows = data
        elif isinstance(data, dict):
            rows = [data]
    elif isinstance(payload, list):
        rows = [x for x in payload if isinstance(x, dict)]

    amount: float | None = None
    currency = "USD"
    for row in rows:
        if not isinstance(row, dict):
            continue
        bal = row.get("balance")
        if isinstance(bal, dict):
            currency = str(bal.get("currency") or currency)
            for key_name in ("amount", "freeBalance", "balance", "available"):
                amt = _coerce_amount(bal.get(key_name))
                if amt is not None:
                    amount = amt
                    break
        if amount is None:
            amount = _coerce_amount(row.get("balance"))
        if amount is not None:
            break

    if amount is None:
        return RunwareBalance(
            ok=True,
            label="Runware · connected",
            check_billing=False,
            detail=(
                "Runware key present. Balance not in API response — "
                "check credits at my.runware.ai. Only needed for Frame Editor / Aleph."
            ),
        )

    money = format_money(float(amount), currency)
    return RunwareBalance(
        ok=True,
        label=f"Runware · {money}",
        amount=float(amount),
        currency=currency,
        check_billing=False,
        detail=f"Balance {money} (Frame Editor / Aleph only — not used by fal Studio/Tools)",
    )
