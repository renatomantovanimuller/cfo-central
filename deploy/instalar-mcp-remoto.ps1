# Aponta o MCP "cfo-central" do Claude Desktop/Claude Code para a VM: o servidor MCP roda dentro do container
# da nuvem e o Claude conversa com ele por SSH pela tailnet (nada exposto na internet).
param([string]$VmHost)
. "$PSScriptRoot\_comum.ps1"
$VmHost = Get-VmHost $VmHost
$name = "cfo-central"
$ssh = (Get-Command ssh -ErrorAction SilentlyContinue).Source
if (-not $ssh) { $ssh = "C:\Windows\System32\OpenSSH\ssh.exe" }
$remote = "docker exec -i cfo-central-app-1 python -m app.assistant.mcp_server"
& $ssh -o BatchMode=yes -o ConnectTimeout=15 $VmHost "docker inspect -f '{{.State.Running}}' cfo-central-app-1"
if ($LASTEXITCODE -ne 0) { throw "Não consegui falar com a VM ($VmHost) ou o app não está rodando." }
$server = [ordered]@{ command = $ssh; args = @("-T", "-o", "BatchMode=yes", "-o", "ServerAliveInterval=30", $VmHost, $remote) }

$targets = @("$env:APPDATA\Claude")
Get-ChildItem "$env:LOCALAPPDATA\Packages" -Directory -Filter "Claude_*" -ErrorAction SilentlyContinue |
    ForEach-Object { $targets += (Join-Path $_.FullName "LocalCache\Roaming\Claude") }
$targets = $targets | Where-Object { Test-Path $_ }
$utf8 = New-Object System.Text.UTF8Encoding $false
foreach ($dir in $targets) {
    $cfg = Join-Path $dir "claude_desktop_config.json"
    $obj = [pscustomobject]@{}
    if (Test-Path $cfg) {
        Copy-Item $cfg "$cfg.bak-$(Get-Date -Format yyyyMMdd-HHmmss)"
        $raw = [System.IO.File]::ReadAllText($cfg)
        if ($raw.Trim()) { $obj = $raw | ConvertFrom-Json }
    }
    if (-not $obj.PSObject.Properties["mcpServers"]) { $obj | Add-Member -NotePropertyName mcpServers -NotePropertyValue ([pscustomobject]@{}) }
    $obj.mcpServers | Add-Member -NotePropertyName $name -NotePropertyValue ([pscustomobject]$server) -Force
    [System.IO.File]::WriteAllText($cfg, ($obj | ConvertTo-Json -Depth 32), $utf8)
    Write-Host "Claude Desktop: '$name' agora usa a VM ($cfg)" -ForegroundColor Green
}
$claude = Get-Command claude -ErrorAction SilentlyContinue
if ($claude) {
    $ErrorActionPreference = "Continue"
    try { & claude mcp remove --scope user $name *> $null } catch { }
    & claude mcp add --scope user $name -- $ssh -T -o BatchMode=yes $VmHost $remote
    Write-Host "Claude Code: '$name' agora usa a VM." -ForegroundColor Green
}
Write-Host "Feche e abra o Claude Desktop. Para voltar ao PC: INSTALAR-MCP.bat"
