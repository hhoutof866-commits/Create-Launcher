"""Формирование команды запуска и старт процесса Minecraft."""

from __future__ import annotations

import os
import shlex
import subprocess

from . import auth, mojang, neoforge, rule, version as version_mod
from .paths import WINDOWS

LAUNCHER_NAME = "NeoForgeLauncher"
LAUNCHER_VERSION = "1.0.0"


def _features(width: int = 0, height: int = 0):
    features = rule.default_features()
    if width and height:
        features["has_custom_resolution"] = True
    return features


def build_command(mc_dir: str, version_id: str, java: str, ram_mb: int, username: str,
                  jvm_extra: str = "", width: int = 0, height: int = 0, features=None,
                  quick_play: str = ""):
    """Собирает полную командную строку java для запуска версии.

    quick_play — адрес сервера («26.0.0.5:51234»): игра сразу зайдёт в него.
    Это штатный ключ Minecraft 1.21.1 `--quickPlayMultiplayer`, который включается
    правилом is_quick_play_multiplayer (см. core/rule.py).
    """
    features = dict(features or _features(width, height))
    resolved = version_mod.resolve(mc_dir, version_id, features)

    natives_dir = os.path.join(mc_dir, "natives", resolved.id)
    version_mod.extract_natives(mc_dir, resolved, natives_dir, features)

    classpath = version_mod.classpath(mc_dir, resolved, features)
    if not classpath:
        raise RuntimeError("Пустой classpath: версия %s установлена некорректно" % version_id)

    uuid_text = auth.offline_uuid(auth.sanitize_username(username))
    mapping = {
        "natives_directory": natives_dir,
        "launcher_name": LAUNCHER_NAME,
        "launcher_version": LAUNCHER_VERSION,
        "classpath": os.pathsep.join(classpath),
        "classpath_separator": os.pathsep,
        "library_directory": mojang.libraries_dir(mc_dir),
        "version_name": resolved.id,
        "game_directory": mc_dir,
        "assets_root": mojang.assets_dir(mc_dir),
        "assets_index_name": resolved.assets_index or "legacy",
        "auth_player_name": username,
        "auth_uuid": uuid_text.replace("-", ""),
        "auth_access_token": "0",
        "clientid": "0",
        "auth_xuid": "0",
        "user_type": "legacy",
        "version_type": resolved.type,
        "resolution_width": str(width or 854),
        "resolution_height": str(height or 480),
        "user_properties": "{}",
    }
    if quick_play:
        features["is_quick_play_multiplayer"] = True
        mapping["quickPlayMultiplayer"] = quick_play

    command = [java, "-Xmx%dM" % max(512, int(ram_mb)), "-Xms512M"]
    jvm_args = rule.resolve_arguments(resolved.jvm_elements, mapping, features)
    joined = " ".join(jvm_args)
    for key in ("java.library.path", "jna.tmpdir",
                "org.lwjgl.system.SharedLibraryExtractPath", "io.netty.native.workdir"):
        if ("-D%s=" % key) not in joined:
            command.append("-D%s=%s" % (key, natives_dir))
    logging_arg = version_mod.logging_argument(mc_dir, resolved)
    if logging_arg:
        template, path = logging_arg
        command.append(template.replace("${path}", path))
    command.extend(jvm_args)
    if jvm_extra:
        try:
            command.extend(shlex.split(jvm_extra, posix=False))
        except ValueError:
            command.extend(jvm_extra.split())
    command.append(resolved.main_class)
    command.extend(rule.resolve_arguments(resolved.game_elements, mapping, features))
    return command, resolved


def launch(mc_dir: str, version_id: str, java: str, ram_mb: int, username: str,
           jvm_extra: str = "", width: int = 0, height: int = 0, log=None,
           quick_play: str = ""):
    command, resolved = build_command(mc_dir, version_id, java, ram_mb, username,
                                      jvm_extra, width, height, quick_play=quick_play)
    if log:
        log("Запуск: %s" % resolved.id)
        if quick_play:
            log("Автозаход в мир по адресу %s" % quick_play)
        log("Команда: %s" % " ".join(command))
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if WINDOWS else 0
    process = subprocess.Popen(
        command, cwd=mc_dir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
        creationflags=flags,
    )
    return process, resolved


def launch_target(cfg, log=None):
    """Какая версия будет запускаться при текущих настройках (для интерфейса)."""
    mode = cfg.get("mode", "neoforge")
    if mode == "neoforge":
        neo = (cfg.get("neoforge_version") or "").strip()
        if neo:
            return neoforge.profile_id(neo)
    return cfg.get("mc_version", "1.21.1")
