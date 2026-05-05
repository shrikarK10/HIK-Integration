# main.py
import sys
import os

import sqlite3

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIcon, QPixmap

from PyQt5 import QtCore

#Config imports
from Config import DB_PATH

class DetailsLoaderThread(QtCore.QThread):
    batch_ready = QtCore.pyqtSignal(list)   # emits list of rows
    finished = QtCore.pyqtSignal()

    def __init__(self, query, params, batch_size=100):
        super().__init__()
        self.query = query
        self.params = params
        self.batch_size = batch_size
        self._running = True

    def run(self):
        try:
            with sqlite3.connect(DB_PATH) as conn:
                cur = conn.cursor()
                cur.execute(self.query, self.params)
                rows = []
                for row in cur:
                    if not self._running:
                        break
                    rows.append(row)
                    if len(rows) >= self.batch_size:
                        self.batch_ready.emit(rows)
                        rows = []
                if rows:
                    self.batch_ready.emit(rows)
        except Exception as e:
            print(f"[ERROR] Loader thread failed: {e}")
        self.finished.emit()

    def stop(self):
        self._running = False

class ThumbnailLoader(QtCore.QThread):
    thumbnail_ready = QtCore.pyqtSignal(int, QIcon)

    def __init__(self, row, path, size=(80, 60)):
        super().__init__()
        self.row = row
        self.path = path
        self.size = size

    def run(self):
        if self.path and os.path.exists(self.path):
            pixmap = QPixmap(self.path).scaled(
                self.size[0], self.size[1],
                Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            self.thumbnail_ready.emit(self.row, QIcon(pixmap))
        else:
            self.thumbnail_ready.emit(self.row, QIcon())

