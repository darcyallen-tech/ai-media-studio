"""Local smoke checks for enhance prompt (no live API required)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from media_studio.config import XAI_DEFAULT_MODEL
from media_studio.services import (
    _normalize_enhance_payload,
    _parse_enhance_json,
    enhance_prompt,
    load_enhance_system_prompt,
)
from media_studio.xai_client import get_client


def main() -> None:
    sys_p = load_enhance_system_prompt()
    assert "nano banana pro" in sys_p
    assert "{model_catalog}" not in sys_p
    print("system prompt OK, model=", XAI_DEFAULT_MODEL)

    sample = (
        '{\n'
        '  "optimized_prompt": "cinematic portrait, soft light",\n'
        '  "chosen_model": "nano banana pro",\n'
        '  "parameters": {"resolution": "2K", "num_images": 1, "aspect_ratio": "1:1", "other": {}},\n'
        '  "notes": ["clamped 4K to 2K"]\n'
        "}"
    )
    data = _parse_enhance_json(sample)
    result = _normalize_enhance_payload(data, "raw")
    assert result.chosen_model == "nano banana pro"
    assert result.parameters["resolution"] == "2K"
    print("parse OK")

    # Missing key path
    saved = os.environ.pop("XAI_API_KEY", None)
    get_client.cache_clear()
    res = enhance_prompt("make it blue", "Auto (default)")
    assert not res.ok
    assert "XAI_API_KEY" in res.status
    print("missing key handled:", res.status[:90])

    if saved:
        os.environ["XAI_API_KEY"] = saved
    get_client.cache_clear()

    build_ui()
    print("UI builds OK")
    print("ALL SMOKE CHECKS PASSED")


if __name__ == "__main__":
    main()
