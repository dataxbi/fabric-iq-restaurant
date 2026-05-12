"""
Create analytical tables in Lakehouse from Eventhouse transactional data.

Generates fact and dimension tables:
- fact_orders: Order lifecycle and KPIs
- fact_kitchen_flow: Kitchen operations and delays
- dim_stations: Kitchen stations
- dim_channels: Order channels (delivery, in_store)
- dim_time: Time dimension for temporal analysis
- dim_order_status: Order status values
"""

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from dotenv import load_dotenv
from fabric_client import FabricClient, FabricConfigError

load_dotenv()


def require_env(name: str) -> str:
    """Get required environment variable."""
    value = os.environ.get(name, "").strip()
    if not value:
        raise FabricConfigError(f"Missing required environment variable: {name}")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create analytical tables in Lakehouse")
    parser.add_argument("--spark-session", default="main", help="Spark session name")
    parser.add_argument("--dry-run", action="store_true", help="Show DDL without executing")
    return parser


def create_fact_orders_ddl() -> str:
    """Create fact_orders table DDL (Spark SQL)."""
    return """
    CREATE TABLE IF NOT EXISTS fact_orders (
        order_id STRING,
        order_date DATE,
        order_hour INT,
        channel STRING,
        status STRING,
        created_at TIMESTAMP,
        completed_at TIMESTAMP,
        delay_minutes DOUBLE,
        is_delayed BOOLEAN,
        is_on_sla BOOLEAN,
        total_items INT,
        priority STRING,
        station_id STRING,
        created_ts TIMESTAMP
    )
    USING DELTA
    PARTITIONED BY (order_date)
    """


def create_fact_kitchen_flow_ddl() -> str:
    """Create fact_kitchen_flow table DDL."""
    return """
    CREATE TABLE IF NOT EXISTS fact_kitchen_flow (
        flow_id STRING,
        order_id STRING,
        station_id STRING,
        event_time TIMESTAMP,
        event_date DATE,
        event_hour INT,
        queue_length INT,
        processing_time_minutes DOUBLE,
        station_status STRING,
        saturation_pct DOUBLE,
        orders_ahead INT,
        created_ts TIMESTAMP
    )
    USING DELTA
    PARTITIONED BY (event_date)
    """


def create_dim_stations_ddl() -> str:
    """Create dim_stations dimension table DDL."""
    return """
    CREATE TABLE IF NOT EXISTS dim_stations (
        station_id STRING PRIMARY KEY,
        station_name STRING,
        station_type STRING,
        capacity INT,
        is_active BOOLEAN,
        created_at TIMESTAMP,
        updated_at TIMESTAMP
    )
    USING DELTA
    """


def create_dim_channels_ddl() -> str:
    """Create dim_channels dimension table DDL."""
    return """
    CREATE TABLE IF NOT EXISTS dim_channels (
        channel_id STRING PRIMARY KEY,
        channel_name STRING,
        channel_type STRING,
        sla_minutes INT,
        priority_default INT,
        is_active BOOLEAN,
        created_at TIMESTAMP
    )
    USING DELTA
    """


def create_dim_time_ddl() -> str:
    """Create dim_time dimension table DDL."""
    return """
    CREATE TABLE IF NOT EXISTS dim_time (
        time_id INT PRIMARY KEY,
        date_id DATE,
        year INT,
        month INT,
        day INT,
        hour INT,
        minute INT,
        day_of_week INT,
        is_weekend BOOLEAN,
        is_peak_hour BOOLEAN
    )
    USING DELTA
    """


def create_dim_order_status_ddl() -> str:
    """Create dim_order_status dimension table DDL."""
    return """
    CREATE TABLE IF NOT EXISTS dim_order_status (
        status_id STRING PRIMARY KEY,
        status_name STRING,
        status_sequence INT,
        is_terminal BOOLEAN,
        description STRING
    )
    USING DELTA
    """


def populate_dim_channels(client: FabricClient, workspace_id: str, lakehouse_id: str) -> None:
    """Populate dim_channels with reference data."""
    sql = """
    DELETE FROM dim_channels WHERE 1=1;
    
    INSERT INTO dim_channels (channel_id, channel_name, channel_type, sla_minutes, priority_default, is_active, created_at)
    VALUES
        ('delivery', 'Delivery', 'external', 45, 1, true, current_timestamp()),
        ('in_store', 'In-Store', 'internal', 30, 2, true, current_timestamp()),
        ('pickup', 'Pickup', 'external', 20, 3, true, current_timestamp());
    """
    client.run_kusto_management(workspace_id, lakehouse_id, sql)


def populate_dim_stations(client: FabricClient, workspace_id: str, lakehouse_id: str) -> None:
    """Populate dim_stations with reference data."""
    sql = """
    DELETE FROM dim_stations WHERE 1=1;
    
    INSERT INTO dim_stations (station_id, station_name, station_type, capacity, is_active, created_at, updated_at)
    VALUES
        ('kitchen-main', 'Main Kitchen', 'primary', 20, true, current_timestamp(), current_timestamp()),
        ('kitchen-secondary', 'Secondary Kitchen', 'secondary', 10, true, current_timestamp(), current_timestamp()),
        ('grill', 'Grill Station', 'specialized', 8, true, current_timestamp(), current_timestamp()),
        ('prep', 'Prep Station', 'specialized', 12, true, current_timestamp(), current_timestamp()),
        ('delivery', 'Delivery Counter', 'output', 15, true, current_timestamp(), current_timestamp());
    """
    client.run_kusto_management(workspace_id, lakehouse_id, sql)


