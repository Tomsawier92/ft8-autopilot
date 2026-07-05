#!/usr/bin/env python3
"""10+ perc folyamatos FT8 stressz — exotic + fuzz, élő visszajelzés."""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path


def _worker(scenario_id: str, fuzz_payload: dict | None = None) -> dict:
  root = Path(__file__).resolve().parents[1]
  if str(root) not in sys.path:
    sys.path.insert(0, str(root))
  from cw_discover.ft8.stress_runner import run_stress_scenario
  from cw_discover.ft8.stress_fuzz import fuzz_scenario
  from cw_discover.ft8.stress_scenarios import scenario_by_id

  if fuzz_payload:
    rng = random.Random(fuzz_payload["seed"])
    sc = fuzz_scenario(rng)
  else:
    sc = scenario_by_id(scenario_id)
    if sc is None:
      return {"id": scenario_id, "ok": False, "failures": ["unknown"]}
  r = run_stress_scenario(sc)
  # Globális invariánsok (fuzz + exotic)
  inv = _invariants(r)
  if inv:
    r["failures"] = list(r.get("failures", [])) + inv
    r["ok"] = False
  return r


def _invariants(result: dict) -> list[str]:
  errs: list[str] = []
  for msg in result.get("tx", []):
    parts = msg.split()
    if len(parts) < 3:
      errs.append(f"invalid tx format: {msg!r}")
    if parts and parts[0] == "N0CALL" and len(parts) >= 2 and parts[1] != "N0CALL":
      pass  # self spill tx would be weird — shouldn't tx
  if result.get("traceback"):
    errs.append("uncaught exception")
  return errs


def main() -> int:
  root = Path(__file__).resolve().parents[1]
  sys.path.insert(0, str(root))
  from cw_discover.paths import FORGALMI_LIVE

  ap = argparse.ArgumentParser()
  ap.add_argument("--minutes", type=float, default=10.0)
  ap.add_argument("--workers", type=int, default=max(1, int((os.cpu_count() or 4) * 0.8)))
  ap.add_argument("--out", type=Path, default=FORGALMI_LIVE / "stress_continuous.jsonl")
  ap.add_argument("--fuzz-ratio", type=float, default=0.35, help="fuzz vs fix scenario")
  args = ap.parse_args()

  root = Path(__file__).resolve().parents[1]
  sys.path.insert(0, str(root))
  from cw_discover.ft8.stress_fuzz import all_scenarios_extended

  fixed = [sc.id for sc in all_scenarios_extended()]
  end = time.time() + args.minutes * 60
  rng = random.Random(42)
  total = ok = fail = 0
  fail_ids: dict[str, int] = {}
  args.out.parent.mkdir(parents=True, exist_ok=True)

  print(f"▶ Folyamatos stressz {args.minutes} perc | {args.workers} worker | {len(fixed)} fix + fuzz")
  print(f"  log: {args.out}")

  with args.out.open("a", encoding="utf-8") as log:
    batch = 0
    while time.time() < end:
      batch += 1
      jobs: list[tuple[str, dict | None]] = []
      n_jobs = args.workers * 2
      for _ in range(n_jobs):
        if rng.random() < args.fuzz_ratio:
          jobs.append((f"fuzz_{rng.randint(0,999999)}", {"seed": rng.randint(0, 2**31)}))
        else:
          jobs.append((rng.choice(fixed), None))

      t_batch = time.perf_counter()
      with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(_worker, sid, fp): sid for sid, fp in jobs}
        for fut in as_completed(futs):
          row = fut.result()
          row["batch"] = batch
          row["ts"] = datetime.now(tz=timezone.utc).isoformat()
          log.write(json.dumps(row, ensure_ascii=False) + "\n")
          total += 1
          if row.get("ok"):
            ok += 1
          else:
            fail += 1
            fid = row.get("id", "?")
            fail_ids[fid] = fail_ids.get(fid, 0) + 1
            print(f"  ✗ {fid}: {row.get('failures', [])[:2]}")

      elapsed = time.perf_counter() - t_batch
      left = max(0, end - time.time())
      rate = total / max(time.time() - (end - args.minutes * 60), 0.1)
      print(
        f"[batch {batch}] {ok}/{total} OK | fail={fail} | "
        f"{rate:.0f}/s | batch {elapsed:.1f}s | hátra {left/60:.1f} min",
        flush=True,
      )
      log.flush()

  print(f"\n{'═'*50}")
  print(f"VÉGE: {ok}/{total} OK, {fail} FAIL")
  if fail_ids:
    print("Top hibák:")
    for k, v in sorted(fail_ids.items(), key=lambda x: -x[1])[:15]:
      print(f"  {v:4d} × {k}")
    return 1
  print("✓ 10 perc — nincs invariant sértés")
  return 0


if __name__ == "__main__":
  sys.exit(main())
