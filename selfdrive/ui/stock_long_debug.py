#!/usr/bin/env python3
import signal
import time
from collections import deque

signal.signal(signal.SIGINT, signal.SIG_DFL)

import cereal.messaging as messaging

from PyQt5.QtCore import QRectF, Qt, QTimer
from PyQt5.QtGui import QColor, QFont, QPainter
from PyQt5.QtWidgets import QApplication, QWidget


CLU11_ADDRESS = 0x4F1
CLU11_BUS = 0
RECENT_WINDOW = 1.0
BUTTON_NAMES = {
  0: "NONE",
  1: "RES/ACCEL",
  2: "SET/DECEL",
  3: "GAP",
  4: "CANCEL",
}
BUTTON_STATES = {
  0: "IDLE",
  1: "INCREASE",
  2: "DECREASE",
  3: "PAUSE",
}


def button_name(button):
  return BUTTON_NAMES.get(int(button), f"UNKNOWN ({button})")


class RotatedDebugWindow(QWidget):
  def __init__(self, screen):
    super().__init__()
    self.lines = []
    self.font = QFont("monospace")
    panel_width = int(screen.width() * 0.36)
    font_size = min(screen.width() // 70, int(panel_width / 15 * 0.75), 32)
    self.font.setPixelSize(max(18, font_size))
    self.font.setBold(True)
    self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus)
    self.setAttribute(Qt.WA_TranslucentBackground)
    self.setAttribute(Qt.WA_TransparentForMouseEvents)

    width = panel_width
    height = int(screen.height() * 0.82)
    self.setGeometry(screen.x() + 24, screen.y() + 80, width, height)

  def setLines(self, lines):
    self.lines = lines
    self.update()

  def paintEvent(self, _event):
    painter = QPainter(self)
    painter.setRenderHint(QPainter.TextAntialiasing)
    painter.translate(self.width(), 0)
    painter.rotate(90)

    content_rect = QRectF(0, 0, self.height(), self.width())
    painter.fillRect(content_rect, QColor(0, 0, 0, 205))
    painter.setPen(QColor("#5ee7ff"))
    painter.drawRect(content_rect.adjusted(1, 1, -1, -1))
    painter.setFont(self.font)
    metrics = painter.fontMetrics()
    line_height = metrics.lineSpacing() + 3
    available_width = int(content_rect.width()) - 32
    y = 16 + metrics.ascent()
    for text, color in self.lines:
      if y + metrics.descent() > content_rect.height() - 12:
        break
      painter.setPen(QColor(color))
      painter.drawText(16, y, metrics.elidedText(text, Qt.ElideRight, available_width))
      y += line_height
    painter.end()


