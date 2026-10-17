"""Мини-кодек NBT — формата, в котором Minecraft хранит servers.dat.

Поддерживаются все теги, которые встречаются в файлах игры. Значения обёрнуты в
простые подклассы int/float/str/bytes, чтобы тип не терялся при чтении и записи:
Byte, Short, Int, Long, Float, Double, String, ByteArray, IntArray, LongArray.
Compound — dict, List — list (тип элементов берётся из первого элемента).
"""

from __future__ import annotations

import gzip
import struct

TAG_END = 0
TAG_BYTE = 1
TAG_SHORT = 2
TAG_INT = 3
TAG_LONG = 4
TAG_FLOAT = 5
TAG_DOUBLE = 6
TAG_BYTE_ARRAY = 7
TAG_STRING = 8
TAG_LIST = 9
TAG_COMPOUND = 10
TAG_INT_ARRAY = 11
TAG_LONG_ARRAY = 12


class NbtError(Exception):
    pass


class Byte(int):
    pass


class Short(int):
    pass


class Int(int):
    pass


class Long(int):
    pass


class Float(float):
    pass


class Double(float):
    pass


class String(str):
    pass


class ByteArray(bytes):
    pass


class IntArray(tuple):
    pass


class LongArray(tuple):
    pass


class Compound(dict):
    pass


class List(list):
    pass


_TYPE_BY_CLASS = (
    (Byte, TAG_BYTE),
    (Short, TAG_SHORT),
    (Int, TAG_INT),
    (Long, TAG_LONG),
    (Float, TAG_FLOAT),
    (Double, TAG_DOUBLE),
    (ByteArray, TAG_BYTE_ARRAY),
    (String, TAG_STRING),
    (IntArray, TAG_INT_ARRAY),
    (LongArray, TAG_LONG_ARRAY),
    (Compound, TAG_COMPOUND),
    (List, TAG_LIST),
)


def tag_id(value) -> int:
    """Определяет тип тега по значению (для List нужен первый элемент)."""
    if isinstance(value, bool):
        return TAG_BYTE
    for cls, number in _TYPE_BY_CLASS:
        if isinstance(value, cls):
            return number
    if isinstance(value, int):
        return TAG_INT
    if isinstance(value, float):
        return TAG_DOUBLE
    if isinstance(value, str):
        return TAG_STRING
    if isinstance(value, dict):
        return TAG_COMPOUND
    if isinstance(value, (list, tuple)):
        return TAG_LIST
    raise NbtError("не понять тип значения: %r" % (value,))


class _Reader:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def take(self, count: int) -> bytes:
        if self.pos + count > len(self.data):
            raise NbtError("файл оборван на позиции %d" % self.pos)
        chunk = self.data[self.pos:self.pos + count]
        self.pos += count
        return chunk

    def numbers(self, fmt: str, count: int):
        size = struct.calcsize(fmt) * count
        values = struct.unpack(fmt, self.take(size))
        return values[0] if count == 1 else values

    def string(self) -> str:
        length = self.numbers(">H", 1)
        return self.take(length).decode("utf-8", "replace")

    def payload(self, tag: int):
        if tag == TAG_BYTE:
            return Byte(self.numbers(">b", 1))
        if tag == TAG_SHORT:
            return Short(self.numbers(">h", 1))
        if tag == TAG_INT:
            return Int(self.numbers(">i", 1))
        if tag == TAG_LONG:
            return Long(self.numbers(">q", 1))
        if tag == TAG_FLOAT:
            return Float(self.numbers(">f", 1))
        if tag == TAG_DOUBLE:
            return Double(self.numbers(">d", 1))
        if tag == TAG_BYTE_ARRAY:
            return ByteArray(self.take(max(0, self.numbers(">i", 1))))
        if tag == TAG_STRING:
            return String(self.string())
        if tag == TAG_LIST:
            element = self.numbers(">B", 1)
            count = max(0, self.numbers(">i", 1))
            return List(self.payload(element) for _ in range(count))
        if tag == TAG_COMPOUND:
            compound = Compound()
            while True:
                child = self.numbers(">B", 1)
                if child == TAG_END:
                    return compound
                name = self.string()
                compound[name] = self.payload(child)
        if tag == TAG_INT_ARRAY:
            return IntArray(self.numbers(">i", max(0, self.numbers(">i", 1))))
        if tag == TAG_LONG_ARRAY:
            return LongArray(self.numbers(">q", max(0, self.numbers(">i", 1))))
        raise NbtError("неизвестный тег: %d" % tag)


