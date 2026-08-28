[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)][string]$Name,
  [string]$EnvFile = '',
  [switch]$RestoreStorage,
  [switch]$Force
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'deployment\ChatBI.Deployment.ps1')
$projectRoot = Split-Path -Parent $PSScriptRoot
$resolvedEnv = Resolve-ChatBIEnvFile -EnvFile $EnvFile
Set-Location -LiteralPath $projectRoot

try {
  $configuration = Assert-ChatBIConfiguration -EnvFile $resolvedEnv
  if (-not $configuration.DatabaseUrl) { throw 'Restore requires an explicit CHATBI_DATABASE_URL.' }
  if ($Name -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]+$') { throw 'Backup name contains unsupported characters' }
  if (-not $Force) {
    $answer = Read-Host 'DESTRUCTIVE_LOCAL_OPERATION. Type RESTORE to replace ChatBI metadata'
    if ($answer -ne 'RESTORE') { throw 'Restore cancelled; no data was changed' }
  }
  $backupRoot = Resolve-ChatBIDataPath -Path $configuration.BackupRoot
  $dumpPath = Join-Path $backupRoot "$Name.dump"
  $manifestPath = Join-Path $backupRoot "$Name.manifest.json"
  if (-not (Test-Path -LiteralPath $dumpPath) -or -not (Test-Path -LiteralPath $manifestPath)) { throw 'Backup dump or manifest is missing' }
  $manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
  if ($manifest.format -ne 'chatbi-enterprise-backup-v2') { throw 'Unsupported backup manifest format; create a V2 candidate backup first' }
  $actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $dumpPath).Hash.ToLowerInvariant()
  if ($actualHash -ne $manifest.dump_sha256) { throw 'Backup SHA-256 verification failed' }
  if ([string]$manifest.database_schema -ne [string]$configuration.DatabaseSchema) { throw 'Backup schema does not match CHATBI_DATABASE_SCHEMA' }

  & (Join-Path $PSScriptRoot 'stop.ps1') -EnvFile $resolvedEnv
  if ($LASTEXITCODE -ne 0) { throw 'Unable to stop the scoped Compose project' }
  $env:CHATBI_BACKUP_ROOT = $backupRoot
  $env:CHATBI_PGTOOLS_DATABASE_URL = ConvertTo-ChatBIPgToolsUrl -DatabaseUrl $configuration.DatabaseUrl
  $compose = Get-ChatBIComposeArguments -EnvFile $resolvedEnv -ProjectName $configuration.ProjectName
  $command = "pg_restore --clean --if-exists --no-owner --no-acl --exit-on-error --dbname=`"`$CHATBI_PGTOOLS_DATABASE_URL`" /backups/$Name.dump"
  & docker @compose --profile maintenance run --rm maintenance sh -c $command
  if ($LASTEXITCODE -ne 0) { throw 'pg_restore failed' }

  if ($RestoreStorage -and $manifest.storage_archive) {
    $archive = Join-Path $backupRoot ([string]$manifest.storage_archive)
    if (-not (Test-Path -LiteralPath $archive)) { throw 'Storage archive named by the manifest is missing' }
    $storage = Resolve-ChatBIDataPath -Path $configuration.StorageRoot
    if (Test-Path -LiteralPath $storage) { Remove-Item -LiteralPath $storage -Recurse -Force }
    [void][IO.Directory]::CreateDirectory($storage)
    Expand-Archive -LiteralPath $archive -DestinationPath $storage -Force
  }
  & (Join-Path $PSScriptRoot 'bootstrap.ps1') -EnvFile $resolvedEnv -SkipBuild
  if ($LASTEXITCODE -ne 0) { throw 'Post-restore migration/bootstrap verification failed' }
  $snapshotOutput = & docker @compose run --rm --no-deps backend python -m app.db.deployment_state snapshot
  if ($LASTEXITCODE -ne 0) { throw 'Unable to verify restored deployment metadata' }
  $snapshotJson = $snapshotOutput | Where-Object { ([string]$_).Trim().StartsWith('{') } | Select-Object -Last 1
  if (-not $snapshotJson) { throw 'Restored deployment metadata snapshot was not returned' }
  $snapshot = [string]$snapshotJson | ConvertFrom-Json
  if ($snapshot.migration_head -ne '20260828_0013' -or $snapshot.migration_head -ne $manifest.migration_head) {
    throw "Restored migration head mismatch: expected=$($manifest.migration_head) actual=$($snapshot.migration_head)"
  }
  if ($snapshot.metadata_sha256 -ne $manifest.metadata.sha256) {
    throw 'Restored Settings/Provider/Invitation/RBAC/Workspace/Persistence fingerprint mismatch'
  }
  Write-Host 'RESTORE=PASS' -ForegroundColor Green
  Write-Host "RESTORED_BACKUP=$Name"
  Write-Host "MIGRATION_HEAD=$($snapshot.migration_head)"
  Write-Host 'RESTORED_METADATA=SETTINGS_PROVIDER_INVITATION_RBAC_WORKSPACE_PERSISTENCE_PASS'
  exit 0
} catch {
  Write-Host 'RESTORE=FAIL' -ForegroundColor Red
  Write-Host $_.Exception.Message
  exit 1
} finally {
  Remove-Item Env:CHATBI_PGTOOLS_DATABASE_URL -ErrorAction SilentlyContinue
}
