# Fabric Real-Time Intelligence Restaurant Demo

A Real-Time Intelligence demonstration for a self-managing restaurant system using Microsoft Fabric, built on event-driven operations, Eventhouse, Fabric Activator, and Operations Agent.

## Overview

This project demonstrates an end-to-end Real-Time Intelligence flow for a restaurant that leverages:
- **Real-time Event Ingestion**: Azure Event Hub → Fabric Eventstream → KQL Database
- **Operational Source of Truth**: Eventhouse/KQL tables for live order, kitchen, inventory, agent, approval, and action events
- **Simple Automation**: Fabric Activator for objective threshold-based conditions
- **Complex Recommendations**: Operations Agent for contextual recommendations and human approval in Teams
- **Operational Visibility**: Real-Time Dashboard over KQL tables

## Architecture

```
Event Hub (Custom Endpoint)
    ↓
Eventstream (Restaurant)
    ↓
Eventhouse (RTI Database)
    ├── raw_restaurant_events (landing)
    ├── order_events (transactional)
    ├── kitchen_events (station state)
    ├── inventory_events (stock changes)
    ├── agent_events (recommendations)
    ├── approval_events (human approvals)
    ├── action_events (executed actions)
    └── stations (reference: capacity & prep times)
    ↓
Real-Time Dashboard + Fabric Activator + Operations Agent
```

## Project Structure

```
fabric-iq-restaurant/
├── README.md                           # This file
├── specs/
│   └── especificaciones.md            # Technical specification (v1.0)
├── config/
│   ├── activator_rules.json           # Activator rule design
│   └── operations_agent_playbook.json # Operations Agent setup guidance
├── kql/
│   └── operational_queries.kql        # Dashboard and condition queries
├── scripts/
│   ├── fabric_client.py               # Fabric REST client wrapper
│   ├── bootstrap_fabric.py            # Create Fabric resources
│   ├── eventhouse_schema.py           # KQL table definitions
│   ├── configure_eventstream.py       # Configure Eventstream topology
│   ├── configure_fabric_artifacts.py  # Create RTI dashboard, Activator, and Operations Agent items
│   ├── configure_user_data_function.py # Create User Data Function for custom actions
│   ├── clear_tables.py                # Clear all operational KQL tables (keep stations reference)
│   ├── send_eventstream_events.py     # Send demo events to Event Hub
│   └── simulate_agent_trigger_events.py # Generate events for Operations Agent testing
├── user_data_functions/
│   └── restaurant_operations/         # User Data Function source and definition
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
pip install azure-eventhub python-dotenv
```

### 4. Configure Environment

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

Edit `.env`:

