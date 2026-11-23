"""Unit tests for the services. Run: QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest -v"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QGuiApplication  # noqa: E402

APP = QGuiApplication.instance() or QGuiApplication([])

from linux_island import config  # noqa: E402
from linux_island.services import audio, battery, bluetooth, brightness, media, microphone  # noqa: E402
from linux_island.services.idle import IdleClock  # noqa: E402


class Spy:
    """Counts emissions of a Qt signal."""
    def __init__(self, signal):
        self.calls = []
        signal.connect(lambda *a: self.calls.append(a))

    def __len__(self):
        return len(self.calls)


def no_threads():
    return mock.patch("threading.Thread.start", lambda self: None)


# ---------------------------------------------------------------- brightness
class AutoDimFilterTest(unittest.TestCase):
    def setUp(self):
        self.f = brightness.AutoDimFilter()

    def test_brightness_key_while_active_shows_hud(self):
        self.assertTrue(self.f.is_user_change(100, 120, idle_ms=50, now=0))

    def test_idle_dim_is_hidden(self):
        self.assertFalse(self.f.is_user_change(100, 60, idle_ms=60_000, now=0))
        self.assertTrue(self.f.dimmed)

    def test_multi_step_fade_down_is_hidden(self):
        for i, level in enumerate((80, 60, 40, 30)):
            self.assertFalse(self.f.is_user_change(level + 10, level, idle_ms=60_000 + i, now=i))

    def test_restore_on_mouse_move_is_hidden(self):
        """The reported bug: moving the mouse after inactivity popped the brightness HUD."""
        self.f.is_user_change(100, 30, idle_ms=60_000, now=0)
        self.assertFalse(self.f.is_user_change(30, 100, idle_ms=10, now=100))
        self.assertFalse(self.f.dimmed)

    def test_stepwise_restore_is_hidden(self):
        self.f.is_user_change(100, 30, idle_ms=60_000, now=0)
        self.assertFalse(self.f.is_user_change(30, 60, idle_ms=10, now=100.0))
        self.assertFalse(self.f.is_user_change(60, 90, idle_ms=200, now=100.2))
        self.assertFalse(self.f.is_user_change(90, 100, idle_ms=400, now=100.4))
        self.assertFalse(self.f.dimmed)
        # the next key press is shown again
        self.assertTrue(self.f.is_user_change(100, 110, idle_ms=30, now=105))

    def test_key_press_long_after_partial_restore_is_shown(self):
        self.f.is_user_change(100, 30, idle_ms=60_000, now=0)
        self.f.is_user_change(30, 80, idle_ms=10, now=100)   # restored to a lower level
        self.assertTrue(self.f.is_user_change(80, 90, idle_ms=10, now=110))
        self.assertFalse(self.f.dimmed)

    def test_reset_after_user_sets_level(self):
        self.f.is_user_change(100, 30, idle_ms=60_000, now=0)
        self.f.reset()
        self.assertTrue(self.f.is_user_change(30, 50, idle_ms=10, now=1))

    def test_wake_after_unseen_dim_is_hidden(self):
        """Island started while the screen was already dimmed: only the restore is seen."""
        self.f.note_idle(65_000)
        self.assertFalse(self.f.is_user_change(30, 100, idle_ms=20, now=0))
        self.assertFalse(self.f.is_user_change(100, 110, idle_ms=200, now=0.4))  # rest of the fade
        self.assertTrue(self.f.is_user_change(110, 120, idle_ms=50, now=10))     # later key press

    def test_key_press_after_short_pause_is_shown(self):
        self.f.note_idle(10_000)   # reading for ten seconds is not "away"
        self.assertTrue(self.f.is_user_change(50, 60, idle_ms=20, now=0))

    def test_key_down_after_being_away_is_shown(self):
        self.f.note_idle(65_000)
        self.assertTrue(self.f.is_user_change(60, 50, idle_ms=20, now=0))

    def test_active_sample_clears_away(self):
        self.f.note_idle(65_000)
        self.f.note_idle(100)
        self.assertTrue(self.f.is_user_change(30, 100, idle_ms=20, now=0))

    def test_dim_after_unfinished_wake_starts_fresh(self):
        """Regression: an unseen-dim wake left a stale restore window; the next dim's restore popped the HUD."""
        self.f.note_idle(65_000)
        self.assertFalse(self.f.is_user_change(58, 114, idle_ms=20, now=0))   # wake, target unknown
        self.assertTrue(self.f.is_user_change(114, 135, idle_ms=20, now=60))  # key press later: shown
        self.f.note_idle(65_000)
        self.f.is_user_change(135, 120, idle_ms=10, now=61)                    # partial restore left dimmed
        self.assertFalse(self.f.is_user_change(135, 59, idle_ms=60_380, now=500))  # GNOME dims again
        self.assertFalse(self.f.is_user_change(59, 135, idle_ms=55, now=510))      # wake: no HUD
        self.assertFalse(self.f.dimmed)

    def test_unknown_idle_falls_back_to_showing(self):
        self.assertTrue(self.f.is_user_change(100, 30, idle_ms=None, now=0))


