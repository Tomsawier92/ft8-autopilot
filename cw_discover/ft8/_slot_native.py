"""Opcionális natív FT8 slot timer — ctypes, fallback Python."""
from __future__ import annotations

import ctypes
import sys
from pathlib import Path

_LIB: ctypes.CDLL | None = None
_LIB_TRIED = False


def _lib_path() -> Path:
  return Path(__file__).resolve().parents[2] / "opt-lab" / "native" / "libslot_timer.so"


def _load() -> ctypes.CDLL | None:
  global _LIB, _LIB_TRIED
  if _LIB_TRIED:
    return _LIB
  _LIB_TRIED = True
  path = _lib_path()
  if not path.is_file():
    return None
  try:
    lib = ctypes.CDLL(str(path))
    lib.seconds_until_tx_period.argtypes = [ctypes.c_int, ctypes.c_double]
    lib.seconds_until_tx_period.restype = ctypes.c_double
    _LIB = lib
    return lib
  except OSError:
    return None


def seconds_until_tx_period_native(want: int, now: float) -> float | None:
  lib = _load()
  if lib is None:
    return None
  return float(lib.seconds_until_tx_period(int(want), float(now)))


def ensure_built() -> bool:
  """Fordítás gcc-vel ha hiányzik a .so."""
  so = _lib_path()
  if so.is_file():
    return True
  src = so.with_suffix(".c")
  if not src.is_file():
    src = Path(__file__).resolve().parents[2] / "opt-lab" / "native" / "slot_timer.c"
  if not src.is_file():
    return False
  import subprocess

  so.parent.mkdir(parents=True, exist_ok=True)
  cmd = ["gcc", "-shared", "-fPIC", "-O2", "-o", str(so), str(src), "-lm"]
  try:
    subprocess.run(cmd, check=True, capture_output=True)
    _LIB_TRIED = False
    return _load() is not None
  except (subprocess.CalledProcessError, FileNotFoundError):
    return False
