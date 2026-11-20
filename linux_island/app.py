"""Entry point: one island window per selected monitor, all sharing the same services."""
import argparse
import json
import ctypes
import ctypes.util
import os
import re
import shlex
import signal
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _preload_xcb_cursor():
    """Qt >= 6.5 needs libxcb-cursor on X11. If the distro package is missing, use a
    copy unpacked into <project>/.libs (see README) so the app still starts."""
    if ctypes.util.find_library("xcb-cursor"):
        return
    for lib in (HERE.parent / ".libs").rglob("libxcb-cursor.so.0"):
        ctypes.CDLL(str(lib), mode=ctypes.RTLD_GLOBAL)
        return


_preload_xcb_cursor()

from PySide6.QtCore import (  # noqa: E402
    QEasingCurve, QFileSystemWatcher, QLockFile, QPropertyAnimation, QRect, QStandardPaths, Qt, QTimer, QUrl, Slot,
)
from PySide6.QtGui import QColor, QGuiApplication, QRegion  # noqa: E402
from PySide6.QtNetwork import QLocalServer, QLocalSocket  # noqa: E402
from PySide6.QtQml import QQmlEngine  # noqa: E402
from PySide6.QtQuick import QQuickView, QQuickWindow  # noqa: E402

from . import config, system  # noqa: E402
from .services import (  # noqa: E402
    AudioService, BatteryService, BluetoothService, BrightnessService, CameraService, DesktopService,
    LockService, MediaService, MicrophoneService,
)  # noqa: E402

DEBUG = bool(os.environ.get("LINUX_ISLAND_DEBUG"))


def _panel_height(screen):
    """Height (logical px) of a desktop panel reserved at the top of `screen`.

    Qt reports no work area on multi-monitor X11, so read the per-monitor work
    areas that GTK-aware window managers (mutter, xfwm, ...) publish on the root window.
    """
    geo, dpr = screen.geometry(), screen.devicePixelRatio()
    fallback = screen.availableGeometry().y() - geo.y()
    if QGuiApplication.platformName() != "xcb":
        return fallback
    try:
        out = subprocess.run(["xprop", "-root", "_GTK_WORKAREAS_D0"], capture_output=True, text=True, timeout=2).stdout
        values = [int(v) for v in re.findall(r"\d+", out.split("=", 1)[1])]
    except (OSError, subprocess.SubprocessError, IndexError):
        return fallback
    for x, y, w, h in zip(*[iter(values)] * 4):
        # X11 screen origins are in device pixels; sizes from Qt are logical
        if geo.x() <= x < geo.x() + geo.width() * dpr and geo.y() <= y < geo.y() + geo.height() * dpr:
            return round((y - geo.y()) / dpr)
    return fallback


