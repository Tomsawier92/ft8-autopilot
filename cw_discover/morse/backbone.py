"""Alapgerinc: szintetikus ITU minták → encoder + címkézett prototípus bank."""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

from cw_discover.config import DiscoverConfig
from cw_discover.discover.encoder import EncoderRuntime, PatternEncoder
from cw_discover.discover.pattern_bank import PatternBank
from cw_discover.io.persist import StatePaths, atomic_save_state, load_state
from cw_discover.morse.alphabet import MORSE_SYMBOLS, MorseSymbol
from cw_discover.morse.synth import symbol_to_segment

DEFAULT_WPM = (10, 15, 20, 25)


@dataclass
class BackboneSample:
  wave: np.ndarray
  class_id: int
  label: str
  wpm: int


def _class_label(sym: MorseSymbol, wpm: int) -> str:
  return f"{sym.key}@{wpm}wpm"


def build_dataset(
  wpm_list: tuple[int, ...] = DEFAULT_WPM,
  variants_per_key: int = 12,
  seg_len: int = 96,
  fs: float = 12_000.0,
  seed: int = 42,
) -> tuple[list[BackboneSample], dict[int, str]]:
  """Összes szimbólum × WPM × variáns → tanító minták."""
  rng = np.random.default_rng(seed)
  class_map: dict[int, str] = {}
  samples: list[BackboneSample] = []
  cid = 0
  for wpm in wpm_list:
    for sym in MORSE_SYMBOLS:
      label = _class_label(sym, wpm)
      class_map[cid] = label
      for v in range(variants_per_key):
        sub = np.random.default_rng(seed + cid * 1000 + v)
        wave = symbol_to_segment(sym, wpm, seg_len, fs, rng=sub)
        # variáns: enyhe idő/skála zaj
        if v % 3 == 1:
          src = np.linspace(0, 1, wave.size)
          dst = np.linspace(0, 1, max(4, int(wave.size * 0.92)))
          warped = np.interp(dst, src, wave)
          out_x = np.linspace(0, 1, seg_len)
          warped_x = np.linspace(0, 1, warped.size)
          wave = np.interp(out_x, warped_x, warped).astype(np.float32)
        elif v % 3 == 2:
          wave = (wave * float(rng.uniform(0.82, 1.0))).astype(np.float32)
          wave += rng.normal(0, 0.012, wave.size).astype(np.float32)
        samples.append(
          BackboneSample(wave=wave, class_id=cid, label=label, wpm=wpm)
        )
      cid += 1
  return samples, class_map


def _supcon_loss(z: torch.Tensor, labels: torch.Tensor, temp: float = 0.08) -> torch.Tensor:
  n = z.size(0)
  if n < 2:
    return z.sum() * 0.0
  sim = (z @ z.T) / temp
  sim = sim - sim.max(dim=1, keepdim=True).values.detach()
  labels = labels.view(-1, 1)
  mask_pos = (labels == labels.T).float()
  mask_pos.fill_diagonal_(0.0)
  self_mask = torch.eye(n, device=z.device)
  logits = sim - 1e9 * self_mask
  exp = torch.exp(logits)
  denom = exp.sum(dim=1).clamp_min(1e-9)
  pos = (exp * mask_pos).sum(dim=1)
  valid = mask_pos.sum(dim=1) > 0
  if not valid.any():
    return z.sum() * 0.0
  loss = -torch.log(pos[valid] / denom[valid] + 1e-9).mean()
  return loss


def train_encoder_on_backbone(
  encoder: EncoderRuntime,
  samples: list[BackboneSample],
  epochs: int = 35,
  batch_size: int = 128,
) -> list[float]:
  """Felügyelt kontrasztív finomhangolás a szintetikus mintákon."""
  device = encoder.device
  model = encoder.model
  opt = encoder._opt
  scaler = encoder._scaler
  cfg = encoder.cfg
  waves = np.stack([s.wave for s in samples], axis=0)
  labels = np.array([s.class_id for s in samples], dtype=np.int64)
  n = waves.shape[0]
  losses: list[float] = []
  model.train()
  for ep in range(epochs):
    perm = np.random.permutation(n)
    ep_loss = 0.0
    steps = 0
    for start in range(0, n, batch_size):
      idx = perm[start : start + batch_size]
      if idx.size < 4:
        continue
      x = torch.from_numpy(waves[idx]).unsqueeze(1).to(device)
      y = torch.from_numpy(labels[idx]).to(device)
      x2 = x + torch.randn_like(x) * 0.035
      opt.zero_grad(set_to_none=True)
      with torch.amp.autocast("cuda", enabled=cfg.use_amp and device.type == "cuda"):
        z1 = model(x)
        z2 = model(x2)
        loss = _supcon_loss(z1, y) + 0.35 * _supcon_loss(z2, y)
      scaler.scale(loss).backward()
      scaler.step(opt)
      scaler.update()
      ep_loss += float(loss.item())
      steps += 1
    if steps:
      losses.append(ep_loss / steps)
  model.eval()
  return losses


