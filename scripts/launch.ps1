[CmdletBinding()]
param(
  [switch]$NoOpen,
  [switch]$SkipBuild,
  [string]$EnvFile = ''
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'deployment\ChatBI.Deployment.ps1')
$resolvedEnv = Resolve-ChatBIEnvFile -EnvFile $EnvFile
$configuration = Assert-ChatBIConfiguration -EnvFile $resolvedEnv
$frontendUrl = "http://127.0.0.1:$($configuration.FrontendPort)/"
$apiDocsUrl = "http://127.0.0.1:$($configuration.BackendPort)/docs"

function Write-Stage {
  param([string]$Message)
  Write-Host "[ChatBI V2] $Message" -ForegroundColor Cyan
}

try {
  Set-Location -LiteralPath $projectRoot

  if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'Docker CLI was not found. Install and start Docker Desktop, then try again.'
  }

  Write-Stage 'Checking Docker Desktop...'
  & docker info *> $null
  if ($LASTEXITCODE -ne 0) {
    throw 'Docker Desktop is not ready. Start Docker Desktop, wait for it to finish loading, then try again.'
  }

  Write-Stage 'Starting Backend, governed RAG Runtime, and Frontend...'
  $startScript = Join-Path $PSScriptRoot 'start.ps1'
  if ($SkipBuild) {
    & $startScript -SkipBuild -EnvFile $resolvedEnv
  } else {
    & $startScript -EnvFile $resolvedEnv
  }

  $version = Invoke-RestMethod -Uri "http://127.0.0.1:$($configuration.BackendPort)/api/v1/version" -TimeoutSec 5
  $frontend = Invoke-WebRequest -UseBasicParsing -Uri $frontendUrl -TimeoutSec 5
  if ($frontend.StatusCode -ne 200) {
    throw "Frontend health check returned HTTP $($frontend.StatusCode)."
  }

  Write-Host ''
  Write-Host 'ChatBI V2 is ready.' -ForegroundColor Green
  Write-Host "Frontend : $frontendUrl"
  Write-Host "API docs : $apiDocsUrl"
  Write-Host "Version  : $($version.version)"

  if (-not $NoOpen) {
    Write-Stage 'Opening ChatBI in your default browser...'
    Start-Process -FilePath $frontendUrl
  }

  exit 0
} catch {
  Write-Host ''
  Write-Host 'ChatBI V2 startup failed.' -ForegroundColor Red
  Write-Host $_.Exception.Message -ForegroundColor Yellow
  Write-Host 'No files were reset or committed. Fix the issue above and run the launcher again.'
  exit 1
}
