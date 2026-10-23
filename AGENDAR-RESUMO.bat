@echo off
REM Agenda o resumo diario "Seu CFO hoje" (Claude Code no seu plano, sem chave de API)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\agendar_resumo.ps1"
pause
