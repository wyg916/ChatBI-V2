[CmdletBinding()]
param(
  [string]$EnvFile = '',
  [switch]$Metadata,
  [switch]$Force
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'deployment\ChatBI.Deployment.ps1')
$projectRoot = Split-Path -Parent $PSScriptRoot
$resolvedEnv = Resolve-ChatBIEnvFile -EnvFile $EnvFile
Set-Location -LiteralPath $projectRoot

try {
  $configuration = Assert-ChatBIConfiguration -EnvFile $resolvedEnv
  if (-not $Force) {
    $answer = Read-Host 'DESTRUCTIVE_LOCAL_OPERATION. Type RESET to continue'
    if ($answer -ne 'RESET') { throw 'Reset cancelled; no data was changed' }
  }
  if ($Metadata) {
    $allow = Get-ChatBIValue -Values $configuration.Values -Name 'CHATBI_ALLOW_METADATA_RESET' -Default 'NO'
    if ($configuration.DeploymentMode -ne 'local' -or $allow -ne 'YES') {
      throw 'Metadata reset is denied. ACTION: Use local mode and explicitly set CHATBI_ALLOW_METADATA_RESET=YES for a disposable project-owned schema.'
    }
    if ($configuration.DatabaseSchema -notmatch '^chatbi_[a-zA-Z0-9_]+$' -or $configuration.DatabaseSchema -eq 'public') {
      throw 'Metadata reset requires an explicit project-owned CHATBI_DATABASE_SCHEMA beginning with chatbi_.'
    }
  }

  & (Join-Path $PSScriptRoot 'stop.ps1') -EnvFile $resolvedEnv
  if ($LASTEXITCODE -ne 0) { throw 'Unable to stop the scoped Compose project' }

  $storageFull = Assert-ChatBISafeStorageTarget -Path $configuration.StorageRoot -Values $configuration.Values -ProjectRoot $projectRoot
  if (Test-Path -LiteralPath $storageFull) { Remove-Item -LiteralPath $storageFull -Recurse -Force }
  [void][IO.Directory]::CreateDirectory($storageFull)

  if ($Metadata) {
    $compose = Get-ChatBIComposeArguments -EnvFile $resolvedEnv -ProjectName $configuration.ProjectName
    & docker @compose run --rm --no-deps backend alembic downgrade base
    if ($LASTEXITCODE -ne 0) { throw 'Metadata downgrade failed; stop and inspect the database before retrying' }
    & (Join-Path $PSScriptRoot 'bootstrap.ps1') -EnvFile $resolvedEnv -SkipBuild
    if ($LASTEXITCODE -ne 0) { throw 'Metadata reinitialization failed' }
  }
  Write-Host "RESET=PASS METADATA=$($Metadata.IsPresent)" -ForegroundColor Green
  exit 0
} catch {
  Write-Host 'RESET=FAIL' -ForegroundColor Red
  Write-Host $_.Exception.Message
  exit 1
}
