#!/usr/bin/env python3
"""PTT tesztsorozat a futó FT8 GUI-n keresztül (operator_in.txt)."""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cw_discover.paths import FORGALMI_LIVE, TX_LOG

LIVE = FORGALMI_LIVE
OPERATOR_IN = LIVE / "operator_in.txt"
GUI_STATUS = LIVE / "gui_status.json"
RESULT = LIVE / "ptt_test_result.json"


def send(cmd: str) -> None:
  OPERATOR_IN.write_text(cmd.strip() + "\n", encoding="utf-8")
  print(f"→ {cmd}")


def read_status() -> dict:
  if not GUI_STATUS.exists():
    return {}
  return json.loads(GUI_STATUS.read_text(encoding="utf-8"))


def wait_idle(timeout: float = 30.0) -> dict:
  t0 = time.time()
  while time.time() - t0 < timeout:
    st = read_status()
    if not st.get("tx_active"):
      return st
    time.sleep(0.3)
  return read_status()


def tail_tx_log(since_lines: int) -> list[str]:
  if not TX_LOG.exists():
    return []
  lines = TX_LOG.read_text(encoding="utf-8").splitlines()
  return lines[since_lines:]


def main() -> None:
  LIVE.mkdir(parents=True, exist_ok=True)
  log_lines_before = len(TX_LOG.read_text(encoding="utf-8").splitlines()) if TX_LOG.exists() else 0
  st0 = read_status()
  if not st0.get("ptt_serial_ok"):
    print("FIGYELEM: ptt_serial_ok=false — a GUI nem látja az ESP-t")

  results: list[dict] = []
  tests = [
    ("PTT_PULSE 3", "Rövid PTT kulcsolás 3 mp — hallanod kell TX-re kapcsolást"),
    ("PTT_PULSE 2", "Második PTT impulzus 2 mp"),
    ("TX_TEST", "FT8 CQ slot (~13 s) — PTT + hang, mint éles adás"),
  ]

  print("=== PTT GUI teszt indul ===")
  print("Visszajelzésedre várok a rádión — nézd a TX zaj elhallgatását.\n")

  for cmd, desc in tests:
    print(f"\n--- {desc} ---")
    send(cmd)
    time.sleep(1.5)
    st = wait_idle(timeout=20.0 if "PULSE" in cmd else 25.0)
    entry = {
      "time_utc": datetime.now(tz=timezone.utc).isoformat(),
      "cmd": cmd,
      "desc": desc,
      "tx_active_end": st.get("tx_active"),
      "last_tx_error": st.get("last_tx_error", ""),
      "note": st.get("note", ""),
      "ptt_serial_ok": st.get("ptt_serial_ok"),
    }
    results.append(entry)
    print(f"   állapot: note={entry['note']!r} error={entry['last_tx_error']!r}")
    time.sleep(3)

  new_tx = tail_tx_log(log_lines_before)
  out = {
    "finished_utc": datetime.now(tz=timezone.utc).isoformat(),
    "ptt_serial_ok_start": st0.get("ptt_serial_ok"),
    "results": results,
    "tx_log_new": new_tx,
  }
  RESULT.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
  print(f"\n=== Kész — eredmény: {RESULT} ===")
  for r in results:
    ok = not r["last_tx_error"] and "HIBA" not in (r["note"] or "")
    print(f"  {'✓' if ok else '✗'} {r['cmd']}: {r['note'] or r['last_tx_error'] or '—'}")


if __name__ == "__main__":
  main()
