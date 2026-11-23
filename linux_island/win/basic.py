"""Windows: battery, lock screen, camera and microphone in use, and which monitors have no windows."""
import ctypes
import os
import sys
import time

from PySide6.QtCore import Property, QObject, QTimer, Signal
from PySide6.QtGui import QGuiApplication

from ..services.battery import BatteryService
from ..services.camera import CameraService
from ..services.lock import LockService
from ..services.microphone import MicrophoneService
from ..services.threads import emit, name_this_thread
from . import api, logic

DEBUG = bool(os.environ.get("LINUX_ISLAND_DEBUG"))


class WinBatteryService(BatteryService):
    def _find(self):
        status = api.power_status()
        return True if status and logic.battery_state(*status)[0] else None

    def _read(self):
        status = api.power_status()
        if not status:
            raise OSError("GetSystemPowerStatus failed")
        _, percent, plugged = logic.battery_state(*status)
        return percent, plugged, logic.charge_state(plugged, status[1], percent)


class WinLockService(LockService):
    """The lock screen is followed by polling the input desktop (cheap); locking is LockWorkStation."""

    def _watch(self):
        name_this_thread("island-lock")
        last = None
        while True:
            try:
                locked = api.session_locked()
            except Exception:
                locked = last
            if locked is not None and locked != last:
                last = locked
                emit(self._locked_from_bus, locked)
            time.sleep(0.5)

    def _lock_session(self):
        if not api.lock_workstation():
            self._lock_failed()


# ---- camera / microphone: Windows' own record of which app uses them ---------------------------
CONSENT_STORE = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore"


def _scan(reg, key, found):
    i = 0
    while True:
        try:
            name = reg.EnumKey(key, i)
        except OSError:
            return
        i += 1
        try:
            with reg.OpenKey(key, name) as sub:
                if name == "NonPackaged":
                    _scan(reg, sub, found)
                    continue
                try:
                    start = reg.QueryValueEx(sub, "LastUsedTimeStart")[0]
                    stop = reg.QueryValueEx(sub, "LastUsedTimeStop")[0]
                except OSError:
                    continue
                if logic.in_use(start, stop):
                    found.append(logic.consent_app_name(name))
        except OSError:
            continue


def apps_using(capability, reg=None):
    """Apps using "webcam" or "microphone" right now, per user and machine-wide."""
    if reg is None:
        import winreg as reg
    found = []
    for root in (reg.HKEY_CURRENT_USER, reg.HKEY_LOCAL_MACHINE):
        try:
            with reg.OpenKey(root, CONSENT_STORE + "\\" + capability) as key:
                _scan(reg, key, found)
        except OSError:
            pass
    return found


class _RegistryWatch:
    """Waits until something under HKCU's ConsentStore\\<capability> changes (or `timeout` passes)."""

    def __init__(self, capability):
        import winreg
        self._key = None
        try:
            self._key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, CONSENT_STORE + "\\" + capability)
            self._advapi = ctypes.WinDLL("advapi32")
            self._event = api.kernel32.CreateEventW(None, False, False, None)
        except (OSError, AttributeError):
            self._key = None

    def wait(self, timeout):
        if self._key is None or not self._event:
            time.sleep(timeout)
            return
        # REG_NOTIFY_CHANGE_NAME | REG_NOTIFY_CHANGE_LAST_SET, the whole subtree, signalled through the event
        if self._advapi.RegNotifyChangeKeyValue(ctypes.c_void_p(self._key.handle), True, 0x1 | 0x4,
                                                ctypes.c_void_p(self._event), True) != 0:
            time.sleep(timeout)
            return
        api.kernel32.WaitForSingleObject(ctypes.c_void_p(self._event), int(timeout * 1000))


api.kernel32.CreateEventW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_wchar_p]
api.kernel32.CreateEventW.restype = ctypes.c_void_p
api.kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]


class WinCameraService(CameraService):
    def _poll(self):
        name_this_thread("island-camera")
        watch = _RegistryWatch("webcam")
        while True:
            try:
                apps = apps_using("webcam")
            except Exception:
                apps = []
            emit(self._polled, apps[0] if apps else "")
            watch.wait(10)
            time.sleep(0.2)   # Windows writes start and stop times one after the other


class WinMicrophoneService(MicrophoneService):
    def _refresh(self):
        try:
            active = bool(apps_using("microphone"))
        except Exception:
            active = False
        if active != self._active:
            self._active = active
            self.activeChanged.emit()


# ---- empty monitors (home card) ---------------------------------------------------------------
class WinDesktopService(QObject):
    """Monitors with no application window (all minimised or none open). Window events (shown, hidden,
    minimised, moved, cloaked) trigger a re-read; a slow timer is only a safety net."""
    emptyChanged = Signal()
    sourceChanged = Signal()

    def __init__(self, parent=None, use_shell=True):
        super().__init__(parent)
        self._empty = []
        self._hook = None
        self._settle = QTimer(self, singleShot=True, interval=80, timeout=self._refresh)
        try:
            self._hook = api.hook_window_events(self._poke)
        except Exception as e:
            print(f"linux-island: window events unavailable ({e}), checking every second", file=sys.stderr)
        self._timer = QTimer(self, interval=3000 if self._hook else 1000, timeout=self._refresh)
        self._timer.start()
        app = QGuiApplication.instance()
        app.screenAdded.connect(self._poke)
        app.screenRemoved.connect(self._poke)
        self._refresh()

    def _poke(self, *_):
        if not self._settle.isActive():
            self._settle.start()

    def _refresh(self):
        try:
            windows, monitors = api.visible_windows(), api.monitors()
        except Exception as e:
            if DEBUG:
                print(f"desktop: {e}", flush=True)
            return
        screens = []
        for s in QGuiApplication.screens():
            g = s.geometry()
            screens.append((s.name(), g.x(), g.y(), g.width(), g.height(), s.devicePixelRatio()))
        screen_of = {m.handle: logic.match_screen(m.device, m.rect, screens) for m in monitors}
        empty = logic.empty_screens(windows, screen_of, [s[0] for s in screens], os.getpid())
        if empty != self._empty:
            if DEBUG:
                print(f"desktop: empty monitors {empty}", flush=True)
            self._empty = empty
            self.emptyChanged.emit()

    @Property(str, notify=sourceChanged)
    def source(self):
        return "windows"

    @Property("QVariantList", notify=emptyChanged)
    def emptyScreens(self):
        return self._empty