def main():
  app = QApplication([])
  screen = app.primaryScreen().geometry()

  window = RotatedDebugWindow(screen)

  sm = messaging.SubMaster(["carParams", "carState", "sendcan", "can"])
  last_tx_time = None
  last_tx_button = 0
  last_tx_data = ""
  tx_frames = deque()
  last_rx_time = None
  last_rx_button = 0
  last_rx_data = ""
  last_rx_change_time = None
  rx_frames = deque()
  last_speed_change_time = None
  last_speed_change = None
  previous_reported_speed = None
  previous_requested_button = None
  request_started_time = None

  def update():
    nonlocal last_tx_time, last_tx_button, last_tx_data
    nonlocal last_rx_time, last_rx_button, last_rx_data, last_rx_change_time
    nonlocal last_speed_change_time, last_speed_change, previous_reported_speed
    nonlocal previous_requested_button, request_started_time
    sm.update(0)
    now = time.monotonic()

    if sm.updated["sendcan"]:
      for frame in sm["sendcan"]:
        if frame.address == CLU11_ADDRESS and frame.src == CLU11_BUS and len(frame.dat):
          last_tx_button = frame.dat[0] & 0x7
          last_tx_data = bytes(frame.dat).hex(" ")
          last_tx_time = now
          tx_frames.append(now)

    if sm.updated["can"]:
      for frame in sm["can"]:
        if frame.address == CLU11_ADDRESS and frame.src == CLU11_BUS and len(frame.dat):
          button = frame.dat[0] & 0x7
          if button != last_rx_button:
            last_rx_change_time = now
          last_rx_button = button
          last_rx_data = bytes(frame.dat).hex(" ")
          last_rx_time = now
          rx_frames.append(now)

    while tx_frames and now - tx_frames[0] > RECENT_WINDOW:
      tx_frames.popleft()
    while rx_frames and now - rx_frames[0] > RECENT_WINDOW:
      rx_frames.popleft()

    if not sm.updated["carParams"] and not sm.alive["carParams"]:
      window.hide()
      return

    cp = sm["carParams"]
    if not cp.customStockLongAvailable or cp.openpilotLongitudinalControl or not sm.alive["carState"]:
      window.hide()
      return

    cs = sm["carState"]
    debug = cs.customStockLong
    cruise_state = cs.cruiseState
    read_speed_kph = cruise_state.speed * 3.6

    if previous_reported_speed is not None and abs(cruise_state.speed - previous_reported_speed) > 0.01:
      last_speed_change_time = now
      last_speed_change = (previous_reported_speed * 3.6, read_speed_kph)
    previous_reported_speed = cruise_state.speed

    requested_button = int(debug.cruiseButton)
    if requested_button != previous_requested_button:
      request_started_time = now if requested_button else None
      previous_requested_button = requested_button

    tx_age = "never"
    if last_tx_time is not None:
      tx_age = f"{now - last_tx_time:.2f} s ago"
    rx_age = "never"
    if last_rx_time is not None:
      rx_age = f"{now - last_rx_time:.2f} s ago"
    speed_change_age = "never"
    if last_speed_change_time is not None:
      speed_change_age = f"{now - last_speed_change_time:.1f} s ago"
    speed_change = "no change observed"
    if last_speed_change is not None:
      speed_change = f"{last_speed_change[0]:.1f} -> {last_speed_change[1]:.1f} km/h"
    request_age = "not requesting"
    if request_started_time is not None:
      request_age = f"{now - request_started_time:.2f} s"

    tx_color = "#ffc857" if tx_frames else "#9aa0a6"
    rx_color = "#5ee7ff" if rx_frames else "#9aa0a6"
    request_color = "#62e890" if requested_button == 1 else "#ff875e" if requested_button == 2 else "#d7dce2"
    speed_color = "#62e890" if cruise_state.enabled else "#ffcc66"
    change_color = "#62e890" if last_speed_change is not None else "#d7dce2"
    window.setLines([
      ("STOCK LONG DEBUG", "#5ee7ff"),
      (f"[TARGET] Planner {debug.finalSpeedKph:.1f} km/h", "#ffcc66"),
      (f"[CAR] Set speed {read_speed_kph:.1f} km/h - {'ON' if cruise_state.enabled else 'OFF'}", speed_color),
      (f"[CHANGE] {speed_change} ({speed_change_age})", change_color),
      (f"[TRACK] Read {debug.vSetDis:.0f} | target {debug.targetSpeed:.0f} | diff {debug.speedDiff:+.1f}", "#d7dce2"),
      (f"[REQUEST] {button_name(requested_button)} for {request_age}", request_color),
      (f"[STATE] {BUTTON_STATES.get(int(debug.buttonType), str(debug.buttonType))}", "#d7dce2"),
      (f"[TX] Panda queued {button_name(last_tx_button)} ({tx_age})", tx_color),
      (f"[TX] CLU11 {last_tx_data or 'none'}", "#ffc857"),
      (f"[TX] {len(tx_frames)} frames in last second", tx_color),
      (f"[RX] Bus button {button_name(last_rx_button)} ({rx_age})", rx_color),
      (f"[RX] Transition {f'{now - last_rx_change_time:.1f} s ago' if last_rx_change_time is not None else 'never'}", rx_color),
      (f"[RX] CLU11 {last_rx_data or 'none'}", "#5ee7ff"),
      (f"[RX] {len(rx_frames)} frames in last second", rx_color),
      ("[NOTE] CAN seen != cruise accepted", "#ff8c8c"),
    ])
    window.show()

  timer = QTimer()
  timer.timeout.connect(update)
  timer.start(100)
  app.exec_()


if __name__ == "__main__":
  main()
