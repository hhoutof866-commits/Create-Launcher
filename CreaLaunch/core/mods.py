"""Менеджер модов: содержимое каталога mods."""

from __future__ import annotations

import os
import shutil

DISABLED_SUFFIX = ".disabled"


class Mod:
    def __init__(self, path: str):
        self.path = path
        self.name = os.path.basename(path)
        self.enabled = not self.name.endswith(DISABLED_SUFFIX)
        try:
            self.size = os.path.getsize(path)
        except OSError:
            self.size = 0

    @property
    def display_name(self) -> str:
        name = self.name
        if name.endswith(DISABLED_SUFFIX):
            name = name[: -len(DISABLED_SUFFIX)]
        return name

    def __str__(self):
        return "%s (%s, %.1f КБ)" % (self.display_name, "включён" if self.enabled else "выключен",
                                     self.size / 1024.0)


def mods_dir(game_dir: str) -> str:
    path = os.path.join(game_dir, "mods")
    os.makedirs(path, exist_ok=True)
    return path


def list_mods(game_dir: str):
    directory = mods_dir(game_dir)
    mods = []
    for name in sorted(os.listdir(directory), key=str.lower):
        if not name.lower().endswith((".jar", ".jar" + DISABLED_SUFFIX, ".zip", ".zip" + DISABLED_SUFFIX)):
            continue
        path = os.path.join(directory, name)
        if os.path.isfile(path):
            mods.append(Mod(path))
    return mods


def set_enabled(path: str, enabled: bool) -> str:
    if enabled and path.endswith(DISABLED_SUFFIX):
        target = path[: -len(DISABLED_SUFFIX)]
    elif not enabled and not path.endswith(DISABLED_SUFFIX):
        target = path + DISABLED_SUFFIX
    else:
        return path
    if os.path.exists(target):
        raise RuntimeError("Файл уже существует: %s" % os.path.basename(target))
    os.rename(path, target)
    return target


def delete(path: str) -> None:
    os.remove(path)


def add(game_dir: str, source_paths):
    directory = mods_dir(game_dir)
    added = []
    for source in source_paths:
        if not os.path.isfile(source):
            continue
        target = os.path.join(directory, os.path.basename(source))
        if os.path.abspath(source) == os.path.abspath(target):
            continue
        shutil.copy2(source, target)
        added.append(target)
    return added
