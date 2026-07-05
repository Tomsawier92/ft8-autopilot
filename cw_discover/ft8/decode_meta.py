"""FT8 dekód meta — üzenettípus, irány, DSP mezők (AI / elemzés)."""
from __future__ import annotations

import math
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

from cw_discover.ft8.grid_geo import (
  REPORT_RE,
  is_callsign,
  lookup,
)
from cw_discover.ft8.home_qth import HomeQth

SCHEMA_DECODE = 1
SCHEMA_CANDIDATE = 1

MSG_TYPES = frozenset({"unknown", "cq", "73", "report", "qso", "grid", "other"})


def classify_message_type(message: str) -> str:
  return _classify_cached(message_stripped(message))


def message_stripped(message: str) -> str:
  """Üzenet strip — közös LRU cache (meta/triplet/geo)."""
  return _message_strip_cached(message)


@lru_cache(maxsize=4096)
def _message_strip_cached(message: str) -> str:
  return message.strip()


def message_upper(message: str) -> str:
  """Strip + upper egy cache passzban (dedup, substring, CQ szűrés)."""
  return _message_upper_cached(message_stripped(message))


@lru_cache(maxsize=4096)
def _message_upper_cached(message: str) -> str:
  return message.upper()


def message_preamble(message: str) -> tuple[str, list[str]]:
  """Üzenettípus + hívójelek egy strip/cache passzban."""
  mt, calls = _message_preamble_cached(message_stripped(message))
  return mt, list(calls)


def message_preamble_geo(message: str, home: HomeQth | None) -> tuple[str, list[str], dict]:
  """Üzenettípus + hívójelek + geo egy cache passzban (GUI dekód)."""
  m = message_stripped(message)
  key = (
    m,
    round(home.lat, 3) if home else 0.0,
    round(home.lon, 3) if home else 0.0,
    home.grid if home else "",
  )
  mt, calls, geo_items = _message_preamble_geo_cached(key)
  return mt, list(calls), dict(geo_items)


@lru_cache(maxsize=4096)
def _message_preamble_geo_cached(
  key: tuple[str, float, float, str],
) -> tuple[str, tuple[str, ...], tuple[tuple[str, object], ...]]:
  message, home_lat, home_lon, home_grid = key
  from cw_discover.ft8.grid_geo import _extract_callsigns_cached

  return (
    _classify_cached(message),
    _extract_callsigns_cached(message),
    _geo_cached((message, home_lat, home_lon, home_grid)),
  )


@lru_cache(maxsize=4096)
def _message_preamble_cached(message: str) -> tuple[str, tuple[str, ...]]:
  from cw_discover.ft8.grid_geo import _extract_callsigns_cached

  return _classify_cached(message), _extract_callsigns_cached(message)


@lru_cache(maxsize=4096)
def _classify_cached(message: str) -> str:
  parts = _message_upper_cached(message).split()
  if not parts:
    return "unknown"
  if parts[0] == "CQ":
    return "cq"
  if any(p in ("73", "RR73") for p in parts):
    return "73"
  if any(REPORT_RE.match(p) for p in parts):
    return "report"
  if len(parts) >= 2 and is_callsign(parts[0]) and is_callsign(parts[1]):
    return "qso"
  from cw_discover.ft8.grid_geo import _extract_grid_cached

  if _extract_grid_cached(message):
    return "grid"
  return "other"


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
  """Azimut ° QTH-tól a cél felé (0=É, 90=K, 180=Ny, 270=É)."""
  return _bearing_deg_cached(
    round(lat1, 1), round(lon1, 1), round(lat2, 1), round(lon2, 1)
  )


