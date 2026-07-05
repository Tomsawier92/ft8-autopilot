#!/usr/bin/env python3
"""Párhuzamos FT8 napló bányászat — QSO minták, anomáliák (CPU, N mag)."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from cw_discover.ft8.log_replay import LogDecode, find_cq_sequences, load_decodes, third_kind
from cw_discover.ft8.ft8_protocol import message_triplet
from cw_discover.paths import LOG_DIR


def _scan_chunk(path: str, offset: int, limit: int) -> dict:
  decodes: list[LogDecode] = []
  with Path(path).open(encoding="utf-8") as fh:
    for i, line in enumerate(fh):
      if i < offset:
        continue
      if i >= offset + limit:
        break
      line = line.strip()
      if not line:
        continue
      try:
        decodes.append(LogDecode.from_json(json.loads(line)))
      except (json.JSONDecodeError, TypeError, ValueError):
        continue

  msg_types: Counter[str] = Counter()
  cq_count = 0
  close_count = 0
  self_spill = 0
  busy_cycles: Counter[str] = Counter()

  for d in decodes:
    msg_types[d.msg_type or "?"] += 1
    tri = message_triplet(d.message)
    if tri and tri.is_cq and d.cycle:
      cq_count += 1
      busy_cycles[d.cycle] += 1
    if tri and len(d.message.split()) >= 3:
      tk = third_kind(tri.third)
      if tk in ("RR73", "73"):
        close_count += 1
    if d.message.startswith("N0CALL "):
      self_spill += 1

  seq_ik = find_cq_sequences(decodes, "IK4LZH", max_gap=8)
  return {
    "rows": len(decodes),
    "msg_types": dict(msg_types),
    "cq": cq_count,
    "closes": close_count,
    "self_spill": self_spill,
    "busy_max": max(busy_cycles.values()) if busy_cycles else 0,
    "ik4lzh_seqs": len(seq_ik),
  }


def _count_lines(path: Path) -> int:
  n = 0
  with path.open(encoding="utf-8") as fh:
    for _ in fh:
      n += 1
  return n


def main() -> int:
  ap = argparse.ArgumentParser(description="FT8 napló párhuzamos elemzés")
  ap.add_argument("--log-dir", type=Path, default=LOG_DIR)
  ap.add_argument("--days", type=int, default=2, help="utolsó N nap mappája")
  ap.add_argument("--workers", type=int, default=8)
  ap.add_argument("--chunk", type=int, default=4000, help="sor / worker feladat")
  args = ap.parse_args()

  log_files = sorted(args.log_dir.glob("*/decodes.jsonl"), reverse=True)[: args.days]
  if not log_files:
    print("Nincs decodes.jsonl", file=sys.stderr)
    return 1

  totals: Counter[str] = Counter()
  agg_cq = agg_close = agg_spill = agg_rows = 0
  busy_max = 0
  ik_seqs = 0

  for lf in log_files:
    total = _count_lines(lf)
    tasks = [(str(lf), off, min(args.chunk, total - off)) for off in range(0, total, args.chunk)]
    print(f"{lf.name}: {total} sor → {len(tasks)} chunk, {args.workers} worker")

    with ProcessPoolExecutor(max_workers=args.workers) as pool:
      futs = [pool.submit(_scan_chunk, p, o, lim) for p, o, lim in tasks]
      for fut in as_completed(futs):
        r = fut.result()
        agg_rows += r["rows"]
        agg_cq += r["cq"]
        agg_close += r["closes"]
        agg_spill += r["self_spill"]
        busy_max = max(busy_max, r["busy_max"])
        ik_seqs += r["ik4lzh_seqs"]
        for k, v in r["msg_types"].items():
          totals[k] += v

  print(f"\nÖsszesen: {agg_rows} sor")
  print(f"  CQ: {agg_cq}  lezárás (73/RR73): {agg_close}")
  print(f"  N0CALL self-spill: {agg_spill}")
  print(f"  Max CQ/slot: {busy_max}")
  print(f"  IK4LZH QSO szekvenciák: {ik_seqs}")
  print(f"  msg_type: {dict(totals.most_common(6))}")
  return 0


if __name__ == "__main__":
  sys.exit(main())
