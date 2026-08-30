Set-StrictMode -Version Latest

$script:ChatBIProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)

function Resolve-ChatBIEnvFile {
  param([string]$EnvFile)
  if ([string]::IsNullOrWhiteSpace($EnvFile)) {
    return [IO.Path]::GetFullPath((Join-Path $script:ChatBIProjectRoot '.env'))
  }
  if ([IO.Path]::IsPathRooted($EnvFile)) { return [IO.Path]::GetFullPath($EnvFile) }
  return [IO.Path]::GetFullPath((Join-Path $script:ChatBIProjectRoot $EnvFile))
}

function Read-ChatBIEnv {
  param([Parameter(Mandatory = $true)][string]$EnvFile)
  if (-not (Test-Path -LiteralPath $EnvFile -PathType Leaf)) {
    throw "Environment file not found: $EnvFile`nACTION: Copy .env.example to .env and configure the required PostgreSQL connection."
  }
  $values = [ordered]@{}
  $lineNumber = 0
  foreach ($rawLine in [IO.File]::ReadAllLines($EnvFile)) {
    $lineNumber++
    $line = $rawLine.Trim()
    if (-not $line -or $line.StartsWith('#')) { continue }
    if ($line -notmatch '^([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
      throw "Malformed environment entry at ${EnvFile}:$lineNumber`nACTION: Use NAME=value with no leading 'export'."
    }
    $name = $matches[1]
    $value = $matches[2].Trim()
    if ($value.Length -ge 2 -and (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'")))) {
      $value = $value.Substring(1, $value.Length - 2)
    }
    if ($values.Contains($name)) {
      throw "Duplicate environment key $name at ${EnvFile}:$lineNumber`nACTION: Keep exactly one definition for each key."
    }
    $values[$name] = $value
  }
  return $values
}

function Get-ChatBIValue {
  param(
    [Parameter(Mandatory = $true)][System.Collections.IDictionary]$Values,
    [Parameter(Mandatory = $true)][string]$Name,
    [string]$Default = ''
  )
  $processValue = [Environment]::GetEnvironmentVariable($Name, 'Process')
  if (-not [string]::IsNullOrWhiteSpace($processValue)) { return $processValue }
  if ($Values.Contains($Name)) { return [string]$Values[$Name] }
  return $Default
}

function Import-ChatBIProcessEnvironment {
  param([Parameter(Mandatory = $true)][System.Collections.IDictionary]$Values)
  foreach ($entry in $Values.GetEnumerator()) {
    $name = [string]$entry.Key
    $explicitProcessValue = [Environment]::GetEnvironmentVariable($name, 'Process')
    if ([string]::IsNullOrWhiteSpace($explicitProcessValue)) {
      [Environment]::SetEnvironmentVariable($name, [string]$entry.Value, 'Process')
    }
  }
}

function Test-ChatBIPlaceholder {
  param([AllowEmptyString()][string]$Value)
  if ([string]::IsNullOrWhiteSpace($Value)) { return $true }
  return $Value -match '^(<.*>|CHANGE_ME.*|REPLACE_ME.*|GENERATED_LOCAL_.*)$'
}

function Set-ChatBIShowcaseProcessEnvironment {
  param(
    [Parameter(Mandatory = $true)][string]$EnvFile,
    [ValidateSet('Auto', 'Live', 'Deterministic')][string]$ProviderMode = 'Auto',
    [string]$BackendImage = '',
    [string]$FrontendImage = '',
    [string]$SandboxImage = ''
  )
  $modeValues = Read-ChatBIEnv -EnvFile $EnvFile
  $frontendPort = '15173'
  $backendPort = '18080'
  $ragPort = '18081'
  $env:COMPOSE_PROJECT_NAME = 'chatbi-v2-showcase'
  $env:CHATBI_BIND_HOST = '127.0.0.1'
  $env:CHATBI_DEPLOYMENT_MODE = 'showcase'
  $env:CHATBI_ENVIRONMENT = 'development'
  $env:CHATBI_FRONTEND_PORT = $frontendPort
  $env:CHATBI_BACKEND_PORT = $backendPort
  $env:CHATBI_RAG_PORT = $ragPort
  $env:CHATBI_CORS_ALLOW_ORIGINS = "http://localhost:$frontendPort,http://127.0.0.1:$frontendPort"

  $configuredProviders = @()
  foreach ($provider in @(
    @{ Name = 'mimo'; Key = 'CHATBI_MIMO_API_KEY' },
    @{ Name = 'deepseek'; Key = 'CHATBI_DEEPSEEK_API_KEY' },
    @{ Name = 'kimi'; Key = 'CHATBI_KIMI_API_KEY' }
  )) {
    $credential = Get-ChatBIValue -Values $modeValues -Name $provider.Key
    if (-not (Test-ChatBIPlaceholder -Value $credential)) { $configuredProviders += $provider.Name }
  }
  $useLiveProviders = $ProviderMode -eq 'Live' -or ($ProviderMode -eq 'Auto' -and $configuredProviders.Count -gt 0)
  if ($ProviderMode -eq 'Live' -and $configuredProviders.Count -eq 0) {
    throw 'Live Provider mode requires at least one configured MiMo, DeepSeek, or Kimi credential in the selected EnvFile.'
  }
  if ($useLiveProviders) {
    $env:CHATBI_MODEL_PROVIDER = 'auto'
    $env:CHATBI_GENERAL_MODEL_PROVIDER = 'auto'
    $env:CHATBI_VISION_MODEL_PROVIDER = 'auto'
    $env:CHATBI_MODEL_BUDGET_MODE = 'quality'
    $env:CHATBI_TEST_COST_CONTROL = 'NO'
    $env:CHATBI_TEST_EXECUTION_LEVEL = 'FINAL'
    $env:CHATBI_PAID_GATE_AUTHORIZED = 'YES'
    $env:CHATBI_LEVEL0_PAID_EXCEPTION = 'YES'
    $env:CHATBI_PROVIDER_USAGE_UNRESTRICTED = 'true'
    # Real provider fallbacks can legitimately cross the deterministic 30 s
    # budget. Keep a finite hard deadline, but give the fixed five-role flow
    # enough time to finish one governed SQL/verification/presentation chain.
    $env:CHATBI_AGENT_TIMEOUT_MS = '120000'
    $runtimeMode = "live providers ($($configuredProviders -join ', ')); automatic capability routing; test cost control disabled"
  } else {
    $env:CHATBI_MODEL_PROVIDER = 'deterministic'
    $env:CHATBI_GENERAL_MODEL_PROVIDER = 'deterministic'
    $env:CHATBI_VISION_MODEL_PROVIDER = 'deterministic'
    $env:CHATBI_MODEL_BUDGET_MODE = 'balanced'
    $env:CHATBI_TEST_COST_CONTROL = 'YES'
    $env:CHATBI_TEST_EXECUTION_LEVEL = 'LEVEL0'
    $env:CHATBI_PAID_GATE_AUTHORIZED = 'NO'
    $env:CHATBI_LEVEL0_PAID_EXCEPTION = 'NO'
    $env:CHATBI_PROVIDER_USAGE_UNRESTRICTED = 'false'
    $env:CHATBI_AGENT_TIMEOUT_MS = '30000'
    $runtimeMode = 'deterministic / LEVEL0 / no paid provider calls'
  }
  $env:CHATBI_SEED_DEMO_SEMANTIC_MODEL = 'true'
  $env:CHATBI_BACKEND_IMAGE = if ($BackendImage) { $BackendImage } else { 'chatbi-v2-backend:latest' }
  $env:CHATBI_FRONTEND_IMAGE = if ($FrontendImage) { $FrontendImage } else { 'chatbi-v2-frontend:latest' }
  $env:CHATBI_SANDBOX_IMAGE = if ($SandboxImage) { $SandboxImage } else { 'chatbi-sandbox-runtime:phase3' }
  $env:CHATBI_STORAGE_ROOT = './.chatbi/showcase-storage'
  $env:CHATBI_BACKUP_ROOT = './.chatbi/showcase-backups'
  $gitSha = (& git -C $script:ChatBIProjectRoot rev-parse HEAD).Trim()
  if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($gitSha)) {
    throw 'Unable to resolve the local Showcase Git identity.'
  }
  $env:CHATBI_GIT_SHA = $gitSha
  $env:CHATBI_RELEASE_VERSION = 'v1.3.1'
  $env:CHATBI_FRONTEND_BUILD = 'production'
  if ([string]::IsNullOrWhiteSpace($env:CHATBI_SHOWCASE_DATABASE_NAME)) {
    $env:CHATBI_SHOWCASE_DATABASE_NAME = 'chatbi_v2'
  }
  if ([string]::IsNullOrWhiteSpace($env:CHATBI_DATABASE_URL)) {
    $metaPassword = Get-ChatBIValue -Values $modeValues -Name 'CHATBI_META_PASSWORD'
    if (Test-ChatBIPlaceholder -Value $metaPassword) {
      throw 'Local Showcase requires CHATBI_DATABASE_URL or CHATBI_META_PASSWORD in the selected EnvFile.'
    }
    $encodedMetaPassword = [uri]::EscapeDataString($metaPassword)
    $env:CHATBI_DATABASE_URL = "postgresql+psycopg://chatbi_app:${encodedMetaPassword}@host.docker.internal:5432/$env:CHATBI_SHOWCASE_DATABASE_NAME"
  }
  $env:CHATBI_BOOTSTRAP_ADMIN_PASSWORD = 'ChatBI-Showcase-2026!'
  $env:CHATBI_BOOTSTRAP_ANALYST_PASSWORD = 'ChatBI-Analyst-2026!'
  return [pscustomobject]@{
    RuntimeMode = $runtimeMode
    ConfiguredProviders = @($configuredProviders)
  }
}

