#!/usr/bin/env python3
"""CUDA CW zajkapu — grafikus felület."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cw_discover.gui.gate_window import main

if __name__ == "__main__":
  raise SystemExit(main())
