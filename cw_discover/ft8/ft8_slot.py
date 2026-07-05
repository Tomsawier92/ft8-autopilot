"""FT8 páros/páratlan 15 s slot — WSJT-X even/odd periódus."""
from __future__ import annotations

import calendar
import time
from functools import lru_cache

from PyFT8.time_utils import global_time_utils

MAX_TX_START_SECONDS = 2.5
CYCLE_SECONDS = 15


def ft8_period_at(t: float | None = None) -> int:
  """0 = :00/:30 UTC, 1 = :15/:45 UTC (30 s párosítás)."""
  ts = time.time() if t is None else t
  return _ft8_period_cached(int(ts // 15))


@lru_cache(maxsize=4)
def _ft8_period_cached(half_bucket: int) -> int:
  return half_bucket % 2


def opposite_period(period: int) -> int:
  return 1 - (period & 1)


@lru_cache(maxsize=256)
def _cycle_start_timestamp(cycle: str) -> float | None:
  try:
    return float(calendar.timegm(time.strptime(cycle, "%y%m%d_%H%M%S")))
  except ValueError:
    return None


def cycle_start_timestamp(cycle: str) -> float:
  """PyFT8 cycle string → UTC epoch (ValueError ha érvénytelen)."""
  t = _cycle_start_timestamp(cycle.strip())
  if t is None:
    raise ValueError(f"invalid cycle: {cycle!r}")
  return t


def period_from_cycle(cycle: str) -> int:
  """cycle: PyFT8 'YYMMDD_HHMMSS' slot kezdet (UTC)."""
  c = cycle.strip()
  parsed = _period_from_valid_cycle(c)
  if parsed is not None:
    return parsed
  return global_time_utils.curr_cycle_from_time()


@lru_cache(maxsize=256)
def _period_from_valid_cycle(cycle: str) -> int | None:
  t = _cycle_start_timestamp(cycle)
  if t is None:
    return None
  return ft8_period_at(t)


def decode_age_seconds(cycle: str) -> float | None:
  return _decode_age_cached(cycle.strip(), int(time.time()))


@lru_cache(maxsize=512)
def _decode_age_cached(cycle: str, now_sec: int) -> float | None:
  t = _cycle_start_timestamp(cycle)
  if t is None:
    return None
  return float(now_sec) - t


@lru_cache(maxsize=128)
def _cycle_key_strftime(aligned: int) -> str:
  return time.strftime("%y%m%d_%H%M%S", time.gmtime(aligned))


def cycle_key_at(t: float | None = None) -> str:
  ts = time.time() if t is None else t
  aligned = int(ts) - int(ts) % 15
  return _cycle_key_strftime(aligned)


def tx_slot_id(period: int, t: float | None = None) -> str:
  """Egyedi kulcs a következő TX 15 s slotra (egy adás / slot)."""
  now = time.time() if t is None else t
  delay = seconds_until_tx_period(period, now)
  return cycle_key_at(now + delay + 0.05)


# Egy teljes FT8 periódus tolerancia: lassú feldolgozás / következő slot elején még elfogadható.
DECODE_FRESH_MAX_AGE = CYCLE_SECONDS * 2 + MAX_TX_START_SECONDS


def decode_is_fresh(cycle: str, max_age: float = DECODE_FRESH_MAX_AGE) -> bool:
  age = decode_age_seconds(cycle)
  return age is None or age <= max_age


def seconds_until_tx_period(want: int, t: float | None = None) -> float:
  """Másodperc a következő TX slot kezdetéig (want periódus, első 2.5 s ablak)."""
  now = time.time() if t is None else t
  try:
    from cw_discover.ft8._slot_native import seconds_until_tx_period_native

    native = seconds_until_tx_period_native(want, now)
    if native is not None:
      return native
  except ImportError:
    pass
  p = ft8_period_at(now)
  in_slot = now % CYCLE_SECONDS
  if p == want and in_slot <= MAX_TX_START_SECONDS:
    return 0.0
  if p == want:
    return 30.0 - (now % 30)
  return CYCLE_SECONDS - in_slot


def wait_for_tx_period(want: int) -> None:
  """Várakozás a saját FT8 slot elejére (WSJT-X TX even/odd).

  Adaptív: távolról 1 s lépések, közel 10 ms, utolsó 50 ms-ben 1 ms —
  pontosabb slot belépés kevesebb CPU-val mint busy-wait.
  """
  while True:
    delay = seconds_until_tx_period(want)
    if delay <= 0:
      return
    if delay > 1.0:
      time.sleep(min(delay - 0.05, 1.0))
    elif delay > 0.05:
      time.sleep(0.01)
    else:
      time.sleep(0.001)
