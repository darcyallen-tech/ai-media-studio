# Release notes

AI Media Studio — real-estate–focused Flet desktop app for AI image, video, and audio.

See also [README.md](README.md) (install) and [FEATURES.txt](FEATURES.txt) (capability list).

**Hard rule:** User-visible changes must update **README.md**, **FEATURES.txt**, and this file as needed ([AGENTS.md](AGENTS.md)).

---

## 0.1.2

**Library, Resolve handoff, Frame Editor, tools, and cost polish.**

### Costume Swap redesign (sequential angles)
- **Front only first** → then Side → Close-up (one image each; no batch-all)
- After Front succeeds, that costume still is **primary ref** for Side/Close-up
- Close-up: front-facing portrait + neckline (not profile); outfit lock on later angles
- Models aligned with multi-ref edit list; default **Seedream 5 Pro**
- Optional clothing helper compiles into wardrobe prompt

### Unified video aspect_ratio policy
- Single module `media_studio/aspect_omit.py`: endpoint → omit | send (allowlist)
- **Omit** (strict): FLUX 3 pure I2V (+ draft), Kling I2V only
- **Send**: **Seedance R2V** (`auto` default | 21:9…9:16 per fal docs), H3 R2V
  (`auto`→`adaptive`), Seedance I2V, FLUX T2V/first-last/extend/keyframes
- Seedance R2V was incorrectly on the omit list (inverted) — fixed; UI re-enables Aspect
- Duration for Seedance: string `"15"` / `"auto"` (not int)
- fal errors append raw body to `outputs/aspect_debug.log` + progress line
- Tests: `python scripts/test_aspect_policy.py`

### R2V / R2I reference UI cleanup
- **Slots**: Character (library dropdown) · Scene (library dropdown) · Prop (upload) · optional Start frame (composition only)
- **Add another character / scene** opens another library dropdown — never OS folder dialog
- Live **citation map**: `Image 1 = Camera Man (character) · Image 2 = Tavern (scene)` (adapts to Image N / @ImageN / model-specific tags)
- Enhance uses the same labels in the rewrite
- **Studio Image R2I**: Character is identity ref, not source; source only if user uploads an edit plate
- **Studio Video R2V**: full Character/Scene/Prop pack; I2V keeps simpler Character identity slots
- **Creative Vision**: same pack on R2I/R2V; start-frame labels hidden when not applicable (no jumbled headers)
- Not in this pass: shot-list storyboard builder; Prop Gen tool (slot + upload only)

### Creative Vision — modality tabs (R2I / R2V)
- Image row: Text→Image | Image→Image | **R2I**; Video: Text→Video | Image→Video | **R2V** | V2V | Bridge | Extend
- Model lists filtered per tab: pure R2V (H3 Omni, Seedance Reference, Grok ref pack) off I2V
- I2V = start-frame layout lock (FLUX 3 no aspect_ratio); R2V = multi-ref / omni
- R2I = build still from Character/Scene/Prop identity refs (not silent plate edit); Enhance tab-aware

### Model Guide (in-app)
- Book icon next to Settings gear → modal catalog of registered models
- Cards: name, modality tags, Best for, strengths, limits; filters (Image / Video / Audio / Tools / Director) + search + multi-char / native audio / draft chips
- Data from same registries + Best For map as pickers; Open in Studio / Vision / Director when practical
- FLUX 3 aspect-follows-still, H3 multi-identity, Kling multi-shot called out in limits

### Creative Vision — Character-first multi-ref (H3 Omni + multi I2V)
- **Default**: Character 1 dropdown → identity (Image 1); **Add another character** → Character 2… with live map
- Optional **Start / source frame** (layout lock) clearly separate from Character/Scene/Prop
- Character picker never silent-fills Start unless user opts in (I2V “use as start”)
- **Advanced refs (video / audio / style)** collapsed by default (no 0/9 omni noise)
- Enhance rewrites to Image 1/2… (model citation style)
- FLUX 3: single character only; multi Add on H3 Omni / Seedance / multi-ref models

