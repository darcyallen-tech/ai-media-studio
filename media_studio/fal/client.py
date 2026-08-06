"""
Thin fal.ai client helpers.

Designed so video models can reuse upload / subscribe / download later.
"""

from __future__ import annotations

import hashlib
import mimetypes
import os
import shutil
import uuid
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import httpx

ProgressCallback = Callable[[str], None]

# Prefer a long-lived public object so the model runner can re-download mid-job.
_UPLOAD_LIFECYCLE_EXPIRES = "1d"

# MIME overrides for extensions that Windows mimetypes sometimes miss
_MIME_BY_EXT: dict[str, str] = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
    ".m4v": "video/x-m4v",
    ".avi": "video/x-msvideo",
    ".mkv": "video/x-matroska",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".ogg": "audio/ogg",
    ".flac": "audio/flac",
}


class FalConfigError(RuntimeError):
    """Missing or invalid FAL_KEY."""


class FalClientError(RuntimeError):
    """fal request or download failure."""


def get_fal_key() -> str:
    # Prefer env (set from Settings / secrets_store on startup)
    key = (os.environ.get("FAL_KEY") or os.environ.get("FAL_API_KEY") or "").strip()
    if not key:
        try:
            from media_studio.secrets_store import effective_fal_key

            key = effective_fal_key()
            if key:
                os.environ["FAL_KEY"] = key
        except Exception:
            pass
    if not key:
        raise FalConfigError(
            "FAL API key is not set. Open Settings (gear icon) and paste your key "
            "from https://fal.ai/dashboard/keys"
        )
    return key


def _ensure_key_in_env() -> None:
    """fal_client reads FAL_KEY from the environment."""
    key = get_fal_key()
    os.environ["FAL_KEY"] = key


def format_bytes(n: int | float | None) -> str:
    """Human-readable file size."""
    if n is None:
        return "?"
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "?"
    if n < 1024:
        return f"{int(n)} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    if n < 1024 * 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MB"
    return f"{n / (1024 * 1024 * 1024):.2f} GB"


def is_remote_url(value: str | Path | None) -> bool:
    if value is None:
        return False
    s = str(value).strip().lower()
    return s.startswith("http://") or s.startswith("https://") or s.startswith("data:")


def require_local_file(path: str | Path | None, *, context: str = "Upload") -> Path:
    """
    Resolve and validate a *local* media path.

    Rejects http(s)/data URLs so we never treat a stale fal.media link as a source.
    """
    if path is None or not str(path).strip():
        raise FalClientError(f"{context}: no local file path provided.")

    raw = str(path).strip().strip('"').strip("'")
    if is_remote_url(raw):
        raise FalClientError(
            f"{context}: got a remote URL instead of a local file "
            f"({raw[:120]}…). Re-select the clip from disk or "
            "Recently from Resolve so it is uploaded fresh — do not reuse "
            "expired fal.media URLs."
        )

    p = Path(raw).expanduser()
    try:
        p = p.resolve()
    except OSError:
        pass

    if not p.is_file():
        raise FalClientError(
            f"{context}: local file not found: {p}"
        )

    try:
        size = p.stat().st_size
    except OSError as exc:
        raise FalClientError(f"{context}: cannot stat {p} ({exc})") from exc

    if size <= 0:
        raise FalClientError(f"{context}: file is empty: {p}")

    return p


