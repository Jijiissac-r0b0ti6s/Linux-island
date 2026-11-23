"""Desktop integration that needs no Qt: start on login, launching, and the GNOME lock shortcut (Linux)."""
import ast
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

WINDOWS = sys.platform == "win32"

CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
AUTOSTART = CONFIG_HOME / "autostart" / "linux-island.desktop"   # per user
SYSTEM_AUTOSTART = Path("/etc/xdg/autostart/linux-island.desktop")   # installed by the package

KEYS = "org.gnome.settings-daemon.plugins.media-keys"
SHORTCUT = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/linux-island-lock/"


def wayland_session():
    """True in a Wayland session (even when the island itself runs through XWayland): X11 then only
    sees the apps that use XWayland, not native Wayland ones such as recent Chrome, Brave or VS Code."""
    if WINDOWS:
        return False
    return os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland" or bool(os.environ.get("WAYLAND_DISPLAY"))


def runtime_dir():
    """Where single-instance locks and command sockets live (the same place, so anything that can
    see one can reach the other)."""
    if WINDOWS:
        return os.environ.get("LOCALAPPDATA") or str(Path.home())
    return os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"


def socket_name(name):
    """Full name of a command socket. Linux: a file next to the lock; Windows: a named pipe, which has
    no directory, so it carries the user name instead."""
    if WINDOWS:
        user = re.sub(r"[^A-Za-z0-9_.-]", "_", os.environ.get("USERNAME", "user"))
        return f"{name}-{user}"
    return name if name.startswith("/") else os.path.join(runtime_dir(), name)


def launcher_args():
    """The command that starts the island, as a list: the installed launcher (it tells us its own path),
    or this Python when running from a development checkout. On Windows, pythonw (no console window)."""
    installed = os.environ.get("LINUX_ISLAND_LAUNCHER", "")
    if installed and os.path.isfile(installed) and (WINDOWS or os.access(installed, os.X_OK)):
        return [installed]
    python = sys.executable
    if WINDOWS:
        windowless = os.path.join(os.path.dirname(python), "pythonw.exe")
        python = windowless if os.path.isfile(windowless) else python
    return [python, "-m", "linux_island"]


def launcher():
    """launcher_args() as one command line for this system's shell."""
    args = launcher_args()
    return subprocess.list2cmdline(args) if WINDOWS else " ".join(shlex.quote(a) for a in args)


def spawn(args):
    """Start another process that outlives this one (the settings panel, the island)."""
    if WINDOWS:
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        return subprocess.Popen(args, creationflags=flags, close_fds=True,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
    return subprocess.Popen(args, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ---- start on login -------------------------------------------------------------
def _entry(hidden=False):
    return ("[Desktop Entry]\nType=Application\nName=Linux Island\nComment=Dynamic island for the desktop\n"
            f"Exec={launcher()}\nIcon=linux-island\nX-GNOME-Autostart-enabled={'false' if hidden else 'true'}\n"
            + ("Hidden=true\n" if hidden else ""))


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"   # Windows: per-user programs started at sign-in
RUN_VALUE = "Linux Island"


def _win_autostart(enable=None):
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        if enable is True:
            winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, launcher())
        elif enable is False:
            try:
                winreg.DeleteValue(key, RUN_VALUE)
            except FileNotFoundError:
                pass
        try:
            return bool(winreg.QueryValueEx(key, RUN_VALUE)[0])
        except FileNotFoundError:
            return False


def autostart_enabled():
    if WINDOWS:
        return _win_autostart()
    if AUTOSTART.exists():
        text = AUTOSTART.read_text()
        return "Hidden=true" not in text and "X-GNOME-Autostart-enabled=false" not in text
    return SYSTEM_AUTOSTART.exists()


def set_autostart(enable):
    """Per user. With the package's system-wide entry, turning it off writes a hidden override."""
    if WINDOWS:
        _win_autostart(bool(enable))
        return
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
    if WINDOWS:
        return False
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
    back in), "pending" (turned on, starts at the next login), "not-installed", or "no-gnome" when
    this isn't a GNOME Shell session."""
    if WINDOWS:
        return "no-gnome"
    try:
        info = _shell_extensions_call("GetExtensionInfo", EXTENSION_UUID)
    except Exception:
        return "no-gnome"
    if not info:
        on_disk = any(os.path.isdir(os.path.join(d, "gnome-shell", "extensions", EXTENSION_UUID)) for d in
                      [os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "/usr/share",
                       "/usr/local/share"])
        if not on_disk:
            return "not-installed"
        # turned on already, GNOME just hasn't loaded it yet (that happens at login)
        enabled = EXTENSION_UUID in _strv(_gsettings("get", "org.gnome.shell", "enabled-extensions"))
        return "pending" if enabled else "missing"
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

