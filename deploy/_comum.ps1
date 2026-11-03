# Funções compartilhadas pelos scripts de nuvem. Host = nome da VM na tailnet (MagicDNS), usuário ubuntu.
$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot
$Compose = "docker compose -f docker-compose.yml -f deploy/docker-compose.cloud.yml"

function Get-VmHost([string]$VmHost) {
    if ($VmHost) { return $VmHost }
    if ($env:CFO_VM) { return $env:CFO_VM }
    return "cfo-central"
}

function Invoke-Vm([string]$VmHost, [string]$Cmd) {
    $Cmd = $Cmd -replace "`r", ""
    & ssh -o BatchMode=yes -o ConnectTimeout=15 $VmHost $Cmd
    if ($LASTEXITCODE -ne 0) { throw "Falhou na VM: $Cmd" }
}

function Send-Code([string]$VmHost) {
    $tar = Join-Path $env:TEMP "cfo-central-src.tgz"
    Push-Location $Root
    try {
        & tar.exe -czf $tar --exclude=.venv --exclude=frontend/node_modules --exclude=frontend/dist `
            --exclude=frontend/dist-demo --exclude=backups --exclude=.git --exclude=.env --exclude="_backup-*" `
            --exclude=__pycache__ --exclude=.pytest_cache --exclude=data --exclude="*.tsbuildinfo" .
        if ($LASTEXITCODE -ne 0) { throw "tar falhou" }
    } finally { Pop-Location }
    & scp -o BatchMode=yes $tar "${VmHost}:/tmp/cfo-central-src.tgz"
    if ($LASTEXITCODE -ne 0) { throw "scp do código falhou" }
    Remove-Item $tar
    Invoke-Vm $VmHost "mkdir -p /opt/cfo-central && tar -xzf /tmp/cfo-central-src.tgz -C /opt/cfo-central && rm /tmp/cfo-central-src.tgz"
}
