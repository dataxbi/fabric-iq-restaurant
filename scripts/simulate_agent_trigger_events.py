#!/usr/bin/env python3
"""Simulate events to trigger Operations Agent conditions and agent decisions.

The emitted JSON matches the repository routing pattern:
raw_restaurant_events -> update policies ->
    order_events / kitchen_events / inventory_events /
    agent_events / approval_events / action_events.

Trigger scenarios (3 types) feed order/kitchen/inventory tables.
Decision scenarios simulate the full loop: recommendation -> approval -> action.
"""

import os
import json
import random
import time
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4
from azure.eventhub import EventHubProducerClient, EventData
from dotenv import load_dotenv

# Load .env from repo root (not from scripts/ directory)
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

# Configuration
EVENT_HUB_CONN_STR = os.getenv("EVENTSTREAM_EVENTHUB_CONNECTION_STRING")
if not EVENT_HUB_CONN_STR:
    raise ValueError("EVENTSTREAM_EVENTHUB_CONNECTION_STRING not set in .env")

STATIONS = ["grill", "fryer", "sauces", "assembly"]
CHANNELS = ["delivery", "dine-in", "takeout"]
INGREDIENTS = ["beef", "chicken", "fries", "sauce_bbq", "sauce_mayo"]
FEEDBACK_LEVELS = ["muy_negativo", "negativo", "neutral", "positivo"]
CANCEL_HISTORY = ["none", "cancelado_1_vez", "cancelado_2_veces", "cancelado_3_veces"]

# Buffer of pending orders waiting to be completed.
# Each entry: {"order_id": str, "station_id": str, "channel": str, "ready_at": float}
_pending_orders: list[dict] = []
# Max orders held in buffer before oldest are dropped (prevents unbounded growth)
_MAX_PENDING = 30

def now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def enqueue_order(order_id: str, station_id: str, channel: str, prep_seconds: int = None) -> None:
    """Register an order as pending so it can be completed later.

    prep_seconds: simulated prep time before the order is ready to complete.
    Defaults to a random value based on the station's avg_prep_minutes.
    """
    if prep_seconds is None:
        # Simulate realistic prep times: 30s–3min for demo speed
        prep_seconds = random.randint(30, 180)
    _pending_orders.append({
        "order_id": order_id,
        "station_id": station_id,
        "channel": channel,
        "ready_at": time.time() + prep_seconds,
    })
    # Keep buffer bounded — drop oldest if over limit
    while len(_pending_orders) > _MAX_PENDING:
        _pending_orders.pop(0)


def random_sla_minutes() -> int:
    """Random SLA remaining: 3-18 minutes."""
    return random.randint(3, 18)


def random_cancellation_history() -> str:
    """Random cancellation history with skew towards fewer cancellations."""
    weights = [70, 15, 10, 5]  # 70% none, 15% one, 10% two, 5% three
    return random.choices(CANCEL_HISTORY, weights=weights, k=1)[0]


def random_feedback() -> str:
    """Random feedback with realistic distribution."""
    weights = [5, 15, 60, 20]  # 5% very negative, 15% negative, 60% neutral, 20% positive
    return random.choices(FEEDBACK_LEVELS, weights=weights, k=1)[0]


def random_is_premium() -> bool:
    """Random premium status: ~20% premium clients."""
    return random.random() < 0.20


