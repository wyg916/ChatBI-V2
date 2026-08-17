param(
  [switch]$ResetDemoData
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$backendRoot = Join-Path $projectRoot 'backend'
$venvPython = Join-Path $backendRoot '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $venvPython)) {
  $pythonLauncher = Get-Command py -ErrorAction SilentlyContinue
  if (-not $pythonLauncher) { throw 'Python 3.11 is required for first-time local database bootstrap' }
  & py -3.11 -m venv (Join-Path $backendRoot '.venv')
  if ($LASTEXITCODE -ne 0) { throw 'Unable to create backend virtual environment' }
  & $venvPython -m pip install -r (Join-Path $backendRoot 'requirements.txt')
  if ($LASTEXITCODE -ne 0) { throw 'Unable to install backend dependencies' }
}

$localPackages = @(
  'rag-contracts',
  'rag-adapter',
  'agent-contracts',
  'agent-orchestrator',
  'prompt-registry'
)
foreach ($package in $localPackages) {
  & $venvPython -m pip install --no-deps -e (Join-Path $projectRoot "packages\$package")
  if ($LASTEXITCODE -ne 0) { throw "Unable to install local package $package" }
}

$postgresAdmin = $env:CHATBI_LOCAL_POSTGRES_ADMIN_PASSWORD
$mysqlAdmin = $env:CHATBI_LOCAL_MYSQL_ADMIN_PASSWORD
$postgresBstr = [IntPtr]::Zero
$mysqlBstr = [IntPtr]::Zero
try {
  if (-not $postgresAdmin) {
    $secure = Read-Host 'Local PostgreSQL administrator password' -AsSecureString
    $postgresBstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    $postgresAdmin = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($postgresBstr)
  }
  if (-not $mysqlAdmin) {
    $secure = Read-Host 'Local MySQL administrator password' -AsSecureString
    $mysqlBstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    $mysqlAdmin = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($mysqlBstr)
  }
  $env:CHATBI_LOCAL_POSTGRES_ADMIN_PASSWORD = $postgresAdmin
  $env:CHATBI_LOCAL_MYSQL_ADMIN_PASSWORD = $mysqlAdmin
  $arguments = @('-m', 'app.db.bootstrap_local')
  if ($ResetDemoData) { $arguments += '--reset-demo' }
  Push-Location -LiteralPath $backendRoot
  try { & $venvPython @arguments } finally { Pop-Location }
  if ($LASTEXITCODE -ne 0) { throw 'Local database bootstrap failed' }
} finally {
  Remove-Item Env:CHATBI_LOCAL_POSTGRES_ADMIN_PASSWORD -ErrorAction SilentlyContinue
  Remove-Item Env:CHATBI_LOCAL_MYSQL_ADMIN_PASSWORD -ErrorAction SilentlyContinue
  if ($postgresBstr -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($postgresBstr) }
  if ($mysqlBstr -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($mysqlBstr) }
}
