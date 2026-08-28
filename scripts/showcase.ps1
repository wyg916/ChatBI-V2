[CmdletBinding()]
param(
  [ValidateSet('Start', 'Stop', 'Reset', 'Status')]
  [string]$Action = 'Start',
  [string]$EnvFile = '',
  [switch]$NoOpen,
  [switch]$Rebuild
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'deployment\ChatBI.Deployment.ps1')
$resolvedEnv = Resolve-ChatBIEnvFile -EnvFile $EnvFile
$showcaseFrontendPort = '15173'
$showcaseBackendPort = '18080'
$showcaseRagPort = '18081'
$showcaseProjectName = 'chatbi-v2-showcase'
$showcaseBackendImage = if ([string]::IsNullOrWhiteSpace($env:CHATBI_BACKEND_IMAGE)) { 'chatbi-v2-backend:latest' } else { $env:CHATBI_BACKEND_IMAGE }
$showcaseFrontendImage = if ([string]::IsNullOrWhiteSpace($env:CHATBI_FRONTEND_IMAGE)) { 'chatbi-v2-frontend:latest' } else { $env:CHATBI_FRONTEND_IMAGE }
$showcaseSandboxImage = if ([string]::IsNullOrWhiteSpace($env:CHATBI_SANDBOX_IMAGE)) { 'chatbi-sandbox-runtime:phase3' } else { $env:CHATBI_SANDBOX_IMAGE }
$frontendUrl = "http://127.0.0.1:$showcaseFrontendPort/"
$backendBase = "http://127.0.0.1:$showcaseBackendPort"
$ragBase = "http://127.0.0.1:$showcaseRagPort"
$apiBase = "$backendBase/api/v1"
$showcaseAdminEmail = 'admin@chatbi.local'
$showcaseAdminPassword = 'ChatBI-Showcase-2026!'
$showcaseAnalystPassword = 'ChatBI-Analyst-2026!'

function Write-Stage {
  param([string]$Message)
  Write-Host "[ChatBI Showcase] $Message" -ForegroundColor Cyan
}

function Assert-LocalPrerequisites {
  if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'Docker CLI was not found. Install and start Docker Desktop.'
  }
  & docker info *> $null
  if ($LASTEXITCODE -ne 0) { throw 'Docker Desktop is not ready.' }
  if (-not (Test-Path -LiteralPath $resolvedEnv)) {
    throw 'Local .env is missing. Run scripts/bootstrap-local-databases.ps1 once.'
  }
  foreach ($port in 5432, 3306) {
    if (-not (Test-NetConnection -ComputerName '127.0.0.1' -Port $port -InformationLevel Quiet)) {
      throw "Required local database port $port is not reachable."
    }
  }
}

