#!/usr/bin/env pwsh
# Deploy semantic model to Fabric via Fabric API

param(
    [string]$WorkspaceName = "Granini_Sell-Out_HORECA",
    [string]$ModelName = "RestaurantAnalytics",
    [string]$TmdlPath = "semantic-model\definition"
)

Write-Host "=== Power BI Semantic Model Deployment ===" -ForegroundColor Cyan

# Step 1: Find workspace ID
Write-Host "`nStep 1: Finding workspace..."
$wsResponse = az rest --method get --resource "https://api.fabric.microsoft.com" `
  --url "https://api.fabric.microsoft.com/v1/workspaces" --output json 2>&1

if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Failed to list workspaces" -ForegroundColor Red
    Write-Host $wsResponse
    exit 1
}

$ws = $wsResponse | ConvertFrom-Json
$workspace = $ws.value | Where-Object { $_.displayName -eq $WorkspaceName } | Select-Object -First 1

if (-not $workspace) {
    Write-Host "ERROR: Workspace not found: $WorkspaceName" -ForegroundColor Red
    exit 1
}

$wsId = $workspace.id
Write-Host "✓ Workspace: $WorkspaceName`n  ID: $wsId" -ForegroundColor Green

# Step 2: Encode TMDL files
Write-Host "Step 2: Encoding TMDL files..."

$pbismFile = "$TmdlPath\definition.pbism"
$dbFile = "$TmdlPath\database.tmdl"
$modelFile = "$TmdlPath\model.tmdl"

if (-not (Test-Path $pbismFile) -or -not (Test-Path $dbFile) -or -not (Test-Path $modelFile)) {
    Write-Host "ERROR: Missing TMDL files" -ForegroundColor Red
    Write-Host "  definition.pbism: $(Test-Path $pbismFile)"
    Write-Host "  database.tmdl: $(Test-Path $dbFile)"
    Write-Host "  model.tmdl: $(Test-Path $modelFile)"
    exit 1
}

$pbismContent = [System.IO.File]::ReadAllBytes($pbismFile)
$pbismB64 = [Convert]::ToBase64String($pbismContent)

$dbContent = [System.IO.File]::ReadAllText($dbFile)
$dbB64 = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($dbContent))

$modelContent = [System.IO.File]::ReadAllText($modelFile)
$modelB64 = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($modelContent))

Write-Host "✓ Encoded TMDL files" -ForegroundColor Green

# Step 3: Build definition payload
Write-Host "`nStep 3: Building definition payload..."

$definition = @{
    displayName = $ModelName
    description = "Semantic model for restaurant operations intelligence"
    definition = @{
        format = "TMDL"
        parts = @(
            @{
                path = "definition.pbism"
                payload = $pbismB64
                payloadType = "InlineBase64"
            },
            @{
                path = "definition/database.tmdl"
                payload = $dbB64
                payloadType = "InlineBase64"
            },
            @{
                path = "definition/model.tmdl"
                payload = $modelB64
                payloadType = "InlineBase64"
            }
        )
    }
}

$payload = $definition | ConvertTo-Json -Depth 10 -EncodingDepth 1

Write-Host "✓ Payload ready ($(($payload.Length / 1KB).ToString('F1')) KB)" -ForegroundColor Green

# Step 4: Create semantic model via Fabric API
Write-Host "`nStep 4: Creating semantic model..."
Write-Host "  POST https://api.fabric.microsoft.com/v1/workspaces/$wsId/semanticModels"

$createCmd = @(
    'az', 'rest',
    '--method', 'post',
    '--resource', 'https://api.fabric.microsoft.com',
    '--url', "https://api.fabric.microsoft.com/v1/workspaces/$wsId/semanticModels",
    '--headers', 'Content-Type=application/json',
    '--body', $payload,
    '--output', 'json'
)

$createResponse = & $createCmd 2>&1
$exitCode = $LASTEXITCODE

if ($exitCode -eq 0) {
    $result = $createResponse | ConvertFrom-Json
    Write-Host "✓ Semantic model created successfully!" -ForegroundColor Green
    Write-Host "  Name: $($result.displayName)"
    Write-Host "  ID: $($result.id)"
    Write-Host "  Path: https://fabric.microsoft.com/groups/$wsId/semanticmodels/$($result.id)"
    
    # Store IDs for later use
    @{
        workspaceId = $wsId
        modelId = $result.id
        modelName = $result.displayName
    } | ConvertTo-Json | Out-File ".fabric-ids.json"
    Write-Host "`n✓ IDs saved to .fabric-ids.json"
} else {
    Write-Host "ERROR: Failed to create semantic model" -ForegroundColor Red
    Write-Host "Exit code: $exitCode" -ForegroundColor Red
    Write-Host "Response:" -ForegroundColor Red
    Write-Host $createResponse
    exit 1
}

Write-Host "`n=== Deployment Complete ===" -ForegroundColor Green
