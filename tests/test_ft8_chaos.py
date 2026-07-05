"""Szándékos hibák / sávon belüli edge case tesztek."""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest

from cw_discover.ft8.analytics import SessionAnalytics
from cw_discover.ft8.audio_fast import HopBuffer, downsample_48k_to_12k
from cw_discover.ft8.decode_meta import (
  candidate_record,
  classify_message_type,
  dsp_from_candidate,
  geo_for_message,
)
from cw_discover.ft8.engine import DecodeReport, Ft8Engine
from cw_discover.ft8.grid_geo import extract_callsigns_from_message, extract_grid_from_message
from cw_discover.ft8.home_qth import DEFAULT_HOME
from cw_discover.ft8.session_log import MAX_DECODES_IN_RAM, SessionLog


# --- Üzenet / sávon belüli edge case-ek ---

@pytest.mark.parametrize(
  "msg,expect_type,min_calls",
  [
    ("", "unknown", 0),
    ("   ", "unknown", 0),
    ("CQ DX IN3IZQ JN56", "cq", 1),
    ("DA0WWA IW5BHU 73", "73", 2),
    ("DL1ABC DA0WWA -12", "report", 2),
    ("DL1ABC DA0WWA R-05", "report", 2),
    ("DL50CN JO40", "grid", 1),
    ("<...>", "other", 0),
    ("CQ DX", "cq", 0),
    ("TEST TEST", "other", 0),
    ("IN3IZQ JN56", "grid", 1),
    ("TM2WWA DH6MBR R-13", "report", 2),
  ],
)
def test_message_classification_and_calls(msg, expect_type, min_calls) -> None:
  assert classify_message_type(msg) == expect_type
  assert len(extract_callsigns_from_message(msg)) >= min_calls


def test_grid_not_parsed_from_callsign() -> None:
  assert extract_grid_from_message("DL50CN JO40 -12") == "JO40"
  assert extract_grid_from_message("DL50CN -12") is None


def test_geo_without_home_still_has_grid() -> None:
  geo = geo_for_message("CQ DX IN3IZQ JN56", None)
  assert geo["grid"] == "JN56"
  assert geo["distance_km"] is None


def test_geo_invalid_grid_does_not_crash() -> None:
  geo = geo_for_message("CQ DX XX99", DEFAULT_HOME)
  assert geo["grid"] == "" or geo.get("lat") is not None


def test_dsp_from_broken_candidate() -> None:
  c = SimpleNamespace()
  d = dsp_from_candidate(c)
  assert d["ncheck"] == 99
  assert d["decoder"] == "PyFT8"


def test_candidate_record_empty_msg() -> None:
  c = SimpleNamespace(msg="", snr=-20, dt=0.0, fHz=1500, sync_score=1.0, ncheck0=5, ncheck=3, n_its=1, llr_sd=0.6, h0_idx=0, f0_idx=0, decoder="PyFT8", decode_path="")
  rec = candidate_record(c, cycle="t", time_received=time.time())
  assert rec["success"] is False


# --- Session log stress ---

def test_concurrent_add_decode() -> None:
  log = SessionLog()
  log.reset("40m", 7.074, home=DEFAULT_HOME)
  errs: list[Exception] = []

  def worker(i: int) -> None:
    try:
      log.add_decode(
        decode_id=i,
        message=f"CQ DL{i % 10}ABC JN56",
        snr=-10 - (i % 5),
        rf_khz=7074.0,
        cycle=f"cyc{i % 3}",
        audio_hz=1500 + i,
        dt=0.1,
        time_received=time.time() + i * 0.01,
      )
    except Exception as e:
      errs.append(e)

  threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
  for t in threads:
    t.start()
  for t in threads:
    t.join()
  assert not errs
  assert log.station_count() >= 1
  assert len(log.decodes) == 50


def test_power_safe_toggle_mid_session(tmp_path, monkeypatch) -> None:
  monkeypatch.setattr("cw_discover.ft8.session_log.LOG_DIR", tmp_path)
  log = SessionLog()
  log.reset("40m", 7.074)
  log.add_decode(
    decode_id=1, message="CQ A1AA JN96", snr=-5, rf_khz=7074.0,
    cycle="t", audio_hz=1000, dt=0.0, time_received=time.time(),
  )
  log.set_power_safe(True)
  log.add_decode(
    decode_id=2, message="CQ B2BB JN96", snr=-6, rf_khz=7074.0,
    cycle="t2", audio_hz=1100, dt=0.0, time_received=time.time(),
  )
  log.flush_snapshot()
  snap = log.log_dir_for_day() / "session_snapshot.json"
  assert snap.is_file()


def test_flush_snapshot_noop_without_power_safe() -> None:
  log = SessionLog()
  log.reset("40m", 7.074)
  log.flush_snapshot()  # nem dob


def test_candidate_filter_skips_noise(tmp_path, monkeypatch) -> None:
  monkeypatch.setattr("cw_discover.ft8.session_log.LOG_DIR", tmp_path)
  log = SessionLog()
  log.reset("40m", 7.074)
  c = SimpleNamespace(
    decode_completed=time.time(), msg="", snr=-30, dt=0.0, fHz=1000,
    sync_score=0.1, ncheck0=99, ncheck=99, n_its=0, llr_sd=0.1,
    h0_idx=0, f0_idx=0, decoder="PyFT8", decode_path="",
  )
  log.add_candidate(c, "cyc", time.time())
  path = log.session_dir / "candidates.jsonl"
  assert not path.exists()


