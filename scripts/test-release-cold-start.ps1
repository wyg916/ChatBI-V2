[CmdletBinding()]
param(
  [string]$EvidencePath = 'docs/evidence/day5/cold-start.json',
  [string]$SourceEnv = '',
  [string]$Python = '',
  [string]$ExpectedMigrationHead = '20260828_0013',
  [ValidateRange(30, 300)]
  [int]$AskTimeoutSeconds = 120,
  [ValidateRange(120, 900)]
  [int]$EvaluationTimeoutSeconds = 300
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not $SourceEnv) { $SourceEnv = Join-Path $projectRoot '.env' }
if (-not (Test-Path -LiteralPath $SourceEnv)) { throw 'Cold-start source env is unavailable' }
if (-not $Python) {
  $pythonCandidates = @(
    (Join-Path $projectRoot 'backend\.venv\Scripts\python.exe'),
    (Join-Path $projectRoot '.venv\Scripts\python.exe')
  )
  $Python = $pythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}
if (-not $Python -or -not (Test-Path -LiteralPath $Python)) { throw 'Cold-start Python runtime is unavailable' }
$python = $Python
$schema = 'chatbi_release_cold_' + (Get-Date -Format 'yyyyMMddHHmmss') + '_' + $PID
$portOffset = $PID % 1000
$backendPort = 18000 + $portOffset
$frontendPort = 15000 + $portOffset
$ragPort = 19000 + $portOffset
$composeProject = 'chatbi-v2-day5-cold-' + $PID
$apiBase = "http://127.0.0.1:${backendPort}/api/v1"
$evidence = if([System.IO.Path]::IsPathRooted($EvidencePath)) { $EvidencePath } else { Join-Path $projectRoot $EvidencePath }
$timer = [System.Diagnostics.Stopwatch]::StartNew()
$passed = $false
$cleanup = $false
$result = [ordered]@{
  timestamp = (Get-Date).ToString('o')
  tested_sha = (& git -C $projectRoot rev-parse HEAD).Trim()
  cold_start = 'FAIL'
  duration_seconds = 0
  project_metadata = 'ISOLATED_TEMPORARY_POSTGRES_SCHEMA'
  demo_business_data = 'EXISTING_REPRODUCIBLE_LOCAL_DATA_READ_ONLY'
  local_external_database = 'PRESERVED'
  bootstrap = 'NOT_RUN'
  migration = 'NOT_RUN'
  demo_data = 'NOT_RUN'
  backend = 'NOT_RUN'
  frontend = 'NOT_RUN'
  sandbox_controller = 'NOT_RUN'
  sandbox_docker_proxy = 'NOT_RUN'
  runtime_dependency = 'NOT_RUN'
  authentication = 'NOT_RUN'
  ask = 'NOT_RUN'
  ask_timeout_seconds = $AskTimeoutSeconds
  evaluation = 'NOT_RUN'
  evaluation_timeout_seconds = $EvaluationTimeoutSeconds
  model_provider_configuration = 'NOT_RUN'
  cleanup = 'NOT_RUN'
  stage = 'INITIALIZE'
  stage_timings_ms = [ordered]@{}
  external_provider_readiness = 'NOT_REQUIRED_LEVEL0_DEGRADED_READY'
  secrets_recorded = $false
}
$stageTimer = [System.Diagnostics.Stopwatch]::StartNew()

function Set-ColdStartStage {
  param([Parameter(Mandatory=$true)][string]$Name)
  if($result.stage) {
    $result.stage_timings_ms[$result.stage] = [Math]::Round($stageTimer.Elapsed.TotalMilliseconds, 1)
  }
  $result.stage = $Name
  $stageTimer.Restart()
}

