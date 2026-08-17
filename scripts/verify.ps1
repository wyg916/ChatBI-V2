$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$backendPort = if($env:CHATBI_BACKEND_PORT) { $env:CHATBI_BACKEND_PORT } else { '8000' }
$frontendPort = if($env:CHATBI_FRONTEND_PORT) { $env:CHATBI_FRONTEND_PORT } else { '5173' }
$apiBase = "http://127.0.0.1:${backendPort}/api/v1"

$backend = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:${backendPort}/health" -TimeoutSec 5
$frontend = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:${frontendPort}/" -TimeoutSec 5
$version = Invoke-RestMethod -Uri "$apiBase/version" -TimeoutSec 5
$sources = Invoke-RestMethod -Uri "$apiBase/datasources" -TimeoutSec 5
$sourceResults = @{}
foreach ($source in $sources) {
  $result = Invoke-RestMethod -Method Post -Uri "$apiBase/datasources/$($source.id)/test" -TimeoutSec 10
  if (-not $result.success) { throw "$($source.type) datasource connection failed" }
  $sourceResults[$source.type] = 'READY'
}
if (-not $sourceResults.ContainsKey('postgresql') -or -not $sourceResults.ContainsKey('mysql')) {
  throw 'PostgreSQL/MySQL demo datasources are not both configured'
}

[pscustomobject]@{
  frontend_http = $frontend.StatusCode
  backend_http = $backend.StatusCode
  backend_version = $version.version
  local_metadata_postgres = 'READY'
  local_demo_postgres = $sourceResults['postgresql']
  local_demo_mysql = $sourceResults['mysql']
} | Format-List
