#!/usr/bin/env python3
"""NeoForge Launcher — точка входа.

Обычный запуск (окно):
    python launcher.py

Консольные команды (удобно для проверки):
    python launcher.py --cli java
    python launcher.py --cli versions
    python launcher.py --cli install --game-dir D:\\minecraft
    python launcher.py --cli launch  --game-dir D:\\minecraft
"""

from __future__ import annotations

import argparse
import base64
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import (auth, branding, config, friends, install, javas, lan, launch, modrinth, mods,  # noqa: E402
                 mojang, neoforge, options, paths, png, servers_dat, shortcut, skins,
                 upnp, version as version_mod)
from core.down import DownloadCancelled, Downloader  # noqa: E402


def _log(message):
    print(message, flush=True)


def _mods_dir(game_dir):
    return mods.mods_dir(game_dir)


def _content_dir(cfg, kind: str, world: str = "") -> str:
    game_dir = cfg.game_dir
    if kind == "mod":
        return mods.mods_dir(game_dir)
    if kind == "resourcepack":
        return os.path.join(game_dir, "resourcepacks")
    if world and world != "-":
        directory = os.path.join(game_dir, "saves", world, "datapacks")
    else:
        directory = os.path.join(game_dir, "datapacks")
    os.makedirs(directory, exist_ok=True)
    return directory


class _Progress:
    def __init__(self):
        self.last = 0.0
        self.label = ""

    def __call__(self, done, total, byte_done, byte_total, label):
        now = time.time()
        if now - self.last < 1.0 and done != total:
            return
        self.last = now
        if byte_total:
            print("  %s: %.1f%% (%d/%d файлов, %.0f/%.0f МБ)" % (
                label or "загрузка", min(100.0, byte_done * 100.0 / byte_total),
                done, total, byte_done / 1048576.0, byte_total / 1048576.0), flush=True)
        elif total:
            print("  %s: %d/%d" % (label or "загрузка", done, total), flush=True)


def _downloader():
    return Downloader(workers=8, on_progress=_Progress(), on_log=_log)


def _split_address(value: str, port: int = 0):
    """«26.0.0.5:51234» или «26.0.0.5» + необязательный порт."""
    try:
        host, parsed = lan.parse_address(value)
    except ValueError:
        return (value or "").strip(), int(port or 0)
    return host, int(port or parsed or 0)


def _my_addresses():
    items = lan.local_addresses()
    if not items:
        _log("Сетевые адреса не найдены — проверьте подключение")
        return []
    _log("Мои адреса (их называют друзьям):")
    for item in items:
        suffix = (" — %s" % item["name"]) if item["name"] else ""
        _log("   %-16s%s" % (item["ip"], suffix))
    return items


def _server_icon() -> str:
    """Иконка для списка серверов игры (64x64 PNG крипера, чистый base64)."""
    try:
        size, _height, rgba = branding.creeper_rgba(64)
        return base64.b64encode(png.encode(size, size, rgba)).decode("ascii")
    except Exception:  # noqa: BLE001
        return ""


def _friend_name(book, host: str, port: int) -> str:
    for item in book.list():
        if item["address"] == host and int(item["port"] or 0) == port:
            return item["name"]
    return lan.format_address(host, port)


def _cli_lan(args) -> int:
    _my_addresses()
    timeout = float(args.timeout or 3.0)
    _log("Ищу миры «открыт для сети» и объявления лаунчеров (%.1f с)…" % timeout)
    result = lan.scan(timeout, log=_log, my_id=friends.Friends.load().me_id())
    for message in result.get("errors", []):
        _log(message)
    for item in result["friends"]:
        _log("   друг  %-16s %s  %s" % (item["nick"], lan.format_address(item["host"], item["port"]),
                                        item.get("world", "")))
    for item in result["worlds"]:
        _log("   мир   %-16s %s" % (item["motd"][:40], lan.format_address(item["host"], item["port"])))
    if not result["friends"] and not result["worlds"]:
        _log("Никого не нашли. Друг должен открыть мир в игре («Открыть для сети»), "
             "а вы оба — быть в одной сети (Radmin VPN / Wi-Fi).")
    return 0


