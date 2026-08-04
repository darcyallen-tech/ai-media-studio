"""Run Director multi-shot jobs via fal."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from media_studio.director_registry import (
    DirectorModelSpec,
    DirectorPolish,
    DirectorShot,
    build_director_arguments,
    collect_director_image_plan,
    default_director_model,
    director_accepted_aspects_label,
    find_director_model,
    still_is_low_res,
    strip_director_internal_args,
    validate_shots,
    write_shot_list_sidecar,
)
from media_studio.errors import friendly_error
from media_studio.fal.client import FalClientError, download_url, extract_video_url, subscribe, upload_file
from media_studio.history import append_history
from media_studio.motion_sync_prep import (
    API_STILL_PROXY_NOTE,
    MAX_API_STILL_BYTES,
    MAX_API_STILL_SIDE,
    prepare_api_still,
)
from media_studio.naming import job_media_dir, make_output_stem, timestamp_now, unique_path
from media_studio.pricing import (
    extract_cost_usd_from_response,
    format_cost_label,
    format_render_metrics,
)

ProgressCallback = Callable[[str], None]


def _enrich_director_aspect_error(
    message: str,
    *,
    sent_aspect: Any,
    accepted: str,
    endpoint: str,
    ui_aspect: str | None,
) -> str:
    """Append sent vs accepted aspect detail when the API rejects aspect_ratio."""
    low = (message or "").lower()
    if "aspect" not in low and "aspect_ratio" not in low:
        return message
    sent_disp = "omitted" if sent_aspect is None else repr(sent_aspect)
    ui_disp = repr(ui_aspect) if ui_aspect else "—"
    extra = (
        f" Sent aspect_ratio={sent_disp} (UI={ui_disp}); "
        f"this endpoint accepts: {accepted}. "
        f"Endpoint: {endpoint}."
    )
    if extra.strip() in (message or ""):
        return message
    return f"{message.rstrip()}{extra}"


@dataclass
class DirectorResult:
    ok: bool
    path: str | None = None
    status: str = ""
    model_key: str = ""
    endpoint: str = ""
    notes: list[str] = field(default_factory=list)
    cost_label: str = ""
    metrics_line: str = ""
    timestamp: str = ""


def run_director(
    *,
    master: str,
    shots: list[DirectorShot],
    model_label: str | None = None,
    duration_s: float = 10.0,
    aspect_ratio: str | None = "16:9",
    style_pack: str | None = "None",
    generate_audio: bool | None = None,
    negative_prompt: str | None = None,
    polish: DirectorPolish | None = None,
    output_dir: str | Path,
    on_progress: ProgressCallback | None = None,
    angle_mode: str | None = None,
) -> DirectorResult:
    """
    Generate one multi-shot video from ordered Director shots.

    Validates times, uploads optional first-ref still for I2V multi-shot,
    posts multi_prompt to Kling V3/O3 endpoints.
    When polish.output_mode is clip pack, also writes a shot-list .txt sidecar
    (API still returns a single multi-shot clip).
    """
    spec = find_director_model(model_label) or default_director_model()

    def progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    errs = validate_shots(
        shots,
        total_duration_s=float(duration_s),
        max_shots=spec.max_shots,
        allow_overlap=False,
        polish=polish,
    )
    if errs:
        return DirectorResult(
            ok=False,
            model_key=spec.key,
            endpoint=spec.endpoint,
            status=" · ".join(errs),
        )

    notes: list[str] = []
    start_url: str | None = None
    ref_urls: list[str] = []
    elements: list[dict[str, Any]] | None = None
    is_grok = (getattr(spec, "engine", None) or "") == "grok_imagine"
    # Kling: always attach full identity pack as element extras (budget still 1/char).
    # Imagine: respect Front only / Full pack toggle.
    plan = collect_director_image_plan(
        shots,
        angle_mode=angle_mode if is_grok else "full_pack",
    )
    if is_grok and plan.get("angle_mode"):
        notes.append(f"Angle mode: {plan['angle_mode']}")

    # Low-res character warning (non-blocking)
    for sh in shots:
        if sh.has_character_bind() and still_is_low_res(sh.character_path):
            notes.append(
                f"Low-res character still ({Path(sh.character_path or '').name}) — "
                "prefer 1K–2K Front for identity lock."
            )

    # Cache prepared still paths (original → proxy or original)
    _prep_cache: dict[str, str] = {}
    _proxy_count = 0

    def _prepare_still(path: str, label: str) -> str:
        """Auto-downscale oversized character/scene stills for Kling/Grok image refs."""
        nonlocal _proxy_count
        key = str(Path(path).resolve()) if path else path
        if key in _prep_cache:
            return _prep_cache[key]
        try:
            prep = prepare_api_still(
                path,
                output_dir=output_dir,
                max_side=MAX_API_STILL_SIDE,
                max_bytes=MAX_API_STILL_BYTES,
                on_progress=progress,
                label=label,
            )
            out = str(prep.path)
            _prep_cache[key] = out
            if prep.used_proxy:
                _proxy_count += 1
                for n in prep.notes or []:
                    if n not in notes:
                        notes.append(n)
            return out
        except Exception as exc:
            notes.append(f"still prep skipped ({label}): {exc}")
            _prep_cache[key] = path
            return path

    def _upload(path: str, label: str) -> str | None:
        try:
            local = _prepare_still(path, label)
            progress(f"Uploading {label}: {Path(local).name}")
            return upload_file(Path(local), on_progress=progress)
        except Exception as exc:
            # Image-aware friendly copy (never “Render-in-Place” for stills)
            msg = friendly_error(exc, context="Director", media_kind="image")
            notes.append(f"Skip {label} upload: {msg}")
            return None

    supports_scene_img = bool(getattr(spec, "supports_scene_image_ref", False))

    if is_grok:
        # Per-shot order: character then location plate (real multi-ref / R2V)
        cap = max(1, int(spec.max_shots or 7))
        upload_list: list[str] = []
        for pair in plan.get("per_shot_pairs") or []:
            for p in pair:
                if p and p not in upload_list:
                    upload_list.append(p)
        for p in plan.get("all_ref_paths") or []:
            if p not in upload_list:
                upload_list.append(p)
        for p in upload_list:
            if len(ref_urls) >= cap:
                break
            url = _upload(p, "ref")
            if url:
                ref_urls.append(url)
                notes.append(f"Ref {len(ref_urls)}: {Path(p).name}")
        if plan.get("character_labels"):
            notes.append(
                "Characters: " + ", ".join(dict.fromkeys(plan["character_labels"]))
            )
        if plan.get("scene_labels"):
            notes.append(
                "Scenes: " + ", ".join(dict.fromkeys(plan["scene_labels"]))
            )
        if not ref_urls and (
            any(sh.has_character_bind() for sh in shots)
            or any(sh.has_scene_bind() for sh in shots)
        ):
            return DirectorResult(
                ok=False,
                model_key=spec.key,
                endpoint=spec.endpoint,
                status=(
                    "Character/Scene selected but still could not be uploaded. "
                    "Check the still file and retry."
                ),
                notes=notes,
            )
    else:
        # Kling multi-shot
        chars = list(plan.get("characters") or [])
        scene_path = plan.get("scene_start") if supports_scene_img else None
        # O3: still collect scene for notes, but do not upload as second image
        scene_path_prompt_only = None
        if not supports_scene_img and plan.get("scene_start"):
            scene_path_prompt_only = plan.get("scene_start")
        scene_url: str | None = None
        path_to_url: dict[str, str] = {}

        for ch in chars:
            p = ch.get("path")
            if not p:
                continue
            u = _upload(p, f"character {ch.get('label') or Path(p).name}")
            if u:
                path_to_url[p] = u
                notes.append(
                    f"Character: {ch.get('label') or Path(p).name}"
                )
            for ex in ch.get("extras") or []:
                if ex in path_to_url:
                    continue
                eu = _upload(ex, "character angle")
                if eu:
                    path_to_url[ex] = eu

        if scene_path:
            scene_url = _upload(scene_path, "scene ref")
            if scene_url:
                notes.append(f"Scene still: {Path(scene_path).name}")
        elif scene_path_prompt_only:
            notes.append(
                f"Scene “{Path(str(scene_path_prompt_only)).name}” in prompt only "
                f"(this model is single image-ref)."
            )

        char_url = None
        primary = plan.get("character_primary")
        if primary and primary in path_to_url:
            char_url = path_to_url[primary]
        elif path_to_url:
            char_url = next(iter(path_to_url.values()))

        # Fallback: first generic ref_path if no character/scene plan
        if not char_url and not scene_url:
            for sh in shots:
                if sh.ref_path and Path(sh.ref_path).is_file():
                    scene_url = _upload(sh.ref_path, "shot ref")
                    if scene_url:
                        notes.append(f"Start frame: {Path(sh.ref_path).name}")
                        break

        if getattr(spec, "supports_kling_elements", False) and path_to_url:
            # V3 I2V: character elements + scene as start (dual image bind)
            elements = []
            for ch in chars:
                p = ch.get("path")
                frontal = path_to_url.get(p) if p else None
                if not frontal:
                    continue
                el: dict[str, Any] = {"frontal_image_url": frontal}
                refs = [
                    path_to_url[ex]
                    for ex in (ch.get("extras") or [])
                    if ex in path_to_url
                ][:4]
                # When multi-scene, attach first scene as element ref too
                if scene_url and scene_url not in refs and scene_url != frontal:
                    refs.append(scene_url)
                if refs:
                    el["reference_image_urls"] = refs[:4]
                elements.append(el)
            if not elements and char_url:
                elements = [{"frontal_image_url": char_url}]
            # Prefer scene as start frame (location plate); else character
            start_url = scene_url or char_url
            notes.append(
                f"Kling elements: {len(elements or [])} character(s)"
                + (" + scene start" if scene_url else "")
            )
        elif char_url:
            # O3 (no elements): first character is I2V start; scene text-only
            start_url = char_url
            n_chars = len(chars)
            if n_chars > 1:
                notes.append(
                    f"O3 I2V: {n_chars} characters bound in prompts; "
                    "single image_url uses first character still."
                )
            if plan.get("scene_labels"):
                notes.append(
                    "Scene bound in prompt only — O3 I2V has a single image_url."
                )
        else:
            start_url = scene_url

        if any(sh.has_character_bind() for sh in shots) and not char_url:
            return DirectorResult(
                ok=False,
                model_key=spec.key,
                endpoint=spec.endpoint,
                status=(
                    "Character selected but still could not be uploaded as an image ref. "
                    "Check the still file and retry."
                ),
                notes=notes,
            )
        if (
            any(sh.has_scene_bind() for sh in shots)
            and supports_scene_img
            and not scene_url
            and not char_url
        ):
            return DirectorResult(
                ok=False,
                model_key=spec.key,
                endpoint=spec.endpoint,
                status=(
                    "Scene selected but still could not be uploaded as an image ref. "
                    "Check the Scenes still file and retry."
                ),
                notes=notes,
            )

    if _proxy_count > 0:
        note = API_STILL_PROXY_NOTE
        if note not in notes:
            notes.append(note)
        progress(note)

    try:
        endpoint, arguments = build_director_arguments(
            spec,
            master=master or "",
            shots=shots,
            duration_s=duration_s,
            aspect_ratio=aspect_ratio,
            style_pack=style_pack,
            generate_audio=generate_audio,
            start_image_url=start_url,
            negative_prompt=negative_prompt,
            polish=polish,
            ref_image_urls=ref_urls or None,
            elements=elements,
        )
    except ValueError as exc:
        return DirectorResult(
            ok=False,
            model_key=spec.key,
            endpoint=spec.endpoint,
            status=str(exc),
            notes=notes,
        )

    aspect_note = str(arguments.pop("_aspect_note", "") or "")
    if aspect_note:
        notes.append(aspect_note)
    mp_max = arguments.pop("_multi_prompt_max_chars", None)
    multi = arguments.get("multi_prompt") or []
    if isinstance(multi, list) and multi:
        counts = [len((m or {}).get("prompt") or "") for m in multi if isinstance(m, dict)]
        if counts:
            mx = max(counts)
            notes.append(
                f"multi_prompt chars: {counts}"
                + (f" (max {mp_max})" if mp_max else "")
            )
            progress(
                f"multi_prompt lengths: {counts}"
                + (f" · limit {mp_max}/shot" if mp_max else "")
            )
            if mp_max and mx > int(mp_max):
                return DirectorResult(
                    ok=False,
                    model_key=spec.key,
                    endpoint=endpoint,
                    status=(
                        f"Prompt still over limit after compact — max shot is {mx} chars "
                        f"(limit {mp_max}). Shorten master brief or shot actions."
                    ),
                    notes=notes,
                )
    api_args = strip_director_internal_args(arguments)
    sent_aspect = api_args.get("aspect_ratio")
    has_start = bool(start_url) or bool(
        api_args.get("image_url") or api_args.get("start_image_url")
    )
    accepted = director_accepted_aspects_label(spec, has_start_image=has_start)

    kind = (
        f"Grok Imagine · {len(ref_urls)} ref(s)"
        if is_grok
        else f"multi-shot × {len(shots)}"
    )
    progress(f"{spec.label} · {kind}")
    progress(f"Endpoint: {endpoint}")
    if sent_aspect is not None:
        progress(f"aspect_ratio={sent_aspect!r} (accepts: {accepted})")
    else:
        progress(f"aspect_ratio omitted (accepts: {accepted})")
    progress("Running Director on fal…")

    t0 = time.perf_counter()
    try:
        result = subscribe(endpoint, api_args, on_progress=progress)
    except FalClientError as exc:
        render_s = time.perf_counter() - t0
        # Director refs are stills — never suggest video Render-in-Place
        status = _enrich_director_aspect_error(
            friendly_error(exc, context="Director", media_kind="image"),
            sent_aspect=sent_aspect,
            accepted=accepted,
            endpoint=endpoint,
            ui_aspect=aspect_ratio,
        )
        return DirectorResult(
            ok=False,
            model_key=spec.key,
            endpoint=endpoint,
            status=status,
            notes=notes,
            metrics_line=format_render_metrics(render_s, None, cost_is_estimate=True),
        )
    except Exception as exc:
        render_s = time.perf_counter() - t0
        status = _enrich_director_aspect_error(
            friendly_error(exc, context="Director", media_kind="image"),
            sent_aspect=sent_aspect,
            accepted=accepted,
            endpoint=endpoint,
            ui_aspect=aspect_ratio,
        )
        return DirectorResult(
            ok=False,
            model_key=spec.key,
            endpoint=endpoint,
            status=status,
            notes=notes,
            metrics_line=format_render_metrics(render_s, None, cost_is_estimate=True),
        )
    render_s = time.perf_counter() - t0

    from media_studio.director_registry import estimate_director_cost

    est = estimate_director_cost(
        spec,
        duration_s=float(duration_s),
        generate_audio=bool(
            generate_audio
            if generate_audio is not None
            else spec.default_generate_audio
        ),
    )
    exact = extract_cost_usd_from_response(result)
    cost_usd = exact if exact is not None else est
    is_est = exact is None
    metrics = format_render_metrics(render_s, cost_usd, cost_is_estimate=is_est)
    cost_lbl = format_cost_label(cost_usd, estimate=is_est)

    out_url = extract_video_url(result)
    if not out_url:
        return DirectorResult(
            ok=False,
            model_key=spec.key,
            endpoint=endpoint,
            status="Director: fal returned no video.",
            notes=notes,
            cost_label=cost_lbl,
            metrics_line=metrics,
        )

    stamp = timestamp_now()
    media_dir = job_media_dir(output_dir, stamp=stamp)
    stem = make_output_stem(
        (master or "director")[:80],
        spec.key,
        stamp=stamp,
        kind="director",
    )
    dest = unique_path(media_dir, stem, ".mp4")
    try:
        download_url(out_url, dest, on_progress=progress, timeout=900.0)
    except FalClientError as exc:
        return DirectorResult(
            ok=False,
            model_key=spec.key,
            endpoint=endpoint,
            status=str(exc),
            notes=notes,
            cost_label=cost_lbl,
            metrics_line=metrics,
        )

    resolved = str(dest.resolve())
    hist_files = [resolved]
    # Clip pack mode: API still returns one multi-shot clip; always write shot list
    # sidecar so Resolve / offline edit has the ordered breakdown.
    if polish is not None and polish.wants_shot_list_sidecar():
        side = write_shot_list_sidecar(
            resolved,
            master=master or "",
            shots=shots,
            model_label=spec.label,
            duration_s=float(duration_s),
            aspect_ratio=aspect_ratio,
            polish=polish,
        )
        if side:
            notes.append(f"Shot list: {Path(side).name}")
            hist_files.append(side)
            progress(f"Wrote shot list {Path(side).name}")
        else:
            notes.append("Shot list sidecar failed to write")
    status = (
        f"{spec.label} OK · {len(shots)} shot(s). "
        f"Saved {Path(resolved).name}. {metrics}."
    )
    if _proxy_count > 0:
        status = f"{status} · {API_STILL_PROXY_NOTE}."
    try:
        append_history(
            job_kind="director",
            model=spec.label,
            prompt=(master or "")[:800],
            files=hist_files,
            cost_estimate=cost_lbl,
            notes=notes + [f"{len(shots)} shots"],
            output_dir=output_dir,
            timestamp=stamp,
            scenario="director",
        )
    except Exception:
        pass

    return DirectorResult(
        ok=True,
        path=resolved,
        status=status,
        model_key=spec.key,
        endpoint=endpoint,
        notes=notes,
        cost_label=cost_lbl,
        metrics_line=metrics,
        timestamp=stamp,
    )
