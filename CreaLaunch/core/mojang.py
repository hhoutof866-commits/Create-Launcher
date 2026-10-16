"""Работа с манифестом Mojang: загрузка версии, библиотек и ассетов."""

from __future__ import annotations

import json
import os
import urllib.request

from . import maven, rule
from .down import USER_AGENT

MANIFEST_URL = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
ASSET_BASE = "https://resources.download.minecraft.net"
LIBRARIES_BASE = "https://libraries.minecraft.net"


def http_json(url: str):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def versions_dir(mc_dir: str) -> str:
    return os.path.join(mc_dir, "versions")


def libraries_dir(mc_dir: str) -> str:
    return os.path.join(mc_dir, "libraries")


def assets_dir(mc_dir: str) -> str:
    return os.path.join(mc_dir, "assets")


def version_json_path(mc_dir: str, version_id: str) -> str:
    return os.path.join(versions_dir(mc_dir), version_id, version_id + ".json")


def client_jar_path(mc_dir: str, version_id: str) -> str:
    return os.path.join(versions_dir(mc_dir), version_id, version_id + ".jar")


def load_version_json(mc_dir: str, version_id: str):
    path = version_json_path(mc_dir, version_id)
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def fetch_manifest():
    return http_json(MANIFEST_URL)


def find_version(manifest: dict, version_id: str):
    for entry in manifest.get("versions", []):
        if entry.get("id") == version_id:
            return entry
    return None


def vanilla_installed(mc_dir: str, version_id: str, skip_sounds: bool = False) -> bool:
    data = load_version_json(mc_dir, version_id)
    if not data:
        return False
    client = (data.get("downloads") or {}).get("client") or {}
    if not os.path.exists(client_jar_path(mc_dir, version_id)):
        return False
    index_id = (data.get("assetIndex") or {}).get("id")
    if index_id:
        index_path = os.path.join(assets_dir(mc_dir), "indexes", index_id + ".json")
        if not os.path.exists(index_path):
            return False
        try:
            with open(index_path, encoding="utf-8") as f:
                index_data = json.load(f)
        except (OSError, ValueError):
            return False
        root = assets_dir(mc_dir)
        for name, obj in (index_data.get("objects") or {}).items():
            if skip_sounds and _is_sound(name):
                continue
            digest = obj.get("hash", "")
            if digest and not os.path.exists(os.path.join(root, "objects", digest[:2], digest)):
                return False
    for library in data.get("libraries", []):
        if not rule.rules_allow(library.get("rules")):
            continue
        artifact = (library.get("downloads") or {}).get("artifact")
        if artifact and artifact.get("path"):
            if not os.path.exists(maven.to_local(libraries_dir(mc_dir), artifact["path"])):
                return False
    return True


def install(mc_dir: str, version_id: str, downloader, on_stage=None, log=None,
            skip_sounds: bool = False) -> dict:
    """Скачивает всё, что нужно для ванильного запуска указанной версии."""
    def stage(text):
        if on_stage:
            on_stage(text)

    def say(text):
        if log:
            log(text)

    os.makedirs(mc_dir, exist_ok=True)
    stage("Получение манифеста версий")
    manifest = fetch_manifest()
    entry = find_version(manifest, version_id)
    if not entry:
        raise RuntimeError("Версия %s не найдена в манифесте Mojang" % version_id)

    stage("Получение описания версии %s" % version_id)
    data = http_json(entry["url"])
    path = version_json_path(mc_dir, version_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    say("Версия %s: %d библиотек" % (version_id, len(data.get("libraries", []))))

    client = (data.get("downloads") or {}).get("client") or {}
    if client.get("url"):
        downloader.add(client["url"], client_jar_path(mc_dir, version_id),
                       client.get("sha1"), client.get("size", 0), "client.jar")

    libs_root = libraries_dir(mc_dir)
    for library in data.get("libraries", []):
        if not rule.rules_allow(library.get("rules")):
            continue
        relative, url, sha1, size = maven.artifact_of(library)
        if url:
            downloader.add(url, maven.to_local(libs_root, relative), sha1, size,
                           os.path.basename(relative))
        natives = library.get("natives") or {}
        classifier = natives.get(rule.platform_name()) if natives else None
        if classifier:
            if "${arch}" in classifier:
                classifier = classifier.replace("${arch}", "64" if rule.platform_arch() != "x86" else "32")
            entry_native = maven.classifier_artifact_of(library, classifier)
            if entry_native:
                rel, url, sha1, size = entry_native
                downloader.add(url, maven.to_local(libs_root, rel), sha1, size,
                               os.path.basename(rel))

    # индекс ассетов + сами ассеты
    index = data.get("assetIndex") or {}
    if index.get("url"):
        stage("Получение списка ассетов")
        index_data = http_json(index["url"])
        index_path = os.path.join(assets_dir(mc_dir), "indexes", index["id"] + ".json")
        os.makedirs(os.path.dirname(index_path), exist_ok=True)
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(index_data, f, ensure_ascii=False)
        objects = index_data.get("objects") or {}
        stage("Подготовка ассетов (%d шт.)" % len(objects))
        for name, obj in objects.items():
            if skip_sounds and _is_sound(name):
                continue
            digest = obj.get("hash", "")
            relative = os.path.join("objects", digest[:2], digest)
            downloader.add(
                "%s/%s/%s" % (ASSET_BASE, digest[:2], digest),
                os.path.join(assets_dir(mc_dir), relative),
                digest, obj.get("size", 0), "assets",
            )

    logging_cfg = (data.get("logging") or {}).get("client") or {}
    file_info = logging_cfg.get("file") or {}
    if file_info.get("url"):
        downloader.add(file_info["url"],
                       os.path.join(assets_dir(mc_dir), "log_configs", file_info.get("id", "client.xml")),
                       file_info.get("sha1"), file_info.get("size", 0), "log4j")
    return data


def _is_sound(name: str) -> bool:
    return name.startswith("minecraft/sounds/")
