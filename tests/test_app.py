"""CLI, monitor selection and window placement helpers."""
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

APP = QGuiApplication.instance() or QGuiApplication([])

from linux_island import app, system  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def screen(name, x=0, y=0, w=1920, h=1080, dpr=1.0, avail_y=0):  # noqa: E302
    s = mock.Mock()
    s.name.return_value = name
    s.geometry.return_value = QRect(x, y, w, h)
    s.availableGeometry.return_value = QRect(x, avail_y, w, h - avail_y)
    s.devicePixelRatio.return_value = dpr
    return s


class MonitorSelectionTest(unittest.TestCase):
    def island(self, monitors, primary=None):
        fake = mock.Mock(spec=app.Island)
        fake.cfg = {"monitors": monitors}
        fake.app = mock.Mock(**{"primaryScreen.return_value": primary})
        return fake

    def test_all(self):
        self.assertTrue(app.Island.wanted(self.island("all"), screen("HDMI-1")))

    def test_named_list(self):
        isl = self.island(["DP-1"])
        self.assertTrue(app.Island.wanted(isl, screen("DP-1")))
        self.assertFalse(app.Island.wanted(isl, screen("eDP-1")))

    def test_primary(self):
        p = screen("DP-1")
        isl = self.island("primary", primary=p)
        self.assertTrue(app.Island.wanted(isl, p))
        self.assertFalse(app.Island.wanted(isl, screen("eDP-1")))


class MonitorFallbackTest(unittest.TestCase):
    """Chosen monitor unplugged: show on the primary screen; plugged back: move back."""
    def make(self, monitors, screens, primary):
        island = mock.Mock(spec=app.Island)
        island.cfg = {"monitors": monitors, "top_margin": 2, "home_position": 0.36}
        island.engine = mock.Mock()
        island.app = mock.Mock()
        island.app.screens.return_value = screens
        island.app.primaryScreen.return_value = primary
        island.wanted = lambda s: app.Island.wanted(island, s)
        island.targets = lambda: app.Island.targets(island)
        island.windows = {}
        return island

    def test_targets(self):
        edp, dp = screen("eDP-1"), screen("DP-1")
        both = self.make(["DP-1"], [edp, dp], edp)
        self.assertEqual(list(app.Island.targets(both)), ["DP-1"])
        alone = self.make(["DP-1"], [edp], edp)
        self.assertEqual(list(app.Island.targets(alone)), ["eDP-1"])   # fallback
        self.assertEqual(sorted(app.Island.targets(self.make("all", [edp, dp], edp))), ["DP-1", "eDP-1"])
        self.assertEqual(app.Island.targets(self.make(["DP-1"], [], None)), {})

    def test_unplug_and_replug(self):
        edp, dp = screen("eDP-1"), screen("DP-1")
        island = self.make(["DP-1"], [edp, dp], edp)
        made = []
        with mock.patch.object(app, "IslandWindow", side_effect=lambda e, s, *a: made.append(mock.Mock(name=s.name())) or made[-1]):
            app.Island.sync(island)
            self.assertEqual(list(island.windows), ["DP-1"])
            dp_window = island.windows["DP-1"]
            island.app.screens.return_value = [edp]                 # unplugged
            app.Island.sync(island)
            self.assertEqual(list(island.windows), ["eDP-1"])
            dp_window.deleteLater.assert_called_once()
            dp_window.close_saver.assert_called_once()
            edp_window = island.windows["eDP-1"]
            island.app.screens.return_value = [edp, dp]             # plugged back
            app.Island.sync(island)
            self.assertEqual(list(island.windows), ["DP-1"])
            edp_window.deleteLater.assert_called_once()

    def test_unplugged_window_hidden_at_once(self):
        island = self.make(["DP-1"], [], None)
        win = mock.Mock()
        island.windows = {"DP-1": win}
        island._resync = mock.Mock()
        app.Island._screen_gone(island, screen("DP-1"))
        win.hide.assert_called_once()
        island._resync.start.assert_called_once()


