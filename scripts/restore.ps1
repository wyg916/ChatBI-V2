[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)][string]$Name,
  [string]$EnvFile = '',
  [string]$ProjectName = '',
  [switch]$RestoreStorage,
  [switch]$Force
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'deployment\ChatBI.Deployment.ps1')
$projectRoot = Split-Path -Parent $PSScriptRoot
$resolvedEnv = Resolve-ChatBIEnvFile -EnvFile $EnvFile
Set-Location -LiteralPath $projectRoot
$storageRestoreTarget = ''
$storageRestoreStaging = ''
$storageRestorePrevious = ''
$storageRestoreSwapped = $false
$storageRestoreHadPrevious = $false
$databaseRestoreCompleted = $false

function Get-ManagedSpreadsheetPreflight {
  param([Parameter(Mandatory = $true)][string[]]$ComposeArguments)
  $output = & docker @ComposeArguments run --rm --no-deps backend python -m app.db.deployment_state managed-spreadsheets
  if ($LASTEXITCODE -ne 0) { throw 'Unable to preflight current managed datasource state; rebuild the current Backend image first.' }
  $json = $output | Where-Object { ([string]$_).Trim().StartsWith('{') } | Select-Object -Last 1
  if (-not $json) { throw 'Managed datasource preflight was not returned' }
  return ([string]$json | ConvertFrom-Json)
}

