"""Run Audio-tab utilities (music / SFX / video-SFX / voiceover / voice clone) via fal."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from media_studio.audio_registry import (
    AMBIENCE_MODELS,
    MUSIC_MODELS,
    SFX_MODELS,
    VIDEO_SFX_MODELS,
    VOICE_CLONE_MODELS,
    VOICEOVER_MODELS,
    AudioSpec,
    build_ambience_args,
    build_music_args,
    build_sfx_args,
    build_video_sfx_args,
    build_voice_clone_args,
    build_voiceover_args,
    estimate_audio_cost,
    find_audio,
    video_sfx_limits,
    video_sfx_prefer_video,
)
from media_studio.errors import friendly_error
from media_studio.fal.client import FalClientError, download_url, subscribe, upload_file
from media_studio.my_voices import (
    SavedVoice,
    add_voice,
    copy_sample_to_store,
    find_voice,
    is_my_voice_label,
    strip_default_prefix,
)
from media_studio.naming import job_media_dir, make_output_stem, timestamp_now, unique_path
from media_studio.pricing import (
    extract_cost_usd_from_response,
    format_cost_label,
    format_render_metrics,
)

ProgressCallback = Callable[[str], None]


@dataclass
class AudioResult:
    ok: bool
    path: str | None = None
    status: str = ""
    metrics_line: str = ""
    cost_label: str = ""
    notes: list[str] = field(default_factory=list)
    # Voice clone extras
    custom_voice_id: str | None = None
    saved_voice: SavedVoice | None = None


def _url_from_fileish(item: Any) -> str | None:
    if isinstance(item, str) and item.strip():
        return item.strip()
    if isinstance(item, dict):
        url = item.get("url") or item.get("file_url") or item.get("audio_url")
        if url:
            return str(url)
    return None


def extract_audio_url(result: dict[str, Any]) -> str | None:
    """Pull audio URL from common fal audio response shapes (incl. Mirelo arrays)."""
    if not isinstance(result, dict):
        return None
    audio = result.get("audio") or result.get("audio_url") or result.get("output")
    # Prefer first sample when models return a list of audio files (Mirelo)
    if isinstance(audio, list) and audio:
        for item in audio:
            u = _url_from_fileish(item)
            if u:
                return u
    u = _url_from_fileish(audio)
    if u:
        lower = u.lower()
        # If top-level "output" is a video, skip (handled by extract_video_url)
        if any(lower.endswith(ext) for ext in (".mp4", ".mov", ".webm", ".mkv")):
            pass
        else:
            return u
    for key in ("audios", "files", "outputs", "audio_files"):
        items = result.get(key)
        if isinstance(items, list) and items:
            for item in items:
                u2 = _url_from_fileish(item)
                if u2:
                    low = u2.lower()
                    if any(
                        low.endswith(ext)
                        for ext in (".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac", ".opus")
                    ):
                        return u2
                    if "audio" in low or "sound" in low or "sfx" in low:
                        return u2
            # fall back to first fileish even without extension hint
            u3 = _url_from_fileish(items[0])
            if u3 and not any(
                u3.lower().endswith(ext) for ext in (".mp4", ".mov", ".webm", ".mkv")
            ):
                return u3
    url = result.get("url")
    if isinstance(url, str) and url.strip():
        lower = url.lower()
        if any(lower.endswith(ext) for ext in (".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac")):
            return url.strip()
        if "audio" in lower or "sound" in lower or "music" in lower:
            return url.strip()
    return None


def extract_video_url(result: dict[str, Any]) -> str | None:
    if not isinstance(result, dict):
        return None
    video = result.get("video") or result.get("video_url")
    if isinstance(video, str) and video.strip():
        return video.strip()
    if isinstance(video, dict):
        url = video.get("url") or video.get("file_url")
        if url:
            return str(url)
    return None


def _extension_from_url(url: str, default: str = ".mp3") -> str:
    path = urlparse(url).path
    suffix = Path(path).suffix.lower()
    if suffix in {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac", ".opus", ".mp4", ".webm", ".mov"}:
        return suffix
    return default


def _run_audio(
    *,
    spec: AudioSpec,
    arguments: dict[str, Any],
    output_dir: str | Path,
    prompt_for_name: str,
    kind: str,
    est_cost: float,
    on_progress: ProgressCallback | None = None,
    prefer_video: bool = False,
) -> AudioResult:
    def progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    est = format_cost_label(est_cost, estimate=True)
    progress(f"{spec.label} · {est}")
    progress(f"Endpoint: {spec.endpoint}")

    progress("Running on fal…")
    t0 = time.perf_counter()
    try:
        result = subscribe(spec.endpoint, arguments, on_progress=progress)
    except FalClientError as exc:
        render_s = time.perf_counter() - t0
        return AudioResult(
            ok=False,
            status=str(exc),
            metrics_line=format_render_metrics(render_s, None, cost_is_estimate=True),
            cost_label=est,
        )
    except Exception as exc:
        render_s = time.perf_counter() - t0
        return AudioResult(
            ok=False,
            status=friendly_error(exc, context=spec.label),
            metrics_line=format_render_metrics(render_s, None, cost_is_estimate=True),
            cost_label=est,
        )
    render_s = time.perf_counter() - t0

    exact = extract_cost_usd_from_response(result)
    cost_usd = exact if exact is not None else est_cost
    is_est = exact is None
    metrics = format_render_metrics(render_s, cost_usd, cost_is_estimate=is_est)
    cost_lbl = format_cost_label(cost_usd, estimate=is_est)

    out_url = extract_audio_url(result)
    if not out_url and prefer_video:
        out_url = extract_video_url(result)
    if not out_url:
        # last resort video
        out_url = extract_video_url(result)
    if not out_url:
        return AudioResult(
            ok=False,
            status=f"{spec.label}: fal returned no audio.",
            metrics_line=metrics,
            cost_label=cost_lbl,
        )

    stamp = timestamp_now()
    media_dir = job_media_dir(output_dir, stamp=stamp)
    stem = make_output_stem(prompt_for_name, spec.key, stamp=stamp, kind=kind)
    ext = _extension_from_url(out_url, default=".mp4" if prefer_video else ".mp3")
    dest = unique_path(media_dir, stem, ext)

    try:
        download_url(out_url, dest, on_progress=progress)
    except FalClientError as exc:
        return AudioResult(
            ok=False,
            status=str(exc),
            metrics_line=metrics,
            cost_label=cost_lbl,
        )

    resolved = str(dest.resolve())
    status = (
        f"{spec.label} OK. Saved {Path(resolved).name} → {media_dir}. "
        f"{metrics}. Use Show in folder or Send to Resolve."
    )
    # Index successful audio gens in Library (newest first)
    try:
        from media_studio.history import append_history

        kind_map = {
            "music": "music",
            "sfx": "sfx",
            "ambience": "ambience",
            "video-sfx": "video-sfx",
            "voiceover": "voiceover",
            "voice-clone": "voiceover",
        }
        job_kind = kind_map.get(kind, "audio")
        append_history(
            job_kind=job_kind,
            model=spec.label,
            prompt=prompt_for_name or "",
            files=[resolved],
            cost_estimate=cost_lbl,
            notes=[spec.notes] if spec.notes else [],
            output_dir=output_dir,
            timestamp=stamp,
            scenario=job_kind,
        )
    except Exception:
        pass  # never block a successful download on history write
    return AudioResult(
        ok=True,
        path=resolved,
        status=status,
        metrics_line=metrics,
        cost_label=cost_lbl,
        notes=[spec.notes] if spec.notes else [],
    )


def run_music(
    *,
    prompt: str | None,
    model_label: str | None,
    duration_s: float = 30.0,
    instrumental: bool = True,
    output_dir: str | Path,
    on_progress: ProgressCallback | None = None,
) -> AudioResult:
    spec = find_audio(model_label, MUSIC_MODELS)
    if not spec:
        return AudioResult(ok=False, status="Choose a music model.")
    text = (prompt or "").strip()
    if not text:
        return AudioResult(ok=False, status="Enter a music prompt (style / mood / instruments).")
    if len(text) < 3:
        return AudioResult(ok=False, status="Prompt is too short.")

    dur = float(duration_s) if duration_s is not None else spec.duration_default_s
    if not spec.supports_duration:
        dur = spec.fixed_duration_s or dur

    args = build_music_args(
        spec, text, duration_s=dur if spec.supports_duration else None, instrumental=instrumental
    )
    est = estimate_audio_cost(
        spec,
        duration_s=dur if spec.supports_duration else (spec.fixed_duration_s or 30.0),
    )
    return _run_audio(
        spec=spec,
        arguments=args,
        output_dir=output_dir,
        prompt_for_name=text,
        kind="music",
        est_cost=est,
        on_progress=on_progress,
    )


def run_sfx(
    *,
    prompt: str | None,
    model_label: str | None,
    duration_s: float = 5.0,
    loop: bool = False,
    output_dir: str | Path,
    on_progress: ProgressCallback | None = None,
    seed: int | None = None,
    variation_index: int | None = None,
) -> AudioResult:
    """
    Single SFX generation.

    ``seed`` / ``variation_index`` are optional for multi-variation batches.
    """
    spec = find_audio(model_label, SFX_MODELS) or next(iter(SFX_MODELS.values()))
    text = (prompt or "").strip()
    if not text:
        return AudioResult(
            ok=False,
            status="Describe the sound effect (e.g. soft door close, city ambience).",
        )

    dur = float(duration_s) if duration_s is not None else spec.duration_default_s
    # Light prompt nudge for variations when seed alone may be ignored
    body = text
    if variation_index is not None and variation_index > 0:
        body = f"{text.rstrip('.')} — alternate take {variation_index + 1}."
    args = build_sfx_args(spec, body, duration_s=dur, loop=loop, seed=seed)
    est = estimate_audio_cost(spec, duration_s=dur)
    name = text if variation_index is None else f"{text[:40]}-v{variation_index + 1}"
    return _run_audio(
        spec=spec,
        arguments=args,
        output_dir=output_dir,
        prompt_for_name=name,
        kind="sfx",
        est_cost=est,
        on_progress=on_progress,
    )


def run_ambience(
    *,
    prompt: str | None,
    model_label: str | None,
    duration_s: float = 30.0,
    output_dir: str | Path,
    on_progress: ProgressCallback | None = None,
    builder_kwargs: dict[str, Any] | None = None,
) -> AudioResult:
    """Continuous background ambient bed (not one-shot SFX)."""
    from media_studio.ambience_builder import fit_ambience_prompt_for_model

    spec = find_audio(model_label, AMBIENCE_MODELS) or next(iter(AMBIENCE_MODELS.values()))
    text = (prompt or "").strip()
    if not text:
        return AudioResult(
            ok=False,
            status="Build or enter an ambience prompt (location, layers, density).",
        )
    if len(text) < 8:
        return AudioResult(ok=False, status="Ambience prompt is too short.")

    dur = float(duration_s) if duration_s is not None else spec.duration_default_s
    # Clamp to model duration limits
    if spec.supports_duration:
        dur = max(spec.duration_min_s, min(spec.duration_max_s, dur))

    # Enforce model prompt length (e.g. ElevenLabs SFX ~450 chars if re-added)
    text, length_note = fit_ambience_prompt_for_model(
        text,
        max_chars=spec.max_prompt_chars,
        builder_kwargs=builder_kwargs,
    )
    if length_note and on_progress:
        on_progress(length_note)

    if duration_s is not None and float(duration_s) > spec.duration_max_s + 0.01:
        clamp_note = (
            f"Duration clamped to {int(spec.duration_max_s)}s for {spec.label} "
            f"(requested {int(float(duration_s))}s)."
        )
        if on_progress:
            on_progress(clamp_note)

    args = build_ambience_args(spec, text, duration_s=dur)
    est = estimate_audio_cost(spec, duration_s=dur)

    result = _run_audio(
        spec=spec,
        arguments=args,
        output_dir=output_dir,
        prompt_for_name=text[:80],
        kind="ambience",
        est_cost=est,
        on_progress=on_progress,
    )

    # Clearer error when fal rejects for prompt length / validation
    if not result.ok and result.status:
        low = result.status.lower()
        if any(
            k in low
            for k in (
                "character",
                "too long",
                "max length",
                "prompt length",
                "450",
                "validation",
                "invalid prompt",
            )
        ):
            limit = spec.max_prompt_chars
            limit_txt = f" (limit ~{limit} characters)" if limit else ""
            result.status = (
                f"{spec.label} rejected the prompt{limit_txt}. "
                f"Est. cost would have been {result.cost_label or format_cost_label(est, estimate=True)}. "
                f"Shorten the prompt or switch to Stable Audio 2.5 Ambience for longer beds. "
                f"Details: {result.status}"
            )
    elif length_note and result.ok:
        result.status = f"{result.status} ({length_note})"
    return result


def run_video_sfx(
    *,
    video_path: str | None,
    model_label: str | None = None,
    prompt: str | None = None,
    output_dir: str | Path,
    on_progress: ProgressCallback | None = None,
    duration_s: float | None = None,
) -> AudioResult:
    """
    Upload a video → generate matching SFX / Foley audio.

    Prefers a standalone audio track when the API provides one (Resolve layering).
    Falls back to muxed video+audio when that is all the endpoint returns (MMAudio).
    """
    spec = find_audio(model_label, VIDEO_SFX_MODELS) or next(iter(VIDEO_SFX_MODELS.values()))

    def progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    path = Path(video_path) if video_path else None
    if not path or not path.is_file():
        return AudioResult(ok=False, status="Upload a video for Video-to-SFX.")

    # Probe length / size for cost + clear preflight errors
    from media_studio.pricing import probe_video_duration

    probed = duration_s
    if probed is None or probed <= 0:
        probed = probe_video_duration(path)
    dur = float(probed) if probed and probed > 0 else None

    try:
        size_mb = path.stat().st_size / (1024 * 1024)
    except OSError:
        size_mb = 0.0

    limits = video_sfx_limits(spec)
    max_s = limits.get("max_video_seconds")
    min_s = limits.get("min_video_seconds")
    max_mb = limits.get("max_file_mb")

    if max_mb is not None and size_mb > max_mb + 0.01:
        return AudioResult(
            ok=False,
            status=(
                f"{spec.label} rejects files over ~{max_mb:.0f} MB "
                f"(yours is {size_mb:.0f} MB). Export a shorter/lower-bitrate "
                "proxy (e.g. 3–15s Render-in-Place) and retry."
            ),
            cost_label=format_cost_label(
                estimate_audio_cost(spec, duration_s=dur or 15.0), estimate=True
            ),
        )
    if dur is not None and min_s is not None and dur + 0.05 < min_s:
        return AudioResult(
            ok=False,
            status=(
                f"{spec.label} needs about {min_s:.0f}s+ of video "
                f"(yours is {dur:.1f}s). Use a longer clip or pick another model."
            ),
            cost_label=format_cost_label(
                estimate_audio_cost(spec, duration_s=dur), estimate=True
            ),
        )
    if dur is not None and max_s is not None and dur > max_s + 0.25:
        # Hard reject when model cannot take the full length (Kling ~20s, MMAudio 30s)
        # MMAudio can clamp via duration param — only hard-fail when far over or no clamp
        if "mmaudio" in spec.endpoint or "mirelo" in spec.endpoint:
            progress(
                f"Clip is {dur:.1f}s; {spec.label} will generate up to "
                f"{max_s:.0f}s of audio (duration param)."
            )
            dur = min(dur, max_s)
        else:
            return AudioResult(
                ok=False,
                status=(
                    f"{spec.label} max length is about {max_s:.0f}s "
                    f"(yours is {dur:.1f}s). Trim/export a shorter proxy and retry, "
                    "or switch to MMAudio V2 / Mirelo / Sonilo."
                ),
                cost_label=format_cost_label(
                    estimate_audio_cost(spec, duration_s=max_s), estimate=True
                ),
            )

    cost_dur = dur if dur is not None else 15.0
    est = estimate_audio_cost(spec, duration_s=cost_dur)
    progress(f"{spec.label} · {format_cost_label(est, estimate=True)}")
    if dur is not None:
        progress(f"Source duration ≈ {dur:.1f}s · {size_mb:.1f} MB")

    # Char-limit feedback (Kling ~200): never silent truncate
    prompt_note = (prompt or "").strip()
    max_chars = spec.max_prompt_chars
    trunc_note = ""
    if max_chars is not None and prompt_note and len(prompt_note) > max_chars:
        trunc_note = (
            f"Prompt truncated {len(prompt_note)} → {max_chars} chars for {spec.label}."
        )
        progress(trunc_note)

    try:
        video_url = upload_file(path, on_progress=progress)
    except (FalClientError, Exception) as exc:
        return AudioResult(
            ok=False,
            status=friendly_error(exc, context="Video upload"),
            cost_label=format_cost_label(est, estimate=True),
        )

    args = build_video_sfx_args(
        spec, video_url, prompt=prompt, duration_s=dur
    )
    name_hint = (prompt or "").strip() or path.stem
    prefer_video = video_sfx_prefer_video(spec)
    result = _run_audio(
        spec=spec,
        arguments=args,
        output_dir=output_dir,
        prompt_for_name=f"video-sfx-{name_hint}",
        kind="video-sfx",
        est_cost=est,
        on_progress=on_progress,
        prefer_video=prefer_video,
    )
    # Clarify muxed-video outcomes for Resolve users
    if result.ok and result.path:
        ext = Path(result.path).suffix.lower()
        if ext in {".mp4", ".mov", ".webm", ".mkv"}:
            result.status = (
                f"{result.status} "
                "(Saved video+audio — no separate audio track from this model; "
                "use in Resolve as a clip or extract audio in post.)"
            )
        else:
            result.status = (
                f"{result.status} "
                "(Audio track — drop onto A1 in Resolve under picture.)"
            )
    if trunc_note:
        result.status = f"{result.status} {trunc_note}".strip()
    return result


def _resolve_voice_for_tts(
    *,
    model_label: str | None,
    voice_label: str | None,
) -> tuple[AudioSpec | None, str | None, str | None, str | None]:
    """
    Returns (spec, stock_voice_name, custom_voice_id, error_message).

    Custom My Voices always use MiniMax Speech 02 HD.
    """
    custom = find_voice(voice_label) if is_my_voice_label(voice_label) else None
    if custom:
        spec = find_audio("minimax speech 02 hd", VOICEOVER_MODELS) or find_audio(
            "MiniMax Speech 02 HD", VOICEOVER_MODELS
        )
        if not spec:
            # hard fallback
            spec = next(
                (s for s in VOICEOVER_MODELS.values() if "minimax" in s.endpoint),
                None,
            )
        return spec, None, custom.custom_voice_id, None

    spec = find_audio(model_label, VOICEOVER_MODELS)
    stock = strip_default_prefix(voice_label) if voice_label else None
    if not stock and spec:
        stock = spec.default_voice
    return spec, stock, None, None


def run_voiceover(
    *,
    text: str | None,
    model_label: str | None,
    voice: str | None = None,
    tone: str | None = None,
    speed: float | None = None,
    delivery_notes: str | None = None,
    output_dir: str | Path,
    on_progress: ProgressCallback | None = None,
) -> AudioResult:
    body = (text or "").strip()
    if not body:
        return AudioResult(ok=False, status="Enter the script to speak.")
    if len(body) < 2:
        return AudioResult(ok=False, status="Script is too short.")

    notes = (delivery_notes or "").strip()

    spec, stock_voice, custom_id, err = _resolve_voice_for_tts(
        model_label=model_label, voice_label=voice
    )
    if err:
        return AudioResult(ok=False, status=err)
    if not spec:
        return AudioResult(ok=False, status="Choose a voiceover model.")

    # When using a custom clone, force MiniMax endpoint + payload
    if custom_id:
        mm = find_audio("minimax speech 02 hd", VOICEOVER_MODELS)
        if mm:
            spec = mm
        args = build_voiceover_args(
            spec,
            body,
            custom_voice_id=custom_id,
            tone=tone,
            speed=speed,
            delivery_notes=notes,
        )
        note = f"Using My Voice clone ({custom_id[:12]}…)"
        if on_progress:
            on_progress(note)
    else:
        args = build_voiceover_args(
            spec,
            body,
            voice=stock_voice,
            tone=tone,
            speed=speed,
            delivery_notes=notes,
        )

    # Cost is based on spoken script only (delivery notes are not billed as speech)
    est = estimate_audio_cost(spec, text=body)
    return _run_audio(
        spec=spec,
        arguments=args,
        output_dir=output_dir,
        prompt_for_name=body[:80],
        kind="voiceover",
        est_cost=est,
        on_progress=on_progress,
    )


def run_voice_clone(
    *,
    audio_path: str | None,
    voice_name: str | None,
    preview_text: str | None = None,
    noise_reduction: bool = True,
    model_label: str | None = None,
    output_dir: str | Path,
    on_progress: ProgressCallback | None = None,
) -> AudioResult:
    """
    Upload speech sample → MiniMax voice clone → save to My Voices.
    Optionally downloads preview audio.
    """
    spec = find_audio(model_label, VOICE_CLONE_MODELS) or next(
        iter(VOICE_CLONE_MODELS.values())
    )

    def progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    name = (voice_name or "").strip()
    if not name:
        return AudioResult(ok=False, status="Give the voice a name (e.g. Realtor Jane).")

    path = Path(audio_path) if audio_path else None
    if not path or not path.is_file():
        return AudioResult(
            ok=False,
            status="Upload a clean speech sample (≥10 seconds of clear talking).",
        )

    est = estimate_audio_cost(spec)
    est_lbl = format_cost_label(est, estimate=True)
    progress(f"{spec.label} · {est_lbl}")
    progress("Tip: use this voice in Voiceover within 7 days so MiniMax keeps the clone.")

    try:
        audio_url = upload_file(path, on_progress=progress)
    except (FalClientError, Exception) as exc:
        return AudioResult(
            ok=False,
            status=friendly_error(exc, context="Voice sample upload"),
            cost_label=est_lbl,
        )

    args = build_voice_clone_args(
        spec,
        audio_url,
        preview_text=preview_text,
        noise_reduction=noise_reduction,
    )

    progress("Cloning voice on fal…")
    t0 = time.perf_counter()
    try:
        result = subscribe(spec.endpoint, args, on_progress=progress)
    except FalClientError as exc:
        render_s = time.perf_counter() - t0
        return AudioResult(
            ok=False,
            status=str(exc),
            metrics_line=format_render_metrics(render_s, None, cost_is_estimate=True),
            cost_label=est_lbl,
        )
    except Exception as exc:
        render_s = time.perf_counter() - t0
        return AudioResult(
            ok=False,
            status=friendly_error(exc, context=spec.label),
            metrics_line=format_render_metrics(render_s, None, cost_is_estimate=True),
            cost_label=est_lbl,
        )
    render_s = time.perf_counter() - t0

    if not isinstance(result, dict):
        return AudioResult(ok=False, status="Unexpected clone response.", cost_label=est_lbl)

    custom_id = (
        result.get("custom_voice_id")
        or result.get("voice_id")
        or result.get("customVoiceId")
    )
    if not custom_id or not str(custom_id).strip():
        return AudioResult(
            ok=False,
            status="Clone finished but no custom_voice_id returned.",
            cost_label=est_lbl,
        )
    custom_id = str(custom_id).strip()

    exact = extract_cost_usd_from_response(result)
    cost_usd = exact if exact is not None else est
    is_est = exact is None
    metrics = format_render_metrics(render_s, cost_usd, cost_is_estimate=is_est)
    cost_lbl = format_cost_label(cost_usd, estimate=is_est)

    # Optional preview download
    preview_path: str | None = None
    out_url = extract_audio_url(result)
    if out_url:
        stamp = timestamp_now()
        media_dir = job_media_dir(output_dir, stamp=stamp)
        stem = make_output_stem(f"clone-preview-{name}", spec.key, stamp=stamp, kind="voice-clone")
        dest = unique_path(media_dir, stem, _extension_from_url(out_url))
        try:
            download_url(out_url, dest, on_progress=progress)
            preview_path = str(dest.resolve())
        except FalClientError:
            preview_path = None

    sample_local = copy_sample_to_store(path, name)
    try:
        saved = add_voice(
            name=name,
            custom_voice_id=custom_id,
            provider="minimax",
            preview_path=preview_path,
            sample_path=sample_local,
            notes="MiniMax voice clone",
        )
    except ValueError as exc:
        return AudioResult(
            ok=False,
            status=str(exc),
            metrics_line=metrics,
            cost_label=cost_lbl,
            custom_voice_id=custom_id,
        )

    status = (
        f"Voice “{saved.name}” saved to My Voices. "
        f"ID: {custom_id[:16]}… · {metrics}. "
        "Select it under Voiceover → Voice (My · …). "
        "Use it for TTS within 7 days so MiniMax retains the clone."
    )
    return AudioResult(
        ok=True,
        path=preview_path,
        status=status,
        metrics_line=metrics,
        cost_label=cost_lbl,
        custom_voice_id=custom_id,
        saved_voice=saved,
        notes=[spec.notes] if spec.notes else [],
    )
