$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot

$backend = Invoke-WebRequest -UseBasicParsing -Uri 'http://localhost:8000/health' -TimeoutSec 5
$frontend = Invoke-WebRequest -UseBasicParsing -Uri 'http://localhost:5173/' -TimeoutSec 5
$version = Invoke-RestMethod -Uri 'http://localhost:8000/api/v1/version' -TimeoutSec 5
$sources = Invoke-RestMethod -Uri 'http://localhost:8000/api/v1/datasources' -TimeoutSec 5
$sourceResults = @{}
foreach ($source in $sources) {
  $result = Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/v1/datasources/$($source.id)/test" -TimeoutSec 10
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
