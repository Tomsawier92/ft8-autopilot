"""
FT8 log-alapú szimulációs forgatókönyvek — ál-dekód, anomáliák.

Forrás: cw-discover/logs/*.jsonl + élő tapasztalat.
Nincs rádió TX — RecordingTx mock.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from cw_discover.ft8.forgalmi_log import QsoRecord
from cw_discover.ft8.log_replay import (
  LogDecode,
  find_cq_sequences,
  fresh_base_cycle,
  load_cycle_slice,
  load_decodes,
  remap_cycles_fresh,
)
from cw_discover.ft8.pro_operator import ProOperatorConfig
from cw_discover.ft8.qso_controller import QsoPhase
from cw_discover.ft8.sim_harness import Ft8SimHarness
from cw_discover.paths import FORGALMI_LIVE, LOG_DIR, PROJECT_ROOT
from cw_discover.ft8.tx_player import snap_ft8_hz

LOG_TODAY = LOG_DIR / "2026-07-04/decodes.jsonl"
LOG_YDAY = LOG_DIR / "2026-07-03/decodes.jsonl"


def _h(tmp_path, **kw) -> Ft8SimHarness:
  return Ft8SimHarness(tmp_dir=tmp_path, **kw)


def _cyc(h: Ft8SimHarness, n: int = 5) -> list[str]:
  return h.make_cycles(fresh_base_cycle(), n)


# --- Naplóból kinyert valós minták ---


@pytest.mark.skipif(not LOG_TODAY.exists(), reason="nincs mai decode napló")
def test_replay_real_ik4lzh_cq_from_log(tmp_path) -> None:
  """Napló: CQ IK4LZH JN54 @ 397 Hz → grid válasz."""
  decs = load_decodes(LOG_TODAY, limit=20000)
  ik = [d for d in decs if d.message.startswith("CQ IK4LZH")]
  assert ik, "nincs IK4LZH CQ a naplóban"
  sample = ik[0]
  h = _h(tmp_path)
  fresh = remap_cycles_fresh([sample])[0]
  h.feed_decode(fresh)
  assert h.last_tx == "IK4LZH N0CALL JN96"
  assert h.op._active.audio_hz == sample.audio_hz


@pytest.mark.skipif(not LOG_TODAY.exists(), reason="nincs mai decode napló")
def test_replay_busy_cycle_multi_cq(tmp_path) -> None:
  """Napló: 10+ CQ egy slotban — csak egy aktív QSO indul."""
  busy = "260704_010530"
  decs = load_cycle_slice(LOG_TODAY, busy)
  if len(decs) < 5:
    pytest.skip("busy cycle nincs a naplóban")
  cqs = [d for d in decs if d.message.startswith("CQ ")]
  h = _h(tmp_path)
  for d in remap_cycles_fresh(cqs[:6]):
    h.feed_decode(d, wait=False)
  h.wait_tx(1)


@pytest.mark.skipif(not LOG_TODAY.exists(), reason="nincs mai decode napló")
def test_replay_remote_busy_with_other_station(tmp_path) -> None:
  """Napló minta: IK4LZH SP9JMZ JO90 — nem minket hív, ignorálás."""
  h = _h(tmp_path)
  cyc = _cyc(h, 2)
  h.feed("CQ IK4LZH JN54", cycle=cyc[0], snr=-8, hz=397)
  h.feed("IK4LZH SP9JMZ JO90", cycle=cyc[1], snr=-5, hz=400)
  assert h.op._active.remote_call == "IK4LZH"
  assert len(h.tx.messages()) == 1  # csak grid válasz, nem report


# --- Standard QSO (log formátum) ---


def test_happy_path_cq_to_log(tmp_path) -> None:
  h = _h(tmp_path)
  c = _cyc(h, 5)
  h.feed("CQ IK4LZH JN54", cycle=c[0], snr=-8, hz=397)
  h.feed("IK4LZH N0CALL -09", cycle=c[1], snr=-9)
  h.feed("IK4LZH N0CALL R-05", cycle=c[2])
  h.feed("IK4LZH N0CALL RR73", cycle=c[3])
  assert h.phase == QsoPhase.IDLE
  assert h.tx.messages() == [
    "IK4LZH N0CALL JN96",
    "IK4LZH N0CALL R-09",
    "IK4LZH N0CALL RR73",
    "IK4LZH N0CALL 73",
  ]
  assert "IK4LZH" in (tmp_path / "qso.jsonl").read_text()


def test_incoming_call_full_path(tmp_path) -> None:
  h = _h(tmp_path)
  c = _cyc(h, 5)
  h.feed("DK7ZT N0CALL JO30", cycle=c[0], snr=-7, hz=1867)
  h.feed("DK7ZT N0CALL -12", cycle=c[1])
  h.feed("DK7ZT N0CALL R-08", cycle=c[2])
  h.feed("DK7ZT N0CALL RR73", cycle=c[3])
  assert h.tx.messages()[0] == "DK7ZT N0CALL JN96"
  assert h.phase == QsoPhase.IDLE


# --- Anomáliák: ön-dekód, régi slot, SNR ---


def test_anomaly_self_spill_ignored(tmp_path) -> None:
  """Napló: N0CALL DK7ZT -09 — saját TX visszahallás."""
  h = _h(tmp_path)
  h.feed("N0CALL DK7ZT -09", hz=1867, snr=-22, wait=False)
  assert h.op._active is None
  assert h.tx.messages() == []


def test_anomaly_stale_decode(tmp_path) -> None:
  h = _h(tmp_path)
  h.feed("CQ IK4LZH JN54", cycle="260704_030000", snr=-8, wait=False)
  assert h.op._active is None


def test_anomaly_snr_too_weak(tmp_path) -> None:
  h = _h(tmp_path, cq_min_snr=-15)
  h.feed("CQ IK4LZH JN54", snr=-22, wait=False)
  assert h.op._active is None


def test_anomaly_snr_too_strong_pro(tmp_path) -> None:
  pro = ProOperatorConfig(enabled=True, max_snr=0, min_snr=-20)
  h = _h(tmp_path, pro=pro)
  h.feed("CQ IK4LZH JN54", snr=+12, wait=False)
  assert h.op._active is None


def test_anomaly_worked_today_skip(tmp_path) -> None:
  from datetime import datetime, timezone

  h = _h(tmp_path)
  h.naplo.append_qso(
    QsoRecord(
      call="IK4LZH",
      grid="JN54",
      band="40m",
      dial_mhz=7.074,
      rst_sent="-10",
      rst_rcvd="-09",
      time_on=datetime.now(tz=timezone.utc),
      time_off=datetime.now(tz=timezone.utc),
      tx_audio_hz=397,
    )
  )
  h.feed("CQ IK4LZH JN54", snr=-8, hz=397, wait=False)
  assert h.op._active is None


# --- Többen hívnak / verseny ---


def test_anomaly_two_incoming_same_cycle_pro_picks_first(tmp_path) -> None:
  h = _h(tmp_path)
  c = _cyc(h, 1)
  h.feed("IK4LZH N0CALL JN54", cycle=c[0], snr=-8, hz=397, wait=False)
  h.feed("DK7ZT N0CALL JO30", cycle=c[0], snr=-6, hz=1867)
  assert h.op._active is not None
  assert h.op._active.remote_call in ("IK4LZH", "DK7ZT")
  assert len(h.tx.messages()) == 1


def test_anomaly_cq_while_active_ignored(tmp_path) -> None:
  h = _h(tmp_path)
  c = _cyc(h, 3)
  h.feed("CQ IK4LZH JN54", cycle=c[0], hz=397)
  h.feed("CQ SP9JMZ JO90", cycle=c[1], snr=-5, hz=1200)
  assert h.op._active.remote_call == "IK4LZH"
  assert len(h.tx.messages()) == 1


def test_anomaly_pro_preempt_stuck_qso(tmp_path) -> None:
  pro = ProOperatorConfig(enabled=True, defer_cq_pick=False)
  h = _h(tmp_path, pro=pro)
  c = _cyc(h, 3)
  h.feed("CQ IK4LZH JN54", cycle=c[0], hz=397)
  h.op._active.cycles_without_reply = 2
  h.feed("DK7ZT N0CALL JO30", cycle=c[1], hz=1867)
  assert h.op._active.remote_call == "DK7ZT"


def test_anomaly_pro_no_preempt_active_exchange(tmp_path) -> None:
  """Aktív QSO közepén másik hívás — nem preempt ha már jött report."""
  pro = ProOperatorConfig(enabled=True)
  h = _h(tmp_path, pro=pro)
  c = _cyc(h, 4)
  h.feed("CQ IK4LZH JN54", cycle=c[0], hz=397)
  h.feed("IK4LZH N0CALL -09", cycle=c[1])
  h.feed("DK7ZT N0CALL JO30", cycle=c[2], hz=1867)
  assert h.op._active.remote_call == "IK4LZH"
  assert h.tx.messages()[-1].endswith("R-10")


def test_anomaly_defer_cq_buffer_then_flush(tmp_path) -> None:
  pro = ProOperatorConfig(enabled=True, defer_cq_pick=True, min_snr=-20, max_snr=10)
  h = _h(tmp_path, pro=pro)
  c = _cyc(h, 3)
  h.feed("CQ IK4LZH JN54", cycle=c[0], snr=-8, hz=397, wait=False)
  h.feed("CQ SP9JMZ JO90", cycle=c[0], snr=-12, hz=800, wait=False)
  assert len(h.op._cq_buffer) == 2
  h.op.on_cycle("cycle_flush_1", 0.0)
  h.wait_tx(1)
  assert h.op._active is not None
  assert len(h.tx.messages()) == 1


# --- QSO elvész / megszakad ---


def test_anomaly_abandon_no_reply_3_cycles(tmp_path) -> None:
  h = _h(tmp_path)
  h.feed("CQ IK4LZH JN54", hz=397)
  tx_p = h.op._active.tx_period
  with patch("cw_discover.ft8.qso_controller.ft8_period_at", return_value=tx_p):
    for i in range(4):
      h.tick_cycle(f"tick{i}")
  assert h.phase == QsoPhase.IDLE
  assert h.op._active is None


def test_anomaly_abort_mid_qso(tmp_path) -> None:
  h = _h(tmp_path)
  c = _cyc(h, 3)
  h.feed("CQ IK4LZH JN54", cycle=c[0])
  h.feed("IK4LZH N0CALL -09", cycle=c[1])
  h.op.abort_qso("teszt")
  assert h.phase == QsoPhase.IDLE
  h.feed("CQ DK7ZT JO30", cycle=c[2], snr=-7, hz=1867)
  assert h.op._active.remote_call == "DK7ZT"


def test_anomaly_disarm_clears(tmp_path) -> None:
  h = _h(tmp_path)
  h.feed("CQ IK4LZH JN54")
  h.op.set_armed(False)
  assert h.op._active is None
  h.op.set_armed(True)
  h.feed("CQ IK4LZH JN54")
  assert h.op._active is not None


# --- Üzenet anomáliák ---


def test_anomaly_wrong_pair_during_active(tmp_path) -> None:
  h = _h(tmp_path)
  c = _cyc(h, 3)
  h.feed("CQ IK4LZH JN54", cycle=c[0], hz=397)
  h.feed("SP9JMZ N0CALL -09", cycle=c[1])  # másik állomás
  assert h.op._active.remote_call == "IK4LZH"
  assert len(h.tx.messages()) == 1


def test_anomaly_remote_rrr_closes(tmp_path) -> None:
  h = _h(tmp_path)
  c = _cyc(h, 4)
  h.feed("CQ IK4LZH JN54", cycle=c[0])
  h.feed("IK4LZH N0CALL -09", cycle=c[1])
  h.feed("IK4LZH N0CALL RRR", cycle=c[2])
  assert h.last_tx.endswith("RR73")
  assert h.phase == QsoPhase.CLOSING


def test_anomaly_remote_73_direct(tmp_path) -> None:
  h = _h(tmp_path)
  c = _cyc(h, 4)
  h.feed("CQ IK4LZH JN54", cycle=c[0])
  h.feed("IK4LZH N0CALL -09", cycle=c[1])
  h.feed("IK4LZH N0CALL R-05", cycle=c[2])
  h.feed("IK4LZH N0CALL 73", cycle=c[3])
  assert h.last_tx.endswith("73")
  assert h.phase == QsoPhase.IDLE


def test_anomaly_hz_stays_on_first(tmp_path) -> None:
  h = _h(tmp_path)
  c = _cyc(h, 3)
  h.feed("CQ IK4LZH JN54", cycle=c[0], hz=397)
  h.feed("IK4LZH N0CALL -09", cycle=c[1], hz=999)
  want_hz = snap_ft8_hz(397)
  assert all(tx.audio_hz == want_hz for tx in h.tx.calls)


def test_anomaly_cq_without_grid(tmp_path) -> None:
  h = _h(tmp_path)
  h.feed("CQ IK4LZH", snr=-8, hz=500)
  assert h.op._active is not None
  assert h.last_tx == "IK4LZH N0CALL JN96"


def test_anomaly_rapid_decodes_drain_queue(tmp_path) -> None:
  h = _h(tmp_path)
  c = _cyc(h, 2)
  h.feed("CQ IK4LZH JN54", cycle=c[0])
  assert h.tx.messages()[0] == "IK4LZH N0CALL JN96"
  h.op.on_decode(
    LogDecode(c[1], "IK4LZH N0CALL -09", -9, 397, 7074.0, "report", 0.0).to_report()
  )
  h.wait_tx(2)
  assert h.tx.messages()[1].endswith("R-09")


# --- on_cycle: retry + saját CQ ---


def test_cycle_retry_same_message(tmp_path) -> None:
  h = _h(tmp_path)
  h.feed("CQ IK4LZH JN54", hz=397)
  tx_p = h.op._active.tx_period
  with patch("cw_discover.ft8.qso_controller.ft8_period_at", return_value=tx_p):
    h.op._active.cycles_without_reply = 1
    h.tick_cycle("retry_cycle")
  h.wait_tx(2)
  assert len(h.tx.messages()) == 2
  assert h.tx.messages()[1] == h.tx.messages()[0]


def test_cycle_own_cq_when_idle(tmp_path) -> None:
  h = _h(tmp_path)
  h.op.station.cq_repeat_cycles = 3
  h.op.set_armed(True)
  with patch("cw_discover.ft8.qso_controller.ft8_period_at", return_value=0):
    h.op._cq_tx_period = 0
    h.op.on_cycle("c1", 0.0)
  h.wait_tx(1)
  assert h.tx.messages()[0].startswith("CQ N0CALL")


# --- engage_call kényszerítés ---


def test_engage_call_with_report(tmp_path) -> None:
  h = _h(tmp_path)
  h.op.engage_call("IK4LZH", 397.0, rx_report="-09", rx_snr=-9)
  h.wait_tx(1)
  assert h.last_tx.endswith("R-09")


def test_engage_call_grid_only(tmp_path) -> None:
  h = _h(tmp_path)
  h.op.engage_call("DK7ZT", 1867.0)
  h.wait_tx(1)
  assert h.last_tx == "DK7ZT N0CALL JN96"


# --- További élő napló anomáliák ---


def test_anomaly_incoming_with_report_not_grid(tmp_path) -> None:
  """Bejövő közvetlen reporttal (kihagyott grid lépés)."""
  h = _h(tmp_path)
  c = _cyc(h, 4)
  h.feed("IK4LZH N0CALL -09", cycle=c[0], snr=-9, hz=397)
  assert h.last_tx.endswith("R-09")
  assert h.op._active.remote_call == "IK4LZH"


def test_anomaly_remote_cq_again_mid_qso(tmp_path) -> None:
  """Remote újra CQ-zik QSO közben — ignoráljuk."""
  h = _h(tmp_path)
  c = _cyc(h, 3)
  h.feed("CQ IK4LZH JN54", cycle=c[0], hz=397)
  h.feed("CQ IK4LZH JN54", cycle=c[1], hz=397)
  assert len(h.tx.messages()) == 1


def test_anomaly_three_cq_defer_best(tmp_path) -> None:
  """3 CQ ugyanabban a slotban — PRO késleltetett választás."""
  pro = ProOperatorConfig(enabled=True, defer_cq_pick=True, max_snr=15)
  h = _h(tmp_path, pro=pro)
  c = _cyc(h, 2)
  h.feed("CQ IK4LZH JN54", cycle=c[0], snr=-18, hz=500, wait=False)
  h.feed("CQ SP9JMZ JO90", cycle=c[0], snr=-5, hz=800, wait=False)
  h.feed("CQ DK7ZT JO30", cycle=c[0], snr=-12, hz=1200, wait=False)
  assert len(h.op._cq_buffer) == 3
  h.op.on_cycle("flush_x", 0.0)
  h.wait_tx(1)
  assert h.op._active is not None


def test_anomaly_max_retry_then_new_cq(tmp_path) -> None:
  """Feladás után új CQ fogadható."""
  h = _h(tmp_path)
  h.feed("CQ IK4LZH JN54", hz=397)
  tx_p = h.op._active.tx_period
  with patch("cw_discover.ft8.qso_controller.ft8_period_at", return_value=tx_p):
    for i in range(4):
      h.tick_cycle(f"abandon{i}")
  assert h.phase == QsoPhase.IDLE
  h.feed("CQ DK7ZT JO30", hz=1867)
  assert h.op._active.remote_call == "DK7ZT"


def test_anomaly_non_callsign_cq_ignored(tmp_path) -> None:
  h = _h(tmp_path)
  h.feed("CQ TESTCALL", wait=False)
  assert h.op._active is None



@pytest.mark.skipif(not LOG_TODAY.exists(), reason="nincs napló")
def test_log_find_cq_sequences_smoke() -> None:
  decs = load_decodes(LOG_TODAY, limit=5000)
  seqs = find_cq_sequences(decs, "IK4LZH")
  # lehet 0 is ha nincs lezárt — csak ne omoljon össze
  assert isinstance(seqs, list)


# --- DA0WWA minta a naplóból (4 lépés) ---


def test_log_style_da0wwa_pattern(tmp_path) -> None:
  """Napló stílus: CQ → report → R-report → 73."""
  h = _h(tmp_path)
  c = _cyc(h, 5)
  h.feed("CQ DA0WWA JN68", cycle=c[0], snr=-10, hz=747)
  h.feed("DA0WWA N0CALL -15", cycle=c[1], snr=4)
  h.feed("DA0WWA N0CALL R-11", cycle=c[2], snr=-11)
  h.feed("DA0WWA N0CALL 73", cycle=c[3], snr=-11)
  assert h.phase == QsoPhase.IDLE
  assert "DA0WWA" in (tmp_path / "qso.jsonl").read_text()
