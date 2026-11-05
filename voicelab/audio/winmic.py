"""Micrófono predeterminado de Windows (Core Audio por COM, con ctypes).

Windows no tiene una API pública para cambiar el dispositivo predeterminado; todas
las herramientas (el propio panel de Sonido, EarTrumpet, SoundVolumeView…) usan la
interfaz ``IPolicyConfig``. Aquí se llama igual, sin dependencias.

Cada operación corre en un hilo propio con COM inicializado (no interfiere con la
ventana ni con el audio).
"""

from __future__ import annotations

import sys
import threading

E_CAPTURE = 1
DEVICE_STATE_ACTIVE = 0x1
ROLES = (0, 1, 2)                      # consola, multimedia, comunicaciones

_CLSID_ENUM = "{BCDE0395-E52F-467C-8E3D-C4579291692E}"
_IID_ENUM = "{A95664D2-9614-4F35-A746-DE8DB63617E6}"
_CLSID_POLICY = "{870AF99C-171D-4F9E-AF0D-E63DF40C2BC9}"
_IID_POLICY = "{F8679F50-850A-41CF-9C72-430F290290C8}"
_FMTID_NAME = "{A45C254E-DF1C-4EFD-8020-67D146A850E0}"   # PKEY_Device_FriendlyName, pid 14


class WinMicError(RuntimeError):
    pass


def available() -> bool:
    return sys.platform == "win32"


def _in_com_thread(fn):
    """Ejecuta ``fn`` en un hilo con COM (MTA) y devuelve su resultado o su error."""
    box: dict = {}

    def run():
        import ctypes
        ole32 = ctypes.windll.ole32  # type: ignore[attr-defined]
        hr = ole32.CoInitializeEx(None, 0)
        try:
            box["v"] = fn()
        except Exception as exc:  # noqa: BLE001
            box["e"] = exc
        finally:
            if hr in (0, 1):
                ole32.CoUninitialize()
    t = threading.Thread(target=run, name="microfono-windows", daemon=True)
    t.start()
    t.join(15)
    if "e" in box:
        raise WinMicError(str(box["e"])) from box["e"]
    if "v" not in box:
        raise WinMicError("Windows no respondió al cambiar el micrófono predeterminado.")
    return box["v"]


def _com():
    import ctypes
    from ctypes import POINTER, WINFUNCTYPE, byref, c_void_p, c_wchar_p

    ole32 = ctypes.OleDLL("ole32")

    class GUID(ctypes.Structure):
        _fields_ = [("d1", ctypes.c_ulong), ("d2", ctypes.c_ushort), ("d3", ctypes.c_ushort),
                    ("d4", ctypes.c_ubyte * 8)]

    class PROPERTYKEY(ctypes.Structure):
        _fields_ = [("fmtid", GUID), ("pid", ctypes.c_ulong)]

    class PROPVARIANT(ctypes.Structure):
        _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort),
                    ("r3", ctypes.c_ushort), ("p", c_void_p), ("p2", c_void_p)]

    def guid(text: str) -> GUID:
        g = GUID()
        ole32.CLSIDFromString(c_wchar_p(text), byref(g))
        return g

    def call(obj, index: int, *args, argtypes=()):
        vtbl = ctypes.cast(obj, POINTER(POINTER(c_void_p))).contents
        fn = WINFUNCTYPE(ctypes.HRESULT, c_void_p, *argtypes)(vtbl[index])
        return fn(obj, *args)

    def release(obj) -> None:
        if obj:
            vtbl = ctypes.cast(obj, POINTER(POINTER(c_void_p))).contents
            WINFUNCTYPE(ctypes.c_ulong, c_void_p)(vtbl[2])(obj)

    def create(clsid: str, iid: str):
        p = c_void_p()
        ole32.CoCreateInstance(byref(guid(clsid)), None, 0x17, byref(guid(iid)), byref(p))
        return p

    _free = ctypes.windll.ole32.CoTaskMemFree  # type: ignore[attr-defined]  (no devuelve HRESULT)
    _free.argtypes, _free.restype = [c_void_p], None

    class Ole:                                              # CoTaskMemFree sin comprobar HRESULT
        PropVariantClear = ole32.PropVariantClear

        @staticmethod
        def CoTaskMemFree(ptr) -> None:  # noqa: N802
            _free(ctypes.cast(ptr, c_void_p))

    return ctypes, Ole, GUID, PROPERTYKEY, PROPVARIANT, guid, call, release, create


