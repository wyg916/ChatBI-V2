[CmdletBinding()]
param([string]$EnvFile = '')

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'deployment\ChatBI.Deployment.ps1')
$resolvedEnv = Resolve-ChatBIEnvFile -EnvFile $EnvFile
$configuration = Assert-ChatBIConfiguration -EnvFile $resolvedEnv
$values = $configuration.Values
$apiBase = "http://127.0.0.1:$($configuration.BackendPort)/api/v1"
$session = [Microsoft.PowerShell.Commands.WebRequestSession]::new()

function Get-SmokeValue {
  param([string]$Name, [string]$Default = '')
  $value = Get-ChatBIValue -Values $values -Name $Name -Default $Default
  if (Test-ChatBIPlaceholder -Value $value) { throw "$Name is required for the enterprise datasource smoke" }
  return $value
}

function Invoke-ChatBIJsonPost {
  param([string]$Path, $Body)
  return Invoke-RestMethod -Method Post -Uri "$apiBase$Path" -ContentType 'application/json' -Body ($Body | ConvertTo-Json -Depth 20) -WebSession $session -TimeoutSec 90
}

function Invoke-ChatBIFileUpload {
  param([Parameter(Mandatory = $true)][string]$ConversationId, [Parameter(Mandatory = $true)][string]$Path)
  $handler = [Net.Http.HttpClientHandler]::new()
  $handler.CookieContainer = $session.Cookies
  $client = [Net.Http.HttpClient]::new($handler)
  $multipart = [Net.Http.MultipartFormDataContent]::new()
  try {
    $multipart.Add([Net.Http.StringContent]::new($ConversationId), 'conversation_id')
    $fileContent = [Net.Http.ByteArrayContent]::new([IO.File]::ReadAllBytes($Path))
    $fileContent.Headers.ContentType = [Net.Http.Headers.MediaTypeHeaderValue]::new('text/csv')
    $multipart.Add($fileContent, 'file', [IO.Path]::GetFileName($Path))
    $response = $client.PostAsync("$apiBase/attachments", $multipart).GetAwaiter().GetResult()
    $body = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
    if (-not $response.IsSuccessStatusCode) {
      throw "File upload failed with HTTP $([int]$response.StatusCode): $body"
    }
    return $body | ConvertFrom-Json
  } finally {
    $multipart.Dispose()
    $client.Dispose()
    $handler.Dispose()
  }
}

