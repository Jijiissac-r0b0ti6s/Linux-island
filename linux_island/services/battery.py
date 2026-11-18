"""Battery level and charger state from /sys/class/power_supply."""
from pathlib import Path

from PySide6.QtCore import Property, QObject, QTimer, Signal


class BatteryService(QObject):
    percentChanged = Signal()
    chargingChanged = Signal()
    pluggedChanged = Signal()  # charger connected / disconnected after start-up

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bat = next(iter(sorted(Path("/sys/class/power_supply").glob("BAT*"))), None)
        self._percent = 0
        self._charging = False
        if self._bat:
            self._refresh(initial=True)
            self._timer = QTimer(self, interval=3000, timeout=self._refresh)
            self._timer.start()

    def _refresh(self, initial=False):
        try:
            percent = int((self._bat / "capacity").read_text())
            status = (self._bat / "status").read_text().strip()
        except (OSError, ValueError):
            return
        charging = status != "Discharging"
        if percent != self._percent:
            self._percent = percent
            self.percentChanged.emit()
        if charging != self._charging:
            self._charging = charging
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
        return self._charging
