# Cria o .env do CFO Central a partir do .env.example e gera segredos locais.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $root ".env"
if (Test-Path $envFile) { Write-Host "[CFO] .env já existe, nada a fazer."; exit 0 }
$lines = Get-Content (Join-Path $root ".env.example") -Encoding UTF8
$vals = @{}
function New-Secret([int]$n) {
  $b = New-Object byte[] $n
  [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b)
  return [Convert]::ToBase64String($b).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}
$vals['SECRET_KEY'] = New-Secret 48
$vals['POSTGRES_PASSWORD'] = New-Secret 24
$out = $lines | ForEach-Object {
  if ($_ -match '^([A-Z_]+)=(.*)$' -and $vals.ContainsKey($matches[1])) { "$($matches[1])=$($vals[$matches[1]])" } else { $_ }
}
[IO.File]::WriteAllLines($envFile, $out, (New-Object System.Text.UTF8Encoding $false))
if (-not $vals.ContainsKey('PLUGGY_CLIENT_ID')) {
  Write-Host "[CFO] Preencha PLUGGY_CLIENT_ID e PLUGGY_CLIENT_SECRET no .env que vai abrir."
  notepad $envFile
}
