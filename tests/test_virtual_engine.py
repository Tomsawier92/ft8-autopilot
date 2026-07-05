"""Virtuális FT8 engine tesztek."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from cw_discover.ft8.ft8_slot import cycle_key_at
from cw_discover.ft8.virtual_engine import VirtualFt8Engine


def test_virtual_inject_jsonl(tmp_path: Path) -> None:
  inj = tmp_path / "inject.jsonl"
  got: list[str] = []
  cycles: list[str] = []

  eng = VirtualFt8Engine(
    inject_jsonl=inj,
    inject_txt=tmp_path / "none.txt",
    on_decode=lambda r: got.append(r.message),
    on_cycle_search=lambda c, *_a: cycles.append(c),
  )
  eng.start()
  time.sleep(0.2)
  inj.write_text(
    json.dumps({"message": "CQ TEST1 JN57", "snr": -10, "hz": 1500}) + "\n",
    encoding="utf-8",
  )
  deadline = time.time() + 2.0
  while time.time() < deadline and not got:
    time.sleep(0.05)
  eng.stop()
  assert got == ["CQ TEST1 JN57"]


def test_cycle_key_aligned() -> None:
  c = cycle_key_at()
  assert len(c) == 13
  assert c[6] == "_"
