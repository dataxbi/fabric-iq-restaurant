#!/usr/bin/env pwsh
# Deploy semantic model to Fabric

$WorkspaceName = "Granini_Sell-Out_HORECA"
$ModelName = "RestaurantAnalytics"
$TmdlPath = "semantic-model\definition"

Write-Host "=== Semantic Model Deployment ===" -ForegroundColor Cyan

# Find workspace
Write-Host "`n1. Finding workspace..."
$wsJson = az rest --method get --resource "https://api.fabric.microsoft.com" `
  --url "https://api.fabric.microsoft.com/v1/workspaces" --output json
$ws = $wsJson | ConvertFrom-Json
$workspace = $ws.value | Where-Object { $_.displayName -eq $WorkspaceName }
$wsId = $workspace.id
Write-Host "✓ Workspace ID: $wsId" -ForegroundColor Green

# Encode files
Write-Host "`n2. Encoding TMDL files..."
$pbismContent = [System.IO.File]::ReadAllBytes("$TmdlPath\definition.pbism")
$pbismB64 = [Convert]::ToBase64String($pbismContent)

$dbContent = [System.IO.File]::ReadAllText("$TmdlPath\database.tmdl")
$dbB64 = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($dbContent))

$modelContent = [System.IO.File]::ReadAllText("$TmdlPath\model.tmdl")
$modelB64 = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($modelContent))

Write-Host "✓ Files encoded" -ForegroundColor Green

# Create payload (using @{} to build object, then ConvertTo-Json with -Depth)
Write-Host "`n3. Building payload..."
$parts = @(
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

$body = @{
    displayName = $ModelName
    description = "Restaurant operations intelligence"
    definition = @{
        format = "TMDL"
        parts = $parts
    }
} | ConvertTo-Json -Depth 10

Write-Host "✓ Payload ready" -ForegroundColor Green

# Create model
Write-Host "`n4. Creating semantic model..."
Write-Host "   POST /v1/workspaces/$wsId/semanticModels"

$response = az rest --method post `
  --resource "https://api.fabric.microsoft.com" `
  --url "https://api.fabric.microsoft.com/v1/workspaces/$wsId/semanticModels" `
  --headers "Content-Type=application/json" `
  --body $body --output json

$model = $response | ConvertFrom-Json
Write-Host "✓ Model created!" -ForegroundColor Green
Write-Host "  ID: $($model.id)"
Write-Host "  Name: $($model.displayName)"

# Save IDs
@{
    workspaceId = $wsId
    modelId = $model.id
} | ConvertTo-Json | Out-File ".fabric-ids.json"
Write-Host "`n✓ IDs saved to .fabric-ids.json" -ForegroundColor Green
