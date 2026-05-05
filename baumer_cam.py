import traceback
import time
import gc
import threading
from PyQt5.QtCore import QThread, pyqtSignal

import cv2
from config import AppConfig

class BaumerCameraThread(QThread):
    frame_captured = pyqtSignal(object)
    camera_connected = pyqtSignal()
    camera_disconnected = pyqtSignal()

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self.camera = None
        self._should_run = False
        self._connected = False
        self._camera_lock = threading.Lock()
        self._last_success_frame_time = 0.0
        self._frame_counter = 0

    def is_connected(self):
        return self._connected

    def connect_camera(self):
        try:
            import neoapi
        except Exception as e:
            print(f"BaumerCameraThread: neoapi import failed: {e}")
            return False

        try:
            cam = neoapi.Cam()
            cam.Connect()
            self.camera_connected.emit()

            if not cam.IsConnected():
                cam.Disconnect()
                self.camera_disconnected.emit()
                print("BaumerCameraThread: Cam.Connect failed")
                return False

            try:
                cam.f.TriggerMode.value = neoapi.TriggerMode_On if self.config.camera_trigger_mode == "software" else neoapi.TriggerMode_Off
                if self.config.camera_trigger_mode == "software":
                    cam.f.TriggerSource.value = neoapi.TriggerSource_Software

                cam.f.Width.value = self.config.baumer_width
                cam.f.Height.value = self.config.baumer_height
                cam.f.OffsetX.value = self.config.baumer_offset_x
                cam.f.OffsetY.value = self.config.baumer_offset_y
                cam.f.ExposureTime.Set(self.config.baumer_exposure_time)
                
                cam.f.Gain.Set(self.config.baumer_gain)
                cam.f.Gamma.Set(self.config.baumer_gamma)
            except Exception as e:
                print(f"BaumerCameraThread: Trigger config warning: {e}")

            self.camera = cam
            self._connected = True
            print("BaumerCameraThread: Camera connected")
            return True

        except Exception as e:
            tb = traceback.format_exc()
            print(f"BaumerCameraThread: connect_camera exception: {e}\n{tb}")
            try:
                cam.Disconnect()
                self.camera_disconnected.emit()
            except Exception:
                pass
            self.camera = None
            self._connected = False
            return False

    def set_trigger_mode(self, mode: str):
        self.config.camera_trigger_mode = mode
        try:
            with self._camera_lock:
                if self.camera and self._connected:
                    import neoapi
                    if mode == "software":
                        self.camera.f.TriggerMode.value = neoapi.TriggerMode_On
                        self.camera.f.TriggerSource.value = neoapi.TriggerSource_Software
                    else:
                        self.camera.f.TriggerMode.value = neoapi.TriggerMode_Off
        except Exception as e:
            print(f"BaumerCameraThread: failed to set trigger mode: {e}")

    def run(self):
        self._should_run = True
        self._last_success_frame_time = time.time()
        self._frame_counter = 0

        while self._should_run:
            if not self.camera or not getattr(self.camera, "IsConnected", lambda: False)():
                if not self.connect_camera():
                    time.sleep(2.0)
                    continue
                try:
                    if self.config.camera_trigger_mode == "continuous":
                        self.camera.f.TriggerMode.value = getattr(self.camera.f.TriggerMode, 'neoapi.TriggerMode_Off', 0)
                    else:
                        import neoapi
                        self.camera.f.TriggerMode.value = neoapi.TriggerMode_On
                        self.camera.f.TriggerSource.value = neoapi.TriggerSource_Software

                    self.camera.StartStreaming()
                except Exception as e:
                    print(f"BaumerCameraThread: StartStreaming failed: {e}")
                    try:
                        self.camera.Disconnect()
                        self.camera_disconnected.emit()
                    except Exception:
                        pass
                    self.camera = None
                    time.sleep(2.0)
                    continue
                self.camera_connected.emit()
                print("BaumerCameraThread: Streaming started")

            image_data = None
            try:
                image_data = self.camera.GetImage(self.config.baumer_get_image_timeout_ms)
            except Exception as e:
                time.sleep(0.1)
                if not getattr(self.camera, "IsConnected", lambda: True)():
                    self._connected = False
                    self.camera_disconnected.emit()
                    try:
                        self.camera.StopStreaming()
                        self.camera.Disconnect()
                    except Exception:
                        pass
                    self.camera = None
                continue

            if image_data is None:
                if time.time() - self._last_success_frame_time > self.config.baumer_watchdog_no_frame_sec:
                    print("BaumerCameraThread: Watchdog triggered -> reconnecting")
                    try:
                        self.camera.StopStreaming()
                        self.camera.Disconnect()
                        self.camera_disconnected.emit()
                    except Exception:
                        pass
                    self.camera = None
                continue

            try:
                frame = image_data.GetNPArray()
                if frame is None or frame.size == 0:
                    continue

                if frame.ndim == 2 or (frame.ndim == 3 and frame.shape[2] == 1):
                    try:
                        pf = str(self.camera.f.PixelFormat.value)
                        conv_map = {
                            "BayerRG8": cv2.COLOR_BAYER_RG2BGR,
                            "BayerBG8": cv2.COLOR_BAYER_BG2BGR,
                            "BayerGR8": cv2.COLOR_BAYER_GR2BGR,
                            "BayerGB8": cv2.COLOR_BAYER_GB2BGR,
                        }
                        code = conv_map.get(pf, cv2.COLOR_BAYER_BG2BGR)
                        frame = cv2.cvtColor(frame, code)
                    except Exception:
                        try:
                            frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
                        except Exception:
                            pass

                self.frame_captured.emit(frame.copy() if hasattr(frame, "copy") else frame)
                self._last_success_frame_time = time.time()
                self._frame_counter += 1
                if self._frame_counter % 50 == 0:
                    gc.collect()

            finally:
                try:
                    del image_data
                except Exception:
                    pass
                try:
                    del frame
                except Exception:
                    pass

        try:
            if self.camera and getattr(self.camera, "IsConnected", lambda: False)():
                try:
                    self.camera.StopStreaming()
                    self.camera.Disconnect()
                    self.camera_disconnected.emit()
                except Exception:
                    pass
        except Exception:
            pass
        self.camera = None
        self._should_run = False
        self._connected = False

    def send_software_trigger(self):
        try:
            with self._camera_lock:
                if self.camera and getattr(self.camera, "IsConnected", lambda: False)():
                    self.camera.f.TriggerSoftware.Execute()
                    print("BaumerCameraThread: Software trigger sent")
        except Exception as e:
            print(f"BaumerCameraThread: Software trigger failed: {e}")

    def stop(self):
        self._should_run = False
        try:
            if self.camera and getattr(self.camera, "IsConnected", lambda: False)():
                self.camera.StopStreaming()
                self.camera.Disconnect()
        except Exception:
            pass
        self.quit()
        self.wait(1500)
        self.camera = None
        self._connected = False
