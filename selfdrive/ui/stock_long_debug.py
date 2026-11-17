#!/usr/bin/env python3
import signal
import time

signal.signal(signal.SIGINT, signal.SIG_DFL)

import cereal.messaging as messaging

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget


CLU11_ADDRESS = 0x4F1
CLU11_BUS = 0
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


def main():
  app = QApplication([])
  screen = app.primaryScreen().geometry()

  window = QWidget()
  window.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus)
  window.setAttribute(Qt.WA_TranslucentBackground)
  window.setAttribute(Qt.WA_TransparentForMouseEvents)

  label = QLabel()
  label.setWordWrap(True)
  label.setFont(QFont("monospace", max(16, screen.width() // 100)))
  label.setStyleSheet("""
    QLabel {
      color: #ffffff;
      background-color: rgba(0, 0, 0, 205);
      border: 2px solid #ffcc00;
      padding: 14px;
    }
  """)

  layout = QVBoxLayout(window)
  layout.setContentsMargins(0, 0, 0, 0)
  layout.addWidget(label)
  window.setGeometry(screen.x() + 24, screen.y() + 80, int(screen.width() * 0.42), int(screen.height() * 0.32))

  sm = messaging.SubMaster(["carParams", "carState", "sendcan"])
  last_tx_time = None
  last_tx_button = 0

  def update():
    nonlocal last_tx_time, last_tx_button
    sm.update(0)

    if sm.updated["sendcan"]:
      for frame in sm["sendcan"]:
        if frame.address == CLU11_ADDRESS and frame.src == CLU11_BUS and len(frame.dat):
          last_tx_button = frame.dat[0] & 0x7
          last_tx_time = time.monotonic()

    cp = sm["carParams"]
    if not cp.customStockLongAvailable or cp.openpilotLongitudinalControl:
      window.hide()
      return

    cs = sm["carState"]
    debug = cs.customStockLong
    cruise_state = cs.cruiseState
    read_speed_kph = cruise_state.speed * 3.6
    tx_age = "never"
    if last_tx_time is not None:
      tx_age = f"{time.monotonic() - last_tx_time:.2f} s ago"

    label.setText(
      "STOCK LONG DEBUG\n"
      f"Planner target: {debug.finalSpeedKph:.1f} km/h\n"
      f"Car-reported set speed: {read_speed_kph:.1f} km/h "
      f"({'enabled' if cruise_state.enabled else 'disabled'})\n"
      f"Controller read: {debug.vSetDis:.0f} dash units | "
      f"delta: {debug.speedDiff:+.1f} dash units\n"
      f"Requested button: {button_name(debug.cruiseButton)}\n"
      f"Button state: {BUTTON_STATES.get(int(debug.buttonType), str(debug.buttonType))}\n"
      f"Last outgoing CLU11: {button_name(last_tx_button)} | {tx_age}"
    )
    window.show()

  timer = QTimer()
  timer.timeout.connect(update)
  timer.start(100)
  app.exec_()


if __name__ == "__main__":
  main()
