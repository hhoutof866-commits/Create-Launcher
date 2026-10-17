"""Баннер вкладки «Играть»: пиксельный пейзаж в сумерках.

Картинка рисуется кодом (чужих изображений лаунчер не тащит) и кэшируется в
cache/. Размер 192x56 пикселей, при увеличении в 4 раза — 768x224 под ширину
вкладки. Номер версии входит в имя файла, поэтому кэш обновляется сам, когда
картинка меняется.
"""

from __future__ import annotations

import math
import os

from . import paths, png

WIDTH, HEIGHT, FACTOR = 192, 56, 4
VERSION = 1

HORIZON = 38          # линия горизонта
GROUND = 52           # «ноги» переднего плана
BUTTON_ZONE = (66, 126)   # середина низа — там лежит кнопка, не загораживаем

SKY_STOPS = (
    (0, (0x15, 0x0f, 0x27)),
    (9, (0x1f, 0x15, 0x35)),
    (18, (0x30, 0x1d, 0x4c)),
    (26, (0x4a, 0x2a, 0x5c)),
    (32, (0x74, 0x41, 0x64)),
    (37, (0xa5, 0x5d, 0x63)),
)

GRASS = (0x3f, 0x6d, 0x4e)
GRASS_DARK = (0x31, 0x59, 0x40)
GRASS_MOON = (0x7a, 0x5e, 0xa6)
DIRT = (0x49, 0x38, 0x2b)
DIRT_DARK = (0x3d, 0x2f, 0x24)
STONE = (0x4a, 0x45, 0x4d)

LEAF_DARK = (0x1d, 0x3d, 0x2a)
LEAF_LIGHT = (0x2c, 0x57, 0x3a)
LEAF_RIM = (0x6b, 0x50, 0x91)
TRUNK = (0x47, 0x32, 0x22)

# Ёлка: одна ячейка карты = 2x2 пикселя.
SPRUCE = (
    "...#...",
    "..###..",
    "..###..",
    ".#####.",
    ".#####.",
    "#######",
)

# Крипер: тело, чёрное лицо и светящиеся фиолетовые глаза.
CREEPER = (
    "....########....",
    "....########....",
    "....#EE##EE#....",
    "....#EE##EE#....",
    "....###MM###....",
    "....##MMMM##....",
    "....#MMMMMM#....",
    "....#MM##MM#....",
    "..############..",
    "..############..",
    "..############..",
    "..############..",
    "..############..",
    "..############..",
    "..############..",
    "..############..",
    "..#####..#####..",
    "..#####..#####..",
    "..#####..#####..",
    "..#####..#####..",
    "..#####..#####..",
    "..#####..#####..",
    "..#####..#####..",
    "..#####..#####..",
)


class _Canvas:
    """Крошечный холст RGBA: точка с наложением, прямоугольник."""

    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        self.data = bytearray(width * height * 4)

    def put(self, x: int, y: int, color, alpha: int = 255) -> None:
        if not (0 <= x < self.width and 0 <= y < self.height):
            return
        index = (y * self.width + x) * 4
        if alpha >= 255:
            self.data[index:index + 3] = bytes(color)
        else:
            for channel in range(3):
                old = self.data[index + channel]
                self.data[index + channel] = (color[channel] * alpha
                                              + old * (255 - alpha)) // 255
        self.data[index + 3] = 255

    def box(self, x: int, y: int, width: int, height: int, color, alpha: int = 255) -> None:
        for row in range(y, y + height):
            for column in range(x, x + width):
                self.put(column, row, color, alpha)


def _mix(first, second, t: float):
    return tuple(int(round(first[index] + (second[index] - first[index]) * t))
                 for index in range(3))


def _noise(x: int, y: int, salt: int = 0) -> int:
    """Псевдослучайное число для зерна на земле (без диагональных полос)."""
    value = (x * 73856093) ^ (y * 19349663) ^ (salt * 83492791)
    return (value >> 5) & 0xFF


def _sky_color(y: int):
    for index in range(len(SKY_STOPS) - 1):
        y0, first = SKY_STOPS[index]
        y1, second = SKY_STOPS[index + 1]
        if y0 <= y <= y1:
            return _mix(first, second, (y - y0) / float(max(1, y1 - y0)))
    return SKY_STOPS[-1][1]


# --------------------------------------------------------------- элементы


