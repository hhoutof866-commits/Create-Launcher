"""Система скинов.

Скин можно взять по нику (Мойанг, если ник лицензионный), по ссылке или из файла.
Превью рисуется прямо из PNG, а в игру скин попадает без модов — через ресурспак,
который подменяет стандартные текстуры игрока (в офлайн-режиме клиент берёт именно их).
"""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
import zipfile

from . import options, png
from .down import USER_AGENT

UUID_URL = "https://api.mojang.com/users/profiles/minecraft/%s"
PROFILE_URL = "https://sessionserver.mojang.com/session/minecraft/profile/%s"

PACK_FORMAT = 34          # 1.21 / 1.21.1
PLAYER_TEXTURES = (
    "assets/minecraft/textures/entity/player/wide/steve.png",
    "assets/minecraft/textures/entity/player/wide/alex.png",
    "assets/minecraft/textures/entity/player/slim/steve.png",
    "assets/minecraft/textures/entity/player/slim/alex.png",
)

# Области в стандартной раскладке скина 64x64: (x, y, ширина, высота)
REGIONS = {
    "head": (8, 8, 8, 8),
    "head_overlay": (40, 8, 8, 8),
    "body": (20, 20, 8, 12),
    "body_overlay": (20, 36, 8, 12),
    "right_arm": (44, 20, 4, 12),
    "right_arm_overlay": (44, 36, 4, 12),
    "left_arm": (36, 48, 4, 12),
    "left_arm_overlay": (52, 48, 4, 12),
    "right_leg": (4, 20, 4, 12),
    "right_leg_overlay": (4, 36, 4, 12),
    "left_leg": (20, 48, 4, 12),
    "left_leg_overlay": (4, 48, 4, 12),
}


class SkinError(Exception):
    """Не удалось получить или разобрать скин."""


def skins_dir(game_dir: str) -> str:
    path = os.path.join(game_dir, "skins")
    os.makedirs(path, exist_ok=True)
    return path


def pack_dir(game_dir: str) -> str:
    path = os.path.join(game_dir, "resourcepacks")
    os.makedirs(path, exist_ok=True)
    return path


def pack_file_name(nickname: str) -> str:
    safe = "".join(ch for ch in nickname if ch.isalnum() or ch in "_-") or "player"
    return "skin-%s.zip" % safe


def saved_skin_path(game_dir: str, nickname: str) -> str:
    safe = "".join(ch for ch in nickname if ch.isalnum() or ch in "_-") or "player"
    return os.path.join(skins_dir(game_dir), "%s.png" % safe)


# ------------------------------------------------------------- получение


def _get(url: str, timeout: int = 45):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def download_by_nickname(nickname: str) -> bytes:
    """Берёт официальный скин ника у Мойанга (нужен лицензионный ник)."""
    try:
        raw = _get(UUID_URL % nickname)
    except urllib.error.HTTPError as exc:
        if exc.code in (204, 404):
            raise SkinError("Игрок %s не найден (ники без лицензии скина не имеют)" % nickname) from exc
        raise SkinError("Ошибка запроса к Мойангу: HTTP %s" % exc.code) from exc
    except OSError as exc:
        raise SkinError("Нет связи с Мойангом: %s" % exc) from exc
    profile_id = json.loads(raw.decode("utf-8")).get("id")
    if not profile_id:
        raise SkinError("Мойанг не вернул UUID игрока")
    try:
        raw = _get(PROFILE_URL % profile_id)
    except OSError as exc:
        raise SkinError("Не удалось получить профиль: %s" % exc) from exc
    for prop in json.loads(raw.decode("utf-8")).get("properties", []):
        if prop.get("name") != "textures":
            continue
        try:
            decoded = json.loads(base64.b64decode(prop["value"]).decode("utf-8"))
        except (ValueError, KeyError):
            continue
        url = ((decoded.get("textures") or {}).get("SKIN") or {}).get("url")
        if url:
            return _get(url)
    raise SkinError("У игрока %s нет установленного скина" % nickname)


