"""Tells the audio service when the sound server's volume, mute or default output changes.

Uses libpulse's subscription API (PulseAudio, or PipeWire through pipewire-pulse) so the volume
is only read when something actually changed, instead of being polled twice a second.
"""
import ctypes
import ctypes.util
import threading

PA_CONTEXT_READY, PA_CONTEXT_FAILED, PA_CONTEXT_TERMINATED = 4, 5, 6
PA_SUBSCRIPTION_MASK_SINK, PA_SUBSCRIPTION_MASK_SERVER = 0x0001, 0x0080
PA_FACILITY_MASK, PA_FACILITY_SERVER = 0x000F, 0x0007
PA_TYPE_MASK, PA_TYPE_NEW, PA_TYPE_REMOVE = 0x0030, 0x0000, 0x0020

_NOTIFY = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p)
_SUBSCRIBE = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_int, ctypes.c_uint32, ctypes.c_void_p)


class PulseEvents:
    """`changed` is set on any volume/mute change; `output_changed` when the default output may differ."""

    def __init__(self):
        self.changed = threading.Event()
        self.output_changed = threading.Event()
        self.alive = False
        name = ctypes.util.find_library("pulse")
        if not name:
            raise OSError("libpulse not found")
        pa = self._pa = ctypes.CDLL(name)
        vp = ctypes.c_void_p
        for fn, res, args in [
            ("pa_threaded_mainloop_new", vp, []), ("pa_threaded_mainloop_get_api", vp, [vp]),
            ("pa_threaded_mainloop_start", ctypes.c_int, [vp]),
            ("pa_threaded_mainloop_lock", None, [vp]), ("pa_threaded_mainloop_unlock", None, [vp]),
            ("pa_context_new", vp, [vp, ctypes.c_char_p]),
            ("pa_context_set_state_callback", None, [vp, _NOTIFY, vp]),
            ("pa_context_set_subscribe_callback", None, [vp, _SUBSCRIBE, vp]),
            ("pa_context_connect", ctypes.c_int, [vp, ctypes.c_char_p, ctypes.c_int, vp]),
            ("pa_context_get_state", ctypes.c_int, [vp]),
            ("pa_context_subscribe", vp, [vp, ctypes.c_int, vp, vp]),
            ("pa_operation_unref", None, [vp]),
        ]:
            getattr(pa, fn).restype = res
            getattr(pa, fn).argtypes = args
        # keep the C callbacks alive as long as this object
        self._on_state = _NOTIFY(self._state)
        self._on_event = _SUBSCRIBE(self._event)
        self._loop = pa.pa_threaded_mainloop_new()
        self._ctx = pa.pa_context_new(pa.pa_threaded_mainloop_get_api(self._loop), b"linux-island")
        pa.pa_context_set_state_callback(self._ctx, self._on_state, None)
        pa.pa_context_set_subscribe_callback(self._ctx, self._on_event, None)
        if pa.pa_context_connect(self._ctx, None, 0, None) < 0:
            raise OSError("cannot connect to the sound server")
        self._ready = threading.Event()
        if pa.pa_threaded_mainloop_start(self._loop) < 0:
            raise OSError("cannot start the libpulse main loop")
        if not self._ready.wait(3) or not self.alive:
            raise OSError("sound server did not answer")

    # both run on libpulse's own thread
    def _state(self, ctx, _):
        state = self._pa.pa_context_get_state(ctx)
        if state == PA_CONTEXT_READY:
            op = self._pa.pa_context_subscribe(ctx, PA_SUBSCRIPTION_MASK_SINK | PA_SUBSCRIPTION_MASK_SERVER, None, None)
            if op:
                self._pa.pa_operation_unref(op)
            self.alive = True
            self._ready.set()
        elif state in (PA_CONTEXT_FAILED, PA_CONTEXT_TERMINATED):
            self.alive = False          # the audio service falls back to polling
            self._ready.set()
            self.changed.set()

    def _event(self, ctx, kind, index, _):
        facility, change = kind & PA_FACILITY_MASK, kind & PA_TYPE_MASK
        if facility == PA_FACILITY_SERVER or change in (PA_TYPE_NEW, PA_TYPE_REMOVE):
            self.output_changed.set()   # default output switched, or an output appeared / went away
        self.changed.set()
