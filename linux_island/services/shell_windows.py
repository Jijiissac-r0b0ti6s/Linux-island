"""Which monitors are empty, from GNOME Shell itself (the Linux Island helper extension).

GNOME Shell sees every window, native Wayland ones included, which the island (running through
XWayland in a Wayland session) cannot. The helper extension answers EmptyMonitors(connectors) and
emits Changed whenever windows open, close, minimise or move. Without it, DesktopService falls back
to watching X11 itself.
"""
import queue
import threading
import time

from jeepney import DBusAddress, MatchRule, MessageType, message_bus, new_method_call
from jeepney.io.blocking import Proxy, open_dbus_connection

from .threads import name_this_thread

UUID = "linux-island@jijiissac-r0b0ti6s.github.io"
HELPER = DBusAddress("/io/github/LinuxIsland/Windows", bus_name="org.gnome.Shell",
                     interface="io.github.LinuxIsland.Windows")
RETRY_S = 10      # extension missing / disabled: look again this often
SAFETY_S = 5      # re-ask now and then even without a Changed signal


class ShellWindows:
    """Runs in a thread; calls `on_result(list_of_empty_connectors)` or `on_result(None)` (unavailable)."""

    def __init__(self, names, on_result):
        self._names = list(names)
        self._on_result = on_result
        self._wake = queue.Queue()
        threading.Thread(target=self._run, daemon=True, name="island-shell").start()

    def set_names(self, names):
        self._names = list(names)
        self._wake.put("names")

    def _ask(self, conn):
        msg = new_method_call(HELPER, "EmptyMonitors", "as", (self._names,))
        reply = conn.send_and_get_reply(msg, timeout=2)
        if reply.header.message_type != MessageType.method_return:
            raise RuntimeError("helper extension not answering")
        return list(reply.body[0])

    def _run(self):
        name_this_thread("island-shell")
        available = True   # report the first failure, then only changes
        while True:
            try:
                conn = open_dbus_connection("SESSION")
                # the bus matches the sender by name; signals then arrive from Shell's unique name
                # (":1.23"), so the local filter must not compare the sender
                Proxy(message_bus, conn).AddMatch(MatchRule(
                    type="signal", sender=HELPER.bus_name, interface=HELPER.interface,
                    member="Changed", path=HELPER.object_path))
                local = MatchRule(type="signal", interface=HELPER.interface, member="Changed",
                                  path=HELPER.object_path)
                with conn.filter(local, bufsize=16) as signals:
                    self._on_result(self._ask(conn))
                    available = True
                    while True:
                        try:
                            conn.recv_until_filtered(signals, timeout=SAFETY_S)
                            time.sleep(0.03)                 # a burst of changes -> one question
                            while signals:
                                signals.popleft()
                        except TimeoutError:
                            pass
                        while not self._wake.empty():
                            self._wake.get_nowait()
                        self._on_result(self._ask(conn))
            except Exception:
                if available:
                    self._on_result(None)
                available = False
                try:
                    conn.close()
                except Exception:
                    pass
                time.sleep(RETRY_S)