function Set-ShowcaseEnvironment {
  $env:COMPOSE_PROJECT_NAME = $showcaseProjectName
  $env:CHATBI_DEPLOYMENT_MODE = 'showcase'
  $env:CHATBI_ENVIRONMENT = 'development'
  $env:CHATBI_FRONTEND_PORT = $showcaseFrontendPort
  $env:CHATBI_BACKEND_PORT = $showcaseBackendPort
  $env:CHATBI_RAG_PORT = $showcaseRagPort
  $env:CHATBI_CORS_ALLOW_ORIGINS = "http://localhost:$showcaseFrontendPort,http://127.0.0.1:$showcaseFrontendPort"
  $env:CHATBI_MODEL_PROVIDER = 'deterministic'
  $env:CHATBI_GENERAL_MODEL_PROVIDER = 'deterministic'
  $env:CHATBI_VISION_MODEL_PROVIDER = 'deterministic'
  $env:CHATBI_TEST_COST_CONTROL = 'YES'
  $env:CHATBI_TEST_EXECUTION_LEVEL = 'LEVEL0'
  $env:CHATBI_PAID_GATE_AUTHORIZED = 'NO'
  $env:CHATBI_LEVEL0_PAID_EXCEPTION = 'NO'
  $env:CHATBI_SEED_DEMO_SEMANTIC_MODEL = 'true'
  $env:CHATBI_BACKEND_IMAGE = $showcaseBackendImage
  $env:CHATBI_FRONTEND_IMAGE = $showcaseFrontendImage
  $env:CHATBI_SANDBOX_IMAGE = $showcaseSandboxImage
  $env:CHATBI_STORAGE_ROOT = './.chatbi/showcase-storage'
  $env:CHATBI_BACKUP_ROOT = './.chatbi/showcase-backups'
  $env:CHATBI_GIT_SHA = (& git -C $projectRoot rev-parse HEAD).Trim()
  $env:CHATBI_RELEASE_VERSION = 'v1.3.1-candidate'
  $env:CHATBI_FRONTEND_BUILD = 'production'
  if ([string]::IsNullOrWhiteSpace($env:CHATBI_SHOWCASE_DATABASE_NAME)) {
    $env:CHATBI_SHOWCASE_DATABASE_NAME = 'chatbi_v2'
  }
  if ([string]::IsNullOrWhiteSpace($env:CHATBI_DATABASE_URL)) {
    $modeValues = Read-ChatBIEnv -EnvFile $resolvedEnv
    $metaPassword = Get-ChatBIValue -Values $modeValues -Name 'CHATBI_META_PASSWORD'
    if (Test-ChatBIPlaceholder -Value $metaPassword) {
      throw 'Local Showcase requires CHATBI_DATABASE_URL or CHATBI_META_PASSWORD in the selected EnvFile.'
    }
    $encodedMetaPassword = [uri]::EscapeDataString($metaPassword)
    $env:CHATBI_DATABASE_URL = "postgresql+psycopg://chatbi_app:${encodedMetaPassword}@host.docker.internal:5432/$env:CHATBI_SHOWCASE_DATABASE_NAME"
  }
  $env:CHATBI_BOOTSTRAP_ADMIN_PASSWORD = $showcaseAdminPassword
  $env:CHATBI_BOOTSTRAP_ANALYST_PASSWORD = $showcaseAnalystPassword
}

function Test-CanonicalImages {
  foreach ($image in $showcaseBackendImage, $showcaseFrontendImage, $showcaseSandboxImage) {
    & docker image inspect $image *> $null
    if ($LASTEXITCODE -ne 0) { return $false }
  }
  return $true
}

function Invoke-CanonicalBuild {
  # Compose v5 delegates multi-service builds to Bake by default. Building the
  # three canonical images directly avoids intermittent Windows gRPC session
  # header failures while keeping the exact same Dockerfiles and contexts.
  Write-Stage 'Building Backend image...'
  & docker build --progress=plain -t $showcaseBackendImage -f backend/Dockerfile .
  if ($LASTEXITCODE -ne 0) { throw 'Backend image build failed.' }
  Write-Stage 'Building Sandbox image...'
  & docker build --progress=plain -t $showcaseSandboxImage -f sandbox_runtime/Dockerfile .
  if ($LASTEXITCODE -ne 0) { throw 'Sandbox image build failed.' }
  Write-Stage 'Building Frontend image...'
  & docker build --progress=plain -t $showcaseFrontendImage frontend
  if ($LASTEXITCODE -ne 0) { throw 'Frontend image build failed.' }
}

function Invoke-StartFromImages {
  $startScript = Join-Path $PSScriptRoot 'start.ps1'
  & $startScript -EnvFile $resolvedEnv -SkipBuild
  if ($LASTEXITCODE -ne 0) { throw 'Canonical stack startup failed.' }
}

function Invoke-StartStack {
  $skipBuild = (-not $Rebuild) -and (Test-CanonicalImages)
  if ($skipBuild) {
    Write-Stage 'Starting the canonical stack from verified local images...'
  } else {
    Invoke-CanonicalBuild
  }
  Invoke-StartFromImages
}

function Reset-MetadataSchema {
  Write-Stage 'Recreating the local metadata schema; demo_business remains read-only and preserved...'
  & docker @script:showcaseCompose run --rm --no-deps backend python -m app.showcase.rebuild_schema --confirm-local-showcase-schema-rebuild
  if ($LASTEXITCODE -ne 0) { throw 'Local metadata schema rebuild failed.' }
  & docker @script:showcaseCompose run --rm --no-deps backend alembic upgrade head
  if ($LASTEXITCODE -ne 0) { throw 'Local metadata migration failed after schema rebuild.' }
}

function Set-DocumentedCredentials {
  Write-Stage 'Applying documented local-demo credentials and revoking stale sessions...'
  & docker @script:showcaseCompose exec -T backend python -m app.showcase.reset --credentials-only
  if ($LASTEXITCODE -ne 0) { throw 'Unable to apply local-demo credentials.' }
}

