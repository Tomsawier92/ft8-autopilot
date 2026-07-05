"""Szintetikus CW — sima kulcsolás, oldalhang, 12 kHz."""
from __future__ import annotations

import numpy as np

from cw_discover.discover.segment import resample_char
from cw_discover.morse.alphabet import MorseSymbol


def dit_length(wpm: float) -> float:
  """PARIS szabvány: 1 dit = 1.2 / WPM másodperc."""
  return 1.2 / max(1.0, float(wpm))


def _raised_cosine_edge(n: int, ramp: int) -> np.ndarray:
  if n <= 0:
    return np.zeros(0, dtype=np.float64)
  w = np.ones(n, dtype=np.float64)
  r = min(ramp, n // 2)
  if r > 0:
    t = np.linspace(0, np.pi, r)
    w[:r] = 0.5 * (1.0 - np.cos(t))
    w[-r:] = 0.5 * (1.0 - np.cos(t[::-1]))
  return w


def _tone_burst(
  fs: float,
  duration: float,
  freq: float,
  phase: float,
  level: float,
) -> np.ndarray:
  n = max(1, int(round(duration * fs)))
  t = np.arange(n, dtype=np.float64) / fs
  env = _raised_cosine_edge(n, max(3, int(0.012 * fs)))
  carrier = np.sin(2 * np.pi * freq * t + phase)
  harm = 0.12 * np.sin(2 * np.pi * 2 * freq * t + phase * 1.1)
  y = level * env * (carrier + harm)
  return y.astype(np.float64)


def render_symbol(
  symbol: MorseSymbol,
  wpm: float,
  fs: float = 12_000.0,
  *,
  tone_hz: float = 800.0,
  rng: np.random.Generator | None = None,
) -> np.ndarray:
  """Egy karakter/prosign teljes sávhangja (kulcsolt CW)."""
  rng = rng or np.random.default_rng()
  dit = dit_length(wpm)
  dah = 3.0 * dit
  gap_intra = dit
  parts: list[np.ndarray] = []
  phase = float(rng.uniform(0, 2 * np.pi))
  freq = float(tone_hz) * float(rng.uniform(0.96, 1.04))
  level = float(rng.uniform(0.72, 1.0))

  code = symbol.code
  for i, el in enumerate(code):
    dur = dah if el == "-" else dit
    parts.append(_tone_burst(fs, dur, freq, phase, level))
    phase += 2 * np.pi * freq * dur
    if i < len(code) - 1:
      parts.append(np.zeros(max(1, int(gap_intra * fs)), dtype=np.float64))

  if not parts:
    return np.zeros(int(0.05 * fs), dtype=np.float64)
  wave = np.concatenate(parts)
  # finom szélső csend
  pad = np.zeros(int(0.02 * fs), dtype=np.float64)
  wave = np.concatenate([pad, wave, pad])
  # enyhe zajpad
  noise = rng.normal(0, 0.0025, wave.size)
  wave = np.tanh(1.15 * wave) + noise
  peak = np.max(np.abs(wave)) + 1e-9
  wave = (wave / peak * 0.92).astype(np.float64)
  return wave


def symbol_to_segment(
  symbol: MorseSymbol,
  wpm: float,
  seg_len: int = 96,
  fs: float = 12_000.0,
  rng: np.random.Generator | None = None,
) -> np.ndarray:
  """Encoder bemenet: 96 mintás szegmens (mint a live pipeline)."""
  wave = render_symbol(symbol, wpm, fs, rng=rng)
  return resample_char(wave.astype(np.float32), seg_len)
