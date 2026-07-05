"""Folyamatos FT8 stressz + fuzz — szokatlan edge case-ek."""
from __future__ import annotations

import random
import string
from dataclasses import replace

from cw_discover.ft8.stress_scenarios import (
  FeedStep,
  PhaseExpect,
  StressChecks,
  StressScenario,
  all_scenarios,
)


def exotic_scenarios() -> list[StressScenario]:
  """Amit átlagosan senki nem szimulál."""
  x: list[StressScenario] = []

  def add(sid: str, title: str, feeds: list[FeedStep], **kw) -> None:
    tags = kw.pop("tags", []) + ["exotic"]
    checks = kw.pop("checks", StressChecks())
    x.append(StressScenario(id=sid, title=title, feeds=feeds, checks=checks, tags=tags, **kw))

  add(
    "exotic_duplicate_cq_20x",
    "Ugyanaz a CQ 20× egy slotban",
    [FeedStep("CQ IK4LZH JN54", snr=-8, hz=397, wait=False, same_cycle=(i > 0)) for i in range(20)]
    + [FeedStep("CQ IK4LZH JN54", snr=-8, hz=397, wait=True, same_cycle=True)],
    checks=StressChecks(min_tx=1, max_tx=1, phase=PhaseExpect.ACTIVE),
    tags=["flood"],
  )

  add(
    "exotic_wrong_order_rr73_first",
    "RR73 report előtt — ne omoljon össze",
    [
      FeedStep("CQ IK4LZH JN54", hz=397),
      FeedStep("IK4LZH N0CALL RR73", wait=False),
      FeedStep("IK4LZH N0CALL -09", wait=False),
    ],
    checks=StressChecks(min_tx=1),  # legalább grid válasz
    tags=["order"],
  )

  add(
    "exotic_73_without_rr73",
    "Remote 73 RR73 nélkül",
    [
      FeedStep("CQ IK4LZH JN54"),
      FeedStep("IK4LZH N0CALL -09"),
      FeedStep("IK4LZH N0CALL R-05"),
      FeedStep("IK4LZH N0CALL 73"),
    ],
    checks=StressChecks(phase=PhaseExpect.IDLE, min_tx=4, logged_call="IK4LZH"),
    tags=["close"],
  )

  add(
    "exotic_echo_own_grid",
    "Saját grid üzenet vissza (IK4LZH N0CALL JN96) QSO közben",
    [
      FeedStep("CQ IK4LZH JN54", hz=397),
      FeedStep("IK4LZH N0CALL JN96", wait=False),  # echo
      FeedStep("IK4LZH N0CALL -09"),
    ],
    checks=StressChecks(remote="IK4LZH", min_tx=2, max_tx=2),
    tags=["echo"],
  )

  add(
    "exotic_cq_dx",
    "CQ DX modifier",
    [FeedStep("CQ DX IK4LZH JN54", snr=-8, hz=397)],
    checks=StressChecks(min_tx=1, remote="IK4LZH"),
    pro=True,
    tags=["cq"],
  )

  add(
    "exotic_lowercase_calls",
    "Kisbetűs hívójelek",
    [FeedStep("cq ik4lzh jn54", snr=-8, hz=397)],
    checks=StressChecks(min_tx=1),
    tags=["parse"],
  )

  add(
    "exotic_empty_third",
    "Üres harmadik mező helyett 2 token",
    [FeedStep("CQ IK4LZH", snr=-8, hz=500)],
    checks=StressChecks(max_tx=1),
    tags=["parse"],
  )

  add(
    "exotic_garbage_message",
    "Szemét üzenet — csend",
    [FeedStep("!!! ??? @@@", wait=False), FeedStep("", wait=False), FeedStep("CQ IK4LZH JN54")],
    checks=StressChecks(min_tx=1),
    tags=["garbage"],
  )

  add(
    "exotic_double_finish",
    "RR73 + 73 egymás után gyorsan",
    [
      FeedStep("CQ IK4LZH JN54"),
      FeedStep("IK4LZH N0CALL -09"),
      FeedStep("IK4LZH N0CALL R-05"),
      FeedStep("IK4LZH N0CALL RR73", wait=False, same_cycle=False),
      FeedStep("IK4LZH N0CALL 73", wait=True),
    ],
    checks=StressChecks(phase=PhaseExpect.IDLE, logged_call="IK4LZH"),
    tags=["close"],
  )

  add(
    "exotic_rearm_mid",
    "Disarm + re-arm + új CQ",
    [
      FeedStep("CQ IK4LZH JN54"),
    ],
    disarm_after_feed=0,
    checks=StressChecks(max_tx=1, phase=PhaseExpect.IDLE),
    tags=["rearm"],
  )

  add(
    "exotic_two_remote_alternate",
    "Két remote váltakozik minden slotban",
    [
      FeedStep("CQ IK4LZH JN54", hz=397),
      FeedStep("IK4LZH N0CALL -09", wait=False),
      FeedStep("DK7ZT N0CALL JO30", hz=1867, wait=False),
      FeedStep("IK4LZH N0CALL R-05", wait=False),
    ],
    checks=StressChecks(remote="IK4LZH", min_tx=1, max_tx=3),
    tags=["confusion"],
  )

  add(
    "exotic_snr_plus_20",
    "Extrém SNR +20",
    [FeedStep("CQ IK4LZH JN54", snr=+20, hz=397)],
    pro=True,
    pro_max_snr=3,
    checks=StressChecks(max_tx=0),
    tags=["snr"],
  )

  add(
    "exotic_hz_extreme",
    "Szélső audio_hz 200 és 2900",
    [
      FeedStep("CQ IK4LZH JN54", hz=200),
      FeedStep("IK4LZH N0CALL -09", hz=2900),
    ],
    checks=StressChecks(min_tx=2),
    tags=["hz"],
  )

  add(
    "exotic_closing_new_cq",
    "RR73 után új CQ — idle legyen",
    [
      FeedStep("CQ IK4LZH JN54"),
      FeedStep("IK4LZH N0CALL -09"),
      FeedStep("IK4LZH N0CALL R-05"),
      FeedStep("IK4LZH N0CALL RR73"),
      FeedStep("CQ SP9JMZ JO90", wait=False),
    ],
    checks=StressChecks(min_tx=4),
    tags=["closing"],
  )

  add(
    "exotic_same_call_two_grids",
    "Ugyanaz a call két grid CQ-ban",
    [
      FeedStep("CQ IK4LZH JN54", hz=397, wait=False),
      FeedStep("CQ IK4LZH JM77", hz=400, wait=True, same_cycle=True),
    ],
    checks=StressChecks(min_tx=1, max_tx=1),
    tags=["cq"],
  )

  add(
    "exotic_report_rr73_same_slot",
    "Report + RR73 egy slotban",
    [
      FeedStep("CQ IK4LZH JN54"),
      FeedStep("IK4LZH N0CALL -09", wait=False, same_cycle=False),
      FeedStep("IK4LZH N0CALL RR73", wait=False, same_cycle=True),
    ],
    checks=StressChecks(min_tx=1, max_tx=2),
    tags=["slot"],
  )

  add(
    "exotic_abort_reengage",
    "Abort majd ugyanaz a station újra",
    [
      FeedStep("CQ IK4LZH JN54"),
      FeedStep("IK4LZH N0CALL -09", wait=False),
    ],
    abort_after_feed=1,
    checks=StressChecks(phase=PhaseExpect.IDLE),
    tags=["abort"],
  )

  return x


def fuzz_scenario(rng: random.Random) -> StressScenario:
  """Véletlen variáns — property: ne crash-eljen, TX formátum OK."""
  base = rng.choice(all_scenarios() + exotic_scenarios())
  sid = f"fuzz_{rng.randint(0, 999999)}"
  feeds = list(base.feeds)
  if rng.random() < 0.3 and feeds:
    i = rng.randrange(len(feeds))
    feeds[i] = replace(feeds[i], snr=rng.randint(-25, 15))
  if rng.random() < 0.2:
    feeds.insert(rng.randrange(0, len(feeds) + 1), FeedStep("CQ TESTCALL", wait=False))
  checks = StressChecks(
    phase=PhaseExpect.ANY,
    min_tx=0,
    max_tx=999,
  )
  return StressScenario(
    id=sid,
    title=f"fuzz:{base.id}",
    feeds=feeds,
    ticks=base.ticks,
    pro=base.pro,
    defer_cq=base.defer_cq,
    checks=checks,
    tags=["fuzz"],
  )


def all_scenarios_extended() -> list[StressScenario]:
  return all_scenarios() + exotic_scenarios()
