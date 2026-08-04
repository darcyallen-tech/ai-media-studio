# Release notes

AI Media Studio — real-estate–focused Flet desktop app for AI image, video, and audio.

See also [README.md](README.md) (install) and [FEATURES.txt](FEATURES.txt) (capability list).

**Hard rule:** User-visible changes must update **README.md**, **FEATURES.txt**, and this file as needed ([AGENTS.md](AGENTS.md)).

---

## 0.1.2

**Library, Resolve handoff, Frame Editor, tools, and cost polish.**

### Studio modality sub-tabs (Image / Video)
- Same row as **Image | Video** (to the right; no third bar): **I2I | T2I | R2I | Region** or **I2V | T2V | V2V | R2V**
- Defaults: Image → I2I, Video → I2V; model dropdown filtered strictly by sub-tab
- Region moved off Standard/Region toggle; H3 Omni under R2V; Enhance modality-aware
- P1: Studio T2V / Vision T2V cost + duration (not Flux image fallback); T2I Size/aspect; R2V = still + optional motion (full omni in Creative Vision)

### MiniMax H3 (Hailuo-03) — first-class video
- **Creative Vision**: MiniMax H3 · Text→Video, Image→Video (optional first→last end frame), and **Omni reference**
- Omni panel: up to 9 stills + 3 motion clips + 3 audio (≤12 files); intent chips insert Image 1 / Video 1 / Audio 1 citation language
- Grok Enhance: mode-aware citations; does not invent unsupported params; native stereo noted
- Duration 5–15s · 2K · cost est. ~$0.26/s (scales with duration); native stereo always on output
- **Studio Video**: MiniMax H3 I2V + Omni Reference in the model picker (still + optional motion plate as Video 1)
- fal endpoints: `minimax/h3/text-to-video`, `image-to-video` (`end_image_url`), `reference-to-video`
- Does not wire Flux 3 or Seedance 2.5; existing Kling / Seedance 2.0 / Aleph / Veo paths unchanged

### Grok Imagine Video 1.5 (fal) — first-class video
- **Studio Video**: I2V + R2V (up to 7 stills; `<IMAGE_n>` tags); **Creative Vision**: T2V + I2V + Reference pack
- **Director**: Grok Imagine 1.5 · Reference storyboard (ordered shot refs → T2V / I2V / R2V single clip)
- Best-for: strong reference consistency, native audio, motion quality
- Pricing: $0.08/s @480p · $0.14/s @720p · $0.25/s @1080p (I2V/T2V) + $0.01 per ref image
- fal: `xai/grok-imagine-video/v1.5/{image,text,reference}-to-video`

### Characters tab
- New main tab **Characters** — save reusable character stills (local store only)
- Upload / Previously used / From Resolve; name + optional notes/tags; Edit · Delete · Show in folder
- **Use in Motion Sync** sets the character still and focuses Motion Sync
- **Phase 2:** multi-angle (1–3 stills), **Generate variation** (I2I face-lock), shortcuts from Motion Sync / Director / Studio
- Curated subset of Library (not a replacement); Voice Clone remains under Audio

### Motion Sync tab
- New main tab **Motion Sync** — character still + driving video → motion transfer
- Models: Kling Motion Control V3 Pro / Standard, Kling 2.6 Motion Control, Wan Motion
- Keep original audio (Kling); orientation match video/image; Wan fit-body / face-identity wording
- Auto-proxy long/large clips + oversized stills (original kept); best-practice tips on tab
- Optional prompt helper chips + Enhance; Est. cost under Generate; Library + Resolve

### VFX tab
- New main tab **VFX** (peer to Studio / Creative Vision / Director / Frame Editor)
- **In-scene** — integrate fire, smoke, energy, weather, debris, lens FX into a still or clip
- **Element plates** — isolated FX on pure black for Resolve **Screen / Add** composite
- Preset packs inject physics-aware prompt language (editable); strength + duration + model picker
- **Custom** preset — user-written vision only (no pack inject); Enhance rewrites model-ready without forcing a category
- Models: Grok Imagine 1.5, Kling I2V, Seedance, H3, Veo Fast, video-edit models
- Est. cost under Generate (Studio chrome); Library / Resolve handoff

