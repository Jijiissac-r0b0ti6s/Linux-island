"""Island.qml with the real service objects (no background threads), driven through their signals."""
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Qt, QUrl, Slot  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlEngine  # noqa: E402
from PySide6.QtQuick import QQuickItem, QQuickView  # noqa: E402

APP = QGuiApplication.instance() or QGuiApplication([])

from linux_island import config  # noqa: E402
from linux_island.services import (AudioService, BatteryService, BluetoothService, BrightnessService,  # noqa: E402
                                   CameraService, DesktopService, LockService, MediaService, MicrophoneService,
                                   brightness)

import linux_island  # noqa: E402
QML = Path(linux_island.__file__).resolve().parent / "qml" / "Island.qml"   # the code under test, wherever it is installed
SCREEN = "DP-1"


class FakeWindow(QObject):
    """Stands in for IslandWindow; the saver window's fade-out is finished by hand (fade_out_done)."""
    def __init__(self):
        super().__init__()
        self.rects = []
        self.saver = []
        self.view = None

    @Slot(float, float, float, float)
    def setInputRect(self, x, y, w, h):
        self.rects.append((x, y, w, h))

    @Slot(bool)
    def setSaver(self, on):
        self.saver.append(on)

    @Slot()
    def openSettings(self):
        self.settings_opened = getattr(self, "settings_opened", 0) + 1

    def fade_out_done(self):
        self.view.rootObject().setProperty("saverHold", False)


def wait(ms):
    end = time.monotonic() + ms / 1000
    while time.monotonic() < end:
        APP.processEvents()
        time.sleep(0.005)


def texts(item):
    out = []
    for child in item.childItems():
        if child.metaObject().className().startswith("QQuickText") and child.isVisible():
            out.append(child.property("text"))
        out += texts(child)
    return out


def all_items(item):
    out = []
    for child in item.childItems():
        out.append(child)
        out += all_items(child)
    return out


class IslandQmlTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "brightness").write_text("500")
        (self.tmp / "max_brightness").write_text("1000")
        screens = [mock.Mock(**{"name.return_value": n}) for n in ("eDP-1", SCREEN)]
        with mock.patch("threading.Thread.start", lambda self: None), \
             mock.patch.object(brightness, "_find_backlight", return_value=self.tmp), \
             mock.patch.object(QGuiApplication, "screens", return_value=screens), \
             mock.patch.object(brightness, "_xrandr_levels", return_value={SCREEN: 1.0}), \
             mock.patch.object(brightness.QGuiApplication, "platformName", return_value="xcb"), \
             mock.patch("shutil.which", return_value="/usr/bin/x"):
            self.s = {
                "media": MediaService(), "audio": AudioService(), "brightness": BrightnessService(),
                "battery": BatteryService(), "camera": CameraService(),
                "microphone": MicrophoneService(), "bluetooth": BluetoothService(),
            }
        self.s["lock"] = LockService(start=False)
        self.s["lock"]._lock_session = mock.Mock()
        self.s["desktop"] = DesktopService(use_shell=False)   # offscreen: no window tracking, driven by hand
        self.s["brightness"]._idle = mock.Mock(idle_ms=mock.Mock(return_value=0))
        self.s["audio"]._run = lambda cmd: None
        self.s["audio"]._apply(0.5, False)
        self.s["media"]._send = lambda *a, **k: None
        bat = self.s["battery"]
        bat._bat, bat._percent, bat._charging = Path("/nonexistent"), 64, True

        self.engine = QQmlEngine()
        self.warnings = []
        self.engine.warnings.connect(lambda ws: self.warnings.extend(w.toString() for w in ws))
        ctx = self.engine.rootContext()
        for name, svc in self.s.items():
            ctx.setContextProperty(name, svc)
        self.cfg = dict(config.DEFAULTS, hud_timeout_ms=300)
        ctx.setContextProperty("cfg", self.cfg)
        self.win = FakeWindow()
        self.view = QQuickView(self.engine, None)
        self.win.view = self.view
        self.view.setResizeMode(QQuickView.SizeRootObjectToView)
        self.view.resize(760, 600)
        self.view.setInitialProperties({"win": self.win, "screenName": SCREEN, "homeCentre": 300})
        self.view.setSource(QUrl.fromLocalFile(str(QML)))
        self.assertEqual([e.toString() for e in self.view.errors()], [])
        self.root = self.view.rootObject()
        self.view.show()
        wait(50)

    def tearDown(self):
        warnings = list(self.warnings)
        self.view.close()
        self.view.setSource(QUrl())   # drop the scene before the services it binds to go away
        wait(10)
        self.assertEqual(warnings, [], "QML warnings")

    def prop(self, name):
        return self.root.property(name)

    def pill(self):
        return [c for c in self.root.childItems() if isinstance(c, QQuickItem)][0]

    def set_empty(self, screens):
        self.s["desktop"]._empty = screens
        self.s["desktop"].emptyChanged.emit()
        wait(20)

    # --- idle / modes
    def test_idle_shows_clock(self):
        self.assertEqual(self.prop("mode"), "idle")
        self.assertEqual(self.prop("hud"), "")

    def test_media_mode(self):
        self.s["media"]._apply(dict(__import__("linux_island.services.media", fromlist=["x"])._EMPTY,
                                    bus="org.mpris.MediaPlayer2.firefox", player="Firefox", title="Song",
                                    artist="Band", track="/t", playing=True, position=5.0, length=100.0))
        wait(20)
        self.assertEqual(self.prop("mode"), "media")
        self.root.setProperty("expanded", True)
        wait(50)
        shown = texts(self.root)
        self.assertIn("Song", shown)
        self.assertIn("Band", shown)

    # --- brightness HUD (the reported bug)
    def test_brightness_key_pops_hud_then_hides(self):
        (self.tmp / "brightness").write_text("700")
        self.s["brightness"]._poll_backlight()
        self.assertEqual(self.prop("hud"), "brightness")
        self.assertEqual(self.prop("hudScreen"), "eDP-1")
        wait(450)
        self.assertEqual(self.prop("hud"), "")

    def test_idle_dim_and_mouse_move_do_not_pop_hud(self):
        b = self.s["brightness"]
        b._idle.idle_ms.return_value = 61_000
        (self.tmp / "brightness").write_text("150")
        b._poll_backlight()
        b._idle.idle_ms.return_value = 3          # user moves the mouse
        (self.tmp / "brightness").write_text("500")
        b._poll_backlight()
        self.assertEqual(self.prop("hud"), "")
        self.assertEqual(self.prop("mode"), "idle")

    def test_slider_drag_does_not_pop_hud(self):
        with mock.patch.object(self.s["brightness"], "_write_logind", return_value=False):
            self.s["brightness"].setLevel("eDP-1", 0.4)
        self.s["brightness"]._poll_backlight()
        self.assertEqual(self.prop("hud"), "")

    # --- other pop-ups
    def test_volume_hud(self):
        self.s["audio"]._apply(0.7, False)
        self.assertEqual(self.prop("hud"), "volume")

    # --- settings: feature switches and colours
    def set_cfg(self, **changes):
        self.cfg = dict(self.cfg, **changes)
        self.engine.rootContext().setContextProperty("cfg", self.cfg)
        wait(20)

    def test_volume_popup_can_be_turned_off(self):
        self.set_cfg(popup_volume=False)
        self.s["audio"]._apply(0.8, False)
        self.assertEqual(self.prop("hud"), "")

    def test_brightness_power_and_device_popups_can_be_turned_off(self):
        self.set_cfg(popup_brightness=False, popup_power=False, popup_devices=False)
        (self.tmp / "brightness").write_text("900")
        self.s["brightness"]._poll_backlight()
        self.s["battery"].pluggedChanged.emit()
        self.s["bluetooth"].deviceEvent.emit("Buds", True, 50, True)
        self.s["audio"].outputChanged.emit("Headphones", True)
        self.assertEqual(self.prop("hud"), "")

    def test_media_can_be_turned_off(self):
        from linux_island.services import media as m
        self.s["media"]._apply(dict(m._EMPTY, bus="org.mpris.MediaPlayer2.x", player="X", title="Song",
                                    track="/t", playing=True, length=100.0))
        wait(20)
        self.assertEqual(self.prop("mode"), "media")
        self.set_cfg(show_media=False)
        self.assertEqual(self.prop("mode"), "idle")

    def test_privacy_dots_can_be_turned_off(self):
        self.s["camera"]._apply("zoom")
        self.s["microphone"]._active = True
        self.s["microphone"].activeChanged.emit()
        self.assertEqual(self.prop("dotsWidth"), 24)
        self.set_cfg(dot_camera=False)
        self.assertEqual(self.prop("dotsWidth"), 12)
        self.set_cfg(dot_mic=False)
        self.assertEqual(self.prop("dotsWidth"), 0)

    def test_colours_from_settings(self):
        self.set_cfg(pill_color="#0b1a33", accent_color="#0a84ff", theme="classic")
        wait(650)   # the accent eases over 0.5 s
        self.assertEqual(self.pill().property("color").name(), "#0b1a33")
        self.assertEqual(self.prop("accent").name(), "#0a84ff")

    def test_home_height_setting_never_resizes_the_window(self):
        from linux_island import app as A
        with mock.patch.object(A, "_panel_height", return_value=0) as panel:
            w = A.IslandWindow(self.engine, APP.primaryScreen(), 2, 0.36)
            wait(30)
            before, centre = w.geometry(), w.rootObject().property("homeCentre")
            looked_up = panel.call_count
            for pos in (0.4, 0.45, 0.5, 0.55, 0.6, 0.9):      # a slider drag (and an out-of-range value)
                w.set_layout(2, pos)
            self.assertEqual(w.geometry(), before)             # same window: nothing to flicker
            self.assertEqual(panel.call_count, looked_up)     # no panel lookup per step
            self.assertGreater(w.rootObject().property("homeCentre"), centre)   # but the card moved
            self.assertLessEqual(w.rootObject().property("homeCentre") + A.IslandWindow.BELOW_HOME, before.height())
            w.set_layout(10, 0.6)                              # the gap above the pill does move it
            self.assertEqual(w.geometry().y(), before.y() + 8)
            self.assertEqual(w.geometry().height(), before.height() - 8)
            w.close()
            w.setSource(QUrl())
            from PySide6.QtCore import QCoreApplication, QEvent
            w.deleteLater()              # also cancels its delayed screensaver warm-up
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def drawn_rect(self, item):
        from PySide6.QtCore import QPointF
        tl = item.mapToScene(QPointF(0, 0))
        br = item.mapToScene(QPointF(item.width(), item.height()))
        return tl.x(), tl.y(), br.x(), br.y()

    def assert_clickable(self, item):
        """The X11 input shape (where clicks are accepted) covers everything of `item` that is drawn."""
        x0, y0, x1, y1 = self.drawn_rect(item)
        sx, sy, sw, sh = self.win.rects[-1]
        self.assertTrue(sx <= x0 + 0.5 and sy <= y0 + 0.5 and x1 - 0.5 <= sx + sw and y1 - 0.5 <= sy + sh,
                        f"drawn {x0:.1f},{y0:.1f}..{x1:.1f},{y1:.1f} vs clickable {sx:.1f},{sy:.1f}..{sx+sw:.1f},{sy+sh:.1f}")

    def test_input_shape_matches_the_drawn_pill_in_every_mode(self):
        self.assert_clickable(self.pill())                 # idle pill
        self.root.setProperty("expanded", True)            # hover popup
        wait(900)
        self.assert_clickable(self.pill())
        self.root.setProperty("expanded", False)
        self.set_empty([SCREEN])                           # home card, scaled up
        wait(900)
        self.assert_clickable(self.pill())
        x0, y0, x1, y1 = self.drawn_rect(self.pill())
        sx, sy, sw, sh = self.win.rects[-1]
        self.assertLess(abs(sy - y0), 2)                    # no click-through strip at the top...
        self.assertLess(abs((sy + sh) - y1), 2)             # ...and no dead strip below the card

    def test_whole_gear_is_clickable(self):
        self.set_empty([SCREEN])
        wait(900)
        self.assert_clickable(self.gear())

    # --- hover: only real pointer movement opens the popup
    def move_to(self, item_x, item_y, steps=1):
        from PySide6.QtCore import QPoint, QPointF
        from PySide6.QtTest import QTest
        for i in range(steps):
            p = self.pill().mapToScene(QPointF(item_x + i * 3, item_y))
            QTest.mouseMove(self.view, QPoint(round(p.x()), round(p.y())))
            wait(30)

    def test_moving_over_the_pill_opens_it(self):
        self.move_to(60, 14, steps=4)
        wait(450)                                             # once it has rested there
        self.assertTrue(self.prop("expanded"))

    def test_passing_over_the_pill_does_not_open(self):
        """Swiping across the top of the screen (to a browser tab, say) crosses the pill."""
        opened = []
        self.root.expandedChanged.connect(lambda: opened.append(self.prop("expanded")))
        self.move_to(10, 14, steps=12)                        # 33 px across in ~0.36 s, never resting...
        self.move_to(self.pill().width() + 80, 14)            # ...and off the other side
        wait(500)
        self.assertNotIn(True, opened, "the popup flashed open while the pointer passed over")

    def test_jitter_in_place_does_not_open(self):
        self.move_to(60, 14)
        for i in range(30):                                   # +-1 px wobble, as some X servers report
            self.move_to(60 + (i % 2), 14 + (i % 2))
        wait(500)
        self.assertFalse(self.prop("expanded"))

    def test_pill_growing_under_a_still_pointer_does_not_open(self):
        self.move_to(self.pill().width() + 30, 14)          # resting just right of the idle pill
        wait(250)
        self.s["audio"]._apply(0.7, False)                   # a volume pop-up widens it under the pointer
        wait(500)
        self.assertFalse(self.prop("expanded"))
        from linux_island.services import media as m         # so does a song starting
        self.s["media"]._apply(dict(m._EMPTY, bus="org.mpris.MediaPlayer2.x", player="X", title="Song",
                                    track="/t", playing=True, length=100.0))
        wait(500)
        self.assertFalse(self.prop("expanded"))
        self.move_to(self.pill().width() - 60, 14, steps=3)  # but moving the pointer onto it and resting does
        wait(450)
        self.assertTrue(self.prop("expanded"))

    def test_hover_open_can_be_turned_off(self):
        self.set_cfg(open_on_hover=False)
        self.move_to(60, 14, steps=4)
        wait(450)
        self.assertFalse(self.prop("expanded"))

    def gear(self):
        return [i for i in all_items(self.root) if i.metaObject().className().startswith("IconButton")
                and i.property("name") == "settings"][0]

    def test_settings_button_only_on_home_card(self):
        self.root.setProperty("expanded", True)          # the hover popup: no gear
        wait(250)
        self.assertFalse(self.gear().isVisible())
        self.root.setProperty("expanded", False)
        self.set_empty([SCREEN])                         # the home card: gear top right
        wait(300)
        gear = self.gear()
        self.assertTrue(gear.isVisible())
        self.assertGreater(gear.x(), self.pill().width() - 60)
        self.win.settings_opened = 0
        gear.clicked.emit()
        self.assertEqual(self.win.settings_opened, 1)

    def speaker(self):
        icons = [g for g in all_items(self.root) if g.metaObject().className().startswith("VolumeIcon") and g.isVisible()]
        self.assertTrue(icons)
        return icons[0]

    def test_volume_icon_follows_level(self):
        a = self.s["audio"]
        for level, waves in ((0.2, (0, 0, 0)), (0.5, (1, 0, 0)), (0.9, (1, 1, 0))):
            a._apply(level, False)
            wait(250)
            icon = self.speaker()
            self.assertEqual((icon.property("wave1"), icon.property("wave2"), icon.property("cross")), waves, level)
        a._apply(0.9, True)                       # muted
        wait(250)
        icon = self.speaker()
        self.assertEqual((icon.property("wave1"), icon.property("wave2"), icon.property("cross")), (0, 0, 1))

    def test_volume_icon_in_popup_follows_slider(self):
        self.root.setProperty("expanded", True)
        wait(50)
        self.s["audio"].setVolume(0.1)
        wait(250)
        icons = [g for g in all_items(self.root) if g.metaObject().className().startswith("VolumeIcon") and g.isVisible()]
        self.assertTrue(any(i.property("wave1") == 0 and i.property("cross") == 0 for i in icons))
        self.s["audio"].setVolume(0.8)
        wait(250)
        self.assertTrue(any(i.property("wave2") == 1 for i in icons))

    def battery_icons(self):
        return [g for g in all_items(self.root) if g.metaObject().className().startswith("BatteryIcon") and g.isVisible()]

    def set_battery(self, percent, charging):
        bat = self.s["battery"]
        bat._percent, bat._charging = percent, charging
        bat.percentChanged.emit()
        bat.chargingChanged.emit()
        wait(20)

    def test_battery_colour_follows_charge(self):
        self.root.setProperty("expanded", True)
        wait(50)
        for percent, charging, colour in ((90, False, "#ffffff"), (50, False, "#ffd60a"), (35, False, "#ffd60a"),
                                          (20, False, "#ff453a"), (5, False, "#ff453a"), (5, True, "#34c759")):
            self.set_battery(percent, charging)
            icons = self.battery_icons()
            self.assertTrue(icons)
            self.assertEqual({i.property("tone").name() for i in icons}, {colour}, (percent, charging))
            self.assertIn(f"Battery {percent}%", texts(self.root))

    def test_power_hud_shows_battery_icon(self):
        self.set_battery(15, False)
        self.s["battery"].pluggedChanged.emit()
        wait(30)
        icons = self.battery_icons()
        self.assertTrue(icons)
        self.assertEqual(icons[0].property("tone").name(), "#ff453a")

    def test_sun_follows_brightness(self):
        self.root.setProperty("expanded", True)
        wait(50)
        suns = lambda: [g for g in all_items(self.root) if g.metaObject().className().startswith("SunIcon") and g.isVisible()]
        b = self.s["brightness"]
        b._levels["DP-1"] = 0.2
        b.levelsChanged.emit()
        wait(250)
        low = [s.property("shown") for s in suns()]
        b._levels["DP-1"] = 0.9
        b.levelsChanged.emit()
        wait(250)
        high = [s.property("shown") for s in suns()]
        self.assertAlmostEqual(min(low), 0.2, delta=0.02)
        self.assertAlmostEqual(max(high), 0.9, delta=0.02)

    def test_power_hud(self):
        self.s["battery"].pluggedChanged.emit()
        self.assertEqual(self.prop("hud"), "power")

    def test_power_hud_is_a_message_not_a_level_bar(self):
        bat = self.s["battery"]
        bat._percent, bat._charging, bat._state = 64, True, "charging"
        bat.percentChanged.emit()
        bat.chargingChanged.emit()
        bat.stateChanged.emit()
        bat.pluggedChanged.emit()
        wait(250)
        shown = texts(self.root)
        self.assertIn("Charging", shown)
        self.assertIn("64%", shown)
        bars = [i for i in all_items(self.root) if i.metaObject().className().startswith("Bar") and i.isVisible()]
        self.assertEqual(bars, [], "the charger pop-up shows no volume-style bar")
        bat._charging, bat._state = False, "battery"
        bat.chargingChanged.emit()
        bat.stateChanged.emit()
        bat.pluggedChanged.emit()
        wait(100)
        self.assertIn("On battery", texts(self.root))
        bat._state = "full"
        bat.stateChanged.emit()
        wait(50)
        self.assertIn("Fully charged", texts(self.root))

    def test_volume_hud_still_has_its_bar(self):
        self.s["audio"].changed.emit()
        wait(250)
        bars = [i for i in all_items(self.root) if i.metaObject().className().startswith("Bar") and i.isVisible()]
        self.assertTrue(bars)

    def test_bluetooth_connect_hud(self):
        self.s["bluetooth"].deviceEvent.emit("Buds", True, 72, True)
        self.assertEqual(self.prop("hud"), "device")
        self.assertEqual(self.prop("hudGlyph"), "headphones")
        self.assertEqual(self.prop("hudLabel"), "Buds")
        self.assertEqual(self.prop("hudPercent"), 72)
        wait(30)
        self.assertIn("72%", texts(self.root))

    def test_bluetooth_disconnect_hud(self):
        self.s["bluetooth"].deviceEvent.emit("Mouse", False, -1, False)
        self.assertEqual(self.prop("hudGlyph"), "bluetooth")
        self.assertEqual(self.prop("hudLabel"), "Mouse disconnected")

    def test_headphone_output_hud(self):
        self.s["audio"].outputChanged.emit("WH-1000XM4", True)
        self.assertEqual(self.prop("hudGlyph"), "headphones")
        self.s["audio"].outputChanged.emit("Speakers", False)
        self.assertEqual(self.prop("hudGlyph"), "volume")

    def test_hud_suppressed_while_open(self):
        self.root.setProperty("expanded", True)
        self.s["audio"]._apply(0.9, False)
        self.assertEqual(self.prop("hud"), "")

    # --- indicators
    def test_camera_and_mic_dots(self):
        self.assertEqual(self.prop("dotsWidth"), 0)
        self.s["camera"]._apply("zoom")
        self.s["microphone"]._active = True
        self.s["microphone"].activeChanged.emit()
        self.assertEqual(self.prop("dotsWidth"), 24)
        self.root.setProperty("expanded", True)
        wait(30)
        self.assertTrue(any("Camera in use by zoom" in t and "Mic in use" in t for t in texts(self.root)))

    # --- swoop / home card
    def test_swoop_when_monitor_empty_and_back(self):
        self.set_empty([SCREEN])
        self.assertTrue(self.prop("home"))
        self.assertEqual(self.prop("mode"), "expanded")
        self.assertEqual(self.prop("expandedWidth"), 400 + 172)
        wait(800)
        pill = self.pill()
        self.assertAlmostEqual(pill.scale(), 1.25, places=2)
        centre = pill.y() + pill.height() * pill.scale() / 2
        self.assertAlmostEqual(centre, 300, delta=4)
        x, y, w, h = self.win.rects[-1]
        self.assert_clickable(pill)                   # clicks land on the card
        self.set_empty([])                             # a window opened
        self.assertFalse(self.prop("home"))
        wait(800)
        self.assertEqual(self.prop("mode"), "idle")
        self.assertAlmostEqual(self.pill().y(), 0, delta=1)

    def test_other_monitor_empty_does_not_swoop(self):
        self.set_empty(["eDP-1"])
        self.assertFalse(self.prop("home"))

    def test_swoop_disabled_in_config(self):
        self.cfg["home_on_empty_desktop"] = False
        self.engine.rootContext().setContextProperty("cfg", self.cfg)
        self.set_empty([SCREEN])
        self.assertFalse(self.prop("home"))

    def test_home_card_shows_battery_once_and_calendar(self):
        self.set_empty([SCREEN])
        wait(400)
        shown = texts(self.root)
        self.assertEqual(sum("64%" in t for t in shown), 1, shown)
        self.assertIn(time.strftime("%d").lstrip("0"), shown)      # calendar has today
        self.assertTrue(any(t.startswith(time.strftime("%A")) for t in shown))  # full date line

    def test_home_card_lists_all_monitors_brightness(self):
        self.assertEqual(self.prop("monitors").toVariant(), ["eDP-1", "DP-1"])   # laptop first
        self.set_empty([SCREEN])
        wait(300)
        shown = texts(self.root)
        self.assertTrue(any("Laptop" in t or "eDP-1" in t for t in shown), shown)
        self.assertTrue(any("DP-1" in t and "eDP" not in t for t in shown), shown)

    def test_home_card_lists_bluetooth_devices(self):
        self.s["bluetooth"]._apply([{"name": "Buds", "battery": 55, "audio": True}])
        self.set_empty([SCREEN])
        wait(300)
        self.assertTrue(any("Buds" in t for t in texts(self.root)))

    def test_popup_status_keeps_battery(self):
        self.root.setProperty("expanded", True)
        wait(30)
        shown = texts(self.root)
        self.assertIn("Battery 64%", shown)
        self.assertFalse(any("⚡" in t for t in shown))       # the emoji is yellow; the icon is green
        icons = self.battery_icons()
        self.assertTrue(icons)
        self.assertTrue(all(i.property("tone").name() == "#34c759" for i in icons))   # charging

    def test_classic_theme_uses_white_bar(self):
        self.cfg["theme"] = "classic"
        self.engine.rootContext().setContextProperty("cfg", self.cfg)
        wait(10)
        self.assertFalse(self.prop("vivid"))


    # --- lock screen / screensaver (the curtain itself is driven by IslandWindow; see test_curtain.py)
    def lock(self):
        return self.s["lock"]

    def test_lock_now_swoops_to_clock_card_then_locks(self):
        self.lock().lockNow()
        self.assertTrue(self.prop("saver"))
        self.assertEqual(self.win.saver, [True])          # the saver window starts its fade
        self.assertEqual(self.prop("mode"), "saver")
        wait(500)
        self.lock()._lock_session.assert_not_called()     # still swooping / fading
        wait(500)
        self.lock()._lock_session.assert_called_once()     # then the real lock
        pill = self.pill()
        self.assertAlmostEqual(pill.width(), 460, delta=2)
        self.assertAlmostEqual(self.card_centre(), 300, delta=3)
        self.lock()._set_locked(True)
        self.assertFalse(self.lock().locking)
        self.assertTrue(self.prop("saver"))

    def test_unlock_card_waits_for_fade_then_returns_to_pill(self):
        self.lock()._set_locked(True)
        wait(900)
        self.lock()._set_locked(False)
        self.assertEqual(self.win.saver, [True, False])
        self.assertEqual(self.prop("mode"), "saver")       # card stays under the fading window
        self.win.fade_out_done()
        wait(1000)
        self.assertEqual(self.prop("mode"), "idle")
        self.assertAlmostEqual(self.pill().y(), 0, delta=0.5)
        self.assertAlmostEqual(self.pill().width(), 156, delta=1)
        x, y, w, h = self.win.rects[-1]
        self.assertLess(w, 200)                            # clicks pass through again

    def test_unlock_back_to_home_card(self):
        self.set_empty([SCREEN])
        wait(700)
        self.lock()._set_locked(True)
        wait(900)
        self.lock()._set_locked(False)
        self.win.fade_out_done()
        wait(1100)
        self.assertEqual(self.prop("mode"), "expanded")
        self.assertAlmostEqual(self.card_centre(), 300, delta=4)

    def card_centre(self):
        pill = self.pill()
        return pill.y() + pill.height() * pill.scale() / 2

    def test_relock_while_fading_back(self):
        self.lock()._set_locked(True)
        self.lock()._set_locked(False)
        self.lock()._set_locked(True)
        self.assertEqual(self.win.saver, [True, False, True])
        self.assertEqual(self.prop("mode"), "saver")

    def test_defaults_screensaver_and_lock_on(self):
        self.assertTrue(config.DEFAULTS["lock_transition"])
        self.assertEqual(config.DEFAULTS["screensaver_minutes"], 5)

    def test_lock_transition_off(self):
        self.cfg["lock_transition"] = False
        self.engine.rootContext().setContextProperty("cfg", self.cfg)
        self.lock()._set_locked(True)
        self.assertFalse(self.prop("saver"))
        self.assertEqual(self.win.saver, [])

    def test_failed_lock_returns(self):
        self.lock().lockNow()
        wait(900)
        self.lock()._lock_failed()
        self.assertFalse(self.prop("saver"))
        self.assertEqual(self.win.saver, [True, False])

    def test_no_hud_or_hover_while_saver(self):
        self.lock()._set_locked(True)
        wait(100)
        self.s["audio"]._apply(0.9, False)
        self.assertEqual(self.prop("hud"), "")
        self.assertFalse(self.prop("expanded"))

    def arm(self, lk):
        lk._clock = mock.Mock(idle_ms=mock.Mock(return_value=100))
        lk._poll_idle()   # someone used the computer

    def screensaver_on(self):
        lk = self.lock()
        lk._saver_ms = 60_000
        self.arm(lk)
        lk._clock.idle_ms.return_value = 61_000
        lk._poll_idle()
        return lk

    def test_screensaver_swoops_pill_into_clock_card(self):
        self.screensaver_on()
        self.assertEqual(self.win.saver, [True])            # card + black fade
        wait(1000)
        pill = self.pill()
        self.assertAlmostEqual(pill.width(), 460, delta=2)
        self.assertAlmostEqual(self.card_centre(), 300, delta=3)   # where the saver window draws its clock
        self.assertIn(time.strftime("%H:%M"), texts(self.root))

    def test_screensaver_card_waits_for_fade_out_then_returns(self):
        lk = self.screensaver_on()
        wait(900)
        lk._clock.idle_ms.return_value = 200                # mouse moved
        lk._poll_idle()
        self.assertEqual(self.win.saver, [True, False])
        self.assertEqual(self.prop("mode"), "saver")        # card stays under the fading window
        wait(300)
        self.assertAlmostEqual(self.pill().width(), 460, delta=2)
        self.win.fade_out_done()
        wait(1000)
        self.assertEqual(self.prop("mode"), "idle")
        self.assertAlmostEqual(self.pill().y(), 0, delta=0.5)
        self.assertAlmostEqual(self.pill().width(), 156, delta=1)

    def test_idle_screensaver_and_wake(self):
        lk = self.lock()
        lk._saver_ms = 60_000
        self.arm(lk)
        lk._clock.idle_ms.return_value = 61_000
        lk._poll_idle()
        self.assertTrue(lk.idle and self.prop("saver"))
        self.assertEqual(self.win.saver, [True])
        lk._clock.idle_ms.return_value = 30_000           # still away
        lk._poll_idle()
        self.assertTrue(lk.idle)
        lk._clock.idle_ms.return_value = 200              # mouse moved
        lk._poll_idle()
        self.assertFalse(lk.idle or self.prop("saver"))
        self.assertEqual(self.win.saver, [True, False])

    def test_screensaver_off_when_minutes_zero(self):
        lk = self.lock()
        lk._saver_ms = 0
        lk._clock = mock.Mock(idle_ms=mock.Mock(return_value=10_000_000))
        lk._poll_idle()
        self.assertFalse(lk.idle)

    def test_start_saver_by_hand_ignores_the_key_that_started_it(self):
        lk = self.lock()
        lk._clock = mock.Mock(idle_ms=mock.Mock(return_value=50))
        lk.startSaver()
        lk._poll_idle()
        lk.wake()                                          # click straight away: ignored
        self.assertTrue(lk.idle and self.prop("saver"))
        lk._ignore_until = 0
        lk._poll_idle()
        self.assertFalse(lk.idle)

    def test_no_screensaver_right_after_fingerprint_unlock(self):
        lk = self.lock()
        lk._saver_ms = 60_000
        self.arm(lk)
        lk._set_locked(True)
        lk._set_locked(False)
        lk._clock.idle_ms.return_value = 400_000
        lk._poll_idle()
        self.assertFalse(lk.idle or self.prop("saver"))
        lk._clock.idle_ms.return_value = 300
        lk._poll_idle()
        lk._clock.idle_ms.return_value = 61_000
        lk._poll_idle()
        self.assertTrue(lk.idle)

    def test_idle_screensaver_not_over_lock(self):
        lk = self.lock()
        lk._saver_ms = 60_000
        self.arm(lk)
        lk._clock.idle_ms.return_value = 61_000
        lk._set_locked(True)
        lk._poll_idle()
        self.assertFalse(lk.idle)
        lk.startSaver()
        self.assertFalse(lk.idle)

    def test_lock_now_twice_is_one_lock(self):
        self.lock().lockNow()
        self.lock().lockNow()
        wait(1000)
        self.lock()._lock_session.assert_called_once()


