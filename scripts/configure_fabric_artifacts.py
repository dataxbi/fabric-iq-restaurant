import argparse
import base64
import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from fabric_client import FabricApiError, FabricClient, FabricConfigError, require_env


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_NAMESPACE = uuid.UUID("a2eb06f7-9e90-4ea7-83f8-5ab1c4b9d19d")


def default_recipient() -> str:
    configured = os.environ.get("FABRIC_ALERT_RECIPIENT", "").strip()
    if configured:
        return configured
    az_command = shutil.which("az") or shutil.which("az.cmd")
    if not az_command:
        default_az_cmd = r"C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd"
        if os.path.exists(default_az_cmd):
            az_command = default_az_cmd
    if not az_command:
        raise FabricConfigError("Set FABRIC_ALERT_RECIPIENT or install Azure CLI and run az login.")
    result = subprocess.run(
        [az_command, "account", "show", "--query", "user.name", "-o", "tsv"],
        capture_output=True,
        text=True,
        check=False,
    )
    recipient = result.stdout.strip()
    if result.returncode == 0 and "@" in recipient:
        return recipient
    raise FabricConfigError("Set FABRIC_ALERT_RECIPIENT or sign in with az login using a user account.")


def to_inline_base64(payload: dict | list) -> str:
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def inline_part(path: str, payload: dict | list) -> dict:
    return {"path": path, "payload": to_inline_base64(payload), "payloadType": "InlineBase64"}


def platform_part(item_type: str, display_name: str, description: str) -> dict:
    return inline_part(
        ".platform",
        {
            "$schema": "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json",
            "metadata": {"type": item_type, "displayName": display_name, "description": description},
            "config": {"version": "2.0", "logicalId": str(uuid.UUID(int=0))},
        },
    )


def visual_options() -> dict:
    return {
        "xColumn": None,
        "yColumns": None,
        "yAxisMinimumValue": None,
        "yAxisMaximumValue": None,
        "seriesColumns": None,
        "hideLegend": False,
        "legendLocation": "bottom",
        "xColumnTitle": "",
        "yColumnTitle": "",
        "horizontalLine": "",
        "verticalLine": "",
        "xAxisScale": "linear",
        "yAxisScale": "linear",
        "crossFilterDisabled": False,
        "drillthroughDisabled": True,
        "hideTileTitle": False,
        "crossFilter": [],
        "drillthrough": [],
        "selectedDataOnLoad": {"all": True, "limit": 50},
        "dataPointsTooltip": {"all": True, "limit": 50},
        "multipleYAxes": {
            "base": {
                "id": "-1",
                "columns": [],
                "label": "",
                "yAxisMinimumValue": None,
                "yAxisMaximumValue": None,
                "yAxisScale": "linear",
                "horizontalLines": [],
            },
            "additional": [],
            "showMultiplePanels": False,
        },
    }


def dashboard_tile(
    title: str,
    query_id: str,
    layout: dict,
    page_id: str,
    visual_type: str = "table",
) -> dict:
    return {
        "id": str(uuid.uuid5(DASHBOARD_NAMESPACE, f"tile:{title}")),
        "title": title,
        "layout": layout,
        "pageId": page_id,
        "visualType": visual_type,
        "queryRef": {"kind": "query", "queryId": query_id},
        "visualOptions": visual_options(),
    }


