"""Настройки лаунчера (config.json рядом с лаунчером)."""

from __future__ import annotations

import json
import os

from . import paths

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
    "close_launcher_on_start": False,
    "keep_console": True,
    "width": 0,
    "height": 0,
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
