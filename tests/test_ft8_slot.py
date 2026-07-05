"""FT8 slot + protokoll tesztek."""
from __future__ import annotations

import calendar
import time

from cw_discover.ft8.ft8_slot import (
  decode_is_fresh,
  ft8_period_at,
  opposite_period,
  period_from_cycle,
  seconds_until_tx_period,
)


def test_period_from_cycle() -> None:
  assert period_from_cycle("260704_122000") == 0
  assert period_from_cycle("260704_122015") == 1
  assert period_from_cycle("260704_122030") == 0
  assert period_from_cycle("260704_122045") == 1


def test_opposite() -> None:
  assert opposite_period(0) == 1
  assert opposite_period(1) == 0


def test_seconds_until_tx_period() -> None:
  t = calendar.timegm(time.strptime("2026-07-04 12:23:17", "%Y-%m-%d %H:%M:%S"))
  assert ft8_period_at(t) == 1
  assert seconds_until_tx_period(0, t) == 13.0
  assert seconds_until_tx_period(1, t) == 0.0


def test_decode_fresh() -> None:
  now_cycle = time.strftime("%y%m%d_%H%M%S", time.gmtime())
  assert decode_is_fresh(now_cycle)
  assert not decode_is_fresh("260704_120000")