### FLUX 3 I2V — aspect hard-omit + Start vs Character slots
- **Aspect hard-omit**: `image-to-video` + `/draft` never post `aspect_ratio` (not auto); UI **Follows still** disabled; draft strip matches full
- **Slots**: **Start / source frame** (layout lock) vs **Character / identity ref(s)** — Character picker never silent-starts as start frame
- **Add character reference** on multi-ref models (Seedance reference, Grok R2V, …) with `n / max` counter; FLUX 3 stays single identity (tooltip → Keyframe Take / composite)
- Enhance: multi-ref names “character from ref 1…”, layout lock only when Start frame present
- Regression: Seedance/other models that need aspect still receive it

### Scene Placer (Character into Scene + pose)
- Focused workspace under **Characters** (not a new top-level tab): **Scene Placer** button + card **Place in scene**
- **Scenes** handoff: top **Scene Placer** + card **Place character** (prefill plate)
- Inputs: Character library (Front/hero; costumes ok) · Scene library or upload still · Pose / body language · optional **What’s happening?** (action/moment) · optional Placement hint · multi-ref Flux 2 Pro/Max (cost shown) · Enhance with identity lock (pose + action)
- Prompt contract: lock character likeness + scene architecture/lighting; only insert character + pose + action
- Result still → outputs + Library; Expand; Show in folder; Send to Resolve / Director Keyframe Take pin / Motion Sync

### Director · Keyframe Take (FLUX 3 continuous)
- New Director mode pill: **Multi-shot** | **Keyframe Take**
- Keyframe Take: ordered pins (still + time, max 10) → `blackforestlabs/flux-3/keyframes-to-video`
- Auto-spread times or manual; 5–20s · 720p/1080p · audio; Character/Scene → Add as pin
- Draft first + Enhance to full; cost live; Send to Upscale / Resolve
- How-to: Multi-shot = cuts; Keyframe Take = pose plates → continuous motion
- QoL: pin thumb expand/lightbox; Send to ▾ → Director → Keyframe Take (add/replace pin);
  Previously used strip under pins; Add from Library / disk
- Multi-shot / Kling paths unchanged

### FLUX 3 Draft + Send to Video Upscale
- **Draft first** on FLUX 3 T2V/I2V/First→Last/Extend (Studio + Creative Vision): cheaper draft preview, then **Enhance to full** via `draft-enhance` + draft_cache
- Cost labels distinguish draft vs full (~$0.06/s draft ballpark · full by resolution)
- Video results: **Send to ▾ → Video Upscale** (Director, Studio Video, Creative Vision)
- **Enhance** for FLUX 3 Video: format-first continuous-take crash course (layout lock, audio, setup→turn→payoff) — not Kling multi-shot syntax; model stays locked

### Director — identity pack ref counting
- Front only / Full pack respected: Full pack only on multi-image / element models (Grok, Kling V3)
- Single-ref (FLUX 3 I2V, First→Last, O3): force Front only; hide Full pack; never count/send Side/Close-up
- Auto: character + scene bound → Front only; budget display matches submitted refs

### FLUX 3 Video (Black Forest Labs on fal) — Phase 1 + Director Phase 2
- **Studio Video**: I2V · First→Last (start + end required) · Extend under V2V · T2V via Vision list
- **Creative Vision**: T2V · I2V · Bridge first→last · **Extend Video** (source clip + prompt)
- **Director**: **FLUX 3 · Continuous I2V** (character still → one take) and **FLUX 3 · First→Last** (Shot 1→2 stills); not a Kling multi_prompt replacement
- Controls: duration up to ~20s · 720p/1080p · generate_audio on/off · cost = $/s × duration × resolution
- Best for: long continuous I2V, first→last transitions, native audio
- How-to tip: FLUX 3 = continuous take / first→last; Kling = multi-shot cuts
- fal: `blackforestlabs/flux-3/{text,image,first-last-frame}-to-video` + `extend-video`
- Kling multi-shot / Imagine Director paths unchanged

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
- Existing Kling / Seedance 2.0 / Aleph / Veo paths unchanged (FLUX 3 wired separately above)

### Grok Imagine Video 1.5 (fal) — first-class video
- **Studio Video**: I2V + R2V (up to 7 stills; `<IMAGE_n>` tags); **Creative Vision**: T2V + I2V + Reference pack
- **Director**: Grok Imagine 1.5 · Reference storyboard (ordered shot refs → T2V / I2V / R2V single clip)
- Best-for: strong reference consistency, native audio, motion quality
- Pricing: $0.08/s @480p · $0.14/s @720p · $0.25/s @1080p (I2V/T2V) + $0.01 per ref image
- fal: `xai/grok-imagine-video/v1.5/{image,text,reference}-to-video`

