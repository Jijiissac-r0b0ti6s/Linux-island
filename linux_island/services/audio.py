"""Output volume through wpctl (PipeWire) or pactl (PulseAudio)."""
import re
import shutil
import subprocess
import threading
import time

from PySide6.QtCore import Property, QObject, Signal, Slot
from .pulse_events import PulseEvents
from .threads import name_this_thread


class _Wpctl:
    sink = "@DEFAULT_AUDIO_SINK@"

    def read(self):
        out = subprocess.run(["wpctl", "get-volume", self.sink], capture_output=True, text=True, timeout=2).stdout
        m = re.search(r"Volume:\s*([\d.]+)", out)
        return (float(m.group(1)), "MUTED" in out) if m else None

    def output(self):
        """(description, internal name) of the default output device."""
        out = subprocess.run(["wpctl", "inspect", self.sink], capture_output=True, text=True, timeout=2).stdout
        desc = re.search(r'node\.description = "(.*)"', out)
        name = re.search(r'node\.name = "(.*)"', out)
        return (desc.group(1), name.group(1) if name else "") if desc else None

    def set_volume(self, v):
        return ["wpctl", "set-volume", "-l", "1.0", self.sink, f"{v:.2f}"]

    def set_mute(self, muted):
        return ["wpctl", "set-mute", self.sink, "1" if muted else "0"]


class _Pactl:
    sink = "@DEFAULT_SINK@"

    def read(self):
        vol = subprocess.run(["pactl", "get-sink-volume", self.sink], capture_output=True, text=True, timeout=2).stdout
        mute = subprocess.run(["pactl", "get-sink-mute", self.sink], capture_output=True, text=True, timeout=2).stdout
        m = re.search(r"(\d+)%", vol)
        return (int(m.group(1)) / 100, "yes" in mute) if m else None

    def set_volume(self, v):
        return ["pactl", "set-sink-volume", self.sink, f"{round(v * 100)}%"]

    def set_mute(self, muted):
        return ["pactl", "set-sink-mute", self.sink, "1" if muted else "0"]


class AudioService(QObject):
    volumeChanged = Signal()
    mutedChanged = Signal()
    availableChanged = Signal()
    changed = Signal()  # volume or mute changed after start-up: show the HUD
    outputChanged = Signal(str, bool)  # device name, looks like headphones?
    _polled = Signal(float, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._volume = 0.0
        self._muted = False
        self._ready = False
        self._backend = _Wpctl() if shutil.which("wpctl") else _Pactl() if shutil.which("pactl") else None
        self._polled.connect(self._apply)
        if self._backend:
            threading.Thread(target=self._poll, daemon=True, name="audio-poll").start()

    def _poll(self):
        name_this_thread("island-audio")
        events = None
        if isinstance(self._backend, _Wpctl):
            try:
                events = PulseEvents()   # read only when the sound server says something changed
            except OSError:
                events = None            # no libpulse / pipewire-pulse: poll instead
        output, tick = None, 0
        while True:
            check_output = tick % 4 == 0
            try:
                state = self._backend.read()
                if state:
                    self._polled.emit(*state)
                if check_output and hasattr(self._backend, "output"):
                    now = self._backend.output()
                    if now and output and now != output:
                        desc, name = now
                        headphones = "bluez" in name or any(w in (desc + name).lower() for w in ("head", "ear"))
                        self.outputChanged.emit(desc, headphones)
                    output = now or output
            except (OSError, subprocess.SubprocessError):
                pass
            if events is not None and events.alive:
                # wait for a change (with a slow safety re-read), then let a burst of events settle
                events.changed.wait(30)
                time.sleep(0.03)
                events.changed.clear()
                tick = 0 if events.output_changed.is_set() else 1
                events.output_changed.clear()
            else:
                tick += 1
                time.sleep(0.5)

    @Slot(float, bool)
    def _apply(self, volume, muted):
        first = not self._ready
        self._ready = True
        dirty = False
        if abs(volume - self._volume) > 0.004:
            self._volume = volume
            self.volumeChanged.emit()
            dirty = True
        if muted != self._muted:
            self._muted = muted
            self.mutedChanged.emit()
            dirty = True
        if first:
            self.availableChanged.emit()
        elif dirty:
            self.changed.emit()

    def _run(self, cmd):
        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass

    @Property(bool, notify=availableChanged)
    def available(self):
        return self._ready

    @Property(float, notify=volumeChanged)
    def volume(self):
        return self._volume

    @Property(bool, notify=mutedChanged)
    def muted(self):
        return self._muted

    @Slot(float)
    def setVolume(self, v):
        if not self._backend:
            return
        v = max(0.0, min(1.0, v))
        if self._muted and v > 0:
            self._run(self._backend.set_mute(False))
        self._run(self._backend.set_volume(v))
        self._apply(v, self._muted and v == 0)

    @Slot(float)
    def nudge(self, delta):
        self.setVolume(round(self._volume + delta, 2))

    @Slot()
    def toggleMute(self):
        if not self._backend:
            return
        self._run(self._backend.set_mute(not self._muted))
        self._apply(self._volume, not self._muted)
