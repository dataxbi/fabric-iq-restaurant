"""DEPRECATED — use simulate_restaurant.py instead.

  python simulate_restaurant.py --orders 20 --scenario peak
"""

import argparse
import json
import os
import time
from datetime import datetime, timezone

from dotenv import load_dotenv
from fabric_client import FabricConfigError

load_dotenv()


STATIONS = ["grill", "fryer", "sauces", "assembly"]
CHANNELS = ["delivery", "in_store", "pickup"]
INGREDIENTS = ["brioche_bun", "tomato", "lettuce", "chicken", "cheese"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Send restaurant demo events to Eventstream CustomEndpoint")
    parser.add_argument("--connection-string", default=None, help="Event Hub connection string from CustomEndpoint")
    parser.add_argument("--eventhub-name", default=None, help="Event Hub name override (optional)")
    parser.add_argument("--orders", type=int, default=12, help="Number of synthetic orders to simulate")
    parser.add_argument("--interval-seconds", type=float, default=0.5, help="Delay between events")
    parser.add_argument(
        "--scenario",
        default="peak",
        choices=["normal", "peak", "stock-critical"],
        help="Operational scenario to simulate",
    )
    return parser


def parse_connection_string(connection_string: str) -> dict[str, str]:
    parts = {}
    for segment in connection_string.split(";"):
        if "=" not in segment:
            continue
        key, value = segment.split("=", 1)
        parts[key.strip()] = value.strip()
    required = {"Endpoint", "SharedAccessKeyName", "SharedAccessKey", "EntityPath"}
    missing = [key for key in required if key not in parts or not parts[key]]
    if missing:
        raise FabricConfigError(f"Invalid Event Hub connection string. Missing: {', '.join(missing)}")
    return parts


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def base_event(idx: int, event_name: str, entity_type: str, entity_id: str, **values: object) -> dict:
    order_id = str(values.get("order_id") or "")
    station_id = str(values.get("station_id") or "")
    ingredient_id = str(values.get("ingredient_id") or "")
    channel = str(values.get("channel") or "")
    severity = str(values.get("severity") or "info")
    payload = {key: value for key, value in values.items() if value is not None}

    return {
        "event_time": utc_now(),
        "event_id": f"evt-{idx:06d}",
        "event_name": event_name,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "order_id": order_id,
        "station_id": station_id,
        "ingredient_id": ingredient_id,
        "channel": channel,
        "severity": severity,
        "payload": payload,
    }


def build_order_events(order_number: int, start_idx: int, scenario: str) -> list[dict]:
    order_id = f"ORD-{1000 + order_number}"
    channel = CHANNELS[order_number % len(CHANNELS)]
    station = STATIONS[order_number % len(STATIONS)]
    high_pressure = scenario == "peak" and order_number % 3 == 0
    stock_pressure = scenario == "stock-critical" or order_number % 5 == 0
    delay_minutes = 8.0 if high_pressure else float(order_number % 4)
    queue_size = 9 if high_pressure else 3 + (order_number % 4)
    stock_pct = 8.0 if stock_pressure else 35.0 + order_number
    sentiment = "negative" if high_pressure and channel == "delivery" else "neutral"
    severity = "warning" if high_pressure or stock_pressure else "info"

    events = [
        base_event(
            start_idx,
            "order.created",
            "order",
            order_id,
            order_id=order_id,
            channel=channel,
            station_id=station,
            order_status="created",
            items=1 + (order_number % 4),
            priority="high" if high_pressure else "normal",
        ),
        base_event(
            start_idx + 1,
            "kitchen.station.updated",
            "station",
            station,
            station_id=station,
            station_status="saturated" if high_pressure else "normal",
            queue_size=queue_size,
            capacity=6,
            severity="warning" if high_pressure else "info",
        ),
        base_event(
            start_idx + 2,
            "inventory.level.changed",
            "ingredient",
            INGREDIENTS[order_number % len(INGREDIENTS)],
            ingredient_id=INGREDIENTS[order_number % len(INGREDIENTS)],
            stock_pct=stock_pct,
            threshold_pct=15.0,
            delta=-2.5,
            severity="warning" if stock_pressure else "info",
        ),
    ]

    if high_pressure:
        events.append(
            base_event(
                start_idx + 3,
                "order.prep.delayed",
                "order",
                order_id,
                order_id=order_id,
                channel=channel,
                station_id=station,
                delay_minutes=delay_minutes,
                queue_size=queue_size,
                severity=severity,
            )
        )

    if sentiment == "negative":
        events.append(
            base_event(
                start_idx + 4,
                "customer.sentiment.signal",
                "order",
                order_id,
                order_id=order_id,
                channel=channel,
                sentiment=sentiment,
                reason="delivery_delay_risk",
                severity="warning",
            )
        )

    events.append(
        base_event(
            start_idx + 5,
            "payment.completed",
            "order",
            order_id,
            order_id=order_id,
            channel=channel,
            amount=18.5 + order_number,
            payment_method="card",
        )
    )
    return events


def generate_events(order_count: int, scenario: str) -> list[dict]:
    events = []
    idx = 1
    for order_number in range(1, order_count + 1):
        order_events = build_order_events(order_number, idx, scenario)
        events.extend(order_events)
        idx += 10
    return events


def main() -> None:
    try:
        from azure.eventhub import EventData, EventHubProducerClient
    except ImportError as exc:
        raise FabricConfigError(
            "Missing dependency azure-eventhub. Install with: py -m pip install azure-eventhub"
        ) from exc

    args = build_parser().parse_args()
    connection_string = args.connection_string or os.environ.get("EVENTSTREAM_EVENTHUB_CONNECTION_STRING", "").strip()
    if not connection_string:
        raise FabricConfigError("Missing EVENTSTREAM_EVENTHUB_CONNECTION_STRING in environment")

    cs = parse_connection_string(connection_string)
    eventhub_name = args.eventhub_name or cs["EntityPath"]
    producer = EventHubProducerClient.from_connection_string(
        conn_str=connection_string,
        eventhub_name=eventhub_name,
    )

    sent = 0
    event_names = []
    events = generate_events(args.orders, args.scenario)
    try:
        for event in events:
            payload = json.dumps(event, separators=(",", ":")).encode("utf-8")
            batch = producer.create_batch()
            batch.add(EventData(payload))
            producer.send_batch(batch)
            sent += 1
            event_names.append(event["event_name"])
            if sent < len(events):
                time.sleep(max(0.0, args.interval_seconds))
    finally:
        producer.close()

    counts = {event_name: event_names.count(event_name) for event_name in sorted(set(event_names))}
    print(json.dumps({"sentEvents": sent, "eventHub": eventhub_name, "scenario": args.scenario, "eventCounts": counts}, indent=2))


if __name__ == "__main__":
    main()
