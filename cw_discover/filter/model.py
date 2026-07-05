"""Kis CNN: CW adás vs. tiszta zaj / véletlen csippanások."""
from __future__ import annotations

import torch
import torch.nn as nn

from cw_discover.filter.features import spectral_flatness, stft_mag, tone_snr_db


class CwGateNet(nn.Module):
  """Spektrogram → P(CW adás)."""

  def __init__(self, n_fft: int = 256) -> None:
    super().__init__()
    self.n_fft = n_fft
    self.cnn = nn.Sequential(
      nn.Conv2d(1, 16, 3, padding=1),
      nn.BatchNorm2d(16),
      nn.ReLU(inplace=True),
      nn.MaxPool2d(2),
      nn.Conv2d(16, 32, 3, padding=1),
      nn.BatchNorm2d(32),
      nn.ReLU(inplace=True),
      nn.MaxPool2d(2),
      nn.Conv2d(32, 64, 3, padding=1),
      nn.BatchNorm2d(64),
      nn.ReLU(inplace=True),
      nn.AdaptiveAvgPool2d(1),
    )
    self.head = nn.Sequential(
      nn.Linear(64 + 2, 32),
      nn.ReLU(inplace=True),
      nn.Linear(32, 1),
    )

  def forward(self, x: torch.Tensor, fs: float = 12_000.0) -> torch.Tensor:
    mag = stft_mag(x, self.n_fft)
    logm = torch.log1p(mag)
    h = self.cnn(logm.unsqueeze(1)).flatten(1)
    snr = tone_snr_db(mag, fs).unsqueeze(1) / 20.0
    flat = spectral_flatness(mag, 400, 2000, fs).unsqueeze(1)
    feat = torch.cat([h, snr, 1.0 - flat], dim=1)
    return self.head(feat).squeeze(1)
