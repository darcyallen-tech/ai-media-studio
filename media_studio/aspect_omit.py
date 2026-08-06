"""
Unified aspect_ratio policy for video (and video-like) fal endpoints.

**Single source of truth.** Studio builders, Creative Vision, last-mile strip,
Director keyframes, and params UI all use this module.

Policies (endpoint-keyed matchers):
  - omit  — never send aspect_ratio (not even auto / Follows …)
  - send  — only allowed enum values; optional auto→adaptive map

Add new models in ENDPOINT_ASPECT_POLICIES only.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

# ---------------------------------------------------------------------------
# UI labels when aspect is omitted
# ---------------------------------------------------------------------------

ASPECT_FOLLOWS_STILL = "Follows still"
ASPECT_FOLLOWS_REFS = "Follows refs / adaptive"

PolicyKind = Literal["omit", "send"]
UiKind = Literal["still", "refs", ""]

# Keys that may carry aspect in payloads (strip all for omit endpoints)
_ASPECT_KEYS = (
    "aspect_ratio",
    "aspectRatio",
    "aspect",
    "image_aspect_ratio",
    "imageAspectRatio",
    "video_aspect_ratio",
    "videoAspectRatio",
    "output_aspect_ratio",
    "outputAspectRatio",
    "aspect_ratio_type",
    "aspectRatioType",
    "target_aspect_ratio",
    "targetAspectRatio",
)


@dataclass(frozen=True)
class AspectPolicy:
    """Per-endpoint aspect rule."""

    kind: PolicyKind
    # omit: "still" | "refs" for UI label
    ui_kind: UiKind = "still"
    # send: allowed values (lowercase match); empty = pass-through non-sentinel
    allowed: tuple[str, ...] = ()
    # send: map bare "auto" → this value (e.g. H3 R2V → adaptive)
    auto_map: str | None = None
    # send: default when requested empty
    default: str | None = None
    note: str = ""


# (endpoint substring lowercase, policy)
# Order: more specific needles first where needed.
# OMIT list (strict): FLUX 3 pure I2V + Kling I2V only.
# Seedance R2V ACCEPTS aspect_ratio (auto | ratios) — SEND, not omit.
ENDPOINT_ASPECT_POLICIES: tuple[tuple[str, AspectPolicy], ...] = (
    # --- SEND: Seedance 2.0 Reference-to-Video (standard + fast) — fal docs ---
    (
        "bytedance/seedance-2.0/fast/reference-to-video",
        AspectPolicy(
            kind="send",
            allowed=(
                "auto",
                "21:9",
                "16:9",
                "4:3",
                "1:1",
                "3:4",
                "9:16",
            ),
            default="auto",
            note="Seedance fast R2V aspect enum (default auto).",
        ),
    ),
    (
        "bytedance/seedance-2.0/reference-to-video",
        AspectPolicy(
            kind="send",
            allowed=(
                "auto",
                "21:9",
                "16:9",
                "4:3",
                "1:1",
                "3:4",
                "9:16",
            ),
            default="auto",
            note="Seedance R2V aspect enum (default auto).",
        ),
    ),
    # --- OMIT: FLUX 3 pure I2V (first-last excluded in matcher) ---
    (
        "blackforestlabs/flux-3/image-to-video",
        AspectPolicy(
            kind="omit",
            ui_kind="still",
            note="FLUX 3 I2V follows the still (no aspect_ratio).",
        ),
    ),
    # --- OMIT: Kling image-to-video family ---
    (
        "kling-video/",
        AspectPolicy(
            kind="omit",
            ui_kind="still",
            note="Kling I2V follows the start still (no aspect_ratio).",
        ),
    ),
    # --- SEND: MiniMax H3 reference / omni (adaptive, not bare auto) ---
    (
        "minimax/h3/reference-to-video",
        AspectPolicy(
            kind="send",
            allowed=(
                "adaptive",
                "21:9",
                "16:9",
                "4:3",
                "1:1",
                "3:4",
                "9:16",
            ),
            auto_map="adaptive",
            default="adaptive",
            note="H3 R2V aspect enum; auto→adaptive.",
        ),
    ),
    (
        "minimax/h3/text-to-video",
        AspectPolicy(
            kind="send",
            allowed=(
                "adaptive",
                "21:9",
                "16:9",
                "4:3",
                "1:1",
                "3:4",
                "9:16",
            ),
            auto_map="adaptive",
            default="16:9",
            note="H3 T2V aspect enum.",
        ),
    ),
    # --- SEND: Seedance I2V (not reference) ---
    (
        "bytedance/seedance-2.0/fast/image-to-video",
        AspectPolicy(
            kind="send",
            allowed=(
                "auto",
                "21:9",
                "16:9",
                "4:3",
                "1:1",
                "3:4",
                "9:16",
            ),
            default="auto",
            note="Seedance I2V accepts aspect incl. auto.",
        ),
    ),
    (
        "bytedance/seedance-2.0/image-to-video",
        AspectPolicy(
            kind="send",
            allowed=(
                "auto",
                "21:9",
                "16:9",
                "4:3",
                "1:1",
                "3:4",
                "9:16",
            ),
            default="auto",
            note="Seedance I2V accepts aspect incl. auto.",
        ),
    ),
    # --- SEND: FLUX 3 first-last / T2V / extend / keyframes ---
    (
        "blackforestlabs/flux-3/first-last-frame-to-video",
        AspectPolicy(
            kind="send",
            allowed=("auto", "16:9", "9:16", "1:1", "4:3", "3:4", "21:9"),
            default="auto",
            note="FLUX 3 first→last accepts aspect.",
        ),
    ),
    (
        "blackforestlabs/flux-3/text-to-video",
        AspectPolicy(
            kind="send",
            allowed=("auto", "16:9", "9:16", "1:1", "4:3", "3:4", "21:9"),
            default="auto",
            note="FLUX 3 T2V accepts aspect.",
        ),
    ),
    (
        "blackforestlabs/flux-3/extend-video",
        AspectPolicy(
            kind="send",
            allowed=("auto", "16:9", "9:16", "1:1", "4:3", "3:4", "21:9"),
            default="auto",
            note="FLUX 3 extend accepts aspect.",
        ),
    ),
    (
        "blackforestlabs/flux-3/keyframes-to-video",
        AspectPolicy(
            kind="send",
            allowed=("auto", "16:9", "9:16", "1:1", "4:3", "3:4", "21:9"),
            default="auto",
            note="FLUX 3 keyframes accepts aspect.",
        ),
    ),
    # --- SEND: Grok R2V ---
    (
        "grok-imagine-video/v1.5/reference-to-video",
        AspectPolicy(
            kind="send",
            allowed=("16:9", "4:3", "3:2", "1:1", "2:3", "3:4", "9:16"),
            default="16:9",
            note="Grok R2V aspect enum.",
        ),
    ),
    # --- SEND: Grok T2V ---
    (
        "grok-imagine-video/v1.5/text-to-video",
        AspectPolicy(
            kind="send",
            allowed=("16:9", "4:3", "3:2", "1:1", "2:3", "3:4", "9:16"),
            default="16:9",
            note="Grok T2V aspect enum.",
        ),
    ),
)

# Back-compat: old matcher list shape used by callers that only care about omit UI
OMIT_ASPECT_ENDPOINT_MATCHERS: tuple[tuple[str, str], ...] = tuple(
    (needle, pol.ui_kind or "still")
    for needle, pol in ENDPOINT_ASPECT_POLICIES
    if pol.kind == "omit"
)


def normalize_endpoint_for_omit(endpoint: str | None) -> str:
    """Lowercase endpoint with trailing /draft stripped."""
    ep = (endpoint or "").strip().lower()
    if not ep:
        return ""
    while ep.endswith("/draft"):
        ep = ep[: -len("/draft")]
    if "/draft/" in ep:
        ep = ep.replace("/draft/", "/")
    return ep


def _policy_for_endpoint(endpoint: str | None) -> AspectPolicy | None:
    """Return matching policy or None (unknown → caller may no-op)."""
    ep = normalize_endpoint_for_omit(endpoint)
    if not ep:
        return None
    for needle, pol in ENDPOINT_ASPECT_POLICIES:
        if needle not in ep:
            continue
        # FLUX 3 pure I2V needle must not match first-last
        if (
            needle == "blackforestlabs/flux-3/image-to-video"
            and "first-last" in ep
        ):
            continue
        # Kling: only omit image-to-video, not video-to-video / multi-shot T2V-ish
        if needle == "kling-video/":
            if "image-to-video" not in ep:
                continue
        # Hailuo: only I2V-style (image-to-video paths)
        if needle == "hailuo" and "image-to-video" not in ep and "image_to_video" not in ep:
            # hailuo bridge sometimes uses image-to-video endpoint — if not, skip
            if "first-last" not in ep and "image" not in ep:
                continue
        return pol
    return None


def endpoint_omits_aspect_ratio(endpoint: str | None) -> bool:
    """True when the API must not receive aspect_ratio (even auto)."""
    pol = _policy_for_endpoint(endpoint)
    return pol is not None and pol.kind == "omit"


def get_aspect_policy(endpoint: str | None) -> AspectPolicy | None:
    """Public: resolve policy for an endpoint."""
    return _policy_for_endpoint(endpoint)


def aspect_omit_ui_label(endpoint: str | None = None) -> str:
    """Disabled dropdown label for omit models."""
    pol = _policy_for_endpoint(endpoint)
    if pol and pol.ui_kind == "refs":
        return ASPECT_FOLLOWS_REFS
    return ASPECT_FOLLOWS_STILL


def aspect_omit_note(endpoint: str | None = None) -> str:
    """Short job-log note when aspect is stripped."""
    pol = _policy_for_endpoint(endpoint)
    if pol and pol.note:
        return f"aspect_ratio omitted — {pol.note}"
    if pol and pol.kind == "omit":
        if pol.ui_kind == "refs":
            return (
                "aspect_ratio omitted — reference-to-video follows refs "
                "(do not send aspect_ratio, not even auto)."
            )
        return (
            "aspect_ratio omitted — follows the still "
            "(do not send aspect_ratio, not even auto)."
        )
    return "aspect_ratio omitted (endpoint rejects it)."


def spec_omits_aspect_ratio(spec: Any) -> bool:
    """Spec-level: omit_aspect_ratio flag or endpoint omit policy."""
    if spec is None:
        return False
    if bool(getattr(spec, "omit_aspect_ratio", False)):
        return True
    ep = getattr(spec, "endpoint", None) or getattr(spec, "draft_endpoint", None)
    if endpoint_omits_aspect_ratio(ep):
        return True
    # VideoModelSpec with no aspect param on known omit task
    if hasattr(spec, "aspect_ratio_param") and not getattr(
        spec, "aspect_ratio_param", True
    ):
        if endpoint_omits_aspect_ratio(ep) or bool(
            getattr(spec, "omit_aspect_ratio", False)
        ):
            return True
        # param None alone is not always omit (many V2V edits) — trust endpoint
        if ep and endpoint_omits_aspect_ratio(ep):
            return True
    return False


def is_aspect_omit_ui_sentinel(value: str | None) -> bool:
    """True for disabled-control labels that must not be posted to the API."""
    if value is None:
        return False
    low = str(value).strip().lower()
    if not low:
        return False
    sentinels = {
        ASPECT_FOLLOWS_STILL.lower(),
        ASPECT_FOLLOWS_REFS.lower(),
        "follows still",
        "follows refs / adaptive",
        "follows refs",
        "auto (from start still)",
        "auto (from ref still)",
        "—",
        "none",
        "match source",
    }
    return low in sentinels


def _pop_aspect_keys(args: dict[str, Any]) -> None:
    for k in _ASPECT_KEYS:
        args.pop(k, None)


def _debug_log(msg: str) -> None:
    if os.environ.get("AMS_ASPECT_POLICY_LOG", "").strip() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        print(f"[aspect_policy] {msg}", flush=True)


def aspect_debug_line(
    *,
    endpoint: str | None,
    arguments: dict[str, Any] | None,
    mode: str | None = None,
    omit: bool | None = None,
    source: str = "subscribe",
) -> str:
    """One-line ASPECT_DEBUG for UI + log file."""
    args = dict(arguments or {})
    ep = endpoint or ""
    if omit is None:
        omit = endpoint_omits_aspect_ratio(ep) or (
            "seedance" in ep.lower() and "reference-to-video" in ep.lower()
        )
    # Prefer first present aspect key, else <missing>
    ar_val: Any = "<missing>"
    for k in _ASPECT_KEYS:
        if k in args:
            ar_val = args.get(k)
            break
    keys = sorted(str(k) for k in args.keys())
    mode_bit = f" mode={mode}" if mode else ""
    return (
        f"ASPECT_DEBUG source={source}{mode_bit} "
        f"endpoint={ep} omit={bool(omit)} "
        f"keys={keys} aspect_ratio={ar_val!r}"
    )


def append_aspect_debug_log(line: str, *, output_dir: str | Path | None = None) -> Path:
    """
    Append one ASPECT_DEBUG line to outputs/aspect_debug.log (create if missing).

    Always writes so failed jobs (no job_*.json) still leave a trail.
    """
    from datetime import datetime, timezone

    try:
        from media_studio.config import OUTPUT_DIR

        base = Path(output_dir) if output_dir else OUTPUT_DIR
    except Exception:
        base = Path(output_dir) if output_dir else Path("outputs")
    base = Path(base)
    try:
        base.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    path = base / "aspect_debug.log"
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    text = f"{ts} {line.rstrip()}\n"
    try:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(text)
    except Exception:
        # Fallback: project-relative
        try:
            fb = Path(__file__).resolve().parent.parent / "outputs" / "aspect_debug.log"
            fb.parent.mkdir(parents=True, exist_ok=True)
            with fb.open("a", encoding="utf-8") as fh:
                fh.write(text)
            return fb
        except Exception:
            pass
    return path


def strip_all_aspect_keys(arguments: dict[str, Any] | None) -> dict[str, Any]:
    """Pop every known aspect alias from a payload dict."""
    out = dict(arguments or {})
    _pop_aspect_keys(out)
    return out


# ---------------------------------------------------------------------------
# Seedance 2.0 reference-to-video payload allowlist (fal OpenAPI)
# ---------------------------------------------------------------------------

SEEDANCE_R2V_ALLOWLIST: frozenset[str] = frozenset(
    {
        "prompt",
        "image_urls",
        "video_urls",
        "audio_urls",
        "resolution",
        "duration",
        "aspect_ratio",
        "generate_audio",
        "seed",
        "end_user_id",
    }
)

SEEDANCE_R2V_RESOLUTIONS: frozenset[str] = frozenset({"480p", "720p"})
SEEDANCE_R2V_ASPECTS: frozenset[str] = frozenset(
    {"auto", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"}
)


def is_seedance_reference_endpoint(endpoint: str | None) -> bool:
    """True for Seedance 2.0 reference-to-video (standard or fast)."""
    ep = (endpoint or "").strip().lower()
    if not ep:
        return False
    return "seedance" in ep and "reference-to-video" in ep


def sanitize_seedance_r2v_arguments(
    arguments: dict[str, Any] | None,
    *,
    endpoint: str | None = None,
) -> dict[str, Any]:
    """
    Allowlist + coerce types for Seedance R2V / fast R2V / V2V ref-edit.

    - Drop negative_prompt and any non-schema keys
    - duration → str ("4".."15" or "auto"), never int
    - resolution ∈ {480p, 720p}; map 1080p/4k → 720p
    - aspect_ratio default "auto" if missing/empty; never omit for this endpoint
    """
    if not is_seedance_reference_endpoint(endpoint):
        return dict(arguments or {})

    raw = dict(arguments or {})
    out: dict[str, Any] = {}

    # Prompt
    if raw.get("prompt") is not None:
        out["prompt"] = str(raw["prompt"])

    # Media arrays
    for fk in ("image_urls", "video_urls", "audio_urls"):
        val = raw.get(fk)
        if isinstance(val, list) and val:
            out[fk] = [str(u) for u in val if u]
        elif isinstance(val, str) and val.strip():
            out[fk] = [val.strip()]

    # Duration: string only
    dur = raw.get("duration")
    if dur is not None and dur != "":
        if isinstance(dur, (int, float)) and not isinstance(dur, bool):
            d_s = str(int(dur))
        else:
            d_s = str(dur).strip().lower().replace("s", "").strip()
        if d_s == "auto":
            out["duration"] = "auto"
        else:
            try:
                n = int(round(float(d_s)))
                n = max(4, min(15, n))
                out["duration"] = str(n)
            except (TypeError, ValueError):
                out["duration"] = "5"
    else:
        out["duration"] = "5"

    # Resolution: 480p | 720p only
    res = str(raw.get("resolution") or "720p").strip().lower()
    if res in ("1080p", "4k", "2k", "1080", "4k"):
        res = "720p"
    if res not in ("480p", "720p"):
        res = "720p"
    out["resolution"] = res

    # Aspect: always send valid enum (docs accept auto)
    ar = raw.get("aspect_ratio")
    if ar is None or str(ar).strip() == "":
        ar_s = "auto"
    else:
        ar_s = str(ar).strip().lower()
        if is_aspect_omit_ui_sentinel(ar_s) or ar_s in ("follows still", "follows refs"):
            ar_s = "auto"
    if ar_s not in SEEDANCE_R2V_ASPECTS:
        ar_s = "auto"
    out["aspect_ratio"] = ar_s

    # Audio
    if "generate_audio" in raw:
        out["generate_audio"] = bool(raw["generate_audio"])

    # Optional seed / end_user_id
    if raw.get("seed") is not None:
        try:
            out["seed"] = int(raw["seed"])
        except (TypeError, ValueError):
            pass
    if raw.get("end_user_id"):
        out["end_user_id"] = str(raw["end_user_id"])

    # Strict allowlist (drops negative_prompt, extra_defaults junk, etc.)
    return {k: v for k, v in out.items() if k in SEEDANCE_R2V_ALLOWLIST and v is not None}


def apply_aspect_policy(
    arguments: dict[str, Any] | None,
    *,
    endpoint: str | None,
    mode: str | None = None,
    requested: str | None = None,
) -> dict[str, Any]:
    """
    Apply endpoint aspect policy to a fal argument dict.

    - omit: pop aspect_ratio and aliases; never leave auto / Follows …
    - send: coerce to allowed enum; map auto when policy.auto_map set
    - no policy: strip UI sentinels only; leave real values if present

    ``requested`` overrides value already in arguments when provided.
    ``mode`` is reserved for future mode-specific tweaks (i2v/r2v/t2v).
    """
    out = dict(arguments or {})
    ep = endpoint or ""
    pol = _policy_for_endpoint(ep)

    # Resolve requested value
    if requested is not None:
        raw = requested
    else:
        raw = None
        for k in _ASPECT_KEYS:
            if k in out and out[k] is not None:
                raw = out[k]
                break

    raw_s = str(raw).strip() if raw is not None else ""

    # UI sentinels ("Follows still/refs") → treat as empty; SEND policies use default
    # (e.g. Seedance R2V → auto). Do not leave sentinel strings in the payload.
    if is_aspect_omit_ui_sentinel(raw_s):
        raw_s = ""
        _pop_aspect_keys(out)

    if pol is None:
        # Unknown endpoint: strip sentinels only; keep numeric ratios
        if not raw_s or is_aspect_omit_ui_sentinel(raw_s):
            _pop_aspect_keys(out)
            _debug_log(f"unknown omit-sentinel endpoint={ep!r}")
        else:
            out["aspect_ratio"] = raw_s
            _debug_log(f"unknown send value={raw_s!r} endpoint={ep!r}")
        return out

    if pol.kind == "omit":
        _pop_aspect_keys(out)
        _debug_log(f"omit endpoint={ep!r} mode={mode!r}")
        return out

    # --- send ---
    value = raw_s
    if not value and pol.default:
        value = pol.default
    if not value:
        _pop_aspect_keys(out)
        _debug_log(f"send empty→omit endpoint={ep!r}")
        return out

    low = value.lower()
    if low == "auto" and pol.auto_map:
        value = pol.auto_map
        low = value.lower()

    if pol.allowed:
        allowed_low = {a.lower(): a for a in pol.allowed}
        if low in allowed_low:
            # Preserve canonical casing from allowlist
            value = allowed_low[low]
        else:
            # Invalid for this endpoint → default or omit
            if pol.default and pol.default.lower() in allowed_low:
                value = allowed_low[pol.default.lower()]
            elif pol.auto_map and pol.auto_map.lower() in allowed_low:
                value = allowed_low[pol.auto_map.lower()]
            else:
                _pop_aspect_keys(out)
                _debug_log(
                    f"send invalid {raw_s!r}→omit endpoint={ep!r} allowed={pol.allowed}"
                )
                return out

    _pop_aspect_keys(out)
    out["aspect_ratio"] = value
    _debug_log(f"send value={value!r} endpoint={ep!r} mode={mode!r}")
    return out


def strip_omitted_aspect(
    arguments: dict[str, Any] | None,
    *,
    endpoint: str | None = None,
) -> dict[str, Any]:
    """
    Last-mile defense: apply policy for the target endpoint.

    Alias of apply_aspect_policy for call sites that only pass endpoint.
    """
    return apply_aspect_policy(arguments, endpoint=endpoint)


# Alias used historically
normalize_endpoint = normalize_endpoint_for_omit
