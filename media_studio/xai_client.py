"""xAI (SpaceXAI) OpenAI-compatible client helpers (text + vision)."""

from __future__ import annotations

import base64
import mimetypes
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Sequence

from openai import OpenAI

from media_studio.config import XAI_BASE_URL, XAI_DEFAULT_MODEL

# Prefer a vision-capable Grok when available; fall back to text default.
XAI_VISION_MODEL = os.environ.get("XAI_VISION_MODEL", "grok-4.5")


class XAIConfigError(RuntimeError):
    """Raised when the API key or client cannot be configured."""


def get_api_key() -> str:
    """Return XAI_API_KEY from env or local Settings store."""
    key = (os.environ.get("XAI_API_KEY") or "").strip()
    if not key:
        try:
            from media_studio.secrets_store import effective_xai_key

            key = effective_xai_key()
            if key:
                os.environ["XAI_API_KEY"] = key
        except Exception:
            pass
    if not key:
        raise XAIConfigError(
            "xAI API key is not set. Open Settings (gear icon) and paste your key "
            "from https://console.x.ai/team/default/api-keys — only needed for "
            "Enhance Prompt / Grok text features."
        )
    return key


@lru_cache(maxsize=1)
def get_client() -> OpenAI:
    """Shared OpenAI-compatible client pointed at api.x.ai."""
    return OpenAI(api_key=get_api_key(), base_url=XAI_BASE_URL)


def _image_data_url(path: str | Path, *, max_side: int = 1280) -> str | None:
    """
    Encode a local still as a compressed data URL for vision requests.

    Shrinks large sources so payloads stay reasonable for chat vision APIs.
    """
    p = Path(path)
    if not p.is_file():
        return None
    try:
        from PIL import Image
        import io

        with Image.open(p) as im:
            im = im.convert("RGB")
            w, h = im.size
            scale = min(1.0, float(max_side) / float(max(w, h) or 1))
            if scale < 1.0:
                im = im.resize(
                    (max(1, int(w * scale)), max(1, int(h * scale))),
                    Image.Resampling.LANCZOS,
                )
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=82, optimize=True)
            b64 = base64.b64encode(buf.getvalue()).decode("ascii")
            return f"data:image/jpeg;base64,{b64}"
    except Exception:
        # Raw file fallback (may be large)
        try:
            mime, _ = mimetypes.guess_type(str(p))
            mime = mime or "image/jpeg"
            raw = p.read_bytes()
            if len(raw) > 4_000_000:
                return None
            b64 = base64.b64encode(raw).decode("ascii")
            return f"data:{mime};base64,{b64}"
        except OSError:
            return None


def chat_json(
    *,
    system: str,
    user: str,
    model: str | None = None,
    temperature: float = 0.4,
    max_tokens: int = 2048,
) -> str:
    """
    Call Grok with system + user messages and return the assistant text.

    Prefers JSON object responses when the API supports response_format.
    """
    client = get_client()
    model_id = model or XAI_DEFAULT_MODEL
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    return _complete(client, model_id, messages, temperature=temperature, max_tokens=max_tokens)


def chat_json_vision(
    *,
    system: str,
    user_text: str,
    image_paths: Sequence[str | Path] | None = None,
    model: str | None = None,
    temperature: float = 0.35,
    max_tokens: int = 2500,
) -> str:
    """
    Grok call with optional still image(s) for spatially grounded answers.

    Falls back to text-only if no readable images are provided.
    """
    paths = [Path(p) for p in (image_paths or []) if p]
    data_urls: list[str] = []
    for p in paths[:3]:
        url = _image_data_url(p)
        if url:
            data_urls.append(url)

    if not data_urls:
        return chat_json(
            system=system,
            user=user_text,
            model=model or XAI_DEFAULT_MODEL,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    client = get_client()
    model_id = model or XAI_VISION_MODEL or XAI_DEFAULT_MODEL
    content: list[dict[str, Any]] = [{"type": "text", "text": user_text}]
    for url in data_urls:
        content.append({"type": "image_url", "image_url": {"url": url}})
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": content},
    ]
    return _complete(client, model_id, messages, temperature=temperature, max_tokens=max_tokens)


def _complete(
    client: OpenAI,
    model_id: str,
    messages: list[dict[str, Any]],
    *,
    temperature: float,
    max_tokens: int,
) -> str:
    try:
        response = client.chat.completions.create(
            model=model_id,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
    except Exception:
        # Some deployments may not accept response_format; retry without it.
        response = client.chat.completions.create(
            model=model_id,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    content = response.choices[0].message.content
    if not content or not str(content).strip():
        raise RuntimeError("xAI returned an empty response.")
    return str(content).strip()
