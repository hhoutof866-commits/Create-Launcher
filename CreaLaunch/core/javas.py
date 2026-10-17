"""Поиск и загрузка Java (для 1.21.1 нужна Java 21+)."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tarfile
import urllib.request
import zipfile

from . import paths
from .down import USER_AGENT

ADOPTIUM_ASSETS = ("https://api.adoptium.net/v3/assets/latest/{major}/hotspot"
                   "?os={os}&architecture={arch}&image_type=jre&vendor=eclipse")
ADOPTIUM_BINARY = ("https://api.adoptium.net/v3/binary/latest/{major}/ga/{os}/{arch}"
                   "/jre/hotspot/normal/eclipse")

REQUIRED_MAJOR = 21


class JavaInfo:
    def __init__(self, path: str, home: str, version: str, major: int, source: str = ""):
        self.path = path
        self.home = home
        self.version = version
        self.major = major
        self.source = source

    def __str__(self):
        return "Java %s (%s)" % (self.version or "?", self.path)


def _creation_flags():
    if paths.WINDOWS:
        return getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return 0


def major_from_home(home: str):
    """Читает release-файл JDK: JAVA_VERSION="21.0.12"."""
    release = os.path.join(home, "release")
    try:
        with open(release, encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith("JAVA_VERSION="):
                    value = line.split("=", 1)[1].strip().strip('"')
                    parts = value.split(".")
                    if parts and parts[0].isdigit():
                        major = int(parts[0])
                        if major == 1 and len(parts) > 1 and parts[1].isdigit():
                            major = int(parts[1])   # legacy-формат 1.8.0_401
                        return major, value
    except OSError:
        pass
    return None, None


def probe(java_path: str):
    """Запускает java -version и парсит версию."""
    if not java_path or not os.path.exists(java_path):
        return None
    home = os.path.dirname(os.path.dirname(java_path))
    major, version = major_from_home(home)
    if major:
        return JavaInfo(java_path, home, version, major, "release-файл")
    try:
        result = subprocess.run([java_path, "-version"], capture_output=True, text=True,
                                timeout=25, creationflags=_creation_flags())
        text = (result.stderr or "") + (result.stdout or "")
        match = re.search(r'version "([^"]+)"', text)
        if match:
            value = match.group(1)
            head = value.split(".")[0]
            major = int(head) if head.isdigit() else 8
            if head == "1" and len(value.split(".")) > 1:
                major = int(value.split(".")[1])
            return JavaInfo(java_path, home, value, major, "java -version")
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    return None


def _java_binaries_in(home: str):
    return os.path.join(home, "bin", paths.java_exe_name())


def candidate_homes():
    homes = []
    env_home = os.environ.get("JAVA_HOME")
    if env_home:
        homes.append(env_home)
    roots = []
    if paths.WINDOWS:
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                     os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                     r"C:\Program Files", r"C:\Program Files (x86)"):
            for vendor in ("Java", "Eclipse Adoptium", "Eclipse Foundation", "Microsoft", "Zulu",
                           "BellSoft", "Amazon Corretto", "Semeru", "JetBrains", "AdoptOpenJDK"):
                roots.append(os.path.join(base, vendor))
    elif paths.MACOS:
        roots.append("/Library/Java/JavaVirtualMachines")
    else:
        roots.extend(["/usr/lib/jvm", "/usr/java", os.path.expanduser("~/.jdks")])
    for root in roots:
        try:
            for name in os.listdir(root):
                homes.append(os.path.join(root, name))
        except OSError:
            continue
    # рантайм официального лаунчера Minecraft: Java 21 у 1.21.1 уже установлена рядом
    runtime_root = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), ".minecraft",
                                "runtime")
    platform_name = "windows" if paths.WINDOWS else ("mac-os" if paths.MACOS else "linux")
    try:
        for name in os.listdir(runtime_root):
            platform_dir = os.path.join(runtime_root, name, platform_name)
            for inner in os.listdir(platform_dir):
                homes.append(os.path.join(platform_dir, inner))
    except OSError:
        pass
    # собственная папка java/ лаунчера
    try:
        for name in os.listdir(paths.java_dir()):
            home = os.path.join(paths.java_dir(), name)
            homes.append(home)
            if os.path.isdir(os.path.join(home, "bin")):
                continue
            # на случай вложенного каталога (jdk-21.0.1+12-jre/)
            try:
                for inner in os.listdir(home):
                    homes.append(os.path.join(home, inner))
            except OSError:
                pass
    except OSError:
        pass
    return homes


def find_all(extra_path: str = ""):
    found = []
    seen = set()

    def add(info):
        if not info:
            return
        key = os.path.normcase(os.path.abspath(info.path))
        if key in seen:
            return
        seen.add(key)
        found.append(info)

    if extra_path:
        add(probe(extra_path))
    which = shutil.which("java")
    if which:
        add(probe(which))
    for home in candidate_homes():
        binary = _java_binaries_in(home)
        if os.path.isfile(binary):
            add(probe(binary))
    found.sort(key=lambda info: info.major, reverse=True)
    return found


def pick(min_major: int = REQUIRED_MAJOR, extra_path: str = ""):
    """Подходящая Java (>= min_major) или None."""
    for info in find_all(extra_path):
        if info.major >= min_major:
            return info
    return None


def adoptium_arch() -> str:
    arch = paths.platform_arch()
    return {"x64": "x64", "x86": "x32", "arm64": "aarch64"}.get(arch, "x64")


def queue_jre(downloader, major: int = REQUIRED_MAJOR, log=None):
    """Ставит в очередь архив JRE с Adoptium и возвращает (url, имя архива)."""
    os_name = paths.platform_name()
    arch = adoptium_arch()
    url = ADOPTIUM_ASSETS.format(major=major, os=os_name, arch=arch)
    try:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=60) as response:
            data = json.loads(response.read().decode("utf-8"))
        package = data[0]["binary"]["package"]
        archive_url = package["link"]
        name = package.get("name") or ("jre-%s.zip" % major)
        downloader.add(archive_url, os.path.join(paths.cache_dir(), name),
                       package.get("checksum"), package.get("size", 0), "Java %d" % major)
        return name
    except Exception as exc:  # noqa: BLE001
        if log:
            log("Adoptium API недоступен (%s), пробую прямую ссылку" % exc)
    archive_url = ADOPTIUM_BINARY.format(major=major, os=os_name, arch=arch)
    name = "jre-%d-%s-%s.zip" % (major, os_name, arch)
    downloader.add(archive_url, os.path.join(paths.cache_dir(), name), None, 0, "Java %d" % major)
    return name


def extract_archive(archive: str, dest: str):
    os.makedirs(dest, exist_ok=True)
    if archive.endswith(".zip"):
        with zipfile.ZipFile(archive) as archive_file:
            archive_file.extractall(dest)
    elif archive.endswith((".tar.gz", ".tgz")):
        with tarfile.open(archive) as tar:
            tar.extractall(dest)
    else:
        raise RuntimeError("Неизвестный формат архива: %s" % archive)
    entries = [os.path.join(dest, name) for name in os.listdir(dest)]
    directories = [e for e in entries if os.path.isdir(e)]
    if len(directories) == 1 and not os.path.exists(os.path.join(dest, "bin")):
        root = directories[0]
        for name in os.listdir(root):
            shutil.move(os.path.join(root, name), os.path.join(dest, name))
        os.rmdir(root)


def install_jre(downloader, major: int = REQUIRED_MAJOR, log=None) -> str:
    """Скачивает и распаковывает JRE, возвращает путь к java."""
    if log:
        log("Загрузка Java %d (Temurin)..." % major)
    archive_name = queue_jre(downloader, major, log)
    downloader.run()
    archive = os.path.join(paths.cache_dir(), archive_name)
    dest = os.path.join(paths.java_dir(), "temurin-%d" % major)
    if os.path.isdir(dest):
        shutil.rmtree(dest, ignore_errors=True)
    if log:
        log("Распаковка Java в %s" % dest)
    extract_archive(archive, dest)
    binary = _java_binaries_in(dest)
    if not os.path.isfile(binary):
        raise RuntimeError("Java не распаковалась: не найден %s" % binary)
    info = probe(binary)
    if log:
        log("Java %d установлена: %s" % (major, info or binary))
    return binary
