[CmdletBinding()]
param(
  [string]$EnvFile = '',
  [string]$Name = '',
  [string]$ProjectName = ''
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'deployment\ChatBI.Deployment.ps1')
$projectRoot = Split-Path -Parent $PSScriptRoot
$resolvedEnv = Resolve-ChatBIEnvFile -EnvFile $EnvFile
Set-Location -LiteralPath $projectRoot
$operationExitCode = 1
$resumeStack = $false
$effectiveProjectName = ''
$stagingPaths = @()
$publishedPaths = @()

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
    -Operation backup
  if (-not $configuration.DatabaseUrl) { throw 'Backup requires an explicit CHATBI_DATABASE_URL.' }
  if (-not $Name) { $Name = 'chatbi-metadata-' + (Get-Date -Format 'yyyyMMdd-HHmmss') }
  if ($Name -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]+$') { throw 'Backup name contains unsupported characters' }
  $backupRoot = Resolve-ChatBIDataPath -Path $configuration.BackupRoot
  [void][IO.Directory]::CreateDirectory($backupRoot)
  $dumpPath = Join-Path $backupRoot "$Name.dump"
  $storageArchive = Join-Path $backupRoot "$Name.storage.zip"
  $manifestPath = Join-Path $backupRoot "$Name.manifest.json"
  $existingArtifacts = @($dumpPath, $storageArchive, $manifestPath) | Where-Object { Test-Path -LiteralPath $_ }
  if ($existingArtifacts.Count -gt 0) {
    throw 'Backup name already exists; choose a new name so an existing recovery point is never overwritten.'
  }
  $stageId = [Guid]::NewGuid().ToString('N')
  $stagedDumpFile = ".${Name}.staging-${stageId}.dump"
  $stagedDumpPath = Join-Path $backupRoot $stagedDumpFile
  $stagedStorageArchive = Join-Path $backupRoot ".${Name}.staging-${stageId}.storage.zip"
  $stagedManifestPath = Join-Path $backupRoot ".${Name}.staging-${stageId}.manifest.json"
  $stagingPaths = @($stagedDumpPath, $stagedStorageArchive, $stagedManifestPath)
  $env:CHATBI_BACKUP_ROOT = $backupRoot
  $env:CHATBI_PGTOOLS_DATABASE_URL = ConvertTo-ChatBIPgToolsUrl -DatabaseUrl $configuration.DatabaseUrl
  $compose = Get-ChatBIComposeArguments -EnvFile $resolvedEnv -ProjectName $effectiveProjectName
  $serviceOutput = @(& docker @compose ps --services --filter status=running)
  if ($LASTEXITCODE -ne 0) { throw 'Unable to inspect the scoped Compose project before backup' }
  $runningServices = @(
    $serviceOutput | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) }
  )
  $resumeStack = $runningServices.Count -gt 0
  if ($resumeStack) {
    & (Join-Path $PSScriptRoot 'stop.ps1') -EnvFile $resolvedEnv
    if ($LASTEXITCODE -ne 0) { throw 'Unable to stop the scoped Compose project for a consistent backup' }
  }
  $snapshotOutput = & docker @compose run --rm --no-deps backend python -m app.db.deployment_state snapshot
  if ($LASTEXITCODE -ne 0) { throw 'Unable to read the sanitized deployment metadata snapshot' }
  $snapshotJson = $snapshotOutput | Where-Object { ([string]$_).Trim().StartsWith('{') } | Select-Object -Last 1
  if (-not $snapshotJson) { throw 'Deployment metadata snapshot was not returned' }
  $snapshot = [string]$snapshotJson | ConvertFrom-Json
  if ($snapshot.migration_head -ne '20260829_0014') {
    throw "Backup requires migration head 20260829_0014; actual=$($snapshot.migration_head)"
  }
  $countProperties = @($snapshot.counts.PSObject.Properties.Name)
  if ($countProperties -notcontains 'datasource_import' -or $countProperties -notcontains 'excel_datasource') {
    throw 'Backup runtime does not expose managed spreadsheet preflight; rebuild the current Backend image first.'
  }
  if ([int]$snapshot.counts.datasource_import -ne 0 -or [int]$snapshot.counts.excel_datasource -ne 0) {
    throw 'Managed Excel/CSV datasources are not covered by metadata backup; export and delete them through the Backend API before backup.'
  }
  $metadataSchema = if ($configuration.DatabaseSchema) { $configuration.DatabaseSchema } else { 'public' }
  $schemaArgument = "--schema=$metadataSchema"
  $command = "pg_dump --format=custom --no-owner --no-acl $schemaArgument --file=/backups/$stagedDumpFile `"`$CHATBI_PGTOOLS_DATABASE_URL`""
  & docker @compose --profile maintenance run --rm maintenance sh -c $command
  if ($LASTEXITCODE -ne 0) { throw 'pg_dump failed' }
  if (-not (Test-Path -LiteralPath $stagedDumpPath) -or (Get-Item -LiteralPath $stagedDumpPath).Length -eq 0) { throw 'Backup dump was not created' }

  $storage = Resolve-ChatBIDataPath -Path $configuration.StorageRoot
  if ((Test-Path -LiteralPath $storage -PathType Container) -and (Get-ChildItem -LiteralPath $storage -Force | Select-Object -First 1)) {
    Compress-Archive -Path (Join-Path $storage '*') -DestinationPath $stagedStorageArchive -CompressionLevel Optimal
  }
  $manifest = [ordered]@{
    format = 'chatbi-enterprise-backup-v3'
    created_at = (Get-Date).ToUniversalTime().ToString('o')
    dump_file = "$Name.dump"
    dump_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $stagedDumpPath).Hash.ToLowerInvariant()
    database_schema = $metadataSchema
    migration_head = $snapshot.migration_head
    candidate_version = $snapshot.candidate_version
    git_sha = $snapshot.git_sha
    metadata = [ordered]@{
      counts = $snapshot.counts
      sha256 = $snapshot.metadata_sha256
      covers = @('workspace', 'settings', 'provider_runtime', 'invitation', 'rbac', 'datasource', 'conversation', 'answer', 'dashboard')
    }
    storage_archive = if (Test-Path -LiteralPath $stagedStorageArchive) { "$Name.storage.zip" } else { $null }
    storage_sha256 = if (Test-Path -LiteralPath $stagedStorageArchive) { (Get-FileHash -Algorithm SHA256 -LiteralPath $stagedStorageArchive).Hash.ToLowerInvariant() } else { $null }
    secrets_included = $false
  }
  [IO.File]::WriteAllText($stagedManifestPath, ($manifest | ConvertTo-Json -Depth 5), [Text.UTF8Encoding]::new($false))

  # Publish the manifest last.  Restore cannot observe a partial recovery point,
  # and any failed publication removes only files created by this invocation.
  Move-Item -LiteralPath $stagedDumpPath -Destination $dumpPath
  $publishedPaths += $dumpPath
  if (Test-Path -LiteralPath $stagedStorageArchive) {
    Move-Item -LiteralPath $stagedStorageArchive -Destination $storageArchive
    $publishedPaths += $storageArchive
  }
  Move-Item -LiteralPath $stagedManifestPath -Destination $manifestPath
  $publishedPaths += $manifestPath
  Write-Host 'BACKUP=PASS' -ForegroundColor Green
  Write-Host "BACKUP_NAME=$Name"
  Write-Host "BACKUP_ROOT=$backupRoot"
  Write-Host "MIGRATION_HEAD=$($snapshot.migration_head)"
  Write-Host "METADATA_SHA256=$($snapshot.metadata_sha256)"
  $operationExitCode = 0
} catch {
  foreach ($path in $publishedPaths) {
    if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Force }
  }
  Write-Host 'BACKUP=FAIL' -ForegroundColor Red
  Write-Host $_.Exception.Message
} finally {
  foreach ($path in $stagingPaths) {
    if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Force }
  }
  Remove-Item Env:CHATBI_PGTOOLS_DATABASE_URL -ErrorAction SilentlyContinue
  if ($resumeStack) {
    if ($effectiveProjectName -eq 'chatbi-v2-showcase') {
      & (Join-Path $PSScriptRoot 'showcase.ps1') -Action Start -EnvFile $resolvedEnv -ProviderMode Auto -NoOpen
    } else {
      & (Join-Path $PSScriptRoot 'start.ps1') -EnvFile $resolvedEnv -SkipBuild -SkipBootstrap
    }
    if ($LASTEXITCODE -ne 0) {
      Write-Host 'BACKUP_STACK_RESUME=FAIL' -ForegroundColor Red
      $operationExitCode = 1
    } else {
      Write-Host 'BACKUP_STACK_RESUME=PASS' -ForegroundColor Green
    }
  }
}
exit $operationExitCode
