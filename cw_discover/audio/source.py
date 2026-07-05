"""Felvételi forrás azonosító — Pulse monitor vagy sounddevice index."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CaptureSource:
  kind: str  # "pulse" | "sd"
  pulse_name: str | None = None
  sd_index: int | None = None

  def storage_key(self) -> str:
    if self.kind == "pulse" and self.pulse_name:
      return f"pulse:{self.pulse_name}"
    return f"sd:{self.sd_index}"

  @staticmethod
  def from_key(key: str) -> CaptureSource:
    if key.startswith("pulse:"):
      return CaptureSource(kind="pulse", pulse_name=key[6:])
    if key.startswith("sd:"):
      rest = key[3:]
      if rest in ("None", "default", ""):
        return CaptureSource(kind="sd", sd_index=None)
      return CaptureSource(kind="sd", sd_index=int(rest))
    return CaptureSource(kind="sd", sd_index=None)
