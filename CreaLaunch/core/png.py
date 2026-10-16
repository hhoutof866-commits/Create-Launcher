"""Минимальный PNG-кодек (RGBA) без внешних зависимостей.

Нужен системе скинов: читаем PNG скина, собираем из него превью персонажа,
отдаём превью в tkinter и упаковываем текстуры в ресурспак.
"""

from __future__ import annotations

import struct
import zlib

SIGNATURE = b"\x89PNG\r\n\x1a\n"


class PngError(Exception):
    """Файл не является корректным PNG, который мы умеем читать."""


# --------------------------------------------------------------- чтение


def read(path: str):
    with open(path, "rb") as handle:
        return decode(handle.read())


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def decode(data: bytes):
    """PNG -> (width, height, rgba_bytes). Поддержка 8-битных, без interlace."""
    if len(data) < 8 or data[:8] != SIGNATURE:
        raise PngError("это не PNG-файл")
    position = 8
    header = None
    compressed = bytearray()
    palette = None
    transparency = None
    while position + 8 <= len(data):
        length, chunk_type = struct.unpack(">I4s", data[position:position + 8])
        position += 8
        chunk = data[position:position + length]
        position += length + 4
        if chunk_type == b"IHDR":
            header = struct.unpack(">IIBBBBB", chunk[:13])
        elif chunk_type == b"PLTE":
            palette = chunk
        elif chunk_type == b"tRNS":
            transparency = chunk
        elif chunk_type == b"IDAT":
            compressed.extend(chunk)
        elif chunk_type == b"IEND":
            break
    if header is None:
        raise PngError("нет заголовка IHDR")
    width, height, depth, color_type, _compression, _filter, interlace = header
    if depth != 8:
        raise PngError("поддерживается только 8 бит на канал (получено %d)" % depth)
    if interlace:
        raise PngError("PNG с чередованием строк не поддерживается")
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color_type)
    if channels is None:
        raise PngError("неизвестный тип цвета %d" % color_type)
    if not compressed:
        raise PngError("нет данных изображения")
    try:
        raw = zlib.decompress(bytes(compressed))
    except zlib.error as exc:
        raise PngError("данные повреждены: %s" % exc) from exc
    stride = width * channels
    if len(raw) < (stride + 1) * height:
        raise PngError("данные обрезаны")

    out = bytearray(width * height * 4)
    previous = bytearray(stride)
    offset = 0
    for y in range(height):
        filter_type = raw[offset]
        offset += 1
        line = bytearray(raw[offset:offset + stride])
        offset += stride
        if filter_type == 1:
            for i in range(channels, stride):
                line[i] = (line[i] + line[i - channels]) & 0xFF
        elif filter_type == 2:
            for i in range(stride):
                line[i] = (line[i] + previous[i]) & 0xFF
        elif filter_type == 3:
            for i in range(stride):
                left = line[i - channels] if i >= channels else 0
                line[i] = (line[i] + ((left + previous[i]) >> 1)) & 0xFF
        elif filter_type == 4:
            for i in range(stride):
                a = line[i - channels] if i >= channels else 0
                b = previous[i]
                c = previous[i - channels] if i >= channels else 0
                line[i] = (line[i] + _paeth(a, b, c)) & 0xFF
        elif filter_type != 0:
            raise PngError("неизвестный фильтр строки %d" % filter_type)
        previous = line
        row = y * width * 4
        if color_type == 6:
            out[row:row + width * 4] = line
        elif color_type == 2:
            for x in range(width):
                out[row + x * 4:row + x * 4 + 3] = line[x * 3:x * 3 + 3]
                out[row + x * 4 + 3] = 255
        elif color_type == 0:
            for x in range(width):
                grey = line[x]
                out[row + x * 4] = out[row + x * 4 + 1] = out[row + x * 4 + 2] = grey
                out[row + x * 4 + 3] = 255
        elif color_type == 4:
            for x in range(width):
                grey = line[x * 2]
                out[row + x * 4] = out[row + x * 4 + 1] = out[row + x * 4 + 2] = grey
                out[row + x * 4 + 3] = line[x * 2 + 1]
        else:  # color_type == 3, палитра
            if palette is None:
                raise PngError("палитровый PNG без PLTE")
            for x in range(width):
                index = line[x]
                base = index * 3
                if base + 2 >= len(palette):
                    raise PngError("индекс палитры вне диапазона")
                out[row + x * 4] = palette[base]
                out[row + x * 4 + 1] = palette[base + 1]
                out[row + x * 4 + 2] = palette[base + 2]
                out[row + x * 4 + 3] = transparency[index] if transparency and index < len(transparency) else 255
    return width, height, bytes(out)


