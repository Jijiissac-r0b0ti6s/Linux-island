"""Windows decisions that need no Windows: kept apart from the Win32 calls so they're tested on Linux too."""
import re

WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
WS_EX_APPWINDOW = 0x00040000

# the desktop, taskbars and shell surfaces: visible, but not application windows
SHELL_CLASSES = {
    "Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd", "Windows.UI.Core.CoreWindow",
    "NotifyIconOverflowWindow", "TopLevelWindowForOverflowXamlIsland", "XamlExplorerHostIslandWindow",
    "ForegroundStaging", "MultitaskingViewFrame", "TaskListThumbnailWnd",
}


def is_app_window(w, own_pid):
    """Would this window show in Alt+Tab? (`w` is api.WindowInfo, already visible and not minimised.)"""
    if w.pid == own_pid or w.cloaked or w.cls in SHELL_CLASSES:
        return False
    if w.exstyle & WS_EX_TRANSPARENT:          # click-through overlays (game / GPU overlays)
        return False
    if not w.exstyle & WS_EX_APPWINDOW:
        if w.exstyle & (WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE) or w.owner:
            return False                        # tool palettes, pop-ups, owned dialogs (their owner counts)
    if w.title_len == 0 or w.size[0] < 40 or w.size[1] < 40:
        return False
    return True


def empty_screens(windows, screen_of_monitor, screen_names, own_pid):
    """Names of the screens with no application window. `screen_of_monitor` maps HMONITOR -> Qt screen name."""
    used = {screen_of_monitor.get(w.monitor) for w in windows if w.monitor and is_app_window(w, own_pid)}
    return sorted(n for n in screen_names if n not in used)


def match_screen(device, rect, screens):
    """Qt screen name for a Win32 monitor (device "\\\\.\\DISPLAY1", rect in physical pixels).

    `screens` are (name, x, y, width, height, device_pixel_ratio) from QScreen. Qt names screens after the
    device on most versions; otherwise Qt keeps each screen's top-left corner in physical pixels."""
    left, top, right, bottom = rect
    for name, *_ in screens:
        if name == device:
            return name
    for name, x, y, w, h, dpr in screens:
        if (x, y) == (left, top) or (abs(x * dpr - left) <= 2 and abs(y * dpr - top) <= 2):
            return name
    sized = [name for name, x, y, w, h, dpr in screens
             if abs(w * dpr - (right - left)) <= 2 and abs(h * dpr - (bottom - top)) <= 2]
    return sized[0] if len(sized) == 1 else None


def pnp_code(device_id):
    """"BOE0867" from "MONITOR\\BOE0867\\{...}\\0001" or WMI's "DISPLAY\\BOE0867\\4&2a6e&0&UID8_0"."""
    parts = re.split(r"[\\#]", device_id or "")
    return parts[1].upper() if len(parts) > 1 else ""


def battery_state(ac_line, flag, percent):
    """(has a battery, percent, on the charger) from GetSystemPowerStatus."""
    has = flag != 255 and not flag & 128   # 128: no system battery, 255: unknown
    return has, (percent if percent <= 100 else 0), ac_line == 1


def charge_state(plugged, flag, percent):
    """"charging", "full", "plugged" (connected, not charging) or "battery", like the Linux service."""
    if not plugged:
        return "battery"
    if flag & 8:   # BATTERY_FLAG_CHARGING
        return "charging"
    return "full" if percent >= 100 else "plugged"


def consent_app_name(key):
    """App name from a CapabilityAccessManager ConsentStore key: a packaged app's family name
    ("Microsoft.WindowsCamera_8wekyb3d8bbwe") or, under NonPackaged, an exe path with # for \\."""
    if "#" in key or key.lower().endswith(".exe"):
        exe = key.replace("#", "\\").rsplit("\\", 1)[-1]
        return re.sub(r"\.exe$", "", exe, flags=re.I)
    name = key.split("_", 1)[0]
    name = name.rsplit(".", 1)[-1] if "." in name else name
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name)   # WindowsCamera -> Windows Camera


def in_use(start, stop):
    """ConsentStore keeps LastUsedTimeStart / LastUsedTimeStop: stop is 0 while the app still uses it."""
    return bool(start) and not stop


PLAYER_NAMES = {
    "spotify": "Spotify", "chrome": "Chrome", "msedge": "Edge", "firefox": "Firefox", "308046b0af4a39cb": "Firefox",
    "vlc": "VLC", "brave": "Brave", "opera": "Opera", "zunemusic": "Media Player", "microsoft.zunemusic": "Media Player",
    "foobar2000": "foobar2000", "musicbee": "MusicBee", "itunes": "iTunes", "applemusic": "Apple Music",
}


def player_name(app_id):
    """A readable player name from a media session's AppUserModelID ("Spotify.exe", "Chrome",
    "Microsoft.ZuneMusic_8wekyb3d8bbwe!Microsoft.ZuneMusic", "308046B0AF4A39CB" = Firefox)."""
    base = (app_id or "").split("!")[0].split("_")[0]
    base = re.sub(r"\.exe$", "", base.rsplit("\\", 1)[-1], flags=re.I)
    key = base.lower()
    if key in PLAYER_NAMES:
        return PLAYER_NAMES[key]
    last = base.rsplit(".", 1)[-1]
    return PLAYER_NAMES.get(last.lower(), last[:1].upper() + last[1:]) if last else ""
