"""Снимок окна лаунчера (для README и проверки вёрстки).

Запуск:  python tools/screenshot.py docs/screenshot.png [play|mods|catalog|friends|skins|console|settings]
"""

from __future__ import annotations

import ctypes
import os
import shutil
import sys
import tempfile
import time
from ctypes import wintypes

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tkinter as tk  # noqa: E402

from core import branding, config, paths, png  # noqa: E402
from ui.app import LauncherApp, _dark_titlebar  # noqa: E402

PW_RENDERFULLCONTENT = 2
TABS = {"play": "Играть", "mods": "Моды", "catalog": "Каталог", "friends": "Друзья",
        "skins": "Скины", "console": "Консоль", "settings": "Настройки"}
DEMO_BUILDS = (
    ("Create 1.21.1", "neoforge", "21.1.262", 8192),
    ("Ванильная", "vanilla", "", 4096),
    ("Тестовая", "neoforge", "", 6144),
)


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


def _demo_friends(app):
    """Наполняет вкладку «Друзья» примером для снимка (живой список не трогаем)."""
    app.friends.file = os.path.join(tempfile.gettempdir(), "crealaunch-demo-friends.json")
    app.friends.items = []
    app.friends.add("Вася", "26.152.171.9", 51234)
    app.friends.add("Петя", "26.152.171.14")
    app.friends.touch("Вася", "26.152.171.9", 51234, "Мир Стива")
    app.found = {
        "worlds": [{"motd": "Мир Стива - 1.21.1", "host": "26.152.171.9", "port": 51234,
                    "source": "игра"}],
        "friends": [{"host": "26.152.171.9", "port": 51234, "nick": "Вася", "world": "Мир Стива",
                     "players": 2, "state": "открыт для сети", "source": "лаунчер"}],
        "errors": [],
    }
    app.world_port = 51234
    app.share_var.set(True)
    app._refresh_friends()
    app._refresh_addresses()
    app.friends_info.configure(text="Найдено в сети: друзей — 1, миров — 1. Вася открыл мир "
                                    "«для сети» — можно заходить.")
    app.share_info.configure(text="Мир открыт: друзья видят его в поиске и могут зайти одной "
                                  "кнопкой (порт 51234).")


def _demo_builds(app):
    """Ставит примеры сборок для снимка (в файл настроек ничего не пишется)."""
    app._collect_config()
    game_dir = app.cfg.game_dir
    app.cfg["builds"] = [
        {"name": name, "mode": mode, "mc_version": "1.21.1", "neoforge_version": version,
         "ram_mb": ram, "game_dir": game_dir, "jvm_args": ""}
        for name, mode, version, ram in DEMO_BUILDS
    ]
    app.cfg["current_build"] = DEMO_BUILDS[0][0]
    app.cfg.select_build(DEMO_BUILDS[0][0])
    app._apply_config()


def main() -> int:
    target = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        paths.launcher_dir(), "docs", "screenshot.png")
    which = sys.argv[2] if len(sys.argv) > 2 else "play"

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
    # настройки — во временный файл: снимок не должен трогать живой config.json
    shot_dir = tempfile.mkdtemp(prefix="launcher-shot-")
    config.PATH = os.path.join(shot_dir, "config.json")
    app = LauncherApp(root)
    _dark_titlebar(root)
    app._refresh_all()
    _demo_builds(app)                    # на снимках показываем примеры сборок
    if which == "friends":
        app.last_scan = time.time()      # не поднимать настоящий поиск ради снимка
    if which in TABS:
        app.show_tab(TABS[which])
    if which == "friends":
        _demo_friends(app)
        pump(root, 0.5)
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
    shutil.rmtree(shot_dir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
