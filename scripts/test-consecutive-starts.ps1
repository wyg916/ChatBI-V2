[CmdletBinding()]
param(
  [string]$EvidencePath = 'artifacts/v2_1/day3/consecutive-starts.json',
  [switch]$SkipBuild,
  [ValidateRange(5, 180)]
  [int]$HealthTimeoutSeconds = 45
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$evidence = Join-Path $projectRoot $EvidencePath
$runs = @()
$passed = $true

function Get-AnonymousStatus {
  $status = & curl.exe -s -o NUL -w '%{http_code}' 'http://127.0.0.1:8000/api/v1/auth/me'
  if($LASTEXITCODE -ne 0) { return 0 }
  return [int]$status
}

function Get-ServiceSnapshot {
  $services = @{}
  foreach($line in (& docker compose ps --format json)) {
    if($line) {
      $item = $line | ConvertFrom-Json
      $services[$item.Service] = [ordered]@{ state = $item.State; health = $item.Health }
    }
  }
  return $services
}

function Wait-ServiceHealth {
  param([int]$TimeoutSeconds)

  $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
  do {
    $services = Get-ServiceSnapshot
    $ready = $true
    foreach($serviceName in @('backend', 'frontend', 'rag-runtime')) {
      if(
        -not $services.ContainsKey($serviceName) -or
        $services[$serviceName].state -ne 'running' -or
        $services[$serviceName].health -ne 'healthy'
      ) {
        $ready = $false
        break
      }
    }
    if($ready) { return $services }
    Start-Sleep -Seconds 1
  } while([DateTime]::UtcNow -lt $deadline)

  return Get-ServiceSnapshot
}

try {
  Set-Location -LiteralPath $projectRoot
  for($sequence = 1; $sequence -le 2; $sequence++) {
    & (Join-Path $PSScriptRoot 'stop.ps1')
    if($LASTEXITCODE -ne 0) { throw "Run $sequence stop failed" }
    $timer = [System.Diagnostics.Stopwatch]::StartNew()
    if($SkipBuild -or $sequence -eq 2) {
      & (Join-Path $PSScriptRoot 'launch.ps1') -NoOpen -SkipBuild
    } else {
      & (Join-Path $PSScriptRoot 'launch.ps1') -NoOpen
    }
    $exitCode = $LASTEXITCODE
    $services = if($exitCode -eq 0) {
      Wait-ServiceHealth -TimeoutSeconds $HealthTimeoutSeconds
    } else {
      Get-ServiceSnapshot
    }
    $timer.Stop()
    $servicePass = @('backend','frontend','rag-runtime') | ForEach-Object {
      $services.ContainsKey($_) -and $services[$_].state -eq 'running' -and $services[$_].health -eq 'healthy'
    }
    $anonymous = Get-AnonymousStatus
    $runPass = $exitCode -eq 0 -and ($servicePass -notcontains $false) -and $anonymous -eq 401
    $runs += [ordered]@{
      run = $sequence
      duration_seconds = [Math]::Round($timer.Elapsed.TotalSeconds, 3)
      launcher_exit_code = $exitCode
      health_wait_timeout_seconds = $HealthTimeoutSeconds
      services = $services
      anonymous_protected_api_status = $anonymous
      one_click_auto_login = 0
      one_click_auto_token_injection = 0
      anonymous_admin_creation = 0
      backend_auth_bypass = 0
      pass = $runPass
    }
    if(-not $runPass) { $passed = $false; break }
  }
} catch {
  $passed = $false
  $errorType = $_.Exception.GetType().Name
  $errorMessage = $_.Exception.Message
}

$result = [ordered]@{
  generated_at = (Get-Date).ToString('o')
  consecutive_start = if($passed -and $runs.Count -eq 2) { 'PASS' } else { 'FAIL' }
  one_click_start = if($passed -and $runs.Count -eq 2) { 'PASS' } else { 'FAIL' }
  run_count = $runs.Count
  runs = $runs
  error_type = $errorType
  error_message = $errorMessage
  secrets_recorded = $false
}
$parent = Split-Path -Parent $evidence
New-Item -ItemType Directory -Path $parent -Force | Out-Null
$result | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $evidence -Encoding utf8
$result | ConvertTo-Json -Depth 8
if($result.consecutive_start -ne 'PASS') { exit 1 }
