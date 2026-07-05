#!/usr/bin/env python3
"""
CW zajkapu → GGMorse virtual bemenet.

  WebSDR / PC monitor  →  [CUDA kapu]  →  PipeWire null-sink  →  GGMorse capture

Használat:
  1. python scripts/train_cw_gate.py          # egyszer (vagy ha nincs cw_gate.pt)
  2. python scripts/run_cw_gate_bridge.py
  3. GGMorse: Capture = „CWFiltered” vagy „CWFiltered.monitor”
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scipy.signal import resample_poly

from cw_discover.audio.pulse_sources import list_pulse_sources, pick_recommended_monitor
from cw_discover.audio.capture import PulseCapture
from cw_discover.filter.gate import CwNoiseGate, GateConfig

SINK_NAME = "CWFiltered"
CAPTURE_FS = 48_000
PROC_FS = 12_000


def _ensure_sink() -> bool:
  if not shutil.which("pactl"):
    print("pactl hiányzik")
    return False
  subprocess.run(
    ["pactl", "unload-module", "module-null-sink"],
    capture_output=True,
  )
  r = subprocess.run(
    [
      "pactl",
      "load-module",
      "module-null-sink",
      f"sink_name={SINK_NAME}",
      f"sink_properties=device.description={SINK_NAME}",
    ],
    capture_output=True,
    text=True,
  )
  if r.returncode != 0 and "exists" not in (r.stderr or "").lower():
    print("null-sink hiba:", r.stderr or r.stdout)
    return False
  print(f"PipeWire sink: {SINK_NAME} (GGMorse: ezt válaszd capture-nek)")
  return True


def _resample(x: np.ndarray, fs_in: int, fs_out: int) -> np.ndarray:
  if fs_in == fs_out:
    return x.astype(np.float32)
  g = np.gcd(fs_in, fs_out)
  return resample_poly(x, fs_out // g, fs_in // g).astype(np.float32)


def main() -> int:
  ap = argparse.ArgumentParser()
  ap.add_argument(
    "--source",
    type=str,
    default="",
    help="pulse forrás név (üres = ajánlott monitor)",
  )
  ap.add_argument("--open", type=float, default=0.62)
  ap.add_argument("--close", type=float, default=0.42)
  args = ap.parse_args()

  if not shutil.which("parec") or not shutil.which("pacat"):
    print("parec/pacat kell (pulseaudio-utils)")
    return 1

  src_name = args.source.strip()
  if not src_name:
    best = pick_recommended_monitor(list_pulse_sources())
    if not best:
      print("Nincs monitor forrás")
      return 1
    src_name = best.name
  print("Bemenet:", src_name)

  if not _ensure_sink():
    return 1

  gate = CwNoiseGate(
    GateConfig(open_threshold=args.open, close_threshold=args.close),
  )
  cap = PulseCapture(PROC_FS, 2048, src_name)

  play = subprocess.Popen(
    [
      "pacat",
      f"--device={SINK_NAME}",
      "--format=float32le",
      f"--rate={CAPTURE_FS}",
      "--channels=1",
      "--latency-msec=40",
    ],
    stdin=subprocess.PIPE,
    stderr=subprocess.DEVNULL,
  )

  cap.start()
  print("Kapu fut — Ctrl+C leállítás. GGMorse capture:", SINK_NAME)
  t0 = time.monotonic()
  try:
    while True:
      chunk = cap.read(timeout=0.1)
      if chunk is None:
        continue
      filtered, meta = gate.process_chunk(chunk)
      if filtered.size == 0:
        continue
      out = _resample(filtered, PROC_FS, CAPTURE_FS)
      if play.stdin:
        play.stdin.write(out.tobytes())
        play.stdin.flush()
      if time.monotonic() - t0 > 1.0:
        t0 = time.monotonic()
        st = "NYITVA" if meta.get("open") else "zárva"
        print(
          f"\r  [{st}] gain={meta.get('gain', 0):.2f} "
          f"P={meta.get('p', 0):.2f} SNR={meta.get('snr', 0):.1f}dB",
          end="",
          flush=True,
        )
  except KeyboardInterrupt:
    print("\nLeállítás.")
  finally:
    cap.stop()
    if play.stdin:
      play.stdin.close()
    play.terminate()
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
