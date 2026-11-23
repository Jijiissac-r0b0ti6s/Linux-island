"""The Windows version, tested on Linux: its decisions (logic.py), and its services driven with stand-ins
for the Win32 / WinRT objects. What only a real Windows computer can show is in WINDOWS-TESTING.md."""
import ctypes
import datetime
import os
import sys
import types
import unittest
from collections import namedtuple
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QGuiApplication  # noqa: E402

APP = QGuiApplication.instance() or QGuiApplication([])

from linux_island.win import logic  # noqa: E402


def load_win_api():
    """Import win/api.py on Linux: every DLL is a stand-in, the ctypes structures are real."""
    sys.modules.pop("linux_island.win.api", None)
    with mock.patch.object(ctypes, "WinDLL", lambda *a, **k: mock.MagicMock(), create=True), \
            mock.patch.object(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE, create=True):
        from linux_island.win import api
    return api


Win = namedtuple("Win", "hwnd pid cls title_len exstyle owner cloaked size monitor")


def window(**kw):
    base = dict(hwnd=1, pid=100, cls="Chrome_WidgetWin_1", title_len=12, exstyle=0, owner=False, cloaked=False,
                size=(1200, 800), monitor=11)
    base.update(kw)
    return Win(**base)


class AppWindowTest(unittest.TestCase):
    def test_an_ordinary_window_counts(self):
        self.assertTrue(logic.is_app_window(window(), own_pid=1))

    def test_windows_that_are_not_apps(self):
        for w in [window(pid=1),                                   # the island itself
                  window(cloaked=True),                            # another virtual desktop, suspended UWP app
                  window(cls="Progman"), window(cls="Shell_TrayWnd"), window(cls="WorkerW"),
                  window(exstyle=logic.WS_EX_TOOLWINDOW),          # tool palette
                  window(exstyle=logic.WS_EX_TRANSPARENT),         # click-through overlay
                  window(owner=True),                              # an owned pop-up
                  window(title_len=0), window(size=(10, 10))]:
            self.assertFalse(logic.is_app_window(w, own_pid=1), w)

    def test_app_window_style_wins_over_tool_window(self):
        self.assertTrue(logic.is_app_window(window(exstyle=logic.WS_EX_TOOLWINDOW | logic.WS_EX_APPWINDOW), 1))

    def test_empty_screens(self):
        screen_of = {11: "A", 22: "B"}
        windows = [window(monitor=11), window(monitor=22, cloaked=True), window(monitor=None)]
        self.assertEqual(logic.empty_screens(windows, screen_of, ["A", "B"], own_pid=1), ["B"])
        self.assertEqual(logic.empty_screens([], screen_of, ["B", "A"], own_pid=1), ["A", "B"])


class ScreenMatchTest(unittest.TestCase):
    screens = [("\\\\.\\DISPLAY1", 0, 0, 1280, 800, 1.5), ("\\\\.\\DISPLAY2", 1920, 0, 2560, 1440, 1.5)]

    def test_by_device_name(self):
        self.assertEqual(logic.match_screen("\\\\.\\DISPLAY2", (0, 0, 1, 1), self.screens), "\\\\.\\DISPLAY2")

    def test_by_top_left_when_qt_uses_other_names(self):
        named = [("BOE panel", 0, 0, 1280, 800, 1.5), ("DELL U2720Q", 1920, 0, 2560, 1440, 1.5)]
        self.assertEqual(logic.match_screen("\\\\.\\DISPLAY9", (1920, 0, 5760, 2160), named), "DELL U2720Q")
        self.assertEqual(logic.match_screen("\\\\.\\DISPLAY9", (0, 0, 1920, 1200), named), "BOE panel")

    def test_by_scaled_top_left(self):
        named = [("A", 0, 0, 1280, 800, 1.5), ("B", 1280, 0, 1280, 800, 1.5)]
        self.assertEqual(logic.match_screen("x", (1920, 0, 3840, 1200), named), "B")

    def test_unknown(self):
        self.assertIsNone(logic.match_screen("x", (5000, 5000, 5100, 5100), [("A", 0, 0, 10, 10, 1.0), ("B", 10, 0, 10, 10, 1.0)]))


