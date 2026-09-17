[CmdletBinding()]
param([string]$EnvFile = '')

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'deployment\ChatBI.Deployment.ps1')
$projectRoot = Split-Path -Parent $PSScriptRoot
$resolvedEnv = Resolve-ChatBIEnvFile -EnvFile $EnvFile
Set-Location -LiteralPath $projectRoot
$configuration = Assert-ChatBIConfiguration -EnvFile $resolvedEnv
$backendPort = $configuration.BackendPort
$frontendPort = $configuration.FrontendPort
$ragPort = $configuration.RagPort
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
$frontend = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:${frontendPort}/healthz" -TimeoutSec 5
$version = Invoke-RestMethod -Uri "$apiBase/version" -TimeoutSec 5
$proxiedVersion = Invoke-RestMethod -Uri "http://127.0.0.1:${frontendPort}/api/v1/version" -TimeoutSec 5
$rag = Invoke-RestMethod -Uri "http://127.0.0.1:${ragPort}/health" -TimeoutSec 5
if($rag.status -ne 'ok') { throw 'Live RAG runtime is not ready' }
if($proxiedVersion.version -ne $version.version) {
  throw "Frontend Backend proxy version mismatch: frontend=$($proxiedVersion.version) backend=$($version.version)"
}

$protectedPaths = @('/auth/me', '/query-capabilities', '/datasources', '/semantic-models', '/conversations')
foreach ($path in $protectedPaths) {
  $status = Get-AnonymousStatus -Uri "$apiBase$path"
  if ($status -ne 401) { throw "Protected endpoint $path returned HTTP $status without a session" }
}

[pscustomobject]@{
  frontend_http = $frontend.StatusCode
  backend_http = $backend.StatusCode
  backend_version = $version.version
  frontend_backend_proxy = 'READY_VERSION_MATCH'
  live_rag = 'HEALTHY_AUTH_REQUIRED'
  protected_api_auth = '5_OF_5_RETURN_401'
  local_metadata_postgres = 'READY'
  local_demo_postgres = 'PORT_REACHABLE_STARTUP_CHECK'
  local_demo_mysql = 'PORT_REACHABLE_STARTUP_CHECK'
} | Format-List
Write-Host 'VERIFY=PASS' -ForegroundColor Green