def build_dashboard_parts(title: str, database_name: str, query_service_uri: str) -> list[dict]:
    page_id = str(uuid.uuid5(DASHBOARD_NAMESPACE, "page:operations"))
    data_source_id = str(uuid.uuid5(DASHBOARD_NAMESPACE, "data-source:restaurant-rti"))
    time_parameter_id = str(uuid.uuid5(DASHBOARD_NAMESPACE, "parameter:time-range"))
    tile_definitions = [
        {
            "title": "Raw Event Throughput",
            "query": """
raw_restaurant_events
| summarize Events=count() by bin(event_time, 1m), event_name
| order by event_time asc
""",
            "layout": {"x": 0, "y": 0, "width": 12, "height": 6},
            "visual_type": "line",
        },
        {
            "title": "Delayed Orders",
            "query": """
order_events
| where event_name == "order.prep.delayed"
| extend queue_size = tolong(payload.queue_size)
| project event_time, order_id, channel, station_id, delay_minutes, queue_size, severity
| order by event_time desc
| take 50
""",
            "layout": {"x": 12, "y": 0, "width": 12, "height": 6},
            "visual_type": "table",
        },
        {
            "title": "Station Status — Live",
            "query": """
let active_orders =
    order_events
    | where event_time >= ago(10m)
    | summarize arg_max(event_time, order_status) by order_id, station_id
    | where order_status !in ("completed", "cancelled")
    | summarize active_orders=count() by station_id;
stations
| join kind=leftouter active_orders on station_id
| extend active_orders = coalesce(active_orders, 0)
| extend queue_size = max_of(0, active_orders - max_capacity)
| extend load_pct = iif(max_capacity > 0, round(100.0 * todouble(active_orders) / todouble(max_capacity), 1), real(0))
| extend drain_minutes = iif(queue_size > 0 and avg_prep_minutes > 0, round(todouble(queue_size) * avg_prep_minutes / todouble(max_capacity), 1), real(0))
| extend station_status = case(load_pct >= 100, "saturated", load_pct >= 75, "busy", active_orders > 0, "active", "idle")
| extend severity = case(load_pct >= 100, "critical", load_pct >= 75, "warning", "info")
| project station_id, display_name, specialization, station_status, active_orders, queue_size, max_capacity, load_pct, drain_minutes, severity
| order by load_pct desc
""",
            "layout": {"x": 0, "y": 6, "width": 14, "height": 7},
            "visual_type": "table",
        },
        {
            "title": "Station Queue Pressure",
            "query": """
order_events
| where event_time > ago(1h)
| summarize
    Created  = countif(event_name == "order.created"),
    Delayed  = countif(event_name == "order.prep.delayed"),
    Completed = countif(event_name == "payment.completed")
    by station_id, bin(event_time, 5m)
| order by event_time asc
""",
            "layout": {"x": 14, "y": 6, "width": 10, "height": 7},
            "visual_type": "line",
        },
        {
            "title": "Critical Inventory",
            "query": """
inventory_events
| where stock_pct <= threshold_pct
| summarize arg_max(event_time, *) by ingredient_id
| project event_time, ingredient_id, stock_pct, threshold_pct, severity
| order by stock_pct asc
""",
            "layout": {"x": 0, "y": 13, "width": 8, "height": 6},
            "visual_type": "table",
        },
        {
            "title": "Agent / Approval / Action Trace",
            "query": """
union
    (agent_events | project event_time, event_name="agent.recommendation.created", entity_id=recommendation_id, order_id, severity, payload),
    (approval_events | project event_time, event_name=strcat("approval.", approval_status), entity_id=recommendation_id, order_id="", severity, payload),
    (action_events | project event_time, event_name=action_type, entity_id=action_id, order_id="", severity, payload)
| order by event_time desc
| take 100
""",
            "layout": {"x": 8, "y": 13, "width": 16, "height": 6},
            "visual_type": "table",
        },
        {
            "title": "Complex Agent Review Candidates",
            "query": """
let DelayedOrders =
    order_events
    | where event_name == "order.prep.delayed"
    | extend queue_size = tolong(payload.queue_size)
    | where delay_minutes >= 5 and queue_size >= 7
    | project order_id, channel, station_id, delay_time=event_time, delay_minutes, queue_size;
let NegativeSignals =
    order_events
    | where event_name == "customer.sentiment.signal"
    | extend sentiment = tostring(payload.sentiment), reason = tostring(payload.reason)
    | where sentiment == "negative"
    | project order_id, sentiment_time=event_time, sentiment, reason;
DelayedOrders
| join kind=leftouter NegativeSignals on order_id
| extend requires_agent_review = isnotempty(sentiment) or delay_minutes >= 8
| where requires_agent_review
| project delay_time, order_id, channel, station_id, delay_minutes, queue_size, sentiment, reason
| order by delay_time desc
""",
            "layout": {"x": 0, "y": 19, "width": 24, "height": 7},
            "visual_type": "table",
        },
    ]
    queries = []
    tiles = []
    for tile_definition in tile_definitions:
        query_id = str(uuid.uuid5(DASHBOARD_NAMESPACE, f"query:{tile_definition['title']}"))
        queries.append(
            {
                "dataSource": {"kind": "inline", "dataSourceId": data_source_id},
                "text": tile_definition["query"].strip(),
                "id": query_id,
                "usedVariables": [],
            }
        )
        tiles.append(
            dashboard_tile(
                tile_definition["title"],
                query_id,
                tile_definition["layout"],
                page_id,
                tile_definition["visual_type"],
            )
        )
    dashboard = {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/kqlDashboard/definition/1.0.0/schema.json",
        "id": str(uuid.uuid5(DASHBOARD_NAMESPACE, "dashboard:restaurant-operations-rti")),
        "eTag": '""',
        "autoRefresh": {"enabled": True, "defaultInterval": "30s", "minInterval": "10s"},
        "baseQueries": [],
        "tiles": tiles,
        "dataSources": [
            {
                "id": data_source_id,
                "name": database_name,
                "clusterUri": query_service_uri,
                "database": database_name,
                "kind": "manual-kusto",
                "scopeId": "KustoDatabaseResource",
            }
        ],
        "pages": [{"name": "Operations", "id": page_id}],
        "parameters": [
            {
                "kind": "duration",
                "id": time_parameter_id,
                "displayName": "Time range",
                "description": "",
                "beginVariableName": "_startTime",
                "endVariableName": "_endTime",
                "defaultValue": {"kind": "dynamic", "count": 1, "unit": "hours"},
                "showOnPages": {"kind": "all"},
            }
        ],
        "queries": queries,
        "schema_version": "52",
        "title": title,
    }
    return [inline_part("RealTimeDashboard.json", dashboard)]


