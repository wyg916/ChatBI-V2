[CmdletBinding()]
param(
  [string]$EnvFile = '',
  [switch]$DemoSeed,
  [switch]$SkipBuild,
  [switch]$NoGenerateSecrets
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'deployment\ChatBI.Deployment.ps1')
$projectRoot = Split-Path -Parent $PSScriptRoot
$resolvedEnv = Resolve-ChatBIEnvFile -EnvFile $EnvFile
Set-Location -LiteralPath $projectRoot

try {
  if (-not $NoGenerateSecrets) { Initialize-ChatBISecrets -EnvFile $resolvedEnv }
  $configuration = Assert-ChatBIConfiguration -EnvFile $resolvedEnv
  if ($DemoSeed) { $env:CHATBI_SEED_DEMO_SEMANTIC_MODEL = 'true'; $configuration.DemoSeed = $true }
  if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'Docker CLI was not found. ACTION: Install Docker Desktop and rerun bootstrap.ps1.'
  }
  & docker info *> $null
  if ($LASTEXITCODE -ne 0) { throw 'Docker Desktop is not running. ACTION: Start Docker Desktop and rerun bootstrap.ps1.' }
  & docker compose version *> $null
  if ($LASTEXITCODE -ne 0) { throw 'Docker Compose is unavailable. ACTION: Install the Compose plugin.' }

  foreach ($path in @($configuration.StorageRoot, $configuration.BackupRoot)) {
    $resolvedPath = Resolve-ChatBIDataPath -Path $path
    [void][IO.Directory]::CreateDirectory($resolvedPath)
  }
  $compose = Get-ChatBIComposeArguments -EnvFile $resolvedEnv -ProjectName $configuration.ProjectName
  & docker @compose config --quiet
  if ($LASTEXITCODE -ne 0) { throw 'Compose configuration validation failed before build' }

  if (-not $SkipBuild) {
    Write-Host '[Bootstrap] Building the Backend migration image...'
    & docker @compose build backend
    if ($LASTEXITCODE -ne 0) { throw 'Backend image build failed' }
  }

  Write-Host '[Bootstrap] Checking authenticated PostgreSQL readiness...'
  & docker @compose run --rm --no-deps backend python -c "from sqlalchemy import text; from app.db.session import engine; c=engine.connect(); c.execute(text('SELECT 1')); c.close(); print('DATABASE_READINESS=PASS')"
  if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL is unreachable or rejected the configured credentials' }

  Write-Host '[Bootstrap] Applying Alembic migrations...'
  & docker @compose run --rm --no-deps backend alembic upgrade head
  if ($LASTEXITCODE -ne 0) { throw 'Alembic migration failed' }
  & docker @compose run --rm --no-deps backend alembic current
  if ($LASTEXITCODE -ne 0) { throw 'Unable to verify the current Alembic revision' }

  Write-Host '[Bootstrap] Creating Workspace, login identities, and governed runtime records...'
  $bootstrapCommand = @('run', '--rm', '--no-deps', 'backend', 'python', '-m', 'app.db.deployment_bootstrap')
  if ($configuration.DemoSeed) { $bootstrapCommand += '--demo-seed' }
  & docker @compose @bootstrapCommand
  if ($LASTEXITCODE -ne 0) { throw 'Workspace/bootstrap initialization failed' }

  Write-Host 'BOOTSTRAP=PASS' -ForegroundColor Green
  Write-Host 'MIGRATION=PASS'
  Write-Host 'BOOTSTRAP_DB=PASS'
  exit 0
} catch {
  Write-Host 'BOOTSTRAP=FAIL' -ForegroundColor Red
  Write-Host $_.Exception.Message
  exit 1
}
