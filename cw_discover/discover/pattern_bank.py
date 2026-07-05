"""Online prototípus bank — klaszterek számlálása."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np
import torch


@dataclass
class ClusterInfo:
  cluster_id: int
  count: int
  strength_avg: float
  last_seen: float
  label: str = ""

  def summary_line(self) -> str:
    age = time.monotonic() - self.last_seen
    lbl = f' "{self.label}"' if self.label else ""
    return (
      f"#{self.cluster_id:03d}  előfordulás={self.count:5d}  "
      f"erő={self.strength_avg:.3f}  utoljára={age:.0f}s{lbl}"
    )


@dataclass
class PatternBank:
  match_threshold: float
  ema_alpha: float
  max_prototypes: int
  prototypes: list[torch.Tensor] = field(default_factory=list)
  counts: list[int] = field(default_factory=list)
  strength_sum: list[float] = field(default_factory=list)
  last_seen: list[float] = field(default_factory=list)
  labels: list[str] = field(default_factory=list)
  total_segments: int = 0
  new_clusters: int = 0

  def assign_batch(self, z: torch.Tensor, strengths: list[float]) -> list[int]:
    n = z.size(0)
    if n == 0:
      return []
    if not self.prototypes:
      ids = [self._new(z[i].numpy(), strengths[i]) for i in range(n)]
      self.total_segments += n
      return ids
    P = torch.stack(self.prototypes)
    sims = z @ P.T
    best_sim, best_i = sims.max(dim=1)
    ids: list[int] = []
    for i in range(n):
      if float(best_sim[i]) >= self.match_threshold:
        idx = int(best_i[i])
        self._update(idx, z[i].numpy(), strengths[i])
        ids.append(idx)
      else:
        if len(self.prototypes) >= self.max_prototypes:
          worst = int(np.argmin(self.counts))
          self.prototypes[worst] = torch.from_numpy(z[i].numpy().astype(np.float32))
          self.counts[worst] = 1
          self.strength_sum[worst] = strengths[i]
          self.last_seen[worst] = time.monotonic()
          ids.append(worst)
        else:
          ids.append(self._new(z[i].numpy(), strengths[i]))
    self.total_segments += n
    return ids

  def _new(self, vec: np.ndarray, strength: float) -> int:
    self.prototypes.append(torch.from_numpy(vec.astype(np.float32)))
    self.counts.append(1)
    self.strength_sum.append(strength)
    self.last_seen.append(time.monotonic())
    self.labels.append("")
    self.new_clusters += 1
    return len(self.prototypes) - 1

  def _update(self, idx: int, vec: np.ndarray, strength: float) -> None:
    a = self.ema_alpha
    old = self.prototypes[idx].numpy()
    merged = (1.0 - a) * old + a * vec
    merged /= max(np.linalg.norm(merged), 1e-9)
    self.prototypes[idx] = torch.from_numpy(merged.astype(np.float32))
    self.counts[idx] += 1
    self.strength_sum[idx] += strength
    self.last_seen[idx] = time.monotonic()

  @property
  def n_clusters(self) -> int:
    return len(self.prototypes)

  def top_clusters(self, n: int = 40) -> list[ClusterInfo]:
    order = sorted(range(len(self.counts)), key=lambda i: -self.counts[i])[:n]
    out: list[ClusterInfo] = []
    for i in order:
      c = self.counts[i]
      out.append(
        ClusterInfo(
          cluster_id=i,
          count=c,
          strength_avg=self.strength_sum[i] / max(1, c),
          last_seen=self.last_seen[i],
          label=self.labels[i],
        )
      )
    return out

  def overview_text(self) -> str:
    lines = [
      f"Klaszterek száma: {self.n_clusters}",
      f"Feldolgozott szegmensek: {self.total_segments}",
      f"Új minták (összesen): {self.new_clusters}",
      "",
      "Leggyakoribb minták:",
    ]
    for info in self.top_clusters(25):
      lines.append("  " + info.summary_line())
    return "\n".join(lines)
