# Escreve o resumo do dia ("Seu CFO hoje") com o Claude Code logado no seu plano (sem chave de API).
# Roda pela tarefa agendada criada por AGENDAR-RESUMO.bat; pode ser rodado à mão a qualquer momento.
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $root "logs"
New-Item -ItemType Directory -Force $logDir | Out-Null
$log = Join-Path $logDir "resumo-diario.log"
function Log($msg) { "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $msg" | Out-File -Append -Encoding utf8 $log }

$claude = (Get-Command claude -ErrorAction SilentlyContinue).Source
if (-not $claude) { Log "Claude Code nao encontrado no PATH. Instale e faca login (claude) uma vez."; exit 1 }

$docker = (Get-Command docker -ErrorAction SilentlyContinue).Source
if (-not $docker) { $docker = "C:\Program Files\Docker\Docker\resources\bin\docker.exe" }
$state = & $docker inspect -f "{{.State.Running}}" cfo-central-app-1 2>$null
if ($state -ne "true") { Log "App parado (cfo-central-app-1). Rode INICIAR.bat; o resumo fica para a proxima."; exit 1 }

$tools = "mcp__cfo-central__guia,mcp__cfo-central__publicar_briefing,mcp__cfo-central__revisoes,mcp__cfo-central__lancamentos"
$prompt = Get-Content -Raw -Encoding UTF8 (Join-Path $PSScriptRoot "resumo_diario.md")
$OutputEncoding = New-Object System.Text.UTF8Encoding $false
Log "inicio"
$out = $prompt | & $claude -p --model sonnet --allowedTools $tools 2>&1
Log ("fim (codigo $LASTEXITCODE): " + (($out | Out-String).Trim() -replace "\s+", " "))
exit $LASTEXITCODE
