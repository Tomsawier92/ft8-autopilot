"""Egyszerű hullámforma scope — QPainter, matplotlib nélkül."""
from __future__ import annotations

import numpy as np
from PyQt5 import QtCore, QtGui, QtWidgets


class WaveformScope(QtWidgets.QWidget):
  def __init__(self, parent=None) -> None:
    super().__init__(parent)
    self.setMinimumHeight(100)
    self.setMaximumHeight(140)
    self._wave = np.zeros(1200, dtype=np.float32)
    self._rms = 0.0
    self._active = False
    self.setStyleSheet("background: #0d1117; border: 1px solid #30363d; border-radius: 4px;")

  def update_scope(self, wave: np.ndarray, rms: float, active: bool) -> None:
    if wave.size:
      self._wave = np.asarray(wave, dtype=np.float32).ravel()
    self._rms = rms
    self._active = active
    self.update()

  def paintEvent(self, event) -> None:  # noqa: ARG002
    p = QtGui.QPainter(self)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    w, h = self.width(), self.height()
    p.fillRect(0, 0, w, h, QtGui.QColor("#0d1117"))

    mid = h // 2
    p.setPen(QtGui.QPen(QtGui.QColor("#21262d"), 1, QtCore.Qt.DashLine))
    p.drawLine(0, mid, w, mid)

    if self._wave.size < 4:
      p.setPen(QtGui.QColor("#8b949e"))
      p.drawText(8, mid, "Nincs jel / várakozás…")
      p.end()
      return

    x = np.linspace(0, w - 1, self._wave.size)
    ymax = float(np.percentile(np.abs(self._wave), 98)) + 1e-9
    ymax = max(ymax, 0.02)
    y = mid - (self._wave / ymax) * (h * 0.42)

    color = QtGui.QColor("#3fb950") if self._active else QtGui.QColor("#58a6ff")
    if self._rms < 0.0005:
      color = QtGui.QColor("#484f58")
    pen = QtGui.QPen(color, 1.5)
    p.setPen(pen)
    path = QtGui.QPainterPath()
    path.moveTo(float(x[0]), float(y[0]))
    for i in range(1, len(x)):
      path.lineTo(float(x[i]), float(y[i]))
    p.drawPath(path)

    p.setPen(QtGui.QColor("#c9d1d9"))
    status = "JEL VAN" if self._active else "csend"
    p.drawText(8, 16, f"RMS: {self._rms:.4f}  |  {status}")
    p.end()
