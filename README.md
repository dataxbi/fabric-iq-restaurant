# Fabric IQ Restaurant Demo

A real-time intelligent orchestration (RTI) demonstration for a self-managing restaurant system using Microsoft Fabric, built on event-driven architecture and real-time analytics.

## Overview

This project demonstrates a complete end-to-end solution for a restaurant that leverages:
- **Real-time Event Ingestion**: Azure Event Hub → Fabric Eventstream → KQL Database
- **Real-time Analytics**: KQL queries on streaming order and operational data
- **Automated Orchestration**: Rules and activators for restaurant operations

## Architecture

```
Event Hub (Custom Endpoint)
    ↓
Eventstream (Restaurant)
    ↓
Eventhouse (RTI Database)
    ├── order_events (transactional)
    ├── order_items (transactional)
    ├── channels (reference)
    ├── stations (reference)
    ├── delays (metrics)
    └── ...
    ↓
Lakehouse (Restaurant)
    └── Analytical tables (Spark/SQL)
```

## Project Structure

```
fabric-iq-restaurant/
├── README.md                           # This file
├── specs/
│   └── especificaciones.md            # Technical specification (v1.0)
├── scripts/
│   ├── fabric_client.py               # Fabric REST client wrapper
│   ├── bootstrap_fabric.py            # Create Fabric resources
│   ├── eventhouse_schema.py           # KQL table definitions
│   ├── configure_eventstream.py       # Configure Eventstream topology
│   └── send_eventstream_events.py     # Send demo events to Event Hub
├── .env.example                        # Environment variables template
└── .gitignore                          # Git ignore patterns
```

## Prerequisites

- Python 3.11+
- Azure CLI (`az` command available in PATH)
- Authenticated Azure subscription with:
  - Fabric capacity
  - Event Hub namespace with SAS policy
- Microsoft Fabric workspace (created manually or via Azure Portal)

## Installation

### 1. Clone the Repository

```bash
git clone https://github.com/yourusername/fabric-iq-restaurant.git
cd fabric-iq-restaurant
```

### 2. Create Virtual Environment

```bash
python -m venv .venv
# On Windows:
.venv\Scripts\activate
# On macOS/Linux:
source .venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

If `requirements.txt` is not available, install manually:

```bash
pip install azure-fabric azure-eventhub python-dotenv
```

### 4. Configure Environment

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

Edit `.env`:

```env
FABRIC_WORKSPACE_NAME=Fabric_IQ_Restaurant
FABRIC_LAKEHOUSE_NAME=restaurant_lakehouse
FABRIC_EVENTHOUSE_NAME=restaurant_eventhouse
FABRIC_KQL_DATABASE_NAME=restaurant_rti
FABRIC_EVENTSTREAM_NAME=restaurant_eventstream
EVENTSTREAM_EVENTHUB_CONNECTION_STRING=Endpoint=sb://...;SharedAccessKeyName=...;SharedAccessKey=...;EntityPath=...
```

**Note**: `EVENTSTREAM_EVENTHUB_CONNECTION_STRING` is obtained from the Event Hub namespace in Azure Portal:
- Navigate to your Event Hub namespace
- Go to **Shared access policies** → Create a policy with "Send" permission
- Copy the **Primary Connection String**

### 5. Authenticate with Azure

```bash
az login
```

## Usage

### Bootstrap Fabric Resources

Create Lakehouse, Eventhouse, KQL Database, and Eventstream:

```bash
py scripts/bootstrap_fabric.py
```

This script is **idempotent**—it checks if resources exist before creating them.

### Create KQL Tables and Schema

Define transactional tables with retention and caching policies:

```bash
py scripts/eventhouse_schema.py
```

### Configure Eventstream Topology

Set up the data flow from Event Hub to Eventhouse:

```bash
py scripts/configure_eventstream.py --recreate --source-type CustomEndpoint
```

Options:
- `--recreate`: Rebuild the Eventstream definition from scratch
- `--source-type`: `CustomEndpoint` (Event Hub) or `SampleData` (demo data)

### Send Demo Events

Publish demo events to the Event Hub:

```bash
py scripts/send_eventstream_events.py --count 100 --interval-seconds 0.5
```

Options:
- `--count`: Number of events to send (default: 20)
- `--interval-seconds`: Delay between events in seconds (default: 1.0)
- `--connection-string`: Override connection string (optional; uses `EVENTSTREAM_EVENTHUB_CONNECTION_STRING` from `.env`)

**Example**: Send 50 events with 0.1-second intervals:

```bash
py scripts/send_eventstream_events.py --count 50 --interval-seconds 0.1
```

## Key Scripts

### `fabric_client.py`

Core wrapper for Fabric and Kusto APIs. Handles:
- Azure CLI authentication (`az account get-access-token`)
- Workspace resolution by name
- Item CRUD operations (create, read, delete, list)
- Long-running operation (LRO) polling
- Eventstream and KQL management

**Usage**:
```python
from scripts.fabric_client import FabricClient

