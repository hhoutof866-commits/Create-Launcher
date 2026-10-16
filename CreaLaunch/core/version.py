"""Сборка «слитой» версии (наследование через inheritsFrom) и classpath."""

from __future__ import annotations

import json
import os
import zipfile

from . import maven, mojang, rule
from .paths import platform_arch, platform_name


class ResolvedVersion:
    """Результат склейки родительской и дочерней версии (например 1.21.1 + NeoForge)."""

    def __init__(self, data: dict):
        self.data = data
        self.id = data.get("id", "")
        self.main_class = data.get("mainClass", "")
        self.type = data.get("type", "release")
        self.assets_index = (data.get("assetIndex") or {}).get("id")
        self.java_major = (data.get("javaVersion") or {}).get("majorVersion", 8)
        self.logging = (data.get("logging") or {}).get("client") or {}
        self.jvm_elements = ((data.get("arguments") or {}).get("jvm")) or []
        self.game_elements = ((data.get("arguments") or {}).get("game")) or []
        self.libraries = data.get("libraries", [])
        self.minecraft_arguments = data.get("minecraftArguments")  # старый формат


def load_local(mc_dir: str, version_id: str):
    return mojang.load_version_json(mc_dir, version_id)


def merge(mc_dir: str, version_id: str) -> dict:
    """Склеивает дочерний профиль с родительским (inheritsFrom), как это делает лаунчер Mojang."""
    child = load_local(mc_dir, version_id)
    if not child:
        raise RuntimeError("Профиль %s не установлен" % version_id)
    parent_id = child.get("inheritsFrom")
    if not parent_id:
        return child
    parent = load_local(mc_dir, parent_id)
    if not parent:
        raise RuntimeError("Не установлена базовая версия %s" % parent_id)

    merged = dict(parent)
    merged["id"] = child.get("id", version_id)

    for key in ("mainClass", "type", "assets", "assetIndex", "downloads", "javaVersion", "logging"):
        if key in child:
            merged[key] = child[key]

    libraries = list(parent.get("libraries", []))
    index = {}
    for position, library in enumerate(libraries):
        index[maven.library_base_name(library.get("name", ""))] = position
    for library in child.get("libraries", []):
        key = maven.library_base_name(library.get("name", ""))
        if key in index:
            libraries[index[key]] = library
        else:
            index[key] = len(libraries)
            libraries.append(library)
    merged["libraries"] = libraries

    parent_args = parent.get("arguments") or {}
    child_args = child.get("arguments") or {}
    if parent_args or child_args:
        merged["arguments"] = {
            "jvm": list(parent_args.get("jvm") or []) + list(child_args.get("jvm") or []),
            "game": list(parent_args.get("game") or []) + list(child_args.get("game") or []),
        }
        merged.pop("minecraftArguments", None)
    return merged


def resolve(mc_dir: str, version_id: str, features=None) -> ResolvedVersion:
    return ResolvedVersion(merge(mc_dir, version_id))


def select_libraries(version: ResolvedVersion, features=None):
    """Список библиотек, подходящих текущей ОС."""
    result = []
    for library in version.libraries:
        if not rule.rules_allow(library.get("rules"), features):
            continue
        result.append(library)
    return result


def library_jar(mc_dir: str, library: dict):
    relative, url, _sha1, _size = maven.artifact_of(library)
    return maven.to_local(mojang.libraries_dir(mc_dir), relative)


def native_libraries(version: ResolvedVersion, features=None):
    """Библиотеки с нативным кодом LWJGL (нужны и в classpath, и для распаковки)."""
    result = []
    for library in select_libraries(version, features):
        name = library.get("name", "")
        if ":natives-" in name:
            if _native_matches(name.split(":natives-", 1)[1]):
                result.append(library)
        elif library.get("natives"):
            result.append(library)
    return result


def _native_matches(classifier: str) -> bool:
    classifier = classifier.lower()
    os_name = platform_name()
    if os_name == "windows":
        if not classifier.startswith("windows"):
            return False
    elif os_name == "osx":
        if not classifier.startswith("macos"):
            return False
    else:
        if not classifier.startswith("linux"):
            return False
    arch = platform_arch()
    if arch == "arm64":
        return "arm64" in classifier or "aarch64" in classifier
    if arch == "x86":
        return classifier.endswith("x86")
    return not classifier.endswith("x86") and "arm64" not in classifier and "aarch64" not in classifier


def classpath(mc_dir: str, version: ResolvedVersion, features=None):
    entries = []
    for library in select_libraries(version, features):
        path = library_jar(mc_dir, library)
        if os.path.isfile(path):
            entries.append(path)
    jar = mojang.client_jar_path(mc_dir, version.id)
    if os.path.isfile(jar):
        entries.append(jar)
    return entries


def extract_natives(mc_dir: str, version: ResolvedVersion, dest: str, features=None):
    """Распаковывает .dll/.so/.dylib из нативных библиотек в отдельный каталог."""
    os.makedirs(dest, exist_ok=True)
    count = 0
    for library in select_libraries(version, features):
        name = library.get("name", "")
        is_native = False
        if ":natives-" in name:
            is_native = _native_matches(name.split(":natives-", 1)[1])
        elif library.get("natives"):
            is_native = True
        if not is_native:
            continue
        path = library_jar(mc_dir, library)
        if not os.path.isfile(path):
            continue
        try:
            with zipfile.ZipFile(path) as archive:
                for entry in archive.namelist():
                    if entry.endswith(("/", ".class", ".java", ".txt", ".md")):
                        continue
                    if not entry.lower().endswith((".dll", ".so", ".dylib", ".jnilib")):
                        continue
                    target = os.path.join(dest, os.path.basename(entry))
                    with archive.open(entry) as src, open(target, "wb") as out:
                        out.write(src.read())
                    count += 1
        except (zipfile.BadZipFile, OSError):
            continue
    return count


def logging_argument(mc_dir: str, version: ResolvedVersion):
    """Путь к конфигу log4j2, если он есть."""
    file_info = version.logging.get("file") if version.logging else None
    if not file_info:
        return None
    path = os.path.join(mojang.assets_dir(mc_dir), "log_configs", file_info.get("id", "client.xml"))
    if os.path.isfile(path):
        return (version.logging.get("argument") or "-Dlog4j.configurationFile=${path}"), path
    return None


def read_json(path: str):
    with open(path, encoding="utf-8") as f:
        return json.load(f)
