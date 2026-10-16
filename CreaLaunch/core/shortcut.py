"""Создание ярлыков (Windows .lnk / Linux .desktop)."""

from __future__ import annotations

import os
import subprocess
import sys

from . import branding, paths

LAUNCHER_NAME = "NeoForge Launcher"


def _python_executable() -> str:
    """pythonw.exe — чтобы не открывалось чёрное окно консоли."""
    executable = sys.executable or "python"
    if paths.WINDOWS:
        candidate = os.path.join(os.path.dirname(executable), "pythonw.exe")
        if os.path.isfile(candidate):
            return candidate
    return executable


def desktop_dir() -> str:
    if paths.WINDOWS:
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 "[Environment]::GetFolderPath('Desktop')"],
                capture_output=True, text=True, timeout=40,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            value = (result.stdout or "").strip()
            if value and os.path.isdir(value):
                return value
        except (OSError, subprocess.SubprocessError):
            pass
    return os.path.join(os.path.expanduser("~"), "Desktop")


def _ps_quote(value) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def create(directory: str = None, name: str = LAUNCHER_NAME, desktop: bool = True,
           in_folder: bool = True) -> list:
    """Создаёт ярлык в папке лаунчера и/или на рабочем столе. Возвращает список путей."""
    directory = directory or paths.launcher_dir()
    entry = os.path.join(directory, "launcher.py")
    executable = _python_executable()
    icon, _logo = branding.ensure()
    created = []

    targets = []
    if in_folder:
        targets.append(os.path.join(directory, name + ".lnk"))
    if desktop:
        targets.append(os.path.join(desktop_dir(), name + ".lnk"))

    for target in targets:
        try:
            if paths.WINDOWS:
                script = (
                    "$s = (New-Object -ComObject WScript.Shell).CreateShortcut({target});"
                    "$s.TargetPath = {exe}; $s.Arguments = '\"{entry}\"';"
                    "$s.WorkingDirectory = {work}; $s.Description = {desc};"
                    "$s.IconLocation = {icon}; $s.Save()"
                ).format(
                    target=_ps_quote(target), exe=_ps_quote(executable),
                    entry=entry.replace("'", "''"), work=_ps_quote(directory),
                    desc=_ps_quote("Minecraft 1.21.1 + NeoForge"),
                    icon=_ps_quote((icon + ",0") if icon else executable),
                )
                subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                               capture_output=True, text=True, timeout=60,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            else:
                target = os.path.join(directory, name + ".desktop") if in_folder else target
                with open(target, "w", encoding="utf-8") as handle:
                    handle.write("[Desktop Entry]\nType=Application\nName=%s\n"
                                 "Exec=%s %s\nPath=%s\nIcon=%s\nTerminal=false\n"
                                 % (name, executable, entry, directory, branding.logo_path()))
                os.chmod(target, 0o755)
            if os.path.exists(target):
                created.append(target)
        except (OSError, subprocess.SubprocessError):
            continue
    return created
