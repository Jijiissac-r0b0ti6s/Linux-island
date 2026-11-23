"""The island's services. Each has a Linux implementation here and a Windows one in `linux_island.win`
with the same properties, signals and slots, so the QML doesn't know which it is talking to."""
import sys

if sys.platform == "win32":
    from ..win.audio import WinAudioService as AudioService
    from ..win.basic import (
        WinBatteryService as BatteryService, WinCameraService as CameraService,
        WinDesktopService as DesktopService, WinLockService as LockService,
        WinMicrophoneService as MicrophoneService)
    from ..win.bluetooth import WinBluetoothService as BluetoothService
    from ..win.brightness import WinBrightnessService as BrightnessService
    from ..win.media import WinMediaService as MediaService
else:
    from .audio import AudioService
    from .battery import BatteryService
    from .bluetooth import BluetoothService
    from .brightness import BrightnessService
    from .camera import CameraService
    from .desktop import DesktopService
    from .lock import LockService
    from .media import MediaService
    from .microphone import MicrophoneService

__all__ = [
    "AudioService", "BatteryService", "BluetoothService", "BrightnessService", "CameraService",
    "DesktopService", "LockService", "MediaService", "MicrophoneService",
]
