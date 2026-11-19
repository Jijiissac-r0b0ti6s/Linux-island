"""Tells the island which monitors have an empty desktop (every window there minimised).

Event-driven: the root window and every application window are watched for property and
structure changes (minimise, restore, move, workspace switch, open, close), and the windows
are only re-read when one of those happens, instead of being polled several times a second.
"""
import ctypes
import ctypes.util

from PySide6.QtCore import Property, QObject, QSocketNotifier, QTimer, Signal
from PySide6.QtGui import QGuiApplication

from .. import system
from .shell_windows import ShellWindows

_ERROR_HANDLER = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
ALL_DESKTOPS = 0xFFFFFFFF
PROPERTY_CHANGE_MASK = 1 << 22
STRUCTURE_NOTIFY_MASK = 1 << 17


class _X11Windows:
    """Minimal EWMH reader on its own Xlib connection."""

    def __init__(self):
        x = self._x = ctypes.CDLL(ctypes.util.find_library("X11"))
        x.XOpenDisplay.restype = ctypes.c_void_p
        x.XOpenDisplay.argtypes = [ctypes.c_char_p]
        x.XDefaultRootWindow.restype = ctypes.c_ulong
        x.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        x.XInternAtom.restype = ctypes.c_ulong
        x.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
        x.XFree.argtypes = [ctypes.c_void_p]
        x.XGetWindowProperty.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_long, ctypes.c_long, ctypes.c_int, ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_void_p),
        ]
        # Windows can disappear between listing and querying them; Xlib's default
        # handler would kill the process on the resulting BadWindow error.
        x.XGetGeometry.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint),
            ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint),
        ]
        x.XTranslateCoordinates.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_int, ctypes.c_int,
            ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_ulong),
        ]
        x.XSelectInput.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_long]
        x.XConnectionNumber.argtypes = [ctypes.c_void_p]
        x.XPending.argtypes = [ctypes.c_void_p]
        x.XNextEvent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        x.XFlush.argtypes = [ctypes.c_void_p]
        self._ignore_errors = _ERROR_HANDLER(lambda display, event: 0)
        x.XSetErrorHandler(self._ignore_errors)
        self._display = x.XOpenDisplay(None)
        if not self._display:
            raise RuntimeError("cannot open X display")
        self._root = x.XDefaultRootWindow(self._display)
        self._atoms = {}
        self._watched = set()
        self._event = ctypes.create_string_buffer(192)   # sizeof(XEvent)
        x.XSelectInput(self._display, self._root, PROPERTY_CHANGE_MASK)   # client list, workspace, show desktop
        x.XFlush(self._display)

    def fileno(self):
        return self._x.XConnectionNumber(self._display)

    def drain(self):
        """Discard queued events; True if there were any."""
        any_events = False
        while self._x.XPending(self._display):
            self._x.XNextEvent(self._display, self._event)
            any_events = True
        return any_events

    def _watch(self, windows):
        """Get told when these windows are minimised, restored, moved or change workspace."""
        new = set(windows) - self._watched
        for window in new:
            self._x.XSelectInput(self._display, window, PROPERTY_CHANGE_MASK | STRUCTURE_NOTIFY_MASK)
        self._watched = set(windows)   # closed windows drop out (their selection dies with them)
        if new:
            self._x.XFlush(self._display)

    def _atom(self, name):
        if name not in self._atoms:
            self._atoms[name] = self._x.XInternAtom(self._display, name.encode(), 0)
        return self._atoms[name]

    def _get(self, window, name):
        """Return a 32-bit list property as Python ints ([] when missing)."""
        kind, fmt = ctypes.c_ulong(), ctypes.c_int()
        count, left, data = ctypes.c_ulong(), ctypes.c_ulong(), ctypes.c_void_p()
        status = self._x.XGetWindowProperty(
            self._display, window, self._atom(name), 0, 4096, 0, 0,
            ctypes.byref(kind), ctypes.byref(fmt), ctypes.byref(count), ctypes.byref(left), ctypes.byref(data),
        )
        if status != 0 or not data:
            return []
        try:
            if fmt.value != 32:
                return []
            # format-32 values arrive in C longs, sign-extended: mask back to 32 bits
            return [v & 0xFFFFFFFF for v in ctypes.cast(data, ctypes.POINTER(ctypes.c_ulong))[: count.value]]
        finally:
            self._x.XFree(data)

    def _centre(self, window):
        """Centre of a window in root (device-pixel) coordinates, or None if it is gone."""
        root, child = ctypes.c_ulong(), ctypes.c_ulong()
        x, y, rx, ry = ctypes.c_int(), ctypes.c_int(), ctypes.c_int(), ctypes.c_int()
        w, h, border, depth = ctypes.c_uint(), ctypes.c_uint(), ctypes.c_uint(), ctypes.c_uint()
        if not self._x.XGetGeometry(self._display, window, ctypes.byref(root), ctypes.byref(x), ctypes.byref(y),
                                    ctypes.byref(w), ctypes.byref(h), ctypes.byref(border), ctypes.byref(depth)):
            return None
        if not self._x.XTranslateCoordinates(self._display, window, self._root, 0, 0,
                                             ctypes.byref(rx), ctypes.byref(ry), ctypes.byref(child)):
            return None
        return rx.value + w.value // 2, ry.value + h.value // 2

    def visible_windows(self):
        """Centres of the application windows currently shown on this workspace."""
        clients = self._get(self._root, "_NET_CLIENT_LIST")
        self._watch(clients)
        if self._get(self._root, "_NET_SHOWING_DESKTOP")[:1] == [1]:
            return []
        centres = []
        current = self._get(self._root, "_NET_CURRENT_DESKTOP")[:1]
        app_types = {self._atom("_NET_WM_WINDOW_TYPE_NORMAL"), self._atom("_NET_WM_WINDOW_TYPE_DIALOG")}
        hidden = {self._atom("_NET_WM_STATE_HIDDEN"), self._atom("_NET_WM_STATE_SKIP_TASKBAR")}
        for window in clients:
            types = self._get(window, "_NET_WM_WINDOW_TYPE")
            if types and not app_types.intersection(types):
                continue  # desktop icons, docks, ...
            if hidden.intersection(self._get(window, "_NET_WM_STATE")):
                continue  # minimised
            desk = self._get(window, "_NET_WM_DESKTOP")[:1]
            if desk and current and desk[0] not in (current[0], ALL_DESKTOPS):
                continue  # on another workspace
            centre = self._centre(window)
            if centre:
                centres.append(centre)
        return centres


