#!/usr/bin/env python3
"""FT8 dekód injektálás a virtuális RX forrásba."""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cw_discover.ft8.virtual_engine import DEFAULT_INJECT_JSONL
from cw_discover.ft8.ft8_slot import cycle_key_at

from cw_discover.paths import FORGALMI_LIVE


def wait_slot_edge(offset: float = 0.15) -> str:
  """Várakozás a következő 15 s FT8 slot elejére (+kis offset)."""
  now = time.time()
  delay = 15.0 - (now % 15.0) + offset
  if delay > 14.9:
    delay = offset
  time.sleep(delay)
  return cycle_key_at()


def main() -> int:
  ap = argparse.ArgumentParser(description="Dekód injektálás virtual RX-be")
  ap.add_argument("message", nargs="?", help='Pl. "CQ TEST1 JN57" vagy "TEST1 N0CALL JN96"')
  ap.add_argument("--snr", type=int, default=-12)
  ap.add_argument("--hz", type=int, default=1867)
  ap.add_argument("--cycle", default="", help="FT8 cycle kulcs (alapból aktuális slot)")
  ap.add_argument("--wait-slot", action="store_true", help="Várakozás a következő slot elejére")
  ap.add_argument("--file", type=Path, default=DEFAULT_INJECT_JSONL)
  ap.add_argument("--txt", action="store_true", help="inject_in.txt-be ír (egysoros)")
  args = ap.parse_args()

  if not args.message:
    ap.error("message kötelező")

  cycle = args.cycle
  if args.wait_slot:
    cycle = wait_slot_edge()
  elif not cycle:
    cycle = cycle_key_at()

  msg = args.message.strip().upper()
  if args.txt:
    path = FORGALMI_LIVE / "inject_in.txt"
    FORGALMI_LIVE.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{msg} {args.hz} {args.snr}\n", encoding="utf-8")
    print(f"inject_in.txt ← {msg}", flush=True)
    return 0

  rec = {
    "time_utc": datetime.now(timezone.utc).isoformat(),
    "message": msg,
    "snr": args.snr,
    "hz": args.hz,
    "cycle": cycle,
  }
  args.file.parent.mkdir(parents=True, exist_ok=True)
  with args.file.open("a", encoding="utf-8") as f:
    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    f.flush()
  print(f"{args.file.name} ← {cycle} {msg} SNR{args.snr:+d} @{args.hz}Hz", flush=True)
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
