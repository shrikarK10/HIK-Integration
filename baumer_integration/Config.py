import os
import sys
from LoggerManager import LoggerManager 


# ---------- Configuration (adjust paths) ----------
APP_TITLE = "Company Name Optical Inspection"
VW_NAVY = "#001E50"

# Camera Configuration
CAMERA_SOURCE = 0
FRAME_SIMULATE_IF_NO_CAM = True

# Debug Paths
DEBUG_DIR = r"C:/SK/Genral_website/captured_frames"
# DEBUG_DIR= r""

#Model Paths
YOLO_MODEL_PATH = r"model/best.pt"  # glass detector
SECOND_MODEL_PATH = r"model/best.pt"  # dot/defect detector

# Main Database Path
DB_PATH = r"database/company-name.db"

# Create necessary directories if they don't exist
if not os.path.exists("database"):  
    os.makedirs("database")
if not os.path.exists("model"):  
    os.makedirs("model")
if not os.path.exists(DEBUG_DIR):
    os.makedirs(DEBUG_DIR, exist_ok=True)

# Image Save Directories
CROP_SAVE_DIR = "captured_crops"
NG_SAVE_DIR = "NG_Frames"
FINAL_RESULT_DIR = "final_results"

# Create image save directories if they don't exist
for d in [CROP_SAVE_DIR, NG_SAVE_DIR, FINAL_RESULT_DIR]:
    if not os.path.exists(d):
        os.makedirs(d)

# Initialize Logger
logger = LoggerManager()

# Global Variables used in multiple modules
GET_IMAGE_TIMEOUT_MS = 40000        # wait up to 8s for PLC trigger
WATCHDOG_NO_FRAME_SEC = 300        # if no frames for 120s, force reconnect
GC_EVERY_N_FRAMES = 50             # force garbage collection every N frames

# Model confidence thresholds
MODEL_GLASS_CONFIDENCE = 0.92
MODEL_DEFECTS_CONFIDENCE = 0.4

# Suggested Config.py additions:
SHIFT_MORNING_START = "07:00:00"
SHIFT_MORNING_END = "15:00:00"
SHIFT_EVENING_START = "15:00:00"
SHIFT_EVENING_END = "23:00:00"
SHIFT_NIGHT_START = "23:00:00"
SHIFT_NIGHT_END = "07:00:00" 

# Check for shift change every 30 seconds
SHIFT_CHECK_INTERVAL_MS = 30000  

FINAL_IMAGE_WIDTH = 640
FINAL_IMAGE_HEIGHT = 640

# Camera/PLC status blink rate
CAMERA_HEARTBEAT_INTERVAL_MS = 1000  

# Update header clock every second
CLOCK_UPDATE_INTERVAL_MS = 1000  

# Camera settings
CAMERA_WIDTH = 2384
CAMERA_HEIGHT = 1246
CAMERA_OFFSET_X = 0
CAMERA_OFFSET_Y = 308
CAMERA_EXPOSURE_TIME = 14912.0
CAMERA_GAIN = 29.17
CAMERA_GAMMA = 1.15

# PDF Report Settings
REPORT_DEFAULT_DAYS_BACK = 30  # Default range for summary reports
REPORT_DIRECTORY = "report"     # Where to save PDF reports
PDF_MAX_DETAIL_ROWS = 50    # Limit detail rows in PDF
PDF_MAX_SUMMARY_ROWS = 30   # Limit summary rows in PDF

