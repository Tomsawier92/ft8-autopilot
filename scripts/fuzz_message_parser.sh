#!/usr/bin/env bash
# Hypothesis stress fuzz — ~1.1M+ parser hívás (11 teszt × 100k példa).
# Futtatás: ./scripts/fuzz_message_parser.sh [profile]
# profile: default | thorough | stress
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
PROFILE="${1:-stress}"
cd "$ROOT"

export PYTHONFAULTHANDLER=1

echo "Hypothesis profil: $PROFILE"
echo "Tesztek: tests/test_fuzz_message_parser.py"

if [[ "$PROFILE" == "stress" ]]; then
  "$PY" -m pytest tests/test_fuzz_message_parser.py -v --tb=short \
    --hypothesis-profile=stress \
    -m "not hypothesis_stress"
  echo "--- extra raw unicode stress (50k) ---"
  "$PY" -m pytest tests/test_fuzz_message_parser.py::test_fuzz_raw_text_stress -v --tb=short
else
  "$PY" -m pytest tests/test_fuzz_message_parser.py -v --tb=short \
    --hypothesis-profile="$PROFILE"
fi

echo "FUZZ OK ($PROFILE)"
