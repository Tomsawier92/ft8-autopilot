"""Sztereó Pulse felvétel — csatornánként (jack TIP/RING azonosításhoz)."""
from __future__ import annotations

import queue
import shutil
import subprocess
import threading

import numpy as np


class StereoPulseCapture:
  """Pulse forrás, 2 csatorna külön (float32, 48 kHz)."""

  def __init__(self, pulse_name: str, sample_rate: int = 48_000) -> None:
    if not shutil.which("parec"):
      raise RuntimeError("parec hiányzik (pulseaudio-utils)")
    self.pulse_name = pulse_name
    self.sample_rate = sample_rate
    self._bytes_per_frame = 4 * 2
    self._q: queue.Queue[tuple[np.ndarray, np.ndarray]] = queue.Queue(maxsize=64)
    self._proc: subprocess.Popen | None = None
    self._thread: threading.Thread | None = None
    self._stop = threading.Event()

  def start(self) -> None:
    self._stop.clear()
    cmd = [
      "parec",
      f"--device={self.pulse_name}",
      "--format=float32le",
      f"--rate={self.sample_rate}",
      "--channels=2",
      "--latency-msec=30",
    ]
    self._proc = subprocess.Popen(
      cmd,
      stdout=subprocess.PIPE,
      stderr=subprocess.DEVNULL,
      bufsize=0,
    )
    self._thread = threading.Thread(target=self._reader, daemon=True)
    self._thread.start()

  def _reader(self) -> None:
    assert self._proc is not None and self._proc.stdout is not None
    chunk_frames = max(512, int(self.sample_rate * 0.03))
    read_bytes = chunk_frames * self._bytes_per_frame
    while not self._stop.is_set():
      raw = self._proc.stdout.read(read_bytes)
      if not raw:
        break
      n = len(raw) // 4
      if n < 2:
        continue
      stereo = np.frombuffer(raw[: n * 4], dtype=np.float32).reshape(-1, 2)
      left = stereo[:, 0].copy()
      right = stereo[:, 1].copy()
      try:
        self._q.put_nowait((left, right))
      except queue.Full:
        pass

  def stop(self) -> None:
    self._stop.set()
    if self._proc is not None:
      proc = self._proc
      self._proc = None
      try:
        if proc.stdout is not None:
          proc.stdout.close()
        proc.terminate()
        proc.wait(timeout=1)
      except Exception:
        try:
          proc.kill()
          proc.wait(timeout=0.5)
        except Exception:
          pass
    if self._thread is not None:
      self._thread.join(timeout=1.5)
      self._thread = None

  def read(self, timeout: float = 0.08) -> tuple[np.ndarray, np.ndarray] | None:
    try:
      return self._q.get(timeout=timeout)
    except queue.Empty:
      return None
