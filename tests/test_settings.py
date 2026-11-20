"""Config validation, the settings panel's backend, and live reload in the island."""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QUrl  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402

APP = QGuiApplication.instance() or QGuiApplication([])

from linux_island import config, settings  # noqa: E402


def wait(ms):
    end = time.monotonic() + ms / 1000
    while time.monotonic() < end:
        APP.processEvents()
        time.sleep(0.005)


class TempConfig(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "linux-island" / "config.json"
        self.patch = mock.patch.object(config, "CONFIG_PATH", self.path)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()

    def written(self):
        return json.loads(self.path.read_text())


class ConfigTest(TempConfig):
    def test_bad_values_fall_back_to_defaults(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text(json.dumps({"show_media": "yes", "hud_timeout_ms": -5, "accent_color": "green",
                                         "monitors": 3, "pill_color": "#123456", "unknown": 1}))
        cfg = config.load()
        self.assertTrue(cfg["show_media"])
        self.assertEqual(cfg["hud_timeout_ms"], config.DEFAULTS["hud_timeout_ms"])
        self.assertEqual(cfg["accent_color"], config.DEFAULTS["accent_color"])
        self.assertEqual(cfg["monitors"], "all")
        self.assertEqual(cfg["pill_color"], "#123456")
        self.assertNotIn("unknown", cfg)

    def test_save_writes_only_changes_and_is_atomic(self):
        cfg = dict(config.DEFAULTS, theme="classic", monitors=["DP-1"])
        config.save(cfg)
        self.assertEqual(self.written(), {"theme": "classic", "monitors": ["DP-1"]})
        self.assertFalse(self.path.with_suffix(".json.tmp").exists())
        self.assertEqual(config.load()["theme"], "classic")

    def test_every_feature_has_a_default(self):
        for key, title, detail in config.FEATURES:
            self.assertIn(key, config.DEFAULTS)
            self.assertIsInstance(config.DEFAULTS[key], bool)


class BackendTest(TempConfig):
    def setUp(self):
        super().setUp()
        self.p2 = mock.patch("linux_island.app._send_to_running", return_value=False)
        self.p2.start()
        self.b = settings.SettingsBackend()

    def tearDown(self):
        self.p2.stop()
        super().tearDown()

    def test_set_saves_at_once(self):
        self.b.set("accent_color", "#0a84ff")
        self.b.set("popup_volume", False)
        self.b.set("hud_timeout_ms", 2399.7)          # sliders hand over floats
        self.assertEqual(self.written(), {"accent_color": "#0a84ff", "popup_volume": False, "hud_timeout_ms": 2400})
        self.assertEqual(self.b.values["accent_color"], "#0a84ff")

    def test_invalid_values_are_refused(self):
        self.b.set("accent_color", "blue")
        self.b.set("nonsense", 1)
        self.assertFalse(self.path.exists())

    def test_monitor_ticks(self):
        names = [m["name"] for m in self.b.monitors]
        self.b.set("monitors", [])
        self.b.setMonitor(names[0], True)
        self.assertEqual(self.b.values["monitors"], [names[0]])
        self.b.setMonitor(names[0], False)
        self.assertEqual(self.b.values["monitors"], "primary")   # never "no monitor at all"

    def test_reset(self):
        self.b.set("theme", "classic")
        self.b.resetAll()
        self.assertEqual(self.written(), {})
        self.assertEqual(self.b.values["theme"], "vivid")

    def test_lists_for_the_panel(self):
        self.assertEqual(len(self.b.features), len(config.FEATURES))
        self.assertIn("#34c759", self.b.accents)
        self.assertTrue(self.b.monitors)


class PanelTest(TempConfig):
    def test_settings_qml_loads_without_warnings(self):
        with mock.patch("linux_island.app._send_to_running", return_value=False):
            backend = settings.SettingsBackend()
            engine = QQmlApplicationEngine()
            warnings = []
            engine.warnings.connect(lambda ws: warnings.extend(w.toString() for w in ws))
            engine.rootContext().setContextProperty("settings", backend)
            engine.load(QUrl.fromLocalFile(str(settings.HERE / "qml" / "Settings.qml")))
            self.assertTrue(engine.rootObjects())
            win = engine.rootObjects()[0]
            for page in range(5):
                win.setProperty("page", page)
                wait(80)
            backend.set("monitors", ["DP-9"])
            backend.set("theme", "classic")
            wait(80)
            win.close()
            found = list(warnings)
            win = None
            engine = None            # destroy the panel now, before its backend goes away
            import gc
            gc.collect()
            self.assertEqual(found, [])


class ShutdownTest(TempConfig):
    def test_dropping_the_backend_first_does_not_break_the_panel(self):
        """The order that printed "Cannot read property ... of null" when the panel closed."""
        import gc
        with mock.patch("linux_island.app._send_to_running", return_value=False):
            engine = QQmlApplicationEngine()
            warnings = []
            engine.warnings.connect(lambda ws: warnings.extend(w.toString() for w in ws))
            backend = settings.SettingsBackend(engine)
            engine.rootContext().setContextProperty("settings", backend)
            engine.load(QUrl.fromLocalFile(str(settings.HERE / "qml" / "Settings.qml")))
            wait(50)
            backend = None              # Python lets go of the backend first...
            gc.collect()
            wait(50)
            win = engine.rootObjects()[0]
            win.setProperty("page", 4)  # ...the panel still works
            wait(50)
            win = None
            engine = None               # ...and closing is quiet
            gc.collect()
            self.assertEqual(warnings, [])

    def test_ctrl_c_closes_the_panel_quietly(self):
        import signal
        import subprocess
        import sys
        runtime = tempfile.mkdtemp()
        os.chmod(runtime, 0o700)
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen", XDG_RUNTIME_DIR=runtime,
                   XDG_CONFIG_HOME=str(self.path.parent.parent))
        proc = subprocess.Popen([sys.executable, "-m", "linux_island", "--settings", "--welcome"],
                                cwd=str(settings.HERE.parent), env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True)
        time.sleep(3)
        self.assertIsNone(proc.poll(), "the panel should be running")
        proc.send_signal(signal.SIGINT)
        out, _ = proc.communicate(timeout=5)
        self.assertNotIn("TypeError", out)
        self.assertNotIn("Traceback", out)


class ReloadTest(TempConfig):
    """The island applies a changed config file without restarting."""
    def test_reload_applies_changes(self):
        from linux_island import app
        island = mock.Mock(spec=app.Island)
        island.cfg = dict(config.DEFAULTS)
        island.engine = mock.Mock()
        island.services = {"lock": mock.Mock()}
        window = mock.Mock()
        island.windows = {"DP-1": window}
        config.save(dict(config.DEFAULTS, screensaver_minutes=10, top_margin=8, monitors=["DP-1"], show_media=False))
        app.Island.reload(island)
        island.engine.rootContext().setContextProperty.assert_called_with("cfg", island.cfg)
        self.assertFalse(island.cfg["show_media"])
        island.services["lock"].set_screensaver_minutes.assert_called_with(10)
        window.set_layout.assert_called_with(8, config.DEFAULTS["home_position"])
        island.sync.assert_called_once()

    def test_unchanged_file_does_nothing(self):
        from linux_island import app
        island = mock.Mock(spec=app.Island)
        island.cfg = config.load()
        island.engine = mock.Mock()
        app.Island.reload(island)
        island.engine.rootContext().setContextProperty.assert_not_called()


if __name__ == "__main__":
    unittest.main()


class HelperRefreshTest(unittest.TestCase):
    def test_helper_state_follows_changes_made_elsewhere(self):
        from unittest import mock
        from linux_island import settings
        with mock.patch.object(settings.system, "helper_extension_state", return_value="off"), \
                mock.patch("linux_island.app._send_to_running", return_value=None):
            backend = settings.SettingsBackend()
            self.assertEqual(backend.helperState, "off")
            seen = []
            backend.helperChanged.connect(lambda: seen.append(backend.helperState))
            settings.system.helper_extension_state.return_value = "active"
            for _ in range(5):
                backend._poll_status()
            self.assertEqual(seen, ["active"])
            backend._status_timer.stop()
