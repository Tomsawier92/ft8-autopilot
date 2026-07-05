#!/usr/bin/env python3
"""CW vs. zaj osztályozó tanítás (CUDA) — szintetikus morze + zaj."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cw_discover.filter.gate import DEFAULT_GATE_PATH
from cw_discover.filter.model import CwGateNet
from cw_discover.morse.alphabet import MORSE_SYMBOLS
from cw_discover.morse.synth import render_symbol


def _noise_chunk(n: int, fs: float, rng: np.random.Generator) -> np.ndarray:
  kind = int(rng.integers(0, 4))
  if kind == 0:
    x = rng.normal(0, 0.25, n)
  elif kind == 1:
    # sávos zaj
    t = np.arange(n) / fs
    x = sum(
      rng.uniform(0.05, 0.2) * np.sin(2 * np.pi * rng.uniform(200, 3000) * t + rng.uniform(0, 6))
      for _ in range(int(rng.integers(3, 8)))
    )
    x = np.asarray(x, dtype=np.float64)
  elif kind == 2:
    # hamis „csippanások” — GGMorse tévesztés
    x = np.zeros(n, dtype=np.float64)
    pos = 0
    while pos < n - 50:
      if rng.random() < 0.35:
        d = min(int(rng.uniform(0.02, 0.15) * fs), n - pos)
        if d < 8:
          break
        f = rng.uniform(500, 1200)
        t = np.arange(d, dtype=np.float64) / fs
        burst = 0.5 * np.sin(2 * np.pi * f * t) * np.hanning(d)
        x[pos : pos + d] = burst[:d]
        pos += d + int(rng.uniform(0.02, 0.12) * fs)
      else:
        pos += int(rng.uniform(0.03, 0.08) * fs)
  else:
    x = rng.normal(0, 0.08, n) + 0.1 * np.sin(2 * np.pi * 50 * np.arange(n) / fs)
  peak = np.max(np.abs(x)) + 1e-9
  return (x / peak * rng.uniform(0.3, 0.9)).astype(np.float32)


def _cw_chunk(fs: int, rng: np.random.Generator) -> np.ndarray:
  wpm = float(rng.choice([10, 12, 15, 18, 20, 22, 25, 28, 32]))
  sym = MORSE_SYMBOLS[int(rng.integers(0, len(MORSE_SYMBOLS)))]
  wave = render_symbol(sym, wpm, fs, tone_hz=float(rng.uniform(650, 950)), rng=rng)
  pad = int(rng.uniform(0.02, 0.15) * fs)
  x = np.concatenate([np.zeros(pad, dtype=np.float64), wave, np.zeros(pad, dtype=np.float64)])
  n = int(rng.uniform(0.25, 0.85) * fs)
  if x.size > n:
    i0 = int(rng.integers(0, max(1, x.size - n)))
    x = x[i0 : i0 + n]
  elif x.size < n:
    x = np.pad(x, (0, n - x.size))
  peak = np.max(np.abs(x)) + 1e-9
  return (x / peak * rng.uniform(0.5, 1.0)).astype(np.float32)


def build_batch(
  batch_size: int,
  fs: int,
  frame: int,
  rng: np.random.Generator,
  device: torch.device,
) -> tuple[torch.Tensor, torch.Tensor]:
  xs, ys = [], []
  for _ in range(batch_size):
    label = int(rng.integers(0, 2))
    n = frame
    if label == 1:
      x = _cw_chunk(fs, rng)
    else:
      x = _noise_chunk(n, fs, rng)
    if x.size < frame:
      x = np.pad(x, (0, frame - x.size))
    else:
      x = x[:frame]
    xs.append(x)
    ys.append(label)
  return (
    torch.from_numpy(np.stack(xs)).to(device),
    torch.from_numpy(np.array(ys, dtype=np.float32)).to(device),
  )


def main() -> int:
  ap = argparse.ArgumentParser()
  ap.add_argument("--epochs", type=int, default=25)
  ap.add_argument("--batch", type=int, default=64)
  ap.add_argument("--fs", type=int, default=12_000)
  ap.add_argument("--frame-ms", type=float, default=80.0)
  ap.add_argument("-o", "--out", type=str, default="")
  args = ap.parse_args()

  device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
  frame = int(args.fs * args.frame_ms / 1000.0)
  model = CwGateNet().to(device)
  opt = torch.optim.AdamW(model.parameters(), lr=2e-3, weight_decay=1e-4)
  rng = np.random.default_rng(0)

  print(f"device={device} frame={frame} fs={args.fs}")

  for ep in range(args.epochs):
    model.train()
    losses, accs = [], []
    for _ in range(80):
      x, y = build_batch(args.batch, args.fs, frame, rng, device)
      opt.zero_grad(set_to_none=True)
      logit = model(x, float(args.fs))
      loss = F.binary_cross_entropy_with_logits(logit, y)
      loss.backward()
      opt.step()
      pred = (torch.sigmoid(logit) > 0.5).float()
      accs.append(float((pred == y).float().mean().item()))
      losses.append(float(loss.item()))
    print(f"epoch {ep+1}/{args.epochs} loss={np.mean(losses):.4f} acc={np.mean(accs):.3f}")

  out = Path(args.out).expanduser() if args.out else DEFAULT_GATE_PATH
  out.parent.mkdir(parents=True, exist_ok=True)
  torch.save(
    {
      "version": 1,
      "model": model.state_dict(),
      "fs": args.fs,
      "frame_ms": args.frame_ms,
    },
    out,
  )
  print(f"mentve: {out}")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
