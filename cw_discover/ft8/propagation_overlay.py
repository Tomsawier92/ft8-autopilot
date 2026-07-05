"""Simított irány-eloszlás — propagation réteg a térképhez (exponenciális csillapítás)."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

EARTH_RADIUS_KM = 6371.0


def destination_point(lat_deg: float, lon_deg: float, bearing_deg: float, dist_km: float) -> tuple[float, float]:
  """Cél koordináta nagykörön (fok)."""
  if dist_km <= 0:
    return lat_deg, lon_deg
  d = dist_km / EARTH_RADIUS_KM
  brng = math.radians(bearing_deg)
  lat1 = math.radians(lat_deg)
  lon1 = math.radians(lon_deg)
  lat2 = math.asin(math.sin(lat1) * math.cos(d) + math.cos(lat1) * math.sin(d) * math.cos(brng))
  lon2 = lon1 + math.atan2(
    math.sin(brng) * math.sin(d) * math.cos(lat1),
    math.cos(d) - math.sin(lat1) * math.sin(lat2),
  )
  return math.degrees(lat2), (math.degrees(lon2) + 540.0) % 360.0 - 180.0


def snr_weight(snr: int) -> float:
  """Gyenge jelek kisebb súlyt kapnak — kevesebb vibrálás."""
  return float(np.clip((snr + 18.0) / 22.0, 0.25, 1.4))


@dataclass
class PropagationOverlay:
  """Irány-binek simított energiája; idővel exponenciálisan cseng."""

  n_bins: int = 16
  decay_per_second: float = 0.035
  _bins: np.ndarray = field(init=False, repr=False)

  def __post_init__(self) -> None:
    self._bins = np.zeros(self.n_bins, dtype=np.float64)

  def reset(self) -> None:
    self._bins.fill(0.0)

  def note_azimuth(self, azimuth_deg: float, *, weight: float = 1.0) -> None:
    if not math.isfinite(azimuth_deg):
      return
    w = max(0.0, float(weight))
    if w <= 0:
      return
    az = float(azimuth_deg) % 360.0
    idx = int(az / (360.0 / self.n_bins)) % self.n_bins
    self._bins[idx] += w

  def tick(self, dt_seconds: float) -> None:
    if dt_seconds <= 0:
      return
    factor = math.exp(-self.decay_per_second * dt_seconds)
    self._bins *= factor

  def smoothed(self) -> np.ndarray:
    """Körkörös simítás — kevesebb „vibrálás” szektorváltáskor."""
    b = self._bins.astype(np.float64, copy=True)
    if b.sum() <= 1e-9:
      return b
    n = len(b)
    out = np.empty(n, dtype=np.float64)
    for i in range(n):
      out[i] = 0.5 * b[i] + 0.25 * b[(i - 1) % n] + 0.25 * b[(i + 1) % n]
    return out

  def normalized(self) -> np.ndarray:
    s = self.smoothed()
    peak = float(s.max())
    if peak <= 1e-9:
      return s
    return s / peak

  def active(self) -> bool:
    return float(self._bins.sum()) > 1e-6

  def wedge_specs(self, *, min_strength: float = 0.08) -> list[tuple[float, float, float]]:
    """(azimuth_center°, half_width°, strength 0..1) lista rajzoláshoz."""
    norm = self.normalized()
    half = 0.5 * (360.0 / self.n_bins) * 1.15
    out: list[tuple[float, float, float]] = []
    for i, strength in enumerate(norm):
      if strength < min_strength:
        continue
      center = (i + 0.5) * (360.0 / self.n_bins)
      out.append((center, half, float(strength)))
    return out
