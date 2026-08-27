[CmdletBinding()]
param(
  [string]$EnvFile = '',
  [string]$Name = ''
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'deployment\ChatBI.Deployment.ps1')
$projectRoot = Split-Path -Parent $PSScriptRoot
$resolvedEnv = Resolve-ChatBIEnvFile -EnvFile $EnvFile
Set-Location -LiteralPath $projectRoot

try {
  $configuration = Assert-ChatBIConfiguration -EnvFile $resolvedEnv
  if (-not $configuration.DatabaseUrl) { throw 'Backup requires an explicit CHATBI_DATABASE_URL.' }
  if (-not $Name) { $Name = 'chatbi-metadata-' + (Get-Date -Format 'yyyyMMdd-HHmmss') }
  if ($Name -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]+$') { throw 'Backup name contains unsupported characters' }
  $backupRoot = Resolve-ChatBIDataPath -Path $configuration.BackupRoot
  [void][IO.Directory]::CreateDirectory($backupRoot)
  $env:CHATBI_BACKUP_ROOT = $backupRoot
  $env:CHATBI_PGTOOLS_DATABASE_URL = ConvertTo-ChatBIPgToolsUrl -DatabaseUrl $configuration.DatabaseUrl
  $compose = Get-ChatBIComposeArguments -EnvFile $resolvedEnv -ProjectName $configuration.ProjectName
  $schemaArgument = if ($configuration.DatabaseSchema) { "--schema=$($configuration.DatabaseSchema)" } else { '' }
  $command = "pg_dump --format=custom --no-owner --no-acl $schemaArgument --file=/backups/$Name.dump `"`$CHATBI_PGTOOLS_DATABASE_URL`""
  & docker @compose --profile maintenance run --rm maintenance sh -c $command
  if ($LASTEXITCODE -ne 0) { throw 'pg_dump failed' }
  $dumpPath = Join-Path $backupRoot "$Name.dump"
  if (-not (Test-Path -LiteralPath $dumpPath) -or (Get-Item -LiteralPath $dumpPath).Length -eq 0) { throw 'Backup dump was not created' }

  $storage = Resolve-ChatBIDataPath -Path $configuration.StorageRoot
  $storageArchive = Join-Path $backupRoot "$Name.storage.zip"
  if ((Test-Path -LiteralPath $storage -PathType Container) -and (Get-ChildItem -LiteralPath $storage -Force | Select-Object -First 1)) {
    Compress-Archive -Path (Join-Path $storage '*') -DestinationPath $storageArchive -CompressionLevel Optimal -Force
  }
  $manifest = [ordered]@{
    format = 'chatbi-enterprise-backup-v1'
    created_at = (Get-Date).ToUniversalTime().ToString('o')
    dump_file = "$Name.dump"
    dump_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $dumpPath).Hash.ToLowerInvariant()
    database_schema = $configuration.DatabaseSchema
    storage_archive = if (Test-Path -LiteralPath $storageArchive) { "$Name.storage.zip" } else { $null }
    secrets_included = $false
  }
  $manifestPath = Join-Path $backupRoot "$Name.manifest.json"
  [IO.File]::WriteAllText($manifestPath, ($manifest | ConvertTo-Json -Depth 5), [Text.UTF8Encoding]::new($false))
  Write-Host 'BACKUP=PASS' -ForegroundColor Green
  Write-Host "BACKUP_NAME=$Name"
  Write-Host "BACKUP_ROOT=$backupRoot"
  exit 0
} catch {
  Write-Host 'BACKUP=FAIL' -ForegroundColor Red
  Write-Host $_.Exception.Message
  exit 1
} finally {
  Remove-Item Env:CHATBI_PGTOOLS_DATABASE_URL -ErrorAction SilentlyContinue
}
