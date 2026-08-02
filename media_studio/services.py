"""
AI services: prompt enhancement (Grok) and generation placeholders.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from media_studio.config import (
    ENHANCE_SYSTEM_PROMPT_PATH,
    XAI_DEFAULT_MODEL,
    ensure_output_dir,
    format_model_catalog_for_prompt,
    model_id_from_choice,
    model_label_for,
)
from media_studio.media import (
    describe_upload,
    media_context_for_enhance,
    safe_path_str,
)
from media_studio.errors import friendly_error
from media_studio.history import append_history
from media_studio.params_ui import clamp_parameters_to_model, is_auto_model
from media_studio.prompt_history import append_prompt
from media_studio.xai_client import XAIConfigError, chat_json, chat_json_vision


@dataclass
class EnhanceResult:
    """Structured result from Enhance Prompt (Grok)."""

    optimized_prompt: str
    chosen_model: str
    parameters: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    status: str = ""
    raw_response: str | None = None
    ok: bool = True
    original_prompt: str = ""
    model_locked: bool = False

    @property
    def chosen_model_label(self) -> str:
        return model_label_for(self.chosen_model) if self.chosen_model else "Auto (default)"

    @property
    def parameters_json(self) -> str:
        return json.dumps(self.parameters or {}, indent=2, ensure_ascii=False)

    @property
    def notes_text(self) -> str:
        if not self.notes:
            return ""
        return "\n".join(f"• {n}" for n in self.notes)


def load_enhance_system_prompt() -> str:
    """Load the editable enhance system prompt and inject the model catalog."""
    path = ENHANCE_SYSTEM_PROMPT_PATH
    if not path.is_file():
        raise FileNotFoundError(f"Enhance system prompt not found: {path}")
    template = path.read_text(encoding="utf-8")
    catalog = format_model_catalog_for_prompt()
    return template.replace("{model_catalog}", catalog)


def _build_enhance_user_message(
    *,
    prompt: str,
    model_preference: str,
    model_locked: bool,
    resolved_model_id: str,
    image_file: str | None,
    video_file: str | None,
    scenario: str | None = None,
    has_vision: bool = False,
    extra_context: dict[str, Any] | None = None,
    extra_image_files: list[str] | None = None,
) -> str:
    media = media_context_for_enhance(image_file, video_file)
    ref_names: list[str] = []
    for p in extra_image_files or []:
        sp = safe_path_str(p)
        if sp and Path(sp).is_file():
            ref_names.append(Path(sp).name)
    if ref_names:
        media["extra_reference_stills"] = ref_names
        media["extra_reference_count"] = len(ref_names)
    # Resolve scenario rules for architecture lock / allowed changes
    scenario_label = scenario
    scenario_rules = None
    scenario_key = None
    try:
        from media_studio.scenarios import get_scenario

        sc = get_scenario(scenario)
        if sc:
            scenario_label = sc.label
            scenario_key = sc.key
            scenario_rules = sc.notes or sc.description
    except Exception:
        pass

    if model_locked:
        instructions = (
            "Optimize the raw_prompt for the LOCKED model only. "
            f"chosen_model MUST be exactly '{resolved_model_id}'. "
            "Do not switch models. Clamp parameters to that model's limits and list clamps in notes. "
            "Return JSON only per the system schema."
        )
    else:
        instructions = (
            "Optimize the raw_prompt for the best target model (auto). "
            "Recommend a model id from the catalog. "
            "Return JSON only per the system schema."
        )
    if has_vision:
        instructions += (
            " A source still is attached — use vision: layout, main objects, empty surfaces, "
            "lighting, camera feel; ground every placement in the optimized_prompt. "
            "Fill scene_brief with one short line of what you see."
        )
    if ref_names:
        instructions += (
            f" Additional reference still(s) are attached ({len(ref_names)}): "
            f"{', '.join(ref_names)}. Treat the first image as the primary edit target; "
            "use extra refs for style, materials, furniture product, or look reference "
            "when the user/prompt implies it (multi-ref edit models)."
        )
    if scenario_key and scenario_key != "blank_canvas":
        instructions += (
            f" Active scenario is {scenario_label!r} — only allowed changes for that workflow; "
            "preserve architecture/windows/camera unless the scenario allows otherwise."
        )
    extra = dict(extra_context or {})
    if extra.get("mode") == "region_edit":
        instructions += (
            " REGION EDIT mode: produce a color-keyed optimized_prompt from the boxes; "
            "append remove-markings / outside-locked language."
        )
    payload = {
        "raw_prompt": prompt,
        "model_preference": preference_label(model_preference),
        "model_preference_resolved": resolved_model_id or "auto",
        "model_locked": model_locked,
        "scenario": scenario_label,
        "scenario_key": scenario_key,
        "scenario_rules": scenario_rules,
        "media": media,
        "has_vision_image": has_vision,
        "instructions": instructions,
        **extra,
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def preference_label(model_preference: str | None) -> str:
    return (model_preference or "auto").strip() or "auto"


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _parse_enhance_json(text: str) -> dict[str, Any]:
    cleaned = _strip_code_fences(text)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        # Try to salvage the first JSON object in the response
        match = re.search(r"\{[\s\S]*\}", cleaned)
        if not match:
            raise
        data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("Enhance response JSON must be an object.")
    return data


def _normalize_enhance_payload(data: dict[str, Any], fallback_prompt: str) -> EnhanceResult:
    optimized = str(data.get("optimized_prompt") or fallback_prompt).strip()
    chosen = str(data.get("chosen_model") or "").strip()
    params = data.get("parameters") or {}
    if not isinstance(params, dict):
        params = {"value": params}

    notes_raw = data.get("notes") or []
    if isinstance(notes_raw, str):
        notes = [notes_raw] if notes_raw.strip() else []
    elif isinstance(notes_raw, list):
        notes = [str(n).strip() for n in notes_raw if str(n).strip()]
    else:
        notes = [str(notes_raw)]

    return EnhanceResult(
        optimized_prompt=optimized,
        chosen_model=chosen,
        parameters=params,
        notes=notes,
        ok=True,
    )


def enhance_prompt(
    prompt: str,
    model_choice: str | None = None,
    image_file: str | None = None,
    video_file: str | None = None,
    parameters: dict[str, Any] | None = None,
    output_dir: str | Path | None = None,
    scenario: str | None = None,
    extra_context: dict[str, Any] | None = None,
    extra_image_files: list[str] | None = None,
) -> EnhanceResult:
    """
    Call Grok 4.5 to optimize the user prompt for the target generation model.

    When a source still is present, uses **vision** so the rewrite is spatially
    grounded. Optional extra reference stills (multi-ref models) are mentioned
    and attached to vision when available. When the user has a non-Auto model
    selected, that model is locked. Does **not** change the caller's model
    dropdown — only returns text.
    """
    original = (prompt or "").strip()
    image_file = safe_path_str(image_file)
    video_file = safe_path_str(video_file)
    extra_refs: list[str] = []
    for p in extra_image_files or []:
        sp = safe_path_str(p)
        if sp and Path(sp).is_file() and sp not in extra_refs:
            if image_file and Path(sp).resolve() == Path(image_file).resolve():
                continue
            extra_refs.append(sp)
    preference = model_choice or ""
    locked = not is_auto_model(preference)
    resolved_id = model_id_from_choice(preference) if locked else ""
    extra = dict(extra_context or {})

    # Vision still: prefer image; for video-only jobs try a poster frame
    vision_path: str | None = None
    if image_file and Path(image_file).is_file():
        vision_path = image_file
    elif video_file and Path(video_file).is_file():
        try:
            from media_studio.media import video_poster_path

            vision_path = video_poster_path(video_file)
        except Exception:
            vision_path = None
    has_vision = bool(vision_path and Path(vision_path).is_file())

    # Empty prompt is OK when region boxes or vision-only build is requested
    region_boxes = extra.get("boxes") if isinstance(extra.get("boxes"), list) else None
    if not original and not region_boxes:
        return EnhanceResult(
            optimized_prompt="",
            chosen_model="",
            status="Enhance Prompt: enter a prompt first (or add region box prompts).",
            ok=False,
            original_prompt="",
            model_locked=locked,
        )
    if not original and region_boxes:
        # Seed a raw_prompt from box texts so Grok has material
        from media_studio.region_edit import build_region_prompt, RegionBox

        try:
            tmp_boxes = []
            for b in region_boxes:
                if not isinstance(b, dict):
                    continue
                tmp_boxes.append(
                    RegionBox(
                        id=str(b.get("color") or "box"),
                        color_name=str(b.get("color") or "red"),
                        color_hex="#E53935",
                        prompt=str(b.get("prompt") or ""),
                    )
                )
            original = build_region_prompt(tmp_boxes) or "Region edit on the marked boxes."
        except Exception:
            original = "Region edit on the marked boxes."

    try:
        system = load_enhance_system_prompt()
        user_msg = _build_enhance_user_message(
            prompt=original,
            model_preference=preference,
            model_locked=locked,
            resolved_model_id=resolved_id or "auto",
            image_file=image_file,
            video_file=video_file,
            scenario=scenario,
            has_vision=has_vision,
            extra_context=extra,
            extra_image_files=extra_refs,
        )
        if has_vision:
            vision_paths: list[str] = [vision_path]  # type: ignore[list-item]
            for rp in extra_refs:
                if rp not in vision_paths:
                    vision_paths.append(rp)
            raw = chat_json_vision(
                system=system,
                user_text=user_msg,
                image_paths=vision_paths[:3],  # xAI vision cap in client
                model=XAI_DEFAULT_MODEL,
            )
        else:
            raw = chat_json(system=system, user=user_msg, model=XAI_DEFAULT_MODEL)
        data = _parse_enhance_json(raw)
        result = _normalize_enhance_payload(data, fallback_prompt=original)
        result.raw_response = raw
        result.original_prompt = original
        result.model_locked = locked
        scene_brief = str(data.get("scene_brief") or "").strip()
        if scene_brief and scene_brief not in result.notes:
            result.notes.insert(0, f"Scene: {scene_brief}")

        # Merge UI parameters with Grok's extracted params (Grok wins on keys it set)
        merged = dict(parameters or {})
        merged.update(result.parameters or {})

        if locked and resolved_id:
            # Force keep user model
            if result.chosen_model and model_id_from_choice(result.chosen_model) not in (
                resolved_id,
                "",
            ):
                result.notes.insert(
                    0,
                    f"Kept your selected model ({model_label_for(resolved_id)}); "
                    f"ignored suggested switch to {result.chosen_model!r}.",
                )
            result.chosen_model = resolved_id
            clamp_choice = resolved_id
        else:
            clamp_choice = result.chosen_model or preference
            if not result.chosen_model:
                result.chosen_model = model_id_from_choice(preference) or ""

        clamped, clamp_notes = clamp_parameters_to_model(
            clamp_choice,
            merged,
            locked_model_key=resolved_id if locked else None,
        )
        result.parameters = clamped
        for n in clamp_notes:
            if n not in result.notes:
                result.notes.append(n)

        # Persist prompt history
        try:
            append_prompt(
                original_prompt=original,
                enhanced_prompt=result.optimized_prompt,
                model=result.chosen_model_label,
                output_dir=output_dir,
            )
        except OSError:
            pass

        model_note = result.chosen_model_label
        parts = [
            f"Enhance Prompt: Grok ({XAI_DEFAULT_MODEL}) OK"
            + (" · vision" if has_vision else "")
            + ".",
            f"Model: {model_note}" + (" (locked)" if locked else " (auto/recommended)") + ".",
            describe_upload(image_file, "image"),
            describe_upload(video_file, "video"),
        ]
        if clamp_notes:
            parts.append("Adjusted: " + "; ".join(clamp_notes) + ".")
        if result.notes:
            # Avoid duplicating clamp notes twice in status
            extra = [n for n in result.notes if n not in clamp_notes]
            if extra:
                parts.append("Notes: " + "; ".join(extra[:4]))
        result.status = " ".join(parts)
        return result

    except XAIConfigError as exc:
        return EnhanceResult(
            optimized_prompt=original,
            chosen_model=resolved_id if locked else model_id_from_choice(preference),
            status=friendly_error(exc, context="Enhance Prompt"),
            ok=False,
            original_prompt=original,
            model_locked=locked,
        )
    except Exception as exc:
        return EnhanceResult(
            optimized_prompt=original,
            chosen_model=resolved_id if locked else model_id_from_choice(preference),
            status=friendly_error(exc, context="Enhance Prompt"),
            ok=False,
            original_prompt=original,
            model_locked=locked,
        )


@dataclass
class GenerateResult:
    """Result of a Generate click (image or video)."""

    ok: bool
    image_paths: list[str] = field(default_factory=list)
    video_path: str | None = None
    status: str = ""
    model: str = ""
    job_kind: str = "image"  # "image" | "video"
    cost_estimate: str = ""
    notes: list[str] = field(default_factory=list)
    render_seconds: float | None = None
    metrics_line: str = ""  # e.g. "Rendered in 7.3s · Cost: $0.041"

    @property
    def primary_image(self) -> str | None:
        return self.image_paths[0] if self.image_paths else None


def _parse_parameters_json(parameters_json: str | None) -> dict[str, Any]:
    if not parameters_json or not str(parameters_json).strip():
        return {}
    try:
        data = json.loads(parameters_json)
        return data if isinstance(data, dict) else {"value": data}
    except json.JSONDecodeError:
        return {"_raw": parameters_json, "_parse_error": True}


def _resolve_edit_image(
    image_file: str | None,
    video_file: str | None,
) -> str | None:
    """Prefer uploaded still; fall back to first frame of video."""
    from media_studio.media import resolve_still_preview

    if image_file and Path(image_file).is_file():
        return image_file
    preview = resolve_still_preview(None, video_file)
    return preview


def describe_job_kind(
    model_choice: str | None,
    image_file: str | None,
    video_file: str | None,
) -> str:
    """Human-readable job type for the UI."""
    from media_studio.fal.models import (
        default_i2v_model,
        default_image_edit_model,
        default_video_edit_model,
        resolve_image_edit_model,
        resolve_job_kind,
        resolve_video_model,
    )

    img = safe_path_str(image_file)
    vid = safe_path_str(video_file)
    has_image = bool(img and Path(img).is_file())
    has_video = bool(vid and Path(vid).is_file())
    kind = resolve_job_kind(model_choice, has_image=has_image, has_video=has_video)

    if kind == "video":
        vspec = resolve_video_model(model_choice)
        if not vspec or vspec.task != "video_edit":
            vspec = default_video_edit_model()
        bits = [f"VIDEO EDIT → {vspec.label}"]
        if has_video:
            bits.append(f"clip: {Path(vid).name}")  # type: ignore[arg-type]
        else:
            bits.append("needs a video upload")
        if has_image:
            bits.append(f"ref still: {Path(img).name}")  # type: ignore[arg-type]
        return " · ".join(bits)

    if kind == "image_to_video":
        vspec = resolve_video_model(model_choice)
        if not vspec or vspec.task != "image_to_video":
            vspec = default_i2v_model()
        bits = [f"IMAGE→VIDEO → {vspec.label}"]
        if has_image:
            bits.append(f"start frame: {Path(img).name}")  # type: ignore[arg-type]
        else:
            bits.append("needs a still as start frame")
        return " · ".join(bits)

    ispec = resolve_image_edit_model(model_choice) or default_image_edit_model()
    bits = [f"IMAGE EDIT → {ispec.label}"]
    if has_image:
        bits.append(f"still: {Path(img).name}")  # type: ignore[arg-type]
    elif has_video:
        bits.append("still: first frame of video")
    else:
        bits.append("needs a still")
    return " · ".join(bits)


def _write_job_receipt(out: Path, body: dict[str, Any]) -> None:
    stamp = body.get("timestamp") or datetime.now().strftime("%Y%m%d_%H%M%S")
    receipt = out / f"job_{stamp}.json"
    try:
        receipt.write_text(
            json.dumps(body, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass


def generate(
    prompt: str,
    model_choice: str | None = None,
    image_file: str | None = None,
    video_file: str | None = None,
    output_dir: str | Path | None = None,
    parameters_json: str | None = None,
    on_progress: Any | None = None,
    scenario: str | None = None,
    extra_image_files: list[str] | None = None,
) -> GenerateResult:
    """
    Run generation / edit via fal.ai.

    Routes to **image edit** or **video-to-video** based on model choice and
    uploaded media (see `resolve_job_kind`).

    on_progress: optional callable(str) for status updates during the job.
    scenario: optional scenario key/label for output naming.
    extra_image_files: optional additional reference stills for multi-ref
    image models (primary remains ``image_file``).
    """
    from media_studio.fal.image_edit import run_image_edit
    from media_studio.fal.image_to_video import run_image_to_video
    from media_studio.fal.models import resolve_job_kind
    from media_studio.fal.video_edit import run_video_edit
    from media_studio.scenarios import get_scenario

    prompt = (prompt or "").strip()
    model = model_id_from_choice(model_choice)
    image_file = safe_path_str(image_file)
    video_file = safe_path_str(video_file)
    extra_refs: list[str] = []
    for p in extra_image_files or []:
        sp = safe_path_str(p)
        if not sp or not Path(sp).is_file():
            continue
        if image_file:
            try:
                if Path(sp).resolve() == Path(image_file).resolve():
                    continue
            except OSError:
                pass
        if sp not in extra_refs:
            extra_refs.append(sp)
    out = ensure_output_dir(Path(output_dir) if output_dir else None)
    params = _parse_parameters_json(parameters_json)
    # Defense-in-depth: clamp resolution/num_images/duration to the selected model
    params, clamp_notes = clamp_parameters_to_model(model_choice or model, params)
    sc = get_scenario(scenario)
    scenario_key = sc.key if sc else (scenario or None)

    def progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    for note in clamp_notes:
        progress(f"Params: {note}")

    has_image = bool(image_file and Path(image_file).is_file())
    has_video = bool(video_file and Path(video_file).is_file())
    kind = resolve_job_kind(
        model_choice or model,
        has_image=has_image,
        has_video=has_video,
    )
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # I2V can run with empty prompt on some models, but we still encourage one
    if kind != "image_to_video" and not prompt:
        return GenerateResult(ok=False, status="Generate: enter a prompt first.")

    # ---- IMAGE-TO-VIDEO ----
    if kind == "image_to_video":
        from media_studio.fal.models import resolve_video_model as _rvm

        vspec_i2v = _rvm(model_choice or model)
        is_omni = bool(
            vspec_i2v
            and getattr(vspec_i2v, "ref_image_field", None)
            and "reference-to-video" in (vspec_i2v.endpoint or "")
        )
        start = _resolve_edit_image(image_file, video_file if not is_omni else None)
        # H3 omni: source clip is a motion reference (Video 1), not V2V source
        ref_videos: list[str] = []
        if is_omni and has_video and video_file:
            ref_videos.append(video_file)
            progress(f"Omni motion ref (Video 1): {Path(video_file).name}")
        if not start and not (is_omni and ref_videos):
            return GenerateResult(
                ok=False,
                model=model,
                job_kind="image_to_video",
                status=(
                    "Generate (image-to-video): upload a still as the start frame."
                    if not is_omni
                    else "MiniMax H3 omni: add a reference still and/or motion clip."
                ),
            )
        progress(
            "Job type: IMAGE→VIDEO omni (fal)" if is_omni else "Job type: IMAGE→VIDEO (fal)"
        )
        result = run_image_to_video(
            prompt=prompt,
            image_path=start,
            model_choice=model_choice or model,
            parameters=params,
            output_dir=out,
            on_progress=progress,
            scenario=scenario_key,
            extra_image_paths=extra_refs or None,
            ref_video_paths=ref_videos or None,
        )
        stamp = result.timestamp or stamp
        _write_job_receipt(
            out,
            {
                "timestamp": stamp,
                "job_kind": "image_to_video",
                "prompt": prompt,
                "model": result.model_key or model or "auto",
                "endpoint": result.endpoint,
                "image_input": start,
                "parameters": params,
                "output_video": result.path,
                "ok": result.ok,
                "status": result.status,
                "notes": result.notes,
                "cost_estimate": result.cost_estimate,
                "render_seconds": result.render_seconds,
                "metrics_line": result.metrics_line,
                "scenario": scenario_key,
            },
        )
        if result.ok and result.path:
            append_history(
                job_kind="image_to_video",
                model=result.model_key or model or "auto",
                prompt=prompt,
                files=[result.path],
                cost_estimate=result.metrics_line or result.cost_estimate,
                notes=result.notes,
                output_dir=out,
                timestamp=stamp,
                scenario=scenario_key,
            )
        return GenerateResult(
            ok=result.ok,
            image_paths=[],
            video_path=result.path,
            status=result.status,
            model=result.model_key or model,
            job_kind="image_to_video",
            cost_estimate=result.cost_estimate,
            notes=list(result.notes),
            render_seconds=result.render_seconds,
            metrics_line=result.metrics_line,
        )

    # ---- VIDEO-TO-VIDEO EDIT ----
    if kind == "video":
        if not has_video:
            return GenerateResult(
                ok=False,
                model=model,
                job_kind="video",
                status=(
                    "Generate (video edit): upload a video clip first. "
                    "Optional still is used as a Kling @Image1 reference."
                ),
            )

        progress("Job type: VIDEO EDIT (fal video-to-video)")
        ref_paths: list[str | Path] = []
        if has_image:
            ref_paths.append(image_file)  # type: ignore[arg-type]
            progress(f"Using still as reference image: {Path(image_file).name}")  # type: ignore[arg-type]

        result = run_video_edit(
            prompt=prompt,
            video_path=video_file,  # type: ignore[arg-type]
            reference_image_paths=ref_paths,
            model_choice=model_choice or model,
            parameters=params,
            output_dir=out,
            on_progress=progress,
            scenario=scenario_key,
        )

        stamp = result.timestamp or stamp
        _write_job_receipt(
            out,
            {
                "timestamp": stamp,
                "job_kind": "video",
                "prompt": prompt,
                "model": result.model_key or model or "auto",
                "endpoint": result.endpoint,
                "image_input": image_file,
                "video_input": video_file,
                "parameters": params,
                "output_video": result.path,
                "ok": result.ok,
                "status": result.status,
                "notes": result.notes,
                "cost_estimate": result.cost_estimate,
                "render_seconds": result.render_seconds,
                "metrics_line": result.metrics_line,
                "scenario": scenario_key,
            },
        )

        if result.ok and result.path:
            append_history(
                job_kind="video",
                model=result.model_key or model or "auto",
                prompt=prompt,
                files=[result.path],
                cost_estimate=result.metrics_line or result.cost_estimate,
                notes=result.notes,
                output_dir=out,
                timestamp=stamp,
                scenario=scenario_key,
            )

        return GenerateResult(
            ok=result.ok,
            image_paths=[],
            video_path=result.path,
            status=result.status,
            model=result.model_key or model,
            job_kind="video",
            cost_estimate=result.cost_estimate,
            notes=list(result.notes),
            render_seconds=result.render_seconds,
            metrics_line=result.metrics_line,
        )

    # ---- IMAGE EDIT ----
    edit_image = _resolve_edit_image(image_file, video_file)
    if not edit_image:
        return GenerateResult(
            ok=False,
            model=model,
            job_kind="image",
            status=(
                "Generate (image edit): upload a still image "
                "(or a video so we can extract the first frame)."
            ),
        )

    if image_file is None and video_file and edit_image:
        progress("No still image — using first frame from video as edit input.")

    progress("Job type: IMAGE EDIT (fal)")
    from media_studio.fal.models import resolve_image_edit_model, default_image_edit_model

    edit_spec = resolve_image_edit_model(model_choice or model) or default_image_edit_model()
    try:
        want_n = int(params.get("num_images") or 1)
    except (TypeError, ValueError):
        want_n = 1
    want_n = max(1, min(4, want_n))
    api_max = max(1, int(getattr(edit_spec, "max_num_images", 1) or 1))

    all_paths: list[str] = []
    all_notes: list[str] = list(clamp_notes)
    total_render = 0.0
    last_status = ""
    last_endpoint = ""
    last_model_key = model
    last_metrics = ""
    last_cost = ""
    ok_any = False

    # Primary + optional multi-ref stills (clamped inside build_edit_arguments)
    edit_paths: list[str] = [edit_image]
    max_refs = max(1, int(getattr(edit_spec, "max_ref_images", 1) or 1))
    if not getattr(edit_spec, "multi_image", False) or getattr(
        edit_spec, "image_field", ""
    ) == "image_url":
        max_refs = 1
    if max_refs > 1 and extra_refs:
        for rp in extra_refs:
            if len(edit_paths) >= max_refs:
                break
            if rp not in edit_paths:
                edit_paths.append(rp)
        if len(edit_paths) > 1:
            progress(
                f"Multi-ref: primary + {len(edit_paths) - 1} reference still(s) "
                f"(model max {max_refs})."
            )
    elif extra_refs and max_refs <= 1:
        progress("Model is single-image — extra reference stills ignored.")

    def _run_one(n_images: int, label: str):
        nonlocal last_status, last_endpoint, last_model_key, last_metrics, last_cost, ok_any
        p = dict(params)
        p["num_images"] = n_images
        progress(label)
        r = run_image_edit(
            prompt=prompt,
            image_paths=edit_paths,
            model_choice=model_choice or model,
            parameters=p,
            output_dir=out,
            on_progress=progress,
            scenario=scenario_key,
        )
        last_status = r.status or last_status
        last_endpoint = r.endpoint or last_endpoint
        last_model_key = r.model_key or last_model_key
        last_metrics = r.metrics_line or last_metrics
        last_cost = r.cost_estimate or last_cost
        if r.render_seconds:
            nonlocal_total[0] += float(r.render_seconds)
        if r.ok and r.paths:
            ok_any = True
            all_paths.extend(r.paths)
            all_notes.extend(list(r.notes or []))
        elif r.notes:
            all_notes.extend(list(r.notes))
        return r

    nonlocal_total = [0.0]

    # One API call when model multi-outputs; else sequential singles (UI stays on image tab busy)
    if want_n <= api_max:
        result = _run_one(want_n, f"Running edit · {want_n} image(s)…")
    else:
        # Prefer multi batches of api_max, then remainder; if api_max==1 → pure sequential
        remaining = want_n
        batch_i = 0
        while remaining > 0:
            batch = min(remaining, api_max)
            batch_i += 1
            done = want_n - remaining
            result = _run_one(
                batch,
                f"Variant batch {batch_i}: images {done + 1}–{done + batch} of {want_n}…",
            )
            if not result.ok:
                break
            got = len(result.paths or [])
            remaining -= got
            if got == 0:
                break
            # If multi-request under-delivered, finish rest as singles
            if batch > 1 and got < batch and remaining > 0:
                progress(
                    f"Under-delivered ({got}/{batch}) — sequential singles for rest…"
                )
                while remaining > 0:
                    r2 = _run_one(
                        1,
                        f"Variant {want_n - remaining + 1}/{want_n}…",
                    )
                    if not r2.ok:
                        remaining = 0
                        break
                    remaining -= 1

    total_render = nonlocal_total[0]
    from media_studio.naming import timestamp_now as _job_stamp

    stamp = _job_stamp()

    # Rebuild a lightweight aggregate status
    if ok_any and all_paths:
        status = (
            f"Generate OK — {last_model_key or model} (image). "
            f"Saved {len(all_paths)} file(s). "
            f"{last_metrics or last_cost or ''}".strip()
        )
    else:
        status = last_status or "Generate failed."

    _write_job_receipt(
        out,
        {
            "timestamp": stamp,
            "job_kind": "image",
            "prompt": prompt,
            "model": last_model_key or model or "auto",
            "endpoint": last_endpoint,
            "image_input": edit_image,
            "video_input": video_file,
            "parameters": params,
            "outputs": all_paths,
            "ok": ok_any,
            "status": status,
            "notes": all_notes,
            "cost_estimate": last_cost,
            "render_seconds": total_render or None,
            "metrics_line": last_metrics,
            "scenario": scenario_key,
            "num_images_requested": want_n,
        },
    )

    # Library: one history row per still (easy Send-to each)
    if ok_any and all_paths:
        n = len(all_paths)
        for i, path in enumerate(all_paths):
            try:
                ts_id = stamp if n == 1 else f"{stamp}_v{i + 1:02d}"
                notes_i = list(all_notes[:4])
                if n > 1:
                    notes_i = [f"variant {i + 1}/{n}"] + notes_i
                append_history(
                    job_kind="image",
                    model=last_model_key or model or "auto",
                    prompt=prompt,
                    files=[path],
                    cost_estimate=last_metrics or last_cost,
                    notes=notes_i,
                    output_dir=out,
                    timestamp=ts_id,
                    scenario=scenario_key,
                )
            except Exception:
                pass

    return GenerateResult(
        ok=ok_any,
        image_paths=all_paths,
        video_path=None,
        status=status,
        model=last_model_key or model,
        job_kind="image",
        cost_estimate=last_cost,
        notes=list(all_notes),
        render_seconds=total_render or None,
        metrics_line=last_metrics,
    )


# Re-export for callers that prefer dicts
def enhance_prompt_as_dict(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return asdict(enhance_prompt(*args, **kwargs))