def build_operations_agent_parts(
    playbook_path: Path,
    workspace_id: str,
    kql_database_id: str,
    recipient: str,
    display_name: str,
    include_actions: bool,
) -> list[dict]:
    playbook = json.loads(playbook_path.read_text(encoding="utf-8"))
    goals = "\n".join(f"- {goal}" for goal in playbook["businessGoals"])
    instructions = "\n".join(f"- {instruction}" for instruction in playbook["instructions"])
    for condition in playbook["complexConditions"]:
        instructions += (
            f"\n- Complex condition '{condition['name']}': {condition['description']} "
            f"Recommended action: {condition['recommendedAction']}"
        )

    configuration = {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/operationsAgents/definition/1.0.0/schema.json",
        "configuration": {
            "goals": goals,
            "instructions": instructions,
            "dataSources": {
                "restaurantKql": {
                    "id": kql_database_id,
                    "type": "KustoDatabase",
                    "workspaceId": workspace_id,
                }
            },
            "actions": {},
            "recipient": recipient,
        },
        "shouldRun": False,
    }
    if include_actions:
        configuration["configuration"]["actions"] = {
            action["name"]: {
                "id": str(uuid.uuid4()),
                "displayName": action["name"],
                "description": f"Recommended restaurant operation: {action['name']}",
                "kind": "PowerAutomateAction",
                "parameters": [{"name": parameter, "description": parameter.replace("_", " ")} for parameter in action["parameters"]],
            }
            for action in playbook["customActions"]
        }
    return [
        inline_part("Configurations.json", configuration),
        platform_part(
            "OperationsAgent",
            display_name,
            "Operations Agent for complex restaurant recommendations",
        ),
    ]


def teams_binding(recipient: str, headline: str, message: str) -> dict:
    return {
        "name": "TeamsBinding",
        "kind": "TeamsMessage",
        "arguments": [
            {"name": "messageLocale", "type": "string", "value": ""},
            {"name": "recipients", "type": "array", "values": [{"type": "string", "value": recipient}]},
            {"name": "headline", "type": "array", "values": [{"type": "string", "value": headline}]},
            {"name": "optionalMessage", "type": "array", "values": [{"type": "string", "value": message}]},
            {"name": "additionalInformation", "type": "array", "values": []},
        ],
    }


