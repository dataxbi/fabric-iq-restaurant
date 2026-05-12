#!/bin/bash
# Deploy semantic model to Fabric

WORKSPACE_NAME="Granini_Sell-Out_HORECA"
MODEL_NAME="RestaurantAnalytics"
TMDL_PATH="semantic-model/definition"

echo "=== Semantic Model Deployment ==="
echo

# 1. Find workspace
echo "1. Finding workspace..."
WS_JSON=$(az rest --method get --resource "https://api.fabric.microsoft.com" \
  --url "https://api.fabric.microsoft.com/v1/workspaces" --output json)

WS_ID=$(echo "$WS_JSON" | jq -r ".value[] | select(.displayName==\"$WORKSPACE_NAME\") | .id")

if [ -z "$WS_ID" ]; then
    echo "ERROR: Workspace not found: $WORKSPACE_NAME"
    exit 1
fi

echo "✓ Workspace ID: $WS_ID"

# 2. Encode TMDL files
echo
echo "2. Encoding TMDL files..."
PBISM_B64=$(base64 -w 0 < "$TMDL_PATH/definition.pbism")
DB_B64=$(base64 -w 0 < "$TMDL_PATH/database.tmdl")
MODEL_B64=$(base64 -w 0 < "$TMDL_PATH/model.tmdl")

echo "✓ Files encoded"

# 3. Create payload
echo
echo "3. Building payload..."
cat > /tmp/semantic_model_payload.json << EOF
{
  "displayName": "$MODEL_NAME",
  "description": "Restaurant operations intelligence",
  "definition": {
    "format": "TMDL",
    "parts": [
      {
        "path": "definition.pbism",
        "payload": "$PBISM_B64",
        "payloadType": "InlineBase64"
      },
      {
        "path": "definition/database.tmdl",
        "payload": "$DB_B64",
        "payloadType": "InlineBase64"
      },
      {
        "path": "definition/model.tmdl",
        "payload": "$MODEL_B64",
        "payloadType": "InlineBase64"
      }
    ]
  }
}
EOF

echo "✓ Payload ready"

# 4. Create semantic model
echo
echo "4. Creating semantic model..."
echo "   POST /v1/workspaces/$WS_ID/semanticModels"

RESPONSE=$(az rest --method post \
  --resource "https://api.fabric.microsoft.com" \
  --url "https://api.fabric.microsoft.com/v1/workspaces/$WS_ID/semanticModels" \
  --headers "Content-Type=application/json" \
  --body @/tmp/semantic_model_payload.json --output json)

MODEL_ID=$(echo "$RESPONSE" | jq -r '.id')

if [ "$MODEL_ID" != "null" ] && [ ! -z "$MODEL_ID" ]; then
    echo "✓ Model created!"
    echo "  ID: $MODEL_ID"
    MODEL_NAME_RESULT=$(echo "$RESPONSE" | jq -r '.displayName')
    echo "  Name: $MODEL_NAME_RESULT"
    
    # Save IDs
    echo "{\"workspaceId\": \"$WS_ID\", \"modelId\": \"$MODEL_ID\"}" > .fabric-ids.json
    echo
    echo "✓ IDs saved to .fabric-ids.json"
else
    echo "ERROR: Failed to create model"
    echo "$RESPONSE"
    exit 1
fi

echo
echo "=== Deployment Complete ==="