class BrightnessServiceTest(unittest.TestCase):
    def make(self, raw=500, idle=0):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "brightness").write_text(str(raw))
        (tmp / "max_brightness").write_text("1000")
        screens = [mock.Mock(**{"name.return_value": "eDP-1"})]
        with mock.patch.object(brightness, "_find_backlight", return_value=tmp), \
             mock.patch.object(QGuiApplication, "screens", return_value=screens), \
             mock.patch.object(brightness, "_xrandr_levels", return_value={}):
            svc = brightness.BrightnessService()
        svc._idle = mock.Mock(idle_ms=mock.Mock(return_value=idle))
        return svc, tmp

    def test_started_while_dimmed_then_wake_does_not_emit(self):
        svc, tmp = self.make(raw=300, idle=70_000)
        spy = Spy(svc.changed)
        svc._poll_backlight()                 # first poll samples idle
        svc._idle.idle_ms.return_value = 15   # mouse moved, GNOME undims
        (tmp / "brightness").write_text("600")
        svc._poll_backlight()
        self.assertEqual(spy.calls, [])

    def test_reads_initial_level(self):
        svc, _ = self.make(raw=500)
        self.assertAlmostEqual(svc.levels["eDP-1"], 0.5)

    def test_logged_wake_sequence_from_17_november(self):
        """The real sequence: idle dim, mouse-move restore, then two key presses straight after."""
        svc, tmp = self.make(raw=85305)
        idle = {"ms": 200}
        svc._idle.idle_ms.side_effect = lambda: idle["ms"]
        shown = Spy(svc.changed)

        def tick(raw=None, ms=None):
            if ms is not None:
                idle["ms"] = ms
            if raw is not None:
                (tmp / "brightness").write_text(str(raw))
            svc._poll_backlight()
        for i in range(150):                      # a minute without input, polled every 0.4 s
            tick(ms=200 + i * 400)
        tick(58944, 60044)                        # GNOME dims
        tick(85555, 270)                          # mouse moved: GNOME restores
        self.assertEqual(len(shown), 0)
        tick(23040, 369)                          # brightness key down
        tick(182400, 233)                         # brightness key up
        self.assertEqual(len(shown), 2)

    def test_key_change_emits(self):
        svc, tmp = self.make()
        spy = Spy(svc.changed)
        (tmp / "brightness").write_text("700")
        svc._poll_backlight()
        self.assertEqual(spy.calls, [("eDP-1",)])
        self.assertAlmostEqual(svc.levels["eDP-1"], 0.7)

    def test_idle_dim_and_restore_do_not_emit(self):
        svc, tmp = self.make()
        spy = Spy(svc.changed)
        svc._idle.idle_ms.return_value = 60_000
        (tmp / "brightness").write_text("150")
        svc._poll_backlight()
        svc._idle.idle_ms.return_value = 5
        (tmp / "brightness").write_text("500")
        svc._poll_backlight()
        self.assertEqual(spy.calls, [])
        self.assertAlmostEqual(svc.levels["eDP-1"], 0.5)  # slider still follows

    def test_set_level_writes_and_does_not_emit_changed(self):
        svc, tmp = self.make()
        spy = Spy(svc.changed)
        with mock.patch.object(svc, "_write_logind", return_value=False):
            svc.setLevel("eDP-1", 0.3)
        self.assertEqual((tmp / "brightness").read_text(), "300")
        svc._poll_backlight()
        self.assertEqual(spy.calls, [])

    def test_set_level_clamps(self):
        svc, tmp = self.make()
        with mock.patch.object(svc, "_write_logind", return_value=False):
            svc.setLevel("eDP-1", 0.0)
        self.assertEqual((tmp / "brightness").read_text(), "10")  # never fully off

    def test_unknown_screen_ignored(self):
        svc, _ = self.make()
        svc.setLevel("HDMI-9", 0.5)
        self.assertNotIn("HDMI-9", svc.levels)

    def test_external_monitor_uses_xrandr_throttled(self):
        svc, _ = self.make()
        svc._levels["DP-1"] = 1.0
        with mock.patch("subprocess.Popen") as popen:
            for v in (0.9, 0.8, 0.05):
                svc.setLevel("DP-1", v)
            svc._apply_pending()
        self.assertEqual(popen.call_count, 1)
        self.assertEqual(popen.call_args[0][0], ["xrandr", "--output", "DP-1", "--brightness", "0.20"])

    def test_xrandr_parser(self):
        out = ("DP-1 connected primary 1920x1080+0+0\n\tBrightness: 0.60\n"
               "eDP-1 connected 1920x1200+1920+0\n\tBrightness: 1.0\nHDMI-1 disconnected\n")
        with mock.patch("subprocess.run", return_value=mock.Mock(stdout=out)):
            self.assertEqual(brightness._xrandr_levels(), {"DP-1": 0.6, "eDP-1": 1.0})


