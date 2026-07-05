"""Kulcsolt szegmensek kivágása streamből — átfedő pufferrel (chunk-határ fix)."""
from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np

from cw_discover.audio.process import envelope_and_key, signal_strong_enough


@dataclass
class RawSegment:
  waveform: np.ndarray
  strength: float
  t_mono: float


def resample_char(w: np.ndarray, out_len: int = 96) -> np.ndarray:
  w = np.asarray(w, dtype=np.float32).ravel()
  if w.size == out_len:
    return w
  if w.size < 4:
    return np.zeros(out_len, dtype=np.float32)
  xi = np.linspace(0, w.size - 1, out_len)
  idx = np.arange(w.size, dtype=np.float32)
  return np.interp(xi, idx, w).astype(np.float32)


class SegmentExtractor:
  """Morse-szerű kulcsolás: szimbólumok kivágása, chunk-határokon át."""

  def __init__(
    self,
    fs: float,
    min_rms: float = 0.0008,
    buf_seconds: float = 1.2,
  ) -> None:
    self.fs = fs
    self.min_rms = min_rms
    self._buf_max = int(buf_seconds * fs)
    self._buf = np.zeros(0, dtype=np.float64)
    self._key_prev = False
    self._dit = 0.068
    self._sym_i0 = 0
    self._sym_i1 = 0
    self._in_symbol = False
    self._last_emit = 0.0

  def feed(self, chunk: np.ndarray) -> list[RawSegment]:
    chunk = np.asarray(chunk, dtype=np.float64).ravel()
    if chunk.size == 0:
      return []
    x = np.concatenate([self._buf, chunk]) if self._buf.size else chunk
    if x.size > self._buf_max:
      x = x[-self._buf_max :]

    if x.size < 256 or not signal_strong_enough(x, self.min_rms):
      tail = min(x.size, int(0.12 * self.fs))
      self._buf = x[-tail:].copy() if tail else np.zeros(0, dtype=np.float64)
      return []

    _, keyed, self._key_prev = envelope_and_key(x, self.fs, self._key_prev)
    dt = 1.0 / self.fs
    runs: list[tuple[bool, float, int, int]] = []
    v = bool(keyed[0])
    c = 1
    i0 = 0
    for i in range(1, keyed.size):
      b = bool(keyed[i])
      if b == v:
        c += 1
      else:
        runs.append((v, c * dt, i0, i))
        v, c, i0 = b, 1, i
    runs.append((v, c * dt, i0, keyed.size))

    ons = [d for hi, d, _, _ in runs if hi and 0.012 < d < 0.45]
    dit = self._dit
    if len(ons) >= 2:
      dit = float(np.clip(np.percentile(np.asarray(ons), 30), 0.022, 0.2))
      self._dit = dit

    letter_gap = 1.5 * dit
    out: list[RawSegment] = []
    cut_end = 0

    for hi, d, a, b in runs:
      if hi:
        if not self._in_symbol:
          self._sym_i0 = a
          self._in_symbol = True
        self._sym_i1 = b
      elif self._in_symbol and d >= letter_gap:
        seg = self._cut_at(x, self._sym_i0, self._sym_i1)
        if seg is not None:
          out.append(seg)
        pad = int(0.03 * self.fs)
        cut_end = max(cut_end, min(x.size, self._sym_i1 + pad))
        self._in_symbol = False

    if self._in_symbol:
      keep = max(0, self._sym_i0 - int(0.04 * self.fs))
    elif cut_end > 0:
      keep = cut_end
    else:
      keep = max(0, x.size - int(0.15 * self.fs))
    self._buf = x[keep:].copy()
    return out

  def _cut_at(self, x: np.ndarray, sym_i0: int, sym_i1: int) -> RawSegment | None:
    now = time.monotonic()
    if now - self._last_emit < 0.035:
      return None
    pad = int(0.03 * self.fs)
    i0 = max(0, sym_i0 - pad)
    i1 = min(x.size, sym_i1 + pad)
    chunk = x[i0:i1]
    if chunk.size < int(0.008 * self.fs):
      return None
    w = resample_char(chunk)
    self._last_emit = now
    return RawSegment(
      waveform=w,
      strength=float(np.max(np.abs(chunk))),
      t_mono=now,
    )