def populate_dim_order_status(client: FabricClient, workspace_id: str, lakehouse_id: str) -> None:
    """Populate dim_order_status with reference data."""
    sql = """
    DELETE FROM dim_order_status WHERE 1=1;
    
    INSERT INTO dim_order_status (status_id, status_name, status_sequence, is_terminal, description)
    VALUES
        ('created', 'Created', 1, false, 'Order created'),
        ('confirmed', 'Confirmed', 2, false, 'Order confirmed'),
        ('prep_started', 'Prep Started', 3, false, 'Preparation started'),
        ('prep_completed', 'Prep Completed', 4, false, 'Preparation completed'),
        ('ready', 'Ready', 5, false, 'Ready for pickup/delivery'),
        ('delivered', 'Delivered', 6, true, 'Delivered to customer'),
        ('completed', 'Completed', 7, true, 'Order completed'),
        ('cancelled', 'Cancelled', 8, true, 'Order cancelled');
    """
    client.run_kusto_management(workspace_id, lakehouse_id, sql)


def populate_dim_time(client: FabricClient, workspace_id: str, lakehouse_id: str, days: int = 7) -> None:
    """Populate dim_time with time dimension data."""
    end_date = datetime.now(timezone.utc).date()
    start_date = end_date - timedelta(days=days)

    time_records = []
    time_id = 0

    current = start_date
    while current <= end_date:
        for hour in range(24):
            for minute in [0, 15, 30, 45]:
                time_id += 1
                day_of_week = current.weekday()
                is_weekend = day_of_week >= 5
                is_peak_hour = 11 <= hour <= 13 or 18 <= hour <= 21

                time_records.append(
                    (
                        time_id,
                        current.isoformat(),
                        current.year,
                        current.month,
                        current.day,
                        hour,
                        minute,
                        day_of_week,
                        is_weekend,
                        is_peak_hour,
                    )
                )

        current += timedelta(days=1)

    # Insert in batches
    batch_size = 500
    for i in range(0, len(time_records), batch_size):
        batch = time_records[i : i + batch_size]
        values_str = ",".join(
            f"({rec[0]}, '{rec[1]}', {rec[2]}, {rec[3]}, {rec[4]}, {rec[5]}, {rec[6]}, {rec[7]}, {rec[8]}, {rec[9]})"
            for rec in batch
        )
        sql = f"""
        INSERT INTO dim_time (time_id, date_id, year, month, day, hour, minute, day_of_week, is_weekend, is_peak_hour)
        VALUES {values_str}
        """
        client.run_kusto_management(workspace_id, lakehouse_id, sql)


def create_tables(client: FabricClient, workspace_name: str, lakehouse_name: str, dry_run: bool = False) -> None:
    """Create all analytical tables in Lakehouse."""
    print("Resolving workspace and lakehouse...")
    workspace = client.resolve_workspace(workspace_name)
    lakehouse = client.find_item(workspace["id"], "lakehouses", lakehouse_name)

    if not workspace or not lakehouse:
        raise FabricConfigError(f"Could not resolve workspace '{workspace_name}' or lakehouse '{lakehouse_name}'")

    workspace_id = workspace["id"]
    lakehouse_id = lakehouse["id"]

    print(f"Workspace: {workspace_name} ({workspace_id})")
    print(f"Lakehouse: {lakehouse_name} ({lakehouse_id})")

    tables_ddl = [
        ("fact_orders", create_fact_orders_ddl()),
        ("fact_kitchen_flow", create_fact_kitchen_flow_ddl()),
        ("dim_stations", create_dim_stations_ddl()),
        ("dim_channels", create_dim_channels_ddl()),
        ("dim_time", create_dim_time_ddl()),
        ("dim_order_status", create_dim_order_status_ddl()),
    ]

    if dry_run:
        print("\n=== DRY RUN: DDL Statements ===")
        for table_name, ddl in tables_ddl:
            print(f"\n-- {table_name}")
            print(ddl)
        return

    print("\nCreating tables...")
    for table_name, ddl in tables_ddl:
        print(f"  Creating {table_name}...", end=" ", flush=True)
        try:
            client.run_kusto_management(workspace_id, lakehouse_id, ddl)
            print("✓")
        except Exception as e:
            print(f"⚠ {e}")

    print("\nPopulating dimension tables...")
    print("  Populating dim_channels...", end=" ", flush=True)
    populate_dim_channels(client, workspace_id, lakehouse_id)
    print("✓")

    print("  Populating dim_stations...", end=" ", flush=True)
    populate_dim_stations(client, workspace_id, lakehouse_id)
    print("✓")

    print("  Populating dim_order_status...", end=" ", flush=True)
    populate_dim_order_status(client, workspace_id, lakehouse_id)
    print("✓")

    print("  Populating dim_time (7 days)...", end=" ", flush=True)
    populate_dim_time(client, workspace_id, lakehouse_id, days=7)
    print("✓")

    print("\n✅ Analytical tables created successfully!")


def main() -> None:
    """Main entry point."""
    args = build_parser().parse_args()

    workspace_name = require_env("FABRIC_WORKSPACE_NAME")
    lakehouse_name = require_env("FABRIC_LAKEHOUSE_NAME")

    client = FabricClient()
    create_tables(client, workspace_name, lakehouse_name, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