### Scenes tab
- New main tab **Scenes** — reusable location / establishing stills (local `data/scenes.json` + `scene_stills/`)
- Upload or **Generate** (T2I) with establishing bias; name + notes; list thumb; Edit / Delete / Lock / Show in folder
- Character = who · Scene = where (Director multi-ref scene plates; later Motion Sync / Vision)
- **Aspect + Quality**: separate Aspect (16:9 Horizontal / 9:16 Vertical / 1:1 / 4:3 / 3:4) and Quality (1K·2K or Standard·HD); framing language in prompt; list **aspect badge** on thumbs
- **Scenes polish**: **New scene** button; enlarge still from generate/form/list; **Name** primary in list (not long prompt); broken/missing thumbs show placeholder + repair path from `scene_stills/`; taller description field; **Create variation** I2I panel (parent ref → Generate → Confirm/Regenerate/Dismiss → child under Variations)
- **Scenes plate helpers**: Setting / Type / Time / Weather / Activity (+ notes) rebuild location description; variation quick chips (Winter, Night, Rain, Golden hour, Overcast)
- **Scenes multi-angle pack**: Hero + Left(B)/Right(C); Generate / Replace / Clear; cost line; list “N angles” badge; Director Hero only vs Full pack
- **Director how-to** updated (duration → balance → Character/Scene → multi-ref packs → budget → Generate); scene pack toggle when multi-ref

### Characters tab
- New main tab **Characters** — save reusable character stills (local store only)
- **Identity pack** Front / Side / Close-up; large preview on thumb click
- **Generate profile** fills missing Front/Side/Close-up from existing stills (multi-ref, black plate)
- **New character**: upload any slot; T2I builder with helpers + sequential Close-up→Front→Side confirm
- **Remove background** (Bria RMBG) per slot or all angles; cost shown; Confirm before replace
- **Costume swap** model picker, per-slot errors, child under parent; Use in Motion Sync on both
- **Lock** protects from retention cleanup; delete parent confirms if costumes exist
- Shortcuts from Motion Sync / Director / Studio; Voice Clone stays under Audio
- **Phase 3 — Character picker**: compact **Saved character** dropdown (thumb + name; costumes as `Parent / Outfit`) on Motion Sync, Director (active shot ref), Creative Vision (start/source still), and Studio Image (I2I/R2I source). One click fills Front (or best available); Clear character unlinks picker only; Upload / Previously used / From Resolve / Library still work beside it

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
- **Aspect fix**: Kling I2V multi-shot (any shot ref) no longer sends `aspect_ratio` (not in OpenAPI — frame follows start still; UI shows **Auto (from start still)**). O3 I2V uses `image_url`; V3 uses `start_image_url`. T2V lists only `16:9` / `9:16` / `1:1`. Errors report sent vs accepted.
- **Prompt 512 + character bind**: Kling multi_prompt auto-compacts to ≤512 chars/shot (live counts; block Generate if still over). Saved character binds a real still (Front preferred) as image ref — V3 `elements`, O3 `image_url`, Grok ref list — plus identity-lock language; shot-row badge/thumb; low-res warn.
- **Per-shot Character control**: each Director shot card has its own Character (this shot) picker; multi-character across shots; **Apply character to all shots** when Same character is on.
- **Per-shot Scene ref**: Scene (this shot) picker (saved Scenes + variations); multi-ref models attach Character + Scene stills; O3 single-ref keeps Scene text-only; **Apply scene to all shots** when Same location is on.
- **Unique ref budget**: count unique assets across the job (not per-shot duplicates). Kling: character pack = 1 element + unique scenes; O3 pack = 1 (scene text-only). Imagine: Front only | Full pack (auto Front if scene bound). Refs N / max + Shots N / max — blue / amber ≥80% / red over; Generate disabled only when over, with short reason.
- **Location (text) + timing QoL**: single-ref models get per-shot Location (text) auto-filled from Scene (action stays separate). **Auto-balance shot times** splits total duration evenly; Add shot re-balances; live red timing warns; title “Shot N · Xs”.
- **Kling still size**: oversized character/scene plates auto-downscale to API-safe proxies (≤1920 long edge / ~8 MB) before upload; originals stay full-res. Image “too large” errors no longer suggest Render-in-Place video proxy.
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
