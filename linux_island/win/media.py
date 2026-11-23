"""Windows now playing: the system media sessions (what the volume flyout shows: Spotify, browsers, Media
Player, VLC, ...), through WinRT's GlobalSystemMediaTransportControlsSessionManager.

The worker thread reads the sessions about once a second (at once after a button press) and hands the same
state dict as the MPRIS version to MediaService, which keeps the position ticking and the controls working.
"""
import datetime
import hashlib
import os
import queue
import tempfile
import threading

from PySide6.QtCore import QUrl

from ..services.media import _EMPTY, MediaService, _accent_for
from ..services.threads import emit, name_this_thread
from . import logic

DEBUG = bool(os.environ.get("LINUX_ISLAND_DEBUG"))
PLAYING, CLOSED = 4, 0
ART_DIR = os.path.join(tempfile.gettempdir(), "linux-island-art")


def wait(operation, timeout=5.0):
    """Result of a WinRT async operation, waited for on this (worker) thread."""
    operation.wait(timeout)
    return operation.get_results()


def init_winrt_thread():
    try:
        from winrt.runtime import MTA, init_apartment
        init_apartment(MTA)
    except Exception:
        pass   # already initialised (or done for us by the runtime)


def _seconds(value):
    if isinstance(value, datetime.timedelta):
        return value.total_seconds()
    try:
        return float(value) / 10_000_000   # 100 ns ticks
    except (TypeError, ValueError):
        return 0.0


def _save_art(session_key, thumbnail):
    """Write the artwork to a temporary file; returns its file:// URL ("" when there is none)."""
    if thumbnail is None:
        return ""
    from winrt.windows.storage.streams import DataReader
    stream = wait(thumbnail.open_read_async())
    size = int(stream.size)
    if not size or size > 8_000_000:
        return ""
    reader = DataReader(stream)
    wait(reader.load_async(size))
    data = bytearray(size)
    reader.read_bytes(data)
    os.makedirs(ART_DIR, exist_ok=True)
    name = hashlib.sha1(session_key.encode() + bytes(data[:4096])).hexdigest()[:16] + ".img"
    path = os.path.join(ART_DIR, name)
    if not os.path.exists(path):
        for old in os.listdir(ART_DIR):   # keep only the current artwork
            try:
                os.remove(os.path.join(ART_DIR, old))
            except OSError:
                pass
        with open(path, "wb") as f:
            f.write(data)
    return QUrl.fromLocalFile(path).toString()


class WinMediaService(MediaService):
    def __init__(self, parent=None):
        self._commands = queue.Queue()
        self._wake = threading.Event()
        self._art_key = None
        self._art_url = ""
        self._manager = None
        super().__init__(parent)   # starts the worker thread (`_run` below)

    # ---- worker thread -------------------------------------------------
    def _run(self):
        name_this_thread("island-media")
        init_winrt_thread()
        try:
            from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as Manager
            self._manager = wait(Manager.request_async())
        except Exception as e:
            print(f"linux-island: media controls disabled ({e})")
            return
        while True:
            try:
                self._do_commands()
                self._refresh_sessions()
            except Exception as e:
                if DEBUG:
                    print(f"media: {e}", flush=True)
            self._wake.wait(1.0)
            self._wake.clear()

    def _sessions(self):
        found = {}
        for session in self._manager.get_sessions():
            try:
                info = session.get_playback_info()
                if int(info.playback_status) == CLOSED:
                    continue
                found[session.source_app_user_model_id] = (session, info)
            except Exception:
                continue
        return found

    def _pick(self, sessions):
        playing = [k for k, (_, info) in sessions.items() if int(info.playback_status) == PLAYING]
        if self._current in playing:
            return self._current
        if playing:
            return playing[0]
        if self._current in sessions:
            return self._current
        current = self._manager.get_current_session()
        if current is not None and current.source_app_user_model_id in sessions:
            return current.source_app_user_model_id
        return next(iter(sessions), "")

    def _refresh_sessions(self):
        sessions = self._sessions()
        pick = self._current = self._pick(sessions)
        if not pick:
            emit(self._state, dict(_EMPTY))
            return
        session, info = sessions[pick]
        props = wait(session.try_get_media_properties_async())
        title = (props.title if props else "") or ""
        artist = (props.artist if props else "") or ""
        playing = int(info.playback_status) == PLAYING
        if not title and not playing:
            emit(self._state, dict(_EMPTY))   # a player with nothing loaded
            return
        key = (pick, title, artist)
        if key != self._art_key:
            self._art_key = key
            try:
                self._art_url = _save_art(pick, props.thumbnail if props else None)
            except Exception as e:
                if DEBUG:
                    print(f"media: artwork: {e}", flush=True)
                self._art_url = ""
            if self._art_url != self._art:
                self._art, self._accent = self._art_url, _accent_for(self._art_url)

        timeline = session.get_timeline_properties()
        start, end = _seconds(timeline.start_time), _seconds(timeline.end_time)
        position = _seconds(timeline.position) - start
        rate = float(info.playback_rate or 1.0)
        updated = timeline.last_updated_time
        if playing and isinstance(updated, datetime.datetime) and updated.year > 2000:
            # Windows gives the position as of `last_updated_time`: carry it forward to now
            now = datetime.datetime.now(updated.tzinfo or datetime.timezone.utc)
            if updated.tzinfo is None:
                now = now.replace(tzinfo=None)
            ahead = (now - updated).total_seconds() * rate
            if 0 <= ahead < 6 * 3600:
                position += ahead
        controls = info.controls
        state = {
            "bus": pick,
            "player": logic.player_name(pick),
            "title": title,
            "artist": artist,
            "art": self._art_url,
            "accent": self._accent,
            "track": f"{pick}\n{title}" if controls.is_playback_position_enabled else "",
            "playing": playing,
            "position": max(0.0, position),
            "length": max(0.0, end - start),
            "rate": rate,
            "next": bool(controls.is_next_enabled),
            "previous": bool(controls.is_previous_enabled),
        }
        if DEBUG:
            print(f"media: {pick} playing={playing} pos={position:.1f}/{end - start:.1f}", flush=True)
        emit(self._state, state)

    def _do_commands(self):
        while True:
            try:
                bus, member, body = self._commands.get_nowait()
            except queue.Empty:
                return
            entry = self._sessions().get(bus)
            if not entry:
                continue
            session = entry[0]
            if member == "PlayPause":
                wait(session.try_toggle_play_pause_async())
            elif member == "Next":
                wait(session.try_skip_next_async())
            elif member == "Previous":
                wait(session.try_skip_previous_async())
            elif member == "SetPosition":
                start = _seconds(session.get_timeline_properties().start_time)
                wait(session.try_change_playback_position_async(int((body[1] / 1e6 + start) * 10_000_000)))

    # ---- main thread ---------------------------------------------------
    def _send(self, member, sig=None, body=()):
        if member == "Seek" or not self._s["bus"]:
            return   # (MPRIS's position probe: Windows always reports the position)
        if DEBUG:
            print(f"media: send {member} -> {self._s['bus']}", flush=True)
        self._commands.put((self._s["bus"], member, body))
        self._wake.set()
