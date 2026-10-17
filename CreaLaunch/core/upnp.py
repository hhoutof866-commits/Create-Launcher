"""UPnP: попросить роутер пробросить порт, чтобы друг зашёл снаружи.

Это «сетевая» часть без Radmin VPN: если у провайдера есть публичный адрес и на
роутере включён UPnP, лаунчер сам открывает порт и показывает адрес вида
1.2.3.4:25565, который можно переслать другу. Если UPnP выключен или адрес
непубличный (CGNAT), честно говорим об этом — тогда путь через Radmin VPN.

Всё «по-простому»: SSDP-поиск шлюза, затем SOAP-команды AddPortMapping /
DeletePortMapping / GetExternalIPAddress. Только стандартная библиотека.
"""

from __future__ import annotations

import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from ipaddress import IPv4Address

SSDP_ADDR = "239.255.255.250"
SSDP_PORT = 1900
USER_AGENT = "CreaLaunch/1.0 UPnP/1.1"
SERVICE_KINDS = ("WANIPConnection", "WANPPPConnection")
DEFAULT_EXTERNAL_PORT = 25565


class UpnpError(Exception):
    pass


def _strip_namespaces(text: str) -> str:
    text = re.sub(r"<(/?)([A-Za-z0-9_.-]+):", r"<\1", text)
    return re.sub(r'\sxmlns(:\w+)?="[^"]*"', "", text)


def _search_xml(service_type: str) -> str:
    return ("M-SEARCH * HTTP/1.1\r\n"
            "HOST: %s:%d\r\n"
            'MAN: "ssdp:discover"\r\n'
            "MX: 2\r\n"
            "ST: %s\r\n"
            "USER-AGENT: %s\r\n\r\n") % (SSDP_ADDR, SSDP_PORT, service_type, USER_AGENT)


