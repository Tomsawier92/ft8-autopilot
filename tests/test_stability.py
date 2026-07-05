"""Atomi I/O és audio gyorsítás tesztek."""
from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

import numpy as np
import pytest

from cw_discover.ft8.atomic_io import AtomicJsonlSink, atomic_write_json
from cw_discover.ft8.audio_fast import HopBuffer, downsample_48k_to_12k


def test_atomic_write_json_survives_replace() -> None:
  with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp) / "snap.json"
    atomic_write_json(path, {"a": 1, "b": [2, 3]}, fsync=True)
    assert json.loads(path.read_text(encoding="utf-8"))["a"] == 1
    atomic_write_json(path, {"a": 99}, fsync=True)
    assert json.loads(path.read_text(encoding="utf-8"))["a"] == 99


def test_atomic_jsonl_power_safe_fsync() -> None:
  with tempfile.TemporaryDirectory() as tmp:
    p = Path(tmp) / "d.jsonl"
    sink = AtomicJsonlSink(p, power_safe=True)
    sink.append({"x": 1})
    sink.append({"x": 2})
    lines = p.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2


def test_downsample_length() -> None:
  x = np.random.randn(4800).astype(np.float32)
  y = downsample_48k_to_12k(x)
  assert y.size == 1200


def test_hop_buffer_pop() -> None:
  buf = HopBuffer()
  buf.extend(np.ones(960, dtype=np.float32))
  hop = buf.pop_hop(480)
  assert hop is not None and hop.size == 480
  assert buf.pop_hop(480) is not None
  assert buf.pop_hop(480) is None


def test_power_safe_snapshot(tmp_path, monkeypatch) -> None:
  from cw_discover.ft8.session_log import SessionLog

  monkeypatch.setattr("cw_discover.ft8.session_log.LOG_DIR", tmp_path)
  log = SessionLog()
  log.power_safe = True
  log.reset("40m", 7.074, home=None)
  log.add_decode(
    decode_id=1,
    message="CQ TEST JN96",
    snr=-5,
    rf_khz=7074.0,
    cycle="t",
    audio_hz=1000,
    dt=0.0,
    time_received=time.time(),
  )
  log.flush_snapshot()
  snap = log.log_dir_for_day() / "session_snapshot.json"
  assert snap.is_file()
  data = json.loads(snap.read_text(encoding="utf-8"))
  assert data["decode_count"] == 1


def test_engine_cycle_callback_signature() -> None:
  from cw_discover.ft8.engine import Ft8Engine

  seen = []

  def on_cycle(cycle, cst, n, busy, ts, snap):
    seen.append((cycle, n))

  eng = Ft8Engine(on_cycle_search=on_cycle)
  eng._handle_cycle_search("260630_120000", 1.0, 42, 3.14)
  assert seen and seen[0][1] == 42

