"""Сеть для игры с друзьями: то, что делает Radmin VPN, но без драйвера.

Логика простая и «сетевая», как у самой игры:

* Minecraft, открывая мир «для сети», рассылает UDP-объявление на мультикаст
  224.0.2.60:4445 — мы его ловим и показываем мир в списке (в том числе через
  Radmin VPN / Hamachi / ZeroTier / обычный Wi-Fi).
* Свой лаунчер умеет так же: раз в пару секунд объявляет в сеть «у меня открыт
  мир, порт такой-то», чтобы друг увидел тебя без ручного ввода адреса.
* Порты мира и объявлений проверяются TCP-подключением (жив ли сервер).

Никаких драйверов и служб: играем через уже существующую локальную сеть
(в т.ч. виртуальную), а если нужно пробросить порт — есть UPnP (core/upnp.py).
"""

from __future__ import annotations

import ctypes
import json
import re
import select
import socket
import struct
import sys
import threading
import time
from ipaddress import IPv4Address, IPv4Network

_IS_WINDOWS = sys.platform == "win32"

LAN_GROUP = "224.0.2.60"        # группа, которую слушает клиент Minecraft
LAN_PORT = 4445
BEACON_GROUP = "239.255.42.99"  # группа для объявлений лаунчеров
BEACON_PORT = 4446
APP_TAG = "CreaLaunch"
PING_MARK = "CreaLaunch-поиск"    # метка своего пинга, чтобы не принять его за мир
DEFAULT_PORT = 25565

_SERVING_RE = re.compile(r"(?:Started serving on|Local game hosted on port)\s+(\d+)")


# ------------------------------------------------------------------ адреса


def _windows_addresses():
    """Список локальных IPv4 через GetAdaptersAddresses (с именами адаптеров)."""
    from ctypes import wintypes

    class SockAddr(ctypes.Structure):
        _fields_ = [("sa_family", wintypes.USHORT), ("sa_data", ctypes.c_char * 14)]

    class SocketAddress(ctypes.Structure):
        _fields_ = [("lpSockaddr", ctypes.POINTER(SockAddr)), ("iSockaddrLength", ctypes.c_int)]

    class Unicast(ctypes.Structure):
        pass

    Unicast._fields_ = [
        ("Length", wintypes.ULONG), ("Flags", wintypes.DWORD),
        ("Next", ctypes.POINTER(Unicast)), ("Address", SocketAddress),
        ("PrefixOrigin", ctypes.c_int), ("SuffixOrigin", ctypes.c_int),
        ("DadState", ctypes.c_int), ("ValidLifetime", wintypes.ULONG),
        ("PreferredLifetime", wintypes.ULONG), ("LeaseLifetime", wintypes.ULONG),
        ("OnLinkPrefixLength", ctypes.c_ubyte),
    ]

    class Adapter(ctypes.Structure):
        pass

    Adapter._fields_ = [
        ("Length", wintypes.ULONG), ("IfIndex", wintypes.DWORD),
        ("Next", ctypes.POINTER(Adapter)), ("AdapterName", ctypes.c_char_p),
        ("FirstUnicastAddress", ctypes.POINTER(Unicast)),
        ("FirstAnycastAddress", ctypes.c_void_p), ("FirstMulticastAddress", ctypes.c_void_p),
        ("FirstDnsServerAddress", ctypes.c_void_p), ("DnsSuffix", ctypes.c_wchar_p),
        ("Description", ctypes.c_wchar_p), ("FriendlyName", ctypes.c_wchar_p),
        ("PhysicalAddress", ctypes.c_ubyte * 8), ("PhysicalAddressLength", wintypes.DWORD),
        ("Flags", wintypes.DWORD), ("Mtu", wintypes.DWORD), ("IfType", wintypes.DWORD),
        ("OperStatus", ctypes.c_int),
    ]

    AF_UNSPEC, AF_INET, IF_OPER_UP = 0, 2, 1
    flags = 0x2 | 0x4 | 0x8 | 0x10          # без anycast/multicast/dns, но с префиксами
    get = ctypes.windll.iphlpapi.GetAdaptersAddresses
    get.argtypes = [wintypes.ULONG, wintypes.ULONG, ctypes.c_void_p,
                    ctypes.POINTER(Adapter), ctypes.POINTER(wintypes.ULONG)]
    size = wintypes.ULONG(32768)
    buffer = ctypes.create_string_buffer(size.value)
    result = get(AF_UNSPEC, flags, None, ctypes.cast(buffer, ctypes.POINTER(Adapter)),
                 ctypes.byref(size))
    if result != 0:                          # 111 = не хватило буфера
        buffer = ctypes.create_string_buffer(size.value)
        result = get(AF_UNSPEC, flags, None, ctypes.cast(buffer, ctypes.POINTER(Adapter)),
                     ctypes.byref(size))
    if result != 0:
        return []

    found = []
    current = ctypes.cast(buffer, ctypes.POINTER(Adapter))
    while bool(current):
        adapter = current.contents
        if adapter.OperStatus == IF_OPER_UP:
            name = adapter.FriendlyName or adapter.Description or ""
            unicast = adapter.FirstUnicastAddress
            while bool(unicast):
                item = unicast.contents
                pointer = item.Address.lpSockaddr
                if bool(pointer):
                    raw = ctypes.string_at(pointer, item.Address.iSockaddrLength or 16)
                    if len(raw) >= 8 and struct.unpack("<H", raw[:2])[0] == AF_INET:
                        address = socket.inet_ntoa(raw[4:8])
                        found.append({
                            "ip": address,
                            "broadcast": _broadcast(address, item.OnLinkPrefixLength),
                            "name": name,
                            "prefix": int(item.OnLinkPrefixLength),
                        })
                unicast = item.Next
        current = adapter.Next
    return found


