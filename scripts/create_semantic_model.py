"""
Create Power BI semantic model with fact/dim relationships and DAX measures.

This script generates TMDL (Tabular Model Definition Language) for a semantic model
that connects to the Lakehouse analytical tables and provides business logic via
calculated measures and hierarchies.

Model structure:
- Tables: 6 fact/dim tables from Lakehouse
- Relationships: star schema (fact -> dim)
- Measures: KPIs (PedidosTotales, AtrasoMedioMinutos, PedidosEnSLA, etc.)
- Hierarchies: time dimension (Year-Month-Day-Hour), orders (Channel/Station)
"""

import argparse
import json
import os
from typing import Any

from fabric_client import FabricClient, FabricConfigError, require_env


def generate_tmdl_model(workspace_name: str, lakehouse_name: str) -> dict[str, Any]:
    """Generate TMDL model definition connecting to Lakehouse tables."""
    
    # Model metadata
    model = {
        "name": "RestaurantAnalytics",
        "description": "Semantic model for restaurant operations intelligence",
        "compatibilityLevel": 1701,
        "culture": "es-ES",
        "tables": [],
        "relationships": [],
        "roles": [],
    }
    
    # Fact and dimension tables (from Lakehouse)
    lakehouse_tables = [
        "fact_orders",
        "fact_kitchen_flow",
        "fact_agent_decisions",
        "dim_stations",
        "dim_channels",
        "dim_order_status",
    ]
    
    # 1. Import fact and dimension tables from Lakehouse SQL endpoint
    for table_name in lakehouse_tables:
        table_def = {
            "name": table_name,
            "description": f"Table {table_name} from Lakehouse",
            "columns": [],
            "measures": [],
            "partitions": [
                {
                    "name": f"Partition-{table_name}",
                    "source": {
                        "type": "m",
                        "expression": f'let\n  Source = Sql.Database("{{LAKEHOUSE_ENDPOINT}}", "{table_name}")\nlet\n  Source = Source\nin\n  Source',
                    },
                }
            ],
        }
        model["tables"].append(table_def)
    
    # 2. Add calculated tables (if needed) and measures
    # Time dimension hierarchy (if not in Lakehouse, can be generated)
    time_table = {
        "name": "Time",
        "description": "Time dimension for temporal analysis",
        "columns": [
            {"name": "Date", "dataType": "datetime"},
            {"name": "Year", "dataType": "int64"},
            {"name": "Month", "dataType": "int64"},
            {"name": "Day", "dataType": "int64"},
            {"name": "Hour", "dataType": "int64"},
        ],
        "measures": [
            {
                "name": "YearMonthDay",
                "expression": 'FORMAT([Date], "YYYY-MM-DD")',
                "formatString": "@",
            }
        ],
        "partitions": [],
    }
    model["tables"].append(time_table)
    
    # 3. Add key measures (KPIs)
    measures_table = {
        "name": "KPIs",
        "description": "Business KPI measures",
        "columns": [],
        "measures": [
            {
                "name": "PedidosTotales",
                "expression": 'COALESCE(COUNTROWS(fact_orders), 0)',
                "formatString": "#,##0",
                "description": "Total number of orders",
            },
            {
                "name": "PedidosAtrasados",
                "expression": 'CALCULATE([PedidosTotales], FILTER(fact_orders, fact_orders[is_delayed]=TRUE()))',
                "formatString": "#,##0",
            },
            {
                "name": "AtrasoMedioMinutos",
                "expression": 'AVERAGE(fact_orders[delay_minutes])',
                "formatString": "0.00",
            },
            {
                "name": "PedidosEnSLA",
                "expression": 'CALCULATE([PedidosTotales], FILTER(fact_orders, fact_orders[is_on_sla]=TRUE()))',
                "formatString": "#,##0",
            },
            {
                "name": "TiempoMedioCocinaMinutos",
                "expression": 'AVERAGE(fact_kitchen_flow[processing_time_minutes])',
                "formatString": "0.00",
            },
            {
                "name": "ColaMediaEstacion",
                "expression": 'AVERAGE(fact_kitchen_flow[queue_length])',
                "formatString": "0.00",
            },
            {
                "name": "SaturationMediaEstacion",
                "expression": 'AVERAGE(fact_kitchen_flow[saturation_pct])',
                "formatString": "0.00%",
            },
            {
                "name": "PedidosPorCanal",
                "expression": 'SUMMARIZE(fact_orders, dim_channels[channel_name], "Total", COALESCE(COUNTROWS(fact_orders), 0))',
                "formatString": "#,##0",
            },
            {
                "name": "SLAPct",
                "expression": 'DIVIDE([PedidosEnSLA], [PedidosTotales], 0)',
                "formatString": "0.00%",
            },
        ],
        "partitions": [],
    }
    model["tables"].append(measures_table)
    
    # 4. Define relationships (star schema)
    # fact_orders -> dim_channels
    model["relationships"].append({
        "name": "fact_orders_to_dim_channels",
        "fromTable": "fact_orders",
        "fromColumn": "channel",
        "toTable": "dim_channels",
        "toColumn": "channel_id",
        "fromCardinality": "many",
        "toCardinality": "one",
        "isActive": True,
    })
    
    # fact_orders -> dim_order_status
    model["relationships"].append({
        "name": "fact_orders_to_dim_order_status",
        "fromTable": "fact_orders",
        "fromColumn": "status",
        "toTable": "dim_order_status",
        "toColumn": "status_id",
        "fromCardinality": "many",
        "toCardinality": "one",
        "isActive": True,
    })
    
    # fact_kitchen_flow -> dim_stations
    model["relationships"].append({
        "name": "fact_kitchen_flow_to_dim_stations",
        "fromTable": "fact_kitchen_flow",
        "fromColumn": "station_id",
        "toTable": "dim_stations",
        "toColumn": "station_id",
        "fromCardinality": "many",
        "toCardinality": "one",
        "isActive": True,
    })
    
    return model


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create Power BI semantic model for restaurant demo")
    parser.add_argument("--model-name", default="RestaurantAnalytics", help="Semantic model name")
    parser.add_argument("--output", default="semantic_model.json", help="Output TMDL definition file")
    parser.add_argument("--dry-run", action="store_true", help="Generate but don't deploy")
    return parser


def main() -> None:
    """Main entry point."""
    args = build_parser().parse_args()
    
    workspace_name = require_env("FABRIC_WORKSPACE_NAME")
    lakehouse_name = require_env("FABRIC_LAKEHOUSE_NAME")
    
    print(f"Generating semantic model for workspace '{workspace_name}' lakehouse '{lakehouse_name}'...")
    
    # Generate TMDL model
    model = generate_tmdl_model(workspace_name, lakehouse_name)
    
    # Save to file
    output_path = args.output
    with open(output_path, "w") as f:
        json.dump(model, f, indent=2)
    print(f"✓ Model definition saved to {output_path}")
    
    if not args.dry_run:
        # TODO: Deploy model to Fabric using FabricClient
        print(f"✓ Model would be deployed to Fabric (deployment not yet implemented)")
    else:
        print("(dry-run mode: deployment skipped)")


if __name__ == "__main__":
    main()
