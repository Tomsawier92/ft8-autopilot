#!/usr/bin/env python3
"""Folyamatos mérési hang PC kimeneten — oszcilloszkóp / FT-817 szintbeállítás."""
from __future__ import annotations

import argparse
import signal
import sys
import time

import numpy as np
import sounddevice as sd

DEFAULT_DEVICE = "pulse"  # PipeWire → vonalkimenet (ne közvetlen hw:0,0)
DEFAULT_FS = 48_000
DEFAULT_HZ = 1000.0
DEFAULT_AMP = 0.5  # peak, -6 dBFS


def _ensure_line_out_unmuted() -> None:
  """ALC897: a hátsó vonalkimenet 'Line' csatornája gyakran alapból némítva van."""
  import subprocess

  for args in (
    ["amixer", "-c", "0", "set", "Line", "100%", "unmute"],
    ["amixer", "-c", "0", "set", "Front", "100%", "unmute"],
    ["amixer", "-c", "0", "set", "PCM", "100%"],
  ):
    subprocess.run(args, check=False, capture_output=True)
  sink = "alsa_output.pci-0000_00_1f.3.analog-stereo.3"
  subprocess.run(["pactl", "set-default-sink", sink], check=False, capture_output=True)
  subprocess.run(["pactl", "set-sink-mute", sink, "0"], check=False, capture_output=True)
  subprocess.run(["pactl", "set-sink-volume", sink, "100%"], check=False, capture_output=True)


def main() -> int:
  p = argparse.ArgumentParser(description="Folyamatos teszthang line-outra")
  p.add_argument("--hz", type=float, default=DEFAULT_HZ, help="Szinusz frekvencia (Hz)")
  p.add_argument("--amp", type=float, default=None, help="Csúszka 0..1 (peak)")
  p.add_argument(
    "--target-vpp",
    type=float,
    default=None,
    help="Becsült cél Vpp ALC897-n (100%% Master/PCM); amp = target_vpp / 3.39",
  )
  p.add_argument("--device", default=DEFAULT_DEVICE, help="sounddevice név vagy index")
  p.add_argument("--fs", type=int, default=DEFAULT_FS)
  args = p.parse_args()
  if args.target_vpp is not None:
    amp = max(0.0, min(1.0, args.target_vpp / 3.39))
  elif args.amp is not None:
    amp = float(np.clip(args.amp, 0.0, 1.0))
  else:
    amp = DEFAULT_AMP

  phase = 0.0
  block = 2048
  running = True

  def stop(_sig, _frame):
    nonlocal running
    running = False

  signal.signal(signal.SIGTERM, stop)
  signal.signal(signal.SIGINT, stop)

  _ensure_line_out_unmuted()

  dev = sd.query_devices(args.device)
  print(
    f"TX teszthang indul: {args.hz:.0f} Hz szinusz, amp={amp:.4f} peak "
    f"({20*np.log10(max(amp,1e-9)):.1f} dBFS), becsült Vpp≈{amp*3.39:.2f} @100% Master, "
    f"fs={args.fs}, device={args.device} ({dev['name']})",
    flush=True,
  )
  print("Mérés: CH1 a bal line-out csúcs (tip), föld a sleeve. Leállítás: SIGTERM / Ctrl+C", flush=True)

  amp = float(np.clip(amp, 0.0, 1.0))
  hz = args.hz
  fs = args.fs
  phase_inc = 2.0 * np.pi * hz / fs

  with sd.OutputStream(
    device=args.device,
    channels=2,
    samplerate=fs,
    dtype="float32",
    blocksize=block,
  ) as stream:
    while running:
      t = (np.arange(block) + phase) / fs
      mono = (amp * np.sin(2.0 * np.pi * hz * t)).astype(np.float32)
      phase = (phase + block) % fs
      stereo = np.column_stack([mono, mono])
      stream.write(stereo)

  print("TX teszthang leállt.", flush=True)
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
