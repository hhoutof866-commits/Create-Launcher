"""Основы авторизации. Вход в Microsoft не подключён — используется офлайн-профиль."""

from __future__ import annotations

import hashlib
import re
import uuid

_ALLOWED = re.compile(r"[^A-Za-z0-9_]")


def offline_uuid(username: str) -> str:
    """Тот же алгоритм, что UUID.nameUUIDFromBytes в Java (version 3, MD5)."""
    digest = bytearray(hashlib.md5(("OfflinePlayer:" + username).encode("utf-8")).digest())
    digest[6] = (digest[6] & 0x0F) | 0x30   # версия 3
    digest[8] = (digest[8] & 0x3F) | 0x80   # вариант RFC 4122
    return str(uuid.UUID(bytes=bytes(digest)))


def sanitize_username(name: str) -> str:
    """Ник Minecraft: только латиница, цифры и подчёркивание, до 16 символов."""
    name = _ALLOWED.sub("", (name or "").strip())
    return name[:16] or "Player"
