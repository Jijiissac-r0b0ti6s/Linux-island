"""Now-playing info and transport controls for any MPRIS player (Spotify, browsers, VLC, mpv...)."""
import os
import queue
import threading
import time
import urllib.request

from jeepney import DBusAddress, MatchRule, MessageType, message_bus, new_method_call
from jeepney.io.threading import DBusRouter, Proxy, open_dbus_connection
from PySide6.QtCore import Property, QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QColor, QImage
from .threads import name_this_thread

PREFIX = "org.mpris.MediaPlayer2."
PATH = "/org/mpris/MediaPlayer2"
PLAYER = "org.mpris.MediaPlayer2.Player"
PROPS = "org.freedesktop.DBus.Properties"

DEFAULT_ACCENT = "#34c759"
DEBUG = bool(os.environ.get("LINUX_ISLAND_DEBUG"))

_EMPTY = {
    "bus": "", "player": "", "title": "", "artist": "", "art": "", "track": "",
    "playing": False, "position": 0.0, "length": 0.0, "next": False, "previous": False, "accent": DEFAULT_ACCENT,
    "rate": 1.0,
}


def _accent_for(url):
    """A bright colour that matches the artwork at `url` (the player's own art link)."""
    try:
        if url.startswith("file://"):
            image = QImage(QUrl(url).toLocalFile())
        elif url.startswith(("http://", "https://")):
            with urllib.request.urlopen(url, timeout=3) as reply:
                image = QImage.fromData(reply.read(4_000_000))
        else:
            return DEFAULT_ACCENT
        if image.isNull():
            return DEFAULT_ACCENT
        image = image.scaled(20, 20).convertToFormat(QImage.Format_RGB32)
        r = g = b = total = 0.0
        for y in range(image.height()):
            for x in range(image.width()):
                c = image.pixelColor(x, y)
                weight = c.hsvSaturationF() ** 2 * c.valueF() + 0.001  # colourful pixels dominate
                r, g, b, total = r + c.redF() * weight, g + c.greenF() * weight, b + c.blueF() * weight, total + weight
        hue, sat, _, _ = QColor.fromRgbF(r / total, g / total, b / total).getHsvF()
        if sat < 0.12:
            return "#d6d6dc"  # black-and-white artwork
        return QColor.fromHsvF(max(hue, 0.0), min(0.8, max(0.45, sat)), 0.96).name()
    except Exception:
        return DEFAULT_ACCENT


