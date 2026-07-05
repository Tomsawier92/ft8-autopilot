#!/usr/bin/env bash
# Gyors opt/CI tesztcsomag (~20s) — chaos/integration nélkül
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT"
PY="$ROOT/.venv/bin/pytest"
"$PY" tests/test_ft8_slot.py tests/test_ft8_protocol.py tests/test_qso_controller.py \
  tests/test_ft8_behavior_50.py tests/test_ft8_log_scenarios.py tests/test_opt_perf.py \
  tests/test_slot_native.py tests/test_virtual_engine.py tests/test_ft8_pro.py \
  -q -m "not integration" "$@"
