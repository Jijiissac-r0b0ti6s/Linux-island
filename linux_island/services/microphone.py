"""Microphone-in-use indicator: is any ALSA capture stream running?

Sound servers (PipeWire, PulseAudio) only keep the capture device running while
some application is recording, so this works without talking to them.
"""
import glob

from PySide6.QtCore import Property, QObject, QTimer, Signal


def _recording():
    for path in glob.glob("/proc/asound/card*/pcm*c/sub*/status"):
        try:
            with open(path) as f:
                if "RUNNING" in f.read():
                    return True
        except OSError:
            pass
    return False


class MicrophoneService(QObject):
    activeChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._active = False
        self._timer = QTimer(self, interval=1500, timeout=self._refresh)
        self._timer.start()
        self._refresh()

    def _refresh(self):
        active = _recording()
        if active != self._active:
            self._active = active
            self.activeChanged.emit()

    @Property(bool, notify=activeChanged)
    def active(self):
        return self._active
