"""Hívójel-formátumok — WSJT-X kompatibilis, valós napló + ismert edge case."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from cw_discover.paths import LOG_DIR

from cw_discover.ft8.callsign import (
  base_callsign,
  is_callsign,
  is_compound_callsign,
  is_cq_modifier,
  is_known_suffix,
  is_standard_callsign,
  normalize_callsign,
  split_callsign_suffixes,
  valid_remote_call,
)
from cw_discover.ft8.ft8_protocol import message_triplet
from cw_discover.ft8.grid_geo import GRID4_RE, REPORT_RE, extract_callsigns_from_message

# --- Standard / regionális ---
STANDARD = [
  "IK4LZH",
  "N0CALL",
  "DL1ABC",
  "OK1MGM",
  "SP9JMZ",
  "W1AW",
  "K1ABC",
  "N2AB",
  "JA1ABC",
  "VK2ABC",
  "RA3FHK",
  "9A1A",
  "TC100N",
]

# --- Egyedi / special event (több számjegy) ---
SPECIAL_EVENT = [
  "YR50NADIA",
  "LY100RADIO",
  "OO26TRUDO",
  "VB3NAHIDA",
  "GB100MC",
  "YW18FIFA",
]

# --- Utótagok (portable, mobile, QRP, contest) ---
WITH_SUFFIX = [
  "N0CALL/P",
  "N0CALL/M",
  "N0CALL/MM",
  "N0CALL/QRP",
  "N0CALL/AM",
  "K1ABC/6",
  "W1AW/2",
  "3Z3GF/P",
  "HB9MOZ/P",
  "EA1YGM/R",
  "E72PT/QRP",
  "DJ2DL/QRP",
  "SMOZ1CTU/P",
]

# --- Összetett prefix/call (DX, /MM, kettős slash) ---
COMPOUND = [
  "4L/SP1MVG",
  "YS3/PY8WW",
  "SP/ER1SKI",
  "DL/EI3FW/P",
  "VK9/N6TQS",
  "PJ4/K1ABC",
  "F/W6YYY",
  "SV5/DJ9PC",
  "ZA/K1ABC",
  "K1ABC/P",
  "W9XYZ/3",
]

# --- Szögletes zárójel (hash decode visszatöltés) ---
BRACKETED = ["<W1ABC/P>", "<4L/SP1MVG>", "<YR50NADIA>"]

NOT_CALLSIGN = [
  "CQ",
  "DX",
  "GAI",
  "SES",
  "USA",
  "QRP",
  "JN96",
  "JO90",
  "RF76",
  "-09",
  "R-05",
  "RR73",
  "73",
  "AB",
  "TESTONLY",
]

SUFFIX_PARTS = ["P", "M", "MM", "AM", "QRP", "R", "2", "6", "Q", "A", "LGT", "LH"]


@pytest.mark.parametrize("call", STANDARD + SPECIAL_EVENT + WITH_SUFFIX + COMPOUND)
def test_callsign_accepted(call: str) -> None:
  assert is_callsign(call), call
  assert valid_remote_call(call), call


@pytest.mark.parametrize("call", BRACKETED)
def test_bracketed_callsign(call: str) -> None:
  assert is_callsign(call)
  assert normalize_callsign(call) == call.strip("<>").upper()


@pytest.mark.parametrize("token", NOT_CALLSIGN)
def test_not_callsign(token: str) -> None:
  assert not is_callsign(token), token


@pytest.mark.parametrize("suf", SUFFIX_PARTS)
def test_known_suffixes(suf: str) -> None:
  assert is_known_suffix(suf), suf


@pytest.mark.parametrize(
  "call,base",
  [
    ("K1ABC/P", "K1ABC"),
    ("VK9/N6TQS", "N6TQS"),
    ("4L/SP1MVG", "SP1MVG"),
    ("N0CALL/P", "N0CALL"),
    ("W1AW/2", "W1AW"),
    ("DL/EI3FW/P", "EI3FW"),
  ],
)
def test_base_callsign(call: str, base: str) -> None:
  assert base_callsign(call) == base


def test_compound_detection() -> None:
  assert is_compound_callsign("VK9/N6TQS")
  assert not is_compound_callsign("IK4LZH")


def test_standard_vs_special() -> None:
  assert is_standard_callsign("IK4LZH")
  assert not is_standard_callsign("YR50NADIA")
  assert is_standard_callsign("SP1MVG")
  assert not is_standard_callsign("4L/SP1MVG")  # összetett, nem standard mező


def test_split_suffixes() -> None:
  base, suf = split_callsign_suffixes("N0CALL/P")
  assert base == "N0CALL"
  assert "P" in suf


@pytest.mark.parametrize(
  "msg,call",
  [
    ("CQ IK4LZH JN54", "IK4LZH"),
    ("CQ DX IK4LZH JN54", "IK4LZH"),
    ("CQ GAI IZ0ZZV JN62", "IZ0ZZV"),
    ("CQ SES SQ8V KO01", "SQ8V"),
    ("CQ 4L/SP1MVG", "4L/SP1MVG"),
    ("CQ E72PT/QRP", "E72PT/QRP"),
    ("CQ LY100RADIO", "LY100RADIO"),
    ("CQ YS3/PY8WW RF76", "YS3/PY8WW"),
    ("IK4LZH N0CALL -09", "IK4LZH"),
    ("<VK9/N6TQS> N0CALL R-05", "VK9/N6TQS"),
  ],
)
def test_message_triplet_calls(msg: str, call: str) -> None:
  tri = message_triplet(msg)
  assert tri is not None
  fields = {normalize_callsign(tri.call_a), normalize_callsign(tri.call_b)}
  assert normalize_callsign(call) in fields
  assert valid_remote_call(call)


def test_cq_modifier_heuristic() -> None:
  assert is_cq_modifier("GAI")
  assert is_cq_modifier("WWA")
  assert not is_cq_modifier("IK4LZH")
  assert not is_cq_modifier("LY100RADIO")


def test_extract_callsigns_mixed() -> None:
  msg = "CQ DX YS3/PY8WW RF76"
  calls = extract_callsigns_from_message(msg)
  assert "YS3/PY8WW" in calls
  assert "RF76" not in calls  # grid


@pytest.mark.skipif(
  not LOG_DIR.exists(),
  reason="nincs FT8 napló",
)
def test_log_callsign_coverage_99pct() -> None:
  """5 nap valós dekód — 99%+ hívójel-szerű token elfogadva."""
  root = LOG_DIR
  total = ok = 0
  bad: list[str] = []
  for day in sorted(root.iterdir())[-5:]:
    p = day / "decodes.jsonl"
    if not p.exists():
      continue
    with p.open() as f:
      for line in f:
        msg = json.loads(line).get("message", "")
        for part in msg.split():
          t = part.upper().strip("<>")
          if len(t) < 3:
            continue
          if GRID4_RE.match(t) or REPORT_RE.match(t):
            continue
          if t in ("CQ", "DE", "QRZ", "73", "RR73", "RRR", "DX"):
            continue
          if not any(c.isalpha() for c in t) and "/" not in t:
            continue
          if not any(c.isdigit() for c in t) and "/" not in t:
            continue
          total += 1
          if is_callsign(part):
            ok += 1
          elif len(bad) < 20:
            bad.append(f"{t} in {msg[:50]}")
  assert total > 1000
  rate = ok / total
  assert rate >= 0.99, f"coverage {rate:.3%} failures e.g. {bad[:5]}"
