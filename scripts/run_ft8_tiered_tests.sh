#!/usr/bin/env bash
# FT8 rétegzett tesztsorozat — 16 mag optimális kihasználás
# CUDA: csak CW/ML (Tier D), FT8 PyFT8 = CPU
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT"
PY="$ROOT/.venv/bin/python3"
PYTEST="$ROOT/.venv/bin/pytest"
NCPU="${NCPU:-$(nproc)}"
# FT8 integrációs tesztek: ne legyen túl sok worker (I/O, thread)
N_FT8="${N_FT8:-$(( NCPU > 8 ? 8 : NCPU ))}"
# Párhuzamos unit/sim: agresszívabb
N_FAST="${N_FAST:-$NCPU}"

_run() {
  echo ""
  echo "══════════════════════════════════════════"
  echo "  $*"
  echo "══════════════════════════════════════════"
}

if ! "$PY" -c "import xdist" 2>/dev/null; then
  echo "pytest-xdist telepítése (párhuzamos Tier A–C)…"
  "$ROOT/.venv/bin/pip" install -q pytest-xdist
fi

_run "Tier A — gyors unit + protokoll + slot (${N_FAST} worker, ~10 s)"
"$PYTEST" tests/test_ft8_slot.py tests/test_ft8_protocol.py \
  tests/test_qso_protocol.py tests/test_qso_controller.py \
  -n "$N_FAST" -q --dist loadscope

_run "Tier B — 50 pont + log forgatókönyvek (${N_FAST} worker, ~15 s)"
"$PYTEST" tests/test_ft8_behavior_50.py tests/test_ft8_log_scenarios.py \
  -n "$N_FAST" -q --dist loadscope

_run "Tier C — PRO + chaos / meta (${N_FT8} worker, ~30–120 s)"
"$PYTEST" tests/test_ft8_pro.py tests/test_ft8_chaos.py \
  -n "$N_FT8" -q --dist loadscope

_run "Tier D — napló bányászat (${NCPU} process, CPU)"
"$PY" "$ROOT/scripts/ft8_log_mine_parallel.py" --workers "$NCPU" --days 2

_run "Tier E — TX slot audit (élő napló, szekvenciális)"
if [[ -f "$ROOT/forgalminaplo/live/tx.log" ]]; then
  "$PY" "$ROOT/scripts/audit_tx_slots.py" | tail -5
else
  echo "(tx.log nincs — kihagyva)"
fi

_run "Tier F — PTT szimuláció ping (opcionális hardver)"
if [[ -e /dev/ttyUSB0 ]]; then
  "$PY" -c "
from cw_discover.ft8.ptt_client import Esp32Ptt
p = Esp32Ptt('/dev/ttyUSB0')
print('PING', p.ping())
" || echo "PTT ping sikertelen (rádió/GUI fut?)"
else
  echo "(/dev/ttyUSB0 nincs — kihagyva)"
fi

_run "Tier G — headless stressz (${NCPU} worker, virtuális QSO)"
"$PY" "$ROOT/scripts/ft8_stress_parallel.py" --workers "$NCPU" --pre-live

echo ""
echo "✓ Rétegzett FT8 tesztsorozat kész."
