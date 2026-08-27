$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
docker compose down --remove-orphans
if ($LASTEXITCODE -ne 0) { throw 'docker compose down failed' }