def _stars(canvas: _Canvas) -> None:
    for index in range(58):
        x = (index * 41 + 7) % WIDTH
        y = (index * 23 + 3) % 30
        if x > 130 and y < 24:            # вокруг луны не сыпем
            continue
        bright = 90 + ((index * 37) % 120)
        canvas.put(x, y, (0xe9, 0xdf, 0xff), alpha=bright)
        if index % 9 == 0:                # редкие звёзды покрупнее
            canvas.put(x + 1, y, (0xdf, 0xd2, 0xff), alpha=bright // 2)


def _moon(canvas: _Canvas, x0: int, y0: int, radius: int = 6) -> None:
    for y in range(-radius - 3, radius + 4):
        for x in range(-radius - 3, radius + 4):
            distance = math.hypot(x, y)
            if distance <= radius - 0.4 and math.hypot(x - 2.6, y + 1.2) > radius - 1.9:
                canvas.put(x0 + x, y0 + y, (0xf3, 0xec, 0xff))
            elif distance <= radius + 2.6:
                canvas.put(x0 + x, y0 + y, (0xb9, 0x9b, 0xe8), alpha=44)


def _clouds(canvas: _Canvas) -> None:
    for x, y, width in ((14, 21, 34), (72, 16, 20), (120, 27, 42)):
        for step in range(width):
            alpha = 150 if step % 7 else 120
            canvas.put(x + step, y, (0x33, 0x24, 0x4e), alpha=alpha)
            canvas.put(x + step, y + 1, (0x33, 0x24, 0x4e), alpha=alpha // 2)


def _ridges(canvas: _Canvas) -> None:
    for x in range(WIDTH):
        top = int(30 + 2.6 * math.sin(x / 17.0) + 1.4 * math.sin(x / 6.3))
        canvas.box(x, top, 1, HORIZON - top, (0x24, 0x18, 0x3c))
        if x > 110:                       # лунный свет на дальнем хребте
            canvas.put(x, top, _mix((0x24, 0x18, 0x3c), (0x58, 0x3c, 0x7e),
                                    min(1.0, (x - 110) / 70.0)))
    for x in range(WIDTH):
        top = int(34 + 1.7 * math.sin((x + 46) / 10.5) + 1.1 * math.sin(x / 3.7))
        canvas.box(x, top, 1, HORIZON - top, (0x1b, 0x13, 0x2c))


def _ground(canvas: _Canvas) -> None:
    for y in range(HORIZON, HEIGHT):
        depth = y - HORIZON
        for x in range(WIDTH):
            grain = _noise(x, y) % 11
            if grain in (0, 5):
                color = DIRT_DARK
            elif grain == 9 and depth > 5:
                color = STONE
            else:
                color = DIRT
            canvas.put(x, y, color)
    for x in range(WIDTH):
        edge = 1 if (_noise(x, 3) % 19) < 3 else 0
        canvas.put(x, HORIZON - edge, GRASS_DARK)
        grass = GRASS
        if x > 100:                       # лунный свет на кромке травы
            grass = _mix(GRASS, GRASS_MOON, min(1.0, (x - 100) / 60.0) * 0.5)
        canvas.put(x, HORIZON + 1 - edge, grass)
    for y in range(48, HEIGHT):           # тень у нижнего края: там кнопка
        canvas.box(0, y, WIDTH, 1, (0x14, 0x0f, 0x1c),
                   alpha=int(80 * (y - 47) / float(HEIGHT - 47)))


def _rock(canvas: _Canvas, x: int, y: int, width: int = 3) -> None:
    """Камешек: пара пикселей со светлым верхом."""
    canvas.box(x, y - 1, width, 2, (0x3a, 0x36, 0x3e))
    canvas.put(x, y - 1, (0x58, 0x53, 0x5c))
    canvas.put(x + width - 1, y, (0x2c, 0x29, 0x30))


def _tuft(canvas: _Canvas, x: int, y: int) -> None:
    canvas.put(x, y, GRASS_DARK)
    canvas.put(x, y - 1, GRASS)
    canvas.put(x + 1, y, GRASS_DARK)
    canvas.put(x + 2, y - 1, GRASS_DARK)


def _flower(canvas: _Canvas, x: int, y: int, color) -> None:
    canvas.put(x, y, (0x38, 0x60, 0x43))
    canvas.put(x, y - 1, (0x38, 0x60, 0x43))
    canvas.put(x, y - 2, color)
    canvas.put(x + 1, y - 2, color)
    canvas.put(x, y - 3, color)
    canvas.put(x + 1, y - 3, (0xc9, 0xb2, 0xf2))


def _spruce(canvas: _Canvas, x: int, ground: int, scale: int = 2) -> None:
    """Ёлка: карта SPRUCE, увеличенная в scale раз, свет падает справа."""
    top = ground - len(SPRUCE) * scale - scale
    for row, line in enumerate(SPRUCE):
        for column, char in enumerate(line):
            if char != "#":
                continue
            color = LEAF_LIGHT if column >= len(line) // 2 else LEAF_DARK
            canvas.box(x + column * scale, top + row * scale, scale, scale, color)
        column = line.rfind("#")
        if column >= len(line) // 2:      # лунный ореол на правых ветках
            canvas.box(x + column * scale + scale - 1, top + row * scale, 1, scale, LEAF_RIM)
    canvas.box(x + 3 * scale, ground - scale, scale, scale, TRUNK)


def _creeper(canvas: _Canvas, x: int, ground: int) -> None:
    map_height = len(CREEPER)
    top = ground - map_height
    for offset in range(len(CREEPER[0]) + 2):      # тень на земле
        canvas.put(x - 1 + offset, ground, (0x2a, 0x1d, 0x2a), alpha=90)
    for row, line in enumerate(CREEPER):
        for column, char in enumerate(line):
            if char == ".":
                continue
            y, px = top + row, x + column
            if char == "E":
                for step in (1, 2):                # фиолетовое свечение глаз
                    for dx in (-step, 0, step):
                        for dy in (-step, 0, step):
                            canvas.put(px + dx, y + dy, (0xa8, 0x8b, 0xf0), alpha=46)
                canvas.put(px, y, (0xd9, 0xc8, 0xff))
            elif char == "M":
                canvas.put(px, y, (0x14, 0x1f, 0x12))
            else:
                color = (0x4b, 0x82, 0x50) if column >= 8 else (0x3c, 0x6b, 0x43)
                canvas.put(px, y, color)


def _torch(canvas: _Canvas, x: int, ground: int) -> None:
    canvas.box(x, ground - 6, 1, 6, (0x5e, 0x3f, 0x24))
    canvas.put(x, ground - 6, (0x7a, 0x55, 0x30))
    for y in range(ground - 11, ground - 5):        # тёплое свечение
        for dx in range(-2, 3):
            canvas.put(x + dx, y, (0xff, 0x9c, 0x42), alpha=38)
    canvas.box(x, ground - 9, 1, 3, (0xff, 0x9c, 0x42))
    canvas.put(x, ground - 9, (0xff, 0xe2, 0x8e))
    canvas.put(x, ground - 8, (0xff, 0xd0, 0x6a))


def render():
    """Рисует баннер и отдаёт (width, height, rgba)."""
    canvas = _Canvas(WIDTH, HEIGHT)
    for y in range(HORIZON):
        canvas.box(0, y, WIDTH, 1, _sky_color(y))
    _stars(canvas)
    _moon(canvas, 168, 9)
    _clouds(canvas)
    _ridges(canvas)
    _ground(canvas)

    _spruce(canvas, 168, GROUND - 6, scale=1)       # дальняя ёлка
    _creeper(canvas, 26, GROUND)
    _torch(canvas, 16, GROUND)
    _spruce(canvas, 140, GROUND)
    for x, y in ((6, HORIZON + 4), (48, HORIZON + 6), (84, HORIZON + 3),
                 (122, HORIZON + 5), (156, HORIZON + 3), (186, HORIZON + 6)):
        _tuft(canvas, x, y)
    _rock(canvas, 66, GROUND + 3)
    _rock(canvas, 104, GROUND + 4, width=4)
    _rock(canvas, 176, GROUND + 2)
    _flower(canvas, 62, HORIZON + 3, (0x8f, 0x6d, 0xd8))
    _flower(canvas, 112, HORIZON + 4, (0xb2, 0x8f, 0xe0))
    _flower(canvas, 132, HORIZON + 3, (0x8f, 0x6d, 0xd8))
    return WIDTH, HEIGHT, bytes(canvas.data)


def image_path(factor: int = FACTOR) -> str:
    """Путь к готовому PNG: рисует и кладёт в кэш при первом обращении."""
    target = os.path.join(paths.cache_dir(), "hero-%d-%dx.png" % (VERSION, factor))
    if not os.path.exists(target):
        width, height, rgba = render()
        width, height, rgba = png.scale(width, height, rgba, max(1, factor))
        png.write(target, width, height, rgba)
    return target


def pick_factor(width: int) -> int:
    """Подбирает увеличение под ширину вкладки: чем шире окно, тем крупнее картинка."""
    if width >= WIDTH * FACTOR - 28:      # почти в размер: по краям обрезается пара пикселей
        return FACTOR
    if width >= WIDTH * 3:
        return 3
    if width >= WIDTH * 2:
        return 2
    return 1