class IdleClockTest(unittest.TestCase):
    def test_reports_milliseconds_on_this_desktop(self):
        ms = IdleClock().idle_ms()
        if ms is None:
            self.skipTest("no idle source in this environment")
        self.assertIsInstance(ms, int)
        self.assertGreaterEqual(ms, 0)


# ---------------------------------------------------------------- media
def track(**kw):
    s = dict(media._EMPTY, bus="org.mpris.MediaPlayer2.firefox", player="Firefox", title="Song",
             track="/t/1", playing=True, position=10.0, length=200.0, next=True, previous=True)
    s.update(kw)
    return s


class MediaTest(unittest.TestCase):
    def setUp(self):
        with no_threads():
            self.m = media.MediaService()
        self.sent = []
        self.m._send = lambda member, sig=None, body=(): self.sent.append((member, body))

    def test_empty(self):
        self.assertFalse(self.m.available)

    def test_new_track_shows_position(self):
        self.m._apply(track())
        self.assertTrue(self.m.available and self.m.playing)
        self.assertAlmostEqual(self.m.position, 10.0, delta=0.2)
        self.assertTrue(self.m.positionKnown)

    def test_position_advances_while_playing(self):
        self.m._apply(track())
        self.m._base_time -= 5
        self.assertAlmostEqual(self.m.position, 15.0, delta=0.2)

    def test_paused_position_holds(self):
        self.m._apply(track(playing=False))
        self.m._base_time -= 5
        self.assertAlmostEqual(self.m.position, 10.0, delta=0.01)

    def test_seek_holds_when_player_reports_zero(self):
        """Firefox reports pos 0 / no length after a seek: the bar must not snap back."""
        self.m._apply(track())
        self.m.seek(0.5)
        self.assertEqual(self.sent[-1][0], "SetPosition")
        self.m._apply(track(position=0.0, length=0.0))
        self.m._apply_position(0.0)
        self.assertAlmostEqual(self.m.position, 100.0, delta=0.5)
        self.assertEqual(self.m.length, 200.0)

    def test_stale_report_right_after_seek_ignored(self):
        self.m._apply(track())
        self.m.seek(0.5)
        self.m._apply(track(position=11.0))   # poll sent before the seek landed
        self.assertAlmostEqual(self.m.position, 100.0, delta=0.5)

    def test_start_up_mid_track_unknown_then_probe(self):
        self.m._apply(track(position=0.0, length=0.0))
        self.assertFalse(self.m.positionKnown)
        APP.processEvents()
        self.assertIn(("Seek", (0,)), self.sent)
        self.m._apply(track(position=95.0, length=200.0))
        self.assertTrue(self.m.positionKnown)
        self.assertAlmostEqual(self.m.position, 95.0, delta=0.3)

    def test_probe_only_once_per_track(self):
        self.m._apply(track(position=0.0, length=0.0))
        self.m._apply(track(position=0.0, length=0.0, playing=False))
        APP.processEvents()
        self.assertEqual([s for s in self.sent if s[0] == "Seek"], [("Seek", (0,))])

    def test_watched_new_track_starts_at_zero(self):
        self.m._apply(track())
        self.m._apply(track(title="Next song", position=0.0, length=0.0))
        self.assertTrue(self.m.positionKnown)
        self.assertAlmostEqual(self.m.position, 0.0, delta=0.2)

    def test_next_previous_are_real_mpris_calls(self):
        self.m._apply(track())
        self.m.next()
        self.m.previous()
        self.m.playPause()
        self.assertEqual([s[0] for s in self.sent], ["Next", "Previous", "PlayPause"])

    def test_seek_clamped(self):
        self.m._apply(track())
        self.m.seek(1.7)
        self.assertEqual(self.sent[-1][1][1], 200_000_000)

    def test_seek_without_length_does_nothing(self):
        self.m._apply(track(position=0, length=0, playing=False))
        self.m.seek(0.5)
        self.assertNotIn("SetPosition", [s[0] for s in self.sent])

    def test_ticker_runs_only_while_playing(self):
        self.m._apply(track())
        self.assertTrue(self.m._ticker.isActive())
        self.m._apply(track(playing=False))
        self.assertFalse(self.m._ticker.isActive())

    def test_position_clamped_to_length(self):
        self.m._apply(track(position=199.0))
        self.m._base_time -= 30
        self.assertEqual(self.m.position, 200.0)

    def test_player_goes_away(self):
        self.m._apply(track())
        self.m._apply(dict(media._EMPTY))
        self.assertFalse(self.m.available)

    def test_accent_defaults_for_missing_art(self):
        self.assertEqual(media._accent_for(""), media.DEFAULT_ACCENT)
        self.assertEqual(media._accent_for("file:///nonexistent.png"), media.DEFAULT_ACCENT)

    def test_accent_from_red_art(self):
        from PySide6.QtGui import QColor, QImage
        path = Path(tempfile.mkdtemp()) / "red.png"
        img = QImage(20, 20, QImage.Format_RGB32)
        img.fill(QColor("#c01010"))
        img.save(str(path))
        hue = QColor(media._accent_for(path.as_uri())).hsvHueF()
        self.assertTrue(hue < 0.05 or hue > 0.95)

    def test_accent_grey_art(self):
        from PySide6.QtGui import QColor, QImage
        path = Path(tempfile.mkdtemp()) / "grey.png"
        img = QImage(20, 20, QImage.Format_RGB32)
        img.fill(QColor("#777777"))
        img.save(str(path))
        self.assertEqual(media._accent_for(path.as_uri()), "#d6d6dc")


