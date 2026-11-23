"""Windows output volume through Core Audio (IAudioEndpointVolume), via comtypes.

All COM calls happen on one worker thread: it reads the default output's volume four times a second (an
in-process call, no sound-server round trip) and applies the volume / mute changes queued by the slider.
"""
import ctypes
import os
import queue
import threading
import time
from ctypes import POINTER, Structure, c_float, c_uint, c_ushort, c_void_p
from ctypes.wintypes import BOOL, DWORD

import comtypes
from comtypes import COMMETHOD, GUID, HRESULT, IUnknown

from ..services.audio import AudioService
from ..services.threads import emit, name_this_thread

DEBUG = bool(os.environ.get("LINUX_ISLAND_DEBUG"))
CLSCTX_ALL = 23
E_RENDER, E_CONSOLE = 0, 0
VT_LPWSTR, VT_UI4 = 31, 19
HEADPHONE_FORM_FACTORS = {3, 5}   # Headphones, Headset


class PROPERTYKEY(Structure):
    _fields_ = [("fmtid", GUID), ("pid", DWORD)]


class PROPVARIANT(Structure):
    _fields_ = [("vt", c_ushort), ("r1", c_ushort), ("r2", c_ushort), ("r3", c_ushort),
                ("value", c_void_p), ("value2", c_void_p)]


PKEY_FRIENDLY_NAME = PROPERTYKEY(GUID("{A45C254E-DF1C-4EFD-8020-67D146A850E0}"), 14)
PKEY_FORM_FACTOR = PROPERTYKEY(GUID("{1DA5D803-D492-4EDD-8C23-E0C0FFEE7F0E}"), 0)

_ole32 = ctypes.OleDLL("ole32")
_ole32.PropVariantClear.argtypes = [POINTER(PROPVARIANT)]
_ole32.CoTaskMemFree.argtypes = [c_void_p]
_ole32.CoTaskMemFree.restype = None


class IAudioEndpointVolume(IUnknown):
    _iid_ = GUID("{5CDF2C82-841E-4546-9722-0CF74078229A}")
    _methods_ = [   # vtable order matters; the methods after GetMute aren't needed
        COMMETHOD([], HRESULT, "RegisterControlChangeNotify", (["in"], c_void_p, "pNotify")),
        COMMETHOD([], HRESULT, "UnregisterControlChangeNotify", (["in"], c_void_p, "pNotify")),
        COMMETHOD([], HRESULT, "GetChannelCount", (["out"], POINTER(c_uint), "pnChannelCount")),
        COMMETHOD([], HRESULT, "SetMasterVolumeLevel", (["in"], c_float, "fLevelDB"), (["in"], POINTER(GUID), "ctx")),
        COMMETHOD([], HRESULT, "SetMasterVolumeLevelScalar", (["in"], c_float, "fLevel"), (["in"], POINTER(GUID), "ctx")),
        COMMETHOD([], HRESULT, "GetMasterVolumeLevel", (["out"], POINTER(c_float), "pfLevelDB")),
        COMMETHOD([], HRESULT, "GetMasterVolumeLevelScalar", (["out"], POINTER(c_float), "pfLevel")),
        COMMETHOD([], HRESULT, "SetChannelVolumeLevel", (["in"], c_uint, "nChannel"), (["in"], c_float, "fLevelDB"),
                  (["in"], POINTER(GUID), "ctx")),
        COMMETHOD([], HRESULT, "SetChannelVolumeLevelScalar", (["in"], c_uint, "nChannel"), (["in"], c_float, "fLevel"),
                  (["in"], POINTER(GUID), "ctx")),
        COMMETHOD([], HRESULT, "GetChannelVolumeLevel", (["in"], c_uint, "nChannel"), (["out"], POINTER(c_float), "pf")),
        COMMETHOD([], HRESULT, "GetChannelVolumeLevelScalar", (["in"], c_uint, "nChannel"), (["out"], POINTER(c_float), "pf")),
        COMMETHOD([], HRESULT, "SetMute", (["in"], BOOL, "bMute"), (["in"], POINTER(GUID), "ctx")),
        COMMETHOD([], HRESULT, "GetMute", (["out"], POINTER(BOOL), "pbMute")),
    ]


class IPropertyStore(IUnknown):
    _iid_ = GUID("{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetCount", (["out"], POINTER(DWORD), "cProps")),
        COMMETHOD([], HRESULT, "GetAt", (["in"], DWORD, "iProp"), (["out"], POINTER(PROPERTYKEY), "pkey")),
        COMMETHOD([], HRESULT, "GetValue", (["in"], POINTER(PROPERTYKEY), "key"), (["in"], POINTER(PROPVARIANT), "pv")),
    ]


