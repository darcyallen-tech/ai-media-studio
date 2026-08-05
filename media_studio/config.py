"""Application configuration and defaults."""

from __future__ import annotations

import os
from pathlib import Path

from media_studio.fal.models import catalog_for_enhance, model_dropdown_choices

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "outputs"

ENHANCE_SYSTEM_PROMPT_PATH = (
    PROJECT_ROOT / "media_studio" / "prompts" / "enhance_system.txt"
)

# Dropdown labels (grouped Image · / Video ·)
MODEL_LABELS: list[str] = model_dropdown_choices()

# Keys aligned where possible for model_id_from_choice (curated registry keys)
MODEL_OPTIONS: list[str] = [""] + [
    # image
    "flux 2 pro",
    "nano banana pro",
    "nano banana 2",
    "seedream 5 pro",
    "flux 2 flex",
    "flux kontext pro",
    "grok imagine edit",
    "grok imagine quality edit",
    "nano banana",
    # video edit
    "kling o3 standard edit",
    "kling o3 pro edit",
    "kling o1 standard edit",
    "kling o1 pro edit",
    "ltx retake",
    "grok imagine edit video",
    "seedance 2.0 v2v",
    "seedance 2.0 fast v2v",
    "flux 3 extend",
    # image-to-video
    "kling o3 standard i2v",
    "kling o3 pro i2v",
    "kling v3 standard i2v",
    "kling v3 pro i2v",
    "kling 2.6 pro i2v",
    "kling 2.5 turbo pro i2v",
    "grok imagine 1.5 i2v",
    "grok imagine 1.5 reference",
    "seedance 2.0 i2v",
    "seedance 2.0 fast i2v",
    "seedance 2.0 reference",
    "flux 3 i2v",
    "flux 3 first last",
    "minimax h3 i2v",
    "minimax h3 reference",
]

MODEL_CATALOG: dict[str, dict] = catalog_for_enhance()

APP_TITLE = "AI Media Studio"
APP_DESCRIPTION = (
    "Local desktop workspace for personal AI image and video editing (Flet). "
    "Studio · Tools · Creative Vision · Director · VFX · Motion Sync · Frame Editor · "
    "Audio · Characters · Library. "
    "Outputs: outputs/YYYY-MM-DD/."
)

# Version / update check — prefer APP_VERSION + git SHA over calendar stamps
try:
    from media_studio import __version__ as _pkg_ver

    APP_VERSION = str(_pkg_ver or "0.1.2").strip() or "0.1.2"
except Exception:
    APP_VERSION = "0.1.2"
# Calendar day of this build/release (YYYY-MM-DD). Bump on tagged releases.
# Same-day remote commits are treated as current unless the git SHA differs.
APP_BUILD_DATE = os.environ.get("AI_MEDIA_STUDIO_BUILD_DATE", "2026-08-01").strip()


def _resolve_app_git_sha() -> str:
    """
    Embedded / local git SHA for update checks (full or short).

    Order: env AI_MEDIA_STUDIO_GIT_SHA → media_studio/_build_sha.txt →
    ``git rev-parse HEAD`` from PROJECT_ROOT → empty.
    """
    env = (os.environ.get("AI_MEDIA_STUDIO_GIT_SHA") or "").strip()
    if env:
        return env[:40]
    try:
        sha_file = Path(__file__).resolve().parent / "_build_sha.txt"
        if sha_file.is_file():
            raw = sha_file.read_text(encoding="utf-8").strip().splitlines()
            if raw and raw[0].strip():
                return raw[0].strip()[:40]
    except OSError:
        pass
    try:
        import subprocess

        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        if out.returncode == 0 and (out.stdout or "").strip():
            return (out.stdout or "").strip()[:40]
    except Exception:
        pass
    return ""


APP_GIT_SHA = _resolve_app_git_sha()
GITHUB_REPO = "darcyallen-tech/ai-media-studio"
GITHUB_URL = f"https://github.com/{GITHUB_REPO}"

XAI_BASE_URL = os.environ.get("XAI_BASE_URL", "https://api.x.ai/v1").rstrip("/")
XAI_DEFAULT_MODEL = os.environ.get("XAI_MODEL", "grok-4.5")


def ensure_output_dir(path: Path | None = None) -> Path:
    out = path or OUTPUT_DIR
    out.mkdir(parents=True, exist_ok=True)
    return out


def model_label_for(model_id: str | None) -> str:
    if not model_id:
        return MODEL_LABELS[0]
    mid = model_id.strip().lower()
    from media_studio.fal.models import (
        IMAGE_EDIT_MODELS,
        VIDEO_MODELS,
        resolve_image_edit_model,
        resolve_video_model,
    )

    img = resolve_image_edit_model(model_id)
    if img:
        return img.label
    vid = resolve_video_model(model_id)
    if vid:
        return vid.label
    for opt, label in zip(MODEL_OPTIONS, MODEL_LABELS):
        if opt and opt.lower() == mid:
            return label
    return model_id.strip()


def model_id_from_choice(model_choice: str | None) -> str:
    if not model_choice:
        return ""
    choice = model_choice.strip()
    if choice in MODEL_OPTIONS:
        return choice
    if choice in MODEL_LABELS:
        # Map label → key
        from media_studio.fal.models import resolve_image_edit_model, resolve_video_model

        img = resolve_image_edit_model(choice)
        if img:
            return img.key
        vid = resolve_video_model(choice)
        if vid:
            return vid.key
        if choice == MODEL_LABELS[0]:
            return ""
    if choice.lower() in ("auto (default)", "auto", "default"):
        return ""
    lower = choice.lower()
    for key in MODEL_CATALOG:
        if key == lower or MODEL_CATALOG[key].get("label", "").lower() == lower:
            return key
    return choice


def format_model_catalog_for_prompt() -> str:
    lines: list[str] = []
    for model_id, spec in MODEL_CATALOG.items():
        lines.append(f"- id: `{model_id}`")
        for k, v in spec.items():
            lines.append(f"  - {k}: {v}")
    return "\n".join(lines) if lines else "(no models configured)"
