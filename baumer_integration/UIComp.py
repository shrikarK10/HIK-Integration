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
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QProgressBar



#Config imports
from Config import DB_PATH, REPORT_DEFAULT_DAYS_BACK, REPORT_DIRECTORY

# DataLoader imports
from DataLoader import DetailsLoaderThread, ThumbnailLoader

#PDFGeneration imports
from PDFGenerationThread import PDFGenerationThread

class KPICard(QtWidgets.QFrame):
    def __init__(self, title, value="0", color="#003366", parent=None):
        super().__init__(parent)
        self.setObjectName("kpicard")
        self.setStyleSheet("""
            QFrame#kpicard {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 #e6f0fa,
                    stop:0.4 #dfe9f3,
                    stop:0.7 #ffffff,
                    stop:1 #f0f7ff
                );
                border-radius: 16px;
                border: 1px solid #c8d7e6;
            }
            QLabel {
                font-family: 'Segoe UI', -apple-system, sans-serif;
            }
        """)
        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(6)

        self.title = QtWidgets.QLabel(title)
        self.title.setStyleSheet("font-size:15px; color:#4a4a4a; font-weight:600;")
        self.title.setWordWrap(True)

        self.value = QtWidgets.QLabel(value)
        self.value.setStyleSheet(f"font-size:24px; color:{color}; font-weight:800;")
        self.value.setWordWrap(True)
        self._value_color = color

        v.addWidget(self.title, 0, QtCore.Qt.AlignHCenter)
        v.addStretch(1)
        v.addWidget(self.value, 0, QtCore.Qt.AlignHCenter)

        self.setMinimumSize(120, 90)

    def set_value(self, value):
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            txt = f"{value:,}" if isinstance(value, int) else f"{value:,.2f}"
        else:
            txt = str(value)
        self.value.setText(txt)

    def set_color(self, color: str):
        self._value_color = color
        self.value.setStyleSheet(f"font-size:24px; color:{color}; font-weight:800;")

    def set_title(self, title: str):
        self.title.setText(title)

    def value_text(self) -> str:
        return self.value.text()

