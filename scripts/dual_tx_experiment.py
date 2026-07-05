#!/usr/bin/env python3
"""Kísérlet: két azonos FT8 üzenet párhuzamosan 1000 Hz + 1430 Hz-en."""
from __future__ import annotations

import json
import sys
import threading
import time
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PyFT8.receiver import AudioIn
from PyFT8.transmitter import AudioOut, pack_message

MSG = ("CQ", "N0CALL", "JN96")
HZ_A, HZ_B = 1000.0, 1430.0
FS = 12000
OUT_DIR = ROOT / "data" / "experiments"
WAV_A = OUT_DIR / "dual_tx_1000hz.wav"
WAV_B = OUT_DIR / "dual_tx_1430hz.wav"
WAV_SUM = OUT_DIR / "dual_tx_combined.wav"
REPORT = OUT_DIR / "dual_tx_report.json"


def gen_wave(hz: float, amplitude: float = 0.45) -> np.ndarray:
  ao = AudioOut()
  symbols = pack_message(*MSG)
  w = ao.create_ft8_wave(symbols, fs=FS, f_base=hz, amplitude=amplitude)
  return w.astype(np.float32) / 32767.0


def write_wav(path: Path, audio_f32: np.ndarray) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  peak = max(float(np.max(np.abs(audio_f32))), 1e-6)
  scaled = np.clip(audio_f32 / peak * 0.85, -1.0, 1.0)
  pcm = (scaled * 32767).astype(np.int16)
  with wave.open(str(path), "wb") as wf:
    wf.setnchannels(1)
    wf.setsampwidth(2)
    wf.setframerate(FS)
    wf.writeframes(pcm.tobytes())


def decode_wav(path: Path, label: str) -> dict:
  decodes: list[dict] = []
  candidates: list[dict] = []
  audio_in = AudioIn(3100, wav_files=[str(path)])

  def on_decode(c):
    if not c.msg:
      return
    decodes.append(_cand_dict(label, c, "decode_callback"))

  def on_candidate(c, _cycle: str):
    if not c.msg or int(c.ncheck) != 0:
      return
    candidates.append(_cand_dict(label, c, "candidate"))

  from cw_discover.ft8.receiver_instrumented import InstrumentedReceiver

  rx = InstrumentedReceiver(
    audio_in, [200, 3100], on_decode, on_candidate=on_candidate, verbose=False
  )
  t = threading.Thread(target=rx.manage_cycle, daemon=True)
  t.start()
  audio_in.start_wav_load()
  time.sleep(14)
  return {"decodes": decodes, "candidates": candidates}


def _cand_dict(label: str, c, source: str) -> dict:
  msg = c.msg if isinstance(c.msg, str) else " ".join(c.msg)
  return {
    "label": label,
    "source": source,
    "message": msg,
    "audio_hz": int(c.fHz),
    "snr": int(c.snr),
    "sync": float(c.sync_score),
    "ncheck": int(c.ncheck),
  }


def unique_by_hz(items: list[dict], target_hz: float, tol: float = 80) -> list[dict]:
  seen: set[int] = set()
  out = []
  for d in items:
    hz = d["audio_hz"]
    if abs(hz - target_hz) > tol or hz in seen:
      continue
    seen.add(hz)
    out.append(d)
  return out


def main() -> int:
  print(f"Üzenet: {' '.join(MSG)}")
  wa = gen_wave(HZ_A)
  wb = gen_wave(HZ_B)
  n = max(len(wa), len(wb))
  wa = np.pad(wa, (0, n - len(wa)))
  wb = np.pad(wb, (0, n - len(wb)))
  combined = wa + wb

  write_wav(WAV_A, wa)
  write_wav(WAV_B, wb)
  write_wav(WAV_SUM, combined)

  sep_hz = abs(HZ_B - HZ_A)
  results = {
    "message": " ".join(MSG),
    "hz_a": HZ_A,
    "hz_b": HZ_B,
    "separation_hz": sep_hz,
    "ft8_tone_step_hz": 6.25,
    "tone_separation": sep_hz / 6.25,
    "duration_s": n / FS,
    "note": (
      "PyFT8 on_decode duplicate_filter kulcsa ciklus+üzenet (frekvencia nélkül), "
      "ezért a candidates lista a megbízható forrás kombinált jelnél."
    ),
    "decode_a_only": decode_wav(WAV_A, "1000_only"),
    "decode_b_only": decode_wav(WAV_B, "1430_only"),
    "decode_combined": decode_wav(WAV_SUM, "combined"),
  }

  target = " ".join(MSG)

  def ok_at_hz(block: dict, hz: float) -> bool:
    cands = unique_by_hz(block["candidates"], hz)
    return any(d["message"] == target and d["ncheck"] == 0 for d in cands)

  comb = results["decode_combined"]
  comb_cands = unique_by_hz(comb["candidates"], HZ_A) + unique_by_hz(comb["candidates"], HZ_B)

  results["summary"] = {
    "a_alone_ok": ok_at_hz(results["decode_a_only"], HZ_A),
    "b_alone_ok": ok_at_hz(results["decode_b_only"], HZ_B),
    "combined_a_ok": ok_at_hz(comb, HZ_A),
    "combined_b_ok": ok_at_hz(comb, HZ_B),
    "both_on_combined": ok_at_hz(comb, HZ_A) and ok_at_hz(comb, HZ_B),
    "combined_decodes": comb["decodes"],
    "combined_unique_candidates": comb_cands,
  }

  REPORT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

  print("\n=== Eredmény ===")
  print(f"Távolság: {sep_hz:.0f} Hz ({sep_hz/6.25:.0f} FT8 tónus)")
  for k in ("decode_a_only", "decode_b_only", "decode_combined"):
    block = results[k]
    print(f"\n{k} (candidates, ncheck=0):")
    for d in unique_by_hz(block["candidates"], HZ_A) + unique_by_hz(block["candidates"], HZ_B):
      print(f"  {d['audio_hz']:4d} Hz  SNR{d['snr']:+3d}  sync={d['sync']:.1f}  {d['message']}")
    if k == "decode_combined" and block["decodes"]:
      print(f"  on_decode callback (duplikátumszűrő): {len(block['decodes'])} db → csak egy frekvencia látszik")
  s = results["summary"]
  print("\nÖsszegzés:")
  print(f"  1000 Hz egyedül: {'OK' if s['a_alone_ok'] else 'FAIL'}")
  print(f"  1430 Hz egyedül: {'OK' if s['b_alone_ok'] else 'FAIL'}")
  print(f"  Kombinált → 1000 Hz: {'OK' if s['combined_a_ok'] else 'FAIL'}")
  print(f"  Kombinált → 1430 Hz: {'OK' if s['combined_b_ok'] else 'FAIL'}")
  print(f"  Mindkettő egyszerre: {'IGEN' if s['both_on_combined'] else 'NEM'}")
  print(f"\nReport: {REPORT}")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
