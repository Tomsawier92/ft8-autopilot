#!/usr/bin/env python3
"""Headless FT8 monitor — élő adatfolyam + statisztika (GUI nélkül)."""
from __future__ import annotations

import argparse
import atexit
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cw_discover.ft8.audio_feed import set_line_in_port
from cw_discover.ft8.engine import DEFAULT_LINEIN, Ft8Engine
from cw_discover.ft8.home_qth import DEFAULT_HOME
from cw_discover.ft8.session_log import SessionLog


def _setup_line_in(pulse: str) -> None:
  if "alsa_input" in pulse:
    set_line_in_port(pulse)
    subprocess.run(["pactl", "set-source-mute", pulse, "0"], capture_output=True)


def main() -> int:
  ap = argparse.ArgumentParser(description="FT8 élő monitor")
  ap.add_argument("-t", "--seconds", type=float, default=120.0, help="Futási idő (0 = végtelen SIGINT/SIGTERM-ig)")
  ap.add_argument("--dial", type=float, default=7.074)
  ap.add_argument("--band", default="40m")
  ap.add_argument("--pulse", default=DEFAULT_LINEIN)
  ap.add_argument("--power-safe", action="store_true", help="Atomi snapshot + fsync JSONL")
  ap.add_argument("--quiet", action="store_true", help="Nincs WSJTX sor a kimenetre (headless)")
  ap.add_argument("--no-candidates", action="store_true", help="Nem ír candidates.jsonl-t")
  args = ap.parse_args()

  _setup_line_in(args.pulse)

  log = SessionLog()
  log.power_safe = args.power_safe
  log.log_candidates = not args.no_candidates
  log.reset(args.band, args.dial, pulse_device=args.pulse, home=DEFAULT_HOME)

  decodes = 0
  candidates = 0
  t0 = time.time()
  stop = False
  eng: Ft8Engine | None = None
  shutdown_done = False

  def _shutdown(reason: str = "normal") -> None:
    nonlocal eng, shutdown_done
    if shutdown_done:
      return
    shutdown_done = True
    if eng is not None:
      eng.stop()
      eng = None
    log.shutdown()
    elapsed = time.time() - t0
    print(
      f"\n--- kilépés ({reason}) {elapsed:.1f}s ---\n"
      f"decodes={decodes} candidates={candidates} "
      f"stations={log.station_count()} mapped={log.mapped_count()}",
      flush=True,
    )
    print(f"log: {log.log_dir_for_day()}", flush=True)

  def _atexit() -> None:
    _shutdown("atexit")

  atexit.register(_atexit)

  def _sig(_s, _f):
    nonlocal stop
    stop = True

  signal.signal(signal.SIGINT, _sig)
  signal.signal(signal.SIGTERM, _sig)

  def on_decode(report):
    nonlocal decodes
    decodes += 1
    log.add_decode(
      decode_id=decodes,
      message=report.message,
      snr=report.snr,
      rf_khz=report.rf_khz,
      cycle=report.cycle,
      audio_hz=report.audio_hz,
      dt=report.dt,
      time_received=report.time_received,
      cycle_start_utc=report.cycle_start_utc,
      dsp=report.dsp,
      audio=report.audio,
    )
    if not args.quiet:
      print(report.wsjtx_line, flush=True)

  def on_candidate(c, cycle, ts, snap):
    nonlocal candidates
    candidates += 1
    log.add_candidate(c, cycle, ts)

  def on_cycle(cycle, cst, n, busy, ts, snap):
    log.note_cycle_search(cycle, cst, n, busy, ts)
    if snap.raw_rms > 0:
      log.note_audio_levels(snap.raw_rms, snap.clip_frac, cycle, ts)

  eng = Ft8Engine(
    dial_mhz=args.dial,
    band=args.band,
    pulse_name=args.pulse,
    on_decode=on_decode,
    on_candidate=on_candidate,
    on_cycle_search=on_cycle,
  )
  eng.start()
  dur = "∞" if args.seconds <= 0 else f"{args.seconds:.0f}s"
  print(
    f"Monitor {dur} — {args.pulse} @ {args.dial} MHz power_safe={args.power_safe}",
    flush=True,
  )

  try:
    while not stop and (args.seconds <= 0 or (time.time() - t0) < args.seconds):
      time.sleep(0.5)
  finally:
    atexit.unregister(_atexit)
    _shutdown("SIGTERM" if stop else "timer")

  return 0


if __name__ == "__main__":
  raise SystemExit(main())
