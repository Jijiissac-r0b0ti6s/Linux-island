"""Bluetooth connect / disconnect events (with battery level when the device reports it), via BlueZ."""
import threading
import time

from jeepney import DBusAddress, MessageType, new_method_call
from jeepney.io.blocking import open_dbus_connection
from PySide6.QtCore import Property, QObject, Signal, Slot
from .threads import emit, name_this_thread

DEVICE = "org.bluez.Device1"
BATTERY = "org.bluez.Battery1"


class BluetoothService(QObject):
    # name, connected?, battery percent (-1 when unknown), is an audio device?
    deviceEvent = Signal(str, bool, int, bool)
    devicesChanged = Signal()
    _snapshot = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._devices = []
        self._snapshot.connect(self._apply)
        threading.Thread(target=self._run, daemon=True, name="bluetooth").start()

    def _connected(self, bus):
        msg = new_method_call(
            DBusAddress("/", bus_name="org.bluez", interface="org.freedesktop.DBus.ObjectManager"),
            "GetManagedObjects",
        )
        reply = bus.send_and_get_reply(msg, timeout=3.0)
        if reply.header.message_type != MessageType.method_return:
            return None  # bluetoothd not running
        devices = {}
        for path, interfaces in reply.body[0].items():
            dev = {k: v[1] for k, v in interfaces.get(DEVICE, {}).items()}
            if not dev.get("Connected"):
                continue
            battery = interfaces.get(BATTERY, {}).get("Percentage")
            devices[path] = {
                "name": dev.get("Alias") or dev.get("Name") or "Bluetooth device",
                "battery": int(battery[1]) if battery else -1,
                "audio": str(dev.get("Icon", "")).startswith("audio"),
            }
        return devices

    def _run(self):
        name_this_thread("island-bt")
        bus, known = None, None
        while True:
            try:
                if bus is None:
                    bus = open_dbus_connection("SYSTEM")
                now = self._connected(bus)
            except Exception:
                bus, now = None, None
            if now is not None:
                if known is not None:
                    for path in now.keys() - known.keys():
                        # the battery level usually shows up a moment after the link does
                        time.sleep(2)
                        try:
                            d = (self._connected(bus) or now).get(path, now[path])
                        except Exception:
                            d = now[path]
                        emit(self.deviceEvent, d["name"], True, d["battery"], d["audio"])
                    for path in known.keys() - now.keys():
                        d = known[path]
                        emit(self.deviceEvent, d["name"], False, -1, d["audio"])
                known = now
                emit(self._snapshot, sorted(now.values(), key=lambda d: d["name"]))
            time.sleep(3)

    @Slot(object)
    def _apply(self, devices):
        if devices != self._devices:
            self._devices = devices
            self.devicesChanged.emit()

    @Property("QVariantList", notify=devicesChanged)
    def devices(self):
        """Connected devices as {name, battery (-1 = unknown), audio}."""
        return list(self._devices)