class DesktopService(QObject):
    """Empty monitors, from the GNOME Shell helper extension when it is there (it sees every window),
    else from X11 (X11 sessions only: in a Wayland session X11 can't see native Wayland windows, so
    every monitor would look empty and the home card would never leave)."""
    emptyChanged = Signal()
    sourceChanged = Signal()
    _from_shell = Signal(object)

    def __init__(self, parent=None, use_shell=True):
        super().__init__(parent)
        self._empty = []
        self._windows = None
        self._shell_ok = False
        self._x11_empty = []
        self._from_shell.connect(self._apply_shell)
        if use_shell:
            names = [s.name() for s in QGuiApplication.screens()]
            self._shell = ShellWindows(names, self._from_shell.emit)
            app = QGuiApplication.instance()
            app.screenAdded.connect(self._names_changed)
            app.screenRemoved.connect(self._names_changed)
        if system.wayland_session():
            print("linux-island: Wayland session: the home card needs the Linux Island helper GNOME extension")
        elif QGuiApplication.platformName() == "xcb":
            try:
                self._windows = _X11Windows()
            except Exception as e:
                print(f"linux-island: window tracking disabled ({e})")
        if self._windows:
            # events arrive in bursts (a dragged window sends dozens): settle briefly, then re-read once
            self._settle = QTimer(self, singleShot=True, interval=60, timeout=self._refresh)
            self._notifier = QSocketNotifier(self._windows.fileno(), QSocketNotifier.Read, self)
            self._notifier.activated.connect(self._on_events)
            self._timer = QTimer(self, interval=5000, timeout=self._refresh)   # safety net only
            self._timer.start()
            self._refresh()

    def _on_events(self, *_):
        if self._windows.drain() and not self._settle.isActive():
            self._settle.start()

    def _refresh(self):
        self._windows.drain()                 # what happened so far is covered by this read
        centres = self._windows.visible_windows()
        if self._windows.drain() and not self._settle.isActive():
            self._settle.start()              # something changed while we were reading: once more
        empty = []
        for screen in QGuiApplication.screens():
            # X11 screen origins are device pixels; Qt reports sizes in logical pixels
            geo, dpr = screen.geometry(), screen.devicePixelRatio()
            x0, y0, x1, y1 = geo.x(), geo.y(), geo.x() + geo.width() * dpr, geo.y() + geo.height() * dpr
            if not any(x0 <= cx < x1 and y0 <= cy < y1 for cx, cy in centres):
                empty.append(screen.name())
        self._x11_empty = empty
        if not self._shell_ok:
            self._set(empty)

    def _set(self, empty):
        if empty != self._empty:
            self._empty = empty
            self.emptyChanged.emit()

    def _names_changed(self, *_):
        self._shell.set_names([s.name() for s in QGuiApplication.screens()])

    def _apply_shell(self, empty):
        ok = empty is not None
        if ok != self._shell_ok:
            self._shell_ok = ok
            self.sourceChanged.emit()
        if ok:
            self._set(sorted(empty))
        else:
            self._set(self._x11_empty)   # extension gone: back to what X11 says (nothing on Wayland)

    @Property(str, notify=sourceChanged)
    def source(self):
        """Where window information comes from: "gnome-extension", "x11" or "none"."""
        return "gnome-extension" if self._shell_ok else "x11" if self._windows else "none"

    @Property("QVariantList", notify=emptyChanged)
    def emptyScreens(self):
        """Names of the monitors with no visible application window."""
        return self._empty
