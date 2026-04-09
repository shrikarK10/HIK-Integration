import sys
from ctypes import POINTER, cast

import numpy as np

SDK_IMPORT_DIR = r"C:\Program Files (x86)\MVS\Development\Samples\Python\MvImport"
if SDK_IMPORT_DIR not in sys.path:
    sys.path.insert(0, SDK_IMPORT_DIR)

import MvCameraControl_class as hik

MV_GIGE_DEVICE = hik.MV_GIGE_DEVICE
MV_USB_DEVICE = hik.MV_USB_DEVICE
MV_ACCESS_EXCLUSIVE = hik.MV_ACCESS_Exclusive


class HikvisionCamera:
    def __init__(self):
        self.sdk = hik.MvCamera()
        self.device_list = hik.MV_CC_DEVICE_INFO_LIST()
        self.device_info = None
        self.frame_info = hik.MV_FRAME_OUT_INFO_EX()
        self.payload_size = 0

    def enumerate(self):
        ret = hik.MvCamera.MV_CC_EnumDevices(MV_GIGE_DEVICE | MV_USB_DEVICE, self.device_list)
        if ret != 0 or self.device_list.nDeviceNum == 0:
            raise Exception("No camera found")

        print(f"Found {self.device_list.nDeviceNum} camera(s)")
        return self.device_list.nDeviceNum

    def create_handle(self):
        if self.device_list.nDeviceNum == 0:
            raise Exception("No device info available")

        self.device_info = cast(self.device_list.pDeviceInfo[0], POINTER(hik.MV_CC_DEVICE_INFO)).contents
        ret = self.sdk.MV_CC_CreateHandle(self.device_info)
        if ret != 0:
            raise Exception(f"Create handle failed: {ret}")

    def open(self, trigger_mode="continuous"):
        ret = self.sdk.MV_CC_OpenDevice(MV_ACCESS_EXCLUSIVE, 0)
        if ret != 0:
            raise Exception(f"Open device failed: {ret}")

        self.set_trigger_mode(trigger_mode)

    def set_trigger_mode(self, trigger_mode):
        if trigger_mode == "software":
            self.enable_software_trigger()
        else:
            self.disable_trigger_mode()

    def disable_trigger_mode(self):
        ret = self.sdk.MV_CC_SetEnumValue("TriggerMode", 0)
        if ret != 0:
            print(f"Warning: failed to disable trigger mode: {ret}")
        else:
            print("Trigger mode disabled")

    def enable_software_trigger(self):
        # Set software trigger source first, then enable trigger mode.
        source_ret = self.sdk.MV_CC_SetEnumValue("TriggerSource", 7)
        if source_ret != 0:
            print(f"Warning: failed to set TriggerSource=Software: {source_ret}")

        mode_ret = self.sdk.MV_CC_SetEnumValue("TriggerMode", 1)
        if mode_ret != 0:
            print(f"Warning: failed to enable trigger mode: {mode_ret}")
        else:
            print("Software trigger mode enabled")

    def send_software_trigger(self):
        ret = self.sdk.MV_CC_SetCommandValue("TriggerSoftware")
        if ret != 0:
            raise Exception(f"Software trigger command failed: {ret}")

    def start(self):
        ret = self.sdk.MV_CC_StartGrabbing()
        if ret != 0:
            raise Exception(f"Start grabbing failed: {ret}")

    def get_frame(self):
        if self.payload_size == 0:
            payload = hik.MVCC_INTVALUE()
            ret = self.sdk.MV_CC_GetIntValueEx("PayloadSize", payload)
            if ret != 0:
                raise Exception(f"Failed to get payload size: {ret}")
            self.payload_size = payload.nCurValue

        buffer_size = max(self.payload_size * 3, self.payload_size)
        data_buf = (hik.c_ubyte * buffer_size)()
        ret = self.sdk.MV_CC_GetImageForBGR(data_buf, buffer_size, self.frame_info, 1000)
        if ret != 0:
            print(f"Frame grab failed: {ret}")
            return None

        height = int(self.frame_info.nHeight)
        width = int(self.frame_info.nWidth)
        if height <= 0 or width <= 0:
            return np.ctypeslib.as_array(data_buf).copy()

        img = np.ctypeslib.as_array(data_buf).copy()
        usable = width * height * 3
        if img.size >= usable:
            return img[:usable].reshape((height, width, 3))

        return img

    def stop(self):
        self.sdk.MV_CC_StopGrabbing()

    def close(self):
        try:
            self.sdk.MV_CC_CloseDevice()
        finally:
            self.sdk.MV_CC_DestroyHandle()