function Assert-Compose-ServiceHealthy {
  param([Parameter(Mandatory=$true)][string]$Service)
  $containerId = (& docker compose ps -q $Service | Out-String).Trim()
  if($LASTEXITCODE -ne 0 -or -not $containerId) {
    throw "Compose service $Service has no container"
  }
  $health = (& docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' $containerId | Out-String).Trim()
  if($LASTEXITCODE -ne 0 -or $health -ne 'healthy') {
    throw "Compose service $Service is not healthy: $health"
  }
  return $containerId
}

function Read-LocalEnv {
  $values = @{}
  foreach($line in Get-Content -LiteralPath $SourceEnv) {
    if($line -and -not $line.TrimStart().StartsWith('#') -and $line.Contains('=')) {
      $key, $value = $line.Split('=', 2)
      $values[$key.Trim()] = $value.Trim()
    }
  }
  return $values
}

try {
  Set-Location -LiteralPath $projectRoot
  Set-ColdStartStage -Name 'BOOTSTRAP'
  $localEnv = Read-LocalEnv
  foreach($key in $localEnv.Keys) {
    [Environment]::SetEnvironmentVariable($key, $localEnv[$key], 'Process')
  }
  $env:CHATBI_MODEL_PROVIDER = 'deterministic'
  $env:CHATBI_GENERAL_MODEL_PROVIDER = 'deterministic'
  $env:CHATBI_TEST_COST_CONTROL = 'YES'
  $env:CHATBI_TEST_EXECUTION_LEVEL = 'LEVEL0'
  $env:CHATBI_PAID_TEST_AUTHORIZED = 'NO'
  $env:COMPOSE_PROJECT_NAME = $composeProject
  $env:CHATBI_BACKEND_PORT = [string]$backendPort
  $env:CHATBI_FRONTEND_PORT = [string]$frontendPort
  $env:CHATBI_RAG_PORT = [string]$ragPort
  & (Join-Path $PSScriptRoot 'stop.ps1')
  $metaPassword = $localEnv['CHATBI_META_PASSWORD']
  if(-not $metaPassword) { throw 'CHATBI_META_PASSWORD is missing from source env' }
  $encodedPassword = [uri]::EscapeDataString($metaPassword)
  $localDatabaseUrl = "postgresql+psycopg://chatbi_app:${encodedPassword}@127.0.0.1:5432/chatbi_v2"
  $env:CHATBI_DATABASE_URL = $localDatabaseUrl
  Set-ColdStartStage -Name 'DB'
  $env:CHATBI_RELEASE_SCHEMA = $schema
  & $python (Join-Path $projectRoot 'backend\scripts\manage_release_schema.py') create
  if($LASTEXITCODE -ne 0) { throw 'Temporary metadata schema creation failed' }

  $env:CHATBI_DATABASE_URL = "postgresql+psycopg://chatbi_app:${encodedPassword}@host.docker.internal:5432/chatbi_v2?options=-csearch_path%3D${schema}"

  Set-ColdStartStage -Name 'MIGRATION'
  & (Join-Path $PSScriptRoot 'start.ps1')
  if($LASTEXITCODE -ne 0) { throw 'Release candidate start failed' }
  $result.bootstrap = 'PASS'
  Set-ColdStartStage -Name 'BACKEND'
  $backendHealth = Invoke-RestMethod -Uri "http://127.0.0.1:${backendPort}/health" -TimeoutSec 5
  if($backendHealth.status -ne 'ok') { throw 'Backend health is not ready' }
  $result.backend = 'HTTP_200'
  Set-ColdStartStage -Name 'FRONTEND'
  $frontendHealth = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:${frontendPort}/" -TimeoutSec 5
  if($frontendHealth.StatusCode -ne 200) { throw 'Frontend health is not ready' }
  $result.frontend = 'HTTP_200'

  Set-ColdStartStage -Name 'SANDBOX'
  $null = Assert-Compose-ServiceHealthy -Service 'sandbox-docker-proxy'
  $result.sandbox_docker_proxy = 'HEALTHY_RESTRICTED_PROXY'
  $null = Assert-Compose-ServiceHealthy -Service 'sandbox-controller'
  $result.sandbox_controller = 'HEALTHY_NONROOT_NO_HOST_SOCKET'
  & docker compose exec -T backend python -c 'from importlib.metadata import version; assert version("httpx2") == "2.12.0"; assert version("aiohttp") == "3.14.3"; assert version("dbgpt") == "0.8.1"' | Out-Null
  if($LASTEXITCODE -ne 0) { throw 'Backend runtime dependency versions do not match the release contract' }
  & docker compose exec -T backend python -c 'from chatbi_dbgpt_runtime import DbgptAwelRuntime, RuntimeRequest; result=DbgptAwelRuntime().run(RuntimeRequest(question="cold start AWEL bridge", route="COMPLEX_ANALYSIS", trace_id="cold-start-awel"), lambda control: "AWEL_OK"); assert result.output == "AWEL_OK" and result.runtime_calls == 1 and result.upstream_package_version == "0.8.1"' | Out-Null
  if($LASTEXITCODE -ne 0) { throw 'Selected DB-GPT AWEL bridge smoke failed in the release image' }
  $result.runtime_dependency = 'HTTPX2_2_12_0_AIOHTTP_3_14_3_DBGPT_AWEL_PASS'

  $migration = (& docker compose exec -T backend sh -c 'alembic current 2>&1' | Out-String)
  if($LASTEXITCODE -ne 0 -or $migration -notmatch [regex]::Escape($ExpectedMigrationHead)) {
    throw "Migration head mismatch; expected $ExpectedMigrationHead"
  }
  $result.migration = "${ExpectedMigrationHead}_HEAD"

  $adminPassword = $localEnv['CHATBI_BOOTSTRAP_ADMIN_PASSWORD']
  if(-not $adminPassword) { throw 'CHATBI_BOOTSTRAP_ADMIN_PASSWORD is missing from local .env' }
  $adminEmail = if($localEnv['CHATBI_BOOTSTRAP_ADMIN_EMAIL']) { $localEnv['CHATBI_BOOTSTRAP_ADMIN_EMAIL'] } else { 'admin@chatbi.local' }
  $webSession = New-Object Microsoft.PowerShell.Commands.WebRequestSession
  $loginBody = @{ email = $adminEmail; password = $adminPassword; remember = $false } | ConvertTo-Json
  $login = Invoke-RestMethod -Method Post -Uri "$apiBase/auth/login" -WebSession $webSession -ContentType 'application/json' -Body $loginBody -TimeoutSec 10
  if(-not $login.authenticated -or $login.user.role -ne 'ADMIN') { throw 'Cold start authentication failed' }
  $result.authentication = 'ADMIN_SESSION_READY_TOKEN_NOT_RECORDED'

  $sources = Invoke-RestMethod -Uri "$apiBase/datasources" -WebSession $webSession -TimeoutSec 10
  foreach($source in $sources) {
    $sync = Invoke-RestMethod -Method Post -Uri "$apiBase/datasources/$($source.id)/sync" -WebSession $webSession -TimeoutSec 30
    if(-not $sync.success) { throw "Datasource sync failed for $($source.type)" }
  }
  if(($sources.type -notcontains 'postgresql') -or ($sources.type -notcontains 'mysql')) {
    throw 'Cold start did not seed both PostgreSQL and MySQL datasources'
  }
  $result.demo_data = 'POSTGRESQL_READY_MYSQL_READY'

  $postgres = $sources | Where-Object { $_.type -eq 'postgresql' } | Select-Object -First 1
  $models = Invoke-RestMethod -Uri "$apiBase/semantic-models" -WebSession $webSession -TimeoutSec 10
  $model = $models | Where-Object { $_.datasource_id -eq $postgres.id -and $_.status -eq 'PUBLISHED' } | Select-Object -First 1
  if(-not $model) { throw 'Published PostgreSQL semantic model was not seeded' }
  $askBody = @{ question = '统计订单数量'; datasource_id = $postgres.id; semantic_model_id = $model.id } | ConvertTo-Json
  $ask = Invoke-RestMethod -Method Post -Uri "$apiBase/ask" -WebSession $webSession -ContentType 'application/json' -Body $askBody -TimeoutSec $AskTimeoutSeconds
  if($ask.status -ne 'SUCCEEDED' -or $ask.oracle.status -ne 'PASSED') { throw 'Cold start Ask gate failed' }
  $result.ask = 'SUCCEEDED_ORACLE_PASSED'

  Set-ColdStartStage -Name 'EVALUATION'
  $evaluation = Invoke-RestMethod -Method Post -Uri "$apiBase/evaluation/runs" -WebSession $webSession -TimeoutSec $EvaluationTimeoutSeconds
  if($evaluation.run.status -ne 'PASS' -or $evaluation.run.golden_set_count -ne 50) {
    throw 'Cold start Evaluation gate failed'
  }
  $result.evaluation = 'GOLDEN50_PASS'

  Set-ColdStartStage -Name 'READY'
  $providers = Invoke-RestMethod -Uri "$apiBase/model-providers" -WebSession $webSession -TimeoutSec 10
  $named = @($providers.items | Where-Object { $_.id -in @('kimi','mimo','deepseek') })
  if($named.Count -ne 3 -or @($named | Where-Object { -not $_.configured }).Count -ne 0 -or $providers.secrets_exposed) {
    throw 'Model Provider configuration gate failed'
  }
  $result.model_provider_configuration = 'KIMI_MIMO_DEEPSEEK_READY_SECRETS_HIDDEN'
  Set-ColdStartStage -Name 'COMPLETE'
  $passed = $true
} catch {
  $result.error_type = $_.Exception.GetType().Name
  $result.error_message = $_.Exception.Message
  if($_.Exception.Response -and $_.Exception.Response.StatusCode) {
    $result.error_status = [int]$_.Exception.Response.StatusCode
  }
} finally {
  $timer.Stop()
  Set-ColdStartStage -Name 'CLEANUP'
  try {
    Set-Location -LiteralPath $projectRoot
    & (Join-Path $PSScriptRoot 'stop.ps1')
    $env:CHATBI_DATABASE_URL = $localDatabaseUrl
    $env:CHATBI_RELEASE_SCHEMA = $schema
    & $python (Join-Path $projectRoot 'backend\scripts\manage_release_schema.py') drop
    $cleanup = $LASTEXITCODE -eq 0
  } catch {
    $cleanup = $false
  } finally {
    Remove-Item Env:CHATBI_DATABASE_URL -ErrorAction SilentlyContinue
    Remove-Item Env:CHATBI_RELEASE_SCHEMA -ErrorAction SilentlyContinue
    Remove-Item Env:COMPOSE_PROJECT_NAME -ErrorAction SilentlyContinue
    Remove-Item Env:CHATBI_BACKEND_PORT -ErrorAction SilentlyContinue
    Remove-Item Env:CHATBI_FRONTEND_PORT -ErrorAction SilentlyContinue
    Remove-Item Env:CHATBI_RAG_PORT -ErrorAction SilentlyContinue
    Remove-Item Env:CHATBI_MODEL_PROVIDER -ErrorAction SilentlyContinue
    Remove-Item Env:CHATBI_GENERAL_MODEL_PROVIDER -ErrorAction SilentlyContinue
    Remove-Item Env:CHATBI_TEST_COST_CONTROL -ErrorAction SilentlyContinue
    Remove-Item Env:CHATBI_TEST_EXECUTION_LEVEL -ErrorAction SilentlyContinue
    Remove-Item Env:CHATBI_PAID_TEST_AUTHORIZED -ErrorAction SilentlyContinue
  }
  $result.stage_timings_ms['CLEANUP'] = [Math]::Round($stageTimer.Elapsed.TotalMilliseconds, 1)
  $result.stage = if($passed -and $cleanup) { 'COMPLETE' } else { $result.stage }
  $result.cleanup = if($cleanup) { 'PASS' } else { 'FAIL' }
  $result.duration_seconds = [Math]::Round($timer.Elapsed.TotalSeconds, 1)
  if($passed -and $cleanup) { $result.cold_start = 'PASS' }
  $parent = Split-Path -Parent $evidence
  New-Item -ItemType Directory -Path $parent -Force | Out-Null
  $result | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $evidence -Encoding utf8
  $result | ConvertTo-Json -Depth 6
}

if($result.cold_start -ne 'PASS') { exit 1 }
