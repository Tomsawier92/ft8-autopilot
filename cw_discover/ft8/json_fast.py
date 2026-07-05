"""Gyors JSON segéd — egy központi dumps konfiguráció."""
from __future__ import annotations

import json
from typing import Any

_SEP = (",", ":")


def dumps_compact(obj: Any) -> str:
  return json.dumps(obj, ensure_ascii=False, separators=_SEP)


def dumps_line(obj: Any) -> bytes:
  return (dumps_compact(obj) + "\n").encode("utf-8")


def dumps_lines(objs: list[Any]) -> bytes:
  if not objs:
    return b""
  return b"".join(dumps_line(o) for o in objs)
