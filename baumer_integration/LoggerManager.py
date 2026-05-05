import sqlite3
import os
from datetime import datetime
from LogConfig import CONFIG , DB_PATH_LOGGER
from enum import IntEnum
from dotenv import load_dotenv
load_dotenv()

class LogMode(IntEnum):
    DISABLE = 0
    FILE = 1
    DB = 2
    BOTH = 3

class LoggerManager:
    def __init__(self, db_path=DB_PATH_LOGGER):
        self.db_path = db_path
        self.log_mode = LogMode(int(os.getenv("LOG_MODE", CONFIG.get("log_mode", 1))))
        self.env = CONFIG.get("env", "production")
        self.log_file = CONFIG.get("log_file_path", "app_logs.txt")
        self._init_db()

    def _init_db(self):
        if self.log_mode in [LogMode.DB, LogMode.BOTH]:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT,
                        function_name TEXT,
                        action TEXT,
                        details TEXT,
                        level TEXT
                    )
                """)

    def log(self, function_name, action, details, level="DEBUG"):
        if self.log_mode == LogMode.DISABLE or (level == "DEBUG" and self.env != "development"):
            return

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if self.log_mode in [LogMode.DB, LogMode.BOTH]:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO logs (timestamp, function_name, action, details, level)
                    VALUES (?, ?, ?, ?, ?)
                """, (timestamp, function_name, action, details, level))

        if self.log_mode in [LogMode.FILE, LogMode.BOTH]:
            with open(self.log_file, "a") as f:
                f.write(f"[{timestamp}] [{level}] {function_name} - {action}: {details}\n")

    def log_debug(self, func, action, msg):
        self.log(func, action, msg, level="DEBUG")

    def log_error(self, func, action, msg):
        self.log(func, action, msg, level="ERROR")

    def log_exception(self, func, action, msg):
        self.log(func, action, msg, level="EXCEPTION")


