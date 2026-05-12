#!/usr/bin/env pwsh
param(
    [string]$WorkspaceName = $env:FABRIC_WORKSPACE_NAME,
    [string]$LakehouseName = $env:FABRIC_LAKEHOUSE_NAME,
    [string]$ModelName = "RestaurantAnalytics_DirectLake",
    [string]$DefinitionPath = "semantic-model\definition",
    [string]$GeneratedPath = ".generated\semantic-model-directlake\definition",
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$FabricResource = "https://api.fabric.microsoft.com"
$FabricApi = "https://api.fabric.microsoft.com/v1"

if ([string]::IsNullOrWhiteSpace($WorkspaceName)) {
    throw "WorkspaceName is required. Pass -WorkspaceName or set FABRIC_WORKSPACE_NAME."
}

if ([string]::IsNullOrWhiteSpace($LakehouseName)) {
    throw "LakehouseName is required. Pass -LakehouseName or set FABRIC_LAKEHOUSE_NAME."
}

function Get-FabricToken {
    $token = az account get-access-token --resource $FabricResource --query accessToken -o tsv
    if ([string]::IsNullOrWhiteSpace($token)) {
        throw "Could not acquire Fabric API token. Run az login first."
    }
    return $token
}

function Invoke-FabricRest {
    param(
        [ValidateSet("GET", "POST", "DELETE")]
        [string]$Method,
        [string]$Uri,
        [object]$Body = $null
    )

    $headers = @{
        Authorization = "Bearer $(Get-FabricToken)"
        Accept = "application/json"
    }

    $params = @{
        Method = $Method
        Uri = $Uri
        Headers = $headers
        ResponseHeadersVariable = "responseHeaders"
        StatusCodeVariable = "statusCode"
    }

    if ($null -ne $Body) {
        $headers["Content-Type"] = "application/json"
        $params.Body = ($Body | ConvertTo-Json -Depth 20)
    }

    $result = Invoke-RestMethod @params
    return [pscustomobject]@{
        StatusCode = $statusCode
        Headers = $responseHeaders
        Body = $result
    }
}

function Wait-FabricOperation {
    param([string]$Location)

    do {
        Start-Sleep -Seconds 5
        $operation = Invoke-FabricRest -Method GET -Uri $Location
        $status = $operation.Body.status
    } while ($status -and $status -notin @("Succeeded", "Failed", "Canceled"))

    if ($status -ne "Succeeded") {
        throw "Fabric operation did not succeed: $($operation.Body | ConvertTo-Json -Depth 10)"
    }
}

function Get-SingleByName {
    param(
        [array]$Items,
        [string]$DisplayName,
        [string]$ItemKind
    )

    $matches = @($Items | Where-Object { $_.displayName -eq $DisplayName })
    if ($matches.Count -eq 0) {
        throw "$ItemKind not found: $DisplayName"
    }
    if ($matches.Count -gt 1) {
        throw "More than one $ItemKind matched name: $DisplayName"
    }
    return $matches[0]
}

function New-DefinitionPart {
    param(
        [string]$SourceRoot,
        [string]$FilePath
    )

    $relativePath = [System.IO.Path]::GetRelativePath($SourceRoot, $FilePath)
    if ($relativePath -eq "definition.pbism") {
        $partPath = "definition.pbism"
    }
    else {
        $partPath = "definition/$($relativePath -replace '\\', '/')"
    }

    return @{
        path = $partPath
        payload = [Convert]::ToBase64String([System.IO.File]::ReadAllBytes($FilePath))
        payloadType = "InlineBase64"
    }
}

Write-Host "Resolving Fabric workspace and lakehouse..." -ForegroundColor Cyan
$workspaces = (Invoke-FabricRest -Method GET -Uri "$FabricApi/workspaces").Body.value
$workspace = Get-SingleByName -Items $workspaces -DisplayName $WorkspaceName -ItemKind "Workspace"

if ([string]::IsNullOrWhiteSpace($workspace.capacityId)) {
    throw "Workspace '$WorkspaceName' is not assigned to a Fabric capacity."
}

$lakehouses = (Invoke-FabricRest -Method GET -Uri "$FabricApi/workspaces/$($workspace.id)/lakehouses").Body.value
$lakehouse = Get-SingleByName -Items $lakehouses -DisplayName $LakehouseName -ItemKind "Lakehouse"

Write-Host "Preparing generated Direct Lake TMDL..." -ForegroundColor Cyan
if (Test-Path $GeneratedPath) {
    Remove-Item -Path $GeneratedPath -Recurse -Force
}
New-Item -ItemType Directory -Path $GeneratedPath -Force | Out-Null
Copy-Item -Path (Join-Path $DefinitionPath "*") -Destination $GeneratedPath -Recurse -Force

$modelPath = Join-Path $GeneratedPath "model.tmdl"
$modelContent = Get-Content -Raw -Path $modelPath
$modelContent = $modelContent.Replace("<workspace-id>", $workspace.id).Replace("<lakehouse-id>", $lakehouse.id)
Set-Content -Path $modelPath -Value $modelContent -NoNewline

$parts = @()
$parts += New-DefinitionPart -SourceRoot $GeneratedPath -FilePath (Join-Path $GeneratedPath "definition.pbism")
Get-ChildItem -Path $GeneratedPath -Recurse -File -Filter "*.tmdl" |
    Sort-Object FullName |
    ForEach-Object { $parts += New-DefinitionPart -SourceRoot $GeneratedPath -FilePath $_.FullName }

$existingModels = (Invoke-FabricRest -Method GET -Uri "$FabricApi/workspaces/$($workspace.id)/semanticModels").Body.value
$existing = @($existingModels | Where-Object { $_.displayName -eq $ModelName })
if ($existing.Count -gt 0) {
    if (-not $Force) {
        throw "Semantic model '$ModelName' already exists. Use -Force to delete and recreate it."
    }

    Write-Host "Deleting existing semantic model '$ModelName'..." -ForegroundColor Yellow
    foreach ($model in $existing) {
        $delete = Invoke-FabricRest -Method DELETE -Uri "$FabricApi/workspaces/$($workspace.id)/semanticModels/$($model.id)"
        $location = $delete.Headers.Location
        if ($location) {
            Wait-FabricOperation -Location $location
        }
    }
}

Write-Host "Creating Direct Lake semantic model '$ModelName'..." -ForegroundColor Cyan
$body = @{
    displayName = $ModelName
    description = "Restaurant operations semantic model in Direct Lake mode"
    definition = @{
        format = "TMDL"
        parts = $parts
    }
}

$create = Invoke-FabricRest -Method POST -Uri "$FabricApi/workspaces/$($workspace.id)/semanticModels" -Body $body
$location = $create.Headers.Location
if ($location) {
    Wait-FabricOperation -Location $location
}

$models = (Invoke-FabricRest -Method GET -Uri "$FabricApi/workspaces/$($workspace.id)/semanticModels").Body.value
$created = Get-SingleByName -Items $models -DisplayName $ModelName -ItemKind "Semantic model"

$metadataPath = Join-Path (Split-Path $GeneratedPath -Parent) "deployment-result.json"
@{
    workspaceName = $WorkspaceName
    workspaceId = $workspace.id
    lakehouseName = $LakehouseName
    lakehouseId = $lakehouse.id
    semanticModelName = $ModelName
    semanticModelId = $created.id
} | ConvertTo-Json | Set-Content -Path $metadataPath

Write-Host "Direct Lake semantic model created." -ForegroundColor Green
Write-Host "  Name: $($created.displayName)"
Write-Host "  ID: $($created.id)"
Write-Host "  Metadata: $metadataPath"
