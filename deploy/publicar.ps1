# Atualização de código: envia o código do PC para a VM e reconstrói o app (o banco fica como está).
param([string]$VmHost)
. "$PSScriptRoot\_comum.ps1"
$VmHost = Get-VmHost $VmHost
Write-Host "Enviando código para $VmHost..." -ForegroundColor Cyan
Send-Code $VmHost
Invoke-Vm $VmHost "bash /opt/cfo-central/deploy/setup-vm.sh"