function Test-ShowcaseLogin {
  $session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
  $body = @{ email = $showcaseAdminEmail; password = $showcaseAdminPassword; remember = $false } | ConvertTo-Json
  $login = Invoke-RestMethod -Method Post -Uri "$apiBase/auth/login" -ContentType 'application/json' -Body $body -WebSession $session -TimeoutSec 10
  if (-not $login.authenticated -or $login.user.email -ne $showcaseAdminEmail) {
    throw 'Showcase login verification failed.'
  }
  $me = Invoke-RestMethod -Uri "$apiBase/auth/me" -WebSession $session -TimeoutSec 10
  if (-not $me.authenticated) { throw 'Showcase session verification failed.' }
  Invoke-RestMethod -Method Post -Uri "$apiBase/auth/logout" -WebSession $session -TimeoutSec 10 | Out-Null
}

function Wait-ShowcaseReady {
  $deadline = (Get-Date).AddMinutes(3)
  do {
    try {
      $backend = Invoke-RestMethod -Uri "$backendBase/health" -TimeoutSec 3
      $rag = Invoke-RestMethod -Uri "$ragBase/health" -TimeoutSec 3
      $frontend = Invoke-WebRequest -UseBasicParsing -Uri $frontendUrl -TimeoutSec 3
      if ($backend.status -eq 'ok' -and $rag.status -eq 'ok' -and $frontend.StatusCode -eq 200) { return }
    } catch {
      Start-Sleep -Seconds 3
    }
  } while ((Get-Date) -lt $deadline)
  throw 'Showcase services did not become ready before the deadline.'
}

function Write-ReadySummary {
  Write-Host ''
  Write-Host 'ChatBI V2 local showcase is ready.' -ForegroundColor Green
  Write-Host "Project  : $projectRoot"
  Write-Host "Browser  : $frontendUrl"
  Write-Host "Account  : $showcaseAdminEmail"
  Write-Host "Password : $showcaseAdminPassword"
  Write-Host 'Mode     : deterministic / LEVEL0 / no paid provider calls'
}

Set-Location -LiteralPath $projectRoot
Set-ShowcaseEnvironment
$showcaseConfiguration = Assert-ChatBIConfiguration -EnvFile $resolvedEnv
$script:showcaseCompose = Get-ChatBIComposeArguments -EnvFile $resolvedEnv -ProjectName $showcaseConfiguration.ProjectName

switch ($Action) {
  'Stop' {
    Write-Stage 'Stopping the canonical local stack...'
    & (Join-Path $PSScriptRoot 'stop.ps1') -EnvFile $resolvedEnv
    exit $LASTEXITCODE
  }
  'Status' {
    Assert-LocalPrerequisites
    & (Join-Path $PSScriptRoot 'status.ps1') -EnvFile $resolvedEnv
    & (Join-Path $PSScriptRoot 'verify.ps1') -EnvFile $resolvedEnv
    Test-ShowcaseLogin
    Write-ReadySummary
    exit 0
  }
  'Reset' {
    Assert-LocalPrerequisites
    Write-Stage 'Resetting local ChatBI metadata; read-only business schemas are preserved...'
    & (Join-Path $PSScriptRoot 'stop.ps1') -EnvFile $resolvedEnv
    if ($Rebuild -or -not (Test-CanonicalImages)) { Invoke-CanonicalBuild }
    Reset-MetadataSchema
    Invoke-StartFromImages
    & docker @script:showcaseCompose exec -T backend python -m app.showcase.reset --confirm-local-showcase-reset
    if ($LASTEXITCODE -ne 0) { throw 'Local showcase metadata reset failed.' }
    & docker @script:showcaseCompose restart backend rag-runtime | Out-Host
    Wait-ShowcaseReady
    & (Join-Path $PSScriptRoot 'verify.ps1') -EnvFile $resolvedEnv
    if ($LASTEXITCODE -ne 0) { throw 'Post-reset service verification failed.' }
    Test-ShowcaseLogin
    Write-ReadySummary
  }
  'Start' {
    Assert-LocalPrerequisites
    Invoke-StartStack
    Set-DocumentedCredentials
    Test-ShowcaseLogin
    Write-ReadySummary
  }
}

if (-not $NoOpen) {
  Write-Stage 'Opening the local showcase in the default browser...'
  Start-Process -FilePath $frontendUrl
}
