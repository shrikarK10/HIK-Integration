# main.py
import sys
import os
import glob
import datetime
import traceback
import sqlite3
import queue
import io
import time
import gc
import threading
from datetime import timedelta
from LoggerManager import LoggerManager
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QDateEdit, QComboBox, QPushButton,
                             QRadioButton, QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox,
                             QProgressDialog,QAbstractItemView, QFrame, QGridLayout)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt5.QtGui import QIcon, QPixmap, QImage
from PyQt5.QtWidgets import QProgressBar

import cv2
import numpy as np
import logging



# YOLO imports; kept lazy inside thread to avoid import-time crashes if missing
# from ultralytics import YOLO  # loaded inside DetectionThread


#Config imports
from Config import (logger,APP_TITLE, VW_NAVY, CAMERA_SOURCE, FRAME_SIMULATE_IF_NO_CAM,
                    DEBUG_DIR, YOLO_MODEL_PATH, SECOND_MODEL_PATH, DB_PATH,
                    GET_IMAGE_TIMEOUT_MS, WATCHDOG_NO_FRAME_SEC, GC_EVERY_N_FRAMES,
                    NG_SAVE_DIR, FINAL_RESULT_DIR,SHIFT_CHECK_INTERVAL_MS ,
                    FINAL_IMAGE_WIDTH, FINAL_IMAGE_HEIGHT, CLOCK_UPDATE_INTERVAL_MS)

