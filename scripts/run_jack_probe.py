#!/usr/bin/env python3
"""Jack / line-in láb azonosító GUI."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cw_discover.gui.jack_probe_window import main

if __name__ == "__main__":
  raise SystemExit(main())
