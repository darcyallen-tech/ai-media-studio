"""
Grok precision layer — Enhance helpers, post-gen QC, scenario suggest,
natural-language local edits, and lightweight model advice.

Not an open chat sidebar: short structured JSON calls only.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from media_studio.config import XAI_DEFAULT_MODEL, model_label_for
from media_studio.errors import friendly_error
from media_studio.media import media_context_for_enhance, safe_path_str
from media_studio.scenarios import SCENARIOS, get_scenario, image_workspace_items
from media_studio.xai_client import XAIConfigError, chat_json, chat_json_vision


def _strip_fences(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _parse_json(text: str) -> dict[str, Any]:
    cleaned = _strip_fences(text)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", cleaned)
        if not match:
            raise
        data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object.")
    return data


def _notes_list(raw: Any) -> list[str]:
    if isinstance(raw, str):
        return [raw] if raw.strip() else []
    if isinstance(raw, list):
        return [str(n).strip() for n in raw if str(n).strip()]
    return []


# ---------------------------------------------------------------------------
# Post-generation QC
# ---------------------------------------------------------------------------


@dataclass
class QcResult:
    ok: bool
    summary: str = ""
    issues: list[str] = field(default_factory=list)
    fix_prompt: str = ""
    score: str = ""  # good | ok | needs_fix
    status: str = ""


_QC_SYSTEM = """You are a QC critic for AI real-estate image/video edits.
Compare the RESULT media to the SOURCE (if provided) and the USER PROMPT intent.
Return JSON only:
{
  "score": "good" | "ok" | "needs_fix",
  "summary": "1-2 sentence plain critique",
  "issues": ["short bullet issues: scale, wall/color drift, blown windows, identity, furniture placement, perspective, ..."],
  "fix_prompt": "A full follow-up image-edit prompt the user can run next to fix the main issues. Spatially grounded. Architecture lock. Empty string if score is good."
}
Rules:
- Be specific (where things went wrong), not vague.
- If score is good, fix_prompt may be empty.
- Do not invent issues you cannot see.
- Prefer listing-ready real-estate criteria.
"""


def critique_generation(
    *,
    result_path: str | Path | None,
    source_path: str | Path | None = None,
    prompt: str | None = None,
    job_kind: str = "image",
) -> QcResult:
    """Short post-gen critique + optional fix prompt (vision when images available)."""
    result_path = safe_path_str(result_path)
    source_path = safe_path_str(source_path)
    if not result_path or not Path(result_path).is_file():
        return QcResult(ok=False, status="QC: no result file to critique.")

    # Video QC: use poster frame if we can extract
    images: list[str] = []
    kind = (job_kind or "image").lower()
    if kind in ("video", "image_to_video", "v2v", "i2v") or Path(result_path).suffix.lower() in {
        ".mp4", ".mov", ".webm", ".m4v",
    }:
        try:
            from media_studio.media import video_poster_path

            poster = video_poster_path(result_path)
            if poster:
                images.append(poster)
        except Exception:
            pass
    else:
        images.append(result_path)
    if source_path and Path(source_path).is_file():
        if Path(source_path).suffix.lower() in {".mp4", ".mov", ".webm", ".m4v"}:
            try:
                from media_studio.media import video_poster_path

                sp = video_poster_path(source_path)
                if sp:
                    images.insert(0, sp)
            except Exception:
                pass
        else:
            images.insert(0, source_path)

    user = json.dumps(
        {
            "user_prompt": (prompt or "").strip(),
            "job_kind": job_kind,
            "instructions": (
                "First image (if two) is SOURCE; last is RESULT. "
                "Critique RESULT vs SOURCE and the prompt intent."
            ),
        },
        indent=2,
    )
    try:
        raw = chat_json_vision(
            system=_QC_SYSTEM,
            user_text=user,
            image_paths=images,
            model=XAI_DEFAULT_MODEL,
        )
        data = _parse_json(raw)
        return QcResult(
            ok=True,
            summary=str(data.get("summary") or "").strip(),
            issues=_notes_list(data.get("issues")),
            fix_prompt=str(data.get("fix_prompt") or "").strip(),
            score=str(data.get("score") or "ok").strip().lower(),
            status="QC complete.",
        )
    except XAIConfigError as exc:
        return QcResult(ok=False, status=friendly_error(exc, context="QC"))
    except Exception as exc:
        return QcResult(ok=False, status=friendly_error(exc, context="QC"))


# ---------------------------------------------------------------------------
# Scenario suggest on import
# ---------------------------------------------------------------------------


@dataclass
class ScenarioSuggestResult:
    ok: bool
    scenario_key: str = ""
    scenario_label: str = ""
    reason: str = ""
    confidence: str = ""  # high | medium | low
    status: str = ""
    tool_id: str = ""  # optional: blown_out | sky | dehaze | …


_SCENARIO_SYSTEM = """You recommend the best AI Media Studio workflow for a new still.
Return JSON only:
{
  "scenario_key": "one of the allowed keys",
  "tool_id": "optional tool id or empty string",
  "reason": "one short sentence why",
  "confidence": "high" | "medium" | "low"
}
Allowed scenario_key values (prefer non-blank when a specialist fits):
furniture_popin — empty/sparse room needing furniture staging
furniture_swap — furnished room restage/swap pieces
day_to_night — daytime photo → night look
twilight_exterior — exterior blue-hour / warm window lights
sky_mood — sky replacement / exterior mood
lot_to_home — vacant lot / pad / foundation → home viz
dehaze — smoke/haze/fog on exteriors
landscaper — yard/softscape upgrade
blank_canvas — none of the above / general edit