def base_event(
    event_name: str,
    entity_type: str,
    entity_id: str,
    order_id: str = "",
    station_id: str = "",
    ingredient_id: str = "",
    channel: str = "",
    severity: str = "info",
    **payload: object,
) -> dict:
    return {
        "event_time": now_iso(),
        "event_id": str(uuid4()),
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


def publish_event(producer: EventHubProducerClient, event: dict, event_name: str):
    """Publish one event to Event Hub."""
    body = json.dumps(event).encode("utf-8")
    batch = producer.create_batch()
    batch.add(EventData(body))
    producer.send_batch(batch)
    print(f"  Published: {event_name} -> {event.get('order_id', event.get('ingredient_id', 'N/A'))}")


def scenario_premium_client_near_sla():
    """
    PremiumClientNearSLA: Premium client with cancellation history, negative feedback, SLA < 10min.
    Varies: sla_remaining (3-8min), cancellation_history, feedback, delay_minutes.
    """
    print("\n=== Scenario: PremiumClientNearSLA ===")
    producer = EventHubProducerClient.from_connection_string(EVENT_HUB_CONN_STR)
    try:
        order_id = f"ORD-PREMIUM-{int(time.time())}-{random.randint(1000, 9999)}"
        sla_min = random.randint(3, 8)  # Force < 10min to trigger condition
        delay_min = random.randint(5, 8)
        cancel_hist = random_cancellation_history()
        feedback = random_feedback()
        station = random.choice(STATIONS)
        
        # order.created (includes premium and sentiment context in payload)
        order_created = base_event(
            event_name="order.created",
            entity_type="order",
            entity_id=order_id,
            order_id=order_id,
            station_id=station,
            channel=random.choice(CHANNELS),
            severity="warning",
            order_status="created",
            is_premium=True,
            type="premium",
            cancellation_history=cancel_hist,
            feedback=feedback,
            sla_remaining=sla_min,
        )
        publish_event(producer, order_created, "order.created")

        # delayed order signal (used by existing routing/alerts)
        delayed = base_event(
            event_name="order.prep.delayed",
            entity_type="order",
            entity_id=order_id,
            order_id=order_id,
            station_id=station,
            channel=random.choice(CHANNELS),
            severity="critical",
            order_status="in_prep",
            delay_minutes=delay_min,
            queue_size=random.randint(5, 10),
            is_premium=True,
            type="premium",
            cancellation_history=cancel_hist,
            feedback=feedback,
            sla_remaining=sla_min,
        )
        publish_event(producer, delayed, "order.prep.delayed")

        kitchen = base_event(
            event_name="kitchen.station.updated",
            entity_type="station",
            entity_id=station,
            station_id=station,
            severity="warning",
            station_status="saturated",
            queue_size=random.randint(6, 10),
            capacity=4,
        )
        publish_event(producer, kitchen, "kitchen.station.updated")

        channel = order_created["channel"]
        enqueue_order(order_id, station, channel)
        print(f"  ✓ Premium {order_id}: SLA={sla_min}min, delay={delay_min}min, cancel={cancel_hist}, feedback={feedback}")
    finally:
        producer.close()


def scenario_anomalous_station_queue():
    """
    AnomalousStationQueue: High queue at a station, analyze root cause (staff/ingredients/seasonality).
    Varies: station, queue_depth, stock levels, delay patterns.
    """
    print("\n=== Scenario: AnomalousStationQueue ===")
    producer = EventHubProducerClient.from_connection_string(EVENT_HUB_CONN_STR)
    try:
        station = random.choice(STATIONS)
        queue_depth = random.randint(5, 8)
        ingredient = random.choice(INGREDIENTS)
        stock_pct = random.randint(5, 15)  # Critical stock levels
        
        # Ingredient stock alert
        inventory = base_event(
            event_name="inventory.level.changed",
            entity_type="ingredient",
            entity_id=ingredient,
            ingredient_id=ingredient,
            severity="warning",
            stock_pct=stock_pct,
            threshold_pct=20.0,
            delta=random.randint(-10, -2),
        )
        publish_event(producer, inventory, "inventory.level.changed")

        # Queue of orders with varied delays and customer types
        for i in range(queue_depth):
            order_id = f"ORD-QUEUE-{int(time.time())}-{i}"
            is_premium = random_is_premium()
            order_event = base_event(
                event_name="order.prep.delayed",
                entity_type="order",
                entity_id=order_id,
                order_id=order_id,
                station_id=station,
                channel=random.choice(CHANNELS),
                severity="warning",
                order_status="in_prep",
                delay_minutes=random.randint(4, 8),
                queue_size=queue_depth - i,
                is_premium=is_premium,
                type="premium" if is_premium else "standard",
                cancellation_history=random_cancellation_history(),
                feedback=random_feedback(),
                sla_remaining=random_sla_minutes(),
            )
            publish_event(producer, order_event, "order.prep.delayed")
            enqueue_order(order_id, station, order_event["channel"])

        kitchen_event= base_event(
            event_name="kitchen.station.updated",
            entity_type="station",
            entity_id=station,
            station_id=station,
            severity="warning",
            station_status="saturated",
            queue_size=queue_depth,
            capacity=4,
        )
        publish_event(producer, kitchen_event, "kitchen.station.updated")

        print(f"  ✓ Station {station} queue={queue_depth}, {ingredient} critical ({stock_pct}%)")
    finally:
        producer.close()


def scenario_multi_channel_pressure():
    """
    MultiChannelPressureWithTrade-off: Pressure across multiple channels, LLM decides which to throttle.
    Varies: premium status by channel, sla_remaining, cancel_history, feedback per order.
    """
    print("\n=== Scenario: MultiChannelPressureWithTrade-off ===")
    producer = EventHubProducerClient.from_connection_string(EVENT_HUB_CONN_STR)
    try:
        # Create pressure across channels with mixed SLA/cost context.
        for channel in CHANNELS:
            for i in range(3):
                order_id = f"ORD-PRESSURE-{channel}-{int(time.time())}-{i}"
                # Delivery tends to be premium/strategic, but still vary
                is_premium = (channel == "delivery" and random.random() < 0.7) or (channel != "delivery" and random.random() < 0.1)
                
                order_event = base_event(
                    event_name="order.prep.delayed",
                    entity_type="order",
                    entity_id=order_id,
                    order_id=order_id,
                    is_premium=is_premium,
                    type="premium" if is_premium else "standard",
                    cancellation_history=random_cancellation_history(),
                    feedback=random_feedback(),
                    sla_remaining=random_sla_minutes(),
                    station_id=random.choice(STATIONS),
                    channel=channel,
                    severity="warning",
                    order_status="in_prep",
                    delay_minutes=random.randint(5, 9),
                    queue_size=random.randint(3, 7),
                )
                publish_event(producer, order_event, "order.prep.delayed")
                enqueue_order(order_id, order_event["station_id"], channel)

        for station in STATIONS:
            kitchen_event = base_event(
                event_name="kitchen.station.updated",
                entity_type="station",
                entity_id=station,
                station_id=station,
                severity="warning",
                station_status="saturated",
                queue_size=random.randint(4, 7),
                capacity=5,
            )
            publish_event(producer, kitchen_event, "kitchen.station.updated")

        print(f"  ✓ Multi-channel pressure: {len(CHANNELS)} channels × 3 orders varied by premium/feedback")
    finally:
        producer.close()


RECOMMENDATION_TYPES = [
    "reprioritize_order",
    "restock_ingredient",
    "reassign_station",
    "throttle_channel",
]
APPROVERS = ["manager_on_duty", "shift_supervisor", "auto_approved"]
ACTION_TYPES = {
    "reprioritize_order": "action.reprioritize_order",
    "restock_ingredient": "action.restock_ingredient",
    "reassign_station": "action.reassign_station",
    "throttle_channel": "action.throttle_channel",
}


def scenario_agent_decision_loop():
    """
    AgentDecisionLoop: Simulate the full traceability chain.

    Emits: agent.recommendation -> approval.decision -> action.executed
    Linked by recommendation_id so the trazabilidad query captures the full trace.
    Randomly includes rejections (~20%) and action failures (~10%).
    """
    print("\n=== Scenario: AgentDecisionLoop ===")
    producer = EventHubProducerClient.from_connection_string(EVENT_HUB_CONN_STR)
    try:
        recommendation_id = f"REC-{str(uuid4())[:8].upper()}"
        order_id = f"ORD-{random.randint(1000, 9999)}"
        station = random.choice(STATIONS)
        channel = random.choice(CHANNELS)
        rec_type = random.choice(RECOMMENDATION_TYPES)
        priority = random.randint(1, 5)
        confidence = round(random.uniform(0.70, 0.99), 2)
        sla_remaining = random.randint(3, 12)

        # 1. Agent generates a recommendation
        recommendation = base_event(
            event_name="agent.recommendation",
            entity_type="recommendation",
            entity_id=recommendation_id,
            order_id=order_id,
            station_id=station,
            channel=channel,
            severity="warning" if priority >= 3 else "info",
            recommendation_id=recommendation_id,
            priority=priority,
            confidence=confidence,
            recommendation_type=rec_type,
            sla_remaining=sla_remaining,
            reason=f"Detected {rec_type.replace('_', ' ')} opportunity with {confidence:.0%} confidence",
        )
        publish_event(producer, recommendation, "agent.recommendation")
        time.sleep(0.3)

        # 2. Human (or auto) approval decision — 80% approved, 20% rejected
        is_approved = random.random() < 0.80
        approver = random.choice(APPROVERS)
        approval_status = "approved" if is_approved else "rejected"
        approval = base_event(
            event_name="approval.decision",
            entity_type="recommendation",
            entity_id=recommendation_id,
            order_id=order_id,
            station_id=station,
            channel=channel,
            severity="info" if is_approved else "warning",
            recommendation_id=recommendation_id,
            approver=approver,
            approval_status=approval_status,
            reason="Within SLA tolerance" if is_approved else "Risk too high at this time",
        )
        publish_event(producer, approval, "approval.decision")
        time.sleep(0.3)

        # 3. If approved, execute the action (90% success, 10% failure)
        if is_approved:
            action_status = "completed" if random.random() < 0.90 else "failed"
            action_id = f"ACT-{str(uuid4())[:8].upper()}"
            action = base_event(
                event_name=ACTION_TYPES[rec_type],
                entity_type="action",
                entity_id=action_id,
                order_id=order_id,
                station_id=station,
                channel=channel,
                severity="info" if action_status == "completed" else "critical",
                action_id=action_id,
                action_status=action_status,
                recommendation_id=recommendation_id,
                action_type=ACTION_TYPES[rec_type],
            )
            publish_event(producer, action, ACTION_TYPES[rec_type])

        print(
            f"  ✓ {recommendation_id}: type={rec_type}, priority={priority}, "
            f"confidence={confidence:.0%}, approval={approval_status}"
            + (f", action={action_status}" if is_approved else "")
        )
    finally:
        producer.close()


def scenario_complete_orders() -> None:
    """Emit payment.completed events for pending orders whose prep time has elapsed.

    Picks up to 5 ready orders per call to avoid bursts. Orders that are not
    yet ready are left in the buffer for a future iteration.
    """
    now = time.time()
    ready = [o for o in _pending_orders if o["ready_at"] <= now]
    if not ready:
        return

    # Process at most 5 completions per cycle to smooth the flow
    to_complete = ready[:5]
    producer = EventHubProducerClient.from_connection_string(EVENT_HUB_CONN_STR)
    try:
        for order in to_complete:
            _pending_orders.remove(order)
            completed = base_event(
                event_name="payment.completed",
                entity_type="order",
                entity_id=order["order_id"],
                order_id=order["order_id"],
                station_id=order["station_id"],
                channel=order["channel"],
                severity="info",
                order_status="completed",
                payment_method=random.choice(["card", "cash", "app"]),
            )
            publish_event(producer, completed, "payment.completed")
        print(f"  ✓ Completed {len(to_complete)} order(s) ({len(_pending_orders)} still pending)")
    finally:
        producer.close()


def main():
    """Run trigger scenarios in continuous loop until interrupted."""
    print("Starting Operations Agent trigger event simulator (continuous mode)...")
    print(f"Event Hub: {EVENT_HUB_CONN_STR[:30]}...")
    print("Press Ctrl+C to stop.\n")

    iteration = 0
    try:
        while True:
            iteration += 1
            print(f"\n--- Iteration {iteration} ---")

            scenario_premium_client_near_sla()
            time.sleep(1)

            scenario_anomalous_station_queue()
            time.sleep(1)

            scenario_multi_channel_pressure()
            time.sleep(1)

            scenario_agent_decision_loop()
            time.sleep(1)

            scenario_complete_orders()
            time.sleep(5)

            print(f"✅ Iteration {iteration} complete. Cycling events...")
    except KeyboardInterrupt:
        print("\n\n⏹ Simulator stopped by user.")
        print("Events have been published. Check Eventhouse for:")
        print("  - order_events     → pedidos y retrasos")
        print("  - kitchen_events   → presión en estaciones")
        print("  - inventory_events → stock crítico")
        print("  - agent_events     → recomendaciones del agente")
        print("  - approval_events  → decisiones de aprobación")
        print("  - action_events    → acciones ejecutadas")


if __name__ == "__main__":
    main()
