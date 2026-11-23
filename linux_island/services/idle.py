"""How long the user has been idle (no mouse or keyboard input), in milliseconds.

GNOME dims the laptop panel when the session goes idle and brightens it again on the first
mouse move. Those changes are not the user's doing, so the island uses this to tell them
apart from the brightness keys.
"""
import ctypes
import ctypes.util
import sys

from jeepney import DBusAddress, MessageType, new_method_call
from jeepney.io.blocking import open_dbus_connection

_MUTTER = DBusAddress(
    "/org/gnome/Mutter/IdleMonitor/Core",
    bus_name="org.gnome.Mutter.IdleMonitor",
    interface="org.gnome.Mutter.IdleMonitor",
)


class _XScreenSaverInfo(ctypes.Structure):
    _fields_ = [("window", ctypes.c_ulong), ("state", ctypes.c_int), ("kind", ctypes.c_int),
                ("til_or_since", ctypes.c_ulong), ("idle", ctypes.c_ulong),
                ("eventMask", ctypes.c_ulong)]


class IdleClock:
    def __init__(self):
        self._bus = None
        self._mutter = True
        self._xss = None
        self._display = None

    def _from_mutter(self):
        if not self._mutter:
            return None
        try:
            if self._bus is None:
                self._bus = open_dbus_connection("SESSION")
            reply = self._bus.send_and_get_reply(new_method_call(_MUTTER, "GetIdletime"), timeout=0.5)
            if reply.header.message_type == MessageType.method_return:
                return int(reply.body[0])
            self._mutter = False  # not GNOME: don't ask again
        except Exception:
            self._bus = None
        return None

    def _from_x11(self):
        try:
            if self._xss is None:
                xlib = ctypes.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")
                xss = ctypes.CDLL(ctypes.util.find_library("Xss") or "libXss.so.1")
                xlib.XOpenDisplay.restype = ctypes.c_void_p
                xlib.XOpenDisplay.argtypes = [ctypes.c_char_p]
                xlib.XDefaultRootWindow.restype = ctypes.c_ulong
                xlib.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
                xss.XScreenSaverAllocInfo.restype = ctypes.POINTER(_XScreenSaverInfo)
                xss.XScreenSaverQueryInfo.argtypes = [ctypes.c_void_p, ctypes.c_ulong,
                                                      ctypes.POINTER(_XScreenSaverInfo)]
                self._display = xlib.XOpenDisplay(None)
                if not self._display:
                    raise OSError("no X display")
                self._root = xlib.XDefaultRootWindow(self._display)
                self._info = xss.XScreenSaverAllocInfo()
                self._xss = xss
            if self._xss.XScreenSaverQueryInfo(self._display, self._root, self._info):
                return int(self._info.contents.idle)
        except (OSError, AttributeError):
            self._xss = False
        return None

    def idle_ms(self):
        """Milliseconds since the last input, or None when it can't be told."""
        if sys.platform == "win32":
            from ..win import api
            return api.idle_ms()
        ms = self._from_mutter()
        if ms is None and self._xss is not False:
            ms = self._from_x11()
        return ms
