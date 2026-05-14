import argparse
import base64
import json
import time
import uuid
from pathlib import Path

from fabric_client import FabricApiError, FabricClient, require_env


ROOT = Path(__file__).resolve().parents[1]
UDF_DIR = ROOT / "user_data_functions" / "restaurant_operations"


def inline_file(path: str, source: Path) -> dict:
    payload = base64.b64encode(source.read_bytes()).decode("ascii")
    return {"path": path, "payload": payload, "payloadType": "InlineBase64"}


def platform_part(display_name: str, description: str) -> dict:
    payload = {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json",
        "metadata": {"type": "UserDataFunction", "displayName": display_name, "description": description},
        "config": {"version": "2.0", "logicalId": str(uuid.uuid5(uuid.NAMESPACE_DNS, display_name))},
    }
    encoded = base64.b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8")).decode("ascii")
    return {"path": ".platform", "payload": encoded, "payloadType": "InlineBase64"}


def build_definition_parts(display_name: str) -> list[dict]:
    return [
        inline_file("definition.json", UDF_DIR / "definition.json"),
        inline_file("function_app.py", UDF_DIR / "function_app.py"),
        inline_file(r"resources\functions.json", UDF_DIR / "resources" / "functions.json"),
        platform_part(display_name, "Restaurant operations custom actions for Operations Agent"),
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create the restaurant Operations Agent User Data Function")
    parser.add_argument("--workspace-name", default=None, help="Fabric workspace name")
    parser.add_argument("--function-name", default="RestaurantOperationsActions", help="User Data Function item name")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    workspace_name = args.workspace_name or require_env("FABRIC_WORKSPACE_NAME")
    client = FabricClient()
    workspace = client.resolve_workspace(workspace_name)
    workspace_id = workspace["id"]
    parts = build_definition_parts(args.function_name)
    deadline = time.time() + 240
    while True:
        try:
            item = client.create_item_with_definition(
                workspace_id,
                args.function_name,
                "UserDataFunction",
                parts,
                description="Restaurant operations custom actions for Operations Agent",
                collection="userDataFunctions",
            )
            break
        except FabricApiError as exc:
            if "ItemDisplayNameNotAvailableYet" not in str(exc) or time.time() >= deadline:
                raise
            time.sleep(20)
    client.update_item_definition(
        workspace_id,
        item["id"],
        parts,
        update_metadata=True,
        collection="userDataFunctions",
    )
    print(
        json.dumps(
            {
                "workspace": workspace_name,
                "userDataFunction": {
                    "name": args.function_name,
                    "id": item["id"],
                    "type": item["type"],
                    "function": "recordReprioritizeOrder",
                },
                "manualFollowUp": [
                    "Open the User Data Function item in Fabric.",
                    "If the Functions explorer is empty, paste user_data_functions/restaurant_operations/function_app.py into the editor and publish.",
                    "Verify azure-eventhub is listed in Library management.",
                    "Set EVENT_HUB_CONNECTION_STRING inside function_app.py before publishing.",
                    "Enable or copy the public function URL for recordReprioritizeOrder.",
                    "Map the Operations Agent/Power Automate action parameters to the function request body.",
                    "Keep secrets out of git: never commit a real EVENT_HUB_CONNECTION_STRING value.",
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
