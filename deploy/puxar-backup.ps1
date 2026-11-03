# Copia o backup mais recente da VM para backups\nuvem\ no PC (cópia extra fora da Oracle). Agende no
# Agendador de Tarefas do Windows (diário, "executar o mais cedo possível se perdido").
param([string]$VmHost, [int]$KeepDays = 60)
. "$PSScriptRoot\_comum.ps1"
$VmHost = Get-VmHost $VmHost
$dest = Join-Path $Root "backups\nuvem"
New-Item -ItemType Directory -Force $dest | Out-Null
$last = (& ssh -o BatchMode=yes $VmHost "ls -1t /opt/cfo-central/backups/cfo-*.dump | head -1").Trim()
if (-not $last) { throw "nenhum backup na VM" }
& scp -o BatchMode=yes "${VmHost}:$last" $dest
if ($LASTEXITCODE -ne 0) { throw "scp falhou" }
Get-ChildItem $dest -Filter "cfo-*.dump" | Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-$KeepDays) } | Remove-Item
Write-Host "Backup copiado: $(Split-Path $last -Leaf)"
