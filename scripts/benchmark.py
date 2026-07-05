#!/usr/bin/env python3
"""Benchmark + optimalizációs összehasonlítás."""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cw_discover.config import DiscoverConfig
from cw_discover.discover.encoder import EncoderRuntime
from cw_discover.discover.pattern_bank import PatternBank


def synth_morse_char(fs: float, wpm: float, pattern: str, tone: float = 700.0) -> np.ndarray:
  """pattern: '.' '-' szóköz"""
  dit = 1.2 / wpm
  dah = 3 * dit
  gap = dit
  letter_gap = 3 * dit
  parts: list[np.ndarray] = []
  t = np.linspace(0, 1, int(fs * 0.02), endpoint=False)

  def tone_burst(dur: float) -> None:
    n = int(fs * dur)
    if n < 8:
      return
    tt = np.arange(n) / fs
    parts.append((0.65 * np.sin(2 * np.pi * tone * tt)).astype(np.float32))

  def silence(dur: float) -> None:
    parts.append(np.zeros(int(fs * dur), dtype=np.float32))

  for sym in pattern:
    if sym == ".":
      tone_burst(dit)
      silence(gap)
    elif sym == "-":
      tone_burst(dah)
      silence(gap)
    elif sym == " ":
      silence(letter_gap)
  if not parts:
    return np.zeros(int(fs * 0.1), dtype=np.float32)
  return np.concatenate(parts)


def synth_dataset(n_per_class: int, n_classes: int, fs: int = 12000) -> tuple[list[np.ndarray], list[int]]:
  patterns = [".-", "-...", "-.-.", "-..", ".", "..-.", "--.", "....", "..", ".---"][:n_classes]
  waves: list[np.ndarray] = []
  labels: list[int] = []
  rng = np.random.default_rng(42)
  for ci, pat in enumerate(patterns):
    for _ in range(n_per_class):
      wpm = float(rng.uniform(14, 28))
      tone = float(rng.uniform(550, 900))
      w = synth_morse_char(fs, wpm, pat, tone)
      # zaj
      w = w + rng.normal(0, 0.02, w.size).astype(np.float32)
      # 96 minta
      if w.size < 96:
        w = np.pad(w, (0, 96 - w.size))
      xi = np.linspace(0, w.size - 1, 96)
      w96 = np.interp(xi, np.arange(w.size), w).astype(np.float32)
      waves.append(w96)
      labels.append(ci)
  return waves, labels


def resample_to_seg(w: np.ndarray, seg_len: int = 96) -> np.ndarray:
  w = np.asarray(w, dtype=np.float32).ravel()
  if w.size == seg_len:
    return w
  xi = np.linspace(0, w.size - 1, seg_len)
  return np.interp(xi, np.arange(w.size), w).astype(np.float32)


@dataclass
class BenchResult:
  name: str
  seg_per_s: float
  infer_ms_batch: float
  cluster_purity: float
  n_clusters: int
  n_classes: int
  train_off: bool
  note: str = ""

  def verdict(self) -> str:
    if self.seg_per_s < 50:
      return "Lassú — napokig is futhat, de CPU szűk"
    if self.cluster_purity < 0.35:
      return "Gyenge klaszterezés — érdemes paraméterezni, de futhat"
    if self.seg_per_s >= 200 and self.cluster_purity >= 0.5:
      return "Érdemes napokig futtatni line-inen"
    return "Közepes — futhat, figyeld a klaszterek számát"


def run_bench(cfg: DiscoverConfig, name: str, waves: list, labels: list) -> BenchResult:
  enc = EncoderRuntime(cfg)
  bank = PatternBank(cfg.match_threshold, cfg.ema_alpha, cfg.max_prototypes)
  strengths = [0.5] * len(waves)

  # warmup
  enc.encode_batch(waves[: min(32, len(waves))])

  t0 = time.perf_counter()
  bs = cfg.infer_batch_size
  n = 0
  infer_ms = 0.0
  for i in range(0, len(waves), bs):
    batch = waves[i : i + bs]
    t1 = time.perf_counter()
    z = enc.encode_batch(batch)
    infer_ms += (time.perf_counter() - t1) * 1000.0
    bank.assign_batch(z, strengths[i : i + len(batch)])
    if cfg.train_enabled:
      enc.push_train_waves(batch)
      enc.maybe_train_step(len(batch))
    n += len(batch)
  elapsed = time.perf_counter() - t0
  sps = n / max(elapsed, 1e-6)

  # purity: dominant cluster per class label
  assigned: list[int] = []
  for i in range(0, len(waves), bs):
    z = enc.encode_batch(waves[i : i + bs])
    assigned.extend(bank.assign_batch(z, strengths[i : i + len(batch)]))
  # re-run assign would double count - compute mapping from first pass
  # Simpler: re-encode and assign fresh bank for purity only
  bank2 = PatternBank(cfg.match_threshold, cfg.ema_alpha, cfg.max_prototypes)
  assigned = []
  for i in range(0, len(waves), bs):
    z = enc.encode_batch(waves[i : i + bs])
    assigned.extend(bank2.assign_batch(z, strengths[i : i + bs]))
  n_classes = len(set(labels))
  # cluster -> majority label
  from collections import defaultdict

  cluster_labels: dict[int, list[int]] = defaultdict(list)
  for a, lab in zip(assigned, labels):
    cluster_labels[a].append(lab)
  correct = 0
  for labs in cluster_labels.values():
    if labs:
      correct += sum(1 for x in labs if x == max(set(labs), key=labs.count))
  purity = correct / max(1, len(labels))

  batches = max(1, (len(waves) + bs - 1) // bs)
  return BenchResult(
    name=name,
    seg_per_s=sps,
    infer_ms_batch=infer_ms / batches,
    cluster_purity=purity,
    n_clusters=bank2.n_clusters,
    n_classes=n_classes,
    train_off=not cfg.train_enabled,
    note="",
  )


def main() -> int:
  print("=== CW-Discover benchmark ===\n")
  waves, labels = synth_dataset(n_per_class=40, n_classes=8)
  print(f"Synthetic: {len(waves)} szegmens, {len(set(labels))} osztály\n")

  base = DiscoverConfig()
  configs = [
    ("v0_alap", base),
    ("v1_nagy_batch", replace(base, infer_batch_size=64, train_batch=128)),
    ("v2_amp_batch_train_off", replace(base, infer_batch_size=64, train_enabled=False)),
    ("v3_szigoru_cluster", replace(base, infer_batch_size=64, match_threshold=0.78, train_enabled=False)),
  ]

  results: list[BenchResult] = []
  for name, cfg in configs:
    print(f"--- {name} ---")
    r = run_bench(cfg, name, waves, labels)
    results.append(r)
    print(f"  sebesség: {r.seg_per_s:.0f} seg/s  infer/batch: {r.infer_ms_batch:.2f} ms")
    print(f"  klaszterek: {r.n_clusters}  tisztaság: {r.cluster_purity*100:.1f}%")
    print(f"  → {r.verdict()}\n")

  best = max(results, key=lambda x: x.seg_per_s * (0.5 + x.cluster_purity))
  print("=== Ajánlott konfig ===")
  print(f"  {best.name}: {best.seg_per_s:.0f} seg/s, purity {best.cluster_purity*100:.1f}%")
  print(f"  {best.verdict()}")
  print("\nLine-in: napokig futhat (~0.1-0.3 GPU), klaszterek lassan nőnek.")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
