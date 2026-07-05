#!/usr/bin/env python3
"""Bemenetek: Pulse monitorok + opcionális rövid mintavétel."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np

from cw_discover.audio.devices import default_capture_source, list_input_devices
from cw_discover.audio.pulse_sources import list_pulse_sources, pick_recommended_monitor
from cw_discover.audio.source import CaptureSource


def list_all() -> None:
  print("=== Pulse/PipeWire források (pactl) ===")
  for s in list_pulse_sources():
    tag = []
    if s.is_monitor:
      tag.append("MONITOR")
    if s.is_mic:
      tag.append("MIC")
    print(f"  {s.index:4d} [{s.state:9s}] {'/'.join(tag) or 'SRC':8s}  {s.name}")
  best = pick_recommended_monitor(list_pulse_sources())
  if best:
    print(f"\n  ◆ ajánlott: {best.name} [{best.state}]")
  print("\n=== GUI lista (cw-discover) ===")
  for d in list_input_devices():
    mark = "◆" if d.recommended else " "
    print(f"  {mark} {d.label}")
  print(f"\n  alapértelmezett indulás: {default_capture_source().storage_key()}")


def probe_source(source: CaptureSource, seconds: float = 2.0) -> None:
  from cw_discover.audio.capture import open_capture

  cap = open_capture(12_000, 2048, source)
  print(f"\n--- {source.storage_key()} ({seconds}s, játssz közben WebSDR hangot!) ---")
  cap.start()
  chunks = []
  t0 = time.monotonic()
  while time.monotonic() - t0 < seconds:
    c = cap.read(timeout=0.1)
    if c is not None:
      chunks.append(c)
  cap.stop()
  if not chunks:
    print("  HIBA: nincs chunk (rossz forrás vagy nincs hang)")
    return
  x = np.concatenate(chunks)
  rms = float(np.sqrt(np.mean(x * x)))
  peak = float(np.max(np.abs(x)))
  n = min(len(x), 12_000)
  spec = np.abs(np.fft.rfft(x[:n] * np.hanning(n)))
  freqs = np.fft.rfftfreq(n, 1 / 12_000)
  band = (freqs > 200) & (freqs < 3000)
  sb = spec[band]
  centroid = float(np.sum(freqs[band] * sb) / (sb.sum() + 1e-12))
  flatness = float(np.exp(np.mean(np.log(sb + 1e-12))) / (np.mean(sb) + 1e-12))
  kind = "tonális/CW?" if flatness < 0.12 and rms > 0.002 else ("zaj?" if flatness > 0.2 else "gyenge")
  print(f"  RMS={rms:.5f} peak={peak:.3f} centroid={centroid:.0f}Hz flat={flatness:.3f} → {kind}")


def main() -> None:
  ap = argparse.ArgumentParser()
  ap.add_argument("--list", action="store_true")
  ap.add_argument("--probe-recommended", action="store_true")
  ap.add_argument("--probe", metavar="KEY", help="pl. pulse:alsa_output....monitor")
  ap.add_argument("-t", "--seconds", type=float, default=2.0)
  args = ap.parse_args()

  if args.list or (not args.probe and not args.probe_recommended):
    list_all()
  if args.probe_recommended:
    probe_source(default_capture_source(), args.seconds)
  if args.probe:
    probe_source(CaptureSource.from_key(args.probe), args.seconds)


if __name__ == "__main__":
  main()
