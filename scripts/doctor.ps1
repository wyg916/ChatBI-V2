[CmdletBinding()]
param([string]$EnvFile = '')

$ErrorActionPreference = 'Continue'
. (Join-Path $PSScriptRoot 'deployment\ChatBI.Deployment.ps1')
$projectRoot = Split-Path -Parent $PSScriptRoot
$resolvedEnv = Resolve-ChatBIEnvFile -EnvFile $EnvFile
Set-Location -LiteralPath $projectRoot
$failures = 0
$warnings = 0
$configuration = $null
$providerStates = @()

function Add-DoctorResult {
  param([string]$Status, [string]$Name, [string]$Message, [string]$Action = '')
  Write-ChatBICheck -Status $Status -Name $Name -Message $Message -Action $Action
  if ($Status -eq 'FAIL') { $script:failures++ }
  if ($Status -eq 'WARN') { $script:warnings++ }
}

try {
  $configuration = Assert-ChatBIConfiguration -EnvFile $resolvedEnv
  Add-DoctorResult PASS 'Configuration' 'environment syntax and required settings are valid'
} catch {
  Add-DoctorResult FAIL 'Configuration' $_.Exception.Message 'Correct the environment file, then rerun doctor.ps1.'
}

$dockerCommand = Get-Command docker -ErrorAction SilentlyContinue
if (-not $dockerCommand) {
  Add-DoctorResult FAIL 'Docker installed' 'Docker CLI was not found' 'Install Docker Desktop.'
} else {
  Add-DoctorResult PASS 'Docker installed' $dockerCommand.Source
  & docker info *> $null
  if ($LASTEXITCODE -eq 0) { Add-DoctorResult PASS 'Docker running' 'Docker Engine is ready' }
  else { Add-DoctorResult FAIL 'Docker running' 'Docker Desktop is not running' 'Start Docker Desktop and wait until it reports Ready.' }
  & docker compose version *> $null
  if ($LASTEXITCODE -eq 0) { Add-DoctorResult PASS 'Docker Compose' ((& docker compose version) -join ' ') }
  else { Add-DoctorResult FAIL 'Docker Compose' 'Compose plugin is unavailable' 'Install or update Docker Desktop.' }
}

try {
  $system = Get-CimInstance Win32_ComputerSystem
  $cpu = [int]$system.NumberOfLogicalProcessors
  $memory = [math]::Round($system.TotalPhysicalMemory / 1GB, 1)
  if ($cpu -lt 2 -or $memory -lt 4) {
    Add-DoctorResult FAIL 'CPU / Memory' "$cpu logical CPU, $memory GB RAM" 'Provide at least 2 logical CPUs and 4 GB RAM.'
  } elseif ($memory -lt 8) {
    Add-DoctorResult WARN 'CPU / Memory' "$cpu logical CPU, $memory GB RAM" '8 GB RAM or more is recommended for image builds.'
  } else { Add-DoctorResult PASS 'CPU / Memory' "$cpu logical CPU, $memory GB RAM" }
} catch { Add-DoctorResult WARN 'CPU / Memory' 'resource discovery was unavailable' 'Check Docker Desktop resource settings manually.' }

try {
  $driveName = (Split-Path -Qualifier $projectRoot).TrimEnd(':')
  $drive = Get-PSDrive -Name $driveName
  $free = [math]::Round($drive.Free / 1GB, 1)
  if ($free -lt 5) { Add-DoctorResult FAIL 'Disk space' "$free GB free" 'Free at least 5 GB before building images.' }
  elseif ($free -lt 10) { Add-DoctorResult WARN 'Disk space' "$free GB free" '10 GB free is recommended for a fresh image build.' }
  else { Add-DoctorResult PASS 'Disk space' "$free GB free" }
} catch { Add-DoctorResult WARN 'Disk space' 'free-space discovery failed' 'Confirm at least 5 GB is free.' }

