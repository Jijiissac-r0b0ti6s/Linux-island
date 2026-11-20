"""Name background threads so `top -H` / `htop` show which part of the island is which."""
import ctypes
import ctypes.util

_PR_SET_NAME = 15
try:
    _libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
except OSError:
    _libc = None


def name_this_thread(name):
    """Set the calling thread's kernel name (max 15 characters)."""
    if _libc is not None:
        _libc.prctl(_PR_SET_NAME, name.encode()[:15], 0, 0, 0)


def emit(signal, *args):
    """Hand a result from a background thread to the main thread. Once the island is shutting down the
    receiving object may already be gone; the thread then just ends (SystemExit isn't caught by the
    loops' `except Exception` and ends a thread silently) instead of printing a traceback."""
    try:
        signal.emit(*args)
    except RuntimeError:          # "Signal source has been deleted" / "Internal C++ object already deleted"
        raise SystemExit
