"""Line-in → PyFT8 AudioIn híd jelszint-szabályzással."""
from __future__ import annotations

import subprocess
import threading
import time

import numpy as np

from cw_discover.audio.stereo_capture import StereoPulseCapture
from cw_discover.ft8.audio_fast import HopBuffer, downsample_48k_to_12k
from PyFT8.receiver import AudioIn, SAMP_RATE, SYM_RATE, HPS

HOP_SAMPLES = int(SAMP_RATE / (SYM_RATE * HPS))  # 480 @ 12 kHz
CAPTURE_FS = 48_000
LEVEL_INTERVAL_S = 0.2


def set_line_in_port(pulse_name: str) -> None:
  subprocess.run(
    ["pactl", "set-source-port", pulse_name, "analog-input-linein"],
    capture_output=True,
  )


class Ft8AudioFeed:
  """Pulse line-in felvétel, erősítés, 12 kHz hopok PyFT8-nek."""

  def __init__(
    self,
    audio_in: AudioIn,
    pulse_name: str,
    on_levels: callable | None = None,
  ) -> None:
    self.audio_in = audio_in
    self.pulse_name = pulse_name
    self.on_levels = on_levels
    self.gain_auto = True
    self.gain_manual = 1.0
    self.target_rms = 0.12
    self._auto_gain = 1.0
    self._cap: StereoPulseCapture | None = None
    self._thread: threading.Thread | None = None
    self._stop = threading.Event()
    self._hop_buf = HopBuffer()
    self._last_level_emit = 0.0
    self._hop_i16 = np.empty(HOP_SAMPLES, dtype=np.int16)
    self._rx_paused = False

  def set_rx_paused(self, paused: bool) -> None:
    self._rx_paused = paused

  @property
  def effective_gain(self) -> float:
    auto = self._auto_gain if self.gain_auto else 1.0
    return auto * self.gain_manual

  def start(self) -> None:
    set_line_in_port(self.pulse_name)
    subprocess.run(
      ["pactl", "set-source-mute", self.pulse_name, "0"],
      capture_output=True,
    )
    self._stop.clear()
    self._hop_buf.clear()
    self._cap = StereoPulseCapture(self.pulse_name, CAPTURE_FS)
    self._cap.start()
    self._thread = threading.Thread(target=self._loop, daemon=True)
    self._thread.start()

  def stop(self) -> None:
    self._stop.set()
    if self._cap is not None:
      self._cap.stop()
      self._cap = None
    if self._thread is not None:
      self._thread.join(timeout=2.0)
      self._thread = None

  def _loop(self) -> None:
    assert self._cap is not None
    while not self._stop.is_set():
      chunk = self._cap.read(timeout=0.1)
      if chunk is None:
        continue
      if self._rx_paused:
        continue
      left, right = chunk
      lr = float(np.mean(left * left))
      rr = float(np.mean(right * right))
      mono = np.asarray(right if rr > lr else left, dtype=np.float32)
      mono_sq = np.square(mono, dtype=np.float32)
      raw_rms = float(np.sqrt(mono_sq.mean()))
      if self.gain_auto and raw_rms > 1e-6:
        want = self.target_rms / raw_rms
        self._auto_gain = 0.92 * self._auto_gain + 0.08 * float(np.clip(want, 0.02, 8.0))

      gain = self.effective_gain
      mono *= gain
      np.clip(mono, -1.0, 1.0, out=mono)
      out_rms = float(np.sqrt(np.mean(np.square(mono))))
      peak = float(np.max(np.abs(mono)))
      clip_frac = float(np.mean(np.abs(mono) > 0.98))

      self._hop_buf.extend(downsample_48k_to_12k(mono))
      while True:
        hop = self._hop_buf.pop_hop(HOP_SAMPLES)
        if hop is None:
          break
        np.multiply(hop, 32767.0, out=hop)
        np.clip(hop, -32768, 32767, out=hop)
        self._hop_i16[:] = hop.astype(np.int16)
        self.audio_in._callback(self._hop_i16.tobytes(), HOP_SAMPLES, None, None)

      if self.on_levels is not None:
        now = time.monotonic()
        if now - self._last_level_emit >= LEVEL_INTERVAL_S:
          self._last_level_emit = now
          self.on_levels(raw_rms, out_rms, peak, clip_frac, gain)
