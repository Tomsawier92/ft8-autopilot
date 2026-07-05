"""FT8 dekód napló beolvasás + QSO szekvencia kinyerés (jsonl)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from datetime import datetime, timezone

from cw_discover.ft8.engine import DecodeReport
from cw_discover.ft8.ft8_protocol import (
  is_73,
  is_grid_token,
  is_r_report,
  is_report,
  is_rr73,
  is_rrr,
  message_triplet,
)
from cw_discover.ft8.grid_geo import _call_key

def third_kind(token: str) -> str:
  if is_rr73(token):
    return "RR73"
  if is_73(token):
    return "73"
  if is_rrr(token):
    return "RRR"
  if is_r_report(token):
    return "r_report"
  if is_report(token):
    return "report"
  if is_grid_token(token):
    return "grid"
  return "other"


@dataclass(frozen=True)
class LogDecode:
  cycle: str
  message: str
  snr: int
  audio_hz: int
  rf_khz: float
  msg_type: str
  time_received: float

  @classmethod
  def from_json(cls, data: dict) -> LogDecode:
    return cls(
      cycle=str(data.get("cycle", "")),
      message=str(data.get("message", "")),
      snr=int(data.get("snr", 0)),
      audio_hz=int(data.get("audio_hz", 1500)),
      rf_khz=float(data.get("rf_khz", 7074.0)),
      msg_type=str(data.get("msg_type", "")),
      time_received=float(data.get("time_received", 0.0)),
    )

  def to_report(self) -> DecodeReport:
    return DecodeReport(
      cycle=self.cycle,
      snr=self.snr,
      dt=0.1,
      audio_hz=self.audio_hz,
      rf_khz=self.rf_khz,
      message=self.message,
      time_received=self.time_received or 0.0,
    )


def load_decodes(path: Path | str, *, limit: int | None = None) -> list[LogDecode]:
  out: list[LogDecode] = []
  with Path(path).open(encoding="utf-8") as fh:
    for i, line in enumerate(fh):
      if limit is not None and i >= limit:
        break
      line = line.strip()
      if not line:
        continue
      try:
        out.append(LogDecode.from_json(json.loads(line)))
      except (json.JSONDecodeError, TypeError, ValueError):
        continue
  return out


def load_cycle_slice(path: Path | str, cycle: str) -> list[LogDecode]:
  return [d for d in load_decodes(path) if d.cycle == cycle]


def find_cq_sequences(
  decodes: list[LogDecode],
  remote: str,
  *,
  max_gap: int = 12,
) -> list[list[LogDecode]]:
  """CQ REMOTE … utáni üzenetek ugyanazzal a remote call_a-val (max_gap dekód)."""
  remote = _call_key(remote)
  sequences: list[list[LogDecode]] = []
  i = 0
  while i < len(decodes):
    d = decodes[i]
    tri = message_triplet(d.message)
    if tri and tri.is_cq and tri.call_b == remote:
      seq = [d]
      j = i + 1
      while j < len(decodes) and j < i + max_gap:
        d2 = decodes[j]
        t2 = message_triplet(d2.message)
        if t2 and t2.call_a == remote:
          seq.append(d2)
          if third_kind(t2.third) in ("RR73", "73"):
            sequences.append(seq)
            break
        elif t2 and t2.is_cq:
          break
        j += 1
      i = max(i + 1, j)
    else:
      i += 1
  return sequences


def remap_cycles_fresh(decodes: list[LogDecode]) -> list[LogDecode]:
  """Napló ciklusok → friss UTC slotok (decode_is_fresh kompatibilis)."""
  import time

  t = int(time.time())
  t -= t % 15
  mapped: dict[str, str] = {}
  idx = 0
  out: list[LogDecode] = []
  for d in decodes:
    if d.cycle not in mapped:
      mapped[d.cycle] = time.strftime("%y%m%d_%H%M%S", time.gmtime(t + idx * 15))
      idx += 1
    out.append(
      LogDecode(
        cycle=mapped[d.cycle],
        message=d.message,
        snr=d.snr,
        audio_hz=d.audio_hz,
        rf_khz=d.rf_khz,
        msg_type=d.msg_type,
        time_received=datetime.now(tz=timezone.utc).timestamp(),
      )
    )
  return out


def cycles_from_base(base_cycle: str, n: int, step: int = 15) -> list[str]:

  """FT8 cycle stringek 15 s lépéssel (YYMMDD_HHMMSS UTC)."""
  import calendar
  import time

  t = calendar.timegm(time.strptime(base_cycle.strip(), "%y%m%d_%H%M%S"))
  return [time.strftime("%y%m%d_%H%M%S", time.gmtime(t + i * step)) for i in range(n)]


def fresh_base_cycle() -> str:
  import time

  t = int(time.time())
  t -= t % 15
  return time.strftime("%y%m%d_%H%M%S", time.gmtime(t))
