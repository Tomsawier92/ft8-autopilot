"""
Amatőr hívójel felismerés — WSJT-X 2.7 Radio.cpp logika (rugalmas, nem esik el).

Forrás: WSJT-X callsign_alphabet_re, valid_callsign_regexp, strict_standard_callsign_re,
non_prefix_suffix, base_callsign().

FT8 üzenetekben max ~11 karakter / mező; prefix/call/suffix: pl. VK9/N6TQS, N0CALL/P, E72PT/QRP.
"""
from __future__ import annotations

import re
from functools import lru_cache

# Maidenhead 4-char — nem hívójel (grid_geo-val azonos)
GRID4_RE = re.compile(r"^[A-R]{2}[0-9]{2}$", re.I)
REPORT_LIKE_RE = re.compile(r"^(R{1,3}|R[+-]?\d{1,2}|73|RR73|[+-]?\d{1,2})$", re.I)

# WSJT-X: ^[A-Z0-9/]{3,11}$
CALLSIGN_ALPHABET_RE = re.compile(r"^[A-Z0-9/]{3,11}$", re.I)
# Betű szomszédos számjeggyel (laza, de kiszűri a czak-betű szavakat)
LETTER_DIGIT_ADJACENT_RE = re.compile(r"\d[A-Z]|[A-Z]\d", re.I)
# Szigorú standard: ^([A-Z][0-9]?|[0-9A-Z][A-Z])[0-9][A-Z]{0,3}$
STANDARD_CALLSIGN_RE = re.compile(r"^([A-Z][0-9]?|[0-9A-Z][A-Z])[0-9][A-Z]{0,3}$", re.I)
# Ismert utótagok (nem DXCC prefix) — WSJT-X non_prefix_suffix
KNOWN_SUFFIX_RE = re.compile(
  r"^([0-9AMPQR]|QRP|F[DF]|[AM]M|L[HT]|LGT)$",
  re.I,
)

# CQ irányító szavak (nem hívójel) — WSJT-X + naplóból
CQ_MODIFIERS = frozenset(
  {
    "DX",
    "POTA",
    "SOTA",
    "ASIA",
    "EU",
    "EUROPE",
    "NA",
    "SA",
    "AF",
    "OC",
    "ANT",
    "WW",
    "WWA",
    "TEST",
    "QRP",
    "FIELD",
    "GAI",
    "SES",
    "USA",
    "UA",
    "AS",
    "US",
    "FF",
    "DE",
    "QRZ",
  }
)

_SKIP_TOKENS = frozenset({"CQ", "DX", "DE", "QRZ", "TEST", "RRR", "RR73", "73"})


def normalize_callsign(token: str) -> str:
  """Szögletes zárójel (hash) eltávolítása — WSJT-X <W1ABC/P>."""
  return _normalize_callsign_cached(token.strip())


@lru_cache(maxsize=8192)
def _normalize_callsign_cached(stripped: str) -> str:
  t = stripped.upper()
  if t.startswith("<") and t.endswith(">"):
    t = t[1:-1].strip()
  return t


def is_known_suffix(part: str) -> bool:
  """/P, /M, /QRP, /MM, /2 … — nem ország-prefix."""
  return bool(KNOWN_SUFFIX_RE.match(part.upper()))


def is_compound_callsign(call: str) -> bool:
  return "/" in normalize_callsign(call)


def is_standard_callsign(call: str) -> bool:
  c = normalize_callsign(call)
  if "/" in c:
    return False
  return bool(STANDARD_CALLSIGN_RE.match(c))


def base_callsign(call: str) -> str:
  """
  Alap hívójel prefix/call/suffix láncból.
  VK9/N6TQS → N6TQS; K1ABC/P → K1ABC; DL/EI3FW/P → EI3FW.
  """
  c = normalize_callsign(call)
  if "/" not in c:
    return c
  parts = [p for p in c.split("/") if p]
  if len(parts) == 1:
    return parts[0]
  while len(parts) > 1 and is_known_suffix(parts[-1]):
    parts.pop()
  if len(parts) == 1:
    return parts[0]
  if len(parts) == 2:
    left, right = parts[0], parts[1]
    if STANDARD_CALLSIGN_RE.match(right):
      return right
    if STANDARD_CALLSIGN_RE.match(left):
      return left
    return right if len(right) >= len(left) else left
  # 3+ rész: leghosszabb standard vagy letter-digit szegmens
  scored = sorted(
    parts,
    key=lambda p: (bool(STANDARD_CALLSIGN_RE.match(p)), len(p)),
    reverse=True,
  )
  return scored[0]


def split_callsign_suffixes(call: str) -> tuple[str, list[str]]:
  """Alap + / utótagok listája (pl. DL/EI3FW/P → EI3FW, ['P'])."""
  c = normalize_callsign(call)
  if "/" not in c:
    return c, []
  parts = [p for p in c.split("/") if p]
  if len(parts) == 1:
    return parts[0], []
  if len(parts) == 2:
    a, b = parts[0], parts[1]
    if is_known_suffix(b) or (len(b) <= 3 and b.isalnum()):
      base = a if STANDARD_CALLSIGN_RE.match(a) or len(a) >= len(b) else b
      if is_known_suffix(b):
        return base_callsign(f"{a}/{b}"), [b.upper()]
    return base_callsign(c), [b.upper()] if is_known_suffix(b) else []
  # Több slash: DL/EI3FW/P
  suffixes = [p.upper() for p in parts[1:] if is_known_suffix(p) or len(p) <= 4]
  return base_callsign(c), suffixes


def is_callsign_alphabet(token: str) -> bool:
  t = normalize_callsign(token)
  return bool(CALLSIGN_ALPHABET_RE.match(t))


def is_callsign(token: str) -> bool:
  """
  Rugalmas hívójel — WSJT-X laza szabály + FT8 hossz.
  Elfogad: IK4LZH, YR50NADIA, 4L/SP1MVG, E72PT/QRP, <VK9/P>.
  Elutasít: JN96, -09, GAI, CQ, LOUD1 (nincs betű-szám szomszédság).
  """
  return _is_callsign_cached(normalize_callsign(token))


@lru_cache(maxsize=8192)
def _is_callsign_cached(t: str) -> bool:
  if not t or t in _SKIP_TOKENS or t in CQ_MODIFIERS:
    return False
  if GRID4_RE.match(t):
    return False
  if REPORT_LIKE_RE.match(t):
    return False
  if not is_callsign_alphabet(t):
    return False
  if not LETTER_DIGIT_ADJACENT_RE.search(t.replace("/", "")):
    return False
  # Csak számok vagy csak betűk (grid-szerű)
  core = t.replace("/", "")
  if core.isdigit() or core.isalpha():
    return False
  return True


def is_cq_modifier(token: str) -> bool:
  """CQ DX / CQ GAI … — nem hívójel, hanem irányító szó."""
  return _is_cq_modifier_cached(token.upper().strip())


@lru_cache(maxsize=1024)
def _is_cq_modifier_cached(t: str) -> bool:
  if t in CQ_MODIFIERS:
    return True
  if is_callsign(t):
    return False
  # Rövid, számjegy nélküli token CQ után (pl. WWA, OH)
  return len(t) <= 4 and t.isalpha()


def valid_remote_call(call: str) -> bool:
  return _valid_remote_call_cached(normalize_callsign(call))


@lru_cache(maxsize=4096)
def _valid_remote_call_cached(t: str) -> bool:
  return bool(t) and t != "CQ" and _is_callsign_cached(t)