def _list_capture() -> list[dict]:
    ctypes, ole32, _G, PROPERTYKEY, PROPVARIANT, guid, call, release, create = _com()
    from ctypes import POINTER, byref, c_uint, c_void_p, c_wchar_p
    enum = create(_CLSID_ENUM, _IID_ENUM)
    out: list[dict] = []
    coll = c_void_p()
    try:
        call(enum, 3, E_CAPTURE, DEVICE_STATE_ACTIVE, byref(coll), argtypes=(ctypes.c_int, ctypes.c_uint, POINTER(c_void_p)))
        n = c_uint()
        call(coll, 3, byref(n), argtypes=(POINTER(c_uint),))
        key = PROPERTYKEY(guid(_FMTID_NAME), 14)
        for i in range(n.value):
            dev, store = c_void_p(), c_void_p()
            try:
                call(coll, 4, i, byref(dev), argtypes=(c_uint, POINTER(c_void_p)))
                pid = c_wchar_p()
                call(dev, 5, byref(pid), argtypes=(POINTER(c_wchar_p),))
                dev_id = pid.value or ""
                ole32.CoTaskMemFree(pid)
                call(dev, 4, 0, byref(store), argtypes=(ctypes.c_uint, POINTER(c_void_p)))   # STGM_READ
                pv = PROPVARIANT()
                call(store, 5, byref(key), byref(pv), argtypes=(POINTER(PROPERTYKEY), POINTER(PROPVARIANT)))
                name = ctypes.wstring_at(pv.p) if pv.vt == 31 and pv.p else dev_id   # VT_LPWSTR
                ole32.PropVariantClear(byref(pv))
                out.append({"id": dev_id, "name": name})
            finally:
                release(store)
                release(dev)
    finally:
        release(coll)
        release(enum)
    return out


def _default_capture(role: int) -> str | None:
    ctypes, ole32, *_rest, call, release, create = _com()
    from ctypes import POINTER, byref, c_void_p, c_wchar_p
    enum = create(_CLSID_ENUM, _IID_ENUM)
    dev = c_void_p()
    try:
        try:
            call(enum, 4, E_CAPTURE, role, byref(dev), argtypes=(ctypes.c_int, ctypes.c_int, POINTER(c_void_p)))
        except OSError:                                     # no hay ningún micrófono predeterminado
            return None
        pid = c_wchar_p()
        call(dev, 5, byref(pid), argtypes=(POINTER(c_wchar_p),))
        val = pid.value
        ole32.CoTaskMemFree(pid)
        return val
    finally:
        release(dev)
        release(enum)


def _set_default(dev_id: str, roles=ROLES) -> None:
    ctypes, _ole32, *_rest, call, release, create = _com()
    from ctypes import c_wchar_p
    policy = create(_CLSID_POLICY, _IID_POLICY)
    try:
        for role in roles:
            call(policy, 13, c_wchar_p(dev_id), role, argtypes=(c_wchar_p, ctypes.c_int))   # SetDefaultEndpoint
    finally:
        release(policy)


# ------------------------------------------------------------------ público
def capture_devices() -> list[dict]:
    return _in_com_thread(_list_capture)


def default_capture(role: int = 0) -> str | None:
    return _in_com_thread(lambda: _default_capture(role))


def set_default_capture(dev_id: str, roles=ROLES) -> None:
    _in_com_thread(lambda: _set_default(dev_id, tuple(roles)))
