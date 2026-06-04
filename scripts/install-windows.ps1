param(
    [string]$GameDir = $env:DISCO_ELYSIUM_GAME_DIR,
    [string]$Configuration = "Release"
)

if (-not $GameDir) {
    $GameDir = "D:\steam\steamapps\common\Disco Elysium"
}

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$Project = Join-Path $RepoRoot "src\DiscoElysiumBridge.csproj"
$PluginsDir = Join-Path $GameDir "BepInEx\plugins"
$Dll = Join-Path $RepoRoot "src\bin\$Configuration\net6.0\DiscoElysiumBridge.dll"

Write-Host "GameDir: $GameDir"
Write-Host "Project: $Project"

if (-not (Test-Path (Join-Path $GameDir "BepInEx"))) {
    throw "BepInEx directory not found under GameDir. Install BepInEx 6 IL2CPP first."
}

dotnet build $Project -c $Configuration -p:GameDir="$GameDir"

New-Item -ItemType Directory -Force -Path $PluginsDir | Out-Null
Copy-Item -Force $Dll (Join-Path $PluginsDir "DiscoElysiumBridge.dll")

Write-Host "Installed: $(Join-Path $PluginsDir 'DiscoElysiumBridge.dll')"
Write-Host "Start Disco Elysium, then test: curl --noproxy localhost http://localhost:7860/health"
