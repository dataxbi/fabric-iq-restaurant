#!/usr/bin/env python3
"""
Create Fabric IQ Ontology from RestaurantAnalytics semantic model.
Generates entity types for Order, Station, Channel with bindings to Eventhouse.
"""

import json
import os
from pathlib import Path

# Read IDs
workspace_id = Path("workspace_id.txt").read_text().strip()
lakehouse_id = Path("lakehouse_id.txt").read_text().strip()

ONTOLOGY_DEFINITION = {
    "displayName": "RestaurantOperationsOntology",
    "description": "Restaurant operations ontology with Eventhouse bindings",
    "entityTypes": [
        {
            "name": "Order",
            "displayName": "Pedido",
            "description": "Restaurant order (Pedido)",
            "properties": {
                "order_id": {
                    "displayName": "Order ID",
                    "dataType": "string",
                    "isKey": True
                },
                "order_date": {
                    "displayName": "Order Date",
                    "dataType": "datetime"
                },
                "channel": {
                    "displayName": "Channel (Dine-in/Delivery)",
                    "dataType": "string"
                },
                "status": {
                    "displayName": "Status (Pending/Preparing/Ready/Completed)",
                    "dataType": "string"
                },
                "delay_minutes": {
                    "displayName": "Delay in Minutes",
                    "dataType": "int64"
                },
                "is_delayed": {
                    "displayName": "Is Delayed",
                    "dataType": "bool"
                },
                "is_on_sla": {
                    "displayName": "On SLA",
                    "dataType": "bool"
                }
            },
            "binding": {
                "source": "fact_orders",
                "sourceType": "Table",
                "keyProperties": ["order_id"]
            }
        },
        {
            "name": "Station",
            "displayName": "Estación de Cocina",
            "description": "Kitchen station (Estación)",
            "properties": {
                "station_id": {
                    "displayName": "Station ID",
                    "dataType": "string",
                    "isKey": True
                },
                "station_name": {
                    "displayName": "Station Name",
                    "dataType": "string"
                },
                "capacity": {
                    "displayName": "Capacity",
                    "dataType": "int64"
                }
            },
            "binding": {
                "source": "dim_stations",
                "sourceType": "Table",
                "keyProperties": ["station_id"]
            }
        },
        {
            "name": "Channel",
            "displayName": "Canal de Pedidos",
            "description": "Order channel (e.g., Dine-in, Delivery)",
            "properties": {
                "channel_id": {
                    "displayName": "Channel ID",
                    "dataType": "string",
                    "isKey": True
                },
                "channel_name": {
                    "displayName": "Channel Name",
                    "dataType": "string"
                },
                "sla_minutes": {
                    "displayName": "SLA Minutes",
                    "dataType": "int64"
                }
            },
            "binding": {
                "source": "dim_channels",
                "sourceType": "Table",
                "keyProperties": ["channel_id"]
            }
        }
    ],
    "relationships": [
        {
            "name": "Order_in_Station",
            "displayName": "Order processed in Station",
            "fromEntity": "Order",
            "toEntity": "Station",
            "fromCardinality": "Many",
            "toCardinality": "One",
            "description": "An order is processed in exactly one kitchen station"
        },
        {
            "name": "Order_from_Channel",
            "displayName": "Order from Channel",
            "fromEntity": "Order",
            "toEntity": "Channel",
            "fromCardinality": "Many",
            "toCardinality": "One",
            "description": "An order comes from exactly one channel"
        }
    ]
}

# Save ontology definition
output_file = Path("semantic-model") / "ontology_definition.json"
output_file.write_text(json.dumps(ONTOLOGY_DEFINITION, indent=2), encoding="utf-8")
print(f"✅ Ontology definition saved to {output_file}")
print(f"   Entities: {len(ONTOLOGY_DEFINITION['entityTypes'])}")
print(f"   Relationships: {len(ONTOLOGY_DEFINITION['relationships'])}")

# Print summary
print("\n📋 Ontology Summary:")
for entity in ONTOLOGY_DEFINITION["entityTypes"]:
    print(f"  • {entity['displayName']} ({entity['name']})")
    print(f"    Properties: {len(entity['properties'])}")
    print(f"    Binding: {entity['binding']['source']}")

print("\n🔗 Relationships:")
for rel in ONTOLOGY_DEFINITION["relationships"]:
    print(f"  • {rel['fromEntity']} --{rel['name']}→ {rel['toEntity']}")
