# Registra o servidor MCP do CFO Central no Claude Desktop (e no Claude Code, se instalado).
# O servidor roda dentro do container do app: docker exec -i cfo-central-app-1 python -m app.assistant.mcp_server
$ErrorActionPreference = "Stop"
$name = "cfo-central"
$container = "cfo-central-app-1"

$docker = (Get-Command docker -ErrorAction SilentlyContinue).Source
if (-not $docker) { $docker = "C:\Program Files\Docker\Docker\resources\bin\docker.exe" }
if (-not (Test-Path $docker)) { Write-Host "Docker nao encontrado. Instale/abra o Docker Desktop." -ForegroundColor Red; exit 1 }

$state = & $docker inspect -f "{{.State.Running}}" $container 2>$null
if ($state -ne "true") { Write-Host "Aviso: o container $container nao esta rodando. Rode INICIAR.bat antes de usar." -ForegroundColor Yellow }

$server = [ordered]@{ command = $docker; args = @("exec", "-i", $container, "python", "-m", "app.assistant.mcp_server") }

$targets = @("$env:APPDATA\Claude")
Get-ChildItem "$env:LOCALAPPDATA\Packages" -Directory -Filter "Claude_*" -ErrorAction SilentlyContinue |
    ForEach-Object { $targets += (Join-Path $_.FullName "LocalCache\Roaming\Claude") }
$targets = $targets | Where-Object { Test-Path $_ }
if (-not $targets) { $targets = @("$env:APPDATA\Claude"); New-Item -ItemType Directory -Force $targets[0] | Out-Null }

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
    Write-Host "Claude Desktop: '$name' registrado em $cfg" -ForegroundColor Green
}

$claude = Get-Command claude -ErrorAction SilentlyContinue
if ($claude) {
    $ErrorActionPreference = "Continue"
    try { & claude mcp remove --scope user $name *> $null } catch { }
    & claude mcp add --scope user $name -- $docker exec -i $container python -m app.assistant.mcp_server
    Write-Host "Claude Code: '$name' registrado (escopo do usuario)." -ForegroundColor Green
}
Write-Host "Feche e abra o Claude Desktop para carregar as ferramentas do CFO Central."
