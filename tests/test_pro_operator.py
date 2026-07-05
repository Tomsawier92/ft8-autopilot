"""PRO operátor pontozás tesztek."""
from __future__ import annotations

from datetime import datetime, timezone

from cw_discover.ft8.engine import DecodeReport
from cw_discover.ft8.ft8_protocol import message_triplet
from cw_discover.ft8.pro_operator import PriorityMode, ProOperatorConfig, score_cq_candidate


def _cq(msg: str, snr: int = -12, hz: int = 1500) -> tuple:
  report = DecodeReport(
    cycle="c",
    snr=snr,
    dt=0.1,
    audio_hz=hz,
    rf_khz=7074.0,
    message=msg,
    time_received=datetime.now(tz=timezone.utc).timestamp(),
  )
  triplet = message_triplet(msg)
  assert triplet is not None
  return report, triplet


def test_weak_dx_prefers_distance_and_weak_snr() -> None:
  cfg = ProOperatorConfig(enabled=True, priority=PriorityMode.WEAK_DX, min_snr=-25, max_snr=5)
  near = score_cq_candidate(
    report=_cq("CQ HA1ABC JN96")[0],
    triplet=_cq("CQ HA1ABC JN96")[1],
    grid="JN96",
    distance_km=50.0,
    worked=False,
    config=cfg,
  )
  far_weak = score_cq_candidate(
    report=_cq("CQ VK9XYZ RF76", snr=-18)[0],
    triplet=_cq("CQ VK9XYZ RF76", snr=-18)[1],
    grid="RF76",
    distance_km=15000.0,
    worked=False,
    config=cfg,
  )
  assert near is not None and far_weak is not None
  assert far_weak.score > near.score


def test_max_snr_filters_local_strong() -> None:
  cfg = ProOperatorConfig(enabled=True, max_snr=3)
  strong = score_cq_candidate(
    report=_cq("CQ HA1LOCAL JN96", snr=8)[0],
    triplet=_cq("CQ HA1LOCAL JN96", snr=8)[1],
    grid="JN96",
    distance_km=20.0,
    worked=False,
    config=cfg,
  )
  assert strong is None