# ---------------------------------------------------------------- audio
class AudioTest(unittest.TestCase):
    def setUp(self):
        with no_threads(), mock.patch("shutil.which", return_value="/usr/bin/wpctl"):
            self.a = audio.AudioService()
        self.ran = []
        self.a._run = self.ran.append

    def test_first_poll_does_not_pop_hud(self):
        spy = Spy(self.a.changed)
        self.a._apply(0.5, False)
        self.assertEqual(len(spy), 0)
        self.assertTrue(self.a.available)

    def test_external_change_pops_hud(self):
        self.a._apply(0.5, False)
        spy = Spy(self.a.changed)
        self.a._apply(0.6, False)
        self.a._apply(0.6, True)
        self.assertEqual(len(spy), 2)

    def test_same_value_no_hud(self):
        self.a._apply(0.5, False)
        spy = Spy(self.a.changed)
        self.a._apply(0.502, False)
        self.assertEqual(len(spy), 0)

    def test_set_volume_clamps_and_unmutes(self):
        self.a._apply(0.5, True)
        self.a.setVolume(1.4)
        self.assertIn(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "0"], self.ran)
        self.assertIn(["wpctl", "set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SINK@", "1.00"], self.ran)
        self.assertEqual(self.a.volume, 1.0)

    def test_nudge_and_mute(self):
        self.a._apply(0.5, False)
        self.a.nudge(-0.05)
        self.assertAlmostEqual(self.a.volume, 0.45)
        self.a.toggleMute()
        self.assertTrue(self.a.muted)

    def test_wpctl_parsers(self):
        w = audio._Wpctl()
        with mock.patch("subprocess.run", return_value=mock.Mock(stdout="Volume: 0.40 [MUTED]\n")):
            self.assertEqual(w.read(), (0.40, True))
        inspect = ' * node.description = "WH-1000XM4"\n * node.name = "bluez_output.AA_BB.1"\n'
        with mock.patch("subprocess.run", return_value=mock.Mock(stdout=inspect)):
            self.assertEqual(w.output(), ("WH-1000XM4", "bluez_output.AA_BB.1"))

    def test_pactl_parser(self):
        p = audio._Pactl()
        outs = [mock.Mock(stdout="Volume: front-left: 26214 /  40% / -23.88 dB"), mock.Mock(stdout="Mute: no")]
        with mock.patch("subprocess.run", side_effect=outs):
            self.assertEqual(p.read(), (0.40, False))