class IslandWindow(QQuickView):
    """A transparent, always-on-top strip at the top centre of one screen.

    The strip is larger than the island so the pill has room to grow; an input
    mask that follows the pill keeps the rest of the strip click-through.
    """

    WIDTH = 760
    BELOW_HOME = 210  # room under the home card's centre line for the enlarged card
    MAX_HOME = 0.6    # lowest the home card can sit (the settings slider's end): the window is sized for it

    def __init__(self, engine, screen, top_margin, home_position):
        super().__init__(engine, None)
        self._top_margin = top_margin
        self._home_position = max(0.15, min(self.MAX_HOME, float(home_position)))
        self._home_centre = 0
        self._panel = None      # height of a desktop panel above the island, looked up once per screen change
        self._saver = None      # full-screen SaverWindow for the screensaver / lock, made on first use
        self._screen = screen  # Qt may reassign QWindow.screen() from the geometry, so keep our own
        self.setFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.WindowDoesNotAcceptFocus
            | Qt.Tool
            # X11: skip the window manager so the island can sit over the panel.
            # Wayland needs a layer-shell surface here instead (not implemented yet).
            | Qt.X11BypassWindowManagerHint
        )
        self.setColor(QColor(Qt.transparent))
        self.setResizeMode(QQuickView.SizeRootObjectToView)
        self.setScreen(screen)
        self.place()  # before the native window exists, so it is created on the right monitor
        self.setInitialProperties({"win": self, "screenName": screen.name(), "homeCentre": self._home_centre})
        self.setSource(QUrl.fromLocalFile(str(HERE / "qml" / "Island.qml")))
        for err in self.errors():
            print("linux-island:", err.toString(), file=sys.stderr)
        screen.geometryChanged.connect(lambda *_: self.place(rescan=True))
        screen.availableGeometryChanged.connect(lambda *_: self.place(rescan=True))
        self.place()
        self.show()
        cfg = self.engine().rootContext().contextProperty("cfg") or {}
        if cfg.get("screensaver_minutes") or cfg.get("lock_transition"):
            QTimer.singleShot(4000, self._warm_saver)   # build it now so the first screensaver doesn't stutter

    def set_layout(self, top_margin, home_position):
        self._top_margin = top_margin
        self._home_position = max(0.15, min(self.MAX_HOME, float(home_position)))
        self.place(rescan=False)

    @Slot()
    def openSettings(self):
        open_settings()

    def place(self, rescan=True):
        geo = self._screen.geometry()
        # Start below any desktop panel: GNOME's top bar swallows pointer input,
        # so an island drawn over it could never be hovered or clicked.
        if rescan or self._panel is None:
            self._panel = _panel_height(self._screen)
        top = geo.y() + self._panel + self._top_margin
        self._home_centre = geo.y() + round(geo.height() * self._home_position) - top
        if self.rootObject():
            self.rootObject().setProperty("homeCentre", self._home_centre)
        # always tall enough for the lowest home card, so moving the card never resizes the window
        # (resizing a large transparent window while dragging the setting flickers)
        height = geo.y() + round(geo.height() * self.MAX_HOME) - top + self.BELOW_HOME
        target = QRect(geo.x() + (geo.width() - self.WIDTH) // 2, top, self.WIDTH, height)
        if self.geometry() != target:
            self.setGeometry(target)
        if self._saver:
            self._saver.place(geo, top - geo.y() + self._home_centre)

    def _release_pill(self):
        root = self.rootObject()
        if root:
            root.setProperty("saverHold", False)

    def _make_saver(self):
        if self._saver is None:
            self._saver = SaverWindow(self.engine(), self._screen, self)
            self.place()
        return self._saver

    def _warm_saver(self):
        saver = self._make_saver()
        if not saver.isVisible():
            saver.warm()

    @Slot(bool)
    def setSaver(self, on):
        """The pill became (or stopped being) the clock card: fade the full-screen saver in around it,
        or out again (the card returns to the pill once the fade-out is done)."""
        if on:
            self._make_saver().fade(True)
        elif self._saver:
            self._saver.fade(False)
        else:
            self._release_pill()

    def close_saver(self):
        if self._saver:
            self._saver.hide()
            self._saver.deleteLater()
            self._saver = None

    @Slot(float, float, float, float)
    def setInputRect(self, x, y, w, h):
        rect = QRect(int(x) - 1, int(y) - 1, int(w) + 3, int(h) + 3)
        shape = _X11InputShape.get() if QGuiApplication.platformName() == "xcb" else None
        if shape:
            dpr = self.devicePixelRatio()
            shape.set(int(self.winId()), *(round(v * dpr) for v in rect.getRect()))
        else:
            self.setMask(QRegion(rect))


class SaverWindow(QQuickView):
    """Opaque full-screen black window with the screensaver clock, faded in and out by the compositor.

    Redrawing a full-screen (4K) window every frame is too slow to animate smoothly, so the motion
    happens in the small island window (the pill swoops into the clock card) and this window only
    changes its window opacity around it.
    """

    FADE_DELAY = 500   # the pill has (nearly) landed as the clock card: only the compositor works during the fade
    FADE_IN = 350
    FADE_OUT = 300

    def __init__(self, engine, screen, island):
        super().__init__(engine, None)
        self._island = island
        self.setFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus
                      | Qt.Tool | Qt.X11BypassWindowManagerHint)
        self.setColor(QColor("#000000"))
        self.setCursor(Qt.BlankCursor)
        self.setResizeMode(QQuickView.SizeRootObjectToView)
        self.setScreen(screen)
        self.setInitialProperties({"clockY": 0})
        self.setSource(QUrl.fromLocalFile(str(HERE / "qml" / "Saver.qml")))
        for err in self.errors():
            print("linux-island:", err.toString(), file=sys.stderr)
        self.setOpacity(0.0)
        self._anim = QPropertyAnimation(self, b"opacity", self)
        self._anim.setEasingCurve(QEasingCurve.InOutQuad)
        self._anim.finished.connect(self._faded)
        self._delay = QTimer(self, singleShot=True, timeout=self._start_in)
        self._on = False

    def place(self, geo, clock_y):
        self.setGeometry(geo)
        if self.rootObject():
            self.rootObject().setProperty("clockY", clock_y)

    def warm(self):
        """Map once, invisibly, so the first real fade doesn't stutter. Clicks pass straight through
        meanwhile: an invisible full-screen window would otherwise swallow them."""
        self.setFlag(Qt.WindowTransparentForInput, True)
        self.setOpacity(0.0)
        self.show()
        QTimer.singleShot(400, self._end_warm)

    def _end_warm(self):
        if not self._on:
            self.hide()
            self.setFlag(Qt.WindowTransparentForInput, False)   # the real screensaver takes clicks

    def _details(self, on):
        if self.rootObject():
            self.rootObject().setProperty("details", on)

    def fade(self, on):
        self._on = on
        self._anim.stop()
        if on:
            if self.flags() & Qt.WindowTransparentForInput:   # still warming up
                self.hide()
                self.setFlag(Qt.WindowTransparentForInput, False)
            if not self.isVisible():
                self.setOpacity(0.0)
                self.show()
            self.raise_()
            self._delay.start(self.FADE_DELAY if self.opacity() == 0 else 0)
        else:
            self._delay.stop()
            self._details(False)
            if not self.isVisible() or self.opacity() == 0:
                self._faded()
                return
            self._anim.setDuration(round(self.FADE_OUT * self.opacity()))
            self._anim.setStartValue(self.opacity())
            self._anim.setEndValue(0.0)
            self._anim.start()

    def _start_in(self):
        self.raise_()
        self._anim.setDuration(round(self.FADE_IN * (1 - self.opacity())) or 1)
        self._anim.setStartValue(self.opacity())
        self._anim.setEndValue(1.0)
        self._anim.start()

    def _faded(self):
        if self._on:
            self._details(True)
            return
        self.hide()
        self._island._release_pill()   # the card can swoop back into the pill


