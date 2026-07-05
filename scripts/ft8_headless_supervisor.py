#!/usr/bin/env python3
"""Éjszakai headless FT8 — óránként tiszta kilépés + újraindítás (log megmarad)."""
from __future__ import annotations

import argparse
import signal
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / ".venv" / "bin" / "python"
MONITOR = ROOT / "scripts" / "monitor_ft8_live.py"


def _log(msg: str) -> None:
  print(msg, flush=True)


def main() -> int:
  ap = argparse.ArgumentParser(description="FT8 headless óránkénti újraindító felügyelő")
  ap.add_argument("--slice-seconds", type=float, default=3600.0, help="Egy futás hossza (alap: 1 óra)")
  ap.add_argument("--pause-seconds", type=float, default=5.0, help="Szünet újraindítás előtt")
  ap.add_argument("--max-cycles", type=int, default=0, help="Teszt: max újraindítás (0 = végtelen)")
  ap.add_argument("--dial", type=float, default=7.074)
  ap.add_argument("--band", default="40m")
  ap.add_argument("--pulse", default="alsa_input.pci-0000_00_1f.3.analog-stereo")
  ap.add_argument("--power-safe", action="store_true", default=True)
  ap.add_argument("--no-power-safe", action="store_false", dest="power_safe")
  args = ap.parse_args()

  stop = False

  def _sig(_s, _f):
    nonlocal stop
    stop = True

  signal.signal(signal.SIGINT, _sig)
  signal.signal(signal.SIGTERM, _sig)

  cycle = 0
  _log(
    f"Supervisor start slice={args.slice_seconds:.0f}s pause={args.pause_seconds:.0f}s "
    f"power_safe={args.power_safe}"
  )

  while not stop:
    cycle += 1
    if args.max_cycles and cycle > args.max_cycles:
      _log(f"max-cycles={args.max_cycles} elérve — kilépés")
      break

    cmd = [
      str(PY),
      str(MONITOR),
      "-t",
      str(args.slice_seconds),
      "--dial",
      str(args.dial),
      "--band",
      args.band,
      "--pulse",
      args.pulse,
    ]
    if args.power_safe:
      cmd.append("--power-safe")
    cmd.extend(["--quiet", "--no-candidates"])

    _log(f"=== ciklus {cycle} indul ===")
    t0 = time.time()
    proc = subprocess.run(cmd, cwd=str(ROOT))
    elapsed = time.time() - t0
    _log(f"=== ciklus {cycle} vége exit={proc.returncode} elapsed={elapsed:.1f}s ===")

    if stop:
      break
    if args.max_cycles and cycle >= args.max_cycles:
      break

    _log(f"szünet {args.pause_seconds:.0f}s majd újraindítás…")
    deadline = time.time() + args.pause_seconds
    while not stop and time.time() < deadline:
      time.sleep(0.2)

  _log("Supervisor stop")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
