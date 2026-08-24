[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$EvidencePath,
  [string]$CandidateSha = '',
  [string]$RollbackSha = '89bdc12936be0555bdad8a85f06932fb7dc476ee',
  [string]$SourceEnv = '',
  [string]$Python = ''
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
if(-not $CandidateSha) { $CandidateSha = (& git -C $projectRoot rev-parse HEAD).Trim() }
if(-not $SourceEnv) { $SourceEnv = Join-Path (Split-Path -Parent (Split-Path -Parent $projectRoot)) '.env' }
if(-not $Python) {
  $Python = @(
    (Join-Path (Split-Path -Parent (Split-Path -Parent $projectRoot)) 'backend\.venv\Scripts\python.exe'),
    (Join-Path $projectRoot 'backend\.venv\Scripts\python.exe')
  ) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}
if(-not (Test-Path -LiteralPath $SourceEnv)) { throw 'Rollback source env is unavailable' }
if(-not $Python -or -not (Test-Path -LiteralPath $Python)) { throw 'Rollback Python runtime is unavailable' }
if((& git -C $projectRoot status --porcelain)) { throw 'Rollback dry-run requires a clean worktree' }
if((& git -C $projectRoot rev-parse $CandidateSha).Trim() -ne $CandidateSha) { throw 'Candidate SHA is not exact' }
& git -C $projectRoot merge-base --is-ancestor $RollbackSha $CandidateSha
if($LASTEXITCODE -ne 0) { throw 'Rollback SHA is not an ancestor of candidate SHA' }

$suffix = (Get-Date -Format 'yyyyMMddHHmmss') + '_' + $PID
$schema = 'chatbi_release_rollback_' + $suffix
$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('chatbi-phase5-rollback-' + $suffix)
$candidateRoot = Join-Path $tempRoot 'candidate'
$rollbackRoot = Join-Path $tempRoot 'rollback'
$candidateArchive = Join-Path $tempRoot 'candidate.tar'
$rollbackArchive = Join-Path $tempRoot 'rollback.tar'
$candidateProject = 'chatbi-p5-candidate-' + $PID
$rollbackProject = 'chatbi-p5-rollback-' + $PID
$offset = $PID % 500
$candidateBackendPort = 22000 + $offset
$candidateFrontendPort = 22500 + $offset
$candidateRagPort = 23000 + $offset
$rollbackBackendPort = 23500 + $offset
$rollbackFrontendPort = 24000 + $offset
$rollbackRagPort = 24500 + $offset
$evidence = [System.IO.Path]::GetFullPath($EvidencePath)
$candidateFingerprint = ''
$rollbackFingerprint = ''
$candidateImage = ''
$rollbackImage = ''
$schemaCreated = $false
$activeProject = ''
$activeRoot = ''
$passed = $false
$cleanup = $false
$redactionValues = @()
$result = [ordered]@{
  schema_version = 'chatbi.v13.phase5.rollback-dry-run.v1'
  timestamp = (Get-Date).ToUniversalTime().ToString('o')
  candidate_sha = $CandidateSha
  rollback_sha = $RollbackSha
  production_target = $false
  isolated_schema = $schema
  candidate_start = 'NOT_RUN'
  candidate_api_smoke = 'NOT_RUN'
  candidate_browser_smoke = 'NOT_RUN'
  candidate_migration = 'NOT_RUN'
  rollback_stop = 'NOT_RUN'
  migration_rollback = 'NOT_RUN'
  rollback_start = 'NOT_RUN'
  rollback_api_smoke = 'NOT_RUN'
  rollback_browser_smoke = 'NOT_RUN'
  rollback_migration = 'NOT_RUN'
  data_consistency = 'NOT_RUN'
  temporary_schema_cleanup = 'NOT_RUN'
  temporary_source_cleanup = 'NOT_RUN'
  compose_diagnostics = 'NOT_REQUIRED'
  real_project_data = 'PRESERVED_READ_ONLY'
  secrets_recorded = $false
  rollback_dry_run = 'FAIL'
  stage = 'INITIALIZE'
}

function Read-LocalEnv {
  param([string]$Path)
  $values = @{}
  foreach($line in Get-Content -LiteralPath $Path) {
    if($line -and -not $line.TrimStart().StartsWith('#') -and $line.Contains('=')) {
      $key, $value = $line.Split('=', 2)
      $values[$key.Trim()] = $value.Trim()
    }
  }
  return $values
}

function Invoke-ComposeDown {
  param([string]$Root, [string]$Project)
  if($Root -and $Project -and (Test-Path -LiteralPath (Join-Path $Root 'docker-compose.yml'))) {
    & docker compose --project-directory $Root -f (Join-Path $Root 'docker-compose.yml') -p $Project down --remove-orphans | Out-Null
    if($LASTEXITCODE -ne 0) { throw "Compose stop failed for $Project" }
  }
}

function Protect-DiagnosticText {
  param([string]$Text)
  $protected = $Text
  foreach($value in $redactionValues) {
    if($value) { $protected = $protected.Replace($value, '[REDACTED]') }
  }
  return $protected
}

function Save-ComposeDiagnostics {
  param([string]$Root, [string]$Project, [string]$Label)
  if(-not $Root -or -not $Project -or -not (Test-Path -LiteralPath (Join-Path $Root 'docker-compose.yml'))) {
    return 'UNAVAILABLE'
  }
  $diagnosticPath = [System.IO.Path]::ChangeExtension($evidence, ".${Label}-compose.log")
  $parent = Split-Path -Parent $diagnosticPath
  New-Item -ItemType Directory -Path $parent -Force | Out-Null
  $psOutput = (& docker compose --project-directory $Root -f (Join-Path $Root 'docker-compose.yml') -p $Project ps -a 2>&1 | Out-String)
  $logOutput = (& docker compose --project-directory $Root -f (Join-Path $Root 'docker-compose.yml') -p $Project logs --no-color --timestamps 2>&1 | Out-String)
  $combined = "COMPOSE_PS`r`n${psOutput}`r`nCOMPOSE_LOGS`r`n${logOutput}"
  Protect-DiagnosticText -Text $combined | Set-Content -LiteralPath $diagnosticPath -Encoding utf8
  return $diagnosticPath
}

function Wait-Endpoint {
  param([string]$Uri, [int]$Seconds = 240)
  $deadline = (Get-Date).AddSeconds($Seconds)
  do {
    try {
      $response = Invoke-WebRequest -UseBasicParsing -Uri $Uri -TimeoutSec 4
      if($response.StatusCode -eq 200) { return }
    } catch {}
    Start-Sleep -Seconds 2
  } while((Get-Date) -lt $deadline)
  throw "Endpoint did not become healthy: $Uri"
}

function Invoke-ApiFingerprint {
  param([int]$BackendPort)
  $apiBase = "http://127.0.0.1:${BackendPort}/api/v1"
  $session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
  $email = if($env:CHATBI_BOOTSTRAP_ADMIN_EMAIL) { $env:CHATBI_BOOTSTRAP_ADMIN_EMAIL } else { 'admin@chatbi.local' }
  $body = @{email=$email; password=$env:CHATBI_BOOTSTRAP_ADMIN_PASSWORD; remember=$false} | ConvertTo-Json
  $login = Invoke-RestMethod -Method Post -Uri "$apiBase/auth/login" -WebSession $session -ContentType 'application/json' -Body $body -TimeoutSec 15
  if(-not $login.authenticated) { throw 'Rollback API authentication failed' }
  $dashboards = Invoke-RestMethod -Uri "$apiBase/dashboards?sort=name&page=1&page_size=100" -WebSession $session -TimeoutSec 15
  $dashboard = @($dashboards.items | Sort-Object id | Select-Object -First 1)[0]
  if(-not $dashboard) { throw 'Rollback dashboard seed is unavailable' }
  $detail = Invoke-RestMethod -Uri "$apiBase/dashboards/$($dashboard.id)" -WebSession $session -TimeoutSec 60
  $stable = [ordered]@{
    dashboard_id = $detail.dashboard.id
    card_count = @($detail.cards).Count
    kpis = $detail.kpis
    trend = $detail.revenue_trend
    regions = $detail.regions
  } | ConvertTo-Json -Depth 20 -Compress
  $bytes = [System.Text.Encoding]::UTF8.GetBytes($stable)
  return [Convert]::ToHexString([System.Security.Cryptography.SHA256]::HashData($bytes)).ToLowerInvariant()
}

function Invoke-BrowserSmoke {
  param([int]$BackendPort, [int]$FrontendPort)
  $priorApi = $env:CHATBI_API_BASE
  $priorWeb = $env:CHATBI_WEB_BASE
  try {
    $env:CHATBI_API_BASE = "http://127.0.0.1:${BackendPort}/api/v1"
    $env:CHATBI_WEB_BASE = "http://127.0.0.1:${FrontendPort}"
    Push-Location -LiteralPath (Join-Path $projectRoot 'frontend')
    try {
      & .\node_modules\.bin\playwright.cmd test e2e/phase5-rollback-browser-smoke.spec.ts --config playwright.config.ts --workers=1
      if($LASTEXITCODE -ne 0) { throw 'Rollback browser smoke failed' }
    } finally { Pop-Location }
  } finally {
    if($null -eq $priorApi) { Remove-Item Env:CHATBI_API_BASE -ErrorAction SilentlyContinue } else { $env:CHATBI_API_BASE = $priorApi }
    if($null -eq $priorWeb) { Remove-Item Env:CHATBI_WEB_BASE -ErrorAction SilentlyContinue } else { $env:CHATBI_WEB_BASE = $priorWeb }
  }
}

function Start-IsolatedVersion {
  param([string]$Root, [string]$Project, [int]$BackendPort, [int]$FrontendPort, [int]$RagPort)
  $env:COMPOSE_PROJECT_NAME = $Project
  $env:CHATBI_BACKEND_PORT = [string]$BackendPort
  $env:CHATBI_FRONTEND_PORT = [string]$FrontendPort
  $env:CHATBI_RAG_PORT = [string]$RagPort
  & docker compose --project-directory $Root -f (Join-Path $Root 'docker-compose.yml') -p $Project up -d --build
  if($LASTEXITCODE -ne 0) { throw "Compose start failed for $Project" }
  Wait-Endpoint -Uri "http://127.0.0.1:${BackendPort}/health"
  Wait-Endpoint -Uri "http://127.0.0.1:${FrontendPort}/healthz"
  Wait-Endpoint -Uri "http://127.0.0.1:${RagPort}/health"
}

try {
  $result.stage = 'PRECHECK_ARCHIVE'
  New-Item -ItemType Directory -Path $candidateRoot, $rollbackRoot -Force | Out-Null
  $runtimePaths = @(
    '.dockerignore', '.env.example', 'backend', 'docker-compose.yml', 'evaluation',
    'frontend', 'packages', 'sandbox_runtime', 'scripts'
  )
  & git -C $projectRoot archive --format=tar --output=$candidateArchive $CandidateSha -- @runtimePaths
  if($LASTEXITCODE -ne 0) { throw 'Candidate archive failed' }
  & git -C $projectRoot archive --format=tar --output=$rollbackArchive $RollbackSha -- @runtimePaths
  if($LASTEXITCODE -ne 0) { throw 'Rollback archive failed' }
  & $Python (Join-Path $projectRoot 'scripts\extract_git_archive.py') $candidateArchive $candidateRoot
  if($LASTEXITCODE -ne 0) { throw 'Candidate extraction failed' }
  & $Python (Join-Path $projectRoot 'scripts\extract_git_archive.py') $rollbackArchive $rollbackRoot
  if($LASTEXITCODE -ne 0) { throw 'Rollback extraction failed' }

  $localEnv = Read-LocalEnv -Path $SourceEnv
  foreach($entry in $localEnv.GetEnumerator()) {
    [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value, 'Process')
  }
  $redactionValues = @()
  foreach($entry in $localEnv.GetEnumerator()) {
    if($entry.Key -match '(?i)(PASSWORD|SECRET|TOKEN|PRIVATE|CREDENTIAL)' -and $entry.Value -and $entry.Value.Length -ge 6) {
      $redactionValues += $entry.Value
      $redactionValues += [uri]::EscapeDataString($entry.Value)
    }
  }
  $redactionValues = @($redactionValues | Sort-Object -Unique)
  if(-not $env:CHATBI_META_PASSWORD) { throw 'CHATBI_META_PASSWORD is missing' }
  if(-not $env:CHATBI_BOOTSTRAP_ADMIN_PASSWORD) { throw 'CHATBI_BOOTSTRAP_ADMIN_PASSWORD is missing' }
  $encodedPassword = [uri]::EscapeDataString($env:CHATBI_META_PASSWORD)
  $env:CHATBI_DATABASE_URL = "postgresql+psycopg://chatbi_app:${encodedPassword}@host.docker.internal:5432/chatbi_v2?options=-csearch_path%3D${schema}"
  $env:CHATBI_MODEL_PROVIDER = 'deterministic'
  $env:CHATBI_GENERAL_MODEL_PROVIDER = 'deterministic'
  $env:CHATBI_VISION_MODEL_PROVIDER = 'deterministic'
  $env:CHATBI_TEST_COST_CONTROL = 'YES'
  $env:CHATBI_TEST_EXECUTION_LEVEL = 'LEVEL0'
  $env:CHATBI_PAID_GATE_AUTHORIZED = 'NO'
  $env:CHATBI_LEVEL0_PAID_EXCEPTION = 'NO'

  $result.stage = 'CREATE_ISOLATED_SCHEMA'
  $env:CHATBI_RELEASE_SCHEMA = $schema
  & $Python (Join-Path $projectRoot 'backend\scripts\manage_release_schema.py') create
  if($LASTEXITCODE -ne 0) { throw 'Isolated rollback schema creation failed' }
  $schemaCreated = $true

  $result.stage = 'CANDIDATE_START'
  $activeProject = $candidateProject
  $activeRoot = $candidateRoot
  Start-IsolatedVersion -Root $candidateRoot -Project $candidateProject -BackendPort $candidateBackendPort -FrontendPort $candidateFrontendPort -RagPort $candidateRagPort
  $result.candidate_start = 'PASS_5_SERVICE_HEALTH'
  $candidateImage = (& docker image inspect --format '{{.Id}}' chatbi-v2-backend:latest).Trim()
  $candidateMigration = (& docker compose --project-directory $candidateRoot -f (Join-Path $candidateRoot 'docker-compose.yml') -p $candidateProject exec -T backend alembic current | Out-String).Trim()
  if($candidateMigration -notmatch '20260822_0012') { throw 'Candidate migration head mismatch' }
  $result.candidate_migration = '20260822_0012'
  $candidateFingerprint = Invoke-ApiFingerprint -BackendPort $candidateBackendPort
  $result.candidate_api_smoke = 'PASS_AUTHENTICATED_DASHBOARD_READBACK'
  Invoke-BrowserSmoke -BackendPort $candidateBackendPort -FrontendPort $candidateFrontendPort
  $result.candidate_browser_smoke = 'PASS'

  $result.stage = 'STOP_CANDIDATE'
  Invoke-ComposeDown -Root $candidateRoot -Project $candidateProject
  $result.rollback_stop = 'PASS'
  $activeProject = ''
  $activeRoot = ''
  $result.migration_rollback = 'NOT_APPLICABLE_SAME_HEAD_20260822_0012'

  $result.stage = 'ROLLBACK_START'
  $activeProject = $rollbackProject
  $activeRoot = $rollbackRoot
  Start-IsolatedVersion -Root $rollbackRoot -Project $rollbackProject -BackendPort $rollbackBackendPort -FrontendPort $rollbackFrontendPort -RagPort $rollbackRagPort
  $result.rollback_start = 'PASS_5_SERVICE_HEALTH'
  $rollbackImage = (& docker image inspect --format '{{.Id}}' chatbi-v2-backend:latest).Trim()
  $rollbackMigration = (& docker compose --project-directory $rollbackRoot -f (Join-Path $rollbackRoot 'docker-compose.yml') -p $rollbackProject exec -T backend alembic current | Out-String).Trim()
  if($rollbackMigration -notmatch '20260822_0012') { throw 'Rollback migration head mismatch' }
  $result.rollback_migration = '20260822_0012'
  $rollbackFingerprint = Invoke-ApiFingerprint -BackendPort $rollbackBackendPort
  $result.rollback_api_smoke = 'PASS_AUTHENTICATED_DASHBOARD_READBACK'
  Invoke-BrowserSmoke -BackendPort $rollbackBackendPort -FrontendPort $rollbackFrontendPort
  $result.rollback_browser_smoke = 'PASS'
  if($candidateFingerprint -ne $rollbackFingerprint) { throw 'Candidate/rollback business data fingerprint mismatch' }
  $result.data_consistency = 'PASS_SHA256_EQUAL'
  $result.candidate_image_digest = $candidateImage
  $result.rollback_image_digest = $rollbackImage
  $result.business_data_fingerprint = $candidateFingerprint
  $result.stage = 'COMPLETE'
  $passed = $true
} catch {
  $result.error_type = $_.Exception.GetType().Name
  $result.error_message = Protect-DiagnosticText -Text $_.Exception.Message
  try {
    $label = if($result.stage -like 'ROLLBACK*') { 'rollback' } else { 'candidate' }
    $result.compose_diagnostics = Save-ComposeDiagnostics -Root $activeRoot -Project $activeProject -Label $label
  } catch {
    $result.compose_diagnostics = 'CAPTURE_FAILED'
  }
} finally {
  try {
    if($activeProject -and $activeRoot) { Invoke-ComposeDown -Root $activeRoot -Project $activeProject }
    Invoke-ComposeDown -Root $candidateRoot -Project $candidateProject
    Invoke-ComposeDown -Root $rollbackRoot -Project $rollbackProject
  } catch {}
  if($schemaCreated) {
    try {
      $env:CHATBI_RELEASE_SCHEMA = $schema
      & $Python (Join-Path $projectRoot 'backend\scripts\manage_release_schema.py') drop | Out-Null
      $result.temporary_schema_cleanup = if($LASTEXITCODE -eq 0) { 'PASS' } else { 'FAIL' }
    } catch { $result.temporary_schema_cleanup = 'FAIL' }
  }
  try {
    $resolvedTemp = [System.IO.Path]::GetFullPath($tempRoot)
    $expectedParent = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
    if(-not $resolvedTemp.StartsWith($expectedParent) -or (Split-Path -Leaf $resolvedTemp) -notlike 'chatbi-phase5-rollback-*') {
      throw 'Refusing to remove unexpected rollback temporary path'
    }
    if(Test-Path -LiteralPath $resolvedTemp) { Remove-Item -LiteralPath $resolvedTemp -Recurse -Force }
    $result.temporary_source_cleanup = 'PASS'
  } catch { $result.temporary_source_cleanup = 'FAIL' }
  $cleanup = $result.temporary_schema_cleanup -eq 'PASS' -and $result.temporary_source_cleanup -eq 'PASS'
  if($passed -and $cleanup) { $result.rollback_dry_run = 'PASS' }
  $parent = Split-Path -Parent $evidence
  New-Item -ItemType Directory -Path $parent -Force | Out-Null
  $result | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $evidence -Encoding utf8
  $result | ConvertTo-Json -Depth 10
  Remove-Item Env:CHATBI_RELEASE_SCHEMA,Env:COMPOSE_PROJECT_NAME,Env:CHATBI_BACKEND_PORT,Env:CHATBI_FRONTEND_PORT,Env:CHATBI_RAG_PORT,Env:CHATBI_TEST_COST_CONTROL,Env:CHATBI_TEST_EXECUTION_LEVEL,Env:CHATBI_PAID_GATE_AUTHORIZED,Env:CHATBI_LEVEL0_PAID_EXCEPTION -ErrorAction SilentlyContinue
}

if($result.rollback_dry_run -ne 'PASS') { exit 1 }
