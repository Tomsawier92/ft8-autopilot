"""Line-in felvétel — Pulse monitor (parec) vagy sounddevice."""
from __future__ import annotations

import queue
import shutil
import subprocess
import threading

import numpy as np
from scipy.signal import resample_poly

from cw_discover.audio.source import CaptureSource

try:
  import sounddevice as sd
except ImportError:
  sd = None


def _to_mono(indata: np.ndarray) -> np.ndarray:
  x = np.asarray(indata, dtype=np.float32)
  if x.ndim == 2 and x.shape[1] > 1:
    return x.mean(axis=1).astype(np.float32)
  if x.ndim == 2:
    return x[:, 0].astype(np.float32)
  return x.ravel().astype(np.float32)


def _pick_samplerate(device: int | None, preferred: int, channels: int = 1) -> int:
  if sd is None:
    return preferred
  for sr in (preferred, 48000, 44100, 96000, 32000, 16000, 8000):
    try:
      sd.check_input_settings(
        device=device, samplerate=sr, channels=channels, dtype="float32"
      )
      return sr
    except Exception:
      continue
  return 44100


def _input_channels(device: int | None) -> int:
  if sd is None or device is None:
    return 1
  try:
    info = sd.query_devices(device)
    return min(2, max(1, int(info["max_input_channels"])))
  except Exception:
    return 1


class _ResampleMixin:
  target_fs: int
  capture_fs: int
  _ratio: float

  def _resample_chunk(self, mono: np.ndarray) -> np.ndarray:
    if self.capture_fs == self.target_fs:
      return mono.astype(np.float32, copy=False)
    n_out = max(1, int(round(mono.size * self._ratio)))
    g = np.gcd(int(self.capture_fs), int(self.target_fs))
    return resample_poly(mono, self.target_fs // g, self.capture_fs // g, padtype="line")[
      :n_out
    ].astype(np.float32)


class LineInCapture(_ResampleMixin):
  def __init__(self, fs: int, blocksize: int, device: int | None = None) -> None:
    self.target_fs = fs
    self.blocksize = blocksize
    self.device = device
    self._in_ch = _input_channels(device)
    self.capture_fs = _pick_samplerate(device, fs, self._in_ch)
    self._ratio = self.target_fs / float(self.capture_fs)
    cap_block = max(256, int(blocksize * self.capture_fs / max(self.target_fs, 1)))
    self._cap_blocksize = cap_block
    self._q: queue.Queue[np.ndarray] = queue.Queue(maxsize=128)
    self._stream = None
    self._stop = threading.Event()

  def _callback(self, indata, frames, time_info, status) -> None:  # noqa: ARG001
    mono = _to_mono(indata)
    try:
      self._q.put_nowait(self._resample_chunk(mono))
    except queue.Full:
      pass

  def start(self) -> None:
    if sd is None:
      raise RuntimeError("sounddevice nincs telepítve")
    self._stop.clear()
    self._stream = sd.InputStream(
      samplerate=self.capture_fs,
      blocksize=self._cap_blocksize,
      channels=self._in_ch,
      dtype="float32",
      device=self.device,
      callback=self._callback,
    )
    self._stream.start()

  def stop(self) -> None:
    self._stop.set()
    if self._stream is not None:
      self._stream.stop()
      self._stream.close()
      self._stream = None

  def read(self, timeout: float = 0.05) -> np.ndarray | None:
    try:
      return self._q.get(timeout=timeout)
    except queue.Empty:
      return None


class PulseCapture(_ResampleMixin):
  """Konkrét Pulse/PipeWire forrás — pl. alsa_output.*.monitor."""

  def __init__(self, fs: int, blocksize: int, pulse_name: str) -> None:
    if not shutil.which("parec"):
      raise RuntimeError("parec hiányzik (pulseaudio-utils csomag)")
    self.target_fs = fs
    self.blocksize = blocksize
    self.pulse_name = pulse_name
    self.capture_fs = 48_000
    self._ratio = self.target_fs / float(self.capture_fs)
    self._q: queue.Queue[np.ndarray] = queue.Queue(maxsize=128)
    self._proc: subprocess.Popen | None = None
    self._thread: threading.Thread | None = None
    self._stop = threading.Event()
    self._bytes_per_frame = 4 * 2  # float32 stereo

  def start(self) -> None:
    self._stop.clear()
    cmd = [
      "parec",
      f"--device={self.pulse_name}",
      "--format=float32le",
      f"--rate={self.capture_fs}",
      "--channels=2",
      "--latency-msec=40",
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
    chunk_frames = max(512, int(self.capture_fs * 0.04))
    read_bytes = chunk_frames * self._bytes_per_frame
    while not self._stop.is_set():
      raw = self._proc.stdout.read(read_bytes)
      if not raw:
        break
      n = len(raw) // 4
      if n < 2:
        continue
      stereo = np.frombuffer(raw[: n * 4], dtype=np.float32).reshape(-1, 2)
      mono = _to_mono(stereo)
      try:
        self._q.put_nowait(self._resample_chunk(mono))
      except queue.Full:
        pass

  def stop(self) -> None:
    self._stop.set()
    if self._proc is not None:
      try:
        self._proc.terminate()
        self._proc.wait(timeout=1)
      except Exception:
        try:
          self._proc.kill()
        except Exception:
          pass
      self._proc = None
    if self._thread is not None:
      self._thread.join(timeout=1.5)
      self._thread = None

  def read(self, timeout: float = 0.05) -> np.ndarray | None:
    try:
      return self._q.get(timeout=timeout)
    except queue.Empty:
      return None


def open_capture(fs: int, blocksize: int, source: CaptureSource):
  if source.kind == "pulse" and source.pulse_name:
    return PulseCapture(fs, blocksize, source.pulse_name)
  return LineInCapture(fs, blocksize, source.sd_index)
