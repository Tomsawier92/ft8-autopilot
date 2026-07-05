#!/bin/bash
# CW stack a :1 kijelzőn
set -e
export DISPLAY=:1

pkill -x ggmorse-gui 2>/dev/null || true
pkill -f "cw-discover/scripts/run_gui.py" 2>/dev/null || true
sleep 0.3

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if ! pgrep -f "run_cw_gate_bridge.py" >/dev/null; then
  nohup "$ROOT/.venv/bin/python" "$ROOT/scripts/run_cw_gate_bridge.py" >>/tmp/cw-gate-bridge.log 2>&1 &
fi

nohup "${HOME}/.local/bin/ggmorse-gui" >>/tmp/ggmorse-gui.log 2>&1 &
nohup "$ROOT/.venv/bin/python" "$ROOT/scripts/run_gui.py" >>/tmp/cw-discover-gui.log 2>&1 &
sleep 1

# Ablak előtérbe (ha van wmctrl)
if command -v wmctrl >/dev/null; then
  sleep 1
  wmctrl -l 2>/dev/null | head -20
  wmctrl -a "GGMorse" 2>/dev/null || true
  wmctrl -a "CW Mintázatfelismerő" 2>/dev/null || true
fi

pgrep -af "ggmorse-gui|run_gui.py|run_cw_gate_bridge" | grep -v grep || true
