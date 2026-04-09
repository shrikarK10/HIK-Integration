import sys

from config import AppConfig
from detection import DetectionEngine


def main() -> int:
    config = AppConfig(
        company_name="WIZPRO",
        app_name="Camera Quality Dashboard",
        # Uses config default path: model/best.pt
        # Example ROI: (120, 80, 1000, 700)
        roi=None,
    )

    # Important on this machine: load YOLO/Torch before importing PyQt UI module.
    detector = DetectionEngine(config)

    from ui import run_app

    return run_app(config, detector=detector)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        from ui import show_startup_error

        show_startup_error(str(exc))
