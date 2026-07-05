"""FT8 munkamenet napló — állomások, JSONL/Parquet export, órás/ciklus aggregátum."""
from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cw_discover.ft8.analytics import SessionAnalytics
from cw_discover.ft8.decode_meta import (
  SCHEMA_DECODE,
  candidate_record,
  classify_message_type,
  cycle_key,
  day_key_utc,
  geo_for_message,
  grid_in_message_geo,
  hour_key_utc,
  message_preamble,
  message_preamble_geo,
  time_iso_utc,
)
from cw_discover.ft8.grid_geo import (
  _call_key,
  grid4_upper,
  grid_centre_deg,
  station_geo_for_g4,
  lookup,
)
from cw_discover.ft8.atomic_io import DailyBufferedWriter, atomic_write_json
from cw_discover.ft8.home_qth import DEFAULT_HOME, HOME_LAT, HOME_LON, HomeQth

from cw_discover.paths import LOG_DIR

# Kompatibilitás (régi tesztek): LIVE = napi log gyökér
LIVE_DIR = LOG_DIR
EXPORT_VERSION = 4
MAX_DECODES_IN_RAM = 10_000


def day_key(ts: float | None = None) -> str:
  t = ts if ts is not None else datetime.now(tz=timezone.utc).timestamp()
  return day_key_utc(t)


@dataclass
class HeardStation:
  call: str
  grid: str
  lat: float | None
  lon: float | None
  snr: int
  rf_khz: float
  band: str
  first_heard: float
  last_heard: float
  hear_count: int = 1
  best_snr: int = -99
  worst_snr: int = 99
  distance_km: float | None = None
  azimuth_deg: float | None = None
  location_text: str = ""
  sample_message: str = ""
  msg_types: dict[str, int] = field(default_factory=dict)

  @property
  def on_map(self) -> bool:
    return self.lat is not None and self.lon is not None

  def to_dict(self) -> dict:
    return asdict(self)


def _iso(ts: float) -> str:
  return time_iso_utc(ts)


def _cycle_start_iso(cycle_start_time: float | None, fallback_ts: float) -> str:
  if cycle_start_time is not None:
    return _iso(cycle_start_time)
  return _iso(fallback_ts)


def _write_parquet_optional(path: Path, rows: list[dict]) -> Path | None:
  if not rows:
    return None
  try:
    import pyarrow as pa
    import pyarrow.parquet as pq
  except ImportError:
    return None
  table = pa.Table.from_pylist(rows)
  out = path.with_suffix(".parquet")
  pq.write_table(table, out)
  return out


def _default_home_dict() -> dict:
  h = DEFAULT_HOME
  return {"name": h.name, "country": h.country, "grid": h.grid, "lat": h.lat, "lon": h.lon}


