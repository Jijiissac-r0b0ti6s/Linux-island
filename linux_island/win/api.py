"""The Win32 calls the Windows services need, through ctypes (nothing to install).

Only imported on Windows. Decisions that can be made without Windows live in `logic.py`, so they
are tested on Linux too.
"""
import ctypes
from collections import namedtuple
from ctypes import wintypes as W

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
try:
    dwmapi = ctypes.WinDLL("dwmapi")
except OSError:
    dwmapi = None
try:
    dxva2 = ctypes.WinDLL("dxva2")   # DDC/CI: brightness of external monitors
except OSError:
    dxva2 = None

# fixed-width types: the same as wintypes' on Windows, and the same size everywhere (so tests on Linux
# check the real structure layouts)
DWORD, UINT, LONG = ctypes.c_uint32, ctypes.c_uint32, ctypes.c_int32
HANDLE = ctypes.c_void_p


class RECT(ctypes.Structure):
    _fields_ = [("left", LONG), ("top", LONG), ("right", LONG), ("bottom", LONG)]


INVALID_HANDLE = ctypes.c_void_p(-1).value


# ---- idle time ----------------------------------------------------------------------
class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", UINT), ("dwTime", DWORD)]


user32.GetLastInputInfo.argtypes = [ctypes.POINTER(LASTINPUTINFO)]
user32.GetLastInputInfo.restype = W.BOOL
kernel32.GetTickCount.restype = DWORD


def idle_ms():
    """Milliseconds since the last keyboard or mouse input in this session."""
    info = LASTINPUTINFO(ctypes.sizeof(LASTINPUTINFO), 0)
    if not user32.GetLastInputInfo(ctypes.byref(info)):
        return None
    return (kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF   # both wrap after 49 days


# ---- battery ------------------------------------------------------------------------
class SYSTEM_POWER_STATUS(ctypes.Structure):
    _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
                ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
                ("BatteryLifeTime", DWORD), ("BatteryFullLifeTime", DWORD)]


kernel32.GetSystemPowerStatus.argtypes = [ctypes.POINTER(SYSTEM_POWER_STATUS)]
kernel32.GetSystemPowerStatus.restype = W.BOOL


def power_status():
    """(ACLineStatus, BatteryFlag, BatteryLifePercent), or None."""
    s = SYSTEM_POWER_STATUS()
    if not kernel32.GetSystemPowerStatus(ctypes.byref(s)):
        return None
    return s.ACLineStatus, s.BatteryFlag, s.BatteryLifePercent


# ---- lock screen ----------------------------------------------------------------------
user32.OpenInputDesktop.argtypes = [DWORD, W.BOOL, DWORD]
user32.OpenInputDesktop.restype = HANDLE
user32.GetUserObjectInformationW.argtypes = [HANDLE, ctypes.c_int, ctypes.c_void_p, DWORD, ctypes.POINTER(DWORD)]
user32.GetUserObjectInformationW.restype = W.BOOL
user32.CloseDesktop.argtypes = [HANDLE]
user32.LockWorkStation.restype = W.BOOL


def input_desktop_name():
    """"Default" while the user's desktop takes input; None when it can't be opened (the lock screen,
    Ctrl+Alt+Del or a UAC prompt is up: those run on Winlogon's secure desktop)."""
    desk = user32.OpenInputDesktop(0, False, 0x0001)   # DESKTOP_READOBJECTS
    if not desk:
        return None
    try:
        buf = ctypes.create_unicode_buffer(256)
        needed = DWORD()
        if not user32.GetUserObjectInformationW(desk, 2, buf, ctypes.sizeof(buf), ctypes.byref(needed)):   # UOI_NAME
            return None
        return buf.value
    finally:
        user32.CloseDesktop(desk)


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", DWORD), ("cntUsage", DWORD), ("th32ProcessID", DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", DWORD), ("cntThreads", DWORD),
                ("th32ParentProcessID", DWORD), ("pcPriClassBase", LONG), ("dwFlags", DWORD),
                ("szExeFile", W.WCHAR * 260)]


