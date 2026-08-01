"""Windows-safe output filenames: timestamp + model + prompt."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

# Windows-forbidden filename characters
_WIN_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_MULTI_DASH = re.compile(r"-{2,}")

_WIN_RESERVED = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}

# Short aliases so model is obvious in Explorer without long names
_MODEL_ALIASES: dict[str, str] = {
    "nano banana pro": "nano-banana-pro",
    "nano banana 2": "nano-banana-2",
    "nano banana": "nano-banana",
    "flux 2 pro": "flux-2-pro",
    "flux 2 flex": "flux-2-flex",
    "flux kontext pro": "flux-kontext-pro",
    "kling o3 standard edit": "kling-o3-std-v2v",
    "kling o3 pro edit": "kling-o3-pro-v2v",
    "kling o3 standard i2v": "kling-o3-std-i2v",
    "kling o3 pro i2v": "kling-o3-pro-i2v",
    "kling v3 standard i2v": "kling-v3-std-i2v",
    "kling v3 pro i2v": "kling-v3-pro-i2v",
    "kling 2.6 pro i2v": "kling-2.6-pro-i2v",
    "kling 2.5 turbo pro i2v": "kling-2.5-turbo-i2v",
    "kling edit": "kling-o3-std-v2v",
    "seedance 2.0 i2v": "seedance-2-i2v",
    "seedance 2.0 fast i2v": "seedance-2-fast-i2v",
    "seedance 2.0 reference": "seedance-2-ref",
    "seedance 2.0 v2v": "seedance-2-v2v",
    "seedance 2.0 fast v2v": "seedance-2-fast-v2v",
    "elevenlabs music": "el-music",
    "lyria 2": "lyria-2",
    "minimax music 2.6": "minimax-music-26",
    "elevenlabs sfx v2": "el-sfx-v2",
    "sonilo video sfx": "sonilo-vsfx",
    "sonilo video sfx mix": "sonilo-vsfx-mix",
    "mmaudio v2": "mmaudio-v2",
    "mirelo sfx v1.5": "mirelo-sfx-v15",
    "kling video to audio": "kling-v2a",
    "veo 3.1": "veo-31",
    "veo 3.1 fast": "veo-31-fast",
    "veo 3.1 reference": "veo-31-ref",
    "veo 3.1 i2v": "veo-31-i2v",
    "veo 3.1 fast i2v": "veo-31-fast-i2v",
    "veo 3.1 bridge": "veo-31-bridge",
    "veo 3.1 fast bridge": "veo-31-fast-bridge",
    "luma ray 2": "luma-ray2",
    "kling o3 pro i2v": "kling-o3-pro-i2v",
    "seedance 2.0 i2v": "seedance-2-i2v",
    "hailuo 02 i2v": "hailuo-02-i2v",
    "hailuo 02 bridge": "hailuo-02-bridge",
    "aleph-2": "aleph-2",
    "aleph 2.0": "aleph-2",
    "elevenlabs v3": "el-tts-v3",
    "elevenlabs turbo": "el-tts-turbo",
    "minimax speech 02 hd": "minimax-speech-hd",
    "minimax voice clone": "minimax-clone",
    "grok tts": "grok-tts",
}


def prompt_slug(prompt: str, max_len: int = 48) -> str:
    """
    Turn a prompt into a short, filesystem-safe description.

    Example: "Replace the sofa with a modern velvet couch" → "replace-sofa-modern-velvet-couch"
    """
    text = (prompt or "").strip().lower()
    text = re.sub(r"[@#]", " ", text)
    text = _WIN_BAD.sub(" ", text)
    text = re.sub(r"[^a-z0-9\s\-]+", " ", text)
    stop = {
        "a", "an", "the", "to", "of", "and", "with", "from", "for", "this",
        "that", "into", "onto", "using", "keep", "exactly", "same", "only",
    }
    words = [w for w in text.split() if w and w not in stop]
    if not words:
        words = ["edit"]
    slug = "-".join(words)
    slug = _MULTI_DASH.sub("-", slug).strip("-")
    if len(slug) > max_len:
        slug = slug[:max_len].rstrip("-")
    if not slug:
        slug = "edit"
    if slug.lower() in _WIN_RESERVED:
        slug = f"x-{slug}"
    return slug


def model_slug(model_key: str, max_len: int = 36) -> str:
    key = (model_key or "model").strip().lower()
    # Prefer registry key so UI labels map to short aliases
    try:
        from media_studio.fal.models import resolve_image_edit_model, resolve_video_model

        img = resolve_image_edit_model(model_key)
        if img:
            key = img.key
        else:
            vid = resolve_video_model(model_key)
            if vid:
                key = vid.key
    except Exception:
        pass
    # Strip UI group prefixes if still present
    for prefix in ("image · ", "video · "):
        if key.startswith(prefix):
            key = key[len(prefix) :]
    # Normalize en-dashes etc.
    key = key.replace("–", "-").replace("—", "-")
    if key in _MODEL_ALIASES:
        s = _MODEL_ALIASES[key]
    else:
        # try without parentheticals / trailing descriptors
        bare = re.sub(r"\([^)]*\)", "", key).strip()
        if bare in _MODEL_ALIASES:
            s = _MODEL_ALIASES[bare]
        else:
            s = _WIN_BAD.sub("-", key)
            s = re.sub(r"[^a-z0-9.]+", "-", s)
            s = _MULTI_DASH.sub("-", s).strip("-") or "model"
    return s[:max_len].rstrip("-.")


def kind_slug(kind: str) -> str:
    k = (kind or "out").strip().lower().replace(" ", "-").replace("_", "-")
    aliases = {
        "edit": "img",
        "image": "img",
        "image-edit": "img",
        "image_edit": "img",
        "v2v": "v2v",
        "video": "v2v",
        "video-edit": "v2v",
        "video_edit": "v2v",
        "i2v": "i2v",
        "image-to-video": "i2v",
        "image_to_video": "i2v",
        "creative-vision": "vision",
        "creative_vision": "vision",
        "vision": "vision",
        "aleph-keyframe": "aleph",
        "aleph_keyframe": "aleph",
        "aleph": "aleph",
        # Tools tab
        "upscale": "tool-upscale",
        "video-upscale": "tool-vupscale",
        "cleanup": "tool-cleanup",
        "sky": "tool-sky",
        "dehaze": "tool-dehaze",
        "relight": "tool-relight",
        "tool-upscale": "tool-upscale",
        "tool-vupscale": "tool-vupscale",
        "tool-cleanup": "tool-cleanup",
        "tool-sky": "tool-sky",
        "tool-dehaze": "tool-dehaze",
        "tool-relight": "tool-relight",
        # Audio tab
        "music": "audio-music",
        "sfx": "audio-sfx",
        "ambience": "audio-ambience",
        "video-sfx": "audio-vsfx",
        "voiceover": "audio-voice",
        "voice-clone": "audio-clone",
        "audio-music": "audio-music",
        "audio-sfx": "audio-sfx",
        "audio-ambience": "audio-ambience",
        "audio-vsfx": "audio-vsfx",
        "audio-voice": "audio-voice",
        "audio-clone": "audio-clone",
    }
    if k in aliases:
        return aliases[k]
    # Keep short tool-prefixed kinds as-is
    if k.startswith("tool-"):
        return k[:18]
    return model_slug(k, 12)


def scenario_slug(scenario_key: str | None, max_len: int = 18) -> str:
    """Short filesystem-safe scenario tag (e.g. day-to-night)."""
    if not scenario_key:
        return ""
    raw = scenario_key.strip().lower().replace("→", "to").replace("_", "-")
    raw = re.sub(r"[^a-z0-9\-]+", "-", raw)
    raw = _MULTI_DASH.sub("-", raw).strip("-")
    return raw[:max_len].rstrip("-")


def timestamp_now() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def date_bucket(stamp: str | None = None) -> str:
    """YYYY-MM-DD folder name from now or a timestamp_now() stamp."""
    if stamp and len(stamp) >= 8 and stamp[:8].isdigit():
        return f"{stamp[0:4]}-{stamp[4:6]}-{stamp[6:8]}"
    return datetime.now().strftime("%Y-%m-%d")


def job_name_slug(name: str | None, max_len: int = 48) -> str:
    """
    Filesystem-safe job / listing folder name.

    Empty / None → \"\" (caller uses flat dated layout).
    """
    text = (name or "").strip().lower()
    if not text:
        return ""
    text = _WIN_BAD.sub(" ", text)
    text = re.sub(r"[^a-z0-9\s\-_.]+", " ", text)
    slug = "-".join(text.split())
    slug = _MULTI_DASH.sub("-", slug).strip("-._")
    if len(slug) > max_len:
        slug = slug[:max_len].rstrip("-._")
    if not slug:
        return ""
    if slug.lower() in _WIN_RESERVED:
        slug = f"job-{slug}"
    return slug


def resolve_job_name(explicit: str | None = None) -> str:
    """Explicit arg wins; else active job_context name."""
    raw = (explicit or "").strip()
    if raw:
        return raw
    try:
        from media_studio.job_context import current_job_name

        return current_job_name()
    except Exception:
        return ""


def job_media_dir(
    output_dir: str | Path,
    *,
    stamp: str | None = None,
    job_name: str | None = None,
) -> Path:
    """
    Media files land in a dated subfolder for easier Explorer browsing.

    Empty job name (default)::

        outputs/2026-07-26/...

    With Job / Listing set::

        outputs/jobs/<safe-job-name>/2026-07-26/...

    History / prompt JSON stay at the output root (not under jobs/).
    """
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    jslug = job_name_slug(resolve_job_name(job_name))
    if jslug:
        root = root / "jobs" / jslug
        root.mkdir(parents=True, exist_ok=True)
    day = root / date_bucket(stamp)
    day.mkdir(parents=True, exist_ok=True)
    return day


def make_output_stem(
    prompt: str,
    model_key: str,
    *,
    stamp: str | None = None,
    kind: str = "edit",
    scenario: str | None = None,
) -> str:
    """
    Readable basename stem:

        20260725_143022__model-flux-2-pro__img__sc-furniture-popin__prompt-stage-living

    Segments are double-underscore separated so model / kind / scenario / prompt
    are obvious when scanning the outputs folder in Explorer.
    """
    stamp = stamp or timestamp_now()
    model = model_slug(model_key, 36)
    k = kind_slug(kind)
    desc = prompt_slug(prompt, max_len=40)
    sc = scenario_slug(scenario)
    if sc:
        stem = f"{stamp}__model-{model}__{k}__sc-{sc}__prompt-{desc}"
    else:
        stem = f"{stamp}__model-{model}__{k}__prompt-{desc}"
    # Windows path component comfort zone
    if len(stem) > 140:
        stem = stem[:140].rstrip("-_")
    return stem


def unique_path(directory: Path, stem: str, ext: str, index: int | None = None) -> Path:
    """
    Return a non-colliding path under directory.

    If index is set, append _01, _02…; if the path exists, bump a counter.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    ext = ext if ext.startswith(".") else f".{ext}"

    def candidate(n: int | None) -> Path:
        if n is None:
            return directory / f"{stem}{ext}"
        return directory / f"{stem}_{n:02d}{ext}"

    if index is not None:
        path = candidate(index)
        if not path.exists():
            return path
        n = index
        while path.exists():
            n += 1
            path = candidate(n)
        return path

    path = candidate(None)
    if not path.exists():
        return path
    n = 2
    while True:
        path = candidate(n)
        if not path.exists():
            return path
        n += 1