class SaverWindowTest(unittest.TestCase):
    """The real full-screen screensaver window: compositor fade only, clock placed on the card."""
    def setUp(self):
        from linux_island import app as A
        from linux_island.services import media as m
        self.engine = QQmlEngine()
        self.warnings = []
        self.engine.warnings.connect(lambda ws: self.warnings.extend(w.toString() for w in ws))
        with mock.patch("threading.Thread.start", lambda self: None):
            self.media = MediaService()
            self.lock = LockService(start=False)
        self.media._apply(dict(m._EMPTY, bus="org.mpris.MediaPlayer2.x", player="X", title="Night Song",
                               artist="Band", track="/t", playing=False, length=100.0))
        bat = BatteryService()
        bat._bat, bat._percent, bat._charging = Path("/nonexistent"), 64, True
        self.battery = bat   # keep it alive for the QML
        ctx = self.engine.rootContext()
        for name, svc in (("media", self.media), ("lock", self.lock), ("battery", bat)):
            ctx.setContextProperty(name, svc)
        ctx.setContextProperty("cfg", dict(config.DEFAULTS))
        self.island = mock.Mock()
        A.SaverWindow.FADE_DELAY, A.SaverWindow.FADE_IN, A.SaverWindow.FADE_OUT = 50, 100, 100
        self.saver = A.SaverWindow(self.engine, APP.primaryScreen(), self.island)
        self.saver.place(APP.primaryScreen().geometry(), 300)

    def tearDown(self):
        self.saver.hide()
        self.saver.setSource(QUrl())
        wait(10)
        found = list(self.warnings)
        self.saver = None            # gone before the services it shows
        import gc
        gc.collect()
        self.assertEqual(found, [])

    def test_fade_in_then_out(self):
        self.saver.fade(True)
        self.assertTrue(self.saver.isVisible())
        wait(30)
        self.assertEqual(self.saver.opacity(), 0.0)        # waits for the card to land first
        wait(250)
        self.assertEqual(self.saver.opacity(), 1.0)
        shown = texts(self.saver.rootObject())
        self.assertIn(time.strftime("%H:%M"), shown)
        self.assertIn("Night Song", shown)
        self.assertIn("64% charging", shown)
        self.saver.fade(False)
        wait(60)
        self.assertTrue(0 < self.saver.opacity() < 1)
        self.island._release_pill.assert_not_called()       # card stays until the fade is done
        wait(200)
        self.assertFalse(self.saver.isVisible())
        self.island._release_pill.assert_called_once()

    def test_warm_up_never_takes_clicks(self):
        self.saver.warm()
        self.assertTrue(self.saver.isVisible())
        self.assertTrue(self.saver.flags() & Qt.WindowTransparentForInput)   # invisible: clicks go through
        wait(500)
        self.assertFalse(self.saver.isVisible())
        self.assertFalse(self.saver.flags() & Qt.WindowTransparentForInput)  # the real screensaver takes them

    def test_screensaver_during_warm_up_takes_clicks(self):
        self.saver.warm()
        self.saver.fade(True)
        self.assertFalse(self.saver.flags() & Qt.WindowTransparentForInput)
        wait(500)
        self.assertTrue(self.saver.isVisible())       # the warm-up's end doesn't hide the real one

    def test_clock_centred_on_card(self):
        self.saver.fade(True)
        wait(300)
        root = self.saver.rootObject()
        clock = [c for c in root.childItems() if c.metaObject().className().startswith("SaverClock")][0]
        self.assertAlmostEqual(clock.y() + clock.height() / 2, 300, delta=1)
        self.assertAlmostEqual(clock.x() + clock.width() / 2, root.width() / 2, delta=1)

    def test_click_ends_screensaver(self):
        self.lock.startSaver()
        self.lock._ignore_until = 0
        self.saver.fade(True)
        wait(300)
        from PySide6.QtTest import QTest
        QTest.mouseClick(self.saver, Qt.LeftButton, pos=self.saver.geometry().center() - self.saver.geometry().topLeft())
        wait(20)
        self.assertFalse(self.lock.idle)


if __name__ == "__main__":
    unittest.main()