kernel32.CreateToolhelp32Snapshot.argtypes = [DWORD, DWORD]
kernel32.CreateToolhelp32Snapshot.restype = HANDLE
kernel32.Process32FirstW.argtypes = [HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
kernel32.Process32FirstW.restype = W.BOOL
kernel32.Process32NextW.argtypes = [HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
kernel32.Process32NextW.restype = W.BOOL
kernel32.CloseHandle.argtypes = [HANDLE]


def process_running(exe):
    """Is a process called `exe` (e.g. "LogonUI.exe") running? Case-insensitive."""
    snap = kernel32.CreateToolhelp32Snapshot(0x2, 0)   # TH32CS_SNAPPROCESS
    if not snap or snap == INVALID_HANDLE:
        return False
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
        exe = exe.lower()
        while ok:
            if entry.szExeFile.lower() == exe:
                return True
            ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
        return False
    finally:
        kernel32.CloseHandle(snap)


def session_locked():
    """The lock screen is up. The secure desktop alone isn't enough (a UAC prompt uses it too), so
    LogonUI, which draws the lock and Ctrl+Alt+Del screens, has to be running as well."""
    name = input_desktop_name()
    if name is not None and name.lower() == "default":
        return False
    return process_running("LogonUI.exe")


def lock_workstation():
    return bool(user32.LockWorkStation())


# ---- monitors --------------------------------------------------------------------------
Monitor = namedtuple("Monitor", "handle device rect primary")   # rect: (left, top, right, bottom), physical px


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [("cbSize", DWORD), ("rcMonitor", RECT), ("rcWork", RECT), ("dwFlags", DWORD),
                ("szDevice", W.WCHAR * 32)]


MONITORENUMPROC = ctypes.WINFUNCTYPE(W.BOOL, HANDLE, HANDLE, ctypes.POINTER(RECT), W.LPARAM)
user32.EnumDisplayMonitors.argtypes = [HANDLE, ctypes.POINTER(RECT), MONITORENUMPROC, W.LPARAM]
user32.EnumDisplayMonitors.restype = W.BOOL
user32.GetMonitorInfoW.argtypes = [HANDLE, ctypes.POINTER(MONITORINFOEXW)]
user32.GetMonitorInfoW.restype = W.BOOL


def monitor_info(handle):
    info = MONITORINFOEXW()
    info.cbSize = ctypes.sizeof(MONITORINFOEXW)
    if not user32.GetMonitorInfoW(handle, ctypes.byref(info)):
        return None
    r = info.rcMonitor
    return Monitor(handle, info.szDevice, (r.left, r.top, r.right, r.bottom), bool(info.dwFlags & 1))


def monitors():
    handles = []

    @MONITORENUMPROC
    def collect(handle, _hdc, _rect, _data):
        handles.append(handle)
        return True

    user32.EnumDisplayMonitors(None, None, collect, 0)
    return [m for m in (monitor_info(h) for h in handles) if m]


class DISPLAY_DEVICEW(ctypes.Structure):
    _fields_ = [("cb", DWORD), ("DeviceName", W.WCHAR * 32), ("DeviceString", W.WCHAR * 128),
                ("StateFlags", DWORD), ("DeviceID", W.WCHAR * 128), ("DeviceKey", W.WCHAR * 128)]


user32.EnumDisplayDevicesW.argtypes = [W.LPCWSTR, DWORD, ctypes.POINTER(DISPLAY_DEVICEW), DWORD]
user32.EnumDisplayDevicesW.restype = W.BOOL


def monitor_device_ids(device):
    """Device IDs ("MONITOR\\BOE0867\\{...}\\0001") of the panels on a display such as "\\\\.\\DISPLAY1"."""
    ids, i = [], 0
    while True:
        dd = DISPLAY_DEVICEW()
        dd.cb = ctypes.sizeof(DISPLAY_DEVICEW)
        if not user32.EnumDisplayDevicesW(device, i, ctypes.byref(dd), 0):
            return ids
        ids.append(dd.DeviceID)
        i += 1


# ---- application windows ---------------------------------------------------------------------
WNDENUMPROC = ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
user32.EnumWindows.argtypes = [WNDENUMPROC, W.LPARAM]
user32.EnumWindows.restype = W.BOOL
user32.IsWindowVisible.argtypes = [W.HWND]
user32.IsWindowVisible.restype = W.BOOL
user32.IsIconic.argtypes = [W.HWND]
user32.IsIconic.restype = W.BOOL
user32.GetWindow.argtypes = [W.HWND, UINT]
user32.GetWindow.restype = W.HWND
user32.GetWindowLongPtrW.argtypes = [W.HWND, ctypes.c_int]
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.GetWindowThreadProcessId.argtypes = [W.HWND, ctypes.POINTER(DWORD)]
user32.GetWindowThreadProcessId.restype = DWORD
user32.GetWindowRect.argtypes = [W.HWND, ctypes.POINTER(RECT)]
user32.GetWindowRect.restype = W.BOOL
user32.GetClassNameW.argtypes = [W.HWND, W.LPWSTR, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int
user32.GetWindowTextLengthW.argtypes = [W.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.MonitorFromWindow.argtypes = [W.HWND, DWORD]
user32.MonitorFromWindow.restype = HANDLE
if dwmapi:
    dwmapi.DwmGetWindowAttribute.argtypes = [W.HWND, DWORD, ctypes.c_void_p, DWORD]
    dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long

WindowInfo = namedtuple("WindowInfo", "hwnd pid cls title_len exstyle owner cloaked size monitor")


def _cloaked(hwnd):
    if not dwmapi:
        return False
    value = DWORD()
    if dwmapi.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(value), ctypes.sizeof(value)) != 0:   # DWMWA_CLOAKED
        return False
    return bool(value.value)


def visible_windows():
    """Every visible, not minimised top-level window, with what's needed to tell app windows apart."""
    found = []

    @WNDENUMPROC
    def collect(hwnd, _data):
        if user32.IsWindowVisible(hwnd) and not user32.IsIconic(hwnd):
            found.append(hwnd)
        return True

    user32.EnumWindows(collect, 0)
    result = []
    cls = ctypes.create_unicode_buffer(64)
    for hwnd in found:
        pid = DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        user32.GetClassNameW(hwnd, cls, 64)
        rect = RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        result.append(WindowInfo(
            hwnd, pid.value, cls.value, user32.GetWindowTextLengthW(hwnd),
            user32.GetWindowLongPtrW(hwnd, -20) & 0xFFFFFFFF,   # GWL_EXSTYLE
            bool(user32.GetWindow(hwnd, 4)),                      # GW_OWNER
            _cloaked(hwnd), (rect.right - rect.left, rect.bottom - rect.top),
            user32.MonitorFromWindow(hwnd, 0)))                   # MONITOR_DEFAULTTONULL
    return result


# window events, delivered through the calling thread's message loop (Qt's, on the main thread)
WINEVENTPROC = ctypes.WINFUNCTYPE(None, HANDLE, DWORD, W.HWND, LONG, LONG, DWORD, DWORD)
user32.SetWinEventHook.argtypes = [DWORD, DWORD, HANDLE, WINEVENTPROC, DWORD, DWORD, DWORD]
user32.SetWinEventHook.restype = HANDLE
user32.UnhookWinEvent.argtypes = [HANDLE]
user32.UnhookWinEvent.restype = W.BOOL

WINDOW_EVENTS = [
    (0x0003, 0x0003),   # foreground window changed
    (0x000B, 0x000B),   # move / resize finished
    (0x0016, 0x0017),   # minimise start / end
    (0x0020, 0x0020),   # desktop switch
    (0x8001, 0x8003),   # destroyed, shown, hidden
    (0x800B, 0x800B),   # moved (also Win+arrow, snapping)
    (0x8017, 0x8018),   # cloaked / uncloaked (virtual desktops, UWP apps)
]


def hook_window_events(callback):
    """Call `callback()` when a top-level window may have changed. Returns what unhook_window_events needs."""
    @WINEVENTPROC
    def proc(_hook, _event, _hwnd, id_object, id_child, _thread, _time):
        if id_object == 0 and id_child == 0:   # OBJID_WINDOW, the window itself (not its caret, cursor, ...)
            callback()

    hooks = [user32.SetWinEventHook(lo, hi, None, proc, 0, 0, 0x0002) for lo, hi in WINDOW_EVENTS]  # OUTOFCONTEXT | SKIPOWNPROCESS
    return proc, [h for h in hooks if h]


def unhook_window_events(handle):
    for h in handle[1]:
        user32.UnhookWinEvent(h)


# ---- DDC/CI brightness of external monitors ----------------------------------------------------
class PHYSICAL_MONITOR(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("hPhysicalMonitor", HANDLE), ("szPhysicalMonitorDescription", W.WCHAR * 128)]


if dxva2:
    dxva2.GetNumberOfPhysicalMonitorsFromHMONITOR.argtypes = [HANDLE, ctypes.POINTER(DWORD)]
    dxva2.GetNumberOfPhysicalMonitorsFromHMONITOR.restype = W.BOOL
    dxva2.GetPhysicalMonitorsFromHMONITOR.argtypes = [HANDLE, DWORD, ctypes.POINTER(PHYSICAL_MONITOR)]
    dxva2.GetPhysicalMonitorsFromHMONITOR.restype = W.BOOL
    dxva2.GetMonitorBrightness.argtypes = [HANDLE] + [ctypes.POINTER(DWORD)] * 3
    dxva2.GetMonitorBrightness.restype = W.BOOL
    dxva2.SetMonitorBrightness.argtypes = [HANDLE, DWORD]
    dxva2.SetMonitorBrightness.restype = W.BOOL
    dxva2.DestroyPhysicalMonitors.argtypes = [DWORD, ctypes.POINTER(PHYSICAL_MONITOR)]
    dxva2.DestroyPhysicalMonitors.restype = W.BOOL


class PhysicalMonitors:
    """The DDC/CI handles behind one HMONITOR (usually one). Each call can take ~50 ms: worker thread only."""

    def __init__(self, hmonitor):
        self._array, self._count = None, 0
        if not dxva2:
            return
        count = DWORD()
        if not dxva2.GetNumberOfPhysicalMonitorsFromHMONITOR(hmonitor, ctypes.byref(count)) or not count.value:
            return
        array = (PHYSICAL_MONITOR * count.value)()
        if dxva2.GetPhysicalMonitorsFromHMONITOR(hmonitor, count.value, array):
            self._array, self._count = array, count.value

    def brightness(self):
        """(min, current, max) of the first monitor that answers, or None (no DDC/CI, e.g. a laptop panel)."""
        for i in range(self._count):
            lo, cur, hi = DWORD(), DWORD(), DWORD()
            if dxva2.GetMonitorBrightness(self._array[i].hPhysicalMonitor, ctypes.byref(lo), ctypes.byref(cur),
                                          ctypes.byref(hi)) and hi.value > lo.value:
                return lo.value, cur.value, hi.value
        return None

    def set_brightness(self, value):
        return any(dxva2.SetMonitorBrightness(self._array[i].hPhysicalMonitor, int(value)) for i in range(self._count))

    def close(self):
        if self._array is not None:
            dxva2.DestroyPhysicalMonitors(self._count, self._array)
            self._array, self._count = None, 0
