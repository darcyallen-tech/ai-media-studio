"""Media helpers: image/video validation and first-frame extraction."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image

# Common extensions we accept
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tiff"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}


def is_image_path(path: str | Path | None) -> bool:
    if not path:
        return False
    return Path(path).suffix.lower() in IMAGE_EXTENSIONS


def is_video_path(path: str | Path | None) -> bool:
    if not path:
        return False
    return Path(path).suffix.lower() in VIDEO_EXTENSIONS


def extract_first_frame(video_path: str | Path, output_path: str | Path | None = None) -> Path:
    """
    Extract the first frame of a video and save it as a PNG.

    Returns the path to the written image.
    """
    return extract_frame_at(video_path, 0.0, output_path=output_path)


def extract_frame_at(
    video_path: str | Path,
    seconds: float,
    output_path: str | Path | None = None,
) -> Path:
    """
    Extract a frame at ``seconds`` (clamped to clip length) and save as PNG.

    Used by Aleph keyframe workflow (edit one frame → pin → propagate).
    """
    import cv2  # lazy import so the UI can still load if OpenCV is missing

    video_path = Path(video_path)
    if not video_path.is_file():
        raise FileNotFoundError(f"Video not found: {video_path}")

    if output_path is None:
        tag = f"{max(0.0, float(seconds)):.2f}".replace(".", "p")
        output_path = video_path.with_name(f"{video_path.stem}_t{tag}.png")
    else:
        output_path = Path(output_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(str(video_path))
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        frame_count = float(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)
        duration = (frame_count / fps) if fps > 0 and frame_count > 0 else 0.0
        t = max(0.0, float(seconds))
        if duration > 0:
            t = min(t, max(0.0, duration - 0.001))
        # Seek by msec
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
        ok, frame = cap.read()
        if not ok or frame is None:
            # Fallback: first frame
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = cap.read()
        if not ok or frame is None:
            raise RuntimeError(f"Could not read a frame from: {video_path}")
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        Image.fromarray(rgb).save(output_path)
    finally:
        cap.release()

    return output_path


def video_poster_path(
    video_path: str | Path | None,
    *,
    cache_dir: str | Path | None = None,
    force: bool = False,
) -> str | None:
    """
    Return a cached poster-frame PNG for a local video (for UI thumbnails).

    Generates on first use under outputs/_previews/video_thumbs/.
    Returns None if the video is missing or frame extraction fails.
    """
    if not video_path:
        return None
    try:
        vp = Path(str(video_path).strip().strip('"')).expanduser()
        if not vp.is_file():
            return None
        resolved = vp.resolve()
    except OSError:
        return None

    from media_studio.config import ensure_output_dir

    if cache_dir is None:
        dest_dir = ensure_output_dir() / "_previews" / "video_thumbs"
    else:
        dest_dir = Path(cache_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Stable name from path + mtime + size so edits refresh the poster
    try:
        st = resolved.stat()
        key = f"{resolved.stem}_{st.st_size}_{int(st.st_mtime)}"
    except OSError:
        key = resolved.stem
    # Keep filesystem-safe
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in key)[:80]
    out = dest_dir / f"{safe}_poster.jpg"

    if out.is_file() and out.stat().st_size > 0 and not force:
        return str(out.resolve())

    try:
        extract_first_frame(resolved, out.with_suffix(".png"))
        png = out.with_suffix(".png")
        if png.is_file():
            # Prefer smaller JPEG thumbs (max ~480px on the long edge)
            try:
                with Image.open(png) as im:
                    rgb = im.convert("RGB")
                    rgb.thumbnail((480, 480), Image.Resampling.LANCZOS)
                    rgb.save(out, format="JPEG", quality=82)
                try:
                    png.unlink()
                except OSError:
                    pass
                return str(out.resolve())
            except Exception:
                return str(png.resolve())
    except Exception:
        return None
    return None if not out.is_file() else str(out.resolve())


def resolve_still_preview(
    image_file: str | Path | None,
    video_file: str | Path | None = None,
    cache_dir: Path | None = None,
) -> str | None:
    """
    Prefer an uploaded still image. If only a video is present, extract frame 0.

    Returns a filesystem path suitable for Gradio Image preview, or None.
    """
    if image_file and Path(image_file).is_file():
        return str(image_file)

    if video_file and is_video_path(video_file) and Path(video_file).is_file():
        from media_studio.config import ensure_output_dir

        dest_dir = cache_dir or ensure_output_dir() / "_previews"
        dest_dir.mkdir(parents=True, exist_ok=True)
        stem = Path(video_file).stem
        out = dest_dir / f"{stem}_frame0.png"
        try:
            extract_first_frame(video_file, out)
            return str(out)
        except Exception:
            return None

    return None


def describe_upload(path: str | Path | None, kind: str) -> str:
    """Short human-readable status line for an uploaded file."""
    if not path:
        return f"No {kind} uploaded."
    p = Path(path)
    if not p.is_file():
        return f"{kind.title()} path is not a file: {p}"
    size_kb = p.stat().st_size / 1024
    return f"{kind.title()}: {p.name} ({size_kb:.1f} KB)"


def compose_overlay_preview(
    source_path: str | Path | None,
    generated_path: str | Path | None,
    opacity: float = 0.5,
    *,
    cache_dir: str | Path | None = None,
) -> str | None:
    """
    Blend generated over source for alignment checks.

    opacity: 0.0 = source only, 1.0 = generated only.
    Generated is resized to the source dimensions so walls/placement can be checked.
    Returns a temporary PNG path, or None if inputs are missing.
    """
    src_p = Path(source_path) if source_path else None
    gen_p = Path(generated_path) if generated_path else None
    if not src_p or not src_p.is_file():
        return str(gen_p.resolve()) if gen_p and gen_p.is_file() else None
    if not gen_p or not gen_p.is_file():
        return str(src_p.resolve())

    try:
        alpha = float(opacity)
    except (TypeError, ValueError):
        alpha = 0.5
    alpha = max(0.0, min(1.0, alpha))

    try:
        with Image.open(src_p) as src_im, Image.open(gen_p) as gen_im:
            src_rgb = src_im.convert("RGB")
            gen_rgb = gen_im.convert("RGB")
            if gen_rgb.size != src_rgb.size:
                gen_rgb = gen_rgb.resize(src_rgb.size, Image.Resampling.LANCZOS)
            blended = Image.blend(src_rgb, gen_rgb, alpha)
    except Exception:
        return str(gen_p.resolve()) if gen_p.is_file() else str(src_p.resolve())

    if cache_dir is None:
        from media_studio.config import ensure_output_dir

        dest_dir = ensure_output_dir() / "_previews" / "compare"
    else:
        dest_dir = Path(cache_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Stable name from inputs + opacity so repeated slider moves don't pile up endlessly
    # but still refresh when alpha changes (include tenths in name).
    tag = f"{src_p.stem[:24]}__vs__{gen_p.stem[:24]}__a{int(round(alpha * 100)):03d}"
    out = dest_dir / f"overlay_{tag}.png"
    try:
        blended.save(out, format="PNG")
        return str(out.resolve())
    except OSError:
        # Fallback unique name
        import time

        out = dest_dir / f"overlay_{int(time.time() * 1000)}.png"
        blended.save(out, format="PNG")
        return str(out.resolve())


def image_metadata(path: str | Path) -> dict[str, Any]:
    """Collect basic still-image metadata for prompt enhancement context."""
    p = Path(path)
    meta: dict[str, Any] = {
        "type": "image",
        "path": str(p),
        "filename": p.name,
        "extension": p.suffix.lower(),
        "size_bytes": p.stat().st_size if p.is_file() else None,
    }
    try:
        with Image.open(p) as im:
            meta["width"] = im.width
            meta["height"] = im.height
            meta["mode"] = im.mode
            meta["format"] = im.format
            if im.width and im.height:
                meta["aspect_ratio_approx"] = _approx_aspect(im.width, im.height)
    except Exception as exc:  # pragma: no cover - defensive
        meta["error"] = f"Could not read image: {exc}"
    return meta


def video_metadata(path: str | Path) -> dict[str, Any]:
    """Collect basic video metadata for prompt enhancement context."""
    import cv2  # lazy import

    p = Path(path)
    meta: dict[str, Any] = {
        "type": "video",
        "path": str(p),
        "filename": p.name,
        "extension": p.suffix.lower(),
        "size_bytes": p.stat().st_size if p.is_file() else None,
    }
    cap = cv2.VideoCapture(str(p))
    try:
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        meta["width"] = width or None
        meta["height"] = height or None
        meta["fps"] = fps if fps > 0 else None
        meta["frame_count"] = frame_count or None
        if fps > 0 and frame_count > 0:
            meta["duration_seconds"] = round(frame_count / fps, 3)
        if width and height:
            meta["aspect_ratio_approx"] = _approx_aspect(width, height)
    except Exception as exc:  # pragma: no cover - defensive
        meta["error"] = f"Could not read video: {exc}"
    finally:
        cap.release()
    return meta


def media_context_for_enhance(
    image_file: str | Path | None,
    video_file: str | Path | None,
) -> dict[str, Any]:
    """Build a media context dict for the enhance-prompt LLM call."""
    ctx: dict[str, Any] = {"has_image": False, "has_video": False}
    if image_file and Path(image_file).is_file():
        ctx["has_image"] = True
        ctx["image"] = image_metadata(image_file)
    if video_file and Path(video_file).is_file():
        ctx["has_video"] = True
        ctx["video"] = video_metadata(video_file)
    if not ctx["has_image"] and not ctx["has_video"]:
        ctx["note"] = "No media uploaded; treat as text-to-image/video unless prompt says otherwise."
    return ctx


def _approx_aspect(width: int, height: int) -> str:
    """Return a simple ratio string like 16:9 for context (not exact GCD)."""
    if width <= 0 or height <= 0:
        return "unknown"
    r = width / height
    candidates = {
        "1:1": 1.0,
        "4:3": 4 / 3,
        "3:4": 3 / 4,
        "16:9": 16 / 9,
        "9:16": 9 / 16,
        "3:2": 1.5,
        "2:3": 2 / 3,
        "21:9": 21 / 9,
    }
    best = min(candidates.items(), key=lambda kv: abs(kv[1] - r))
    if abs(best[1] - r) < 0.08:
        return best[0]
    return f"{width}:{height}"


def safe_path_str(value: Any) -> str | None:
    """
    Normalize Gradio file values to a local filesystem path string.

    Handles: str, Path, dict {path,name,url}, FileData-like objects, tuples/lists
    from Gallery items, and tempfile objects with .name / .path.
    """
    if value is None:
        return None

    # Gallery / select often wraps as (path, caption) or [path, ...]
    if isinstance(value, (list, tuple)) and value:
        return safe_path_str(value[0])

    if isinstance(value, str):
        s = value.strip()
        # Ignore empty / pure URL placeholders without a local file
        if not s:
            return None
        return s

    if isinstance(value, Path):
        return str(value)

    # Gradio FileData / dict-like
    if isinstance(value, dict):
        for key in ("path", "name", "orig_name"):
            if value.get(key):
                return str(value[key])
        return None

    # pydantic / FileData objects (Gradio 4–6)
    for attr in ("path", "name"):
        try:
            attr_val = getattr(value, attr, None)
        except Exception:
            attr_val = None
        if attr_val and isinstance(attr_val, (str, Path)):
            s = str(attr_val).strip()
            if s and not s.startswith("http://") and not s.startswith("https://"):
                return s
            if s and attr == "path":
                return s

    return None


def ensure_local_image(value: Any) -> str | None:
    """
    Resolve a Gradio image value to an existing local image file path, or None.
    """
    path = safe_path_str(value)
    if not path:
        return None
    try:
        p = Path(path)
        if p.is_file():
            return str(p.resolve())
    except OSError:
        return None
    return None
