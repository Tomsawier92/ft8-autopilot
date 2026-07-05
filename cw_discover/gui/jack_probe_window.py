"""Jack / line-in láb azonosító — TIP (L) vs RING (R) élő jelszint + CW boríték."""
from __future__ import annotations

import subprocess
import sys

import numpy as np
from PyQt5 import QtCore, QtGui, QtWidgets
from scipy.signal import butter, sosfilt

from cw_discover.audio.pulse_sources import list_pulse_sources
from cw_discover.audio.stereo_capture import StereoPulseCapture

FS = 48_000
# CW sáv + boríték simítás (~4 ms) — dit/dah csúcsok láthatók
_CW_SOS = butter(4, [350, 1200], btype="band", fs=FS, output="sos")
_ENV_KERNEL = np.ones(int(0.004 * FS), dtype=np.float32) / max(1, int(0.004 * FS))


def _set_line_in_port(pulse_name: str) -> None:
  subprocess.run(
    ["pactl", "set-source-port", pulse_name, "analog-input-linein"],
    capture_output=True,
  )


def _rms(x: np.ndarray) -> float:
  if x.size == 0:
    return 0.0
  return float(np.sqrt(np.mean(x * x)))


def _peak(x: np.ndarray) -> float:
  if x.size == 0:
    return 0.0
  return float(np.max(np.abs(x)))


def _cw_envelope(x: np.ndarray) -> np.ndarray:
  """CW hang sávból boríték — a morse kiugrások (ON/OFF) ezen látszanak."""
  if x.size == 0:
    return x
  xf = sosfilt(_CW_SOS, x.astype(np.float64, copy=False)).astype(np.float32)
  env = np.abs(xf)
  if _ENV_KERNEL.size > 1:
    env = np.convolve(env, _ENV_KERNEL, mode="same")
  return env


def _downsample_max(x: np.ndarray, n_out: int) -> np.ndarray:
  if x.size == 0 or n_out <= 0:
    return np.zeros(max(n_out, 0), dtype=np.float32)
  if x.size <= n_out:
    return x.astype(np.float32, copy=False)
  edges = np.linspace(0, x.size, n_out + 1, dtype=int)
  out = np.empty(n_out, dtype=np.float32)
  for i in range(n_out):
    chunk = x[edges[i] : edges[i + 1]]
    out[i] = float(np.max(chunk)) if chunk.size else 0.0
  return out


class LevelBar(QtWidgets.QWidget):
  def __init__(self, title: str, color: str, parent=None) -> None:
    super().__init__(parent)
    self._title = title
    self._color = QtGui.QColor(color)
    self._rms = 0.0
    self._peak = 0.0
    self._peak_hold = 0.0
    self._active = False
    self.setMinimumHeight(72)

  def set_levels(self, rms: float, peak: float, active: bool) -> None:
    self._rms = rms
    self._peak = peak
    self._peak_hold = max(self._peak_hold * 0.96, peak)
    self._active = active
    self.update()

  def reset_peak_hold(self) -> None:
    self._peak_hold = 0.0
    self.update()

  def paintEvent(self, event) -> None:  # noqa: ARG002
    p = QtGui.QPainter(self)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    w, h = self.width(), self.height()
    p.fillRect(0, 0, w, h, QtGui.QColor("#161b22"))
    p.setPen(QtGui.QColor("#8b949e"))
    p.drawText(8, 16, self._title)

    bar_y, bar_h = 24, h - 36
    p.setPen(QtCore.Qt.NoPen)
    p.setBrush(QtGui.QColor("#21262d"))
    p.drawRoundedRect(8, bar_y, w - 16, bar_h, 4, 4)

    # dB skála ~ -60..0 dBFS (RMS)
    db = 20.0 * np.log10(max(self._rms, 1e-8))
    frac = np.clip((db + 60.0) / 60.0, 0.0, 1.0)
    fill_w = int((w - 16) * frac)
    col = self._color if self._active else QtGui.QColor("#484f58")
    p.setBrush(col)
    if fill_w > 0:
      p.drawRoundedRect(8, bar_y, fill_w, bar_h, 4, 4)

    ph_db = 20.0 * np.log10(max(self._peak_hold, 1e-8))
    ph_frac = np.clip((ph_db + 60.0) / 60.0, 0.0, 1.0)
    ph_x = 8 + int((w - 16) * ph_frac)
    p.setPen(QtGui.QPen(QtGui.QColor("#f0f6fc"), 2))
    p.drawLine(ph_x, bar_y, ph_x, bar_y + bar_h)

    p.setPen(QtGui.QColor("#c9d1d9"))
    status = "● JEL" if self._active else "○ csend"
    p.drawText(8, h - 6, f"RMS {self._rms:.5f}  peak {self._peak:.3f}  {status}")
    p.end()


