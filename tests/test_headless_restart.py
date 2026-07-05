"""Headless monitor shutdown és supervisor ciklus."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from cw_discover.paths import LOG_DIR

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / ".venv" / "bin" / "python"
MONITOR = ROOT / "scripts" / "monitor_ft8_live.py"
SUP = ROOT / "scripts" / "ft8_headless_supervisor.py"
LOG = LOG_DIR


def _count_decodes() -> int:
  files = sorted(LOG.glob("*/decodes.jsonl"), reverse=True)
  if not files:
    return 0
  return sum(1 for _ in files[0].open())


@pytest.mark.integration
def test_headless_restart_preserves_log() -> None:
  """~25s futás + supervisor 2×15s ciklus — log nem törlődik, writer lezáródik."""
  if not PY.exists():
    pytest.skip("venv missing")

  before = _count_decodes()

  r1 = subprocess.run(
    [str(PY), str(MONITOR), "-t", "20", "--power-safe"],
    cwd=str(ROOT),
    capture_output=True,
    text=True,
    timeout=90,
  )
  assert r1.returncode == 0, r1.stderr
  assert "kilépés" in r1.stdout

  mid = _count_decodes()
  assert mid >= before

  r2 = subprocess.run(
    [
      str(PY),
      str(SUP),
      "--slice-seconds",
      "12",
      "--pause-seconds",
      "2",
      "--max-cycles",
      "2",
      "--power-safe",
    ],
    cwd=str(ROOT),
    capture_output=True,
    text=True,
    timeout=120,
  )
  assert r2.returncode == 0, r2.stderr
  assert "ciklus 1" in r2.stdout
  assert "ciklus 2" in r2.stdout

  after = _count_decodes()
  assert after >= mid


def test_session_log_shutdown_closes_writer() -> None:
  from cw_discover.ft8.session_log import SessionLog

  log = SessionLog()
  log.power_safe = True
  log.reset("40m", 7.074)
  log.add_decode(
    decode_id=1,
    message="CQ TEST JN96",
    snr=-5,
    rf_khz=7074.0,
    cycle="test_cycle",
    audio_hz=1500,
    dt=0.0,
    time_received=1.0,
  )
  log.shutdown()
  assert log._writer is None
