"""Propagation overlay — simítás és csillapítás."""
from __future__ import annotations

import math

from cw_discover.ft8.propagation_overlay import PropagationOverlay, destination_point, snr_weight


def test_destination_point_north() -> None:
  lat, lon = destination_point(46.9, 18.0, 0.0, 500.0)
  assert lat > 46.9
  assert abs(lon - 18.0) < 0.5


def test_overlay_decay_and_smooth() -> None:
  ov = PropagationOverlay(n_bins=8, decay_per_second=1.0)
  ov.note_azimuth(90.0, weight=10.0)
  before = float(ov._bins.sum())
  ov.tick(1.0)
  after = float(ov._bins.sum())
  assert after < before


def test_overlay_spreads_neighbor_bins() -> None:
  ov = PropagationOverlay(n_bins=8)
  ov.note_azimuth(0.0, weight=8.0)
  s = ov.smoothed()
  peak = int(s.argmax())
  assert s[peak] > s[(peak + 1) % 8]
  assert s[(peak + 1) % 8] > 0


def test_snr_weight_bounds() -> None:
  assert snr_weight(-30) >= 0.25
  assert snr_weight(10) <= 1.4


def test_wedge_specs_threshold() -> None:
  ov = PropagationOverlay(n_bins=16)
  ov.note_azimuth(45.0, weight=5.0)
  specs = ov.wedge_specs(min_strength=0.01)
  assert specs
  az, half, st = specs[0]
  assert 0 <= az < 360
  assert half > 0
  assert 0 < st <= 1.0