def seed_bank_from_backbone(
  bank: PatternBank,
  encoder: EncoderRuntime,
  samples: list[BackboneSample],
  class_map: dict[int, str],
) -> int:
  """Egy prototípus / (szimbólum, WPM) — címkézve."""
  bank.prototypes.clear()
  bank.counts.clear()
  bank.strength_sum.clear()
  bank.labels.clear()
  bank.last_seen.clear()
  bank.total_segments = 0
  bank.new_clusters = 0

  by_class: dict[int, list[np.ndarray]] = {}
  for s in samples:
    by_class.setdefault(s.class_id, []).append(s.wave)

  waves: list[np.ndarray] = []
  labels: list[str] = []
  for cid, label in sorted(class_map.items()):
    chunk = by_class.get(cid, [])
    if not chunk:
      continue
    waves.append(chunk[len(chunk) // 2])
    labels.append(label)

  if not waves:
    return 0
  z = encoder.encode_batch(waves)
  now = time.monotonic()
  for i, label in enumerate(labels):
    vec = z[i].numpy()
    bank.prototypes.append(torch.from_numpy(vec.astype(np.float32)))
    bank.counts.append(1)
    bank.strength_sum.append(1.0)
    bank.labels.append(label)
    bank.last_seen.append(now)
    bank.new_clusters += 1
  bank.total_segments = len(labels)
  return len(labels)


def build_backbone_blob(
  encoder: EncoderRuntime,
  bank: PatternBank,
  class_map: dict[int, str],
  wpm_list: tuple[int, ...],
  variants_per_key: int,
) -> dict:
  from cw_discover.io.persist import bank_to_dict

  return {
    "version": 2,
    "kind": "backbone",
    "created_at": time.time(),
    "wpm_list": list(wpm_list),
    "variants_per_key": variants_per_key,
    "n_symbols": len(MORSE_SYMBOLS),
    "n_classes": len(class_map),
    "class_map": class_map,
    "encoder": encoder.model.state_dict(),
    "bank": bank_to_dict(bank),
    "total_segments": bank.total_segments,
    "n_clusters": bank.n_clusters,
  }


def train_and_save_backbone(
  cfg: DiscoverConfig | None = None,
  *,
  wpm_list: tuple[int, ...] = DEFAULT_WPM,
  variants_per_key: int = 12,
  epochs: int = 35,
  out_path: Path | None = None,
) -> Path:
  cfg = cfg or DiscoverConfig()
  paths = StatePaths(
    root=Path(cfg.state_dir).expanduser() if cfg.state_dir else StatePaths().root
  )
  out = out_path or paths.backbone
  paths.ensure()

  samples, class_map = build_dataset(
    wpm_list=wpm_list,
    variants_per_key=variants_per_key,
    seg_len=cfg.seg_len,
    fs=float(cfg.fs),
  )
  encoder = EncoderRuntime(cfg)
  bank = PatternBank(
    match_threshold=cfg.match_threshold,
    ema_alpha=cfg.ema_alpha,
    max_prototypes=cfg.max_prototypes,
  )

  losses = train_encoder_on_backbone(encoder, samples, epochs=epochs)
  n_proto = seed_bank_from_backbone(bank, encoder, samples, class_map)
  blob = build_backbone_blob(encoder, bank, class_map, wpm_list, variants_per_key)
  blob["train_loss_last"] = losses[-1] if losses else None
  atomic_save_state(blob, out)
  return out


def apply_backbone_state(
  encoder: EncoderRuntime,
  bank: PatternBank,
  path: Path,
  *,
  merge: bool = True,
) -> str:
  """Encoder + bank betöltése backbone fájlból."""
  blob = load_state(path)
  if not blob or blob.get("kind") != "backbone":
    return "backbone: nincs érvényes fájl"
  try:
    encoder.model.load_state_dict(blob["encoder"])
    if merge and bank.n_clusters > 0:
      return f"backbone: encoder frissítve, bank megtartva ({bank.n_clusters} klaszter)"
    from cw_discover.io.persist import bank_from_dict

    bank_from_dict(blob["bank"], bank)
    return f"backbone: {bank.n_clusters} prototípus betöltve"
  except Exception as e:
    return f"backbone hiba: {e}"
