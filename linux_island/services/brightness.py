"""Per-monitor brightness.

* Laptop panel: real backlight, read from sysfs and written through systemd-logind (no root).
* External monitors (X11): software dimming with `xrandr --brightness`. It darkens the
  picture rather than the backlight, but needs no extra packages or permissions.
"""
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from jeepney import DBusAddress, MessageType, new_method_call
from jeepney.io.blocking import open_dbus_connection
from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot
from PySide6.QtGui import QGuiApplication

from .idle import IdleClock

INTERNAL_PREFIXES = ("eDP", "LVDS", "DSI")
MIN_BACKLIGHT = 0.01   # never let the slider turn the panel fully off
MIN_SOFTWARE = 0.2     # below this an xrandr-dimmed screen is unreadable


def _find_backlight():
    devices = sorted(Path("/sys/class/backlight").glob("*"))
    # firmware/platform drivers first, raw GPU drivers as a fallback
    devices.sort(key=lambda d: 0 if (d / "type").exists() and (d / "type").read_text().strip() != "raw" else 1)
    return devices[0] if devices else None


class AutoDimFilter:
    """Tells brightness-key changes apart from the desktop's own idle dimming.

    GNOME fades the panel down after a while without input and back up on the first mouse
    move. The fade down happens while the user is idle; the fade back up is the first change
    after they return. Neither should pop the brightness HUD.
    """
    IDLE_MS = 4000        # idle this long when the level drops: the desktop dimmed it
    RESTORE_S = 3.0       # after input resumes, the fade back up finishes within this
    AWAY_MS = 30_000      # idle this long, then brighter on return: the desktop undimming

    def __init__(self):
        self.dimmed = False
        self._before_dim = 0
        self._restore_until = None
        self._was_idle = False     # the last idle sample said nobody was at the computer

    def reset(self):
        self.dimmed = False
        self._restore_until = None
        self._was_idle = False

    def note_idle(self, idle_ms):
        """Periodic idle sample, so a wake-up is recognised even if the dim itself went unseen
        (e.g. the island started while the screen was already dimmed)."""
        if idle_ms is not None:
            self._was_idle = idle_ms >= self.AWAY_MS

    def is_user_change(self, before, after, idle_ms, now=None):
        now = time.monotonic() if now is None else now
        if idle_ms is None:          # can't tell: behave as before
            return True
        if idle_ms >= self.IDLE_MS:  # nobody is touching anything
            if not self.dimmed or self._restore_until is not None:
                # a new dim (also after an earlier wake-up that never got back to its level)
                self.dimmed, self._before_dim, self._restore_until = True, before, None
            self._was_idle = idle_ms >= self.AWAY_MS
            return False
        if not self.dimmed and self._was_idle and after > before:
            # brightening the moment the user came back: the undim of a dim we never saw;
            # its target is unknown, so only the time window ends it
            self.dimmed, self._before_dim = True, float("inf")
        self._was_idle = False
        if self.dimmed:
            if self._restore_until is None:
                self._restore_until = now + self.RESTORE_S
            restoring = now < self._restore_until
            if after >= self._before_dim or not restoring:
                self.reset()      # back where it was (or the fade is long over)
            return not restoring
        return True


def _xrandr_levels():
    """Current software brightness of every connected output."""
    try:
        out = subprocess.run(["xrandr", "--verbose"], capture_output=True, text=True, timeout=4).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    levels, name = {}, None
    for line in out.splitlines():
        m = re.match(r"(\S+) connected", line)
        if m:
            name = m.group(1)
        m = re.match(r"\s+Brightness:\s*([\d.]+)", line)
        if m and name:
            levels[name] = float(m.group(1))
    return levels


