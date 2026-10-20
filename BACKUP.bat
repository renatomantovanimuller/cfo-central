@echo off
setlocal
cd /d "%~dp0"
if not exist backups mkdir backups
for /f %%d in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmm"') do set STAMP=%%d
docker compose exec -T db pg_dump -U cfo -Fc cfo > "backups\cfo-%STAMP%.dump"
if errorlevel 1 ( echo [CFO] Falha no backup. O Docker esta rodando? & pause & exit /b 1 )
echo [CFO] Backup salvo em backups\cfo-%STAMP%.dump
echo Para restaurar: docker compose exec -T db pg_restore -U cfo -d cfo --clean ^< backups\ARQUIVO.dump
pause
