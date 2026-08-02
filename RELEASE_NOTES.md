# Release notes

AI Media Studio — real-estate–focused Flet desktop app for AI image, video, and audio.

See also [README.md](README.md) (install) and [FEATURES.txt](FEATURES.txt) (capability list).

**Hard rule:** User-visible changes must update **README.md**, **FEATURES.txt**, and this file as needed ([AGENTS.md](AGENTS.md)).

---

## 0.1.2

**Library, Resolve handoff, Frame Editor, tools, and cost polish.**

### Audio — Layered SFX mixer (v1)
- New **Mixer** pill: Bed / Spot / Accent (plain labels + subtitles; not a DAW)
- **Scene Enhance** — one scene box → Grok fills Bed/Spot/Accent prompts (no auto Generate)
- **Generate all** — sequential Generate for unmuted layers with prompts; keeps old audio until a slot succeeds
- Per-slot Generate / Enhance + intent helpers; **Load from Video → SFX** on Bed/Spot
- Bounce mix + optional stems; MP3 via pygame WAV sidecars; cost sums pending layers

### Library
- **Bulk Assign to Job / Listing** — multi-select cards (checkbox), bulk bar with Assign to ▾ (New / existing jobs / Clear); same metadata + optional move under `jobs/<name>/` as single-card Assign
- **Bulk Send to Resolve** — same bulk bar; each selected item uses Tier A send (bin / optional track+marker); mixed image+video OK; continues on failures; snack “N sent, M skipped”
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
- Gen blend layer is **removed from the Comparison Stack** while placing boxes (asserted; rebuild failures force source-only); Overlay/A-B only after a real generation when A/B is on

### Tools — Inpaint (freehand)
- New Image tool with **3-column layout**: left controls · large center canvas · right result
- Brush / eraser / size / clear / undo; live canvas strokes, committed overlay on stroke end
- **Canvas zoom** (− / Fit / + and scroll wheel) + **Pan** mode for fine masking; brush size is **constant screen pixels** under zoom; Fit resets to whole image
- Mask baked at **full source resolution** (EXIF-normalized); zoom/pan map brush→full-res so fal fill never sees mask≠image size
- **Grow mask** 0 / 2 / 4 / 8 px (default 4): dilate white edit region at **export only** (hard MaxFilter) so fill blends at edges; canvas strokes unchanged; WxH still matches source
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
