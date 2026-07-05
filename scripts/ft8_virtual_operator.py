#!/usr/bin/env python3
"""Headless FT8 operátor — virtuális RX (AI injekt), valódi PTT/TX."""
from __future__ import annotations

import argparse
import atexit
import json
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cw_discover.ft8.atomic_io import atomic_write_json
from cw_discover.ft8.engine import DecodeReport
from cw_discover.ft8.ptt_client import Esp32Ptt, make_ptt
from cw_discover.ft8.qso_controller import Ft8AutoOperator
from cw_discover.ft8.session_log import SessionLog
from cw_discover.ft8.station_identity import StationIdentity
from cw_discover.ft8.tx_player import Ft8TxPlayer
from cw_discover.ft8.virtual_engine import (
  DEFAULT_INJECT_JSONL,
  DEFAULT_INJECT_TXT,
  FORGALMI_LIVE,
  VirtualFt8Engine,
)

OPERATOR_IN = FORGALMI_LIVE / "operator_in.txt"
GUI_STATUS = FORGALMI_LIVE / "gui_status.json"
OPERATOR_LOG = FORGALMI_LIVE / "virtual_operator.log"


def _log(msg: str) -> None:
  FORGALMI_LIVE.mkdir(parents=True, exist_ok=True)
  line = f"[{datetime.now(timezone.utc).isoformat()}] {msg}\n"
  with OPERATOR_LOG.open("a", encoding="utf-8") as f:
    f.write(line)
  print(msg, flush=True)


