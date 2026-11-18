"""Screen lock and screensaver state, for the clock card and black fade the pill turns into.

* `locked`   - the desktop's lock screen is up (GNOME's org.gnome.ScreenSaver, else logind's LockedHint).
* `locking`  - lockNow() was called: the card and fade play first, the real lock follows.
* `idle`     - screensaver: nobody has touched the computer for `screensaver_minutes`.
"""
import os
import subprocess
import threading
import time

from jeepney import DBusAddress, MatchRule, MessageType, message_bus, new_method_call
from jeepney.io.blocking import Proxy, open_dbus_connection
from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from .idle import IdleClock
from .threads import name_this_thread

GNOME = DBusAddress("/org/gnome/ScreenSaver", bus_name="org.gnome.ScreenSaver", interface="org.gnome.ScreenSaver")
LOGIND_SESSION = DBusAddress("/org/freedesktop/login1/session/auto", bus_name="org.freedesktop.login1",
                             interface="org.freedesktop.DBus.Properties")
GROW_MS = 900        # card landed + screen faded to black: hand over to the lock screen
WAKE_IDLE_MS = 1500  # input this recent ends the screensaver
DEBUG = bool(os.environ.get("LINUX_ISLAND_DEBUG"))


class LockService(QObject):
    changed = Signal()
    _locked_from_bus = Signal(bool)

    def __init__(self, screensaver_minutes=0, parent=None, start=True):
        super().__init__(parent)
        self._locked = False
        self._locking = False
        self._idle = False
        self._ignore_until = 0.0   # input before this doesn't end a screensaver started by hand
        self._armed = False        # screensaver may start: someone used the computer since the last one / unlock
        self._saver_ms = max(0, float(screensaver_minutes or 0)) * 60_000
        self._clock = IdleClock()
        self._locked_from_bus.connect(self._set_locked)
        self._lock_timer = QTimer(self, singleShot=True, interval=GROW_MS, timeout=self._lock_session)
        self._giveup = QTimer(self, singleShot=True, interval=6000, timeout=self._lock_failed)
        self._idle_timer = QTimer(self, interval=2000, timeout=self._poll_idle)
        if start:
            threading.Thread(target=self._watch, daemon=True, name="lock-watch").start()
            self._idle_timer.start()

    # ---- worker thread: follow the lock screen ---------------------------
    def _watch(self):
        name_this_thread("island-lock")
        try:
            conn = open_dbus_connection("SESSION")
            reply = conn.send_and_get_reply(new_method_call(GNOME, "GetActive"), timeout=2)
            if reply.header.message_type != MessageType.method_return:
                raise RuntimeError("no org.gnome.ScreenSaver")
            self._locked_from_bus.emit(bool(reply.body[0]))
            rule = MatchRule(type="signal", interface=GNOME.interface, member="ActiveChanged",
                             path=GNOME.object_path)
            Proxy(message_bus, conn).AddMatch(rule)
            with conn.filter(rule) as signals:
                while True:
                    msg = conn.recv_until_filtered(signals)
                    self._locked_from_bus.emit(bool(msg.body[0]))
        except Exception as e:
            if DEBUG:
                print(f"lock: GNOME screensaver unavailable ({e}), polling logind", flush=True)
        self._poll_logind()

    def _poll_logind(self):
        try:
            conn = open_dbus_connection("SYSTEM")
        except Exception:
            return
        last = None
        while True:
            try:
                msg = new_method_call(LOGIND_SESSION, "Get", "ss", ("org.freedesktop.login1.Session", "LockedHint"))
                reply = conn.send_and_get_reply(msg, timeout=2)
                if reply.header.message_type == MessageType.method_return:
                    locked = bool(reply.body[0][1])
                    if locked != last:
                        last = locked
                        self._locked_from_bus.emit(locked)
            except Exception:
                pass
            time.sleep(0.5)

    # ---- main thread -------------------------------------------------------
    @Slot(bool)
    def _set_locked(self, locked):
        if DEBUG:
            print(f"lock: locked={locked}", flush=True)
        self._locked = locked
        if locked:
            self._locking = False   # the real lock took over
            self._giveup.stop()
        else:
            self._idle = False      # unlocking means someone is here...
            self._armed = False     # ...even if a fingerprint unlock didn't count as input
            self._idle_timer.setInterval(2000)
        self.changed.emit()

    def set_screensaver_minutes(self, minutes):
        """Settings changed: 0 turns the screensaver off."""
        self._saver_ms = max(0, float(minutes or 0)) * 60_000
        if not self._saver_ms and self._idle:
            self.wake()

    def _poll_idle(self):
        ms = self._clock.idle_ms()
        if ms is None:
            return
        if ms < min(self._saver_ms or WAKE_IDLE_MS, 60_000) and not self._armed:
            self._armed = True
            if DEBUG:
                print(f"screensaver: armed (idle {ms} ms)", flush=True)
        if self._saver_ms and self._armed and not self._idle and not self._locked and ms >= self._saver_ms:
            if DEBUG:
                print(f"screensaver: starting after {ms} ms idle", flush=True)
            self._idle = True
            self._armed = False
            self._idle_timer.setInterval(250)   # react quickly to the first input
            self.changed.emit()
        elif self._idle and ms < WAKE_IDLE_MS and time.monotonic() >= self._ignore_until:
            self.wake()

    def _lock_session(self):
        try:
            conn = open_dbus_connection("SESSION")
            reply = conn.send_and_get_reply(new_method_call(GNOME, "Lock"), timeout=3)
            conn.close()
            if reply.header.message_type == MessageType.method_return:
                return
        except Exception:
            pass
        try:
            subprocess.Popen(["loginctl", "lock-session"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            self._lock_failed()

    def _lock_failed(self):
        if self._locking and not self._locked:
            self._locking = False
            self.changed.emit()

    @Slot()
    def lockNow(self):
        """Grow the pill to full screen, then lock."""
        if self._locked or self._locking:
            return
        self._locking = True
        self.changed.emit()
        self._lock_timer.start()
        self._giveup.start()   # nothing locked: shrink back instead of staying black

    @Slot()
    def startSaver(self):
        """Screensaver now (`linux-island --screensaver`), until the next input after a short grace."""
        if self._locked or self._idle:
            return
        self._idle = True
        self._ignore_until = time.monotonic() + 2.0   # the key that ran the command
        self._idle_timer.setInterval(250)
        self.changed.emit()

    @Slot()
    def wake(self):
        """End the idle screensaver (any input)."""
        if self._idle and time.monotonic() >= self._ignore_until:
            self._idle = False
            self._idle_timer.setInterval(2000)
            self.changed.emit()

    @Property(bool, notify=changed)
    def locked(self):
        return self._locked

    @Property(bool, notify=changed)
    def locking(self):
        return self._locking

    @Property(bool, notify=changed)
    def idle(self):
        return self._idle

    @Property(bool, notify=changed)
    def active(self):
        """The pill should be full screen."""
        return self._locked or self._locking or self._idle
