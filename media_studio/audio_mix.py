"""
Lightweight multi-layer SFX mix (v1) — sum of unmuted stems × volumes.

Not a DAW: no EQ, automation, or plugins. Bounce writes a stereo WAV;
optional stem export writes per-layer files with gain applied.

MP3/M4A: prefer a WAV sidecar (decoded via pygame — same path as single-file
Play) so bounce never depends on system ffmpeg. Absolute paths only at mix time.
"""

from __future__ import annotations

import shutil
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np

from media_studio.naming import job_media_dir, make_output_stem, timestamp_now, unique_path

TARGET_RATE = 44100
TARGET_CH = 2


@dataclass
class MixLayer:
    """One unmuted contribution to the mix."""

    name: str  # bed | spot | accent
    path: str
    volume: float = 1.0  # 0..1
    muted: bool = False


@dataclass
class MixResult:
    ok: bool
    mix_path: str | None = None
    stem_paths: list[str] | None = None
    status: str = ""
    duration_s: float = 0.0


def _resolve_existing(path: str | Path) -> Path:
    """Absolute path that must exist (no truncated relative names)."""
    p = Path(path).expanduser()
    try:
        p = p.resolve()
    except OSError:
        p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"Layer file missing: {p}")
    return p


def _ffmpeg_exe() -> str | None:
    """Resolve ffmpeg for optional MP3 decode (not required when pygame works)."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and Path(exe).is_file():
            return str(exe)
    except Exception:
        pass
    return None


def _configure_pydub_ffmpeg() -> str | None:
    """Point pydub at a real ffmpeg binary if available."""
    exe = _ffmpeg_exe()
    if not exe:
        return None
    try:
        from pydub import AudioSegment

        AudioSegment.converter = exe
        AudioSegment.ffmpeg = exe
        AudioSegment.ffprobe = exe.replace("ffmpeg", "ffprobe")
    except Exception:
        pass
    return exe


def write_wav(
    path: str | Path, samples: np.ndarray, sample_rate: int = TARGET_RATE
) -> str:
    """Write stereo float samples as 16-bit PCM WAV. Returns absolute path."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if samples.ndim == 1:
        samples = samples.reshape(-1, 1)
    if samples.shape[1] == 1:
        samples = np.repeat(samples, 2, axis=1)
    clipped = np.clip(samples, -1.0, 1.0)
    pcm = (clipped * 32767.0).astype(np.int16)
    with wave.open(str(p), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(int(sample_rate))
        wf.writeframes(pcm.tobytes())
    return str(p.resolve())


def _load_wav_float(p: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(p), "rb") as wf:
        ch = wf.getnchannels()
        sw = wf.getsampwidth()
        rate = wf.getframerate()
        n = wf.getnframes()
        raw = wf.readframes(n)
    if sw == 2:
        data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif sw == 4:
        data = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
    elif sw == 1:
        data = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    else:
        raise ValueError(f"Unsupported WAV sample width: {sw}")
    if ch > 1:
        data = data.reshape(-1, ch)
    else:
        data = data.reshape(-1, 1)
    return data, int(rate)


def _load_via_pygame(p: Path) -> tuple[np.ndarray, int]:
    """
    Decode with pygame (same stack as single-file Play) → float samples.

    Works for MP3 on Windows without system ffmpeg.
    """
    try:
        from media_studio.flet_audio_player import _ensure_mixer
    except Exception as exc:
        raise RuntimeError(f"pygame mixer unavailable: {exc}") from exc

    ok, err = _ensure_mixer()
    if not ok:
        raise RuntimeError(err or "pygame.mixer failed to init")

    import pygame

    # Pause music stream so Sound load is clean
    try:
        if pygame.mixer.get_init() and pygame.mixer.music.get_busy():
            pygame.mixer.music.stop()
    except Exception:
        pass

    abs_path = str(p.resolve())
    try:
        snd = pygame.mixer.Sound(abs_path)
    except Exception as exc:
        raise RuntimeError(f"pygame could not load {p.name}: {exc}") from exc

    rate = TARGET_RATE
    try:
        init = pygame.mixer.get_init()
        if init:
            rate = int(init[0])
    except Exception:
        pass

    try:
        import pygame.sndarray

        arr = pygame.sndarray.array(snd)
        data = np.asarray(arr, dtype=np.float32)
        if data.ndim == 1:
            data = data.reshape(-1, 1)
        # int16 typical
        if data.dtype == np.int16 or np.max(np.abs(data)) > 1.5:
            data = data / 32768.0
        return data.astype(np.float32), rate
    except Exception:
        raw = snd.get_raw()
        data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        # Assume stereo if even length and mixer is stereo
        ch = 2
        try:
            init = pygame.mixer.get_init()
            if init:
                ch = int(init[2]) or 2
        except Exception:
            pass
        if ch > 1 and data.size % ch == 0:
            data = data.reshape(-1, ch)
        else:
            data = data.reshape(-1, 1)
        return data, rate


def _load_via_ffmpeg_wav(p: Path, dest_wav: Path) -> tuple[np.ndarray, int]:
    """Decode any format to temp WAV with ffmpeg, then load."""
    exe = _ffmpeg_exe()
    if not exe:
        raise RuntimeError("ffmpeg not found")
    dest_wav.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        exe,
        "-y",
        "-i",
        str(p.resolve()),
        "-ac",
        "2",
        "-ar",
        str(TARGET_RATE),
        "-sample_fmt",
        "s16",
        str(dest_wav.resolve()),
    ]
    try:
        subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            timeout=120,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"ffmpeg missing (WinError 2). Path tried: {exe}"
        ) from exc
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or b"").decode("utf-8", errors="replace")[:200]
        raise RuntimeError(f"ffmpeg decode failed for {p.name}: {err}") from exc
    return _load_wav_float(dest_wav)


