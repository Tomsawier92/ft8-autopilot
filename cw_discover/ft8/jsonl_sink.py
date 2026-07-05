"""Append-only JSONL napló fájlok (munkamenet alatt)."""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from cw_discover.ft8.json_fast import dumps_line


class JsonlSink:
  def __init__(self, path: Path) -> None:
    self.path = path
    self._lock = threading.Lock()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)

  def append(self, record: dict[str, Any]) -> None:
    data = dumps_line(record)
    with self._lock:
      with self.path.open("ab") as f:
        f.write(data)

  def close(self) -> None:
    pass
