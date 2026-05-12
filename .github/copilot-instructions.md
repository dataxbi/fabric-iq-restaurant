# GitHub Copilot Instructions

## Project goal
Build a small Microsoft Fabric demo for a self-managing restaurant using:
- Real-Time Intelligence for live events
- Fabric Activator for simple rules
- Operations Agent for the one complex LLM-driven recommendation
- A real-time dashboard for live visibility

## Working principles
- Keep the solution demo-sized and easy to explain.
- Prefer simple, idempotent scripts over manual one-off steps.
- Use workspace/item names from configuration; never hard-code IDs.
- Keep secrets out of the repository. Local-only values belong in `.env`.
- Treat `specs/especificaciones.md` as the source of truth for architecture and behavior.

## Implementation conventions
- Use English for code comments and user-facing script output.
- Put shared Fabric REST helpers under `scripts/`.
- Separate provisioning from schema creation.
- Keep scripts standard-library only unless a dependency is clearly justified.
- Print created resource names and IDs to stdout, but do not persist them to git.

## Fabric provisioning target
The scripts should prepare:
- Lakehouse
- Eventhouse
- KQL database
- Eventstream
- Initial Eventhouse transaction tables

## Security rules
- Do not commit access tokens, IDs, connection strings, or workspace secrets.
- Read configuration from environment variables and `.env` only.
- Provide `.env.example` with placeholder values, never real tenant data.

## Coding style
- Favor small functions and explicit errors.
- Make retries and long-running operation polling visible and predictable.
- Fail fast on missing configuration.
- Keep CLI output concise and actionable.

## Suggested execution order
1. Bootstrap Fabric resources by name.
2. Create the Eventhouse schema.
3. Load demo data later from the analytical pipeline.
