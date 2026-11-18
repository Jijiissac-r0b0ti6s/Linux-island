"""User configuration: ~/.config/linux-island/config.json (all keys optional).

The settings panel (`linux-island --settings`) edits this file; the running island notices
the change and applies it straight away.
"""
import json
import os
from pathlib import Path

CONFIG_PATH = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "linux-island" / "config.json"

DEFAULTS = {
    # --- where ---
    # "all", "primary", or a list of output names such as ["eDP-1", "DP-1"]
    "monitors": "all",
    # gap in pixels between the top of the screen (or panel) and the island
    "top_margin": 2,

    # --- look ---
    # "vivid": colours follow the album art; "classic": the accent colour below throughout
    "theme": "vivid",
    "accent_color": "#34c759",      # equaliser, play button, seek bar (when not taken from the art)
    "pill_color": "#000000",        # background of the pill and the cards
    # Qt date format, see https://doc.qt.io/qt-6/qml-qtqml-qt.html#formatDateTime-method
    "clock_format": "ddd d MMM  hh:mm",
    # how long volume / brightness / power / device pop-ups stay visible
    "hud_timeout_ms": 1600,

    # --- features (true = on) ---
    "show_media": True,             # now playing: artwork, title, controls
    "popup_volume": True,           # pop-up when the volume changes
    "popup_brightness": True,       # pop-up when the brightness keys are used
    "popup_power": True,            # pop-up when the charger is plugged in / out
    "popup_devices": True,          # pop-up when Bluetooth devices / headphones connect
    "dot_camera": True,             # green dot while the camera is in use
    "dot_mic": True,                # orange dot while the microphone is in use
    "open_on_hover": True,          # pointer over the pill opens it (a click always does)
    "scroll_volume": True,          # scrolling over the pill changes the volume
    # when every window on a monitor is minimised, swoop to a large card with the time and a calendar
    "home_on_empty_desktop": True,
    # where the centre of that card sits, as a fraction of the screen height (0.5 = dead centre)
    "home_position": 0.36,
    # screensaver: after this many idle minutes the pill swoops into a clock card and the screen fades
    # to a black full-screen clock around it (0 = off)
    "screensaver_minutes": 5,
    # where the screensaver (and lock fade) shows: "all" connected monitors, or only the "island" ones
    "screensaver_screens": "all",
    # locking the screen: the same card and black fade first; unlocking fades back to the pill
    "lock_transition": True,
}

# shown in the settings panel, in this order
FEATURES = [
    ("show_media", "Now playing", "Artwork, title and controls for music and video"),
    ("popup_volume", "Volume pop-up", "When the volume changes"),
    ("popup_brightness", "Brightness pop-up", "When the brightness keys are used"),
    ("popup_power", "Charger pop-up", "When the charger is plugged in or out"),
    ("popup_devices", "Device pop-up", "Bluetooth devices and headphones connecting"),
    ("dot_camera", "Camera indicator", "Green dot while an app uses the camera"),
    ("dot_mic", "Microphone indicator", "Orange dot while an app records"),
    ("open_on_hover", "Open on hover", "Pointer over the pill opens it (a click always does)"),
    ("scroll_volume", "Scroll for volume", "Scrolling over the pill changes the volume"),
    ("home_on_empty_desktop", "Home card", "Large clock and calendar when every window is minimised"),
    ("lock_transition", "Lock animation", "Clock card and black fade before the lock screen"),
]


def _valid(key, value):
    """The value if it has the right type for `key`, else the default."""
    default = DEFAULTS[key]
    if key == "monitors":
        if value in ("all", "primary") or (isinstance(value, list) and all(isinstance(v, str) for v in value)):
            return value
        return default
    if isinstance(default, bool):
        return value if isinstance(value, bool) else default
    if isinstance(default, (int, float)):
        return value if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0 else default
    if key == "screensaver_screens":
        return value if value in ("all", "island") else default
    if key.endswith("_color"):
        return value if isinstance(value, str) and value.startswith("#") and len(value) in (4, 7, 9) else default
    return value if isinstance(value, type(default)) else default


def load() -> dict:
    cfg = dict(DEFAULTS)
    try:
        user = json.loads(CONFIG_PATH.read_text())
    except FileNotFoundError:
        return cfg
    except (OSError, ValueError) as e:
        print(f"linux-island: ignoring {CONFIG_PATH}: {e}")
        return cfg
    if isinstance(user, dict):
        cfg.update({k: _valid(k, v) for k, v in user.items() if k in DEFAULTS})
    return cfg


def save(cfg: dict) -> None:
    """Write only what differs from the defaults, atomically (the island watches this file)."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    changed = {k: v for k, v in cfg.items() if k in DEFAULTS and v != DEFAULTS[k]}
    tmp = CONFIG_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(changed, indent=2) + "\n")
    tmp.replace(CONFIG_PATH)
