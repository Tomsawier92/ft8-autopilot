#!/usr/bin/env python3
"""FT8 auto üzem felügyelet — live dekódok, PRO+PTT fenntartás."""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cw_discover.ft8.decode_meta import daily_decodes_day, daily_decodes_jsonl
from cw_discover.paths import FORGALMI_LIVE, LOG_DIR

LIVE = FORGALMI_LIVE
OPERATOR_IN = LIVE / "operator_in.txt"
GUI_STATUS = LIVE / "gui_status.json"
DECODES = LIVE / "decodes.log"
WATCH_LOG = LIVE / "auto_watch.log"
ME = "N0CALL"
_status_cache: dict = {}
_status_mtime: float = -1.0
_ha3gx_tail_cache: tuple[str, list[str]] = ("", [])


def today_decodes_path() -> Path:
  return daily_decodes_jsonl(LOG_DIR)


def log(msg: str) -> None:
  LIVE.mkdir(parents=True, exist_ok=True)
  ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
  line = f"[{ts}] {msg}"
  print(line, flush=True)
  with WATCH_LOG.open("a", encoding="utf-8") as f:
    f.write(line + "\n")


def send(*cmds: str) -> None:
  OPERATOR_IN.write_text("\n".join(cmds) + "\n", encoding="utf-8")


def status() -> dict:
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


def tail_jsonl_ha3gx() -> list[str]:
  global _ha3gx_tail_cache
  path = today_decodes_path()
  try:
    st = path.stat()
    cache_key = f"{daily_decodes_day(LOG_DIR)}:{st.st_mtime}"
    if cache_key == _ha3gx_tail_cache[0]:
      return _ha3gx_tail_cache[1]
    size = st.st_size
    with path.open("rb") as f:
      f.seek(max(0, size - 65536))
      chunk = f.read()
    lines = chunk.splitlines()[-40:]
  except OSError:
    return []
  out: list[str] = []
  for raw_line in lines:
    try:
      d = json.loads(raw_line)
      msg = str(d.get("message", ""))
      if ME in msg:
        out.append(f"{d.get('cycle','')} SNR{d.get('snr',0):+d} {msg}")
    except json.JSONDecodeError:
      pass
  result = out[-5:]
  _ha3gx_tail_cache = (cache_key, result)
  return result


def ensure_auto() -> None:
  st = status()
  if not st:
    log("GUI status hiányzik")
    return
  cmds: list[str] = []
  if not st.get("rx_running"):
    cmds.append("START_RX")
  if not st.get("pro_operator"):
    cmds.append("PRO_ON")
  if not st.get("ptt_armed"):
    cmds.append("PTT_ON")
  if cmds:
    log("Parancs: " + ", ".join(cmds))
    send(*cmds)


def main() -> None:
  log("=== auto_ft8_watch indul ===")
  send("START_RX", "PRO_ON", "PTT_ON")
  last_phase = ""
  last_note = ""
  while True:
    ensure_auto()
    st = status()
    phase = st.get("qso_phase", "?")
    note = st.get("note", "")
    tx = st.get("tx_active", False)
    last = st.get("last_message", "")
    if phase != last_phase or note != last_note:
      log(f"állapot: phase={phase} tx={tx} last={last!r} note={note!r}")
      last_phase, last_note = phase, note
    hits = tail_jsonl_ha3gx()
    if hits:
      log("N0CALL jel: " + hits[-1])
    time.sleep(5)


if __name__ == "__main__":
  main()