class IMMDevice(IUnknown):
    _iid_ = GUID("{D666063F-1587-4E43-81F1-B948E807363F}")
    _methods_ = [
        COMMETHOD([], HRESULT, "Activate", (["in"], POINTER(GUID), "iid"), (["in"], DWORD, "dwClsCtx"),
                  (["in"], c_void_p, "pActivationParams"), (["out"], POINTER(POINTER(IUnknown)), "ppInterface")),
        COMMETHOD([], HRESULT, "OpenPropertyStore", (["in"], DWORD, "stgmAccess"),
                  (["out"], POINTER(POINTER(IPropertyStore)), "ppProperties")),
        COMMETHOD([], HRESULT, "GetId", (["out"], POINTER(c_void_p), "ppstrId")),
        COMMETHOD([], HRESULT, "GetState", (["out"], POINTER(DWORD), "pdwState")),
    ]


class IMMDeviceEnumerator(IUnknown):
    _iid_ = GUID("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
    _methods_ = [
        COMMETHOD([], HRESULT, "EnumAudioEndpoints", (["in"], DWORD, "dataFlow"), (["in"], DWORD, "dwStateMask"),
                  (["out"], POINTER(c_void_p), "ppDevices")),
        COMMETHOD([], HRESULT, "GetDefaultAudioEndpoint", (["in"], DWORD, "dataFlow"), (["in"], DWORD, "role"),
                  (["out"], POINTER(POINTER(IMMDevice)), "ppEndpoint")),
    ]


CLSID_MMDeviceEnumerator = GUID("{BCDE0395-E52F-467C-8E3D-C4579291692E}")


def _property(store, key):
    pv = PROPVARIANT()
    try:
        store.GetValue(ctypes.byref(key), ctypes.byref(pv))
        if pv.vt == VT_LPWSTR and pv.value:
            return ctypes.wstring_at(pv.value)
        if pv.vt == VT_UI4:
            return (pv.value or 0) & 0xFFFFFFFF
        return None
    except comtypes.COMError:
        return None
    finally:
        _ole32.PropVariantClear(ctypes.byref(pv))


class DefaultOutput:
    """The default playback device and its volume control (worker thread only)."""

    def __init__(self, enumerator):
        device = enumerator.GetDefaultAudioEndpoint(E_RENDER, E_CONSOLE)
        self.id = self.device_id(device)
        self.volume = device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None).QueryInterface(IAudioEndpointVolume)
        name, form = "", None
        try:
            store = device.OpenPropertyStore(0)   # STGM_READ
            name = _property(store, PKEY_FRIENDLY_NAME) or ""
            form = _property(store, PKEY_FORM_FACTOR)
        except comtypes.COMError:
            pass
        self.name = name
        self.headphones = form in HEADPHONE_FORM_FACTORS or any(
            w in name.lower() for w in ("head", "ear", "bud", "pods", "hands-free"))

    @staticmethod
    def device_id(device):
        ptr = device.GetId()
        try:
            return ctypes.wstring_at(ptr) if ptr else ""
        finally:
            _ole32.CoTaskMemFree(ptr)

    def read(self):
        return float(self.volume.GetMasterVolumeLevelScalar()), bool(self.volume.GetMute())


class _Commands:
    """What AudioService hands to `_run`: here a request for the worker instead of a command line."""
    def set_volume(self, v):
        return ("volume", v)

    def set_mute(self, muted):
        return ("mute", muted)


class WinAudioService(AudioService):
    def __init__(self, parent=None):
        super().__init__(parent)   # finds no wpctl / pactl, so starts nothing
        self._queue = queue.Queue()
        self._backend = _Commands()
        threading.Thread(target=self._poll, daemon=True, name="audio-poll").start()

    def _run(self, cmd):
        self._queue.put(cmd)

    def _poll(self):
        name_this_thread("island-audio")
        comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
        enumerator = output = None
        last_output, tick = None, 0
        while True:
            try:
                if enumerator is None:
                    enumerator = comtypes.CoCreateInstance(CLSID_MMDeviceEnumerator, IMMDeviceEnumerator, CLSCTX_ALL)
                if output is None or tick % 4 == 0:   # the default output can change (headphones, HDMI)
                    current = DefaultOutput.device_id(enumerator.GetDefaultAudioEndpoint(E_RENDER, E_CONSOLE))
                    if output is None or current != output.id:
                        output = DefaultOutput(enumerator)
                        if last_output is not None and output.id != last_output:
                            emit(self.outputChanged, output.name, output.headphones)
                        last_output = output.id
                while True:
                    try:
                        kind, value = self._queue.get_nowait()
                    except queue.Empty:
                        break
                    if kind == "volume":
                        output.volume.SetMasterVolumeLevelScalar(float(value), None)
                    else:
                        output.volume.SetMute(bool(value), None)
                emit(self._polled, *output.read())
            except (comtypes.COMError, OSError) as e:   # no output device, or it just went away
                if DEBUG:
                    print(f"audio: {e}", flush=True)
                if not isinstance(e, comtypes.COMError):
                    enumerator = None
                output = None
                while not self._queue.empty():      # nothing to apply them to
                    self._queue.get_nowait()
                time.sleep(1)
                continue
            tick += 1
            try:   # wake at once for the slider, else re-read after 250 ms
                self._queue.put(self._queue.get(timeout=0.25))
            except queue.Empty:
                pass
