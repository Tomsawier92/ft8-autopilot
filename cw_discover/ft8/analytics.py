"""FT8 aggregátumok — 15 s ciklus és órás bontás (ML feature store)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from cw_discover.ft8.decode_meta import compass_bin, hour_key_utc


def _snr_stats(values: list[int]) -> dict:
  if not values:
    return {"snr_mean": None, "snr_min": None, "snr_max": None}
  return {
    "snr_mean": round(sum(values) / len(values), 2),
    "snr_min": min(values),
    "snr_max": max(values),
  }


@dataclass
class _SnrRunning:
  """O(1) SNR aggregátum — nem nő végtelen listával."""

  count: int = 0
  total: int = 0
  mn: int = 99
  mx: int = -99

  def note(self, snr: int) -> None:
    self.count += 1
    self.total += snr
    self.mn = min(self.mn, snr)
    self.mx = max(self.mx, snr)

  def as_dict(self) -> dict:
    if not self.count:
      return {"snr_mean": None, "snr_min": None, "snr_max": None}
    return {
      "snr_mean": round(self.total / self.count, 2),
      "snr_min": self.mn,
      "snr_max": self.mx,
    }


@dataclass
class _DistRunning:
  """O(1) távolság átlag — órás bucket memória."""

  count: int = 0
  total: float = 0.0

  def note(self, km: float) -> None:
    self.count += 1
    self.total += km

  def mean(self) -> float | None:
    if not self.count:
      return None
    return round(self.total / self.count, 1)


@dataclass
class CycleBucket:
  cycle_key: str
  cycle: str
  cycle_start_utc: str = ""
  decode_count: int = 0
  unique_calls: set[str] = field(default_factory=set)
  new_stations: int = 0
  _snr: _SnrRunning = field(default_factory=_SnrRunning)
  snr_values: list[int] = field(default_factory=list)  # legacy: max 64 minta exporthoz
  msg_types: dict[str, int] = field(default_factory=dict)
  audio_rms_sum: float = 0.0
  audio_samples: int = 0
  clip_events: int = 0
  candidate_count: int = 0
  candidate_success: int = 0
  busy_max: float | None = None

  def note_audio(self, raw_rms: float, clip_frac: float) -> None:
    self.audio_rms_sum += raw_rms
    self.audio_samples += 1
    if clip_frac > 0.01:
      self.clip_events += 1

  def note_candidate_search(self, n_candidates: int, busy_max: float | None) -> None:
    self.candidate_count += n_candidates
    if busy_max is not None:
      if self.busy_max is None or busy_max > self.busy_max:
        self.busy_max = round(busy_max, 3)

  def note_decode(
    self,
    *,
    calls: list[str],
    snr: int,
    msg_type: str,
    new_station_calls: list[str],
  ) -> None:
    self.decode_count += 1
    self.unique_calls.update(calls)
    self._snr.note(snr)
    if len(self.snr_values) < 64:
      self.snr_values.append(snr)
    try:
      self.msg_types[msg_type] += 1
    except KeyError:
      self.msg_types[msg_type] = 1
    self.new_stations += len(new_station_calls)

  def to_dict(self) -> dict[str, Any]:
    audio_mean = None
    if self.audio_samples:
      audio_mean = round(self.audio_rms_sum / self.audio_samples, 5)
    out = {
      "cycle_key": self.cycle_key,
      "cycle": self.cycle,
      "cycle_start_utc": self.cycle_start_utc,
      "decode_count": self.decode_count,
      "unique_call_count": len(self.unique_calls),
      "new_stations": self.new_stations,
      "msg_types": dict(self.msg_types),
      "audio_rms_mean": audio_mean,
      "clip_events": self.clip_events,
      "candidate_count": self.candidate_count,
      "busy_max_db": self.busy_max,
      **self._snr.as_dict(),
    }
    return out


@dataclass
class HourBucket:
  hour_utc: str
  decode_count: int = 0
  unique_calls: set[str] = field(default_factory=set)
  new_stations: int = 0
  _snr: _SnrRunning = field(default_factory=_SnrRunning)
  snr_values: list[int] = field(default_factory=list)  # legacy: max 64 minta exporthoz
  msg_types: dict[str, int] = field(default_factory=dict)
  compass_bins: dict[str, int] = field(default_factory=dict)
  _dist: _DistRunning = field(default_factory=_DistRunning)
  distance_values: list[float] = field(default_factory=list)  # legacy: max 64 minta exporthoz
  audio_rms_sum: float = 0.0
  audio_samples: int = 0
  clip_events: int = 0
  mapped_decodes: int = 0

  def note_audio(self, raw_rms: float, clip_frac: float) -> None:
    self.audio_rms_sum += raw_rms
    self.audio_samples += 1
    if clip_frac > 0.01:
      self.clip_events += 1

  def note_decode(
    self,
    *,
    calls: list[str],
    snr: int,
    msg_type: str,
    azimuth_deg: float | None,
    distance_km: float | None,
    has_geo: bool,
    new_station_calls: list[str],
  ) -> None:
    self.decode_count += 1
    self.unique_calls.update(calls)
    self._snr.note(snr)
    if len(self.snr_values) < 64:
      self.snr_values.append(snr)
    try:
      self.msg_types[msg_type] += 1
    except KeyError:
      self.msg_types[msg_type] = 1
    self.new_stations += len(new_station_calls)
    if has_geo:
      self.mapped_decodes += 1
    if azimuth_deg is not None:
      b = compass_bin(azimuth_deg)
      try:
        self.compass_bins[b] += 1
      except KeyError:
        self.compass_bins[b] = 1
    if distance_km is not None:
      self._dist.note(distance_km)
      if len(self.distance_values) < 64:
        self.distance_values.append(distance_km)

  def to_dict(self) -> dict[str, Any]:
    audio_mean = None
    if self.audio_samples:
      audio_mean = round(self.audio_rms_sum / self.audio_samples, 5)
    dist_mean = self._dist.mean()
    out = {
      "hour_utc": self.hour_utc,
      "decode_count": self.decode_count,
      "unique_call_count": len(self.unique_calls),
      "new_stations": self.new_stations,
      "mapped_decodes": self.mapped_decodes,
      "msg_types": dict(self.msg_types),
      "compass_bins": dict(self.compass_bins),
      "distance_km_mean": dist_mean,
      "audio_rms_mean": audio_mean,
      "clip_events": self.clip_events,
      **self._snr.as_dict(),
    }
    return out


class SessionAnalytics:
  def __init__(self) -> None:
    self.cycles: dict[str, CycleBucket] = {}
    self.hours: dict[str, HourBucket] = {}

  def reset(self) -> None:
    self.cycles.clear()
    self.hours.clear()

  def _cycle(self, cycle_key: str, cycle: str, cycle_start_utc: str) -> CycleBucket:
    if cycle_key not in self.cycles:
      self.cycles[cycle_key] = CycleBucket(
        cycle_key=cycle_key,
        cycle=cycle,
        cycle_start_utc=cycle_start_utc,
      )
    return self.cycles[cycle_key]

  def _hour(self, ts: float) -> HourBucket:
    key = hour_key_utc(ts)
    if key not in self.hours:
      self.hours[key] = HourBucket(hour_utc=key)
    return self.hours[key]

  def note_audio(self, ts: float, cycle_key: str, cycle: str, raw_rms: float, clip_frac: float) -> None:
    self._hour(ts).note_audio(raw_rms, clip_frac)
    if cycle_key in self.cycles:
      self.cycles[cycle_key].note_audio(raw_rms, clip_frac)

  def note_candidate_search(
    self, cycle_key: str, cycle: str, cycle_start_utc: str, n_candidates: int, busy_max: float | None
  ) -> None:
    self._cycle(cycle_key, cycle, cycle_start_utc).note_candidate_search(n_candidates, busy_max)

  def note_decode(
    self,
    *,
    ts: float,
    cycle_key: str,
    cycle: str,
    cycle_start_utc: str,
    calls: list[str],
    snr: int,
    msg_type: str,
    azimuth_deg: float | None,
    distance_km: float | None,
    has_geo: bool,
    new_station_calls: list[str],
  ) -> None:
    self._cycle(cycle_key, cycle, cycle_start_utc).note_decode(
      calls=calls,
      snr=snr,
      msg_type=msg_type,
      new_station_calls=new_station_calls,
    )
    self._hour(ts).note_decode(
      calls=calls,
      snr=snr,
      msg_type=msg_type,
      azimuth_deg=azimuth_deg,
      distance_km=distance_km,
      has_geo=has_geo,
      new_station_calls=new_station_calls,
    )
