$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
docker compose down
if ($LASTEXITCODE -ne 0) { throw 'docker compose down failed' }