if ($configuration) {
  foreach ($probe in @(
    @('Backend port', $configuration.BackendPort, "http://127.0.0.1:$($configuration.BackendPort)/health"),
    @('Frontend port', $configuration.FrontendPort, "http://127.0.0.1:$($configuration.FrontendPort)/healthz"),
    @('RAG port', $configuration.RagPort, "http://127.0.0.1:$($configuration.RagPort)/health")
  )) {
    if (-not (Test-ChatBIPortListening -Port $probe[1])) {
      Add-DoctorResult PASS $probe[0] "port $($probe[1]) is available"
    } elseif (Test-ChatBIUrl -Uri $probe[2]) {
      Add-DoctorResult PASS $probe[0] "port $($probe[1]) is served by a healthy ChatBI endpoint"
    } else {
      Add-DoctorResult FAIL $probe[0] "port $($probe[1]) is occupied by another process" 'Stop the conflicting process or choose another port.'
    }
  }

  $endpoint = Get-ChatBIDatabaseEndpoint -Configuration $configuration
  if ($endpoint -and (Test-NetConnection -ComputerName $endpoint.Host -Port $endpoint.Port -InformationLevel Quiet -WarningAction SilentlyContinue)) {
    Add-DoctorResult PASS 'PostgreSQL TCP' "$($endpoint.Host):$($endpoint.Port) is reachable"
  } else {
    Add-DoctorResult FAIL 'PostgreSQL TCP' 'configured database endpoint is unreachable' 'Start PostgreSQL and verify host, port, firewall, and Docker reachability.'
  }

  if ($dockerCommand -and $failures -eq 0) {
    $compose = Get-ChatBIComposeArguments -EnvFile $resolvedEnv -ProjectName $configuration.ProjectName
    $imageId = (& docker @compose images -q backend 2>$null | Select-Object -First 1)
    if ($LASTEXITCODE -eq 0 -and $imageId) {
      $probeScript = "python -c `"from sqlalchemy import text; from app.db.session import engine; c=engine.connect(); c.execute(text('SELECT 1')); c.close(); print('DATABASE_CONNECTION=PASS')`" && alembic current && python -m app.db.deployment_state providers"
      $probeOutput = & docker @compose run --rm --no-deps backend sh -c $probeScript 2>&1
      $probeText = $probeOutput -join "`n"
      if ($probeText -match 'DATABASE_CONNECTION=PASS') { Add-DoctorResult PASS 'DB connectivity' 'authenticated SQL SELECT 1 succeeded' }
      else { Add-DoctorResult FAIL 'DB connectivity' 'authenticated SQL connection failed' 'Correct CHATBI_DATABASE_URL credentials and database privileges.' }
      if ($LASTEXITCODE -eq 0 -and $probeText -match '\(head\)') {
        Add-DoctorResult PASS 'Migration status' 'metadata database is at the Alembic head'
      } else {
        Add-DoctorResult WARN 'Migration status' 'metadata database is not yet verified at head' 'Run scripts/bootstrap.ps1.'
      }
      $providerJson = $probeOutput | Where-Object { ([string]$_).Trim().StartsWith('[') } | Select-Object -Last 1
      if ($providerJson) {
        try { $providerStates = @(([string]$providerJson | ConvertFrom-Json)) }
        catch { Add-DoctorResult WARN 'Provider state' 'runtime configuration state could not be parsed' 'Rerun Doctor after rebuilding the Backend image.' }
      }
    } else {
      Add-DoctorResult WARN 'DB connectivity' 'Backend image is not built; authenticated probe is deferred' 'Run scripts/bootstrap.ps1, then rerun doctor.ps1.'
      Add-DoctorResult WARN 'Migration status' 'Backend image is not built' 'Run scripts/bootstrap.ps1.'
    }

    $running = @(& docker @compose ps --status running --services 2>$null)
    foreach ($service in @('backend', 'frontend', 'rag-runtime', 'sandbox-controller', 'sandbox-docker-proxy')) {
      if ($running -contains $service) { Add-DoctorResult PASS $service 'service is running' }
      else { Add-DoctorResult WARN $service 'service is stopped' 'Run scripts/start.ps1 when ready.' }
    }
  }

  $provider = (Get-ChatBIValue -Values $configuration.Values -Name 'CHATBI_MODEL_PROVIDER' -Default 'auto').ToLowerInvariant()
  $providerDefinitions = @(
    @('mimo', 'CHATBI_MIMO_API_KEY'),
    @('deepseek', 'CHATBI_DEEPSEEK_API_KEY'),
    @('kimi', 'CHATBI_KIMI_API_KEY')
  )
  if ($providerStates.Count -eq 0) {
    $providerStates = @($providerDefinitions | ForEach-Object {
      $providerId = $_[0]
      $configured = -not (Test-ChatBIPlaceholder -Value (Get-ChatBIValue -Values $configuration.Values -Name $_[1]))
      [pscustomobject]@{
        provider = $providerId
        configured = $configured
        enabled = $configured -and $provider -ne 'deterministic' -and ($provider -eq 'auto' -or $provider -eq $providerId)
        health = if($configured) { 'NOT_CHECKED' } else { 'CREDENTIAL_MISSING' }
        reachability = 'NOT_TESTED'
      }
    })
  }
  foreach ($state in $providerStates) {
    $configuredText = if($state.configured) { 'YES' } else { 'NO' }
    $enabledText = if($state.enabled) { 'YES' } else { 'NO' }
    Add-DoctorResult PASS "Provider $($state.provider)" "Configured=$configuredText Enabled=$enabledText Health=$($state.health) Reachability=$($state.reachability)"
  }
  Add-DoctorResult PASS 'Provider deterministic' 'Configured=YES Enabled=YES Health=LOCAL_READY Reachability=LOCAL'
  Write-Host 'PROVIDER_LIVE_CALLS=0'
  $providerKeys = @($providerStates | Where-Object { $_.configured })
  if ($provider -eq 'deterministic') {
    Add-DoctorResult PASS 'Provider configuration' 'deterministic local mode; no external key is required'
  } elseif ($providerKeys.Count -gt 0) {
    Add-DoctorResult PASS 'Provider configuration' "$($providerKeys.Count) named Provider credential(s) configured server-side"
  } else {
    Add-DoctorResult WARN 'Provider configuration' 'base application can start, but live AI Provider calls are unavailable' 'Configure MiMo, DeepSeek, or Kimi server-side when live AI is required.'
  }

  if ($configuration.DemoSeed) {
    Add-DoctorResult PASS 'Datasource requirements' 'optional Demo Seed configuration is enabled'
  } else {
    Add-DoctorResult PASS 'Datasource requirements' 'enterprise mode expects a read-only datasource to be added through the UI or API after login'
  }
}

if ($failures -gt 0) {
  Write-Host "DOCTOR=FAIL FAILURES=$failures WARNINGS=$warnings" -ForegroundColor Red
  exit 1
}
Write-Host "DOCTOR=PASS FAILURES=0 WARNINGS=$warnings" -ForegroundColor Green
exit 0
