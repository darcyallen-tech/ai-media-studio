"""
Persistence for Creative Vision: subject library + user vision presets.

Stored under the outputs folder so they travel with the project.
"""

from __future__ import annotations

import json
import shutil
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from media_studio.config import ensure_output_dir

SUBJECTS_FILE = "vision_subjects.json"
PRESETS_FILE = "vision_presets.json"
SUBJECTS_DIR = "_vision_subjects"

_lock = threading.Lock()


def _root(output_dir: str | Path | None = None) -> Path:
    return ensure_output_dir(Path(output_dir) if output_dir else None)


def _subjects_path(output_dir: str | Path | None = None) -> Path:
    return _root(output_dir) / SUBJECTS_FILE


def _presets_path(output_dir: str | Path | None = None) -> Path:
    return _root(output_dir) / PRESETS_FILE


def _subject_cache(output_dir: str | Path | None = None) -> Path:
    d = _root(output_dir) / SUBJECTS_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass
class VisionSubject:
    id: str
    name: str
    notes: str = ""
    image_paths: list[str] = field(default_factory=list)
    created: str = ""
    updated: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VisionSubject:
        return cls(
            id=str(data.get("id") or ""),
            name=str(data.get("name") or "Subject"),
            notes=str(data.get("notes") or ""),
            image_paths=[str(p) for p in (data.get("image_paths") or []) if p],
            created=str(data.get("created") or ""),
            updated=str(data.get("updated") or ""),
        )

    def existing_images(self) -> list[str]:
        out: list[str] = []
        for p in self.image_paths:
            try:
                if Path(p).is_file():
                    out.append(str(Path(p).resolve()))
            except OSError:
                continue
        return out


@dataclass
class VisionPreset:
    id: str
    name: str
    prompt: str = ""
    mode: str = "text_to_video"
    model_label: str = ""
    shot_type: str = ""
    lens: str = ""
    motion: str = ""
    style_preset: str = ""
    duration: str = "8s"
    aspect: str = "16:9"
    resolution: str = "720p"
    ref_paths: list[str] = field(default_factory=list)
    subject_id: str = ""
    notes: str = ""
    created: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VisionPreset:
        return cls(
            id=str(data.get("id") or ""),
            name=str(data.get("name") or "Preset"),
            prompt=str(data.get("prompt") or ""),
            mode=str(data.get("mode") or "text_to_video"),
            model_label=str(data.get("model_label") or ""),
            shot_type=str(data.get("shot_type") or ""),
            lens=str(data.get("lens") or ""),
            motion=str(data.get("motion") or ""),
            style_preset=str(data.get("style_preset") or ""),
            duration=str(data.get("duration") or "8s"),
            aspect=str(data.get("aspect") or "16:9"),
            resolution=str(data.get("resolution") or "720p"),
            ref_paths=[str(p) for p in (data.get("ref_paths") or []) if p],
            subject_id=str(data.get("subject_id") or ""),
            notes=str(data.get("notes") or ""),
            created=str(data.get("created") or ""),
        )


def _load_json(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(raw, list):
        return []
    return [x for x in raw if isinstance(x, dict)]


def _save_json(path: Path, rows: list[dict]) -> None:
    try:
        path.write_text(
            json.dumps(rows, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass


def load_subjects(output_dir: str | Path | None = None) -> list[VisionSubject]:
    with _lock:
        rows = _load_json(_subjects_path(output_dir))
    return [VisionSubject.from_dict(r) for r in rows]


def save_subjects(
    subjects: list[VisionSubject],
    output_dir: str | Path | None = None,
) -> None:
    with _lock:
        _save_json(_subjects_path(output_dir), [s.to_dict() for s in subjects])


def find_subject(
    subject_id: str | None,
    output_dir: str | Path | None = None,
) -> VisionSubject | None:
    if not subject_id:
        return None
    for s in load_subjects(output_dir):
        if s.id == subject_id or s.name == subject_id:
            return s
    return None


def add_or_update_subject(
    *,
    name: str,
    image_paths: list[str],
    notes: str = "",
    subject_id: str | None = None,
    output_dir: str | Path | None = None,
) -> VisionSubject:
    """
    Save a subject with 3–8 reference stills (cached under outputs).

    Identity is consistency help — not a perfect lock.
    """
    name = (name or "").strip() or "Subject"
    notes = (notes or "").strip()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    sid = subject_id or uuid.uuid4().hex[:12]
    cache = _subject_cache(output_dir) / sid
    cache.mkdir(parents=True, exist_ok=True)

    kept: list[str] = []
    for i, src in enumerate(image_paths or []):
        try:
            p = Path(src)
            if not p.is_file():
                continue
            dest = cache / f"{i:02d}_{p.name}"
            if str(p.resolve()) != str(dest.resolve()):
                shutil.copy2(p, dest)
            kept.append(str(dest.resolve()))
        except OSError:
            continue
        if len(kept) >= 8:
            break

    if len(kept) < 1:
        raise ValueError("Add at least one reference still for the subject.")

    subjects = load_subjects(output_dir)
    existing = next((s for s in subjects if s.id == sid), None)
    if existing:
        existing.name = name
        existing.notes = notes
        existing.image_paths = kept
        existing.updated = stamp
        sub = existing
    else:
        sub = VisionSubject(
            id=sid,
            name=name,
            notes=notes,
            image_paths=kept,
            created=stamp,
            updated=stamp,
        )
        subjects.insert(0, sub)
    save_subjects(subjects, output_dir)
    return sub


def delete_subject(subject_id: str, output_dir: str | Path | None = None) -> bool:
    subjects = load_subjects(output_dir)
    n = len(subjects)
    subjects = [s for s in subjects if s.id != subject_id]
    if len(subjects) == n:
        return False
    save_subjects(subjects, output_dir)
    return True


def subject_choice_labels(output_dir: str | Path | None = None) -> list[str]:
    return ["(none)"] + [s.name for s in load_subjects(output_dir)]


def load_presets(output_dir: str | Path | None = None) -> list[VisionPreset]:
    with _lock:
        rows = _load_json(_presets_path(output_dir))
    return [VisionPreset.from_dict(r) for r in rows]


def save_presets(
    presets: list[VisionPreset],
    output_dir: str | Path | None = None,
) -> None:
    with _lock:
        _save_json(_presets_path(output_dir), [p.to_dict() for p in presets])


def add_vision_preset(
    preset: VisionPreset,
    output_dir: str | Path | None = None,
) -> VisionPreset:
    if not preset.id:
        preset.id = uuid.uuid4().hex[:12]
    if not preset.created:
        preset.created = datetime.now().strftime("%Y%m%d_%H%M%S")
    presets = load_presets(output_dir)
    presets.insert(0, preset)
    # Cap
    presets = presets[:40]
    save_presets(presets, output_dir)
    return preset


def delete_vision_preset(preset_id: str, output_dir: str | Path | None = None) -> bool:
    presets = load_presets(output_dir)
    n = len(presets)
    presets = [p for p in presets if p.id != preset_id]
    if len(presets) == n:
        return False
    save_presets(presets, output_dir)
    return True


def preset_choice_labels(output_dir: str | Path | None = None) -> list[str]:
    return ["(none)"] + [p.name for p in load_presets(output_dir)]
