"""Atomi fájlírás — áramszünet / összeomlás ellen (rename + fsync)."""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from cw_discover.ft8.decode_meta import day_key_utc
from cw_discover.ft8.json_fast import dumps_compact, dumps_line, dumps_lines


def atomic_write_bytes(path: Path, data: bytes, *, fsync: bool = True) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
  os.close(fd)
  tmp_path = Path(tmp)
  try:
    with tmp_path.open("wb") as f:
      f.write(data)
      if fsync:
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)
    if fsync:
      dir_fd = os.open(path.parent, os.O_RDONLY)
      try:
        os.fsync(dir_fd)
      finally:
        os.close(dir_fd)
  finally:
    if tmp_path.exists():
      tmp_path.unlink(missing_ok=True)


def atomic_write_json(path: Path, payload: dict[str, Any], *, compact: bool = True, fsync: bool = True) -> None:
  if compact:
    text = dumps_compact(payload)
  else:
    text = json.dumps(payload, indent=2, ensure_ascii=False)
  atomic_write_bytes(path, text.encode("utf-8"), fsync=fsync)


class AtomicJsonlSink:
  """JSONL soronként; power_safe módban fsync minden sor után."""

  def __init__(self, path: Path, *, power_safe: bool = False) -> None:
    self.path = path
    self.power_safe = power_safe
    self._lock = threading.Lock()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)

  def append(self, record: dict[str, Any]) -> None:
    data = dumps_line(record)
    with self._lock:
      with self.path.open("ab") as f:
        f.write(data)
        if self.power_safe:
          f.flush()
          os.fsync(f.fileno())


class DailyBufferedWriter:
  """Napi JSONL fájlok — memóriában gyűjt, 5 percenként (vagy kényszerítve) ír lemezre."""

  FLUSH_INTERVAL_S = 300.0
  TICK_S = 30.0

  def __init__(self, log_dir: Path, *, power_safe: bool = False) -> None:
    self.log_dir = log_dir
    self.power_safe = power_safe
    self._lock = threading.Lock()
    self._decode_buf: list[dict[str, Any]] = []
    self._candidate_buf: list[dict[str, Any]] = []
    self._last_flush = time.monotonic()
    self._stop = threading.Event()
    self._timer = threading.Thread(target=self._timer_loop, daemon=True, name="daily-log-flush")
    self._timer.start()

  @staticmethod
  def day_key(ts: float) -> str:
    return day_key_utc(ts)

  def _path_for(self, day: str, kind: str) -> Path:
    d = self.log_dir / day
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{kind}.jsonl"

  def append_decode(self, record: dict[str, Any]) -> None:
    with self._lock:
      self._decode_buf.append(record)
      self._maybe_flush_locked()

  def append_candidate(self, record: dict[str, Any]) -> None:
    with self._lock:
      self._candidate_buf.append(record)
      self._maybe_flush_locked()

  def pending_count(self) -> int:
    with self._lock:
      return len(self._decode_buf) + len(self._candidate_buf)

  def flush(self) -> None:
    with self._lock:
      self._flush_locked()

  def _maybe_flush_locked(self) -> None:
    if time.monotonic() - self._last_flush >= self.FLUSH_INTERVAL_S:
      self._flush_locked()

  def _timer_loop(self) -> None:
    while not self._stop.wait(self.TICK_S):
      with self._lock:
        if time.monotonic() - self._last_flush >= self.FLUSH_INTERVAL_S:
          self._flush_locked()

  def _flush_locked(self) -> None:
    self._last_flush = time.monotonic()
    for buf, kind in ((self._decode_buf, "decodes"), (self._candidate_buf, "candidates")):
      if not buf:
        continue
      by_day: dict[str, list[bytes]] = {}
      for rec in buf:
        ts = float(rec.get("time_received", time.time()))
        by_day.setdefault(self.day_key(ts), []).append(dumps_line(rec))
      for day, chunks in by_day.items():
        path = self._path_for(day, kind)
        blob = b"".join(chunks)
        with path.open("ab") as f:
          f.write(blob)
          if self.power_safe:
            f.flush()
            os.fsync(f.fileno())
    self._decode_buf.clear()
    self._candidate_buf.clear()

  def close(self) -> None:
    self._stop.set()
    self.flush()
