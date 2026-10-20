@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
title CFO Central

if not exist ".env" powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\setup_env.ps1"

docker info >nul 2>&1
if errorlevel 1 (
  echo [CFO] Iniciando o Docker Desktop...
  start "" "%ProgramFiles%\Docker\Docker\Docker Desktop.exe"
  for /l %%i in (1,1,60) do (
    timeout /t 3 >nul
    docker info >nul 2>&1 && goto docker_ok
  )
  echo [CFO] O Docker nao respondeu. Abra o Docker Desktop e rode de novo, ou use INICIAR-SEM-DOCKER.bat
  pause
  exit /b 1
)
:docker_ok
echo [CFO] Subindo banco e aplicativo (na primeira vez leva alguns minutos)...
docker compose up -d --build
if errorlevel 1 ( pause & exit /b 1 )

echo [CFO] Aguardando o app responder...
powershell -NoProfile -Command "for($i=0;$i -lt 90;$i++){try{Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8060/api/health -TimeoutSec 2 | Out-Null; exit 0}catch{Start-Sleep 2}}; exit 1"
if errorlevel 1 (
  echo [CFO] O app nao respondeu. Logs: docker compose logs app
  pause
  exit /b 1
)
start "" http://127.0.0.1:8060
echo [CFO] Pronto. O app segue rodando em segundo plano (PARAR.bat desliga).
timeout /t 6 >nul