def _cli_friends(args) -> int:
    book = friends.Friends.load()
    if args.add:
        text = args.add.strip()
        parsed = friends.parse_invite(text) or {}
        name = (parsed.get("name") or text)[:24]
        address = parsed.get("address", "")
        port = int(parsed.get("port") or 0)
        if args.addr:
            address, port = _split_address(args.addr, args.port)
        elif address:
            address, port = _split_address(address, port)
        if not address:
            _log("Нужен адрес: --cli friends --add \"Вася 26.0.0.5:51234\" "
                 "(или вставьте приглашение с кодом CL1.…)")
            return 2
        friend = book.add(name, address, port)
        _log("Друг сохранён: %s — %s" % (friend["name"], lan.format_address(address, port)))
    if args.remove:
        if book.remove(args.remove):
            _log("Друг удалён: %s" % args.remove)
        else:
            _log("Друг «%s» не найден" % args.remove)
            return 1
    items = book.list()
    if not items:
        _log("Список друзей пуст. Добавить: --cli friends --add \"Вася 26.0.0.5:51234\"")
        return 0
    _log("Мои друзья (%d):" % len(items))
    for item in items:
        address = lan.format_address(item["address"], item["port"]) if item["address"] else "—"
        if args.check and item["address"]:
            host, port = _split_address(address, item["port"])
            address += "  " + ("доступен" if lan.probe(host, port, 1.5) else "не отвечает")
        seen = (time.strftime("%d.%m %H:%M", time.localtime(item["last_seen"]))
                if item["last_seen"] else "—")
        _log("   %-16s %-26s мир: %-18s был: %s" % (item["name"], address,
                                                     item.get("world") or "—", seen))
    return 0


def _cli_invite(cfg, args) -> int:
    items = _my_addresses()
    port = int(args.port or 0)
    if not port:
        _log("Укажите порт мира: --port 51234 (игра показывает его при открытии мира «для сети»)")
        return 2
    nick = auth.sanitize_username(cfg.get("username", "Player"))
    world = (cfg.get("last_world") or "").strip() or "Мир %s" % nick
    _log("")
    _log(friends.invite_text(nick, lan.best_share_address(items), port, world))
    return 0


def _cli_upnp(args) -> int:
    _log("Ищу роутер с UPnP…")
    info = upnp.status(3.0)
    if not info["ok"]:
        _log("UPnP: %s%s" % (info["error"], ("  (роутер: %s)" % info["router"]) if info["router"] else ""))
        return 1
    _log("Роутер: %s, внешний адрес: %s" % (info["router"] or "—", info["address"]))
    if args.world_port:
        mapping = upnp.open_world_port(lan.primary_address(), int(args.world_port),
                                       int(args.port or upnp.DEFAULT_EXTERNAL_PORT))
        _log("Порт открыт: %s → %s (%s)" % (
            lan.format_address(mapping["address"], mapping["port"]), mapping["internal"],
            ", ".join(mapping["mapped"])))
    else:
        _log("Чтобы открыть порт: --cli upnp --world-port 51234")
    return 0


