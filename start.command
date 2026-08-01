#!/usr/bin/env bash
# AI Media Studio — macOS double-click launcher
# (Terminal opens; close the window after quit.)
set -e
cd "$(dirname "$0")"

echo ""
echo " AI Media Studio"
echo " ---------------"
echo ""

if [ ! -x ".venv/bin/python" ]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

if ! python -c "import flet, PIL, cv2, fal_client, httpx, openai, dotenv, pygame" >/dev/null 2>&1; then
  echo "Installing / updating dependencies..."
  python -m pip install --upgrade pip >/dev/null 2>&1 || true
  python -m pip install -r requirements.txt
else
  echo "Dependencies already satisfied — skipping pip install."
fi

echo ""
echo "Launching desktop app..."
python app.py
STATUS=$?
if [ "$STATUS" -ne 0 ]; then
  echo ""
  echo "App exited with code $STATUS."
  read -r -p "Press Enter to close…"
fi
exit "$STATUS"
