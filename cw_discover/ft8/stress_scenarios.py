"""FT8 stressz forgatókönyvek — headless virtuális QSO példányok."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PhaseExpect(str, Enum):
  IDLE = "idle"
  ACTIVE = "active"
  CLOSING = "closing"
  ANY = "any"


@dataclass
class FeedStep:
  message: str
  snr: int = -10
  hz: int = 1500
  wait: bool = True
  same_cycle: bool = False  # előzővel azonos slot


@dataclass
class CycleTick:
  count: int = 1
  force_period: bool = True  # patch ft8_period_at to tx_period


@dataclass
class StressChecks:
  phase: PhaseExpect = PhaseExpect.ANY
  remote: str | None = None
  min_tx: int = 0
  max_tx: int = 999
  tx_first: str | None = None
  tx_last: str | None = None
  tx_sequence: list[str] | None = None
  tx_contains: list[str] = field(default_factory=list)
  logged_call: str | None = None
  no_log: bool = False
  status_contains: str | None = None


@dataclass
class StressScenario:
  id: str
  title: str
  feeds: list[FeedStep] = field(default_factory=list)
  ticks: list[CycleTick] = field(default_factory=list)
  pro: bool = False
  defer_cq: bool = False
  cq_min_snr: int = -20
  pro_max_snr: int = 10
  abort_after_feed: int | None = None
  disarm_after_feed: int | None = None
  flush_cq_on_cycle: str | None = None
  set_cycles_without_reply: int | None = None
  checks: StressChecks = field(default_factory=StressChecks)
  tags: list[str] = field(default_factory=list)


def _incoming(call: str, grid: str, snr: int = -8, hz: int = 1500) -> FeedStep:
  return FeedStep(f"{call} N0CALL {grid}", snr=snr, hz=hz)


def _cq(call: str, grid: str, snr: int = -8, hz: int = 1500) -> FeedStep:
  return FeedStep(f"CQ {call} {grid}", snr=snr, hz=hz)


def _ex(remote: str, third: str, snr: int = -10) -> FeedStep:
  return FeedStep(f"{remote} N0CALL {third}", snr=snr)


def all_scenarios() -> list[StressScenario]:
  """Összes headless forgatókönyv — bővíthető."""
  s: list[StressScenario] = []

  s.append(
    StressScenario(
      id="happy_cq_ik4lzh",
      title="CQ válasz → teljes QSO napló",
      feeds=[
        _cq("IK4LZH", "JN54", hz=397),
        _ex("IK4LZH", "-09", snr=-9),
        _ex("IK4LZH", "R-05"),
        _ex("IK4LZH", "RR73"),
      ],
      checks=StressChecks(
        phase=PhaseExpect.IDLE,
        min_tx=4,
        tx_sequence=[
          "IK4LZH N0CALL JN96",
          "IK4LZH N0CALL R-09",
          "IK4LZH N0CALL RR73",
          "IK4LZH N0CALL 73",
        ],
        logged_call="IK4LZH",
      ),
      tags=["baseline", "qso"],
    )
  )

  s.append(
    StressScenario(
      id="incoming_dk7zt",
      title="Bejövő hívás grid-del",
      feeds=[_incoming("DK7ZT", "JO30", hz=1867)],
      checks=StressChecks(phase=PhaseExpect.ACTIVE, remote="DK7ZT", min_tx=1, tx_first="DK7ZT N0CALL JN96"),
      tags=["incoming"],
    )
  )

  s.append(
    StressScenario(
      id="incoming_2_same_slot",
      title="2 állomás hív egyszerre — egy TX",
      feeds=[
        FeedStep("IK4LZH N0CALL JN54", snr=-8, hz=397, wait=False, same_cycle=True),
        FeedStep("DK7ZT N0CALL JO30", snr=-6, hz=1867, wait=True, same_cycle=True),
      ],
      checks=StressChecks(min_tx=1, max_tx=1, phase=PhaseExpect.ACTIVE),
      tags=["multi", "incoming", "2"],
    )
  )

  for n, calls in [
    (4, [("IK4LZH", "JN54", 397), ("DK7ZT", "JO30", 1867), ("SP9JMZ", "JO90", 800), ("OM3XYZ", "JN88", 1200)]),
    (8, [
      ("IK4LZH", "JN54", 397),
      ("DK7ZT", "JO30", 1867),
      ("SP9JMZ", "JO90", 800),
      ("HB9EFK", "JN46", 900),
      ("PI4DX", "JO21", 1100),
      ("UA3VVA", "LO06", 700),
      ("DJ2MS", "JO30", 1300),
      ("GB2WWA", "IO90", 600),
    ]),
  ]:
    feeds = []
    for i, (call, grid, hz) in enumerate(calls):
      feeds.append(
        FeedStep(
          f"{call} N0CALL {grid}",
          snr=-10 + i,
          hz=hz,
          wait=(i == len(calls) - 1),
          same_cycle=(i > 0),
        )
      )
    s.append(
      StressScenario(
        id=f"incoming_{n}_same_slot",
        title=f"{n} bejövő egy slotban — max 1 TX",
        feeds=feeds,
        checks=StressChecks(min_tx=1, max_tx=1, phase=PhaseExpect.ACTIVE),
        tags=["multi", "incoming", str(n)],
      )
    )

  s.append(
    StressScenario(
      id="incoming_8_pro_defer_cq",
      title="8 CQ egy slotban PRO defer — buffer majd 1 válasz",
      pro=True,
      defer_cq=True,
      feeds=[
        FeedStep(f"CQ {c} {g}", snr=snr, hz=hz, wait=False, same_cycle=(i > 0))
        for i, (c, g, snr, hz) in enumerate([
          ("IK4LZH", "JN54", -8, 397),
          ("SP9JMZ", "JO90", -12, 800),
          ("DK7ZT", "JO30", -5, 1867),
          ("HB9EFK", "JN46", -14, 900),
          ("PI4DX", "JO21", -7, 1100),
          ("GB2WWA", "IO90", -16, 600),
          ("DJ2MS", "JO30", -9, 1300),
          ("UA3VVA", "LO06", -11, 700),
        ])
      ],
      flush_cq_on_cycle="flush_1",
      checks=StressChecks(min_tx=1, max_tx=1, phase=PhaseExpect.ACTIVE),
      tags=["multi", "cq", "8", "pro"],
    )
  )

  s.append(
    StressScenario(
      id="active_no_preempt_after_report",
      title="QSO közepén másik hívó — NEM vált (report után)",
      pro=True,
      feeds=[
        _cq("IK4LZH", "JN54", hz=397),
        _ex("IK4LZH", "-09"),
        FeedStep("DK7ZT N0CALL JO30", snr=-7, hz=1867, wait=False),
      ],
      checks=StressChecks(
        remote="IK4LZH",
        min_tx=2,
        tx_last="IK4LZH N0CALL R-10",
        phase=PhaseExpect.ACTIVE,
      ),
      tags=["preempt", "no"],
    )
  )

  s.append(
    StressScenario(
      id="active_pro_preempt_stuck",
      title="Beragadt QSO — PRO vált új bejövőre",
      pro=True,
      feeds=[
        _cq("IK4LZH", "JN54", hz=397),
        _incoming("DK7ZT", "JO30", hz=1867),
      ],
      set_cycles_without_reply=2,
      checks=StressChecks(remote="DK7ZT", min_tx=2, tx_last="DK7ZT N0CALL JN96"),
      tags=["preempt", "yes"],
    )
  )

  s.append(
    StressScenario(
      id="remote_busy_other_station",
      title="Remote másikkal QSO-zik — ignorálás",
      feeds=[_cq("IK4LZH", "JN54", hz=397), FeedStep("IK4LZH SP9JMZ JO90", snr=-5, hz=400, wait=False)],
      checks=StressChecks(remote="IK4LZH", max_tx=1),
      tags=["log", "busy"],
    )
  )

  s.append(
    StressScenario(
      id="self_spill_ignored",
      title="Saját TX visszahallás — nincs QSO",
      feeds=[FeedStep("N0CALL IK4LZH -18", snr=-15, hz=397, wait=False)],
      checks=StressChecks(max_tx=0, phase=PhaseExpect.IDLE),
      tags=["anomaly", "self"],
    )
  )

  s.append(
    StressScenario(
      id="stale_decode",
      title="Régi slot dekód — ignorálás",
      feeds=[FeedStep("CQ IK4LZH JN54", snr=-8, wait=False, same_cycle=False)],
      checks=StressChecks(max_tx=0),
      tags=["anomaly", "stale"],
    )
  )
  # patch cycle in runner for stale

  s.append(
    StressScenario(
      id="abandon_3_cycles",
      title="3 ciklus nincs válasz → feladás",
      feeds=[_cq("IK4LZH", "JN54", hz=397)],
      ticks=[CycleTick(count=4)],
      checks=StressChecks(phase=PhaseExpect.IDLE, remote=None, min_tx=1),
      tags=["abandon"],
    )
  )

  s.append(
    StressScenario(
      id="abort_mid_qso",
      title="QSO megszakítás abort_qso",
      feeds=[_cq("IK4LZH", "JN54"), _ex("IK4LZH", "-09")],
      abort_after_feed=1,
      checks=StressChecks(phase=PhaseExpect.IDLE, no_log=True),
      tags=["abort"],
    )
  )

  s.append(
    StressScenario(
      id="disarm_mid_qso",
      title="PTT disarm aktív QSO alatt",
      feeds=[_cq("IK4LZH", "JN54")],
      disarm_after_feed=0,
      checks=StressChecks(phase=PhaseExpect.IDLE, max_tx=1),
      tags=["disarm"],
    )
  )

  s.append(
    StressScenario(
      id="cq_while_active",
      title="Másik CQ aktív QSO alatt — ignorálás",
      feeds=[_cq("IK4LZH", "JN54", hz=397), FeedStep("CQ SP9JMZ JO90", snr=-5, hz=800, wait=False)],
      checks=StressChecks(remote="IK4LZH", max_tx=1),
      tags=["multi", "cq"],
    )
  )

  s.append(
    StressScenario(
      id="wrong_pair_ignored",
      title="Rossz call pár aktív QSO mellett",
      feeds=[_cq("IK4LZH", "JN54"), FeedStep("SP9JMZ N0CALL -09", wait=False)],
      checks=StressChecks(remote="IK4LZH", max_tx=1),
      tags=["anomaly"],
    )
  )

  s.append(
    StressScenario(
      id="snr_too_weak",
      title="CQ SNR küszöb alatt",
      cq_min_snr=-15,
      feeds=[FeedStep("CQ IK4LZH JN54", snr=-22, wait=False)],
      checks=StressChecks(max_tx=0),
      tags=["snr"],
    )
  )

  s.append(
    StressScenario(
      id="remote_rrr_close",
      title="Remote RRR → RR73",
      feeds=[_cq("IK4LZH", "JN54"), _ex("IK4LZH", "-09"), FeedStep("IK4LZH N0CALL RRR")],
      checks=StressChecks(tx_contains=["RR73"], phase=PhaseExpect.CLOSING),
      tags=["close"],
    )
  )

  s.append(
    StressScenario(
      id="after_abandon_new_cq",
      title="Feladás után új CQ fogadható",
      feeds=[_cq("IK4LZH", "JN54", hz=397)],
      ticks=[CycleTick(count=4)],
      checks=StressChecks(min_tx=2),
      tags=["abandon", "recovery"],
    )
  )

  s.append(
    StressScenario(
      id="incoming_direct_report",
      title="Bejövő közvetlen reporttal (grid skip)",
      feeds=[FeedStep("IK4LZH N0CALL -09", snr=-9, hz=397)],
      checks=StressChecks(
        remote="IK4LZH",
        tx_first="IK4LZH N0CALL R-09",
        min_tx=1,
      ),
      tags=["incoming", "report"],
    )
  )

  s.append(
    StressScenario(
      id="hz_locked",
      title="Hz nem változik QSO alatt",
      feeds=[_cq("IK4LZH", "JN54", hz=397), _ex("IK4LZH", "-09", snr=-9)],
      checks=StressChecks(min_tx=2),
      tags=["hz"],
    )
  )

  return s


def scenario_by_id(sid: str) -> StressScenario | None:
  from cw_discover.ft8.stress_fuzz import all_scenarios_extended

  for sc in all_scenarios_extended():
    if sc.id == sid:
      return sc
  return None
