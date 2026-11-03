# Primeira ida para a nuvem: código, .env, banco atual e curadoria do PC para a VM, tudo pela tailnet.
# Pré-requisitos: VM criada com deploy/cloud-init.yaml, "ssh cfo-central" funcionando (ver deploy/README.md)
# e o CFO Central rodando no PC (INICIAR.bat) para exportar o banco.
param([string]$VmHost)
. "$PSScriptRoot\_comum.ps1"
$VmHost = Get-VmHost $VmHost
Set-Location $Root

Write-Host "1/5 Testando acesso à VM ($VmHost)..." -ForegroundColor Cyan
Invoke-Vm $VmHost "docker version --format '{{.Server.Version}}' && tailscale status --self --peers=false"

Write-Host "2/5 Exportando o banco do PC..." -ForegroundColor Cyan
$dump = Join-Path $Root "backups\migracao-nuvem.dump"
docker exec cfo-central-db-1 sh -c "pg_dump -U cfo -d cfo -Fc -f /tmp/migra.dump && pg_restore --list /tmp/migra.dump > /dev/null"
if ($LASTEXITCODE -ne 0) { throw "pg_dump falhou: o CFO Central está rodando no PC?" }
docker cp cfo-central-db-1:/tmp/migra.dump $dump
if ((Get-Item $dump).Length -lt 10000) { throw "dump suspeito (muito pequeno): $dump" }

Write-Host "3/5 Enviando código, .env e curadoria..." -ForegroundColor Cyan
Send-Code $VmHost
& scp -o BatchMode=yes (Join-Path $Root ".env") "${VmHost}:/opt/cfo-central/.env"
Get-ChildItem (Join-Path $Root "curadoria") -Filter *.json | ForEach-Object {
    & scp -o BatchMode=yes $_.FullName "${VmHost}:/opt/cfo-central/curadoria/$($_.Name)"
}
& scp -o BatchMode=yes $dump "${VmHost}:/tmp/migra.dump"
if ($LASTEXITCODE -ne 0) { throw "envio falhou" }

Write-Host "4/5 Restaurando o banco na VM..." -ForegroundColor Cyan
Invoke-Vm $VmHost @"
set -e; cd /opt/cfo-central; chmod 600 .env
$Compose up -d db
for i in `$(seq 1 60); do docker exec cfo-central-db-1 pg_isready -U cfo -d cfo >/dev/null 2>&1 && break; sleep 2; done
docker cp /tmp/migra.dump cfo-central-db-1:/tmp/migra.dump
docker exec cfo-central-db-1 pg_restore -U cfo -d cfo --clean --if-exists --no-owner /tmp/migra.dump || true
docker exec cfo-central-db-1 psql -U cfo -d cfo -tAc 'select count(*) from transactions'
rm /tmp/migra.dump
"@

Write-Host "5/5 Subindo o app e o HTTPS da tailnet..." -ForegroundColor Cyan
Invoke-Vm $VmHost "bash /opt/cfo-central/deploy/setup-vm.sh"
Write-Host ""
Write-Host "Feito. Confira o app no endereço acima, depois desligue a cópia do PC (PARAR.bat) para não haver" -ForegroundColor Green
Write-Host "duas instâncias sincronizando e mandando e-mail. Para o Claude usar a nuvem: deploy\instalar-mcp-remoto.ps1" -ForegroundColor Green
