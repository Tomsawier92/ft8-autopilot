#!/usr/bin/env bash
# Mély teszt — ritka flag-ek amiket szinte senki nem futtat együtt.
# Használat: ./scripts/deep_chaos_ft8.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"

export PYTHONFAULTHANDLER=1
export PYTHONDEVMODE=1
export PYTHONMALLOC="${PYTHONMALLOC:-debug}"
export PYTHONWARNINGS="error::ResourceWarning,error::DeprecationWarning"

echo "=== 1/5 pytest (warnings=errors, dev mode, malloc debug) ==="
"$PY" -W error::ResourceWarning -W error::DeprecationWarning -m pytest tests/ -v --tb=short -q

echo "=== 2/5 fault injection (synthetic chaos) ==="
"$PY" scripts/deep_fault_inject.py

echo "=== 3/5 pytest repeat x20 (order shuffle, flake hunt) ==="
for i in $(seq 1 20); do
  "$PY" -m pytest tests/test_ft8_chaos.py tests/test_stability.py -q --tb=line -p no:cacheprovider \
    || { echo "flake on iteration $i"; exit 1; }
done

echo "=== 4/5 audio benchmark sanity ==="
"$PY" scripts/benchmark_audio.py

echo "=== 5/5 live 45s headless (optional RF) ==="
"$PY" scripts/monitor_ft8_live.py -t 45 --power-safe || true

echo "=== 6/6 Qt fatal warnings (GUI regresszió — hal meg minden rejtett Qt hiba) ==="
DISPLAY="${DISPLAY:-:1}" QT_FATAL_WARNINGS=1 "$PY" -m pytest tests/test_ft8_chaos.py::test_pro_ui_toggle_no_crash -v --tb=short -q

echo ""
echo "=== DEEP CHAOS COMPLETE ==="
