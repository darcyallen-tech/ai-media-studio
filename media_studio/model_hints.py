"""
Short “Best for” hints for model dropdowns.

Keys are matched case-insensitively against model labels and registry keys.
Missing entry → hide the line (never show empty “Best for:”).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BestFor:
    """short ≈ 6–12 words under the dropdown; detail ≈ 1–2 sentences for tooltip."""

    short: str
    detail: str


# Canonical map — add aliases as needed. Prefer short, scannable phrases.
_BEST_FOR: dict[str, BestFor] = {
    # --- Studio / fal image edit ---
    "flux 2 pro": BestFor(
        "furniture / architecture lock, photoreal edits",
        "Strong default for listing stills: keeps structure locked while changing "
        "furniture, decor, or local details.",
    ),
    "image · flux 2 pro (edit)": BestFor(
        "furniture / architecture lock, photoreal edits",
        "Strong default for listing stills: keeps structure locked while changing "
        "furniture, decor, or local details.",
    ),
    "flux 2 max": BestFor(
        "highest-quality Flux edit, fine detail",
        "Premium Flux edit when you need maximum fidelity on complex plates.",
    ),
    "image · flux 2 max (edit)": BestFor(
        "highest-quality Flux edit, fine detail",
        "Premium Flux edit when you need maximum fidelity on complex plates.",
    ),
    "flux 2 flex": BestFor(
        "flexible style control on edits",
        "Flux Flex when you want more stylistic latitude without leaving Flux.",
    ),
    "flux kontext pro": BestFor(
        "subject-locked single-image edits",
        "Kontext Pro preserves subject/context in single-image edits; no multi-ref.",
    ),
    "nano banana pro": BestFor(
        "creative restyle, strong prompt adherence",
        "Excellent for creative inserts and restyles with tight prompt following.",
    ),
    "nano banana 2": BestFor(
        "creative restyle, faster drafts",
        "Faster/cheaper Nano Banana edit for drafts and light creative work.",
    ),
    "nano banana": BestFor(
        "general still edits, economical",
        "Solid general-purpose still edit when cost and speed matter.",
    ),
    "seedream 5 pro": BestFor(
        "grounded still edits, listing detail",
        "Seedream edit for realistic detail and listing-friendly stills.",
    ),
    "seedream": BestFor(
        "grounded still edits, listing detail",
        "Seedream edit for realistic detail and listing-friendly stills.",
    ),
    "mai-image": BestFor(
        "Microsoft MAI still edits",
        "MAI Image edit path for general photoreal still work.",
    ),
    # --- Video ---
    "kling o3": BestFor(
        "camera-locked video edit",
        "Kling O3 V2V is the usual pick for motion-preserving listing video edits.",
    ),
    "kling o3 standard": BestFor(
        "camera-locked video edit",
        "Kling O3 Standard V2V — reliable camera-lock friendly video edits.",
    ),
    "kling o3 pro": BestFor(
        "higher-quality camera-locked V2V",
        "Kling O3 Pro when you want higher quality on short V2V clips.",
    ),
    "seedance": BestFor(
        "longer / higher-res video when needed",
        "Seedance for longer or higher-res motion when Kling length/res is limiting.",
    ),
    "veo 3.1": BestFor(
        "top cinematic T2V quality",
        "Highest quality text→video; expensive — check est. cost (rate × seconds).",
    ),
    "veo 3.1 fast": BestFor(
        "cinematic T2V, lower $/s",
        "Faster/cheaper Veo path for cinematic drafts before a full Pro run.",
    ),
    "luma ray": BestFor(
        "cinematic T2V / I2V alternative",
        "Luma Ray as an alternative cinematic motion model.",
    ),
    "hailuo": BestFor(
        "I2V / bridge with start–end frames",
        "Hailuo when you need start+end frame control on short clips.",
    ),
    "minimax h3": BestFor(
        "multimodal ref + native stereo audio / motion transfer",
        "MiniMax H3 (Hailuo-03): T2V, first→last I2V, or omni refs "
        "(up to 9 stills + 3 clips + 3 audio). Cite Image 1 / Video 1 / Audio 1. "
        "Native stereo; ~$0.26/s @2K.",
    ),
    "minimax h3 i2v": BestFor(
        "first/last frame I2V + native stereo 2K",
        "H3 image-to-video: start still as first frame; optional last frame for "
        "day→night / porch→interior. 5–15s · 2K · native stereo. Est. ~$0.26/s.",
    ),
    "video · minimax h3 – image-to-video": BestFor(
        "first/last frame I2V + native stereo 2K",
        "H3 image-to-video: start still as first frame; optional last frame for "
        "transitions. 5–15s · 2K · native stereo. Est. ~$0.26/s.",
    ),
    "minimax h3 reference": BestFor(
        "multimodal ref + native stereo audio / motion transfer",
        "H3 omni: multi stills (subject lock) + motion plate as Video 1 + optional "
        "Audio 1 bed. Cite assets in the prompt. 2K · ~$0.26/s.",
    ),
    "video · minimax h3 – omni reference": BestFor(
        "multimodal ref + native stereo audio / motion transfer",
        "H3 omni reference-to-video for realtor consistency + camera-path lock.",
    ),
    "minimax h3 t2v": BestFor(
        "cinematic T2V 2K + native stereo",
        "H3 text-to-video: 5–15s · 2K · native stereo. Est. ~$0.26/s.",
    ),
    "minimax h3 · text→video": BestFor(
        "cinematic T2V 2K + native stereo",
        "H3 text-to-video: 5–15s · 2K · native stereo. Est. ~$0.26/s.",
    ),
    "minimax h3 · image→video": BestFor(
        "first/last frame I2V + native stereo 2K",
        "H3 I2V with optional end frame; native stereo · 2K · ~$0.26/s.",
    ),
    "minimax h3 omni": BestFor(
        "multimodal ref + native stereo audio / motion transfer",
        "H3 omni reference: Image/Video/Audio plates with citation labels in prompt.",
    ),
    "minimax h3 · omni reference": BestFor(
        "multimodal ref + native stereo audio / motion transfer",
        "H3 omni: multi stills + motion plate + optional audio; cite Image/Video/Audio N.",
    ),
    # --- Director multi-shot ---
    "kling v3 pro multi-shot": BestFor(
        "multi-shot storyboard, cinematic V3 Pro",
        "Kling V3 Pro multi_prompt director — up to 6 shots, total ≤15s.",
    ),
    "kling v3 pro · multi-shot": BestFor(
        "multi-shot storyboard, cinematic V3 Pro",
        "Kling V3 Pro multi_prompt director — up to 6 shots, total ≤15s.",
    ),
    "kling v3 standard multi-shot": BestFor(
        "multi-shot storyboard, faster V3 Standard",
        "Kling V3 Standard multi-shot — cheaper iteration, total ≤15s.",
    ),
    "kling v3 standard · multi-shot": BestFor(
        "multi-shot storyboard, faster V3 Standard",
        "Kling V3 Standard multi-shot — cheaper iteration, total ≤15s.",
    ),
    "kling o3 pro multi-shot": BestFor(
        "O3 director multi-shot + optional audio",
        "Kling O3 Pro multi-shot / director path for structured storyboards.",
    ),
    "kling o3 pro · multi-shot (director)": BestFor(
        "O3 director multi-shot + optional audio",
        "Kling O3 Pro multi-shot / director path for structured storyboards.",
    ),
    "kling o3 standard multi-shot": BestFor(
        "O3 Standard multi-shot, cheaper iteration",
        "Kling O3 Standard multi_prompt storyboard — same shot structure as Pro, lower $/s.",
    ),
    "kling o3 standard · multi-shot": BestFor(
        "O3 Standard multi-shot, cheaper iteration",
        "Kling O3 Standard multi_prompt storyboard — same shot structure as Pro, lower $/s.",
    ),
    "grok imagine 1.5": BestFor(
        "strong reference consistency, native audio, motion quality",
        "xAI Grok Imagine Video 1.5 — I2V / T2V / R2V (up to 7 stills). "
        "Native audio; $0.08–0.25/s by resolution + $0.01/ref image.",
    ),
    "grok imagine 1.5 i2v": BestFor(
        "strong reference consistency, native audio, motion quality",
        "Grok Imagine 1.5 image-to-video from a start still.",
    ),
    "video · grok imagine 1.5 – image-to-video": BestFor(
        "strong reference consistency, native audio, motion quality",
        "Grok Imagine 1.5 image-to-video from a start still.",
    ),
    "grok imagine 1.5 t2v": BestFor(
        "strong reference consistency, native audio, motion quality",
        "Grok Imagine 1.5 text-to-video with native audio.",
    ),
    "grok imagine 1.5 · text→video": BestFor(
        "strong reference consistency, native audio, motion quality",
        "Grok Imagine 1.5 text-to-video with native audio.",
    ),
    "grok imagine 1.5 reference": BestFor(
        "strong reference consistency, native audio, motion quality",
        "Grok Imagine 1.5 R2V — up to 7 stills; tag <IMAGE_0>… in the prompt.",
    ),
    "video · grok imagine 1.5 – reference-to-video": BestFor(
        "strong reference consistency, native audio, motion quality",
        "Grok Imagine 1.5 R2V — up to 7 stills; tag <IMAGE_0>… in the prompt.",
    ),
    "grok imagine 1.5 · reference pack": BestFor(
        "strong reference consistency, native audio, motion quality",
        "Grok Imagine 1.5 R2V — up to 7 stills; tag <IMAGE_0>… in the prompt.",
    ),
    "grok imagine 1.5 director": BestFor(
        "strong reference consistency, native audio, motion quality",
        "Director via Grok Imagine 1.5 — ordered shot refs as R2V/I2V/T2V single clip.",
    ),
    "grok imagine 1.5 · reference storyboard": BestFor(
        "strong reference consistency, native audio, motion quality",
        "Director via Grok Imagine 1.5 — ordered shot refs as R2V/I2V/T2V single clip.",
    ),
    # --- Creative Vision I2I labels ---
    "flux 2 pro (edit)": BestFor(
        "furniture / architecture lock, photoreal edits",
        "Default I2I for creative plate work with multi-ref support.",
    ),
    "flux 2 max (edit)": BestFor(
        "highest-quality Flux edit, fine detail",
        "Premium multi-ref Flux edit for complex creative inserts.",
    ),
    "flux 2 flex (edit)": BestFor(
        "flexible style control on edits",
        "Flux Flex I2I with multi-ref for more stylistic latitude.",
    ),
    "flux kontext pro (edit)": BestFor(
        "subject-locked single-image edits",
        "Single-image Kontext — no multi-ref; strong subject preservation.",
    ),
    "nano banana pro (edit)": BestFor(
        "creative restyle, strong prompt adherence",
        "I2I multi-ref restyles and creative inserts with tight adherence.",
    ),
    "nano banana 2 (edit · fast)": BestFor(
        "creative restyle, faster drafts",
        "Faster I2I multi-ref drafts before a Pro pass.",
    ),
    "nano banana (edit)": BestFor(
        "general still edits, economical",
        "Economical multi-ref still edits.",
    ),
    "seedream 5.0 pro (edit)": BestFor(
        "grounded still edits, listing detail",
        "Multi-ref Seedream for realistic creative stills.",
    ),
    # --- Tools restore / denoise ---
    "codeformer": BestFor(
        "soft faces, identity-close restore",
        "Face-first restore with fidelity control; use a sharp ref model for multi-ref lock.",
    ),
    "codeformer (face restore)": BestFor(
        "soft faces, identity-close restore",
        "Face-first restore with fidelity control; ref still is not used by this model.",
    ),
    "nafnet": BestFor(
        "whole-frame soft/defocus deblur",
        "Whole-frame deblur for soft or motion-blurred stills — no prompt or ref.",
    ),
    "nafnet deblur (whole frame)": BestFor(
        "whole-frame soft/defocus deblur",
        "Whole-frame deblur for soft or motion-blurred stills — no prompt or ref.",
    ),
    "topaz": BestFor(
        "professional upscale / denoise families",
        "Topaz endpoints for polish: upscale, denoise, or generative enhance by family.",
    ),
    "seedvr": BestFor(
        "balanced temporal / still upscale",
        "SeedVR2 for sharp general upscale without a heavy restyle.",
    ),
    # --- Frame Editor ---
    "aleph": BestFor(
        "keyframe look through motion",
        "Aleph 2.0 propagates keyframe stills through the clip (first/last/timestamps).",
    ),
    "aleph 2.0": BestFor(
        "keyframe look through motion",
        "Aleph 2.0 propagates keyframe stills through the clip (first/last/timestamps).",
    ),
    # --- Inpaint (mask-capable only) ---
    "flux fill": BestFor(
        "default masked fill / object replace",
        "Flux Pro Fill for freehand mask inpaint — batch-capable, only painted pixels change.",
    ),
    "flux pro fill": BestFor(
        "default masked fill / object replace",
        "Flux Pro Fill for high-quality masked inpaint on stills; supports # Images batch.",
    ),
    "flux pro fill (inpaint)": BestFor(
        "default masked fill / object replace",
        "Flux Pro Fill for freehand mask inpaint — only painted pixels change; batch 1–4.",
    ),
    "flux lora fill": BestFor(
        "economical fill, optional fill ref",
        "Flux LoRA Fill — lighter cost; optional fill reference for mask content.",
    ),
    "flux lora fill (inpaint)": BestFor(
        "economical fill, optional fill ref",
        "Flux LoRA Fill for lighter cost mask-guided still inpaint; optional fill ref.",
    ),
    "flux dev inpaint": BestFor(
        "Flux dev inpaint with strength",
        "FLUX.1 [dev] LoRA inpainting with strength control; no reference still.",
    ),
    "flux dev inpaint (lora)": BestFor(
        "Flux dev inpaint with strength",
        "FLUX.1 [dev] LoRA inpainting with strength control; no reference still.",
    ),
    "flux kontext lora inpaint": BestFor(
        "ref-locked mask fill (requires ref)",
        "Kontext LoRA inpaint — needs a reference still for identity/style into the mask.",
    ),
    "juggernaut flux lora inpaint": BestFor(
        "sharper Flux LoRA inpaint detail",
        "Juggernaut Flux LoRA inpainting — richer detail/color drop-in for Flux Dev inpaint.",
    ),
}


def _norm(s: str) -> str:
    return " ".join((s or "").strip().lower().split())


def lookup_best_for(model_choice: str | None) -> BestFor | None:
    """
    Resolve BestFor for a dropdown label or registry key.

    Tries exact key, then substring heuristics. Returns None if unknown.
    """
    if not model_choice or not str(model_choice).strip():
        return None
    raw = str(model_choice).strip()
    key = _norm(raw)
    if key in _BEST_FOR:
        return _BEST_FOR[key]
    # Strip common prefixes
    for prefix in ("image · ", "video · ", "tools · "):
        if key.startswith(prefix):
            k2 = key[len(prefix) :]
            if k2 in _BEST_FOR:
                return _BEST_FOR[k2]
    # Substring match on known keys (longest first)
    for k in sorted(_BEST_FOR.keys(), key=len, reverse=True):
        if len(k) < 4:
            continue
        if k in key or key in k:
            return _BEST_FOR[k]
    return None
