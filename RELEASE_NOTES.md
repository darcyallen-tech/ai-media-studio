# Release notes

AI Media Studio — real-estate–focused Flet desktop app for AI image, video, and audio.

See also [README.md](README.md) (install) and [FEATURES.txt](FEATURES.txt) (capability list).

**Hard rule:** User-visible changes must update **README.md**, **FEATURES.txt**, and this file as needed ([AGENTS.md](AGENTS.md)).

---

## 0.1.2

**Library, Resolve handoff, Frame Editor, tools, and cost polish.**

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
