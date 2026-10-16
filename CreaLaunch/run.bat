@echo off
chcp 65001 >nul
cd /d "%~dp0"
title NeoForge Launcher

set PY=
where python >nul 2>nul && set PY=python
if "%PY%"=="" (where py >nul 2>nul && set PY=py)
if "%PY%"=="" (
    echo.
    echo Python не найден. Установите Python 3.9+ с https://www.python.org/downloads/
    echo и обязательно отметьте галочку "Add Python to PATH".
    echo.
    pause
    exit /b 1
)

%PY% launcher.py %*
if errorlevel 1 (
    echo.
    echo Лаунчер завершился с ошибкой.
    pause
)