```env
FABRIC_WORKSPACE_NAME=Fabric_IQ_Restaurant
FABRIC_EVENTHOUSE_NAME=restaurant_eventhouse
FABRIC_KQL_DATABASE_NAME=restaurant_rti
FABRIC_EVENTSTREAM_NAME=restaurant_eventstream
EVENTSTREAM_EVENTHUB_CONNECTION_STRING=Endpoint=sb://...;SharedAccessKeyName=...;SharedAccessKey=...;EntityPath=...
FABRIC_ALERT_RECIPIENT=user@contoso.com
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

Create Eventhouse, KQL Database, Eventstream, and the operational KQL schema:

```bash
py scripts/bootstrap_fabric.py
```

This script is **idempotent**: it checks whether resources exist before creating them.

### Create KQL Tables and Schema

Define transactional tables with retention and caching policies:

```bash
py scripts/eventhouse_schema.py
```

### Configure Eventstream Topology

Set up the data flow from Event Hub to the raw landing `raw_restaurant_events` table in Eventhouse:

```bash
py scripts/configure_eventstream.py --recreate --source-type CustomEndpoint
```

Options:
- `--recreate`: Rebuild the Eventstream definition from scratch
- `--source-type`: `CustomEndpoint` (Event Hub) or `SampleData` (demo data)

### Create RTI UI Artifacts

Create or update the Real-Time Dashboard, Activator item, and Operations Agent item:

```bash
py scripts/configure_fabric_artifacts.py
```

The script uses Fabric REST APIs because Operations Agent is not yet exposed as a first-class path type in the current `fab` CLI. The installed `fab` CLI can list/create `KQLDashboard` and `Reflex` items and can call the Operations Agent endpoint through `fab api`, but the Python script keeps the flow consistent with the rest of the repo.

Current scripted coverage:
- KQL Dashboard: deploys `RealTimeDashboard.json` with six operational tiles over the KQL tables.
- Activator/Reflex: deploys three KQL-backed rules for delayed orders, critical inventory, and delivery saturation, with Teams notifications routed to `FABRIC_ALERT_RECIPIENT` or the current Azure CLI user.
- Operations Agent: deploys goals, instructions, and a KQL data source from `config/operations_agent_playbook.json`. Power Automate action wiring still needs UI completion because the current preview API accepted action definitions but then made `getDefinition` return HTTP 500 during testing.

### Create Operations Agent Custom Action Function

Create or update a Fabric User Data Function item with `recordReprioritizeOrder`:

```bash
py scripts/configure_user_data_function.py
```

The function publishes an `action.kitchen.reprioritized` event to Event Hub. Eventstream ingests it into `raw_restaurant_events`, and the Eventhouse update policy routes it into `action_events`.

The Fabric REST definition API can create the User Data Function item and libraries, but in preview it might not preserve the Python function body on readback. If the Functions explorer is empty after running the script, open the item in Fabric, paste `user_data_functions/restaurant_operations/function_app.py` into the editor, verify `azure-eventhub` in **Library management**, and publish.

The function reads an internal constant named `EVENT_HUB_CONNECTION_STRING` from `function_app.py`. Set that value in Fabric before publishing. Never commit a real value to git.

Function parameters:

| Parameter | Description |
|----------|-------------|
| `orderId` | Order to reprioritize |
| `stationId` | Kitchen station handling the order |
| `priority` | Proposed priority, for example `urgent` |
| `reason` | Agent explanation approved by the human reviewer |
| `approvedBy` | Approver identity from Teams/Power Automate |
| `channel` | Order channel, defaults to `delivery` |
| `severity` | Action severity, defaults to `warning` |

### Manual Fabric UI Steps

Some RTI preview features require UI confirmation even after the item definition is deployed by script:

1. Open the **Restaurant Operations RTI** Real-Time Dashboard and confirm the six tiles render without load errors.
2. Open **Restaurant Operations Activator** and confirm the three rules are enabled. If Fabric asks for permissions, authorize Teams notifications for the configured recipient.
3. Open **RestaurantOperationsAgent** and review the goals, instructions, and KQL data source.
4. Open **RestaurantOperationsActions**, paste/publish `recordReprioritizeOrder` if the Functions explorer is empty, and copy or enable its function URL.
5. In **RestaurantOperationsAgent**, attach the Power Automate or Teams approval actions manually, then set the agent to run only after the action connection is confirmed.

Do not enable scripted Operations Agent actions by default. The script has an opt-in `--include-agent-actions` flag, but current preview behavior can accept the action definition and then make `getDefinition` fail. Keep the default stable configuration unless testing the preview API intentionally.

### Send Demo Events

Publish a peak-hour demo scenario to the Event Hub:

```bash
py scripts/send_eventstream_events.py --scenario peak --orders 12 --interval-seconds 0.5
```

Options:
- `--orders`: Number of synthetic orders to simulate (default: 12)
- `--scenario`: `normal`, `peak`, or `stock-critical`
- `--interval-seconds`: Delay between events in seconds (default: 1.0)
- `--connection-string`: Override connection string (optional; uses `EVENTSTREAM_EVENTHUB_CONNECTION_STRING` from `.env`)

**Example**: Send 50 events with 0.1-second intervals:

```bash
py scripts/send_eventstream_events.py --scenario stock-critical --orders 8 --interval-seconds 0.1
```

### Test Operations Agent Trigger Conditions

Generate events that specifically trigger the Operations Agent conditions defined in `config/operations_agent_playbook.json`:

```bash
py scripts/simulate_agent_trigger_events.py
```

The script runs **continuously** (press `Ctrl+C` to stop) and emits three realistic scenarios every ~7 seconds with randomized values:

1. **PremiumClientNearSLA**: Premium customer with varied cancellation history, random feedback, and SLA 3–8 minutes remaining
2. **AnomalousStationQueue**: High queue (5–8 orders) at a random station with a critical ingredient shortage
3. **MultiChannelPressureWithTrade-off**: Simultaneous pressure across delivery, dine-in, and takeout with varied premium/standard mix

Each iteration uses randomized `order_id`, SLA values, delay minutes, feedback, and cancellation history to produce realistic, non-repeating event patterns.

Monitor the **Operations Agent** in Fabric UI or check the Teams approval channel to see if the agent detects these conditions and recommends `ReprioritizeOrder` or other actions.

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
eventhouse = client.find_item(workspace["id"], "eventhouses", "restaurant_eventhouse")
```

### `bootstrap_fabric.py`

Provisioning script for Fabric resources:
- Creates Eventhouse, KQL Database, and Eventstream
- Skips existing resources (idempotent)
- Stores resource IDs in memory for dependent resources

### `eventhouse_schema.py`

