#!/usr/bin/env python3
"""FT8 ál-dekód szimuláció — napló lejátszás vagy egyedi üzenetek (nincs rádió TX)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cw_discover.ft8.log_replay import load_decodes, remap_cycles_fresh
from cw_discover.ft8.sim_harness import Ft8SimHarness


def main() -> int:
  ap = argparse.ArgumentParser(description="FT8 operátor szimuláció (RecordingTx)")
  ap.add_argument("--log", type=Path, help="decodes.jsonl útvonal")
  ap.add_argument("--limit", type=int, default=50, help="max sor naplóból")
  ap.add_argument("--message", "-m", action="append", help="egyedi üzenet (ismételhető)")
  ap.add_argument("--callsign", default="N0CALL")
  ap.add_argument("--grid", default="JN96")
  args = ap.parse_args()

  h = Ft8SimHarness(callsign=args.callsign, grid=args.grid)

  if args.log:
    decs = remap_cycles_fresh(load_decodes(args.log, limit=args.limit))
    print(f"Lejátszás: {len(decs)} dekód ← {args.log}")
    for d in decs:
      before = len(h.tx.messages())
      h.feed_decode(d, wait=False)
      if len(h.tx.messages()) > before:
        print(f"  TX → {h.last_tx}")
    h.wait_tx(len(h.tx.messages()))
  elif args.message:
    for m in args.message:
      before = len(h.tx.messages())
      h.feed(m)
      if len(h.tx.messages()) > before:
        print(f"TX → {h.last_tx}")
      else:
        print(f"RX  {m} (nincs TX)")
  else:
    ap.print_help()
    return 1

  print(f"\nÖsszes TX ({len(h.tx.messages())}):")
  for i, msg in enumerate(h.tx.messages(), 1):
    print(f"  {i}. {msg}")
  print(f"Fázis: {h.phase.value}")
  return 0


if __name__ == "__main__":
  sys.exit(main())
