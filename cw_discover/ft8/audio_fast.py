"""Gyors 48 kHz → 12 kHz audio út (i5 AVX2-barát, scipy helyett)."""
from __future__ import annotations

import numpy as np

DECIMATE = 4
HOP_12K = 480  # @ 12 kHz, 25 Hz hop


def downsample_48k_to_12k(mono_f32: np.ndarray) -> np.ndarray:
  """4:1 átlagoló decimáció — FT8 sávhoz elég, ~5× gyorsabb mint resample_poly."""
  if mono_f32.size == 0:
    return np.empty(0, dtype=np.float32)
  clean = np.nan_to_num(mono_f32, nan=0.0, posinf=1.0, neginf=-1.0, copy=False)
  n = (clean.size // DECIMATE) * DECIMATE
  if n == 0:
    return np.empty(0, dtype=np.float32)
  return clean[:n].reshape(-1, DECIMATE).mean(axis=1, dtype=np.float32)


class HopBuffer:
  """Előre allokált 12 kHz puffér — np.concatenate helyett."""

  __slots__ = ("_data", "_len", "_cap")

  def __init__(self, cap_samples: int = HOP_12K * 32) -> None:
    self._data = np.empty(cap_samples, dtype=np.float32)
    self._len = 0
    self._cap = cap_samples

  def clear(self) -> None:
    self._len = 0

  def extend(self, samples: np.ndarray) -> None:
    n = int(samples.size)
    if n == 0:
      return
    need = self._len + n
    if need > self._cap:
      while self._cap < need:
        self._cap *= 2
      grown = np.empty(self._cap, dtype=np.float32)
      grown[: self._len] = self._data[: self._len]
      self._data = grown
    self._data[self._len : self._len + n] = samples
    self._len += n

  def pop_hop(self, hop_samples: int) -> np.ndarray | None:
    if self._len < hop_samples:
      return None
    hop = self._data[:hop_samples].copy()
    rest = self._len - hop_samples
    if rest > 0:
      self._data[:rest] = self._data[hop_samples : self._len]
    self._len = rest
    return hop

  @property
  def pending_samples(self) -> int:
    return self._len