class BrightnessService(QObject):
    levelsChanged = Signal()
    changed = Signal(str)  # monitor whose brightness changed from outside (e.g. brightness keys)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._levels = {}
        self._internal = ""        # screen name driven by the backlight
        self._dev = _find_backlight()
        self._max = 1
        self._raw = -1
        self._bus = None
        self._software = QGuiApplication.platformName() == "xcb" and bool(shutil.which("xrandr"))
        self._pending = {}         # external monitor -> level waiting to be applied
        self._idle = IdleClock()
        self._auto_dim = AutoDimFilter()
        self._ticks = 0
        self._apply_timer = QTimer(self, interval=70, singleShot=True, timeout=self._apply_pending)
        if self._dev:
            try:
                self._max = max(1, int((self._dev / "max_brightness").read_text()))
            except (OSError, ValueError):
                self._dev = None

        app = QGuiApplication.instance()
        app.screenAdded.connect(self._rescan)
        app.screenRemoved.connect(self._rescan)
        self._rescan()
        if self._dev:
            self._timer = QTimer(self, interval=400, timeout=self._poll_backlight)
            self._timer.start()

    def _rescan(self, *_):
        names = [s.name() for s in QGuiApplication.screens()]
        internal = [n for n in names if n.startswith(INTERNAL_PREFIXES)]
        self._internal = internal[0] if internal and self._dev else ""
        levels = {}
        if self._internal:
            self._read_backlight()
            levels[self._internal] = self._raw / self._max
        if self._software:
            current = _xrandr_levels()
            for name in names:
                if name != self._internal and name in current:
                    levels[name] = max(MIN_SOFTWARE, min(1.0, current[name]))
        self._levels = levels
        self.levelsChanged.emit()

    # ---- laptop backlight ----------------------------------------------
    def _read_backlight(self):
        try:
            self._raw = int((self._dev / "brightness").read_text())
        except (OSError, ValueError):
            pass

    def _poll_backlight(self):
        if not self._internal:
            return
        self._ticks += 1
        if self._ticks % 5 == 1:   # every 2 s, starting with the first poll
            self._auto_dim.note_idle(self._idle.idle_ms())
        before = self._raw
        self._read_backlight()
        if self._raw != before:
            self._levels[self._internal] = self._raw / self._max
            self.levelsChanged.emit()
            idle = self._idle.idle_ms()
            user = self._auto_dim.is_user_change(before, self._raw, idle)
            if os.environ.get("LINUX_ISLAND_DEBUG"):
                f = self._auto_dim
                print(f"brightness: {before} -> {self._raw} idle={idle}ms hud={user} "
                      f"(dimmed={f.dimmed} target={f._before_dim} away={f._was_idle})", flush=True)
            if user:
                self.changed.emit(self._internal)

    def _set_backlight(self, v):
        raw = round(max(MIN_BACKLIGHT, min(1.0, v)) * self._max)
        if raw != self._raw and (self._write_logind(raw) or self._write_sysfs(raw)):
            self._auto_dim.reset()  # the user picked a level; forget any idle dim
            self._raw = raw
            self._levels[self._internal] = raw / self._max
            self.levelsChanged.emit()

    def _write_logind(self, raw):
        try:
            if self._bus is None:
                self._bus = open_dbus_connection("SYSTEM")
            addr = DBusAddress(
                "/org/freedesktop/login1/session/auto",
                bus_name="org.freedesktop.login1",
                interface="org.freedesktop.login1.Session",
            )
            msg = new_method_call(addr, "SetBrightness", "ssu", ("backlight", self._dev.name, raw))
            reply = self._bus.send_and_get_reply(msg, timeout=1.0)
            return reply.header.message_type == MessageType.method_return
        except Exception:
            self._bus = None
            return False

    def _write_sysfs(self, raw):
        try:
            (self._dev / "brightness").write_text(str(raw))
            return True
        except OSError:
            return False

    # ---- external monitors ---------------------------------------------
    def _apply_pending(self):
        pending, self._pending = self._pending, {}
        for name, level in pending.items():
            try:
                subprocess.Popen(["xrandr", "--output", name, "--brightness", f"{level:.2f}"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError:
                pass

    # ---- QML API --------------------------------------------------------
    @Property("QVariantMap", notify=levelsChanged)
    def levels(self):
        """Brightness (0..1) for each monitor that can be controlled, keyed by output name."""
        return dict(self._levels)

    @Slot(str, float)
    def setLevel(self, screen, v):
        if screen not in self._levels:
            return
        if screen == self._internal:
            self._set_backlight(v)
            return
        level = max(MIN_SOFTWARE, min(1.0, v))
        self._levels[screen] = level
        self.levelsChanged.emit()
        self._pending[screen] = level  # throttled: a slider drag would otherwise spawn xrandr per pixel
        if not self._apply_timer.isActive():
            self._apply_timer.start()
