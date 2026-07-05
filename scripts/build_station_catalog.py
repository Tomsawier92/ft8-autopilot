#!/usr/bin/env python3
"""Összesített állomás-katalógus a decode JSONL logokból."""
from __future__ import annotations

import json
import statistics
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cw_discover.ft8.decode_meta import classify_message_type, compass_bin
from cw_discover.ft8.grid_geo import (
  _haversine_km,
  extract_callsigns_from_message,
  extract_grid_from_message,
  grid_to_latlong,
)
from cw_discover.ft8.home_qth import DEFAULT_HOME
from cw_discover.paths import LOG_DIR
OUT = ROOT / "data" / "station_catalog.json"
SCHEMA = 1


def load_decodes() -> list[dict[str, Any]]:
  rows: list[dict[str, Any]] = []
  log_days: list[str] = []
  for fp in sorted(LOG_DIR.glob("*/decodes.jsonl")):
    if fp.parent.name == "1970-01-01":
      continue
    log_days.append(fp.parent.name)
    with fp.open(encoding="utf-8") as f:
      for line in f:
        line = line.strip()
        if not line:
          continue
        try:
          rows.append(json.loads(line))
        except json.JSONDecodeError:
          continue
  rows.sort(key=lambda r: r.get("time_received", 0))
  return rows, log_days


def _grid_for_call_in_decode(call: str, rec: dict[str, Any]) -> str | None:
  msg = rec.get("message", "")
  grid_msg = extract_grid_from_message(msg)
  if grid_msg:
    calls = extract_callsigns_from_message(msg)
    if call in calls:
      return grid_msg
  geo = rec.get("geo") or {}
  if geo.get("grid"):
    return str(geo["grid"])
  return None


def build_catalog(rows: list[dict[str, Any]]) -> dict[str, Any]:
  home = DEFAULT_HOME
  stations: dict[str, dict[str, Any]] = {}

  for rec in rows:
    msg = rec.get("message", "")
    calls = rec.get("calls") or extract_callsigns_from_message(msg)
    if not calls:
      continue
    ts = float(rec.get("time_received", 0))
    time_iso = rec.get("time_iso") or datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    snr = int(rec.get("snr", 0))
    band = rec.get("band") or ""
    msg_type = rec.get("msg_type") or classify_message_type(msg)

    for call in calls:
      if len(call) < 3:
        continue
      call = call.upper()
      st = stations.get(call)
      if not st:
        st = {
          "grids": Counter(),
          "first_heard": time_iso,
          "last_heard": time_iso,
          "first_heard_ts": ts,
          "last_heard_ts": ts,
          "hear_count": 0,
          "best_snr": snr,
          "worst_snr": snr,
          "snrs": [],
          "bands": Counter(),
          "msg_types": Counter(),
        }
        stations[call] = st

      st["hear_count"] += 1
      st["snrs"].append(snr)
      st["best_snr"] = max(st["best_snr"], snr)
      st["worst_snr"] = min(st["worst_snr"], snr)
      if ts < st["first_heard_ts"]:
        st["first_heard_ts"] = ts
        st["first_heard"] = time_iso
      if ts > st["last_heard_ts"]:
        st["last_heard_ts"] = ts
        st["last_heard"] = time_iso
      if band:
        st["bands"][band] += 1
      st["msg_types"][msg_type] += 1
      g = _grid_for_call_in_decode(call, rec)
      if g:
        st["grids"][g] += 1

  out_stations: dict[str, dict[str, Any]] = {}
  with_grid = 0
  for call, st in sorted(stations.items()):
    grid = None
    grid_confidence = None
    alt_grids: dict[str, int] | None = None
    if st["grids"]:
      grid, n = st["grids"].most_common(1)[0]
      grid_confidence = round(n / st["hear_count"], 3)
      alt_grids = dict(st["grids"].most_common(5))
      with_grid += 1

    lat = lon = distance_km = azimuth_deg = None
    compass = None
    if grid:
      try:
        lat, lon = grid_to_latlong(grid[:4])
        distance_km = round(_haversine_km(home.lat, home.lon, lat, lon), 1)
        from cw_discover.ft8.decode_meta import bearing_deg

        azimuth_deg = round(bearing_deg(home.lat, home.lon, lat, lon), 1)
        compass = compass_bin(azimuth_deg)
      except Exception:
        pass

    med_snr = int(statistics.median(st["snrs"]))
    out_stations[call] = {
      "grid": grid,
      "grid_confidence": grid_confidence,
      "alt_grids": alt_grids,
      "lat": lat,
      "lon": lon,
      "distance_km": distance_km,
      "azimuth_deg": azimuth_deg,
      "compass": compass,
      "first_heard": st["first_heard"],
      "last_heard": st["last_heard"],
      "hear_count": st["hear_count"],
      "best_snr": st["best_snr"],
      "worst_snr": st["worst_snr"],
      "median_snr": med_snr,
      "bands": dict(st["bands"]),
      "msg_types": dict(st["msg_types"]),
      "cq_count": int(st["msg_types"].get("cq", 0)),
    }

  first_ts = rows[0].get("time_received") if rows else None
  last_ts = rows[-1].get("time_received") if rows else None
  return {
    "schema": SCHEMA,
    "generated_at": datetime.now(tz=timezone.utc).isoformat(),
    "qth": {
      "name": home.name,
      "grid": home.grid,
      "lat": home.lat,
      "lon": home.lon,
    },
    "stats": {
      "decode_rows": len(rows),
      "unique_callsigns": len(out_stations),
      "with_grid": with_grid,
      "without_grid": len(out_stations) - with_grid,
      "log_first": datetime.fromtimestamp(first_ts, tz=timezone.utc).isoformat() if first_ts else None,
      "log_last": datetime.fromtimestamp(last_ts, tz=timezone.utc).isoformat() if last_ts else None,
    },
    "stations": out_stations,
  }


def main() -> int:
  print("Decode logok betöltése…")
  rows, log_days = load_decodes()
  print(f"  {len(rows)} dekód, napok: {', '.join(log_days)}")
  catalog = build_catalog(rows)
  OUT.parent.mkdir(parents=True, exist_ok=True)
  OUT.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
  s = catalog["stats"]
  print(f"Katalógus: {OUT}")
  print(f"  {s['unique_callsigns']} hívójel ({s['with_grid']} lokátorral, {s['without_grid']} nélkül)")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