### Director tab (multi-shot)
- New main tab **Director** (peer to Studio / Creative Vision / Frame Editor)
- Master brief + total duration/aspect/style pack; multi-shot models only (Kling V3 Pro/Standard, O3 Pro/Standard)
- **Est. cost** chrome matches Studio (bordered block under Generate; live on model / duration / audio)
- Ordered shot list (up to model max, typically 6): start/end times, camera presets, per-shot action, optional ref still with **thumbnail** (~64px) + filename
- Fail-safes: times within total duration, no overlap, clear Generate blocks
- Enhance rewrites master + per-shot language; Generate → single multi-shot clip; Library + Resolve
- **Library Send to ▾** nested: Director ▶ Shot 1…N (dynamic), Creative Vision ▶, Tools ▶ — short top-level list; sending a still to Shot K sets that ref + thumbnail, focuses Director, highlights the row
- **Phase 2 polish**: audio style (No music / Soft bed / Full score) + SFX notes; continuity toggles; **per-gap transitions** (Hard cut / Soft dissolve / Continuous) with global default + control between Shot N→N+1; energy curve; Enhance-only vision notes; output mode (clip or clip + shot-list sidecar for Resolve)

### Music — Arrangement builder
- Optional **Arrangement** block: intro energy/length, lift cue, solo instrument/start/length, outro style, band layers (drums/bass/…)
- Merges into the auto-built editable Music prompt (ElevenLabs-friendly form language); Enhance keeps structure
- Duration reliability: hard-limit length language in auto prompt + Enhance; **Trim to Ns** after generate (ffmpeg + short fade-out)

### Audio — Layered SFX mixer (v1)
- New **Mixer** pill: Bed / Spot / Accent (plain labels + subtitles; not a DAW)
- **Scene Enhance** — one scene box → Grok fills Bed/Spot/Accent; retry if &lt;2 slots parse; raw text to Spot on sparse fill
- **Generate all** — sequential Generate for unmuted layers with prompts; busy lock always cleared on error; keeps old audio until success
- Per-slot Generate / Enhance + intent helpers; **Load from Video → SFX** on Bed/Spot
- Bounce mix + optional stems; MP3 via pygame WAV sidecars; cost sums pending layers

### Cost chrome (all Generate surfaces)
- Shared **Estimated cost** panel (Studio pattern): ACCENT border, caption + bold job-total line, placed **directly under** the primary Generate button
- Applied on Studio Image/Video, Director, Creative Vision, Tools, Frame Editor, Audio

### Library
- **Bulk Assign to Job / Listing** — multi-select cards (checkbox), bulk bar with Assign to ▾ (New / existing jobs / Clear); same metadata + optional move under `jobs/<name>/` as single-card Assign
- **Bulk Send to Resolve** — same bulk bar; each selected item uses Tier A send (bin / optional track+marker); mixed image+video OK; continues on failures unless Resolve is unavailable / no project (stops with one snack)
- **From Resolve** filter chip (All | Image | Video | Audio | From Resolve)
- **Resolve** badge on handoff-origin cards in All (and other filters)
- History stores `origin=resolve` on Import / plugin send

### Resolve
- **From Resolve** strips wherever media loads: Studio Image / Video, Tools image + video, Creative Vision (I2I / start), Frame Editor (stills → pin, clips → source)
- DaVinci Resolve logo asset on Send to Resolve
- Single-instance: Resolve Send focuses the open Studio window
- **Tier A smarter Send**: Media Pool `AI Media Studio / <Job|date>`; optional place on V2 at playhead; marker with model/scenario/cost; soft-fail opens folder if Resolve is closed

### Frame Editor (Aleph 2.0)
- **Edit intent**: Apply through clip | Transition first→last | Custom timestamps
- Dual-anchor transition UX (first + last / timestamps); Enhance steers transition language
- Denser filmstrip (more samples on short clips; more + scroll on long)
- Result playback: CONTAIN, play/pause, Show in folder / Resolve under player
- Keyframe position badges (`first` / `last` / `1.61s`); day→night empty tip

### Tools — Sharpen / Restore
- **NAFNet Deblur** (`fal-ai/nafnet/deblur`) — whole-frame soft/defocus
- **CodeFormer** face restore with fidelity control (default without ref still)
- Ref-identity multi-image models remain default when a sharp ref still is set
- Per-model cost estimates; ref still only where the model uses guidance
- Soft source + Reference still **stacked vertically** (no clipped “Reference still” / upload in the form rail)

### Creative Vision — Image → Image multi-ref
- Primary source + up to **3 reference stills** on multi-image edit models (Flux 2, Nano Banana, Seedream)
- Single-image models (e.g. Kontext): extra refs disabled with note; primary only on generate
- Previously used / From Resolve: load as source or add as ref
- Enhance: vision on primary + refs; rewritten prompt describes ref roles
- Send to: **I2I source** and **Add as I2I ref**

### Model “Best for” hints
- Short **Best for:** line under major model dropdowns (Studio Image/Video, Creative Vision, Tools)
- Tooltip for 1–2 sentence detail; missing registry entry hides the line (no empty Best for)

### Update checker
- Prefers **APP_VERSION** vs GitHub release/tag (semver), then **git SHA** vs latest commit
- Same-day remote commits no longer show “newer commits” from calendar alone; banner only when version or SHA proves remote is newer
- Local SHA from env / `_build_sha.txt` / `git rev-parse HEAD`