def download_by_url(url: str) -> bytes:
    try:
        return _get(url.strip())
    except OSError as exc:
        raise SkinError("Не удалось скачать по ссылке: %s" % exc) from exc


def read_file(path: str) -> bytes:
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except OSError as exc:
        raise SkinError("Не удалось прочитать файл: %s" % exc) from exc


def parse(data: bytes):
    """Проверяет PNG и возвращает (width, height, rgba)."""
    try:
        width, height, rgba = png.decode(data)
    except png.PngError as exc:
        raise SkinError("Проблема с PNG: %s" % exc) from exc
    if width < 64 or height < 32:
        raise SkinError("Слишком маленький скин: %dx%d (нужно 64x64)" % (width, height))
    return width, height, rgba


# --------------------------------------------------------------- превью


def _checker(width: int, height: int) -> bytes:
    data = bytearray(width * height * 4)
    for y in range(height):
        for x in range(width):
            index = (y * width + x) * 4
            light = ((x // 2) + (y // 2)) % 2 == 0
            color = (37, 41, 49) if light else (29, 32, 39)
            data[index:index + 3] = bytes(color)
            data[index + 3] = 255
    return bytes(data)


def _paste_region(canvas, canvas_wh, skin, region, x, y, slim=False, flip=False):
    width, height, data = skin
    source_region = region
    if flip and region.startswith("left_"):
        source_region = "right_" + region[len("left_"):]
    rx, ry, rw, rh = REGIONS[source_region]
    if slim and "arm" in source_region:
        rw = 3
    if rx + rw > width or ry + rh > height:
        return canvas
    piece = png.crop(width, height, data, rx, ry, rw, rh)
    if flip and source_region != region:
        piece = png.flip_horizontal(rw, rh, piece)
    return png.paste(canvas_wh[0], canvas_wh[1], canvas, rw, rh, piece, x, y)


def render_player(skin, slim: bool = False, factor: int = 5):
    """Собирает фигурку персонажа 16x32 (вид спереди) из областей скина.

    Старый формат 64x32 не содержит левых конечностей — как и сама игра,
    достраиваем их зеркальным отражением правых.
    """
    width, height, _data = skin
    legacy = height < 64
    canvas_wh = (16, 32)
    canvas = _checker(canvas_wh[0], canvas_wh[1])
    arm_x = (0, 13 if slim else 12)
    leg_x = (4, 8)
    pieces = (
        ("right_leg", leg_x[0], 20), ("left_leg", leg_x[1], 20),
        ("body", 4, 8),
        ("right_arm", arm_x[0], 8), ("left_arm", arm_x[1], 8),
        ("head", 4, 0),
        ("right_leg_overlay", leg_x[0], 20), ("left_leg_overlay", leg_x[1], 20),
        ("body_overlay", 4, 8),
        ("right_arm_overlay", arm_x[0], 8), ("left_arm_overlay", arm_x[1], 8),
        ("head_overlay", 4, 0),
    )
    for region, x, y in pieces:
        canvas = _paste_region(canvas, canvas_wh, skin, region, x, y, slim, legacy)
    return png.scale(canvas_wh[0], canvas_wh[1], canvas, max(1, factor))


def render_head(skin, factor: int = 10):
    """Только голова (лицо + слой волос/шляпы)."""
    canvas = png.blank(8, 8)
    canvas = _paste_region(canvas, (8, 8), skin, "head", 0, 0)
    canvas = _paste_region(canvas, (8, 8), skin, "head_overlay", 0, 0)
    return png.scale(8, 8, canvas, max(1, factor))


# --------------------------------------------------------- применение


def demo_skin() -> bytes:
    """Простой «стивоподобный» скин — чтобы превью было не пустым при первом запуске."""
    data = bytearray(png.blank(64, 64))

    def fill(region: str, color, row_from: int = 0, row_to: int = None) -> None:
        rx, ry, rw, rh = REGIONS[region]
        row_to = rh if row_to is None else row_to
        for y in range(row_from, row_to):
            for x in range(rw):
                index = ((ry + y) * 64 + rx + x) * 4
                data[index:index + 4] = bytes(color)

    def pixel(region: str, x: int, y: int, color) -> None:
        rx, ry, _rw, _rh = REGIONS[region]
        index = ((ry + y) * 64 + rx + x) * 4
        data[index:index + 4] = bytes(color[:3]) + b"\xff"

    skin_tone = (198, 140, 102, 255)
    hair = (58, 38, 24, 255)
    shirt = (0, 158, 166, 255)
    pants = (52, 62, 140, 255)
    fill("head", skin_tone)
    fill("head_overlay", hair, 0, 2)
    pixel("head", 2, 3, (70, 58, 48))          # глаза и рот — чтобы лицо было узнаваемым
    pixel("head", 5, 3, (70, 58, 48))
    pixel("head", 3, 5, (140, 92, 72))
    pixel("head", 4, 5, (140, 92, 72))
    for region in ("body", "right_arm", "left_arm"):
        fill(region, shirt)
    for region in ("right_leg", "left_leg"):
        fill(region, pants)
    return png.encode(64, 64, bytes(data))


def demo_skin_rgba():
    return parse(demo_skin())


def apply(game_dir: str, nickname: str, skin_data: bytes, slim: bool = False,
          log=None) -> str:
    """Кладёт скин в skins/, собирает ресурспак и включает его в options.txt."""
    width, height, _rgba = parse(skin_data)
    target = saved_skin_path(game_dir, nickname)
    with open(target, "wb") as handle:
        handle.write(skin_data)

    pack_path = os.path.join(pack_dir(game_dir), pack_file_name(nickname))
    meta = {
        "pack": {
            "pack_format": PACK_FORMAT,
            "description": "Скин игрока %s (NeoForge Launcher)" % nickname,
            "supported_formats": {"min_inclusive": 15, "max_inclusive": 99},
        }
    }
    with zipfile.ZipFile(pack_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("pack.mcmeta", json.dumps(meta, ensure_ascii=False, indent=2))
        for name in PLAYER_TEXTURES:
            archive.writestr(name, skin_data)
    if log:
        log("Ресурспак со скином: %s (%dx%d)" % (pack_path, width, height))

    options.enable_resource_pack(game_dir, pack_file_name(nickname), True, log)
    if slim and log:
        log("Выбрана тонкая модель рук — если руки выглядят толще, смените модель в лаунчере")
    return pack_path


def remove(game_dir: str, nickname: str, log=None) -> None:
    pack_path = os.path.join(pack_dir(game_dir), pack_file_name(nickname))
    try:
        if os.path.exists(pack_path):
            os.remove(pack_path)
            if log:
                log("Ресурспак со скином удалён")
    except OSError as exc:
        if log:
            log("Не удалось удалить ресурспак: %s" % exc)
    options.enable_resource_pack(game_dir, pack_file_name(nickname), False, log)


def status(game_dir: str, nickname: str) -> dict:
    pack = os.path.join(pack_dir(game_dir), pack_file_name(nickname))
    return {
        "pack": pack,
        "pack_exists": os.path.exists(pack),
        "enabled": options.is_resource_pack_enabled(game_dir, pack_file_name(nickname)),
        "saved": saved_skin_path(game_dir, nickname),
        "sample": os.path.join(skins_dir(game_dir), "sample.png"),
    }


def current(game_dir: str, nickname: str):
    """Текущий скин (bytes) для превью: сохранённый, сохранённый ранее или образец."""
    info = status(game_dir, nickname)
    for path in (info["saved"], info["sample"]):
        if os.path.exists(path):
            try:
                with open(path, "rb") as handle:
                    return handle.read()
            except OSError:
                continue
    saved = [name for name in os.listdir(skins_dir(game_dir))
             if name.lower().endswith(".png") and name != "sample.png"]
    if saved:
        try:
            with open(os.path.join(skins_dir(game_dir), saved[0]), "rb") as handle:
                return handle.read()
        except OSError:
            pass
    return demo_skin()
