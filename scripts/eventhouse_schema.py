import argparse

from fabric_client import FabricClient, FabricConfigError, read_bool_env, require_env, run_kusto_management


TABLES = [
    (
        "raw_restaurant_events",
        "event_time:datetime, event_id:string, event_name:string, entity_type:string, entity_id:string, order_id:string, station_id:string, ingredient_id:string, channel:string, severity:string, payload:dynamic",
    ),
    (
        "order_events",
        "event_time:datetime, event_id:string, order_id:string, channel:string, event_name:string, order_status:string, station_id:string, delay_minutes:real, severity:string, payload:dynamic",
    ),
    (
        "kitchen_events",
        "event_time:datetime, event_id:string, station_id:string, station_status:string, queue_size:long, capacity:long, severity:string, payload:dynamic",
    ),
    (
        "inventory_events",
        "event_time:datetime, event_id:string, ingredient_id:string, stock_pct:real, threshold_pct:real, severity:string, payload:dynamic",
    ),
    (
        "agent_events",
        "event_time:datetime, event_id:string, recommendation_id:string, order_id:string, priority:int, confidence:real, severity:string, payload:dynamic",
    ),
    (
        "approval_events",
        "event_time:datetime, event_id:string, recommendation_id:string, approver:string, approval_status:string, severity:string, payload:dynamic",
    ),
    (
        "action_events",
        "event_time:datetime, event_id:string, action_id:string, action_type:string, action_status:string, severity:string, payload:dynamic",
    ),
]

FUNCTIONS = [
    (
        "RouteOrderEvents",
        """
raw_restaurant_events
| where event_name in ("order.created", "order.prep.delayed", "customer.sentiment.signal", "payment.completed")
| project
    event_time,
    event_id,
    order_id,
    channel,
    event_name,
    order_status = tostring(payload.order_status),
    station_id,
    delay_minutes = todouble(payload.delay_minutes),
    severity,
    payload
""".strip(),
    ),
    (
        "RouteKitchenEvents",
        """
raw_restaurant_events
| where event_name == "kitchen.station.updated"
| project
    event_time,
    event_id,
    station_id,
    station_status = tostring(payload.station_status),
    queue_size = tolong(payload.queue_size),
    capacity = tolong(payload.capacity),
    severity,
    payload
""".strip(),
    ),
    (
        "RouteInventoryEvents",
        """
raw_restaurant_events
| where event_name == "inventory.level.changed"
| project
    event_time,
    event_id,
    ingredient_id,
    stock_pct = todouble(payload.stock_pct),
    threshold_pct = todouble(payload.threshold_pct),
    severity,
    payload
""".strip(),
    ),
    (
        "RouteAgentEvents",
        """
raw_restaurant_events
| where event_name startswith "agent."
| project
    event_time,
    event_id,
    recommendation_id = tostring(payload.recommendation_id),
    order_id,
    priority = toint(payload.priority),
    confidence = todouble(payload.confidence),
    severity,
    payload
""".strip(),
    ),
    (
        "RouteApprovalEvents",
        """
raw_restaurant_events
| where event_name startswith "approval."
| project
    event_time,
    event_id,
    recommendation_id = tostring(payload.recommendation_id),
    approver = tostring(payload.approver),
    approval_status = tostring(payload.approval_status),
    severity,
    payload
""".strip(),
    ),
    (
        "RouteActionEvents",
        """
raw_restaurant_events
| where event_name startswith "action."
| project
    event_time,
    event_id,
    action_id = tostring(payload.action_id),
    action_type = event_name,
    action_status = tostring(payload.action_status),
    severity,
    payload
""".strip(),
    ),
]

UPDATE_POLICIES = [
    ("order_events", "RouteOrderEvents"),
    ("kitchen_events", "RouteKitchenEvents"),
    ("inventory_events", "RouteInventoryEvents"),
    ("agent_events", "RouteAgentEvents"),
    ("approval_events", "RouteApprovalEvents"),
    ("action_events", "RouteActionEvents"),
]

# Reference table: static station definitions.
# Use .set-or-replace so re-running the script resets to the canonical values.
STATIONS_DATA = """.set-or-replace stations <|
datatable(
    station_id:string,
    display_name:string,
    specialization:string,
    max_capacity:long,
    avg_prep_minutes:real,
    is_active:bool
)[
    "grill",    "Plancha / Parrilla", "Carnes, hamburguesas, filetes",      4, 8.0,  true,
    "fryer",    "Freidora",           "Patatas fritas, croquetas, alitas",   4, 6.0,  true,
    "sauces",   "Salsas y Aderezos",  "Salsas, ensaladas, preparaciones",   3, 3.0,  true,
    "assembly", "Montaje Final",      "Ensamblaje del plato y empaquetado",  5, 2.0,  true
]"""


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

    for function_name, body in FUNCTIONS:
        run_kusto_management(
            query_service_uri,
            database_name,
            f".create-or-alter function with (folder='Routing', docstring='Route raw restaurant events') {function_name}() {{\n{body}\n}}",
        )

    for table_name, function_name in UPDATE_POLICIES:
        policy = (
            "["
            f'{{"IsEnabled":true,"Source":"raw_restaurant_events","Query":"{function_name}()",'
            '"IsTransactional":true,"PropagateIngestionProperties":false}'
            "]"
        )
        run_kusto_management(query_service_uri, database_name, f".alter table {table_name} policy update @'{policy}'")

    # Seed reference table with station definitions
    run_kusto_management(query_service_uri, database_name, STATIONS_DATA)
    print("  stations reference table seeded (4 stations).")


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
        run_kusto_management(query_service_uri, database_name, STATIONS_DATA)
        print("Table creation completed.")
        return

    deploy_schema(query_service_uri, database_name)
    print("Table creation, functions, and policies completed.")


if __name__ == "__main__":
    main()