def _broadcast(address: str, prefix: int) -> str:
    """Широковещательный адрес подсети (для 26.0.0.5/8 это 26.255.255.255)."""
    try:
        if not prefix or prefix > 32:
            return "255.255.255.255"
        network = IPv4Network("%s/%d" % (address, prefix), strict=False)
        return str(network.broadcast_address)
    except ValueError:
        return "255.255.255.255"


def _is_usable(address: str) -> bool:
    try:
        parsed = IPv4Address(address)
    except ValueError:
        return False
    return not (parsed.is_loopback or parsed.is_link_local or parsed.is_unspecified
                or parsed.is_multicast or str(parsed).startswith("127."))


VPN_HINTS = ("radmin", "hamachi", "vpn", "zerotier", "tailscale", "tap", "tun")


def best_share_address(items=None) -> str:
    """Адрес, который называют другу: сначала виртуальная сеть (Radmin VPN и похожие)."""
    items = local_addresses() if items is None else items
    for item in items:
        name = (item.get("name") or "").lower()
        if any(word in name for word in VPN_HINTS):
            return item["ip"]
    return items[0]["ip"] if items else primary_address()


def local_addresses(only_usable: bool = True) -> list:
    """Локальные IPv4-адреса с именем адаптера и широковещательным адресом."""
    found = []
    if _IS_WINDOWS:
        try:
            found = _windows_addresses()
        except Exception:                    # noqa: BLE001
            found = []
    if not found:
        found = _fallback_addresses()
    primary = primary_address()
    seen = set()
    result = []
    for item in found:
        key = (item["ip"], item["name"])
        if key in seen:
            continue
        seen.add(key)
        if only_usable and not _is_usable(item["ip"]):
            continue
        result.append(item)
    # сначала «главный» адрес машины, дальше по имени адаптера
    result.sort(key=lambda item: (item["ip"] != primary, item["name"], item["ip"]))
    return result


def _fallback_addresses():
    found = []
    try:
        for address in socket.gethostbyname_ex(socket.gethostname())[2]:
            found.append({"ip": address, "broadcast": _broadcast(address, 24), "name": "",
                          "prefix": 24})
    except OSError:
        pass
    primary = primary_address()
    if primary:
        found.append({"ip": primary, "broadcast": _broadcast(primary, 24), "name": "", "prefix": 24})
    return found


