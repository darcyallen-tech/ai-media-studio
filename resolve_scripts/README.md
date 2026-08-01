# Resolve → AI Media Studio

Send the **current timeline clip** (still + media path) from **DaVinci Resolve Studio** into **AI Media Studio**.

**This script does not render.** Rendering is a manual step in Resolve.

## Setup (Windows)

1. **Copy the script** into Resolve’s Utility scripts folder:

   ```
   %APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Utility\
   ```

   File: `Send_to_AI_Media_Studio.py` (from this folder).

2. **How the Studio project path is found** (no personal path is hard-coded in the script):

   | Priority | Source |
   |----------|--------|
   | 1 | Environment variable **`AI_MEDIA_STUDIO_ROOT`** → folder that contains `app.py` |
   | 2 | **`studio_root.txt`** next to the script (one line = full path to the Studio folder). See `studio_root.txt.example`. |
   | 3 | **`%LOCALAPPDATA%\AI Media Studio\studio_root.txt`** — written automatically when you open the desktop app |
   | 4 | If the script still lives under `<project>\resolve_scripts\`, the parent project folder is used |

   **Recommended:** Launch **AI Media Studio** once on the machine so step 3 registers the path, then run the Resolve script.

3. **Preferences → System → General → External scripting = Local**.

4. Restart Resolve if the script does not appear under **Workspace → Scripts**.

## Workflow

1. Open a project and timeline; grade the clip as usual.
2. **Render in Place** (or Deliver + replace the clip) so the timeline item points at a **graded, smaller** file — not the camera master.
3. Park the playhead on that clip (Edit or Color).
4. **Workspace → Scripts → Send_to_AI_Media_Studio**.
5. In AI Media Studio: auto-import, or click **Import from Resolve**.

| Sent | Source |
|------|--------|
| **Still** | Playhead frame (exported PNG into the handoff folder) |
| **Video** | Clip’s **current media path** (whatever Resolve has linked after RIP) |

Still → Image source (+ Video reference).  
Video path → Studio → Video **Source video**.

## Handoff folder

```
<AI Media Studio>/data/resolve_handoff/
  latest.json
  handoff_*.json
  handoff_*_still.png
```

Old handoff files are **auto-purged** by the desktop app (about **7 days** or **~200** files).  
Settings → **Clear handoff cache** removes artifacts only inside this folder.

Example JSON:

```json
{
  "id": "handoff_20260730_120000",
  "clip_name": "C0362_RIP",
  "still_path": ".../handoff_..._still.png",
  "video_path": "D:/Project/Renders/C0362_RIP.mp4",
  "source": "davinci_resolve"
}
```

## Tips

- If the selected media is **very large** (e.g. 150 MB+ camera master), the script warns:  
  **Please Render in Place first for a graded, smaller proxy.**
- Generators / titles often have **no file path** — RIP or use a media clip.
- Reverse direction (Studio → Resolve) remains **Send to Resolve** on result panels.
