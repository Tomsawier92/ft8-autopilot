"""Globális konfig — optimalizálható benchmark alap."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DiscoverConfig:
    fs: int = 12_000
    blocksize: int = 2048
    seg_len: int = 96
    embed_dim: int = 64
    # Klaszterezés (koszinusz távolság normalizált embeddingen)
    match_threshold: float = 0.72
    ema_alpha: float = 0.08
    min_strength: float = 0.0008
    # GPU
    use_cuda: bool = True
    use_amp: bool = True
    infer_batch_size: int = 64
    min_flush_segments: int = 1  # azonnali klaszterezés (ne várjon batchre)
    max_pending_segments: int = 256
    gpu_fraction: float = 0.35
    # Online tanulás (kontrasztív finomhangolás)
    train_enabled: bool = True
    train_batch: int = 64
    train_lr: float = 3e-4
    train_every_n_segments: int = 24
    max_prototypes: int = 512
    # Mentés (RAM → lemez ritkán)
    state_dir: str = ""  # üres = cw-discover/state
    save_min_interval_s: float = 90.0
    save_min_segments_delta: int = 400
    save_on_stop: bool = True
    # Alapgerinc (szintetikus ITU @ 10/15/20/25 WPM)
    load_backbone: bool = True
    backbone_path: str = ""  # üres = cw-discover/state/backbone.pt
    backbone_min_clusters: int = 8  # ennél kevesebb → backbone betöltés
    backbone_wpm: tuple[int, ...] = (10, 15, 20, 25)
    backbone_variants: int = 12
