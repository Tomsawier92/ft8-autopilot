"""FT8 QSO protokoll — üzenetváltás szimuláció."""
from __future__ import annotations

import time
from datetime import datetime, timezone

from cw_discover.ft8.engine import DecodeReport
from cw_discover.ft8.forgalmi_log import ForgalmiNaplo
from cw_discover.ft8.qso_controller import Ft8AutoOperator, QsoPhase
from cw_discover.ft8.ft8_slot import opposite_period, period_from_cycle
from cw_discover.ft8.station_identity import StationIdentity
from cw_discover.ft8.tx_player import Ft8TxPlayer


def _fresh_cycle(align_offset: int = 0) -> str:
  t = int(time.time()) - align_offset
  t -= t % 15
  return time.strftime("%y%m%d_%H%M%S", time.gmtime(t))


def _report(message: str, cycle: str | None = None, snr: int = -10, hz: int = 1500) -> DecodeReport:
  return DecodeReport(
    cycle=cycle or _fresh_cycle(),
    snr=snr,
    dt=0.1,
    audio_hz=hz,
    rf_khz=7074.0,
    message=message,
    time_received=datetime.now(tz=timezone.utc).timestamp(),
  )


def test_cq_answer_sets_opposite_slot(tmp_path) -> None:
  st = StationIdentity(callsign="N0CALL", grid="JN96", cq_min_snr=-20, ptt_port="")
  op = Ft8AutoOperator(station=st, naplo=ForgalmiNaplo(tmp_path, station=st), tx=Ft8TxPlayer(simulate=True))
  op.set_armed(True)
  op.on_decode(_report("CQ IK4LZH JN54", cycle=_fresh_cycle(0)))
  assert op._active is not None
  heard = period_from_cycle(_fresh_cycle(0))
  assert op._active.tx_period == opposite_period(heard)


def test_incoming_call(tmp_path) -> None:
  st = StationIdentity(callsign="N0CALL", grid="JN96", ptt_port="")
  op = Ft8AutoOperator(station=st, naplo=ForgalmiNaplo(tmp_path, station=st), tx=Ft8TxPlayer(simulate=True))
  op.set_armed(True)
  op.on_decode(_report("IK4LZH N0CALL JN54", cycle=_fresh_cycle(0)))
  assert op._active.remote_call == "IK4LZH"


def test_self_decode_ignored(tmp_path) -> None:
  st = StationIdentity(callsign="N0CALL", grid="JN96", ptt_port="")
  op = Ft8AutoOperator(station=st, naplo=ForgalmiNaplo(tmp_path, station=st), tx=Ft8TxPlayer(simulate=True))
  op.set_armed(True)
  op.on_decode(_report("N0CALL DK7ZT -09"))
  assert op._active is None


def test_active_report_exchange(tmp_path) -> None:
  st = StationIdentity(callsign="N0CALL", grid="JN96", ptt_port="")
  op = Ft8AutoOperator(station=st, naplo=ForgalmiNaplo(tmp_path, station=st), tx=Ft8TxPlayer(simulate=True))
  op.set_armed(True)
  op.on_decode(_report("CQ IK4LZH JN54", cycle=_fresh_cycle(0)))
  op.on_decode(_report("IK4LZH N0CALL -09", cycle=_fresh_cycle(0)))
  assert op._active.rst_rcvd == "-09"
  assert op._last_tx_msg.startswith("IK4LZH N0CALL R")
