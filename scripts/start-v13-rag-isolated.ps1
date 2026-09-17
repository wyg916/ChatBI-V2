param(
  [Parameter(Mandatory = $true)][string]$SourceEnv,
  [Parameter(Mandatory = $true)][string]$Schema,
  [Parameter(Mandatory = $true)][string]$EvidenceRoot,
  [int]$RagPort = 8001,
  [string]$Python = 'python'
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$backendRoot = Join-Path $projectRoot 'backend'
if (-not (Test-Path -LiteralPath $SourceEnv)) { throw 'Source env file is unavailable' }
if (Test-NetConnection -ComputerName '127.0.0.1' -Port $RagPort -InformationLevel Quiet) {
  throw "Port $RagPort is already in use"
}

$values = @{}
Get-Content -LiteralPath $SourceEnv | ForEach-Object {
  if ($_ -match '^[A-Za-z_][A-Za-z0-9_]*=') {
    $key, $value = $_ -split '=', 2
    $values[$key] = $value
    [Environment]::SetEnvironmentVariable($key, $value, 'Process')
  }
}
if (-not $values['CHATBI_META_PASSWORD']) { throw 'CHATBI_META_PASSWORD is missing' }
if (-not $values['CHATBI_RAG_SHARED_SECRET']) { throw 'CHATBI_RAG_SHARED_SECRET is missing' }

$encodedPassword = [System.Uri]::EscapeDataString($values['CHATBI_META_PASSWORD'])
$env:CHATBI_DATABASE_URL = "postgresql+psycopg://chatbi_app:${encodedPassword}@127.0.0.1:5432/chatbi_v2?options=-csearch_path%3D${Schema}"
$packagePaths = @(
  $backendRoot,
  (Join-Path $projectRoot 'packages\agent-contracts\src'),
  (Join-Path $projectRoot 'packages\agent-orchestrator\src'),
  (Join-Path $projectRoot 'packages\prompt-registry\src'),
  (Join-Path $projectRoot 'packages\rag-adapter\src'),
  (Join-Path $projectRoot 'packages\rag-contracts\src'),
  (Join-Path $projectRoot 'packages\dbgpt-runtime-adapter\src'),
  (Join-Path $projectRoot 'packages\pandasai-selected-runtime\src')
)
$env:PYTHONPATH = $packagePaths -join [System.IO.Path]::PathSeparator

New-Item -ItemType Directory -Path $EvidenceRoot -Force | Out-Null
$stdout = Join-Path $EvidenceRoot "rag-runtime-${RagPort}.stdout.log"
$stderr = Join-Path $EvidenceRoot "rag-runtime-${RagPort}.stderr.log"
$process = Start-Process -FilePath $Python `
  -ArgumentList @('-m', 'uvicorn', 'app.rag_runtime.main:app', '--host', '127.0.0.1', '--port', [string]$RagPort) `
  -WorkingDirectory $backendRoot `
  -WindowStyle Hidden `
  -RedirectStandardOutput $stdout `
  -RedirectStandardError $stderr `
  -PassThru

$deadline = (Get-Date).AddSeconds(20)
do {
  Start-Sleep -Milliseconds 300
  try {
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:${RagPort}/health" -TimeoutSec 2
  } catch {
    $health = $null
  }
} while (-not $health -and (Get-Date) -lt $deadline)
if (-not $health) { throw 'RAG runtime start timeout' }
if ($health.status -ne 'ok' -or -not $health.identity_signing) { throw 'RAG runtime is not identity-signing ready' }

Write-Output "RAG_PORT=$RagPort"
Write-Output "RAG_PID=$($process.Id)"
Write-Output "RAG_HEALTH=$($health.status)"