# ------------------ BaumerCameraThread (from old app, simplified) ------------------
from BaumerCameraThread import BaumerCameraThread
# ------------------ Detection Thread (wraps old process_frame logic) ------------------
from DetectionThread import DetectionThread
# ------------------ Reuse KPICard and EmbeddedReportWidget from new app ------------------
from UIComp import KPICard, EmbeddedReportWidget
# ------------------ Main App (new UI + integrated backend) ------------------
class VWPorosityApp(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.setMinimumSize(1000, 700)

        self.camera_thread = None
        self.detection_thread = None
        self.plc_thread = None
        self.awaiting_trigger = False
        self.awaiting_result = False

        self.camera_status_label = None  # Will be set in UI
        self.plc_status_label = None
        self.camera_heartbeat_label = None
        self.plc_heartbeat_label = None
        self.current_shift_label = None
        self.last_detection_label = None
        self.camera_heartbeat_timer = QTimer(self)
        self.plc_heartbeat_timer = QTimer(self)
        self.camera_connected = False
        self.plc_connected = False

        self.latest_qimg = None
        self.last_ng_qimg = None
        self.latest_bgr = None

        self.total = 0
        self.good = 0
        self.bad = 0
        self.last_kpi_update = 0
        self.frame_count = 0
        self.last_fps_time = time.time()


        self._build_ui()
        
        self._init_database()
        self._load_previous_kpis()
        self._start_shift_timer()
        self._start_detection_thread()
        self._init_camera_and_plc()

        # Clock
        self._start_clock()
        self._navigate_to("inspection")

    def _build_ui(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        base = QtWidgets.QVBoxLayout(central)
        base.setContentsMargins(8, 8, 8, 8)
        base.setSpacing(8)

        right_col = QtWidgets.QVBoxLayout()
        right_col.setSpacing(8)
        right_col.setContentsMargins(0, 0, 0, 0)

        header = QtWidgets.QFrame()
        header.setMinimumHeight(60)
        header.setStyleSheet("QFrame { background: #0b2b5c; border-radius:8px; }")
        h_layout = QtWidgets.QHBoxLayout(header)
        h_layout.setContentsMargins(8, 4, 8, 4)

        vw_logo = QtWidgets.QLabel()
        vw_logo.setPixmap(QPixmap())
        vw_logo.setStyleSheet("padding-right: 8px;")
        h_layout.addWidget(vw_logo)

        self.header_title = QtWidgets.QLabel("Optical Inspection System")
        self.header_title.setStyleSheet("color:white; font-weight:700; font-size:14px;")
        self.header_title.setWordWrap(True)
        h_layout.addWidget(self.header_title, 1)

        self.btn_inspection = QtWidgets.QPushButton("Inspect")
        self.btn_reports = QtWidgets.QPushButton("Reports")
        self.btn_settings = QtWidgets.QPushButton("Settings")
        for b in (self.btn_inspection, self.btn_reports, self.btn_settings):
            b.setCheckable(True)
            b.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
            b.setStyleSheet("""
                QPushButton { color:white; background: #003366; padding:6px 10px; border-radius:5px; font-size:12px; }
                QPushButton:hover { background:#004080; }
                QPushButton:checked { background:#0051A3; }
            """)
            h_layout.addWidget(b)

        h_layout.addStretch(1)

        self.btn_live = QtWidgets.QPushButton("Live")
        self.btn_debug = QtWidgets.QPushButton("Debug")
        self.btn_trigger = QtWidgets.QPushButton("Trigger")
        for b in (self.btn_live, self.btn_debug):
            b.setCheckable(True)
        for b in (self.btn_live, self.btn_debug, self.btn_trigger):
            b.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
            b.setStyleSheet("""
                QPushButton { background:#0e3a7d; color:white; border:none; padding:6px 10px; border-radius:5px; font-size:12px; }
                QPushButton:checked { background:#1371d6; }
                QPushButton:hover { background:#1371d6; }
            """)
        self.btn_live.setChecked(True)
        h_layout.addWidget(self.btn_live)
        h_layout.addWidget(self.btn_debug)
        h_layout.addWidget(self.btn_trigger)

        self.clock_lbl = QtWidgets.QLabel("--:--:--")
        self.clock_lbl.setStyleSheet("color:white; font-weight:600; font-size:12px;")
        h_layout.addWidget(self.clock_lbl)
        right_col.addWidget(header)

        self.pages = QtWidgets.QStackedWidget()
        right_col.addWidget(self.pages, 1)

        # Inspection page
        self.page_inspection = QtWidgets.QWidget()
        ins_layout = QtWidgets.QVBoxLayout(self.page_inspection)
        ins_layout.setContentsMargins(0, 0, 0, 0)
        ins_layout.setSpacing(8)

        cam_card = QtWidgets.QFrame()
        cam_card.setStyleSheet("QFrame { background:#0b0b0b; border-radius:8px; }")
        cam_layout = QtWidgets.QHBoxLayout(cam_card)
        cam_layout.setContentsMargins(6, 6, 6, 6)
        cam_layout.setSpacing(8)

        self.cam_display = QtWidgets.QLabel("Camera feed will appear here")
        self.cam_display.setAlignment(QtCore.Qt.AlignCenter)
        self.cam_display.setStyleSheet("color:white; background:black;")
        self.cam_display.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        cam_layout.addWidget(self.cam_display, 3)

        # Status badge overlay on camera feed
        self.status_tag = QLabel(self.cam_display)
        self.status_tag.setGeometry(10, 10, 140, 45)
        self.status_tag.setAlignment(Qt.AlignCenter)
        self.status_tag.setStyleSheet("""
            QLabel {
                background-color: #6c757d;
                color: white;
                font: bold 18px "Segoe UI";
                border-radius: 8px;
                padding: 5px;
            }
        """)
        self.status_tag.setText("WAITING")
        self.status_tag.hide()

        side_panel = QtWidgets.QFrame()
        side_panel.setStyleSheet("QFrame { background:white; border-radius:8px; border:1px solid #dbe4f2; }")
        side_layout = QtWidgets.QVBoxLayout(side_panel)
        side_layout.setContentsMargins(6, 6, 6, 6)
        side_layout.setSpacing(6)

        cards_frame = QtWidgets.QFrame()
        cards_layout = QtWidgets.QGridLayout(cards_frame)
        cards_layout.setContentsMargins(0, 0, 0, 0)
        cards_layout.setSpacing(8)
        self.kpi_total = KPICard("Detected", "0", VW_NAVY)
        self.kpi_acc = KPICard("Bad Ratio", "0%", "#6A5ACD")
        self.kpi_good = KPICard("Good", "0", "#198754")
        self.kpi_ng = KPICard("NG", "0", "#C00000")
        for c in (self.kpi_total, self.kpi_good, self.kpi_ng, self.kpi_acc):
            c.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        cards_layout.addWidget(self.kpi_total, 0, 0)
        cards_layout.addWidget(self.kpi_acc, 0, 1)
        cards_layout.addWidget(self.kpi_good, 1, 0)
        cards_layout.addWidget(self.kpi_ng, 1, 1)
        side_layout.addWidget(cards_frame)

        status_frame = QtWidgets.QFrame()
        status_frame.setStyleSheet("""
            QFrame {
                background: #f8f9fa;
                border-radius: 8px;
                border: 1px solid #dbe4f2;
                padding: 6px;
            }
            QLabel {
                font-size: 12px;
                color: #444;
            }
        """)
        status_layout = QtWidgets.QVBoxLayout(status_frame)
        status_layout.setContentsMargins(6, 6, 6, 6)
        status_layout.setSpacing(4)

        # Camera status
        camera_status_layout = QtWidgets.QHBoxLayout()
        self.camera_status_label = QtWidgets.QLabel("Camera: Disconnected")
        self.camera_status_label.setStyleSheet("color: #C00000; font-weight: 600;")
        self.camera_heartbeat_label = QtWidgets.QLabel("●")
        self.camera_heartbeat_label.setStyleSheet("color: #C00000; font-size: 14px;")
        camera_status_layout.addWidget(self.camera_status_label)
        camera_status_layout.addWidget(self.camera_heartbeat_label)
        camera_status_layout.addStretch(1)
        status_layout.addLayout(camera_status_layout)

        # Current shift
        self.current_shift_label = QtWidgets.QLabel("Current Shift: Unknown")
        status_layout.addWidget(self.current_shift_label)

        # Last detection timestamp
        self.last_detection_label = QtWidgets.QLabel("Last Detection: None")
        status_layout.addWidget(self.last_detection_label)

        side_layout.addWidget(status_frame)

        # Last NG
        ng_header_frame = QtWidgets.QFrame()
        ng_header_layout = QtWidgets.QHBoxLayout(ng_header_frame)
        ng_header_layout.setContentsMargins(0, 0, 0, 0)
        ng_label = QtWidgets.QLabel("Last NG")
        ng_label.setStyleSheet("font-weight:600; font-size:14px; color:#444;")
        ng_header_layout.addWidget(ng_label)
        ng_header_layout.addStretch(1)
        self.ng_timestamp = QtWidgets.QLabel("")
        self.ng_timestamp.setStyleSheet("color:#666; font-size:11px;")
        ng_header_layout.addWidget(self.ng_timestamp)
        side_layout.addWidget(ng_header_frame)

        ng_content_frame = QtWidgets.QFrame()
        ng_content_frame.setStyleSheet("""
            QFrame {
                border-radius: 12px;
                border: 1px solid #dbe4f2;
                background: #ffffff;
            }
            QLabel {
                background: #f6f8fc;
                border: 1px dashed #cbd5e1;
                font-size:12px;
                color:#777;
            }
        """)
        ng_content_layout = QtWidgets.QVBoxLayout(ng_content_frame)
        ng_content_layout.setContentsMargins(8, 8, 8, 8)

        self.last_ng = QtWidgets.QLabel("No NG yet")
        self.last_ng.setAlignment(QtCore.Qt.AlignCenter)
        self.last_ng.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.last_ng.setMinimumSize(120, 100)
        ng_content_layout.addWidget(self.last_ng)

        side_layout.addWidget(ng_content_frame)

        # self.btn_capture = QtWidgets.QPushButton("Capture")
        # self.btn_mark_ng = QtWidgets.QPushButton("Mark NG")
        # for b in (self.btn_capture, self.btn_mark_ng):
        #     b.setMinimumHeight(36)
        #     b.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        #     b.setStyleSheet(
        #         "QPushButton { background:#003366; color:white; border:none; border-radius:6px; padding:6px; font-size:12px; } QPushButton:hover{background:#004080;}")
        #     side_layout.addWidget(b)

        cam_layout.addWidget(side_panel, 1)
        ins_layout.addWidget(cam_card, 1)

        # Reports page
        self.page_reports = EmbeddedReportWidget(self)

        # Settings page
        self.page_settings = QtWidgets.QWidget()
        s_layout = QtWidgets.QVBoxLayout(self.page_settings)
        s_layout.addWidget(QtWidgets.QLabel("Settings - configure DB / Camera / Shift timings here"))
        s_layout.addStretch(1)

        # Add pages
        self.pages.addWidget(self.page_inspection)
        self.pages.addWidget(self.page_reports)
        self.pages.addWidget(self.page_settings)

        # Wire navigation
        self.btn_inspection.clicked.connect(lambda: self._navigate("inspection"))
        self.btn_reports.clicked.connect(lambda: self._navigate("reports"))
        self.btn_settings.clicked.connect(lambda: self._navigate("settings"))

        self.camera_heartbeat_timer.timeout.connect(self._blink_camera_heartbeat)
        self.plc_heartbeat_timer.timeout.connect(self._blink_plc_heartbeat)

        # Wire toggles and actions
        self.btn_live.clicked.connect(self._on_live_clicked)
        self.btn_debug.clicked.connect(self._on_debug_clicked)
        self.btn_trigger.clicked.connect(self._on_trigger_clicked)
        # self.btn_capture.clicked.connect(self._capture_pressed)
        # self.btn_mark_ng.clicked.connect(self._mark_preview_ng)

        base.addLayout(right_col, 1)

        footer_frame = QtWidgets.QFrame()
        footer_frame.setMinimumHeight(32)  # Slightly taller for better readability
        footer_frame.setStyleSheet("""
            QFrame {
                background-color: #001E50;  /* VW Navy base */
                border-radius:8px;
                border-top: 1px solid #003366;  /* Subtle darker border for separation */
            }
        """)

        # Layout: Horizontal, minimal margins/spacing for a clean bar
        footer_layout = QtWidgets.QHBoxLayout(footer_frame)
        footer_layout.setContentsMargins(10, 4, 10, 4)  # Balanced padding (top/bottom reduced)
        footer_layout.setSpacing(10)  # Small gap between notification and footer

        # Notification Label (left side, 80% stretch)
        self.notification_lbl = QtWidgets.QLabel("")
        self.notification_lbl.setStyleSheet("""
            QLabel {
                background-color: transparent;  /* Blend into frame */
                color: #FFFFFF;                 /* White text */
                font-family: 'Segoe UI', Arial, sans-serif;
                font-size: 12px;
                font-weight: 400;
                padding: 4px 8px;               /* Compact padding */
                border-radius: 4px;
            }
        """)
        self.notification_lbl.setWordWrap(True)  # Allow wrapping for long notifications
        self.notification_lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        footer_layout.addWidget(self.notification_lbl, 80)  # Flexible stretch

        # Footer Label (right side, 20% stretch, single-line)
        self.footer_lbl = QtWidgets.QLabel("© 2025 Company Name | V 0.1 | Powered by Wizpro Technovations")
        self.footer_lbl.setStyleSheet("""
            QLabel {
                background-color: transparent;  /* Blend seamlessly */
                color: #E0E0E0;                 /* Off-white for subtlety */
                font-family: 'Segoe UI', Arial, sans-serif;
                font-size: 13px;                /* Slightly smaller for compactness */
                font-weight: 500;               /* Semi-bold for emphasis */
                padding: 4px 8px;
                border-radius: 4px;
            }
        """)
        self.footer_lbl.setWordWrap(False)  # Force single line—no wrapping!
        self.footer_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)  # Right-align for footer feel
        footer_layout.addWidget(self.footer_lbl, 20)  # Fixed stretch

        # Add to main layout (assuming 'base' is your QVBoxLayout)
        base.addWidget(footer_frame)

    # ---------------- UI helpers ----------------
    def _set_label_pixmap(self, label: QtWidgets.QLabel, qimg: QImage, save_attr=None):
        if qimg is None:
            return
        pixmap = QPixmap.fromImage(qimg)
        label.original_pixmap = pixmap  # store original pixmap
        self._update_label_scaled_pixmap(label)
        if save_attr == "latest":
            self.latest_qimg = qimg
        elif save_attr == "last_ng":
            self.last_ng_qimg = qimg

    def _update_label_scaled_pixmap(self, label):
        if hasattr(label, "original_pixmap"):
            scaled = label.original_pixmap.scaled(
                label.size(),
                QtCore.Qt.KeepAspectRatio,
                QtCore.Qt.SmoothTransformation
            )
            label.setPixmap(scaled)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # rescale NG and camera preview dynamically
        if self.last_ng:
            self._update_label_scaled_pixmap(self.last_ng)
        if self.cam_display:
            self._update_label_scaled_pixmap(self.cam_display)

    def _show_notification(self, message, timeout_ms=4000):
        self.notification_lbl.setText(message)
        QtCore.QTimer.singleShot(timeout_ms, lambda: self.notification_lbl.setText(""))

    def _start_clock(self):
        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self._update_clock)
        self.clock_timer.start(CLOCK_UPDATE_INTERVAL_MS)  # update every second
        self._update_clock()

    def _update_clock(self):
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.clock_lbl.setText(now)

    def _navigate(self, name):
        mapping = {"inspection": (self.btn_inspection, 0), "reports": (self.btn_reports, 1),
                   "settings": (self.btn_settings, 2)}
        for btn in (self.btn_inspection, self.btn_reports, self.btn_settings):
            btn.setChecked(False)
        btn, idx = mapping[name]
        btn.setChecked(True)
        self.pages.setCurrentIndex(idx)
        if name == "inspection":
            if self.btn_live.isChecked():
                self._start_camera()

    def _navigate_to(self, name):
        self._navigate(name)

    def _on_live_clicked(self):
        if self.btn_live.isChecked():
            return
        self.btn_live.setChecked(True)
        self.btn_debug.setChecked(False)
        self._start_camera()

    def _on_debug_clicked(self):
        if self.btn_debug.isChecked():
            return
        self.btn_debug.setChecked(True)
        self.btn_live.setChecked(False)
        self._stop_camera()
        self._load_debug_filelist()
        self.cam_display.setText("Press Capture to load next debug image")

    def _on_trigger_clicked(self):
        if hasattr(self, "baumer_thread") and self.baumer_thread:
            if hasattr(self.baumer_thread, "software_trigger"):
                self.baumer_thread.software_trigger()
                self._show_notification("Software trigger sent", 2000)

    

    def _init_database(self):
        try:
            with sqlite3.connect(DB_PATH) as conn:
                cur = conn.cursor()

                # --- Core tables ---
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS Operating_Shifts (
                        id INTEGER PRIMARY KEY,
                        name TEXT NOT NULL,
                        isActive INTEGER DEFAULT 1,
                        timestamp TEXT
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS Transactions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        Object_Category_id INTEGER,
                        Operating_Shifts_id INTEGER,
                        image_file_path TEXT,
                        status TEXT,
                        timestamp TEXT
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS ShiftSummary (
                        shift_id INTEGER,
                        date TEXT,
                        total INTEGER,
                        good INTEGER,
                        bad INTEGER,
                        last_updated TEXT,
                        PRIMARY KEY (shift_id, date)
                    )
                """)

                # --- Enforce only Morning/Evening/Night in Operating_Shifts ---
                ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                cur.execute("DELETE FROM Operating_Shifts WHERE name NOT IN ('Morning','Evening','Night')")
                cur.execute("INSERT OR REPLACE INTO Operating_Shifts (id, name, isActive, timestamp) VALUES (1, 'Morning', 1, ?)", (ts,))
                cur.execute("INSERT OR REPLACE INTO Operating_Shifts (id, name, isActive, timestamp) VALUES (2, 'Evening', 1, ?)", (ts,))
                cur.execute("INSERT OR REPLACE INTO Operating_Shifts (id, name, isActive, timestamp) VALUES (3, 'Night', 1, ?)", (ts,))

                # --- Indexes for performance ---
                # Transactions table is expected to grow the most
                cur.execute("CREATE INDEX IF NOT EXISTS idx_transactions_shift ON Transactions (Operating_Shifts_id)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_transactions_date ON Transactions (DATE(timestamp))")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_transactions_status ON Transactions (status)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_transactions_timestamp ON Transactions (timestamp)")

                # ShiftSummary lookups are by (shift_id, date)
                cur.execute("CREATE INDEX IF NOT EXISTS idx_shiftsummary_date ON ShiftSummary (date)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_shiftsummary_shift ON ShiftSummary (shift_id)")

                # Operating_Shifts name lookup
                cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_operatingshifts_name ON Operating_Shifts (name)")

                conn.commit()

            print("[DB] Initialized with indexes and repaired Operating_Shifts")
            logger.log_debug("MainApp", "_init_database", "DB initialized with indexes & Operating_Shifts reset")

        except Exception as e:
            logger.log_error("MainApp", "_init_database", f"DB init error: {e}")


    def _get_current_shift(self):
        now = datetime.datetime.now()
        today_str = now.strftime("%Y-%m-%d")

        # Morning: 06:30 - 15:00
        morning_start_str = f"{today_str} 07:00:00"
        morning_end_str = f"{today_str} 15:00:00"

        # Evening: 15:00 - 23:30
        evening_start_str = f"{today_str} 15:00:00"
        evening_end_str = f"{today_str} 23:00:00"

        # Night: 23:30 - 06:30 next day
        night_start_str = f"{today_str} 23:00:00"
        night_end_str = f"{(now + timedelta(days=1)).strftime('%Y-%m-%d')} 07:00:00"

        now_str = now.strftime("%Y-%m-%d %H:%M:%S")

        if morning_start_str <= now_str < morning_end_str:
            return "Morning", 1, morning_start_str, morning_end_str
        elif evening_start_str <= now_str < night_start_str:
            return "Evening", 2, evening_start_str, evening_end_str
        else:  # Night: 23:30 - 23:59:59 or 00:00 - 06:30
            prev_day_str = (now - timedelta(days=1)).strftime("%Y-%m-%d")
            prev_night_start_str = f"{prev_day_str} 23:00:00"
            return "Night", 3, prev_night_start_str, night_end_str

    # def _get_current_shift(self):
    #     now = datetime.datetime.now()
    #     current_time = now.time()
    #     morning_start = datetime.time(6, 30)
    #     morning_end = datetime.time(15, 0)
    #     evening_start = datetime.time(15, 0)
    #     evening_end = datetime.time(23, 30)

    #     if morning_start <= current_time < morning_end:
    #         return "Morning", now.date()
    #     elif evening_start <= current_time <= evening_end:
    #         return "Evening", now.date()
    #     else:
    #         # Off-shift: Default to Evening
    #         return "Evening", now.date()

    def _get_shift_id(self, shift_name):
        try:
            with sqlite3.connect(DB_PATH) as conn:
                row = conn.execute("SELECT id FROM Operating_Shifts WHERE name=?", (shift_name,)).fetchone()
                return row[0] if row else None
        except Exception as e:
            logger.log_error("MainApp", "_get_shift_id", f"Error: {e}")
            return None

    def _start_shift_timer(self):
        self.shift_timer = QTimer(self)
        self.shift_timer.timeout.connect(self._check_shift_change)
        self.shift_timer.start(SHIFT_CHECK_INTERVAL_MS)  # Every 30s for faster response

    def _check_shift_change(self):
        new_shift, new_id, new_start, new_end = self._get_current_shift()
        if new_id != self.current_shift_id:  # Compare ID (more reliable than start datetime)
            print(
                f"[DEBUG] Shift change detected: {self.current_shift} (ID={self.current_shift_id}) -> {new_shift} (ID={new_id})")
            self.current_shift = new_shift
            self.current_shift_id = new_id
            self.current_shift_start = new_start
            self.current_shift_end = new_end
            self.current_shift_label.setText(f"Current Shift: {self.current_shift} (ID: {self.current_shift_id})")
            self._load_previous_kpis()  # Reload (will be ~0 for new shift)
            self._show_notification(f"Shift changed to {self.current_shift}. KPIs reset to shift totals.", 5000)
        else:
            # Periodic refresh without reset (sync any missed logs)
            self._load_previous_kpis(force_refresh=True)

    def _update_kpis(self):
        accuracy = f"{(self.bad/ self.total * 100):.2f}%" if self.total > 0 else "0%"
        self.kpi_total.set_value(self.total)
        self.kpi_good.set_value(self.good)
        self.kpi_ng.set_value(self.bad)
        self.kpi_acc.set_value(accuracy)
        print(f"[DEBUG] Updated KPIs: Total={self.total}, Good={self.good}, Bad={self.bad}, Accuracy={accuracy}")

    def _load_previous_kpis(self, force_refresh=False):
        self.current_shift, self.current_shift_id, _, _ = self._get_current_shift()
        self.current_shift_label.setText(f"Current Shift: {self.current_shift} (ID: {self.current_shift_id})")

        try:
            current_date_str = datetime.datetime.now().strftime("%Y-%m-%d")
            
            # DEBUG: Print params
            print(f"[DEBUG] KPI Query Params: Shift ID={self.current_shift_id} (type={type(self.current_shift_id)}), Date={current_date_str}")

            with sqlite3.connect(DB_PATH) as conn:
                cur = conn.cursor()
                
                # Fallback 1: Total rows (no filters) to verify data exists
                cur.execute("""
                    SELECT COUNT(*) FROM Transactions 
                    WHERE Operating_Shifts_id = ? AND strftime('%Y-%m-%d', timestamp) = ?
                """, (self.current_shift_id, current_date_str))
                total_rows = cur.fetchone()[0] or 0
                print(f"[DEBUG] Total raw rows (incl. EMPTY): {total_rows}")
                
                # Main query: Non-EMPTY only (use strftime for robust DATE)
                cur.execute("""
                    SELECT 
                        COUNT(*) as total,  
                        SUM(CASE WHEN status = 'GOOD' THEN 1 ELSE 0 END) as good,
                        SUM(CASE WHEN status = 'BAD' THEN 1 ELSE 0 END) as bad
                    FROM Transactions 
                    WHERE Operating_Shifts_id = ? 
                    AND strftime('%Y-%m-%d', timestamp) = ? 
                    AND status != 'EMPTY'  -- Exclude no-glass
                """, (self.current_shift_id, current_date_str))
                row = cur.fetchone()
                
                old_total = self.total
                self.total = row[0] or 0
                self.good = row[1] or 0
                self.bad = row[2] or 0

            # DEBUG: Full log
            print(f"[DEBUG] KPIs: Total (inspected)={self.total}, Good={self.good}, Bad={self.bad} "
                f"(out of {total_rows} raw rows)")
            
            if total_rows > 0 and self.total == 0:
                print(f"[INFO] All {total_rows} rows are 'EMPTY'—no inspections detected today!")

            self._update_kpis()
            
            if force_refresh and old_total != self.total:
                self._show_notification(
                    f"KPIs: {self.total} inspected ({self.good} good, {self.bad} bad)", 3000)

        except Exception as e:
            print(f"[ERROR] KPI load failed: {e}")
            logger.log_error("MainApp", "_load_previous_kpis", f"Error: {e}")
            self.total = self.good = self.bad = 0
            self._update_kpis()

    
    def _update_shift_summary(self, is_good):
        
        shift_name, shift_id, shift_start, shift_end = self._get_current_shift()
        if not shift_id:
            print("[DEBUG] No shift ID—skipping summary update")
            return
        
        date_str = datetime.datetime.now().strftime("%Y-%m-%d")
        
        try:
            with sqlite3.connect(DB_PATH) as conn:
                cur = conn.cursor()
                
                # DEBUG: Verify params
                print(f"[DEBUG] Summary Update Params: Shift ID={shift_id} (type={type(shift_id)}), Date={date_str}")
                
                # Query: Aggregate non-EMPTY only (aligns with _load_previous_kpis)
                cur.execute("""
                    SELECT 
                        COUNT(*) as total,  
                        SUM(CASE WHEN status = 'GOOD' THEN 1 ELSE 0 END) as good,
                        SUM(CASE WHEN status = 'BAD' THEN 1 ELSE 0 END) as bad
                    FROM Transactions 
                    WHERE Operating_Shifts_id = ? 
                    AND strftime('%Y-%m-%d', timestamp) = ? 
                    AND status != 'EMPTY'  -- Only inspected glass
                """, (shift_id, date_str))
                row = cur.fetchone()
                
                total = row[0] or 0
                good = row[1] or 0
                bad = row[2] or 0
                
                # Insert or replace (assumes UNIQUE(shift_id, date))
                cur.execute("""
                    INSERT OR REPLACE INTO ShiftSummary 
                    (shift_id, date, total, good, bad, last_updated)
                    VALUES (?, ?, ?, ?, ?, datetime('now'))
                """, (shift_id, date_str, total, good, bad))
                # No explicit commit needed (with conn: autocommits)

            # DEBUG: Log results
            print(f"[DEBUG] Updated ShiftSummary for {shift_name} on {date_str}: "
                f"Total={total} (inspected), Good={good}, Bad={bad}")
            
            logger.log_debug("MainApp", "_update_shift_summary",
                            f"Updated KPIs for {shift_name} {date_str}: total={total}, good={good}, bad={bad}")
            
            # Optional: Quick UI refresh (if called frequently)
            if is_good:  # Param hint: Maybe notify on good detections?
                self._load_previous_kpis(force_refresh=True)

        except Exception as e:
            print(f"[ERROR] Shift summary update failed: {e}")
            logger.log_error("MainApp", "_update_shift_summary", f"Error: {e}")


    def _log_transaction(self, image_path, status):
        _, shift_id, _, _ = self._get_current_shift()  # Get fresh shift
        print("Shift", shift_id)
        try:
            with sqlite3.connect(DB_PATH) as conn:
                ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                conn.execute("""
                        INSERT INTO Transactions 
                        (Object_Category_id, Operating_Shifts_id, image_file_path, status, timestamp) 
                        VALUES (1, ?, ?, ?, ?)  -- Object_Category_id=1 (as in your data)
                    """, (shift_id, image_path, status, ts))
                conn.commit()
            print(f"[DEBUG] Logged {status} for shift ID={shift_id}, path={image_path}")  # Remove in prod
        except Exception as e:
            print(f"[ERROR] Log failed: {e}")
            logger.log_error("MainApp", "_log_transaction", f"Error: {e}")

        # ---------------- Camera + PLC ----------------

    def _init_camera_and_plc(self):
        self.baumer_thread = BaumerCameraThread()

        # Move signal connections here, before connect_camera()
        self.baumer_thread.camera_connected.connect(self._on_camera_connected)
        self.baumer_thread.camera_disconnected.connect(self._on_camera_disconnected)
        self.baumer_thread.frame_captured.connect(self._on_camera_frame)

        if self.baumer_thread.connect_camera():
            self.camera_thread = self.baumer_thread
            self.baumer_thread.start()
            self._show_notification("Baumer camera connected", 3000)

        self._update_current_shift()

    def _start_camera(self):
        if self.camera_thread and not self.camera_thread.isRunning():
            try:
                self.camera_thread.start()
            except Exception:
                pass

    def _stop_camera(self):
        if self.camera_thread:
            try:
                self.camera_thread.stop()
            except Exception:
                pass

    def _on_camera_connected(self):
        print("here")
        self.camera_connected = True
        self.camera_status_label.setText("Camera: Connected")
        self.camera_status_label.setStyleSheet("color: #198754; font-weight: 600;")
        self.camera_heartbeat_label.setStyleSheet("color: #198754; font-size: 14px;")
        self.camera_heartbeat_timer.start(1000)  # Start blinking

    def _on_camera_disconnected(self):
        self.camera_connected = False
        self.camera_status_label.setText("Camera: Disconnected")
        self.camera_status_label.setStyleSheet("color: #C00000; font-weight: 600;")
        self.camera_heartbeat_label.setStyleSheet("color: #C00000; font-size: 14px;")
        self.camera_heartbeat_timer.stop()
        self.camera_heartbeat_label.setVisible(True)  # Solid red

    def _on_plc_connected(self):
        self.plc_connected = True
        self.plc_status_label.setText("PLC: Connected")
        self.plc_status_label.setStyleSheet("color: #198754; font-weight: 600;")
        self.plc_heartbeat_label.setStyleSheet("color: #198754; font-size: 14px;")
        self.plc_heartbeat_timer.start(1000)  # Start blinking
        self._show_notification("PLC connected", 3000)

    def _on_plc_disconnected(self):
        self.plc_connected = False
        self.plc_status_label.setText("PLC: Disconnected")
        self.plc_status_label.setStyleSheet("color: #C00000; font-weight: 600;")
        self.plc_heartbeat_label.setStyleSheet("color: #C00000; font-size: 14px;")
        self.plc_heartbeat_timer.stop()
        self.plc_heartbeat_label.setVisible(True)  # Solid red
        self._show_notification("PLC disconnected", 3000)

    def _blink_camera_heartbeat(self):
        # Instead of hide/show, toggle color
        if self.camera_heartbeat_label.styleSheet().find("#198754") != -1:
            # green → transparent
            self.camera_heartbeat_label.setStyleSheet("color: transparent; font-size: 14px;")
        else:
            # transparent → green
            self.camera_heartbeat_label.setStyleSheet("color: #198754; font-size: 14px;")
        # self.camera_heartbeat_label.setVisible(not self.camera_heartbeat_label.isVisible())

    def _blink_plc_heartbeat(self):
        if self.plc_heartbeat_label.styleSheet().find("#198754") != -1:
            self.plc_heartbeat_label.setStyleSheet("color: transparent; font-size: 14px;")
        else:
            self.plc_heartbeat_label.setStyleSheet("color: #198754; font-size: 14px;")

        # self.plc_heartbeat_label.setVisible(not self.plc_heartbeat_label.isVisible())

    def _update_current_shift(self):
        try:
            now = datetime.datetime.now()
            today_str = now.strftime("%Y-%m-%d")

            # Morning: 06:30 - 15:00
            morning_start_str = f"{today_str} 06:30:00"
            morning_end_str = f"{today_str} 15:00:00"

            # Evening: 15:00 - 23:30
            evening_start_str = f"{today_str} 15:00:00"
            evening_end_str = f"{today_str} 23:30:00"

            # Night: 23:30 - 06:30 next day
            night_start_str = f"{today_str} 23:30:00"
            night_end_str = f"{(now + timedelta(days=1)).strftime('%Y-%m-%d')} 06:30:00"

            now_str = now.strftime("%Y-%m-%d %H:%M:%S")

            # Determine shift based on time (no DB query needed; IDs match Transactions)
            if morning_start_str <= now_str < morning_end_str:
                shift_name = "Morning"
                shift_id = 1  # Matches Transactions Operating_Shifts_id=1
            elif evening_start_str <= now_str < night_start_str:
                shift_name = "Evening"
                shift_id = 2  # Matches Transactions Operating_Shifts_id=2
            else:  # Night: 23:30 - 23:59:59 or 00:00 - 06:30
                shift_name = "Night"
                shift_id = 3  # New ID for Night
                night_start_str = f"{today_str} 23:30:00" if now_str >= night_start_str else f"{(now - timedelta(days=1)).strftime('%Y-%m-%d')} 23:30:00"

            # Update instance variables
            self.current_shift = shift_name
            self.current_shift_id = shift_id
            self.current_shift_label.setText(f"Current Shift: {shift_name} (ID: {shift_id})")

            # Log for debugging
            print(f"[DEBUG] Updated current shift: {shift_name} (ID={shift_id}) at {now_str}")

            # Refresh KPIs to ensure they match the current shift
            self._load_previous_kpis()

        except Exception as e:
            logger.log_error("VWPorosityApp", "_update_current_shift", f"Error updating shift: {e}")
            self.current_shift_label.setText("Current Shift: Error")

    def _on_plc_trigger(self):

        self.awaiting_trigger = True

        # When PLC triggers, request a software trigger if possible
        self._show_notification("PLC triggered capture", 2000)
        # If Baumer camera with neoapi supports software trigger, try
        try:
            if hasattr(self.baumer_thread, "camera") and self.baumer_thread._use_neoapi and self.baumer_thread.camera:
                try:
                    self.baumer_thread.camera.f.TriggerSoftware.Execute()
                except Exception:
                    pass
        except Exception:
            pass

    def _on_camera_frame(self, bgr):
        # print("caputre image")
        self.frame_count += 1
        # Log FPS every 5s
        if time.time() - self.last_fps_time > 5:
            fps = self.frame_count / (time.time() - self.last_fps_time)
            logger.log_debug("Main", "_on_camera_frame", f"Camera FPS: {fps:.2f}")
            self.frame_count = 0
            self.last_fps_time = time.time()
        
        if self.detection_thread:
            try:
                if not self.detection_thread.frame_queue.full():
                    self.detection_thread.request(bgr, tag="live", src_path="")
                else:
                    logger.log_debug("Main", "_on_camera_frame", "Dropping frame because worker queue is full")
            except Exception as e:
                logger.log_error("Main", "_on_camera_frame", f"Failed to request worker: {e}")

    # --------------- Detection thread wiring ---------------
    def _start_detection_thread(self):
        self.detection_thread = DetectionThread(
            model_path=YOLO_MODEL_PATH,
            second_model_path=SECOND_MODEL_PATH,
        )
        self.detection_thread.result_ready.connect(self._on_detection_result)
        # self.detection_thread.status.connect(lambda s: self._show_notification(s, 4000))
        self.detection_thread.start()

    def update_status(self, is_good, head_count):
        try:
            if head_count == 0:
                self.status_tag.setText("EMPTY")
                self.status_tag.setStyleSheet("""
                    QLabel {
                        background-color: #ffc107;  /* Yellow */
                        color: black;
                        font: bold 18px "Segoe UI";
                        border-radius: 8px;
                        padding: 5px;
                    }
                """)
            elif is_good:
                self.status_tag.setText("GOOD")
                self.status_tag.setStyleSheet("""
                    QLabel {
                        background-color: #28a745;  /* Green */
                        color: white;
                        font: bold 18px "Segoe UI";
                        border-radius: 8px;
                        padding: 5px;
                    }
                """)
            else:
                self.status_tag.setText("BAD")
                self.status_tag.setStyleSheet("""
                    QLabel {
                        background-color: #dc3545;  /* Red */
                        color: white;
                        font: bold 18px "Segoe UI";
                        border-radius: 8px;
                        padding: 5px;
                    }
                """)
            self.status_tag.show()
        except Exception as e:
            logger.log_error("MainApp", "update_status", f"Error updating status: {e}")


    def qimage_to_cv(self,qimg: QImage) -> np.ndarray:
        qformat = qimg.format()
        width, height = qimg.width(), qimg.height()
        ptr = qimg.constBits()
        ptr.setsize(qimg.byteCount())

        if qformat in (QImage.Format_ARGB32, QImage.Format_ARGB32_Premultiplied, QImage.Format_RGBA8888):
            arr = np.frombuffer(ptr, np.uint8).reshape((height, width, 4))
            return cv2.cvtColor(arr, cv2.COLOR_RGBA2BGR)

        elif qformat == QImage.Format_RGB32:
            arr = np.frombuffer(ptr, np.uint8).reshape((height, width, 4))
            return cv2.cvtColor(arr, cv2.COLOR_BGRA2BGR)

        elif qformat == QImage.Format_RGB888:
            arr = np.frombuffer(ptr, np.uint8).reshape((height, qimg.bytesPerLine() // 3, 3))
            arr = arr[:, :width, :]  # remove possible padding
            return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)

        elif qformat in (QImage.Format_Grayscale8, QImage.Format_Indexed8):
            arr = np.frombuffer(ptr, np.uint8).reshape((height, width))
            return arr

        else:
            raise ValueError(f"Unsupported QImage format: {qformat}")

    def _on_detection_result(self, qimg, is_good, glass_present, tag, src):
        try:
            print("on_detection_result called, qimg:", type(qimg), 
                "valid:", (qimg is not None and not qimg.isNull()))

            # if not glass_present:
            #     return  # like EMPTY, no count

            # --- 1. Update UI immediately ---
            if qimg and not qimg.isNull():
                self._set_label_pixmap(self.cam_display, qimg, save_attr="latest")
            else:
                print("⚠️ QImage invalid, not displaying")
                return

            # Update status overlay (optional quick feedback)
            status = "EMPTY" if not glass_present else "GOOD" if is_good else "BAD"
            if status == "GOOD":
                self.status_tag.setStyleSheet("background:limegreen; color:white; font:bold 18px 'Segoe UI';")
            elif status == "BAD":
                self.status_tag.setStyleSheet("background:red; color:white; font:bold 18px 'Segoe UI';")
            else:
                self.status_tag.setStyleSheet("background:#FFFF00; color:black; font:bold 18px 'Segoe UI';")
            self.status_tag.setText(status)
            self.status_tag.show()

            if glass_present:
                # --- 2. PLC output (fast I/O) ---
                try:
                    if self.baumer_thread:
                        print("going to set PLC bit")
                        user_output_value = (status == "BAD")
                        self.baumer_thread.set_user_output(user_output_value)
                except Exception as e:
                    logger.log_error("Main", "_on_detection_result", f"Failed to set UserOutputValue: {e}")

                # --- 3. Save images (can be slow) ---
                ts_file = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                result_path = os.path.join(FINAL_RESULT_DIR, f"result_{ts_file}.jpg")
                img_cv = self.qimage_to_cv(qimg)
                final_image= cv2.resize(img_cv, (FINAL_IMAGE_WIDTH, FINAL_IMAGE_HEIGHT))
                cv2.imwrite(result_path,final_image)

                if not is_good:
                    try:
                        ng_path = os.path.join(NG_SAVE_DIR, f"NG_{ts_file}.jpg")
                        
                        cv2.imwrite(ng_path,final_image)
                        self._show_notification(f"Saved NG: {os.path.basename(ng_path)}", 3000)
                        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        self.ng_timestamp.setText(ts)
                        self._set_label_pixmap(self.last_ng, qimg, save_attr="last_ng")
                    except Exception as e:
                        logger.log_error("Main", "_on_detection_result", f"Failed saving NG: {e}")

                # --- 4. DB + KPIs (heaviest, keep at end) ---
                self._log_transaction(result_path, status)
                self._update_shift_summary(is_good)

                self._load_previous_kpis()

        except Exception as e:
            logger.log_error("MainApp", "_on_detection_result", f"Detection error: {e}")
            self._show_notification(f"Error processing detection: {e}", 5000)

    # --------------- Utilities ---------------
    def _bgr_to_qimage(self, bgr):
        try:
            h, w = bgr.shape[:2]
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            bytes_per_line = 3 * w
            qimg = QImage(rgb.data, w, h, bytes_per_line, QImage.Format_RGB888).copy()
            return qimg
        except Exception:
            # fallback: create gray image
            try:
                h, w = 480, 640
                qimg = QImage(w, h, QImage.Format_RGB888)
                qimg.fill(Qt.black)
                return qimg
            except Exception:
                return None

    # --------------- Debug helpers ---------------
    def _load_debug_filelist(self):
        exts = ("*.jpg", "*.jpeg", "*.png", "*.bmp", "*.tif", "*.tiff")
        files = []
        for e in exts:
            files.extend(glob.glob(os.path.join(DEBUG_DIR, e)))
        files.sort()
        self.debug_files = files
        self.debug_index = -1
        if not files:
            QtWidgets.QMessageBox.information(self, "Debug Images", f"No images found in:\n{DEBUG_DIR}")

    def _show_next_debug_image(self):
        if not hasattr(self, "debug_files") or not self.debug_files:
            self._load_debug_filelist()
            if not self.debug_files:
                return
        self.debug_index = (self.debug_index + 1) % len(self.debug_files)
        path = self.debug_files[self.debug_index]
        bgr = cv2.imread(path)
        if bgr is None:
            QtWidgets.QMessageBox.warning(self, "Load Error", f"Failed to read:\n{path}")
            return
        # enqueue
        self.detection_thread.enqueue(bgr)

    def _capture_pressed(self):
        if self.btn_debug.isChecked():
            self._show_next_debug_image()
            return
        if self.latest_qimg is None:
            QtWidgets.QMessageBox.information(self, "Info", "No frame available to capture.")
            return
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = os.path.join(DEBUG_DIR, f"CAPTURE_{ts}.jpg")
        try:
            QPixmap.fromImage(self.latest_qimg).save(fname, "JPEG", quality=100)
            self._show_notification(f"Captured saved: {fname}", 4000)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Save Error", f"Failed to save capture:\n{e}")

    def _mark_preview_ng(self):
        if self.latest_qimg is None:
            QtWidgets.QMessageBox.information(self, "Info", "No frame to mark NG.")
            return
        self._set_label_pixmap(self.last_ng, self.latest_qimg, save_attr="last_ng")
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.ng_timestamp.setText(ts)
        ts_file = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = os.path.join(NG_SAVE_DIR, f"NG_{ts_file}.jpg")
        try:
            QPixmap.fromImage(self.latest_qimg).save(fname, "JPEG", quality=100)
            # self._log_transaction(fname, "Not Good")
            self._show_notification(f"NG saved: {fname}", 4000)
        except Exception as e:
            print("mark_preview_ng save error: %s", e)

    # --------------- Shutdown ---------------
    def closeEvent(self, event):
        try:
            if self.camera_thread:
                try:
                    self.camera_thread.stop()
                except Exception:
                    pass
            if self.detection_thread:
                try:
                    self.detection_thread.stop()
                except Exception:
                    pass
        except Exception:
            pass
        super().closeEvent(event)



