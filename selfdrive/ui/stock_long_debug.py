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
    self.text = ""
    self.font = QFont("monospace", max(12, min(18, screen.width() // 120)))
    self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus)
    self.setAttribute(Qt.WA_TranslucentBackground)
    self.setAttribute(Qt.WA_TransparentForMouseEvents)

    width = int(screen.width() * 0.28)
    height = int(screen.height() * 0.82)
    self.setGeometry(screen.x() + 24, screen.y() + 80, width, height)

  def setText(self, text):
    self.text = text
    self.update()

  def paintEvent(self, _event):
    painter = QPainter(self)
    painter.setRenderHint(QPainter.TextAntialiasing)
    painter.translate(self.width(), 0)
    painter.rotate(90)

    content_rect = QRectF(0, 0, self.height(), self.width())
    painter.fillRect(content_rect, QColor(0, 0, 0, 205))
    painter.setPen(QColor("#ffcc00"))
    painter.drawRect(content_rect.adjusted(1, 1, -1, -1))
    painter.setPen(QColor("#ffffff"))
    painter.setFont(self.font)
    painter.drawText(content_rect.adjusted(14, 14, -14, -14), Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap, self.text)
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

    window.setText(
      "STOCK LONG DEBUG\n"
      f"Planner target: {debug.finalSpeedKph:.1f} km/h\n"
      f"Car-reported set speed: {read_speed_kph:.1f} km/h "
      f"({'enabled' if cruise_state.enabled else 'disabled'})\n"
      f"Last set-speed change: {speed_change} ({speed_change_age})\n"
      f"Controller read: {debug.vSetDis:.0f} dash units | "
      f"controller target: {debug.targetSpeed:.0f} | diff: {debug.speedDiff:+.1f}\n"
      f"Requested: {button_name(requested_button)} for {request_age}\n"
      f"Button state: {BUTTON_STATES.get(int(debug.buttonType), str(debug.buttonType))}\n"
      f"Panda sendcan queued: {button_name(last_tx_button)} ({tx_age})\n"
      f"TX CLU11 data: {last_tx_data or 'none'}\n"
      f"TX frames seen in last second: {len(tx_frames)}\n"
      f"Bus-observed CLU11: {button_name(last_rx_button)} ({rx_age})\n"
      f"RX button transition: {f'{now - last_rx_change_time:.1f} s ago' if last_rx_change_time is not None else 'never'}\n"
      f"RX CLU11 data: {last_rx_data or 'none'}\n"
      f"Bus CLU11 frames seen in last second: {len(rx_frames)}\n"
      "Bus-observed data is not proof the cruise ECU accepted the command."
    )
    window.show()

  timer = QTimer()
  timer.timeout.connect(update)
  timer.start(100)
  app.exec_()


if __name__ == "__main__":
  main()
