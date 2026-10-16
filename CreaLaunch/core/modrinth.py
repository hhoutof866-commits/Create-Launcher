"""Каталог Modrinth: поиск и установка модов, датапаков и ресурспаков.

Публичный API, ключ не нужен. Обязателен только User-Agent.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from .down import USER_AGENT

API = "https://api.modrinth.com/v2"

# То, что считаем «контентом для Create», даже если слово не попало в заголовок
CREATE_SLUGS = {
    "create", "flywheel", "ponder", "copycats", "steam-n-rails", "createaddition",
    "create-big-cannons", "createbigcannons", "create-enchantment-industry",
    "createnuclear", "create-aeronautics", "create-connected", "create-central-kitchen",
    "create-diesel-generators", "create-more-automation", "create-slice-and-dice",
    "create-jetpack", "create-ultimate", "create-ore-excavation", "create-steam-n-rails",
    "create-new-age",
}

CONTENT_LABELS = {
    "mod": "Моды",
    "datapack": "Датапаки",
    "resourcepack": "Ресурспаки",
    "shader": "Шейдеры",
}


class ModrinthError(Exception):
    pass


def _request(url: str, timeout: int = 45):
    request = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise ModrinthError("Modrinth ответил HTTP %s" % exc.code) from exc
    except (OSError, ValueError) as exc:
        raise ModrinthError("Нет связи с Modrinth: %s" % exc) from exc


def _facets(project_type: str, game_version: str, loader: str):
    facets = [["project_type:" + project_type]]
    if game_version:
        facets.append(["versions:" + game_version])
    if loader and project_type == "mod":
        facets.append(["categories:" + loader])
    return facets


def _is_create(hit: dict) -> bool:
    slug = (hit.get("slug") or "").lower()
    if slug in CREATE_SLUGS:
        return True
    text = " ".join([hit.get("title") or "", hit.get("description") or "",
                     slug, " ".join(hit.get("categories") or [])]).lower()
    return "create" in text


def _normalize(hit: dict) -> dict:
    return {
        "id": hit.get("project_id"),
        "slug": hit.get("slug"),
        "title": hit.get("title") or hit.get("slug"),
        "description": hit.get("description") or "",
        "author": hit.get("author"),
        "downloads": hit.get("downloads") or 0,
        "follows": hit.get("follows") or 0,
        "icon": hit.get("icon_url"),
        "categories": hit.get("categories") or [],
        "page": "https://modrinth.com/%s/%s" % (
            (hit.get("project_type") or "mod"), hit.get("slug")),
    }


def search(query: str, project_type: str = "mod", game_version: str = "1.21.1",
           loader: str = "neoforge", limit: int = 20, offset: int = 0,
           create_only: bool = False):
    """Поиск проектов. create_only добавляет слово create и фильтрует результаты."""
    text = (query or "").strip()
    if create_only and "create" not in text.lower():
        text = ("create " + text).strip()
    parameters = {
        "query": text,
        "limit": max(1, min(limit, 50)),
        "offset": max(0, offset),
        "facets": json.dumps(_facets(project_type, game_version, loader)),
    }
    data = _request(API + "/search?" + urllib.parse.urlencode(parameters))
    hits = [_normalize(hit) for hit in data.get("hits", [])]
    if create_only:
        hits = [hit for hit in hits if _is_create(hit)]
    return {"hits": hits, "total": data.get("total_hits", len(hits)), "offset": offset}


def project_versions(project_id: str, game_version: str = "1.21.1",
                     loader: str = "neoforge"):
    parameters = {}
    if game_version:
        parameters["game_versions"] = json.dumps([game_version])
    if loader:
        parameters["loaders"] = json.dumps([loader])
    url = "%s/project/%s/version" % (API, urllib.parse.quote(project_id))
    if parameters:
        url += "?" + urllib.parse.urlencode(parameters)
    versions = _request(url)
    if not isinstance(versions, list):
        raise ModrinthError("Неожиданный ответ Modrinth")
    return versions


def project(project_id: str) -> dict:
    """Проект по id или slug (slug тоже принимается сервером)."""
    data = _request("%s/project/%s" % (API, urllib.parse.quote(project_id)))
    return {
        "id": data.get("id"),
        "slug": data.get("slug") or project_id,
        "title": data.get("title") or project_id,
        "project_type": data.get("project_type") or "mod",
    }


def primary_file(version: dict):
    files = version.get("files") or []
    if not files:
        raise ModrinthError("У версии %s нет файлов" % version.get("version_number"))
    for item in files:
        if item.get("primary"):
            return item
    return files[0]


# ------------------------------------------------------------- индекс


def index_path(game_dir: str) -> str:
    return os.path.join(game_dir, "launcher-content.json")


def load_index(game_dir: str) -> dict:
    try:
        with open(index_path(game_dir), encoding="utf-8") as handle:
            data = json.load(handle)
            return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_index(game_dir: str, data: dict) -> None:
    try:
        os.makedirs(game_dir, exist_ok=True)
        with open(index_path(game_dir), "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
    except OSError:
        pass


def remember(game_dir: str, project_id: str, record: dict) -> None:
    data = load_index(game_dir)
    record["installed_at"] = int(time.time())
    data[project_id] = record
    save_index(game_dir, data)


def installed_here(dest_dir: str, file_name: str) -> bool:
    return bool(file_name) and os.path.exists(os.path.join(dest_dir, file_name))


# ------------------------------------------------------------ установка


def plan_install(project_id: str, dest_dir: str, game_version: str = "1.21.1",
                 loader: str = "neoforge", allow_dependencies: bool = True,
                 _seen=None, _depth: int = 0):
    """Готовит список файлов к загрузке (с обязательными зависимостями)."""
    seen = _seen if _seen is not None else set()
    if project_id in seen or _depth > 3:
        return []
    seen.add(project_id)
    versions = project_versions(project_id, game_version, loader)
    if not versions:
        raise ModrinthError("Для Minecraft %s%s у проекта нет подходящей версии"
                            % (game_version, "/" + loader if loader else ""))
    version = versions[0]
    file = primary_file(version)
    plan = [{
        "project_id": project_id,
        "title": version.get("name") or project_id,
        "file_name": file.get("filename"),
        "url": file.get("url"),
        "size": file.get("size") or 0,
        "sha1": (file.get("hashes") or {}).get("sha1"),
        "version_number": version.get("version_number"),
        "dest_dir": dest_dir,
    }]
    if allow_dependencies:
        for dependency in version.get("dependencies") or []:
            if dependency.get("dependency_type") != "required":
                continue
            dependency_id = dependency.get("project_id")
            if dependency_id:
                plan.extend(plan_install(dependency_id, dest_dir, game_version, loader,
                                         allow_dependencies, seen, _depth + 1))
    return plan


def install(downloader, project_id: str, dest_dir: str, game_version: str = "1.21.1",
            loader: str = "neoforge", slug: str = "", kind: str = "mod",
            game_dir: str = "", allow_dependencies: bool = True, log=None):
    """Ставит проект в очередь загрузки. downloader.run() вызывает вызывающий."""
    plan = plan_install(project_id, dest_dir, game_version, loader, allow_dependencies)
    queued = []
    for item in plan:
        target = os.path.join(item["dest_dir"], item["file_name"])
        queued.append(item)
        downloader.add(item["url"], target, item["sha1"], item["size"], item["file_name"])
        if log:
            log("  + %s (%s)" % (item["file_name"], item["title"]))
    if game_dir and slug:
        remember(game_dir, project_id, {
            "slug": slug, "title": plan[0]["title"] if plan else project_id,
            "file": plan[0]["file_name"] if plan else "",
            "kind": kind, "version": plan[0]["version_number"] if plan else "",
        })
    return queued