# --------------------------------------------------------------- запись


def encode(width: int, height: int, rgba: bytes) -> bytes:
    if len(rgba) < width * height * 4:
        raise PngError("недостаточно данных для %dx%d" % (width, height))
    raw = bytearray()
    stride = width * 4
    for y in range(height):
        raw.append(0)
        raw.extend(rgba[y * stride:(y + 1) * stride])
    return b"".join([
        SIGNATURE,
        _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)),
        _chunk(b"IDAT", zlib.compress(bytes(raw), 9)),
        _chunk(b"IEND", b""),
    ])


def _chunk(chunk_type: bytes, payload: bytes) -> bytes:
    return (struct.pack(">I", len(payload)) + chunk_type + payload
            + struct.pack(">I", zlib.crc32(chunk_type + payload) & 0xFFFFFFFF))


def write(path: str, width: int, height: int, rgba: bytes) -> None:
    with open(path, "wb") as handle:
        handle.write(encode(width, height, rgba))


# ------------------------------------------------------- операции с картинкой


def blank(width: int, height: int, color=(0, 0, 0, 0)) -> bytes:
    pixel = bytes(color)
    return pixel * (width * height)


def crop(width: int, height: int, rgba: bytes, x: int, y: int, w: int, h: int) -> bytes:
    """Вырезает прямоугольник, вышедшие за границы пиксели — прозрачные."""
    out = bytearray(w * h * 4)
    for row in range(h):
        source_y = y + row
        if source_y < 0 or source_y >= height:
            continue
        for column in range(w):
            source_x = x + column
            if source_x < 0 or source_x >= width:
                continue
            source = (source_y * width + source_x) * 4
            target = (row * w + column) * 4
            out[target:target + 4] = rgba[source:source + 4]
    return bytes(out)


def paste(dst_width: int, dst_height: int, dst: bytes, src_width: int, src_height: int,
          src: bytes, x: int, y: int, blend: bool = True) -> bytes:
    """Накладывает src на dst с учётом прозрачности (пиксель за пикселем)."""
    out = bytearray(dst)
    for row in range(src_height):
        target_y = y + row
        if target_y < 0 or target_y >= dst_height:
            continue
        for column in range(src_width):
            target_x = x + column
            if target_x < 0 or target_x >= dst_width:
                continue
            source = (row * src_width + column) * 4
            alpha = src[source + 3]
            if alpha == 0:
                continue
            target = (target_y * dst_width + target_x) * 4
            if not blend or alpha == 255:
                out[target:target + 4] = src[source:source + 4]
                continue
            inverse = 255 - alpha
            for channel in range(3):
                out[target + channel] = (src[source + channel] * alpha
                                         + out[target + channel] * inverse) // 255
            out[target + 3] = max(out[target + 3], alpha)
    return bytes(out)


def flip_horizontal(width: int, height: int, rgba: bytes) -> bytes:
    """Зеркалит изображение по горизонтали (нужно для старых скинов 64x32)."""
    out = bytearray(len(rgba))
    for row in range(height):
        base = row * width * 4
        for column in range(width):
            source = base + (width - 1 - column) * 4
            target = base + column * 4
            out[target:target + 4] = rgba[source:source + 4]
    return bytes(out)


def scale(width: int, height: int, rgba: bytes, factor: int) -> tuple:
    """Увеличение «по пикселям» (nearest neighbour) — сохраняет пиксель-арт."""
    if factor <= 1:
        return width, height, rgba
    out_width, out_height = width * factor, height * factor
    out = bytearray(out_width * out_height * 4)
    for row in range(height):
        base = bytearray()
        for column in range(width):
            source = (row * width + column) * 4
            base.extend(rgba[source:source + 4] * factor)
        for step in range(factor):
            target = (row * factor + step) * out_width * 4
            out[target:target + out_width * 4] = base
    return out_width, out_height, bytes(out)


def to_photo(width: int, height: int, rgba: bytes):
    """Готовит PNG в base64 — для tkinter.PhotoImage(data=...)."""
    import base64

    return base64.b64encode(encode(width, height, rgba)).decode("ascii")
