import argparse
import base64
import json
import time
import uuid

from fabric_client import FabricApiError, FabricClient, FabricConfigError, require_env


def to_inline_base64(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Configure Eventstream topology (CustomEndpoint/SampleData source -> Eventhouse destination)"
    )
    parser.add_argument("--workspace-name", default=None, help="Fabric workspace name")
    parser.add_argument("--eventstream-name", default=None, help="Eventstream display name")
    parser.add_argument("--eventhouse-name", default=None, help="Eventhouse display name")
    parser.add_argument("--kql-database-name", default=None, help="KQL database display name")
    parser.add_argument("--target-table", default="order_events", help="KQL destination table name")
    parser.add_argument(
        "--source-type",
        default="CustomEndpoint",
        choices=["CustomEndpoint", "SampleData"],
        help="Source type to configure in Eventstream",
    )
    parser.add_argument("--sample-type", default="Bicycles", help="SampleData type when --source-type=SampleData")
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Delete existing Eventstream and recreate it with definition",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    workspace_name = args.workspace_name or require_env("FABRIC_WORKSPACE_NAME")
    eventstream_name = args.eventstream_name or require_env("FABRIC_EVENTSTREAM_NAME")
    eventhouse_name = args.eventhouse_name or require_env("FABRIC_EVENTHOUSE_NAME")
    database_name = args.kql_database_name or require_env("FABRIC_KQL_DATABASE_NAME")

    client = FabricClient()
    workspace = client.resolve_workspace(workspace_name)
    workspace_id = workspace["id"]

    eventstream = client.find_item(workspace_id, "eventstreams", eventstream_name)
    if not eventstream and not args.recreate:
        raise FabricConfigError(f"Eventstream not found: {eventstream_name}")

    eventhouse = client.find_item(workspace_id, "eventhouses", eventhouse_name)
    if not eventhouse:
        raise FabricConfigError(f"Eventhouse not found: {eventhouse_name}")

    kql_database = client.find_item(workspace_id, "kqlDatabases", database_name)
    if not kql_database:
        raise FabricConfigError(f"KQL database not found: {database_name}")

    source_name = "RestaurantSource"
    default_stream_name = f"{eventstream_name}-stream"
    destination_name = "EventhouseDestination"

    source: dict = {
        "name": source_name,
        "type": args.source_type,
        "properties": {},
    }
    if args.source_type == "SampleData":
        source["properties"] = {"type": args.sample_type}

    eventstream_definition = {
        "sources": [source],
        "destinations": [
            {
                "name": destination_name,
                "type": "Eventhouse",
                "properties": {
                    "dataIngestionMode": "ProcessedIngestion",
                    "workspaceId": workspace_id,
                    "itemId": kql_database["id"],
                    "databaseName": database_name,
                    "tableName": args.target_table,
                    "inputSerialization": {
                        "type": "Json",
                        "properties": {"encoding": "UTF8"},
                    },
                },
                "inputNodes": [{"name": default_stream_name}],
            }
        ],
        "streams": [
            {
                "name": default_stream_name,
                "type": "DefaultStream",
                "properties": {},
                "inputNodes": [{"name": source_name}],
            }
        ],
        "operators": [],
        "compatibilityLevel": "1.1",
    }

    platform_definition = {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json",
        "metadata": {
            "type": "Eventstream",
            "displayName": eventstream_name,
        },
        "config": {
            "version": "2.0",
            "logicalId": str(uuid.UUID(int=0)),
        },
    }

    parts = [
        {
            "path": "eventstream.json",
            "payload": to_inline_base64(eventstream_definition),
            "payloadType": "InlineBase64",
        },
        {
            "path": ".platform",
            "payload": to_inline_base64(platform_definition),
            "payloadType": "InlineBase64",
        },
    ]

    if args.recreate:
        if eventstream:
            client.delete_item(workspace_id, "eventstreams", eventstream["id"])
        attempts = 0
        while True:
            attempts += 1
            try:
                eventstream = client.create_item_with_definition(
                    workspace_id=workspace_id,
                    display_name=eventstream_name,
                    item_type="Eventstream",
                    definition_parts=parts,
                    description="Restaurant demo eventstream with sample source and Eventhouse destination",
                )
                break
            except FabricApiError as exc:
                if "ItemDisplayNameNotAvailableYet" in str(exc) and attempts < 12:
                    time.sleep(10)
                    continue
                raise
    else:
        client.update_eventstream_definition(workspace_id, eventstream["id"], parts, update_metadata=True)
    print(
        json.dumps(
            {
                "workspace": workspace_name,
                "eventstream": eventstream_name,
                "eventstreamId": eventstream["id"],
                "source": {
                    "type": args.source_type,
                    "name": source_name,
                    "sampleType": args.sample_type if args.source_type == "SampleData" else None,
                },
                "destination": {
                    "type": "Eventhouse",
                    "eventhouseName": eventhouse_name,
                    "eventhouseId": eventhouse["id"],
                    "kqlDatabaseId": kql_database["id"],
                    "databaseName": database_name,
                    "tableName": args.target_table,
                },
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