class JackDiagram(QtWidgets.QWidget):
  """3,5 mm TRS dugó — TIP / RING / SLEEVE kiemelés."""

  def __init__(self, parent=None) -> None:
    super().__init__(parent)
    self._tip_on = False
    self._ring_on = False
    self.setMinimumSize(220, 280)

  def set_active(self, tip: bool, ring: bool) -> None:
    self._tip_on = tip
    self._ring_on = ring
    self.update()

  def paintEvent(self, event) -> None:  # noqa: ARG002
    p = QtGui.QPainter(self)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    w, h = self.width(), self.height()
    p.fillRect(0, 0, w, h, QtGui.QColor("#0d1117"))

    cx = w // 2
    p.setPen(QtGui.QColor("#c9d1d9"))
    p.setFont(QtGui.QFont("Sans", 11, QtGui.QFont.Bold))
    p.drawText(cx - 90, 22, "3,5 mm TRS jack (dugó)")

    # dugó test
    plug_w, plug_h = 44, 160
    px = cx - plug_w // 2
    py = 50
    p.setPen(QtGui.QPen(QtGui.QColor("#8b949e"), 2))
    p.setBrush(QtGui.QColor("#30363d"))
    p.drawRoundedRect(px, py, plug_w, plug_h, 6, 6)

    # szegmensek (felülről: csúcs, gyűrű, tok)
    tip_h = 36
    ring_h = 28
    sleeve_y = py + tip_h + ring_h

    tip_col = QtGui.QColor("#3fb950") if self._tip_on else QtGui.QColor("#484f58")
    ring_col = QtGui.QColor("#58a6ff") if self._ring_on else QtGui.QColor("#484f58")

    p.setPen(QtCore.Qt.NoPen)
    p.setBrush(tip_col)
    p.drawRect(px + 4, py + 4, plug_w - 8, tip_h)
    p.setBrush(ring_col)
    p.drawRect(px + 4, py + tip_h + 2, plug_w - 8, ring_h)
    p.setBrush(QtGui.QColor("#6e7681"))
    p.drawRect(px + 4, sleeve_y, plug_w - 8, plug_h - tip_h - ring_h - 8)

    p.setPen(QtGui.QColor("#f0f6fc"))
    p.setFont(QtGui.QFont("Monospace", 10))
    labels = [
      (py + tip_h // 2 + 4, "TIP (csúcs)", "Bal csatorna / L"),
      (py + tip_h + ring_h // 2 + 4, "RING (gyűrű)", "Jobb csatorna / R"),
      (sleeve_y + 30, "SLEEVE (tok)", "Föld / GND"),
    ]
    for y, title, sub in labels:
      p.drawText(px + plug_w + 12, y, title)
      p.setPen(QtGui.QColor("#8b949e"))
      p.drawText(px + plug_w + 12, y + 16, sub)
      p.setPen(QtGui.QColor("#f0f6fc"))

    p.end()


class EnvelopeScope(QtWidgets.QWidget):
  """CW boríték — morse csúcsok / csendek (nem a 700 Hz sinus)."""

  def __init__(self, title: str, color: str, parent=None) -> None:
    super().__init__(parent)
    self._title = title
    self._color = color
    self._env = np.zeros(900, dtype=np.float32)
    self._thresh = 0.0
    self.setMinimumHeight(110)
    self.setMaximumHeight(130)

  def set_envelope(self, env: np.ndarray, thresh: float) -> None:
    if env.size:
      self._env = np.asarray(env, dtype=np.float32).ravel()
    self._thresh = thresh
    self.update()

  def paintEvent(self, event) -> None:  # noqa: ARG002
    p = QtGui.QPainter(self)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    w, h = self.width(), self.height()
    p.fillRect(0, 0, w, h, QtGui.QColor("#0d1117"))
    p.setPen(QtGui.QColor("#8b949e"))
    p.drawText(8, 14, self._title)

    base_y = h - 8
    top_y = 22
    plot_h = base_y - top_y - 4
    if self._env.size < 4 or plot_h < 10:
      p.end()
      return

    ymax = max(float(np.percentile(self._env, 99.5)) * 1.15, self._thresh * 2, 0.005)
    xs = np.linspace(8, w - 8, self._env.size)
    ys = base_y - (self._env / ymax) * plot_h

    # küszöb vonal
    if self._thresh > 0:
      ty = base_y - (self._thresh / ymax) * plot_h
      p.setPen(QtGui.QPen(QtGui.QColor("#484f58"), 1, QtCore.Qt.DashLine))
      p.drawLine(8, int(ty), w - 8, int(ty))

    path = QtGui.QPainterPath()
    path.moveTo(float(xs[0]), float(base_y))
    for i in range(len(xs)):
      path.lineTo(float(xs[i]), float(ys[i]))
    path.lineTo(float(xs[-1]), float(base_y))
    p.setPen(QtCore.Qt.NoPen)
    p.setBrush(QtGui.QColor(self._color + "55"))
    p.drawPath(path)

    p.setPen(QtGui.QPen(QtGui.QColor(self._color), 1.8))
    for i in range(1, len(xs)):
      p.drawLine(int(xs[i - 1]), int(ys[i - 1]), int(xs[i]), int(ys[i]))
    p.end()


class JackProbeWindow(QtWidgets.QMainWindow):
  THRESH_ENV = 0.004
  THRESH_RATIO = 2.5
  ENV_HISTORY = int(FS * 2.0)  # ~2 mp boríték görbe

  def __init__(self) -> None:
    super().__init__()
    self.setWindowTitle("Jack / Line-in láb azonosító + CW boríték")
    self.resize(860, 720)
    self._cap: StereoPulseCapture | None = None
    self._pulse_name = ""
    self._env_left_buf = np.zeros(self.ENV_HISTORY, dtype=np.float32)
    self._env_right_buf = np.zeros(self.ENV_HISTORY, dtype=np.float32)
    self._noise_floor = 0.001

    central = QtWidgets.QWidget()
    self.setCentralWidget(central)
    root = QtWidgets.QVBoxLayout(central)

    hint = QtWidgets.QLabel(
      "Jack láb azonosítás: TIP=csúcs/L, RING=gyűrű/R. "
      "CW/morse-nál a felső **boríték** grafikon mutatja a dit/dah csúcsokat "
      "(a nyers 700 Hz hang sűrűnek tűnik — az normális)."
    )
    hint.setWordWrap(True)
    root.addWidget(hint)

    row = QtWidgets.QHBoxLayout()
    self.combo_src = QtWidgets.QComboBox()
    self.btn_refresh = QtWidgets.QPushButton("↻")
    self.btn_linein = QtWidgets.QPushButton("Line-in port")
    self.btn_start = QtWidgets.QPushButton("▶ Figyelés")
    self.btn_stop = QtWidgets.QPushButton("⏹ Stop")
    self.btn_stop.setEnabled(False)
    self.btn_reset = QtWidgets.QPushButton("Peak nullázás")
    row.addWidget(QtWidgets.QLabel("Bemenet:"))
    row.addWidget(self.combo_src, stretch=1)
    row.addWidget(self.btn_refresh)
    row.addWidget(self.btn_linein)
    row.addWidget(self.btn_start)
    row.addWidget(self.btn_stop)
    row.addWidget(self.btn_reset)
    root.addLayout(row)

    self.lbl_verdict = QtWidgets.QLabel("Állapot: —")
    f = QtGui.QFont()
    f.setPointSize(16)
    f.setBold(True)
    self.lbl_verdict.setFont(f)
    self.lbl_verdict.setAlignment(QtCore.Qt.AlignCenter)
    root.addWidget(self.lbl_verdict)

    body = QtWidgets.QHBoxLayout()
    self.diagram = JackDiagram()
    body.addWidget(self.diagram, stretch=0)

    meters = QtWidgets.QVBoxLayout()
    self.scope_env_l = EnvelopeScope("CW boríték — TIP / Bal (L)  [morse csúcsok]", "#3fb950")
    self.bar_left = LevelBar("TIP / Csúcs — boríték szint (L)", "#3fb950")
    self.scope_env_r = EnvelopeScope("CW boríték — RING / Jobb (R)", "#58a6ff")
    self.bar_right = LevelBar("RING / Gyűrű — boríték szint (R)", "#58a6ff")
    self.bar_mono = LevelBar("Mono boríték (L+R)/2", "#d29922")
    self.lbl_keying = QtWidgets.QLabel("Kulcsolás: —")
    for w in (
      self.scope_env_l,
      self.bar_left,
      self.scope_env_r,
      self.bar_right,
      self.bar_mono,
      self.lbl_keying,
    ):
      meters.addWidget(w)
    body.addLayout(meters, stretch=1)
    root.addLayout(body, stretch=1)

    self.lbl_log = QtWidgets.QLabel(
      "Ha van jel de lapos a görbe: ellenőrizd a Line-in portot. "
      "A szintmérő a CW borítékot mutatja (nem a nyers hangero RMS-t)."
    )
    self.lbl_log.setWordWrap(True)
    root.addWidget(self.lbl_log)

    self.btn_refresh.clicked.connect(self._fill_sources)
    self.btn_linein.clicked.connect(self._apply_line_in)
    self.btn_start.clicked.connect(self._start)
    self.btn_stop.clicked.connect(self._stop)
    self.btn_reset.clicked.connect(self._reset_peaks)

    self._timer = QtCore.QTimer(self)
    self._timer.setInterval(40)
    self._timer.timeout.connect(self._tick)

    self._fill_sources()

  def _fill_sources(self) -> None:
    self.combo_src.clear()
    for s in list_pulse_sources():
      if "ggmorse" in s.name.lower():
        continue
      tag = []
      if s.is_monitor:
        tag.append("MONITOR")
      elif s.is_mic or "alsa_input" in s.name:
        tag.append("LINE-IN")
      st = f" [{s.state}]" if s.state else ""
      self.combo_src.addItem(f"{'/'.join(tag) or 'SRC'}: {s.name}{st}", s.name)

    # alap: alsa_input
    for i in range(self.combo_src.count()):
      name = self.combo_src.itemData(i)
      if name and "alsa_input" in str(name):
        self.combo_src.setCurrentIndex(i)
        break

  def _apply_line_in(self) -> None:
    name = self.combo_src.currentData()
    if name and "alsa_input" in str(name):
      _set_line_in_port(str(name))
      self.lbl_log.setText(f"Line-in port beállítva: {name}")
    else:
      self.lbl_log.setText("Line-in port csak alsa_input forrásnál értelmes.")

  def _start(self) -> None:
    self._stop()
    name = self.combo_src.currentData()
    if not name:
      return
    self._pulse_name = str(name)
    if "alsa_input" in self._pulse_name:
      _set_line_in_port(self._pulse_name)
    try:
      self._cap = StereoPulseCapture(self._pulse_name)
      self._cap.start()
    except Exception as e:
      self.lbl_verdict.setText(f"Hiba: {e}")
      return
    self.btn_start.setEnabled(False)
    self.btn_stop.setEnabled(True)
    self._timer.start()
    self.lbl_log.setText(f"Figyelés: {self._pulse_name}")

  def _stop(self) -> None:
    self._timer.stop()
    if self._cap is not None:
      self._cap.stop()
      self._cap = None
    self.btn_start.setEnabled(True)
    self.btn_stop.setEnabled(False)

  def _reset_peaks(self) -> None:
    self.bar_left.reset_peak_hold()
    self.bar_right.reset_peak_hold()
    self.bar_mono.reset_peak_hold()

  def _tick(self) -> None:
    if self._cap is None:
      return
    chunks_l: list[np.ndarray] = []
    chunks_r: list[np.ndarray] = []
    for _ in range(4):
      got = self._cap.read(timeout=0.02)
      if got is None:
        break
      l, r = got
      chunks_l.append(l)
      chunks_r.append(r)
    if not chunks_l:
      return

    left = np.concatenate(chunks_l)
    right = np.concatenate(chunks_r)
    mono = (left + right) * 0.5

    env_l = _cw_envelope(left)
    env_r = _cw_envelope(right)
    env_m = (env_l + env_r) * 0.5

    # ~2 mp gördülő boríték buffer
    n = min(len(env_l), 4800)
    self._env_left_buf = np.concatenate([self._env_left_buf[n:], env_l[-n:]])
    self._env_right_buf = np.concatenate([self._env_right_buf[n:], env_r[-n:]])

    disp_l = _downsample_max(self._env_left_buf, 900)
    disp_r = _downsample_max(self._env_right_buf, 900)

    # adaptív küszöb a mono borítékból
    nf = float(np.percentile(env_m, 25))
    sp = float(np.percentile(env_m, 95))
    self._noise_floor = 0.92 * self._noise_floor + 0.08 * nf
    thresh = max(self.THRESH_ENV, self._noise_floor + 0.25 * max(sp - self._noise_floor, 0.0))

    rms_l, peak_l = _rms(env_l), _peak(env_l)
    rms_r, peak_r = _rms(env_r), _peak(env_r)
    rms_m = _rms(env_m)

    act_l = peak_l >= thresh
    act_r = peak_r >= thresh
    on = env_m > thresh
    edges = int(np.sum(np.abs(np.diff(on.astype(int)))))
    on_pct = float(np.mean(on)) * 100.0

    self.scope_env_l.set_envelope(disp_l, thresh)
    self.scope_env_r.set_envelope(disp_r, thresh)
    self.bar_left.set_levels(rms_l, peak_l, act_l)
    self.bar_right.set_levels(rms_r, peak_r, act_r)
    self.bar_mono.set_levels(rms_m, max(peak_l, peak_r), act_l or act_r)

    if act_l or act_r:
      if edges > 8 and on_pct < 95:
        key_txt = f"Kulcsolás: ON {on_pct:.0f}%  |  {edges} él/ blokk — morse csúcsok látszanak"
      elif on_pct >= 95:
        key_txt = f"Folyamatos hang (nincs morse szünet) — ON {on_pct:.0f}%"
      else:
        key_txt = f"Gyenge kulcsolás — ON {on_pct:.0f}%"
    else:
      key_txt = "Kulcsolás: nincs jel a CW sávban"
    self.lbl_keying.setText(key_txt)

    tip_on = act_l and (peak_l >= peak_r / self.THRESH_RATIO or not act_r)
    ring_on = act_r and (peak_r >= peak_l / self.THRESH_RATIO or not act_l)
    if act_l and act_r and abs(peak_l - peak_r) / max(peak_l, peak_r, 1e-9) < 0.35:
      tip_on = ring_on = True

    self.diagram.set_active(tip_on, ring_on)

    if not act_l and not act_r:
      verdict = "Nincs jel — kösd a dugót / érintsd a lábakat"
      col = "#8b949e"
    elif tip_on and not ring_on:
      verdict = "► TIP (csúcs) / BAL (L) — ide van kötve a jel!"
      col = "#3fb950"
    elif ring_on and not tip_on:
      verdict = "► RING (gyűrű) / JOBB (R) — ide van kötve a jel!"
      col = "#58a6ff"
    else:
      verdict = "Mindkét csatornán jel (mono / mindkét láb / közös föld)"
      col = "#d29922"

    self.lbl_verdict.setText(verdict)
    self.lbl_verdict.setStyleSheet(f"color: {col};")

  def closeEvent(self, event) -> None:  # noqa: ARG002
    self._stop()


def main() -> int:
  app = QtWidgets.QApplication(sys.argv)
  app.setStyle("Fusion")
  w = JackProbeWindow()
  w.show()
  return app.exec_()


if __name__ == "__main__":
  raise SystemExit(main())
