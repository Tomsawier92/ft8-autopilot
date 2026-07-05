"""CUDA CW zajkapu — csak „szép” morze mehet át (histerézis + SNR)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

from cw_discover.filter.features import spectral_flatness, stft_mag, tone_snr_db
from cw_discover.filter.model import CwGateNet

from cw_discover.paths import STATE_DIR

DEFAULT_GATE_PATH = STATE_DIR / "cw_gate.pt"


@dataclass
class GateConfig:
  fs: int = 12_000
  frame_ms: float = 80.0
  open_threshold: float = 0.62
  close_threshold: float = 0.42
  min_snr_db: float = 4.0
  max_flatness: float = 0.55
  attack_ms: float = 25.0
  release_ms: float = 180.0
  use_cuda: bool = True


class CwNoiseGate:
  """
  Hibrid kapu: neurális P(CW) + spektrális SNR + tónusság.
  Zárt állapotban csend (GGMorse nem ír random betűket).
  """

  def __init__(self, cfg: GateConfig | None = None, weights_path: Path | None = None) -> None:
    self.cfg = cfg or GateConfig()
    self.device = torch.device(
      "cuda" if self.cfg.use_cuda and torch.cuda.is_available() else "cpu"
    )
    self.model = CwGateNet().to(self.device)
    self.model.eval()
    self._open = False
    self._gain = 0.0
    self._buf = np.zeros(0, dtype=np.float32)
    self._frame = max(256, int(self.cfg.fs * self.cfg.frame_ms / 1000.0))
    path = weights_path or DEFAULT_GATE_PATH
    if path.is_file():
      self._load_weights(path)

  def _load_weights(self, path: Path) -> None:
    try:
      blob = torch.load(path, map_location=self.device, weights_only=False)
      if isinstance(blob, dict) and "model" in blob:
        self.model.load_state_dict(blob["model"])
    except Exception:
      pass

  @torch.inference_mode()
  def _score_frame(self, frame: np.ndarray) -> tuple[float, float, float]:
    x = torch.from_numpy(frame.astype(np.float32)).to(self.device)
    if x.numel() < 256:
      return 0.0, 0.0, 1.0
    logit = self.model(x.unsqueeze(0), float(self.cfg.fs))
    p = float(torch.sigmoid(logit).item())
    mag = stft_mag(x.unsqueeze(0))
    snr = float(tone_snr_db(mag, float(self.cfg.fs)).item())
    flat = float(spectral_flatness(mag, 400, 2000, float(self.cfg.fs)).item())
    return p, snr, flat

  def _heuristic_score(self, frame: np.ndarray) -> tuple[float, float, float]:
    x = torch.from_numpy(frame.astype(np.float32)).to(self.device).unsqueeze(0)
    if x.size(1) < 256:
      return 0.0, 0.0, 1.0
    mag = stft_mag(x)
    snr = float(tone_snr_db(mag, float(self.cfg.fs)).item())
    flat = float(spectral_flatness(mag, 400, 2000, float(self.cfg.fs)).item())
    snr_ok = np.clip((snr - 2.0) / 12.0, 0, 1)
    flat_ok = np.clip((0.65 - flat) / 0.45, 0, 1)
    p = float(0.55 * snr_ok + 0.45 * flat_ok)
    return p, snr, flat

  def process_chunk(self, chunk: np.ndarray) -> tuple[np.ndarray, dict]:
    """chunk float32 mono @ cfg.fs → szűrt chunk + meta."""
    chunk = np.asarray(chunk, dtype=np.float32).ravel()
    if chunk.size == 0:
      return chunk, {"open": self._open, "gain": self._gain}

    self._buf = np.concatenate([self._buf, chunk]) if self._buf.size else chunk.copy()
    out_parts: list[np.ndarray] = []
    meta = {"p": 0.0, "snr": 0.0, "flat": 1.0, "open": False, "gain": 0.0}

    while self._buf.size >= self._frame:
      frame = self._buf[: self._frame]
      self._buf = self._buf[self._frame :]

      try:
        p, snr, flat = self._score_frame(frame)
      except Exception:
        p, snr, flat = self._heuristic_score(frame)

      want_open = (
        p >= self.cfg.open_threshold
        and snr >= self.cfg.min_snr_db
        and flat <= self.cfg.max_flatness
      )
      want_close = (
        p < self.cfg.close_threshold
        or snr < self.cfg.min_snr_db - 2.0
        or flat > self.cfg.max_flatness + 0.12
      )

      if self._open:
        if want_close:
          self._open = False
      elif want_open:
        self._open = True

      target = 1.0 if self._open else 0.0
      if self._open and not want_open and not want_close:
        target = 0.85

      attack = max(1e-6, self.cfg.attack_ms / 1000.0)
      release = max(1e-6, self.cfg.release_ms / 1000.0)
      tau = attack if target > self._gain else release
      alpha = 1.0 - np.exp(-self._frame / (tau * self.cfg.fs))
      self._gain = float(self._gain + alpha * (target - self._gain))
      self._gain = float(np.clip(self._gain, 0.0, 1.0))

      out_parts.append((frame * self._gain).astype(np.float32))
      meta = {
        "p": p,
        "snr": snr,
        "flat": flat,
        "open": self._open,
        "gain": self._gain,
      }

    if not out_parts:
      return np.zeros(0, dtype=np.float32), meta
    return np.concatenate(out_parts), meta
