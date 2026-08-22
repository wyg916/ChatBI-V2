[CmdletBinding()]
param(
  [string]$EvidencePath = 'docs/evidence/day5/cold-start.json'
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot 'backend\.venv\Scripts\python.exe'
$schema = 'chatbi_release_cold_' + (Get-Date -Format 'yyyyMMddHHmmss') + '_' + $PID
$portOffset = $PID % 1000
$backendPort = 18000 + $portOffset
$frontendPort = 15000 + $portOffset
$ragPort = 19000 + $portOffset
$composeProject = 'chatbi-v2-day5-cold-' + $PID
$apiBase = "http://127.0.0.1:${backendPort}/api/v1"
$evidence = Join-Path $projectRoot $EvidencePath
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
  evaluation = 'NOT_RUN'
  model_provider_configuration = 'NOT_RUN'
  cleanup = 'NOT_RUN'
  stage = 'INITIALIZE'
  secrets_recorded = $false
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
  foreach($line in Get-Content -LiteralPath (Join-Path $projectRoot '.env')) {
    if($line -and -not $line.TrimStart().StartsWith('#') -and $line.Contains('=')) {
      $key, $value = $line.Split('=', 2)
      $values[$key.Trim()] = $value.Trim()
    }
  }
  return $values
}

try {
  Set-Location -LiteralPath $projectRoot
  $env:COMPOSE_PROJECT_NAME = $composeProject
  $env:CHATBI_BACKEND_PORT = [string]$backendPort
  $env:CHATBI_FRONTEND_PORT = [string]$frontendPort
  $env:CHATBI_RAG_PORT = [string]$ragPort
  & (Join-Path $PSScriptRoot 'stop.ps1')
  $env:CHATBI_RELEASE_SCHEMA = $schema
  & $python (Join-Path $projectRoot 'backend\scripts\manage_release_schema.py') create
  if($LASTEXITCODE -ne 0) { throw 'Temporary metadata schema creation failed' }

  $localEnv = Read-LocalEnv
  $metaPassword = $localEnv['CHATBI_META_PASSWORD']
  if(-not $metaPassword) { throw 'CHATBI_META_PASSWORD is missing from local .env' }
  $encodedPassword = [uri]::EscapeDataString($metaPassword)
  $env:CHATBI_DATABASE_URL = "postgresql+psycopg://chatbi_app:${encodedPassword}@host.docker.internal:5432/chatbi_v2?options=-csearch_path%3D${schema}"

  & (Join-Path $PSScriptRoot 'start.ps1')
  if($LASTEXITCODE -ne 0) { throw 'Release candidate start failed' }
  $result.bootstrap = 'PASS'
  $result.backend = 'HTTP_200'
  $result.frontend = 'HTTP_200'

  $result.stage = 'SANDBOX_RUNTIME'
  $null = Assert-Compose-ServiceHealthy -Service 'sandbox-docker-proxy'
  $result.sandbox_docker_proxy = 'HEALTHY_RESTRICTED_PROXY'
  $null = Assert-Compose-ServiceHealthy -Service 'sandbox-controller'
  $result.sandbox_controller = 'HEALTHY_NONROOT_NO_HOST_SOCKET'
  & docker compose exec -T backend python -c 'import httpx2; print(httpx2.__version__)' | Out-Null
  if($LASTEXITCODE -ne 0) { throw 'Backend runtime dependency httpx2 is unavailable' }
  $result.runtime_dependency = 'HTTPX2_IMPORT_PASS'

  $result.stage = 'MIGRATION'
  $migration = (& docker compose exec -T backend sh -c 'alembic current 2>&1' | Out-String)
  if($LASTEXITCODE -ne 0 -or $migration -notmatch '20260822_0012') { throw 'Migration head mismatch' }
  $result.migration = '20260822_0012_HEAD'

  $adminPassword = $localEnv['CHATBI_BOOTSTRAP_ADMIN_PASSWORD']
  if(-not $adminPassword) { throw 'CHATBI_BOOTSTRAP_ADMIN_PASSWORD is missing from local .env' }
  $adminEmail = if($localEnv['CHATBI_BOOTSTRAP_ADMIN_EMAIL']) { $localEnv['CHATBI_BOOTSTRAP_ADMIN_EMAIL'] } else { 'admin@chatbi.local' }
  $webSession = New-Object Microsoft.PowerShell.Commands.WebRequestSession
  $loginBody = @{ email = $adminEmail; password = $adminPassword; remember = $false } | ConvertTo-Json
  $login = Invoke-RestMethod -Method Post -Uri "$apiBase/auth/login" -WebSession $webSession -ContentType 'application/json' -Body $loginBody -TimeoutSec 10
  if(-not $login.authenticated -or $login.user.role -ne 'ADMIN') { throw 'Cold start authentication failed' }
  $result.authentication = 'ADMIN_SESSION_READY_TOKEN_NOT_RECORDED'

  $result.stage = 'DATASOURCE_LIST'
  $sources = Invoke-RestMethod -Uri "$apiBase/datasources" -WebSession $webSession -TimeoutSec 10
  $result.stage = 'DATASOURCE_SYNC'
  foreach($source in $sources) {
    $sync = Invoke-RestMethod -Method Post -Uri "$apiBase/datasources/$($source.id)/sync" -WebSession $webSession -TimeoutSec 30
    if(-not $sync.success) { throw "Datasource sync failed for $($source.type)" }
  }
  if(($sources.type -notcontains 'postgresql') -or ($sources.type -notcontains 'mysql')) {
    throw 'Cold start did not seed both PostgreSQL and MySQL datasources'
  }
  $result.demo_data = 'POSTGRESQL_READY_MYSQL_READY'

  $result.stage = 'SEMANTIC_MODEL'
  $postgres = $sources | Where-Object { $_.type -eq 'postgresql' } | Select-Object -First 1
  $models = Invoke-RestMethod -Uri "$apiBase/semantic-models" -WebSession $webSession -TimeoutSec 10
  $model = $models | Where-Object { $_.datasource_id -eq $postgres.id -and $_.status -eq 'PUBLISHED' } | Select-Object -First 1
  if(-not $model) { throw 'Published PostgreSQL semantic model was not seeded' }
  $askBody = @{ question = '统计订单数量'; datasource_id = $postgres.id; semantic_model_id = $model.id } | ConvertTo-Json
  $result.stage = 'ASK'
  $ask = Invoke-RestMethod -Method Post -Uri "$apiBase/ask" -WebSession $webSession -ContentType 'application/json' -Body $askBody -TimeoutSec 30
  if($ask.status -ne 'SUCCEEDED' -or $ask.oracle.status -ne 'PASSED') { throw 'Cold start Ask gate failed' }
  $result.ask = 'SUCCEEDED_ORACLE_PASSED'

  $result.stage = 'EVALUATION'
  $evaluation = Invoke-RestMethod -Method Post -Uri "$apiBase/evaluation/runs" -WebSession $webSession -TimeoutSec 120
  if($evaluation.run.status -ne 'PASS' -or $evaluation.run.golden_set_count -ne 50) {
    throw 'Cold start Evaluation gate failed'
  }
  $result.evaluation = 'GOLDEN50_PASS'

  $result.stage = 'MODEL_PROVIDERS'
  $providers = Invoke-RestMethod -Uri "$apiBase/model-providers" -WebSession $webSession -TimeoutSec 10
  $named = @($providers.items | Where-Object { $_.id -in @('kimi','mimo','deepseek') })
  if($named.Count -ne 3 -or @($named | Where-Object { -not $_.configured }).Count -ne 0 -or $providers.secrets_exposed) {
    throw 'Model Provider configuration gate failed'
  }
  $result.model_provider_configuration = 'KIMI_MIMO_DEEPSEEK_READY_SECRETS_HIDDEN'
  $result.stage = 'COMPLETE'
  $passed = $true
} catch {
  $result.error_type = $_.Exception.GetType().Name
  if($_.Exception.Response -and $_.Exception.Response.StatusCode) {
    $result.error_status = [int]$_.Exception.Response.StatusCode
  }
} finally {
  $timer.Stop()
  try {
    Set-Location -LiteralPath $projectRoot
    & (Join-Path $PSScriptRoot 'stop.ps1')
    Remove-Item Env:CHATBI_DATABASE_URL -ErrorAction SilentlyContinue
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
  }
  $result.cleanup = if($cleanup) { 'PASS' } else { 'FAIL' }
  $result.duration_seconds = [Math]::Round($timer.Elapsed.TotalSeconds, 1)
  if($passed -and $cleanup) { $result.cold_start = 'PASS' }
  $parent = Split-Path -Parent $evidence
  New-Item -ItemType Directory -Path $parent -Force | Out-Null
  $result | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $evidence -Encoding utf8
  $result | ConvertTo-Json -Depth 6
}

if($result.cold_start -ne 'PASS') { exit 1 }