function New-ChatBISecret {
  param([int]$Bytes = 36)
  $buffer = New-Object byte[] $Bytes
  $generator = [Security.Cryptography.RandomNumberGenerator]::Create()
  try { $generator.GetBytes($buffer) } finally { $generator.Dispose() }
  return [Convert]::ToBase64String($buffer).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

function Set-ChatBIEnvValues {
  param(
    [Parameter(Mandatory = $true)][string]$EnvFile,
    [Parameter(Mandatory = $true)][System.Collections.IDictionary]$Updates
  )
  $lines = [Collections.Generic.List[string]]::new()
  $seen = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
  foreach ($line in [IO.File]::ReadAllLines($EnvFile)) {
    if ($line -match '^([A-Za-z_][A-Za-z0-9_]*)=') {
      $name = $matches[1]
      if ($Updates.Contains($name)) {
        $lines.Add("$name=$($Updates[$name])")
        [void]$seen.Add($name)
        continue
      }
    }
    $lines.Add($line)
  }
  foreach ($entry in $Updates.GetEnumerator()) {
    if (-not $seen.Contains([string]$entry.Key)) { $lines.Add("$($entry.Key)=$($entry.Value)") }
  }
  $temporary = "$EnvFile.$([Guid]::NewGuid().ToString('N')).tmp"
  [IO.File]::WriteAllText($temporary, (($lines -join [Environment]::NewLine) + [Environment]::NewLine), [Text.UTF8Encoding]::new($false))
  Move-Item -LiteralPath $temporary -Destination $EnvFile -Force
}

function Initialize-ChatBISecrets {
  param([Parameter(Mandatory = $true)][string]$EnvFile)
  $values = Read-ChatBIEnv -EnvFile $EnvFile
  $updates = [ordered]@{}
  foreach ($name in @(
    'CHATBI_DATASOURCE_SECRET_KEY',
    'CHATBI_RAG_SHARED_SECRET',
    'CHATBI_BOOTSTRAP_ADMIN_PASSWORD',
    'CHATBI_BOOTSTRAP_ANALYST_PASSWORD'
  )) {
    if (Test-ChatBIPlaceholder -Value (Get-ChatBIValue -Values $values -Name $name)) {
      $updates[$name] = New-ChatBISecret
    }
  }
  if ($updates.Count -gt 0) {
    Set-ChatBIEnvValues -EnvFile $EnvFile -Updates $updates
    Write-Host "CONFIG_SECRETS_GENERATED=$($updates.Count)" -ForegroundColor Yellow
    Write-Host "ACTION: Protect $EnvFile and do not commit or share it."
  } else {
    Write-Host 'CONFIG_SECRETS_GENERATED=0'
  }
}

function Assert-ChatBIConfiguration {
  param([Parameter(Mandatory = $true)][string]$EnvFile)
  $values = Read-ChatBIEnv -EnvFile $EnvFile
  Import-ChatBIProcessEnvironment -Values $values
  $errors = [Collections.Generic.List[string]]::new()

  $secretMinimums = [ordered]@{
    CHATBI_DATASOURCE_SECRET_KEY = 32
    CHATBI_RAG_SHARED_SECRET = 32
    CHATBI_BOOTSTRAP_ADMIN_PASSWORD = 12
    CHATBI_BOOTSTRAP_ANALYST_PASSWORD = 12
  }
  foreach ($entry in $secretMinimums.GetEnumerator()) {
    $name = [string]$entry.Key
    $secretValue = Get-ChatBIValue -Values $values -Name $name
    if (Test-ChatBIPlaceholder -Value $secretValue) {
      $errors.Add("$name is missing or still a placeholder")
    } elseif ($secretValue.Length -lt [int]$entry.Value) {
      $errors.Add("$name must contain at least $($entry.Value) characters")
    }
  }

  $databaseUrl = Get-ChatBIValue -Values $values -Name 'CHATBI_DATABASE_URL'
  $metaPassword = Get-ChatBIValue -Values $values -Name 'CHATBI_META_PASSWORD'
  if (Test-ChatBIPlaceholder -Value $databaseUrl) {
    if (Test-ChatBIPlaceholder -Value $metaPassword) {
      $errors.Add('CHATBI_DATABASE_URL is required for enterprise deployment (or CHATBI_META_PASSWORD for the legacy local default)')
    }
  } elseif ($databaseUrl -notmatch '^postgresql\+psycopg://') {
    $errors.Add('CHATBI_DATABASE_URL must use postgresql+psycopg://')
  } elseif ($databaseUrl -match 'postgresql\+psycopg://[^/]*(localhost|127\.0\.0\.1)') {
    $errors.Add('CHATBI_DATABASE_URL cannot use localhost from Docker; use host.docker.internal or a reachable database hostname')
  }
  $databaseSchema = Get-ChatBIValue -Values $values -Name 'CHATBI_DATABASE_SCHEMA'
  if ($databaseSchema -and $databaseSchema -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') {
    $errors.Add('CHATBI_DATABASE_SCHEMA must be one unquoted PostgreSQL identifier')
  }

  $ports = [ordered]@{}
  foreach ($entry in @(
    @('CHATBI_FRONTEND_PORT', '5173'),
    @('CHATBI_BACKEND_PORT', '8000'),
    @('CHATBI_RAG_PORT', '8001')
  )) {
    $raw = Get-ChatBIValue -Values $values -Name $entry[0] -Default $entry[1]
    $port = 0
    if (-not [int]::TryParse($raw, [ref]$port) -or $port -lt 1 -or $port -gt 65535) {
      $errors.Add("$($entry[0]) must be an integer from 1 to 65535")
    } else { $ports[$entry[0]] = $port }
  }
  if (($ports.Values | Select-Object -Unique).Count -ne $ports.Count) {
    $errors.Add('Frontend, Backend, and RAG ports must be distinct')
  }

  foreach ($name in @('CHATBI_KIMI_BASE_URL', 'CHATBI_MIMO_BASE_URL', 'CHATBI_DEEPSEEK_BASE_URL')) {
    $value = Get-ChatBIValue -Values $values -Name $name
    if ($value -and $value -notmatch '^https?://[^\s]+$') { $errors.Add("$name must be an absolute HTTP(S) URL") }
  }

  $demoSeed = (Get-ChatBIValue -Values $values -Name 'CHATBI_SEED_DEMO_SEMANTIC_MODEL' -Default 'false').ToLowerInvariant()
  if ($demoSeed -notin @('true', 'false')) { $errors.Add('CHATBI_SEED_DEMO_SEMANTIC_MODEL must be true or false') }
  if ($demoSeed -eq 'true') {
    foreach ($name in @('CHATBI_DEMO_POSTGRES_PASSWORD', 'CHATBI_DEMO_MYSQL_PASSWORD')) {
      if (Test-ChatBIPlaceholder -Value (Get-ChatBIValue -Values $values -Name $name)) {
        $errors.Add("$name is required when Demo Seed is enabled")
      }
    }
  }

  $projectName = (Get-ChatBIValue -Values $values -Name 'COMPOSE_PROJECT_NAME' -Default 'chatbi-v2').ToLowerInvariant()
  if ($projectName -notmatch '^[a-z0-9][a-z0-9_-]+$') {
    $errors.Add('COMPOSE_PROJECT_NAME must contain only lowercase letters, digits, underscore, or hyphen')
  }
  if ($errors.Count -gt 0) {
    throw "CONFIG_VALIDATION=FAIL`n$($errors | ForEach-Object { "- $_" } | Out-String)ACTION: Correct the environment file and rerun scripts/config.ps1."
  }
  return [pscustomobject]@{
    Values = $values
    ProjectName = $projectName
    FrontendPort = $ports['CHATBI_FRONTEND_PORT']
    BackendPort = $ports['CHATBI_BACKEND_PORT']
    RagPort = $ports['CHATBI_RAG_PORT']
    DeploymentMode = Get-ChatBIValue -Values $values -Name 'CHATBI_DEPLOYMENT_MODE' -Default 'local'
    DatabaseUrl = $databaseUrl
    DatabaseSchema = $databaseSchema
    StorageRoot = Get-ChatBIValue -Values $values -Name 'CHATBI_STORAGE_ROOT' -Default './.chatbi/storage'
    BackupRoot = Get-ChatBIValue -Values $values -Name 'CHATBI_BACKUP_ROOT' -Default './.chatbi/backups'
    DemoSeed = ($demoSeed -eq 'true')
  }
}

function Get-ChatBIComposeArguments {
  param(
    [Parameter(Mandatory = $true)][string]$EnvFile,
    [Parameter(Mandatory = $true)][string]$ProjectName
  )
  return @('compose', '--env-file', $EnvFile, '--project-name', $ProjectName)
}

function Assert-ChatBINoCompetingMetadataWriteStack {
  param(
    [Parameter(Mandatory = $true)][string]$EnvFile,
    [Parameter(Mandatory = $true)][string]$TargetProjectName,
    [Parameter(Mandatory = $true)][string[]]$KnownProjectNames,
    [Parameter(Mandatory = $true)][ValidateSet('backup', 'restore')][string]$Operation
  )
  $target = $TargetProjectName.ToLowerInvariant()
  $candidates = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
  foreach ($projectName in $KnownProjectNames) {
    $candidate = ([string]$projectName).Trim().ToLowerInvariant()
    if (-not $candidate -or $candidate -eq $target) { continue }
    if ($candidate -notmatch '^[a-z0-9][a-z0-9_-]*$') {
      throw "Known Compose project name contains unsupported characters: $candidate"
    }
    [void]$candidates.Add($candidate)
  }
  foreach ($candidate in $candidates) {
    $candidateCompose = Get-ChatBIComposeArguments -EnvFile $EnvFile -ProjectName $candidate
    $serviceOutput = @(& docker @candidateCompose ps --services --filter status=running)
    if ($LASTEXITCODE -ne 0) {
      throw "Unable to inspect competing Compose project '$candidate' before $Operation"
    }
    $runningServices = @(
      $serviceOutput | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) }
    )
    if ($runningServices.Count -gt 0) {
      throw (
        "COMPETING_METADATA_WRITER=$candidate. Refusing $Operation because another canonical ChatBI " +
        "Compose project may be writing the selected metadata database. Stop that project explicitly; " +
        "this command will not stop it automatically."
      )
    }
  }
}

