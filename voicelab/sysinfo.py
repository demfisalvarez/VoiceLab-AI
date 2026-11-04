"""Información del equipo: sistema, CPU, RAM, GPU y aceleración de IA.

En Windows todo se lee del registro o de la API del sistema (sin abrir
consolas ni lanzar procesos), así que es instantáneo.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import platform
import sys

log = logging.getLogger(__name__)

_GPU_CLASS = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
_IGNORED_GPUS = ("microsoft basic", "remote display", "virtual display", "parsec", "meta virtual")


def _windows_os() -> str:
    try:
        build = sys.getwindowsversion().build  # type: ignore[attr-defined]
    except Exception:
        return platform.platform()
    name = "Windows 11" if build >= 22000 else "Windows 10"
    return f"{name} (compilación {build})"


def _windows_cpu() -> str | None:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
            return str(winreg.QueryValueEx(k, "ProcessorNameString")[0]).strip()
    except Exception:
        return None


def _windows_ram_gb() -> float | None:
    try:
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]

        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))  # type: ignore[attr-defined]
        return round(stat.ullTotalPhys / 1024 ** 3, 1)
    except Exception:
        return None


def _windows_gpus() -> list[dict]:
    gpus: list[dict] = []
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _GPU_CLASS) as root:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(root, i)
                except OSError:
                    break
                i += 1
                if not sub.isdigit():
                    continue
                try:
                    with winreg.OpenKey(root, sub) as k:
                        name = str(winreg.QueryValueEx(k, "DriverDesc")[0])
                        vram = None
                        for value in ("HardwareInformation.qwMemorySize", "HardwareInformation.MemorySize"):
                            try:
                                raw = winreg.QueryValueEx(k, value)[0]
                                if isinstance(raw, bytes):
                                    raw = int.from_bytes(raw[:8], "little")
                                vram = round(int(raw) / 1024 ** 3, 1)
                                break
                            except OSError:
                                continue
                except OSError:
                    continue
                if any(x in name.lower() for x in _IGNORED_GPUS):
                    continue
                if not any(g["name"] == name for g in gpus):
                    gpus.append({"name": name, "vram_gb": vram})
    except Exception as exc:
        log.debug("No se pudo leer la GPU: %s", exc)
    return gpus


def _linux_cpu() -> str | None:
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as f:
            for line in f:
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or None


def _linux_ram_gb() -> float | None:
    try:
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemTotal"):
                    return round(int(line.split()[1]) / 1024 ** 2, 1)
    except OSError:
        pass
    return None


def ai_runtime() -> dict:
    """Estado del motor de IA (ONNX Runtime). No se importa si no está
    instalado: en la Fase 1 todavía no forma parte de la instalación."""
    if importlib.util.find_spec("onnxruntime") is None:
        return {"installed": False, "version": None, "providers": [], "gpu": False,
                "summary": "No instalado (Ajustes → Motor de IA)"}
    try:
        import onnxruntime as ort
        providers = list(ort.get_available_providers())
        gpu_providers = [p for p in providers if p in ("DmlExecutionProvider", "ROCMExecutionProvider",
                                                         "MIGraphXExecutionProvider", "CUDAExecutionProvider")]
        if "DmlExecutionProvider" in providers:
            summary = "DirectML disponible (GPU)"
        elif gpu_providers:
            summary = f"GPU: {gpu_providers[0]}"
        else:
            summary = "Solo CPU"
        return {"installed": True, "version": ort.__version__, "providers": providers,
                "gpu": bool(gpu_providers), "summary": summary}
    except Exception as exc:
        return {"installed": False, "version": None, "providers": [], "gpu": False,
                "summary": f"Error al cargar ONNX Runtime: {exc}"}


def collect() -> dict:
    if sys.platform == "win32":
        os_name, cpu, ram, gpus = _windows_os(), _windows_cpu(), _windows_ram_gb(), _windows_gpus()
    else:
        os_name, cpu, ram, gpus = platform.platform(), _linux_cpu(), _linux_ram_gb(), []
    return {
        "os": os_name,
        "cpu": cpu,
        "cpu_threads": os.cpu_count(),
        "ram_gb": ram,
        "gpus": gpus,
        "python": platform.python_version(),
        "ai": ai_runtime(),
    }
