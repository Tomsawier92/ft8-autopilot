#!/bin/bash
# FT8 virtuális üzem — nincs rádió, szimulált dekód
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LIVE="$ROOT/forgalminaplo/live"
DISPLAY="${DISPLAY:-:1}"

mkdir -p "$LIVE"
cd "$ROOT"
nohup env DISPLAY="$DISPLAY" .venv/bin/python scripts/ft8_virtual_operator.py >> "$LIVE/virtual_nohup.log" 2>&1 &
sleep 3
nohup python3 "$ROOT/scripts/auto_ft8_watch.py" >> "$LIVE/auto_watch_nohup.log" 2>&1 &
echo "Virtuális FT8 üzem indul"
