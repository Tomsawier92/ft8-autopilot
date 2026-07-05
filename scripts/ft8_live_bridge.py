#!/usr/bin/env python3
"""FT8 élő híd — AI olvassa a dekódokat, küldjön operátor parancsot."""
from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cw_discover.ft8.decode_meta import daily_decodes_jsonl, daily_decodes_jsonl_str
from cw_discover.ft8.json_fast import dumps_compact
from cw_discover.paths import FORGALMI_LIVE, LOG_DIR

LIVE = FORGALMI_LIVE
DECODES_LOG = LIVE / "decodes.log"
STATUS = LIVE / "ft8_status.json"
OPERATOR_IN = LIVE / "operator_in.txt"
OPERATOR_OUT = LIVE / "operator_out.log"

STATUS_MIN_INTERVAL_S = 1.0
RX_LOG_BATCH = 32


def ts() -> str:
  return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def today_decodes() -> Path:
  return daily_decodes_jsonl(LOG_DIR)


def today_decodes_str() -> str:
  return daily_decodes_jsonl_str(LOG_DIR)


def log_out(msg: str) -> None:
  LIVE.mkdir(parents=True, exist_ok=True)
  line = f"[{ts()}] {msg}\n"
  with OPERATOR_OUT.open("a", encoding="utf-8") as f:
    f.write(line)
  print(msg, flush=True)


def _flush_rx_batch(batch: list[str]) -> None:
  if not batch:
    return
  with DECODES_LOG.open("a", encoding="utf-8") as f:
    f.writelines(batch)
  batch.clear()


class BridgeStatus:
  """Státusz írás throttle — ne írjunk minden dekódnál teljes JSON-t."""

  def __init__(self) -> None:
    self._last_write = 0.0
    self._pending: dict | None = None
    self._static = {
      "bridge_running": True,
      "operator_in": str(OPERATOR_IN),
      "gui_hint": "Írj operator_in.txt: PTT_ON | PTT_OFF | PRO_ON | PRO_OFF | STATUS",
    }

  def update(self, extra: dict | None = None, *, force: bool = False) -> None:
    LIVE.mkdir(parents=True, exist_ok=True)
    st: dict = {
      **self._static,
      "time_utc": ts(),
      "decodes_path": today_decodes_str(),
    }
    if extra:
      st.update(extra)
    now = time.monotonic()
    if force or now - self._last_write >= STATUS_MIN_INTERVAL_S:
      STATUS.write_text(dumps_compact(st) + "\n", encoding="utf-8")
      self._last_write = now
      self._pending = None
    else:
      self._pending = st

  def flush(self) -> None:
    if self._pending is not None:
      self.update(self._pending, force=True)


from cw_discover.ft8.decode_tail import MmapJsonlTail


def main() -> None:
  LIVE.mkdir(parents=True, exist_ok=True)
  log_out("=== FT8 live bridge ===")
  log_out(f"Dekódok: {today_decodes()}")
  path = today_decodes()
  status = BridgeStatus()
  status.update(force=True)
  tail = MmapJsonlTail(path)

  rx_batch: list[str] = []
  last_decode: dict | None = None
  operator_mtime = -1.0

  while True:
    path = today_decodes()
    if tail.path != path:
      tail.set_path(path)
    recs = tail.read_new()
    if recs:
      batch_ts = ts()
    for rec in recs:
      t = str(rec.get("time_iso", ""))[:19]
      snr = rec.get("snr", "?")
      msg = rec.get("message", "?")
      line = f"{t}  SNR{snr:+d}  {msg}" if isinstance(snr, int) else f"{t}  {msg}"
      rx_batch.append(f"[{batch_ts}] {line}\n")
      last_decode = rec
      if len(rx_batch) >= RX_LOG_BATCH:
        _flush_rx_batch(rx_batch)

    _flush_rx_batch(rx_batch)

    if last_decode is not None:
      status.update({"last_decode": last_decode})
      last_decode = None

    try:
      st = OPERATOR_IN.stat()
      if st.st_size > 0 and st.st_mtime != operator_mtime:
        operator_mtime = st.st_mtime
        pending = OPERATOR_IN.read_text(encoding="utf-8").strip()
        if pending:
          status.update({"operator_pending": pending}, force=True)
    except OSError:
      pass

    status.flush()
    time.sleep(0.5)


if __name__ == "__main__":
  main()