def main() -> int:
  ap = argparse.ArgumentParser(description="FT8 virtuális RX + éles TX operátor")
  ap.add_argument("--dial", type=float, default=7.074)
  ap.add_argument("--band", default="40m")
  ap.add_argument("--simulate-tx", action="store_true", help="Nincs PTT/hang (teszt)")
  ap.add_argument("--no-arm", action="store_true", help="Ne kapcsolja be automatikusan a PTT-t")
  ap.add_argument("--no-pro", action="store_true", help="PRO operátor kikapcsolva induláskor")
  args = ap.parse_args()

  station = StationIdentity.load()
  if station.callsign in ("", "N0CALL"):
    _log("HIBA: állítsd be a hívójelet forgalminaplo/station.json-ban")
    return 1

  ptt = make_ptt(station.ptt_port)
  ptt_ok = True
  if isinstance(ptt, Esp32Ptt):
    ptt.sync_time()
    ptt_ok = ptt.ping()

  tx_active = False
  last_tx_error = ""
  decode_count = 0
  last_message = ""
  note = ""

  def on_tx_state(active: bool, _label: str, err: str = "") -> None:
    nonlocal tx_active, last_tx_error
    tx_active = active
    if err:
      last_tx_error = err

  def on_status(msg: str) -> None:
    nonlocal note
    note = msg
    _log(f"STATUS| {msg}")

  def on_tx(msg: str) -> None:
    nonlocal last_message
    last_message = msg
    _log(f"TX| {msg}")

  operator = Ft8AutoOperator(
    station=station,
    tx=Ft8TxPlayer(
      ptt=ptt,
      audio_device=station.tx_audio_device,
      simulate=args.simulate_tx,
      on_state=on_tx_state,
    ),
    on_status=on_status,
    on_tx=on_tx,
  )
  operator.set_band(args.band, args.dial)

  session = SessionLog()
  session.reset(args.band, args.dial, pulse_device="virtual", home=None)

  stop = False
  eng: VirtualFt8Engine | None = None

  def shutdown(reason: str = "normal") -> None:
    nonlocal eng
    if eng is not None:
      eng.stop()
      eng = None
    session.shutdown()
    operator.set_armed(False)
    _log(f"Leállítás ({reason})")

  def on_sig(_s, _f):
    nonlocal stop
    stop = True

  signal.signal(signal.SIGINT, on_sig)
  signal.signal(signal.SIGTERM, on_sig)
  atexit.register(lambda: shutdown("atexit"))

  def on_decode(report: DecodeReport) -> None:
    nonlocal decode_count, last_message
    decode_count += 1
    last_message = report.message
    _log(f"RX| {report.wsjtx_line}")
    operator.on_decode(report)
    session.add_decode(
      decode_id=decode_count,
      message=report.message,
      snr=report.snr,
      rf_khz=report.rf_khz,
      cycle=report.cycle,
      audio_hz=report.audio_hz,
      dt=report.dt,
      time_received=report.time_received,
      cycle_start_utc=report.cycle_start_utc,
      dsp=report.dsp,
      audio=report.audio,
    )

  def on_cycle(cycle: str, cst: float, n: int, busy, ts: float, _snap) -> None:
    session.note_cycle_search(cycle, cst, n, busy, ts)
    operator.on_cycle(cycle, ts)

  eng = VirtualFt8Engine(
    dial_mhz=args.dial,
    band=args.band,
    on_decode=on_decode,
    on_cycle_search=on_cycle,
  )
  eng.start()

  if not args.no_arm:
    operator.set_armed(True)
  if not args.no_pro:
    station.pro.enabled = True
    operator.set_pro_config(station.pro)

  pro_on = station.pro.enabled
  ptt_armed = operator.armed

  _log(
    f"Virtuális FT8 indul — {station.callsign} @ {args.dial} MHz "
    f"inject={DEFAULT_INJECT_JSONL} ptt_ok={ptt_ok} simulate={args.simulate_tx}"
  )

  def poll_operator_in() -> None:
    nonlocal pro_on, ptt_armed, note
    if not OPERATOR_IN.exists():
      return
    text = OPERATOR_IN.read_text(encoding="utf-8").strip()
    if not text:
      return
    OPERATOR_IN.write_text("", encoding="utf-8")
    for line in text.splitlines():
      cmd = line.strip().upper()
      if cmd == "PTT_ON":
        operator.set_armed(True)
        ptt_armed = True
      elif cmd == "PTT_OFF":
        operator.set_armed(False)
        ptt_armed = False
      elif cmd == "PRO_ON":
        station.pro.enabled = True
        operator.set_pro_config(station.pro)
        pro_on = True
      elif cmd == "PRO_OFF":
        station.pro.enabled = False
        operator.set_pro_config(station.pro)
        pro_on = False
      elif cmd == "ABORT_QSO":
        operator.abort_qso("operátor")
      elif cmd.startswith("CALL "):
        parts = cmd.split()
        if len(parts) >= 2:
          call = parts[1]
          hz = float(parts[2]) if len(parts) > 2 else 1867.0
          report = parts[3] if len(parts) > 3 else ""
          snr = int(parts[4]) if len(parts) > 4 else -15
          operator.engage_call(call, hz, rx_report=report, rx_snr=snr)
      elif cmd == "START_RX":
        pass
      else:
        _log(f"Ismeretlen parancs: {cmd}")
    note = f"cmd:{text}"

  def write_status() -> None:
    st = {
      "time_utc": datetime.now(timezone.utc).isoformat(),
      "mode": "virtual_rx",
      "callsign": station.callsign,
      "operator": station.operator_name,
      "band": args.band,
      "dial_mhz": args.dial,
      "rx_running": eng is not None and eng.running,
      "rx_source": "virtual",
      "inject_jsonl": str(DEFAULT_INJECT_JSONL),
      "inject_txt": str(DEFAULT_INJECT_TXT),
      "ptt_armed": ptt_armed,
      "pro_operator": pro_on,
      "qso_phase": operator.phase.value,
      "tx_active": tx_active,
      "last_tx_error": last_tx_error,
      "ptt_serial_ok": ptt_ok,
      "decode_count": decode_count,
      "inject_count": eng.inject_count if eng else 0,
      "last_message": last_message,
      "note": note,
    }
    atomic_write_json(GUI_STATUS, st, compact=False, fsync=False)

  def status_loop() -> None:
    while not stop:
      write_status()
      time.sleep(1.0)

  threading.Thread(target=status_loop, daemon=True, name="virtual-status").start()

  while not stop:
    poll_operator_in()
    time.sleep(0.25)

  shutdown("signal")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
