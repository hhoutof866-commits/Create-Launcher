"""Быстрые проверки без сети: правила, UUID, пути maven, моды, скины, PNG, каталог, окно.

Запуск:            python tests/smoke.py
С сетью (Modrinth): python tests/smoke.py --online
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import auth, branding, maven, modrinth, mods, options, png, rule, skins  # noqa: E402

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


def check_window() -> None:
    try:
        import tkinter as tk
        from ui.app import LauncherApp
        root = tk.Tk()
        root.withdraw()
        app = LauncherApp(root)
        for _ in range(5):
            root.update()
        app._refresh_skin()
        root.update()
        check("окно собралось", bool(app.play_button), True)
        check("папка игры по умолчанию не пуста", bool(app.dir_var.get()), True)
        check("вкладок пять", len(app.tabs), 5)
        check("активная вкладка одна", app.current_tab, app.tab_order[0])
        check("превью скина построено", app.skin_player_image is not None, True)
        root.destroy()
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
