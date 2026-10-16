"""Установка NeoForge: список версий, скачивание и запуск установщика."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import urllib.request
import xml.etree.ElementTree as ET

from . import maven, mojang, paths
from .down import USER_AGENT

METADATA_URL = "https://maven.neoforged.net/releases/net/neoforged/neoforge/maven-metadata.xml"
REPO_URL = "https://maven.neoforged.net/releases"


def compatible_prefix(mc_version: str) -> str:
    """1.21.1 -> 21.1, 1.21 -> 21.0 (схема нумерации NeoForge)."""
    parts = mc_version.split(".")
    major = parts[1] if len(parts) > 1 else "0"
    patch = parts[2] if len(parts) > 2 else "0"
    return "%s.%s" % (major, patch)


def _version_key(text: str):
    return tuple(int(part) if part.isdigit() else 0 for part in text.split("."))


def list_versions(mc_version: str, timeout: int = 60):
    """Все версии NeoForge для указанной версии Minecraft (по возрастанию)."""
    request = urllib.request.Request(METADATA_URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        root = ET.fromstring(response.read())
    prefix = compatible_prefix(mc_version) + "."
    versions = []
    for element in root.iter("version"):
        text = (element.text or "").strip()
        if text.startswith(prefix):
            versions.append(text)
    versions.sort(key=_version_key)
    return versions


def latest_version(mc_version: str):
    versions = list_versions(mc_version)
    return versions[-1] if versions else None


def profile_id(neo_version: str) -> str:
    return "neoforge-" + neo_version


def installer_url(neo_version: str) -> str:
    return "%s/net/neoforged/neoforge/%s/neoforge-%s-installer.jar" % (REPO_URL, neo_version, neo_version)


def profile_json_path(mc_dir: str, neo_version: str) -> str:
    version_id = profile_id(neo_version)
    return mojang.version_json_path(mc_dir, version_id)


def load_profile(mc_dir: str, neo_version: str):
    path = profile_json_path(mc_dir, neo_version)
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def neoform_version(profile: dict):
    args = ((profile.get("arguments") or {}).get("game")) or []
    for position, token in enumerate(args):
        if token == "--fml.neoFormVersion" and position + 1 < len(args):
            return args[position + 1]
    return None


def generated_files(mc_dir: str, neo_version: str, profile: dict):
    """Файлы, которые создаёт установщик (патченый клиент и NeoForm-артефакты)."""
    files = [
        os.path.join(mojang.libraries_dir(mc_dir), "net", "neoforged", "neoforge", neo_version,
                     "neoforge-%s-client.jar" % neo_version),
        os.path.join(mojang.libraries_dir(mc_dir), "net", "neoforged", "neoforge", neo_version,
                     "neoforge-%s-universal.jar" % neo_version),
    ]
    mc_version = profile.get("inheritsFrom")
    neoform = neoform_version(profile)
    if mc_version and neoform:
        base = os.path.join(mojang.libraries_dir(mc_dir), "net", "minecraft", "client",
                            "%s-%s" % (mc_version, neoform))
        stem = "client-%s-%s" % (mc_version, neoform)
        files.append(os.path.join(base, stem + "-srg.jar"))
        files.append(os.path.join(base, stem + "-extra.jar"))
    return files


def is_installed(mc_dir: str, neo_version: str) -> bool:
    profile = load_profile(mc_dir, neo_version)
    if not profile:
        return False
    for path in generated_files(mc_dir, neo_version, profile):
        if not os.path.exists(path):
            return False
    return True


def ensure_launcher_profiles(mc_dir: str) -> str:
    """Установщику NeoForge нужен launcher_profiles.json в каталоге игры."""
    path = os.path.join(mc_dir, "launcher_profiles.json")
    if os.path.exists(path):
        return path
    data = {
        "profiles": {},
        "settings": {"enableSnapshots": False, "keepLauncherOpen": False},
        "selectedProfile": "",
        "clientToken": "",
        "authenticationDatabase": {},
        "selectedUser": "",
        "launcherVersion": {"name": "NeoForgeLauncher", "format": 21},
    }
    os.makedirs(mc_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def installer_cache_path(neo_version: str) -> str:
    return os.path.join(paths.cache_dir(), "neoforge-%s-installer.jar" % neo_version)


def queue_installer(downloader, neo_version: str, log=None):
    url = installer_url(neo_version)
    if log:
        try:
            request = urllib.request.Request(url + ".sha1", headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=30) as response:
                expected = response.read().decode("utf-8").split()[0].strip()
        except Exception:
            expected = None
    else:
        expected = None
    downloader.add(url, installer_cache_path(neo_version), expected, 0, "установщик NeoForge")


def run_installer(java: str, mc_dir: str, neo_version: str, log=None) -> None:
    """Запускает установщик NeoForge в режиме --installClient."""
    jar = installer_cache_path(neo_version)
    if not os.path.exists(jar):
        raise RuntimeError("Установщик NeoForge не найден: %s" % jar)
    ensure_launcher_profiles(mc_dir)
    command = [java, "-jar", jar, "--installClient", mc_dir]
    if log:
        log("Запуск установщика NeoForge: %s" % " ".join(command))
    creation = 0
    if paths.WINDOWS:
        creation = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", cwd=mc_dir,
        creationflags=creation,
    )
    tail = []
    for line in process.stdout or []:
        line = line.rstrip()
        if not line:
            continue
        tail.append(line)
        if len(tail) > 40:
            tail.pop(0)
        if log:
            log("  " + line)
    code = process.wait()
    if code != 0:
        raise RuntimeError("Установщик NeoForge завершился с кодом %s:\n%s" % (code, "\n".join(tail[-12:])))


def copy_client_jar(mc_dir: str, mc_version: str, neo_version: str, log=None) -> str:
    """Лаунчер Mojang кладёт jar ванильного клиента в каталог профиля — делаем то же."""
    source = mojang.client_jar_path(mc_dir, mc_version)
    target = mojang.client_jar_path(mc_dir, profile_id(neo_version))
    if os.path.exists(target) or not os.path.exists(source):
        return target
    os.makedirs(os.path.dirname(target), exist_ok=True)
    shutil.copyfile(source, target)
    if log:
        log("Клиентский jar скопирован в профиль %s" % profile_id(neo_version))
    return target


def queue_profile_libraries(downloader, mc_dir: str, neo_version: str):
    """Проверяет библиотеки профиля и ставит отсутствующие в очередь."""
    profile = load_profile(mc_dir, neo_version)
    if not profile:
        return 0
    libraries_root = mojang.libraries_dir(mc_dir)
    added = 0
    for library in profile.get("libraries", []):
        relative, url, sha1, size = maven.artifact_of(library)
        if not url:
            continue
        target = maven.to_local(libraries_root, relative)
        if os.path.exists(target) and (not sha1 or _sha1_ok(target, sha1)):
            continue
        downloader.add(url, target, sha1, size, os.path.basename(relative))
        added += 1
    return added


def _sha1_ok(path: str, expected: str) -> bool:
    from .down import sha1_file

    try:
        return sha1_file(path) == expected.lower()
    except OSError:
        return False


def install(mc_dir: str, mc_version: str, neo_version: str, java: str, downloader,
            on_stage=None, log=None) -> None:
    """Полная установка профиля NeoForge (установщик + проверка файлов)."""
    def stage(text):
        if on_stage:
            on_stage(text)

    if is_installed(mc_dir, neo_version):
        if log:
            log("NeoForge %s уже установлен" % neo_version)
        return

    stage("Скачивание установщика NeoForge %s" % neo_version)
    queue_installer(downloader, neo_version, log)
    downloader.run()

    stage("Установка NeoForge %s (это может занять пару минут)" % neo_version)
    run_installer(java, mc_dir, neo_version, log)

    profile = load_profile(mc_dir, neo_version)
    if not profile:
        raise RuntimeError("Установщик не создал профиль %s" % profile_id(neo_version))

    missing = [path for path in generated_files(mc_dir, neo_version, profile) if not os.path.exists(path)]
    if missing:
        raise RuntimeError("Установщик не создал файлы:\n" + "\n".join(missing))

    stage("Проверка библиотек NeoForge")
    added = queue_profile_libraries(downloader, mc_dir, neo_version)
    if added:
        downloader.run()

    copy_client_jar(mc_dir, mc_version, neo_version, log)

    if not re.match(r"^\d+\.\d+", neo_version):
        raise RuntimeError("Некорректная версия NeoForge: %s" % neo_version)
