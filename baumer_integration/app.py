# import sys
# from PyQt5.QtWidgets import (
#     QApplication, QMainWindow, QWidget, QLabel, QVBoxLayout, QHBoxLayout,
#     QGridLayout, QFrame, QTabWidget, QListWidget, QListWidgetItem
# )
# from PyQt5.QtCore import Qt, QSize
# from PyQt5.QtGui import QIcon, QPixmap


# # ---------------- CAMERA TILE ----------------
# class CameraWidget(QLabel):
#     def __init__(self, cam_id):
#         super().__init__()
#         self.cam_id = cam_id
#         self.setText(f"CAM {cam_id}\nNO SIGNAL")
#         self.setAlignment(Qt.AlignCenter)
#         self.setStyleSheet("""
#             QLabel {
#                 background-color: black;
#                 border: 2px solid #00C853;
#                 color: white;
#                 font-size: 14px;
#             }
#         """)


# # ---------------- MAIN WINDOW ----------------
# class VisionDashboard(QMainWindow):
#     def __init__(self):
#         super().__init__()
#         self.setWindowTitle("Engine Leakage Detection System")
#         self.resize(1600, 900)

#         central = QWidget()
#         self.setCentralWidget(central)
#         main_layout = QVBoxLayout(central)

#         main_layout.addWidget(self.create_header())
#         main_layout.addLayout(self.create_body())
#         main_layout.addWidget(self.create_footer())

#         self.update_camera_grid([1, 2, 3, 4, 5])  # DEMO


#     # ---------------- HEADER ----------------
#     def create_header(self):
#         header = QFrame()
#         header.setFixedHeight(70)
#         header.setStyleSheet("""
#             QFrame {
#                 background: qlineargradient(
#                     x1:0, y1:0, x2:1, y2:0,
#                     stop:0 #0f2027,
#                     stop:0.5 #203a43,
#                     stop:1 #2c5364
#                 );
#             }
#         """)

#         layout = QHBoxLayout(header)

#         title = QLabel("ENGINE LEAKAGE DETECTION SYSTEM")
#         title.setStyleSheet("color:white;font-size:22px;font-weight:bold;")
#         layout.addWidget(title)

#         layout.addStretch()

#         self.cam_leds = []
#         for i in range(5):
#             cam_lbl = QLabel(f"Cam{i+1}")
#             cam_lbl.setStyleSheet("color:white;")
#             led = QLabel("●")
#             led.setStyleSheet("color:lime;font-size:18px;")
#             layout.addWidget(cam_lbl)
#             layout.addWidget(led)
#             self.cam_leds.append(led)

#         return header


#     # ---------------- BODY ----------------
#     def create_body(self):
#         body = QHBoxLayout()

#         # Camera Grid
#         cam_area = QWidget()
#         self.grid = QGridLayout(cam_area)
#         self.grid.setSpacing(8)
#         body.addWidget(cam_area, 3)

#         # Right Panel
#         self.tabs = QTabWidget()
#         self.tabs.addTab(self.create_stats_tab(), "Statistics")
#         self.tabs.addTab(self.create_ng_tab(), "NG Images")
#         body.addWidget(self.tabs, 1)

#         return body


#     # ---------------- CAMERA GRID ----------------
#     def update_camera_grid(self, active_cams):
#         while self.grid.count():
#             w = self.grid.takeAt(0).widget()
#             if w:
#                 w.deleteLater()

#         n = len(active_cams)

#         if n <= 2:
#             cols = n
#         elif n <= 4:
#             cols = 2
#         else:
#             cols = 3

#         for i, cam in enumerate(active_cams):
#             r = i // cols
#             c = i % cols
#             self.grid.addWidget(CameraWidget(cam), r, c)


#     # ---------------- STATS TAB ----------------
#     def create_stats_tab(self):
#         tab = QWidget()
#         layout = QVBoxLayout(tab)

#         self.lbl_total = QLabel("Total Inspected: 1250")
#         self.lbl_good = QLabel("Good: 1210")
#         self.lbl_ng = QLabel("Not Good: 40")

#         for lbl in [self.lbl_total, self.lbl_good, self.lbl_ng]:
#             lbl.setStyleSheet("font-size:18px;color:white;")
#             layout.addWidget(lbl)

#         layout.addStretch()
#         return tab


#     # ---------------- NG TAB ----------------
#     def create_ng_tab(self):
#         tab = QWidget()
#         layout = QVBoxLayout(tab)

#         self.ng_list = QListWidget()
#         self.ng_list.setViewMode(QListWidget.IconMode)
#         self.ng_list.setIconSize(QSize(140, 140))
#         self.ng_list.setResizeMode(QListWidget.Adjust)

#         # Demo NG Images
#         for i in range(4):
#             item = QListWidgetItem(QIcon(QPixmap(140, 140)), f"NG {i+1}")
#             self.ng_list.addItem(item)

#         layout.addWidget(self.ng_list)
#         return tab


#     # ---------------- FOOTER ----------------
#     def create_footer(self):
#         footer = QFrame()
#         footer.setFixedHeight(30)
#         footer.setStyleSheet("background-color:#1E1E1E;")

#         layout = QHBoxLayout(footer)
#         status = QLabel("FPS: 30 | Model: YOLOv8 | Inference: 12ms | PLC: Connected")
#         status.setStyleSheet("color:#AAAAAA;")
#         layout.addWidget(status)

#         return footer


# # ---------------- RUN ----------------
# if __name__ == "__main__":
#     app = QApplication(sys.argv)

#     app.setStyleSheet("""
#         QMainWindow { background-color: #121212; }
#         QTabWidget::pane { border: 1px solid #333; }
#         QTabBar::tab {
#             background: #1E1E1E;
#             padding: 10px;
#             color: white;
#         }
#         QTabBar::tab:selected {
#             background: #00C853;
#             color: black;
#         }
#     """)

#     window = VisionDashboard()
#     window.show()
#     sys.exit(app.exec_())













import sys
from MainWindow import VWPorosityApp
from PyQt5 import QtWidgets

def main():
    app = QtWidgets.QApplication(sys.argv)
    win = VWPorosityApp()
    win.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()