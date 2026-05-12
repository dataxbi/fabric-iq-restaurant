import argparse
import json

from fabric_client import FabricClient, FabricConfigError, read_bool_env, require_env
from eventhouse_schema import deploy_schema


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bootstrap Fabric resources for the restaurant demo")
    parser.add_argument("--workspace-name", default=None, help="Fabric workspace name")
    parser.add_argument("--lakehouse-name", default=None, help="Lakehouse display name")
    parser.add_argument("--eventhouse-name", default=None, help="Eventhouse display name")
    parser.add_argument("--kql-database-name", default=None, help="KQL database display name")
    parser.add_argument("--eventstream-name", default=None, help="Eventstream display name")
    parser.add_argument("--skip-schema", action="store_true", help="Do not create the Eventhouse tables")
    return parser


def main() -> None:
    args = build_parser().parse_args()

    workspace_name = args.workspace_name or require_env("FABRIC_WORKSPACE_NAME")
    lakehouse_name = args.lakehouse_name or require_env("FABRIC_LAKEHOUSE_NAME")
    eventhouse_name = args.eventhouse_name or require_env("FABRIC_EVENTHOUSE_NAME")
    database_name = args.kql_database_name or require_env("FABRIC_KQL_DATABASE_NAME")
    eventstream_name = args.eventstream_name or require_env("FABRIC_EVENTSTREAM_NAME")

    client = FabricClient()
    workspace = client.resolve_workspace(workspace_name)
    workspace_id = workspace["id"]

    lakehouse = client.ensure_item(workspace_id, "lakehouses", lakehouse_name)
    eventhouse = client.ensure_item(workspace_id, "eventhouses", eventhouse_name)
    database = client.create_or_get_eventhouse_database(workspace_id, eventhouse["id"], database_name)
    eventstream = client.ensure_item(workspace_id, "eventstreams", eventstream_name)

    schema_enabled = not args.skip_schema and read_bool_env("FABRIC_APPLY_EVENTHOUSE_SCHEMA", True)
    if schema_enabled:
        query_service_uri = client.get_eventhouse_query_service_uri(workspace_id, eventhouse["id"])
        deploy_schema(query_service_uri, database_name)

    summary = {
        "workspace": workspace_name,
        "workspaceId": workspace_id,
        "lakehouse": {"name": lakehouse_name, "id": lakehouse["id"]},
        "eventhouse": {"name": eventhouse_name, "id": eventhouse["id"]},
        "kqlDatabase": {"name": database_name, "id": database["id"]},
        "eventstream": {"name": eventstream_name, "id": eventstream["id"]},
        "schemaApplied": schema_enabled,
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    try:
        main()
    except FabricConfigError as exc:
        raise SystemExit(str(exc))