# ---------------------------------------------------------------- battery / mic
class BatteryTest(unittest.TestCase):
    def make(self, cap="80", status="Discharging"):
        root = Path(tempfile.mkdtemp())
        bat = root / "BAT0"
        bat.mkdir()
        (bat / "capacity").write_text(cap)
        (bat / "status").write_text(status)
        real_glob = Path.glob
        with mock.patch.object(Path, "glob", lambda self, pat: real_glob(root, pat)):
            return battery.BatteryService(), bat

    def test_reads_level(self):
        b, _ = self.make()
        self.assertTrue(b.available)
        self.assertEqual(b.percent, 80)
        self.assertFalse(b.charging)

    def test_plug_in_pops_hud_once(self):
        b, bat = self.make()
        spy = Spy(b.pluggedChanged)
        (bat / "status").write_text("Charging")
        b._refresh()
        b._refresh()
        self.assertEqual(len(spy), 1)
        self.assertTrue(b.charging)

    def test_full_counts_as_plugged(self):
        b, _ = self.make(cap="100", status="Full")
        self.assertTrue(b.charging)

    def make_with_charger(self, online="1", cap="100", status="Not charging"):
        root = Path(tempfile.mkdtemp())
        bat, ac = root / "BAT0", root / "AC"
        bat.mkdir()
        ac.mkdir()
        (bat / "type").write_text("Battery\n")
        (bat / "capacity").write_text(cap)
        (bat / "status").write_text(status)
        (ac / "type").write_text("Mains\n")
        (ac / "online").write_text(online + "\n")
        real_glob = Path.glob
        with mock.patch.object(Path, "glob", lambda self, pat: real_glob(root, pat)):
            return battery.BatteryService(), bat, ac

    def test_battery_status_wandering_at_full_charge_does_not_pop_hud(self):
        # charger stays connected; the firmware reports Not charging / Discharging / Full in turn
        b, bat, _ = self.make_with_charger()
        spy = Spy(b.pluggedChanged)
        for status in ("Discharging", "Not charging", "Discharging", "Full", "Not charging"):
            (bat / "status").write_text(status)
            b._refresh()
        self.assertEqual(len(spy), 0)
        self.assertTrue(b.charging)

    def test_charger_online_drives_plugged(self):
        b, bat, ac = self.make_with_charger(online="0", cap="60", status="Discharging")
        self.assertFalse(b.charging)
        self.assertEqual(b.state, "battery")
        spy = Spy(b.pluggedChanged)
        (ac / "online").write_text("1\n")
        (bat / "status").write_text("Charging")
        b._refresh()
        self.assertEqual((len(spy), b.charging, b.state), (1, True, "charging"))
        (ac / "online").write_text("0\n")
        (bat / "status").write_text("Discharging")
        b._refresh()
        self.assertEqual((len(spy), b.charging, b.state), (2, False, "battery"))

    def test_states(self):
        for online, cap, status, state in (("1", "100", "Not charging", "full"), ("1", "100", "Full", "full"),
                                           ("1", "80", "Not charging", "plugged"), ("1", "50", "Charging", "charging"),
                                           ("0", "50", "Discharging", "battery")):
            b, _, _ = self.make_with_charger(online, cap, status)
            self.assertEqual(b.state, state, (online, cap, status))

    def test_level_change_does_not_pop_hud(self):
        b, bat = self.make()
        spy = Spy(b.pluggedChanged)
        (bat / "capacity").write_text("79")
        b._refresh()
        self.assertEqual(b.percent, 79)
        self.assertEqual(len(spy), 0)


