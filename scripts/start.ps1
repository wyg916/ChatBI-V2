[CmdletBinding()]
param(
  [string]$EnvFile = '',
  [switch]$SkipBuild,
  [switch]$SkipBootstrap
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'deployment\ChatBI.Deployment.ps1')
$projectRoot = Split-Path -Parent $PSScriptRoot
$resolvedEnv = Resolve-ChatBIEnvFile -EnvFile $EnvFile
Set-Location -LiteralPath $projectRoot

try {
  $bootstrapBuiltImages = $false
  if (-not $SkipBootstrap) {
    $bootstrapParameters = @{ EnvFile = $resolvedEnv }
    if ($SkipBuild) { $bootstrapParameters.SkipBuild = $true }
    & (Join-Path $PSScriptRoot 'bootstrap.ps1') @bootstrapParameters
    if ($LASTEXITCODE -ne 0) { throw 'Bootstrap prerequisite failed' }
    $bootstrapBuiltImages = -not $SkipBuild
  }
  $configuration = Assert-ChatBIConfiguration -EnvFile $resolvedEnv
  $backendHealth = "http://127.0.0.1:$($configuration.BackendPort)/health"
  $frontendHealth = "http://127.0.0.1:$($configuration.FrontendPort)/healthz"
  $ragHealth = "http://127.0.0.1:$($configuration.RagPort)/health"

  foreach ($probe in @(
    @($configuration.BackendPort, $backendHealth),
    @($configuration.FrontendPort, $frontendHealth),
    @($configuration.RagPort, $ragHealth)
  )) {
    if ((Test-ChatBIPortListening -Port $probe[0]) -and -not (Test-ChatBIUrl -Uri $probe[1])) {
      throw "Port $($probe[0]) is already used by another process. ACTION: Stop that process or change the corresponding CHATBI_*_PORT value."
    }
  }

  $compose = Get-ChatBIComposeArguments -EnvFile $resolvedEnv -ProjectName $configuration.ProjectName
  $up = @('up', '-d')
  if (-not $SkipBuild -and -not $bootstrapBuiltImages) { $up += '--build' }
  & docker @compose @up
  if ($LASTEXITCODE -ne 0) { throw 'docker compose up failed' }

  if (-not (Wait-ChatBIUrl -Uri $backendHealth)) { throw "Backend health timed out: $backendHealth" }
  if (-not (Wait-ChatBIUrl -Uri $ragHealth)) { throw "RAG health timed out: $ragHealth" }
  if (-not (Wait-ChatBIUrl -Uri $frontendHealth)) { throw "Frontend readiness timed out: $frontendHealth" }
  & (Join-Path $PSScriptRoot 'verify.ps1') -EnvFile $resolvedEnv
  if ($LASTEXITCODE -ne 0) { throw 'Post-start verification failed' }

  Write-Host '========================================' -ForegroundColor Green
  Write-Host 'ChatBI V2 Ready' -ForegroundColor Green
  Write-Host "Frontend: http://127.0.0.1:$($configuration.FrontendPort)/"
  Write-Host "Backend: http://127.0.0.1:$($configuration.BackendPort)/"
  Write-Host "RAG: http://127.0.0.1:$($configuration.RagPort)/"
  Write-Host "Deployment Mode: $($configuration.DeploymentMode)"
  Write-Host '========================================' -ForegroundColor Green
  Write-Host 'START=PASS'
  exit 0
} catch {
  Write-Host 'START=FAIL' -ForegroundColor Red
  Write-Host $_.Exception.Message
  try {
    if ($configuration) {
      $compose = Get-ChatBIComposeArguments -EnvFile $resolvedEnv -ProjectName $configuration.ProjectName
      & docker @compose ps
    }
  } catch { }
  exit 1
}
