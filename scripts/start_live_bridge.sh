#!/bin/bash
# FT8 + operátor élő híd — AI menedzseléshez
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LIVE="$ROOT/live"
mkdir -p "$LIVE"
echo "FT8 live bridge → $LIVE/"
exec python3 "$ROOT/scripts/ft8_live_bridge.py"