def source_event_entity(container_id: str, source_id: str, name: str) -> tuple[dict, str]:
    event_id = str(uuid.uuid4())
    instance = {
        "templateId": "SourceEvent",
        "templateVersion": "1.2.4",
        "steps": [
            {
                "name": "SourceEventStep",
                "id": str(uuid.uuid4()),
                "rows": [
                    {
                        "name": "SourceSelector",
                        "kind": "SourceReference",
                        "arguments": [{"name": "entityId", "type": "string", "value": source_id}],
                    }
                ],
            }
        ],
    }
    return (
        {
            "uniqueIdentifier": event_id,
            "payload": {
                "name": name,
                "parentContainer": {"targetUniqueIdentifier": container_id},
                "definition": {"type": "Event", "instance": json.dumps(instance, separators=(",", ":"))},
            },
            "type": "timeSeriesView-v1",
        },
        event_id,
    )


def event_trigger_rule(container_id: str, event_id: str, name: str, recipient: str, headline: str, message: str) -> dict:
    instance = {
        "templateId": "EventTrigger",
        "templateVersion": "1.2.4",
        "steps": [
            {
                "name": "FieldsDefaultsStep",
                "id": str(uuid.uuid4()),
                "rows": [
                    {
                        "name": "EventSelector",
                        "kind": "Event",
                        "arguments": [
                            {
                                "kind": "EventReference",
                                "type": "complex",
                                "arguments": [{"name": "entityId", "type": "string", "value": event_id}],
                                "name": "event",
                            }
                        ],
                    }
                ],
            },
            {
                "name": "EventDetectStep",
                "id": str(uuid.uuid4()),
                "rows": [{"name": "OnEveryValue", "kind": "OnEveryValue", "arguments": []}],
            },
            {
                "name": "ActStep",
                "id": str(uuid.uuid4()),
                "rows": [teams_binding(recipient, headline, message)],
            },
        ],
    }
    return {
        "uniqueIdentifier": str(uuid.uuid4()),
        "payload": {
            "name": name,
            "description": "Created by: fabric-iq-restaurant automation",
            "parentContainer": {"targetUniqueIdentifier": container_id},
            "definition": {
                "type": "Rule",
                "instance": json.dumps(instance, separators=(",", ":")),
                "settings": {"shouldRun": True, "shouldApplyRuleOnUpdate": False},
            },
        },
        "type": "timeSeriesView-v1",
    }


def kql_source_entity(container_id: str, workspace_id: str, kql_database_id: str, name: str, query: str) -> tuple[dict, str]:
    source_id = str(uuid.uuid4())
    return (
        {
            "uniqueIdentifier": source_id,
            "payload": {
                "name": name,
                "runSettings": {"executionIntervalInSeconds": 300},
                "query": {"queryString": query.strip()},
                "eventhouseItem": {
                    "itemId": kql_database_id,
                    "workspaceId": workspace_id,
                    "itemType": "KustoDatabase",
                },
                "queryParameters": [],
                "metadata": {"workspaceId": workspace_id, "measureName": "", "querySetId": "", "queryId": ""},
                "parentContainer": {"targetUniqueIdentifier": container_id},
            },
            "type": "kqlSource-v1",
        },
        source_id,
    )