class ExtraSaversTest(unittest.TestCase):
    """screensaver_screens: monitors without the pill fade to the black clock too ("all"), or stay ("island")."""
    def make(self, mode, idle=True):
        edp, dp = screen("eDP-1", h=1200), screen("DP-1")
        island = mock.Mock(spec=app.Island)
        island.cfg = {"screensaver_screens": mode, "lock_transition": True, "home_position": 0.36}
        island.app = mock.Mock(**{"screens.return_value": [edp, dp]})
        island.windows = {"DP-1": mock.Mock()}          # the pill is on DP-1 only
        island.extra_savers = {}
        island.engine = mock.Mock()
        island.services = {"lock": mock.Mock(idle=idle, locked=False, locking=False)}
        island.saver_active = lambda: app.Island.saver_active(island)
        return island

    def test_all_monitors(self):
        island = self.make("all")
        with mock.patch.object(app, "SaverWindow") as saver_cls:
            app.Island.update_extra_savers(island)
            self.assertEqual(list(island.extra_savers), ["eDP-1"])   # only the monitor without the pill
            saver = island.extra_savers["eDP-1"]
            saver.fade.assert_called_with(True)
            saver.place.assert_called_once()
            island.services["lock"].idle = False                   # mouse moved
            app.Island.update_extra_savers(island)
            saver.fade.assert_called_with(False)
            self.assertEqual(saver_cls.call_count, 1)              # reused, not rebuilt

    def test_pill_monitors_only(self):
        island = self.make("island")
        with mock.patch.object(app, "SaverWindow") as saver_cls:
            app.Island.update_extra_savers(island)
            saver_cls.assert_not_called()

    def test_lock_also_fades_other_monitors(self):
        island = self.make("all", idle=False)
        island.services["lock"].locking = True
        with mock.patch.object(app, "SaverWindow"):
            app.Island.update_extra_savers(island)
            island.extra_savers["eDP-1"].fade.assert_called_with(True)

    def test_dropped_when_the_pill_moves_there(self):
        island = self.make("all")
        with mock.patch.object(app, "SaverWindow"):
            app.Island.update_extra_savers(island)
            saver = island.extra_savers["eDP-1"]
            island.windows["eDP-1"] = mock.Mock()                  # the island now shows there too
            app.Island.update_extra_savers(island)
            self.assertEqual(island.extra_savers, {})
            saver.deleteLater.assert_called_once()


class PanelHeightTest(unittest.TestCase):
    XPROP = "_GTK_WORKAREAS_D0(CARDINAL) = 0, 0, 1920, 1080, 1920, 64, 3840, 2336\n"

    def run_with(self, scr, out):
        with mock.patch.object(app.QGuiApplication, "platformName", return_value="xcb"), \
             mock.patch("subprocess.run", return_value=mock.Mock(stdout=out)):
            return app._panel_height(scr)

    def test_hidpi_laptop_panel(self):
        # second monitor at x=1920 device px, scale 2: a 64 device-px bar is 32 logical px
        self.assertEqual(self.run_with(screen("eDP-1", x=1920, w=1920, h=1200, dpr=2.0), self.XPROP), 32)

    def test_monitor_without_panel(self):
        self.assertEqual(self.run_with(screen("DP-1"), self.XPROP), 0)

    def test_falls_back_without_xprop(self):
        with mock.patch.object(app.QGuiApplication, "platformName", return_value="xcb"), \
             mock.patch("subprocess.run", side_effect=OSError):
            self.assertEqual(app._panel_height(screen("DP-1", avail_y=27)), 27)


