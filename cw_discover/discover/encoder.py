"""Embedding CNN — CUDA, batch, AMP."""
from __future__ import annotations

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F


class PatternEncoder(nn.Module):
  def __init__(self, in_len: int = 96, dim: int = 64) -> None:
    super().__init__()
    self.dim = dim
    self.net = nn.Sequential(
      nn.Conv1d(1, 32, 7, padding=3),
      nn.BatchNorm1d(32),
      nn.ReLU(inplace=True),
      nn.MaxPool1d(2),
      nn.Conv1d(32, 64, 5, padding=2),
      nn.BatchNorm1d(64),
      nn.ReLU(inplace=True),
      nn.MaxPool1d(2),
      nn.Conv1d(64, 128, 5, padding=2),
      nn.BatchNorm1d(128),
      nn.ReLU(inplace=True),
      nn.AdaptiveAvgPool1d(1),
    )
    self.head = nn.Linear(128, dim)

  def forward(self, x: torch.Tensor) -> torch.Tensor:
    h = self.net(x).flatten(1)
    z = self.head(h)
    return F.normalize(z, dim=1)


class EncoderRuntime:
  def __init__(self, cfg) -> None:
    self.cfg = cfg
    self.device = torch.device(
      "cuda" if cfg.use_cuda and torch.cuda.is_available() else "cpu"
    )
    if self.device.type == "cuda":
      try:
        torch.cuda.set_per_process_memory_fraction(cfg.gpu_fraction, 0)
      except Exception:
        pass
      torch.backends.cudnn.benchmark = True
    self.model = PatternEncoder(cfg.seg_len, cfg.embed_dim).to(self.device)
    self._opt = torch.optim.AdamW(self.model.parameters(), lr=cfg.train_lr, weight_decay=1e-5)
    self._scaler = torch.amp.GradScaler("cuda", enabled=cfg.use_amp and self.device.type == "cuda")
    self._train_waves: list[np.ndarray] = []

  @torch.inference_mode()
  def encode_batch(self, waves: list) -> torch.Tensor:
    """waves: list of (96,) float32 → (N, dim) CPU tensor."""
    if not waves:
      return torch.empty(0, self.cfg.embed_dim)
    x = torch.from_numpy(np.stack(waves, axis=0)).unsqueeze(1).to(self.device, non_blocking=True)
    with torch.amp.autocast("cuda", enabled=self.cfg.use_amp and self.device.type == "cuda"):
      z = self.model(x)
    return z.float().cpu()

  def push_train_waves(self, waves: list[np.ndarray]) -> None:
    if not self.cfg.train_enabled:
      return
    self._train_waves.extend(waves)
    cap = self.cfg.train_batch * 8
    if len(self._train_waves) > cap:
      self._train_waves = self._train_waves[-cap:]

  def maybe_train_step(self, n_new: int) -> float | None:
    if not self.cfg.train_enabled or n_new < self.cfg.train_every_n_segments:
      return None
    if len(self._train_waves) < self.cfg.train_batch:
      return None
    import random

    idx = random.sample(range(len(self._train_waves)), self.cfg.train_batch)
    batch = np.stack([self._train_waves[i] for i in idx], axis=0)
    x = torch.from_numpy(batch).unsqueeze(1).to(self.device)
    x2 = x + torch.randn_like(x) * 0.04
    self.model.train()
    self._opt.zero_grad(set_to_none=True)
    with torch.amp.autocast("cuda", enabled=self.cfg.use_amp and self.device.type == "cuda"):
      z1 = self.model(x)
      z2 = self.model(x2)
      logits = (z1 @ z2.T) / 0.07
      labels = torch.arange(z1.size(0), device=self.device)
      loss = F.cross_entropy(logits, labels)
    self._scaler.scale(loss).backward()
    self._scaler.step(self._opt)
    self._scaler.update()
    self.model.eval()
    return float(loss.item())
