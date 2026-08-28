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
    Write-Host '[Bootstrap] Building deployment images...'
    & docker @compose build backend frontend sandbox-controller
    if ($LASTEXITCODE -ne 0) { throw 'Deployment image build failed' }
  }

  Write-Host '[Bootstrap] Checking PostgreSQL, migrating, and creating baseline records...'
  $demoArgument = if ($configuration.DemoSeed) { ' --demo-seed' } else { '' }
  $bootstrapScript = "python -c `"from sqlalchemy import text; from app.db.session import engine; c=engine.connect(); c.execute(text('SELECT 1')); c.close(); print('DATABASE_READINESS=PASS')`" && alembic upgrade head && alembic current && python -m app.db.deployment_bootstrap$demoArgument"
  & docker @compose run --rm --no-deps backend sh -c $bootstrapScript
  if ($LASTEXITCODE -ne 0) {
    throw 'Database readiness, migration, or deployment record bootstrap failed; inspect the preceding command output'
  }

  Write-Host 'BOOTSTRAP=PASS' -ForegroundColor Green
  Write-Host 'MIGRATION=PASS'
  Write-Host 'BOOTSTRAP_DB=PASS'
  exit 0
} catch {
  Write-Host 'BOOTSTRAP=FAIL' -ForegroundColor Red
  Write-Host $_.Exception.Message
  exit 1
}