class _X11InputShape:
    """Sets only the *input* shape of a window through the XShape extension.

    QWindow.setMask() also clips drawing on X11, which leaves stale pixels behind
    while the pill animates; an input-only shape keeps drawing untouched.
    """

    _instance = None

    class _Rect(ctypes.Structure):
        _fields_ = [("x", ctypes.c_short), ("y", ctypes.c_short), ("w", ctypes.c_ushort), ("h", ctypes.c_ushort)]

    @classmethod
    def get(cls):
        if cls._instance is None:
            try:
                cls._instance = cls()
            except Exception as e:
                print(f"linux-island: XShape unavailable, falling back to window mask ({e})", file=sys.stderr)
                cls._instance = False
        return cls._instance or None

    def __init__(self):
        self._x11 = ctypes.CDLL(ctypes.util.find_library("X11"))
        self._ext = ctypes.CDLL(ctypes.util.find_library("Xext"))
        self._x11.XOpenDisplay.restype = ctypes.c_void_p
        self._x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        self._x11.XFlush.argtypes = [ctypes.c_void_p]
        self._ext.XShapeCombineRectangles.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.POINTER(self._Rect), ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ]
        self._display = self._x11.XOpenDisplay(None)
        if not self._display:
            raise RuntimeError("cannot open X display")

    def set(self, window, x, y, w, h):
        rect = self._Rect(x, y, max(1, w), max(1, h))
        SHAPE_INPUT, SHAPE_SET, UNSORTED = 2, 0, 0
        self._ext.XShapeCombineRectangles(self._display, window, SHAPE_INPUT, 0, 0, ctypes.byref(rect), 1, SHAPE_SET, UNSORTED)
        self._x11.XFlush(self._display)


class _NoPill:
    """Stands in for an island window on monitors without the pill (nothing to give back)."""
    def _release_pill(self):
        pass


