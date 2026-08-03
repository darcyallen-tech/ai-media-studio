# AI Media Studio

Local **Flet** desktop app for real-estate–focused AI **image**, **video**, and **audio** work.

Stage empties, invent stills then bridge them, lock camera moves, clean noisy clips, generate Foley, run cinematic Vision shots, and send results to **DaVinci Resolve** — pay only for what you generate.

**Built with Grok 4.5.**

| Provider | Role |
|----------|------|
| **fal.ai** | Main generation (Studio, Tools, Creative Vision, Audio; Frame Editor 1080p proxy) |
| **xAI** | Optional — Grok Enhance / QC |
| **Runware** | Optional — Frame Editor / Aleph 2.0 only |

Capability list: **[FEATURES.txt](FEATURES.txt)**. What’s new: **[RELEASE_NOTES.md](RELEASE_NOTES.md)**. This README is the install source of truth.

**Hard rule:** Any user-visible change must update **README.md**, **FEATURES.txt**, and **RELEASE_NOTES.md** as needed (see [AGENTS.md](AGENTS.md)).

**License:** [MIT](LICENSE)

---

## Requirements

- **Python 3.10+** (3.11–3.14 fine)
- Network access for fal / xAI / Runware APIs
- Optional: DaVinci Resolve Studio (Local scripting) for Send/Import
- **Linux video preview:** if inline video fails, install `libmpv` (`sudo apt install libmpv-dev mpv`)

---

## Install

```bash
git clone <your-repo-url> ai-media-studio
cd ai-media-studio
python -m venv .venv   # or python3 -m venv .venv
```

### Windows

```bat
.venv\Scripts\activate
pip install -r requirements.txt
```

Or double-click **`start.bat`** (creates venv, installs if needed, launches).

### macOS

```bash
source .venv/bin/activate
pip install -r requirements.txt
chmod +x start.command start.sh   # once
```

Double-click **`start.command`**, or run `./start.sh`.

### Linux

```bash
source .venv/bin/activate
pip install -r requirements.txt
chmod +x start.sh
./start.sh
```

Launchers **skip `pip install`** when core packages already import.

### Manual run

```bash
python app.py
```

---

## First run

1. Launch the app → **Quick Start** wizard (first launch).
2. **Settings** (gear) → paste API keys for this machine only.
3. Upload a still or clip and Generate — or start in **Creative Vision → Text → Image** and Send to Start/End for a bridge.

Reopen the wizard anytime: top bar **?** → **Quick Start**.  
Also: **?** → Check for updates… / Open FEATURES.txt / README.md.