Defines KQL tables with:
- **Raw landing table**: `raw_restaurant_events`
- **Operational tables**: `order_events`, `kitchen_events`, `inventory_events`, `agent_events`, `approval_events`, `action_events`
- **Reference table**: `stations` — static definition of the 4 kitchen stations (grill, fryer, sauces, assembly) with `max_capacity` (parallel units, e.g. burners), `avg_prep_minutes`, and `is_active`. Seeded with `.set-or-replace` on every run.
- **Routing logic**: KQL functions and update policies that distribute raw events to operational tables
- **Retention policies**: Soft delete after 30 days
- **Caching policies**: Hot cache for recent data

### `configure_eventstream.py`

Sets up Eventstream topology:
- **Source**: Custom Event Hub endpoint or sample data
- **Destination**: KQL table `raw_restaurant_events`
- **Format**: JSON with automatic schema detection

### `clear_tables.py`

Clears all 7 operational KQL tables (excludes `stations` reference table) before a simulator restart or demo reset:

```bash
py scripts/clear_tables.py          # clear all tables
py scripts/clear_tables.py --dry-run  # preview commands without executing
```

### `send_eventstream_events.py`

Event generator using Azure Event Hub SDK:
- Generates synthetic restaurant events for orders, kitchen stations, inventory, delays, sentiment, and payments
- Batches events for efficiency
- Sends via Event Hub producer client

### `configure_user_data_function.py`

Creates the `RestaurantOperationsActions` Fabric User Data Function item and stores its deployable definition in the repo:
- Defines `recordReprioritizeOrder` with the Fabric User Data Functions Python programming model.
- Includes the `azure-eventhub` PyPI dependency in the item definition.
- Publishes approved custom action events back through Event Hub/Eventstream instead of writing directly to derived KQL tables.

**Event schema**:
```json
{
  "event_id": "evt-000001",
  "event_time": "2026-05-12T10:30:00Z",
  "event_name": "order.prep.delayed",
  "entity_type": "order",
  "entity_id": "ORD-1001",
  "order_id": "ORD-1001",
  "channel": "delivery",
  "station_id": "grill",
  "ingredient_id": "",
  "severity": "warning",
  "payload": {
    "delay_minutes": 8.0
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

# 4. Configure RTI dashboard, Activator, and Operations Agent
py scripts/configure_fabric_artifacts.py

# 5. Configure the custom action User Data Function
py scripts/configure_user_data_function.py

# 6. Send demo events
py scripts/send_eventstream_events.py --scenario peak --orders 12 --interval-seconds 0.5

# 7. Query data (in Fabric portal)
# KQL: raw_restaurant_events | count
# KQL: order_events | count
```

## Troubleshooting

### "Session token expired" error

This is a temporary authentication issue. Retry the command:

```bash
py scripts/send_eventstream_events.py --scenario peak --orders 12 --interval-seconds 0.5
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
3. Check the raw KQL table is receiving: Query in KQL editor → `raw_restaurant_events | count`
4. Check update policies are routing rows: Query in KQL editor → `order_events | count`, `kitchen_events | count`, `inventory_events | count`

### Real-Time Dashboard load errors

The dashboard definition must use the current Fabric schema:
- Tiles reference queries with `tiles[].queryRef`.
- KQL text lives in `queries[]`.
- `queries[].dataSource.kind` is `inline`.
- Tiles must not include deprecated `usedParamVariables`.

Run `py scripts/configure_fabric_artifacts.py` to redeploy the corrected dashboard definition.

### Operations Agent actions are missing

This is expected. The script deploys the stable Operations Agent configuration without actions. Complete Power Automate or Teams approval action wiring manually in the Operations Agent UI.

## Remaining Manual Work

- Review Teams notification permissions in Activator.
- Attach Operations Agent actions in the Fabric UI.
- Run a final end-to-end demo and capture evidence:
  - `raw_restaurant_events | count`
  - `order_events | count`
  - `inventory_events | where stock_pct <= threshold_pct`
  - Dashboard tiles updating after event generation

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
| `FABRIC_EVENTHOUSE_NAME` | Yes | Eventhouse (KQL database) name |
| `FABRIC_KQL_DATABASE_NAME` | Yes | KQL database name |
| `FABRIC_EVENTSTREAM_NAME` | Yes | Eventstream name |
| `EVENTSTREAM_EVENTHUB_CONNECTION_STRING` | Yes | Event Hub connection string (from portal) |
| `FABRIC_ALERT_RECIPIENT` | No | Teams/email recipient for Activator and Operations Agent notifications; defaults to current Azure CLI user |

## References

- [Microsoft Fabric Documentation](https://learn.microsoft.com/en-us/fabric/)
- [Real-time Intelligence (RTI)](https://learn.microsoft.com/en-us/fabric/real-time-intelligence/)
- [Azure Event Hub SDK for Python](https://learn.microsoft.com/en-us/python/api/overview/azure/eventhub-readme)
- [KQL Query Language](https://learn.microsoft.com/en-us/kusto/query/)

## License

MIT

## Author

Copilot