def read(data: bytes) -> Compound:
    """Читает NBT (без сжатия) и возвращает корневой Compound."""
    reader = _Reader(data)
    tag = reader.numbers(">B", 1)
    if tag != TAG_COMPOUND:
        raise NbtError("корневой тег не Compound, а %d" % tag)
    reader.string()                     # имя корня не нужно
    return reader.payload(TAG_COMPOUND)


def write(root: Compound, name: str = "") -> bytes:
    """Пишет NBT (без сжатия)."""
    if not isinstance(root, dict):
        raise NbtError("корень должен быть Compound (dict)")
    out = bytearray()
    out += struct.pack(">B", TAG_COMPOUND)
    _write_string(out, name)
    _write_compound(out, root)
    return bytes(out)


def _write_string(out: bytearray, text: str) -> None:
    raw = str(text).encode("utf-8")
    out += struct.pack(">H", len(raw))
    out += raw


def _write_payload(out: bytearray, value) -> None:
    tag = tag_id(value)
    if tag == TAG_BYTE:
        out += struct.pack(">b", int(value))
    elif tag == TAG_SHORT:
        out += struct.pack(">h", int(value))
    elif tag == TAG_INT:
        out += struct.pack(">i", int(value))
    elif tag == TAG_LONG:
        out += struct.pack(">q", int(value))
    elif tag == TAG_FLOAT:
        out += struct.pack(">f", float(value))
    elif tag == TAG_DOUBLE:
        out += struct.pack(">d", float(value))
    elif tag == TAG_BYTE_ARRAY:
        out += struct.pack(">i", len(value))
        out += bytes(value)
    elif tag == TAG_STRING:
        _write_string(out, value)
    elif tag == TAG_LIST:
        out += _write_list(out, value)
    elif tag == TAG_COMPOUND:
        _write_compound(out, value)
    elif tag == TAG_INT_ARRAY:
        out += struct.pack(">i", len(value))
        out += struct.pack(">%di" % len(value), *[int(item) for item in value])
    elif tag == TAG_LONG_ARRAY:
        out += struct.pack(">i", len(value))
        out += struct.pack(">%dq" % len(value), *[int(item) for item in value])
    else:
        raise NbtError("не записать тег %d" % tag)


def _write_list(out: bytearray, values) -> bytes:
    if not values:
        out += struct.pack(">B", TAG_END)
        out += struct.pack(">i", 0)
        return b""
    element = tag_id(values[0])
    out += struct.pack(">B", element)
    out += struct.pack(">i", len(values))
    for item in values:
        _write_payload(out, item)
    return b""


def _write_compound(out: bytearray, compound: dict) -> None:
    for key, value in compound.items():
        out += struct.pack(">B", tag_id(value))
        _write_string(out, key)
        _write_payload(out, value)
    out += struct.pack(">B", TAG_END)


def read_file(path: str) -> Compound:
    with open(path, "rb") as handle:
        blob = handle.read()
    if blob[:2] == b"\x1f\x8b":
        blob = gzip.decompress(blob)
    return read(blob)


def write_file(path: str, root: Compound, compress: bool = True) -> None:
    blob = write(root)
    if compress:
        blob = gzip.compress(blob, 6)
    with open(path, "wb") as handle:
        handle.write(blob)
