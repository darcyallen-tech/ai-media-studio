"""Smoke test: Flet app imports and Studio image prompt/cost builders."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")


def main() -> None:
    assert importlib.util.find_spec("media_studio.ui") is None, "Gradio ui.py still present"
    assert importlib.util.find_spec("media_studio.studio_ui") is None

    from media_studio.flet_app import StudioImageView, StudioState, main as flet_main
    from media_studio.flet_audio import AudioView
    from media_studio.flet_tools import ToolsView
    from media_studio.flet_video import StudioVideoView
    from media_studio.params_ui import build_parameters_dict, control_options, parameters_to_json
    from media_studio.pricing import live_estimate_cost
    from media_studio.scenarios import (
        DEFAULT_IMAGE_MODEL,
        DEFAULT_VIDEO_EDIT_MODEL,
        build_scenario_prompt,
        build_video_ref_prompt,
        scenario_choices,
    )
    from media_studio.scene_builder import styles_for_room
    from media_studio.music_builder import build_music_prompt, subgenres_for
    from media_studio.sfx_builder import build_sfx_prompt

    assert "Furniture Pop-in" in scenario_choices()
    assert "Landscaper" in scenario_choices()
    styles = styles_for_room("Living Room")
    assert "Modern" in styles
    prompt = build_scenario_prompt(
        "furniture_popin",
        room_type="Living Room",
        style="Modern",
        furniture_density="Balanced",
        decor_amount="Light",
        plants="Light",
        camera_feel="Natural",
    )
    assert "living room" in prompt.lower() or "Living" in prompt or "stage" in prompt.lower()
    vprompt = build_video_ref_prompt("furniture_popin")
    assert len(vprompt) > 20
    land_v = build_video_ref_prompt("landscaper")
    assert "@Image1" in land_v and "landscap" in land_v.lower()
    assert "Rock" not in subgenres_for("Ambient")
    assert "Grunge" in subgenres_for("Rock")
    assert "whoosh" in build_sfx_prompt().lower() or "Whoosh" in build_sfx_prompt() or "sound" in build_sfx_prompt().lower()
    assert build_music_prompt(genre="Ambient", subgenre="Chillout", era="Modern", tempo="Slow", instrumental=True)

    opts = control_options(DEFAULT_IMAGE_MODEL)
    pj = parameters_to_json(
        build_parameters_dict(
            resolution=opts["resolution_value"],
            num_images=opts["num_images_value"],
            strength=0.6,
        )
    )
    cost = live_estimate_cost(model_choice=DEFAULT_IMAGE_MODEL, parameters_json=pj)
    assert cost.startswith("Est. cost:")
    assert DEFAULT_VIDEO_EDIT_MODEL.startswith("Video")

    class FakePage:
        def __init__(self):
            self.services = []
            self.overlay = []
            self._dialogs = []

        def update(self): pass
        def add(self, *c): pass
        def show_dialog(self, dialog):
            dialog.open = True
            self._dialogs.append(dialog)
        def pop_dialog(self):
            if self._dialogs:
                d = self._dialogs.pop()
                d.open = False
                return d
            return None

    from media_studio.flet_progress import JobProgress, classify_progress
    from media_studio.flet_audio_player import AudioResultBar
    from media_studio.folder_util import show_in_folder
    from media_studio.flet_dialogs import show_dialog, close_dialog, show_snack
    from media_studio.flet_pickers import (
        IMAGE_EXTS,
        VIDEO_EXTS,
        PickedFile,
        ensure_file_picker,
        _paths_to_picked,
    )

    assert classify_progress("Uploading file…") == "Uploading…"
    assert classify_progress("In queue") == "Queued…"
    assert classify_progress("Generating image") == "Generating…"
    assert classify_progress("Saving output") == "Saving…"

    page = FakePage()
    # Desktop pickers never mount a Flet FilePicker (no Unknown control)
    assert ensure_file_picker(page) is None
    assert "mp4" in VIDEO_EXTS and "png" in IMAGE_EXTS
    sample = _paths_to_picked([str(ROOT / "app.py")])
    assert sample and isinstance(sample[0], PickedFile) and sample[0].path
    assert sample[0].name == "app.py"

    state = StudioState()
    img = StudioImageView(page, state)
    assert img.build()
    assert hasattr(img, "job_progress")
    vid = StudioVideoView(page, state)
    assert vid.build()
    assert hasattr(vid, "job_progress")
    tools = ToolsView(page, state)
    assert tools.build()
    audio = AudioView(page, state)
    assert audio.build()
    # Music wider fields + progress + player wired
    assert audio.mu_lyrics is not None and audio.mu_prompt is not None
    assert audio.mu_progress is not None and audio.mu_player is not None
    assert audio.sfx_player is not None and audio.vo_player is not None
    assert audio.cl_player is not None and audio.vs_player is not None
    assert audio.ambience_card is not None and audio.amb_player is not None
    assert audio.amb_prompt is not None
    assert hasattr(vid, "video_player")
    assert vid.video_player.control is not None
    from media_studio.flet_audio_player import (
        mixer_play,
        mixer_stop,
        open_with_system_player,
        _ensure_mixer,
    )
    from media_studio.resolve_export import send_file_to_resolve, default_bin_name

    assert "AI Media Studio" in default_bin_name()
    # Without Resolve running, send should fail gracefully (not crash)
    r = send_file_to_resolve(str(ROOT / "app.py"))
    assert r.ok is False and r.message
    assert hasattr(audio.mu_player, "btn_resolve")
    assert hasattr(vid.video_player, "btn_resolve")

    # Mixer init (may work without a real device in CI; skip hard fail on init)
    ok, _err = _ensure_mixer()
    # Path validation always works
    assert "not found" in mixer_play(str(ROOT / "no-such-audio.mp3")).lower()
    mixer_stop()
    assert "empty" in open_with_system_player("").lower() or "path" in open_with_system_player("").lower()

    prog = JobProgress()
    prog.start("Queued…")
    assert prog.active
    prog.finish_ok("Done")
    assert not prog.active
    bar = AudioResultBar(page)
    assert bar.control is not None
    # show_in_folder empty path is safe
    assert "empty" in show_in_folder(None).lower() or "path" in show_in_folder("").lower()

    assert callable(flet_main)
    print("smoke_flet OK")
    print("  default image model:", DEFAULT_IMAGE_MODEL)
    print("  default video model:", DEFAULT_VIDEO_EDIT_MODEL)
    print("  cost:", cost)
    print("  image prompt sample:", prompt[:80], "…")
    print("  video prompt sample:", vprompt[:80], "…")
    print("  progress + audio players wired")



if __name__ == "__main__":
    main()
