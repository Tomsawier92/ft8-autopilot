#!/bin/bash
# Éjszakai figyelés — supervisor + élő állapot terminál (Ctrl+C = stop)
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LINEIN_SRC="${FT8_PULSE:-alsa_input.pci-0000_00_1f.3.analog-stereo}"
pactl set-source-port "$LINEIN_SRC" analog-input-linein 2>/dev/null || true
pactl set-source-mute "$LINEIN_SRC" 0 2>/dev/null || true
exec "$ROOT/.venv/bin/python" "$ROOT/scripts/overnight_watch.py"
