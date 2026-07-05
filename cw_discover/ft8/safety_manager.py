"""Biztonsági állapot — mentés + visszaállítás."""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from cw_discover.ft8.decode_meta import time_iso_utc
from cw_discover.ft8.json_fast import dumps_compact

from cw_discover.paths import SAFETY_STATE as SAFETY_STATE_PATH


@dataclass
class SafetySnapshot:
  tripped: bool = False
  reason: str = ""
  time_utc: str = ""
  watchdog_on: bool = True
  line_guard_on: bool = True
  mcu_active: bool = True


def load_safety_state(path: Path = SAFETY_STATE_PATH) -> SafetySnapshot:
  try:
    data = json.loads(path.read_text(encoding="utf-8"))
    return SafetySnapshot(
      tripped=bool(data.get("tripped", False)),
      reason=str(data.get("reason", "")),
      time_utc=str(data.get("time_utc", "")),
      watchdog_on=bool(data.get("watchdog_on", True)),
      line_guard_on=bool(data.get("line_guard_on", True)),
      mcu_active=bool(data.get("mcu_active", True)),
    )
  except (OSError, json.JSONDecodeError, TypeError):
    return SafetySnapshot()


def save_safety_state(snap: SafetySnapshot, path: Path = SAFETY_STATE_PATH) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_text(dumps_compact(asdict(snap)) + "\n", encoding="utf-8")


def mark_tripped(snap: SafetySnapshot, reason: str) -> SafetySnapshot:
  snap.tripped = True
  snap.reason = reason
  snap.time_utc = time_iso_utc(time.time())
  snap.watchdog_on = False
  snap.line_guard_on = False
  snap.mcu_active = False
  return snap


def mark_reactivated(snap: SafetySnapshot, *, watchdog: bool, line_guard: bool, mcu: bool) -> SafetySnapshot:
  snap.tripped = False
  snap.reason = ""
  snap.time_utc = ""
  snap.watchdog_on = watchdog
  snap.line_guard_on = line_guard
  snap.mcu_active = mcu
  return snap


def status_summary(snap: SafetySnapshot) -> str:
  if snap.tripped:
    when = snap.time_utc[:19].replace("T", " ") if snap.time_utc else "?"
    return f"TILTVA — {snap.reason} ({when} UTC)"
  parts = []
  parts.append("PTT watchdog: " + ("BE" if snap.watchdog_on else "KI"))
  parts.append("Vonal: " + ("ZÁROLVA" if snap.line_guard_on else "szabad"))
  parts.append("ESP32: " + ("OK" if snap.mcu_active else "LEÁLLÍTVA"))
  return " | ".join(parts)