**Updates:** on startup (default on, Settings → Storage), the app quietly compares **APP_VERSION** and **git SHA** with [darcyallen-tech/ai-media-studio](https://github.com/darcyallen-tech/ai-media-studio) (release tag first, then latest commit SHA). Same-day commits alone do not flag “behind.” Banner only when remote is actually newer — no auto-download. Offline checks fail silently.

---

## API keys (none shipped)

Keys live in **local app data** via Settings. Developers may use a project `.env` from **`.env.example`**; Settings values win when present.

| Key | Env names | Required? | Used for |
|-----|-----------|-----------|----------|
| **fal** | `FAL_KEY` or `FAL_API_KEY` | **Yes** for almost all generation | Studio, Tools, Vision, Audio, FE proxy |
| **xAI / Grok** | `XAI_API_KEY` | Optional | Enhance, QC |
| **Runware** | `RUNWARE_API_KEY` or `RUNWARE_KEY` | Optional | **Frame Editor / Aleph only** |

### Notes

- **Grok Imagine** models on **fal** bill via the **fal** key, not xAI.
- **fal balance** in the top bar needs an **Admin-scoped** fal key. A normal key still generates.
- **Frame Editor** often needs **two** keys when auto-downscaling: fal (proxy) + Runware (Aleph).

Dashboards:

- [fal keys](https://fal.ai/dashboard/keys)
- [xAI keys](https://console.x.ai/team/default/api-keys)
- [Runware](https://my.runware.ai/)

---

## Tabs (current product)

| Tab | What it does |
|-----|----------------|
| **Studio** | Image (scenarios, Region edit, compare) · Video (Received / Blank / Camera Lock) |
| **Tools** | Image \| Video tools + large result viewer (upscale, **Inpaint**, **Denoise**, **Slow Mo**, cleanup, sky, …) |
| **Creative Vision** | **Text → Image**, **Image → Image**, Text → Video, Image → Video, Bridge / Connect |
| **Director** | Multi-shot storyboard: master brief, ordered shots, camera presets, ref stills per shot, cut/continuous transitions |
| **Frame Editor** | Aleph 2.0 keyframe edit via **Runware** + optional fal 1080p proxy |
| **Audio** | Music, SFX, Ambience, VO, Voice clone, **Video → SFX** |
| **Library** | History; filters including **From Resolve**; Send to Studio / Tools / Frame Editor / Resolve |

### Creative Vision highlights

- **Text → Image** — invent stills (no source). Still-only helpers (framing / lens / lighting / style); **no camera motion** on rebuild or Enhance. T2I models include Flux family, **Nano Banana** / 2 / Pro, **Seedream** 4.5 / 5 Lite / 5 Pro, Recraft (see FEATURES.txt). **# Images 1–4** multi-variant; **cost always × count** (including sequential singles); separate Library rows; sequential if the API is one-at-a-time (per-tab busy only).
- **Studio Image** — same 1–4 multi-variant pattern when generating edits. Est. cost scales with **# Images** even when the model max is 1 per call (e.g. Flux 2 Pro · 4 images → ~4× rate). Multi-reference stills when the model allows (primary + optional refs); single-image models stay one still. Region edit uses the annotated primary only; box L/T/W/H map to the source image content rect on both the small preview and large Comparison stage. **Previously used** + **From Resolve** stills.
- **Image → Image** — creative plate edits with optional **multi-ref** (primary + up to 3 refs for identity/material/furniture on multi-image models; single-image models hide extras). Same still helpers; From Resolve / Previously used for source or refs; Enhance names ref roles in the prompt.
- T2I / still results: **Send to ▾ → Start frame / End frame** (bridge handoff) without re-exporting from disk.
- Every helper that feeds Rebuild/Enhance has **(None)** — omit that dimension. Same pattern in Studio scene builders and Audio builders where helpers inject text.
- **Creative direction for Enhance** (optional) — steers Grok Enhance only; **not** sent raw on Generate. Empty = helpers + prompt only.
- Frame Editor ↔ Vision: **I2I source**, Start / End / I2V; I2I results pin back as **Frame Editor · keyframe**.
- Cost labels are **job totals** (e.g. Veo standard ~$0.40/s × duration, Fast ~$0.15/s × duration on fal).
- **MiniMax H3 (Hailuo-03)** — T2V · I2V first/last frame · **Omni reference** (up to 9 stills + 3 clips + 3 audio; cite Image 1 / Video 1 / Audio 1). Native stereo · 2K · ~$0.26/s. Also in Studio Video model list.
- **Grok Imagine Video 1.5** (fal) — T2V · I2V · R2V (up to 7 stills, `<IMAGE_n>` tags); native audio; also Director reference storyboard. Est. ~$0.08–0.25/s by resolution + $0.01/ref.

### Frame Editor highlights

- **Edit intent**: Apply through clip · Transition first→last · Custom timestamps (UI helper only — Aleph still gets first/last/timestamp pins + prompt).
- Dense **filmstrip** (more samples on short clips; scroll on long); click to preview, Pin frame for a slot.
- **Result playback**: full CONTAIN in-app video with play/pause; Show in folder / Send to Resolve stay under the player.
- Day→night style transitions: pin day @ **first**, night @ **last**, transition prompt / Enhance.

### Tools highlights

- **Inpaint (freehand)** — 3-column UI; brush/eraser; zoom/pan; Grow mask 0–8 px; **# Images 1–4** (cost × N); optional/required **ref still** per model; mask 1:1 with source; mask-capable models only (Pro Fill, LoRA Fill, Dev, Kontext LoRA, Juggernaut — not Nano Banana / Flux 2 edit).
- Model dropdowns show a short **Best for:** line under the selection (tooltip for more detail).
- **From Resolve** strips on image + video tool forms (with Previously used).

### Tools video extras

- **Denoise / Clean** — Topaz Nyx / Artemis (control-driven).
- **Slow Mo / Interpolate** — RIFE (default) or FILM; 2×–5×.

### Audio highlights

- **Layered SFX mixer** — Bed / Spot / Accent with plain labels + intent helpers; generate or load; **Load from Video → SFX** into a layer; mute + volume; **Bounce mix** (optional stems); Send to Resolve. Additive (not a DAW).

Full tool and model lists: **FEATURES.txt**.

---

## Resolve integration (optional)

### Studio → Resolve

**Send to Resolve** on results (DaVinci Resolve logo on the button). With Resolve Studio open and a project loaded (**External scripting = Local**):

1. Import into Media Pool bin **`AI Media Studio / <Job name or today’s date>`**
2. Optionally place on **video track V2** (preference; default 2) at the **playhead** when the API allows
3. Optional **timeline/clip marker** with a short note (model, scenario, cost when known from history)

If Resolve is closed or scripting fails: the file stays on disk and its folder is revealed — the app does not crash.  
Does **not** render-in-place, create compounds, auto-transitions, or bake grade.

### Resolve → Studio

1. Copy `resolve_scripts/Send_to_AI_Media_Studio.py` into Resolve’s Utility scripts folder  
   (Windows: `%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Utility\`).
2. **Studio path is auto-detected** — no personal path is hard-coded:
   - Env `AI_MEDIA_STUDIO_ROOT`, or  
   - `studio_root.txt` next to the script (see `studio_root.txt.example`), or  
   - Path registered when you open AI Media Studio once.
3. Prefer **Render in Place** before send.
4. In Studio: auto-import or **Import from Resolve**.

**From Resolve** recent strips appear wherever media can load (Studio Image/Video, Tools, Vision, Frame Editor). Imports are stored in **Library** with a **Resolve** badge and a **From Resolve** filter (`origin=resolve`).

**Single-instance:** a second launch (e.g. Resolve Send) focuses the open window instead of starting a second app.

Details: [resolve_scripts/README.md](resolve_scripts/README.md).  
Handoff: `data/resolve_handoff/` (auto-purge ~7 days; Settings → Clear handoff cache).

---

## Settings (storage & safety)

| Preference | Notes |
|------------|--------|
| **Output folder** | Persisted across sessions |
| **Retention** | Never / 7 / 14 / 30 / 90 days for Library media under the app output tree |
| **Clear caches** | App-owned dirs only (previews, proxies, upload temp, handoff) — not arbitrary paths |
| **Hide missing** | Library can hide rows whose files are gone |
| **Cost guard** | Optional confirm when a generate estimate is ≥ $2 or ≥ $5 (default off) |

Long jobs use **per-tab busy** scopes so one generate does not lock the whole app.

---

## Sharing / clean clone

**Do not commit or zip:**

- `outputs/` (generations, caches)
- `data/resolve_handoff/`
- `.env` (secrets)
- `data/voice_samples/`, local `Reports/` (audits; gitignored)

`.gitignore` already excludes these. Recipients: clone → `start.bat` / `start.sh` → Settings → keys.

---

## Layout (quick)

- Top: Settings, **Help (?)**, fal / Runware / xAI chips, Import from Resolve, output folder  
- App-level **scenario** bar + optional **Job / Listing** field  
- Main tabs: Studio · Tools · Creative Vision · Director · Frame Editor · Audio · Library  

### Job / Listing folders

Optional field (address, client, shoot date) shared by all generate surfaces. Last value is remembered.

| Job name | Where media lands |
|----------|-------------------|
| Empty | `outputs/YYYY-MM-DD/…` (default) |
| Set | `outputs/jobs/<safe-name>/YYYY-MM-DD/…` |

Library can filter or group by job; cards show the job label. Media filters: **All | Image | Video | Audio | From Resolve**. Handoff imports show a **Resolve** chip in All. History JSON stays at the output root. No cloud sync.

**Assign later:** each Library card has **Assign to ▾** (Image / Video / Audio). Pick an existing job, **New Job / Listing…**, or **Clear job (Ungrouped)**. Metadata always updates so filters and grouping work; files under the output folder are moved into `jobs/<slug>/…` when safe. Paths outside the output root stay put.

**Bulk actions:** check multiple cards → bulk bar → **Assign to ▾** (same menu) and/or **Send to Resolve** (Tier A per item; mixed types OK; continues on failures with a summary snack). Single-card menus stay unchanged.

### Prompt favorites + packs

- **★ Star** saves the current prompt (user or post-Enhance) under app data  
- **Favorites** dropdown + **Apply** reloads into the prompt box (Studio, Vision, Tools, Frame Editor, Audio)  
- **Export / Import pack** (JSON) on Studio Image and Music — small name + prompts + optional scenario tags; not a marketplace  

### Local spend

Library (and Settings) show a **local spend** summary from generation history: today / week / month / all-time totals, top models, and provider buckets. Uses the cost labels already logged per generate — no extra billing APIs. Rows with missing or $0 cost are skipped.

### Before / after export (stills)

On **Studio Image** and **Tools** image results with a known source still: **Export before/after ▾** builds a labeled side-by-side or vertical phone stack and saves it under the current job/dated output folder. Video before/after is not included yet.

Storage prefs (output path, retention, clear caches, cost guard) live in **Settings**.

---

## Media notes

- **Audio Play** — in-process via `pygame-ce` where supported  
- **Video preview** — `flet-video` when available  
- **Linux:** install libmpv if inline video fails  

For scenario names, tool lists, T2I models, Veo rates, and feature detail, see **FEATURES.txt**.
