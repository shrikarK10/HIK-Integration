# main.py
import os
import datetime
import io
from PyQt5 import QtCore

# ReportLab imports for PDF

from reportlab.lib.pagesizes import letter, landscape, A4
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, KeepTogether
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.platypus import Image


class PDFGenerationThread(QtCore.QThread):
    progress = QtCore.pyqtSignal(int)
    finished = QtCore.pyqtSignal(str, str)
    error = QtCore.pyqtSignal(str)
    indeterminate_mode = QtCore.pyqtSignal(bool)

    def __init__(self, start_date, end_date, shift, status, is_summary, rows):
        super().__init__()
        self.start_date = start_date
        self.end_date = end_date
        self.shift = shift
        self.status = status
        self.is_summary = is_summary
        self.rows = rows
        self._is_running = True

    def run(self):
        try:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            report_dir = os.path.join(current_dir, "report")
            os.makedirs(report_dir, exist_ok=True)

            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            pdf_path = os.path.join(report_dir, f"report_{timestamp}.pdf")

            # ---Build in memory to allow cancel without writing file ---
            buffer = io.BytesIO()
            doc = SimpleDocTemplate(buffer, pagesize=landscape(A4))
            elements = []

            title = "Inspection Report - Summary" if self.is_summary else "Inspection Report - Details"

            elements.append(Paragraph(title, getSampleStyleSheet()['Heading1']))

            headers = (
                ["Date", "Shift", "Total Count", "Good Count", "Bad Count"]
                if self.is_summary else
                ["Date", "Shift", "Frame", "Status"]
            )

            # Build table data
            table_data = [headers]
            total_rows = len(self.rows)
            for idx, row in enumerate(self.rows, start=1):
                if not self._is_running:
                    return

                if self.is_summary:
                    table_data.append(row)
                else:
                    # Insert thumbnail for frame (with error handling)
                    frame_path = row[2]
                    if frame_path and os.path.exists(frame_path):
                        try:
                            img = Image(frame_path, width=1.2 * inch, height=0.9 * inch)
                            row_with_img = [row[0], row[1], img, row[3]]
                        except Exception as img_err:
                            print(f"Warning: Failed to load image {frame_path}: {img_err}")  # Or emit a signal
                            row_with_img = [row[0], row[1],
                                            Paragraph("Image Load Failed", getSampleStyleSheet()['Normal']), row[3]]
                    else:
                        row_with_img = [row[0], row[1], Paragraph("No Image", getSampleStyleSheet()['Normal']), row[3]]

                    table_data.append(row_with_img)

                # ---Progress for row processing (0-70%) ---
                row_progress = int((idx / total_rows) * 70)  # Scale to 70% max for this phase
                self.progress.emit(row_progress)

            # ---Emit 70% before heavy build phase ---
            self.progress.emit(70)

            # ---Create table after loop for efficiency ---
            col_widths = [1.5 * inch, 1 * inch, 1.5 * inch, 1 * inch] if not self.is_summary else None
            table = Table(table_data, repeatRows=1, colWidths=col_widths)
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#2E6DA4")),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('GRID', (0, 0), (-1, -1), 0.25, colors.black),
                # Optional: Better padding for image cells
                ('LEFTPADDING', (0, 0), (-1, -1), 5),
                ('RIGHTPADDING', (0, 0), (-1, -1), 5),
            ]))
            elements.append(table)

            # --- Signal to enter indeterminate mode ---
            self.indeterminate_mode.emit(True)

            doc.build(elements)

            # --- to exit indeterminate mode ---
            self.indeterminate_mode.emit(False)

            # --- Emit 100% only AFTER build completes ---
            self.progress.emit(100)

            # --- Only write to file if not cancelled ---
            if self._is_running:
                with open(pdf_path, 'wb') as f:
                    f.write(buffer.getvalue())
                self.finished.emit(pdf_path, "")
            else:
                self.finished.emit("", "Cancelled")
        except Exception as e:
            self.progress.emit(0)  # Reset on error
            self.error.emit(str(e))

    def stop(self):
        self._is_running = False
