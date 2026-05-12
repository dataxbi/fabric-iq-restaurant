import argparse
import json
import os
import time
from datetime import datetime, timezone

from dotenv import load_dotenv
from fabric_client import FabricConfigError

load_dotenv()


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise FabricConfigError(f"Missing required environment variable: {name}")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Send demo events to Eventstream CustomEndpoint")
    parser.add_argument("--connection-string", default=None, help="Event Hub connection string from CustomEndpoint")
    parser.add_argument("--eventhub-name", default=None, help="Event Hub name override (optional)")
    parser.add_argument("--count", type=int, default=20, help="Number of events to send")
    parser.add_argument("--interval-seconds", type=float, default=1.0, help="Delay between events")
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


def make_event(idx: int) -> dict:
    return {
        "event_id": f"evt-{idx:05d}",
        "event_time": datetime.now(timezone.utc).isoformat(),
        "order_id": f"ORD-{1000 + idx}",
        "channel": "delivery" if idx % 2 == 0 else "in_store",
        "event_name": "order.created",
        "order_status": "created",
        "station_id": "kitchen-main",
        "delay_minutes": float(idx % 7),
        "payload": {
            "items": 1 + (idx % 4),
            "priority": "high" if idx % 5 == 0 else "normal",
        },
    }


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
    try:
        for i in range(1, args.count + 1):
            payload = json.dumps(make_event(i)).encode("utf-8")
            batch = producer.create_batch()
            batch.add(EventData(payload))
            producer.send_batch(batch)
            sent += 1
            if i < args.count:
                time.sleep(max(0.0, args.interval_seconds))
    finally:
        producer.close()

    print(json.dumps({"sentEvents": sent, "eventHub": eventhub_name}, indent=2))


if __name__ == "__main__":
    main()
