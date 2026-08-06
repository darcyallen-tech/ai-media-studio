"""
AI Media Studio — Flet desktop entrypoint.

Run:
    python app.py

Or double-click:
    Start AI Media Studio.bat

Single-instance: if Studio is already open, a second launch (e.g. Resolve
Send) signals the primary process and exits — no second window.
"""

from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

# Optional project .env for developers; local Settings store overrides below
_ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(_ENV_PATH)

from media_studio.config import ensure_output_dir  # noqa: E402
from media_studio.flet_app import run  # noqa: E402
from media_studio.secrets_store import apply_secrets_to_env  # noqa: E402
from media_studio.single_instance import (  # noqa: E402
    register_primary_lock,
    signal_primary_instance,
    try_acquire_primary,
)


def main() -> None:
    # Local app-data keys (Settings UI) win over / fill env for this process
    apply_secrets_to_env()
    ensure_output_dir()

    # Single-instance: second launch only nudges primary (Resolve handoff)
    outcome, lock = try_acquire_primary()
    if outcome == "secondary":
        # Handoff JSON is already written by the Resolve script (or Import path).
        # Wake the primary poller, then exit without opening a UI.
        signal_primary_instance(reason="second_launch")
        print(
            "AI Media Studio is already running — "
            "signaled the open window to pick up Resolve handoff.",
            file=sys.stderr,
        )
        sys.exit(0)

    # "primary" holds lock; "unlocked" = fail soft (run without guard)
    register_primary_lock(lock)
    try:
        run()
    finally:
        if lock is not None:
            try:
                lock.release()
            except Exception:
                pass
            try:
                register_primary_lock(None)
            except Exception:
                pass


if __name__ == "__main__":
    main()
