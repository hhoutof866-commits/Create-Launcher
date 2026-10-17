"""Друзья: список, адреса и приглашения (friends.json рядом с лаунчером).

Друг хранится как имя + адрес + порт (+ заметка). Адрес общий для всех способов
подключения: локальная сеть, Radmin VPN, проброшенный порт или публичный адрес
от UPnP — лаунчер просто проверяет, отвечает ли там мир.

Приглашение можно переслать другу текстом или коротким кодом (CL1.…), в котором
зашиты ник, адрес, порт и название мира.
"""

from __future__ import annotations

import base64
import json
import os
import re
import time
import zlib

from . import paths

FILE_NAME = "friends.json"
CODE_PREFIX = "CL1."
_ADDRESS_RE = re.compile(r"(?<![\w.])((?:\d{1,3}\.){3}\d{1,3}|[A-Za-z0-9][\w.-]*\.[A-Za-z]{2,})"
                         r"(?::(\d{2,5}))?")


def path() -> str:
    return os.path.join(paths.launcher_dir(), FILE_NAME)


class Friends:
    """Список друзей + свой идентификатор (по нему узнаём свои же объявления)."""

    def __init__(self, data=None, file_path=None):
        self.file = file_path or path()
        self.items = []
        self.data = {"me": {}}
        if isinstance(data, dict):
            self.data["me"] = data.get("me") or {}
            for item in data.get("items") or []:
                if isinstance(item, dict) and item.get("name"):
                    self.items.append(self._normalize(item))

    # ------------------------------------------------------------ хранилище
    @staticmethod
    def _normalize(item: dict) -> dict:
        return {
            "name": str(item.get("name", "")).strip(),
            "address": str(item.get("address", "")).strip(),
            "port": int(item.get("port") or 0),
            "note": str(item.get("note", "")),
            "world": str(item.get("world", "")),
            "last_seen": float(item.get("last_seen") or 0),
            "added": float(item.get("added") or time.time()),
        }

    @staticmethod
    def load(file_path=None) -> "Friends":
        target = file_path or path()
        try:
            with open(target, encoding="utf-8") as handle:
                return Friends(json.load(handle), file_path=target)
        except (OSError, ValueError):
            return Friends(file_path=target)

    def save(self) -> None:
        payload = {"me": self.data.get("me") or {}, "items": self.items}
        try:
            with open(self.file, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
        except OSError:
            pass

    # ---------------------------------------------------------------- свой id
    def me_id(self) -> str:
        me = self.data.setdefault("me", {})
        if not me.get("id"):
            me["id"] = base64.b16encode(os.urandom(6)).decode("ascii").lower()
            self.save()
        return me["id"]

    def me_nick(self) -> str:
        return str((self.data.get("me") or {}).get("nick") or "")

    def set_me_nick(self, nick: str) -> None:
        me = self.data.setdefault("me", {})
        if me.get("nick") != nick:
            me["nick"] = nick
            self.save()

    # ------------------------------------------------------------ список
    def list(self) -> list:
        return sorted(self.items, key=lambda item: item["name"].lower())

    def names(self) -> list:
        return [item["name"] for item in self.list()]

    def find(self, name: str):
        wanted = (name or "").strip().lower()
        for item in self.items:
            if item["name"].lower() == wanted:
                return item
        return None

    def add(self, name: str, address: str = "", port: int = 0, note: str = "") -> dict:
        """Добавляет друга или обновляет адрес у существующего."""
        clean = (name or "").strip()[:24] or "Друг"
        current = self.find(clean)
        if current is None:
            current = self._normalize({"name": clean, "address": address, "port": port,
                                       "note": note})
            self.items.append(current)
        else:
            if address:
                current["address"] = address.strip()
            if port:
                current["port"] = int(port)
            if note:
                current["note"] = note
        self.save()
        return current

    def remove(self, name: str) -> bool:
        current = self.find(name)
        if current is None:
            return False
        self.items = [item for item in self.items if item is not current]
        self.save()
        return True

    def touch(self, name: str, address: str = "", port: int = 0, world: str = "") -> dict:
        """Отмечает, что друг только что был в сети (обновляет адрес)."""
        current = self.add(name, address, port) if self.find(name) is None else self.find(name)
        if address:
            current["address"] = address.strip()
        if port:
            current["port"] = int(port)
        if world:
            current["world"] = world
        current["last_seen"] = time.time()
        self.save()
        return current

    def known_address(self, name: str):
        current = self.find(name)
        if not current or not current.get("address"):
            return None
        return current["address"], int(current.get("port") or 0)


# ------------------------------------------------------------- приглашения


def share_code(nick: str, address: str, port: int, world: str = "", note: str = "") -> str:
    """Короткий код с адресом мира — удобно переслать другу."""
    payload = {"v": 1, "nick": nick, "address": address, "port": int(port or 0),
               "world": world, "note": note}
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    packed = base64.b32encode(zlib.compress(raw, 9)).decode("ascii").rstrip("=")
    return CODE_PREFIX + packed


def parse_share_code(text: str):
    """Разбирает код CL1.… (None, если это не код или он испорчен)."""
    blob = (text or "").strip()
    index = blob.find(CODE_PREFIX)
    if index < 0:
        return None
    code = blob[index + len(CODE_PREFIX):].split()[0].strip()
    padding = "=" * (-len(code) % 8)
    try:
        raw = zlib.decompress(base64.b32decode(code + padding))
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, zlib.error):
        return None
    if not isinstance(data, dict) or not data.get("address"):
        return None
    return {"name": str(data.get("nick") or "Друг"), "address": str(data["address"]),
            "port": int(data.get("port") or 0), "world": str(data.get("world") or ""),
            "note": str(data.get("note") or "")}


def invite_text(nick: str, address: str, port: int, world: str = "") -> str:
    """Готовое сообщение, которое можно скинуть другу."""
    lines = ["Заходи ко мне в Minecraft!"]
    if world:
        lines.append("Мир: %s" % world)
    lines.append("Адрес: %s" % (("%s:%d" % (address, port)) if port else address))
    lines.append("В лаунчере: «Друзья» → «Добавить друга» → вставить это сообщение.")
    lines.append("Код: %s" % share_code(nick, address, port, world))
    return "\n".join(lines)


def parse_invite(text: str):
    """Понимает и код, и приглашение, и просто «Вася 26.0.0.5:51234»."""
    value = (text or "").strip()
    if not value:
        return None
    coded = parse_share_code(value)
    if coded:
        return coded
    match = _ADDRESS_RE.search(value)
    if not match:
        return None
    address = match.group(1)
    port = int(match.group(2)) if match.group(2) else 0
    rest = (value[:match.start()] + " " + value[match.end():])
    name = ""
    for line in rest.splitlines():
        clean = line.strip(" :—-\t")
        for prefix in ("Мир", "Код", "Адрес", "В лаунчере", "Мой ник", "Ник"):
            if clean.lower().startswith(prefix.lower()):
                clean = ""
                break
        if clean:
            name = clean.split()[:2]
            name = " ".join(name)[:24]
            break
    return {"name": name or "Друг", "address": address, "port": port, "world": "", "note": ""}
