import argparse

from fabric_client import FabricClient, FabricConfigError, read_bool_env, require_env, run_kusto_management


TABLES = [
    (
        "order_events",
        "event_time:datetime, event_id:string, order_id:string, channel:string, event_name:string, order_status:string, station_id:string, delay_minutes:real, payload:dynamic",
    ),
    (
        "kitchen_events",
        "event_time:datetime, event_id:string, station_id:string, station_status:string, queue_size:long, capacity:long, payload:dynamic",
    ),
    (
        "inventory_events",
        "event_time:datetime, event_id:string, ingredient_id:string, stock_pct:real, threshold_pct:real, payload:dynamic",
    ),
    (
        "agent_events",
        "event_time:datetime, event_id:string, recommendation_id:string, order_id:string, priority:int, confidence:real, payload:dynamic",
    ),
    (
        "approval_events",
        "event_time:datetime, event_id:string, recommendation_id:string, approver:string, approval_status:string, payload:dynamic",
    ),
    (
        "action_events",
        "event_time:datetime, event_id:string, action_id:string, action_type:string, action_status:string, payload:dynamic",
    ),
]


def deploy_schema(query_service_uri: str, database_name: str) -> None:
    for table_name, columns in TABLES:
        run_kusto_management(query_service_uri, database_name, f".create-merge table {table_name} ({columns})")
        run_kusto_management(query_service_uri, database_name, f".alter table {table_name} policy streamingingestion enable")
        run_kusto_management(
            query_service_uri,
            database_name,
            f".alter table {table_name} policy retention '{{\"SoftDeletePeriod\":\"30.00:00:00\",\"Recoverability\":\"Enabled\"}}'",
    )
        run_kusto_management(query_service_uri, database_name, f".alter table {table_name} policy caching hot = 7d")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create the Eventhouse tables for the restaurant demo")
    parser.add_argument("--workspace-name", default=None, help="Fabric workspace name")
    parser.add_argument("--eventhouse-name", default=None, help="Eventhouse display name")
    parser.add_argument("--kql-database-name", default=None, help="KQL database display name")
    parser.add_argument("--skip-policies", action="store_true", help="Only create tables, skip policies")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    workspace_name = args.workspace_name or require_env("FABRIC_WORKSPACE_NAME")
    eventhouse_name = args.eventhouse_name or require_env("FABRIC_EVENTHOUSE_NAME")
    database_name = args.kql_database_name or require_env("FABRIC_KQL_DATABASE_NAME")

    client = FabricClient()
    workspace = client.resolve_workspace(workspace_name)
    eventhouse = client.find_item(workspace["id"], "eventhouses", eventhouse_name)
    if not eventhouse:
        raise FabricConfigError(f"Eventhouse not found: {eventhouse_name}")

    query_service_uri = client.get_eventhouse_query_service_uri(workspace["id"], eventhouse["id"])
    if args.skip_policies or not read_bool_env("FABRIC_APPLY_EVENTHOUSE_SCHEMA", True):
        for table_name, columns in TABLES:
            run_kusto_management(query_service_uri, database_name, f".create-merge table {table_name} ({columns})")
        print("Table creation completed.")
        return

    deploy_schema(query_service_uri, database_name)
    print("Table creation and policies completed.")


if __name__ == "__main__":
    main()

