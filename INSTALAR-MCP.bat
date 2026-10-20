@echo off
REM Conecta o Claude (Desktop/Code) ao CFO Central via MCP
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\instalar_mcp.ps1"
pause