def _load_via_pydub(p: Path) -> tuple[np.ndarray, int]:
    _configure_pydub_ffmpeg()
    from pydub import AudioSegment

    seg = AudioSegment.from_file(str(p.resolve()))
    samples = np.array(seg.get_array_of_samples())
    ch = seg.channels
    if ch > 1:
        samples = samples.reshape(-1, ch)
    else:
        samples = samples.reshape(-1, 1)
    max_v = float(1 << (8 * seg.sample_width - 1))
    data = samples.astype(np.float32) / max_v
    return data, int(seg.frame_rate)


def ensure_wav_for_mix(path: str | Path) -> str:
    """
    Return absolute path to a WAV suitable for mixing.

    - Already WAV → resolved absolute path
    - Else create/reuse sibling sidecar ``<stem>.mix.wav`` via pygame (preferred)
      or ffmpeg, so bounce never requires a system ffmpeg for typical SFX MP3s.
    """
    p = _resolve_existing(path)
    if p.suffix.lower() in (".wav", ".wave"):
        return str(p)

    sidecar = p.with_suffix(p.suffix + ".mix.wav")
    # Reuse if newer or same mtime as source
    try:
        if sidecar.is_file() and sidecar.stat().st_mtime >= p.stat().st_mtime - 0.5:
            if sidecar.stat().st_size > 44:
                return str(sidecar.resolve())
    except OSError:
        pass

    errors: list[str] = []

    # 1) pygame (same as Play layer — works for MP3 on Windows without ffmpeg)
    try:
        data, rate = _load_via_pygame(p)
        data = _to_stereo(data)
        data = _resample_linear(data, rate, TARGET_RATE)
        write_wav(sidecar, data, TARGET_RATE)
        return str(sidecar.resolve())
    except Exception as exc:
        errors.append(f"pygame: {exc}")

    # 2) ffmpeg → WAV sidecar
    try:
        data, rate = _load_via_ffmpeg_wav(p, sidecar)
        return str(sidecar.resolve())
    except Exception as exc:
        errors.append(f"ffmpeg: {exc}")

    # 3) pydub with configured converter
    try:
        data, rate = _load_via_pydub(p)
        data = _to_stereo(data)
        data = _resample_linear(data, rate, TARGET_RATE)
        write_wav(sidecar, data, TARGET_RATE)
        return str(sidecar.resolve())
    except Exception as exc:
        errors.append(f"pydub: {exc}")

    detail = "; ".join(errors[:3])
    raise RuntimeError(
        f"Could not prepare WAV for mix from {p.name}. "
        f"Single-file Play uses pygame; mix needs a WAV sidecar. ({detail})"
    )


def _load_audio_float(path: str | Path) -> tuple[np.ndarray, int]:
    """
    Load audio as float32 (n_samples, channels) in [-1, 1].

    Always resolves to WAV first (ensure_wav_for_mix) for non-WAV sources.
    """
    p = _resolve_existing(path)
    if p.suffix.lower() not in (".wav", ".wave"):
        p = Path(ensure_wav_for_mix(p))
    return _load_wav_float(p)


