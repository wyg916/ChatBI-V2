[CmdletBinding()]
param([string]$EnvFile = '')

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'deployment\ChatBI.Deployment.ps1')
$projectRoot = Split-Path -Parent $PSScriptRoot
$resolvedEnv = Resolve-ChatBIEnvFile -EnvFile $EnvFile
Set-Location -LiteralPath $projectRoot

try {
  $configuration = Assert-ChatBIConfiguration -EnvFile $resolvedEnv
  $compose = Get-ChatBIComposeArguments -EnvFile $resolvedEnv -ProjectName $configuration.ProjectName
  & docker @compose down --remove-orphans
  if ($LASTEXITCODE -ne 0) { throw 'docker compose down failed' }
  Write-Host "STOP=PASS PROJECT=$($configuration.ProjectName)" -ForegroundColor Green
  exit 0
} catch {
  Write-Host 'STOP=FAIL' -ForegroundColor Red
  Write-Host $_.Exception.Message
  exit 1
}
