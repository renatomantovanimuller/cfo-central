@echo off
chcp 65001 >nul
cd /d "%~dp0"
title CFO Central - verificacao
set OUT=docs\verificacao.txt
echo === pytest %DATE% %TIME% === > %OUT%
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider >> %OUT% 2>&1
echo === exit pytest: %ERRORLEVEL% === >> %OUT%
cd frontend
echo === npm run build === >> ..\%OUT%
call npm run build >> ..\%OUT% 2>&1
echo === exit build: %ERRORLEVEL% === >> ..\%OUT%
call npx vitest run >> ..\%OUT% 2>&1
echo === exit vitest: %ERRORLEVEL% === >> ..\%OUT%
cd ..
echo Pronto. Resultado em %OUT%
timeout /t 5 >nul