def build_reflex_parts(display_name: str, workspace_id: str, kql_database_id: str, recipient: str) -> list[dict]:
    container_id = str(uuid.uuid4())
    entities = [
        {
            "uniqueIdentifier": container_id,
            "payload": {"name": display_name, "type": "kqlQueries"},
            "type": "container-v1",
        },
    ]
    definitions = [
        {
            "source_name": "Delayed orders with high station queue",
            "event_name": "Delayed order alert events",
            "rule_name": "DelayedOrderHighQueue",
            "headline": "Restaurant alert: delayed order with high queue",
            "message": "A delayed order is waiting behind a high station queue. Review the station and reprioritize if needed.",
            "query": """
order_events
| where event_name == "order.prep.delayed"
| extend queue_size = tolong(payload.queue_size)
| where delay_minutes >= 5 and queue_size >= 7
| project event_time, order_id, channel, station_id, delay_minutes, queue_size, severity
""",
        },
        {
            "source_name": "Critical inventory",
            "event_name": "Critical inventory alert events",
            "rule_name": "CriticalInventory",
            "headline": "Restaurant alert: ingredient below threshold",
            "message": "An ingredient has fallen below its threshold. Trigger replenishment or prepare substitutions.",
            "query": """
inventory_events
| where stock_pct <= threshold_pct
| project event_time, ingredient_id, stock_pct, threshold_pct, severity
""",
        },
        {
            "source_name": "Delivery channel saturation",
            "event_name": "Delivery saturation alert events",
            "rule_name": "DeliveryChannelSaturation",
            "headline": "Restaurant alert: delivery channel saturation",
            "message": "Three or more delivery delays were detected in a five-minute window. Consider throttling delivery intake.",
            "query": """
order_events
| where event_name == "order.prep.delayed" and channel == "delivery"
| where delay_minutes >= 5
| summarize delayed_count=count(), max_delay=max(delay_minutes) by bin(event_time, 5m), channel
| where delayed_count >= 3
| project event_time, channel, delayed_count, max_delay, severity="warning"
""",
        },
    ]
    for definition in definitions:
        source, source_id = kql_source_entity(container_id, workspace_id, kql_database_id, definition["source_name"], definition["query"])
        source_event, event_id = source_event_entity(container_id, source_id, definition["event_name"])
        rule = event_trigger_rule(
            container_id,
            event_id,
            definition["rule_name"],
            recipient,
            definition["headline"],
            definition["message"],
        )
        entities.extend([source, source_event, rule])
    return [inline_part("ReflexEntities.json", entities)]


