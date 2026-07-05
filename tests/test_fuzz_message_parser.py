"""Hypothesis property-based fuzz — FT8 üzenet-parser (millió véletlen string)."""
from __future__ import annotations

import math
import re

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from cw_discover.ft8.decode_meta import (
  MSG_TYPES,
  classify_message_type,
  compass_bin,
  geo_for_message,
  grid_source_for_message,
  bearing_deg,
)
from cw_discover.ft8.grid_geo import (
  GRID4_RE,
  extract_callsigns_from_message,
  extract_grid_from_message,
  is_callsign,
)
from cw_discover.ft8.home_qth import DEFAULT_HOME

# --- Stratégiák ---

ft8_token = st.sampled_from(
  [
    "CQ",
    "DX",
    "DE",
    "QRZ",
    "TEST",
    "73",
    "RR73",
    "R",
    "RR",
    "RRR",
    "R-13",
    "R+05",
    "-12",
    "+03",
    "DL1ABC",
    "DA0WWA",
    "IN3IZQ",
    "SP9LS",
    "TM2WWA",
    "DH6MBR",
    "DL50CN",
    "JN56",
    "JN96",
    "JO40",
    "JO40fk",
    "<...>",
  ]
)

ft8_message = st.one_of(
  st.text(min_size=0, max_size=300),
  st.text(alphabet=st.characters(blacklist_categories=("Cs",)), min_size=0, max_size=200),
  st.lists(ft8_token, min_size=0, max_size=12).map(" ".join),
  st.lists(st.text(alphabet="A-Z0-9+-/", min_size=1, max_size=12), min_size=0, max_size=8).map(
    " ".join
  ),
)

latlon = st.floats(min_value=-90.0, max_value=90.0, allow_nan=False, allow_infinity=False)
lon = st.floats(min_value=-180.0, max_value=180.0, allow_nan=False, allow_infinity=False)


# --- Property tesztek ---


@given(msg=ft8_message)
def test_fuzz_classify_never_crashes(msg: str) -> None:
  t = classify_message_type(msg)
  assert t in MSG_TYPES


@given(msg=ft8_message)
def test_fuzz_classify_is_deterministic(msg: str) -> None:
  assert classify_message_type(msg) == classify_message_type(msg)


@given(msg=ft8_message)
def test_fuzz_extract_callsigns_never_crashes(msg: str) -> None:
  calls = extract_callsigns_from_message(msg)
  assert isinstance(calls, list)
  for c in calls:
    assert c == c.upper()
    assert is_callsign(c)


@given(msg=ft8_message)
def test_fuzz_extract_grid_never_crashes(msg: str) -> None:
  g = extract_grid_from_message(msg)
  if g is not None:
    assert len(g) == 4
    assert GRID4_RE.match(g) or re.match(r"^[A-R]{2}[0-9]{2}$", g)


@given(msg=ft8_message)
def test_fuzz_callsigns_never_include_grids(msg: str) -> None:
  for call in extract_callsigns_from_message(msg):
    assert not GRID4_RE.match(call)


@given(msg=ft8_message)
def test_fuzz_geo_for_message_never_crashes(msg: str) -> None:
  for home in (None, DEFAULT_HOME):
    geo = geo_for_message(msg, home)
    assert isinstance(geo, dict)
    assert "grid" in geo
    assert "compass" in geo
    if geo.get("azimuth_deg") is not None:
      assert 0 <= geo["azimuth_deg"] < 360


@given(msg=ft8_message)
def test_fuzz_grid_source_never_crashes(msg: str) -> None:
  g, src = grid_source_for_message(msg)
  assert src in ("message", "cache", "unknown")
  if g:
    assert len(g) >= 4


@given(lat1=latlon, lon1=lon, lat2=latlon, lon2=lon)
def test_fuzz_bearing_finite(lat1: float, lon1: float, lat2: float, lon2: float) -> None:
  az = bearing_deg(lat1, lon1, lat2, lon2)
  assert math.isfinite(az)
  assert 0 <= az < 360


@given(az=st.floats(allow_nan=False, allow_infinity=False))
def test_fuzz_compass_bin_never_crashes(az: float) -> None:
  b = compass_bin(az)
  assert b in ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


cq_message = st.lists(ft8_token, min_size=0, max_size=8).map(lambda ts: "CQ " + " ".join(ts))


@given(msg=cq_message)
def test_fuzz_cq_prefix_is_cq(msg: str) -> None:
  assert classify_message_type(msg) == "cq"


@given(tokens=st.lists(ft8_token, min_size=1, max_size=8))
def test_fuzz_realistic_token_messages(tokens: list[str]) -> None:
  msg = " ".join(tokens)
  classify_message_type(msg)
  extract_callsigns_from_message(msg)
  extract_grid_from_message(msg)
  geo_for_message(msg, DEFAULT_HOME)


# --- Profil: stressz futtatáskor külön marker ---

@pytest.mark.hypothesis_stress
@settings(max_examples=50_000)
@given(msg=st.text(min_size=0, max_size=500))
def test_fuzz_raw_text_stress(msg: str) -> None:
  """Tiszta véletlen Unicode — 50k példa stressz profilban."""
  classify_message_type(msg)
  extract_callsigns_from_message(msg)
  extract_grid_from_message(msg)