class MicrophoneTest(unittest.TestCase):
    def test_running_capture_detected(self):
        root = Path(tempfile.mkdtemp())
        f = root / "status"
        f.write_text("state: RUNNING\n")
        with mock.patch("glob.glob", return_value=[str(f)]):
            self.assertTrue(microphone._recording())
        f.write_text("closed\n")
        with mock.patch("glob.glob", return_value=[str(f)]):
            self.assertFalse(microphone._recording())

    def test_service_toggles(self):
        with mock.patch.object(microphone, "_recording", return_value=False):
            m = microphone.MicrophoneService()
        spy = Spy(m.activeChanged)
        with mock.patch.object(microphone, "_recording", return_value=True):
            m._refresh()
            m._refresh()
        self.assertTrue(m.active)
        self.assertEqual(len(spy), 1)


# ---------------------------------------------------------------- bluetooth
class FakeBus:
    def __init__(self, objects):
        self.objects = objects

    def send_and_get_reply(self, msg, timeout=None):
        from jeepney import MessageType
        return mock.Mock(header=mock.Mock(message_type=MessageType.method_return), body=(self.objects,))


def bt_device(name, connected=True, battery=None, icon="audio-headset"):
    ifaces = {bluetooth.DEVICE: {"Alias": ("s", name), "Connected": ("b", connected), "Icon": ("s", icon)}}
    if battery is not None:
        ifaces[bluetooth.BATTERY] = {"Percentage": ("y", battery)}
    return ifaces


class BluetoothTest(unittest.TestCase):
    def setUp(self):
        with no_threads():
            self.b = bluetooth.BluetoothService()

    def test_connected_devices_parsed(self):
        bus = FakeBus({
            "/org/bluez/hci0/dev_1": bt_device("Buds", battery=70),
            "/org/bluez/hci0/dev_2": bt_device("Mouse", icon="input-mouse"),
            "/org/bluez/hci0/dev_3": bt_device("Old", connected=False),
            "/org/bluez/hci0": {"org.bluez.Adapter1": {}},
        })
        got = self.b._connected(bus)
        self.assertEqual(sorted(d["name"] for d in got.values()), ["Buds", "Mouse"])
        self.assertEqual(got["/org/bluez/hci0/dev_1"], {"name": "Buds", "battery": 70, "audio": True})
        self.assertEqual(got["/org/bluez/hci0/dev_2"]["battery"], -1)
        self.assertFalse(got["/org/bluez/hci0/dev_2"]["audio"])

    def test_devices_list_updates(self):
        spy = Spy(self.b.devicesChanged)
        devs = [{"name": "Buds", "battery": 70, "audio": True}]
        self.b._apply(devs)
        self.b._apply(list(devs))
        self.assertEqual(self.b.devices, devs)
        self.assertEqual(len(spy), 1)


# ---------------------------------------------------------------- windows / Wayland
class WaylandTest(unittest.TestCase):
    def test_session_detection(self):
        from linux_island import system
        with mock.patch.dict(os.environ, {"XDG_SESSION_TYPE": "wayland"}, clear=False):
            self.assertTrue(system.wayland_session())
        with mock.patch.dict(os.environ, {"XDG_SESSION_TYPE": "x11", "WAYLAND_DISPLAY": "wayland-0"}):
            self.assertTrue(system.wayland_session())             # e.g. a nested Wayland compositor
        env = {k: v for k, v in os.environ.items() if k not in ("WAYLAND_DISPLAY",)}
        env["XDG_SESSION_TYPE"] = "x11"
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertFalse(system.wayland_session())

    def test_no_home_card_in_a_wayland_session(self):
        """X11 can't see native Wayland windows: the card would swoop in and never leave."""
        from linux_island.services import desktop
        with mock.patch.object(desktop.system, "wayland_session", return_value=True), \
             mock.patch.object(desktop.QGuiApplication, "platformName", return_value="xcb"), \
             mock.patch.object(desktop, "_X11Windows") as x11, mock.patch("builtins.print"):
            d = desktop.DesktopService(use_shell=False)
        x11.assert_not_called()
        self.assertEqual(d.emptyScreens, [])


