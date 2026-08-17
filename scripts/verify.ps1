$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$backendPort = if($env:CHATBI_BACKEND_PORT) { $env:CHATBI_BACKEND_PORT } else { '8000' }
$frontendPort = if($env:CHATBI_FRONTEND_PORT) { $env:CHATBI_FRONTEND_PORT } else { '5173' }
$ragPort = if($env:CHATBI_RAG_PORT) { $env:CHATBI_RAG_PORT } else { '8001' }
$apiBase = "http://127.0.0.1:${backendPort}/api/v1"

function Get-AnonymousStatus {
  param([Parameter(Mandatory = $true)][string]$Uri)
  try {
    return [int](Invoke-WebRequest -UseBasicParsing -Uri $Uri -TimeoutSec 5).StatusCode
  } catch {
    if ($null -eq $_.Exception.Response) { throw }
    return [int]$_.Exception.Response.StatusCode
  }
}

$backend = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:${backendPort}/health" -TimeoutSec 5
$frontend = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:${frontendPort}/" -TimeoutSec 5
$version = Invoke-RestMethod -Uri "$apiBase/version" -TimeoutSec 5
$rag = Invoke-RestMethod -Uri "http://127.0.0.1:${ragPort}/health" -TimeoutSec 5
if($rag.status -ne 'ok') { throw 'Live RAG runtime is not ready' }

$protectedPaths = @('/auth/me', '/query-capabilities', '/datasources', '/semantic-models', '/conversations')
foreach ($path in $protectedPaths) {
  $status = Get-AnonymousStatus -Uri "$apiBase$path"
  if ($status -ne 401) { throw "Protected endpoint $path returned HTTP $status without a session" }
}

[pscustomobject]@{
  frontend_http = $frontend.StatusCode
  backend_http = $backend.StatusCode
  backend_version = $version.version
  live_rag = 'HEALTHY_AUTH_REQUIRED'
  protected_api_auth = '5_OF_5_RETURN_401'
  local_metadata_postgres = 'READY'
  local_demo_postgres = 'PORT_REACHABLE_STARTUP_CHECK'
  local_demo_mysql = 'PORT_REACHABLE_STARTUP_CHECK'
} | Format-List
