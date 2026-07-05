"""Mintázatfelismerő GUI — klaszterek, forrásváltás, mentés."""
from __future__ import annotations

import sys

import numpy as np
from PyQt5 import QtCore, QtGui, QtWidgets

from cw_discover.audio.devices import default_capture_source, list_input_devices
from cw_discover.audio.source import CaptureSource
from cw_discover.discover.engine import DiscoveryEngine
from cw_discover.gui.scope_widget import WaveformScope


class MainWindow(QtWidgets.QMainWindow):
  def __init__(self) -> None:
    super().__init__()
    self.setWindowTitle("CW Mintázatfelismerő — line-in")
    self.resize(780, 600)
    self.engine = DiscoveryEngine()

    central = QtWidgets.QWidget()
    self.setCentralWidget(central)
    root = QtWidgets.QVBoxLayout(central)

    row = QtWidgets.QHBoxLayout()
    self.combo_in = QtWidgets.QComboBox()
    self.btn_refresh = QtWidgets.QPushButton("↻")
    self.btn_refresh.setToolTip("Bemenetek frissítése")
    self.btn_apply = QtWidgets.QPushButton("Forrás alkalmazása")
    self.btn_apply.setToolTip("Tanítás közben is — WebSDR / más kimenet")
    self.btn_start = QtWidgets.QPushButton("▶ Figyelés")
    self.btn_stop = QtWidgets.QPushButton("⏹ Stop")
    self.btn_stop.setEnabled(False)
    row.addWidget(QtWidgets.QLabel("Bemenet:"))
    row.addWidget(self.combo_in, stretch=1)
    row.addWidget(self.btn_refresh)
    row.addWidget(self.btn_apply)
    row.addWidget(self.btn_start)
    row.addWidget(self.btn_stop)
    root.addLayout(row)

    hint = QtWidgets.QLabel(
      "WebSDR: ◆ AJÁNLOTT monitor. Alapgerinc: ITU betűk/számok/prosignok @ 10–25 WPM "
      "(scripts/train_backbone.py). A line-in tanítás erre épül."
    )
    hint.setWordWrap(True)
    root.addWidget(hint)

    self.lbl_big = QtWidgets.QLabel("Klaszterek: —")
    f = QtGui.QFont()
    f.setPointSize(18)
    f.setBold(True)
    self.lbl_big.setFont(f)
    root.addWidget(self.lbl_big)

    self.lbl_scope_title = QtWidgets.QLabel("Hullámforma (line-in élő)")
    root.addWidget(self.lbl_scope_title)
    self.scope = WaveformScope()
    root.addWidget(self.scope)

    self.lbl_feed = QtWidgets.QLabel("Állapot: kész")
    root.addWidget(self.lbl_feed)

    self.lbl_save = QtWidgets.QLabel("Mentés: RAM-ban tanul → lemez ~90 s vagy +400 szegmens (atomi)")
    root.addWidget(self.lbl_save)

    self.text = QtWidgets.QPlainTextEdit()
    self.text.setReadOnly(True)
    self.text.setFont(QtGui.QFont("Monospace", 10))
    root.addWidget(self.text, stretch=1)

    self.btn_refresh.clicked.connect(self._fill_devices)
    self.btn_apply.clicked.connect(self._apply_source)
    self.btn_start.clicked.connect(self._start)
    self.btn_stop.clicked.connect(self._stop)
    self._timer = QtCore.QTimer(self)
    self._timer.setInterval(50)
    self._timer.timeout.connect(self._tick)
    self._fill_devices()

  def _fill_devices(self) -> None:
    cur = self.combo_in.currentData()
    self.combo_in.clear()
    rec_key = default_capture_source().storage_key()
    for d in list_input_devices():
      key = d.source.storage_key()
      self.combo_in.addItem(d.label, key)
    pick = cur if cur is not None else rec_key
    for i in range(self.combo_in.count()):
      if self.combo_in.itemData(i) == pick:
        self.combo_in.setCurrentIndex(i)
        break

  def _source(self) -> CaptureSource:
    key = self.combo_in.currentData()
    if key is None:
      return default_capture_source()
    return CaptureSource.from_key(str(key))

  def _apply_source(self) -> None:
    src = self._source()
    if self.engine.stats.running:
      try:
        self.engine.swap_input(src)
        self.lbl_feed.setText(f"Forrás váltva: {self.engine.stats.input_label}")
      except Exception as e:
        self.lbl_feed.setText(f"Forrás hiba: {e}")
    else:
      self.lbl_feed.setText(f"Kiválasztva: {self.combo_in.currentText()}")

  def _start(self) -> None:
    try:
      self.engine.start(self._source())
    except Exception as e:
      self.lbl_feed.setText(f"Line-in hiba: {e}")
      return
    self.btn_start.setEnabled(False)
    self.btn_stop.setEnabled(True)
    self.combo_in.setEnabled(True)
    self._timer.start()

  def _stop(self) -> None:
    self.engine.stop()
    self.btn_start.setEnabled(True)
    self.btn_stop.setEnabled(False)
    self._timer.stop()
    self._tick()

  def _tick(self) -> None:
    s = self.engine.stats
    if s.running:
      wave, rms, active = self.engine.get_scope_snapshot()
      self.scope.update_scope(wave, rms, active)
    else:
      self.scope.update_scope(np.zeros(0), 0.0, False)

    self.lbl_big.setText(f"Klaszterek: {s.n_clusters}")
    loss_s = f"  loss={s.train_loss:.3f}" if s.train_loss is not None else ""
    dirty_s = "  [mentésre vár]" if s.dirty else ""
    cap_s = "● VESZ" if s.running and s.chunks_received > 0 else ("● vár" if s.running else "áll")
    jel_s = " 🟢 JEL" if s.scope_active else (" 🔴 nincs jel" if s.running else "")
    self.lbl_feed.setText(
      f"{cap_s}{jel_s} | {s.input_label} | "
      f"RMS: {s.scope_rms:.4f} | szeg/s: {s.segments_per_sec:.1f} | "
      f"vár: {s.pending_segments} | kivágva: {s.segments_emitted} | "
      f"klaszter: {s.n_clusters} | össz: {s.total_segments}{loss_s}"
    )
    self.lbl_save.setText(
      f"Mentés: utoljára {s.last_save} | atomi → {self.engine.state_path}{dirty_s}"
    )
    if s.error:
      self.lbl_feed.setText(s.error)
    self.text.setPlainText(s.overview or "Várakozás jelre…")
    sb = self.text.verticalScrollBar()
    sb.setValue(sb.maximum())

  def closeEvent(self, event) -> None:
    self.engine.stop()
    super().closeEvent(event)


def main() -> int:
  app = QtWidgets.QApplication(sys.argv)
  w = MainWindow()
  w.show()
  return app.exec_()


if __name__ == "__main__":
  raise SystemExit(main())
