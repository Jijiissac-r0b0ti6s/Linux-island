"""Battery level and charger state from /sys/class/power_supply.

"Plugged in" comes from the charger itself (the Mains supply's `online`), not from the battery's status:
at a full charge (or a charge limit) many laptops let the battery status wander between "Full",
"Not charging" and a brief "Discharging" while the charger stays connected, which would pop the
charger message up with nothing touched.
"""
from pathlib import Path

from PySide6.QtCore import Property, QObject, QTimer, Signal

SUPPLIES = Path("/sys/class/power_supply")


def _read_text(path):
    return path.read_text().strip()


class BatteryService(QObject):
    percentChanged = Signal()
    chargingChanged = Signal()
    stateChanged = Signal()
    pluggedChanged = Signal()  # charger connected / disconnected after start-up

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bat = self._find()
        self._chargers = self._find_chargers()
        self._percent = 0
        self._charging = False     # the charger is connected
        self._state = "battery"    # "charging", "full", "plugged" (connected, not charging) or "battery"
        if self._bat:
            self._refresh(initial=True)
            self._timer = QTimer(self, interval=3000, timeout=self._refresh)
            self._timer.start()

    def _find(self):
        return next(iter(sorted(SUPPLIES.glob("BAT*"))), None)

    def _find_chargers(self):
        """The AC adapter (type Mains); USB-C supplies only when there is no Mains one."""
        mains, usb = [], []
        for supply in sorted(SUPPLIES.glob("*")):
            try:
                kind = _read_text(supply / "type")
            except OSError:
                continue
            if (supply / "online").exists():
                (mains if kind == "Mains" else usb if kind.startswith("USB") else []).append(supply)
        return mains or usb

    def _read(self):
        """(percent, charger connected, state)."""
        percent = int(_read_text(self._bat / "capacity"))
        status = _read_text(self._bat / "status")
        if self._chargers:
            plugged = any(_read_text(c / "online") == "1" for c in self._chargers)
        else:
            plugged = status != "Discharging"
        if not plugged:
            state = "battery"
        elif status == "Charging":
            state = "charging"
        elif status == "Full" or percent >= 100:
            state = "full"
        else:
            state = "plugged"
        return percent, plugged, state

    def _refresh(self, initial=False):
        try:
            percent, plugged, state = self._read()
        except (OSError, ValueError):
            return
        if percent != self._percent:
            self._percent = percent
            self.percentChanged.emit()
        if state != self._state:
            self._state = state
            self.stateChanged.emit()
        if plugged != self._charging:
            self._charging = plugged
            self.chargingChanged.emit()
            if not initial:
                self.pluggedChanged.emit()

    @Property(bool, constant=True)
    def available(self):
        return self._bat is not None

    @Property(int, notify=percentChanged)
    def percent(self):
        return self._percent

    @Property(bool, notify=chargingChanged)
    def charging(self):
        """The charger is connected (the bolt shows, green)."""
        return self._charging

    @Property(str, notify=stateChanged)
    def state(self):
        return self._state
