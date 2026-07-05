"""Folyamatos line-in mintafelismerő motor."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from cw_discover.audio.capture import open_capture
from cw_discover.audio.devices import default_capture_source, source_label
from cw_discover.audio.source import CaptureSource
from cw_discover.audio.process import signal_strong_enough
from cw_discover.config import DiscoverConfig
from cw_discover.discover.encoder import EncoderRuntime
from cw_discover.discover.pattern_bank import PatternBank
from cw_discover.discover.segment import RawSegment, SegmentExtractor
from cw_discover.io.persist import (
  PersistScheduler,
  StatePaths,
  bank_from_dict,
  bank_to_dict,
  load_state,
)


@dataclass
class EngineStats:
  running: bool = False
  n_clusters: int = 0
  total_segments: int = 0
  segments_per_sec: float = 0.0
  infer_ms: float = 0.0
  train_loss: float | None = None
  device: str = "cpu"
  input_label: str = "—"
  overview: str = ""
  error: str = ""
  last_save: str = "—"
  dirty: bool = False
  scope_rms: float = 0.0
  scope_active: bool = False
  chunks_received: int = 0
  pending_segments: int = 0
  segments_emitted: int = 0


class DiscoveryEngine:
  def __init__(self, cfg: DiscoverConfig | None = None) -> None:
    self.cfg = cfg or DiscoverConfig()
    self.stats = EngineStats()
    self.bank = PatternBank(
      match_threshold=self.cfg.match_threshold,
      ema_alpha=self.cfg.ema_alpha,
      max_prototypes=self.cfg.max_prototypes,
    )
    self.encoder = EncoderRuntime(self.cfg)
    self.extractor = SegmentExtractor(self.cfg.fs, self.cfg.min_strength)
    root = Path(self.cfg.state_dir).expanduser() if self.cfg.state_dir else StatePaths().root
    self._paths = StatePaths(root=root)
    self._persist = PersistScheduler(
      self._paths,
      min_interval_s=self.cfg.save_min_interval_s,
      min_segments_delta=self.cfg.save_min_segments_delta,
    )
    self._capture = None
    self._input_source: CaptureSource | None = None
    self._cap_lock = threading.Lock()
    self._thread: threading.Thread | None = None
    self._stop = threading.Event()
    self._pending: list[RawSegment] = []
    self._lock = threading.Lock()
    self._seg_counter = 0
    self._last_seg_t = time.monotonic()
    self._sps = 0.0
    self._segments_emitted = 0
    self._last_flush_t = time.monotonic()
    self._scope_lock = threading.Lock()
    self._scope_len = int(self.cfg.fs * 0.25)
    self._scope_buf = np.zeros(self._scope_len, dtype=np.float32)
    self._scope_rms = 0.0
    self._scope_active = False
    self._chunks_received = 0
    self._load_checkpoint()
    self._ensure_backbone()

  @property
  def state_path(self) -> Path:
    return self._paths.state

  def _build_blob(self) -> dict:
    return {
      "version": 1,
      "cfg": {
        "embed_dim": self.cfg.embed_dim,
        "seg_len": self.cfg.seg_len,
        "match_threshold": self.cfg.match_threshold,
      },
      "encoder": self.encoder.model.state_dict(),
      "bank": bank_to_dict(self.bank),
      "total_segments": self.bank.total_segments,
      "n_clusters": self.bank.n_clusters,
    }

  def _meta(self) -> dict:
    return {
      "total_segments": self.bank.total_segments,
      "n_clusters": self.bank.n_clusters,
      "input_source": self._input_source.storage_key() if self._input_source else None,
      "input_label": self.stats.input_label,
    }

  def _load_checkpoint(self) -> None:
    blob = load_state(self._paths.state)
    if not blob:
      return
    try:
      self.encoder.model.load_state_dict(blob["encoder"])
      if "bank" in blob:
        bank_from_dict(blob["bank"], self.bank)
      self.stats.last_save = "betöltve"
      self._persist._last_saved_segments = self.bank.total_segments
    except Exception:
      pass

  def _backbone_path(self) -> Path:
    if self.cfg.backbone_path:
      return Path(self.cfg.backbone_path).expanduser()
    return self._paths.backbone

  def _ensure_backbone(self) -> None:
    if not self.cfg.load_backbone:
      return
    if self.bank.n_clusters >= self.cfg.backbone_min_clusters:
      return
    path = self._backbone_path()
    if not path.is_file():
      self.stats.overview = (
        "Alapgerinc még nincs. Futtasd: python scripts/train_backbone.py\n"
        "Ez legenerálja az összes betűt/számot/prosignt @ 10–25 WPM-en."
      )
      return
    from cw_discover.morse.backbone import apply_backbone_state

    # Gyenge / üres live bank → teljes gerinc; erős live → csak encoder
    merge = self.bank.n_clusters >= self.cfg.backbone_min_clusters
    msg = apply_backbone_state(
      self.encoder,
      self.bank,
      path,
      merge=merge,
    )
    self.stats.last_save = msg
    self._refresh_stats()

  def start(self, source: CaptureSource | None = None) -> None:
    if source is None:
      source = default_capture_source()
    if self._thread and self._thread.is_alive():
      self.swap_input(source)
      return
    self._input_source = source
    self.stats.input_label = source_label(source)
    self._stop.clear()
    self._open_capture(source)
    self.stats.running = True
    self.stats.device = str(self.encoder.device)
    self.stats.error = ""
    self._thread = threading.Thread(target=self._loop, daemon=True)
    self._thread.start()

  def swap_input(self, source: CaptureSource | None) -> None:
    """Forrás váltás tanítás közben — rövid szünet a felvételben."""
    if source is None:
      source = default_capture_source()
    with self._cap_lock:
      self._input_source = source
      self.stats.input_label = source_label(source)
      if self._capture:
        self._capture.stop()
        self._capture = None
      if self.stats.running and not self._stop.is_set():
        self._open_capture(source)

  def _open_capture(self, source: CaptureSource) -> None:
    self._capture = open_capture(self.cfg.fs, self.cfg.blocksize, source)
    self._capture.start()

  def stop(self) -> None:
    self._stop.set()
    with self._cap_lock:
      if self._capture:
        self._capture.stop()
        self._capture = None
    if self.cfg.save_on_stop:
      self._persist.force_save(self._build_blob, self._meta())
    self.stats.running = False

  def refresh_devices_hint(self) -> str:
    return source_label(self._input_source)

  def get_scope_snapshot(self) -> tuple[np.ndarray, float, bool]:
    with self._scope_lock:
      return self._scope_buf.copy(), self._scope_rms, self._scope_active

  def _push_scope(self, chunk: np.ndarray) -> None:
    chunk = np.asarray(chunk, dtype=np.float32).ravel()
    n = chunk.size
    if n <= 0:
      return
    self._chunks_received += 1
    rms = float(np.sqrt(np.mean(chunk * chunk) + 1e-18))
    active = signal_strong_enough(chunk, self.cfg.min_strength)
    with self._scope_lock:
      if n >= self._scope_len:
        self._scope_buf[:] = chunk[-self._scope_len :]
      else:
        self._scope_buf = np.roll(self._scope_buf, -n)
        self._scope_buf[-n:] = chunk
      self._scope_rms = rms
      self._scope_active = active
    self.stats.scope_rms = rms
    self.stats.scope_active = active
    self.stats.chunks_received = self._chunks_received

  def _loop(self) -> None:
    while not self._stop.is_set():
      with self._cap_lock:
        cap = self._capture
      if cap is None:
        time.sleep(0.05)
        continue
      chunk = cap.read(timeout=0.05)
      if chunk is None:
        continue
      self._push_scope(chunk)
      try:
        for seg in self.extractor.feed(chunk):
          with self._lock:
            self._pending.append(seg)
            self._segments_emitted += 1
            if len(self._pending) >= self.cfg.max_pending_segments:
              self._pending = self._pending[-self.cfg.max_pending_segments :]
        self._flush_pending()
        if time.monotonic() - self._last_flush_t >= 2.0:
          self._flush_pending(force=True)
          self._last_flush_t = time.monotonic()
        self._refresh_stats()
        self._persist.maybe_save(self._build_blob, self._meta())
      except Exception as e:
        self.stats.error = str(e)
    self._flush_pending(force=True)

  def _flush_pending(self, force: bool = False) -> None:
    with self._lock:
      if not self._pending:
        return
      min_n = max(1, self.cfg.min_flush_segments)
      if not force and len(self._pending) < min_n:
        return
      batch = self._pending[: self.cfg.infer_batch_size]
      self._pending = self._pending[len(batch) :]

    waves = [s.waveform for s in batch]
    strengths = [s.strength for s in batch]
    t0 = time.perf_counter()
    z = self.encoder.encode_batch(waves)
    self.stats.infer_ms = (time.perf_counter() - t0) * 1000.0
    self.bank.assign_batch(z, strengths)
    self.encoder.push_train_waves(waves)
    loss = self.encoder.maybe_train_step(len(batch))
    if loss is not None:
      self.stats.train_loss = loss
    self._persist.mark_dirty()
    self._seg_counter += len(batch)
    now = time.monotonic()
    dt = now - self._last_seg_t
    if dt >= 1.0:
      self._sps = self._seg_counter / dt
      self._seg_counter = 0
      self._last_seg_t = now

  def _refresh_stats(self) -> None:
    with self._lock:
      self.stats.pending_segments = len(self._pending)
    self.stats.segments_emitted = self._segments_emitted
    self.stats.n_clusters = self.bank.n_clusters
    self.stats.total_segments = self.bank.total_segments
    self.stats.segments_per_sec = self._sps
    self.stats.overview = self.bank.overview_text()
    self.stats.last_save = self._persist.last_save_message or self.stats.last_save
    self.stats.dirty = self._persist.is_dirty
