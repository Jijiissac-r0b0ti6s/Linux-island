"""Camera-in-use indicator: is any of the user's processes holding /dev/video* open?"""
import ctypes
import ctypes.util
import glob
import os
import select
import struct
import threading
import time

from PySide6.QtCore import Property, QObject, Signal, Slot
from .threads import emit, name_this_thread

_RELAYS = {"pipewire", "wireplumber", "xdg-desktop-por"}  # hold the device on behalf of another app


def _scan():
    """Return the name of a process using a camera, or None."""
    me = str(os.getpid())
    relay = None
    for pid in os.listdir("/proc"):
        if not pid.isdigit() or pid == me:
            continue
        try:
            with os.scandir(f"/proc/{pid}/fd") as fds:
                using = any(os.readlink(fd.path).startswith("/dev/video") for fd in fds)
            if not using:
                continue
            with open(f"/proc/{pid}/comm") as f:
                name = f.read().strip()
        except OSError:
            continue  # other users' processes, or the process just exited
        if name not in _RELAYS:
            return name
        relay = name
    return relay


class _CameraWatch:
    """inotify on /dev/video* (opened / closed) and /dev (a webcam plugged in or removed)."""
    IN_OPEN, IN_CLOSE, IN_CREATE, IN_DELETE = 0x20, 0x18, 0x100, 0x200

    def __init__(self):
        self.ok = False
        self._nodes = set()
        try:
            self._libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
            self._fd = self._libc.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
            if self._fd < 0:
                return
            self._libc.inotify_add_watch(self._fd, b"/dev", self.IN_CREATE | self.IN_DELETE)
            self._add_nodes()
            self.ok = True
        except (OSError, AttributeError):
            pass

    def _add_nodes(self):
        for node in glob.glob("/dev/video*"):
            if node not in self._nodes:
                self._libc.inotify_add_watch(self._fd, node.encode(), self.IN_OPEN | self.IN_CLOSE)
                self._nodes.add(node)

    def wait(self, timeout):
        """True when something camera-related happened within `timeout` seconds."""
        if not self.ok:
            time.sleep(timeout)
            return True
        ready, _, _ = select.select([self._fd], [], [], timeout)
        if not ready:
            return False
        try:
            data = os.read(self._fd, 65536)
        except BlockingIOError:
            return False
        if b"video" in data:   # a /dev entry named video*: (un)plugged camera
            self._nodes = {n for n in self._nodes if os.path.exists(n)}
            self._add_nodes()
        return any(self._is_camera_event(data))

    def _is_camera_event(self, data):
        i = 0
        while i + 16 <= len(data):
            wd, mask, cookie, length = struct.unpack_from("iIII", data, i)
            name = data[i + 16:i + 16 + length].rstrip(b"\0")
            i += 16 + length
            yield wd != 1 or name.startswith(b"video")   # wd 1 is /dev itself: only care about video*


class CameraService(QObject):
    activeChanged = Signal()
    _polled = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._app = ""
        self._polled.connect(self._apply)
        threading.Thread(target=self._poll, daemon=True, name="camera-poll").start()

    def _poll(self):
        name_this_thread("island-camera")
        watch = _CameraWatch()
        while True:
            if glob.glob("/dev/video*"):
                emit(self._polled, _scan() or "")
            # rescan only when a camera device is opened or closed (or one is plugged in);
            # without inotify, fall back to a scan every 3 s
            if not watch.wait(30 if watch.ok else 3):
                continue
            time.sleep(0.3)   # let the app finish opening, or the last holder close

    @Slot(str)
    def _apply(self, app):
        if app != self._app:
            self._app = app
            self.activeChanged.emit()

    @Property(bool, notify=activeChanged)
    def active(self):
        return bool(self._app)

    @Property(str, notify=activeChanged)
    def app(self):
        return "" if self._app in _RELAYS else self._app