Special tool-only keys (set scenario_key to blank_canvas and tool_id as below):
tool_id "blown_out" — interior with blown-out / overexposed windows
tool_id "sky" — exterior where only sky swap is needed (also can use sky_mood scenario)
tool_id "dehaze" — heavy smoke/haze (or use dehaze scenario)
tool_id empty — no tool handoff
"""


def suggest_scenario_for_still(image_path: str | Path | None) -> ScenarioSuggestResult:
    image_path = safe_path_str(image_path)
    if not image_path or not Path(image_path).is_file():
        return ScenarioSuggestResult(ok=False, status="Suggest: no still to analyze.")

    allowed = {k for k, _ in image_workspace_items()}
    user = (
        "Pick the best scenario (and optional tool) for this still. "
        f"Allowed scenario keys: {sorted(allowed)}. "
        "If blown-out windows dominate an interior, use tool_id blown_out."
    )
    try:
        raw = chat_json_vision(
            system=_SCENARIO_SYSTEM,
            user_text=user,
            image_paths=[image_path],
            model=XAI_DEFAULT_MODEL,
            temperature=0.2,
            max_tokens=600,
        )
        data = _parse_json(raw)
        key = str(data.get("scenario_key") or "blank_canvas").strip().lower()
        tool_id = str(data.get("tool_id") or "").strip().lower()
        # Map tool-only fake keys
        if key in ("blown_out", "blown-out", "window_repair"):
            tool_id = tool_id or "blown_out"
            key = "blank_canvas"
        if key not in SCENARIOS and key not in allowed:
            key = "blank_canvas"
        if tool_id not in ("", "blown_out", "sky", "dehaze", "upscale", "restore"):
            tool_id = ""
        sc = get_scenario(key)
        label = sc.label if sc else key
        if tool_id == "blown_out":
            label = "Blown Out Repair (Tools)"
        return ScenarioSuggestResult(
            ok=True,
            scenario_key=sc.key if sc else key,
            scenario_label=label,
            reason=str(data.get("reason") or "").strip(),
            confidence=str(data.get("confidence") or "medium").strip().lower(),
            status="Scenario suggestion ready.",
            tool_id=tool_id,
        )
    except XAIConfigError as exc:
        return ScenarioSuggestResult(ok=False, status=friendly_error(exc, context="Suggest"))
    except Exception as exc:
        return ScenarioSuggestResult(ok=False, status=friendly_error(exc, context="Suggest"))


# ---------------------------------------------------------------------------
# Natural-language local edit helper
# ---------------------------------------------------------------------------


@dataclass
class LocalEditResult:
    ok: bool
    edit_prompt: str = ""
    status: str = ""


_LOCAL_EDIT_SYSTEM = """You write a full image-edit prompt for real-estate AI tools from a short user request.
Use the attached still (vision) to ground placement, scale, perspective, materials, and lighting.
Return JSON only:
{
  "edit_prompt": "complete standalone edit prompt",
  "notes": ["optional short notes"]
}
Rules:
- Spatially grounded (e.g. "three bar stools at the kitchen island along the near overhang, correct scale and perspective").
- Preserve architecture, windows, camera, wall colors unless the user asks to change them.
- Photorealistic listing-ready language.
- Do not invent rooms that are not visible.
"""


def grounded_local_edit(
    *,
    request: str,
    image_path: str | Path | None,
    scenario_label: str | None = None,
) -> LocalEditResult:
    req = (request or "").strip()
    if not req:
        return LocalEditResult(ok=False, status="Type a short edit request first.")
    image_path = safe_path_str(image_path)
    sc = get_scenario(scenario_label)
    user = json.dumps(
        {
            "user_request": req,
            "scenario": sc.label if sc else None,
            "scenario_rules": sc.notes if sc else None,
            "instructions": "Write one full edit_prompt ready for the image model.",
        },
        indent=2,
    )
    try:
        raw = chat_json_vision(
            system=_LOCAL_EDIT_SYSTEM,
            user_text=user,
            image_paths=[image_path] if image_path else None,
            model=XAI_DEFAULT_MODEL,
        )
        data = _parse_json(raw)
        prompt = str(data.get("edit_prompt") or "").strip()
        if not prompt:
            return LocalEditResult(ok=False, status="Grok returned an empty edit prompt.")
        return LocalEditResult(ok=True, edit_prompt=prompt, status="Local edit prompt ready.")
    except XAIConfigError as exc:
        return LocalEditResult(ok=False, status=friendly_error(exc, context="Local edit"))
    except Exception as exc:
        return LocalEditResult(ok=False, status=friendly_error(exc, context="Local edit"))


# ---------------------------------------------------------------------------
# Lightweight model + cost advisor
# ---------------------------------------------------------------------------


@dataclass
class AdvisorResult:
    ok: bool
    model_label: str = ""
    model_key: str = ""
    cost_hint: str = ""
    reason: str = ""
    status: str = ""


def advise_model(
    *,
    task: str,
    has_image: bool = False,
    has_video: bool = False,
    scenario_label: str | None = None,
) -> AdvisorResult:
    """Non-blocking heuristic + optional Grok nudge for default model."""
    # Fast local heuristics first (no API required)
    task_l = (task or "").lower()
    sc = get_scenario(scenario_label)
    if has_video or "video" in task_l or "v2v" in task_l:
        return AdvisorResult(
            ok=True,
            model_label="Video · Kling O3 Standard – V2V Edit",
            model_key="kling o3 standard edit",
            cost_hint="Est. ~$0.17/s (Kling O3 Standard)",
            reason="Source clip present — motion-preserving V2V is the usual path.",
            status="Advisor (local).",
        )
    if "i2v" in task_l or "animate" in task_l or "image-to-video" in task_l:
        return AdvisorResult(
            ok=True,
            model_label="Video · Seedance 2.0 – Image-to-Video",
            model_key="seedance 2.0 i2v",
            cost_hint="Est. ~$0.30/s @720p (Seedance 2.0)",
            reason="Still → motion: Seedance 2.0 is strong for product/furniture motion; up to 4K.",
            status="Advisor (local).",
        )
    # Image defaults
    label = (sc.default_model_hint if sc else None) or "Image · Flux 2 Pro (edit)"
    return AdvisorResult(
        ok=True,
        model_label=label,
        model_key="flux 2 pro",
        cost_hint="Est. ~$0.03–0.08 / image (Flux-class edit)",
        reason="Still edit — Flux 2 Pro is the Studio default for architecture-locked work.",
        status="Advisor (local).",
    )


# ---------------------------------------------------------------------------
# Optional smarter export stem (when Grok available)
# ---------------------------------------------------------------------------


def suggest_export_slug(prompt: str, *, max_len: int = 40) -> str | None:
    """Short filesystem-safe slug from a prompt; None if Grok unavailable."""
    p = (prompt or "").strip()
    if not p:
        return None
    system = (
        'Return JSON only: {"slug":"kebab-case-short-name-max-6-words"}. '
        "No stop words. Suitable as part of a filename."
    )
    try:
        raw = chat_json(
            system=system,
            user=p[:500],
            model=XAI_DEFAULT_MODEL,
            temperature=0.2,
            max_tokens=80,
        )
        data = _parse_json(raw)
        slug = str(data.get("slug") or "").strip().lower()
        slug = re.sub(r"[^a-z0-9\-]+", "-", slug).strip("-")
        if not slug:
            return None
        return slug[:max_len]
    except Exception:
        return None