def primary_address() -> str:
    """Адрес, через который машина выходит в сеть (без единого пакета)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 53))
        return sock.getsockname()[0]
    except OSError:
        return ""
    finally:
        sock.close()


# ------------------------------------------------------- миры Minecraft в сети


def parse_lan_ping(text: str):
    """Разбирает ответ мира «открыт для сети»: [MOTD]…[/MOTD][ADDR]…[/ADDR][PORT]…[/PORT]."""
    if "[MOTD]" not in text or "[PORT]" not in text:
        return None

    def between(start: str, end: str) -> str:
        try:
            begin = text.index(start) + len(start)
            finish = text.index(end, begin)
        except ValueError:
            return ""
        return text[begin:finish].strip()

    motd = between("[MOTD]", "[/MOTD]")
    address = between("[ADDR]", "[/ADDR]")
    port_text = between("[PORT]", "[/PORT]")
    if not port_text.isdigit():
        return None
    if ":" in address:                       # иногда игра пишет «адрес:порт»
        host, _, maybe_port = address.rpartition(":")
        if maybe_port.isdigit():
            address = host
    return {"motd": motd or "Мир Minecraft", "address": address, "port": int(port_text)}


def lan_ping_bytes(motd: str = APP_TAG, address: str = "0.0.0.0", port: int = 0) -> bytes:
    return ("[MOTD]%s[/MOTD][ADDR]%s[/ADDR][PORT]%s[/PORT]" % (motd, address, port)).encode("utf-8")


def started_serving_port(line: str):
    """Порт мира, который игрок только что открыл для сети (по строке лога игры)."""
    match = _SERVING_RE.search(line or "")
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _listen_socket(port: int, group: str = "", log=None) -> "socket.socket | None":
    """UDP-сокет, слушающий порт и (если указано) мультикаст-группу на всех адаптерах."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("", port))
    except OSError as exc:
        if log:
            log("Порт %d занят (%s) — пропускаю этот способ поиска" % (port, exc))
        sock.close()
        return None
    if group:
        for item in local_addresses() + [{"ip": "0.0.0.0"}]:
            try:
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                                socket.inet_aton(group) + socket.inet_aton(item["ip"]))
            except OSError:
                continue
    sock.settimeout(0.25)
    return sock


def _send_to_network(sock: socket.socket, port: int, blob: bytes, group: str = "") -> None:
    """Шлёт датаграмму всем, кто может нас услышать: broadcast + мультикаст."""
    targets = [("255.255.255.255", port)]
    for item in local_addresses():
        if item.get("broadcast"):
            targets.append((item["broadcast"], port))
    if group:
        targets.append((group, port))
    for host, target_port in targets:
        try:
            sock.sendto(blob, (host, target_port))
        except OSError:
            continue


def scan(timeout: float = 2.5, log=None, my_id: str = "", ignore_hosts=None) -> dict:
    """Ищет миры, открытые для сети, и объявления других лаунчеров.

    Один проход: слушаем порт игры (4445) и порт объявлений (4446).
    Свои собственные миры и объявления отбрасываем (ignore_hosts — кого считать собой).
    """
    game_sock = _listen_socket(LAN_PORT, LAN_GROUP, log)
    beacon_sock = _listen_socket(BEACON_PORT, BEACON_GROUP, log)
    sockets = [item for item in (game_sock, beacon_sock) if item is not None]
    result = {"worlds": [], "friends": [], "errors": []}
    if not sockets:
        result["errors"].append("не удалось занять порты 4445/4446 — игру видно не будет")
        return result

    mine = set(ignore_hosts) if ignore_hosts is not None else \
        {item["ip"] for item in local_addresses(only_usable=False)}
    if game_sock is not None:
        _send_to_network(game_sock, LAN_PORT, lan_ping_bytes(PING_MARK), LAN_GROUP)

    seen_worlds, seen_friends = set(), set()
    deadline = time.time() + max(0.5, timeout)
    while True:
        left = deadline - time.time()
        if left <= 0:
            break
        ready = select.select(sockets, [], [], min(0.25, left))[0]
        for sock in ready:
            try:
                payload, sender = sock.recvfrom(4096)
            except OSError:
                continue
            text = payload.decode("utf-8", "replace")
            if sock is game_sock:
                world = parse_lan_ping(text)
                if not world or world["motd"] == PING_MARK or world["port"] <= 0:
                    continue                  # это чей-то пинг, а не открытый мир
                if sender[0] in mine:
                    continue                  # мой собственный мир
                world["host"] = sender[0]     # как и игра, доверяем адресу отправителя
                key = (world["host"], world["port"])
                if key not in seen_worlds:
                    seen_worlds.add(key)
                    world["source"] = "игра"
                    result["worlds"].append(world)
                continue
            try:
                data = json.loads(text)
            except ValueError:
                continue
            if not isinstance(data, dict) or data.get("app") != APP_TAG:
                continue
            if sender[0] in mine or (my_id and data.get("id") == my_id):
                continue                      # это объявление моего лаунчера
            key = (sender[0], data.get("port"))
            if key in seen_friends:
                continue
            seen_friends.add(key)
            result["friends"].append({
                "host": sender[0],
                "port": int(data.get("port") or 0),
                "nick": str(data.get("nick") or "Друг"),
                "world": str(data.get("world") or ""),
                "players": int(data.get("players") or 0),
                "state": str(data.get("state") or ""),
                "source": "лаунчер",
            })
    for sock in sockets:
        sock.close()
    result["worlds"].sort(key=lambda item: item["motd"].lower())
    result["friends"].sort(key=lambda item: item["nick"].lower())
    return result


