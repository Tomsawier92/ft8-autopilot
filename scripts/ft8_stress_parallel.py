#!/usr/bin/env python3
"""
FT8 headless stressz — sok virtuális példány párhuzamosan.

~80% CPU, nincs rádió/GUI. Jelentés: forgalminaplo/live/stress_report.jsonl

  cd ~/ai/cw-discover
  PYTHONPATH=. .venv/bin/python scripts/ft8_stress_parallel.py
  PYTHONPATH=. .venv/bin/python scripts/ft8_stress_parallel.py --workers 12 --repeat 3
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

# subprocess entry — csak scenario id
def _worker(scenario_id: str) -> dict:
  import sys
  from pathlib import Path

  root = Path(__file__).resolve().parents[1]
  if str(root) not in sys.path:
    sys.path.insert(0, str(root))
  from cw_discover.ft8.stress_runner import run_stress_by_id

  return run_stress_by_id(scenario_id)


def _default_workers() -> int:
  n = os.cpu_count() or 4
  return max(1, int(n * 0.8))


def main() -> int:
  root = Path(__file__).resolve().parents[1]
  sys.path.insert(0, str(root))
  from cw_discover.paths import FORGALMI_LIVE

  ap = argparse.ArgumentParser(description="FT8 párhuzamos stressz (headless)")
  ap.add_argument("--workers", type=int, default=_default_workers())
  ap.add_argument("--repeat", type=int, default=1, help="minden forgatókönyv ismétlése")
  ap.add_argument("--out", type=Path, default=FORGALMI_LIVE / "stress_report.jsonl")
  ap.add_argument("--list", action="store_true", help="forgatókönyvek listája")
  ap.add_argument("--pre-live", action="store_true", help="indulás előtti ajánlott futtatás (repeat=2)")
  args = ap.parse_args()
  if args.pre_live:
    args.repeat = max(args.repeat, 2)

  root = Path(__file__).resolve().parents[1]
  sys.path.insert(0, str(root))
  from cw_discover.ft8.stress_scenarios import all_scenarios

  scenarios = all_scenarios()
  if args.list:
    for sc in scenarios:
      print(f"  {sc.id:32} [{','.join(sc.tags)}] {sc.title}")
    print(f"\nÖsszesen: {len(scenarios)} forgatókönyv")
    return 0

  job_ids: list[str] = []
  for r in range(args.repeat):
    for sc in scenarios:
      job_ids.append(sc.id if r == 0 else f"{sc.id}__run{r}")

  # repeat with same scenario id (worker uses base id)
  run_ids = []
  for jid in job_ids:
    base = jid.split("__run")[0]
    run_ids.append(base)

  print(f"Stressz: {len(run_ids)} futás, {args.workers} worker (~{int(args.workers / (os.cpu_count() or 1) * 100)}% CPU)")
  print(f"Kimenet: {args.out}")
  t0 = time.perf_counter()
  results: list[dict] = []
  failed: list[dict] = []

  args.out.parent.mkdir(parents=True, exist_ok=True)
  with args.out.open("w", encoding="utf-8") as rep:
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
      futs = {pool.submit(_worker, sid): (sid, i) for i, sid in enumerate(run_ids)}
      for fut in as_completed(futs):
        sid, idx = futs[fut]
        row = fut.result()
        row["run_index"] = idx
        row["ts"] = datetime.now(tz=timezone.utc).isoformat()
        rep.write(json.dumps(row, ensure_ascii=False) + "\n")
        rep.flush()
        results.append(row)
        if not row.get("ok"):
          failed.append(row)
        mark = "OK" if row.get("ok") else "FAIL"
        print(f"  [{mark}] {row['id']:30} {row.get('elapsed_ms', 0):>5} ms  tx={len(row.get('tx', []))}")

  elapsed = time.perf_counter() - t0
  ok_n = sum(1 for r in results if r.get("ok"))
  print(f"\n{'═' * 50}")
  print(f"Eredmény: {ok_n}/{len(results)} OK  ({elapsed:.1f} s, {len(results)/max(elapsed,0.1):.0f} futás/s)")

  if failed:
    print(f"\n❌ HIBÁK ({len(failed)}):")
    for f in failed:
      print(f"\n  ▶ {f['id']}: {f.get('title', '')}")
      for err in f.get("failures", []):
        print(f"      • {err}")
      if f.get("tx"):
        print(f"      TX: {f['tx']}")
      if f.get("status"):
        print(f"      status: {f['status'][-3:]}")
    return 1

  print("\n✓ Minden forgatókönyv OK — indulhat az élő stack.")
  return 0


if __name__ == "__main__":
  sys.exit(main())
