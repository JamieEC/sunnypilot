#!/usr/bin/env python3
import signal
import time

signal.signal(signal.SIGINT, signal.SIG_DFL)

import cereal.messaging as messaging

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QApplication, QGraphicsScene, QGraphicsView, QLabel


CLU11_ADDRESS = 0x4F1
CLU11_BUS = 0
BUTTON_NAMES = {
  0: "-",
  1: "↑ RES/ACCEL",
  2: "↓ SET/DECEL",
  3: "↔ GAP",
  4: "× CANCEL",
}
BUTTON_STATES = {
  0: "○ IDLE",
  1: "↑ INCREASE",
  2: "↓ DECREASE",
  3: "Ⅱ PAUSE",
}


def button_name(button):
  return BUTTON_NAMES.get(int(button), f"UNKNOWN ({button})")


def main():
  app = QApplication([])
  screen = app.primaryScreen().geometry()

  window = QGraphicsView()
  window.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus)
  window.setAttribute(Qt.WA_TranslucentBackground)
  window.setAttribute(Qt.WA_TransparentForMouseEvents)
  window.setFrameShape(QGraphicsView.NoFrame)
  window.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
  window.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
  window.setAlignment(Qt.AlignLeft | Qt.AlignTop)
  window.setStyleSheet("QGraphicsView { background: transparent; border: none; }")

  scene = QGraphicsScene(window)
  scene.setBackgroundBrush(Qt.transparent)
  window.setScene(scene)

  panel_width = int(screen.width() * 0.48)
  panel_height = int(screen.height() * 0.58)
  label = QLabel()
  label.setWordWrap(True)
  label.setTextFormat(Qt.RichText)
  label.setFont(QFont("monospace", max(22, screen.height() // 45), QFont.DemiBold))
  label.setStyleSheet("""
    QLabel {
      color: #f4f7fb;
      background-color: rgba(7, 12, 18, 238);
      border: 3px solid #ffd166;
      padding: 20px;
    }
  """)

  label.setFixedSize(panel_height, panel_width)
  proxy = scene.addWidget(label)
  proxy.setTransformOriginPoint(proxy.boundingRect().center())
  proxy.setRotation(90)
  rotated_bounds = proxy.mapRectToScene(proxy.boundingRect()).boundingRect()
  proxy.setPos(proxy.pos() - rotated_bounds.topLeft())
  scene.setSceneRect(0, 0, panel_width, panel_height)
  window.setGeometry(screen.x() + 24, screen.y() + 80, panel_width, panel_height)

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
    tx_age = "NEVER"
    tx_color = "#9aa7b5"
    if last_tx_time is not None:
      age_seconds = time.monotonic() - last_tx_time
      tx_age = f"{age_seconds:.1f} s"
      tx_color = "#65e6a5" if age_seconds < 1 else "#ffd166" if age_seconds < 3 else "#ff7373"

    cruise_color = "#65e6a5" if cruise_state.enabled else "#ff7373"
    cruise_status = "● CRUISE ON" if cruise_state.enabled else "○ CRUISE OFF"
    delta_color = "#6dd6ff" if debug.speedDiff > 0 else "#ff9b85" if debug.speedDiff < 0 else "#f4f7fb"
    button_state = int(debug.buttonType)
    button_color = {1: "#65e6a5", 2: "#ff7373", 3: "#ffd166"}.get(button_state, "#c2ccd6")
    base_size = max(22, screen.height() // 45)
    value_size = base_size + 8
    target_size = base_size + 24

    label.setText(
      f"<div style='font-size:{base_size + 12}px; color:#ffd166; font-weight:700'>STOCK LONG DEBUG</div>"
      f"<div style='font-size:{value_size}px; color:{cruise_color}; margin-top:12px'>{cruise_status}</div>"
      f"<div style='margin-top:16px; color:#aab6c3; font-size:{base_size}px'>PLANNER TARGET</div>"
      f"<div style='font-size:{target_size}px; color:#ffd166; font-weight:700'>{debug.finalSpeedKph:.1f} <span style='font-size:{base_size}px'>km/h</span></div>"
      f"<div style='margin-top:12px; font-size:{value_size}px'>SET {read_speed_kph:.1f} km/h</div>"
      f"<div style='margin-top:10px; font-size:{value_size}px'>CTRL {debug.vSetDis:.0f} <span style='color:{delta_color}'>Δ {debug.speedDiff:+.1f}</span> dash</div>"
      f"<div style='margin-top:10px; font-size:{value_size}px'>REQ {button_name(debug.cruiseButton)}</div>"
      f"<div style='font-size:{value_size}px; color:{button_color}'>{BUTTON_STATES.get(button_state, str(button_state))}</div>"
      f"<div style='margin-top:10px; font-size:{value_size}px'>TX {button_name(last_tx_button)} <span style='color:{tx_color}'>· {tx_age}</span></div>"
    )
    window.show()

  timer = QTimer()
  timer.timeout.connect(update)
  timer.start(100)
  app.exec_()


if __name__ == "__main__":
  main()