class Island:
    def __init__(self, app, cfg):
        self.app = app
        self.cfg = cfg
        self.windows = {}
        self.extra_savers = {}   # screensaver on monitors without the pill (screensaver_screens = "all")
        self.engine = QQmlEngine()
        self.services = {
            "media": MediaService(),
            "audio": AudioService(),
            "brightness": BrightnessService(),
            "battery": BatteryService(),
            "camera": CameraService(),
            "desktop": DesktopService(),
            "microphone": MicrophoneService(),
            "bluetooth": BluetoothService(),
            "lock": LockService(cfg.get("screensaver_minutes", 0)),
        }
        ctx = self.engine.rootContext()
        for name, service in self.services.items():
            ctx.setContextProperty(name, service)
        ctx.setContextProperty("cfg", cfg)
        ctx.setContextProperty("islandDebug", DEBUG)

        # the settings panel writes the config file: apply changes as soon as it is saved
        self._watcher = QFileSystemWatcher()
        self._watch_config()
        self._watcher.fileChanged.connect(self._config_touched)
        self._watcher.directoryChanged.connect(self._config_touched)
        self._reload = QTimer(singleShot=True, interval=150, timeout=self.reload)
        self.services["lock"].changed.connect(self.update_extra_savers)
        QTimer.singleShot(5000, self._warm_extra_savers)

        # hotplug arrives as a burst of signals, some before Qt's screen list is updated: settle first
        self._resync = QTimer(singleShot=True, interval=300, timeout=self.sync)
        app.screenAdded.connect(self._resync.start)
        app.screenRemoved.connect(self._screen_gone)
        app.primaryScreenChanged.connect(self._resync.start)
        self.sync()

    def _watch_config(self):
        config.CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        paths = [str(config.CONFIG_PATH.parent)] + ([str(config.CONFIG_PATH)] if config.CONFIG_PATH.exists() else [])
        missing = [p for p in paths if p not in self._watcher.files() + self._watcher.directories()]
        if missing:
            self._watcher.addPaths(missing)

    def _config_touched(self, *_):
        self._watch_config()   # the file is replaced on save: watch the new one
        self._reload.start()

    def reload(self):
        """Apply a changed config file without restarting."""
        new = config.load()
        if new == self.cfg:
            return
        old, self.cfg = self.cfg, new
        self.engine.rootContext().setContextProperty("cfg", new)
        self.services["lock"].set_screensaver_minutes(new["screensaver_minutes"])
        if (old["top_margin"], old["home_position"]) != (new["top_margin"], new["home_position"]):
            for window in self.windows.values():
                window.set_layout(int(new["top_margin"]), new["home_position"])
        if old["monitors"] != new["monitors"]:
            self.sync()
        self.update_extra_savers()
        if DEBUG:
            print("island: settings applied:", {k: v for k, v in new.items() if old.get(k) != v}, flush=True)

    def saver_active(self):
        lock = self.services["lock"]
        return lock.idle or (self.cfg.get("lock_transition") is not False and (lock.locked or lock.locking))

    def update_extra_savers(self):
        """Fade the other monitors to the black clock too, together with the island's own screensaver."""
        on = self.saver_active() and self.cfg.get("screensaver_screens", "all") == "all"
        for screen in self.app.screens():
            name = screen.name()
            if name in self.windows:
                continue
            saver = self.extra_savers.get(name)
            if on and saver is None:
                saver = self.extra_savers[name] = SaverWindow(self.engine, screen, _NoPill())
            if saver is None:
                continue
            if on:
                geo = screen.geometry()
                saver.place(geo, round(geo.height() * float(self.cfg.get("home_position", 0.36))))
            saver.fade(on)
        for name in list(self.extra_savers):   # monitor unplugged, or the island moved onto it
            if name in self.windows or name not in [s.name() for s in self.app.screens()]:
                saver = self.extra_savers.pop(name)
                saver.hide()
                saver.deleteLater()

    def _warm_extra_savers(self):
        """Build the other monitors' screensaver windows now, so the first one doesn't stutter."""
        if not (self.cfg.get("screensaver_minutes") or self.cfg.get("lock_transition")):
            return
        if self.cfg.get("screensaver_screens", "all") != "all":
            return
        for screen in self.app.screens():
            if screen.name() not in self.windows and screen.name() not in self.extra_savers:
                saver = self.extra_savers[screen.name()] = SaverWindow(self.engine, screen, _NoPill())
                saver.place(screen.geometry(), round(screen.geometry().height() * float(self.cfg.get("home_position", 0.36))))
                saver.warm()

    def _screen_gone(self, screen):
        # hide at once: Qt would otherwise move the orphaned window onto another monitor
        window = self.windows.get(screen.name())
        if window:
            window.close_saver()
            window.hide()
        self._resync.start()

    def status(self):
        """What the island currently sees (`linux-island --status`)."""
        lock = self.services["lock"]
        return {
            "monitors": sorted(self.windows),
            "locked": lock.locked, "locking": lock.locking, "screensaver": lock.idle,
            "screensaver_armed": lock._armed, "screensaver_after_s": lock._saver_ms / 1000,
            "idle_s": round((lock._clock.idle_ms() or 0) / 1000, 1),
            "lock_transition": bool(self.cfg.get("lock_transition")),
            "windows_from": self.services["desktop"].source,
        }

    def wanted(self, screen):
        monitors = self.cfg["monitors"]
        if monitors == "all":
            return True
        if monitors == "primary":
            return screen == self.app.primaryScreen()
        return screen.name() in monitors

    def targets(self):
        """Screens to show the island on: the configured ones, or (when none of them is connected,
        e.g. the external monitor was unplugged) the primary screen until one comes back."""
        screens = {s.name(): s for s in self.app.screens() if self.wanted(s)}
        if not screens and self.app.screens():
            fallback = self.app.primaryScreen() or self.app.screens()[0]
            screens = {fallback.name(): fallback}
        return screens

    def sync(self, *_):
        screens = self.targets()
        for name in list(self.windows):
            if name not in screens:
                window = self.windows.pop(name)
                window.close_saver()
                window.deleteLater()
        for name, screen in screens.items():
            if name not in self.windows:
                self.windows[name] = IslandWindow(
                    self.engine, screen, int(self.cfg["top_margin"]), self.cfg["home_position"])
        if DEBUG:
            print(f"island: showing on {sorted(self.windows)} (wanted {self.cfg['monitors']!r})", flush=True)


