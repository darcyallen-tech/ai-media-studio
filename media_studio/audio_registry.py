"""
Audio utility models on fal.ai — music, SFX, video→SFX, voiceover, voice clone.

Minimal specs for the Audio tab (not a DAW).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal


Category = Literal["music", "sfx", "ambience", "video_sfx", "voiceover", "voice_clone"]


@dataclass(frozen=True)
class AudioSpec:
    key: str
    label: str
    category: Category
    endpoint: str
    cost_estimate_usd: float
    notes: str = ""
    supports_duration: bool = False
    duration_min_s: float = 3.0
    duration_max_s: float = 120.0
    duration_default_s: float = 30.0
    cost_per_second: float | None = None
    fixed_duration_s: float | None = None
    supports_voice: bool = False
    default_voice: str = "Rachel"
    # elevenlabs | minimax | grok — which default voice list / API shape
    voice_provider: str = "elevenlabs"
    # Soft/hard prompt length limit (chars). None = no enforced limit.
    max_prompt_chars: int | None = None
    extra_defaults: dict[str, Any] = field(default_factory=dict)


# Built-in ElevenLabs voices (name or ID on fal endpoints)
ELEVENLABS_VOICES: list[str] = [
    "Rachel",
    "Aria",
    "Roger",
    "Sarah",
    "Laura",
    "Charlie",
    "George",
    "Callum",
    "River",
    "Liam",
    "Charlotte",
    "Alice",
    "Matilda",
    "Will",
    "Jessica",
    "Eric",
    "Chris",
    "Brian",
    "Daniel",
    "Lily",
    "Bill",
]

# Common MiniMax stock voice IDs (used when not a custom clone)
MINIMAX_VOICES: list[str] = [
    "Wise_Woman",
    "Friendly_Person",
    "Inspirational_girl",
    "Deep_Voice_Man",
    "Calm_Woman",
    "Casual_Guy",
    "Lively_Girl",
    "Patient_Man",
    "Young_Knight",
    "Determined_Man",
    "Lovely_Girl",
    "Decent_Boy",
    "Imposing_Manner",
    "Elegant_Man",
    "Abbess",
    "Sweet_Girl_2",
    "Exuberant_Girl",
]

# xAI Grok TTS stock voices (API expects lowercase ids)
GROK_VOICES: list[str] = [
    "Eve",
    "Ara",
    "Leo",
    "Rex",
    "Sal",
]

# Back-compat alias used by older UI
TTS_VOICES = ELEVENLABS_VOICES


# --- Music ---
MUSIC_MODELS: dict[str, AudioSpec] = {
    "minimax music 2.6": AudioSpec(
        key="minimax music 2.6",
        label="MiniMax Music 2.6",
        category="music",
        endpoint="fal-ai/minimax-music/v2.6",
        cost_estimate_usd=0.15,
        notes="Default. Full tracks from style prompt. Instrumental-friendly for listings.",
        supports_duration=False,
        extra_defaults={
            "is_instrumental": True,
            "lyrics_optimizer": False,
        },
    ),
    "elevenlabs music": AudioSpec(
        key="elevenlabs music",
        label="ElevenLabs Music",
        category="music",
        endpoint="fal-ai/elevenlabs/music",
        cost_estimate_usd=0.12,
        notes="High-quality listing/background music. Duration control (3s–3 min). Instrumental option.",
        supports_duration=True,
        duration_min_s=3.0,
        duration_max_s=180.0,
        duration_default_s=30.0,
        cost_per_second=0.0133,  # ~$0.80/min on fal
        extra_defaults={
            "force_instrumental": True,
            "output_format": "mp3_44100_128",
        },
    ),
    "lyria 2": AudioSpec(
        key="lyria 2",
        label="Google Lyria 2",
        category="music",
        endpoint="fal-ai/lyria2",
        cost_estimate_usd=0.06,
        notes="Google Lyria 2 — ~30s clips. Great ambient / mood beds.",
        supports_duration=False,
        fixed_duration_s=30.0,
        extra_defaults={
            "negative_prompt": "vocals, lyrics, speech, low quality",
        },
    ),
    "stable audio 25": AudioSpec(
        key="stable audio 25",
        label="Stable Audio 2.5",
        category="music",
        endpoint="fal-ai/stable-audio-25/text-to-audio",
        cost_estimate_usd=0.20,
        notes="Stability AI music/SFX beds — longer ambient beds when needed.",
        supports_duration=True,
        duration_min_s=5.0,
        duration_max_s=190.0,
        duration_default_s=30.0,
        cost_per_second=0.01,
        extra_defaults={},
    ),
}

# --- Ambience beds (continuous background, not one-shot SFX) ---
# ElevenLabs SFX v2 is intentionally omitted here: ~450 char prompt limit and
# short-SFX focus make it a poor fit for multi-layer beds (use SFX tab instead).
AMBIENCE_MODELS: dict[str, AudioSpec] = {
    "stable audio 25 ambience": AudioSpec(
        key="stable audio 25 ambience",
        label="Stable Audio 2.5 Ambience",
        category="ambience",
        endpoint="fal-ai/stable-audio-25/text-to-audio",
        cost_estimate_usd=0.20,
        notes=(
            "Default. Best for 15–60s+ environmental beds. "
            "Use a pure ambience prompt (no music / no melody)."
        ),
        supports_duration=True,
        duration_min_s=15.0,
        duration_max_s=190.0,
        duration_default_s=30.0,
        cost_per_second=0.01,
        extra_defaults={},
    ),
}

# --- Text → Sound effects ---
SFX_MODELS: dict[str, AudioSpec] = {
    "elevenlabs sfx v2": AudioSpec(
        key="elevenlabs sfx v2",
        label="ElevenLabs Sound Effects V2",
        category="sfx",
        endpoint="fal-ai/elevenlabs/sound-effects/v2",
        cost_estimate_usd=0.04,
        notes="Default. Text → SFX (0.5–22s). Optional seamless loop.",
        supports_duration=True,
        duration_min_s=0.5,
        duration_max_s=22.0,
        duration_default_s=5.0,
        cost_per_second=0.002,
        extra_defaults={
            "prompt_influence": 0.3,
            "output_format": "mp3_44100_128",
            "loop": False,
        },
    ),
    "sonilo text sfx": AudioSpec(
        key="sonilo text sfx",
        label="Sonilo Text-to-SFX",
        category="sfx",
        endpoint="sonilo/v1.1/text-to-sound-effects",
        cost_estimate_usd=0.02,
        notes="Sonilo commercial-use text → SFX with duration control.",
        supports_duration=True,
        duration_min_s=0.5,
        duration_max_s=30.0,
        duration_default_s=5.0,
        cost_per_second=0.0018,
        extra_defaults={
            "audio_format": "mp3",
        },
    ),
}

# --- Video → SFX / video-to-audio ---
# Order matters: first entry is the UI default.
# Prefer audio-track models first (Resolve A1 layering); muxed video models labeled clearly.
# controlfoley (fal-ai/controlfoley) is omitted — OpenAPI 404 / not stable on fal.
VIDEO_SFX_MODELS: dict[str, AudioSpec] = {
    "mirelo sfx v1.5": AudioSpec(
        key="mirelo sfx v1.5",
        label="Mirelo SFX V1.5 (audio track · Resolve A1)",
        category="video_sfx",
        endpoint="mirelo-ai/sfx-v1.5/video-to-audio",
        cost_estimate_usd=0.10,
        notes=(
            "Default. Synced SFX track only (~$0.01/s). Optional text_prompt. "
            "Best for layering in Resolve (audio file, not muxed video)."
        ),
        supports_duration=True,
        duration_min_s=1.0,
        duration_max_s=60.0,
        duration_default_s=10.0,
        cost_per_second=0.01,
        extra_defaults={
            "num_samples": 1,
            "_prompt_field": "text_prompt",
            "_max_video_seconds": 60.0,
            "_max_file_mb": 200.0,
            "_output_kind": "audio",
        },
    ),
    "sonilo video sfx": AudioSpec(
        key="sonilo video sfx",
        label="Sonilo Video-to-SFX (audio track)",
        category="video_sfx",
        endpoint="sonilo/v1.1/video-to-sound-effects",
        cost_estimate_usd=0.15,
        notes=(
            "Commercial-use video → matching SFX track. Optional prompt steers scenes. "
            "Returns audio (and samples) for Resolve layering."
        ),
        cost_per_second=0.01,
        extra_defaults={
            "audio_format": "mp3",
            "_max_file_mb": 250.0,
            "_output_kind": "audio",
        },
    ),
    "kling video to audio": AudioSpec(
        key="kling video to audio",
        label="Kling Video-to-Audio (audio + muxed)",
        category="video_sfx",
        endpoint="fal-ai/kling-video/video-to-audio",
        cost_estimate_usd=0.035,
        notes=(
            "Fixed ~$0.035/clip. Maps Style/Pace prompt → sound_effect_prompt "
            "(max 200 chars). mp4/mov, typically short clips (≈3–20s, ≤100 MB). "
            "Returns audio track + muxed video."
        ),
        # Fixed per-job pricing (not duration-based)
        cost_per_second=None,
        max_prompt_chars=200,
        extra_defaults={
            "asmr_mode": False,
            "background_music_prompt": "none, no music, silent background bed",
            "_prompt_field": "sound_effect_prompt",
            "_max_video_seconds": 20.0,
            "_min_video_seconds": 2.0,
            "_max_file_mb": 100.0,
            "_output_kind": "audio",
        },
    ),
    "mmaudio v2": AudioSpec(
        key="mmaudio v2",
        label="MMAudio V2 (muxed video)",
        category="video_sfx",
        endpoint="fal-ai/mmaudio-v2",
        cost_estimate_usd=0.05,
        notes=(
            "Synced video→audio (prompt required). Duration 1–30s. "
            "Returns video with audio muxed — not ideal for separate Resolve A1 tracks."
        ),
        supports_duration=True,
        duration_min_s=1.0,
        duration_max_s=30.0,
        duration_default_s=8.0,
        cost_per_second=0.002,
        max_prompt_chars=None,
        extra_defaults={
            "num_steps": 25,
            "cfg_strength": 4.5,
            "negative_prompt": (
                "music, voiceover, dialogue, speech, narration, "
                "distortion, reverb wash"
            ),
            "_prefer_video": True,
            "_max_video_seconds": 30.0,
            "_max_file_mb": 200.0,
            "_output_kind": "muxed",
        },
    ),
    "sonilo video sfx mix": AudioSpec(
        key="sonilo video sfx mix",
        label="Sonilo Video+SFX Mix (muxed video)",
        category="video_sfx",
        endpoint="sonilo/v1.1/video-to-video-sound-effects",
        cost_estimate_usd=0.18,
        notes=(
            "Returns video with generated SFX mixed in; still prefers a separate "
            "audio track when the API provides one."
        ),
        cost_per_second=0.012,
        extra_defaults={
            "audio_format": "mp3",
            "_prefer_video": True,
            "_max_file_mb": 250.0,
            "_output_kind": "muxed",
        },
    ),
}

# --- Voiceover (TTS) ---
VOICEOVER_MODELS: dict[str, AudioSpec] = {
    "minimax speech 02 hd": AudioSpec(
        key="minimax speech 02 hd",
        label="MiniMax Speech 02 HD",
        category="voiceover",
        endpoint="fal-ai/minimax/speech-02-hd",
        cost_estimate_usd=0.04,
        notes="Default for My Voices. MiniMax HD TTS with emotion + speed control.",
        supports_voice=True,
        default_voice="Wise_Woman",
        voice_provider="minimax",
        extra_defaults={
            "output_format": "url",
        },
    ),
    "grok tts": AudioSpec(
        key="grok tts",
        label="Grok TTS",
        category="voiceover",
        endpoint="xai/tts/v1",
        cost_estimate_usd=0.02,
        notes=(
            "xAI Grok TTS via fal. Voices: Eve, Ara, Leo, Rex, Sal. "
            "Delivery notes map to wrapping tags (slow/soft/whisper); "
            "script can also use [laugh], [pause], [sigh]."
        ),
        supports_voice=True,
        default_voice="Eve",
        voice_provider="grok",
        extra_defaults={
            "language": "auto",
        },
    ),
    "elevenlabs v3": AudioSpec(
        key="elevenlabs v3",
        label="ElevenLabs Eleven v3",
        category="voiceover",
        endpoint="fal-ai/elevenlabs/tts/eleven-v3",
        cost_estimate_usd=0.05,
        notes="Natural TTS. Tags: [laughs], [whispers]. Stock voices.",
        supports_voice=True,
        default_voice="Rachel",
        voice_provider="elevenlabs",
        extra_defaults={"stability": 0.5},
    ),
    "elevenlabs turbo": AudioSpec(
        key="elevenlabs turbo",
        label="ElevenLabs Turbo v2.5",
        category="voiceover",
        endpoint="fal-ai/elevenlabs/tts/turbo-v2.5",
        cost_estimate_usd=0.03,
        notes="Fast multilingual TTS for quick listing reads.",
        supports_voice=True,
        default_voice="Rachel",
        voice_provider="elevenlabs",
        extra_defaults={
            "stability": 0.5,
            "similarity_boost": 0.75,
            "speed": 1.0,
        },
    ),
}

# --- Voice clone ---
# ElevenLabs Instant Voice Clone is not exposed as a standalone fal clone endpoint;
# MiniMax is the practical option that integrates with Voiceover (My Voices).
VOICE_CLONE_MODELS: dict[str, AudioSpec] = {
    "minimax voice clone": AudioSpec(
        key="minimax voice clone",
        label="MiniMax Voice Clone",
        category="voice_clone",
        endpoint="fal-ai/minimax/voice-clone",
        cost_estimate_usd=1.50,
        notes=(
            "Primary clone path on fal. ≥10s clean speech. Est. ~$1.50 per clone. "
            "Use the voice in Voiceover (MiniMax) within 7 days to keep it active. "
            "No second practical clone endpoint on fal for this workflow yet."
        ),
        extra_defaults={
            "noise_reduction": True,
            "need_volume_normalization": True,
            "model": "speech-02-hd",
            "text": (
                "Hello, this is a preview of your cloned voice for listing videos. "
                "Welcome to this beautiful home."
            ),
        },
    ),
}


def music_labels() -> list[str]:
    return [s.label for s in MUSIC_MODELS.values()]


def sfx_labels() -> list[str]:
    return [s.label for s in SFX_MODELS.values()]


def ambience_labels() -> list[str]:
    return [s.label for s in AMBIENCE_MODELS.values()]


def video_sfx_labels() -> list[str]:
    return [s.label for s in VIDEO_SFX_MODELS.values()]


def voiceover_labels() -> list[str]:
    return [s.label for s in VOICEOVER_MODELS.values()]


def voice_clone_labels() -> list[str]:
    return [s.label for s in VOICE_CLONE_MODELS.values()]


def find_audio(label_or_key: str | None, registry: dict[str, AudioSpec]) -> AudioSpec | None:
    if not label_or_key:
        return None
    raw = label_or_key.strip().lower()
    if raw in registry:
        return registry[raw]
    for spec in registry.values():
        if spec.label.lower() == raw or spec.key == raw:
            return spec
    return None


def estimate_audio_cost(
    spec: AudioSpec,
    *,
    duration_s: float | None = None,
    text: str | None = None,
) -> float:
    """Rough USD estimate for UI display."""
    if spec.category == "voice_clone":
        return spec.cost_estimate_usd
    if spec.cost_per_second is not None and duration_s is not None and duration_s > 0:
        return max(0.01, round(duration_s * spec.cost_per_second, 4))
    if spec.category == "voiceover" and text:
        chars = max(1, len(text.strip()))
        if "turbo" in spec.key:
            per_char = 0.00005  # ~$0.05 / 1k
        elif "grok" in spec.key or "xai" in spec.endpoint:
            per_char = 0.000015  # $0.015 / 1k (fal xai/tts/v1)
        elif "minimax" in spec.key:
            per_char = 0.0001  # ~$0.10 / 1k
        else:
            per_char = 0.0001  # ~$0.10 / 1k Eleven v3
        # Grok can bill under a cent for short scripts; show true ballpark
        floor = 0.001 if ("grok" in spec.key or "xai" in spec.endpoint) else 0.01
        return max(floor, round(chars * per_char, 4))
    return spec.cost_estimate_usd


def format_audio_cost(
    spec: AudioSpec,
    *,
    duration_s: float | None = None,
    text: str | None = None,
) -> str:
    """Job-total label (duration / characters when billed that way)."""
    from media_studio.pricing import format_job_cost

    amount = estimate_audio_cost(spec, duration_s=duration_s, text=text)
    unit = None
    if spec.category == "voice_clone":
        unit = "clone job"
    elif spec.cost_per_second is not None and duration_s is not None and duration_s > 0:
        unit = f"{float(duration_s):.0f}s"
    elif spec.category == "voiceover" and text:
        unit = f"{max(1, len(text.strip()))} chars"
    elif duration_s is not None and duration_s > 0:
        unit = f"{float(duration_s):.0f}s"
    return format_job_cost(amount, unit=unit, model=spec.label)


def build_music_args(
    spec: AudioSpec,
    prompt: str,
    *,
    duration_s: float | None = None,
    instrumental: bool = True,
) -> dict[str, Any]:
    args = dict(spec.extra_defaults)
    prompt = (prompt or "").strip()
    if "elevenlabs/music" in spec.endpoint:
        args["prompt"] = prompt
        if duration_s is not None:
            ms = int(max(spec.duration_min_s, min(spec.duration_max_s, duration_s)) * 1000)
            args["music_length_ms"] = ms
        args["force_instrumental"] = bool(instrumental)
    elif "lyria2" in spec.endpoint:
        args["prompt"] = prompt
        # Defaults include "vocals, lyrics…" in negative_prompt for instrumental beds.
        # When the user wants vocals, drop those negatives so Lyria can actually sing.
        if not instrumental:
            neg = str(args.get("negative_prompt") or "")
            if neg:
                ban = ("vocals", "lyrics", "speech", "singing", "choir")
                parts = [p.strip() for p in neg.split(",") if p.strip()]
                kept = [p for p in parts if p.lower() not in ban]
                if kept:
                    args["negative_prompt"] = ", ".join(kept)
                else:
                    args.pop("negative_prompt", None)
    elif "minimax-music" in spec.endpoint:
        args["prompt"] = prompt
        args["is_instrumental"] = bool(instrumental)
        if not instrumental:
            args["lyrics_optimizer"] = True
        else:
            args["lyrics_optimizer"] = False
            args["lyrics"] = ""
    elif "stable-audio" in spec.endpoint:
        args["prompt"] = prompt
        if duration_s is not None:
            d = int(round(max(spec.duration_min_s, min(spec.duration_max_s, float(duration_s)))))
            # Stable Audio 2.5: seconds_total is an integer
            args["seconds_total"] = d
    else:
        args["prompt"] = prompt
    return args


def build_sfx_args(
    spec: AudioSpec,
    prompt: str,
    *,
    duration_s: float | None = None,
    loop: bool = False,
    seed: int | None = None,
) -> dict[str, Any]:
    args = dict(spec.extra_defaults)
    text = (prompt or "").strip()
    if "sonilo" in spec.endpoint and "text-to-sound" in spec.endpoint:
        args["prompt"] = text
        if duration_s is not None and spec.supports_duration:
            d = float(max(spec.duration_min_s, min(spec.duration_max_s, duration_s)))
            args["duration"] = d
        # Sonilo does not use ElevenLabs loop flag
        args.pop("loop", None)
        if seed is not None:
            args["seed"] = int(seed)
        return args

    args["text"] = text
    if duration_s is not None and spec.supports_duration:
        d = float(duration_s)
        d = max(spec.duration_min_s, min(spec.duration_max_s, d))
        args["duration_seconds"] = d
    args["loop"] = bool(loop)
    if seed is not None:
        # ElevenLabs / others may honor seed when present; ignored if unsupported
        args["seed"] = int(seed)
    return args


def build_ambience_args(
    spec: AudioSpec,
    prompt: str,
    *,
    duration_s: float | None = None,
) -> dict[str, Any]:
    """
    Args for continuous ambience beds.

    Reuses Stable Audio / ElevenLabs SFX payload shapes with loop-friendly defaults.
    """
    args = dict(spec.extra_defaults)
    text = (prompt or "").strip()
    dur = float(duration_s) if duration_s is not None else spec.duration_default_s
    dur = max(spec.duration_min_s, min(spec.duration_max_s, dur))

    if "stable-audio" in spec.endpoint:
        args["prompt"] = text
        args["seconds_total"] = int(round(dur))
        return args

    if "elevenlabs/sound-effects" in spec.endpoint:
        args["text"] = text
        args["duration_seconds"] = float(dur)
        args["loop"] = True
        return args

    # Generic fallback
    args["prompt"] = text
    if spec.supports_duration:
        args["duration_seconds"] = float(dur)
    return args


def build_video_sfx_args(
    spec: AudioSpec,
    video_url: str,
    *,
    prompt: str | None = None,
    duration_s: float | None = None,
) -> dict[str, Any]:
    """
    Build fal arguments for a video→SFX / video-to-audio endpoint.

    Field names differ by model:
      - MMAudio: prompt (required) + duration
      - Mirelo: text_prompt + duration + num_samples
      - Kling: sound_effect_prompt (+ optional background_music_prompt)
      - Sonilo: prompt + audio_format
    """
    raw = dict(spec.extra_defaults)
    prompt_field = str(raw.pop("_prompt_field", "prompt") or "prompt")
    # Drop other service-only keys from the payload
    for k in list(raw.keys()):
        if str(k).startswith("_"):
            raw.pop(k, None)

    args: dict[str, Any] = dict(raw)
    args["video_url"] = video_url
    note = (prompt or "").strip()
    max_chars = spec.max_prompt_chars
    # Truncation is applied for API limits; callers should warn the user first
    # (Video → SFX char counter). Never drop silently without feedback at the UI.
    if max_chars is not None and note and len(note) > max_chars:
        note = note[: max(0, max_chars - 1)].rstrip() + "…"

    ep = spec.endpoint.lower()

    # --- MMAudio V2 ---
    if "mmaudio" in ep:
        # prompt is required
        args["prompt"] = note or (
            "natural real-estate foley: footsteps, doors, soft room tone, "
            "practicals; no music, no voiceover"
        )
        dur = duration_s if duration_s is not None else spec.duration_default_s
        if spec.supports_duration and dur is not None:
            d = float(max(spec.duration_min_s, min(spec.duration_max_s, float(dur))))
            args["duration"] = d
        return args

    # --- Mirelo SFX ---
    if "mirelo" in ep:
        if note:
            args["text_prompt"] = note
        else:
            args.pop("text_prompt", None)
        dur = duration_s if duration_s is not None else spec.duration_default_s
        if dur is not None:
            d = float(max(1.0, min(float(spec.duration_max_s or 60.0), float(dur))))
            args["duration"] = d
        # One sample keeps cost/latency predictable for RE tooling
        args["num_samples"] = int(args.get("num_samples") or 1)
        return args

    # --- Kling video-to-audio ---
    if "kling-video" in ep and "video-to-audio" in ep:
        sfx = note or (
            "natural diegetic foley for real-estate walkthrough: footsteps, "
            "doors, soft ambience"
        )
        if max_chars is not None and len(sfx) > max_chars:
            sfx = sfx[: max_chars - 1].rstrip() + "…"
        args["sound_effect_prompt"] = sfx
        # Keep music subdued unless the user baked music into the prompt
        if "background_music_prompt" not in args:
            args["background_music_prompt"] = "none, no music, silent background bed"
        args["asmr_mode"] = bool(args.get("asmr_mode", False))
        return args

    # --- Sonilo + generic ---
    if note:
        args[prompt_field if prompt_field in ("prompt", "text_prompt") else "prompt"] = note
    elif note is not None and prompt_field == "prompt":
        # optional prompt — omit when empty
        args.pop("prompt", None)
    if "sonilo" in ep and "audio_format" not in args:
        args["audio_format"] = "mp3"
    # Sonilo matches video length; duration not required
    return args


def video_sfx_limits(spec: AudioSpec) -> dict[str, float | None]:
    """Soft limits from extra_defaults for preflight checks."""
    ex = spec.extra_defaults or {}
    def _f(key: str) -> float | None:
        v = ex.get(key)
        if v is None:
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    return {
        "max_video_seconds": _f("_max_video_seconds"),
        "min_video_seconds": _f("_min_video_seconds"),
        "max_file_mb": _f("_max_file_mb"),
    }


def video_sfx_prefer_video(spec: AudioSpec) -> bool:
    """True when the model primarily returns muxed video (no separate audio)."""
    return bool((spec.extra_defaults or {}).get("_prefer_video"))


# Practical delivery presets for Voiceover UI
VOICEOVER_TONES: list[str] = [
    "Neutral",
    "Warm / Friendly",
    "Confident",
    "Calm / Professional",
    "Upbeat",
    "Serious",
]

# MiniMax speech-02 emotion enum: happy, sad, angry, fearful, disgusted, surprised, neutral
_TONE_TO_MINIMAX_EMOTION: dict[str, str] = {
    "Neutral": "neutral",
    "Warm / Friendly": "happy",
    "Confident": "neutral",
    "Calm / Professional": "neutral",
    "Upbeat": "happy",
    "Serious": "neutral",
}

# ElevenLabs stability / style knobs (no native emotion enum on fal TTS)
_TONE_TO_ELEVENLABS: dict[str, dict[str, float]] = {
    "Neutral": {"stability": 0.50, "style": 0.15, "similarity_boost": 0.75},
    "Warm / Friendly": {"stability": 0.42, "style": 0.35, "similarity_boost": 0.75},
    "Confident": {"stability": 0.55, "style": 0.28, "similarity_boost": 0.80},
    "Calm / Professional": {"stability": 0.72, "style": 0.08, "similarity_boost": 0.70},
    "Upbeat": {"stability": 0.38, "style": 0.45, "similarity_boost": 0.75},
    "Serious": {"stability": 0.68, "style": 0.05, "similarity_boost": 0.78},
}


def clamp_voiceover_speed(speed: float | None, default: float = 1.0) -> float:
    """Keep speed in a practical 0.8×–1.2× band (models may allow wider)."""
    try:
        s = float(speed) if speed is not None else default
    except (TypeError, ValueError):
        s = default
    return max(0.8, min(1.2, s))


def _clean_delivery_notes(notes: str | None) -> str:
    """Optional delivery / style notes — never spoken aloud."""
    return (notes or "").strip()


def _normalize_grok_voice(voice: str | None, default: str = "eve") -> str:
    """Map UI labels (Eve) or raw ids (eve) to fal xai/tts voice enum."""
    raw = (voice or default or "eve").strip().lower()
    allowed = {"eve", "ara", "rex", "sal", "leo"}
    if raw in allowed:
        return raw
    # Tolerate "Default · Eve" leftovers
    for name in allowed:
        if name in raw:
            return name
    return default


def _infer_minimax_emotion(tone_key: str, delivery_notes: str) -> str:
    """
    MiniMax only accepts a fixed emotion enum.
    Prefer keywords in delivery notes; fall back to Tone dropdown.
    """
    notes = (delivery_notes or "").lower()
    if notes:
        # Stem-friendly patterns so "warmly" / "authority" still match
        rules: list[tuple[str, str]] = [
            (r"\b(angry|furious|enraged|hostile)\w*\b", "angry"),
            (r"\b(sad|sorrow\w*|melanchol\w*|grief|mourn\w*)\b", "sad"),
            (r"\b(fear\w*|scared|anxious|nervous|afraid)\b", "fearful"),
            (r"\b(disgust\w*|repulsed|revolted)\b", "disgusted"),
            (r"\b(surpris\w*|amazed|shocked|astonished)\b", "surprised"),
            (
                r"\b(happy|cheer\w*|joyful|excit\w*|upbeat|energetic|enthusias\w*|"
                r"warm\w*|friend\w*)\b",
                "happy",
            ),
            (
                r"\b(calm\w*|neutral|profession\w*|serious|authorit\w*|measured|"
                r"matter[- ]of[- ]fact|documentar\w*|narrat\w*)\b",
                "neutral",
            ),
        ]
        for pattern, emotion in rules:
            if re.search(pattern, notes):
                return emotion
    return _TONE_TO_MINIMAX_EMOTION.get(tone_key, "neutral")


def _infer_elevenlabs_knobs(
    tone_key: str, delivery_notes: str
) -> dict[str, float]:
    """
    ElevenLabs fal TTS has style / stability floats, not freeform instructions.
    Start from Tone preset, then nudge from delivery notes.
    """
    base = dict(_TONE_TO_ELEVENLABS.get(tone_key, _TONE_TO_ELEVENLABS["Neutral"]))
    notes = (delivery_notes or "").lower()
    if not notes:
        return base

    style = float(base["style"])
    stability = float(base["stability"])
    sim = float(base["similarity_boost"])

    expressive = bool(
        re.search(
            r"\b(dramatic|expressi\w*|emotional|energetic|excit\w*|passion\w*|animated)\b",
            notes,
        )
    )
    composed = bool(
        re.search(
            r"\b(calm\w*|profession\w*|serious|measured|authorit\w*|"
            r"documentar\w*|narrat\w*)\b",
            notes,
        )
    )
    warm = bool(re.search(r"\b(warm\w*|friend\w*|intimate|gentle)\b", notes))
    whispery = bool(
        re.search(r"\b(whisper\w*|hushed|under[- ]breath)\b", notes)
        or re.search(r"\b(speak|talk|read)\w*\s+soft(ly)?\b", notes)
        or re.search(r"\bsoft(ly)?\s+(voice|spoken|tone)\b", notes)
    )
    slow = bool(re.search(r"\b(slow\w*|deliberate|unhurried|measured)\b", notes))

    if expressive and not composed:
        style = max(style, 0.55)
        stability = min(stability, 0.40)
    if composed:
        stability = max(stability, 0.68)
        style = min(style, 0.22 if warm else 0.18)
    if warm:
        style = max(style, 0.28 if composed else 0.32)
        if not composed:
            stability = min(stability, 0.50)
    if whispery:
        style = max(style, 0.40)
        stability = min(stability, 0.45)
    if slow:
        # No native pace field beyond speed slider — slightly calmer delivery
        stability = max(stability, 0.60)

    return {
        "stability": max(0.0, min(1.0, stability)),
        "style": max(0.0, min(1.0, style)),
        "similarity_boost": max(0.0, min(1.0, sim)),
    }


def _wrap_if_missing(body: str, tag: str) -> str:
    """Wrap spoken body in <tag>…</tag> unless already present."""
    lower = body.lower()
    open_t, close_t = f"<{tag}>", f"</{tag}>"
    if open_t in lower or close_t in lower:
        return body
    return f"{open_t}{body}{close_t}"


def _apply_grok_delivery_tags(
    text: str,
    *,
    rate: float,
    delivery_notes: str = "",
) -> str:
    """
    Map speed + delivery notes to Grok wrapping tags around the spoken script.

    Delivery notes are never inserted as words — only known control tags.
    Known tags used: slow, soft, whisper (documented wrapping styles).
    """
    body = (text or "").strip()
    if not body:
        return body

    notes = (delivery_notes or "").lower()
    tags: list[str] = []

    want_slow = rate < 0.95 or bool(
        re.search(r"\b(slow\w*|deliberate|measured|unhurried|paced)\b", notes)
    )
    want_whisper = bool(
        re.search(r"\b(whisper\w*|hushed|under[- ]breath)\b", notes)
    )
    # "quiet authority" should not force soft/whisper tags
    want_soft = bool(
        re.search(r"\b(soft\w*|gentle|tender|intimate)\b", notes)
        or re.search(r"\b(speak|talk|read)\w*\s+quiet(ly)?\b", notes)
    ) and not want_whisper

    # Innermost → outermost: whisper/soft first, then slow
    if want_whisper:
        tags.append("whisper")
    elif want_soft:
        tags.append("soft")
    if want_slow:
        tags.append("slow")

    spoken = body
    for tag in tags:
        spoken = _wrap_if_missing(spoken, tag)
    return spoken


def build_voiceover_args(
    spec: AudioSpec,
    text: str,
    *,
    voice: str | None = None,
    custom_voice_id: str | None = None,
    tone: str | None = None,
    speed: float | None = None,
    delivery_notes: str | None = None,
) -> dict[str, Any]:
    """
    Build TTS args.

    ``text`` is the spoken script only — never mix delivery notes into it as prose.

    custom_voice_id: MiniMax clone ID — forces MiniMax-shaped payload.
    voice: default stock voice name/id for the provider.
    tone: UI delivery label (see VOICEOVER_TONES).
    speed: speech rate multiplier (~0.8–1.2).
    delivery_notes: optional style direction (not spoken). Mapped to provider
      knobs/tags when supported; ignored gracefully otherwise.
    """
    body = (text or "").strip()
    notes = _clean_delivery_notes(delivery_notes)
    args: dict[str, Any] = dict(spec.extra_defaults)
    tone_key = (tone or "Neutral").strip() or "Neutral"
    rate = clamp_voiceover_speed(speed, 1.0)

    if custom_voice_id or spec.voice_provider == "minimax" or "minimax" in spec.endpoint:
        # MiniMax speech-02-hd: emotion enum + speed; no freeform style field
        voice_id = (custom_voice_id or voice or spec.default_voice or "Wise_Woman").strip()
        emotion = _infer_minimax_emotion(tone_key, notes)
        args["text"] = body  # spoken only
        args["voice_setting"] = {
            "voice_id": voice_id,
            "speed": rate,
            "vol": 1.0,
            "emotion": emotion,
        }
        args["output_format"] = "url"
        for k in ("voice", "stability", "similarity_boost", "speed", "style"):
            args.pop(k, None)
        return args

    if spec.voice_provider == "grok" or "xai/tts" in spec.endpoint:
        # Grok: wrap spoken text with control tags derived from notes/speed.
        # Never inject delivery-notes prose into the payload.
        spoken = _apply_grok_delivery_tags(body, rate=rate, delivery_notes=notes)
        args["text"] = spoken
        args["voice"] = _normalize_grok_voice(voice or spec.default_voice, "eve")
        if "language" not in args:
            args["language"] = "auto"
        for k in (
            "voice_setting",
            "stability",
            "similarity_boost",
            "speed",
            "style",
            "output_format",
        ):
            args.pop(k, None)
        return args

    # ElevenLabs — spoken text only; style via stability/style floats
    args["text"] = body
    if spec.supports_voice:
        args["voice"] = (voice or spec.default_voice or "Rachel").strip() or "Rachel"
    el = _infer_elevenlabs_knobs(tone_key, notes)
    args["speed"] = rate
    args["stability"] = el["stability"]
    args["style"] = el["style"]
    args["similarity_boost"] = el["similarity_boost"]
    return args


def build_voice_clone_args(
    spec: AudioSpec,
    audio_url: str,
    *,
    preview_text: str | None = None,
    noise_reduction: bool = True,
) -> dict[str, Any]:
    args = dict(spec.extra_defaults)
    args["audio_url"] = audio_url
    args["noise_reduction"] = bool(noise_reduction)
    args["need_volume_normalization"] = True
    if preview_text and preview_text.strip():
        args["text"] = preview_text.strip()
    return args


def default_voices_for_model(spec: AudioSpec | None) -> list[str]:
    if not spec:
        return ELEVENLABS_VOICES
    if spec.voice_provider == "minimax" or "minimax" in spec.endpoint:
        return MINIMAX_VOICES
    if spec.voice_provider == "grok" or "xai/tts" in spec.endpoint:
        return GROK_VOICES
    return ELEVENLABS_VOICES
