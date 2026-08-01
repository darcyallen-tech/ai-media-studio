"""
Runware API client — SEPARATE from fal.

Used only for Aleph 2.0 (runway:aleph@2.0) and other second-provider models.
Never reads FAL_KEY. Never routes fal models through this client.
"""

from __future__ import annotations

import base64
import mimetypes
import time
import uuid
from pathlib import Path
from typing import Any, Callable

import httpx

ProgressCallback = Callable[[str], None]

RUNWARE_API_URL = "https://api.runware.ai/v1"
ALEPH_MODEL_ID = "runway:aleph@2.0"
# Docs: pricing starts at $0.28 / second
ALEPH_COST_PER_SECOND = 0.28
ALEPH_MIN_DURATION_S = 2.0
ALEPH_MAX_DURATION_S = 30.0
ALEPH_MAX_KEYFRAMES = 5
ALEPH_MAX_PROMPT_CHARS = 1000

_MIME_BY_EXT: dict[str, str] = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
    ".m4v": "video/x-m4v",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
}


class RunwareConfigError(RuntimeError):
    """Missing Runware / Aleph API key."""


class RunwareClientError(RuntimeError):
    """Runware request failure."""


def get_runware_key() -> str:
    """Effective Runware key from secrets or env — never fal."""
    key = ""
    try:
        from media_studio.secrets_store import effective_runware_key

        key = effective_runware_key()
    except Exception:
        pass
    if not key:
        import os

        key = (
            os.environ.get("RUNWARE_API_KEY")
            or os.environ.get("RUNWARE_KEY")
            or ""
        ).strip()
    if not key:
        raise RunwareConfigError(
            "Runware / Aleph API key is not set. Open Settings and paste your "
            "Runware key from https://my.runware.ai/ (optional second provider)."
        )
    return key


def has_runware_key() -> bool:
    try:
        return bool(get_runware_key())
    except RunwareConfigError:
        return False


