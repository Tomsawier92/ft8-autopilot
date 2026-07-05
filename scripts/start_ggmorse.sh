#!/bin/bash
# GGMorse — line-in (ggmorse_linein) alapértelmezés, zajkapu nélkül
export DISPLAY=:1

LINEIN_SRC="alsa_input.pci-0000_00_1f.3.analog-stereo"

pkill -x ggmorse-gui 2>/dev/null || true
pkill -f "run_gate_gui.py" 2>/dev/null || true
pkill -f "run_cw_gate_bridge.py" 2>/dev/null || true
sleep 0.3

# Line-in port + tiszta remap (ugyanaz az útvonal mint jack-probe)
pactl set-source-port "$LINEIN_SRC" analog-input-linein 2>/dev/null || true
pactl unload-module module-remap-source 2>/dev/null || true

nohup "${HOME}/.local/bin/ggmorse-gui" >>/tmp/ggmorse-gui.log 2>&1 &
sleep 1
echo "GGMorse indul — bemenet: $LINEIN_SRC (line-in / GGMorse LineIn)"
echo "Settings → Capture: ◆ Vonalbemenet (line-in)"
pgrep -af "ggmorse-gui" | grep -v grep || true
