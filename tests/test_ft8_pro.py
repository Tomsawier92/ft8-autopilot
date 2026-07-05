"""FT8 pro naplózás és elemzés tesztek."""
from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

import pytest

from cw_discover.ft8.analytics import SessionAnalytics
from cw_discover.ft8.decode_meta import (
  bearing_deg,
  classify_message_type,
  compass_bin,
  geo_for_message,
  hour_key_utc,
)
from cw_discover.ft8.home_qth import DEFAULT_HOME
from cw_discover.ft8.session_log import SessionLog


def test_classify_message_type() -> None:
  assert classify_message_type("CQ DX IN3IZQ JN56") == "cq"
  assert classify_message_type("DA0WWA IW5BHU 73") == "73"
  assert classify_message_type("DL1ABC DA0WWA -12") == "report"


def test_bearing_and_compass() -> None:
  az = bearing_deg(46.9, 18.0, 50.0, 8.0)
  assert 240 < az < 310
  assert compass_bin(az) in ("W", "NW", "SW")


def test_geo_for_cq() -> None:
  geo = geo_for_message("CQ DX IN3IZQ JN56", DEFAULT_HOME)
  assert geo["grid"] == "JN56"
  assert geo["grid_source"] == "message"
  assert geo["distance_km"] is not None
  assert geo["azimuth_deg"] is not None


def test_session_decode_and_hourly() -> None:
  log = SessionLog()
  log.reset("40m", 7.074, pulse_device="test", home=DEFAULT_HOME)
  t = time.time()
  log.add_decode(
    decode_id=1,
    message="CQ DX IN3IZQ JN56",
    snr=-10,
    rf_khz=7074.0,
    cycle="260630_120000",
    audio_hz=1500,
    dt=0.2,
    time_received=t,
    dsp={"sync_score": 12.5, "ncheck": 0, "n_its": 2, "llr_sd": 1.1},
    audio={"raw_rms": 0.1, "clip_frac": 0.0},
  )
  log.add_decode(
    decode_id=2,
    message="DA0WWA IW5BHU 73",
    snr=-8,
    rf_khz=7074.0,
    cycle="260630_120015",
    audio_hz=1600,
    dt=0.1,
    time_received=t + 5,
    dsp={"sync_score": 8.0, "ncheck": 0, "n_its": 1, "llr_sd": 0.9},
  )
  assert log.station_count() == 3
  assert len(log.decodes) == 2
  assert log.decodes[0]["msg_type"] == "cq"
  assert log.decodes[0]["dsp"]["sync_score"] == 12.5
  hour = hour_key_utc(t)
  assert hour in log.analytics.hours
  assert log.analytics.hours[hour].decode_count == 2

  with tempfile.TemporaryDirectory() as tmp:
    base = Path(tmp) / "sess.json"
    paths = log.export_bundle(base)
    assert paths["session_json"].exists()
    assert paths["hours_json"].exists()
    assert paths["cycles_json"].exists()
    payload = json.loads(paths["session_json"].read_text(encoding="utf-8"))
    assert payload["version"] == 4
    assert payload["decode_count"] == 2
    assert len(payload["hours"]) >= 1
    log.flush_logs()
    if log.session_dir:
      assert (log.session_dir / "decodes.jsonl").exists()


def test_map_station_list_cq_only() -> None:
  log = SessionLog()
  log.reset("40m", 7.074, home=DEFAULT_HOME)
  t = time.time()
  log.add_decode(
    decode_id=1,
    message="CQ DX IN3IZQ JN56",
    snr=-10,
    rf_khz=7074.0,
    cycle="260630_120000",
    audio_hz=1500,
    dt=0.2,
    time_received=t,
  )
  log.add_decode(
    decode_id=2,
    message="DA0WWA IW5BHU 73",
    snr=-8,
    rf_khz=7074.0,
    cycle="260630_120015",
    audio_hz=1600,
    dt=0.1,
    time_received=t + 5,
  )
  all_map = log.map_station_list()
  cq_map = log.map_station_list(cq_only=True)
  assert len(all_map) >= 1
  assert all(s.msg_types.get("cq", 0) > 0 for s in cq_map)
  assert len(cq_map) <= len(all_map)


def test_session_analytics_compass_bins() -> None:
  a = SessionAnalytics()
  ts = time.time()
  a.note_decode(
    ts=ts,
    cycle_key="c1",
    cycle="1200",
    cycle_start_utc="2026-06-30T12:00:00+00:00",
    calls=["DL1ABC"],
    snr=-5,
    msg_type="cq",
    azimuth_deg=270.0,
    distance_km=400.0,
    has_geo=True,
    new_station_calls=["DL1ABC"],
  )
  h = a.hours[hour_key_utc(ts)]
  assert h.compass_bins.get("W") == 1
  assert h.new_stations == 1


def test_daily_log_buffered_until_flush(tmp_path, monkeypatch) -> None:
  monkeypatch.setattr("cw_discover.ft8.session_log.LOG_DIR", tmp_path)
  log = SessionLog()
  log.reset("40m", 7.074, home=DEFAULT_HOME)
  t = time.time()
  log.add_decode(
    decode_id=1,
    message="CQ DX IN3IZQ JN56",
    snr=-10,
    rf_khz=7074.0,
    cycle="260630_120000",
    audio_hz=1500,
    dt=0.2,
    time_received=t,
  )
  day_dir = log.log_dir_for_day(t)
  assert log._writer is not None and log._writer.pending_count() == 1
  assert not (day_dir / "decodes.jsonl").exists()
  log.flush_logs()
  assert (day_dir / "decodes.jsonl").exists()
  lines = (day_dir / "decodes.jsonl").read_text().strip().splitlines()
  assert len(lines) == 1
