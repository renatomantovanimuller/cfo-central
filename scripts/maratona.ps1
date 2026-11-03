# Executor da maratona: retoma o orquestrador headless quando nenhuma sessão do Claude está ativa.
# Chamado pela tarefa agendada CFO-Maratona a cada 20 min. Ver docs/maratona/README.md.
$ErrorActionPreference = "Continue"
$Deadline = [datetime]"2026-10-16T09:30:00"
$StopNewRunsAt = [datetime]"2026-10-16T09:05:00"
$IdleMinutes = 15
$Root = Split-Path -Parent $PSScriptRoot
$Dir = Join-Path $Root "docs\maratona"
$LogDir = Join-Path $Dir "logs"
$Lock = Join-Path $LogDir "runner.lock"
$Claude = Join-Path $env:USERPROFILE ".local\bin\claude.exe"
$Prompt = "Leia o arquivo docs/maratona/RETOMAR.md e siga exatamente as instruções dele."
New-Item -ItemType Directory -Force $LogDir | Out-Null

function Write-Log([string]$msg) {
  Add-Content -Path (Join-Path $LogDir "runner.log") -Value "$(Get-Date -Format s) $msg" -Encoding UTF8
}

if ((Get-Date) -ge $Deadline) {
  Write-Log "prazo encerrado; removendo a tarefa agendada"
  Unregister-ScheduledTask -TaskName "CFO-Maratona" -Confirm:$false -ErrorAction SilentlyContinue
  exit 0
}
if ((Get-Date) -ge $StopNewRunsAt) { Write-Log "perto do prazo; nenhuma execução nova"; exit 0 }

if (Test-Path $Lock) {
  $lockPid = Get-Content $Lock -ErrorAction SilentlyContinue
  if ($lockPid -and (Get-Process -Id $lockPid -ErrorAction SilentlyContinue)) { Write-Log "executor já ativo (pid $lockPid)"; exit 0 }
}

# Sessão ativa = algum transcript deste projeto (inclusive de subagentes) escrito há pouco.
$latest = Get-ChildItem (Join-Path $env:USERPROFILE ".claude\projects") -Directory |
  Where-Object Name -like "*CFO-Pessoal*" |
  Get-ChildItem -Recurse -File -Filter *.jsonl -ErrorAction SilentlyContinue |
  Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($latest) {
  $age = ((Get-Date) - $latest.LastWriteTime).TotalMinutes
  if ($age -lt $IdleMinutes) { Write-Log ("sessão ativa ({0:N0} min desde a última escrita)" -f $age); exit 0 }
}

Set-Content -Path $Lock -Value $PID
try {
  Set-Location $Root
  while ((Get-Date) -lt $StopNewRunsAt) {
    $out = Join-Path $LogDir ("run-" + (Get-Date -Format "MMdd-HHmm") + ".log")
    Write-Log "iniciando claude -p -> $out"
    $t0 = Get-Date
    & $Claude -p $Prompt --model opus --permission-mode auto --permission-prompts none --output-format text 2>&1 |
      Out-File -FilePath $out -Encoding UTF8
    $mins = ((Get-Date) - $t0).TotalMinutes
    Write-Log ("claude terminou: código {0}, {1:N1} min" -f $LASTEXITCODE, $mins)
    if ($mins -lt 3) { Write-Log "execução curta (cota esgotada?); nova tentativa no próximo disparo"; break }
  }
} finally {
  Remove-Item $Lock -Force -ErrorAction SilentlyContinue
}
