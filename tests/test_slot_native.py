"""Natív slot timer tesztek."""
from __future__ import annotations

from cw_discover.ft8._slot_native import ensure_built, seconds_until_tx_period_native
from cw_discover.ft8.ft8_slot import CYCLE_SECONDS, seconds_until_tx_period


def test_native_matches_python() -> None:
  if not ensure_built():
    return  # gcc hiány — skip csendben
  for want in (0, 1):
    for t in (1_700_000_000.0, 1_700_000_007.5, 1_700_000_015.0, 1_700_000_022.3):
      py = seconds_until_tx_period(want, t)
      # bypass native path: compute python ref manually
      p = int((t % 30) / 15)
      in_slot = t % CYCLE_SECONDS
      if p == want and in_slot <= 2.5:
        ref = 0.0
      elif p == want:
        ref = 30.0 - (t % 30)
      else:
        ref = CYCLE_SECONDS - in_slot
      nat = seconds_until_tx_period_native(want, t)
      assert nat is not None
      assert abs(nat - ref) < 1e-9
      assert abs(py - ref) < 1e-9


def test_seconds_until_bounds() -> None:
  d = seconds_until_tx_period(0, 1_700_000_000.0)
  assert 0.0 <= d <= 30.0