function Resolve-ChatBIDataPath {
  param([Parameter(Mandatory = $true)][string]$Path)
  if ([IO.Path]::IsPathRooted($Path)) { return [IO.Path]::GetFullPath($Path) }
  return [IO.Path]::GetFullPath((Join-Path $script:ChatBIProjectRoot $Path))
}

function Assert-ChatBISafeStorageTarget {
  param(
    [Parameter(Mandatory = $true)][string]$Path,
    [Parameter(Mandatory = $true)][System.Collections.IDictionary]$Values,
    [string]$ProjectRoot = $script:ChatBIProjectRoot
  )
  $trimCharacters = [char[]]@('\', '/')
  $projectFull = [IO.Path]::GetFullPath($ProjectRoot).TrimEnd($trimCharacters)
  $storageFull = Resolve-ChatBIDataPath -Path $Path
  $storageFull = [IO.Path]::GetFullPath($storageFull).TrimEnd($trimCharacters)
  $rootPath = [IO.Path]::GetPathRoot($storageFull).TrimEnd($trimCharacters)
  if ([string]::IsNullOrWhiteSpace($storageFull) -or $storageFull -eq $projectFull -or $storageFull -eq $rootPath) {
    throw 'Unsafe storage target was rejected'
  }
  $projectPrefix = $projectFull + [IO.Path]::DirectorySeparatorChar
  if (-not $storageFull.StartsWith($projectPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    $allowExternal = Get-ChatBIValue -Values $Values -Name 'CHATBI_ALLOW_EXTERNAL_STORAGE_RESET' -Default 'NO'
    if ($allowExternal -ne 'YES') {
      throw 'External storage replacement is denied unless CHATBI_ALLOW_EXTERNAL_STORAGE_RESET=YES.'
    }
  }
  return $storageFull
}

function Assert-ChatBIShowcaseDatabaseTarget {
  param(
    [Parameter(Mandatory = $true)]$Configuration,
    [string]$ExpectedDatabaseName = 'chatbi_v2'
  )
  $databaseUrl = [string]$Configuration.DatabaseUrl
  if ($databaseUrl -notmatch '^postgresql\+psycopg://(?:[^@/]+@)?([^/:?]+)(?::(\d+))?/([^?]+)(?:\?.*)?$') {
    throw 'Local Showcase database URL could not be validated.'
  }
  $hostName = $matches[1].ToLowerInvariant()
  $port = if ($matches[2]) { [int]$matches[2] } else { 5432 }
  $databaseName = [uri]::UnescapeDataString($matches[3])
  if ($hostName -ne 'host.docker.internal' -or $port -ne 5432 -or $databaseName -ne $ExpectedDatabaseName) {
    throw "Local Showcase refused a non-local metadata target. ACTION: Remove inherited CHATBI_DATABASE_URL and use the project .env local chatbi_v2 connection."
  }
}

function Test-ChatBIUrl {
  param([Parameter(Mandatory = $true)][string]$Uri, [int]$TimeoutSec = 2)
  try {
    $response = Invoke-WebRequest -UseBasicParsing -Uri $Uri -TimeoutSec $TimeoutSec
    return $response.StatusCode -ge 200 -and $response.StatusCode -lt 400
  } catch { return $false }
}

function Wait-ChatBIUrl {
  param(
    [Parameter(Mandatory = $true)][string]$Uri,
    [int]$TimeoutSeconds = 240,
    [int]$IntervalSeconds = 3
  )
  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  do {
    if (Test-ChatBIUrl -Uri $Uri -TimeoutSec 3) { return $true }
    Start-Sleep -Seconds $IntervalSeconds
  } while ((Get-Date) -lt $deadline)
  return $false
}

function Test-ChatBIPortListening {
  param([Parameter(Mandatory = $true)][int]$Port)
  try { return $null -ne (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction Stop | Select-Object -First 1) }
  catch { return $false }
}

function Get-ChatBIDatabaseEndpoint {
  param([Parameter(Mandatory = $true)]$Configuration)
  if ([string]::IsNullOrWhiteSpace($Configuration.DatabaseUrl)) {
    return [pscustomobject]@{ Host = '127.0.0.1'; Port = 5432 }
  }
  if ($Configuration.DatabaseUrl -notmatch '^postgresql\+psycopg://(?:[^@/]+@)?([^/:?]+)(?::(\d+))?') {
    return $null
  }
  $hostName = $matches[1]
  if ($hostName -eq 'host.docker.internal') { $hostName = '127.0.0.1' }
  $port = if ($matches[2]) { [int]$matches[2] } else { 5432 }
  return [pscustomobject]@{ Host = $hostName; Port = $port }
}

function ConvertTo-ChatBIPgToolsUrl {
  param([Parameter(Mandatory = $true)][string]$DatabaseUrl)
  if ($DatabaseUrl -notmatch '^postgresql\+psycopg://') { throw 'A PostgreSQL SQLAlchemy URL is required' }
  return $DatabaseUrl -replace '^postgresql\+psycopg://', 'postgresql://'
}

function Write-ChatBICheck {
  param(
    [ValidateSet('PASS', 'WARN', 'FAIL')][string]$Status,
    [Parameter(Mandatory = $true)][string]$Name,
    [Parameter(Mandatory = $true)][string]$Message,
    [string]$Action = ''
  )
  $color = @{ PASS = 'Green'; WARN = 'Yellow'; FAIL = 'Red' }[$Status]
  Write-Host "${Status}: $Name - $Message" -ForegroundColor $color
  if ($Action) { Write-Host "ACTION: $Action" }
}
