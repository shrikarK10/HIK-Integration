from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple


@dataclass
class AppConfig:
    company_name: str = "WIZPRO"
    app_name: str = "Inspection App"

    raw_images_dir: Path = Path("raw_images")
    ng_images_dir: Path = Path("ng_images")

    # Optional logo path. Keep None to show a placeholder in the UI.
    logo_path: Optional[Path] = Path("logo.jpeg")

    # Camera settings
    camera_trigger_mode: str = "software"
    live_refresh_ms: int = 33

    # Detection settings
    use_yolo: bool = True
    yolo_model_path: Path = Path("model/best.pt")
    yolo_confidence: float = 0.25

    # ROI format: (x, y, width, height). Set to None to use full frame.
    roi: Optional[Tuple[int, int, int, int]] = None

    # Judgment rule for GOOD/BAD by detection count.
    # GOOD when good_count_min <= detections <= good_count_max.
    # Default keeps current behavior: only 0 detections is GOOD.
    good_count_min: int = 0
    good_count_max: int = 0


def ensure_output_dirs(config: AppConfig) -> None:
    config.raw_images_dir.mkdir(parents=True, exist_ok=True)
    config.ng_images_dir.mkdir(parents=True, exist_ok=True)
