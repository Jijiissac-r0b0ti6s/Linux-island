"""Windows per-monitor brightness.

* Laptop panel: WMI (root\\wmi WmiMonitorBrightness / WmiSetBrightness), read once a second so the
  brightness keys show the pop-up (Windows' own adaptive / battery-saver dimming doesn't, see AutoDimFilter).
* External monitors: DDC/CI (dxva2), the monitor's real backlight, when the monitor supports it.

Both are slow-ish calls, so a worker thread owns them; the slider only queues the level it wants.
"""
import os
import subprocess
import threading

from PySide6.QtCore import Property, QObject, Signal, Slot
from PySide6.QtGui import QGuiApplication

from ..services.brightness import MIN_BACKLIGHT, AutoDimFilter
from ..services.idle import IdleClock
from ..services.threads import emit, name_this_thread
from . import api, logic

DEBUG = bool(os.environ.get("LINUX_ISLAND_DEBUG"))


def _dynamic(obj):
    from comtypes.client.dynamic import Dispatch, _Dispatch
    return obj if isinstance(obj, _Dispatch) else Dispatch(obj)


class Wmi:
    """The laptop panel's brightness through WMI (COM, on the calling thread)."""

    def __init__(self):
        import comtypes.client
        self._svc = _dynamic(comtypes.client.CoGetObject(r"winmgmts:{impersonationLevel=impersonate}!\\.\root\wmi",
                                                         dynamic=True))
        self._svc._FlagAsMethod("ExecQuery")

    def _query(self, wql):
        return [_dynamic(o) for o in _dynamic(self._svc.ExecQuery(wql))]

    def panels(self):
        """[(instance name, percent)] of the built-in panels (none on a desktop PC)."""
        return [(str(o.InstanceName), int(o.CurrentBrightness))
                for o in self._query("SELECT InstanceName, CurrentBrightness FROM WmiMonitorBrightness WHERE Active=TRUE")]

    def set(self, percent):
        for o in self._query("SELECT * FROM WmiMonitorBrightnessMethods WHERE Active=TRUE"):
            o._FlagAsMethod("WmiSetBrightness")
            o.WmiSetBrightness(1, int(percent))


def _powershell_set(percent):
    """Fallback when WMI through COM doesn't work: the same call through PowerShell (slower)."""
    script = ("Get-CimInstance -Namespace root/wmi -ClassName WmiMonitorBrightnessMethods | "
              f"Invoke-CimMethod -MethodName WmiSetBrightness -Arguments @{{Timeout=1; Brightness={int(percent)}}}")
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                   creationflags=subprocess.CREATE_NO_WINDOW, capture_output=True, timeout=15)


