"""Утилиты для maven-координат и файловой раскладки библиотек."""

from __future__ import annotations

import os


def maven_to_path(name: str) -> str:
    """'org.lwjgl:lwjgl:3.3.3:natives-windows' -> 'org/lwjgl/lwjgl/3.3.3/lwjgl-3.3.3-natives-windows.jar'."""
    extension = "jar"
    if "@" in name:
        name, extension = name.split("@", 1)
    parts = name.split(":")
    group = parts[0]
    artifact = parts[1]
    version = parts[2]
    classifier = parts[3] if len(parts) > 3 else None
    filename = "%s-%s" % (artifact, version)
    if classifier:
        filename += "-" + classifier
    filename += "." + extension
    return "/".join(group.split(".") + [artifact, version, filename])


def library_base_name(name: str) -> str:
    return name.split("@")[0]


def artifact_of(library: dict):
    """Возвращает (relative_path, url, sha1, size) для артефакта библиотеки."""
    downloads = library.get("downloads") or {}
    artifact = downloads.get("artifact")
    if artifact and artifact.get("path"):
        return (artifact["path"], artifact.get("url"), artifact.get("sha1"), artifact.get("size", 0))
    # библиотека без downloads (например, из maven-репозитория NeoForge)
    base = (library.get("url") or "https://libraries.minecraft.net/").rstrip("/")
    path = maven_to_path(library["name"])
    return (path, base + "/" + path, None, 0)


def classifier_artifact_of(library: dict, classifier: str):
    downloads = library.get("downloads") or {}
    classifiers = downloads.get("classifiers") or {}
    entry = classifiers.get(classifier)
    if entry and entry.get("path"):
        return (entry["path"], entry.get("url"), entry.get("sha1"), entry.get("size", 0))
    return None


def to_local(libraries_dir: str, relative: str) -> str:
    return os.path.join(libraries_dir, *relative.split("/"))
