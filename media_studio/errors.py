"""User-facing error messages (Windows-friendly)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

ProviderId = Literal["fal", "xai"]

# Real provider top-up / billing pages (open in browser)
FAL_TOPUP_URL = "https://fal.ai/dashboard/usage-billing/credits"
FAL_BILLING_URL = "https://fal.ai/dashboard/billing"
XAI_TOPUP_URL = "https://console.x.ai/team/default/billing"
XAI_CREDITS_URL = "https://console.x.ai/team/default/billing/credits"

# Keywords that strongly indicate credits / quota / billing (not generic auth)
_CREDITS_HINTS = (
    "insufficient credit",
    "insufficient credits",
    "insufficient balance",
    "insufficient funds",
    "insufficient quota",
    "exhausted balance",
    "exhausted credits",
    "out of credits",
    "out of credit",
    "no credits",
    "no credit",
    "credit balance",
    "credits depleted",
    "credits exhausted",
    "balance depleted",
    "prepaid credits",
    "top up your balance",
    "top-up",
    "top up",
    "add credits",
    "purchase credits",
    "user is locked",
    "account is locked",
    "account locked",
    "payment required",
    "402",
    "billing",
    "quota exceeded",
    "quota limit",
    "rate limit.*credit",  # rare phrasing
    "spending limit",
    "spend limit",
    "usage limit",
)


@dataclass(frozen=True)
class CreditsErrorInfo:
    """Structured insufficient-credits signal for UI modals."""

    provider: ProviderId
    provider_label: str  # "fal.ai" | "xAI (Grok)"
    message: str
    topup_url: str
    topup_button_label: str


@dataclass(frozen=True)
class ContentPolicyInfo:
    """Structured content / partner-policy rejection for UI popup + status."""

    kind: Literal["likeness", "other"]
    short_reason: str  # plain "because" clause + status one-liner
    full_error: str  # raw provider / app error for Copy
    body: str  # full popup body including "Your generation was stopped because:"


# Provider type strings and message phrases that indicate policy rejections
_POLICY_TYPE_MARKERS = (
    "content_policy_violation",
    "partner_validation_failed",
    "content_policy",
    "content policy",
    "policy_violation",
    "safety_violation",
    "moderation",
    "sensitive content",
    "nsfw",
)

_LIKENESS_MARKERS = (
    "likeness",
    "real people",
    "real person",
    "real-world person",
    "private information",
    "face filter",
    "photoreal face",
    "photorealistic face",
    "looks like a real",
    "resemblance to",
    "celebrity",
)

_LIKENESS_REASON = (
    "The reference images may look like real people. Seedance’s partner filter "
    "often blocks photoreal faces (including AI-generated ones that look "
    "photographic). Try stylized characters or a character-sheet layout."
)


def detect_content_policy_violation(
    exc: BaseException | str,
    *,
    context: str = "",
) -> ContentPolicyInfo | None:
    """
    If this looks like a fal/partner content or face-filter rejection, return
    structured copy for the Generation stopped popup and status line.

    Detects:
    - type-like tokens: content_policy_violation, partner_validation_failed
    - message phrases: likeness / real people / private information / sensitive content
    """
    raw = str(exc).strip() if not isinstance(exc, str) else exc.strip()
    if not raw:
        return None
    low = raw.lower()
    ctx = (context or "").lower()
    combined = f"{ctx} {low}"

    has_type = any(m in combined for m in _POLICY_TYPE_MARKERS)
    has_likeness = any(m in combined for m in _LIKENESS_MARKERS)
    # "blocked" alone is too broad; require policy context
    has_blocked = "blocked" in combined and any(
        w in combined
        for w in ("content", "policy", "safety", "partner", "moderation", "prompt")
    )

    if not (has_type or has_likeness or has_blocked):
        return None

    if has_likeness or (
        "partner_validation" in combined
        and any(w in combined for w in ("face", "person", "people", "likeness", "photo"))
    ):
        reason = _LIKENESS_REASON
        kind: Literal["likeness", "other"] = "likeness"
    else:
        # Shortened provider message (drop long JSON / stack noise)
        reason = _shorten_policy_message(raw)
        kind = "other"

    body = f"Your generation was stopped because: {reason}"
    return ContentPolicyInfo(
        kind=kind,
        short_reason=reason,
        full_error=raw,
        body=body,
    )


def _shorten_policy_message(raw: str) -> str:
    """One short plain-language clause from a provider policy error."""
    text = re.sub(r"\s+", " ", (raw or "").strip())
    # Prefer nested "message": "..." if present
    m = re.search(r'"message"\s*:\s*"([^"]{8,200})"', text, re.I)
    if m:
        text = m.group(1).strip()
    # Drop common prefixes
    for pref in (
        "fal subscribe failed:",
        "fal (",
        "error:",
        "exception:",
        "generate:",
    ):
        if text.lower().startswith(pref):
            text = text[len(pref) :].strip()
    # First sentence-ish chunk
    for sep in (". ", "; ", "\n"):
        if sep in text:
            head = text.split(sep, 1)[0].strip()
            if len(head) >= 12:
                text = head
                break
    text = _clip(text, 220)
    if not text:
        return (
            "The provider blocked this request under its content policy. "
            "Soften the prompt or change references, then retry."
        )
    # Ensure it reads as a reason clause
    if text[0].islower():
        text = text[0].upper() + text[1:]
    if not text.endswith("."):
        text = text + "."
    return text


def detect_credits_error(
    exc: BaseException | str,
    *,
    context: str = "",
) -> CreditsErrorInfo | None:
    """
    If this looks like a credits / quota / billing failure, return provider info.

    Distinguishes fal vs xAI from context + message text.
    """
    raw = str(exc).strip() if not isinstance(exc, str) else exc.strip()
    low = raw.lower()
    ctx = (context or "").lower()
    combined = f"{ctx} {low}"

    if not _looks_like_credits_error(low, combined):
        return None

    provider = _infer_provider(low, ctx)
    if provider == "xai":
        return CreditsErrorInfo(
            provider="xai",
            provider_label="xAI (Grok)",
            message=(
                "Your xAI / Grok account is out of API credits (or has hit a spend limit). "
                "Top up in the xAI console, then retry."
            ),
            topup_url=XAI_TOPUP_URL,
            topup_button_label="Top up xAI",
        )
    return CreditsErrorInfo(
        provider="fal",
        provider_label="fal.ai",
        message=(
            "Your fal.ai account is out of credits (or locked for insufficient balance). "
            "Top up on the fal dashboard, then retry."
        ),
        topup_url=FAL_TOPUP_URL,
        topup_button_label="Top up fal",
    )


def _looks_like_credits_error(low: str, combined: str) -> bool:
    # Explicit hints
    for hint in _CREDITS_HINTS:
        if "*" in hint:
            # crude wildcard: "rate limit.*credit" style not needed often
            parts = hint.split("*")
            if all(p in combined for p in parts if p):
                return True
        elif hint in combined:
            return True
    # "insufficient" near money/credit words
    if "insufficient" in combined and any(
        w in combined for w in ("credit", "balance", "fund", "quota", "payment")
    ):
        return True
    if "locked" in combined and any(
        w in combined for w in ("balance", "credit", "exhaust", "billing")
    ):
        return True
    # OpenAI-compatible xAI: insufficient_quota
    if "insufficient_quota" in combined or "insufficient_quota" in low:
        return True
    if "payment" in combined and "required" in combined:
        return True
    return False


def _infer_provider(low: str, ctx: str) -> ProviderId:
    blob = f"{ctx} {low}"
    # Strong fal signals
    if any(
        x in blob
        for x in (
            "fal.ai",
            "fal (",
            "fal:",
            "fal ",
            "fal_key",
            "fal-ai",
            "fal.media",
            "exhausted balance",
            "user is locked",
        )
    ):
        # "exhausted balance" / locked is the classic fal lock message
        if "xai" not in blob and "grok" not in blob and "openai" not in blob:
            if any(
                x in blob
                for x in (
                    "fal",
                    "exhausted balance",
                    "user is locked",
                    "top up your balance at fal",
                )
            ):
                return "fal"
    if any(
        x in blob
        for x in (
            "xai",
            "x.ai",
            "grok",
            "openai",
            "enhance",
            "insufficient_quota",
            "console.x.ai",
        )
    ):
        return "xai"
    # Context prefixes from our code
    if any(x in ctx for x in ("enhance", "qc", "local edit", "suggest", "vision", "grok")):
        return "xai"
    if any(x in ctx for x in ("fal", "upload", "video edit", "generate", "tool")):
        return "fal"
    # Default: generation path is usually fal
    return "fal"


@dataclass(frozen=True)
class FriendlyError:
    """One-line human message + optional technical detail (collapsed in UI)."""

    message: str
    detail: str = ""
    suggested_fix: str = ""


def _infer_media_kind(
    raw: str,
    context: str = "",
    media_kind: str | None = None,
) -> str | None:
    """
    ``image`` | ``video`` | None — used to pick the right “too large” guidance.
    Prefer explicit ``media_kind``; else sniff path/mime/context.
    """
    if media_kind:
        mk = media_kind.strip().lower()
        if mk in ("image", "still", "ref", "photo", "png", "jpg", "jpeg"):
            return "image"
        if mk in ("video", "clip", "motion"):
            return "video"
    blob = f"{context} {raw}".lower()
    image_hints = (
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".gif",
        ".bmp",
        "image/",
        "image_url",
        "start_image",
        "reference image",
        "still",
        "character still",
        "scene still",
        "downscale the still",
    )
    video_hints = (
        ".mp4",
        ".mov",
        ".webm",
        ".m4v",
        ".mkv",
        "video/",
        "render-in-place",
        "render in place",
    )
    has_image = any(h in blob for h in image_hints)
    has_video = any(h in blob for h in video_hints)
    if has_image and not has_video:
        return "image"
    if has_video and not has_image:
        return "video"
    # Director / Vision I2V paths are predominantly still refs
    ctx = (context or "").lower()
    if any(x in ctx for x in ("director", "i2v", "image-to-video", "image edit")):
        return "image"
    return None


def format_friendly_error(
    exc: BaseException | str,
    *,
    context: str = "",
    media_kind: str | None = None,
) -> FriendlyError:
    """Structured plain-language error; ``message`` is the one-liner for status."""
    raw = str(exc).strip() if not isinstance(exc, str) else exc.strip()
    msg = friendly_error(exc, context=context, media_kind=media_kind)
    # Suggested fix is already baked into many messages; extract trailing "Details:" if any
    detail = raw if raw and raw not in msg else ""
    fix = ""
    low = msg.lower()
    kind = _infer_media_kind(raw, context, media_kind) or _infer_media_kind(msg, context)
    if "top up" in low or "credits" in low:
        fix = "Open billing and add credits, then retry."
    elif "too large" in low or "downscale" in low:
        if kind == "image":
            fix = "Downscale the reference still (longest edge ≤1920) and retry."
        else:
            fix = "Render a short graded proxy (3–10s, ≤~100 MB) and re-upload local."
    elif "proxy" in low and kind != "image":
        fix = "Render a short graded proxy (3–10s, ≤~100 MB) and re-upload local."
    elif "download failed" in low or "re-select" in low:
        fix = "Always re-upload from a local path; do not reuse old fal.media URLs."
    elif "api key" in low or "settings" in low:
        fix = "Open Settings (gear) and paste a valid key."
    elif "rate limit" in low:
        fix = "Wait 30–60s and try again."
    elif "network" in low:
        fix = "Check internet / VPN / firewall, then retry."
    return FriendlyError(message=msg, detail=_clip(detail, 400) if detail else "", suggested_fix=fix)


def friendly_error(
    exc: BaseException | str,
    *,
    context: str = "",
    media_kind: str | None = None,
) -> str:
    """
    Turn raw exceptions / fal messages into short, actionable status text.

    ``media_kind``: ``image`` | ``video`` — when set (or inferred), “too large”
    messages avoid the wrong proxy advice (e.g. Render-in-Place on stills).
    """
    raw = str(exc).strip() if not isinstance(exc, str) else exc.strip()
    low = raw.lower()
    prefix = f"{context}: " if context else ""
    kind = _infer_media_kind(raw, context, media_kind)

    # Credits / quota — specific, not generic unknown
    credits = detect_credits_error(raw, context=context)
    if credits is not None:
        return (
            f"{prefix}Insufficient credits on {credits.provider_label}. "
            f"Top up: {credits.topup_url}"
        )

    # Content policy / partner face filter — before generic "validation" branch
    # (partner_validation_failed contains "validation" and would otherwise mis-map)
    policy = detect_content_policy_violation(raw, context=context)
    if policy is not None:
        return f"{prefix}{policy.short_reason}"

    # API keys
    if "xai_api_key" in low or ("api key" in low and "xai" in low) or "xai api key is not set" in low:
        return (
            f"{prefix}Missing xAI API key. Open Settings (gear icon) and paste your key "
            "from https://console.x.ai/team/default/api-keys"
        )
    if "fal_key" in low or "fal_api_key" in low or "fal api key is not set" in low:
        return (
            f"{prefix}Missing FAL API key. Open Settings (gear icon) and paste your key "
            "from https://fal.ai/dashboard/keys"
        )

    # Auth (not credits)
    if any(x in low for x in ("401", "403", "unauthorized", "forbidden", "invalid api key")):
        return (
            f"{prefix}API rejected the request (auth). Check that your key is valid "
            "and has credit. Details: "
            + _clip(raw, 160)
        )

    # Multi-ref megapixel / combined area (Flux 2 sheet compose, etc.)
    if any(
        x in low
        for x in (
            "requested area too large",
            "area too large",
            "megapixel",
            "mega-pixel",
            "too many megapixels",
            "max megapixel",
        )
    ):
        return (
            f"{prefix}Too many/large refs for this model — try Local layout, "
            "fewer angles, or a lower Resolution."
        )

    # File too large / payload limits — image vs video copy
    if any(
        x in low
        for x in (
            "too large",
            "file size",
            "payload too large",
            "413",
            "entity too large",
            "max size",
            "exceeds the maximum",
        )
    ):
        if kind == "image":
            return (
                f"{prefix}Reference image too large for the API — "
                "downscale the still (longest edge ≤1920) and retry. "
                "Director auto-downscales refs when possible."
            )
        if kind == "video":
            return (
                f"{prefix}File is too large for the API. "
                "Use a shorter 3–10s Render-in-Place proxy (≤~100 MB), then retry."
            )
        # Unknown: mention both without implying video is required
        return (
            f"{prefix}File is too large for the API. "
            "If this is a still, downscale (longest edge ≤1920) and retry; "
            "if video, use a shorter 3–10s Render-in-Place proxy (≤~100 MB)."
        )

    # Aspect ratio / dimension enum rejections
    if "aspect" in low or "aspect_ratio" in low:
        # Keep raw fal body / director detail when already present
        if (
            "sent aspect_ratio=" in low
            or "this endpoint accepts" in low
            or "raw fal:" in low
            or "raw:" in low
            or "unexpected" in low
            or "additional propert" in low
            or "not permitted" in low
        ):
            if prefix and not raw.startswith(prefix.rstrip(": ")):
                return f"{prefix}{raw}"
            return raw or f"{prefix}Aspect ratio not accepted by this model."
        if "flux" in low or "flux-3" in low or "blackforest" in low:
            return (
                f"{prefix}Aspect ratio not accepted. FLUX 3 I2V follows the still — "
                "do not send aspect_ratio (not even auto). Hide Aspect / use "
                "“Follows still”, then retry."
            )
        if "seedance" in low:
            # Prefer original message (may be wrong-field, not aspect enum)
            return raw if raw else (
                f"{prefix}Seedance R2V: check aspect_ratio (auto|ratios), "
                "resolution (480p|720p), duration as string, no negative_prompt."
            )
        return (
            f"{prefix}Aspect ratio not accepted by this model. "
            "For Kling I2V or FLUX 3 pure I2V, aspect follows the still "
            "(do not send aspect_ratio). Seedance R2V uses auto or listed ratios. "
            "For pure text multi-shot use exactly 16:9, 9:16, or 1:1. Retry."
        )
    if any(x in low for x in ("invalid resolution", "resolution", "unsupported size")) and (
        "422" in low or "enum" in low or "allowed" in low or "must be" in low
    ):
        return (
            f"{prefix}Resolution not supported for this model. "
            "Choose a listed resolution (e.g. 720p / 1K / 2K) and try again."
        )

    # Validation
    if "422" in low or "unprocessable" in low or "validation" in low:
        hint = ""
        if "duration" in low or ("3" in low and "10" in low) or "too long" in low:
            hint = (
                " Clip length rejected — try 3–15s (Kling video→audio ≈3–20s; "
                "MMAudio duration ≤30s), mp4/mov."
            )
        if "image" in low and "large" in low:
            hint = " Try a smaller image."
        if "content_type" in low or "mime" in low:
            hint = " Use mp4/mov for video or png/jpg for stills."
        if "sound_effect_prompt" in low or "200" in low and "char" in low:
            hint = " Sound-effect prompt max 200 characters (Kling) — shorten and retry."
        return f"{prefix}Request rejected by the model (invalid input).{hint} {_clip(raw, 160)}"

    # Network / timeouts
    if any(x in low for x in ("timeout", "timed out", "deadline")):
        return (
            f"{prefix}Timed out waiting for the provider. Video jobs can take several minutes — "
            "try again, or use a shorter clip. "
            + _clip(raw, 100)
        )
    if any(x in low for x in ("connection", "network", "dns", "ssl", "connecterror")):
        return f"{prefix}Network error talking to the API. Check internet / VPN / firewall. {_clip(raw, 120)}"

    # Files / Windows paths
    if isinstance(exc, FileNotFoundError) or "no such file" in low or "cannot find the path" in low:
        return (
            f"{prefix}File not found. If the path has unusual characters, try a simpler folder "
            f"(e.g. C:\\Users\\You\\ai-media-studio\\outputs). {_clip(raw, 140)}"
        )
    if "permission" in low or "access is denied" in low or "winerror 5" in low:
        return (
            f"{prefix}Permission denied writing/reading a file. Close programs locking the file "
            "and ensure the output folder is writable. "
            + _clip(raw, 100)
        )
    if "winerror" in low or "errno 22" in low:
        return (
            f"{prefix}Windows path/name problem. Filenames cannot contain "
            '<>:"/\\|?* — the app sanitizes outputs; check custom output folder paths. '
            + _clip(raw, 120)
        )

    # Rate limits
    if "429" in low or "rate limit" in low or "too many requests" in low:
        return f"{prefix}Rate limited by the API. Wait a moment and try again. {_clip(raw, 100)}"

    # fal could not pull an input URL (often large camera masters / stale CDN)
    if "file_download_error" in low or "failed to download the file" in low:
        return (
            f"{prefix}Download failed on fal’s side. "
            "Re-select the local clip (Render in Place proxy, 3–10s) so it re-uploads fresh — "
            "don’t reuse old fal.media links."
        )
    if "upload" in low and any(x in low for x in ("fail", "error", "timeout")):
        return (
            f"{prefix}Upload to fal failed. Check internet/VPN, then retry with a smaller file."
        )

    # Content policy fallback (detect already ran early; catch residual phrasing)
    if any(
        x in low
        for x in (
            "content policy",
            "safety",
            "nsfw",
            "moderation",
            "blocked",
            "content_policy",
        )
    ):
        return (
            f"{prefix}Provider blocked the content. Soften the prompt "
            "(no people/faces if rejected) and retry. "
            + _clip(raw, 120)
        )

    # Model / queue capacity
    if any(x in low for x in ("overloaded", "capacity", "no capacity", "503", "service unavailable")):
        return (
            f"{prefix}Provider is busy. Wait a minute and retry, or pick another model."
        )

    # Empty / generic fal
    if "fal subscribe failed" in low or "fal upload failed" in low:
        return f"{prefix}{_clip(raw, 240)}"

    if not raw:
        return f"{prefix}Unknown error."
    return f"{prefix}{_clip(raw, 280)}"


def _clip(text: str, n: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= n:
        return text
    return text[: n - 1] + "…"


def path_for_display(path: str | Path | None) -> str:
    """Normalize path string for status messages on Windows."""
    if not path:
        return ""
    try:
        return str(Path(path))
    except Exception:
        return str(path)
