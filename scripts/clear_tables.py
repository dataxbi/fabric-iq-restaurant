"""Clear all operational KQL tables in the restaurant Eventhouse.

The 'stations' reference table is intentionally excluded.
Run this script before restarting the simulator to start fresh.

Usage:
    python scripts/clear_tables.py
    python scripts/clear_tables.py --dry-run
"""
import argparse
import sys

from fabric_client import FabricClient, FabricConfigError, require_env, run_kusto_management

TABLES = [
    "raw_restaurant_events",
    "order_events",
    "kitchen_events",
    "inventory_events",
    "agent_events",
    "approval_events",
    "action_events",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Clear all operational KQL tables.")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without executing them.")
    args = parser.parse_args()

    workspace_name = require_env("FABRIC_WORKSPACE_NAME")
    eventhouse_name = require_env("FABRIC_EVENTHOUSE_NAME")
    kql_database_name = require_env("FABRIC_KQL_DATABASE_NAME")

    client = FabricClient()
    workspace = client.resolve_workspace(workspace_name)
    workspace_id = workspace["id"]

    eventhouse = client.find_item(workspace_id, "eventhouses", eventhouse_name)
    if not eventhouse:
        print(f"ERROR: Eventhouse not found: {eventhouse_name}", file=sys.stderr)
        sys.exit(1)

    query_uri = client.get_eventhouse_query_service_uri(workspace_id, eventhouse["id"])

    print(f"Workspace : {workspace['displayName']}  ({workspace_id})")
    print(f"Eventhouse: {eventhouse['displayName']}  ({eventhouse['id']})")
    print(f"KQL DB    : {kql_database_name}")
    print(f"Cluster   : {query_uri}")
    print()

    if args.dry_run:
        print("[DRY RUN] The following commands would be executed:")

    errors = 0
    for table in TABLES:
        cmd = f".clear table {table} data"
        if args.dry_run:
            print(f"  {cmd}")
            continue
        print(f"  Clearing {table} ...", end=" ", flush=True)
        try:
            run_kusto_management(query_uri, kql_database_name, cmd)
            print("OK")
        except Exception as exc:  # noqa: BLE001
            print(f"FAILED — {exc}")
            errors += 1

    if args.dry_run:
        return

    print()
    if errors:
        print(f"Completed with {errors} error(s).")
        sys.exit(1)
    else:
        print(f"All {len(TABLES)} tables cleared successfully.")


if __name__ == "__main__":
    try:
        main()
    except FabricConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        sys.exit(1)
