#!/usr/bin/env python3
"""ITU morze alapgerinc — szintetikus 10/15/20/25 WPM → encoder + prototípus bank."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cw_discover.config import DiscoverConfig
from cw_discover.morse.alphabet import MORSE_SYMBOLS
from cw_discover.morse.backbone import DEFAULT_WPM, train_and_save_backbone


def main() -> int:
  ap = argparse.ArgumentParser(description="CW alapgerinc tanítás (szintetikus ITU)")
  ap.add_argument("--epochs", type=int, default=35)
  ap.add_argument("--variants", type=int, default=12, help="variáns / (szimbólum,WPM)")
  ap.add_argument("--wpm", type=int, nargs="+", default=list(DEFAULT_WPM))
  ap.add_argument("-o", "--out", type=str, default="")
  args = ap.parse_args()

  cfg = DiscoverConfig()
  wpm = tuple(sorted(set(args.wpm)))
  n_classes = len(MORSE_SYMBOLS) * len(wpm)
  n_samples = n_classes * args.variants

  print(f"Szimbólumok: {len(MORSE_SYMBOLS)}  WPM: {wpm}")
  print(f"Osztályok: {n_classes}  minták: ~{n_samples}  epoch: {args.epochs}")

  out = Path(args.out).expanduser() if args.out else None
  path = train_and_save_backbone(
    cfg,
    wpm_list=wpm,
    variants_per_key=args.variants,
    epochs=args.epochs,
    out_path=out,
  )
  print(f"Kész: {path}")
  print("A GUI induláskor betölti, ha kevesebb mint", cfg.backbone_min_clusters, "klaszter van.")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