try {
  $adminPassword = Get-SmokeValue -Name 'CHATBI_BOOTSTRAP_ADMIN_PASSWORD'
  $null = Invoke-ChatBIJsonPost -Path '/auth/login' -Body @{ email = 'admin@chatbi.local'; password = $adminPassword; remember = $false }
  $me = Invoke-RestMethod -Uri "$apiBase/auth/me" -WebSession $session -TimeoutSec 10
  if (-not $me.authenticated) { throw 'Login did not establish an authenticated session' }
  Write-Host 'LOGIN_SMOKE=PASS'

  $datasource = Invoke-ChatBIJsonPost -Path '/datasources' -Body @{
    name = 'Fresh PostgreSQL API Smoke'
    type = 'postgresql'
    host = Get-SmokeValue -Name 'CHATBI_SMOKE_DATASOURCE_HOST' -Default 'host.docker.internal'
    port = [int](Get-SmokeValue -Name 'CHATBI_SMOKE_DATASOURCE_PORT' -Default '5432')
    database = Get-SmokeValue -Name 'CHATBI_SMOKE_DATASOURCE_DATABASE'
    username = Get-SmokeValue -Name 'CHATBI_SMOKE_DATASOURCE_USERNAME'
    password = Get-SmokeValue -Name 'CHATBI_SMOKE_DATASOURCE_PASSWORD'
    ssl = $false
    schema = Get-SmokeValue -Name 'CHATBI_SMOKE_DATASOURCE_SCHEMA'
  }
  $connection = Invoke-ChatBIJsonPost -Path "/datasources/$($datasource.id)/test" -Body @{}
  if (-not $connection.success) { throw $connection.message }
  Write-Host 'DATASOURCE_CONNECT=PASS'
  $sync = Invoke-ChatBIJsonPost -Path "/datasources/$($datasource.id)/sync" -Body @{}
  if (-not $sync.success -or $sync.tables -lt 1 -or $sync.columns -lt 1) { throw 'Schema sync returned no usable catalog tables/columns' }
  Write-Host "SCHEMA_SYNC=PASS TABLES=$($sync.tables) COLUMNS=$($sync.columns)"
  Write-Host 'CATALOG_SYNC=PASS'

  $table = Get-SmokeValue -Name 'CHATBI_SMOKE_TABLE' -Default 'orders'
  $primaryKey = Get-SmokeValue -Name 'CHATBI_SMOKE_PRIMARY_KEY' -Default 'order_id'
  $metricColumn = Get-SmokeValue -Name 'CHATBI_SMOKE_METRIC_COLUMN' -Default 'revenue'
  $timeColumn = Get-SmokeValue -Name 'CHATBI_SMOKE_TIME_COLUMN' -Default 'order_date'
  $dimensionColumn = Get-SmokeValue -Name 'CHATBI_SMOKE_DIMENSION_COLUMN' -Default 'region_id'
  $model = Invoke-ChatBIJsonPost -Path '/semantic-models' -Body @{
    name = 'Fresh PostgreSQL Semantic Binding'; description = 'Created through the public API during deployment smoke'; datasource_id = $datasource.id
  }
  $null = Invoke-ChatBIJsonPost -Path "/semantic-models/$($model.id)/entities" -Body @{
    name = $table; source_table = $table; primary_key = $primaryKey; time_dimension = $timeColumn
  }
  $null = Invoke-ChatBIJsonPost -Path "/semantic-models/$($model.id)/metrics" -Body @{
    name = 'revenue'; label = '收入'; description = '部署验证收入'; expression = "$table.$metricColumn"; aggregation = 'SUM'; filters = @()
  }
  $null = Invoke-ChatBIJsonPost -Path "/semantic-models/$($model.id)/dimensions" -Body @{
    name = 'region'; label = '地区'; source_column = "$table.$dimensionColumn"; type = 'STRING'
  }
  $null = Invoke-ChatBIJsonPost -Path "/semantic-models/$($model.id)/business-terms" -Body @{
    term = '收入'; synonyms = @('营收', '销售额'); definition = '订单收入总额'; mapped_object = 'metric.revenue'
  }
  $published = Invoke-ChatBIJsonPost -Path "/semantic-models/$($model.id)/publish" -Body @{}
  if (-not $published.success) { throw 'Semantic model publish failed' }
  Write-Host 'SEMANTIC_BINDING=PASS'

  $query = Invoke-ChatBIJsonPost -Path '/ask' -Body @{
    question = '统计收入'; datasource_id = $datasource.id; semantic_model_id = $model.id; row_limit = 50
  }
  if ($query.status -ne 'SUCCEEDED' -or $query.oracle.status -ne 'PASSED') { throw "Core query failed with status $($query.status)" }
  Write-Host 'CORE_CHATBI_SMOKE=PASS'

  $rag = Invoke-ChatBIJsonPost -Path '/analysis' -Body @{ question = '收入指标口径是什么'; route = 'KNOWLEDGE_QUERY' }
  if ($rag.status -ne 'SUCCEEDED' -or -not $rag.primary.citations) { throw 'RAG smoke returned no verified citation' }
  Write-Host 'RAG_SMOKE=PASS'

  $conversation = Invoke-ChatBIJsonPost -Path '/conversations' -Body @{ title = 'Deployment file smoke' }
  $temporary = [IO.Path]::Combine([IO.Path]::GetTempPath(), "chatbi-smoke-$([Guid]::NewGuid().ToString('N')).csv")
  [IO.File]::WriteAllText($temporary, "region,revenue`nEast,10`nWest,20`n", [Text.UTF8Encoding]::new($false))
  try {
    $fileResult = Invoke-ChatBIFileUpload -ConversationId $conversation.id -Path $temporary
  } finally { Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue }
  if ($fileResult.status -ne 'READY') { throw 'File upload/extraction smoke failed' }
  Write-Host 'FILE_SMOKE=PASS'

  $agent = Invoke-ChatBIJsonPost -Path '/analysis' -Body @{
    question = '请综合分析收入并结合口径给出结论'; route = 'COMPLEX_ANALYSIS'; datasource_id = $datasource.id; semantic_model_id = $model.id
  }
  if ($agent.status -ne 'SUCCEEDED' -or -not $agent.primary.trace_complete) { throw 'Bounded Agent smoke failed' }
  Write-Host 'AGENT_SMOKE=PASS'
  Write-Host 'ENTERPRISE_SMOKE=PASS' -ForegroundColor Green
  exit 0
} catch {
  Write-Host 'ENTERPRISE_SMOKE=FAIL' -ForegroundColor Red
  Write-Host $_.Exception.Message
  exit 1
}
