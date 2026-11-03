# Publica o CFO Central (127.0.0.1:8060) só para os aparelhos da sua rede Tailscale, com HTTPS.
# Nada é aberto para a internet: o tráfego passa pelo túnel WireGuard do Tailscale.
# Uso: TAILSCALE-CELULAR.bat (liga)  |  TAILSCALE-CELULAR.bat desligar
param([string]$acao = "ligar")
$ErrorActionPreference = "Continue"
$root = Split-Path $PSScriptRoot -Parent
$log = Join-Path $root "docs\tailscale.txt"
Start-Transcript -Path $log -Force | Out-Null

$ts = (Get-Command tailscale -ErrorAction SilentlyContinue).Source
if (-not $ts) { $ts = Join-Path $env:ProgramFiles "Tailscale\tailscale.exe" }
if (-not (Test-Path $ts)) { Write-Host "ERRO: Tailscale não encontrado. Instale em https://tailscale.com/download/windows"; Stop-Transcript | Out-Null; exit 1 }

if ($acao -eq "desligar") {
  & $ts serve reset
  Write-Host "Publicação desligada. O app continua só em http://127.0.0.1:8060"
  Stop-Transcript | Out-Null; exit 0
}

# 1) liga o aplicativo do Tailscale (ele sobe a conexão e mostra o ícone na bandeja)
$gui = Join-Path $env:ProgramFiles "Tailscale\tailscale-ipn.exe"
if ((Test-Path $gui) -and -not (Get-Process tailscale-ipn -ErrorAction SilentlyContinue)) { Start-Process $gui; Start-Sleep 4 }
$up = Start-Job { param($t) & $t up 2>&1 } -ArgumentList $ts
if (-not (Wait-Job $up -Timeout 20)) { Write-Host "AGUARDANDO LOGIN: entre na sua conta Tailscale pelo link abaixo." }
Receive-Job $up | ForEach-Object { Write-Host $_ }
Stop-Job $up -ErrorAction SilentlyContinue; Remove-Job $up -Force -ErrorAction SilentlyContinue
Write-Host "=== status ==="
& $ts status 2>&1 | Select-Object -First 15

# 2) o app precisa responder no PC
Write-Host "=== app local ==="
try { $r = Invoke-WebRequest "http://127.0.0.1:8060/api/auth/status" -UseBasicParsing -TimeoutSec 8; Write-Host "app ok: HTTP $($r.StatusCode)" }
catch { Write-Host "ERRO: o app não respondeu em 127.0.0.1:8060 ($($_.Exception.Message)). Rode INICIAR.bat." }

# 3) publica na tailnet com HTTPS (a configuração fica salva e volta sozinha após reiniciar o PC)
Write-Host "=== serve ==="
$job = Start-Job { param($t) & $t serve --bg --https=443 http://127.0.0.1:8060 2>&1 } -ArgumentList $ts
if (-not (Wait-Job $job -Timeout 30)) { Write-Host "AGUARDANDO: o Tailscale pediu para habilitar HTTPS/Serve na sua tailnet (link abaixo)." }
Receive-Job $job | ForEach-Object { Write-Host $_ }
Stop-Job $job -ErrorAction SilentlyContinue; Remove-Job $job -Force -ErrorAction SilentlyContinue

Write-Host "=== serve status ==="
& $ts serve status 2>&1
$self = (& $ts status --json | ConvertFrom-Json).Self
$name = $self.DNSName.TrimEnd(".")
Write-Host "=== endereço ==="
Write-Host "No celular (com o app Tailscale ligado na mesma conta): https://$name"
Write-Host "=== teste pela tailnet ==="
for ($i = 1; $i -le 6; $i++) {
  try { $r = Invoke-WebRequest "https://$name/api/auth/status" -UseBasicParsing -TimeoutSec 20; Write-Host "tailnet ok: HTTP $($r.StatusCode) $($r.Content)"; break }
  catch { Write-Host "tentativa $i : $($_.Exception.Message)"; Start-Sleep 5 }
}
Stop-Transcript | Out-Null