class AutostartTest(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        self.user = tmp / "autostart" / "linux-island.desktop"
        self.system_file = tmp / "etc" / "linux-island.desktop"
        self.patches = [mock.patch.object(system, "AUTOSTART", self.user),
                        mock.patch.object(system, "SYSTEM_AUTOSTART", self.system_file)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_on_and_off_without_package(self):
        self.assertFalse(system.autostart_enabled())
        system.set_autostart(True)
        self.assertIn("-m linux_island", self.user.read_text())
        self.assertTrue(system.autostart_enabled())
        system.set_autostart(False)
        self.assertFalse(self.user.exists())
        self.assertFalse(system.autostart_enabled())

    def test_with_the_packages_system_entry(self):
        self.system_file.parent.mkdir(parents=True)
        self.system_file.write_text("[Desktop Entry]\nExec=linux-island\n")
        self.assertTrue(system.autostart_enabled())        # on by default once installed
        system.set_autostart(False)
        self.assertIn("Hidden=true", self.user.read_text())  # a per-user override
        self.assertFalse(system.autostart_enabled())
        system.set_autostart(True)
        self.assertFalse(self.user.exists())               # back to the system entry
        self.assertTrue(system.autostart_enabled())


class LockCommandTest(unittest.TestCase):
    """`linux-island --lock` hands the command to the running island instead of locking directly."""
    def setUp(self):
        self.name = os.path.join(system.runtime_dir(), f"linux-island-test-{os.getpid()}.sock")
        self.patch = mock.patch.object(app, "_server_name", return_value=self.name)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()

    def pump(self, ms=300):
        import time
        end = time.monotonic() + ms / 1000
        while time.monotonic() < end:
            APP.processEvents()

    def test_no_island_running(self):
        self.assertFalse(app._send_to_running("lock"))

    def test_running_island_animates_then_locks(self):
        island = mock.Mock(cfg={"lock_transition": True}, services={"lock": mock.Mock()})
        server = app._listen(island)  # noqa: F841
        import threading
        result = []
        t = threading.Thread(target=lambda: result.append(app._send_to_running("lock")))
        t.start()
        while t.is_alive():
            self.pump(20)
        self.pump(200)
        self.assertEqual(result, [True])
        island.services["lock"].lockNow.assert_called_once()

    def test_status_answers_another_process(self):
        island = mock.Mock(cfg={}, services={"lock": mock.Mock()})
        island.status.return_value = {"locked": False, "screensaver_armed": True, "idle_s": 12.0}
        server = app._listen(island)  # noqa: F841
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen", LINUX_ISLAND_SOCKET=self.name)
        proc = subprocess.Popen([sys.executable, "-m", "linux_island", "--status"], cwd=ROOT, env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        import time
        end = time.monotonic() + 20
        while proc.poll() is None and time.monotonic() < end:
            self.pump(20)
        out, err = proc.communicate(timeout=5)
        self.assertEqual(proc.returncode, 0, err)
        self.assertIn("screensaver_armed    True", out)
        self.assertIn("idle_s               12.0", out)

    def test_transition_off_locks_straight_away(self):
        island = mock.Mock(cfg={"lock_transition": False}, services={"lock": mock.Mock()})
        server = app._listen(island)  # noqa: F841
        import threading
        t = threading.Thread(target=lambda: app._send_to_running("lock"))
        t.start()
        while t.is_alive():
            self.pump(20)
        self.pump(200)
        island.services["lock"]._lock_session.assert_called_once()
        island.services["lock"].lockNow.assert_not_called()


class SettingsHandoffTest(unittest.TestCase):
    """A second `linux-island --settings` brings the open panel forward (and shows the welcome)."""
    def test_second_launch_reaches_the_open_panel(self):
        import threading
        from linux_island import settings as S
        name = os.path.join(system.runtime_dir(), f"linux-island-settings-test-{os.getpid()}.sock")
        window, backend = mock.Mock(), mock.Mock()
        with mock.patch.object(S, "_server_name", return_value=name), mock.patch.object(S, "_show") as show:
            server = S._listen(window, backend)  # noqa: F841
            for welcome in (False, True):
                result = []
                t = threading.Thread(target=lambda: result.append(S._ask_open_panel_to_show(welcome)))
                t.start()
                end = time.monotonic() + 3
                while (t.is_alive() or show.call_count < (2 if welcome else 1)) and time.monotonic() < end:
                    APP.processEvents()
                self.assertEqual(result, [True])
            self.assertEqual(show.call_count, 2)
            backend.showWelcome.assert_called_once()

    def test_sockets_live_next_to_the_locks(self):
        from linux_island import settings as S
        self.assertTrue(app._server_name().startswith(system.runtime_dir()))
        self.assertTrue(S._server_name().startswith(system.runtime_dir()))


class LockShortcutTest(unittest.TestCase):
    """The lock shortcut against a fake gsettings store (the real desktop settings are not touched)."""
    def setUp(self):
        self.store = {(system.KEYS, "custom-keybindings"): "@as []", (system.KEYS, "screensaver"): "['<Control><Alt>l']"}

        def fake(*args):
            op, schema, key = args[0], args[1], args[2]
            if op == "get":
                return self.store.get((schema, key), "''")
            if op == "set":
                self.store[(schema, key)] = args[3]
            if op == "reset":
                self.store.pop((schema, key), None)
            return ""
        self.patch = mock.patch.object(system, "_gsettings", side_effect=fake)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()

    def test_on_moves_the_key_to_the_island_and_off_restores(self):
        entry = f"{system.KEYS}.custom-keybinding:{system.SHORTCUT}"
        self.assertEqual(system.set_lock_shortcut(True), "<Control><Alt>l")
        self.assertTrue(system.lock_shortcut_enabled())
        self.assertEqual(self.store[(system.KEYS, "screensaver")], "[]")
        self.assertEqual(self.store[(entry, "binding")], "<Control><Alt>l")
        self.assertIn("--lock", self.store[(entry, "command")])
        system.set_lock_shortcut(True)   # twice: still one entry, same key
        self.assertEqual(self.store[(system.KEYS, "custom-keybindings")], str([system.SHORTCUT]))
        system.set_lock_shortcut(False)
        self.assertFalse(system.lock_shortcut_enabled())
        self.assertEqual(self.store[(system.KEYS, "screensaver")], "['<Control><Alt>l']")

    def test_off_when_never_on_changes_nothing(self):
        before = dict(self.store)
        system.set_lock_shortcut(False)
        self.assertEqual(self.store, before)

    def test_launcher_in_development(self):
        self.assertIn("-m linux_island", system.launcher())


class HelperExtensionTest(unittest.TestCase):
    """Turning the GNOME helper on before GNOME has loaded it (just installed)."""
    def setUp(self):
        self.store = {"enabled-extensions": "['tilingshell@ferrarodomenico.com', 'dash2dock-lite@icedman.github.com']"}

        def fake(op, schema, key, *value):
            if op == "get":
                return self.store.get(key, "@as []")
            if op == "set":
                self.store[key] = value[0]
            return ""
        tmp = Path(tempfile.mkdtemp())
        (tmp / "gnome-shell" / "extensions" / system.EXTENSION_UUID).mkdir(parents=True)
        self.patches = [mock.patch.object(system, "_gsettings", side_effect=fake),
                        mock.patch.dict(os.environ, {"XDG_DATA_HOME": str(tmp)})]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def shell(self, info=None, enable_works=False):
        def call(method, *args):
            if method == "GetExtensionInfo":
                return info if info is not None else {}
            if method == "EnableExtension":
                if not enable_works:
                    raise RuntimeError("No extension with that uuid")
                return True
        return mock.patch.object(system, "_shell_extensions_call", side_effect=call)

    def test_not_loaded_yet_then_turned_on_for_next_login(self):
        with self.shell():
            self.assertEqual(system.helper_extension_state(), "missing")
            self.assertEqual(system.enable_helper_extension(), "pending")      # the panel now says so
        saved = self.store["enabled-extensions"]
        self.assertIn(system.EXTENSION_UUID, saved)
        self.assertIn("tilingshell@ferrarodomenico.com", saved)            # the user's own ones stay
        self.assertIn("dash2dock-lite@icedman.github.com", saved)
        with self.shell():
            system.enable_helper_extension()                                # clicking twice adds it once
        self.assertEqual(self.store["enabled-extensions"].count(system.EXTENSION_UUID), 1)

    def test_states_gnome_reports(self):
        with self.shell(info={"state": ("d", 1.0)}):
            self.assertEqual(system.helper_extension_state(), "active")
        with self.shell(info={"state": ("d", 2.0)}):
            self.assertEqual(system.helper_extension_state(), "off")
        with self.shell(info={"state": ("d", 3.0)}):
            self.assertEqual(system.helper_extension_state(), "error")

    def test_not_installed(self):
        with self.shell(), mock.patch.dict(os.environ, {"XDG_DATA_HOME": tempfile.mkdtemp()}), \
             mock.patch.object(system.os.path, "isdir", return_value=False):
            self.assertEqual(system.helper_extension_state(), "not-installed")

    def test_no_gnome(self):
        with mock.patch.object(system, "_shell_extensions_call", side_effect=OSError("no bus")):
            self.assertEqual(system.helper_extension_state(), "no-gnome")


class CliTest(unittest.TestCase):
    def run_cli(self, *args):
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        return subprocess.run([sys.executable, "-m", "linux_island", *args], cwd=ROOT, env=env,
                              capture_output=True, text=True, timeout=30)

    @unittest.skipUnless(os.environ.get("DISPLAY"), "needs an X display")
    def test_list_monitors(self):
        env = dict(os.environ, QT_QPA_PLATFORM="xcb")
        r = subprocess.run([sys.executable, "-m", "linux_island", "--list-monitors"], cwd=ROOT, env=env,
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout, r"\S+\t\d+x\d+ at -?\d+,-?\d+")

    def test_help(self):
        r = self.run_cli("--help")
        self.assertEqual(r.returncode, 0)
        for flag in ("--monitors", "--save", "--list-monitors", "--autostart", "--lock", "--lock-shortcut", "--status", "--settings"):
            self.assertIn(flag, r.stdout)

    def test_bad_autostart_value(self):
        self.assertNotEqual(self.run_cli("--autostart", "maybe").returncode, 0)


if __name__ == "__main__":
    unittest.main()