@dataclass
class SessionLog:
  band: str = "40m"
  dial_mhz: float = 7.074
  started_at: float = field(default_factory=lambda: datetime.now(tz=timezone.utc).timestamp())
  session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
  antenna_note: str = ""
  pulse_device: str = ""
  audio_settings: dict = field(default_factory=dict)
  home_qth: dict = field(default_factory=_default_home_dict)
  stations: dict[str, HeardStation] = field(default_factory=dict)
  decodes: list[dict] = field(default_factory=list)
  analytics: SessionAnalytics = field(default_factory=SessionAnalytics)
  power_safe: bool = False
  log_candidates: bool = True
  _writer: DailyBufferedWriter | None = field(default=None, repr=False)
  _snapshot_path: Path | None = field(default=None, repr=False)
  _last_audio: dict = field(default_factory=dict, repr=False)
  _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

  def _ensure_writer(self) -> DailyBufferedWriter:
    if self._writer is None:
      self._writer = DailyBufferedWriter(LOG_DIR, power_safe=self.power_safe)
    else:
      self._writer.power_safe = self.power_safe
    return self._writer

  def log_dir_for_day(self, ts: float | None = None) -> Path:
    return LOG_DIR / day_key(ts)

  def reset(
    self,
    band: str,
    dial_mhz: float,
    *,
    pulse_device: str = "",
    audio_settings: dict | None = None,
    home: HomeQth | None = None,
  ) -> None:
    self.band = band
    self.dial_mhz = dial_mhz
    self.started_at = datetime.now(tz=timezone.utc).timestamp()
    self.session_id = str(uuid.uuid4())
    self.pulse_device = pulse_device
    self.audio_settings = dict(audio_settings or {})
    if home is not None:
      self.home_qth = {
        "name": home.name,
        "country": home.country,
        "grid": home.grid,
        "lat": home.lat,
        "lon": home.lon,
      }
    self.stations.clear()
    self.decodes.clear()
    self.analytics.reset()
    self._last_audio.clear()
    self._ensure_writer()
    if self.power_safe:
      self._snapshot_path = self.log_dir_for_day() / "session_snapshot.json"
    else:
      self._snapshot_path = None

  def set_power_safe(self, enabled: bool) -> None:
    with self._lock:
      self.power_safe = enabled
      if self._writer is not None:
        self._writer.power_safe = enabled
      if enabled:
        self._snapshot_path = self.log_dir_for_day() / "session_snapshot.json"
      else:
        self._snapshot_path = None

  def set_log_candidates(self, enabled: bool) -> None:
    self.log_candidates = enabled

  @property
  def session_dir(self) -> Path | None:
    """Kompatibilitás: mai nap log mappája."""
    return self.log_dir_for_day()

  def _home(self) -> HomeQth:
    h = self.home_qth
    return HomeQth(
      name=h.get("name", "QTH"),
      country=h.get("country", ""),
      grid=h.get("grid", ""),
      lat=float(h.get("lat", 0)),
      lon=float(h.get("lon", 0)),
    )

  def station_count(self) -> int:
    return len(self.stations)

  def mapped_count(self) -> int:
    return sum(1 for s in self.stations.values() if s.on_map)

  def station_list(self) -> list[HeardStation]:
    return list(self.stations.values())

  def map_station_list(self, *, cq_only: bool = False) -> list[HeardStation]:
    spots = [s for s in self.stations.values() if s.on_map]
    if cq_only:
      spots = [s for s in spots if s.msg_types.get("cq", 0) > 0]
    return spots

  def note_audio_levels(self, raw_rms: float, clip_frac: float, cycle: str, ts: float) -> None:
    with self._lock:
      self._last_audio = {"raw_rms": raw_rms, "clip_frac": clip_frac}
      ck = cycle_key(cycle, ts)
      self.analytics.note_audio(ts, ck, cycle, raw_rms, clip_frac)

  def note_cycle_search(
    self, cycle: str, cycle_start_time: float | None, n_candidates: int, busy_max: float | None, ts: float
  ) -> None:
    with self._lock:
      ck = cycle_key(cycle, ts)
      ciso = _cycle_start_iso(cycle_start_time, ts)
      self.analytics.note_candidate_search(ck, cycle, ciso, n_candidates, busy_max)

  def add_candidate(self, candidate: Any, cycle: str, ts: float) -> None:
    if not self.log_candidates:
      return
    if not getattr(candidate, "decode_completed", False):
      return
    # Csak sikeres vagy LDPC-közeli kísérlet (AI-hoz elég, ~50× kevesebb sor)
    msg = getattr(candidate, "msg", "") or ""
    ncheck = int(getattr(candidate, "ncheck", 99))
    llr_sd = float(getattr(candidate, "llr_sd", 0.0))
    if not msg:
      sync = float(getattr(candidate, "sync_score", 0.0))
      if llr_sd < 0.5 or not (2 <= ncheck <= 6) or sync < 2.0:
        return
    rec = candidate_record(candidate, cycle=cycle, time_received=ts)
    with self._lock:
      self._ensure_writer().append_candidate(rec)

  def add_decode(
    self,
    *,
    decode_id: int,
    message: str,
    snr: int,
    rf_khz: float,
    cycle: str,
    audio_hz: int,
    dt: float,
    time_received: float,
    cycle_start_utc: str = "",
    cycle_start_time: float | None = None,
    dsp: dict | None = None,
    audio: dict | None = None,
    location_text: str = "",
    geo: dict | None = None,
    msg_type: str | None = None,
    calls: list[str] | None = None,
  ) -> list[str]:
    # Geo / osztályozás lock nélkül — kevesebb contention a QSO szálon.
    home = self._home()
    if msg_type is None and calls is None and geo is None:
      msg_type, calls, geo = message_preamble_geo(message, home)
    else:
      if msg_type is None or calls is None:
        mt, call_list = message_preamble(message)
        if msg_type is None:
          msg_type = mt
        if calls is None:
          calls = call_list
      if geo is None:
        geo = geo_for_message(message, home)
    ck = cycle_key(cycle, time_received)
    hour = hour_key_utc(time_received)
    grid_in_msg = grid_in_message_geo(geo)
    if grid_in_msg:
      lookup.remember_callsigns(message, grid_in_msg, calls)
    ciso = cycle_start_utc or _cycle_start_iso(cycle_start_time, time_received)
    with self._lock:
      return self._add_decode_unlocked(
        decode_id=decode_id,
        message=message,
        snr=snr,
        rf_khz=rf_khz,
        cycle=cycle,
        audio_hz=audio_hz,
        dt=dt,
        time_received=time_received,
        cycle_start_utc=cycle_start_utc,
        cycle_start_time=cycle_start_time,
        dsp=dsp,
        audio=audio,
        location_text=location_text,
        _pre={
          "home": home,
          "msg_type": msg_type,
          "calls": calls,
          "geo": geo,
          "ck": ck,
          "hour": hour,
          "ciso": ciso,
          "grid_in_msg": grid_in_msg,
        },
      )

  def _add_decode_unlocked(
    self,
    *,
    decode_id: int,
    message: str,
    snr: int,
    rf_khz: float,
    cycle: str,
    audio_hz: int,
    dt: float,
    time_received: float,
    cycle_start_utc: str = "",
    cycle_start_time: float | None = None,
    dsp: dict | None = None,
    audio: dict | None = None,
    location_text: str = "",
    _pre: dict | None = None,
  ) -> list[str]:
    if _pre is not None:
      home = _pre["home"]
      msg_type = _pre["msg_type"]
      calls = _pre["calls"]
      geo = _pre["geo"]
      ck = _pre["ck"]
      hour = _pre["hour"]
      ciso = _pre["ciso"]
      grid_in_msg = _pre["grid_in_msg"]
    else:
      home = self._home()
      msg_type, calls, geo = message_preamble_geo(message, home)
      ck = cycle_key(cycle, time_received)
      hour = hour_key_utc(time_received)
      ciso = cycle_start_utc or _cycle_start_iso(cycle_start_time, time_received)
      grid_in_msg = grid_in_message_geo(geo)
      if grid_in_msg:
        lookup.remember_callsigns(message, grid_in_msg, calls)

    new_on_map: list[str] = []
    new_station_calls: list[str] = []
    geo_grid = (geo.get("grid") or "")[:4]
    geo_lat = geo.get("lat")
    geo_lon = geo.get("lon")
    geo_dist = geo.get("distance_km")
    geo_az = geo.get("azimuth_deg")

    for call in calls:
      grid = lookup.grid_for_call(call)
      lat: float | None = None
      lon: float | None = None
      dist: float | None = None
      az: float | None = None
      if grid:
        g4 = grid4_upper(grid)
        if geo_grid and g4 == geo_grid and geo_lat is not None and geo_lon is not None:
          lat, lon = float(geo_lat), float(geo_lon)
          dist = float(geo_dist) if geo_dist is not None else None
          az = float(geo_az) if geo_az is not None else None
        else:
          if home:
            lat, lon, dist, az = station_geo_for_g4(g4, HOME_LAT, HOME_LON)
            if az is not None:
              az = round(az, 1)
          else:
            lat, lon = grid_centre_deg(g4)

      if call in self.stations:
        st = self.stations[call]
        st.last_heard = time_received
        st.hear_count += 1
        st.best_snr = max(st.best_snr, snr)
        st.worst_snr = min(st.worst_snr, snr)
        try:
          st.msg_types[msg_type] += 1
        except KeyError:
          st.msg_types[msg_type] = 1
        if snr > st.snr:
          st.snr = snr
        if grid and not st.grid:
          st.grid = g4
          st.lat, st.lon = lat, lon
          st.distance_km = dist
          st.azimuth_deg = az
          if st.on_map:
            new_on_map.append(call)
        if location_text and not st.location_text and grid:
          st.location_text = location_text
        continue

      new_station_calls.append(call)
      st = HeardStation(
        call=call,
        grid=g4 if grid else "",
        lat=lat,
        lon=lon,
        snr=snr,
        best_snr=snr,
        worst_snr=snr,
        distance_km=dist,
        azimuth_deg=az,
        rf_khz=rf_khz,
        band=self.band,
        first_heard=time_received,
        last_heard=time_received,
        location_text=location_text if grid else "",
        sample_message=message,
        msg_types={msg_type: 1},
      )
      self.stations[call] = st
      if st.on_map:
        new_on_map.append(call)

    record = {
      "schema": SCHEMA_DECODE,
      "id": decode_id,
      "session_id": self.session_id,
      "message": message,
      "msg_type": msg_type,
      "calls": calls,
      "snr": snr,
      "dt": dt,
      "audio_hz": audio_hz,
      "rf_khz": rf_khz,
      "band": self.band,
      "dial_mhz": self.dial_mhz,
      "cycle": cycle,
      "cycle_key": ck,
      "cycle_start_utc": ciso,
      "hour_utc": hour,
      "time_received": time_received,
      "time_iso": _iso(time_received),
      "dsp": dsp or {},
      "audio": audio or dict(self._last_audio),
      "geo": geo,
      "flags": {
        "new_station_calls": new_station_calls,
        "is_new_station": bool(new_station_calls),
      },
    }
    self.decodes.append(record)
    if len(self.decodes) > MAX_DECODES_IN_RAM:
      self.decodes = self.decodes[-MAX_DECODES_IN_RAM:]
    self._ensure_writer().append_decode(record)

    self.analytics.note_decode(
      ts=time_received,
      cycle_key=ck,
      cycle=cycle,
      cycle_start_utc=ciso,
      calls=calls,
      snr=snr,
      msg_type=msg_type,
      azimuth_deg=float(geo_az) if geo_az is not None else None,
      distance_km=float(geo_dist) if geo_dist is not None else None,
      has_geo=bool(geo_grid),
      new_station_calls=new_station_calls,
    )
    return new_on_map

  def flush_logs(self) -> None:
    """Puffer → napi JSONL fájlok (Stop / kilépés / kényszerített mentés)."""
    with self._lock:
      if self._writer is not None:
        self._writer.flush()

  def _snapshot_payload_unlocked(self) -> dict:
    return {
      **self.metadata_dict(),
      "power_safe": True,
      "cycles": [b.to_dict() for b in self.analytics.cycles.values()],
      "hours": [b.to_dict() for b in self.analytics.hours.values()],
      "stations": [s.to_dict() for s in self.station_list()],
      "decodes_tail": self.decodes[-200:],
    }

  def _write_snapshot_unlocked(self) -> None:
    if self._snapshot_path is None:
      return
    atomic_write_json(self._snapshot_path, self._snapshot_payload_unlocked(), compact=True, fsync=True)

  def flush_snapshot(self) -> None:
    """Puffer mentés + opcionális atomi pillanatkép (Stop / kilépés)."""
    with self._lock:
      if self._writer is not None:
        self._writer.flush()
      if self.power_safe:
        self._write_snapshot_unlocked()

  def shutdown(self) -> None:
    """Tiszta kilépés: puffer → lemez, writer szál leáll (log fájlok megmaradnak)."""
    with self._lock:
      if self._writer is not None:
        self._writer.flush()
        if self.power_safe:
          self._write_snapshot_unlocked()
        self._writer.close()
        self._writer = None

  def set_location_for_call(self, call: str, text: str) -> None:
    st = self.stations.get(_call_key(call))
    if st and text and text != "—":
      st.location_text = text

  def metadata_dict(self) -> dict:
    return {
      "session_id": self.session_id,
      "format": "cw-discover-ft8-session",
      "version": EXPORT_VERSION,
      "started_at": _iso(self.started_at),
      "exported_at": datetime.now(tz=timezone.utc).isoformat(),
      "band": self.band,
      "dial_mhz": self.dial_mhz,
      "pulse_device": self.pulse_device,
      "audio_settings": self.audio_settings,
      "home_qth": self.home_qth,
      "antenna_note": self.antenna_note,
      "unique_by_callsign": True,
      "station_count": self.station_count(),
      "mapped_station_count": self.mapped_count(),
      "decode_count": len(self.decodes),
      "pending_log_rows": self._writer.pending_count() if self._writer else 0,
      "log_flush_interval_s": int(DailyBufferedWriter.FLUSH_INTERVAL_S),
      "candidate_log": str(self.log_dir_for_day() / "candidates.jsonl"),
      "decode_log": str(self.log_dir_for_day() / "decodes.jsonl"),
    }

  def export_json(self, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
      **self.metadata_dict(),
      "cycles": [b.to_dict() for b in self.analytics.cycles.values()],
      "hours": [b.to_dict() for b in self.analytics.hours.values()],
      "stations": [s.to_dict() for s in self.station_list()],
      "decodes": self.decodes,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

  def export_bundle(self, json_path: Path) -> dict[str, Path]:
    """JSON összefoglaló + JSONL + opcionális Parquet fájlok."""
    self.flush_logs()
    json_path.parent.mkdir(parents=True, exist_ok=True)
    base = json_path.with_suffix("")
    self.export_json(json_path)

    out: dict[str, Path] = {"session_json": json_path}

    hours_path = base.with_name(base.name + "_hours.json")
    hours_path.write_text(
      json.dumps([b.to_dict() for b in self.analytics.hours.values()], indent=2, ensure_ascii=False),
      encoding="utf-8",
    )
    out["hours_json"] = hours_path

    cycles_path = base.with_name(base.name + "_cycles.json")
    cycles_path.write_text(
      json.dumps([b.to_dict() for b in self.analytics.cycles.values()], indent=2, ensure_ascii=False),
      encoding="utf-8",
    )
    out["cycles_json"] = cycles_path

    stations_path = base.with_name(base.name + "_stations.json")
    stations_path.write_text(
      json.dumps([s.to_dict() for s in self.station_list()], indent=2, ensure_ascii=False),
      encoding="utf-8",
    )
    out["stations_json"] = stations_path

    today = self.log_dir_for_day()
    if today.exists():
      out["log_dir"] = today
      dec_path = today / "decodes.jsonl"
      cand_path = today / "candidates.jsonl"
      if dec_path.exists():
        out["decodes_jsonl"] = dec_path
      if cand_path.exists():
        out["candidates_jsonl"] = cand_path

    pq = _write_parquet_optional(base.with_name(base.name + "_decodes"), self.decodes)
    if pq:
      out["decodes_parquet"] = pq
    pq_h = _write_parquet_optional(
      base.with_name(base.name + "_hours"), [b.to_dict() for b in self.analytics.hours.values()]
    )
    if pq_h:
      out["hours_parquet"] = pq_h
    pq_s = _write_parquet_optional(
      base.with_name(base.name + "_stations"), [s.to_dict() for s in self.station_list()]
    )
    if pq_s:
      out["stations_parquet"] = pq_s

    return out

  def export_adif(self, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
      "ADIF Export from cw-discover FT8",
      "<programid:11>cw-discover",
      f"<created:15>{datetime.now(tz=timezone.utc).strftime('%d-%b-%Y %H%M')} UTC",
      "<eoh>",
    ]

    def _field(tag: str, value: str | int | float) -> str:
      v = str(value)
      return f"<{tag}:{len(v)}>{v}"

    for st in self.map_station_list():
      ts = datetime.fromtimestamp(st.first_heard, tz=timezone.utc)
      parts = [
        _field("call", st.call),
        _field("gridsquare", st.grid),
        _field("mode", "FT8"),
        _field("band", st.band),
        _field("freq", f"{st.rf_khz:.6f}"),
        _field("rst_rcvd", f"{st.snr:+03d}"),
        _field("qso_date", ts.strftime("%Y%m%d")),
        _field("time_on", ts.strftime("%H%M%S")),
        _field("comment", st.sample_message[:240]),
      ]
      if st.location_text:
        parts.append(_field("notes", st.location_text[:240]))
      if st.lat is not None and st.lon is not None:
        parts.append(_field("lat", f"{st.lat:.5f}"))
        parts.append(_field("lon", f"{st.lon:.5f}"))
      lines.append(" ".join(parts) + " <eor>")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

  def default_export_stem(self) -> str:
    ts = datetime.fromtimestamp(self.started_at).strftime("%Y%m%d_%H%M%S")
    return f"ft8_session_{ts}"

  def hour_rows_for_ui(self) -> list[dict]:
    rows = sorted(self.analytics.hours.values(), key=lambda h: h.hour_utc)
    return [b.to_dict() for b in rows]


HeardSpot = HeardStation
