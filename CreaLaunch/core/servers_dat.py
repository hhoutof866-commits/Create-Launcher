"""servers.dat — список серверов в игре.

Лаунчер дописывает туда друзей, чтобы они были видны в сетевой игре Minecraft
(и чтобы автозаход `--quickPlayMultiplayer` смотрелся естественно).
Чужой файл не портим: читаем что было, обновляем только нужную запись.
"""

from __future__ import annotations

import os
import tempfile

from . import nbt
from .nbt import Byte, Compound, List, String

FILE_NAME = "servers.dat"


def path(game_dir: str) -> str:
    return os.path.join(game_dir, FILE_NAME)


def load(game_dir: str) -> Compound:
    """Читает servers.dat (если файла нет — пустая заготовка)."""
    target = path(game_dir)
    if not os.path.exists(target):
        return Compound({"servers": List()})
    try:
        root = nbt.read_file(target)          # сам поймёт, сжат файл или нет
    except (OSError, nbt.NbtError):
        return Compound({"servers": List()})
    if not isinstance(root.get("servers"), list):
        root["servers"] = List()
    return root


def servers(root: Compound) -> list:
    items = root.get("servers")
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def save(game_dir: str, root: Compound) -> str:
    """Пишет servers.dat атомарно (на случай, если игра читает его в этот момент).

    Важно: в 1.21.1 файл лежит без сжатия (gzip только у level.dat), поэтому пишем
    как есть — иначе игра не может прочитать список и пишет «Invalid tag id».
    """
    os.makedirs(game_dir, exist_ok=True)
    target = path(game_dir)
    handle = tempfile.NamedTemporaryFile(delete=False, dir=game_dir, suffix=".tmp")
    try:
        handle.write(nbt.write(root))
        handle.close()
        os.replace(handle.name, target)
    except Exception:
        handle.close()
        try:
            os.unlink(handle.name)
        except OSError:
            pass
        raise
    return target


def entry(name: str, address: str, icon: str = "", hidden: bool = False) -> Compound:
    """Запись сервера в формате игры."""
    data = Compound({
        "name": String(name),
        "ip": String(address),
        "acceptTextures": Byte(0),
        "hidden": Byte(1 if hidden else 0),
    })
    if icon:
        data["icon"] = String(icon)
    return data


def find(root: Compound, name: str):
    """Ищет запись по имени (без учёта регистра)."""
    wanted = name.strip().lower()
    for item in servers(root):
        if str(item.get("name", "")).strip().lower() == wanted:
            return item
    return None


def upsert(game_dir: str, name: str, address: str, icon: str = "",
           keep_icon: bool = True) -> Compound:
    """Добавляет друга в список серверов или обновляет адрес существующей записи.

    Другие серверы и их поля остаются на месте.
    """
    root = load(game_dir)
    items = root.setdefault("servers", List())
    if not isinstance(items, list):
        items = root["servers"] = List()
    current = find(root, name)
    if current is None:
        current = entry(name, address, icon)
        items.append(current)
    else:
        current["name"] = String(name)
        current["ip"] = String(address)
        if icon:
            current["icon"] = String(icon)
        elif not keep_icon and "icon" in current:
            del current["icon"]
        if "acceptTextures" not in current:
            current["acceptTextures"] = Byte(0)
    save(game_dir, root)
    return current


def remove(game_dir: str, name: str) -> bool:
    """Убирает запись по имени. True, если что-то удалили."""
    root = load(game_dir)
    items = servers(root)
    current = find(root, name)
    if current is None:
        return False
    root["servers"] = List(item for item in items if item is not current)
    save(game_dir, root)
    return True


def names(game_dir: str) -> list:
    return [str(item.get("name", "")) for item in servers(load(game_dir))]
