from pathlib import Path
from dataclasses import dataclass
import importlib
import os
from typing import List, Optional, Tuple

import cv2
import numpy as np

from config import AppConfig

Box = Tuple[int, int, int, int]


@dataclass
class DetectionItem:
    x: int
    y: int
    w: int
    h: int
    class_id: int
    class_name: str
    confidence: float


class DetectionEngine:
    def __init__(self, config: AppConfig):
        self.config = config
        self._model = None
        self._backend_name = "Contour"
        self._yolo_error: Optional[str] = None
        self._load_model()

    @property
    def backend_name(self) -> str:
        return self._backend_name

    @property
    def yolo_error(self) -> Optional[str]:
        return self._yolo_error

    def _load_model(self) -> None:
        self._backend_name = "YOLO"

        if not self.config.use_yolo:
            self._yolo_error = "YOLO model loading is disabled in config."
            print(f"[Detection] {self._yolo_error}")
            return

        model_path = Path(self.config.yolo_model_path)
        if not model_path.is_absolute():
            project_root = Path(__file__).resolve().parent
            model_path = (project_root / model_path).resolve()

        print(f"[Detection] CWD: {Path(os.getcwd()).resolve()}")
        print(f"[Detection] Model path from config: {self.config.yolo_model_path}")
        print(f"[Detection] Resolved model path: {model_path}")

        if not model_path.exists():
            self._yolo_error = f"YOLO model not found: {model_path}"
            print(f"[Detection] ERROR: {self._yolo_error}")
            return

        try:
            ultralytics = importlib.import_module("ultralytics")
            YOLO = ultralytics.YOLO
            self._model = YOLO(str(model_path))
            self._yolo_error = None
            print("[Detection] YOLO model loaded successfully")
        except Exception as exc:
            self._model = None
            self._yolo_error = f"YOLO load failed: {exc}"
            print(f"[Detection] ERROR: {self._yolo_error}")

    @property
    def is_ready(self) -> bool:
        return self._model is not None and self._yolo_error is None

    def detect(self, frame: np.ndarray) -> List[DetectionItem]:
        if not self.is_ready:
            raise RuntimeError(self._yolo_error or "YOLO model is not available")

        roi_frame, offset = self._apply_roi(frame)
        detections = self._detect_with_yolo(roi_frame)
        off_x, off_y = offset
        return [
            DetectionItem(
                x=item.x + off_x,
                y=item.y + off_y,
                w=item.w,
                h=item.h,
                class_id=item.class_id,
                class_name=item.class_name,
                confidence=item.confidence,
            )
            for item in detections
        ]

    def annotate(self, frame: np.ndarray, detections: List[DetectionItem]) -> np.ndarray:
        out = frame.copy()
        box_thickness = 3
        text_scale = 1
        text_thickness =3
        text_padding = 14

        if self.config.roi is not None:
            x, y, w, h = self.config.roi
            cv2.rectangle(out, (x, y), (x + w, y + h), (16, 185, 129), 2)

        for item in detections:
            x, y, w, h = item.x, item.y, item.w, item.h
            cv2.rectangle(out, (x, y), (x + w, y + h), (0, 0, 255), box_thickness)

            label = f"{item.class_name} {item.confidence:.2f}"
            (text_w, text_h), baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, text_scale, text_thickness)
            y1 = max(0, y - text_h - baseline - text_padding)
            y2 = max(0, y - 2)
            x2 = x + text_w + text_padding

            cv2.rectangle(out, (x, y1), (x2, y2), (0, 0, 255), -1)
            cv2.putText(
                out,
                label,
                (x + (text_padding // 2), y2 - 4),
                cv2.FONT_HERSHEY_SIMPLEX,
                text_scale,
                (255, 255, 255),
                text_thickness,
                cv2.LINE_AA,
            )

        return out

    def _apply_roi(self, frame: np.ndarray) -> Tuple[np.ndarray, Tuple[int, int]]:
        if self.config.roi is None:
            return frame, (0, 0)

        x, y, w, h = self.config.roi
        fh, fw = frame.shape[:2]

        x = max(0, min(x, fw - 1))
        y = max(0, min(y, fh - 1))
        w = max(1, min(w, fw - x))
        h = max(1, min(h, fh - y))

        return frame[y : y + h, x : x + w], (x, y)

    def _detect_with_yolo(self, frame: np.ndarray) -> List[DetectionItem]:
        try:
            results = self._model.predict(frame, conf=self.config.yolo_confidence, verbose=False)
        except Exception as exc:
            raise RuntimeError(f"YOLO inference failed: {exc}") from exc

        if not results:
            return []

        detections: List[DetectionItem] = []
        det = results[0]
        if det.boxes is None:
            return detections

        names = det.names if hasattr(det, "names") else getattr(self._model, "names", {})

        xyxy = det.boxes.xyxy.cpu().numpy().astype(int)
        confs = det.boxes.conf.cpu().numpy() if det.boxes.conf is not None else np.ones((len(xyxy),), dtype=float)
        classes = det.boxes.cls.cpu().numpy().astype(int) if det.boxes.cls is not None else np.zeros((len(xyxy),), dtype=int)

        for idx, (x1, y1, x2, y2) in enumerate(xyxy):
            w = max(1, x2 - x1)
            h = max(1, y2 - y1)
            class_id = int(classes[idx])
            class_name = str(names.get(class_id, f"class_{class_id}")) if isinstance(names, dict) else str(class_id)
            confidence = float(confs[idx])

            detections.append(
                DetectionItem(
                    x=int(x1),
                    y=int(y1),
                    w=int(w),
                    h=int(h),
                    class_id=class_id,
                    class_name=class_name,
                    confidence=confidence,
                )
            )

        return detections
