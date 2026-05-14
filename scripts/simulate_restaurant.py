#!/usr/bin/env python3
"""Unified restaurant event simulator.

Merges send_eventstream_events.py (batch) and simulate_agent_trigger_events.py
(continuous trigger loop) into a single script.

Order lifecycle guarantee
─────────────────────────
  order.created  (always, exactly once per order_id)
  order.prep.delayed  (at most once, only if the order is actually delayed)
  payment.completed   (exactly once, after prep time elapses or immediately in batch)

Modes
─────
  batch      : one-shot pass, N orders fully closed before the script exits
               python simulate_restaurant.py --orders 20 --scenario peak

  continuous : loop forever — used to trigger Operations Agent conditions
               python simulate_restaurant.py --continuous
               python simulate_restaurant.py --continuous --no-agent-loop
"""

from __future__ import annotations

import argparse
import json
import os
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv

# Load .env from repo root
load_dotenv(Path(__file__).parent.parent / ".env")

# ─── constants ────────────────────────────────────────────────────────────────
STATIONS = ["grill", "fryer", "sauces", "assembly"]
CHANNELS = ["delivery", "dine-in", "takeout"]
INGREDIENTS = ["beef", "chicken", "fries", "sauce_bbq", "sauce_mayo"]
FEEDBACK_LEVELS = ["muy_negativo", "negativo", "neutral", "positivo"]
CANCEL_HISTORY = ["none", "cancelado_1_vez", "cancelado_2_veces", "cancelado_3_veces"]
def _inventory_severity(stock_pct: float, threshold_pct: float = 20.0) -> str:
    """Return severity based on how far stock is below threshold."""
    if stock_pct <= threshold_pct * 0.5:   # <= 10% when threshold=20
        return "critical"
    return "warning"


RECOMMENDATION_TYPES = [
    "reprioritize_order",
    "restock_ingredient",
    "reassign_station",
    "throttle_channel",
]
APPROVERS = ["manager_on_duty", "shift_supervisor", "auto_approved"]
ACTION_EVENT = {
    "reprioritize_order": "action.reprioritize_order",
    "restock_ingredient": "action.restock_ingredient",
    "reassign_station": "action.reassign_station",
    "throttle_channel": "action.throttle_channel",
}

# ─── order lifecycle tracker ──────────────────────────────────────────────────
# Maps order_id → "created" | "delayed" | "completed"
_order_state: dict[str, str] = {}
# Queue of orders waiting for payment.completed
# Each entry: {order_id, station_id, channel, ready_at (epoch seconds)}
_pending: list[dict] = []
_MAX_PENDING = 500

# ─── persistent daily order counter ───────────────────────────────────────────
# State file: scripts/.sim_state.json  (excluded from git)
# Format:     {"date": "YYYYMMDD", "counter": N}
# Order IDs:  ORD-YYYYMMDD-NNNN  (e.g. ORD-20260514-0023)
#             Trigger-script IDs: ORD-PREM-YYYYMMDD-NNNN, ORD-Q0-…, etc.
_STATE_FILE = Path(__file__).parent / ".sim_state.json"


def _load_counter() -> tuple[str, int]:
    """Return (today_str, next_counter). Resets to 1 on a new day."""
    today = datetime.now().strftime("%Y%m%d")
    if _STATE_FILE.exists():
        try:
            data = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
            if data.get("date") == today:
                return today, int(data.get("counter", 0)) + 1
        except (json.JSONDecodeError, KeyError, ValueError):
            pass
    return today, 1


