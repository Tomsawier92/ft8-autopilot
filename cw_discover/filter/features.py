"""Spektrális jellemzők CW zajkapuhoz — PyTorch / CUDA."""
from __future__ import annotations

import torch
import torch.nn.functional as F


def stft_mag(x: torch.Tensor, n_fft: int = 256, hop: int = 64) -> torch.Tensor:
  """x: (B, T) → (B, F, T') magnitúdó."""
  if x.dim() == 1:
    x = x.unsqueeze(0)
  win = torch.hann_window(n_fft, device=x.device, dtype=x.dtype)
  spec = torch.stft(
    x,
    n_fft=n_fft,
    hop_length=hop,
    win_length=n_fft,
    window=win,
    return_complex=True,
  )
  return spec.abs().clamp_min(1e-8)


def tone_snr_db(mag: torch.Tensor, fs: float, f_lo: float = 350.0, f_hi: float = 2200.0) -> torch.Tensor:
  """Egy domináns tónus SNR-e a sávban (B,)."""
  b, f_bins, _ = mag.shape
  freqs = torch.linspace(0, fs / 2, f_bins, device=mag.device)
  band = (freqs >= f_lo) & (freqs <= f_hi)
  if not band.any():
    return torch.zeros(b, device=mag.device)
  m = mag[:, band, :].mean(dim=2)  # (B, Fb)
  peak, idx = m.max(dim=1)
  total = m.mean(dim=1).clamp_min(1e-8)
  snr = 10.0 * torch.log10((peak / total).clamp_min(1e-8))
  return snr


def spectral_flatness(mag: torch.Tensor, f_lo_hz: float, f_hi_hz: float, fs: float) -> torch.Tensor:
  """0 = tónusos (CW), 1 = zaj (B,)."""
  b, f_bins, _ = mag.shape
  freqs = torch.linspace(0, fs / 2, f_bins, device=mag.device)
  band = (freqs >= f_lo_hz) & (freqs <= f_hi_hz)
  m = mag[:, band, :].mean(dim=2).clamp_min(1e-8)
  geo = torch.exp(torch.mean(torch.log(m), dim=1))
  arith = torch.mean(m, dim=1)
  return (geo / arith).clamp(0, 1)
