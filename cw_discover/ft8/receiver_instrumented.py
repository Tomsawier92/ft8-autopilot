"""PyFT8 Receiver kiterjesztés — kandidát- és ciklus-naplózás."""
from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import numpy as np
from PyFT8.receiver import (
  BASE_PAYLOAD_HOPS,
  HOPS_PER_CYCLE,
  H_SEARCH_1,
  Receiver,
)
from PyFT8.time_utils import global_time_utils, Ticker


class InstrumentedReceiver(Receiver):
  """Ugyanaz mint PyFT8 Receiver, plusz on_candidate / on_cycle_search hookok."""

  def __init__(
    self,
    audio_in,
    freq_range,
    on_decode,
    on_busy_profile=None,
    verbose=False,
    *,
    on_candidate: Callable[[Any, str], None] | None = None,
    on_cycle_search: Callable[[str, float, int, float | None], None] | None = None,
  ) -> None:
    self._on_candidate = on_candidate
    self._on_cycle_search = on_cycle_search
    super().__init__(audio_in, freq_range, on_decode, on_busy_profile=on_busy_profile, verbose=verbose)

  def manage_cycle(self) -> None:
    candidates = []
    duplicate_filter: set[str] = set()
    base_pyld_hops = BASE_PAYLOAD_HOPS
    ticker_cycle_rollover = Ticker(0)
    ticker_search_for_syncs = Ticker(
      H_SEARCH_1,
      timing_function=lambda: self.audio_in.dBgrid_main_ptr,
      cycle_length=HOPS_PER_CYCLE,
    )
    self.audio_in.sync_pointer_to_wall_clock()
    while True:
      time.sleep(0.040)
      ptr = self.audio_in.dBgrid_main_ptr

      if ticker_cycle_rollover.ticked():
        self.audio_in.sync_pointer_to_wall_clock()
        self.curr_cycle = int(
          ((self.audio_in.dBgrid_main_ptr + 1) % (2 * HOPS_PER_CYCLE)) / HOPS_PER_CYCLE
        )

      new_to_decode = []
      for c in candidates:
        ptr_rel_to_h0 = (ptr - c.h0_idx) % HOPS_PER_CYCLE
        if not (base_pyld_hops[0] <= ptr_rel_to_h0 <= base_pyld_hops[-1]) and not c.demap_started:
          c.demap(self.audio_in.dBgrid_main)
        if c.llr_sd > 0 and not c.decode_completed:
          new_to_decode.append(c)
        if c.msg:
          msg = c.msg
          msg_key = msg if isinstance(msg, str) else " ".join(msg)
          key = f"{c.cyclestart['string']}|{msg_key}"
          if key not in duplicate_filter:
            duplicate_filter.add(key)
            self.on_decode(c)

      new_to_decode.sort(key=lambda c: c.llr_sd, reverse=True)
      cycle_str = ""
      if new_to_decode:
        cycle_str = new_to_decode[0].cyclestart.get("string", "")
      for c in new_to_decode[:55]:
        c.decode()
        if self._on_candidate is not None:
          self._on_candidate(c, cycle_str or c.cyclestart.get("string", ""))

      if ticker_search_for_syncs.ticked():
        global_time_utils.tlog(
          f"[Cycle manager] start search at hop {self.audio_in.dBgrid_main_ptr}",
          verbose=self.verbose,
        )
        cyclestart = global_time_utils.cyclestart(time.time())
        cycle_str = cyclestart.get("string", "")
        candidates = self.search(self.f0_idxs, cyclestart)
        busy_max = None
        if self.on_busy_profile is not None:
          bp, _ = self.get_busy_profile()
          busy_max = float(np.max(bp)) if bp.size else None
          self.on_busy_profile(bp, self.curr_cycle)
        if self._on_cycle_search is not None:
          self._on_cycle_search(cycle_str, float(cyclestart.get("time", time.time())), len(candidates), busy_max)
        global_time_utils.tlog(
          f"[Cycle manager] New spectrum searched -> {len(candidates)} candidates",
          verbose=self.verbose,
        )