class EmbeddedReportWidget(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("""
            QWidget {
                background:#4B4376; 
                border: 0px solid #4A90E2;
                border-radius: 5px;
            }
            QPushButton {
                background-color: #2E6DA4;
                color: white;
                padding: 8px 15px;
                border: none;
                border-radius: 5px;
                font: bold 12px "Segoe UI";
            }
            QPushButton:hover {
                background-color: #357ABD;
            }
            QRadioButton {
                font: bold 12px "Segoe UI";
                color: #ffffff;
                padding: 5px;
            }
            QTableWidget {
                background-color: white;
                border: 1px solid #ccc;
                border-radius: 5px;
                font-size: 18px; 
                color: #001E50;
                gridline-color: #ddd;
            }
            QHeaderView::section {
                background-color: #2E6DA4;
                color: white;
                font: bold 18px "Segoe UI";
                padding: 5px;
                border: none;
            }
            QComboBox {
                background-color: #ffffff;
                border: 1px solid #0078d4;
                border-radius: 8px;
                padding: 6px 30px 6px 10px;
                font: 14px 'Segoe UI';
                color: #333;
                min-width: 150px;
            }
            QComboBox::drop-down {
                border: none;
                width: 25px;
                subcontrol-origin: padding;
                subcontrol-position: top right;
            }
            QComboBox::down-arrow {
                image: url(:/icons/arrow-down.svg);  /* use a custom SVG or PNG */
                width: 14px;
                height: 14px;
            }
            QComboBox QAbstractItemView {
                border: 1px solid #0078d4;
                border-radius: 6px;
                background-color: #ffffff;
                selection-background-color: #0078d4;
                selection-color: #ffffff;
                padding: 5px;
            }               
            QDateEdit{
                background-color: white;
                border: 1px solid #ccc;
                border-radius: 5px;
                padding: 5px;
                font: 18px "Segoe UI";
            }
            QLabel {
                font: bold 18px "Segoe UI";
                color: #ffffff;
                padding: 5px;
            }
        """)

        # Header
        header = QLabel("Inspection Report Generator")
        header.setAlignment(Qt.AlignCenter)
        header.setStyleSheet(
            "font: bold 20px 'Segoe UI'; color: white; padding: 10px; background-color: #2E6DA4; border-radius: 5px;")

        # Left layout (filters)
        left_layout = QVBoxLayout()
        left_layout.addStretch(1)

        # Start Date
        self.start_date = QDateEdit()
        self.start_date.setCalendarPopup(True)
        self.start_date.setDate(datetime.datetime.now())
        self._style_calendar(self.start_date)

        # End Date
        self.end_date = QDateEdit()
        self.end_date.setCalendarPopup(True)
        self.end_date.setDate(datetime.datetime.now())
        self._style_calendar(self.end_date)

        self.shift_combo = QComboBox()
        self.shift_combo.addItems(["All", "Morning", "Evening","Night"])

        self.status_combo = QComboBox()
        self.status_combo.addItems(["All", "GOOD", "BAD"])
        self.status_combo.setCurrentText("All")

        self.search_button = QPushButton("Search")
        self.search_button.clicked.connect(self.update_table)

        left_layout.addWidget(QLabel("Start Date"))
        left_layout.addWidget(self.start_date)
        left_layout.addWidget(QLabel("End Date"))
        left_layout.addWidget(self.end_date)
        left_layout.addWidget(QLabel("Select Shift"))
        left_layout.addWidget(self.shift_combo)
        left_layout.addWidget(QLabel("Select Status"))
        left_layout.addWidget(self.status_combo)
        left_layout.addWidget(self.search_button)
        left_layout.addStretch(1)

        # Right layout
        right_layout = QVBoxLayout()
        self.summary_radio = QRadioButton("30 Days Summary")
        self.details_radio = QRadioButton("Details")
        self.summary_radio.setStyleSheet(""" font-size:18px; """)
        self.details_radio.setStyleSheet(""" font-size:18px; """)

        self.summary_radio.setChecked(True)

        self.table = QTableWidget()
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(
            ["Sr No", "Date", "Shift", "Total Count", "Good Count", "Bad Count"]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setAlternatingRowColors(True)

        # Connect frame double click
        self.table.cellDoubleClicked.connect(self.open_frame_image)

        radio_layout = QHBoxLayout()
        radio_layout.addWidget(self.summary_radio)
        radio_layout.addWidget(self.details_radio)
        right_layout.addLayout(radio_layout)
        right_layout.addWidget(self.table, 1)

        self.summary_radio.toggled.connect(self.update_table_layout)
        self.details_radio.toggled.connect(self.update_table_layout)
        self.summary_radio.toggled.connect(self._auto_set_dates)

        # --- NEW: Cancel button ---
        self.cancel_button = QPushButton("Cancel Loading")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_loading)
        right_layout.addWidget(self.cancel_button)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 2px solid #2E6DA4;
                border-radius: 5px;
                text-align: center;
                font: bold 12px "Segoe UI";
                color: white;
                background-color: #ffffff;
            }
            QProgressBar::chunk {
                background-color: #2E6DA4;
                border-radius: 3px;
            }
        """)

        self.cancel_pdf_button = QPushButton("Cancel PDF")
        self.cancel_pdf_button.setVisible(False)
        self.cancel_pdf_button.clicked.connect(self.cancel_pdf_generation)
        self.cancel_pdf_button.setStyleSheet("""
            QPushButton {
                background-color: #E74C3C;
                color: white;
                padding: 8px 15px;
                border: none;
                border-radius: 5px;
                font: bold 12px "Segoe UI";
            }
            QPushButton:hover {
                background-color: #C0392B;
            }
        """)

        self.pdf_button = QPushButton("Generate PDF")
        self.pdf_button.clicked.connect(self.generate_pdf_async)

        pdf_layout = QHBoxLayout()
        pdf_layout.addWidget(self.pdf_button)
        pdf_layout.addStretch()  # Push progress/cancel to the right if needed
        right_layout.addLayout(pdf_layout)  # Replace the old right_layout.addWidget(self.pdf_button)

        # Now add progress and cancel to the same sub-layout (they'll appear inline)
        pdf_layout.addWidget(self.progress_bar)
        pdf_layout.addWidget(self.cancel_pdf_button)

        # right_layout.addWidget(self.pdf_button)

        self.pdf_location = QLabel("PDF will be saved as 'report.pdf' in the /report.")
        self.pdf_location.setStyleSheet("font: italic 15px 'Segoe UI'; color: #ffffff; padding: 5px;")
        right_layout.addWidget(self.pdf_location)

        # Main layout
        main_layout = QHBoxLayout()
        main_layout.addLayout(left_layout, 1)
        main_layout.addLayout(right_layout, 2)
        main_layout.setSpacing(20)
        main_layout.setContentsMargins(20, 20, 20, 20)

        layout = QVBoxLayout()
        layout.addWidget(header)
        layout.addLayout(main_layout)
        self.setLayout(layout)
        self.table.verticalHeader().setVisible(False)

        # Lazy thumbnail tracking
        self.table.verticalScrollBar().valueChanged.connect(self._on_scroll)
        self.active_loaders = {}
        self.canceled = False

        self.update_table()

    # --- Style calendar popup ---

    def _style_calendar(self, date_edit):
        cal = date_edit.calendarWidget()
        cal.setGridVisible(True)
        cal.setVerticalHeaderFormat(QtWidgets.QCalendarWidget.NoVerticalHeader)
        cal.setHorizontalHeaderFormat(QtWidgets.QCalendarWidget.SingleLetterDayNames)
        cal.setNavigationBarVisible(True)

        cal.setStyleSheet("""       
            QCalendarWidget QWidget {
                background-color: #ffffff;
            }              
            QCalendarWidget {
                background-color: #ffffff;
                border: 2px solid #d0d7de;
                border-radius: 0px;
            }
            /* Main date grid */
            QCalendarWidget QAbstractItemView {
                font: 15px "Segoe UI";
                color: #222222;                     /* <-- makes all day numbers black */
                selection-background-color: #0078d4;
                selection-color: #ffffff;
                outline: none;
                gridline-color: #e0e0e0;
                alternate-background-color: #fafafa;
            }
            /* Ensure no blue text for weekends */
            QCalendarWidget QAbstractItemView:enabled {
                color: #222222;
                selection-background-color: #0078d4;
                selection-color: #ffffff;
            }
            /* Top navigation bar */
            QCalendarWidget QWidget#qt_calendar_navigationbar {
                background-color: #f5f5f5;
                border-top-left-radius: 10px;
                border-top-right-radius: 10px;
                padding: 4px;
            }
            QCalendarWidget QToolButton {
                background: transparent;
                color: #222222;
                font: bold 14px "Segoe UI";
                border: none;
                padding: 4px 8px;
                margin: 2px;
            }
            QCalendarWidget QToolButton:hover {
                background-color: #e8e8e8;
                border-radius: 0px;
            }
            /* Month navigation buttons */
            QCalendarWidget QToolButton#qt_calendar_prevmonth,
            QCalendarWidget QToolButton#qt_calendar_nextmonth {
                background-color: #f0f0f0;
                border-radius: 0px;
                padding: 5px;
            }
            QCalendarWidget QToolButton#qt_calendar_prevmonth:hover,
            QCalendarWidget QToolButton#qt_calendar_nextmonth:hover {
                background-color: #e0e0e0;
            }
            /* Month & Year spinboxes */
            QCalendarWidget QSpinBox {
                background: #ffffff;
                border: 1px solid #cccccc;
                border-radius: 0px;
                padding: 2px;
                font: 13px "Segoe UI";
                color: #333333;
            }
        """)

        # Slightly larger for better user experience
        cal.setFixedSize(420, 320)

    def _auto_set_dates(self, checked):
        if checked:
            end = datetime.date.today()
            start = end - datetime.timedelta(days=REPORT_DEFAULT_DAYS_BACK)
            self.start_date.setDate(start)
            self.end_date.setDate(end)

    def update_table_layout(self):
        self.table.clear()
        if self.summary_radio.isChecked():
            self.table.setColumnCount(6)
            self.table.setHorizontalHeaderLabels(
                ["Sr No", "Date", "Shift", "Total Count", "Good Count", "Bad Count"]
            )
        else:
            self.table.setColumnCount(5)
            self.table.setHorizontalHeaderLabels(
                ["Sr No", "Date", "Shift", "Frame", "Status"]
            )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.update_table()

    def update_table(self):
        start = self.start_date.date().toPyDate()
        end = self.end_date.date().toPyDate()
        shift = self.shift_combo.currentText()
        status = self.status_combo.currentText()
        is_summary = self.summary_radio.isChecked()

        try:
            with sqlite3.connect(DB_PATH) as conn:
                if is_summary:
                    query = """
                        SELECT strftime('%Y-%m-%d', t.timestamp) as date, os.name as shift,
                            COUNT(*) as total, 
                            SUM(CASE WHEN t.status = 'GOOD' THEN 1 ELSE 0 END) as good,
                            SUM(CASE WHEN t.status = 'BAD' THEN 1 ELSE 0 END) as bad
                        FROM Transactions t
                        JOIN Operating_Shifts os ON t.Operating_Shifts_id = os.id
                        WHERE strftime('%Y-%m-%d', t.timestamp) BETWEEN ? AND ?
                        AND t.status != 'EMPTY'
                    """ + (" AND os.name = ?" if shift != "All" else "") + """
                        GROUP BY date, os.name
                        ORDER BY date DESC
                        LIMIT 30
                    """
                    params = [start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d')]
                    if shift != "All":
                        params.append(shift)

                    rows = conn.execute(query, params).fetchall()
                    print(f"[DEBUG] Summary rows loaded: {len(rows)} groups")

                    self.table.setRowCount(len(rows))
                    for i, row in enumerate(rows):
                        self.table.setItem(i, 0, QTableWidgetItem(str(i + 1)))
                        for j, val in enumerate(row, start=1):
                            item = QTableWidgetItem(str(val) if val else "0")
                            item.setTextAlignment(Qt.AlignCenter)
                            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                            self.table.setItem(i, j, item)

                else:
                    query = """
                        SELECT strftime('%Y-%m-%d', t.timestamp) as date, os.name as shift,
                            t.image_file_path as frame, t.status
                        FROM Transactions t
                        JOIN Operating_Shifts os ON t.Operating_Shifts_id = os.id
                        WHERE strftime('%Y-%m-%d', t.timestamp) BETWEEN ? AND ?
                    """ + (" AND os.name = ?" if shift != "All" else "") + \
                            (" AND t.status = ?" if status != "All" else "") + """
                        ORDER BY t.timestamp DESC
                    """

                    params = [start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d')]
                    if shift != "All":
                        params.append(shift)
                    if status != "All":
                        params.append("GOOD" if status == "GOOD" else "BAD")

                    # stop old thread if running
                    if hasattr(self, "loader_thread") and self.loader_thread.isRunning():
                        self.loader_thread.stop()
                        self.loader_thread.wait()

                    self.table.setRowCount(0)  # clear
                    self.loader_thread = DetailsLoaderThread(query, params, batch_size=100)
                    self.loader_thread.batch_ready.connect(self._append_rows)
                    self.loader_thread.finished.connect(self._on_loading_finished)
                    self.loader_thread.start()
                    self.cancel_button.setEnabled(True)

        except sqlite3.Error as e:
            print(f"[ERROR] DB query failed in update_table: {e}")
            QMessageBox.warning(self, "DB Error", f"Could not connect to DB\nError: {e}")
            self._load_sample_data(is_summary)

    def _append_rows(self, rows):
        start_row = self.table.rowCount()
        self.table.setRowCount(start_row + len(rows))

        for i, row in enumerate(rows, start=start_row):
            self.table.setItem(i, 0, QTableWidgetItem(str(i + 1)))
            self.table.setItem(i, 1, QTableWidgetItem(str(row[0]) or ""))
            self.table.setItem(i, 2, QTableWidgetItem(str(row[1]) or ""))

            # Frame placeholder for lazy load
            frame_path = row[2]
            frame_item = QTableWidgetItem("Loading...")
            frame_item.setFlags(frame_item.flags() & ~Qt.ItemIsEditable)
            frame_item.setData(Qt.UserRole, frame_path)
            self.table.setItem(i, 3, frame_item)

            status_item = QTableWidgetItem(str(row[3]) or "")
            status_item.setFlags(status_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(i, 4, status_item)

        # trigger lazy load for visible rows
        self._on_scroll(self.table.verticalScrollBar().value())

    def _on_scroll(self, value):
        first_row = self.table.rowAt(0)
        last_row = self.table.rowAt(self.table.viewport().height())
        if last_row == -1:
            last_row = self.table.rowCount() - 1

        for row in range(first_row, last_row + 1):
            item = self.table.item(row, 3)
            if item and item.text() == "Loading...":
                frame_path = item.data(Qt.UserRole)
                if frame_path and row not in self.active_loaders:
                    loader = ThumbnailLoader(row, frame_path)
                    loader.thumbnail_ready.connect(self._set_thumbnail)
                    loader.finished.connect(lambda r=row: self.active_loaders.pop(r, None))
                    self.active_loaders[row] = loader
                    loader.start()

    def _set_thumbnail(self, row, icon):
        item = self.table.item(row, 3)
        if item:
            if not icon.isNull():
                item.setIcon(icon)
                item.setText("")
            else:
                item.setText("No Image")

    def _on_loading_finished(self):
        self.cancel_button.setEnabled(False)
        print("[DEBUG] Loading finished")

    def cancel_loading(self):
        if hasattr(self, "loader_thread") and self.loader_thread.isRunning():
            self.loader_thread.stop()
            self.loader_thread.wait()
            self.cancel_button.setEnabled(False)
            print("[DEBUG] Loading cancelled by user")

    def _load_sample_data(self, is_summary):
        sample_rows = [
            ["2025-09-18", "Morning", 2377, 0, 2377] if is_summary else
            ["2025-09-18", "Morning", "frame1.jpg", "Not Good"]
        ]
        self.table.setRowCount(len(sample_rows))
        for i, row in enumerate(sample_rows):
            self.table.setItem(i, 0, QTableWidgetItem(str(i + 1)))
            for j, val in enumerate(row, start=1):
                self.table.setItem(i, j, QTableWidgetItem(str(val)))

    def open_frame_image(self, row, col):
        if self.details_radio.isChecked() and col == 3:
            item = self.table.item(row, col)
            if item:
                frame_path = item.data(Qt.UserRole)
                if frame_path and os.path.exists(frame_path):
                    viewer = QtWidgets.QDialog(self)
                    viewer.setWindowTitle("Frame Viewer")
                    layout = QtWidgets.QVBoxLayout(viewer)
                    label = QtWidgets.QLabel()
                    pixmap = QtGui.QPixmap(frame_path)
                    label.setPixmap(pixmap.scaled(800, 600, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                    layout.addWidget(label)
                    viewer.resize(820, 620)
                    viewer.exec_()
                else:
                    QMessageBox.warning(self, "Image Missing", "Image file not found.")

    def generate_pdf_async(self):
        start_date = self.start_date.date().toPyDate()
        end_date = self.end_date.date().toPyDate()
        shift = self.shift_combo.currentText()
        status = self.status_combo.currentText()
        is_summary = self.summary_radio.isChecked()

        rows = []
        for i in range(self.table.rowCount()):
            row_data = []
            for j in range(self.table.columnCount()):
                item = self.table.item(i, j)
                if item:
                    if not is_summary and j == 3:  # Frame column in details mode: extract path from UserRole
                        frame_path = item.data(QtCore.Qt.UserRole)
                        row_data.append(frame_path or "")  #path (string) for PDF thread
                    else:
                        row_data.append(item.text() or "")  # Standard text extraction
                else:
                    row_data.append("")
            rows.append(row_data[1:])  # Skip Sr No (index 0)

        # ---Hide button, show inline progress (no dialog) ---
        self.pdf_button.setVisible(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.progress_bar.setRange(0, 100)  # Start determinate
        self.cancel_pdf_button.setVisible(True)
        self.pdf_location.setText("Generating PDF...")

        # ---Connect progress with indeterminate handling ---
        def update_progress(value):
            if value == 70:  # Detected build phase start
                self.progress_bar.setRange(0, 0)  # Indeterminate (pulsing)
                self.progress_bar.setFormat("Building PDF... %p%")  # Optional: Custom text
            elif value == 100:  # End of build
                self.progress_bar.setRange(0, 100)  # Back to determinate
                self.progress_bar.setFormat("Complete")  # Optional
            self.progress_bar.setValue(value)

        def toggle_indeterminate(start_pulsing):
            if start_pulsing:
                self.progress_bar.setRange(0, 0)  # Pulse
                self.progress_bar.setFormat("Rendering PDF...")
            else:
                self.progress_bar.setRange(0, 100)  # Stop pulsing
                self.progress_bar.setFormat("%p%")

        self.thread = PDFGenerationThread(start_date, end_date, shift, status, is_summary, rows)
        self.thread.progress.connect(update_progress)  # Use the wrapped function
        self.thread.indeterminate_mode.connect(toggle_indeterminate)
        self.thread.finished.connect(self.pdf_generation_finished)
        self.thread.error.connect(self.pdf_generation_error)
        self.canceled = False
        self.thread.start()

    def cancel_pdf_generation(self):
        if hasattr(self, 'thread') and self.thread.isRunning():
            self.thread.stop()
            self.canceled = True
            # ---Hide progress, show button, update status ---
            self.progress_bar.setVisible(False)
            self.cancel_pdf_button.setVisible(False)
            self.pdf_button.setVisible(True)
            self.pdf_location.setText("PDF generation cancelled.")

    def pdf_generation_finished(self, pdf_path, error_message):
        # --- If cancelled, ignore or reinforce cancelled status ---
        if self.canceled or error_message == "Cancelled":
            self.pdf_location.setText("PDF generation cancelled.")
            self.canceled = False
            # Ensure UI is reset (in case thread finished after cancel)
            self.progress_bar.setVisible(False)
            self.cancel_pdf_button.setVisible(False)
            self.pdf_button.setVisible(True)
            return

        # Hide progress/cancel, show button ---
        self.progress_bar.setVisible(False)
        self.cancel_pdf_button.setVisible(False)
        self.pdf_button.setVisible(True)

        # ---Ensure determinate mode on finish/error ---
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setFormat("%p%")

        if error_message:
            QtWidgets.QMessageBox.critical(self, "Error", error_message)
            self.pdf_location.setText(f"Error generating PDF: {error_message}")
        else:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            report_dir = os.path.join(current_dir, REPORT_DIRECTORY)
            self.pdf_location.setText(f"PDF 'report_{timestamp}.pdf' generated successfully in {report_dir}")

    def pdf_generation_error(self, error_message):
        # ---If cancelled, ignore ---
        if self.canceled:
            self.canceled = False
            return

        # ---Hide progress/cancel, show button ---
        self.progress_bar.setVisible(False)
        self.cancel_pdf_button.setVisible(False)
        self.pdf_button.setVisible(True)

        # ---Ensure determinate mode on finish/error ---
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setFormat("%p%")

        QtWidgets.QMessageBox.critical(self, "Error", error_message)
        self.pdf_location.setText(f"Error generating PDF: {error_message}")