def _mime_for_path(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in _MIME_BY_EXT:
        return _MIME_BY_EXT[ext]
    guessed, _ = mimetypes.guess_type(str(path.with_suffix(ext)))
    return guessed or "application/octet-stream"


def _staging_dir() -> Path:
    from media_studio.config import ensure_output_dir

    d = ensure_output_dir() / "_fal_upload"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _needs_staging(path: Path) -> bool:
    """Stage when the path/name may confuse upload or CDN (spaces, non-ascii, odd case)."""
    name = path.name
    if " " in str(path) or "\t" in str(path):
        return True
    try:
        name.encode("ascii")
    except UnicodeEncodeError:
        return True
    # Uppercase video extensions sometimes confuse MIME guessers on older clients
    if path.suffix and path.suffix != path.suffix.lower():
        return True
    return False


def _stage_for_upload(path: Path, on_progress: ProgressCallback | None = None) -> Path:
    """
    Copy to a clean short filename under outputs/_fal_upload.

    Always used for large/awkward paths so fal receives a simple .mp4 name.
    """
    digest = hashlib.sha1(str(path.resolve()).encode("utf-8", errors="replace")).hexdigest()[:10]
    ext = path.suffix.lower() or ".bin"
    if ext == ".jpeg":
        ext = ".jpg"
    dest = _staging_dir() / f"src_{digest}{ext}"

    try:
        if dest.is_file() and dest.stat().st_size == path.stat().st_size:
            return dest
    except OSError:
        pass

    if on_progress:
        on_progress(
            f"Staging {path.name} ({format_bytes(path.stat().st_size)}) for upload…"
        )
    try:
        shutil.copy2(path, dest)
    except OSError as exc:
        raise FalClientError(
            f"Upload staging failed for {path} ({format_bytes(path.stat().st_size)}): {exc}"
        ) from exc
    return dest


def _lifecycle_settings() -> Any:
    """Prefer long-lived public objects when the SDK supports lifecycle."""
    try:
        from fal_client import StorageSettings

        return StorageSettings(expires_in=_UPLOAD_LIFECYCLE_EXPIRES)
    except Exception:
        return None


def _verify_url_reachable(url: str, *, timeout: float = 30.0) -> tuple[bool, str]:
    """Best-effort check that the uploaded URL is publicly fetchable."""
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            # HEAD first; some CDNs only allow GET
            try:
                resp = client.head(url)
                if resp.status_code < 400:
                    return True, f"HTTP {resp.status_code}"
            except Exception:
                pass
            resp = client.get(url, headers={"Range": "bytes=0-1023"})
            if resp.status_code < 400:
                return True, f"HTTP {resp.status_code}"
            return False, f"HTTP {resp.status_code}"
    except Exception as exc:
        return False, str(exc)


def _upload_bytes_with_mime(
    path: Path,
    *,
    mime: str,
    on_progress: ProgressCallback | None = None,
) -> str:
    """Upload using path upload (multipart for large files) + lifecycle when possible."""
    import fal_client

    lifecycle = _lifecycle_settings()
    size = path.stat().st_size

    def _try_upload_file(**extra: Any) -> str:
        url = fal_client.upload_file(str(path), **extra) if extra else fal_client.upload_file(str(path))
        if not url:
            raise FalClientError("fal upload returned an empty URL.")
        return str(url)

    # Prefer path upload — uses multipart above ~100MB (never load whole file into RAM)
    last_err: Exception | None = None
    if lifecycle is not None:
        try:
            return _try_upload_file(lifecycle=lifecycle)
        except TypeError:
            # Older SDK without lifecycle kwarg
            pass
        except Exception as exc:
            last_err = exc

    try:
        return _try_upload_file()
    except Exception as exc:
        last_err = exc

    # Small-file fallback: explicit content-type via upload(data, mime)
    # Skip for large files — reading into memory can OOM.
    if size <= 80 * 1024 * 1024:
        if on_progress:
            on_progress(f"Retry upload with content-type {mime}…")
        try:
            data = path.read_bytes()
            try:
                url = fal_client.upload(
                    data, mime, file_name=path.name, lifecycle=lifecycle
                ) if lifecycle is not None else fal_client.upload(
                    data, mime, file_name=path.name
                )
            except TypeError:
                url = fal_client.upload(data, mime, file_name=path.name)
            if url:
                return str(url)
        except Exception as exc:
            last_err = exc

    detail = f" ({last_err})" if last_err else ""
    raise FalClientError(
        f"fal upload failed for {path.name} ({format_bytes(size)}, {mime}){detail}"
    )


def upload_file(path: str | Path, on_progress: ProgressCallback | None = None) -> str:
    """
    Upload a *local* file to fal storage; return a public URL.

    Always uploads from disk — never reuses prior fal.media URLs.
    Stages awkward paths (spaces / uppercase ext) to a clean temp name first.
    """
    from media_studio.errors import friendly_error

    _ensure_key_in_env()
    local = require_local_file(path, context="fal upload")
    size = local.stat().st_size
    size_s = format_bytes(size)

    # Stage for reliable MIME / filename (and always for videos with awkward paths)
    upload_path = local
    staged: Path | None = None
    try:
        if _needs_staging(local):
            staged = _stage_for_upload(local, on_progress=on_progress)
            upload_path = staged
    except FalClientError:
        raise
    except Exception as exc:
        # Staging is best-effort; fall back to original path
        if on_progress:
            on_progress(f"Staging skipped ({exc}); uploading original path.")
        upload_path = local

    mime = _mime_for_path(upload_path)
    if on_progress:
        on_progress(f"Uploading {local.name} ({size_s}, {mime}) to fal…")

    # Sniff image vs video so “too large” copy never suggests Render-in-Place for stills
    _img_ext = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
    media_kind = (
        "image"
        if (upload_path.suffix.lower() in _img_ext or (mime or "").startswith("image/"))
        else (
            "video"
            if (mime or "").startswith("video/")
            or upload_path.suffix.lower() in {".mp4", ".mov", ".webm", ".m4v", ".mkv", ".avi"}
            else None
        )
    )

    try:
        url = _upload_bytes_with_mime(upload_path, mime=mime, on_progress=on_progress)
    except FalClientError:
        raise
    except Exception as exc:
        raise FalClientError(
            friendly_error(exc, context="fal upload", media_kind=media_kind)
            + f" Local: {local} ({size_s})."
        ) from exc

    if not url or not str(url).strip():
        raise FalClientError(
            f"fal upload returned an empty URL for {local} ({size_s})."
        )

    url = str(url).strip()

    # Verify the URL is publicly reachable before the model tries (and fails)
    ok, detail = _verify_url_reachable(url)
    if not ok:
        if on_progress:
            on_progress(f"Upload URL not reachable ({detail}); retrying once…")
        try:
            # Force re-stage with unique name and re-upload
            forced = _staging_dir() / f"retry_{uuid.uuid4().hex[:12]}{upload_path.suffix.lower()}"
            shutil.copy2(local, forced)
            url = _upload_bytes_with_mime(forced, mime=_mime_for_path(forced), on_progress=on_progress)
            ok2, detail2 = _verify_url_reachable(url)
            if not ok2:
                raise FalClientError(
                    f"fal upload URL is not publicly downloadable ({detail2}). "
                    f"Local: {local} ({size_s}). "
                    "Try a shorter mp4 proxy (3–10s) from Resolve, or re-export the clip."
                )
        except FalClientError:
            raise
        except Exception as exc:
            raise FalClientError(
                f"fal upload verify failed for {local} ({size_s}): {exc}"
            ) from exc

    if on_progress:
        on_progress(f"Upload complete: {local.name} ({size_s})")
    return url


def upload_error_detail(path: str | Path | None, exc: BaseException | str) -> str:
    """Status line including local path + size when an upload-related step fails."""
    bits = [str(exc).strip() if not isinstance(exc, str) else exc.strip()]
    if path and not is_remote_url(path):
        try:
            p = Path(str(path))
            if p.is_file():
                bits.append(f"Local: {p} ({format_bytes(p.stat().st_size)})")
            else:
                bits.append(f"Local path missing: {p}")
        except OSError:
            bits.append(f"Local: {path}")
    return " ".join(bits)


def _format_fal_error_body(exc: BaseException) -> str:
    """Best-effort extraction of fal/http error body for logs + UI."""
    bits: list[str] = [f"{type(exc).__name__}: {exc}"]
    for attr in (
        "body",
        "message",
        "detail",
        "args",
        "response",
        "status_code",
        "error",
    ):
        try:
            val = getattr(exc, attr, None)
        except Exception:
            continue
        if val is None or val == "":
            continue
        if attr == "response":
            try:
                code = getattr(val, "status_code", None)
                text = getattr(val, "text", None)
                if code is not None:
                    bits.append(f"status_code={code}")
                if text:
                    bits.append(f"response_text={str(text)[:1200]}")
                elif hasattr(val, "json"):
                    try:
                        bits.append(f"response_json={val.json()!r}"[:1200])
                    except Exception:
                        pass
            except Exception:
                bits.append(f"response={val!r}"[:400])
        elif attr == "args" and isinstance(val, (tuple, list)):
            bits.append(f"args={val!r}"[:800])
        else:
            bits.append(f"{attr}={val!r}"[:800])
    # Nested __cause__
    cause = getattr(exc, "__cause__", None) or getattr(exc, "__context__", None)
    if cause is not None and cause is not exc:
        bits.append(f"cause={type(cause).__name__}: {cause}")
    return " | ".join(bits)


def subscribe(
    endpoint: str,
    arguments: dict[str, Any],
    *,
    on_progress: ProgressCallback | None = None,
    with_logs: bool = True,
) -> dict[str, Any]:
    """
    Run a fal model endpoint and return the result dict.

    Uses fal_client.subscribe with optional queue log streaming.
    """
    import fal_client

    _ensure_key_in_env()

    # Absolute last-mile aspect policy (Seedance R2V / FLUX 3 I2V / Kling I2V…)
    # Runs here so no caller can re-inject after builders.
    args_out = dict(arguments or {})
    omit_flag = False
    debug_line = ""
    try:
        from media_studio.aspect_omit import (
            append_aspect_debug_log,
            apply_aspect_policy,
            aspect_debug_line,
            endpoint_omits_aspect_ratio,
            strip_all_aspect_keys,
        )

        omit_flag = bool(endpoint_omits_aspect_ratio(endpoint))
        args_out = apply_aspect_policy(
            args_out, endpoint=endpoint, requested=args_out.get("aspect_ratio")
        )
        if omit_flag:
            args_out = strip_all_aspect_keys(args_out)
        # Seedance R2V: allowlist-only payload (drops negative_prompt, etc.)
        from media_studio.aspect_omit import sanitize_seedance_r2v_arguments

        args_out = sanitize_seedance_r2v_arguments(args_out, endpoint=endpoint)
        debug_line = aspect_debug_line(
            endpoint=endpoint,
            arguments=args_out,
            omit=omit_flag,
            source="fal.subscribe",
        )
        # Always write disk log (failed jobs often have no job_*.json)
        append_aspect_debug_log(debug_line)
        append_aspect_debug_log(
            f"PAYLOAD_DEBUG endpoint={endpoint} keys={sorted(args_out.keys())} "
            f"duration={args_out.get('duration')!r}({type(args_out.get('duration')).__name__}) "
            f"resolution={args_out.get('resolution')!r} "
            f"aspect_ratio={args_out.get('aspect_ratio')!r} "
            f"has_neg={('negative_prompt' in args_out)}"
        )
    except Exception as exc:
        debug_line = f"ASPECT_DEBUG source=fal.subscribe ERROR {exc!r} endpoint={endpoint}"
        try:
            from media_studio.aspect_omit import append_aspect_debug_log

            append_aspect_debug_log(debug_line)
        except Exception:
            pass

    # Surface to UI progress (must not be classified away — callers pass-through)
    if on_progress:
        if debug_line:
            try:
                on_progress(debug_line)
            except Exception:
                pass
        try:
            # Show key payload facts before queue (Seedance smoke)
            from media_studio.aspect_omit import is_seedance_reference_endpoint

            if is_seedance_reference_endpoint(endpoint):
                on_progress(
                    f"SEEDANCE_PAYLOAD keys={sorted(args_out.keys())} "
                    f"aspect={args_out.get('aspect_ratio')!r} "
                    f"dur={args_out.get('duration')!r} "
                    f"res={args_out.get('resolution')!r}"
                )
        except Exception:
            pass
        try:
            on_progress(f"Queued on fal: {endpoint}")
        except Exception:
            pass

    def _on_queue_update(update: Any) -> None:
        if on_progress is None:
            return
        status = getattr(update, "status", None) or type(update).__name__
        # InProgress carries logs
        logs = getattr(update, "logs", None) or []
        if logs:
            for log in logs:
                msg = log.get("message") if isinstance(log, dict) else str(log)
                if msg:
                    on_progress(str(msg))
        else:
            on_progress(f"fal status: {status}")

    from media_studio.errors import friendly_error

    try:
        result = fal_client.subscribe(
            endpoint,
            arguments=args_out,
            with_logs=with_logs,
            on_queue_update=_on_queue_update if with_logs else None,
        )
    except Exception as exc:
        # Prefer RAW fal body in UI/logs (not only rewritten help text)
        raw_body = _format_fal_error_body(exc)
        try:
            from media_studio.aspect_omit import append_aspect_debug_log

            append_aspect_debug_log(
                f"FAL_ERROR endpoint={endpoint} body={raw_body[:4000]}"
            )
            append_aspect_debug_log(
                f"FAL_ERROR_PAYLOAD endpoint={endpoint} sent_keys={sorted(args_out.keys())} "
                f"sent={{{', '.join(f'{k}={args_out.get(k)!r}' for k in sorted(args_out) if k != 'prompt')}}}"
            )
        except Exception:
            pass
        if on_progress:
            try:
                on_progress(f"FAL_RAW: {raw_body[:900]}")
            except Exception:
                pass
            try:
                on_progress(
                    f"FAL_SENT keys={sorted(args_out.keys())} "
                    f"aspect={args_out.get('aspect_ratio')!r} "
                    f"dur={args_out.get('duration')!r} "
                    f"res={args_out.get('resolution')!r}"
                )
            except Exception:
                pass
        # Lead with RAW so panel shows fal body even when friendly rewrites aspect text
        friendly = friendly_error(exc, context=f"fal ({endpoint})")
        raise FalClientError(
            f"RAW fal: {raw_body[:1200]}\n{friendly}"
            if raw_body
            else friendly
        ) from exc

    if result is None:
        raise FalClientError(f"fal returned empty result for {endpoint}")

    # Some SDK versions wrap as object with .data
    if hasattr(result, "data") and isinstance(result.data, dict):
        return result.data
    if isinstance(result, dict):
        return result
    # Best-effort conversion
    try:
        return dict(result)  # type: ignore[arg-type]
    except Exception as exc:
        raise FalClientError(f"Unexpected fal result type: {type(result)}") from exc


def extract_image_urls(result: dict[str, Any]) -> list[str]:
    """Pull image URLs from common fal image response shapes."""
    urls: list[str] = []
    images = result.get("images") or result.get("image") or []
    if isinstance(images, dict):
        images = [images]
    if isinstance(images, str):
        return [images]
    for item in images:
        if isinstance(item, str):
            urls.append(item)
        elif isinstance(item, dict):
            url = item.get("url") or item.get("file_url")
            if url:
                urls.append(str(url))
    # Single-image aliases
    if not urls and result.get("url"):
        urls.append(str(result["url"]))
    return urls


def extract_video_url(result: dict[str, Any]) -> str | None:
    """Pull a single video URL from common fal video response shapes."""
    video = result.get("video") or result.get("video_url") or result.get("output")
    if isinstance(video, str) and video.strip():
        return video.strip()
    if isinstance(video, dict):
        url = video.get("url") or video.get("file_url")
        if url:
            return str(url)
    # List of videos
    videos = result.get("videos")
    if isinstance(videos, list) and videos:
        first = videos[0]
        if isinstance(first, str):
            return first
        if isinstance(first, dict):
            url = first.get("url") or first.get("file_url")
            if url:
                return str(url)
    if result.get("url") and str(result["url"]).lower().endswith(
        (".mp4", ".mov", ".webm", ".m4v")
    ):
        return str(result["url"])
    return None


def extract_draft_cache_url(result: dict[str, Any]) -> str | None:
    """
    FLUX 3 draft output: durable encrypted cache for draft-enhance.

    OpenAPI: ``draft_cache`` File with ``url``.
    """
    if not isinstance(result, dict):
        return None
    cache = result.get("draft_cache") or result.get("draft_cache_url")
    if isinstance(cache, str) and cache.strip():
        return cache.strip()
    if isinstance(cache, dict):
        url = cache.get("url") or cache.get("file_url")
        if url:
            return str(url)
    return None


def _extension_from_url_or_type(url: str, content_type: str | None = None) -> str:
    if content_type:
        ext = mimetypes.guess_extension(content_type.split(";")[0].strip())
        if ext:
            return ext if ext != ".jpe" else ".jpg"
    path = urlparse(url).path
    suffix = Path(path).suffix.lower()
    if suffix in {
        ".png", ".jpg", ".jpeg", ".webp", ".gif",
        ".mp4", ".mov", ".webm", ".m4v",
        ".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac", ".opus",
    }:
        return ".jpg" if suffix == ".jpeg" else suffix
    return ".png"


def download_url(
    url: str,
    dest: str | Path,
    *,
    on_progress: ProgressCallback | None = None,
    timeout: float = 120.0,
) -> Path:
    """Download a remote file to dest (parent dirs created)."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    if on_progress:
        on_progress(f"Downloading result → {dest.name}…")

    # Data URI support
    if url.startswith("data:"):
        import base64

        header, _, b64 = url.partition(",")
        data = base64.b64decode(b64)
        dest.write_bytes(data)
        if on_progress:
            on_progress(f"Saved {dest.name} ({len(data)} bytes)")
        return dest

    from media_studio.errors import friendly_error

    # Write to a temp file then replace — safer on Windows if something crashes mid-write
    partial = dest.with_name(dest.name + ".partial")
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
            partial.write_bytes(resp.content)
        if dest.exists():
            try:
                dest.unlink()
            except OSError:
                pass
        partial.replace(dest)
    except Exception as exc:
        try:
            if partial.exists():
                partial.unlink()
        except OSError:
            pass
        raise FalClientError(friendly_error(exc, context="Download")) from exc

    if on_progress:
        on_progress(f"Saved {dest.name} ({dest.stat().st_size} bytes)")
    return dest


def slugify(value: str, max_len: int = 40) -> str:
    """Legacy helper — prefer media_studio.naming for new filenames."""
    from media_studio.naming import model_slug

    return model_slug(value, max_len=max_len)
