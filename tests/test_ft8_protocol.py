"""FT8 protokoll helper tesztek."""
from __future__ import annotations

from cw_discover.ft8.ft8_protocol import (
  is_73,
  is_grid_token,
  is_report,
  is_rr73,
  message_triplet,
)


def test_cq_triplet() -> None:
  t = message_triplet("CQ IK4LZH JN54")
  assert t is not None
  assert t.is_cq
  assert t.call_b == "IK4LZH"
  assert t.third == "JN54"


def test_cq_dx_triplet() -> None:
  t = message_triplet("CQ DX DA0WWA JN68")
  assert t is not None
  assert t.call_b == "DA0WWA"


def test_qso_triplet() -> None:
  t = message_triplet("IK4LZH N0CALL -12")
  assert t is not None
  assert t.call_a == "IK4LZH"
  assert t.call_b == "N0CALL"
  assert is_report(t.third)


def test_grid_token() -> None:
  assert is_grid_token("JN54")
  assert not is_grid_token("-12")
  assert is_rr73("RR73")
  assert is_73("73")
