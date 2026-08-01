# AI Media Studio

Local **Flet** desktop app for real-estate–focused AI **image**, **video**, and **audio** work.

Stage empties, lock camera moves, clean noisy clips, generate Foley, run cinematic Vision shots, and send results to **DaVinci Resolve** — pay only for what you generate.

**Built with Grok 4.5.**

| Provider | Role |
|----------|------|
| **fal.ai** | Main generation (Studio, Tools, Creative Vision, Audio; Frame Editor 1080p proxy) |
| **xAI** | Optional — Grok Enhance / QC |
| **Runware** | Optional — Frame Editor / Aleph 2.0 only |

Capability list: **[FEATURES.txt](FEATURES.txt)**. This README is the install source of truth.

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
3. Upload a still or clip and Generate.

Reopen the wizard anytime: top bar **?** → **Quick Start**.  
Also: **?** → Open FEATURES.txt / README.md.

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
| **Tools** | Image \| Video tools + large result viewer (upscale, **Denoise**, **Slow Mo**, cleanup, sky, …) |
| **Creative Vision** | Cinematic T2V / I2V / bridge (expensive playground) |
| **Frame Editor** | Aleph 2.0 keyframe edit via **Runware** + optional fal 1080p proxy |
| **Audio** | Music, SFX, Ambience, VO, Voice clone, **Video → SFX** |
| **Library** | History; Send to Studio / Tools / Frame Editor / Resolve |

---

## Resolve integration (optional)

### Studio → Resolve

**Send to Resolve** on results (Media Pool bin for the day).  
Requires Resolve Studio with **External scripting = Local**.

### Resolve → Studio

1. Copy `resolve_scripts/Send_to_AI_Media_Studio.py` into Resolve’s Utility scripts folder  
   (Windows: `%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Utility\`).
2. **Studio path is auto-detected** — no personal path is hard-coded:
   - Env `AI_MEDIA_STUDIO_ROOT`, or  
   - `studio_root.txt` next to the script (see `studio_root.txt.example`), or  
   - Path registered when you open AI Media Studio once.
3. Prefer **Render in Place** before send.
4. In Studio: auto-import or **Import from Resolve**.

Details: [resolve_scripts/README.md](resolve_scripts/README.md).  
Handoff: `data/resolve_handoff/` (auto-purge ~7 days; Settings → Clear handoff cache).

---

## Sharing / clean clone

**Do not commit or zip:**

- `outputs/` (generations, caches)
- `data/resolve_handoff/`
- `.env` (secrets)
- `data/voice_samples/`, personal `AUDIT_REPORT*.txt`

`.gitignore` already excludes these. Recipients: clone → `start.bat` / `start.sh` → Settings → keys.

---

## Layout (quick)

- Top: Settings, **Help (?)**, fal / Runware / xAI chips, Import from Resolve, output folder  
- App-level **scenario** bar  
- Main tabs: Studio · Tools · Creative Vision · Frame Editor · Audio · Library  

Storage prefs (output path, retention, clear caches, cost guard) live in **Settings**.

---

## Media notes

- **Audio Play** — in-process via `pygame-ce` where supported  
- **Video preview** — `flet-video` when available  
- **Linux:** install libmpv if inline video fails  

For scenario names, tool lists, and feature detail, see **FEATURES.txt**.