def _resample_linear(data: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    if src_rate == dst_rate or data.shape[0] < 2:
        return data
    n_src = data.shape[0]
    n_dst = max(1, int(round(n_src * dst_rate / src_rate)))
    x_old = np.linspace(0.0, 1.0, n_src, endpoint=False)
    x_new = np.linspace(0.0, 1.0, n_dst, endpoint=False)
    out = np.zeros((n_dst, data.shape[1]), dtype=np.float32)
    for c in range(data.shape[1]):
        out[:, c] = np.interp(x_new, x_old, data[:, c]).astype(np.float32)
    return out


def _to_stereo(data: np.ndarray) -> np.ndarray:
    if data.ndim == 1:
        data = data.reshape(-1, 1)
    ch = data.shape[1]
    if ch == 1:
        return np.repeat(data, 2, axis=1)
    if ch == 2:
        return data
    return data[:, :2].copy()


def prepare_layer(
    path: str | Path,
    *,
    volume: float = 1.0,
    target_rate: int = TARGET_RATE,
) -> tuple[np.ndarray, int]:
    """Load (via WAV sidecar if needed), resample, apply volume."""
    wav_path = ensure_wav_for_mix(path)
    data, rate = _load_wav_float(Path(wav_path))
    data = _to_stereo(data)
    data = _resample_linear(data, rate, target_rate)
    vol = max(0.0, min(2.0, float(volume)))
    return (data * vol).astype(np.float32), target_rate


def mix_layers(
    layers: Sequence[MixLayer],
    *,
    target_rate: int = TARGET_RATE,
) -> tuple[np.ndarray, int, list[tuple[str, np.ndarray]]]:
    """
    Sum unmuted layers × volumes.

    Returns (mix_samples, sample_rate, stem_samples_list).
    """
    active: list[MixLayer] = []
    for L in layers:
        if L.muted:
            continue
        if not L.path:
            continue
        try:
            abs_p = str(_resolve_existing(L.path))
        except FileNotFoundError:
            raise FileNotFoundError(
                f"Layer “{L.name}” file missing or moved: {L.path}"
            ) from None
        active.append(
            MixLayer(name=L.name, path=abs_p, volume=L.volume, muted=False)
        )

    if not active:
        raise ValueError("No unmuted layers with audio to mix.")

    stems: list[tuple[str, np.ndarray]] = []
    max_len = 0
    for L in active:
        samples, _ = prepare_layer(L.path, volume=L.volume, target_rate=target_rate)
        stems.append((L.name, samples))
        max_len = max(max_len, samples.shape[0])

    mix = np.zeros((max_len, TARGET_CH), dtype=np.float32)
    padded_stems: list[tuple[str, np.ndarray]] = []
    for name, samples in stems:
        if samples.shape[0] < max_len:
            pad = np.zeros((max_len - samples.shape[0], TARGET_CH), dtype=np.float32)
            samples = np.vstack([samples, pad])
        mix += samples
        padded_stems.append((name, samples))

    peak = float(np.max(np.abs(mix))) if mix.size else 0.0
    if peak > 1.0:
        mix = mix / peak * 0.98

    return mix, target_rate, padded_stems


def bounce_mix(
    layers: Sequence[MixLayer],
    *,
    output_dir: str | Path,
    export_stems: bool = False,
    name_hint: str = "sfx_mix",
) -> MixResult:
    """
    Bounce mix to outputs/… and optionally export gain-applied stems.
    """
    try:
        # Pre-resolve all layers to absolute WAV before summing
        resolved: list[MixLayer] = []
        for L in layers:
            if L.muted or not L.path:
                continue
            try:
                abs_src = str(_resolve_existing(L.path))
                wav = ensure_wav_for_mix(abs_src)
                resolved.append(
                    MixLayer(
                        name=L.name,
                        path=wav,
                        volume=L.volume,
                        muted=False,
                    )
                )
            except Exception as exc:
                return MixResult(
                    ok=False,
                    status=f"Layer “{L.name}”: {exc}",
                )
        if not resolved:
            return MixResult(
                ok=False,
                status="No unmuted layers with audio to mix.",
            )
        mix, rate, stems = mix_layers(resolved)
    except Exception as exc:
        return MixResult(ok=False, status=str(exc))

    stamp = timestamp_now()
    media_dir = job_media_dir(output_dir, stamp=stamp)
    stem = make_output_stem(name_hint[:40], "mixer", stamp=stamp, kind="audio")
    mix_path = unique_path(media_dir, stem, ".wav")
    try:
        write_wav(mix_path, mix, rate)
    except Exception as exc:
        return MixResult(ok=False, status=f"Write mix failed: {exc}")

    stem_paths: list[str] = []
    if export_stems:
        for slot_name, samples in stems:
            peak = float(np.max(np.abs(samples))) if samples.size else 0.0
            out = samples
            if peak > 1.0:
                out = samples / peak * 0.98
            sp = unique_path(media_dir, f"{stem}_{slot_name}", ".wav")
            try:
                write_wav(sp, out, rate)
                stem_paths.append(str(Path(sp).resolve()))
            except Exception:
                pass

    dur = float(mix.shape[0]) / float(rate) if rate else 0.0
    n_layers = len(stems)
    status = (
        f"Mix bounced ({n_layers} layer{'s' if n_layers != 1 else ''}, "
        f"{dur:.1f}s) → {Path(mix_path).name}"
    )
    if stem_paths:
        status += f" · {len(stem_paths)} stem(s)"
    return MixResult(
        ok=True,
        mix_path=str(Path(mix_path).resolve()),
        stem_paths=stem_paths or None,
        status=status,
        duration_s=dur,
    )


def copy_as_stem(
    src: str | Path,
    *,
    output_dir: str | Path,
    slot_name: str,
) -> str | None:
    """Copy a layer file into the job folder as a named stem (no re-encode)."""
    try:
        p = _resolve_existing(src)
        stamp = timestamp_now()
        media_dir = job_media_dir(output_dir, stamp=stamp)
        dest = unique_path(media_dir, f"stem_{slot_name}", p.suffix or ".wav")
        shutil.copy2(p, dest)
        return str(dest.resolve())
    except (OSError, FileNotFoundError):
        return None
