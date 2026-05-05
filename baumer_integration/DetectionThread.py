# main.py
import traceback
import queue
import time
import threading
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage

import cv2


#Config imports
from Config import logger , MODEL_GLASS_CONFIDENCE, MODEL_DEFECTS_CONFIDENCE



class DetectionThread(QThread):
    result_ready = pyqtSignal(object, bool, bool, str, str)  # qimg, is_good, glass_present, tag, src

    def __init__(self, model_path, second_model_path, parent=None, queue_maxsize=1):
        super().__init__(parent)
        self.model_glass_path = model_path
        self.model_defects_path = second_model_path
        self._running = False
        self.frame_queue = queue.Queue(maxsize=queue_maxsize)
        self.model_glass = None
        self.model_defects = None
        self.device = 'cpu'  # or 'cuda' if available, but for simplicity
        # Display size
        self._display_size = None
        self._display_size_lock = threading.Lock() 

    def set_display_size(self, w: int, h: int):
        with self._display_size_lock:
            self._display_size = (int(w), int(h))

    def _get_display_size(self):
        with self._display_size_lock:
            return self._display_size

    def run(self):
        try:
            from ultralytics import YOLO
            # load models once
            try:
                # self.model_glass = YOLO(self.model_glass_path).to(self.device)
                self.model_defects = YOLO(self.model_defects_path).to(self.device)
            except Exception as e:
                logger.log_exception("DetectionThread", "run", f"Model load failed: {e}")
        except Exception as e:
            logger.log_exception("DetectionThread", "run", f"YOLO import failed: {e}")
            return

        self._running = True
        while self._running:
            try:
                frame, tag, src = self.frame_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                start_time = time.time()
                # Stage 1: Glass detection (Commented out)
                # glass_results = self.model_glass(frame, conf=MODEL_GLASS_CONFIDENCE, verbose=False)[0]
                # glass_present = len(getattr(glass_results, "boxes", [])) > 0

                # annotated is BGR image
                # annotated = glass_results.plot() if hasattr(glass_results, "plot") else frame.copy()

                # Bypass glass detection: assume glass is always present
                glass_present = True
                annotated = frame.copy()

                if glass_present:
                    # Stage 2: Defect detection directly on the frame
                    defect_results = self.model_defects(frame, conf=MODEL_DEFECTS_CONFIDENCE, verbose=False)[0]
                    # plot defects on the annotated image
                    try:
                        annotated = defect_results.plot(img=annotated)
                    except Exception:
                        # fallback: don't overlay if plot fails
                        pass
                    is_good = len(getattr(defect_results, "boxes", [])) != 0
                else:
                    is_good = False

                # If display size is provided, resize now (cheap in worker)
                display_size = self._get_display_size()
                if display_size is not None:
                    try:
                        target_w, target_h = display_size
                        # maintain aspect ratio - use cv2.resize with INTER_LINEAR
                        h, w = annotated.shape[:2]
                        scale = min(target_w / w, target_h / h) if w and h else 1.0
                        if scale < 1.0:
                            new_w = max(1, int(w * scale))
                            new_h = max(1, int(h * scale))
                            annotated = cv2.resize(annotated, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
                    except Exception:
                        pass

                # Convert to QImage before emitting to reduce mainthread work
                try:
                    rgb = cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB)
                    h, w, ch = rgb.shape
                    bytes_per_line = ch * w
                    qimg = QImage(rgb.data, w, h, bytes_per_line, QImage.Format_RGB888).copy()
                except Exception:
                    # if anything fails, emit original frame converted
                    try:
                        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        h, w, ch = rgb.shape
                        bytes_per_line = ch * w
                        qimg = QImage(rgb.data, w, h, bytes_per_line, QImage.Format_RGB888).copy()
                    except Exception:
                        qimg = None
                print("processed")
                self.result_ready.emit(qimg, is_good, glass_present, tag, src)
                
                logger.log_debug("DetectionThread", "run", f"Inference took {time.time() - start_time:.3f}s")
            except Exception as e:
                tb = traceback.format_exc()
                logger.log_exception("DetectionThread", "run", f"{e}\n{tb}")
                try:
                    self.result_ready.emit(None, False, False, tag, src)
                except Exception:
                    pass

        # cleanup
        try:
            # optionally release model resources if needed
            # self.model_glass = None
            self.model_defects = None
        except Exception:
            pass

    def request(self, frame_bgr, tag="live", src_path=""):
            
            if not self._running or frame_bgr is None:
                return
            try:
                if self.frame_queue.full():
                    try:
                        # drop oldest
                        self.frame_queue.get_nowait()
                    except Exception:
                        pass
                # put a shallow copy (we copy to avoid caller mutating)
                self.frame_queue.put_nowait((frame_bgr.copy(), tag, src_path))
            except Exception as e:
                logger.log_error("YOLOWorker", "request", f"Queue error: {e}")

    def enqueue(self, frame, tag="", src=""):
        if not self._running or frame is None:
            return
        try:
            if self.frame_queue.full():
                try:
                    # drop oldest
                    self.frame_queue.get_nowait()
                except Exception:
                    pass
            # put a shallow copy
            self.frame_queue.put_nowait((frame.copy(), tag, src))
        except Exception as e:
            logger.log_error("DetectionThread", "enqueue", f"Queue error: {e}")

    def stop(self):
        self._running = False
        # clear queued frames
        try:
            while not self.frame_queue.empty():
                self.frame_queue.get_nowait()
        except Exception:
            pass
        try:
            self.quit()
            self.wait(1000)
        except Exception:
            pass