def ensure_item_after_name_reservation(
    client: FabricClient,
    workspace_id: str,
    collection: str,
    display_name: str,
    extra: dict,
) -> dict:
    deadline = time.time() + 240
    last_error: FabricApiError | None = None
    while time.time() < deadline:
        existing = client.find_item(workspace_id, collection, display_name)
        if existing:
            return existing
        try:
            return client.ensure_item(workspace_id, collection, display_name, extra)
        except FabricApiError as exc:
            if "ItemDisplayNameNotAvailableYet" not in str(exc):
                raise
            last_error = exc
            time.sleep(20)
    raise FabricApiError(f"Timed out waiting for {display_name} to become available after preview API failure: {last_error}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create Fabric UI artifacts for the restaurant RTI demo")
    parser.add_argument("--workspace-name", default=None, help="Fabric workspace name")
    parser.add_argument("--eventstream-name", default=None, help="Eventstream display name")
    parser.add_argument("--kql-database-name", default=None, help="KQL database display name")
    parser.add_argument("--dashboard-name", default="Restaurant Operations RTI", help="KQL dashboard display name")
    parser.add_argument("--activator-name", default="Restaurant Operations Activator", help="Reflex/Activator display name")
    parser.add_argument("--agent-name", default="RestaurantOperationsAgent", help="Operations Agent display name")
    parser.add_argument("--recipient", default=None, help="Teams/email recipient for Activator and Operations Agent")
    parser.add_argument(
        "--include-agent-actions",
        action="store_true",
        help="Attempt preview Operations Agent Power Automate action definitions. Disabled by default because the API can corrupt definition readback.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    workspace_name = args.workspace_name or require_env("FABRIC_WORKSPACE_NAME")
    eventstream_name = args.eventstream_name or require_env("FABRIC_EVENTSTREAM_NAME")
    database_name = args.kql_database_name or require_env("FABRIC_KQL_DATABASE_NAME")
    recipient = args.recipient or default_recipient()

    client = FabricClient()
    workspace = client.resolve_workspace(workspace_name)
    workspace_id = workspace["id"]

    kql_database = client.find_item(workspace_id, "kqlDatabases", database_name)
    if not kql_database:
        raise FabricConfigError(f"KQL database not found: {database_name}")
    eventstream = client.find_item(workspace_id, "eventstreams", eventstream_name)
    if not eventstream:
        raise FabricConfigError(f"Eventstream not found: {eventstream_name}")
    eventhouse = client.find_item(workspace_id, "eventhouses", require_env("FABRIC_EVENTHOUSE_NAME"))
    if not eventhouse:
        raise FabricConfigError(f"Eventhouse not found: {require_env('FABRIC_EVENTHOUSE_NAME')}")
    query_service_uri = client.get_eventhouse_query_service_uri(workspace_id, eventhouse["id"])

    dashboard = client.create_item_with_definition(
        workspace_id,
        args.dashboard_name,
        "KQLDashboard",
        build_dashboard_parts(args.dashboard_name, database_name, query_service_uri),
        description="Restaurant operations Real-Time Dashboard",
        collection="kqlDashboards",
    )
    client.update_item_definition(
        workspace_id,
        dashboard["id"],
        build_dashboard_parts(args.dashboard_name, database_name, query_service_uri),
    )
    activator = client.create_item_with_definition(
        workspace_id,
        args.activator_name,
        "Reflex",
        build_reflex_parts(args.activator_name, workspace_id, kql_database["id"], recipient),
        description="Activator rules for restaurant operations",
        collection="reflexes",
    )
    client.update_item_definition(
        workspace_id,
        activator["id"],
        build_reflex_parts(args.activator_name, workspace_id, kql_database["id"], recipient),
    )
    existing_agent = client.find_item(workspace_id, "operationsAgents", args.agent_name)
    agent_definition_status = "not-updated-existing-item"
    if existing_agent:
        agent = existing_agent
    else:
        try:
            agent = client.create_item_with_definition(
                workspace_id,
                args.agent_name,
                "OperationsAgent",
                build_operations_agent_parts(
                    ROOT / "config" / "operations_agent_playbook.json",
                    workspace_id,
                    kql_database["id"],
                    recipient,
                    args.agent_name,
                    args.include_agent_actions,
                ),
                description="Operations Agent for complex restaurant recommendations",
                collection="operationsAgents",
            )
            agent_definition_status = "applied"
        except FabricApiError as exc:
            agent_definition_status = "definition-rejected-shell-created"
            print(f"Operations Agent definition was not accepted by the preview API: {exc}")
            agent = ensure_item_after_name_reservation(
                client,
                workspace_id,
                "operationsAgents",
                args.agent_name,
                {"description": "Operations Agent for complex restaurant recommendations"},
            )
    try:
        client.update_item_definition(
            workspace_id,
            agent["id"],
            build_operations_agent_parts(
                ROOT / "config" / "operations_agent_playbook.json",
                workspace_id,
                kql_database["id"],
                recipient,
                args.agent_name,
                args.include_agent_actions,
            ),
            definition_format="OperationsAgentV1",
            update_metadata=True,
            collection="operationsAgents",
        )
        agent_definition_status = "updated-without-actions"
    except FabricApiError as exc:
        print(f"Operations Agent definition was not accepted by the preview API, retrying without actions: {exc}")
        client.update_item_definition(
            workspace_id,
            agent["id"],
            build_operations_agent_parts(
                ROOT / "config" / "operations_agent_playbook.json",
                workspace_id,
                kql_database["id"],
                recipient,
                args.agent_name,
                False,
            ),
            definition_format="OperationsAgentV1",
            update_metadata=True,
            collection="operationsAgents",
        )
        agent_definition_status = "updated-without-actions"
    if agent_definition_status == "not-updated-existing-item":
        agent_definition_status = "updated"

    print(
        json.dumps(
            {
                "workspace": workspace_name,
                "dashboard": {"name": args.dashboard_name, "id": dashboard["id"], "type": dashboard["type"]},
                "activator": {"name": args.activator_name, "id": activator["id"], "type": activator["type"]},
                "operationsAgent": {
                    "name": args.agent_name,
                    "id": agent["id"],
                    "type": agent["type"],
                    "definitionStatus": agent_definition_status,
                },
                "manualFollowUp": [
                    "Review dashboard visuals in the Real-Time Intelligence UI.",
                    "Review Activator Teams notification permissions and enable rules if the preview UI requires confirmation.",
                    "Attach Power Automate or Teams approval actions to the Operations Agent in the UI before setting it to run.",
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
