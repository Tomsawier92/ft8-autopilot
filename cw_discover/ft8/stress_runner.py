"""Egy stressz forgatókönyv futtatása — subprocess-barát."""
from __future__ import annotations

import tempfile
import time
import traceback
from dataclasses import asdict
from pathlib import Path
from typing import Any
from unittest.mock import patch

from cw_discover.ft8.log_replay import fresh_base_cycle, cycles_from_base
from cw_discover.ft8.pro_operator import ProOperatorConfig
from cw_discover.ft8.qso_controller import QsoPhase
from cw_discover.ft8.sim_harness import Ft8SimHarness
from cw_discover.ft8.stress_scenarios import PhaseExpect, StressScenario, scenario_by_id


def _check_phase(got: QsoPhase, want: PhaseExpect) -> str | None:
  if want == PhaseExpect.ANY:
    return None
  if got.value != want.value:
    return f"phase: {got.value} != {want.value}"
  return None


def run_stress_scenario(scenario: StressScenario | str) -> dict[str, Any]:
  """Headless virtuális példány — vissza: ok, tx, hibák."""
  if isinstance(scenario, str):
    sc = scenario_by_id(scenario)
    if sc is None:
      return {"id": scenario, "ok": False, "error": "unknown scenario"}
  else:
    sc = scenario

  t0 = time.perf_counter()
  result: dict[str, Any] = {
    "id": sc.id,
    "title": sc.title,
    "tags": sc.tags,
    "ok": True,
    "failures": [],
    "tx": [],
    "status": [],
    "phase": "",
    "remote": None,
    "elapsed_ms": 0,
  }

  try:
    with tempfile.TemporaryDirectory(prefix=f"ft8stress_{sc.id}_") as td:
      pro = ProOperatorConfig(
        enabled=sc.pro,
        defer_cq_pick=sc.defer_cq,
        min_snr=-20,
        max_snr=sc.pro_max_snr,
      )
      h = Ft8SimHarness(tmp_dir=Path(td), pro=pro, cq_min_snr=sc.cq_min_snr)
      base = fresh_base_cycle()
      cycles = cycles_from_base(base, max(32, len(sc.feeds) + 4))
      cycle_i = 0
      last_cycle = cycles[0]

      for fi, step in enumerate(sc.feeds):
        if sc.set_cycles_without_reply is not None and fi == 1 and h.op._active:
          h.op._active.cycles_without_reply = sc.set_cycles_without_reply

        if sc.id == "stale_decode":
          cyc = "260704_030000"
        elif step.same_cycle:
          cyc = last_cycle
        else:
          if cycle_i < len(cycles):
            cyc = cycles[cycle_i]
            cycle_i += 1
            last_cycle = cyc
          else:
            cyc = last_cycle

        before = len(h.tx.calls)
        h.feed(step.message, cycle=cyc, snr=step.snr, hz=step.hz, wait=step.wait)
        if step.wait and len(h.tx.calls) < before + 1:
          h.wait_tx(before + 1, timeout=0.5)

        if sc.abort_after_feed is not None and fi == sc.abort_after_feed:
          h.op.abort_qso("stress")
        if sc.disarm_after_feed is not None and fi == sc.disarm_after_feed:
          h.op.set_armed(False)

      if sc.flush_cq_on_cycle:
        h.op.on_cycle(sc.flush_cq_on_cycle, time.time())
        h.wait_tx(max(1, len(h.tx.calls)))

      for tick in sc.ticks:
        tx_p = h.op._active.tx_period if h.op._active else 0
        with patch("cw_discover.ft8.qso_controller.ft8_period_at", return_value=tx_p):
          for _ in range(tick.count):
            h.tick_cycle(f"tick_{time.time_ns()}")

      if sc.id == "after_abandon_new_cq" and h.phase == QsoPhase.IDLE:
        cyc = cycles[cycle_i] if cycle_i < len(cycles) else last_cycle
        h.feed("CQ DK7ZT JO30", cycle=cyc, snr=-7, hz=1867)

      result["tx"] = h.tx.messages()
      result["status"] = list(h.status)
      result["phase"] = h.phase.value
      result["remote"] = h.op._active.remote_call if h.op._active else None

      qso_log = (Path(td) / "qso.jsonl").read_text() if (Path(td) / "qso.jsonl").exists() else ""
      result["qso_log"] = qso_log

      ch = sc.checks
      if err := _check_phase(h.phase, ch.phase):
        result["failures"].append(err)
      if ch.remote is not None and result["remote"] != ch.remote:
        result["failures"].append(f"remote: {result['remote']!r} != {ch.remote!r}")
      n_tx = len(result["tx"])
      if n_tx < ch.min_tx:
        result["failures"].append(f"tx count {n_tx} < min {ch.min_tx}")
      if n_tx > ch.max_tx:
        result["failures"].append(f"tx count {n_tx} > max {ch.max_tx}")
      if ch.tx_first and (not result["tx"] or result["tx"][0] != ch.tx_first):
        result["failures"].append(f"tx_first: {result['tx'][:1]!r} != {ch.tx_first!r}")
      if ch.tx_last and (not result["tx"] or result["tx"][-1] != ch.tx_last):
        result["failures"].append(f"tx_last: {result['tx'][-1:]!r} != {ch.tx_last!r}")
      if ch.tx_sequence and result["tx"] != ch.tx_sequence:
        result["failures"].append(f"tx_sequence mismatch:\n  got {result['tx']!r}\n  want {ch.tx_sequence!r}")
      for frag in ch.tx_contains:
        if not any(frag in m for m in result["tx"]):
          result["failures"].append(f"tx missing fragment {frag!r}")
      if ch.logged_call:
        if ch.logged_call not in qso_log:
          result["failures"].append(f"qso log missing {ch.logged_call}")
      if ch.no_log and qso_log.strip():
        result["failures"].append("unexpected qso log")
      if ch.status_contains and not any(ch.status_contains in s for s in h.status):
        result["failures"].append(f"status missing {ch.status_contains!r}")

      if sc.id == "hz_locked":
        if not all(tx.audio_hz == 397 for tx in h.tx.calls):
          result["failures"].append("audio_hz changed during QSO")

      result["ok"] = len(result["failures"]) == 0

  except Exception as exc:
    result["ok"] = False
    result["failures"].append(f"exception: {exc}")
    result["traceback"] = traceback.format_exc()

  result["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 1)
  return result


def run_stress_by_id(scenario_id: str) -> dict[str, Any]:
  return run_stress_scenario(scenario_id)