def _cli_join(cfg, args) -> int:
    if not args.addr:
        _log("Нужен адрес друга: --cli join --addr 26.0.0.5:51234")
        return 2
    host, port = _split_address(args.addr, args.port)
    address = lan.format_address(host, port)
    _log("Проверяю мир %s…" % address)
    if not lan.probe(host, port, 3.0):
        _log("Мир не отвечает. Друг должен открыть мир «для сети», и вы оба — в одной сети "
             "(Radmin VPN / Wi-Fi).")
        return 1
    mc_version = cfg.get("mc_version", "1.21.1")
    book = friends.Friends.load()
    name = _friend_name(book, host, port)
    try:
        servers_dat.upsert(cfg.game_dir, name, address, icon=_server_icon())
        _log("«%s» добавлен в список серверов игры" % name)
    except Exception as exc:  # noqa: BLE001
        _log("servers.dat обновить не удалось: %s" % exc)
    downloader = _downloader()
    java = install.ensure_java(cfg, downloader, _log)
    neo_version = ""
    if cfg.get("mode") == "neoforge":
        neo_version = install.resolve_neo_version(mc_version, cfg.get("neoforge_version", ""), _log)
    if not install.installed(cfg.game_dir, mc_version, cfg.get("mode"), neo_version,
                             bool(cfg.get("skip_sounds"))):
        install.install_all(cfg.game_dir, mc_version, cfg.get("mode"), neo_version, java,
                            downloader, _log, _log, bool(cfg.get("skip_sounds")))
    target = neoforge.profile_id(neo_version) if cfg.get("mode") == "neoforge" else mc_version
    process, resolved = launch.launch(
        cfg.game_dir, target, java, int(cfg.get("ram_mb", 4096)),
        auth.sanitize_username(cfg.get("username", "Player")), cfg.get("jvm_args", ""),
        int(cfg.get("width") or 0), int(cfg.get("height") or 0), log=_log, quick_play=address)
    _log("Запущено: %s (pid %s) — автозаход в мир %s" % (resolved.id, process.pid, address))
    for line in process.stdout or []:
        print(line.rstrip(), flush=True)
    return process.wait()


