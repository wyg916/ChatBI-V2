param(
  [Parameter(Mandatory = $true)][string]$SourceEnv,
  [string]$Schema = 'chatbi_eval_feedback_v21',
  [int]$BackendPort = 18080,
  [string]$Python = 'python'
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$backendRoot = Join-Path $projectRoot 'backend'
if (-not (Test-Path -LiteralPath $SourceEnv)) { throw 'Source env file is unavailable' }
if (Test-NetConnection -ComputerName '127.0.0.1' -Port $BackendPort -InformationLevel Quiet) { throw "Port $BackendPort is already in use" }

$values = @{}
Get-Content -LiteralPath $SourceEnv | ForEach-Object {
  if ($_ -match '^[A-Za-z_][A-Za-z0-9_]*=') {
    $key, $value = $_ -split '=', 2
    $values[$key] = $value
    [Environment]::SetEnvironmentVariable($key, $value, 'Process')
  }
}
if (-not $values['CHATBI_META_PASSWORD']) { throw 'CHATBI_META_PASSWORD is missing' }
$encodedPassword = [System.Uri]::EscapeDataString($values['CHATBI_META_PASSWORD'])
$baseUrl = "postgresql+psycopg://chatbi_app:${encodedPassword}@127.0.0.1:5432/chatbi_v2"
$env:CHATBI_DATABASE_URL = $baseUrl
$env:PYTHONPATH = $backendRoot
& $Python (Join-Path $backendRoot 'scripts\prepare_eval_schema.py') --schema $Schema
if ($LASTEXITCODE -ne 0) { throw 'Isolated schema preparation failed' }

$env:CHATBI_DATABASE_URL = "${baseUrl}?options=-csearch_path%3D${Schema}"
Push-Location $backendRoot
try {
  & $Python -m alembic upgrade head
  if ($LASTEXITCODE -ne 0) { throw 'Isolated migration failed' }
} finally {
  Pop-Location
}
$env:CHATBI_SEED_DEMO_SEMANTIC_MODEL = 'true'
$stdout = Join-Path $projectRoot "backend-v21-$BackendPort.stdout.log"
$stderr = Join-Path $projectRoot "backend-v21-$BackendPort.stderr.log"
$process = Start-Process -FilePath $Python -ArgumentList @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', "$BackendPort") -WorkingDirectory $backendRoot -RedirectStandardOutput $stdout -RedirectStandardError $stderr -WindowStyle Hidden -PassThru

$ready = $false
for ($attempt = 0; $attempt -lt 40; $attempt++) {
  try {
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:$BackendPort/health" -TimeoutSec 2
    if ($health.status -eq 'ok') { $ready = $true; break }
  } catch { }
  Start-Sleep -Milliseconds 500
}
if (-not $ready) {
  Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
  throw "Isolated Backend failed to start; inspect $stderr"
}
Write-Output "BACKEND_PORT=$BackendPort"
Write-Output "BACKEND_PID=$($process.Id)"
Write-Output 'HEALTH=ok'
