"""CWFiltered PipeWire sink — GGMorse bemenet."""
from __future__ import annotations

import shutil
import subprocess

SINK_NAME = "CWFiltered"
CAPTURE_FS = 48_000


def ensure_filtered_sink(name: str = SINK_NAME) -> bool:
  if not shutil.which("pactl"):
    return False
  chk = subprocess.run(
    ["pactl", "list", "sinks", "short"],
    capture_output=True,
    text=True,
  )
  if name in (chk.stdout or ""):
    return True
  r = subprocess.run(
    [
      "pactl",
      "load-module",
      "module-null-sink",
      f"sink_name={name}",
      f"sink_properties=device.description={name}",
    ],
    capture_output=True,
    text=True,
  )
  return r.returncode == 0 or "exists" in (r.stderr or "").lower()
