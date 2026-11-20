"""Settings panel: `linux-island --settings`.

Every change is saved to the config file at once; the running island notices and applies it.
"""
import subprocess
import sys
from pathlib import Path

import os
import shlex

from PySide6.QtCore import Property, QLockFile, QObject, QStandardPaths, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

from . import __version__, config, system

HERE = Path(__file__).resolve().parent

ACCENTS = ["#34c759", "#0a84ff", "#5e5ce6", "#bf5af2", "#ff375f", "#ff9f0a", "#ffd60a", "#64d2ff", "#ffffff"]
PILLS = ["#000000", "#1c1c1e", "#2c2c2e", "#0b1a33", "#1a0b2e", "#062b1d"]


class SettingsBackend(QObject):
    changed = Signal()
    statusChanged = Signal()

    def __init__(self, parent=None, welcome=False):
        super().__init__(parent)
        self._welcome = welcome
        self._cfg = config.load()
        self._running = False
        self._autostart = system.autostart_enabled()
        self._shortcut_ok = system.lock_shortcut_available()
        self._shortcut = system.lock_shortcut_enabled() if self._shortcut_ok else False
        self._status_timer = QTimer(self, interval=2000, timeout=self._poll_status)
        self._status_timer.start()
        self._poll_status()

    # ---- config ------------------------------------------------------------
    @Property("QVariantMap", notify=changed)
    def values(self):
        return dict(self._cfg)

    @Slot(str, "QVariant")
    def set(self, key, value):
        if key not in config.DEFAULTS:
            return
        if isinstance(config.DEFAULTS[key], (int, float)) and not isinstance(config.DEFAULTS[key], bool):
            value = float(value) if isinstance(config.DEFAULTS[key], float) else int(round(float(value)))
        if hasattr(value, "toVariant"):
            value = value.toVariant()
        value = config._valid(key, value)
        if self._cfg.get(key) == value:
            return
        self._cfg[key] = value
        config.save(self._cfg)
        self.changed.emit()

    @Slot()
    def resetAll(self):
        self._cfg = dict(config.DEFAULTS)
        config.save(self._cfg)
        self.changed.emit()

    @Property("QVariantMap", constant=True)
    def defaults(self):
        return dict(config.DEFAULTS)

    @Property("QVariantList", constant=True)
    def features(self):
        return [{"key": k, "title": t, "detail": d} for k, t, d in config.FEATURES]

    @Property("QVariantList", constant=True)
    def accents(self):
        return ACCENTS

    @Property("QVariantList", constant=True)
    def pills(self):
        return PILLS

    @Property("QVariantList", constant=True)
    def monitors(self):
        app = QGuiApplication.instance()
        primary = app.primaryScreen()
        return [{"name": s.name(), "size": f"{s.size().width()} × {s.size().height()}", "primary": s == primary,
                 "laptop": s.name().startswith(("eDP", "LVDS", "DSI"))} for s in app.screens()]

    @Slot(str, bool)
    def setMonitor(self, name, on):
        """Tick / untick one monitor in the "chosen monitors" list."""
        current = self._cfg["monitors"]
        names = [m["name"] for m in self.monitors]
        chosen = list(names if current == "all" else [] if current == "primary" else current)
        if on and name not in chosen:
            chosen.append(name)
        if not on and name in chosen:
            chosen.remove(name)
        self.set("monitors", chosen if chosen else "primary")

    welcomeChanged = Signal()

    @Property(bool, notify=welcomeChanged)
    def welcome(self):
        """Opened by the island's first start (or --welcome): show the welcome card."""
        return self._welcome

    @Slot()
    def showWelcome(self):
        self._welcome = True
        self.welcomeChanged.emit()

    @Slot()
    def dismissWelcome(self):
        self._welcome = False
        self.welcomeChanged.emit()

    helperChanged = Signal()

    @Property(str, notify=helperChanged)
    def helperState(self):
        """The GNOME helper extension: active, off, error, out-of-date, missing, no-gnome."""
        if not hasattr(self, "_helper"):
            self._helper = system.helper_extension_state()
        return self._helper

    @Slot()
    def enableHelper(self):
        self._helper = system.enable_helper_extension()
        self.helperChanged.emit()

    @Property(bool, constant=True)
    def waylandSession(self):
        """The home card can't work here (see DesktopService)."""
        return system.wayland_session()

    @Property(str, constant=True)
    def configPath(self):
        return str(config.CONFIG_PATH)

    @Property(str, constant=True)
    def version(self):
        return __version__

    # ---- desktop integration --------------------------------------------------
    def _get_autostart(self):
        return self._autostart

    def _set_autostart(self, on):
        system.set_autostart(on)
        self._autostart = system.autostart_enabled()
        self.statusChanged.emit()

    autostart = Property(bool, _get_autostart, _set_autostart, notify=statusChanged)

    @Property(bool, notify=statusChanged)
    def lockShortcutAvailable(self):
        return self._shortcut_ok

    def _get_shortcut(self):
        return self._shortcut

    def _set_shortcut(self, on):
        if self._shortcut_ok:
            system.set_lock_shortcut(on)
            self._shortcut = system.lock_shortcut_enabled()
            self.statusChanged.emit()

    lockShortcut = Property(bool, _get_shortcut, _set_shortcut, notify=statusChanged)

    # ---- the island itself ---------------------------------------------------------
    def _poll_status(self):
        from .app import _send_to_running   # lazy: keeps the panel's start-up light
        running = bool(_send_to_running("status", reply=True))
        if running != self._running:
            self._running = running
            self.statusChanged.emit()
        # the helper can be turned on or off elsewhere (the Extensions app) while the panel is open
        self._helper_ticks = getattr(self, "_helper_ticks", 0) + 1
        if hasattr(self, "_helper") and self._helper_ticks % 5 == 0:
            self._refresh_helper()

    def _refresh_helper(self):
        state = system.helper_extension_state()
        if state != self._helper:
            self._helper = state
            self.helperChanged.emit()

    @Property(bool, notify=statusChanged)
    def running(self):
        return self._running

    @Slot()
    def startIsland(self):
        try:
            subprocess.Popen(shlex.split(system.launcher()), start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as e:
            print(f"linux-island: cannot start ({e})", file=sys.stderr)
        QTimer.singleShot(1500, self._poll_status)

    @Slot()
    def previewScreensaver(self):
        from .app import _send_to_running
        _send_to_running("screensaver")


def _server_name():
    return os.path.join(system.runtime_dir(), "linux-island-settings.sock")


def _ask_open_panel_to_show(welcome=False):
    """Another panel is open: bring it to the front. False if it can't be reached."""
    sock = QLocalSocket()
    sock.connectToServer(_server_name())
    if not sock.waitForConnected(500):
        return False
    sock.write(b"welcome\n" if welcome else b"show\n")
    sock.waitForBytesWritten(500)
    sock.disconnectFromServer()
    return True


def _show(window):
    """Bring the panel back even if it was minimised or behind other windows."""
    if window.visibility() in (window.Visibility.Minimized, window.Visibility.Hidden):
        window.showNormal()
    window.show()
    window.raise_()
    window.requestActivate()
    window.alert(0)   # if the desktop refuses to focus it, at least flag it in the dock / overview


def _listen(window, backend):
    QLocalServer.removeServer(_server_name())
    server = QLocalServer()
    server.setSocketOptions(QLocalServer.UserAccessOption)

    def on_connection():
        sock = server.nextPendingConnection()

        def read():
            if b"welcome" in bytes(sock.readAll()):
                backend.showWelcome()
            _show(window)
        sock.readyRead.connect(read)
        sock.disconnected.connect(sock.deleteLater)
        if sock.bytesAvailable():
            read()

    server.newConnection.connect(on_connection)
    server.listen(_server_name())
    return server


def main(welcome=False):
    QQuickStyle.setStyle("Material")
    app = QGuiApplication(sys.argv[:1])
    app.setApplicationName("Linux Island Settings")
    app.setDesktopFileName("linux-island-settings")
    icon = HERE / "data" / "linux-island.svg"
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))

    lock = QLockFile(QStandardPaths.writableLocation(QStandardPaths.RuntimeLocation) + "/linux-island-settings.lock")
    if not lock.tryLock(0):
        # one panel at a time: bring the open one to the front instead
        if _ask_open_panel_to_show(welcome):
            return 0
        print("the settings panel is already open", file=sys.stderr)
        return 1

    import signal
    signal.signal(signal.SIGINT, signal.SIG_DFL)   # Ctrl+C in a terminal closes the panel

    engine = QQmlApplicationEngine()
    # owned by the engine: Qt tears the panel down first and its backend after, never the other way
    # round (that order is what prints "Cannot read property ... of null" on the way out)
    backend = SettingsBackend(engine, welcome=welcome)
    engine.rootContext().setContextProperty("settings", backend)
    engine.load(QUrl.fromLocalFile(str(HERE / "qml" / "Settings.qml")))
    if not engine.rootObjects():
        return 1
    server = _listen(engine.rootObjects()[0], backend)  # later launches bring this window forward
    code = app.exec()
    # tear down the panel before its backend: otherwise every binding complains on the way out
    server.close()
    del server
    del engine
    import gc
    gc.collect()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