def _mime_for(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in _MIME_BY_EXT:
        return _MIME_BY_EXT[ext]
    guess, _ = mimetypes.guess_type(str(path))
    return guess or "application/octet-stream"


def file_to_data_uri(path: str | Path) -> str:
    p = Path(path)
    if not p.is_file():
        raise RunwareClientError(f"File not found: {p}")
    raw = p.read_bytes()
    # Guard huge payloads (prefer mediaStorage for big masters)
    mb = len(raw) / (1024 * 1024)
    if mb > 95:
        raise RunwareClientError(
            f"File is {mb:.0f} MB — too large for inline upload. "
            "Use a 2–30s 1080p proxy (Render-in-Place) and retry."
        )
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:{_mime_for(p)};base64,{b64}"


def _new_task_uuid() -> str:
    return str(uuid.uuid4())


def runware_post(
    tasks: list[dict[str, Any]],
    *,
    timeout: float = 120.0,
) -> list[dict[str, Any]]:
    """
    POST task array to Runware. Returns the ``data`` list from the response.
    """
    key = get_runware_key()
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(RUNWARE_API_URL, headers=headers, json=tasks)
    except httpx.HTTPError as exc:
        raise RunwareClientError(f"Runware network error: {exc}") from exc

    if resp.status_code >= 400:
        detail = ""
        try:
            detail = resp.text[:400]
        except Exception:
            pass
        raise RunwareClientError(
            f"Runware HTTP {resp.status_code}: {detail or resp.reason_phrase}"
        )

    try:
        body = resp.json()
    except Exception as exc:
        raise RunwareClientError(f"Runware returned non-JSON: {exc}") from exc

    # Error shape: {"errors": [...]} or data with error fields
    if isinstance(body, dict):
        if body.get("errors"):
            errs = body["errors"]
            msg = errs[0] if isinstance(errs, list) and errs else errs
            raise RunwareClientError(f"Runware error: {msg}")
        data = body.get("data")
        if isinstance(data, list):
            return data
        # Some responses wrap single object
        if data is not None:
            return [data] if isinstance(data, dict) else []
    if isinstance(body, list):
        return [x for x in body if isinstance(x, dict)]
    raise RunwareClientError(f"Unexpected Runware response: {str(body)[:200]}")


def upload_media(
    path: str | Path,
    *,
    on_progress: ProgressCallback | None = None,
) -> str:
    """
    Upload local file via mediaStorage → returns mediaURL (or mediaUUID).

    Prefer URL for videoInference inputs.
    """
    p = Path(path)
    if not p.is_file():
        raise RunwareClientError(f"Missing file: {p}")
    if on_progress:
        on_progress(f"Uploading to Runware: {p.name}")
    data_uri = file_to_data_uri(p)
    task = {
        "taskType": "mediaStorage",
        "taskUUID": _new_task_uuid(),
        "operation": "upload",
        "media": data_uri,
    }
    # Large videos need long timeout
    timeout = 300.0 if p.suffix.lower() in {".mp4", ".mov", ".webm", ".m4v"} else 120.0
    rows = runware_post([task], timeout=timeout)
    if not rows:
        raise RunwareClientError("Runware mediaStorage returned empty data.")
    row = rows[0]
    url = row.get("mediaURL") or row.get("mediaUrl")
    mid = row.get("mediaUUID") or row.get("mediaUuid")
    if url:
        if on_progress:
            on_progress(f"Stored on Runware: {p.name}")
        return str(url)
    if mid:
        if on_progress:
            on_progress(f"Stored UUID: {mid}")
        return str(mid)
    raise RunwareClientError(f"mediaStorage missing URL/UUID: {row}")


def estimate_aleph_cost_usd(duration_s: float | None) -> float:
    secs = float(duration_s) if duration_s and duration_s > 0 else 8.0
    secs = max(ALEPH_MIN_DURATION_S, min(ALEPH_MAX_DURATION_S, secs))
    return round(secs * ALEPH_COST_PER_SECOND, 2)


def format_aleph_cost(duration_s: float | None) -> str:
    """Job total for clip length (not bare $/s)."""
    from media_studio.pricing import format_job_cost

    usd = estimate_aleph_cost_usd(duration_s)
    secs = float(duration_s) if duration_s and duration_s > 0 else 8.0
    secs = max(ALEPH_MIN_DURATION_S, min(ALEPH_MAX_DURATION_S, secs))
    return format_job_cost(
        usd,
        unit=f"{secs:.0f}s",
        model="Aleph 2.0 / Runware",
    )


def run_aleph_video_edit(
    *,
    video_url: str,
    prompt: str,
    frame_images: list[dict[str, Any]] | None = None,
    on_progress: ProgressCallback | None = None,
    poll_timeout_s: float = 900.0,
) -> str:
    """
    Run runway:aleph@2.0 videoInference.

    ``frame_images`` items: ``{image: url, frame: first|last}`` or
    ``{image: url, timestamp: float}``.

    Returns output video URL.
    """
    text = (prompt or "").strip()
    if not text:
        raise RunwareClientError("Aleph requires a prompt describing the edit.")
    if len(text) > ALEPH_MAX_PROMPT_CHARS:
        text = text[: ALEPH_MAX_PROMPT_CHARS - 1].rstrip() + "…"

    frames = list(frame_images or [])[:ALEPH_MAX_KEYFRAMES]
    inputs: dict[str, Any] = {"video": video_url}
    if frames:
        inputs["frameImages"] = frames

    task_uuid = _new_task_uuid()
    task = {
        "taskType": "videoInference",
        "taskUUID": task_uuid,
        "model": ALEPH_MODEL_ID,
        "inputs": inputs,
        "positivePrompt": text,
        "numberResults": 1,
    }
    if on_progress:
        on_progress(f"Aleph 2.0 · submitting ({len(frames)} keyframe(s))…")

    # First POST — may return immediately or need poll via getResponse
    rows = runware_post([task], timeout=min(poll_timeout_s, 600.0))
    url = _extract_video_url(rows, task_uuid)
    if url:
        if on_progress:
            on_progress("Aleph 2.0 complete.")
        return url

    # Poll getResponse for long-running video jobs
    if on_progress:
        on_progress("Aleph 2.0 running (polling)…")
    deadline = time.time() + poll_timeout_s
    while time.time() < deadline:
        time.sleep(4.0)
        try:
            poll_task = {
                "taskType": "getResponse",
                "taskUUID": task_uuid,
            }
            # Some Runware versions use getResponse differently — also re-post
            # with connectionSession if needed. Try simple getResponse first.
            poll_rows = runware_post([poll_task], timeout=60.0)
            url = _extract_video_url(poll_rows, task_uuid)
            if url:
                if on_progress:
                    on_progress("Aleph 2.0 complete.")
                return url
            # Check for explicit failure
            for row in poll_rows:
                if row.get("error") or row.get("status") in ("error", "failed"):
                    raise RunwareClientError(
                        f"Aleph failed: {row.get('error') or row.get('status')}"
                    )
        except RunwareClientError as exc:
            low = str(exc).lower()
            if "getresponse" in low or "unknown task" in low or "404" in low:
                # Fallback: re-submit is wrong; break with last error
                pass
            else:
                raise
        if on_progress:
            remain = int(deadline - time.time())
            on_progress(f"Aleph 2.0 still running… ({remain}s left)")

    raise RunwareClientError(
        "Aleph 2.0 timed out waiting for video. Check Runware dashboard / retry "
        "with a shorter 2–30s clip."
    )


def _extract_video_url(rows: list[dict[str, Any]], task_uuid: str | None = None) -> str | None:
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key in ("videoURL", "videoUrl", "video_url"):
            v = row.get(key)
            if isinstance(v, str) and v.startswith("http"):
                return v
        video = row.get("video")
        if isinstance(video, dict):
            u = video.get("url") or video.get("videoURL")
            if u:
                return str(u)
        if isinstance(video, str) and video.startswith("http"):
            return video
    return None


def download_url(url: str, dest: Path, *, on_progress: ProgressCallback | None = None) -> Path:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if on_progress:
        on_progress(f"Downloading result → {dest.name}")
    try:
        with httpx.Client(timeout=300.0, follow_redirects=True) as client:
            with client.stream("GET", url) as resp:
                resp.raise_for_status()
                with dest.open("wb") as f:
                    for chunk in resp.iter_bytes():
                        f.write(chunk)
    except httpx.HTTPError as exc:
        raise RunwareClientError(f"Download failed: {exc}") from exc
    return dest
