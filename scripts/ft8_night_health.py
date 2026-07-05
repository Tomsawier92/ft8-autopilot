#!/usr/bin/env python3
"""FT8 éjszakai egészségellenőrzés — csak kritikus hibánál restart."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cw_discover.ft8.decode_meta import time_iso_utc
from cw_discover.ft8.json_fast import dumps_compact
from cw_discover.paths import FORGALMI_LIVE, TX_LOG

LIVE = FORGALMI_LIVE
GUI_STATUS = LIVE / "gui_status.json"
STATE_PATH = LIVE / "night_watch_state.json"
WATCH_LOG = LIVE / "night_watch.log"
START_SCRIPT = ROOT / "scripts" / "start_auto_ft8.sh"
OPERATOR_IN = LIVE / "operator_in.txt"

STALE_STATUS_SEC = 180
STUCK_TX_SEC = 90
FLAT_DECODE_CHECKS = 3  # 3×30 perc dekód nélkül + nincs TX → restart


def log(msg: str) -> None:
  LIVE.mkdir(parents=True, exist_ok=True)
  ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
  line = f"[{ts}] {msg}"
  print(line, flush=True)
  with WATCH_LOG.open("a", encoding="utf-8") as f:
    f.write(line + "\n")


_status_cache: dict = {}
_status_mtime: float = -1.0
_tx_ts_cache: tuple[float, str] = (-1.0, "")


def load_status() -> dict:
  global _status_cache, _status_mtime
  try:
    mtime = GUI_STATUS.stat().st_mtime
    if mtime == _status_mtime:
      return _status_cache
    _status_cache = json.loads(GUI_STATUS.read_text(encoding="utf-8"))
    _status_mtime = mtime
    return _status_cache
  except (json.JSONDecodeError, OSError):
    return {}


def status_age_sec(st: dict) -> float | None:
  raw = st.get("time_utc")
  if not raw:
    return None
  try:
    ts = datetime.fromisoformat(str(raw))
    if ts.tzinfo is None:
      ts = ts.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - ts).total_seconds()
  except ValueError:
    return None


def gui_running() -> bool:
  try:
    r = subprocess.run(
      ["pgrep", "-f", "run_ft8_gui.py"],
      capture_output=True,
      text=True,
      timeout=5,
    )
    return r.returncode == 0
  except (subprocess.TimeoutExpired, OSError):
    return False


def bridge_running() -> bool:
  try:
    r = subprocess.run(
      ["pgrep", "-f", "ft8_live_bridge.py"],
      capture_output=True,
      text=True,
      timeout=5,
    )
    return r.returncode == 0
  except (subprocess.TimeoutExpired, OSError):
    return False


def last_tx_age_sec() -> float | None:
  global _tx_ts_cache
  try:
    st = TX_LOG.stat()
    mtime = st.st_mtime
    if mtime == _tx_ts_cache[0] and _tx_ts_cache[1]:
      ts = datetime.fromisoformat(_tx_ts_cache[1])
      if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
      return (datetime.now(timezone.utc) - ts).total_seconds()
    size = st.st_size
    with TX_LOG.open("rb") as f:
      f.seek(max(0, size - 8192))
      chunk = f.read().decode("utf-8", errors="replace")
    lines = chunk.splitlines()
  except OSError:
    return None
  for line in reversed(lines):
    if "TX_START" not in line and "TX_OK" not in line:
      continue
    try:
      iso = line[:26]
      ts = datetime.fromisoformat(iso)
      if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
      _tx_ts_cache = (mtime, iso)
      return (datetime.now(timezone.utc) - ts).total_seconds()
    except ValueError:
      continue
  return None


def load_state() -> dict:
  try:
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))
  except (json.JSONDecodeError, OSError):
    return {}


def save_state(**fields) -> None:
  st = load_state()
  st.update(fields)
  st["updated_utc"] = time_iso_utc(time.time())
  STATE_PATH.write_text(dumps_compact(st) + "\n", encoding="utf-8")


def soft_fix(st: dict) -> list[str]:
  cmds: list[str] = []
  if not st.get("rx_running"):
    cmds.append("START_RX")
  if not st.get("pro_operator"):
    cmds.append("PRO_ON")
  if not st.get("ptt_armed"):
    cmds.append("PTT_ON")
  if cmds:
    OPERATOR_IN.write_text("\n".join(cmds) + "\n", encoding="utf-8")
    log("soft_fix: " + ", ".join(cmds))
  return cmds


def hard_restart(cq_only: bool) -> None:
  log(f"HARD RESTART (cq_only={cq_only})")
  subprocess.run(["bash", str(START_SCRIPT)], check=False, timeout=120)
  time.sleep(8)
  mode = "CQ_MODE_ON" if cq_only else "CQ_MODE_OFF"
  OPERATOR_IN.write_text(f"{mode}\n", encoding="utf-8")
  log(f"post-restart: {mode}")


def assess() -> tuple[str, list[str]]:
  """Return (verdict, reasons). verdict: ok | soft | restart"""
  reasons: list[str] = []
  st = load_status()
  prev = load_state()

  if not gui_running():
    return "restart", ["run_ft8_gui.py nem fut"]

  if not st:
    return "restart", ["gui_status.json hiányzik vagy sérült"]

  age = status_age_sec(st)
  if age is not None and age > STALE_STATUS_SEC:
    reasons.append(f"gui_status elavult ({age:.0f}s)")

  if st.get("safety_tripped"):
    reasons.append(f"safety_tripped: {st.get('safety_reason', '?')}")

  if st.get("last_tx_error"):
    reasons.append(f"last_tx_error: {st.get('last_tx_error')}")

  if st.get("tx_active"):
    tx_age = age if age is not None else 0
    if tx_age > STUCK_TX_SEC:
      reasons.append(f"tx_active túl sokáig ({tx_age:.0f}s)")

  if reasons:
    return "restart", reasons

  decode = int(st.get("decode_count") or 0)
  prev_decode = prev.get("decode_count")
  flat_count = int(prev.get("flat_decode_checks") or 0)
  tx_age = last_tx_age_sec()

  if prev_decode is not None and decode <= prev_decode:
    if tx_age is None or tx_age > 1800:
      flat_count += 1
    else:
      flat_count = 0
  else:
    flat_count = 0

  save_state(
    decode_count=decode,
    flat_decode_checks=flat_count,
    qso_phase=st.get("qso_phase"),
    qso_partner=st.get("qso_partner"),
    cq_only_mode=st.get("cq_only_mode"),
  )

  if flat_count >= FLAT_DECODE_CHECKS and not st.get("rx_running"):
    return "restart", [f"nincs dekód/TX {flat_count} ellenőrzés óta, RX sem fut"]

  soft_needed = (
    not st.get("rx_running")
    or not st.get("pro_operator")
    or not st.get("ptt_armed")
  )
  if soft_needed:
    return "soft", ["RX/PRO/PTT kikapcsolva"]

  if not bridge_running():
    return "soft", ["ft8_live_bridge.py nem fut — auto_watch kezeli"]

  return "ok", []


def main() -> int:
  st = load_status()
  verdict, reasons = assess()
  cq_only = bool(st.get("cq_only_mode", False))

  summary = {
    "verdict": verdict,
    "reasons": reasons,
    "phase": st.get("qso_phase"),
    "partner": st.get("qso_partner"),
    "decode_count": st.get("decode_count"),
    "rx": st.get("rx_running"),
    "ptt": st.get("ptt_armed"),
    "pro": st.get("pro_operator"),
    "cq_only": cq_only,
    "safety_tripped": st.get("safety_tripped"),
  }
  log("check: " + json.dumps(summary, ensure_ascii=False))

  if verdict == "ok":
    log("OK — nincs beavatkozás")
    return 0

  if verdict == "soft":
    soft_fix(st)
    log("SOFT FIX — várunk")
    return 0

  cq_only = bool(st.get("cq_only_mode", False))
  hard_restart(cq_only)
  time.sleep(5)
  v2, r2 = assess()
  if v2 == "ok":
    log("RESTART sikeres")
    return 0
  log("RESTART után még gond: " + "; ".join(r2))
  return 1


if __name__ == "__main__":
  sys.exit(main())
