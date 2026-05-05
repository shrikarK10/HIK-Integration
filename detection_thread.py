import queue
import traceback
import cv2
from PyQt5.QtCore import QThread, pyqtSignal
from config import AppConfig

class DetectionThread(QThread):
    # Emits: (annotated_frame, detections, is_good, is_bad, detection_count)
    result_ready = pyqtSignal(object, list, bool, bool, int)

    def __init__(self, config: AppConfig, engine, parent=None, queue_maxsize=1):
        super().__init__(parent)
        self.config = config
        self._running = False
        self.frame_queue = queue.Queue(maxsize=queue_maxsize)
        self.engine = engine
        self._display_size = None

    def set_display_size(self, w: int, h: int):
        self._display_size = (w, h)

    def enqueue(self, frame):
        if not self._running or frame is None:
            return
        try:
            if self.frame_queue.full():
                try:
                    self.frame_queue.get_nowait()
                except Exception:
                    pass
            self.frame_queue.put_nowait(frame.copy() if hasattr(frame, "copy") else frame)
        except Exception as e:
            print(f"DetectionThread: Queue error: {e}")

    def _evaluate_quality(self, detection_count):
        min_good = self.config.good_count_min
        max_good = self.config.good_count_max
        is_good = min_good <= detection_count <= max_good
        return is_good, (not is_good)

    def run(self):
        self._running = True
        while self._running:
            try:
                frame = self.frame_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            try:
                if not self.engine.is_ready:
                    # Model not loaded, just emit original
                    self.result_ready.emit(frame, [], False, False, 0)
                    continue

                detections = self.engine.detect(frame)
                annotated = self.engine.annotate(frame, detections)
                
                detection_count = len(detections)
                is_good, is_bad = self._evaluate_quality(detection_count)

                if self._display_size is not None:
                    try:
                        target_w, target_h = self._display_size
                        h, w = annotated.shape[:2]
                        scale = min(target_w / w, target_h / h) if w and h else 1.0
                        if scale < 1.0:
                            new_w = max(1, int(w * scale))
                            new_h = max(1, int(h * scale))
                            annotated = cv2.resize(annotated, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
                    except Exception:
                        pass

                self.result_ready.emit(annotated, detections, is_good, is_bad, detection_count)
            except Exception as e:
                print(f"DetectionThread inference error: {e}")
                traceback.print_exc()

    def stop(self):
        self._running = False
        try:
            while not self.frame_queue.empty():
                self.frame_queue.get_nowait()
        except Exception:
            pass
        self.quit()
        self.wait(1000)
