"""PipeWire/Pulse bemenetek — pactl (monitor = böngésző/WebSDR hang)."""
from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class PulseSource:
  index: int
  name: str
  state: str
  sample_rate: int
  channels: int
  is_monitor: bool
  is_mic: bool

  @property
  def running(self) -> bool:
    return self.state.upper() == "RUNNING"


def _parse_pactl_line(line: str) -> PulseSource | None:
  line = line.strip()
  if not line or line.startswith("#"):
    return None
  parts = line.split("\t")
  if len(parts) < 2:
    return None
  try:
    idx = int(parts[0])
  except ValueError:
    return None
  name = parts[1]
  state = parts[-1] if len(parts) >= 5 else "UNKNOWN"
  fmt = parts[3] if len(parts) >= 4 else ""
  sr_m = re.search(r"(\d+)Hz", fmt)
  ch_m = re.search(r"(\d+)ch", fmt)
  sr = int(sr_m.group(1)) if sr_m else 48_000
  ch = int(ch_m.group(1)) if ch_m else 2
  nlow = name.lower()
  is_monitor = ".monitor" in nlow or nlow.endswith("_monitor") or "monitor" in nlow
  is_mic = (
    nlow.startswith("alsa_input.")
    or ".capture" in nlow
    or (not is_monitor and "input." in nlow and "monitor" not in nlow)
  )
  return PulseSource(
    index=idx,
    name=name,
    state=state,
    sample_rate=sr,
    channels=ch,
    is_monitor=is_monitor,
    is_mic=is_mic and not is_monitor,
  )


def list_pulse_sources() -> list[PulseSource]:
  if not shutil.which("pactl"):
    return []
  try:
    out = subprocess.run(
      ["pactl", "list", "sources", "short"],
      capture_output=True,
      text=True,
      timeout=5,
      check=False,
    )
  except Exception:
    return []
  if out.returncode != 0:
    return []
  items: list[PulseSource] = []
  for line in out.stdout.splitlines():
    src = _parse_pactl_line(line)
    if src is not None:
      items.append(src)
  return items


def pick_recommended_monitor(sources: list[PulseSource]) -> PulseSource | None:
  """WebSDR: futó hangkimenet monitorja (nem mikrofon)."""
  monitors = [s for s in sources if s.is_monitor and not s.is_mic]
  if not monitors:
    return None

  def score(s: PulseSource) -> tuple:
    n = s.name.lower()
    running = 0 if s.running else 1
    analog = 0 if "analog-stereo" in n else 1
    hdmi = 1 if "hdmi" in n else 0
    ggmorse = 1 if "ggmorse" in n else 0
    return (running, analog, hdmi, ggmorse, s.name)

  return min(monitors, key=score)