class SmallDecisionsTest(unittest.TestCase):
    def test_pnp_code(self):
        self.assertEqual(logic.pnp_code("MONITOR\\BOE0867\\{4d36e96e-e325}\\0001"), "BOE0867")
        self.assertEqual(logic.pnp_code("DISPLAY\\boe0867\\4&2a6e&0&UID8_0"), "BOE0867")
        self.assertEqual(logic.pnp_code(""), "")

    def test_battery_state(self):
        self.assertEqual(logic.battery_state(1, 8, 64), (True, 64, True))      # charging
        self.assertEqual(logic.battery_state(0, 0, 30), (True, 30, False))
        self.assertEqual(logic.battery_state(1, 128, 255), (False, 0, True))   # desktop PC: no battery
        self.assertEqual(logic.battery_state(255, 255, 255)[0], False)          # unknown

    def test_charge_state(self):
        self.assertEqual(logic.charge_state(True, 8, 70), "charging")
        self.assertEqual(logic.charge_state(True, 0, 100), "full")
        self.assertEqual(logic.charge_state(True, 0, 80), "plugged")
        self.assertEqual(logic.charge_state(False, 8, 70), "battery")

    def test_consent_app_names(self):
        self.assertEqual(logic.consent_app_name("C:#Program Files#Google#Chrome#Application#chrome.exe"), "chrome")
        self.assertEqual(logic.consent_app_name("C:#Users#me#AppData#Local#Discord#app-1.0#Discord.exe"), "Discord")
        self.assertEqual(logic.consent_app_name("Microsoft.WindowsCamera_8wekyb3d8bbwe"), "Windows Camera")
        self.assertEqual(logic.consent_app_name("MSTeams_8wekyb3d8bbwe"), "MSTeams")

    def test_in_use(self):
        self.assertTrue(logic.in_use(133_000_000, 0))
        self.assertFalse(logic.in_use(133_000_000, 133_000_100))
        self.assertFalse(logic.in_use(0, 0))

    def test_player_names(self):
        for app_id, name in [("Spotify.exe", "Spotify"), ("Chrome", "Chrome"), ("MSEdge", "Edge"),
                             ("308046B0AF4A39CB", "Firefox"), ("Microsoft.ZuneMusic_8wekyb3d8bbwe!Microsoft.ZuneMusic",
                                                                "Media Player"), ("vlc.exe", "VLC"),
                             ("C:\\Tools\\mpv.exe", "Mpv"), ("", "")]:
            self.assertEqual(logic.player_name(app_id), name, app_id)


class FakeRegistry:
    """Enough of winreg for the ConsentStore scan: nested dicts, values as {name: value}."""
    HKEY_CURRENT_USER, HKEY_LOCAL_MACHINE = "HKCU", "HKLM"

    class Key:
        def __init__(self, node):
            self.node = node

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def __init__(self, tree):
        self.tree = tree

    def OpenKey(self, key, path):
        node = self.tree.get(key) if isinstance(key, str) else key.node
        for part in path.split("\\"):
            if not isinstance(node, dict) or part not in node:
                raise FileNotFoundError(path)
            node = node[part]
        return self.Key(node)

    def EnumKey(self, key, i):
        subkeys = [k for k, v in key.node.items() if isinstance(v, dict)]
        if i >= len(subkeys):
            raise OSError("no more")
        return subkeys[i]

    def QueryValueEx(self, key, name):
        if name not in key.node or isinstance(key.node[name], dict):
            raise FileNotFoundError(name)
        return key.node[name], 11


def consent(tree):
    node = {}
    cur = node
    for part in ["Software", "Microsoft", "Windows", "CurrentVersion", "CapabilityAccessManager", "ConsentStore"]:
        cur[part] = {}
        cur = cur[part]
    cur.update(tree)
    return node