FIRST_RUN_DONE = config.CONFIG_PATH.parent / ".welcomed"


def open_settings(welcome=False):
    """Start the settings panel as its own process."""
    try:
        subprocess.Popen(shlex.split(system.launcher()) + ["--settings"] + (["--welcome"] if welcome else []),
                         start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as e:
        print(f"linux-island: cannot open settings ({e})", file=sys.stderr)


def _server_name():
    """Full path of the command socket, next to the single-instance lock (not /tmp, which a
    sandboxed shell may not share)."""
    name = os.environ.get("LINUX_ISLAND_SOCKET") or "linux-island.sock"
    return name if name.startswith("/") else os.path.join(system.runtime_dir(), name)


def _send_to_running(command, reply=False):
    """Hand a command to the running island. False when none is running; with `reply`, its answer."""
    sock = QLocalSocket()
    sock.connectToServer(_server_name())
    if not sock.waitForConnected(500):
        return False
    sock.write(command.encode() + b"\n")
    sock.waitForBytesWritten(500)
    answer = True
    if reply:
        answer = bytes(sock.readAll()) if sock.waitForReadyRead(1500) else b""
        answer = answer.decode(errors="replace").strip() or None
    sock.disconnectFromServer()
    return answer


def _listen(island):
    """Accept commands (`linux-island --lock`) from other invocations."""
    QLocalServer.removeServer(_server_name())   # stale socket from a crash
    server = QLocalServer()
    server.setSocketOptions(QLocalServer.UserAccessOption)

    def on_connection():
        sock = server.nextPendingConnection()

        def read():
            for line in bytes(sock.readAll()).decode(errors="ignore").split():
                if line == "screensaver":
                    island.services["lock"].startSaver()
                if line == "lock":
                    lock = island.services["lock"]
                    lock.lockNow() if island.cfg.get("lock_transition", True) else lock._lock_session()
                if line == "status":
                    sock.write((json.dumps(island.status()) + "\n").encode())
                    sock.flush()
        sock.readyRead.connect(read)
        sock.disconnected.connect(sock.deleteLater)
        if sock.bytesAvailable():
            read()   # the command often arrives together with the connection

    server.newConnection.connect(on_connection)
    server.listen(_server_name())
    return server


def main(argv=None):
    parser = argparse.ArgumentParser(prog="linux-island", description="Dynamic-island style status pill for Linux")
    parser.add_argument("--monitors", help='"all", "primary", or comma-separated output names (e.g. eDP-1,DP-1)')
    parser.add_argument("--save", action="store_true", help="remember --monitors in the config file")
    parser.add_argument("--list-monitors", action="store_true", help="print connected monitors and exit")
    parser.add_argument("--autostart", choices=["on", "off"], help="start with the desktop session, then exit")
    parser.add_argument("--lock-shortcut", choices=["on", "off"],
                        help="GNOME: route the lock shortcut through the island (on) or back to GNOME (off)")
    parser.add_argument("--screensaver", action="store_true", help="start the screensaver now (any input ends it)")
    parser.add_argument("--settings", action="store_true", help="open the settings panel")
    parser.add_argument("--welcome", action="store_true", help=argparse.SUPPRESS)   # first run: greet in the panel
    parser.add_argument("--status", action="store_true", help="show what the running island sees (lock, idle, ...)")
    parser.add_argument("--lock", action="store_true",
                        help="lock the screen; the running island first grows into a full-screen clock")
    args = parser.parse_args(argv)

    if args.autostart:
        system.set_autostart(args.autostart == "on")
        print("start on login:", "on" if system.autostart_enabled() else "off")
        return 0
    if args.lock_shortcut:
        if not system.lock_shortcut_available():
            print("GNOME's gsettings not found: bind a shortcut to `linux-island --lock` in your desktop's settings")
            return 1
        key = system.set_lock_shortcut(args.lock_shortcut == "on")
        print(f"lock shortcut {key}:", "through linux-island" if args.lock_shortcut == "on" else "GNOME's own")
        return 0
    if args.settings:
        from .settings import main as settings_main
        return settings_main(welcome=args.welcome)

    if args.status:
        from PySide6.QtCore import QCoreApplication
        core = QCoreApplication(sys.argv[:1])  # noqa: F841
        answer = _send_to_running("status", reply=True)
        if not answer:
            print("linux-island is not running (or too old to answer --status)", file=sys.stderr)
            return 1
        for key, value in json.loads(answer).items():
            print(f"{key:20} {value}")
        return 0

    if args.screensaver:
        from PySide6.QtCore import QCoreApplication
        core = QCoreApplication(sys.argv[:1])  # noqa: F841
        if not _send_to_running("screensaver"):
            print("linux-island is not running", file=sys.stderr)
            return 1
        return 0

    if args.lock:   # no GUI needed: just tell the running island (fast, for a keyboard shortcut)
        from PySide6.QtCore import QCoreApplication
        core = QCoreApplication(sys.argv[:1])  # noqa: F841
        if not _send_to_running("lock"):
            LockService(start=False)._lock_session()   # no island running: plain lock
        return 0

    signal.signal(signal.SIGINT, signal.SIG_DFL)
    QQuickWindow.setDefaultAlphaBuffer(True)
    app = QGuiApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)

    if args.list_monitors:
        for s in app.screens():
            g = s.geometry()
            primary = "  (primary)" if s == app.primaryScreen() else ""
            print(f"{s.name()}\t{g.width()}x{g.height()} at {g.x()},{g.y()}{primary}")
        return 0

    cfg = config.load()
    if args.monitors:
        cfg["monitors"] = args.monitors if args.monitors in ("all", "primary") else args.monitors.split(",")
        if args.save:
            config.save(cfg)

    lock = QLockFile(QStandardPaths.writableLocation(QStandardPaths.RuntimeLocation) + "/linux-island.lock")
    if not lock.tryLock(0):
        print("linux-island is already running", file=sys.stderr)
        return 1

    if app.platformName().startswith("wayland"):
        print("linux-island: Wayland placement is not implemented yet; run with QT_QPA_PLATFORM=xcb", file=sys.stderr)

    island = Island(app, cfg)  # noqa: F841 - keeps windows and services alive
    server = _listen(island)  # noqa: F841
    if not FIRST_RUN_DONE.exists():
        # first start after installing: open the settings once so monitors and colours can be picked
        try:
            FIRST_RUN_DONE.parent.mkdir(parents=True, exist_ok=True)
            FIRST_RUN_DONE.touch()
        except OSError:
            pass
        QTimer.singleShot(2500, lambda: open_settings(welcome=True))
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
