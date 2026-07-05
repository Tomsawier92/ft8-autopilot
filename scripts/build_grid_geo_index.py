#!/usr/bin/env python3
"""GeoNames cities15000 index előállítása FT8 lokátor leírásokhoz."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cw_discover.ft8.grid_geo import build_index, lookup, INDEX_FILE


def main() -> None:
  print(f"Index építése → {INDEX_FILE}")
  build_index()
  lookup.ensure_ready()
  for g in ("JO40", "JN58", "JN56", "JN63", "OM89"):
    print(lookup.describe_grid(g))


if __name__ == "__main__":
  main()