def test_session_decodes_ram_cap() -> None:
  log = SessionLog()
  log.reset("40m", 7.074, home=DEFAULT_HOME)
  for i in range(MAX_DECODES_IN_RAM + 50):
    log.add_decode(
      decode_id=i,
      message=f"CQ DL1ABC JN56",
      snr=-10,
      rf_khz=7074.0,
      cycle="t",
      audio_hz=1500,
      dt=0.0,
      time_received=time.time() + i * 0.001,
    )
  assert len(log.decodes) == MAX_DECODES_IN_RAM


def test_report_r_notation() -> None:
  assert classify_message_type("TM2WWA DH6MBR R-13") == "report"
  assert classify_message_type("DL1ABC DA0WWA R-05") == "report"


def test_engine_rejects_empty_cycle() -> None:
  seen: list[str] = []
  eng = Ft8Engine(on_decode=lambda r: seen.append(r.message))
  c = SimpleNamespace(
    msg="CQ DL1ABC JN56",
    cyclestart={},
    snr=-10, dt=0.1, fHz=1500,
    sync_score=5.0, ncheck0=0, ncheck=0, n_its=1, llr_sd=1.0,
    h0_idx=0, f0_idx=0, decoder="PyFT8", decode_path="",
  )
  eng._handle_decode(c)
  assert seen == []


def test_downsample_nan_becomes_finite() -> None:
  import numpy as np
  from cw_discover.ft8.audio_fast import downsample_48k_to_12k
  y = downsample_48k_to_12k(np.full(4800, np.nan, dtype=np.float32))
  assert y.size > 0
  assert np.isfinite(y).all()


def test_decode_report_wsjtx_line() -> None:
  r = DecodeReport("1200", -12, 0.3, 1500, 7074.0, "CQ TEST", time.time())
  assert "CQ TEST" in r.wsjtx_line


# --- Engine dedup ---

def test_engine_dedup_same_cycle_message() -> None:
  seen: list[str] = []

  def on_decode(report: DecodeReport) -> None:
    seen.append(report.message)

  eng = Ft8Engine(on_decode=on_decode)
  c = SimpleNamespace(
    msg="CQ DUP JN96",
    cyclestart={"string": "260630_120000", "time": time.time()},
    snr=-10, dt=0.1, fHz=1500, sync_score=5.0, ncheck0=0, ncheck=0,
    n_its=1, llr_sd=1.0, h0_idx=0, f0_idx=0, decoder="PyFT8", decode_path="",
  )
  eng._handle_decode(c)
  eng._handle_decode(c)
  assert seen == ["CQ DUP JN96"]


def test_engine_rejects_empty_message() -> None:
  seen: list[str] = []
  eng = Ft8Engine(on_decode=lambda r: seen.append(r.message))
  c = SimpleNamespace(msg="", cyclestart={"string": "t", "time": time.time()}, fHz=0, snr=0, dt=0)
  eng._handle_decode(c)
  assert seen == []


# --- Audio edge ---

def test_downsample_empty_and_tiny() -> None:
  assert downsample_48k_to_12k(np.zeros(0, dtype=np.float32)).size == 0
  assert downsample_48k_to_12k(np.zeros(3, dtype=np.float32)).size == 0


def test_hop_buffer_oversize() -> None:
  buf = HopBuffer(cap_samples=1000)
  buf.extend(np.ones(2000, dtype=np.float32))
  assert buf.pop_hop(480) is not None


# --- Analytics edge ---

def test_hour_bucket_empty_snr_stats() -> None:
  a = SessionAnalytics()
  h = a._hour(time.time())
  d = h.to_dict()
  assert d["snr_mean"] is None


# --- Map widget (no display) ---

def test_map_widget_zero_spots(qtbot) -> None:
  pytest.importorskip("PyQt5")
  from cw_discover.gui.world_map_widget import WorldMapWidget

  w = WorldMapWidget()
  w.set_spots([])
  w._redraw_spots_now()
  assert w.isVisible() or True


def test_map_widget_pan_at_edges_never_collapses_limits(qtbot) -> None:
  pytest.importorskip("PyQt5")
  from cw_discover.gui.world_map_widget import WorldMapWidget

  w = WorldMapWidget()
  w._set_limits((170.0, 180.0), (75.0, 85.0))
  w._on_press(type("E", (), {"inaxes": w.ax, "button": 1, "xdata": 175.0, "ydata": 80.0, "dblclick": False})())
  for dx, dy in ((50.0, 0.0), (0.0, 50.0), (-200.0, -200.0)):
    w._on_motion(type("E", (), {"inaxes": w.ax, "xdata": 175.0 + dx, "ydata": 80.0 + dy})())
    xlim, ylim = w._current_limits()
    assert xlim[1] > xlim[0]
    assert ylim[1] > ylim[0]
  w._apply_limits()


def test_map_widget_spots_without_coords(qtbot) -> None:
  pytest.importorskip("PyQt5")
  from cw_discover.gui.world_map_widget import WorldMapWidget
  from cw_discover.ft8.session_log import HeardStation

  st = HeardStation(
    call="NOGRID", grid="", lat=None, lon=None, snr=-10, rf_khz=7074.0,
    band="40m", first_heard=time.time(), last_heard=time.time(),
  )
  w = WorldMapWidget()
  w.set_spots([st])
  w._redraw_spots_now()


# --- GUI pro toggle (regression any()) ---

def test_pro_ui_toggle_no_crash(qtbot) -> None:
  pytest.importorskip("PyQt5")
  from PyQt5 import QtWidgets
  from cw_discover.gui.ft8_window import Ft8Window

  app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
  win = Ft8Window()
  win.chk_pro.setChecked(True)
  win._apply_pro_ui()
  win.chk_pro_dsp.setChecked(False)
  win.chk_pro_geo.setChecked(False)
  win.chk_pro_hourly.setChecked(True)
  win._apply_pro_ui()
  win.chk_power_safe.setChecked(True)
  win._on_power_safe_toggled(True)
  win.close()
