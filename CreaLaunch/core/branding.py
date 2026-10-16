"""Иконка и логотип лаунчера: рисуем пиксель-арт крипера сами (без картинок в репозитории)."""

from __future__ import annotations

import os

from . import paths, png

ASSETS_DIR = os.path.join(paths.launcher_dir(), "assets")

# Классическое лицо крипера 8x8
_FACE = (
    "........",
    ".XX..XX.",
    ".XX..XX.",
    "...XX...",
    "..XXXX..",
    "..XXXX..",
    "..X..X..",
    "........",
)

_GREENS = (
    (74, 168, 66),
    (67, 155, 60),
    (80, 178, 71),
    (61, 143, 55),
)
_DARK = (16, 22, 16)


def icon_path() -> str:
    return os.path.join(ASSETS_DIR, "launcher.ico")


def logo_path() -> str:
    return os.path.join(ASSETS_DIR, "logo.png")


def creeper_rgba(size: int, rounded: bool = True):
    """Рисует квадрат с лицом крипера размера size x size."""
    grid = size / 16.0
    radius = max(1, size // 8)
    out = bytearray(size * size * 4)
    for y in range(size):
        for x in range(size):
            index = (y * size + x) * 4
            if rounded:
                dx = dy = 0
                if x < radius and y < radius:
                    dx, dy = radius - x, radius - y
                elif x >= size - radius and y < radius:
                    dx, dy = x - (size - radius - 1), radius - y
                elif x < radius and y >= size - radius:
                    dx, dy = radius - x, y - (size - radius - 1)
                elif x >= size - radius and y >= size - radius:
                    dx, dy = x - (size - radius - 1), y - (size - radius - 1)
                if dx * dx + dy * dy > radius * radius:
                    continue
            face_x = min(7, int(x / grid / 2))
            face_y = min(7, int(y / grid / 2))
            if _FACE[face_y][face_x] == "X":
                color = _DARK
            else:
                color = _GREENS[(x * 7 + y * 13) % len(_GREENS)]
            out[index:index + 3] = bytes(color)
            out[index + 3] = 255
    return size, size, bytes(out)


# ------------------------------------------------------------------ ICO


def _bmp_entry(size: int):
    width, height, rgba = creeper_rgba(size)
    header = b"".join([
        (40).to_bytes(4, "little"),          # размер BITMAPINFOHEADER
        width.to_bytes(4, "little"),
        (height * 2).to_bytes(4, "little"),  # XOR + AND маски
        (1).to_bytes(2, "little"),
        (32).to_bytes(2, "little"),
        (0).to_bytes(4, "little"),           # без сжатия
        (width * height * 4).to_bytes(4, "little"),
        (0).to_bytes(4, "little"),
        (0).to_bytes(4, "little"),
        (0).to_bytes(4, "little"),
        (0).to_bytes(4, "little"),
    ])
    pixels = bytearray()
    for row in range(height - 1, -1, -1):     # BMP хранит строки снизу вверх
        for column in range(width):
            index = (row * width + column) * 4
            r, g, b, a = rgba[index], rgba[index + 1], rgba[index + 2], rgba[index + 3]
            pixels.extend((b, g, r, a))
    mask_row = ((width + 31) // 32) * 4
    mask = bytes(mask_row * height)
    return header + bytes(pixels) + mask


def write_ico(path: str, sizes=(16, 32, 48, 64, 128, 256)) -> str:
    entries = []
    for size in sizes:
        entries.append((size, _bmp_entry(size)))
    offset = 6 + 16 * len(entries)
    directory = bytearray()
    directory.extend((0).to_bytes(2, "little"))
    directory.extend((1).to_bytes(2, "little"))
    directory.extend(len(entries).to_bytes(2, "little"))
    body = bytearray()
    for size, data in entries:
        directory.extend(bytes([0 if size >= 256 else size, 0 if size >= 256 else size]))
        directory.extend(b"\x00\x00")
        directory.extend((1).to_bytes(2, "little"))
        directory.extend((32).to_bytes(2, "little"))
        directory.extend(len(data).to_bytes(4, "little"))
        directory.extend(offset.to_bytes(4, "little"))
        body.extend(data)
        offset += len(data)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(bytes(directory) + bytes(body))
    return path


def ensure(recreate: bool = False):
    """Создаёт assets/launcher.ico и assets/logo.png (если их ещё нет)."""
    os.makedirs(ASSETS_DIR, exist_ok=True)
    icon = icon_path()
    logo = logo_path()
    try:
        if recreate or not os.path.exists(icon) or os.path.getsize(icon) < 1024:
            write_ico(icon)
        if recreate or not os.path.exists(logo):
            width, height, data = creeper_rgba(48)
            png.write(logo, width, height, data)
    except OSError:
        return icon if os.path.exists(icon) else "", logo if os.path.exists(logo) else ""
    return icon, logo
