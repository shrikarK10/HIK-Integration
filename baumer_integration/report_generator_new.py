import sys
import subprocess
import os
import sqlite3
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QDateEdit, QComboBox, QPushButton, QRadioButton, \
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, QProgressDialog
from PyQt5.QtCore import Qt, QSize, QThread, pyqtSignal, QTimer
from PyQt5.QtGui import QIcon
from datetime import datetime
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, KeepTogether
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
import logging

from Config import PDF_MAX_DETAIL_ROWS, PDF_MAX_SUMMARY_ROWS
# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s', filename='report_generator.log')
logger = logging.getLogger(__name__)

class PDFGenerationThread(QThread):
    progress = pyqtSignal(int)
    finished = pyqtSignal(str, str)  # (pdf_path, error_msg)
    error = pyqtSignal(str)

    def __init__(self, start_date, end_date, shift, status, is_summary, table_rows):
        super().__init__()
        self.start_date = start_date
        self.end_date = end_date
        self.shift = shift
        self.status = status
        self.is_summary = is_summary
        self.table_rows = table_rows[:PDF_MAX_DETAIL_ROWS if not is_summary else PDF_MAX_SUMMARY_ROWS]  # Limit to 50 for details, 30 for summary
        self.running = True

    def run(self):
        logger.debug("PDFGenerationThread started")
        try:
            current_dir = os.getcwd()
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            report_dir = os.path.join(current_dir, "report")
            os.makedirs(report_dir, exist_ok=True)
            pdf_file_path = os.path.join(report_dir, f"report_{timestamp}.pdf")
            logger.debug(f"PDF file path: {pdf_file_path}")

            if not os.access(report_dir, os.W_OK):
                raise Exception("No write permissions for report directory")

            # Headers & data
            headers = (
                ["Sr No", "Date", "Shift", "Total Count", "Good Count", "Bad Count"]
                if self.is_summary else
                ["Sr No", "Date", "Shift", "Frame", "Status"]
            )
            table_data = [headers] + [[str(i + 1)] + row for i, row in enumerate(self.table_rows)] \
                if self.table_rows else [headers + ["No data available"]]
            logger.debug(f"Table data rows: {len(table_data)}")

            # PDF doc
            doc = SimpleDocTemplate(
                pdf_file_path,
                pagesize=letter,
                leftMargin=0.75 * inch,
                rightMargin=0.75 * inch,
                topMargin=0.75 * inch,
                bottomMargin=0.75 * inch
            )
            elements = []

            # Common border style for boxed sections
            border_style = TableStyle([
                ('BOX', (0, 0), (-1, -1), 2, colors.darkblue),
                ('LEFTPADDING', (0, 0), (-1, -1), 12),
                ('RIGHTPADDING', (0, 0), (-1, -1), 12),
                ('TOPPADDING', (0, 0), (-1, -1), 12),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
            ])

            # --- Logo ---
            styles = getSampleStyleSheet()
            logo_style = ParagraphStyle(name='LogoStyle', fontSize=10, textColor=colors.gray)
            left_logo_path = os.path.join("assets", "company-logo.png")
            right_logo_path = os.path.join("assets", "Wizpro.png")
            max_logo_height, max_logo_width = 0.75 * inch, 1.5 * inch
            try:
                if os.path.exists(left_logo_path) and os.path.exists(right_logo_path):
                    left_logo = Image(left_logo_path, width=max_logo_width, height=max_logo_height, kind='proportional')
                    right_logo = Image(right_logo_path, width=max_logo_width, height=max_logo_height,
                                       kind='proportional')
                    logo_table = Table([[left_logo, Paragraph(" ", logo_style), right_logo]],
                                       colWidths=[1.5 * inch, None, 1.5 * inch])
                    logo_table.setStyle(TableStyle([
                        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                        ('ALIGN', (0, 0), (-1, -1), 'CENTER')
                    ]))
                    logo_box = Table([[logo_table]], colWidths=[doc.width])
                else:
                    logo_box = Table([[Paragraph("Logos not found in assets folder.", logo_style)]],
                                     colWidths=[doc.width])
                logo_box.setStyle(border_style)
                elements.append(KeepTogether(logo_box))
            except Exception as e:
                elements.append(Paragraph(f"Error loading logos: {str(e)}", logo_style))

            # --- Title ---
            title_style = ParagraphStyle(name='TitleStyle', parent=styles['Heading1'],
                                         fontSize=18, textColor=colors.darkblue,
                                         spaceAfter=20, alignment=1)
            title_box = Table([[Paragraph("Inspection Report", title_style)]], colWidths=[doc.width])
            title_box.setStyle(border_style)
            elements.append(KeepTogether(title_box))

            # --- Filters ---
            filter_style = ParagraphStyle(name='FilterStyle', parent=styles['Normal'],
                                          fontSize=12, textColor=colors.black, spaceAfter=10)
            filter_content = [
                Paragraph(f"<b>Start Date:</b> {self.start_date.strftime('%Y-%m-%d')}", filter_style),
                Paragraph(f"<b>End Date:</b> {self.end_date.strftime('%Y-%m-%d')}", filter_style),
                Paragraph(f"<b>Shifts:</b> {self.shift}", filter_style),
            ]
            if not self.is_summary:
                filter_content.append(Paragraph(f"<b>Status:</b> {self.status}", filter_style))
            filter_box = Table([[filter_content]], colWidths=[doc.width])
            filter_box.setStyle(border_style)
            elements.append(KeepTogether(filter_box))

            # --- Data Table (framed & padded, splittable) ---
            logger.debug("Building data table")

            # Insert empty padding rows (top & bottom) so border isn't stuck
            padded_table_data = [[""] * len(headers)] + table_data + [[""] * len(headers)]

            col_widths = [inch * 0.8] + [inch * (4.4 / (len(headers) - 1))] * (len(headers) - 1)
            data_table = Table(padded_table_data, colWidths=col_widths, splitByRow=True, repeatRows=2)

            data_table.setStyle(TableStyle([
                # Outer border
                ('BOX', (0, 0), (-1, -1), 2, colors.darkblue),

                # Invisible first row (padding)
                ('LINEBELOW', (0, 0), (-1, 0), 0, colors.white),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),

                # Invisible last row (padding)
                ('LINEABOVE', (0, -1), (-1, -1), 0, colors.white),
                ('TEXTCOLOR', (0, -1), (-1, -1), colors.white),

                # Header row (now row 1, since row 0 is padding)
                ('BACKGROUND', (0, 1), (-1, 1), colors.lightslategray),
                ('TEXTCOLOR', (0, 1), (-1, 1), colors.whitesmoke),
                ('ALIGN', (0, 1), (-1, 1), 'CENTER'),
                ('FONTNAME', (0, 1), (-1, 1), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 1), (-1, 1), 12),
                ('BOTTOMPADDING', (0, 1), (-1, 1), 12),

                # Body rows (2 .. -2)
                ('BACKGROUND', (0, 2), (-1, -2), colors.white),
                ('TEXTCOLOR', (0, 2), (-1, -2), colors.black),
                ('ALIGN', (0, 2), (-1, -2), 'CENTER'),
                ('FONTNAME', (0, 2), (-1, -2), 'Helvetica'),
                ('FONTSIZE', (0, 2), (-1, -2), 10),
                ('GRID', (0, 2), (-1, -2), 1, colors.lightslategray),
                ('VALIGN', (0, 2), (-1, -2), 'MIDDLE'),

                # Padding
                ('LEFTPADDING', (0, 0), (-1, -1), 8),
                ('RIGHTPADDING', (0, 0), (-1, -1), 8),
                ('TOPPADDING', (0, 0), (-1, -1), 6),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ]))
            elements.append(data_table)
            elements.append(Spacer(1, 20))

            # --- Footer ---
            footer_style = ParagraphStyle(name='FooterStyle', parent=styles['Normal'],
                                          fontSize=8, textColor=colors.gray, alignment=1)
            footer_box = Table(
                [[Paragraph(f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S IST')}", footer_style)]],
                colWidths=[doc.width]
            )
            footer_box.setStyle(border_style)
            elements.append(KeepTogether(footer_box))

            # Build PDF
            doc.build(elements)
            self.finished.emit(pdf_file_path, "")

        except Exception as e:
            error_msg = f"PDF generation failed: {str(e)}"
            logger.exception(error_msg)
            self.error.emit(error_msg)
            self.finished.emit("", error_msg)

    def stop(self):
        self.running = False
        self.quit()
        self.wait()

class ReportDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Inspection Report Generator")
        self.setMinimumSize(800, 600)
        self.setStyleSheet("""
            QDialog {
                background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1, stop: 0 #4A90E2, stop: 1 #D3D3D3);
                border: 1px solid #4A90E2;
                border-radius: 10px;
                box-shadow: 0 5px 15px rgba(0, 0, 0, 0.3);
            }
            QPushButton {
                background-color: #4A90E2;
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
                gridline-color: #ddd;
            }
            QHeaderView::section {
                background-color: #4A90E2;
                color: white;
                font: bold 12px "Segoe UI";
                padding: 5px;
                border: none;
            }
            QDateEdit, QComboBox {
                background-color: white;
                border: 1px solid #ccc;
                border-radius: 5px;
                padding: 5px;
                font: 12px "Segoe UI";
            }
            QLabel {
                font: bold 14px "Segoe UI";
                color: #ffffff;
                padding: 5px;
            }
        """)

        header = QLabel("Inspection Report Generator")
        header.setAlignment(Qt.AlignCenter)
        header.setStyleSheet("font: bold 18px 'Segoe UI'; color: white; padding: 10px; background-color: #2E6DA4; border-radius: 5px;")

        left_layout = QVBoxLayout()
        left_layout.addStretch(1)
        self.start_date = QDateEdit()
        self.start_date.setDate(datetime(2025, 7, 1))
        self.end_date = QDateEdit()
        self.end_date.setDate(datetime.now())
        self.shift_combo = QComboBox()
        self.shift_combo.addItems(["All", "Morning", "Afternoon", "Evening", "Night"])
        self.status_combo = QComboBox()
        self.status_combo.addItems(["All", "Good", "Not Good"])
        self.status_combo.setCurrentText("All")
        self.search_button = QPushButton("Search")
        self.search_button.setIcon(QIcon("icons/search.png"))
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

        right_layout = QVBoxLayout()
        self.summary_radio = QRadioButton("30 Days Summary")
        self.details_radio = QRadioButton("Details")
        self.summary_radio.setChecked(True)
        self.table = QTableWidget()
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.table.setColumnCount(6 if self.summary_radio.isChecked() else 5)
        self.table.setHorizontalHeaderLabels(["Sr No", "Date", "Shift", "Total Count", "Good Count", "Bad Count"] if self.summary_radio.isChecked() else ["Sr No", "Date", "Shift", "Frame", "Status"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setAlternatingRowColors(True)

        radio_layout = QHBoxLayout()
        radio_layout.addWidget(self.summary_radio)
        radio_layout.addWidget(self.details_radio)
        right_layout.addLayout(radio_layout)
        right_layout.addWidget(self.table, 1)

        self.summary_radio.toggled.connect(self.update_table_layout)
        self.details_radio.toggled.connect(self.update_table_layout)

        self.pdf_button = QPushButton("Generate PDF")
        self.pdf_button.setIcon(QIcon("icons/pdf.png"))
        self.pdf_button.clicked.connect(self.generate_pdf_async)
        right_layout.addWidget(self.pdf_button)

        self.pdf_location = QLabel("PDF will be saved as 'report.pdf' in the current directory.")
        self.pdf_location.setStyleSheet("font: italic 10px 'Segoe UI'; color: #ffffff; padding: 5px;")
        right_layout.addWidget(self.pdf_location)

        main_layout = QHBoxLayout()
        main_layout.addLayout(left_layout, 1)
        main_layout.addLayout(right_layout, 2)
        main_layout.setSpacing(20)
        main_layout.setContentsMargins(20, 20, 20, 20)

        layout = QVBoxLayout()
        layout.addWidget(header)
        layout.addLayout(main_layout)
        self.setLayout(layout)

        self.update_table()

    def update_table_layout(self):
        self.table.clear()
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.table.setColumnCount(6 if self.summary_radio.isChecked() else 5)
        self.table.setHorizontalHeaderLabels(["Sr No", "Date", "Shift", "Total Count", "Good Count", "Bad Count"] if self.summary_radio.isChecked() else ["Sr No", "Date", "Shift", "Frame", "Status"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.update_table()

    def update_table(self):
        start = self.start_date.date().toPyDate()
        end = self.end_date.date().toPyDate()
        shift = self.shift_combo.currentText()
        status = self.status_combo.currentText()
        is_summary = self.summary_radio.isChecked()

        with sqlite3.connect("logs.db") as conn:
            if is_summary:
                query = """
                    SELECT strftime('%Y-%m-%d', t.timestamp) as date, os.name as shift,
                           COUNT(*) as total, SUM(CASE WHEN t.status = 'Good' THEN 1 ELSE 0 END) as good,
                           SUM(CASE WHEN t.status = 'Not Good' THEN 1 ELSE 0 END) as bad
                    FROM Transactions t
                    JOIN Operating_Shifts os ON t.Operating_Shifts_id = os.id
                    WHERE DATE(t.timestamp) BETWEEN ? AND ?
                    """ + ("AND os.name = ?" if shift != "All" else "") + """
                    GROUP BY date, os.name
                    ORDER BY date DESC
                    LIMIT 30
                """
                params = [start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d')]
                if shift != "All":
                    params.append(shift)
                rows = conn.execute(query, params).fetchall()
                logger.debug(f"Summary rows fetched: {len(rows)}")
                self.table.setRowCount(len(rows))
                for i, row in enumerate(rows):
                    self.table.setItem(i, 0, QTableWidgetItem(str(i + 1)))
                    for j, val in enumerate(row[:5], start=1):
                        item = QTableWidgetItem(str(val) if val else "0")
                        item.setTextAlignment(Qt.AlignCenter)
                        self.table.setItem(i, j, item)
            else:
                query = """
                    SELECT t.id, strftime('%Y-%m-%d', t.timestamp) as date, os.name as shift,
                           t.image_file_path as frame, t.status
                    FROM Transactions t
                    JOIN Operating_Shifts os ON t.Operating_Shifts_id = os.id
                    WHERE DATE(t.timestamp) BETWEEN ? AND ?
                    """ + ("AND os.name = ?" if shift != "All" else "") + """
                    """ + ("AND t.status = ?" if status != "All" else "") + """
                    ORDER BY t.timestamp DESC
                    LIMIT 50
                """
                params = [start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d')]
                if shift != "All":
                    params.append(shift)
                if status != "All":
                    params.append(status)
                rows = conn.execute(query, params).fetchall()
                logger.debug(f"Details rows fetched: {len(rows)}")
                self.table.setRowCount(len(rows))
                for i, row in enumerate(rows):
                    self.table.setItem(i, 0, QTableWidgetItem(str(i + 1)))
                    self.table.setItem(i, 1, QTableWidgetItem(str(row[1]) if row[1] else ""))
                    self.table.setItem(i, 2, QTableWidgetItem(str(row[2]) if row[2] else ""))
                    self.table.setItem(i, 3, QTableWidgetItem(str(row[3]) if row[3] else ""))
                    self.table.setItem(i, 4, QTableWidgetItem(str(row[4]) if row[4] else ""))

        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        if self.table.rowCount() == 0:
            self.table.setRowCount(1)
            for j in range(self.table.columnCount()):
                self.table.setItem(0, j, QTableWidgetItem(""))
        self.table.resizeColumnsToContents()
        self.table.updateGeometry()
        self.adjustSize()

    def accept(self):
        super().accept()

    def generate_pdf_async(self):
        start_date = self.start_date.date().toPyDate()
        end_date = self.end_date.date().toPyDate()
        shift = self.shift_combo.currentText()
        status = self.status_combo.currentText()
        is_summary = self.summary_radio.isChecked()

        rows = []
        max_rows = 30 if is_summary else 50  # Limit to 30 for summary, 50 for details
        for i in range(min(self.table.rowCount(), max_rows)):
            row_data = []
            for j in range(self.table.columnCount()):
                item = self.table.item(i, j)
                row_data.append(item.text() if item else "")
            rows.append(row_data)
        logger.debug(f"Collected {len(rows)} rows for PDF generation")
        print(f"Collected {len(rows)} rows for PDF generation")
        self.progress_dialog = QProgressDialog("Generating PDF...", "Cancel", 0, 100, self)
        self.progress_dialog.setWindowModality(Qt.WindowModal)
        self.progress_dialog.setMinimumDuration(0)
        self.progress_dialog.canceled.connect(self.cancel_pdf_generation)
        logger.debug("Progress dialog created")
        print("Progress dialog created")

        self.thread = PDFGenerationThread(start_date, end_date, shift, status, is_summary, rows)
        self.thread.progress.connect(self.progress_dialog.setValue)
        self.thread.finished.connect(self.pdf_generation_finished)
        self.thread.error.connect(self.pdf_generation_error)
        self.thread.finished.connect(lambda: logger.debug("PDF thread finished"))
        self.thread.start()
        logger.debug("PDF generation thread started")
        print("PDF generation thread started")

        # Add timeout to prevent hanging
        QTimer.singleShot(30000, self.check_thread_timeout)

    def check_thread_timeout(self):
        if hasattr(self, 'thread') and self.thread.isRunning():
            logger.warning("PDF generation timed out after 30 seconds")
            self.cancel_pdf_generation()
            self.pdf_location.setText("PDF generation timed out.")
            QMessageBox.warning(self, "Timeout", "PDF generation took too long and was cancelled.")

    def cancel_pdf_generation(self):
        if hasattr(self, 'thread') and self.thread.isRunning():
            self.thread.stop()
            self.progress_dialog.close()
            self.pdf_location.setText("PDF generation cancelled.")
            logger.debug("PDF generation cancelled")
            print("PDF generation cancelled")

    def pdf_generation_finished(self, pdf_path, error_message):
        self.progress_dialog.close()
        if error_message:
            QMessageBox.critical(self, "Error", error_message)
            self.pdf_location.setText(f"Error generating PDF: {error_message}")
            logger.error(f"PDF generation failed: {error_message}")
            print(f"PDF generation failed: {error_message}")
        else:
            current_dir = os.getcwd()
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            report_dir = os.path.join(current_dir, "report")
            self.pdf_location.setText(f"PDF 'report_{timestamp}.pdf' generated successfully in {report_dir}")
            logger.debug(f"PDF generated at: {pdf_path}")
            print(f"PDF generated at: {pdf_path}")

    def pdf_generation_error(self, error_message):
        self.progress_dialog.close()
        QMessageBox.critical(self, "Error", error_message)
        self.pdf_location.setText(f"Error generating PDF: {error_message}")
        logger.error(f"PDF generation error: {error_message}")
        print(f"PDF generation error: {error_message}")



