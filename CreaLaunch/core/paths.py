"""Пути и платформенные мелочи."""

from __future__ import annotations

import os
import platform
import sys

WINDOWS = sys.platform == "win32"
MACOS = sys.platform == "darwin"


def launcher_dir() -> str:
    """Каталог, в котором лежит сам лаунчер."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def cache_dir() -> str:
    d = os.path.join(launcher_dir(), "cache")
    os.makedirs(d, exist_ok=True)
    return d


def java_dir() -> str:
    d = os.path.join(launcher_dir(), "java")
    os.makedirs(d, exist_ok=True)
    return d


def default_game_dir() -> str:
    return os.path.join(launcher_dir(), ".minecraft")


def platform_name() -> str:
    if WINDOWS:
        return "windows"
    if MACOS:
        return "osx"
    return "linux"


def platform_arch() -> str:
    m = platform.machine().lower()
    if m in ("x86", "i386", "i486", "i586", "i686", "x86_32"):
        return "x86"
    if m in ("arm64", "aarch64"):
        return "arm64"
    return "x64"


def java_exe_name() -> str:
    return "java.exe" if WINDOWS else "java"


def system_memory_mb() -> int:
    """Сколько всего ОЗУ в системе (МБ), 0 если не удалось узнать."""
    try:
        if WINDOWS:
            import ctypes

            class MemoryStatusEx(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            st = MemoryStatusEx()
            st.dwLength = ctypes.sizeof(MemoryStatusEx)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
                return int(st.ullTotalPhys // (1024 * 1024))
        else:
            return int(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") // (1024 * 1024))
    except Exception:
        pass
    return 0
