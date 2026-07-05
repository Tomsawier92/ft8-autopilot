#!/usr/bin/env python3
"""Mély hibainjektálás — JSONL, audio, session, engine, Qt nélkül."""
from __future__ import annotations

import json
import os
import random
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILURES: list[str] = []


def _ok(name: str) -> None:
  print(f"  OK  {name}")


def _fail(name: str, exc: BaseException) -> None:
  FAILURES.append(f"{name}: {exc}")
  print(f"  FAIL {name}: {exc}")


def inject_jsonl_corruption(path: Path) -> None:
  """Félbeszakított sor — következő olvasás ne omoljon össze."""
  path.write_text('{"a":1}\n{"broken"\n{"c":3}\n', encoding="utf-8")
  good = 0
  for line in path.read_text(encoding="utf-8").splitlines():
    try:
      json.loads(line)
      good += 1
    except json.JSONDecodeError:
      pass
  assert good >= 1


def inject_atomic_snapshot_race(tmp: Path) -> None:
  from cw_discover.ft8.atomic_io import atomic_write_json
  from cw_discover.ft8.session_log import SessionLog

  log = SessionLog()
  log.power_safe = True
  with patch("cw_discover.ft8.session_log.LOG_DIR", tmp):
    log.reset("40m", 7.074)
    errors = []

    def hammer():
      try:
        for i in range(30):
          log.add_decode(
            decode_id=i,
            message=f"CQ DL1ABC JN56",
            snr=-10,
            rf_khz=7074.0,
            cycle=f"c{i}",
            audio_hz=1500 + i,
            dt=0.1,
            time_received=time.time(),
          )
      except Exception as e:
        errors.append(e)

    threads = [threading.Thread(target=hammer) for _ in range(4)]
    for t in threads:
      t.start()
    for t in threads:
      t.join()
    if errors:
      raise errors[0]
    log.flush_snapshot()
    snap = log.log_dir_for_day() / "session_snapshot.json"
    data = json.loads(snap.read_text(encoding="utf-8"))
    assert data["decode_count"] > 0


def inject_audio_nan_clip_silence() -> None:
  import numpy as np

  from cw_discover.ft8.audio_fast import HopBuffer, downsample_48k_to_12k

  for label, arr in [
    ("silence", np.zeros(4800, dtype=np.float32)),
    ("clip", np.full(4800, 1.5, dtype=np.float32)),
    ("nan", np.full(4800, np.nan, dtype=np.float32)),
    ("noise", np.random.randn(4800).astype(np.float32)),
  ]:
    y = downsample_48k_to_12k(arr)
    buf = HopBuffer()
    if not np.isnan(arr).all():
      buf.extend(y)
    hop = buf.pop_hop(480)
    _ok(f"audio/{label} hop={hop is not None}")


def inject_engine_malformed_candidates() -> None:
  from cw_discover.ft8.engine import Ft8Engine, DecodeReport

  got: list[DecodeReport] = []

  eng = Ft8Engine(on_decode=lambda r: got.append(r))
  cases = [
    SimpleNamespace(msg="", cyclestart={"string": "t", "time": time.time()}, fHz=0, snr=0, dt=0),
    SimpleNamespace(msg="CQ X", cyclestart={}, fHz=1500, snr=-10, dt=0.1),
    SimpleNamespace(
      msg="CQ DL1ABC JN56",
      cyclestart={"string": "260630_120000", "time": time.time()},
      snr=-10, dt=0.1, fHz=1500,
    ),
  ]
  for c in cases:
    eng._handle_decode(c)
  assert len(got) == 1  # csak érvényes ciklus + üzenet


def inject_geo_edge_messages() -> None:
  from cw_discover.ft8.decode_meta import geo_for_message, classify_message_type
  from cw_discover.ft8.home_qth import DEFAULT_HOME

  msgs = [
    "",
    "CQ",
    "CQ DX",
    "ZZ99 ZZ99",
    "CQ DL1ABC JN99",
    "TM2WWA DH6MBR R-13",
    "DA0WWA IW5BHU 73",
    "\x00\x01",
    "A" * 500,
  ]
  for m in msgs:
    classify_message_type(m)
    geo_for_message(m, DEFAULT_HOME)
    geo_for_message(m, None)


def inject_power_safe_toggle_storm(tmp: Path) -> None:
  from cw_discover.ft8.session_log import SessionLog

  with patch("cw_discover.ft8.session_log.LOG_DIR", tmp):
    log = SessionLog()
    for _ in range(20):
      log.set_power_safe(random.choice([True, False]))
      log.reset("40m", 7.074)
      log.add_decode(
        decode_id=1,
        message="CQ DL1ABC JN56",
        snr=-5,
        rf_khz=7074.0,
        cycle="t",
        audio_hz=1500,
        dt=0.0,
        time_received=time.time(),
      )
    log.flush_snapshot()


def inject_candidate_flood_filter() -> None:
  from cw_discover.ft8.session_log import SessionLog

  log = SessionLog()
  log.reset("40m", 7.074)
  path = log.session_dir / "candidates.jsonl"
  n_before = path.read_text().count("\n") if path.exists() else 0
  for i in range(500):
    c = SimpleNamespace(
      decode_completed=time.time(),
      msg="" if i % 3 else "CQ DL1ABC JN56",
      snr=-10,
      dt=0.0,
      fHz=1500,
      sync_score=float(i % 5),
      ncheck0=99,
      ncheck=i % 15,
      n_its=1,
      llr_sd=0.3 + (i % 10) * 0.1,
      h0_idx=0,
      f0_idx=0,
      decoder="PyFT8",
      decode_path="",
    )
    log.add_candidate(c, "cyc", time.time())
  n_after = path.read_text().count("\n") if path.exists() else 0
  assert n_after - n_before < 260, f"too many candidates logged: {n_after - n_before}"


def main() -> int:
  import tempfile

  print("=== deep fault injection ===")
  with tempfile.TemporaryDirectory() as tmp:
    tmp_p = Path(tmp)
    tests = [
      ("jsonl_corruption", lambda: inject_jsonl_corruption(tmp_p / "bad.jsonl")),
      ("atomic_snapshot_race", lambda: inject_atomic_snapshot_race(tmp_p)),
      ("audio_nan_clip", inject_audio_nan_clip_silence),
      ("engine_malformed", inject_engine_malformed_candidates),
      ("geo_edge_messages", inject_geo_edge_messages),
      ("power_safe_storm", lambda: inject_power_safe_toggle_storm(tmp_p)),
      ("candidate_flood_filter", inject_candidate_flood_filter),
    ]
    for name, fn in tests:
      try:
        fn()
        _ok(name)
      except Exception as e:
        _fail(name, e)

  if FAILURES:
    print(f"\n{len(FAILURES)} FAILURE(S)")
    return 1
  print("\nall fault injections survived")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
