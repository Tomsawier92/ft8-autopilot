"""Virtuális FT8 vétel — AI injektált dekódok, nincs line-in / PyFT8 audio."""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from cw_discover.ft8.decode_meta import message_upper, time_iso_utc
from cw_discover.ft8.decode_tail import MmapJsonlTail
from pathlib import Path
from typing import Any

from cw_discover.ft8.engine import AudioSnapshot, DecodeReport

from cw_discover.ft8.ft8_slot import cycle_key_at, cycle_start_timestamp, seconds_until_tx_period

from cw_discover.paths import FORGALMI_LIVE
DEFAULT_INJECT_JSONL = FORGALMI_LIVE / "inject_decodes.jsonl"
DEFAULT_INJECT_TXT = FORGALMI_LIVE / "inject_in.txt"


@dataclass
class InjectRequest:
  message: str
  snr: int = -12
  hz: int = 1867
  cycle: str = ""
  rf_khz: float = 0.0


class VirtualFt8Engine:
  """Ft8Engine kompatibilis felület — dekódok fájlból / API-ból, FT8 slot óra."""

  def __init__(
    self,
    dial_mhz: float = 7.074,
    band: str = "40m",
    on_decode: callable | None = None,
    on_cycle_search: callable | None = None,
    inject_jsonl: Path | None = None,
    inject_txt: Path | None = None,
  ) -> None:
    self.dial_mhz = dial_mhz
    self._dial_khz = dial_mhz * 1000.0
    self.band = band
    self._on_decode = on_decode
    self._on_cycle_search = on_cycle_search
    self.inject_jsonl = inject_jsonl or DEFAULT_INJECT_JSONL
    self.inject_txt = inject_txt or DEFAULT_INJECT_TXT
    self._seen: OrderedDict[str, None] = OrderedDict()
    self._lock = threading.Lock()
    self._rx_paused = False
    self._inject_tail: MmapJsonlTail | None = None
    self._last_cycle = ""
    self._inject_txt_mtime = -1.0
    self._thread: threading.Thread | None = None
    self.running = False
    self.inject_count = 0

  def _emit_decode(self, req: InjectRequest) -> None:
    msg = message_upper(req.message)
    if not msg:
      return
    cycle = req.cycle.strip() or cycle_key_at()
    key = f"{cycle}|{msg}"
    with self._lock:
      if key in self._seen:
        return
      self._seen[key] = None
      if len(self._seen) > 5000:
        self._seen.popitem(last=False)
    rf_khz = req.rf_khz or (self._dial_khz + req.hz / 1000.0)
    cst = cycle_start_timestamp(cycle)
    now = time.time()
    report = DecodeReport(
      cycle=cycle,
      snr=req.snr,
      dt=0.0,
      audio_hz=req.hz,
      rf_khz=rf_khz,
      message=msg,
      time_received=now,
      cycle_start_utc=time_iso_utc(cst),
      dsp={"virtual": True},
      audio={"virtual": True},
    )
    self.inject_count += 1
    if self._on_decode is not None:
      self._on_decode(report)

  def inject_decode(
    self,
    message: str,
    *,
    snr: int = -12,
    hz: int = 1867,
    cycle: str | None = None,
    rf_khz: float = 0.0,
  ) -> None:
    if self._rx_paused:
      return
    self._emit_decode(
      InjectRequest(message=message, snr=snr, hz=hz, cycle=cycle or "", rf_khz=rf_khz)
    )

  def _parse_jsonl_line(self, raw: dict[str, Any]) -> InjectRequest | None:
    msg = str(raw.get("message", "")).strip()
    if not msg:
      return None
    return InjectRequest(
      message=msg,
      snr=int(raw.get("snr", -12)),
      hz=int(raw.get("hz", raw.get("audio_hz", 1867))),
      cycle=str(raw.get("cycle", "")),
      rf_khz=float(raw.get("rf_khz", 0.0)),
    )

  def _tail_jsonl(self) -> None:
    path = self.inject_jsonl
    if self._inject_tail is None or self._inject_tail.path != path:
      self._inject_tail = MmapJsonlTail(path)
    for raw in self._inject_tail.read_new():
      req = self._parse_jsonl_line(raw)
      if req is not None:
        self._emit_decode(req)

  def _poll_txt(self) -> None:
    path = self.inject_txt
    try:
      st = path.stat()
      if st.st_size == 0:
        self._inject_txt_mtime = st.st_mtime
        return
      if st.st_mtime == self._inject_txt_mtime:
        return
      self._inject_txt_mtime = st.st_mtime
      text = path.read_text(encoding="utf-8").strip()
    except OSError:
      return
    if not text:
      return
    path.write_text("", encoding="utf-8")
    self._inject_txt_mtime = -1.0
    for line in text.splitlines():
      line = line.strip()
      if not line or line.startswith("#"):
        continue
      parts = line.split()
      snr, hz = -12, 1867
      msg = line
      if (
        len(parts) >= 3
        and parts[-1].lstrip("+-").isdigit()
        and parts[-2].replace(".", "", 1).isdigit()
      ):
        snr = int(parts[-1])
        hz = int(float(parts[-2]))
        msg = " ".join(parts[:-2])
      self._emit_decode(InjectRequest(message=msg, snr=snr, hz=hz))

  def _tick_cycle(self, now: float) -> None:
    cycle = cycle_key_at(now)
    if cycle == self._last_cycle:
      return
    self._last_cycle = cycle
    if self._on_cycle_search is not None:
      snap = AudioSnapshot()
      self._on_cycle_search(cycle, cycle_start_timestamp(cycle), 0, None, now, snap)

  def _loop(self) -> None:
    while self.running:
      now = time.time()
      if not self._rx_paused:
        self._tail_jsonl()
        self._poll_txt()
      self._tick_cycle(now)
      # Következő FT8 ciklusig alszunk (max 80 ms poll ha injekt aktív)
      delay = seconds_until_tx_period(0, now)
      if delay > 0.5:
        time.sleep(min(delay - 0.1, 2.0))
      else:
        time.sleep(0.08)

  def start(self) -> None:
    if self.running:
      return
    FORGALMI_LIVE.mkdir(parents=True, exist_ok=True)
    self.inject_jsonl.touch(exist_ok=True)
    self._inject_tail = MmapJsonlTail(self.inject_jsonl)
    self._last_cycle = ""
    self.running = True
    self._thread = threading.Thread(target=self._loop, daemon=True, name="virtual-ft8")
    self._thread.start()

  def stop(self) -> None:
    self.running = False
    if self._thread is not None:
      self._thread.join(timeout=2.0)
      self._thread = None

  def set_dial_mhz(self, mhz: float) -> None:
    self.dial_mhz = mhz
    self._dial_khz = mhz * 1000.0

  def set_rx_paused(self, paused: bool) -> None:
    self._rx_paused = paused

  def get_audio_settings(self) -> dict:
    return {
      "gain_auto": False,
      "gain_manual": 1.0,
      "target_rms": 0.0,
      "pulse_device": "virtual",
      "inject_jsonl": str(self.inject_jsonl),
      "inject_txt": str(self.inject_txt),
    }
