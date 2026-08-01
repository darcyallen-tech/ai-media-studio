"""
AI Media Studio — Flet desktop entrypoint.

Run:
    python app.py

Or double-click:
    Start AI Media Studio.bat
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

# Optional project .env for developers; local Settings store overrides below
_ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(_ENV_PATH)

from media_studio.config import ensure_output_dir  # noqa: E402
from media_studio.flet_app import run  # noqa: E402
from media_studio.secrets_store import apply_secrets_to_env  # noqa: E402


def main() -> None:
    # Local app-data keys (Settings UI) win over / fill env for this process
    apply_secrets_to_env()
    ensure_output_dir()
    run()


if __name__ == "__main__":
    main()