try {
  $configuredValues = Read-ChatBIEnv -EnvFile $resolvedEnv
  $configuredProjectName = (Get-ChatBIValue -Values $configuredValues -Name 'COMPOSE_PROJECT_NAME' -Default 'chatbi-v2').ToLowerInvariant()
  if ($ProjectName -and $ProjectName.ToLowerInvariant() -eq 'chatbi-v2-showcase') {
    [void](Set-ChatBIShowcaseProcessEnvironment -EnvFile $resolvedEnv -ProviderMode Auto)
  }
  $configuration = Assert-ChatBIConfiguration -EnvFile $resolvedEnv
  $effectiveProjectName = if ($ProjectName) { $ProjectName.ToLowerInvariant() } else { $configuration.ProjectName }
  if ($effectiveProjectName -notmatch '^[a-z0-9][a-z0-9_-]*$') { throw 'ProjectName contains unsupported characters' }
  $env:COMPOSE_PROJECT_NAME = $effectiveProjectName
  if ($effectiveProjectName -eq 'chatbi-v2-showcase') {
    Assert-ChatBIShowcaseDatabaseTarget -Configuration $configuration
  }
  Assert-ChatBINoCompetingMetadataWriteStack `
    -EnvFile $resolvedEnv `
    -TargetProjectName $effectiveProjectName `
    -KnownProjectNames @('chatbi-v2-showcase', 'chatbi-v2', $configuredProjectName) `
    -Operation restore
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
  if ($manifest.format -eq 'chatbi-enterprise-backup-v2') {
    throw 'Backup manifest V2 belongs to an earlier release contract. Restore it with the source/tag that created it (published V1.3.1: chatbi-v2-v1.3.1); the current source accepts only V3.'
  }
  if ($manifest.format -ne 'chatbi-enterprise-backup-v3') {
    throw 'Unsupported backup manifest format; create a V3 backup with the current source.'
  }
  $actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $dumpPath).Hash.ToLowerInvariant()
  if ($actualHash -ne $manifest.dump_sha256) { throw 'Backup SHA-256 verification failed' }
  $expectedMetadataSchema = if ($configuration.DatabaseSchema) { $configuration.DatabaseSchema } else { 'public' }
  if ([string]$manifest.database_schema -ne [string]$expectedMetadataSchema) { throw 'Backup schema does not match the configured metadata schema' }
  $manifestCountProperties = @($manifest.metadata.counts.PSObject.Properties.Name)
  if ($manifestCountProperties -notcontains 'datasource_import' -or $manifestCountProperties -notcontains 'excel_datasource') {
    throw 'Backup manifest predates managed spreadsheet preflight; create a current backup before restore.'
  }
  if ([int]$manifest.metadata.counts.datasource_import -ne 0 -or [int]$manifest.metadata.counts.excel_datasource -ne 0) {
    throw 'Backup contains unsupported managed Excel/CSV datasources and cannot be restored safely.'
  }
  $compose = Get-ChatBIComposeArguments -EnvFile $resolvedEnv -ProjectName $effectiveProjectName
  $currentManaged = Get-ManagedSpreadsheetPreflight -ComposeArguments $compose
  if ([int]$currentManaged.datasource_import -ne 0 -or [int]$currentManaged.excel_datasource -ne 0) {
    throw 'Current deployment has managed Excel/CSV datasources; export and delete them through the Backend API before restore.'
  }

  if ($RestoreStorage) {
    if (-not $manifest.storage_archive) { throw 'RestoreStorage was requested but the backup has no storage archive.' }
    $archive = Join-Path $backupRoot ([string]$manifest.storage_archive)
    if (-not (Test-Path -LiteralPath $archive -PathType Leaf)) { throw 'Storage archive named by the manifest is missing' }
    if (-not $manifest.storage_sha256) { throw 'Storage archive checksum is missing from the manifest' }
    $actualStorageHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash.ToLowerInvariant()
    if ($actualStorageHash -ne $manifest.storage_sha256) { throw 'Storage archive SHA-256 verification failed' }
    $storageRestoreTarget = Assert-ChatBISafeStorageTarget -Path $configuration.StorageRoot -Values $configuration.Values -ProjectRoot $projectRoot
    $storageParent = Split-Path -Parent $storageRestoreTarget
    $storageLeaf = Split-Path -Leaf $storageRestoreTarget
    $restoreId = [Guid]::NewGuid().ToString('N')
    $storageRestoreStaging = Join-Path $storageParent ".${storageLeaf}.restore-staging-${restoreId}"
    $storageRestorePrevious = Join-Path $storageParent ".${storageLeaf}.restore-previous-${restoreId}"
    [void][IO.Directory]::CreateDirectory($storageRestoreStaging)
    Expand-Archive -LiteralPath $archive -DestinationPath $storageRestoreStaging -Force
  }

  & (Join-Path $PSScriptRoot 'stop.ps1') -EnvFile $resolvedEnv
  if ($LASTEXITCODE -ne 0) { throw 'Unable to stop the scoped Compose project' }
  $stoppedManaged = Get-ManagedSpreadsheetPreflight -ComposeArguments $compose
  if ([int]$stoppedManaged.datasource_import -ne 0 -or [int]$stoppedManaged.excel_datasource -ne 0) {
    throw 'A managed Excel/CSV datasource appeared during restore preflight; restore stopped before changing PostgreSQL.'
  }
  if ($RestoreStorage) {
    $storageRestoreHadPrevious = Test-Path -LiteralPath $storageRestoreTarget
    if ($storageRestoreHadPrevious) {
      Move-Item -LiteralPath $storageRestoreTarget -Destination $storageRestorePrevious
    }
    try {
      Move-Item -LiteralPath $storageRestoreStaging -Destination $storageRestoreTarget
      $storageRestoreSwapped = $true
      $storageRestoreStaging = ''
    } catch {
      if ($storageRestoreHadPrevious -and (Test-Path -LiteralPath $storageRestorePrevious) -and -not (Test-Path -LiteralPath $storageRestoreTarget)) {
        Move-Item -LiteralPath $storageRestorePrevious -Destination $storageRestoreTarget
      }
      throw
    }
  }
  $env:CHATBI_BACKUP_ROOT = $backupRoot
  $env:CHATBI_PGTOOLS_DATABASE_URL = ConvertTo-ChatBIPgToolsUrl -DatabaseUrl $configuration.DatabaseUrl
  $command = "pg_restore --clean --if-exists --no-owner --no-acl --exit-on-error --single-transaction --dbname=`"`$CHATBI_PGTOOLS_DATABASE_URL`" /backups/$Name.dump"
  & docker @compose --profile maintenance run --rm maintenance sh -c $command
  if ($LASTEXITCODE -ne 0) { throw 'pg_restore failed' }
  $databaseRestoreCompleted = $true
  # The restored fingerprint must be verified before any seed/bootstrap path is
  # allowed to mutate identities or governed settings.  The V3 contract already
  # requires the current migration head, so this check is intentionally read-only.
  & docker @compose run --rm --no-deps backend alembic current
  if ($LASTEXITCODE -ne 0) { throw 'Post-restore migration verification failed' }
  $snapshotOutput = & docker @compose run --rm --no-deps backend python -m app.db.deployment_state snapshot
  if ($LASTEXITCODE -ne 0) { throw 'Unable to verify restored deployment metadata' }
  $snapshotJson = $snapshotOutput | Where-Object { ([string]$_).Trim().StartsWith('{') } | Select-Object -Last 1
  if (-not $snapshotJson) { throw 'Restored deployment metadata snapshot was not returned' }
  $snapshot = [string]$snapshotJson | ConvertFrom-Json
  if ($snapshot.migration_head -ne '20260829_0015' -or $snapshot.migration_head -ne $manifest.migration_head) {
    throw "Restored migration head mismatch: expected=$($manifest.migration_head) actual=$($snapshot.migration_head)"
  }
  if ($snapshot.metadata_sha256 -ne $manifest.metadata.sha256) {
    throw 'Restored Settings/Provider/Invitation/RBAC/Workspace/Persistence fingerprint mismatch'
  }
  if ($storageRestoreSwapped -and (Test-Path -LiteralPath $storageRestorePrevious)) {
    Remove-Item -LiteralPath $storageRestorePrevious -Recurse -Force
    $storageRestorePrevious = ''
  }
  $storageRestoreSwapped = $false
  Write-Host 'RESTORE=PASS' -ForegroundColor Green
  Write-Host "RESTORED_BACKUP=$Name"
  Write-Host "MIGRATION_HEAD=$($snapshot.migration_head)"
  Write-Host 'RESTORED_METADATA=SETTINGS_PROVIDER_INVITATION_RBAC_WORKSPACE_PERSISTENCE_PASS'
  exit 0
} catch {
  if ($storageRestoreSwapped -and -not $databaseRestoreCompleted) {
    if (Test-Path -LiteralPath $storageRestoreTarget) {
      Remove-Item -LiteralPath $storageRestoreTarget -Recurse -Force
    }
    if ($storageRestoreHadPrevious -and (Test-Path -LiteralPath $storageRestorePrevious)) {
      Move-Item -LiteralPath $storageRestorePrevious -Destination $storageRestoreTarget
      $storageRestorePrevious = ''
    }
  } elseif (
    $storageRestoreSwapped -and $databaseRestoreCompleted -and $storageRestoreHadPrevious -and
    $storageRestorePrevious -and (Test-Path -LiteralPath $storageRestorePrevious)
  ) {
    Write-Host "RESTORE_STORAGE_PREVIOUS_RETAINED=$storageRestorePrevious" -ForegroundColor Yellow
  }
  Write-Host 'RESTORE=FAIL' -ForegroundColor Red
  Write-Host $_.Exception.Message
  exit 1
} finally {
  if ($storageRestoreStaging -and (Test-Path -LiteralPath $storageRestoreStaging)) {
    Remove-Item -LiteralPath $storageRestoreStaging -Recurse -Force
  }
  Remove-Item Env:CHATBI_PGTOOLS_DATABASE_URL -ErrorAction SilentlyContinue
}
