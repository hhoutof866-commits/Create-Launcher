"""Установка: Minecraft + NeoForge + Java, с проверкой уже скачанных файлов."""

from __future__ import annotations

import os

from . import javas, mojang, neoforge


def resolve_neo_version(mc_version: str, wanted: str = "", log=None):
    """Выбирает версию NeoForge: указанную или последнюю для данной версии Minecraft."""
    versions = neoforge.list_versions(mc_version)
    if not versions:
        raise RuntimeError("Не найдено ни одной версии NeoForge для Minecraft %s" % mc_version)
    wanted = (wanted or "").strip()
    if wanted and wanted in versions:
        return wanted
    if wanted and log:
        log("Версия NeoForge %s недоступна, беру %s" % (wanted, versions[-1]))
    return versions[-1]


def ensure_java(cfg, downloader, log=None) -> str:
    """Возвращает путь к java 21+, при необходимости скачивает Temurin."""
    info = javas.pick(javas.REQUIRED_MAJOR, cfg.get("java_path", ""))
    if info:
        if log:
            log("Найдена подходящая Java: %s" % info)
        return info.path
    if log:
        log("Подходящая Java %d не найдена — качаю Temurin JRE" % javas.REQUIRED_MAJOR)
    return javas.install_jre(downloader, javas.REQUIRED_MAJOR, log)


def installed(mc_dir: str, mc_version: str, mode: str, neo_version: str = "",
              skip_sounds: bool = False) -> bool:
    if not mojang.vanilla_installed(mc_dir, mc_version, skip_sounds):
        return False
    if mode == "neoforge":
        return bool(neo_version) and neoforge.is_installed(mc_dir, neo_version)
    return True


def install_all(mc_dir: str, mc_version: str, mode: str, neo_version: str, java: str,
                downloader, on_stage=None, log=None, skip_sounds: bool = False) -> None:
    """Доводит каталог игры до состояния «можно запускать»."""
    def stage(text):
        if on_stage:
            on_stage(text)

    def say(text):
        if log:
            log(text)

    os.makedirs(mc_dir, exist_ok=True)
    for name in ("mods", "resourcepacks", "shaderpacks", "saves"):
        os.makedirs(os.path.join(mc_dir, name), exist_ok=True)

    if mojang.vanilla_installed(mc_dir, mc_version):
        say("Minecraft %s уже установлен" % mc_version)
    else:
        stage("Установка Minecraft %s" % mc_version)
        mojang.install(mc_dir, mc_version, downloader, stage, log, skip_sounds)
        downloader.run()

    if mode == "neoforge":
        if not neo_version:
            neo_version = resolve_neo_version(mc_version, "", log)
        stage("Установка NeoForge %s" % neo_version)
        neoforge.install(mc_dir, mc_version, neo_version, java, downloader, stage, log)
    say("Установка завершена")
