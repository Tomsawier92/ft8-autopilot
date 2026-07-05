"""decode_tail + json_fast tesztek."""
from __future__ import annotations

import json
from pathlib import Path

from cw_discover.ft8.decode_tail import MmapJsonlTail
from cw_discover.ft8.json_fast import dumps_compact, dumps_line, dumps_lines


def test_dumps_roundtrip() -> None:
  obj = {"message": "CQ N0CALL JN96", "snr": -10, "id": 1}
  assert json.loads(dumps_compact(obj)) == obj
  assert json.loads(dumps_line(obj).decode()) == obj


def test_mmap_tail_incremental(tmp_path: Path) -> None:
  p = tmp_path / "decodes.jsonl"
  tail = MmapJsonlTail(p)
  assert tail.read_new() == []

  p.write_text('{"id":1,"message":"A"}\n', encoding="utf-8")
  assert len(tail.read_new()) == 1
  assert tail.read_new() == []

  with p.open("ab") as f:
    f.write(dumps_lines([{"id": 2, "message": "B"}, {"id": 3, "message": "C"}]))
  got = tail.read_new()
  assert len(got) == 2
  assert got[0]["id"] == 2


def test_tail_day_rollover(tmp_path: Path) -> None:
  a = tmp_path / "a.jsonl"
  b = tmp_path / "b.jsonl"
  tail = MmapJsonlTail(a)
  a.write_text('{"id":1}\n')
  tail.read_new()
  tail.set_path(b)
  b.write_text('{"id":2}\n')
  assert tail.read_new()[0]["id"] == 2


def test_message_preamble_cached() -> None:
  from cw_discover.ft8.decode_meta import message_preamble

  msg = "CQ HA1ABC JN96"
  mt1, c1 = message_preamble(msg)
  mt2, c2 = message_preamble(msg)
  assert mt1 == mt2 == "cq"
  assert c1 == c2
  assert "HA1ABC" in c1