class ConsentStoreTest(unittest.TestCase):
    def setUp(self):
        self.api = load_win_api()
        with mock.patch.dict(sys.modules, {"linux_island.win.api": self.api}):
            sys.modules.pop("linux_island.win.basic", None)
            from linux_island.win import basic
        self.basic = basic

    def test_apps_using_the_camera(self):
        reg = FakeRegistry({"HKCU": consent({"webcam": {
            "Value": "Allow",
            "Microsoft.WindowsCamera_8wekyb3d8bbwe": {"LastUsedTimeStart": 5, "LastUsedTimeStop": 9},   # was used
            "NonPackaged": {
                "C:#Program Files#Zoom#bin#Zoom.exe": {"LastUsedTimeStart": 10, "LastUsedTimeStop": 0},  # in use
                "C:#Tools#old.exe": {"LastUsedTimeStart": 3, "LastUsedTimeStop": 4},
                "C:#Broken#no-values.exe": {},
            }}}), "HKLM": {}})
        self.assertEqual(self.basic.apps_using("webcam", reg), ["Zoom"])
        self.assertEqual(self.basic.apps_using("microphone", reg), [])

    def test_machine_wide_entries_count_too(self):
        reg = FakeRegistry({"HKCU": {}, "HKLM": consent({"microphone": {
            "Microsoft.WindowsSoundRecorder_8wekyb3d8bbwe": {"LastUsedTimeStart": 1, "LastUsedTimeStop": 0}}})})
        self.assertEqual(self.basic.apps_using("microphone", reg), ["Windows Sound Recorder"])

    def test_battery_service_on_a_laptop_and_a_desktop(self):
        with mock.patch.object(self.basic.api, "power_status", return_value=(1, 8, 64)):
            b = self.basic.WinBatteryService()
            self.assertTrue(b.available)
            self.assertEqual((b.percent, b.charging, b.state), (64, True, "charging"))
            plugged = []
            b.pluggedChanged.connect(lambda: plugged.append(1))
            with mock.patch.object(self.basic.api, "power_status", return_value=(0, 0, 63)):
                b._refresh()
            self.assertEqual((b.percent, b.charging, b.state, plugged), (63, False, "battery", [1]))
            b._timer.stop()
        with mock.patch.object(self.basic.api, "power_status", return_value=(1, 128, 255)):
            self.assertFalse(self.basic.WinBatteryService().available)

    def test_lock_service_follows_the_lock_screen(self):
        lock = self.basic.WinLockService(start=False)
        states = iter([False, False, True, True, False])
        sleeps = []

        def fake_sleep(s):
            sleeps.append(s)
            if len(sleeps) >= 5:
                raise SystemExit   # ends the watch loop

        seen = []
        lock._locked_from_bus.connect(lambda v: seen.append(v))
        with mock.patch.object(self.basic.api, "session_locked", side_effect=lambda: next(states)), \
                mock.patch.object(self.basic.time, "sleep", fake_sleep), \
                mock.patch.object(self.basic, "name_this_thread"):
            with self.assertRaises(SystemExit):
                lock._watch()
        self.assertEqual(seen, [False, True, False])

    def test_lock_now_uses_lock_workstation(self):
        lock = self.basic.WinLockService(start=False)
        with mock.patch.object(self.basic.api, "lock_workstation", return_value=True) as lw:
            lock._lock_session()
        lw.assert_called_once()

    def test_desktop_service_reports_empty_monitors(self):
        screen = APP.screens()[0]
        g = screen.geometry()
        Mon = namedtuple("Mon", "handle device rect primary")
        mon = Mon(11, "\\\\.\\DISPLAY1", (g.x(), g.y(), g.x() + g.width(), g.y() + g.height()), True)
        with mock.patch.object(self.basic.api, "hook_window_events", return_value=("proc", [1])), \
                mock.patch.object(self.basic.api, "monitors", return_value=[mon]), \
                mock.patch.object(self.basic.api, "visible_windows", return_value=[window(monitor=11)]):
            d = self.basic.WinDesktopService()
            self.assertEqual(d.emptyScreens, [])
            self.assertEqual(d.source, "windows")
            with mock.patch.object(self.basic.api, "visible_windows", return_value=[window(monitor=11, cloaked=True)]):
                d._refresh()
            self.assertEqual(d.emptyScreens, [screen.name()])
            d._timer.stop()


