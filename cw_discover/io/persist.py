"""RAM állapot + atomi, SSD-kímélő mentés."""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import torch

from cw_discover.paths import STATE_DIR as DEFAULT_STATE_DIR


@dataclass
class StatePaths:
  root: Path = DEFAULT_STATE_DIR
  state: Path = DEFAULT_STATE_DIR / "discover_state.pt"
  backbone: Path = DEFAULT_STATE_DIR / "backbone.pt"
  meta: Path = DEFAULT_STATE_DIR / "discover_meta.json"

  def ensure(self) -> None:
    self.root.mkdir(parents=True, exist_ok=True)


def atomic_save_state(blob: dict, path: Path) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".pt.tmp")
  os.close(fd)
  tmp_path = Path(tmp)
  try:
    torch.save(blob, tmp_path)
    os.replace(tmp_path, path)
  finally:
    if tmp_path.exists():
      tmp_path.unlink(missing_ok=True)


def atomic_save_meta(meta: dict, path: Path) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".json.tmp")
  try:
    with os.fdopen(fd, "w", encoding="utf-8") as f:
      json.dump(meta, f, ensure_ascii=False, indent=0)
    os.replace(tmp, path)
  except Exception:
    os.unlink(tmp)
    raise


def load_state(path: Path) -> dict | None:
  if not path.is_file():
    return None
  try:
    return torch.load(path, map_location="cpu", weights_only=False)
  except Exception:
    return None


def bank_to_dict(bank) -> dict:
  return {
    "match_threshold": bank.match_threshold,
    "ema_alpha": bank.ema_alpha,
    "max_prototypes": bank.max_prototypes,
    "prototypes": [p.numpy().tolist() for p in bank.prototypes],
    "counts": list(bank.counts),
    "strength_sum": list(bank.strength_sum),
    "labels": list(bank.labels),
    "total_segments": bank.total_segments,
    "new_clusters": bank.new_clusters,
  }


def bank_from_dict(d: dict, bank) -> None:
  import numpy as np

  bank.prototypes = [torch.tensor(p, dtype=torch.float32) for p in d.get("prototypes", [])]
  bank.counts = list(d.get("counts", []))
  bank.strength_sum = list(d.get("strength_sum", []))
  bank.labels = list(d.get("labels", []))
  bank.total_segments = int(d.get("total_segments", 0))
  bank.new_clusters = int(d.get("new_clusters", 0))
  bank.last_seen = [time.monotonic()] * len(bank.counts)


class PersistScheduler:
  """Csak RAM-ban dolgozik; lemezre ritkán, atomikusan."""

  def __init__(
    self,
    paths: StatePaths,
    min_interval_s: float = 90.0,
    min_segments_delta: int = 400,
  ) -> None:
    self.paths = paths
    self.min_interval_s = min_interval_s
    self.min_segments_delta = min_segments_delta
    self._dirty = False
    self._lock = threading.Lock()
    self._last_save = 0.0
    self._last_saved_segments = 0
    self._last_save_wall = 0.0
    self.last_save_message = ""

  @property
  def is_dirty(self) -> bool:
    with self._lock:
      return self._dirty

  def mark_dirty(self) -> None:
    with self._lock:
      self._dirty = True

  def maybe_save(self, build_blob, meta: dict) -> bool:
    with self._lock:
      if not self._dirty:
        return False
      now = time.monotonic()
      segs = int(meta.get("total_segments", 0))
      due_time = (now - self._last_save) >= self.min_interval_s
      due_segs = (segs - self._last_saved_segments) >= self.min_segments_delta
      if not due_time and not due_segs:
        return False
      self._dirty = False
    try:
      blob = build_blob()
      self.paths.ensure()
      atomic_save_state(blob, self.paths.state)
      meta["saved_at"] = time.time()
      atomic_save_meta(meta, self.paths.meta)
      with self._lock:
        self._last_save = time.monotonic()
        self._last_saved_segments = int(meta.get("total_segments", 0))
        self._last_save_wall = time.time()
        self.last_save_message = time.strftime("%H:%M:%S", time.localtime(self._last_save_wall))
      return True
    except Exception as e:
      with self._lock:
        self._dirty = True
      self.last_save_message = f"mentés hiba: {e}"
      return False

  def force_save(self, build_blob, meta: dict) -> bool:
    with self._lock:
      self._dirty = True
    return self.maybe_save(build_blob, meta)
