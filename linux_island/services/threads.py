"""Name background threads so `top -H` / `htop` (or Process Explorer) show which part of the island is which."""
import ctypes
import ctypes.util
import sys

_PR_SET_NAME = 15
_libc = _kernel32 = None
try:
    if sys.platform == "win32":
        _kernel32 = ctypes.WinDLL("kernel32")
        _kernel32.GetCurrentThread.restype = ctypes.c_void_p
        _kernel32.SetThreadDescription.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
    else:
        _libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
except (OSError, AttributeError):
    pass


def name_this_thread(name):
    """Set the calling thread's kernel name (max 15 characters; Task Manager / Process Explorer on Windows)."""
    if _libc is not None:
        _libc.prctl(_PR_SET_NAME, name.encode()[:15], 0, 0, 0)
    elif _kernel32 is not None:
        _kernel32.SetThreadDescription(_kernel32.GetCurrentThread(), name)


def emit(signal, *args):
    """Hand a result from a background thread to the main thread. Once the island is shutting down the
    receiving object may already be gone; the thread then just ends (SystemExit isn't caught by the
    loops' `except Exception` and ends a thread silently) instead of printing a traceback."""
    try:
        signal.emit(*args)
    except RuntimeError:          # "Signal source has been deleted" / "Internal C++ object already deleted"
        raise SystemExit
