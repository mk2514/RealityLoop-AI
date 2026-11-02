# Production simulation and replay

## Source and immutability

Simulation runs use immutable `production_line_versions` documents. A run also pins
the resolved machine parameters, factory timezone/calendar, recipe, product,
assumptions, seed, engine/translator versions, and run limits in its snapshot.
Edits to live assets or lines do not alter completed runs.

## Determinism

The engine uses one Python `random.Random(seed)` stream. The same snapshot and
seed produce identical event-log and snapshot hashes. Deterministic mode has no
random variation. `uniform_cycle_time` is explicitly stochastic and is identified
in run assumptions.

## Event replay

Simulation events are stored separately from assets and line documents. Reads are
organization-scoped and paginated. The UI replay is a presentation of stored
events only; it does not invoke the engine and does not read current asset state.

## Current limits

Defaults are configured in the backend environment and exported as
`SIMULATION_MAX_TIME_SECONDS`, `SIMULATION_MAX_EVENTS`, `SIMULATION_MAX_EVENT_LOG_BYTES`,
and `SIMULATION_MAX_WALL_SECONDS`. Unsupported distributions, missing cycle times,
missing finite-buffer capacities, unresolved routing, missing recipes/products,
and unbounded rework are rejected with an action code and remediation text.
