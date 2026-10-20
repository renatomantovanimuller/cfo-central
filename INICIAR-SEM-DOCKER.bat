@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
title CFO Central (sem Docker, SQLite)
if not exist ".env" powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\setup_env.ps1"

set "PY="
if exist ".venv\Scripts\python.exe" goto run
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY if exist "%USERPROFILE%\anaconda3\python.exe" set "PY=%USERPROFILE%\anaconda3\python.exe"
if not defined PY ( echo [CFO] Python nao encontrado. & pause & exit /b 1 )
%PY% -m venv .venv || ( pause & exit /b 1 )
:run
".venv\Scripts\python.exe" -m pip install -q --disable-pip-version-check -r requirements.txt || ( pause & exit /b 1 )
set "DATABASE_URL=sqlite:///data/cfo-central.db"
start "" cmd /c "timeout /t 5 >nul & start http://127.0.0.1:8060"
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8060
pause
