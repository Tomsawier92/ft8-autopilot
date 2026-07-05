#!/bin/bash
set -e
cd "$(dirname "$0")/.."
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
echo "Kész. GUI: .venv/bin/python scripts/run_gui.py"