client = FabricClient()
workspace = client.resolve_workspace("Fabric_IQ_Restaurant")
eventhouse = client.find_item("restaurant_eventhouse", workspace["id"])
```

### `bootstrap_fabric.py`

Provisioning script for Fabric resources:
- Creates Lakehouse, Eventhouse, KQL Database, Eventstream
- Skips existing resources (idempotent)
- Stores resource IDs in memory for dependent resources

### `eventhouse_schema.py`

Defines KQL tables with:
- **Transactional tables**: `order_events`, `order_items`, `channels`, `stations`, `delays`
- **Retention policies**: Soft delete after 30 days
- **Caching policies**: Hot cache for recent data

### `configure_eventstream.py`

Sets up Eventstream topology:
- **Source**: Custom Event Hub endpoint or sample data
- **Destination**: KQL table `order_events`
- **Format**: JSON with automatic schema detection

### `send_eventstream_events.py`

Event generator using Azure Event Hub SDK:
- Generates synthetic order events (order ID, channel, status, etc.)
- Batches events for efficiency
- Sends via Event Hub producer client

**Event schema**:
```json
{
  "event_id": "evt-00001",
  "event_time": "2026-05-12T10:30:00Z",
  "order_id": "ORD-1001",
  "channel": "delivery",
  "event_name": "order.created",
  "order_status": "created",
  "station_id": "kitchen-main",
  "delay_minutes": 0.0,
  "payload": {
    "items": 3,
    "priority": "high"
  }
}
```

## Workflow Example

```bash
# 1. Bootstrap Fabric resources
py scripts/bootstrap_fabric.py

# 2. Create KQL schema
py scripts/eventhouse_schema.py

# 3. Configure Eventstream
py scripts/configure_eventstream.py --recreate --source-type CustomEndpoint

# 4. Send demo events
py scripts/send_eventstream_events.py --count 100 --interval-seconds 0.5

# 5. Query data (in Fabric portal)
# KQL: order_events | count
```

## Troubleshooting

### "Session token expired" error

This is a temporary authentication issue. Retry the command:

```bash
py scripts/send_eventstream_events.py --count 20 --interval-seconds 0.5
```

### "Missing EVENTSTREAM_EVENTHUB_CONNECTION_STRING"

Ensure `.env` file exists and contains the connection string. Verify the Event Hub namespace and SAS policy are created in Azure Portal.

### "Workspace not found"

Check that:
- `FABRIC_WORKSPACE_NAME` matches your workspace name in Fabric portal
- You are authenticated: `az login`
- Your Azure subscription has access to the workspace

### Eventstream shows no data

1. Verify Event Hub is receiving events: Check Azure Portal → Event Hub Namespace → Metrics
2. Verify Eventstream source is configured: `py scripts/configure_eventstream.py --recreate --source-type CustomEndpoint`
3. Check KQL table is receiving: Query in KQL editor → `order_events | count`

## Next Steps

- **Real-time Dashboard**: Create Power BI or Fabric RTI dashboard on `order_events`
- **Operational Rules**: Implement Activators for order alerts and kitchen automation
- **Analytical Tables**: Populate fact and dimension tables in Lakehouse via Spark
- **Data Quality**: Add validation rules and monitoring

## Technical Details

### Authentication Flow

1. `az account get-access-token` → Bearer token (Fabric API)
2. Kusto management queries use separate token with audience `https://kusto.kusto.windows.net`
3. Event Hub uses SAS connection string (no token needed)

### Long-Running Operations (LRO)

Fabric returns `Location` header; scripts poll until status is 200/201:

```python
response = client.create_item_with_definition(...)
lro_status = client.wait_for_lro(response)
```

### Idempotency

All scripts check for resource existence before creation:

```python
existing = client.find_item(name, workspace_id)
if existing:
    print(f"Resource '{name}' already exists, skipping.")
else:
    client.create_item(...)
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `FABRIC_WORKSPACE_NAME` | Yes | Fabric workspace name |
| `FABRIC_LAKEHOUSE_NAME` | Yes | Lakehouse name |
| `FABRIC_EVENTHOUSE_NAME` | Yes | Eventhouse (KQL database) name |
| `FABRIC_KQL_DATABASE_NAME` | Yes | KQL database name |
| `FABRIC_EVENTSTREAM_NAME` | Yes | Eventstream name |
| `EVENTSTREAM_EVENTHUB_CONNECTION_STRING` | Yes | Event Hub connection string (from portal) |

## References

- [Microsoft Fabric Documentation](https://learn.microsoft.com/en-us/fabric/)
- [Real-time Intelligence (RTI)](https://learn.microsoft.com/en-us/fabric/real-time-intelligence/)
- [Azure Event Hub SDK for Python](https://learn.microsoft.com/en-us/python/api/overview/azure/eventhub-readme)
- [KQL Query Language](https://learn.microsoft.com/en-us/kusto/query/)

## License

MIT

## Author

Copilot