# ------------------------------------------------------------------ объявления


def beacon_payload(nick: str, port: int, world: str = "", players: int = 0,
                   state: str = "открыт для сети", ident: str = "") -> bytes:
    data = {"app": APP_TAG, "nick": nick, "port": int(port), "world": world,
            "players": int(players), "state": state, "id": ident, "ts": int(time.time())}
    return json.dumps(data, ensure_ascii=False).encode("utf-8")


class Beacon(threading.Thread):
    """Раз в пару секунд объявляет в локальную сеть: «у меня открыт мир».

    Так друг видит тебя в списке «рядом» и подключается одной кнопкой.
    """

    def __init__(self, provider, interval: float = 2.0, port: int = BEACON_PORT):
        super().__init__(daemon=True)
        self.provider = provider          # функция -> (nick, port, world, players, state, id)
        self.interval = interval
        self.port = port
        self._stop = threading.Event()
        self.sent = 0

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        try:
            while not self._stop.is_set():
                try:
                    nick, port, world, players, state, ident = self.provider()
                except Exception:            # noqa: BLE001
                    break
                if port:
                    blob = beacon_payload(nick, port, world, players, state, ident)
                    _send_to_network(sock, self.port, blob, BEACON_GROUP)
                    self.sent += 1
                self._stop.wait(self.interval)
        finally:
            sock.close()


# ------------------------------------------------------------------- проверки


def parse_address(text: str):
    """«26.0.0.5:51234» → (host, port). Без порта считается 25565."""
    value = (text or "").strip().replace("minecraft://", "")
    if not value:
        raise ValueError("пустой адрес")
    if value.startswith("["):                # [ipv6]:port
        host, _, rest = value[1:].partition("]")
        port = rest.lstrip(":")
        return host, int(port) if port.isdigit() else DEFAULT_PORT
    if ":" in value:
        host, _, port = value.rpartition(":")
        if not port.isdigit():
            raise ValueError("порт должен быть числом: %s" % port)
        return host.strip(), int(port)
    return value, DEFAULT_PORT


def format_address(host: str, port: int) -> str:
    if not port or int(port) == DEFAULT_PORT:
        return host
    return "%s:%d" % (host, int(port))


def probe(host: str, port: int, timeout: float = 1.5) -> bool:
    """Отвечает ли на этом адресе открытый мир (обычная TCP-проверка)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        return sock.connect_ex((host, int(port))) == 0
    except OSError:
        return False
    finally:
        sock.close()


def is_local(host: str) -> bool:
    """Адрес принадлежит этой машине?"""
    if host in ("localhost", "127.0.0.1", "0.0.0.0"):
        return True
    return any(item["ip"] == host for item in local_addresses(only_usable=False))