class ShellExtensionTest(unittest.TestCase):
    """With the GNOME helper extension, its answers decide; without it, X11 (or nothing on Wayland)."""
    def make(self):
        from linux_island.services import desktop
        with mock.patch.object(desktop.system, "wayland_session", return_value=True), \
             mock.patch.object(desktop, "ShellWindows") as shell, mock.patch("builtins.print"):
            d = desktop.DesktopService()
        return d, shell

    def test_extension_answers_drive_the_home_card(self):
        d, shell = self.make()
        self.assertEqual(d.source, "none")                       # Wayland, extension not heard from yet
        changes = Spy(d.emptyChanged)
        d._apply_shell(["DP-1"])                                  # extension: DP-1 has no windows
        self.assertEqual((d.source, d.emptyScreens), ("gnome-extension", ["DP-1"]))
        d._apply_shell([])                                        # a (native Wayland) window opened there
        self.assertEqual(d.emptyScreens, [])
        self.assertEqual(len(changes), 2)

    def test_losing_the_extension_falls_back(self):
        d, shell = self.make()
        d._apply_shell(["DP-1"])
        d._apply_shell(None)                                      # extension disabled / shell restarted
        self.assertEqual((d.source, d.emptyScreens), ("none", []))   # on Wayland: no card rather than a stuck one

    def test_monitor_names_follow_hotplug(self):
        d, shell = self.make()
        d._names_changed()
        shell.return_value.set_names.assert_called_once()

    def test_client_reports_unavailable_once(self):
        from linux_island.services import shell_windows
        results = []
        with mock.patch.object(shell_windows, "open_dbus_connection", side_effect=OSError("no bus")), \
             mock.patch.object(shell_windows.time, "sleep", side_effect=[None, SystemExit]):
            c = shell_windows.ShellWindows.__new__(shell_windows.ShellWindows)
            c._names, c._on_result, c._wake = ["DP-1"], results.append, __import__("queue").Queue()
            with self.assertRaises(SystemExit):
                c._run()
        self.assertEqual(results, [None])                         # said once, not every retry


# ---------------------------------------------------------------- config
class ConfigTest(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "linux-island" / "config.json"
        self.patch = mock.patch.object(config, "CONFIG_PATH", self.path)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()

    def test_defaults_without_file(self):
        self.assertEqual(config.load(), config.DEFAULTS)

    def test_round_trip_and_unknown_keys_dropped(self):
        config.save({**config.DEFAULTS, "monitors": ["DP-1"]})
        data = json.loads(self.path.read_text())
        data["bogus"] = 1
        self.path.write_text(json.dumps(data))
        cfg = config.load()
        self.assertEqual(cfg["monitors"], ["DP-1"])
        self.assertNotIn("bogus", cfg)

    def test_broken_file_falls_back(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{not json")
        with mock.patch("builtins.print"):
            self.assertEqual(config.load(), config.DEFAULTS)


if __name__ == "__main__":
    unittest.main()


class ThreadEmitTest(unittest.TestCase):
    def test_emit_after_the_receiver_is_gone_ends_the_thread_quietly(self):
        import threading
        from linux_island.services.threads import emit

        class Gone:
            def emit(self, *args):
                raise RuntimeError("Signal source has been deleted")

        errors = []
        old = threading.excepthook
        threading.excepthook = lambda a: errors.append(a)
        try:
            t = threading.Thread(target=lambda: (emit(Gone(), 1), errors.append("kept going")))
            t.start(); t.join()
        finally:
            threading.excepthook = old
        # Python's default thread hook prints nothing for SystemExit; the loop doesn't carry on
        self.assertEqual([getattr(e, "exc_type", e) for e in errors], [SystemExit])
