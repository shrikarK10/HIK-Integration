# main.py
import traceback
import time
import gc
import threading
from PyQt5.QtCore import QThread, pyqtSignal, QTimer

import cv2

#Config imports
from Config import (GET_IMAGE_TIMEOUT_MS, logger, WATCHDOG_NO_FRAME_SEC , 
                    GC_EVERY_N_FRAMES, CAMERA_WIDTH, CAMERA_HEIGHT, 
                    CAMERA_OFFSET_X, CAMERA_OFFSET_Y, CAMERA_EXPOSURE_TIME, 
                    CAMERA_GAIN, CAMERA_GAMMA)

class BaumerCameraThread(QThread):
    frame_captured = pyqtSignal(object)
    camera_connected = pyqtSignal()  # New signal
    camera_disconnected = pyqtSignal()  # New signal


    def __init__(self, parent=None):
        super().__init__(parent)
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
            logger.log_error("BaumerCameraThread", "connect_camera", f"neoapi import failed: {e}")
            return False

        try:
            cam = neoapi.Cam()
            cam.Connect()
            self.camera_connected.emit()  # Emit connected

            if not cam.IsConnected():
                cam.Disconnect()
                self.camera_disconnected.emit()  # Emit disconnected

                logger.log_error("BaumerCameraThread", "connect_camera", "Cam.Connect failed")
                return False

            # Configure trigger lines if required
            try:
                cam.f.TriggerMode.value = neoapi.TriggerMode_On
                cam.f.TriggerSource.value = neoapi.TriggerSource_Software
                # cam.f.LineSelector.value = neoapi.LineSelector_Line3
                # cam.f.LineSource.value = neoapi.LineSource_UserOutput1
                # cam.f.UserOutputSelector.value = neoapi.UserOutputSelector_UserOutput1
                cam.f.Width.value = CAMERA_WIDTH         # will set the value to the maximum sensor size
                cam.f.Height.value = CAMERA_HEIGHT         # will set the value to the maximum sensor size
                cam.f.OffsetX.value= CAMERA_OFFSET_X
                cam.f.OffsetY.value= CAMERA_OFFSET_Y
                cam.f.ExposureTime.Set(CAMERA_EXPOSURE_TIME)
                
                # Set gain (dB)
                cam.f.Gain.Set(CAMERA_GAIN)
                cam.f.Gamma.Set(CAMERA_GAMMA)
            except Exception as e:
                logger.log_debug("BaumerCameraThread", "connect_camera", f"Trigger config warning: {e}")

            self.camera = cam
            self._connected = True
            logger.log_debug("BaumerCameraThread", "connect_camera", "Camera connected")
            return True

        except Exception as e:
            tb = traceback.format_exc()
            logger.log_exception("BaumerCameraThread", "connect_camera", f"{e}\n{tb}")
            try:
                cam.Disconnect()
                self.camera_disconnected.emit()  # Emit disconnected

            except Exception:
                pass
            self.camera = None
            self._connected = False
            return False

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
                    self.camera.StartStreaming()
                except Exception as e:
                    logger.log_error("BaumerCameraThread", "run", f"StartStreaming failed: {e}")
                    try:
                        self.camera.Disconnect()
                        self.camera_disconnected.emit()  # Emit disconnected

                    except Exception:
                        pass
                    self.camera = None
                    time.sleep(2.0)
                    continue
                self.camera_connected.emit()
                logger.log_debug("BaumerCameraThread", "run", "Streaming started")

            image_data = None
            try:
                image_data = self.camera.GetImage(GET_IMAGE_TIMEOUT_MS)
            except Exception as e:
                logger.log_exception("BaumerCameraThread", "run", f"GetImage exception: {e}")
                time.sleep(0.1)
                if not getattr(self.camera, "IsConnected", lambda: True)():
                    self._connected = False
                    self.camera_disconnected.emit()

                    try:
                        self.camera.StopStreaming()

                    except Exception:
                        pass
                    try:
                        self.camera.Disconnect()
                        self.camera_disconnected.emit()

                    except Exception:
                        pass
                    self.camera = None
                continue

            if image_data is None:
                if time.time() - self._last_success_frame_time > WATCHDOG_NO_FRAME_SEC:  # WATCHDOG_NO_FRAME_SEC
                    logger.log_error("BaumerCameraThread", "run", "Watchdog triggered -> reconnecting")
                    try:
                        self.camera.StopStreaming()
                    except Exception:
                        pass
                    try:
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
                if self._frame_counter % GC_EVERY_N_FRAMES == 0:  # GC_EVERY_N_FRAMES
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
                except Exception:
                    pass
                try:
                    self.camera.Disconnect()
                    self.camera_disconnected.emit()

                except Exception:
                    pass
        except Exception:
            pass
        self.camera = None
        self._should_run = False
        self._connected = False

    def software_trigger(self):
        try:
            with self._camera_lock:
                if self.camera and getattr(self.camera, "IsConnected", lambda: False)():
                    self.camera.f.TriggerSoftware.Execute()
                    logger.log_debug("BaumerCameraThread", "software_trigger", "Software trigger sent")
        except Exception as e:
            logger.log_error("BaumerCameraThread", "software_trigger", f"Software trigger failed: {e}")

    def set_user_output(self, value: bool, pulse_ms: int = 5000):
        try:
            with self._camera_lock:
                if self.camera and getattr(self.camera, "IsConnected", lambda: False)():
                    if value:  # BAD -> pulse buzzer
                        def pulse():
                            try:
                                self.camera.f.UserOutputValue.value = True
                                logger.log_debug("BaumerCameraThread", "set_user_output",
                                                 "UserOutputValue HIGH (BAD pulse started)")
                                time.sleep(3)
                                self.camera.f.UserOutputValue.value = False
                                logger.log_debug("BaumerCameraThread", "set_user_output",
                                                 "UserOutputValue LOW (BAD pulse ended)")
                            except Exception as e:
                                logger.log_error("BaumerCameraThread", "set_user_output",
                                                 f"Pulse failed: {e}")

                        threading.Thread(target=pulse, daemon=True).start()

                    else:  # GOOD -> force LOW
                        self.camera.f.UserOutputValue.value = False
                        logger.log_debug("BaumerCameraThread", "set_user_output",
                                         "UserOutputValue set LOW (GOOD)")
        except Exception as e:
            logger.log_error("BaumerCameraThread", "set_user_output", f"Failed: {e}")

    def stop(self):
        self._should_run = False
        try:
            if self.camera and getattr(self.camera, "IsConnected", lambda: False)():
                try:
                    self.camera.StopStreaming()
                except Exception:
                    pass
                try:
                    self.camera.Disconnect()
                except Exception:
                    pass
        except Exception:
            pass
        try:
            self.quit()
            self.wait(1500)
        except Exception:
            pass
        self.camera = None
        self._connected = False
