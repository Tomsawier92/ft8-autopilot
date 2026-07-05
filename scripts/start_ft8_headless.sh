#!/bin/bash
# Éjszakai headless FT8 — óránként újraindít, log megmarad
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LINEIN_SRC="${FT8_PULSE:-alsa_input.pci-0000_00_1f.3.analog-stereo}"

pactl set-source-port "$LINEIN_SRC" analog-input-linein 2>/dev/null || true
pactl set-source-mute "$LINEIN_SRC" 0 2>/dev/null || true

SLICE="${FT8_SLICE_SECONDS:-3600}"
echo "Headless supervisor — $LINEIN_SRC @ 7.074 MHz, slice=${SLICE}s"
exec "$ROOT/.venv/bin/python" "$ROOT/scripts/ft8_headless_supervisor.py" \
  --slice-seconds "$SLICE" \
  --pulse "$LINEIN_SRC" \
  --power-safe \
  "$@"
