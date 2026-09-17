[CmdletBinding()]
param(
  [string]$EvidencePath = 'docs/evidence/day5/rollback-simulation.json'
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot 'backend\.venv\Scripts\python.exe'
$schema = 'chatbi_release_rollback_' + (Get-Date -Format 'yyyyMMddHHmmss') + '_' + $PID
$previousSha = '4ec4f0eb8e4060cec035d76b1ffbe32d8f80fce0'
$previousMigration = '20260817_0007'
$finalMigration = '20260818_0009'
$portOffset = $PID % 1000
$previousPort = 20000 + $portOffset
$finalPort = 21000 + $portOffset
$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('chatbi-day5-rollback-' + $PID)
$archive = Join-Path $tempRoot 'day4.tar'
$previousRoot = Join-Path $tempRoot 'day4'
$evidence = Join-Path $projectRoot $EvidencePath
$previousProcess = $null
$finalProcess = $null
$passed = $false
$cleanup = $false
$result = [ordered]@{
  timestamp = (Get-Date).ToString('o')
  rollback_simulation = 'FAIL'
  final_candidate = $finalMigration
  previous_safe_baseline_sha = $previousSha
  previous_safe_migration = $previousMigration
  previous_start = 'NOT_RUN'
  previous_ask = 'NOT_RUN'
  previous_evaluation = 'NOT_RUN'
  restore_migration = 'NOT_RUN'
  final_start = 'NOT_RUN'
  final_ask = 'NOT_RUN'
  final_evaluation = 'NOT_RUN'
  temporary_metadata_cleanup = 'NOT_RUN'
  temporary_source_cleanup = 'NOT_RUN'
  real_project_data = 'PRESERVED'
  secrets_recorded = $false
  stage = 'INITIALIZE'
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

function Wait-Backend {
  param([int]$Port)
  $deadline = (Get-Date).AddSeconds(60)
  do {
    try {
      $response = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:${Port}/health" -TimeoutSec 3
      if($response.StatusCode -eq 200) { return }
    } catch {}
    Start-Sleep -Seconds 1
  } while((Get-Date) -lt $deadline)
  throw "Backend on rollback test port did not become healthy"
}

function Invoke-CoreChecks {
  param([int]$Port)
  $apiBase = "http://127.0.0.1:${Port}/api/v1"
  $requestSession = @{}
  try {
    $adminPassword = $env:CHATBI_BOOTSTRAP_ADMIN_PASSWORD
    if($adminPassword) {
      $webSession = New-Object Microsoft.PowerShell.Commands.WebRequestSession
      $adminEmail = if($env:CHATBI_BOOTSTRAP_ADMIN_EMAIL) { $env:CHATBI_BOOTSTRAP_ADMIN_EMAIL } else { 'admin@chatbi.local' }
      $loginBody = @{ email = $adminEmail; password = $adminPassword; remember = $false } | ConvertTo-Json
      $login = Invoke-RestMethod -Method Post -Uri "$apiBase/auth/login" -WebSession $webSession -ContentType 'application/json' -Body $loginBody -TimeoutSec 10
      if($login.authenticated) { $requestSession = @{ WebSession = $webSession } }
    }
  } catch {
    # The previous safe baseline predates Phase 2 authentication and is checked anonymously.
    $requestSession = @{}
  }
  $sources = Invoke-RestMethod -Uri "$apiBase/datasources" @requestSession -TimeoutSec 10
  foreach($source in $sources) {
    $sync = Invoke-RestMethod -Method Post -Uri "$apiBase/datasources/$($source.id)/sync" @requestSession -TimeoutSec 30
    if(-not $sync.success) { throw 'Rollback datasource sync failed' }
  }
  $postgres = $sources | Where-Object { $_.type -eq 'postgresql' } | Select-Object -First 1
  $models = Invoke-RestMethod -Uri "$apiBase/semantic-models" @requestSession -TimeoutSec 10
  $model = $models | Where-Object { $_.datasource_id -eq $postgres.id -and $_.status -eq 'PUBLISHED' } | Select-Object -First 1
  if(-not $postgres -or -not $model) { throw 'Rollback seed verification failed' }
  $body = @{ question = '统计订单数量'; datasource_id = $postgres.id; semantic_model_id = $model.id } | ConvertTo-Json
  $ask = Invoke-RestMethod -Method Post -Uri "$apiBase/ask" @requestSession -ContentType 'application/json' -Body $body -TimeoutSec 30
  if($ask.status -ne 'SUCCEEDED' -or $ask.oracle.status -ne 'PASSED') { throw 'Rollback Ask verification failed' }
  $evaluation = Invoke-RestMethod -Method Post -Uri "$apiBase/evaluation/runs" @requestSession -TimeoutSec 120
  if($evaluation.run.status -ne 'PASS' -or $evaluation.run.golden_set_count -ne 50) {
    throw 'Rollback Evaluation verification failed'
  }
}

function Start-Backend {
  param([string]$WorkingDirectory, [int]$Port, [string]$Name)
  $stdout = Join-Path $tempRoot ($Name + '.stdout.log')
  $stderr = Join-Path $tempRoot ($Name + '.stderr.log')
  return Start-Process -FilePath $python -ArgumentList @(
    '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', [string]$Port
  ) -WorkingDirectory $WorkingDirectory -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
}

try {
  Set-Location -LiteralPath $projectRoot
  New-Item -ItemType Directory -Path $previousRoot -Force | Out-Null
  git archive --format=tar --output=$archive $previousSha
  if($LASTEXITCODE -ne 0) { throw 'Unable to archive previous safe baseline' }
  tar -xf $archive -C $previousRoot
  if($LASTEXITCODE -ne 0) { throw 'Unable to extract previous safe baseline' }

  $localEnv = Read-LocalEnv
  foreach($entry in $localEnv.GetEnumerator()) {
    [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value, 'Process')
  }
  $metaPassword = $localEnv['CHATBI_META_PASSWORD']
  if(-not $metaPassword) { throw 'CHATBI_META_PASSWORD is missing from local .env' }
  $encodedPassword = [uri]::EscapeDataString($metaPassword)
  $env:CHATBI_DATABASE_URL = "postgresql+psycopg://chatbi_app:${encodedPassword}@127.0.0.1:5432/chatbi_v2?options=-csearch_path%3D${schema}"
  $env:CHATBI_SEED_DEMO_SEMANTIC_MODEL = 'true'
  $env:CHATBI_MODEL_PROVIDER = 'deterministic'
  $env:CHATBI_DEMO_POSTGRES_HOST = '127.0.0.1'
  $env:CHATBI_DEMO_MYSQL_HOST = '127.0.0.1'
  $env:CHATBI_RAG_MODE = 'off'
  $env:CHATBI_AGENT_MODE = 'off'

  $env:CHATBI_RELEASE_SCHEMA = $schema
  & $python (Join-Path $projectRoot 'backend\scripts\manage_release_schema.py') create
  if($LASTEXITCODE -ne 0) { throw 'Rollback schema creation failed' }

  $result.stage = 'FINAL_TO_PREVIOUS_MIGRATION'
  Push-Location -LiteralPath (Join-Path $projectRoot 'backend')
  try {
    & $python -m alembic upgrade $finalMigration
    if($LASTEXITCODE -ne 0) { throw 'Initial final migration failed' }
    & $python -m alembic downgrade $previousMigration
    if($LASTEXITCODE -ne 0) { throw 'Downgrade to public v1.0.0 failed' }
  } finally { Pop-Location }

  $result.stage = 'PREVIOUS_SAFE_START'
  $previousBackend = Join-Path $previousRoot 'backend'
  $previousProcess = Start-Backend -WorkingDirectory $previousBackend -Port $previousPort -Name 'previous'
  Wait-Backend -Port $previousPort
  $result.previous_start = 'HTTP_200'
  Invoke-CoreChecks -Port $previousPort
  $result.previous_ask = 'SUCCEEDED_ORACLE_PASSED'
  $result.previous_evaluation = 'GOLDEN50_PASS'
  Stop-Process -Id $previousProcess.Id -Force -ErrorAction SilentlyContinue
  $previousProcess = $null

  $result.stage = 'RESTORE_FINAL_MIGRATION'
  Push-Location -LiteralPath (Join-Path $projectRoot 'backend')
  try {
    & $python -m alembic upgrade $finalMigration
    if($LASTEXITCODE -ne 0) { throw 'Restore final migration failed' }
  } finally { Pop-Location }
  $result.restore_migration = 'PASS'

  $result.stage = 'RESTORE_FINAL_START'
  $finalProcess = Start-Backend -WorkingDirectory (Join-Path $projectRoot 'backend') -Port $finalPort -Name 'final'
  Wait-Backend -Port $finalPort
  $result.final_start = 'HTTP_200'
  Invoke-CoreChecks -Port $finalPort
  $result.final_ask = 'SUCCEEDED_ORACLE_PASSED'
  $result.final_evaluation = 'GOLDEN50_PASS'
  $result.stage = 'COMPLETE'
  $passed = $true
} catch {
  $result.error_type = $_.Exception.GetType().Name
} finally {
  if($previousProcess) { Stop-Process -Id $previousProcess.Id -Force -ErrorAction SilentlyContinue }
  if($finalProcess) { Stop-Process -Id $finalProcess.Id -Force -ErrorAction SilentlyContinue }
  try {
    $env:CHATBI_RELEASE_SCHEMA = $schema
    & $python (Join-Path $projectRoot 'backend\scripts\manage_release_schema.py') drop
    $result.temporary_metadata_cleanup = if($LASTEXITCODE -eq 0) { 'PASS' } else { 'FAIL' }
  } catch {
    $result.temporary_metadata_cleanup = 'FAIL'
  }
  try {
    $resolvedTemp = [System.IO.Path]::GetFullPath($tempRoot)
    $expectedParent = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
    if(-not $resolvedTemp.StartsWith($expectedParent) -or (Split-Path -Leaf $resolvedTemp) -notlike 'chatbi-day5-rollback-*') {
      throw 'Refusing to remove an unexpected rollback temporary path'
    }
    if(Test-Path -LiteralPath $resolvedTemp) { Remove-Item -LiteralPath $resolvedTemp -Recurse -Force }
    $result.temporary_source_cleanup = 'PASS'
  } catch {
    $result.temporary_source_cleanup = 'FAIL'
  }
  $cleanup = $result.temporary_metadata_cleanup -eq 'PASS' -and $result.temporary_source_cleanup -eq 'PASS'
  if($passed -and $cleanup) { $result.rollback_simulation = 'PASS' }
  $parent = Split-Path -Parent $evidence
  New-Item -ItemType Directory -Path $parent -Force | Out-Null
  $result | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $evidence -Encoding utf8
  $result | ConvertTo-Json -Depth 6
  Remove-Item Env:CHATBI_DATABASE_URL -ErrorAction SilentlyContinue
  Remove-Item Env:CHATBI_RELEASE_SCHEMA -ErrorAction SilentlyContinue
}

if($result.rollback_simulation -ne 'PASS') { exit 1 }
