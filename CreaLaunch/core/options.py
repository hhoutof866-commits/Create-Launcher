"""Файл options.txt: включение ресурспаков и слоёв скина."""

from __future__ import annotations

import json
import os

SKIN_PART_KEYS = (
    "modelPart_cape",
    "modelPart_jacket",
    "modelPart_left_sleeve",
    "modelPart_right_sleeve",
    "modelPart_left_pants_leg",
    "modelPart_right_pants_leg",
    "modelPart_hat",
)


def path_of(game_dir: str) -> str:
    return os.path.join(game_dir, "options.txt")


def load(game_dir: str):
    """Список пар [ключ, значение] в исходном порядке (значение может быть None)."""
    entries = []
    try:
        with open(path_of(game_dir), encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.rstrip("\r\n")
                if not line:
                    continue
                if ":" in line:
                    key, value = line.split(":", 1)
                    entries.append([key, value])
                else:
                    entries.append([line, None])
    except OSError:
        return []
    return entries


def save(game_dir: str, entries) -> None:
    os.makedirs(game_dir, exist_ok=True)
    with open(path_of(game_dir), "w", encoding="utf-8") as handle:
        for key, value in entries:
            handle.write(key if value is None else "%s:%s" % (key, value))
            handle.write("\n")


def get(entries, key):
    for item in entries:
        if item[0] == key:
            return item[1]
    return None


def set_value(entries, key, value) -> None:
    for item in entries:
        if item[0] == key:
            item[1] = value
            return
    entries.append([key, value])


def resource_packs(entries):
    raw = get(entries, "resourcePacks")
    if not raw:
        return ["vanilla"]
    try:
        packs = json.loads(raw)
    except ValueError:
        return ["vanilla"]
    if not isinstance(packs, list):
        return ["vanilla"]
    return [str(item) for item in packs]


def _dump(packs) -> str:
    return json.dumps(packs, separators=(",", ":"), ensure_ascii=False)


def enable_resource_pack(game_dir: str, file_name: str, enable: bool = True,
                         log=None) -> None:
    """Включает/выключает ресурспак file/<file_name> и открывает слои скина."""
    entries = load(game_dir)
    packs = resource_packs(entries)
    wanted = "file/" + file_name
    packs = [pack for pack in packs if pack != wanted]
    if enable:
        packs.append(wanted)
        for key in SKIN_PART_KEYS:
            set_value(entries, key, "true")
    if "vanilla" not in packs:
        packs.insert(0, "vanilla")
    set_value(entries, "resourcePacks", _dump(packs))
    incompatible = get(entries, "incompatibleResourcePacks")
    if incompatible:
        try:
            values = json.loads(incompatible)
            if isinstance(values, list):
                values = [value for value in values if value != wanted]
                set_value(entries, "incompatibleResourcePacks", _dump(values))
        except ValueError:
            pass
    save(game_dir, entries)
    if log:
        log("Ресурспак %s %s в options.txt" % (file_name, "включён" if enable else "выключен"))


def is_resource_pack_enabled(game_dir: str, file_name: str) -> bool:
    return ("file/" + file_name) in resource_packs(load(game_dir))
