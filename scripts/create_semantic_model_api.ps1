#!/usr/bin/env pwsh
# Create Power BI semantic model via Fabric API

param(
    [string]$WorkspaceName = "Fabric_IQ_Restaurant",
    [string]$ModelName = "RestaurantAnalytics"
)

# Step 1: Find workspace ID
Write-Host "Finding workspace: $WorkspaceName"
$wsResponse = az rest --method get --resource "https://api.fabric.microsoft.com" `
  --url "https://api.fabric.microsoft.com/v1/workspaces" --output json

$ws = $wsResponse | ConvertFrom-Json
$workspace = $ws.value | Where-Object { $_.displayName -eq $WorkspaceName } | Select-Object -First 1

if (-not $workspace) {
    throw "Workspace not found: $WorkspaceName"
}

$wsId = $workspace.id
Write-Host "✓ Workspace ID: $wsId"

# Step 2: Read and base64-encode TMDL files
Write-Host "Encoding TMDL files..."

$pbismContent = [System.IO.File]::ReadAllBytes("semantic-model\definition\definition.pbism")
$pbismB64 = [Convert]::ToBase64String($pbismContent)

$dbContent = [System.IO.File]::ReadAllText("semantic-model\definition\database.tmdl")
$dbB64 = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($dbContent))

Write-Host "✓ Encoded pbism and database.tmdl"

# Step 3: Create minimal definition payload
$payload = @{
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
            }
        )
    }
} | ConvertTo-Json -Depth 10

# Step 4: Create semantic model
Write-Host "Creating semantic model..."
$createResponse = az rest --method post --verbose `
  --resource "https://api.fabric.microsoft.com" `
  --url "https://api.fabric.microsoft.com/v1/workspaces/$wsId/semanticModels" `
  --headers "Content-Type=application/json" `
  --body $payload --output json 2>&1

Write-Host "Response:"
Write-Host $createResponse

# Extract model ID if successful
$result = $createResponse | ConvertFrom-Json -ErrorAction SilentlyContinue
if ($result.id) {
    Write-Host "✓ Semantic model created: $($result.displayName) ($($result.id))"
} else {
    Write-Host "⚠ Check response above for status"
}