def discover_locations(timeout: float = 2.0) -> list:
    """Ищет адреса описаний устройств (LOCATION) через SSDP."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(0.4)
    locations = []
    try:
        for target in ("urn:schemas-upnp-org:device:InternetGatewayDevice:1",
                       "urn:schemas-upnp-org:device:WANConnectionDevice:1", "upnp:rootdevice"):
            try:
                sock.sendto(_search_xml(target).encode("ascii"), (SSDP_ADDR, SSDP_PORT))
            except OSError:
                continue
        deadline = time.time() + max(0.5, timeout)
        while time.time() < deadline:
            try:
                payload, _sender = sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            text = payload.decode("utf-8", "replace")
            for line in text.splitlines():
                if line.lower().startswith("location:"):
                    url = line.split(":", 1)[1].strip()
                    if url and url not in locations:
                        locations.append(url)
    finally:
        sock.close()
    return locations


def _fetch(url: str, timeout: float = 3.0) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", "replace")


def parse_description(xml_text: str, base_url: str):
    """Из описания устройства достаёт управляющий адрес службы WANIPConnection."""
    try:
        root = ET.fromstring(_strip_namespaces(xml_text))
    except ET.ParseError as exc:
        raise UpnpError("не разобрать описание роутера: %s" % exc)
    base = root.findtext("URLBase") or base_url
    for service in root.iter("service"):
        kind = service.findtext("serviceType") or ""
        if not any(name in kind for name in SERVICE_KINDS):
            continue
        control = (service.findtext("controlURL") or "").strip()
        if not control:
            continue
        return {"service": kind.strip(), "control": urllib.parse.urljoin(base, control),
                "router": (root.findtext(".//friendlyName") or "").strip(),
                "location": base_url}
    return None


def find_gateway(timeout: float = 2.0):
    """Первый роутер, который умеет пробрасывать порты (None, если не нашёлся)."""
    for location in discover_locations(timeout):
        try:
            gate = parse_description(_fetch(location), location)
        except (UpnpError, OSError, ValueError, urllib.error.URLError):
            continue
        if gate:
            return gate
    return None


def soap_request(gate: dict, action: str, arguments: dict) -> dict:
    """Собирает SOAP-запрос (отдельно от отправки — удобно проверять без сети)."""
    parts = ["<?xml version=\"1.0\"?>",
             "<s:Envelope xmlns:s=\"http://schemas.xmlsoap.org/soap/envelope/\" "
             "s:encodingStyle=\"http://schemas.xmlsoap.org/soap/encoding/\"><s:Body>",
             "<u:%s xmlns:u=\"%s\">" % (action, gate["service"])]
    for key, value in arguments.items():
        parts.append("<%s>%s</%s>" % (key, value, key))
    parts.append("</u:%s></s:Body></s:Envelope>" % action)
    return {"url": gate["control"], "body": "".join(parts).encode("utf-8"),
            "headers": {"Content-Type": 'text/xml; charset="utf-8"',
                        "SOAPAction": '"%s#%s"' % (gate["service"], action),
                        "User-Agent": USER_AGENT}}


def _soap(gate: dict, action: str, arguments: dict, timeout: float = 4.0) -> str:
    request = soap_request(gate, action, arguments)
    try:
        with urllib.request.urlopen(urllib.request.Request(
                request["url"], data=request["body"], method="POST",
                headers=request["headers"]), timeout=timeout) as response:
            return response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", "replace")
        code = _find_text(text, "errorCode") or str(exc.code)
        message = _find_text(text, "errorDescription") or exc.reason
        raise UpnpError("роутер отказал (%s: %s)" % (code, message))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise UpnpError("роутер недоступен: %s" % exc)


def _find_text(xml_text: str, tag: str) -> str:
    try:
        root = ET.fromstring(_strip_namespaces(xml_text))
    except ET.ParseError:
        return ""
    for element in root.iter():
        if element.tag == tag:
            return (element.text or "").strip()
    return ""


def external_address(gate: dict) -> str:
    """Внешний адрес по мнению роутера."""
    text = _soap(gate, "GetExternalIPAddress", {})
    value = _find_text(text, "NewExternalIPAddress")
    if not value:
        raise UpnpError("роутер не сказал внешний адрес")
    return value


def is_public(address: str) -> bool:
    """Годится ли адрес для друзей (не «серый» и не из сети провайдера)."""
    try:
        parsed = IPv4Address(address)
    except ValueError:
        return False
    carrier_grade = IPv4Address("100.64.0.0")
    return not (parsed.is_private or parsed.is_loopback or parsed.is_link_local
                or (carrier_grade <= parsed <= IPv4Address("100.127.255.255")))


def add_mapping(gate: dict, external_port: int, internal_ip: str, internal_port: int,
                protocol: str = "TCP", description: str = "CreaLaunch",
                lifetime: int = 0) -> bool:
    """Открывает порт на роутере: внешний порт → порт мира на этой машине."""
    _soap(gate, "AddPortMapping", {
        "NewRemoteHost": "",
        "NewExternalPort": int(external_port),
        "NewProtocol": protocol.upper(),
        "NewInternalPort": int(internal_port),
        "NewInternalClient": internal_ip,
        "NewEnabled": 1,
        "NewPortMappingDescription": description,
        "NewLeaseDuration": int(lifetime),
    })
    return True


def delete_mapping(gate: dict, external_port: int, protocol: str = "TCP") -> bool:
    try:
        _soap(gate, "DeletePortMapping", {
            "NewRemoteHost": "", "NewExternalPort": int(external_port),
            "NewProtocol": protocol.upper()})
        return True
    except UpnpError:
        return False


def open_world_port(internal_ip: str, internal_port: int,
                    external_port: int = DEFAULT_EXTERNAL_PORT,
                    protocols=("TCP",), timeout: float = 2.0) -> dict:
    """Пробрасывает порт мира и возвращает внешний адрес для друзей.

    Итог: {"address": "1.2.3.4", "port": 25565, "router": "…", "mapped": ["TCP"]}.
    Если роутер не найден или адрес «серый» — понятная ошибка.
    """
    gate = find_gateway(timeout)
    if not gate:
        raise UpnpError("роутер с UPnP не найден — включи UPnP в настройках роутера "
                        "или используй Radmin VPN")
    external = external_address(gate)
    if not is_public(external):
        raise UpnpError("провайдер выдаёт непубличный адрес (%s) — снаружи не подключиться, "
                        "нужен Radmin VPN" % external)
    mapped = []
    last_error = None
    for protocol in protocols:
        try:
            add_mapping(gate, external_port, internal_ip, internal_port, protocol)
            mapped.append(protocol.upper())
        except UpnpError as exc:
            last_error = exc
    if not mapped:
        raise UpnpError(str(last_error or "роутер не разрешил проброс порта"))
    return {"address": external, "port": int(external_port), "router": gate.get("router", ""),
            "mapped": mapped, "internal": "%s:%d" % (internal_ip, internal_port)}


def close_world_port(external_port: int = DEFAULT_EXTERNAL_PORT, protocols=("TCP",),
                     timeout: float = 2.0) -> list:
    """Убирает проброс (например, когда мир закрыли)."""
    gate = find_gateway(timeout)
    if not gate:
        return []
    removed = []
    for protocol in protocols:
        if delete_mapping(gate, external_port, protocol):
            removed.append(protocol.upper())
    return removed


def status(timeout: float = 2.0) -> dict:
    """Короткая сводка для интерфейса: есть ли роутер и публичный адрес."""
    gate = find_gateway(timeout)
    if not gate:
        return {"ok": False, "error": "роутер с UPnP не найден", "router": "", "address": ""}
    try:
        address = external_address(gate)
    except UpnpError as exc:
        return {"ok": False, "error": str(exc), "router": gate.get("router", ""), "address": ""}
    return {"ok": is_public(address), "router": gate.get("router", ""), "address": address,
            "error": "" if is_public(address) else "адрес провайдера непубличный (CGNAT)"}
