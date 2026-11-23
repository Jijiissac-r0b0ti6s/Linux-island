"""Windows Bluetooth: connected devices (classic and Bluetooth LE) through WinRT, checked every 3 s.

The battery level comes from the device's Bluetooth battery property when Windows has one (most
headphones on Windows 11 do); -1 otherwise, as on Linux.
"""
import os
import time

from ..services.bluetooth import BluetoothService
from ..services.threads import emit, name_this_thread
from .media import init_winrt_thread, wait

DEBUG = bool(os.environ.get("LINUX_ISLAND_DEBUG"))
BATTERY = "{104EA319-6EE2-4701-BD47-8DDBF425BBE5} 2"   # DEVPKEY_Bluetooth_Battery
AUDIO_WORDS = ("bud", "head", "ear", "pods", "speaker", "sound", "audio")


def _battery(info):
    try:
        value = info.properties.get(BATTERY) if info.properties else None
        if value is None:
            return -1
        from winrt.system import unbox_uint8
        return int(unbox_uint8(value))
    except Exception:
        try:
            return int(value)
        except Exception:
            return -1


class WinBluetoothService(BluetoothService):
    def __init__(self, parent=None):
        self._audio = {}   # device id -> is an audio device (asked once per device)
        super().__init__(parent)

    def _find(self, cls, status):
        from winrt.windows.devices.enumeration import DeviceInformation
        aqs = cls.get_device_selector_from_connection_status(status)
        try:
            return list(wait(DeviceInformation.find_all_async(aqs, [BATTERY])))
        except Exception:
            return list(wait(DeviceInformation.find_all_async(aqs, None)))

    def _is_audio(self, info, classic):
        if info.id not in self._audio:
            audio = any(w in (info.name or "").lower() for w in AUDIO_WORDS)
            if classic and not audio:
                try:
                    from winrt.windows.devices.bluetooth import BluetoothDevice, BluetoothMajorClass
                    device = wait(BluetoothDevice.from_id_async(info.id))
                    audio = device is not None and device.class_of_device.major_class == BluetoothMajorClass.AUDIO_VIDEO
                except Exception:
                    pass
            self._audio[info.id] = audio
        return self._audio[info.id]

    def _connected(self, bus=None):
        from winrt.windows.devices.bluetooth import (
            BluetoothConnectionStatus, BluetoothDevice, BluetoothLEDevice)
        devices, names = {}, set()
        for cls, classic in ((BluetoothDevice, True), (BluetoothLEDevice, False)):
            for info in self._find(cls, BluetoothConnectionStatus.CONNECTED):
                name = info.name or "Bluetooth device"
                if name in names:      # a dual-mode device shows up as both
                    continue
                names.add(name)
                devices[info.id] = {"name": name, "battery": _battery(info), "audio": self._is_audio(info, classic)}
        return devices

    def _run(self):
        name_this_thread("island-bt")
        init_winrt_thread()
        known = None
        while True:
            try:
                now = self._connected()
            except Exception as e:
                if DEBUG:
                    print(f"bluetooth: {e}", flush=True)
                now = None
            if now is not None:
                if known is not None:
                    for key in now.keys() - known.keys():
                        time.sleep(2)   # the battery level usually shows up a moment after the link does
                        try:
                            d = self._connected().get(key, now[key])
                        except Exception:
                            d = now[key]
                        emit(self.deviceEvent, d["name"], True, d["battery"], d["audio"])
                    for key in known.keys() - now.keys():
                        d = known[key]
                        emit(self.deviceEvent, d["name"], False, -1, d["audio"])
                known = now
                emit(self._snapshot, sorted(now.values(), key=lambda d: d["name"]))
            time.sleep(3)
