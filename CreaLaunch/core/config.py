"""Настройки лаунчера (config.json рядом с лаунчером)."""

from __future__ import annotations

import json
import os

from . import paths

# Поля, которые хранит каждая сборка (остальные настройки — общие для лаунчера).
BUILD_FIELDS = ("mode", "mc_version", "neoforge_version", "ram_mb", "game_dir", "jvm_args")

DEFAULTS = {
    "username": "Player",
    "game_dir": "",
    "ram_mb": 4096,
    "java_path": "",
    "jvm_args": "",
    "mc_version": "1.21.1",
    "mode": "neoforge",          # neoforge | vanilla
    "neoforge_version": "",      # пусто = последняя подходящая
    "skip_sounds": False,        # не качать звуки (~700 МБ)
    "download_workers": 8,
    "skin_model": "wide",        # wide = толстые руки, slim = тонкие
    "content_type": "mod",
    "content_create_only": True,
    "content_query": "",
    "enable_resource_packs": True,
    "last_world": "",
    "share_world": True,         # объявлять открытый для сети мир друзьям
    "upnp_port": 25565,          # внешний порт на роутере для игры с друзьями
    "close_launcher_on_start": False,
    "keep_console": True,
    "width": 0,
    "height": 0,
    "builds": [],                # сборки: имя + режим, версия, ОЗУ, папка игры
    "current_build": "",         # какая сборка выбрана
}

PATH = os.path.join(paths.launcher_dir(), "config.json")


class Config(dict):
    def __init__(self, data=None):
        super().__init__(DEFAULTS)
        if data:
            for k, v in data.items():
                if k in DEFAULTS:
                    self[k] = v
                else:
                    self[k] = v

    @property
    def game_dir(self) -> str:
        value = (self.get("game_dir") or "").strip()
        return value or paths.default_game_dir()

    # ------------------------------------------------------------- сборки
    def build_list(self) -> list:
        """Список сборок так, как он лежит в config.json."""
        items = self.get("builds")
        return items if isinstance(items, list) else []

    def find_build(self, name: str):
        """Сборка по имени (None, если такой нет)."""
        for build in self.build_list():
            if build.get("name") == name:
                return build
        return None

    def active_build(self) -> dict:
        """Выбранная сборка; если списка ещё нет — заводит «Основную» из настроек."""
        items = self.build_list()
        if not items:
            build = self._build_from_config("Основная")
            self["builds"] = [build]
            self["current_build"] = build["name"]
            return build
        name = self.get("current_build") or ""
        for build in items:
            if build.get("name") == name:
                return build
        self["current_build"] = items[0].get("name") or ""
        return items[0]

    def _build_from_config(self, name: str) -> dict:
        build = {"name": name}
        for field in BUILD_FIELDS:
            build[field] = self.get(field)
        return build

    def sync_active_build(self) -> None:
        """Переносит текущие настройки в выбранную сборку (перед сохранением)."""
        build = self.active_build()
        for field in BUILD_FIELDS:
            build[field] = self.get(field)

    def select_build(self, name: str) -> dict:
        """Делает сборку текущей и раскладывает её значения в настройки."""
        for build in self.build_list():
            if build.get("name") == name:
                self["current_build"] = name
                for field in BUILD_FIELDS:
                    if field in build:
                        self[field] = build[field]
                return build
        return self.active_build()

    def upsert_build(self, data: dict) -> dict:
        """Сохраняет сборку: переданные поля заменяются, остальные берутся из настроек."""
        name = (data.get("name") or "").strip()
        build = self.find_build(name)
        if build is None:
            build = self._build_from_config(name)
            self.build_list().append(build)
        for field, value in data.items():
            build[field] = value
        return build

    def rename_build(self, old: str, new: str) -> bool:
        """Переименовывает сборку (активность сохраняется)."""
        build = self.find_build(old)
        if build is None:
            return False
        build["name"] = new
        if self.get("current_build") == old:
            self["current_build"] = new
        return True

    def remove_build(self, name: str) -> bool:
        """Удаляет сборку; последнюю удалить нельзя."""
        items = self.build_list()
        if len(items) <= 1:
            return False
        for index, build in enumerate(items):
            if build.get("name") == name:
                items.pop(index)
                if self.get("current_build") == name:
                    self.select_build(items[0].get("name", ""))
                return True
        return False

    @staticmethod
    def build_label(build: dict) -> str:
        """Подпись сборки для списка: режим, версия."""
        mc_version = build.get("mc_version") or "1.21.1"
        if build.get("mode", "neoforge") == "neoforge":
            neo = (build.get("neoforge_version") or "").strip()
            return "NeoForge %s · %s" % (neo or "последняя", mc_version)
        return "Ванильная · %s" % mc_version

    def save(self) -> None:
        try:
            with open(PATH, "w", encoding="utf-8") as f:
                json.dump(dict(self), f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    @staticmethod
    def load() -> "Config":
        try:
            with open(PATH, encoding="utf-8") as f:
                return Config(json.load(f))
        except (OSError, ValueError):
            return Config()