@lru_cache(maxsize=8192)
def _bearing_deg_cached(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
  phi1 = math.radians(lat1)
  phi2 = math.radians(lat2)
  dlam = math.radians(lon2 - lon1)
  x = math.sin(dlam) * math.cos(phi2)
  y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlam)
  return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def compass_bin(azimuth_deg: float | None) -> str:
  if azimuth_deg is None:
    return "?"
  return _compass_bin_cached(int((azimuth_deg + 22.5) // 45) % 8)


@lru_cache(maxsize=8)
def _compass_bin_cached(idx: int) -> str:
  bins = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
  return bins[idx]


def hour_key_utc(ts: float) -> str:
  return _hour_key_cached(int(ts // 3600))


@lru_cache(maxsize=256)
def _hour_key_cached(ts_hour_bucket: int) -> str:
  from datetime import datetime, timezone

  return datetime.fromtimestamp(ts_hour_bucket * 3600, tz=timezone.utc).strftime("%Y-%m-%dT%H")


def day_key_utc(ts: float) -> str:
  return _day_key_cached(int(ts // 86400))


@lru_cache(maxsize=64)
def _day_key_cached(ts_day_bucket: int) -> str:
  from datetime import datetime, timezone

  return datetime.fromtimestamp(ts_day_bucket * 86400, tz=timezone.utc).strftime("%Y-%m-%d")


_daily_decodes_cache: tuple[str, Path, str] = ("", Path(), "")


def daily_decodes_jsonl(log_dir: Path) -> Path:
  global _daily_decodes_cache
  day = day_key_utc(time.time())
  if day == _daily_decodes_cache[0]:
    return _daily_decodes_cache[1]
  path = log_dir / day / "decodes.jsonl"
  _daily_decodes_cache = (day, path, str(path))
  return path


def daily_decodes_jsonl_str(log_dir: Path) -> str:
  daily_decodes_jsonl(log_dir)
  return _daily_decodes_cache[2]


def daily_decodes_day(log_dir: Path) -> str:
  daily_decodes_jsonl(log_dir)
  return _daily_decodes_cache[0]


def grid_in_message_geo(geo: dict) -> str | None:
  """Grid kizárólag az üzenetből (nem callsign cache-ből)."""
  if geo.get("grid_source") != "message":
    return None
  g = geo.get("grid")
  return g or None


def time_iso_utc(ts: float) -> str:
  return _time_iso_cached(int(ts * 1000))


@lru_cache(maxsize=4096)
def _time_iso_cached(ts_ms: int) -> str:
  from datetime import datetime, timezone

  return datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc).isoformat()


def time_hms_utc(ts: float) -> str:
  return _time_hms_cached(int(ts))


@lru_cache(maxsize=4096)
def _time_hms_cached(ts_sec: int) -> str:
  from datetime import datetime, timezone

  return datetime.fromtimestamp(ts_sec, tz=timezone.utc).strftime("%H:%M:%S")


def cycle_key(cycle: str, ts: float) -> str:
  return _cycle_key_cached(cycle, int(ts // 86400))


@lru_cache(maxsize=512)
def _cycle_key_cached(cycle: str, ts_day_bucket: int) -> str:
  return f"{_day_key_cached(ts_day_bucket)}T{cycle}"


def grid_source_for_message(message: str) -> tuple[str | None, str]:
  return _grid_source_cached(message_stripped(message))


@lru_cache(maxsize=4096)
def _grid_source_cached(message: str) -> tuple[str | None, str]:
  from cw_discover.ft8.grid_geo import _extract_callsigns_cached, _extract_grid_cached

  g = _extract_grid_cached(message)
  if g:
    return g, "message"
  for call in _extract_callsigns_cached(message):
    cached = lookup.grid_for_call(call)
    if cached:
      return cached, "cache"
  return None, "unknown"


def dsp_from_candidate(candidate: Any) -> dict:
  key = (
    round(float(getattr(candidate, "sync_score", 0.0)), 3),
    int(getattr(candidate, "ncheck0", 99)),
    int(getattr(candidate, "ncheck", 99)),
    int(getattr(candidate, "n_its", 0)),
    round(float(getattr(candidate, "llr_sd", 0.0)), 4),
    int(getattr(candidate, "h0_idx", 0)),
    int(getattr(candidate, "f0_idx", 0)),
    str(getattr(candidate, "decoder", "PyFT8")),
    str(getattr(candidate, "decode_path", "") or ""),
  )
  return _dsp_cached(key)


@lru_cache(maxsize=2048)
def _dsp_cached(key: tuple) -> dict:
  sync_score, ncheck0, ncheck, n_its, llr_sd, h0_idx, f0_idx, decoder, decode_path = key
  return {
    "sync_score": sync_score,
    "ncheck0": ncheck0,
    "ncheck": ncheck,
    "n_its": n_its,
    "llr_sd": llr_sd,
    "h0_idx": h0_idx,
    "f0_idx": f0_idx,
    "decoder": decoder,
    "decode_path": decode_path,
  }


def candidate_record(candidate: Any, *, cycle: str, time_received: float) -> dict:
  success = bool(getattr(candidate, "msg", ""))
  return {
    "schema": SCHEMA_CANDIDATE,
    "time_iso": time_iso_utc(time_received),
    "time_received": time_received,
    "cycle": cycle,
    "success": success,
    "message": getattr(candidate, "msg", "") or "",
    "snr": int(getattr(candidate, "snr", -30)),
    "dt": float(getattr(candidate, "dt", 0.0)),
    "f_hz": int(getattr(candidate, "fHz", 0)),
    "dsp": dsp_from_candidate(candidate),
  }


def geo_for_message(message: str, home: HomeQth | None) -> dict:
  key = (
    message_stripped(message),
    round(home.lat, 3) if home else 0.0,
    round(home.lon, 3) if home else 0.0,
    home.grid if home else "",
  )
  return dict(_geo_cached(key))


@lru_cache(maxsize=4096)
def _geo_cached(key: tuple) -> tuple[tuple[str, object], ...]:
  message, home_lat, home_lon, home_grid = key
  from cw_discover.ft8.grid_geo import grid_centre_deg

  home = None
  if home_grid:
    from cw_discover.ft8.home_qth import HomeQth

    home = HomeQth(name="", country="", grid=home_grid, lat=home_lat, lon=home_lon)
  grid, grid_source = _grid_source_cached(message)
  out: dict = {
    "grid": grid or "",
    "grid_source": grid_source,
    "lat": None,
    "lon": None,
    "distance_km": None,
    "azimuth_deg": None,
    "compass": "?",
  }
  if not grid:
    return tuple(out.items())
  if home is not None:
    from cw_discover.ft8.grid_geo import grid4_upper, station_geo_for_g4

    g4 = grid4_upper(grid)
    lat, lon, dist, az = station_geo_for_g4(g4, home_lat, home_lon)
    if not g4:
      return tuple(out.items())
    out["lat"] = round(lat, 5)
    out["lon"] = round(lon, 5)
    if dist is not None:
      out["distance_km"] = dist
    if az is not None:
      out["azimuth_deg"] = az
      out["compass"] = compass_bin(az)
    return tuple(out.items())
  try:
    lat, lon = grid_centre_deg(grid)
  except Exception:
    return tuple(out.items())
  out["lat"] = round(lat, 5)
  out["lon"] = round(lon, 5)
  return tuple(out.items())