class MediaService(QObject):
    changed = Signal()
    positionChanged = Signal()
    _state = Signal(object)
    _pos = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._s = dict(_EMPTY)
        self._router = None
        self._current = ""
        self._art = ""
        self._accent = DEFAULT_ACCENT
        # Playback position is extrapolated locally: some players (Firefox) only refresh
        # their reported Position on pause/track change, so polling it would drag the
        # seek bar back to a stale value.
        self._reported = None      # last Position the player reported
        self._base = 0.0           # position (s) at _base_time
        self._base_time = time.monotonic()
        self._seek_guard = 0.0     # ignore reports until this time (a poll may predate our seek)
        # Firefox also withdraws the duration and reports position 0 for a while after a
        # seek or when a track is already playing at start-up; remember what we knew.
        self._key = None           # (bus, title) of the current track
        self._length = 0.0         # last duration the player gave for it
        self._known = True         # False: we never learnt where in the track playback is
        self._probed = None        # track we already asked for its real position
        # repaint the elapsed time while playing, even when the player sends nothing
        self._ticker = QTimer(self, interval=500)
        self._ticker.timeout.connect(lambda: self.positionChanged.emit())
        self._state.connect(self._apply)
        self._pos.connect(self._apply_position)
        threading.Thread(target=self._run, daemon=True, name="mpris").start()

    # ---- worker thread -------------------------------------------------
    def _call(self, dest, iface, member, sig=None, body=()):
        msg = new_method_call(DBusAddress(PATH, bus_name=dest, interface=iface), member, sig, body)
        reply = self._router.send_and_get_reply(msg, timeout=1.5)
        if reply.header.message_type != MessageType.method_return:
            raise RuntimeError(f"{member} failed")
        return reply.body

    def _run(self):
        name_this_thread("island-media")
        try:
            self._router = DBusRouter(open_dbus_connection("SESSION"))
            bus = Proxy(message_bus, self._router)
            names = MatchRule(type="signal", sender="org.freedesktop.DBus", interface="org.freedesktop.DBus",
                              member="NameOwnerChanged", path="/org/freedesktop/DBus")
            names.add_arg_condition(0, PREFIX.rstrip("."), kind="namespace")
            rules = [
                names,
                MatchRule(type="signal", interface=PROPS, member="PropertiesChanged", path=PATH),
                MatchRule(type="signal", interface=PLAYER, member="Seeked", path=PATH),
            ]
            events = queue.Queue()
            self._filters = []
            for rule in rules:
                bus.AddMatch(rule)
                self._filters.append(self._router.filter(rule, queue=events))
        except Exception as e:
            print(f"linux-island: media controls disabled ({e})")
            self._router = None
            return

        self._refresh(bus)
        while True:
            try:
                events.get(timeout=1.0)
                while not events.empty():  # collapse bursts into one refresh
                    events.get_nowait()
                self._refresh(bus)
            except queue.Empty:
                if self._s["playing"]:
                    self._refresh_position()
            except Exception:
                pass

    def _refresh(self, bus):
        players = {}
        for name in bus.ListNames()[0]:
            if not name.startswith(PREFIX):
                continue
            try:
                raw = self._call(name, PROPS, "GetAll", "s", (PLAYER,))[0]
            except Exception:
                continue
            p = {k: v[1] for k, v in raw.items()}
            meta = {k: v[1] for k, v in p.get("Metadata", {}).items()}
            if not meta.get("xesam:title") and p.get("PlaybackStatus") != "Playing":
                continue  # idle player with nothing loaded
            p["Metadata"] = meta
            players[name] = p

        playing = [n for n, p in players.items() if p.get("PlaybackStatus") == "Playing"]
        if self._current in playing:
            pick = self._current
        elif playing:
            pick = playing[0]
        elif self._current in players:
            pick = self._current
        else:
            pick = next(iter(players), "")
        self._current = pick
        if not pick:
            self._state.emit(dict(_EMPTY))
            return

        p, meta = players[pick], players[pick]["Metadata"]
        if DEBUG:
            print(f"media: {pick} status={p.get('PlaybackStatus')} next={p.get('CanGoNext')} "
                  f"previous={p.get('CanGoPrevious')} seek={p.get('CanSeek')} len={meta.get('mpris:length')} pos={p.get('Position')} track={meta.get('mpris:trackid')}", flush=True)
        artist = meta.get("xesam:artist") or ""
        art = str(meta.get("mpris:artUrl") or "")
        if art != self._art:
            self._art, self._accent = art, _accent_for(art)
        self._state.emit({
            "bus": pick,
            "player": pick[len(PREFIX):].split(".")[0].capitalize(),
            "title": str(meta.get("xesam:title") or ""),
            "artist": ", ".join(artist) if isinstance(artist, (list, tuple)) else str(artist),
            "art": art,
            "accent": self._accent,
            "track": str(meta.get("mpris:trackid") or ""),
            "playing": p.get("PlaybackStatus") == "Playing",
            "position": max(0, p.get("Position") or 0) / 1e6,
            "length": max(0, meta.get("mpris:length") or 0) / 1e6,
            "rate": float(p.get("Rate") or 1.0),
            "next": bool(p.get("CanGoNext")),
            "previous": bool(p.get("CanGoPrevious")),
        })

    def _refresh_position(self):
        try:
            value = self._call(self._s["bus"], PROPS, "Get", "ss", (PLAYER, "Position"))[0][1]
            self._pos.emit(max(0, value) / 1e6)
        except Exception:
            pass

    # ---- main thread ---------------------------------------------------
    def _position_now(self):
        elapsed = (time.monotonic() - self._base_time) * self._s["rate"] if self._s["playing"] else 0.0
        position = self._base + elapsed
        return min(position, self._s["length"]) if self._s["length"] > 0 else position

    def _rebase(self, reported, force=False):
        """Restart extrapolation: from the player's value if it is fresh, else from our own estimate."""
        now = time.monotonic()
        fresh = force or (reported != self._reported and now >= self._seek_guard)
        self._base = reported if fresh else self._position_now()
        self._base_time = now
        self._reported = reported

    @Slot(object)
    def _apply(self, state):
        key = (state["bus"], state["title"])
        new_track = key != self._key
        no_info = state["position"] == 0 and state["length"] == 0   # the player is telling us nothing
        if new_track:
            # A track we watched start really is at 0; one already playing when we first
            # look (island just started) is somewhere unknown.
            first_look = self._key is None
            self._key, self._length = key, state["length"]
            self._known = not (first_look and no_info and state["playing"])
        elif state["length"] > 0:
            self._length = state["length"]
        state["length"] = self._length

        rest_changed = any(state[k] != self._s[k] for k in state if k != "position")
        current = self._position_now()   # with the old playing state and rate
        self._base, self._base_time = current, time.monotonic()
        self._s = state
        if new_track:
            self._rebase(state["position"], force=True)
        elif no_info:
            self._base_time = time.monotonic()   # keep our own estimate
        else:
            self._rebase(state["position"])
            self._known = True
        if not self._known and self._probed != key:
            # A zero-length relative seek makes Firefox publish its real position and
            # duration without any audible jump.
            self._probed = key
            QTimer.singleShot(0, lambda: self._send("Seek", "x", (0,)))
        if state["playing"] != self._ticker.isActive():
            self._ticker.start() if state["playing"] else self._ticker.stop()
        if rest_changed:
            self.changed.emit()
        self.positionChanged.emit()

    @Slot(float)
    def _apply_position(self, seconds):
        if seconds == 0 and (not self._known or self._position_now() > 2):
            return  # "no information", not a jump back to the start
        self._rebase(seconds)
        self._known = True
        self.positionChanged.emit()

    def _send(self, member, sig=None, body=()):
        if self._router and self._s["bus"]:
            addr = DBusAddress(PATH, bus_name=self._s["bus"], interface=PLAYER)
            if DEBUG:
                print(f"media: send {member} -> {self._s['bus']}", flush=True)
            try:
                self._router.send(new_method_call(addr, member, sig, body))
            except Exception:
                pass

    available = Property(bool, lambda self: bool(self._s["bus"]), notify=changed)
    player = Property(str, lambda self: self._s["player"], notify=changed)
    title = Property(str, lambda self: self._s["title"], notify=changed)
    artist = Property(str, lambda self: self._s["artist"], notify=changed)
    artUrl = Property(str, lambda self: self._s["art"], notify=changed)
    accent = Property(str, lambda self: self._s["accent"], notify=changed)
    playing = Property(bool, lambda self: self._s["playing"], notify=changed)
    canNext = Property(bool, lambda self: self._s["next"], notify=changed)
    canPrevious = Property(bool, lambda self: self._s["previous"], notify=changed)
    length = Property(float, lambda self: self._s["length"], notify=changed)
    position = Property(float, lambda self: self._position_now(), notify=positionChanged)
    positionKnown = Property(bool, lambda self: self._known, notify=positionChanged)

    @Slot()
    def playPause(self):
        self._send("PlayPause")

    @Slot()
    def next(self):
        self._send("Next")

    @Slot()
    def previous(self):
        self._send("Previous")

    @Slot(float)
    def seek(self, fraction):
        if self._s["length"] > 0 and self._s["track"]:
            target = max(0.0, min(1.0, fraction)) * self._s["length"]
            self._send("SetPosition", "ox", (self._s["track"], int(target * 1e6)))
            self._base, self._base_time = target, time.monotonic()
            self._seek_guard = self._base_time + 1.5
            self._known = True
            self.positionChanged.emit()
