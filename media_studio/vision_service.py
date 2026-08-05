"""Run Creative Vision jobs (T2I / I2I / T2V / I2V / bridge) via fal."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from media_studio.errors import friendly_error
from media_studio.fal.client import (
    FalClientError,
    download_url,
    extract_draft_cache_url,
    extract_image_urls,
    extract_video_url,
    subscribe,
    upload_file,
)
from media_studio.history import append_history
from media_studio.naming import job_media_dir, make_output_stem, timestamp_now, unique_path
from media_studio.pricing import (
    extract_cost_usd_from_response,
    format_cost_label,
    format_render_metrics,
)
from media_studio.vision_registry import (
    VisionMode,
    build_vision_arguments,
    clamp_vision_num_images,
    default_vision_model,
    estimate_vision_cost,
    find_vision_model,
    format_vision_cost,
    is_still_mode,
    map_t2i_image_size,
)

ProgressCallback = Callable[[str], None]


@dataclass
class VisionResult:
    ok: bool
    path: str | None = None
    paths: list[str] = field(default_factory=list)
    model_key: str = ""
    endpoint: str = ""
    status: str = ""
    notes: list[str] = field(default_factory=list)
    cost_label: str = ""
    metrics_line: str = ""
    timestamp: str = ""
    is_draft: bool = False
    draft_cache_url: str | None = None


def run_vision(
    *,
    mode: VisionMode,
    prompt: str,
    model_label: str | None = None,
    image_path: str | None = None,
    first_frame_path: str | None = None,
    last_frame_path: str | None = None,
    ref_paths: list[str] | None = None,
    ref_video_paths: list[str] | None = None,
    ref_audio_paths: list[str] | None = None,
    source_video_path: str | None = None,
    duration: str | None = None,
    aspect_ratio: str | None = None,
    resolution: str | None = None,
    negative_prompt: str | None = None,
    generate_audio: bool | None = None,
    strength: float | None = None,
    num_images: int | None = None,
    draft: bool = False,
    output_dir: str | Path,
    on_progress: ProgressCallback | None = None,
) -> VisionResult:
    """
    Generate a Creative Vision still (T2I / I2I) or clip (T2V / I2V / bridge / extend).

    Still modes index as Image; video modes as creative_vision (Video filter).
    T2I supports multi-variant (1–4): multi-output in one call when the model
    allows, otherwise sequential singles (per-tab busy stays on vision).
    """
    spec = find_vision_model(model_label, mode) or default_vision_model(mode)
    want_n = clamp_vision_num_images(spec, num_images if mode == "text_to_image" else 1)

    def progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    est = estimate_vision_cost(
        spec,
        duration_token=duration or spec.default_duration,
        resolution=resolution,
        aspect_ratio=aspect_ratio,
        generate_audio=generate_audio,
        num_images=want_n if mode == "text_to_image" else 1,
    )
    est_lbl = format_cost_label(est, estimate=True)
    progress(f"{spec.label} · {est_lbl}")
    progress(f"Endpoint: {spec.endpoint}")

    # Upload media (not needed for pure T2I)
    image_url = None
    first_url = None
    last_url = None
    source_video_url = None
    ref_urls: list[str] = []
    ref_video_urls: list[str] = []
    ref_audio_urls: list[str] = []
    source_still_path: Path | None = None
    build_notes: list[str] = []
    is_omni = bool(getattr(spec, "omni_reference", False))

    try:
        if mode == "text_to_image":
            pass  # no uploads
        elif mode == "extend":
            vp = Path(source_video_path) if source_video_path else None
            if (not vp or not vp.is_file()) and ref_video_paths:
                for cand in ref_video_paths:
                    p = Path(cand) if cand else None
                    if p and p.is_file():
                        vp = p
                        break
            if not vp or not vp.is_file():
                return VisionResult(
                    ok=False,
                    model_key=spec.key,
                    endpoint=spec.endpoint,
                    status="Extend needs a source video clip.",
                    cost_label=format_vision_cost(spec, duration_token=duration),
                )
            progress(f"Uploading source clip: {vp.name}")
            source_video_url = upload_file(vp, on_progress=progress)
        elif mode == "image_to_image":
            ip = Path(image_path) if image_path else None
            if not ip or not ip.is_file():
                return VisionResult(
                    ok=False,
                    model_key=spec.key,
                    endpoint=spec.endpoint,
                    status="Image→Image needs a source still.",
                    cost_label=format_vision_cost(
                        spec, aspect_ratio=aspect_ratio, resolution=resolution
                    ),
                )
            source_still_path = ip
            progress(f"Uploading source still: {ip.name}")
            image_url = upload_file(ip, on_progress=progress)
            # Multi-ref extras — cap from fal.models (edit_model_key), not dual table
            from media_studio.fal.models import max_extra_ref_images_for_choice
            from media_studio.vision_registry import I2I_MAX_EXTRA_REFS

            edit_key = (getattr(spec, "edit_model_key", None) or "").strip() or (
                getattr(spec, "label", None) or ""
            )
            extra_cap = min(
                I2I_MAX_EXTRA_REFS,
                max(0, int(max_extra_ref_images_for_choice(edit_key))),
            )
            for rp in (ref_paths or [])[:extra_cap]:
                try:
                    p = Path(rp)
                    if not p.is_file():
                        continue
                    if str(p.resolve()) == str(ip.resolve()):
                        continue
                    progress(f"Uploading ref: {p.name}")
                    ref_urls.append(upload_file(p, on_progress=progress))
                except Exception as exc:
                    progress(f"Skip ref {rp}: {exc}")
                if len(ref_urls) >= extra_cap:
                    break
        elif mode == "image_to_video":
            ip = Path(image_path) if image_path else None
            if not ip or not ip.is_file():
                return VisionResult(
                    ok=False,
                    model_key=spec.key,
                    endpoint=spec.endpoint,
                    status="Image→Video needs a start still.",
                    cost_label=format_vision_cost(spec, duration_token=duration),
                )
            progress(f"Uploading start frame: {ip.name}")
            image_url = upload_file(ip, on_progress=progress)
            # Optional end for Hailuo / H3 I2V
            if last_frame_path and Path(last_frame_path).is_file():
                progress(f"Uploading end frame: {Path(last_frame_path).name}")
                last_url = upload_file(Path(last_frame_path), on_progress=progress)

        elif mode == "bridge":
            fp = Path(first_frame_path) if first_frame_path else None
            lp = Path(last_frame_path) if last_frame_path else None
            if not fp or not fp.is_file() or not lp or not lp.is_file():
                return VisionResult(
                    ok=False,
                    model_key=spec.key,
                    endpoint=spec.endpoint,
                    status="Bridge needs both start and end stills.",
                    cost_label=format_vision_cost(spec, duration_token=duration),
                )
            progress(f"Uploading start frame: {fp.name}")
            first_url = upload_file(fp, on_progress=progress)
            progress(f"Uploading end frame: {lp.name}")
            last_url = upload_file(lp, on_progress=progress)

        # Reference pack for reference-to-video / omni / video context
        if mode not in ("image_to_image", "text_to_image") or is_omni:
            # Still refs (omni + Veo reference pack + subject library)
            if mode != "image_to_image":
                cap_img = max(1, int(spec.max_refs or 8)) if (
                    is_omni or int(spec.max_refs or 0) > 0
                ) else 8
                for rp in ref_paths or []:
                    try:
                        p = Path(rp)
                        if not p.is_file():
                            continue
                        progress(f"Uploading ref still: {p.name}")
                        ref_urls.append(upload_file(p, on_progress=progress))
                    except Exception as exc:
                        progress(f"Skip ref still {rp}: {exc}")
                    if len(ref_urls) >= cap_img:
                        break

            # Omni motion + audio plates (MiniMax H3)
            if is_omni or getattr(spec, "max_ref_videos", 0):
                cap_v = max(0, int(getattr(spec, "max_ref_videos", 0) or 0)) or 3
                for rp in ref_video_paths or []:
                    try:
                        p = Path(rp)
                        if not p.is_file():
                            continue
                        progress(f"Uploading ref video: {p.name}")
                        ref_video_urls.append(upload_file(p, on_progress=progress))
                    except Exception as exc:
                        progress(f"Skip ref video {rp}: {exc}")
                    if len(ref_video_urls) >= cap_v:
                        break
            if is_omni or getattr(spec, "max_ref_audios", 0):
                cap_a = max(0, int(getattr(spec, "max_ref_audios", 0) or 0)) or 3
                for rp in ref_audio_paths or []:
                    try:
                        p = Path(rp)
                        if not p.is_file():
                            continue
                        progress(f"Uploading ref audio: {p.name}")
                        ref_audio_urls.append(upload_file(p, on_progress=progress))
                    except Exception as exc:
                        progress(f"Skip ref audio {rp}: {exc}")
                    if len(ref_audio_urls) >= cap_a:
                        break

    except (FalClientError, Exception) as exc:
        return VisionResult(
            ok=False,
            model_key=spec.key,
            endpoint=spec.endpoint,
            status=friendly_error(exc, context="Creative Vision upload"),
            cost_label=est_lbl,
        )

    try:
        if mode == "image_to_image":
            from media_studio.fal.models import (
                build_edit_arguments,
                resolve_image_edit_model,
            )

            edit_key = (spec.edit_model_key or "").strip() or None
            edit_spec = resolve_image_edit_model(edit_key) or resolve_image_edit_model(
                "flux 2 pro"
            )
            if edit_spec is None:
                return VisionResult(
                    ok=False,
                    model_key=spec.key,
                    endpoint=spec.endpoint,
                    status="No image-edit model resolved for Image→Image.",
                    cost_label=est_lbl,
                )
            # Prefer the real edit endpoint / key on the result
            spec_endpoint = edit_spec.endpoint
            spec_key = edit_spec.key
            # Build parameters for Studio-compatible edit path
            from media_studio.vision_registry import map_t2i_aspect_colon

            params: dict[str, Any] = {"num_images": 1}
            asp = (aspect_ratio or "").strip()
            # "Match source" / empty → leave aspect to build_edit_arguments (source image)
            if asp and "match" not in asp.lower():
                params["image_size"] = map_t2i_image_size(asp)
                params["aspect_ratio"] = map_t2i_aspect_colon(asp)
            else:
                params["aspect_ratio"] = "auto"
                params["image_size"] = "auto"
            if resolution and str(resolution).strip():
                params["resolution"] = str(resolution).strip()
            if strength is not None and spec.supports_strength:
                try:
                    params["strength"] = float(strength)
                except (TypeError, ValueError):
                    pass
            # Primary first, then refs (API multi-image order)
            edit_urls: list[str] = []
            if image_url:
                edit_urls.append(image_url)
            edit_urls.extend(u for u in ref_urls if u and u not in edit_urls)
            arguments, build_notes = build_edit_arguments(
                edit_spec,
                prompt=prompt,
                image_urls=edit_urls,
                parameters=params,
                source_image_path=source_still_path,
            )
            if len(ref_urls) > 0 and edit_spec.clamp_ref_images(len(edit_urls)) <= 1:
                build_notes.append(
                    "Model is single-image — extra reference stills ignored."
                )
            elif len(ref_urls) > 0:
                build_notes.append(
                    f"I2I multi-ref: primary + {min(len(ref_urls), max(0, edit_spec.max_ref_images - 1))} ref(s)."
                )
            # Keep endpoint aligned with resolved edit model
            endpoint_for_run = spec_endpoint
            model_key_for_result = spec_key
        else:
            arguments = build_vision_arguments(
                spec,
                prompt=prompt,
                image_url=image_url,
                first_frame_url=first_url,
                last_frame_url=last_url,
                ref_urls=ref_urls or None,
                ref_video_urls=ref_video_urls or None,
                ref_audio_urls=ref_audio_urls or None,
                source_video_url=source_video_url,
                duration=duration,
                aspect_ratio=aspect_ratio,
                resolution=resolution,
                negative_prompt=negative_prompt,
                generate_audio=generate_audio,
                num_images=want_n if mode == "text_to_image" else 1,
            )
            endpoint_for_run = spec.endpoint
            model_key_for_result = spec.key
            # FLUX 3 draft: switch endpoint + drop resolution (+ aspect on I2V draft)
            if draft and getattr(spec, "draft_endpoint", None):
                from media_studio.flux3_draft import (
                    estimate_draft_cost_usd,
                    strip_omitted_aspect,
                    strip_resolution_for_draft,
                )
                from media_studio.vision_registry import duration_seconds

                endpoint_for_run = str(spec.draft_endpoint)
                arguments = strip_resolution_for_draft(arguments)
                arguments = strip_omitted_aspect(
                    arguments, endpoint=endpoint_for_run
                )
                # Also strip if full endpoint omits (spec-level) even if draft URL differs
                arguments = strip_omitted_aspect(
                    arguments, endpoint=getattr(spec, "endpoint", None)
                )
                dur_s = duration_seconds(duration or spec.default_duration)
                draft_est = estimate_draft_cost_usd(spec, duration_s=dur_s)
                if draft_est is not None:
                    est_lbl = format_cost_label(draft_est, estimate=True) + " (draft)"
                progress(f"Draft mode · {endpoint_for_run}")
                progress(f"Draft cost · {est_lbl}")
            elif draft:
                progress("Draft not available for this model — full quality.")
            else:
                # Full quality: still hard-omit aspect for FLUX 3 I2V
                try:
                    from media_studio.flux3_draft import strip_omitted_aspect

                    arguments = strip_omitted_aspect(
                        arguments, endpoint=endpoint_for_run
                    )
                except Exception:
                    pass
    except ValueError as exc:
        return VisionResult(
            ok=False,
            model_key=spec.key,
            endpoint=spec.endpoint,
            status=str(exc),
            cost_label=est_lbl,
        )

    def _collect_image_urls(payload: Any) -> list[str]:
        urls = list(extract_image_urls(payload) or [])
        if urls:
            return urls
        if isinstance(payload, dict):
            img = payload.get("image")
            if isinstance(img, dict) and img.get("url"):
                return [str(img["url"])]
            if isinstance(img, str) and img.strip():
                return [img.strip()]
        return []

    # --- Run fal: T2I may sequential-batch when API is one-at-a-time ---
    progress("Running Creative Vision on fal…")
    t0 = time.perf_counter()
    all_image_urls: list[str] = []
    video_url: str | None = None
    cost_sum = 0.0
    cost_any_exact = False
    last_result: Any = None

    try:
        if mode == "text_to_image" and want_n > 1:
            api_max = max(1, int(getattr(spec, "max_num_images", 1) or 1))
            remaining = want_n
            batch_i = 0
            while remaining > 0:
                batch = min(remaining, api_max)
                batch_i += 1
                progress(
                    f"Variant batch {batch_i}: {batch} image(s) "
                    f"({want_n - remaining + 1}–{want_n - remaining + batch} of {want_n})…"
                )
                batch_args = build_vision_arguments(
                    spec,
                    prompt=prompt,
                    aspect_ratio=aspect_ratio,
                    resolution=resolution,
                    negative_prompt=negative_prompt,
                    num_images=batch,
                )
                last_result = subscribe(
                    endpoint_for_run, batch_args, on_progress=progress
                )
                got = _collect_image_urls(last_result)
                if not got:
                    # Sequential fallback: one-at-a-time for this batch
                    if batch > 1:
                        progress(
                            f"Batch returned no multi-output — sequential singles "
                            f"for remaining {remaining}…"
                        )
                        for _ in range(remaining):
                            one_args = build_vision_arguments(
                                spec,
                                prompt=prompt,
                                aspect_ratio=aspect_ratio,
                                resolution=resolution,
                                negative_prompt=negative_prompt,
                                num_images=1,
                            )
                            last_result = subscribe(
                                endpoint_for_run, one_args, on_progress=progress
                            )
                            one = _collect_image_urls(last_result)
                            if one:
                                all_image_urls.append(one[0])
                                exact = extract_cost_usd_from_response(last_result)
                                if exact is not None:
                                    cost_sum += exact
                                    cost_any_exact = True
                        remaining = 0
                        break
                    return VisionResult(
                        ok=False,
                        model_key=model_key_for_result,
                        endpoint=endpoint_for_run,
                        status=f"{spec.label}: fal returned no image.",
                        cost_label=est_lbl,
                    )
                all_image_urls.extend(got[:batch])
                exact = extract_cost_usd_from_response(last_result)
                if exact is not None:
                    cost_sum += exact
                    cost_any_exact = True
                remaining -= len(got[:batch])
                if len(got) < batch and remaining > 0:
                    # Model under-delivered; finish with singles
                    continue
        else:
            last_result = subscribe(
                endpoint_for_run, arguments, on_progress=progress
            )
            if is_still_mode(mode):
                all_image_urls = _collect_image_urls(last_result)
            else:
                video_url = extract_video_url(last_result)
            exact = extract_cost_usd_from_response(last_result)
            if exact is not None:
                cost_sum = exact
                cost_any_exact = True
    except FalClientError as exc:
        render_s = time.perf_counter() - t0
        return VisionResult(
            ok=False,
            model_key=model_key_for_result,
            endpoint=endpoint_for_run,
            status=str(exc),
            cost_label=est_lbl,
            metrics_line=format_render_metrics(render_s, None, cost_is_estimate=True),
        )
    except Exception as exc:
        render_s = time.perf_counter() - t0
        return VisionResult(
            ok=False,
            model_key=model_key_for_result,
            endpoint=endpoint_for_run,
            status=friendly_error(exc, context=spec.label),
            cost_label=est_lbl,
            metrics_line=format_render_metrics(render_s, None, cost_is_estimate=True),
        )
    render_s = time.perf_counter() - t0

    used_draft = bool(
        draft
        and getattr(spec, "draft_endpoint", None)
        and endpoint_for_run == str(getattr(spec, "draft_endpoint", "") or "")
    )
    draft_cache_url: str | None = None
    if used_draft and isinstance(last_result, dict):
        draft_cache_url = extract_draft_cache_url(last_result)

    if used_draft:
        from media_studio.flux3_draft import estimate_draft_cost_usd
        from media_studio.vision_registry import duration_seconds

        dur_s = duration_seconds(duration or spec.default_duration)
        draft_est = estimate_draft_cost_usd(spec, duration_s=dur_s)
        cost_usd = cost_sum if cost_any_exact else (draft_est if draft_est is not None else est)
        is_est = not cost_any_exact
        cost_lbl = format_cost_label(cost_usd, estimate=is_est) + " (draft)"
    else:
        cost_usd = cost_sum if cost_any_exact else est
        is_est = not cost_any_exact
        cost_lbl = format_cost_label(cost_usd, estimate=is_est)
    metrics = format_render_metrics(render_s, cost_usd, cost_is_estimate=is_est)

    still_job = is_still_mode(mode) or is_still_mode(spec.mode)
    if still_job:
        if not all_image_urls:
            return VisionResult(
                ok=False,
                model_key=model_key_for_result,
                endpoint=endpoint_for_run,
                status=f"{spec.label}: fal returned no image.",
                cost_label=cost_lbl,
                metrics_line=metrics,
            )
        if mode == "image_to_image":
            kind_tag = "creative-vision-i2i"
            scenario = "creative_vision_i2i"
        else:
            kind_tag = "creative-vision-t2i"
            scenario = "creative_vision_t2i"
        job_kind = "image"
    else:
        if not video_url:
            return VisionResult(
                ok=False,
                model_key=model_key_for_result,
                endpoint=endpoint_for_run,
                status=f"{spec.label}: fal returned no video.",
                cost_label=cost_lbl,
                metrics_line=metrics,
            )
        kind_tag = "creative-vision"
        job_kind = "creative_vision"
        scenario = "creative_vision"

    stamp = timestamp_now()
    media_dir = job_media_dir(output_dir, stamp=stamp)
    stem = make_output_stem(
        prompt or "vision",
        model_key_for_result or spec.key,
        stamp=stamp,
        kind=kind_tag,
    )

    saved: list[str] = []
    if still_job:
        for i, out_url in enumerate(all_image_urls, start=1):
            ext = ".jpg"
            low = out_url.lower().split("?")[0]
            if low.endswith(".png"):
                ext = ".png"
            elif low.endswith(".webp"):
                ext = ".webp"
            dest = unique_path(
                media_dir,
                stem,
                ext,
                index=i if len(all_image_urls) > 1 else None,
            )
            try:
                progress(f"Downloading {i}/{len(all_image_urls)}…")
                download_url(out_url, dest, on_progress=progress, timeout=900.0)
                saved.append(str(dest.resolve()))
            except FalClientError as exc:
                build_notes.append(f"Failed download {i}: {exc}")
        if not saved:
            return VisionResult(
                ok=False,
                model_key=model_key_for_result,
                endpoint=endpoint_for_run,
                status="Could not download any result images.",
                cost_label=cost_lbl,
                metrics_line=metrics,
                timestamp=stamp,
            )
    else:
        dest = unique_path(media_dir, stem, ".mp4")
        try:
            download_url(video_url, dest, on_progress=progress, timeout=900.0)
        except FalClientError as exc:
            return VisionResult(
                ok=False,
                model_key=model_key_for_result,
                endpoint=endpoint_for_run,
                status=str(exc),
                cost_label=cost_lbl,
                metrics_line=metrics,
                timestamp=stamp,
            )
        saved = [str(dest.resolve())]

    resolved = saved[0]
    n = len(saved)
    if mode == "image_to_image":
        send_hint = (
            "Send to Frame Editor · keyframe, or Start / End / I2V for motion."
        )
    elif still_job:
        send_hint = (
            f"Saved {n} still(s). Send each to Start / End frame or Studio Image."
            if n > 1
            else "Send to Start / End frame for a bridge, or Studio Image."
        )
    else:
        send_hint = "Use Show in folder or Send to Resolve."
    note_bits = [spec.notes] if spec.notes else [f"mode={mode}"]
    if build_notes:
        note_bits.extend(build_notes[:3])
    if n > 1:
        note_bits.append(f"batch={n}")
    if used_draft:
        note_bits.append("draft preview")
        if draft_cache_url:
            note_bits.append("draft_cache ready for Enhance to full")
        send_hint = "Draft ready — use Enhance to full for quality render."
    status = (
        f"{spec.label} OK. Saved {n} file(s) → {media_dir.name}/. "
        f"{metrics}. {send_hint}"
    )

    # Library: one entry per still so each has its own Send-to
    per_cost = None
    if n > 1 and cost_usd is not None:
        per_cost = cost_usd / n
    for i, path in enumerate(saved):
        try:
            entry_cost = (
                format_cost_label(per_cost, estimate=is_est)
                if per_cost is not None and n > 1
                else cost_lbl
            )
            ts_id = stamp if n == 1 else f"{stamp}_v{i + 1:02d}"
            notes_i = list(note_bits)
            if n > 1:
                notes_i = [f"variant {i + 1}/{n}"] + notes_i
            append_history(
                job_kind=job_kind,
                model=spec.label,
                prompt=prompt or "",
                files=[path],
                cost_estimate=entry_cost,
                notes=notes_i,
                output_dir=output_dir,
                timestamp=ts_id,
                scenario=scenario,
            )
        except Exception:
            pass

    return VisionResult(
        ok=True,
        path=resolved,
        paths=list(saved),
        model_key=model_key_for_result,
        endpoint=endpoint_for_run,
        status=status,
        notes=note_bits,
        cost_label=cost_lbl,
        metrics_line=metrics,
        timestamp=stamp,
        is_draft=used_draft,
        draft_cache_url=draft_cache_url,
    )
