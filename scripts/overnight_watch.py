#!/usr/bin/env python3
"""Éjszakai FT8 — supervisor indítás + élő állapot a terminálban."""
from __future__ import annotations

import json
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT))

from cw_discover.paths import LOG_DIR

ROOT = Path(__file__).resolve().parents[1]
SUP = ROOT / "scripts" / "ft8_headless_supervisor.py"
PY = ROOT / ".venv" / "bin" / "python"


def _day_log() -> Path:
  day = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
  return LOG_DIR / day / "decodes.jsonl"


def _count_lines(path: Path) -> int:
  if not path.exists():
    return 0
  n = 0
  with path.open("rb") as f:
    for _ in f:
      n += 1
  return n


def _last_decode_line(path: Path) -> str:
  if not path.exists() or path.stat().st_size == 0:
    return "—"
  try:
    with path.open("rb") as f:
      f.seek(max(0, path.stat().st_size - 8192))
      lines = f.read().decode("utf-8", errors="replace").splitlines()
    for line in reversed(lines):
      line = line.strip()
      if not line:
        continue
      rec = json.loads(line)
      msg = rec.get("message", "?")
      snr = rec.get("snr", "?")
      t = rec.get("time_iso", "")[:19]
      return f"{t}  SNR{snr:+d}  {msg}" if isinstance(snr, int) else f"{t}  {msg}"
  except Exception as exc:
    return f"(olvasási hiba: {exc})"
  return "—"


def _print_status(started: float, proc: subprocess.Popen | None) -> None:
  dec = _day_log()
  now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
  running = proc is not None and proc.poll() is None
  print("\n" + "=" * 72, flush=True)
  print(f"  ÁLLAPOT  {now}  |  futás: {(time.time()-started)/3600:.1f} h", flush=True)
  print(f"  Supervisor: {'FUT' if running else 'LEÁLLT exit=' + str(proc.poll() if proc else '?')}", flush=True)
  print(f"  Dekódok ma: {_count_lines(dec)} sor  →  {dec}", flush=True)
  print(f"  Utolsó dekód: {_last_decode_line(dec)}", flush=True)
  print("=" * 72 + "\n", flush=True)


def main() -> int:
  LOG_DIR.mkdir(parents=True, exist_ok=True)
  started = time.time()
  stop = False

  def _sig(_s, _f):
    nonlocal stop
    stop = True

  signal.signal(signal.SIGINT, _sig)
  signal.signal(signal.SIGTERM, _sig)

  cmd = [str(PY), str(SUP), "--power-safe"]
  print("Éjszakai FT8 figyelés indul — Ctrl+C = teljes leállítás", flush=True)
  print(f"Parancs: {' '.join(cmd)}", flush=True)
  print(f"Dekód napló: {_day_log()}", flush=True)
  print("(Csak decodes.jsonl mentés — nincs overnight/supervisor/candidates log)", flush=True)

  proc = subprocess.Popen(cmd, cwd=str(ROOT))

  next_status = time.time() + 15
  try:
    while not stop:
      if proc.poll() is not None and not stop:
        print(f"\n⚠ Supervisor leállt (exit {proc.returncode}) — újraindítás 10 s múlva…", flush=True)
        time.sleep(10)
        if stop:
          break
        proc = subprocess.Popen(cmd, cwd=str(ROOT))
      if time.time() >= next_status:
        _print_status(started, proc)
        next_status = time.time() + 60
      time.sleep(1)
  finally:
    print("\nLeállítás — supervisor SIGTERM…", flush=True)
    if proc.poll() is None:
      proc.terminate()
      try:
        proc.wait(timeout=90)
      except subprocess.TimeoutExpired:
        proc.kill()
    _print_status(started, proc)
    print("Kész. Dekód napló megmaradt.", flush=True)
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
