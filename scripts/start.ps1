param(
  [switch]$SkipBuild
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$backendPort = if($env:CHATBI_BACKEND_PORT) { $env:CHATBI_BACKEND_PORT } else { '8000' }
$frontendPort = if($env:CHATBI_FRONTEND_PORT) { $env:CHATBI_FRONTEND_PORT } else { '5173' }
$ragPort = if($env:CHATBI_RAG_PORT) { $env:CHATBI_RAG_PORT } else { '8001' }
$backendHealth = "http://127.0.0.1:${backendPort}/health"
$frontendHealth = "http://127.0.0.1:${frontendPort}/"
$ragHealth = "http://127.0.0.1:${ragPort}/health"

if (-not (Test-Path -LiteralPath (Join-Path $projectRoot '.env'))) {
  throw 'Missing local .env. Run scripts/bootstrap-local-databases.ps1 first.'
}
foreach ($port in 5432, 3306) {
  if (-not (Test-NetConnection -ComputerName '127.0.0.1' -Port $port -InformationLevel Quiet)) {
    throw "Required local database port $port is not reachable"
  }
}

$composeArgs = @('compose', 'up', '-d')
if (-not $SkipBuild) { $composeArgs += '--build' }
& docker @composeArgs
if ($LASTEXITCODE -ne 0) { throw 'docker compose up failed' }

$deadline = (Get-Date).AddMinutes(4)
do {
  try {
    $backend = Invoke-WebRequest -UseBasicParsing -Uri $backendHealth -TimeoutSec 3
    $frontend = Invoke-WebRequest -UseBasicParsing -Uri $frontendHealth -TimeoutSec 3
    $rag = Invoke-RestMethod -Uri $ragHealth -TimeoutSec 3
    if ($backend.StatusCode -eq 200 -and $frontend.StatusCode -eq 200 -and $rag.status -eq 'ok') { break }
  } catch {
    Start-Sleep -Seconds 3
  }
} while ((Get-Date) -lt $deadline)

if ((Get-Date) -ge $deadline) {
  docker compose ps
  throw 'ChatBI services did not become healthy before the deadline'
}

$seedScript = Join-Path $PSScriptRoot 'seed-demo.ps1'
if (Test-Path -LiteralPath $seedScript) { & $seedScript }
& (Join-Path $PSScriptRoot 'verify.ps1')
