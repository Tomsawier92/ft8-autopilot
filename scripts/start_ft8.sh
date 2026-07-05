#!/bin/bash
# FT8 vétel GUI — FT-817 line-in, PyFT8 LDPC dekóder
export DISPLAY="${DISPLAY:-:1}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LINEIN_SRC="alsa_input.pci-0000_00_1f.3.analog-stereo"

pactl set-source-port "$LINEIN_SRC" analog-input-linein 2>/dev/null || true
pactl set-source-mute "$LINEIN_SRC" 0 2>/dev/null || true

echo "FT8 GUI — bemenet: $LINEIN_SRC, dial: 7.074 MHz USB (40m)"
exec "$ROOT/.venv/bin/python" "$ROOT/scripts/run_ft8_gui.py"
