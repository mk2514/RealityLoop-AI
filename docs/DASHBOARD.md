# Machine and Sensor Dashboards

## Query semantics

- Storage values and timestamps remain canonical: canonical units from `NormalizedReadingV1` and timezone-aware UTC event times.
- `event_time_utc` is the chart/query time basis. `received_at_utc` is receipt/provenance metadata only.
- Raw queries are bounded by the configured row cap. Oversized raw windows return `413` with guidance to use aggregation.
- Aggregation returns `min`, `max`, `avg`, `count`, `first`, and `last` per UTC bucket.
- Buckets without readings are returned with null values and `count: 0`. They are not represented as zero or interpolated.
- Boundary rule: readings at `start` and `end` are included (`$gte` start, `$lte` end).
- CSV exports use the same sensor query path, unit, timezone, view and window as the chart. Over-cap exports are rejected.

## Defaults

Layer 9 limits are configurable in backend settings:

- `DASHBOARD_MAX_RANGE_SECONDS`: maximum selected window
- `DASHBOARD_RAW_MAX_ROWS`: raw-view row cap
- `DASHBOARD_MAX_BUCKETS`: maximum returned bucket count
- `DASHBOARD_EXPORT_MAX_ROWS`: maximum export row count

The Vite frontend does not change these limits; the API is authoritative.

## Provenance

Every raw reading carries `source`, `source_ref`, `event_time_utc`, `received_at_utc`, `quality`, and the tenant-scoped `event_key`.
CSV-import readings link through `source_ref` as an import identifier; REST, MQTT and OPC UA readings link through device/topic/node source references.

## Layouts and alerts

- Dashboard layouts are versioned, per user, per organization and per scope.
- Invalid saved layouts are rejected rather than partially applied; the UI can fall back to its empty panel state.
- Threshold rules are append-style versioned records.
- Alert state transitions must be based on real samples and staleness/missing-data conditions. Missing data is never scored as zero.

## Simulation overlays

An observed/simulated overlay requires:

1. A pinned station-to-sensor mapping for the exact saved line version used by the run.
2. Matching quantity and compatible units.
3. Event-time UTC as the observed and simulation time basis.

Missing or mismatched mappings return an actionable, specific reason and no overlaid series.
