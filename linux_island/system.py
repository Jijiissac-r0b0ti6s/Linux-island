"""Desktop integration that needs no Qt: start on login, and the GNOME lock shortcut."""
import ast
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
AUTOSTART = CONFIG_HOME / "autostart" / "linux-island.desktop"   # per user
SYSTEM_AUTOSTART = Path("/etc/xdg/autostart/linux-island.desktop")   # installed by the package

KEYS = "org.gnome.settings-daemon.plugins.media-keys"
SHORTCUT = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/linux-island-lock/"


def wayland_session():
    """True in a Wayland session (even when the island itself runs through XWayland): X11 then only
    sees the apps that use XWayland, not native Wayland ones such as recent Chrome, Brave or VS Code."""
    return os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland" or bool(os.environ.get("WAYLAND_DISPLAY"))


def runtime_dir():
    """Where single-instance locks and command sockets live (the same place, so anything that can
    see one can reach the other)."""
    return os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"


def launcher():
    """The command that starts the island: the installed `linux-island` launcher (it tells us its own
    path), or this Python when running from a development checkout."""
    installed = os.environ.get("LINUX_ISLAND_LAUNCHER", "")
    if installed and os.path.isfile(installed) and os.access(installed, os.X_OK):
        return shlex.quote(installed)
    return f"{shlex.quote(sys.executable)} -m linux_island"


# ---- start on login -------------------------------------------------------------
def _entry(hidden=False):
    return ("[Desktop Entry]\nType=Application\nName=Linux Island\nComment=Dynamic island for the desktop\n"
            f"Exec={launcher()}\nIcon=linux-island\nX-GNOME-Autostart-enabled={'false' if hidden else 'true'}\n"
            + ("Hidden=true\n" if hidden else ""))


def autostart_enabled():
    if AUTOSTART.exists():
        text = AUTOSTART.read_text()
        return "Hidden=true" not in text and "X-GNOME-Autostart-enabled=false" not in text
    return SYSTEM_AUTOSTART.exists()


def set_autostart(enable):
    """Per user. With the package's system-wide entry, turning it off writes a hidden override."""
    if enable:
        if SYSTEM_AUTOSTART.exists():
            AUTOSTART.unlink(missing_ok=True)     # the system entry applies again
        else:
            AUTOSTART.parent.mkdir(parents=True, exist_ok=True)
            AUTOSTART.write_text(_entry())
    elif SYSTEM_AUTOSTART.exists():
        AUTOSTART.parent.mkdir(parents=True, exist_ok=True)
        AUTOSTART.write_text(_entry(hidden=True))
    else:
        AUTOSTART.unlink(missing_ok=True)


# ---- GNOME lock shortcut ------------------------------------------------------------
def _gsettings(*args):
    try:
        return subprocess.run(["gsettings", *args], capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _strv(text):
    try:
        return ast.literal_eval(text.replace("@as ", "") or "[]")
    except (ValueError, SyntaxError):
        return []


def lock_shortcut_available():
    return bool(shutil.which("gsettings")) and bool(_gsettings("get", KEYS, "custom-keybindings"))


def lock_shortcut_enabled():
    return SHORTCUT in _strv(_gsettings("get", KEYS, "custom-keybindings"))


def set_lock_shortcut(enable):
    """Route GNOME's lock shortcut through the island (so its animation plays first), or give it back."""
    paths = _strv(_gsettings("get", KEYS, "custom-keybindings"))
    entry = f"{KEYS}.custom-keybinding:{SHORTCUT}"
    if enable:
        binding = _strv(_gsettings("get", KEYS, "screensaver"))
        binding = binding[0] if binding else _gsettings("get", entry, "binding").strip("'") or "<Super>l"
        _gsettings("set", entry, "name", "Lock screen (Linux Island)")
        # falls back to a plain lock if the island is gone (e.g. the package was removed)
        command = "sh -c " + shlex.quote(f"{launcher()} --lock || loginctl lock-session")
        _gsettings("set", entry, "command", '"' + command.replace("\\", "\\\\").replace('"', '\\"') + '"')
        _gsettings("set", entry, "binding", binding)
        if SHORTCUT not in paths:
            _gsettings("set", KEYS, "custom-keybindings", str(paths + [SHORTCUT]))
        _gsettings("set", KEYS, "screensaver", "[]")   # free the key for the island
        return binding
    binding = _gsettings("get", entry, "binding").strip("'") or "<Control><Alt>l"
    if SHORTCUT in paths:
        _gsettings("set", KEYS, "custom-keybindings", str([p for p in paths if p != SHORTCUT]))
        _gsettings("reset", entry, "binding")
        _gsettings("set", KEYS, "screensaver", str([binding]))
    return binding


# ---- GNOME Shell helper extension (window information in Wayland sessions) -------------------------
EXTENSION_UUID = "linux-island@jijiissac-r0b0ti6s.github.io"
_EXTENSION_STATES = {1: "active", 2: "off", 3: "error", 4: "out-of-date", 6: "off", 99: "missing"}


def _shell_extensions_call(method, *args):
    from jeepney import DBusAddress, MessageType, new_method_call
    from jeepney.io.blocking import open_dbus_connection
    addr = DBusAddress("/org/gnome/Shell/Extensions", bus_name="org.gnome.Shell.Extensions",
                       interface="org.gnome.Shell.Extensions")
    conn = open_dbus_connection("SESSION")
    try:
        reply = conn.send_and_get_reply(new_method_call(addr, method, "s" if args else None, args), timeout=2)
    finally:
        conn.close()
    if reply.header.message_type != MessageType.method_return:
        raise RuntimeError(str(reply.body))
    return reply.body[0]


def helper_extension_state():
    """"active", "off", "error", "out-of-date", "missing" (installed after GNOME started: log out and
    back in), "not-installed", or "no-gnome" when this isn't a GNOME Shell session."""
    try:
        info = _shell_extensions_call("GetExtensionInfo", EXTENSION_UUID)
    except Exception:
        return "no-gnome"
    if not info:
        on_disk = any(os.path.isdir(os.path.join(d, "gnome-shell", "extensions", EXTENSION_UUID)) for d in
                      [os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "/usr/share",
                       "/usr/local/share"])
        return "missing" if on_disk else "not-installed"
    state = info.get("state", ("d", 99))[1]
    return _EXTENSION_STATES.get(int(state), "off")


def enable_helper_extension():
    """Turn the helper on; if GNOME hasn't picked it up yet (just installed), it is added to the list of
    extensions to start at the next login instead. Returns the new state."""
    try:
        if _shell_extensions_call("EnableExtension", EXTENSION_UUID):
            return helper_extension_state()
    except Exception:
        pass
    current = _strv(_gsettings("get", "org.gnome.shell", "enabled-extensions"))
    if EXTENSION_UUID not in current:
        _gsettings("set", "org.gnome.shell", "enabled-extensions", str(current + [EXTENSION_UUID]))
    return helper_extension_state()