def cli(args) -> int:
    cfg = config.Config.load()
    if args.java:
        cfg["java_path"] = os.path.abspath(args.java)
    if args.game_dir:
        cfg["game_dir"] = os.path.abspath(args.game_dir)
    if args.username:
        cfg["username"] = args.username
    if args.ram:
        cfg["ram_mb"] = args.ram
    if args.mode:
        cfg["mode"] = args.mode
    if args.neo:
        cfg["neoforge_version"] = args.neo
    if args.skip_sounds:
        cfg["skip_sounds"] = True

    mc_version = cfg.get("mc_version", "1.21.1")

    if args.cli == "lan":
        return _cli_lan(args)

    if args.cli == "friends":
        return _cli_friends(args)

    if args.cli == "invite":
        return _cli_invite(cfg, args)

    if args.cli == "upnp":
        return _cli_upnp(args)

    if args.cli == "join":
        return _cli_join(cfg, args)

    if args.cli == "java":
        found = javas.find_all(cfg.get("java_path", ""))
        if not found:
            _log("Java не найдена")
        for info in found:
            marker = "  <-- подходит для 1.21.1" if info.major >= javas.REQUIRED_MAJOR else ""
            _log("%s  [Java %d, %s]%s" % (info.path, info.major, info.source, marker))
        return 0

    if args.cli == "versions":
        for version in neoforge.list_versions(mc_version):
            _log("neoforge-%s" % version)
        return 0

    if args.cli == "setup":
        _log("Папка игры: %s" % cfg.game_dir)
        _log("Режим: %s" % cfg.get("mode"))
        downloader = _downloader()
        java = install.ensure_java(cfg, downloader, _log)
        neo_version = ""
        if cfg.get("mode") == "neoforge":
            neo_version = install.resolve_neo_version(mc_version, cfg.get("neoforge_version", ""), _log)
            _log("Версия NeoForge: %s" % neo_version)
        install.install_all(cfg.game_dir, mc_version, cfg.get("mode"), neo_version, java,
                            downloader, _log, _log, bool(cfg.get("skip_sounds")))
        _log("Готово. Java: %s" % java)
        return 0

    if args.cli == "launch":
        downloader = _downloader()
        java = install.ensure_java(cfg, downloader, _log)
        neo_version = ""
        if cfg.get("mode") == "neoforge":
            neo_version = install.resolve_neo_version(mc_version, cfg.get("neoforge_version", ""), _log)
        if not install.installed(cfg.game_dir, mc_version, cfg.get("mode"), neo_version,
                                 bool(cfg.get("skip_sounds"))):
            install.install_all(cfg.game_dir, mc_version, cfg.get("mode"), neo_version, java,
                                downloader, _log, _log, bool(cfg.get("skip_sounds")))
        target = neoforge.profile_id(neo_version) if cfg.get("mode") == "neoforge" else mc_version
        process, resolved = launch.launch(
            cfg.game_dir, target, java, int(cfg.get("ram_mb", 4096)),
            auth.sanitize_username(cfg.get("username", "Player")), cfg.get("jvm_args", ""),
            int(cfg.get("width") or 0), int(cfg.get("height") or 0), log=_log)
        _log("Запущено: %s (pid %s)" % (resolved.id, process.pid))
        for line in process.stdout or []:
            print(line.rstrip(), flush=True)
        return process.wait()

    if args.cli == "content":
        kind = args.type or "mod"
        create_only = not args.all
        if args.install:
            hit = modrinth.project(args.install)
            _log("Проект: %s (%s)" % (hit["title"], hit["slug"]))
            destination = _content_dir(cfg, kind, args.world or "")
            downloader = _downloader()
            queued = modrinth.install(downloader, hit["id"], destination, mc_version, "neoforge",
                                      slug=hit["slug"], kind=kind, game_dir=cfg.game_dir,
                                      allow_dependencies=(kind == "mod"), log=_log)
            if not queued:
                _log("Нечего устанавливать")
                return 1
            downloader.run()
            if kind == "resourcepack":
                for item in queued:
                    options.enable_resource_pack(cfg.game_dir, item["file_name"], True, _log)
            _log("Установлено в %s" % destination)
            return 0
        result = modrinth.search(args.query or "", kind, mc_version, "neoforge",
                                 args.limit, 0, create_only)
        _log("Найдено (всего %s), показано %d:" % (result["total"], len(result["hits"])))
        for hit in result["hits"]:
            _log("  %-42s %10d  %s" % (hit["title"][:42], hit["downloads"], hit["slug"]))
        _log("Установка: python launcher.py --cli content --install <slug> --type %s" % kind)
        return 0

    if args.cli == "skin":
        nickname = auth.sanitize_username(cfg.get("username", "Player"))
        if args.skin:
            data = skins.read_file(args.skin)
            source = os.path.basename(args.skin)
        elif args.skin_url:
            data = skins.download_by_url(args.skin_url)
            source = args.skin_url
        else:
            data = skins.download_by_nickname(nickname)
            source = "Мойанг"
        path = skins.apply(cfg.game_dir, nickname, data,
                           slim=cfg.get("skin_model", "wide") == "slim", log=_log)
        _log("Скин %s применён к %s: %s" % (source, nickname, path))
        return 0

    if args.cli == "shortcut":
        created = shortcut.create(desktop=True, in_folder=True)
        for path in created:
            _log("Ярлык: %s" % path)
        _log("Готово" if created else "Не удалось создать ярлык")
        return 0 if created else 1

    if args.cli == "check":
        target = None
        if cfg.get("mode") == "neoforge" and cfg.get("neoforge_version"):
            target = neoforge.profile_id(cfg["neoforge_version"])
        if not target or not mojang.load_version_json(cfg.game_dir, target):
            target = mc_version
        resolved = version_mod.resolve(cfg.game_dir, target)
        entries = version_mod.classpath(cfg.game_dir, resolved)
        missing = [entry for entry in entries if not os.path.exists(entry)]
        _log("Версия: %s" % resolved.id)
        _log("Классов в classpath: %d (%d отсутствуют)" % (len(entries), len(missing)))
        for entry in missing[:20]:
            _log("  нет: %s" % entry)
        java = install.ensure_java(cfg, _downloader(), _log) if args.resolve_java else cfg.get("java_path")
        if java:
            command, _ = launch.build_command(
                cfg.game_dir, target, java, int(cfg.get("ram_mb", 4096)),
                auth.sanitize_username(cfg.get("username", "Player")), cfg.get("jvm_args", ""))
            _log("Java: %s" % java)
            _log("Команда:")
            for index, token in enumerate(command):
                if token == "--cp" or (index and command[index - 1] in ("-cp", "-p", "--class-path")):
                    _log("  [%d] <длинный список из %d символов>" % (index, len(token)))
                else:
                    _log("  [%d] %s" % (index, token))
        _log("Vanilla установлена: %s" % ("да" if mojang.vanilla_installed(cfg.game_dir, mc_version) else "нет"))
        if cfg.get("neoforge_version"):
            _log("NeoForge установлен: %s" % (
                "да" if neoforge.is_installed(cfg.game_dir, cfg["neoforge_version"]) else "нет"))
        return 0
    return 2


