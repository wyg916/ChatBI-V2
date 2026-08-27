[CmdletBinding()]
param([string]$EnvFile = '')

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'deployment\ChatBI.Deployment.ps1')
$resolvedEnv = Resolve-ChatBIEnvFile -EnvFile $EnvFile

try {
  $configuration = Assert-ChatBIConfiguration -EnvFile $resolvedEnv
  if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw 'Docker CLI is not installed' }
  $compose = Get-ChatBIComposeArguments -EnvFile $resolvedEnv -ProjectName $configuration.ProjectName
  & docker @compose config --quiet
  if ($LASTEXITCODE -ne 0) { throw 'docker compose config rejected the deployment configuration' }
  Write-Host 'CONFIG_VALIDATION=PASS' -ForegroundColor Green
  Write-Host "COMPOSE_PROJECT_NAME=$($configuration.ProjectName)"
  Write-Host "DEPLOYMENT_MODE=$($configuration.DeploymentMode)"
  exit 0
} catch {
  Write-Host 'CONFIG_VALIDATION=FAIL' -ForegroundColor Red
  Write-Host $_.Exception.Message
  exit 1
}