### Studio — Region box alignment
- Small left source preview and large Comparison stage share one coordinate system: L/T/W/H are % of the **source image content box** (CONTAIN letterbox), not the outer panel
- Large stage size comes from layout (`on_size_change`), with a fallback that subtracts the versions rail — fixes ~25% horizontal offset between previews
- Overlay / A-B still maps boxes to the source frame; slider and drag stay in sync across both views
- Region placement: **no full-stage grey blend scrim** — source stays full brightness; only colored box rects sit on the photo
- Region box host is sized to the **image content_rect only** (not a full-stage transparent pin that could grey-veil the photo)
- Gen blend layer is **removed from the Comparison Stack** while placing boxes (asserted; rebuild failures force source-only); after Generate, status/toast points to versions + A/B for Gen

### Tools — Inpaint (freehand)
- New Image tool with **3-column layout**: left controls · large center canvas · right result
- Brush / eraser / size / clear / undo; live canvas strokes, committed overlay on stroke end
- **Canvas zoom** (− / Fit / + and scroll wheel) + **Pan** mode for fine masking; brush size is **constant screen pixels** under zoom; Fit resets to whole image
- Mask baked at **full source resolution** (EXIF-normalized); zoom/pan map brush→full-res so fal fill never sees mask≠image size
- **Grow mask** 0 / 2 / 4 / 8 px (default 4): dilate at **export only** — UI note “Applied at export only (canvas shows exact brush)”
- **# Images 1–4** when the endpoint supports `num_images` (e.g. Flux Pro Fill); Est. cost = per-image × N; multi results → Library as separate stills
- **Reference still** (upload / Previously used / From Resolve) only when the model supports ref — optional for Flux LoRA Fill, **required** for Flux Kontext LoRA Inpaint; hidden for Pro Fill / Dev / Juggernaut
- Models (mask-capable only): Flux Pro Fill, Flux LoRA Fill, Flux Dev Inpaint (LoRA), Flux Kontext LoRA Inpaint, Juggernaut Flux LoRA Inpaint — not Nano Banana / Flux 2 edit
- Best-for lines per model; pre-submit size assert; status logs `image WxH, mask WxH` on mismatch
- Intent helpers; prompt + optional negative; Enhance for inpaint wording

### Cost & previews
- **Batch cost × N** — Est. cost always multiplies by selected **# Images** (including sequential singles when API max is 1, e.g. Flux 2 Pro)
- Label notes sequential runs when batching 1-at-a-time calls
- Preview **CONTAIN** (no crop) for video/result panes (Tools, Frame Editor, players)

### Docs
- README + FEATURES updated for the above
- **Hard rule** (AGENTS.md): always keep README, FEATURES, and RELEASE_NOTES in sync with product changes

---

## 0.1.1

**Layout hygiene, Job/Listing, favorites, spend, update check, batch generate.**

### Layout & shell
- Fixed left rail + cap-right-empty pattern — fewer grey voids under Star / multi-ref / empty panes
- Video preview cropping fixes (CONTAIN)
- Single-instance app lock; startup disk hygiene for handoff/caches

### Studio & generation
- **# Images** multi-variant batch (1–4); sequential when the API is one-at-a-time
- Multi-reference stills on Studio Image when the model allows
- Creative Vision: Text → Image still-only helpers; **Image → Image**; bridge handoffs
- Before/after still export (side-by-side or vertical stack)
- Video cost estimate fixes (job totals, e.g. Veo rate × duration)

### Job / Listing
- App-level Job / Listing field → media under `outputs/jobs/<name>/<date>/`
- Library Assign to ▾ (single card), job filter, group headers

### Library & QoL
- Local spend dashboard (history costs: today / week / month / all-time)
- Prompt favorites + simple JSON packs (Star / Apply / export-import)
- GitHub update check (banner + toast; no auto-download)
- Release hygiene (version / build date for update checker)

---

## 0.1.0

**Initial public baseline.**

- Flet desktop shell: Studio (Image / Video), Tools, Creative Vision, Frame Editor (Aleph / Runware), Audio, Library
- fal.ai main generation; optional xAI Enhance/QC; optional Runware for Frame Editor
- Scenarios (furniture, day→night, sky, dehaze, …)
- Tools: upscale, cleanup, sky, dehaze, restore, blown-out, amenity, re-aspect, video denoise / slow-mo, …
- DaVinci Resolve Send / Import handoff
- Settings: keys, output folder, retention, caches, cost guard
- Quick Start onboarding

---

## Versioning

App version is `media_studio.__version__` (shown in Help / update check).  
Bump that value and this file when cutting a GitHub Release/tag.
