# Agenda o resumo diário do CFO (Claude Code no seu plano) no Agendador de Tarefas do Windows.
$ErrorActionPreference = "Stop"
$hora = "07:30"
$nome = "CFO Central - resumo diario"

$claude = Get-Command claude -ErrorAction SilentlyContinue
if (-not $claude) {
    Write-Host "Claude Code nao encontrado. Instale (https://claude.com/claude-code), rode 'claude' uma vez e faca login" -ForegroundColor Red
    Write-Host "com a sua conta do plano (Pro/Max). Depois rode este arquivo de novo." -ForegroundColor Red
    exit 1
}
& claude mcp get cfo-central *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Registrando o servidor do CFO Central no Claude Code..."
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "instalar_mcp.ps1")
}

$script = Join-Path $PSScriptRoot "resumo_diario.ps1"
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$script`""
$trigger = New-ScheduledTaskTrigger -Daily -At $hora
# se o PC estiver desligado no horário, roda assim que possível
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 15)
Register-ScheduledTask -TaskName $nome -Action $action -Trigger $trigger -Settings $settings `
    -Description "Escreve o resumo 'Seu CFO hoje' no CFO Central usando o Claude Code (plano do usuario)." -Force | Out-Null
Write-Host "Agendado: todo dia as $hora ('$nome')." -ForegroundColor Green

Write-Host "Gerando o primeiro resumo agora (leva cerca de 1 minuto)..."
& powershell -NoProfile -ExecutionPolicy Bypass -File $script
if ($LASTEXITCODE -eq 0) { Write-Host "Pronto: abra o Painel do CFO Central." -ForegroundColor Green }
else { Write-Host "Nao deu certo desta vez. Veja logs\resumo-diario.log." -ForegroundColor Yellow }