def main() -> int:
    parser = argparse.ArgumentParser(description="Лаунчер Minecraft 1.21.1 + NeoForge")
    parser.add_argument("--cli", choices=["java", "versions", "setup", "launch", "check",
                                          "content", "skin", "shortcut", "lan", "friends",
                                          "invite", "join", "upnp"],
                        help="работать без окна")
    parser.add_argument("--game-dir", help="папка игры")
    parser.add_argument("--mode", choices=["neoforge", "vanilla"])
    parser.add_argument("--neo", help="версия NeoForge, например 21.1.262")
    parser.add_argument("--username")
    parser.add_argument("--java", help="путь к java.exe")
    parser.add_argument("--resolve-java", action="store_true",
                        help="для команды check: найти/скачать подходящую Java")
    parser.add_argument("--ram", type=int)
    parser.add_argument("--skip-sounds", action="store_true")
    parser.add_argument("--skin", help="PNG-файл скина для команды skin")
    parser.add_argument("--skin-url", help="ссылка на PNG-скин")
    parser.add_argument("--query", default="", help="поисковый запрос для каталога")
    parser.add_argument("--type", choices=["mod", "datapack", "resourcepack"], default="mod",
                        help="тип контента для каталога")
    parser.add_argument("--install", metavar="SLUG",
                        help="для команды content: установить проект по slug")
    parser.add_argument("--all", action="store_true",
                        help="для команды content: снять фильтр «только Create»")
    parser.add_argument("--world", default="", help="мир для датапаков")
    parser.add_argument("--limit", type=int, default=15, help="сколько результатов показать")
    parser.add_argument("--add", metavar="ТЕКСТ",
                        help="для команды friends: добавить друга («Имя 26.0.0.5:51234» или "
                             "приглашение с кодом CL1.…)")
    parser.add_argument("--remove", metavar="ИМЯ", help="для команды friends: удалить друга")
    parser.add_argument("--check", action="store_true",
                        help="для команды friends: проверить, отвечают ли адреса")
    parser.add_argument("--addr", help="адрес мира друга (26.0.0.5:51234)")
    parser.add_argument("--port", type=int, default=0,
                        help="порт: мира для invite, внешний для upnp")
    parser.add_argument("--world-port", type=int, default=0,
                        help="для upnp: порт мира, который пробрасываем")
    parser.add_argument("--timeout", type=float, default=3.0, help="сколько искать в сети, секунд")
    args = parser.parse_args()

    if args.cli:
        try:
            return cli(args)
        except DownloadCancelled:
            _log("Отменено")
            return 130

    try:
        from ui.app import run
    except ImportError as exc:  # нет tkinter
        print("Не удалось запустить интерфейс (%s).\nИспользуйте консольный режим, "
              "например: python launcher.py --cli setup" % exc, file=sys.stderr)
        return 1
    return run()


if __name__ == "__main__":
    sys.exit(main())
