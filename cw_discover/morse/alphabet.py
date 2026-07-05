"""ITU nemzetközi morze — betűk, számok, írásjelek, prosignok."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MorseSymbol:
  key: str
  code: str
  kind: str  # letter | digit | punct | prosign
  prosign: bool = False

  @property
  def label(self) -> str:
    return self.key


def _sym(key: str, code: str, kind: str, prosign: bool = False) -> MorseSymbol:
  return MorseSymbol(key=key, code=code, kind=kind, prosign=prosign)


# —— Betűk ——
_LETTERS = [
  _sym("A", ".-", "letter"),
  _sym("B", "-...", "letter"),
  _sym("C", "-.-.", "letter"),
  _sym("D", "-..", "letter"),
  _sym("E", ".", "letter"),
  _sym("F", "..-.", "letter"),
  _sym("G", "--.", "letter"),
  _sym("H", "....", "letter"),
  _sym("I", "..", "letter"),
  _sym("J", ".---", "letter"),
  _sym("K", "-.-", "letter"),
  _sym("L", ".-..", "letter"),
  _sym("M", "--", "letter"),
  _sym("N", "-.", "letter"),
  _sym("O", "---", "letter"),
  _sym("P", ".--.", "letter"),
  _sym("Q", "--.-", "letter"),
  _sym("R", ".-.", "letter"),
  _sym("S", "...", "letter"),
  _sym("T", "-", "letter"),
  _sym("U", "..-", "letter"),
  _sym("V", "...-", "letter"),
  _sym("W", ".--", "letter"),
  _sym("X", "-..-", "letter"),
  _sym("Y", "-.--", "letter"),
  _sym("Z", "--..", "letter"),
]

# —— Számok ——
_DIGITS = [_sym(str(d), code, "digit") for d, code in [
  ("0", "-----"), ("1", ".----"), ("2", "..---"), ("3", "...--"), ("4", "....-"),
  ("5", "....."), ("6", "-...."), ("7", "--..."), ("8", "---.."), ("9", "----."),
]]

# —— Írásjelek / speciális ——
_PUNCT = [
  _sym(".", ".-.-.-", "punct"),
  _sym(",", "--..--", "punct"),
  _sym("?", "..--..", "punct"),
  _sym("'", ".----.", "punct"),
  _sym("!", "-.-.--", "punct"),
  _sym("/", "-..-.", "punct"),
  _sym("(", "-.--.", "punct"),
  _sym(")", "-.--.-", "punct"),
  _sym("&", ".-...", "punct"),
  _sym(":", "---...", "punct"),
  _sym(";", "-.-.-.", "punct"),
  _sym("=", "-...-", "punct"),
  _sym("+", ".-.-.", "punct"),
  _sym("-", "-....-", "punct"),
  _sym("_", "..--.-", "punct"),
  _sym('"', ".-..-.", "punct"),
  _sym("$", "...-..-", "punct"),
  _sym("@", ".--.-.", "punct"),
]

# —— Prosignok (egységként, betűköz nélkül) ——
_PROSIGNS = [
  _sym("<AR>", ".-.-.", "prosign", True),       # üzenet vége
  _sym("<AS>", ".-...", "prosign", True),       # várakozás
  _sym("<SK>", ".-.-.-", "prosign", True),      # kapcsolás vége
  _sym("<KN>", "-.-.", "prosign", True),        # csak neked
  _sym("<BK>", "-...-.-", "prosign", True),     # szünet / új sor
  _sym("<CL>", "-.-..-..", "prosign", True),    # törlés
  _sym("<CT>", "-.-.-", "prosign", True),       # KA — üzenet kezdete
  _sym("<SN>", "...-.", "prosign", True),       # hívójel ismétlés
  _sym("<SOS>", "...---...", "prosign", True),
  _sym("<AA>", ".-.-", "prosign", True),        # minden eladó figyeljen
  _sym("<N>", "-.", "prosign", True),           # no / hiba
  _sym("<RO>", ".-.-", "prosign", True),        # received OK (egyszerűsített)
]

MORSE_SYMBOLS: list[MorseSymbol] = _LETTERS + _DIGITS + _PUNCT + _PROSIGNS

MORSE_BY_KEY: dict[str, MorseSymbol] = {s.key: s for s in MORSE_SYMBOLS}