# ---- media, with stand-ins for the WinRT session objects -------------------------------------------
def session(app="Spotify.exe", status=4, title="Song", artist="Band", position=30.0, end=200.0,
            updated=None, next_ok=True, seek_ok=True):
    controls = types.SimpleNamespace(is_next_enabled=next_ok, is_previous_enabled=True,
                                     is_playback_position_enabled=seek_ok)
    info = types.SimpleNamespace(playback_status=status, playback_rate=1.0, controls=controls)
    timeline = types.SimpleNamespace(start_time=datetime.timedelta(0), end_time=datetime.timedelta(seconds=end),
                                     position=datetime.timedelta(seconds=position),
                                     last_updated_time=updated or datetime.datetime.now(datetime.timezone.utc))
    props = types.SimpleNamespace(title=title, artist=artist, thumbnail=None)
    s = mock.MagicMock()
    s.source_app_user_model_id = app
    s.get_playback_info.return_value = info
    s.get_timeline_properties.return_value = timeline
    s.try_get_media_properties_async.return_value = props
    return s


class WinMediaTest(unittest.TestCase):
    def setUp(self):
        from linux_island.win import media
        self.media = media
        self.patches = [mock.patch.object(media, "wait", lambda op, timeout=5.0: op),
                        mock.patch.object(media.threading, "Thread")]   # no worker thread
        for p in self.patches:
            p.start()
        self.svc = media.WinMediaService()
        self.manager = self.svc._manager = mock.MagicMock()
        self.manager.get_current_session.return_value = None

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_now_playing(self):
        earlier = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=4)
        self.manager.get_sessions.return_value = [session(updated=earlier)]
        self.svc._refresh_sessions()
        self.assertEqual((self.svc.available, self.svc.player, self.svc.title, self.svc.artist),
                         (True, "Spotify", "Song", "Band"))
        self.assertTrue(self.svc.playing)
        self.assertEqual(self.svc.length, 200.0)
        self.assertAlmostEqual(self.svc.position, 34.0, delta=0.5)   # carried forward from last_updated_time
        self.assertTrue(self.svc.canNext)

    def test_prefers_the_session_that_is_playing(self):
        self.manager.get_sessions.return_value = [session("Chrome", status=5, title="Paused video"),
                                                  session("Spotify.exe", title="Playing song")]
        self.svc._refresh_sessions()
        self.assertEqual(self.svc.title, "Playing song")

    def test_nothing_loaded_or_closed(self):
        self.manager.get_sessions.return_value = [session(status=5, title=""), session("x", status=0)]
        self.svc._refresh_sessions()
        self.assertFalse(self.svc.available)

    def test_controls_reach_the_session(self):
        s = session()
        self.manager.get_sessions.return_value = [s]
        self.svc._refresh_sessions()
        self.svc.playPause()
        self.svc.next()
        self.svc.seek(0.5)
        self.svc._do_commands()
        s.try_toggle_play_pause_async.assert_called_once()
        s.try_skip_next_async.assert_called_once()
        s.try_change_playback_position_async.assert_called_once_with(100 * 10_000_000)

    def test_mpris_position_probe_is_ignored(self):
        self.manager.get_sessions.return_value = [session()]
        self.svc._refresh_sessions()
        self.svc._send("Seek", "x", (0,))
        self.assertTrue(self.svc._commands.empty())


class WinBluetoothTest(unittest.TestCase):
    def test_connect_and_disconnect_events(self):
        from linux_island.win import bluetooth
        from linux_island.services import bluetooth as base
        with mock.patch.object(base.threading, "Thread"):
            bt = bluetooth.WinBluetoothService()
        snapshots = iter([{}, {"id1": {"name": "Buds", "battery": 80, "audio": True}}, {}])
        events, rounds = [], []
        bt.deviceEvent.connect(lambda *a: events.append(a))

        def fake_sleep(s):
            rounds.append(s)
            if len(rounds) > 4:
                raise SystemExit

        with mock.patch.object(bt, "_connected", side_effect=lambda bus=None: next(snapshots, {})), \
                mock.patch.object(bluetooth.time, "sleep", fake_sleep), \
                mock.patch.object(bluetooth, "init_winrt_thread"), mock.patch.object(bluetooth, "name_this_thread"):
            with self.assertRaises(SystemExit):
                bt._run()
        self.assertEqual(events, [("Buds", True, 80, True), ("Buds", False, -1, True)])


