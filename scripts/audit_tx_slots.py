#!/usr/bin/env python3
"""TX napló ellenőrzés — csak páros/páratlan slotban kell adni."""
from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cw_discover.ft8.ft8_slot import ft8_period_at
from cw_discover.paths import TX_LOG


def main() -> int:
  if not TX_LOG.exists():
    print("nincs tx.log")
    return 1
  lines = [ln for ln in TX_LOG.read_text(encoding="utf-8").splitlines() if "TX_START" in ln][-20:]
  if not lines:
    print("nincs TX_START")
    return 1
  periods: list[int] = []
  for ln in lines:
    m = re.match(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})", ln)
    if not m:
      continue
    t = datetime.fromisoformat(m.group(1)).replace(tzinfo=timezone.utc).timestamp()
    p = ft8_period_at(t)
    periods.append(p)
    sec = datetime.fromisoformat(m.group(1)).second
    in_slot = sec % 15
    ok = in_slot <= 3
    print(f"{'OK' if ok else 'LATE'} p{p} :{sec:02d}s  {ln.split('TX_START',1)[1].strip()}")
  if len(set(periods)) == 1:
    print(f"\n✓ Minden adás ugyanazon a sloton (p{periods[0]}) — váltakozó protokoll OK")
    return 0
  print(f"\n? Vegyes slotok: {periods}")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
