"""Снимок окна лаунчера (для README и проверки вёрстки).

Запуск:  python tools/screenshot.py docs/screenshot.png [main|catalog|skins|settings|mods]
"""

from __future__ import annotations

import ctypes
import os
import sys
import time
from ctypes import wintypes

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tkinter as tk  # noqa: E402

from core import branding, paths, png  # noqa: E402
from ui.app import LauncherApp, _dark_titlebar  # noqa: E402

PW_RENDERFULLCONTENT = 2
TABS = {"console": "Консоль", "mods": "Моды", "catalog": "Каталог", "skins": "Скины",
        "settings": "Настройки"}


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


def capture(hwnd: int):
    """Снимок окна без системного заголовка (его рисует Windows, в тему он не входит).

    PrintWindow рисует само окно, поэтому в кадр не попадает рабочий стол —
    в отличие от BitBlt прямо с экрана.
    """
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    frame = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(frame))
    full_width = frame.right - frame.left
    full_height = frame.bottom - frame.top
    origin = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(origin))
    client = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(client))
    client_width, client_height = client.right - client.left, client.bottom - client.top
    offset_x, offset_y = origin.x - frame.left, origin.y - frame.top

    window_dc = user32.GetWindowDC(hwnd)
    memory_dc = gdi32.CreateCompatibleDC(window_dc)
    bitmap = gdi32.CreateCompatibleBitmap(window_dc, full_width, full_height)
    gdi32.SelectObject(memory_dc, bitmap)
    user32.PrintWindow(hwnd, memory_dc, PW_RENDERFULLCONTENT)
    header = BITMAPINFOHEADER()
    header.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    header.biWidth = full_width
    header.biHeight = -full_height
    header.biPlanes = 1
    header.biBitCount = 32
    header.biCompression = 0
    buffer = ctypes.create_string_buffer(full_width * full_height * 4)
    gdi32.GetDIBits(memory_dc, bitmap, 0, full_height, buffer, ctypes.byref(header), 0)
    gdi32.DeleteObject(bitmap)
    gdi32.DeleteDC(memory_dc)
    user32.ReleaseDC(hwnd, window_dc)
    bgra = buffer.raw
    rgba = bytearray(len(bgra))
    for index in range(0, len(bgra), 4):
        rgba[index] = bgra[index + 2]
        rgba[index + 1] = bgra[index + 1]
        rgba[index + 2] = bgra[index]
        rgba[index + 3] = 255
    visible = png.crop(full_width, full_height, bytes(rgba), offset_x, offset_y,
                       client_width, client_height)
    return client_width, client_height, visible


def pump(root, seconds: float):
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        time.sleep(0.02)


def main() -> int:
    target = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        paths.launcher_dir(), "docs", "screenshot.png")
    which = sys.argv[2] if len(sys.argv) > 2 else "main"

    if paths.WINDOWS:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

    root = tk.Tk()
    icon, logo = branding.ensure()
    if paths.WINDOWS and icon:
        try:
            root.iconbitmap(icon)
        except tk.TclError:
            pass
    app = LauncherApp(root)
    _dark_titlebar(root)
    app._refresh_all()
    if which in TABS:
        app.show_tab(TABS[which])
    if which == "catalog":
        app._on_search(False)
        for _ in range(60):
            root.update()
            if app.results:
                break
            time.sleep(0.25)
        pump(root, 0.6)
    root.deiconify()
    root.lift()
    pump(root, 1.2)

    hwnd = ctypes.windll.user32.GetParent(root.winfo_id()) or root.winfo_id()
    width, height, rgba = capture(hwnd)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    png.write(target, width, height, rgba)
    print("снимок: %s (%dx%d)" % (target, width, height))
    root.destroy()
    return 0


if __name__ == "__main__":
    sys.exit(main())