def _save_state(today: str, counter: int) -> None:
    """Persist counter and pending orders to the state file."""
    _STATE_FILE.write_text(
        json.dumps(
            {
                "date": today,
                "counter": counter,
                "pending": _pending,
                "order_state": _order_state,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _save_counter(today: str, counter: int) -> None:
    """Persist the current counter (and pending snapshot) to the state file."""
    _save_state(today, counter)


def _restore_pending() -> None:
    """Load pending orders from state file on startup.

    Orders that were open when the simulator last stopped are immediately
    eligible for completion (ready_at set to now) so they get closed in
    the first _scenario_complete_pending call.
    """
    if not _STATE_FILE.exists():
        return
    try:
        data = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        today = datetime.now().strftime("%Y%m%d")
        if data.get("date") != today:
            return  # stale state from a previous day — ignore
        saved_pending = data.get("pending", [])
        saved_state = data.get("order_state", {})
        restored = 0
        now = time.time()
        for entry in saved_pending:
            oid = entry.get("order_id", "")
            if not oid:
                continue
            if _order_state.get(oid) == "completed":
                continue
            # Mark as eligible for immediate completion
            entry["ready_at"] = now
            _pending.append(entry)
            if oid not in _order_state:
                _order_state[oid] = saved_state.get(oid, "created")
            restored += 1
        if restored:
            print(f"  ↩  Restored {restored} pending order(s) from previous run — will complete on first cycle.")
    except (json.JSONDecodeError, KeyError, ValueError):
        pass


def next_order_id(prefix: str = "") -> str:
    """Return the next unique order ID and persist the counter.

    Batch orders:   ORD-20260514-0001, ORD-20260514-0002, …
    Trigger orders: ORD-PREM-20260514-0003, ORD-Q0-20260514-0004, …
    """
    today, counter = _load_counter()
    _save_counter(today, counter)
    tag = f"-{prefix}" if prefix else ""
    return f"ORD{tag}-{today}-{counter:04d}"


# ─── helpers ──────────────────────────────────────────────────────────────────

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Restaurant event simulator — batch or continuous mode",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples
  # One-shot batch of 20 orders in peak scenario
  python simulate_restaurant.py --orders 20 --scenario peak

  # Continuous loop for Operations Agent testing
  python simulate_restaurant.py --continuous

  # Continuous without agent traceability events
  python simulate_restaurant.py --continuous --no-agent-loop
        """,
    )
    parser.add_argument("--connection-string", default=None,
                        help="Event Hub connection string (overrides env)")
    parser.add_argument("--eventhub-name", default=None,
                        help="Event Hub entity name override")
    # Mode
    parser.add_argument("--continuous", action="store_true", default=False,
                        help="Run in continuous loop mode (default: batch)")
    # Batch options
    parser.add_argument("--orders", type=int, default=12,
                        help="Orders to simulate in batch mode (default: 12)")
    parser.add_argument("--scenario", default="peak",
                        choices=["normal", "peak", "stock-critical"],
                        help="Scenario preset for batch mode (default: peak)")
    parser.add_argument("--interval-seconds", type=float, default=0.5,
                        help="Pause between events in batch mode (default: 0.5s)")
    # Continuous options
    parser.add_argument("--no-agent-loop", action="store_true", default=False,
                        help="Skip agent recommendation/approval/action events in continuous mode")
    parser.add_argument("--cycle-seconds", type=float, default=15.0,
                        help="Pause between iterations in continuous mode (default: 15s)")
    return parser


def _get_connection_string(args: argparse.Namespace) -> str:
    cs = (args.connection_string or
          os.environ.get("EVENTSTREAM_EVENTHUB_CONNECTION_STRING", "")).strip()
    if not cs:
        raise ValueError(
            "Missing Event Hub connection string. "
            "Set EVENTSTREAM_EVENTHUB_CONNECTION_STRING in .env or pass --connection-string."
        )
    return cs


def _eventhub_name(connection_string: str, override: str | None) -> str | None:
    if override:
        return override
    for segment in connection_string.split(";"):
        if segment.startswith("EntityPath="):
            return segment.split("=", 1)[1].strip()
    return None


def _base_event(
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
        "event_time": utc_now(),
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


def _send(producer, event: dict) -> None:
    """Publish one event to Event Hub."""
    from azure.eventhub import EventData
    body = json.dumps(event, separators=(",", ":")).encode("utf-8")
    batch = producer.create_batch()
    batch.add(EventData(body))
    producer.send_batch(batch)
    label = event.get("order_id") or event.get("ingredient_id") or event.get("entity_id", "")
    print(f"  → {event['event_name']:<42} {label}")


def _random_feedback() -> str:
    return random.choices(FEEDBACK_LEVELS, weights=[5, 15, 60, 20], k=1)[0]


def _random_cancel() -> str:
    return random.choices(CANCEL_HISTORY, weights=[70, 15, 10, 5], k=1)[0]


def _flush_state() -> None:
    """Persist current counter + pending queue to disk (called after every enqueue/complete)."""
    today = datetime.now().strftime("%Y%m%d")
    counter = 0
    if _STATE_FILE.exists():
        try:
            counter = json.loads(_STATE_FILE.read_text(encoding="utf-8")).get("counter", 0)
        except (json.JSONDecodeError, ValueError):
            pass
    _save_state(today, counter)


# ─── order lifecycle helpers ──────────────────────────────────────────────────

def _enqueue(order_id: str, station_id: str, channel: str,
             prep_seconds: int | None = None) -> None:
    """Add order to pending-completion queue (idempotent — skips if already queued or completed)."""
    # Skip if already in the pending queue or already completed
    if _order_state.get(order_id) == "completed":
        return
    if any(o["order_id"] == order_id for o in _pending):
        return
    if prep_seconds is None:
        prep_seconds = random.randint(45, 90)
    _pending.append({
        "order_id": order_id,
        "station_id": station_id,
        "channel": channel,
        "ready_at": time.time() + prep_seconds,
    })
    # Evict oldest when buffer is full
    while len(_pending) > _MAX_PENDING:
        evicted = _pending.pop(0)
        _order_state.pop(evicted["order_id"], None)
    # Persist so restarts don't create orphan orders
    _flush_state()


def _emit_order_lifecycle(
    producer,
    order_id: str,
    station: str,
    channel: str,
    *,
    is_premium: bool = False,
    is_delayed: bool = False,
    delay_minutes: int = 6,
    queue_size: int = 5,
    sla_remaining: int = 10,
    cancel_hist: str = "none",
    feedback: str = "neutral",
    severity_order: str = "info",
    complete_immediately: bool = False,
    amount: float = 18.5,
    items: int = 1,
) -> None:
    """Emit the full lifecycle for a single order.

    Guarantees:
    - order.created     exactly once
    - order.prep.delayed at most once (only if is_delayed=True)
    - payment.completed exactly once (immediately or via _pending buffer)
    """
    if order_id in _order_state:
        return  # already emitted — no duplicates

    # 1. order.created
    _send(producer, _base_event(
        "order.created", "order", order_id,
        order_id=order_id, channel=channel, station_id=station,
        order_status="created", severity=severity_order,
        is_premium=is_premium, type="premium" if is_premium else "standard",
        cancellation_history=cancel_hist, feedback=feedback,
        sla_remaining=sla_remaining, items=items,
    ))
    _order_state[order_id] = "created"
    time.sleep(0.05)

    # 2. order.prep.delayed (at most once)
    if is_delayed:
        _send(producer, _base_event(
            "order.prep.delayed", "order", order_id,
            order_id=order_id, channel=channel, station_id=station,
            order_status="in_prep", severity="warning",
            delay_minutes=delay_minutes, queue_size=queue_size,
            is_premium=is_premium, type="premium" if is_premium else "standard",
            cancellation_history=cancel_hist, feedback=feedback,
            sla_remaining=sla_remaining,
        ))
        _order_state[order_id] = "delayed"
        time.sleep(0.05)

    # 3a. Immediate completion (batch mode)
    if complete_immediately:
        _send(producer, _base_event(
            "payment.completed", "order", order_id,
            order_id=order_id, channel=channel, station_id=station,
            order_status="completed", severity="info",
            amount=amount, payment_method="card",
        ))
        _order_state[order_id] = "completed"
    else:
        # 3b. Deferred completion (continuous mode — via _pending buffer)
        _enqueue(order_id, station, channel)


# ─────────────────────────────────────────────────────────────────────────────
#  BATCH MODE
# ─────────────────────────────────────────────────────────────────────────────

def run_batch(producer, args: argparse.Namespace) -> None:
    """One-shot simulation of N orders. Each order is fully closed before exit."""
    global _batch_counter
    scenario = args.scenario
    print(f"\n🍽  Batch: {args.orders} orders | scenario={scenario}")

    counts: dict[str, int] = {}

    for n in range(1, args.orders + 1):
        order_id = next_order_id()
        channel = CHANNELS[n % len(CHANNELS)]
        station = STATIONS[n % len(STATIONS)]
        ingredient = INGREDIENTS[n % len(INGREDIENTS)]
        high_pressure = scenario == "peak" and n % 3 == 0
        stock_pressure = scenario == "stock-critical" or n % 5 == 0

        # kitchen event
        _send(producer, _base_event(
            "kitchen.station.updated", "station", station,
            station_id=station,
            severity="warning" if high_pressure else "info",
            station_status="saturated" if high_pressure else "normal",
            queue_size=9 if high_pressure else 3 + (n % 4),
            capacity=6,
        ))

        # inventory event
        _send(producer, _base_event(
            "inventory.level.changed", "ingredient", ingredient,
            ingredient_id=ingredient,
            stock_pct=8.0 if stock_pressure else 35.0 + n,
            threshold_pct=15.0, delta=-2.5,
            severity=_inventory_severity(8.0 if stock_pressure else 35.0 + n, threshold_pct=15.0),
        ))

        is_delayed = high_pressure
        is_premium = high_pressure and channel == "delivery"

        _emit_order_lifecycle(
            producer, order_id, station, channel,
            is_premium=is_premium,
            is_delayed=is_delayed,
            delay_minutes=8.0 if high_pressure else float(n % 4),
            queue_size=9 if high_pressure else 3 + (n % 4),
            complete_immediately=True,
            amount=round(18.5 + n, 2),
            items=1 + (n % 4),
        )

        if is_premium and channel == "delivery":
            _send(producer, _base_event(
                "customer.sentiment.signal", "order", order_id,
                order_id=order_id, channel=channel,
                sentiment="negative", reason="delivery_delay_risk", severity="warning",
            ))

        for event_name in ["order.created", "kitchen.station.updated",
                           "inventory.level.changed", "payment.completed"]:
            counts[event_name] = counts.get(event_name, 0) + 1
        if is_delayed:
            counts["order.prep.delayed"] = counts.get("order.prep.delayed", 0) + 1

        if n < args.orders:
            time.sleep(args.interval_seconds)

    print(f"\n✅ Batch complete: {sum(counts.values())} events — {counts}")


# ─────────────────────────────────────────────────────────────────────────────
#  CONTINUOUS MODE SCENARIOS
# ─────────────────────────────────────────────────────────────────────────────

def _scenario_premium_near_sla(producer) -> None:
    """Premium order with SLA < 10 min — always delayed (order.created included)."""
    print("\n  [Scenario] PremiumNearSLA")
    order_id = next_order_id("PREM")
    station = random.choice(STATIONS)
    channel = random.choice(CHANNELS)
    sla = random.randint(3, 8)
    delay = random.randint(5, 8)
    cancel = _random_cancel()
    feedback = _random_feedback()

    _emit_order_lifecycle(
        producer, order_id, station, channel,
        is_premium=True, is_delayed=True,
        delay_minutes=delay, queue_size=random.randint(5, 10),
        sla_remaining=sla, cancel_hist=cancel, feedback=feedback,
        severity_order="warning",
    )
    _send(producer, _base_event(
        "kitchen.station.updated", "station", station,
        station_id=station, severity="warning", capacity=4,
    ))
    print(f"    ✓ {order_id}: SLA={sla}min, delay={delay}min, cancel={cancel}")


def _scenario_anomalous_queue(producer) -> None:
    """1-2 orders at an overloaded station — each gets order.created before delay."""
    print("\n  [Scenario] AnomalousQueue")
    station = random.choice(STATIONS)
    ingredient = random.choice(INGREDIENTS)
    queue_depth = random.randint(1, 2)
    stock_pct = random.randint(5, 15)

    _send(producer, _base_event(
        "inventory.level.changed", "ingredient", ingredient,
        ingredient_id=ingredient, severity=_inventory_severity(stock_pct),
        stock_pct=stock_pct, threshold_pct=20.0, delta=random.randint(-10, -2),
    ))
    for i in range(queue_depth):
        order_id = next_order_id(f"Q{i}")
        channel = random.choice(CHANNELS)
        is_premium = random.random() < 0.20
        _emit_order_lifecycle(
            producer, order_id, station, channel,
            is_premium=is_premium, is_delayed=True,
            delay_minutes=random.randint(4, 8),
            queue_size=queue_depth - i,
            sla_remaining=random.randint(3, 18),
            cancel_hist=_random_cancel(), feedback=_random_feedback(),
        )
    _send(producer, _base_event(
        "kitchen.station.updated", "station", station,
        station_id=station, severity="warning", capacity=4,
    ))
    print(f"    ✓ station={station}, queue={queue_depth}, {ingredient}={stock_pct}%")


def _scenario_multi_channel(producer) -> None:
    """2 delayed orders per channel — each with order.created first."""
    print("\n  [Scenario] MultiChannelPressure")
    for channel in CHANNELS:
        for i in range(2):
            order_id = next_order_id(f"MC{channel[:2].upper()}{i}")
            is_premium = (channel == "delivery" and random.random() < 0.7) or random.random() < 0.1
            station = random.choice(STATIONS)
            _emit_order_lifecycle(
                producer, order_id, station, channel,
                is_premium=is_premium, is_delayed=True,
                delay_minutes=random.randint(5, 9),
                queue_size=random.randint(3, 7),
                sla_remaining=random.randint(3, 18),
                cancel_hist=_random_cancel(), feedback=_random_feedback(),
            )
    for station in STATIONS:
        _send(producer, _base_event(
            "kitchen.station.updated", "station", station,
            station_id=station, severity="warning", capacity=5,
        ))
    print(f"    ✓ {len(CHANNELS)} channels × 2 orders")


def _scenario_agent_loop(producer) -> None:
    """agent.recommendation → approval.decision → action (full traceability chain)."""
    print("\n  [Scenario] AgentDecisionLoop")
    rec_id = f"REC-{str(uuid4())[:8].upper()}"
    # Agent loop uses a dedicated prefix to avoid overlapping with real order IDs
    order_id = f"ORD-AGENT-{str(uuid4())[:8].upper()}"
    station = random.choice(STATIONS)
    channel = random.choice(CHANNELS)
    rec_type = random.choice(RECOMMENDATION_TYPES)
    priority = random.randint(1, 5)
    confidence = round(random.uniform(0.70, 0.99), 2)
    sla_remaining = random.randint(3, 12)

    _send(producer, _base_event(
        "agent.recommendation", "recommendation", rec_id,
        order_id=order_id, station_id=station, channel=channel,
        severity="warning" if priority >= 3 else "info",
        recommendation_id=rec_id, priority=priority, confidence=confidence,
        recommendation_type=rec_type, sla_remaining=sla_remaining,
        reason=f"Detected {rec_type.replace('_', ' ')} with {confidence:.0%} confidence",
    ))
    time.sleep(0.3)

    is_approved = random.random() < 0.80
    approver = random.choice(APPROVERS)
    _send(producer, _base_event(
        "approval.decision", "recommendation", rec_id,
        order_id=order_id, station_id=station, channel=channel,
        severity="info" if is_approved else "warning",
        recommendation_id=rec_id, approver=approver,
        approval_status="approved" if is_approved else "rejected",
        reason="Within SLA tolerance" if is_approved else "Risk too high",
    ))
    time.sleep(0.3)

    if is_approved:
        action_status = "completed" if random.random() < 0.90 else "failed"
        action_id = f"ACT-{str(uuid4())[:8].upper()}"
        action_name = ACTION_EVENT[rec_type]
        _send(producer, _base_event(
            action_name, "action", action_id,
            order_id=order_id, station_id=station, channel=channel,
            severity="info" if action_status == "completed" else "critical",
            action_id=action_id, action_status=action_status,
            recommendation_id=rec_id, action_type=action_name,
        ))

    status_str = ("approved, " + ("completed" if is_approved and action_status == "completed" else "failed")) \
        if is_approved else "rejected"
    print(f"    ✓ {rec_id}: {rec_type}, confidence={confidence:.0%}, {status_str}")


def _scenario_complete_pending(producer) -> None:
    """Emit payment.completed for all pending orders whose prep time has elapsed.

    Each order is completed exactly once — protected by _order_state tracking.
    """
    now = time.time()
    ready = [o for o in _pending if o["ready_at"] <= now]
    if not ready:
        return

    to_complete = ready[:20]
    completed_by_station: dict[str, int] = {}

    for order in to_complete:
        order_id = order["order_id"]
        # Skip if already completed (safety guard)
        if _order_state.get(order_id) == "completed":
            _pending.remove(order)
            continue

        _pending.remove(order)
        _order_state[order_id] = "completed"

        _send(producer, _base_event(
            "payment.completed", "order", order_id,
            order_id=order_id, station_id=order["station_id"],
            channel=order["channel"], severity="info",
            order_status="completed",
            payment_method=random.choice(["card", "cash", "app"]),
        ))
        completed_by_station[order["station_id"]] = (
            completed_by_station.get(order["station_id"], 0) + 1
        )

    for station_id in completed_by_station:
        _send(producer, _base_event(
            "kitchen.station.updated", "station", station_id,
            station_id=station_id, severity="info",
            station_status="normal", capacity=5,
        ))

    print(f"\n  ✓ Completed {len(to_complete)} order(s) | still pending: {len(_pending)}")
    _flush_state()


def run_continuous(producer, args: argparse.Namespace) -> None:
    """Loop forever running all trigger scenarios until Ctrl+C."""
    _restore_pending()
    print("\n🔁 Continuous mode | Ctrl+C to stop\n")
    iteration = 0
    try:
        while True:
            iteration += 1
            ts = utc_now()
            print(f"\n{'─' * 55}")
            print(f"Iteration {iteration} | {ts} | pending={len(_pending)}")
            print(f"{'─' * 55}")

            _scenario_premium_near_sla(producer)
            time.sleep(1)

            _scenario_anomalous_queue(producer)
            time.sleep(1)

            _scenario_multi_channel(producer)
            time.sleep(1)

            if not args.no_agent_loop:
                _scenario_agent_loop(producer)
                time.sleep(1)

            _scenario_complete_pending(producer)

            print(f"\n✅ Iteration {iteration} done | sleeping {args.cycle_seconds}s…")
            time.sleep(args.cycle_seconds)

    except KeyboardInterrupt:
        print("\n\n⏹  Simulator stopped.")
        print(f"   Orders tracked : {len(_order_state)}")
        print(f"   Still pending  : {len(_pending)}")
        counts: dict[str, int] = {}
        for state in _order_state.values():
            counts[state] = counts.get(state, 0) + 1
        print(f"   State summary  : {counts}")


# ─── entry point ──────────────────────────────────────────────────────────────

def main() -> None:
    try:
        from azure.eventhub import EventHubProducerClient  # noqa: F401 — verify installed
    except ImportError as exc:
        raise ImportError(
            "Missing dependency. Install with: py -m pip install azure-eventhub"
        ) from exc

    args = build_parser().parse_args()
    connection_string = _get_connection_string(args)
    hub_name = _eventhub_name(connection_string, args.eventhub_name)

    from azure.eventhub import EventHubProducerClient
    producer = EventHubProducerClient.from_connection_string(
        conn_str=connection_string,
        eventhub_name=hub_name,
    )

    try:
        if args.continuous:
            run_continuous(producer, args)
        else:
            run_batch(producer, args)
    finally:
        producer.close()


if __name__ == "__main__":
    main()
