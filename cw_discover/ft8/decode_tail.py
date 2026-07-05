"""MMAP-alapú JSONL tail — kevesebb stat/seek overhead élő követéshez."""
from __future__ import annotations

import json
import mmap
from pathlib import Path


class MmapJsonlTail:
  """Fájl végének követése — bridge / watcher számára."""

  __slots__ = ("_path", "_offset")

  @staticmethod
  def _file_size(path: Path) -> int:
    try:
      return path.stat().st_size
    except OSError:
      return 0

  def __init__(self, path: Path) -> None:
    self._path = path
    self._offset = self._file_size(path)

  @property
  def offset(self) -> int:
    return self._offset

  @property
  def path(self) -> Path:
    return self._path

  def set_path(self, path: Path) -> None:
    if path != self._path:
      self._path = path
      self._offset = self._file_size(path)

  def reset(self) -> None:
    self._offset = 0

  @staticmethod
  def _parse_chunk(chunk: bytes | memoryview) -> list[dict]:
    out: list[dict] = []
    for raw in chunk.splitlines():
      if not raw.strip():
        continue
      try:
        out.append(json.loads(raw))
      except (json.JSONDecodeError, UnicodeDecodeError):
        pass
    return out

  def read_new(self) -> list[dict]:
    path = self._path
    try:
      size = path.stat().st_size
    except OSError:
      return []
    if size < self._offset:
      self._offset = 0
    if size <= self._offset:
      return []
    with path.open("rb") as fh:
      fh.seek(self._offset)
      chunk = fh.read(size - self._offset)
      self._offset = size
    return self._parse_chunk(chunk)

  def read_new_mmap(self) -> list[dict]:
    """Nagy fájloknál mmap (read_new elegendő <100MB napi loghoz)."""
    path = self._path
    try:
      size = path.stat().st_size
    except OSError:
      return []
    if size < self._offset:
      self._offset = 0
    if size <= self._offset:
      return []
    with path.open("rb") as fh:
      with mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ) as mm:
        chunk = mm[self._offset : size]
        self._offset = size
    return self._parse_chunk(chunk)
