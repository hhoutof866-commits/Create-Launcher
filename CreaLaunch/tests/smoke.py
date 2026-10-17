"""Быстрые проверки без сети: правила, UUID, пути maven, моды, скины, PNG, каталог, окно.

Запуск:            python tests/smoke.py
С сетью (Modrinth): python tests/smoke.py --online
"""

from __future__ import annotations

import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import (auth, branding, friends, hero, lan, maven, modrinth, mods, nbt,  # noqa: E402
                  options, png, rule, servers_dat, skins, upnp)
from core.config import Config  # noqa: E402

FAILED = []
ONLINE = "--online" in sys.argv


def check(name, got, expected):
    ok = got == expected
    print("%-52s %s" % (name, "OK" if ok else "ПРОВАЛ (получено %r, ждали %r)" % (got, expected)))
    if not ok:
        FAILED.append(name)


def check_png() -> None:
    rgba = bytearray()
    for y in range(8):
        for x in range(8):
            rgba += bytes((x * 30, y * 30, 128, 255 if (x + y) % 2 else 120))
    rgba = bytes(rgba)
    blob = png.encode(8, 8, rgba)
    check("PNG: сигнатура", blob[:8], png.SIGNATURE)
    check("PNG: чтение совпадает с записью", png.decode(blob)[2], rgba)
    check("PNG: масштаб 3x", png.scale(8, 8, rgba, 3)[:2], (24, 24))
    check("PNG: вырезка 2x2 = 16 байт", len(png.crop(8, 8, rgba, 4, 4, 2, 2)), 16)
    base = png.blank(4, 4, (0, 0, 0, 255))
    mixed = png.paste(4, 4, base, 2, 2, png.crop(8, 8, rgba, 1, 0, 2, 2), 1, 1)
    check("PNG: наложение непрозрачного пикселя", mixed[20:24], rgba[4:8])
    blend = png.paste(4, 4, base, 1, 1, rgba[0:4], 0, 0)
    check("PNG: полупрозрачный пиксель смешан", blend[0:4], bytes((0, 0, (128 * 120) // 255, 255)))


def check_branding() -> None:
    directory = tempfile.mkdtemp(prefix="launcher-ico-")
    try:
        path = os.path.join(directory, "launcher.ico")
        branding.write_ico(path)
        with open(path, "rb") as handle:
            header = handle.read(6)
        check("ICO: сигнатура", header[:4], b"\x00\x00\x01\x00")
        check("ICO: шесть размеров", int.from_bytes(header[4:6], "little"), 6)
        size, _height, data = branding.creeper_rgba(16)
        check("ICO: угол прозрачный", data[3], 0)
        check("ICO: центр закрашен", data[((8 * size) + 8) * 4 + 3], 255)
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def check_options() -> None:
    directory = tempfile.mkdtemp(prefix="launcher-opt-")
    try:
        with open(os.path.join(directory, "options.txt"), "w", encoding="utf-8") as handle:
            handle.write('version:3955\nfoo:bar\nresourcePacks:["vanilla","mod_resources"]\n')
        options.enable_resource_pack(directory, "skin-X.zip", True)
        entries = options.load(directory)
        check("options: порядок строк сохранён", [key for key, _ in entries][:3],
              ["version", "foo", "resourcePacks"])
        check("options: чужие значения не потеряны", options.get(entries, "foo"), "bar")
        check("options: ресурспак добавлен в конец", options.resource_packs(entries),
              ["vanilla", "mod_resources", "file/skin-X.zip"])
        check("options: слой шляпы включён", options.get(entries, "modelPart_hat"), "true")
        options.enable_resource_pack(directory, "skin-X.zip", False)
        check("options: ресурспак выключен", options.resource_packs(options.load(directory)),
              ["vanilla", "mod_resources"])
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def check_skins() -> None:
    game = tempfile.mkdtemp(prefix="launcher-skin-")
    try:
        data = skins.demo_skin()
        parsed = skins.parse(data)
        check("Скин: образец 64x64", (parsed[0], parsed[1]), (64, 64))
        check("Скин: фигурка 16x32 при x5", skins.render_player(parsed, False, 5)[:2], (80, 160))
        check("Скин: фигурка slim", skins.render_player(parsed, True, 5)[:2], (80, 160))
        check("Скин: превью головы x5", skins.render_head(parsed, 5)[:2], (40, 40))
        pack = skins.apply(game, "Player", data, slim=False, log=None)
        names = zipfile.ZipFile(pack).namelist()
        check("Скин: в ресурспаке 4 текстуры игрока",
              len([name for name in names if name.endswith(".png")]), 4)
        check("Скин: pack.mcmeta на месте", "pack.mcmeta" in names, True)
        check("Скин: ресурспак включён",
              options.is_resource_pack_enabled(game, skins.pack_file_name("Player")), True)
        check("Скин: файл скина сохранён", os.path.exists(skins.saved_skin_path(game, "Player")),
              True)
        check("Скин: текущий скин читается", skins.parse(skins.current(game, "Player"))[:2], (64, 64))
        skins.remove(game, "Player")
        check("Скин: после снятия ресурспак выключен",
              options.is_resource_pack_enabled(game, skins.pack_file_name("Player")), False)
        bad = png.encode(4, 4, png.blank(4, 4, (1, 2, 3, 255)))
        try:
            skins.parse(bad)
            check("Скин: маленький PNG отклонён", False, True)
        except skins.SkinError:
            check("Скин: маленький PNG отклонён", True, True)
    finally:
        shutil.rmtree(game, ignore_errors=True)


def check_modrinth_offline() -> None:
    check("Каталог: фасеты мода", modrinth._facets("mod", "1.21.1", "neoforge"),
          [["project_type:mod"], ["versions:1.21.1"], ["categories:neoforge"]])
    check("Каталог: датапак без фильтра загрузчика",
          modrinth._facets("datapack", "1.21.1", "neoforge"),
          [["project_type:datapack"], ["versions:1.21.1"]])
    check("Каталог: create по slug",
          modrinth._is_create({"slug": "create", "title": "Create"}), True)
    check("Каталог: create по описанию",
          modrinth._is_create({"slug": "x", "title": "Some", "description": "adds Create stuff"}),
          True)
    check("Каталог: посторонний мод отфильтрован",
          modrinth._is_create({"slug": "jei", "title": "JEI", "description": "recipe viewer"}),
          False)


def check_modrinth_online() -> None:
    result = modrinth.search("", project_type="mod", create_only=True, limit=5)
    check("Каталог (сеть): поиск Create не пуст", result["total"] > 0 and len(result["hits"]) > 0,
          True)
    check("Каталог (сеть): все результаты про Create",
          all("create" in (hit["title"] + hit["slug"]).lower() or hit["slug"] in modrinth.CREATE_SLUGS
              for hit in result["hits"]), True)
    versions = modrinth.project_versions("create", "1.21.1", "neoforge")
    check("Каталог (сеть): есть версия Create под 1.21.1", len(versions) > 0, True)
    if versions:
        file = modrinth.primary_file(versions[0])
        check("Каталог (сеть): у версии есть файл и sha1",
              bool(file.get("url")) and bool((file.get("hashes") or {}).get("sha1")), True)


def check_mods() -> None:
    tmp = tempfile.mkdtemp(prefix="launcher-smoke-")
    try:
        directory = mods.mods_dir(tmp)
        jar = os.path.join(directory, "jei.jar")
        open(jar, "wb").write(b"x")
        listed = mods.list_mods(tmp)
        check("найден 1 мод", len(listed), 1)
        check("мод включён", listed[0].enabled, True)
        new_path = mods.set_enabled(jar, False)
        check("выключение даёт .disabled", new_path.endswith("jei.jar.disabled"), True)
        check("выключенный мод в списке", mods.list_mods(tmp)[0].enabled, False)
        mods.set_enabled(new_path, True)
        check("обратное включение", os.path.exists(jar), True)

        other = os.path.join(tmp, "sodium.jar")
        open(other, "wb").write(b"y")
        check("добавление мода", len(mods.add(tmp, [other])), 1)
        check("после добавления 2 мода", len(mods.list_mods(tmp)), 2)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def check_nbt() -> None:
    root = nbt.Compound({
        "servers": nbt.List([
            nbt.Compound({"name": nbt.String("Вася"), "ip": nbt.String("26.0.0.5:51234"),
                          "acceptTextures": nbt.Byte(0), "hidden": nbt.Byte(1)}),
            nbt.Compound({"name": nbt.String("Сервак"), "ip": nbt.String("play.example.org"),
                          "acceptTextures": nbt.Byte(1)}),
        ]),
        "число": nbt.Int(-42),
        "дробное": nbt.Double(1.5),
        "метка": nbt.Long(1234567890123),
        "байты": nbt.ByteArray(b"\x01\x02\x03"),
        "строка": nbt.String("привет"),
        "пусто": nbt.List(),
    })
    back = nbt.read(nbt.write(root))
    check("NBT: корень — Compound", isinstance(back, dict), True)
    check("NBT: целые и метки", (int(back["число"]), int(back["метка"])), (-42, 1234567890123))
    check("NBT: дробное", float(back["дробное"]), 1.5)
    check("NBT: строка", str(back["строка"]), "привет")
    check("NBT: байтовый массив", bytes(back["байты"]), b"\x01\x02\x03")
    check("NBT: пустой список", len(back["пусто"]), 0)
    check("NBT: список серверов", len(back["servers"]), 2)
    check("NBT: поля записи", (str(back["servers"][0]["name"]), str(back["servers"][0]["ip"]),
                              int(back["servers"][0]["hidden"])), ("Вася", "26.0.0.5:51234", 1))
    check("NBT: тип сохраняется", isinstance(back["число"], nbt.Int), True)


def check_servers_dat() -> None:
    tmp = tempfile.mkdtemp(prefix="launcher-servers-")
    try:
        servers_dat.upsert(tmp, "Вася", "26.0.0.5:51234", icon="data:image/png;base64,AA")
        servers_dat.upsert(tmp, "Петя", "26.0.0.6")
        servers_dat.upsert(tmp, "Вася", "26.0.0.9:51235")
        check("servers.dat: две записи", sorted(servers_dat.names(tmp)), ["Вася", "Петя"])
        entry = servers_dat.find(servers_dat.load(tmp), "вася")
        check("servers.dat: адрес обновился", str(entry["ip"]), "26.0.0.9:51235")
        check("servers.dat: иконка на месте",
              str(entry.get("icon", "")).startswith("data:image/png"), True)
        check("servers.dat: удаление", servers_dat.remove(tmp, "Петя"), True)
        check("servers.dat: остался один", servers_dat.names(tmp), ["Вася"])
        check("servers.dat: файл на месте", os.path.exists(servers_dat.path(tmp)), True)
        with open(servers_dat.path(tmp), "rb") as handle:
            check("servers.dat: без сжатия (как в 1.21.1)", handle.read(3), b"\x0a\x00\x00")

        custom = nbt.Compound({"version": nbt.Int(1), "servers": nbt.List([
            nbt.Compound({"name": nbt.String("Старый"), "ip": nbt.String("1.2.3.4"),
                          "acceptTextures": nbt.Byte(1), "extra": nbt.String("важно")})])})
        nbt.write_file(servers_dat.path(tmp), custom)     # сжатый файл прошлых версий
        servers_dat.upsert(tmp, "Новый", "5.6.7.8")
        root = servers_dat.load(tmp)
        check("servers.dat: поле вне списка цело", int(root["version"]), 1)
        check("servers.dat: чужое поле записи цело",
              str(servers_dat.find(root, "Старый")["extra"]), "важно")
        check("servers.dat: новые и старые рядом", sorted(servers_dat.names(tmp)),
              ["Новый", "Старый"])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def check_lan() -> None:
    check("сеть: разбор объявления мира",
          lan.parse_lan_ping("[MOTD]Мир Стива[/MOTD][ADDR]26.0.0.5:51234[/ADDR][PORT]51234[/PORT]"),
          {"motd": "Мир Стива", "address": "26.0.0.5", "port": 51234})
    check("сеть: мусор не разбирается", lan.parse_lan_ping("привет"), None)
    check("сеть: порт открытого мира из лога",
          lan.started_serving_port("[12:00:00] [Render thread/INFO]: Started serving on 51234"),
          51234)
    check("сеть: старый вариант строки",
          lan.started_serving_port("[Client thread/INFO]: Local game hosted on port 4242"), 4242)
    check("сеть: чужая строка лога", lan.started_serving_port("[INFO]: Что-то ещё"), None)
    check("сеть: адрес с портом", lan.parse_address("26.0.0.5:51234"), ("26.0.0.5", 51234))
    check("сеть: адрес без порта", lan.parse_address("26.0.0.5"), ("26.0.0.5", 25565))
    check("сеть: пустой адрес не принимается", _raises_regex(lan.parse_address, ""), True)
    check("сеть: формат без порта", lan.format_address("26.0.0.5", 0), "26.0.0.5")
    check("сеть: формат с портом", lan.format_address("26.0.0.5", 51234), "26.0.0.5:51234")
    check("сеть: широковещательный адрес /8", lan._broadcast("26.152.171.63", 8), "26.255.255.255")
    check("сеть: широковещательный адрес /24", lan._broadcast("192.168.0.104", 24), "192.168.0.255")
    check("сеть: адрес для друзей — виртуальная сеть",
          lan.best_share_address([{"ip": "192.168.0.5", "name": "Ethernet"},
                                  {"ip": "26.1.2.3", "name": "Radmin VPN"}]), "26.1.2.3")
    check("сеть: локальные адреса найдены", len(lan.local_addresses()) > 0, True)
    check("сеть: все адреса непустые", all(len(item["ip"]) > 6 for item in lan.local_addresses()),
          True)

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    check("сеть: живой порт отвечает", lan.probe("127.0.0.1", port, 1.0), True)
    listener.close()
    check("сеть: закрытый порт молчит", lan.probe("127.0.0.1", port, 0.5), False)

    # живой обмен по сети: «друг» рассылает мир и объявление лаунчера, мы это ловим
    stop = threading.Event()

    def fake_friend():
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            while not stop.is_set():
                try:
                    sock.sendto(lan.lan_ping_bytes("Мир друга", "26.0.0.5", 51234),
                                ("127.0.0.1", lan.LAN_PORT))
                    sock.sendto(lan.beacon_payload("Вася", 51234, "Мир друга", 1, "открыт", "id1"),
                                ("127.0.0.1", lan.BEACON_PORT))
                except OSError:
                    break
                stop.wait(0.15)
        finally:
            sock.close()

    thread = threading.Thread(target=fake_friend, daemon=True)
    thread.start()
    time.sleep(0.1)
    result = lan.scan(1.2, ignore_hosts=[])
    stop.set()
    thread.join(timeout=1.0)
    worlds = [item for item in result["worlds"] if item["motd"] == "Мир друга"]
    check("сеть: мир друга найден", len(worlds), 1)
    check("сеть: адрес мира — отправитель", worlds[0]["host"] if worlds else "", "127.0.0.1")
    check("сеть: порт мира верный", worlds[0]["port"] if worlds else 0, 51234)
    check("сеть: объявление лаунчера найдено", [item["nick"] for item in result["friends"]], ["Вася"])
    check("сеть: мир своего пинга не показывается",
          [item["motd"] for item in result["worlds"] if item["motd"] == lan.PING_MARK], [])


def _raises_regex(function, value) -> bool:
    try:
        function(value)
    except ValueError:
        return True
    return False


def check_friends() -> None:
    tmp = tempfile.mkdtemp(prefix="launcher-friends-")
    try:
        path = os.path.join(tmp, "friends.json")
        book = friends.Friends.load(path)
        check("друзья: сразу пусто", book.list(), [])
        book.add("Вася", "26.0.0.5", 51234)
        book.touch("Вася", "26.0.0.9", 51235, "Мир Стива")
        book.add("Петя", "26.0.0.6")
        reopened = friends.Friends.load(path)
        check("друзья: адрес сохранился", reopened.known_address("Вася"), ("26.0.0.9", 51235))
        check("друзья: мир сохранился", reopened.find("Вася")["world"], "Мир Стива")
        check("друзья: двое в списке", [item["name"] for item in reopened.list()], ["Вася", "Петя"])
        check("друзья: удаление", reopened.remove("Петя"), True)
        check("друзья: остался один", [item["name"] for item in friends.Friends.load(path).list()],
              ["Вася"])
        check("друзья: удаление несуществующего", reopened.remove("Никто"), False)
        check("друзья: свой id стабилен",
              friends.Friends.load(path).me_id(), friends.Friends.load(path).me_id())
        check("друзья: свой id непустой", len(friends.Friends.load(path).me_id()) >= 8, True)

        code = friends.share_code("Вася", "26.152.171.63", 51234, "Мир Стива")
        check("приглашение: код с меткой CL1.", code.startswith("CL1."), True)
        parsed = friends.parse_share_code(code)
        check("приглашение: код разобран",
              (parsed["name"], parsed["address"], parsed["port"]) if parsed else None,
              ("Вася", "26.152.171.63", 51234))
        check("приглашение: испорченный код", friends.parse_share_code("CL1.ППП"), None)
        text = friends.invite_text("Вася", "26.152.171.63", 51234, "Мир Стива")
        again = friends.parse_invite(text)
        check("приглашение: готовый текст разобран",
              (again["name"], again["address"], again["port"]) if again else None,
              ("Вася", "26.152.171.63", 51234))
        plain = friends.parse_invite("Вася 26.0.0.5:51234")
        check("приглашение: строка «Имя адрес»",
              (plain["name"], plain["address"], plain["port"]), ("Вася", "26.0.0.5", 51234))
        check("приглашение: без адреса", friends.parse_invite("просто привет"), None)
        check("приглашение: адрес без порта",
              friends.parse_invite("26.0.0.5")["address"], "26.0.0.5")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


DESCRIPTION = """<?xml version="1.0"?>
<root xmlns="urn:schemas-upnp-org:device-1-0">
  <device>
    <friendlyName>TP-Link Archer</friendlyName>
    <serviceList>
      <service>
        <serviceType>urn:schemas-upnp-org:device:WANDevice:1</serviceType>
        <controlURL>/ctl/WAN</controlURL>
      </service>
      <service>
        <serviceType>urn:schemas-upnp-org:service:WANIPConnection:1</serviceType>
        <controlURL>/ctl/IPConn</controlURL>
      </service>
    </serviceList>
  </device>
</root>"""


def check_upnp() -> None:
    gate = upnp.parse_description(DESCRIPTION, "http://192.168.0.1:1900/rootDesc.xml")
    check("UPnP: служба найдена", bool(gate), True)
    check("UPnP: адрес управления", gate["control"] if gate else "",
          "http://192.168.0.1:1900/ctl/IPConn")
    check("UPnP: имя роутера", gate["router"] if gate else "", "TP-Link Archer")
    check("UPnP: служба WANPPPConnection тоже годится",
          bool(upnp.parse_description(DESCRIPTION.replace("WANIPConnection", "WANPPPConnection"),
                                      "http://192.168.0.1:1900/rootDesc.xml")), True)
    check("UPnP: чужое описание не подходит",
          upnp.parse_description("<root><device/></root>", "http://192.168.0.1/x.xml"), None)

    request = upnp.soap_request(gate, "AddPortMapping",
                               {"NewExternalPort": 25565, "NewProtocol": "TCP"})
    check("UPnP: SOAPAction с именем службы", request["headers"]["SOAPAction"],
          '"urn:schemas-upnp-org:service:WANIPConnection:1#AddPortMapping"')
    check("UPnP: тело — правильный XML",
          ET.fromstring(request["body"]).tag.endswith("Envelope"), True)
    check("UPnP: значение попало в тело", b"25565" in request["body"], True)
    check("UPnP: разбор внешнего адреса",
          upnp._find_text("<x><NewExternalIPAddress>1.2.3.4</NewExternalIPAddress></x>",
                          "NewExternalIPAddress"), "1.2.3.4")
    check("UPnP: разбор ошибки роутера",
          upnp._find_text("<x><errorCode>718</errorCode></x>", "errorCode"), "718")
    check("UPnP: серый адрес не годится", upnp.is_public("192.168.0.1"), False)
    check("UPnP: CGNAT не годится", upnp.is_public("100.64.5.5"), False)
    check("UPnP: публичный адрес годится", upnp.is_public("1.2.3.4"), True)


def check_quick_play() -> None:
    element = [{"rules": [{"action": "allow", "features": {"is_quick_play_multiplayer": True}}],
                "value": ["--quickPlayMultiplayer", "${quickPlayMultiplayer}"]}]
    features = rule.default_features()
    features["is_quick_play_multiplayer"] = True
    args = rule.resolve_arguments(element, {"quickPlayMultiplayer": "26.0.0.5:51234"}, features)
    check("автозаход: ключ и адрес переданы", args, ["--quickPlayMultiplayer", "26.0.0.5:51234"])
    check("автозаход: без правила ключа нет",
          rule.resolve_arguments(element, {"quickPlayMultiplayer": "26.0.0.5:51234"},
                                 rule.default_features()), [])


def check_builds() -> None:
    """Сборки: список, переключение, подписи, переименование и удаление."""
    cfg = Config({"mode": "neoforge", "mc_version": "1.21.1", "neoforge_version": "21.1.262",
                  "ram_mb": 6144, "game_dir": r"C:\games\one", "jvm_args": "-Xss4M"})
    check("сборки: по умолчанию пусто", cfg.get("builds"), [])
    build = cfg.active_build()
    check("сборки: завелась «Основная»", build["name"], "Основная")
    check("сборки: поля взяты из настроек",
          (build["mode"], build["ram_mb"], build["game_dir"], build["jvm_args"]),
          ("neoforge", 6144, r"C:\games\one", "-Xss4M"))
    check("сборки: выбрана «Основная»", cfg.get("current_build"), "Основная")
    check("сборки: подпись NeoForge", Config.build_label(build), "NeoForge 21.1.262 · 1.21.1")

    cfg["ram_mb"] = 8192
    cfg.sync_active_build()
    check("сборки: sync переносит правки", cfg.find_build("Основная")["ram_mb"], 8192)

    cfg.upsert_build({"name": "Ванильная", "mode": "vanilla", "neoforge_version": "",
                      "ram_mb": 4096, "game_dir": r"C:\games\two"})
    check("сборки: добавилась вторая", [item["name"] for item in cfg.build_list()],
          ["Основная", "Ванильная"])
    check("сборки: подпись ванильной", Config.build_label(cfg.find_build("Ванильная")),
          "Ванильная · 1.21.1")
    cfg.select_build("Ванильная")
    check("сборки: режим переключился", cfg.get("mode"), "vanilla")
    check("сборки: папка переключилась", cfg.get("game_dir"), r"C:\games\two")
    check("сборки: переименование", cfg.rename_build("Ванильная", "Чистая"), True)
    check("сборки: активная переименовалась", cfg.get("current_build"), "Чистая")
    check("сборки: удаление", cfg.remove_build("Чистая"), True)
    check("сборки: осталась одна", len(cfg.build_list()), 1)
    check("сборки: активной стала «Основная»", cfg.get("current_build"), "Основная")
    check("сборки: последнюю удалить нельзя", cfg.remove_build("Основная"), False)
    check("сборки: мусор в config не ломает список", Config({"builds": "нет"}).build_list(), [])
    check("сборки: переключение на незнакомую не падает",
          Config({"builds": [{"name": "Одна"}]}).select_build("Другой")["name"], "Одна")


def check_hero() -> None:
    """Баннер вкладки «Играть»: рисуется кодом и кладётся в кэш."""
    width, height, rgba = hero.render()
    check("баннер: размер полотна", (width, height), (hero.WIDTH, hero.HEIGHT))
    check("баннер: буфер нужной длины", len(rgba), hero.WIDTH * hero.HEIGHT * 4)
    sky_green = rgba[(6 * hero.WIDTH + 6) * 4 + 1]
    grass_green = rgba[((hero.HORIZON + 1) * hero.WIDTH + 6) * 4 + 1]
    check("баннер: небо темнее травы", sky_green < grass_green, True)
    check("баннер: увеличение под ширину окна",
          (hero.pick_factor(744), hero.pick_factor(600), hero.pick_factor(400),
           hero.pick_factor(200)), (4, 3, 2, 1))
    path = hero.image_path()
    check("баннер: файл в кэше", os.path.exists(path), True)
    check("баннер: имя файла с версией и увеличением", os.path.basename(path),
          "hero-%d-%dx.png" % (hero.VERSION, hero.FACTOR))
    image_width, image_height, _pixels = png.read(path)
    check("баннер: размер картинки в кэше", (image_width, image_height),
          (hero.WIDTH * hero.FACTOR, hero.HEIGHT * hero.FACTOR))
    check("баннер: картинка не пустая", os.path.getsize(path) > 1000, True)


def check_window() -> None:
    try:
        import tkinter as tk
        from ui.app import LauncherApp
        from core import config as config_mod
        tmp = tempfile.mkdtemp(prefix="launcher-window-")
        config_mod.PATH = os.path.join(tmp, "config.json")   # живой config.json не трогаем
        root = tk.Tk()
        root.withdraw()
        app = LauncherApp(root)
        for _ in range(5):
            root.update()
        app._refresh_skin()
        root.update()
        check("окно собралось", bool(app.play_button), True)
        check("папка игры по умолчанию не пуста", bool(app.dir_var.get()), True)
        check("вкладок семь", len(app.tabs), 7)
        check("первая вкладка — «Играть»", app.tab_order[0], "Играть")
        check("порядок вкладок", app.tab_order,
              ["Играть", "Моды", "Каталог", "Друзья", "Скины", "Консоль", "Настройки"])
        check("активная вкладка одна", app.current_tab, app.tab_order[0])
        check("превью скина построено", app.skin_player_image is not None, True)
        check("вкладка «Друзья» на месте", "Друзья" in app.tabs, True)
        check("аватар аккаунта построен", app.avatar_image is not None, True)
        check("строка сборок нарисована", list(app.build_rows), ["Основная"])
        check("подпись аккаунта — ник", app.account_name.cget("text"), "Player")
        check("заголовок с именем сборки", app.main_title.cget("text"), "MINECRAFT: ОСНОВНАЯ")
        check("подпись на баннере", app.hero_canvas.itemcget(app.hero_title, "text"), "ОСНОВНАЯ")
        check("кнопка «ИГРАТЬ» на месте", app.play_button.cget("text"), "ИГРАТЬ")
        check("баннер загружен", app.hero_images.get(4) is not None, True)
        check("низ описывает сборку", "Minecraft 1.21.1" in app.footer.cget("text"), True)

        app._collect_config()
        app.cfg.upsert_build({"name": "Ванильная", "mode": "vanilla", "mc_version": "1.21.1",
                              "neoforge_version": "", "ram_mb": 8192, "game_dir": "",
                              "jvm_args": ""})
        app.cfg.save()
        app._refresh_builds()
        app._select_build("Ванильная")
        for _ in range(3):
            root.update()
        check("сборок в списке две", len(app.build_rows), 2)
        check("сборка переключилась", app.cfg.get("current_build"), "Ванильная")
        check("режим сборки применился", app.mode_var.get(), "Ванильный (без модов)")
        check("ОЗУ сборки применилось", app.cfg.get("ram_mb"), 8192)
        check("заголовок сменился", app.main_title.cget("text"), "MINECRAFT: ВАНИЛЬНАЯ")
        check("подпись баннера сменилась", app.hero_canvas.itemcget(app.hero_title, "text"),
              "ВАНИЛЬНАЯ")
        check("комбо в настройках показывает сборку", app.build_var.get(), "Ванильная")
        check("низ описывает ванильную сборку",
              "ванильная" in app.footer.cget("text"), True)

        app.friends.file = os.path.join(tmp, "friends.json")     # чтобы не трогать живой файл
        app.friends.items = []
        app.friends.add("Тест", "26.0.0.7", 51234)
        app._refresh_friends()
        app._refresh_addresses()
        values = [app.friends_tree.item(item, "values")
                  for item in app.friends_tree.get_children()]
        check("список друзей строится", any(row[0] == "Тест" for row in values), True)
        check("адрес друга в таблице", any(row[1] == "26.0.0.7:51234" for row in values), True)
        check("адрес для друзей найден", bool(app.my_addresses.cget("text")), True)
        root.destroy()
        shutil.rmtree(tmp, ignore_errors=True)
    except Exception as exc:  # noqa: BLE001
        check("окно собралось (%s)" % exc, False, True)


def main() -> int:
    # --- офлайн-UUID: сверяем с Java UUID.nameUUIDFromBytes("OfflinePlayer:Notch")
    check("offline_uuid(Notch)", auth.offline_uuid("Notch"), "b50ad385-829d-3141-a216-7e7d7539ba7f")
    check("sanitize_username('Плохой ник!')", auth.sanitize_username("Плохой ник!"), "Player")
    check("sanitize_username('Steve_99')", auth.sanitize_username("Steve_99"), "Steve_99")

    # --- maven
    check("maven_to_path(lwjgl natives)",
          maven.maven_to_path("org.lwjgl:lwjgl:3.3.3:natives-windows"),
          "org/lwjgl/lwjgl/3.3.3/lwjgl-3.3.3-natives-windows.jar")
    check("maven_to_path(простой)",
          maven.maven_to_path("com.google.code.gson:gson:2.10.1"),
          "com/google/code/gson/gson/2.10.1/gson-2.10.1.jar")
    check("maven_to_path(@zip)",
          maven.maven_to_path("net.neoforged:neoform:1.21.1-20240808.144430@zip"),
          "net/neoforged/neoform/1.21.1-20240808.144430/neoform-1.21.1-20240808.144430.zip")

    # --- правила
    features = rule.default_features()
    check("правило: без rules = разрешено", rule.rules_allow(None, features), True)
    check("правило: windows-специфичное",
          rule.rules_allow([{"action": "allow", "os": {"name": "windows"}}], features), True)
    check("правило: osx отброшено",
          rule.rules_allow([{"action": "allow", "os": {"name": "osx"}}], features), False)
    check("правило: disallow после allow",
          rule.rules_allow([{"action": "allow"}, {"action": "disallow", "os": {"name": "windows"}}],
                           features), False)
    check("features: демо выключено",
          rule.rules_allow([{"action": "allow", "features": {"is_demo_user": True}}], features), False)
    check("подстановка ${version_name}",
          rule.substitute("-DignoreList=client-extra,${version_name}.jar",
                          {"version_name": "neoforge-21.1.262"}),
          "-DignoreList=client-extra,neoforge-21.1.262.jar")

    # --- разбор аргументов с незаполненными переменными
    elements = ["--username", "${auth_player_name}",
                {"rules": [{"action": "allow", "features": {"is_demo_user": True}}], "value": "--demo"},
                {"rules": [{"action": "allow", "features": {"has_custom_resolution": True}}],
                 "value": ["--width", "${resolution_width}"]}]
    resolved = rule.resolve_arguments(elements, {"auth_player_name": "Steve"}, features)
    check("аргументы игры", resolved, ["--username", "Steve"])

    check_mods()
    check_png()
    check_branding()
    check_options()
    check_skins()
    check_modrinth_offline()
    check_nbt()
    check_servers_dat()
    check_friends()
    check_lan()
    check_upnp()
    check_quick_play()
    check_builds()
    check_hero()
    if ONLINE:
        check_modrinth_online()
    check_window()

    print()
    if FAILED:
        print("Провалено проверок: %d" % len(FAILED))
        return 1
    print("Все проверки пройдены")
    return 0


if __name__ == "__main__":
    sys.exit(main())
