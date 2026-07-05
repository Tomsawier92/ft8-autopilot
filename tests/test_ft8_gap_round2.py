"""PRO defer választás + napló regresszió — gap pótlás."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from cw_discover.ft8.log_replay import load_decodes, remap_cycles_fresh
from cw_discover.ft8.pro_operator import PriorityMode, ProOperatorConfig
from cw_discover.ft8.qso_controller import QsoPhase
from cw_discover.paths import LOG_DIR
from cw_discover.ft8.sim_harness import Ft8SimHarness

LOG = LOG_DIR / "2026-07-04/decodes.jsonl"


def test_pro_defer_weak_dx_picks_far(tmp_path) -> None:
  """8 CQ defer — WEAK_DX: távolabbi gyengébb nyer."""
  pro = ProOperatorConfig(
    enabled=True,
    defer_cq_pick=True,
    priority=PriorityMode.WEAK_DX,
    max_snr=10,
  )
  h = Ft8SimHarness(tmp_dir=tmp_path, pro=pro)
  from cw_discover.ft8.log_replay import fresh_base_cycle, cycles_from_base

  cyc = cycles_from_base(fresh_base_cycle(), 1)[0]
  h.feed("CQ HA1NEAR JN96", cycle=cyc, snr=-5, hz=500, wait=False)
  h.feed("CQ VK9FAR RF76", cycle=cyc, snr=-18, hz=800, wait=False)
  h.op.on_cycle("flush", 0.0)
  h.wait_tx(1)
  assert h.op._active is not None
  assert h.op._active.remote_call == "VK9FAR"


def test_pro_strong_fast_picks_loud(tmp_path) -> None:
  pro = ProOperatorConfig(
    enabled=True,
    defer_cq_pick=True,
    priority=PriorityMode.STRONG_FAST,
    max_snr=15,
  )
  h = Ft8SimHarness(tmp_dir=tmp_path, pro=pro)
  from cw_discover.ft8.log_replay import fresh_base_cycle, cycles_from_base

  cyc = cycles_from_base(fresh_base_cycle(), 1)[0]
  h.feed("CQ IK4LZH JN54", cycle=cyc, snr=-18, hz=500, wait=False)
  h.feed("CQ SP9JMZ JO90", cycle=cyc, snr=-3, hz=800, wait=False)
  h.op.on_cycle("flush", 0.0)
  h.wait_tx(1)
  assert h.op._active.remote_call == "SP9JMZ"


@pytest.mark.skipif(not LOG.exists(), reason="nincs napló")
def test_log_mined_cq_gets_grid_answer(tmp_path) -> None:
  """Naplóból vett valós CQ → grid válasz."""
  decs = [d for d in load_decodes(LOG, limit=30000) if d.message.startswith("CQ IK4LZH")]
  assert decs
  h = Ft8SimHarness(tmp_dir=tmp_path)
  h.feed_decode(remap_cycles_fresh([decs[0]])[0])
  assert h.last_tx == "IK4LZH N0CALL JN96"


def test_idle_cq_after_complete_qso(tmp_path) -> None:
  """Teljes QSO után új CQ másik állomástól — OK."""
  h = Ft8SimHarness(tmp_dir=tmp_path)
  from cw_discover.ft8.log_replay import fresh_base_cycle, cycles_from_base

  c = cycles_from_base(fresh_base_cycle(), 6)
  for msg, ci in zip(
    [
      "CQ IK4LZH JN54",
      "IK4LZH N0CALL -09",
      "IK4LZH N0CALL R-05",
      "IK4LZH N0CALL RR73",
    ],
    c[:4],
  ):
    h.feed(msg, cycle=ci)
  assert h.phase == QsoPhase.IDLE
  h.feed("CQ DK7ZT JO30", cycle=c[5], snr=-7, hz=1867)
  assert h.op._active.remote_call == "DK7ZT"