class WinBrightnessService(QObject):
    levelsChanged = Signal()
    changed = Signal(str)            # monitor whose brightness changed from outside (brightness keys)
    _read = Signal(object, object)   # {screen: level}, (before, after) of the panel when it changed by itself

    def __init__(self, parent=None):
        super().__init__(parent)
        self._levels = {}
        self._internal = ""
        self._pending = {}           # screen -> level the slider asked for
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._rescan = True
        self._screens = []
        self._idle = IdleClock()
        self._auto_dim = AutoDimFilter()
        self._ticks = 0
        self._read.connect(self._apply)
        app = QGuiApplication.instance()
        app.screenAdded.connect(self._screens_changed)
        app.screenRemoved.connect(self._screens_changed)
        self._screens_changed()
        threading.Thread(target=self._work, daemon=True, name="brightness").start()

    def _screens_changed(self, *_):
        screens = []
        for s in QGuiApplication.screens():   # QScreen is only safe on this (main) thread: hand over a copy
            g = s.geometry()
            screens.append((s.name(), g.x(), g.y(), g.width(), g.height(), s.devicePixelRatio()))
        with self._lock:
            self._screens, self._rescan = screens, True
        self._wake.set()

    # ---- worker thread -------------------------------------------------
    def _work(self):
        name_this_thread("island-bright")
        import comtypes
        comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
        try:
            wmi = Wmi()
            wmi.panels()
        except Exception as e:
            if DEBUG:
                print(f"brightness: WMI unavailable ({e})", flush=True)
            wmi = None
        use_powershell = False
        external, internal = {}, ""   # screen -> (PhysicalMonitors, min, max); the panel's screen name
        panel = None                  # last panel percent
        while True:
            with self._lock:
                rescan, screens = self._rescan, self._screens
                self._rescan = False
                pending, self._pending = self._pending, {}
            if rescan:
                for phys, *_ in external.values():
                    phys.close()
                external, internal = self._scan(screens, wmi)
            levels, change = {}, None
            for screen, level in pending.items():
                try:
                    if screen == internal:
                        percent = max(1, round(level * 100))
                        if wmi and not use_powershell:
                            try:
                                wmi.set(percent)
                            except Exception:
                                use_powershell = True
                        if use_powershell:
                            _powershell_set(percent)
                        panel = percent   # ours: not a brightness-key change
                    elif screen in external:
                        phys, lo, hi = external[screen]
                        phys.set_brightness(lo + round(level * (hi - lo)))
                except Exception as e:
                    if DEBUG:
                        print(f"brightness: set {screen}: {e}", flush=True)
            if internal and wmi:
                try:
                    now = wmi.panels()[0][1]
                    if panel is not None and now != panel:
                        change = (panel, now)
                    panel = now
                except Exception:
                    pass
            if internal and panel is not None:
                levels[internal] = panel / 100
            for screen, (phys, lo, hi) in external.items():
                levels[screen] = self._levels.get(screen, 1.0) if not rescan else self._ddc_level(phys, lo, hi)
            emit(self._read, levels, change)
            self._wake.wait(1.0)
            self._wake.clear()

    @staticmethod
    def _ddc_level(phys, lo, hi):
        got = phys.brightness()
        return (got[1] - lo) / (hi - lo) if got else 1.0

    def _scan(self, screens, wmi):
        """Which screen is the laptop panel, and which external ones answer DDC/CI."""
        external, no_ddc = {}, []
        for m in api.monitors():
            name = logic.match_screen(m.device, m.rect, screens)
            if not name:
                continue
            phys = api.PhysicalMonitors(m.handle)
            got = phys.brightness()
            if got:
                external[name] = (phys, got[0], got[2])
            else:
                phys.close()
                no_ddc.append((name, m))
        internal = ""
        if wmi and no_ddc:
            try:
                codes = {logic.pnp_code(instance) for instance, _ in wmi.panels()}
            except Exception:
                codes = set()
            for name, m in no_ddc:
                if any(logic.pnp_code(i) in codes for i in api.monitor_device_ids(m.device)):
                    internal = name
                    break
            if not internal and codes and len(no_ddc) == 1:
                internal = no_ddc[0][0]
        if DEBUG:
            print(f"brightness: panel {internal or '-'}, DDC/CI {sorted(external) or '-'}", flush=True)
        self._internal_found = internal
        return external, internal

    # ---- main thread ---------------------------------------------------
    @Slot(object, object)
    def _apply(self, levels, change):
        self._internal = getattr(self, "_internal_found", "")
        self._ticks += 1
        if self._ticks % 2 == 1:
            self._auto_dim.note_idle(self._idle.idle_ms())
        with self._lock:
            waiting = set(self._pending)
        for screen in waiting:          # the slider is ahead of the hardware: keep showing its value
            if screen in self._levels:
                levels[screen] = self._levels[screen]
        if levels != self._levels:
            self._levels = levels
            self.levelsChanged.emit()
        if change and self._internal:
            before, after = change
            user = self._auto_dim.is_user_change(before, after, self._idle.idle_ms())
            if DEBUG:
                print(f"brightness: panel {before} -> {after} hud={user}", flush=True)
            if user:
                self.changed.emit(self._internal)

    @Property("QVariantMap", notify=levelsChanged)
    def levels(self):
        return self._levels

    @Slot(str, float)
    def setLevel(self, screen, v):
        if screen not in self._levels:
            return
        v = max(MIN_BACKLIGHT, min(1.0, v))
        if screen == self._internal:
            self._auto_dim.reset()   # the user picked a level; forget any idle dim
        with self._lock:
            self._pending[screen] = v
        self._levels = dict(self._levels, **{screen: v})
        self.levelsChanged.emit()
        self._wake.set()
