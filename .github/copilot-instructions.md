# GitHub Copilot Instructions

## Project goal
Build a small Microsoft Fabric Real-Time Intelligence demo for a self-managing restaurant using:
- Eventstream for live restaurant events
- Eventhouse/KQL database as the operational source of truth
- Fabric Activator for simple threshold-based conditions
- Operations Agent for complex contextual recommendations and human approval in Teams
- A real-time dashboard for live visibility and traceability

## Working principles
- Keep the solution demo-sized and easy to explain.
- Prefer simple, idempotent scripts over manual one-off steps.
- Use workspace/item names from configuration; never hard-code IDs.
- Keep secrets out of the repository. Local-only values belong in `.env`.
- Treat `specs/especificaciones.md` as the source of truth for architecture and behavior.
- Do not make Power BI semantic models or Ontology/Fabric IQ required for the main demo path.

## Implementation conventions
- Use English for code comments and user-facing script output.
- Put shared Fabric REST helpers under `scripts/`.
- Separate provisioning from schema creation.
- Keep scripts standard-library only unless a dependency is clearly justified.
- Print created resource names and IDs to stdout, but do not persist them to git.

## Fabric provisioning target
The scripts should prepare:
- Eventhouse
- KQL database
- Eventstream
- Raw landing KQL table: `raw_restaurant_events`
- Operational KQL tables: `order_events`, `kitchen_events`, `inventory_events`, `agent_events`, `approval_events`, and `action_events`
- Reference KQL table: `stations` — static kitchen station definitions (grill, fryer, sauces, assembly) with `max_capacity` and `avg_prep_minutes`; seeded with `.set-or-replace` on every schema deploy
- KQL functions and update policies that distribute/transform rows from `raw_restaurant_events` into the operational tables
- Activator rules/actions for simple operational conditions
- Operations Agent configuration guidance/playbook for complex conditions

## KQL schema and stations
- The `stations` table is the canonical reference for kitchen capacity. It defines each station's `max_capacity` (parallel processing slots, e.g. burners) and `avg_prep_minutes`.
- Active order count per station: `order_events | where event_time > ago(10m) | summarize arg_max(event_time, order_status) by order_id | where order_status !in ("completed","cancelled") | summarize active_orders = count() by station_id`.
- Queue drain time formula: `(active_orders - max_capacity) * avg_prep_minutes / max_capacity`, where `active_orders` comes from `order_events`.
- `kitchen_events` only records station activity signals (event log); it does not carry `queue_size` or `station_status`. Load and status are always derived from `order_events`.
- Join pattern for capacity lookup: `order_events | ... | join kind=leftouter stations on station_id`.
- Station IDs are: `grill`, `fryer`, `sauces`, `assembly`.

## Event ingestion pattern
- Eventstream should route raw restaurant events into `raw_restaurant_events`.
- Keep Eventstream configuration simple: ingestion/routing only, not the main operational modeling layer.
- Implement event classification and normalization in Eventhouse with KQL functions and update policies.
- Activator, Operations Agent, dashboards, and traceability queries should use the derived operational tables unless raw event inspection is explicitly needed.
- The simulator emits these event types: `order.created`, `kitchen.station.updated`, `inventory.level.changed`, `order.prep.delayed`, `customer.sentiment.signal`, `payment.completed`.

## Activator vs Operations Agent
- **Fabric Activator**: simple, objective conditions — thresholds, high queue, critical stock, delayed orders. Triggers automatic technical actions or flows.
- **Operations Agent**: complex conditions with mixed context — combines delay, station saturation, stock level, channel pressure, and customer sentiment. Produces a natural-language recommendation and requests human approval in Teams before executing any action.
- No autonomous actions in this demo version. All actions require human approval.

## Security rules
- Do not commit access tokens, IDs, connection strings, or workspace secrets.
- Read configuration from environment variables and `.env` only.
- Provide `.env.example` with placeholder values, never real tenant data.

## Coding style
- Favor small functions and explicit errors.
- Make retries and long-running operation polling visible and predictable.
- Fail fast on missing configuration.
- Keep CLI output concise and actionable.

## Commit authorship
- `specs/especificaciones.md` commits: author is Nelson López (`nelson.lopez@dataxbi.com`), Copilot as co-author.
- All other files: author is Copilot (`223556219+Copilot@users.noreply.github.com`), no additional co-author.
- Always include a blank line before the `Co-authored-by:` trailer so Git recognizes it as a proper trailer.
- Keep spec changes in a separate commit from code/config changes.

## Suggested execution order
1. Bootstrap Fabric resources by name.
2. Create the Eventhouse schema, KQL functions, update policies, and seed the `stations` reference table.
3. Configure Eventstream routing into `raw_restaurant_events`.
4. Configure Activator rules for simple conditions such as stock-critical, high queue, and delayed orders.
5. Configure Operations Agent with Eventhouse as knowledge source for complex recommendations.
6. Run the restaurant event simulator and verify the event -> condition -> recommendation/approval -> action trace.
