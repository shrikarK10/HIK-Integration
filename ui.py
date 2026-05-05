from datetime import datetime
import sys
import time

import cv2
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QImage, QPixmap
from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QComboBox,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from config import AppConfig, ensure_output_dirs
from detection import DetectionEngine


class WizproInspectionUI(QMainWindow):
    def __init__(self, config: AppConfig, detector=None):
        super().__init__()
        self.config = config

        self.setWindowTitle(f"{self.config.company_name} Camera Inspection")
        self.resize(1400, 860)

        ensure_output_dirs(self.config)

        self.good_count = 0
        self.bad_count = 0
        self.total_triggers = 0
        self.last_frame = None
        self.current_mode = self.config.camera_trigger_mode

        self.detector = detector if detector is not None else DetectionEngine(self.config)

        from detection_thread import DetectionThread
        self.detection_thread = DetectionThread(self.config, engine=self.detector)
        self.detection_thread.result_ready.connect(self.on_detection_result_ready)
        self.detection_thread.start()

        self.cam_thread = None

        self._build_ui()
        self._connect_camera()

    def _build_ui(self):
        self.setStyleSheet(
            """
            QMainWindow {
                background-color: #f4f7fb;
            }
            QWidget {
                font-family: 'Trebuchet MS';
                color: #0f172a;
            }
            QFrame#leftPanel {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                            stop:0 #0f172a, stop:1 #1e293b);
                border-radius: 18px;
            }
            QLabel#title {
                color: #f8fafc;
                font-size: 24px;
                font-weight: 700;
            }
            QLabel#subtitle {
                color: #cbd5e1;
                font-size: 13px;
            }
            QFrame#card {
                background-color: #f8fafc;
                border-radius: 14px;
            }
            QLabel#cardLabel {
                color: #334155;
                font-size: 12px;
            }
            QLabel#cardValue {
                color: #0f172a;
                font-size: 26px;
                font-weight: 700;
            }
            QLabel#logoRoom {
                border: none;
                border-radius: 14px;
                color: #e2e8f0;
                font-size: 14px;
                font-weight: 600;
            }
            QPushButton {
                background-color: #0ea5e9;
                color: #ffffff;
                border: none;
                border-radius: 12px;
                padding: 12px 16px;
                font-size: 14px;
                font-weight: 700;
            }
            QPushButton:hover {
                background-color: #0284c7;
            }
            QPushButton:pressed {
                background-color: #0369a1;
            }
            QFrame#feedFrame {
                background-color: #ffffff;
                border: 1px solid #dbe4f0;
                border-radius: 18px;
            }
            QLabel#status {
                color: #334155;
                font-size: 13px;
            }
            QLabel#feedLabel {
                border-radius: 14px;
                background-color: #e2e8f0;
                color: #475569;
                font-size: 16px;
            }
            """
        )

        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(16, 16, 16, 16)
        root_layout.setSpacing(16)

        top_bar = QFrame()
        top_bar.setObjectName("feedFrame")
        top_bar_layout = QHBoxLayout(top_bar)
        top_bar_layout.setContentsMargins(14, 12, 14, 12)
        top_bar_layout.setSpacing(12)

        cam_label = QLabel("Camera")
        cam_label.setObjectName("subtitle")
        top_bar_layout.addWidget(cam_label)

        self.camera_selector = QComboBox()
        self.camera_selector.addItem("Hikvision", "Hikvision")
        self.camera_selector.addItem("Baumer", "Baumer")
        self.camera_selector.setCurrentIndex(0 if self.config.active_camera == "Hikvision" else 1)
        self.camera_selector.currentIndexChanged.connect(self.on_camera_changed)
        top_bar_layout.addWidget(self.camera_selector)

        mode_label = QLabel("Camera Mode")
        mode_label.setObjectName("subtitle")
        top_bar_layout.addWidget(mode_label)

        self.mode_selector = QComboBox()
        self.mode_selector.addItem("Continuous Live Feed", "continuous")
        self.mode_selector.addItem("Trigger Mode", "software")
        self.mode_selector.setCurrentIndex(0 if self.current_mode == "continuous" else 1)
        self.mode_selector.currentIndexChanged.connect(self.on_mode_changed)
        top_bar_layout.addWidget(self.mode_selector)

        top_bar_layout.addStretch(1)

        initial_mode_text = "Mode: Continuous Live Feed" if self.current_mode == "continuous" else "Mode: Trigger Mode"
        self.mode_status = QLabel(initial_mode_text)
        self.mode_status.setObjectName("status")
        top_bar_layout.addWidget(self.mode_status)

        root_layout.addWidget(top_bar)

        content_layout = QHBoxLayout()
        content_layout.setSpacing(16)

        left_panel = QFrame()
        left_panel.setObjectName("leftPanel")
        left_panel.setFixedWidth(360)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(20, 20, 20, 20)
        left_layout.setSpacing(14)

        title = QLabel(self.config.company_name)
        title.setObjectName("title")
        subtitle = QLabel(self.config.app_name)
        subtitle.setObjectName("subtitle")
        left_layout.addWidget(title)
        left_layout.addWidget(subtitle)

        self.logo_room = QLabel("Logo Area")
        self.logo_room.setObjectName("logoRoom")
        self.logo_room.setAlignment(Qt.AlignCenter)
        self.logo_room.setFixedHeight(90)
        self._load_logo_if_available()
        left_layout.addWidget(self.logo_room)

        self.good_value = self._add_metric_card(left_layout, "Good (count / trigger)", "0")
        self.bad_value = self._add_metric_card(left_layout, "Bad (count / trigger)", "0")
        self.bad_percent_value = self._add_metric_card(left_layout, "Percentage Bad", "0.0%")

        self.trigger_btn = QPushButton("Software Trigger")
        self.trigger_btn.clicked.connect(self.on_software_trigger)
        left_layout.addWidget(self.trigger_btn)

        self.result_label = QLabel("Last Trigger Result: N/A")
        self.result_label.setObjectName("subtitle")
        left_layout.addWidget(self.result_label)

        self.camera_label = QLabel("Camera: Connecting...")
        self.camera_label.setObjectName("subtitle")
        left_layout.addWidget(self.camera_label)

        self.detector_label = QLabel(f"Detector: {self.detector.backend_name}")
        self.detector_label.setObjectName("subtitle")
        left_layout.addWidget(self.detector_label)

        if self.detector.yolo_error:
            self.detector_hint = QLabel(f"Hint: {self.detector.yolo_error}")
            self.detector_hint.setObjectName("subtitle")
            self.detector_hint.setWordWrap(True)
            left_layout.addWidget(self.detector_hint)

        left_layout.addStretch(1)

        right_panel = QFrame()
        right_panel.setObjectName("feedFrame")
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(14, 14, 14, 14)
        right_layout.setSpacing(10)

        feed_header = QLabel("Live Camera Feed")
        feed_header.setFont(QFont("Trebuchet MS", 16, QFont.Bold))
        right_layout.addWidget(feed_header)

        self.feed_label = QLabel("Waiting for frame...")
        self.feed_label.setObjectName("feedLabel")
        self.feed_label.setAlignment(Qt.AlignCenter)
        self.feed_label.setMinimumSize(900, 640)
        right_layout.addWidget(self.feed_label, 1)

        self.status_label = QLabel("Status: Idle")
        self.status_label.setObjectName("status")
        right_layout.addWidget(self.status_label)

        content_layout.addWidget(left_panel)
        content_layout.addWidget(right_panel, 1)

        root_layout.addLayout(content_layout, 1)

        self.setCentralWidget(root)

    def _load_logo_if_available(self):
        if self.config.logo_path is None:
            return

        if not self.config.logo_path.exists():
            return

        pix = QPixmap(str(self.config.logo_path))
        if pix.isNull():
            return

        scaled = pix.scaled(
            self.logo_room.width() - 12,
            self.logo_room.height() - 12,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.logo_room.setPixmap(scaled)
        self.logo_room.setText("")

    def _add_metric_card(self, parent_layout, label_text, value_text):
        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 12, 14, 12)
        card_layout.setSpacing(4)

        label = QLabel(label_text)
        label.setObjectName("cardLabel")

        value = QLabel(value_text)
        value.setObjectName("cardValue")

        card_layout.addWidget(label)
        card_layout.addWidget(value)
        parent_layout.addWidget(card)
        return value

    def on_camera_changed(self, *_args):
        camera = self.camera_selector.currentData()
        if camera:
            self.config.active_camera = camera
            self.camera_label.setText(f"Camera: Connecting {camera}...")
            self._connect_camera()

    def _connect_camera(self):
        try:
            if self.cam_thread is not None:
                self.cam_thread.stop()
                self.cam_thread = None

            if self.config.active_camera == "Hikvision":
                from hikvision_cam import HikvisionCameraThread
                self.cam_thread = HikvisionCameraThread(self.config)
            else:
                from baumer_cam import BaumerCameraThread
                self.cam_thread = BaumerCameraThread(self.config)

            self.cam_thread.frame_captured.connect(self.on_frame_captured)
            self.cam_thread.camera_connected.connect(lambda: self.camera_label.setText(f"Camera: Connected ({self.config.active_camera})"))
            self.cam_thread.camera_disconnected.connect(lambda: self.camera_label.setText(f"Camera: Disconnected ({self.config.active_camera})"))
            
            self.cam_thread.start()
            self._apply_mode_ui(self.current_mode, initial=True)
        except Exception as exc:
            self.camera_label.setText("Camera: Not connected")
            self.status_label.setText(f"Status: Camera error - {exc}")

    def on_mode_changed(self, *_args):
        mode = self.mode_selector.currentData()
        if mode:
            self.apply_mode(mode)

    def apply_mode(self, mode, initial=False):
        self.current_mode = mode

        if self.cam_thread is not None:
            self.cam_thread.set_trigger_mode(mode)

        self._apply_mode_ui(mode, initial=initial)

    def _apply_mode_ui(self, mode, initial=False):
        if mode == "software":
            self.last_frame = None
            self.feed_label.clear()
            self.feed_label.setText("Waiting for software trigger...")
            self.mode_status.setText("Mode: Trigger Mode")
            self.status_label.setText("Status: Trigger mode active")
        else:
            self.mode_status.setText("Mode: Continuous Live Feed")
            if self.detector.yolo_error:
                self.status_label.setText(f"Status: Live feed started | {self.detector.yolo_error}")
            else:
                self.status_label.setText("Status: Live feed started")

        if not initial:
            self.result_label.setText("Last Trigger Result: N/A")

    def on_frame_captured(self, frame):
        normalized = self._normalize_frame(frame)
        if normalized is None:
            return

        self.last_frame = normalized

        if self.detector.is_ready:
            self.detection_thread.enqueue(normalized)
        else:
            self._show_frame(normalized)
            if self.current_mode == "software":
                self.status_label.setText(f"Status: Captured frame only | {self.detector.yolo_error}")

    def _normalize_frame(self, frame):
        if frame is None:
            return None

        if frame.ndim == 2:
            return cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)

        if frame.ndim == 3 and frame.shape[2] == 4:
            return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

        return frame

    def _show_frame(self, frame):
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        qimg = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888).copy()
        pix = QPixmap.fromImage(qimg)
        scaled = pix.scaled(
            self.feed_label.width(),
            self.feed_label.height(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.feed_label.setPixmap(scaled)

    def _draw_judgement_badge(self, frame, is_bad, detection_count):
        out = frame.copy()
        label_text = f"BAD ({detection_count})" if is_bad else "GOOD"
        bg_color = (0, 0, 255) if is_bad else (0, 170, 0)

        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 1.4
        thickness = 3
        padding_x = 20
        padding_y = 16
        margin = 16

        (text_w, text_h), baseline = cv2.getTextSize(label_text, font, font_scale, thickness)
        box_w = text_w + (2 * padding_x)
        box_h = text_h + baseline + (2 * padding_y)
        x0 = max(0, out.shape[1] - box_w - margin)
        y0 = margin
        x1 = x0 + box_w
        y1 = y0 + box_h

        cv2.rectangle(out, (x0, y0), (x1, y1), bg_color, -1)
        cv2.putText(
            out,
            label_text,
            (x0 + padding_x, y1 - padding_y - baseline),
            font,
            font_scale,
            (255, 255, 255),
            thickness,
            cv2.LINE_AA,
        )
        return out

    def _evaluate_quality(self, detection_count):
        min_good = self.config.good_count_min
        max_good = self.config.good_count_max

        is_good = min_good <= detection_count <= max_good
        return is_good, (not is_good)

    def on_detection_result_ready(self, annotated, detections, is_good, is_bad, detection_count):
        if self.current_mode == "continuous":
            self._show_frame(annotated)
            return

        # Software trigger handling
        self.total_triggers += 1
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        
        raw_path = self.config.raw_images_dir / f"trigger_{stamp}.jpg"
        if self.last_frame is not None:
            cv2.imwrite(str(raw_path), self.last_frame)
        
        annotated_with_badge = self._draw_judgement_badge(annotated, is_bad, detection_count)
        self._show_frame(annotated_with_badge)

        ng_path = self.config.ng_images_dir / f"ng_{stamp}.jpg"
        if is_bad:
            self.bad_count += 1
            cv2.imwrite(str(ng_path), annotated_with_badge)
            top_labels = ", ".join(
                [f"{det.class_name} {det.confidence:.2f}" for det in detections[:3]]
            )
            self.result_label.setText(
                f"Last Trigger Result: BAD ({detection_count} object(s)) | {top_labels}"
            )
        else:
            self.good_count += 1
            self.result_label.setText(f"Last Trigger Result: GOOD ({detection_count} object(s))")

        bad_pct = (self.bad_count / self.total_triggers) * 100 if self.total_triggers else 0.0
        self.good_value.setText(str(self.good_count))
        self.bad_value.setText(str(self.bad_count))
        self.bad_percent_value.setText(f"{bad_pct:.1f}%")

        target = "ng_images" if is_bad else "good"
        self.status_label.setText(
            f"Status: Trigger #{self.total_triggers} saved | raw_images + {target} | detector={self.detector.backend_name}"
        )

    def on_software_trigger(self):
        if self.cam_thread:
            self.cam_thread.send_software_trigger()
            self.status_label.setText("Status: Software trigger sent, waiting for frame...")

    def closeEvent(self, event):
        try:
            self.detection_thread.stop()
            if self.cam_thread:
                self.cam_thread.stop()
        except Exception:
            pass
        super().closeEvent(event)


def run_app(config: AppConfig, detector=None) -> int:
    app = QApplication(sys.argv)
    window = WizproInspectionUI(config, detector=detector)
    window.show()
    return app.exec_()


def show_startup_error(error_text: str) -> None:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    message = QMessageBox()
    message.setIcon(QMessageBox.Critical)
    message.setWindowTitle("Wizpro Camera Inspection")
    message.setText("Application startup failed")
    message.setInformativeText(error_text)
    message.exec_()
