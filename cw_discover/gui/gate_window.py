"""CUDA CW zajkapu — külön GUI, scope, csúszkák, CWFiltered kimenet."""
from __future__ import annotations

import sys
import threading

import numpy as np
from PyQt5 import QtCore, QtGui, QtWidgets
from scipy.signal import resample_poly

from cw_discover.audio.bridge_sink import CAPTURE_FS, SINK_NAME, ensure_filtered_sink
from cw_discover.audio.capture import PulseCapture
from cw_discover.audio.pulse_sources import list_pulse_sources, pick_recommended_monitor
from cw_discover.filter.gate import CwNoiseGate, GateConfig
from cw_discover.gui.scope_widget import WaveformScope

PROC_FS = 12_000


def _resample(x: np.ndarray, fs_in: int, fs_out: int) -> np.ndarray:
  if fs_in == fs_out:
    return x.astype(np.float32)
  g = np.gcd(fs_in, fs_out)
  return resample_poly(x, fs_out // g, fs_in // g).astype(np.float32)


class GateWorker(QtCore.QThread):
  tick = QtCore.pyqtSignal(object, object, dict)  # wave_in, wave_out, meta
  error = QtCore.pyqtSignal(str)

  def __init__(self, parent=None) -> None:
    super().__init__(parent)
    self._stop = threading.Event()
    self.gate: CwNoiseGate | None = None
    self.bypass = False
    self.source_name = ""
    self._cap: PulseCapture | None = None
    self._play = None
    self._scope_in = np.zeros(int(PROC_FS * 0.25), dtype=np.float32)
    self._scope_out = np.zeros(int(PROC_FS * 0.25), dtype=np.float32)

  def configure(self, gate: CwNoiseGate, source_name: str) -> None:
    self.gate = gate
    self.source_name = source_name

  def stop_work(self) -> None:
    self._stop.set()

  def run(self) -> None:
    import shutil
    import subprocess

    if not shutil.which("parec") or not shutil.which("pacat"):
      self.error.emit("parec/pacat hiányzik")
      return
    if not ensure_filtered_sink():
      self.error.emit("CWFiltered sink nem hozható létre (pactl)")
      return

    self._stop.clear()
    try:
      self._cap = PulseCapture(PROC_FS, 2048, self.source_name)
      self._play = subprocess.Popen(
        [
          "pacat",
          f"--device={SINK_NAME}",
          "--format=float32le",
          f"--rate={CAPTURE_FS}",
          "--channels=1",
          "--latency-msec=40",
        ],
        stdin=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
      )
      self._cap.start()
    except Exception as e:
      self.error.emit(str(e))
      return

    while not self._stop.is_set():
      chunk = self._cap.read(timeout=0.05) if self._cap else None
      if chunk is None:
        continue
      chunk = np.asarray(chunk, dtype=np.float32).ravel()
      n = chunk.size
      if n > 0:
        if n >= self._scope_in.size:
          self._scope_in[:] = chunk[-self._scope_in.size :]
        else:
          self._scope_in = np.roll(self._scope_in, -n)
          self._scope_in[-n:] = chunk

      if self.bypass or self.gate is None:
        filtered = chunk
        meta = {"p": 0.0, "snr": 0.0, "flat": 0.0, "open": True, "gain": 1.0, "bypass": True}
      else:
        filtered, meta = self.gate.process_chunk(chunk)
        meta["bypass"] = False

      if filtered.size > 0:
        n2 = filtered.size
        if n2 >= self._scope_out.size:
          self._scope_out[:] = filtered[-self._scope_out.size :]
        else:
          self._scope_out = np.roll(self._scope_out, -n2)
          self._scope_out[-n2:] = filtered
        out48 = _resample(filtered, PROC_FS, CAPTURE_FS)
        if self._play and self._play.stdin:
          try:
            self._play.stdin.write(out48.tobytes())
          except BrokenPipeError:
            break

      self.tick.emit(self._scope_in.copy(), self._scope_out.copy(), meta)

    if self._cap:
      self._cap.stop()
    if self._play:
      try:
        if self._play.stdin:
          self._play.stdin.close()
        self._play.terminate()
      except Exception:
        pass


class MetricBar(QtWidgets.QWidget):
  """0..1 skálás sáv címkével."""

  def __init__(self, title: str, color: str = "#3fb950", parent=None) -> None:
    super().__init__(parent)
    self._val = 0.0
    self._color = color
    self._title = title
    self.setMinimumHeight(22)
    self.setMaximumHeight(28)

  def set_value(self, v: float, text: str = "") -> None:
    self._val = float(np.clip(v, 0.0, 1.0))
    self._text = text
    self.update()

  def paintEvent(self, event) -> None:  # noqa: ARG002
    p = QtGui.QPainter(self)
    w, h = self.width(), self.height()
    p.fillRect(0, 0, w, h, QtGui.QColor("#161b22"))
    p.setPen(QtGui.QColor("#8b949e"))
    p.drawText(4, 14, self._title)
    bx, bw = 90, w - 98
    p.fillRect(bx, 6, bw, h - 12, QtGui.QColor("#21262d"))
    fw = int(bw * self._val)
    if fw > 0:
      p.fillRect(bx, 6, fw, h - 12, QtGui.QColor(self._color))
    if getattr(self, "_text", ""):
      p.setPen(QtGui.QColor("#c9d1d9"))
      p.drawText(bx + 4, h - 8, self._text)
    p.end()


class GateMainWindow(QtWidgets.QMainWindow):
  def __init__(self) -> None:
    super().__init__()
    self.setWindowTitle("CW CUDA zajkapu → GGMorse")
    self.resize(720, 620)
    self.gate = CwNoiseGate(GateConfig())
    self.worker = GateWorker()
    self.worker.tick.connect(self._on_tick)
    self.worker.error.connect(self._on_error)

    central = QtWidgets.QWidget()
    self.setCentralWidget(central)
    root = QtWidgets.QVBoxLayout(central)

    row = QtWidgets.QHBoxLayout()
    self.combo_in = QtWidgets.QComboBox()
    self.btn_start = QtWidgets.QPushButton("▶ Kapu + kimenet")
    self.btn_stop = QtWidgets.QPushButton("⏹ Stop")
    self.btn_stop.setEnabled(False)
    self.chk_bypass = QtWidgets.QCheckBox("Bypass (nyers hang → GGMorse)")
    row.addWidget(QtWidgets.QLabel("Bemenet:"))
    row.addWidget(self.combo_in, stretch=1)
    row.addWidget(self.chk_bypass)
    row.addWidget(self.btn_start)
    row.addWidget(self.btn_stop)
    root.addLayout(row)

    hint = QtWidgets.QLabel(
      f"Kimenet: PipeWire „{SINK_NAME}” → GGMorse capture. "
      "Zöld = kapu nyitva, kék/szürke = zárva / csend."
    )
    hint.setWordWrap(True)
    root.addWidget(hint)

    self.lbl_state = QtWidgets.QLabel("Állapot: kész")
    f = QtGui.QFont()
    f.setPointSize(12)
    f.setBold(True)
    self.lbl_state.setFont(f)
    root.addWidget(self.lbl_state)

    self.bar_p = MetricBar("P(CW)")
    self.bar_snr = MetricBar("SNR", "#58a6ff")
    self.bar_gain = MetricBar("Gain", "#d29922")
    self.bar_flat = MetricBar("Tónus", "#a371f7")
    for b in (self.bar_p, self.bar_snr, self.bar_gain, self.bar_flat):
      root.addWidget(b)

    root.addWidget(QtWidgets.QLabel("Bemenet (monitor)"))
    self.scope_in = WaveformScope()
    root.addWidget(self.scope_in)

    root.addWidget(QtWidgets.QLabel("Kimenet (→ GGMorse)"))
    self.scope_out = WaveformScope()
    root.addWidget(self.scope_out)

    scroll = QtWidgets.QScrollArea()
    scroll.setWidgetResizable(True)
    sl = QtWidgets.QWidget()
    form = QtWidgets.QFormLayout(sl)
    self._sliders: dict[str, QtWidgets.QSlider] = {}

    def add_slider(key: str, label: str, lo: int, hi: int, val: float, scale: float = 100.0):
      s = QtWidgets.QSlider(QtCore.Qt.Horizontal)
      s.setRange(lo, hi)
      s.setValue(int(val * scale))
      lbl = QtWidgets.QLabel(f"{val:.2f}")
      s.valueChanged.connect(lambda v, k=key, l=lbl, sc=scale: self._slider_changed(k, v, l, sc))
      row_w = QtWidgets.QHBoxLayout()
      row_w.addWidget(s)
      row_w.addWidget(lbl)
      w = QtWidgets.QWidget()
      w.setLayout(row_w)
      form.addRow(label, w)
      self._sliders[key] = s
      self._slider_labels = getattr(self, "_slider_labels", {})
      self._slider_labels[key] = lbl

    c = self.gate.cfg
    add_slider("open_threshold", "Nyitás P küszöb", 20, 95, c.open_threshold)
    add_slider("close_threshold", "Zárás P küszöb", 10, 90, c.close_threshold)
    add_slider("min_snr_db", "Min SNR (dB)", 0, 200, c.min_snr_db, 10.0)
    add_slider("max_flatness", "Max lapos spektrum", 20, 95, c.max_flatness)
    add_slider("attack_ms", "Attack (ms)", 5, 200, c.attack_ms, 1.0)
    add_slider("release_ms", "Release (ms)", 50, 600, c.release_ms, 1.0)
    add_slider("frame_ms", "Keret (ms)", 40, 150, c.frame_ms, 1.0)

    scroll.setWidget(sl)
    root.addWidget(QtWidgets.QLabel("Finomhangolás"))
    root.addWidget(scroll, stretch=1)

    self.btn_start.clicked.connect(self._start)
    self.btn_stop.clicked.connect(self._stop)
    self._fill_sources()

  def _slider_changed(self, key: str, v: int, lbl: QtWidgets.QLabel, scale: float) -> None:
    val = v / scale
    lbl.setText(f"{val:.2f}" if scale >= 10 else f"{val:.1f}")
    setattr(self.gate.cfg, key, val)
    if key == "frame_ms":
      self.gate._frame = max(256, int(self.gate.cfg.fs * val / 1000.0))

  def _fill_sources(self) -> None:
    self.combo_in.clear()
    best = pick_recommended_monitor(list_pulse_sources())
    pick_key = best.name if best else None
    for s in list_pulse_sources():
      if s.is_mic and not s.is_monitor:
        continue
      if "alsa_input" in s.name and ".monitor" not in s.name:
        continue
      tag = " ★" if best and s.name == best.name else ""
      self.combo_in.addItem(f"{s.name} [{s.state}]{tag}", s.name)
    if pick_key:
      for i in range(self.combo_in.count()):
        if self.combo_in.itemData(i) == pick_key:
          self.combo_in.setCurrentIndex(i)
          break

  def _source_name(self) -> str:
    v = self.combo_in.currentData()
    if v:
      return str(v)
    best = pick_recommended_monitor(list_pulse_sources())
    return best.name if best else ""

  def _start(self) -> None:
    src = self._source_name()
    if not src:
      self.lbl_state.setText("Nincs monitor forrás")
      return
    self.worker.configure(self.gate, src)
    self.worker.bypass = self.chk_bypass.isChecked()
    self.btn_start.setEnabled(False)
    self.btn_stop.setEnabled(True)
    self.worker.start()

  def _stop(self) -> None:
    self.worker.stop_work()
    self.worker.wait(3000)
    self.btn_start.setEnabled(True)
    self.btn_stop.setEnabled(False)
    self.lbl_state.setText("Állapot: leállítva")

  def _on_error(self, msg: str) -> None:
    self.lbl_state.setText(f"Hiba: {msg}")
    self._stop()

  def _on_tick(self, wave_in: np.ndarray, wave_out: np.ndarray, meta: dict) -> None:
    self.worker.bypass = self.chk_bypass.isChecked()
    rms_in = float(np.sqrt(np.mean(wave_in * wave_in))) if wave_in.size else 0.0
    rms_out = float(np.sqrt(np.mean(wave_out * wave_out))) if wave_out.size else 0.0
    open_ = bool(meta.get("open", False)) or bool(meta.get("bypass"))
    self.scope_in.update_scope(wave_in, rms_in, rms_in > 0.002)
    self.scope_out.update_scope(wave_out, rms_out, open_ and rms_out > 0.0003)

    p = float(meta.get("p", 0))
    snr = float(meta.get("snr", 0))
    flat = float(meta.get("flat", 1))
    gain = float(meta.get("gain", 0))

    self.bar_p.set_value(p, f"{p:.2f}")
    self.bar_snr.set_value(min(1.0, snr / 20.0), f"{snr:.1f} dB")
    self.bar_gain.set_value(gain, f"{gain:.2f}")
    self.bar_flat.set_value(1.0 - flat, f"flat {flat:.2f}")

    if meta.get("bypass"):
      self.lbl_state.setText("BYPASS — nyers hang megy GGMorse-ra")
      self.lbl_state.setStyleSheet("color: #d29922;")
    elif meta.get("open"):
      self.lbl_state.setText(f"● KAPU NYITVA  gain={gain:.2f}  P={p:.2f}  SNR={snr:.1f} dB")
      self.lbl_state.setStyleSheet("color: #3fb950;")
    else:
      self.lbl_state.setText(f"○ KAPU ZÁRVA (csend → GGMorse)  P={p:.2f}  SNR={snr:.1f} dB")
      self.lbl_state.setStyleSheet("color: #8b949e;")

  def closeEvent(self, event) -> None:
    self._stop()
    super().closeEvent(event)


def main() -> int:
  app = QtWidgets.QApplication(sys.argv)
  w = GateMainWindow()
  w.show()
  return app.exec_()


if __name__ == "__main__":
  raise SystemExit(main())
