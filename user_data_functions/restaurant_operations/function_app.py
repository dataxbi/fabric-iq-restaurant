import datetime
import json
import logging
import uuid

import fabric.functions as fn

udf = fn.UserDataFunctions()
EVENT_HUB_CONNECTION_STRING = ""


def _require(value: str, name: str) -> str:
    if not value or not value.strip():
        raise fn.UserThrownError(f"{name} is required.", {name: value})
    return value.strip()


def _eventhub_name_from_connection_string(connection_string: str) -> str:
    for part in connection_string.split(";"):
        if part.startswith("EntityPath="):
            return part.split("=", 1)[1]
    raise fn.UserThrownError("EVENT_HUB_CONNECTION_STRING must include EntityPath.", {})


@udf.function()
def recordReprioritizeOrder(
    orderId: str,
    stationId: str,
    priority: str,
    reason: str,
    approvedBy: str,
    channel: str = "delivery",
    severity: str = "warning",
) -> dict:
    """
    Summary: Publish an approved restaurant reprioritization action event.
    Description: Sends an action.kitchen.reprioritized event to Event Hub so Eventstream ingests it into raw_restaurant_events and KQL update policies route it into action_events.
    """
    from azure.eventhub import EventData, EventHubProducerClient

    connection_string = _require(EVENT_HUB_CONNECTION_STRING, "EVENT_HUB_CONNECTION_STRING")
    order_id = _require(orderId, "orderId")
    station_id = _require(stationId, "stationId")
    action_id = f"act-{uuid.uuid4()}"
    event = {
        "event_time": datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z"),
        "event_id": f"evt-{uuid.uuid4()}",
        "event_name": "action.kitchen.reprioritized",
        "entity_type": "action",
        "entity_id": action_id,
        "order_id": order_id,
        "station_id": station_id,
        "ingredient_id": "",
        "channel": channel,
        "severity": severity,
        "payload": {
            "action_id": action_id,
            "action_status": "approved",
            "priority": priority,
            "reason": reason,
            "approved_by": approvedBy,
        },
    }
    producer = EventHubProducerClient.from_connection_string(
        conn_str=connection_string,
        eventhub_name=_eventhub_name_from_connection_string(connection_string),
    )
    try:
        batch = producer.create_batch()
        batch.add(EventData(json.dumps(event, separators=(",", ":"))))
        producer.send_batch(batch)
    finally:
        producer.close()
    logging.info("Published reprioritization action for order %s.", order_id)
    return {
        "published": True,
        "actionId": action_id,
        "eventId": event["event_id"],
        "eventName": event["event_name"],
        "orderId": order_id,
        "stationId": station_id,
    }