class WinApiTest(unittest.TestCase):
    def test_structures_match_the_windows_headers(self):
        api = load_win_api()
        w = ctypes.sizeof(ctypes.c_wchar)   # 2 on Windows (4 here): the sizes below are Windows' with w = 2
        self.assertEqual(ctypes.sizeof(api.LASTINPUTINFO), 8)
        self.assertEqual(ctypes.sizeof(api.SYSTEM_POWER_STATUS), 12)
        self.assertEqual(ctypes.sizeof(api.RECT), 16)
        self.assertEqual(ctypes.sizeof(api.MONITORINFOEXW), 40 + 32 * w)
        self.assertEqual(ctypes.sizeof(api.DISPLAY_DEVICEW), 4 + 32 * w + 128 * w + 4 + 128 * w + 128 * w)
        self.assertEqual(ctypes.sizeof(api.PHYSICAL_MONITOR), 8 + 128 * w)
        self.assertEqual(ctypes.sizeof(api.PROCESSENTRY32W), (44 + 260 * w + 7) // 8 * 8)   # x64: 568
        self.assertEqual(api.PROCESSENTRY32W.th32DefaultHeapID.offset, 16)
        self.assertEqual(api.MONITORINFOEXW.szDevice.offset, 40)

    def test_idle_time_wraps_with_the_tick_count(self):
        api = load_win_api()

        def fill(ref):
            ctypes.cast(ref, ctypes.POINTER(api.LASTINPUTINFO)).contents.dwTime = 0xFFFFFF00
            return 1
        api.user32.GetLastInputInfo.side_effect = fill
        api.kernel32.GetTickCount.return_value = 0x100
        self.assertEqual(api.idle_ms(), 0x200)


class PlatformChoiceTest(unittest.TestCase):
    def test_system_helpers_on_windows(self):
        from linux_island import system
        with mock.patch.object(system, "WINDOWS", True), mock.patch.dict(os.environ, {"USERNAME": "Jo Smith"}):
            self.assertEqual(system.socket_name("linux-island.sock"), "linux-island.sock-Jo_Smith")
            self.assertFalse(system.lock_shortcut_available())
            self.assertEqual(system.helper_extension_state(), "no-gnome")
            self.assertFalse(system.wayland_session())
            with mock.patch.object(system.sys, "executable", "C:\\Python\\python.exe"), \
                    mock.patch.object(system.os.path, "isfile", lambda p: p.endswith("pythonw.exe")), \
                    mock.patch.dict(os.environ, {"LINUX_ISLAND_LAUNCHER": ""}):
                args = system.launcher_args()
                self.assertTrue(args[0].endswith("pythonw.exe"), args)
                self.assertEqual(args[1:], ["-m", "linux_island"])
            with mock.patch.dict(os.environ, {"LINUX_ISLAND_LAUNCHER": "C:\\Program Files\\Linux Island\\x.exe"}), \
                    mock.patch.object(system.os.path, "isfile", return_value=True):
                self.assertEqual(system.launcher(), '"C:\\Program Files\\Linux Island\\x.exe"')

    def test_linux_keeps_its_own(self):
        from linux_island import services
        self.assertEqual(services.AudioService.__module__, "linux_island.services.audio")


if __name__ == "__main__":
    unittest.main()


class SameInterfaceTest(unittest.TestCase):
    """The QML talks to the Windows services exactly as to the Linux ones."""

    @staticmethod
    def members(cls):
        meta = cls.staticMetaObject
        props = {meta.property(i).name() for i in range(meta.propertyOffset(), meta.propertyCount())}
        methods = {bytes(meta.method(i).name()).decode() for i in range(meta.methodOffset(), meta.methodCount())}
        return props, {m for m in methods if not m.startswith("_")}

    def test_brightness_and_desktop(self):
        api = load_win_api()
        with mock.patch.dict(sys.modules, {"linux_island.win.api": api}):
            for name in ("linux_island.win.basic", "linux_island.win.brightness"):
                sys.modules.pop(name, None)
            from linux_island.win.basic import WinDesktopService
            from linux_island.win.brightness import WinBrightnessService
        from linux_island.services.brightness import BrightnessService
        from linux_island.services.desktop import DesktopService
        for linux, windows in ((BrightnessService, WinBrightnessService), (DesktopService, WinDesktopService)):
            lp, lm = self.members(linux)
            wp, wm = self.members(windows)
            self.assertEqual(lp, wp, windows.__name__)
            self.assertLessEqual(lm, wm, windows.__name__)
