# Historical sensor CSV imports — Layer 6

This workflow imports private historical data only. It is separate from the
browser-local landing-page demo. It does not create sensor assets or change
machine settings.

## Reading contract

`backend/app/telemetry/readings.py` defines `NormalizedReadingV1` (`schema_version`
1). A reading records the organization, registered sensor and machine, a
measurement quantity, canonical unit and finite numeric value, device/source
event time, server receipt time, source (`csv_import`, `rest`, `mqtt` or
`opcua`), source reference, optional quality and deterministic `event_key`.
Database references use MongoDB `ObjectId`s; the validated contract represents
those IDs as strings.

`event_time_utc` is parsed from the CSV source timestamp. `received_at_utc` is
the UTC time at which the worker processes the row. The original source file
and its SHA-256 checksum remain associated with the import for audit. The
worker rejects non-finite numeric values and never substitutes rated or
nameplate values.

### Event-key definition and duplicates

The SHA-256 event key is over canonical JSON with sorted keys and compact
separators containing these exact fields:

```json
{
  "organization_id": "MongoDB organization ID as a string",
  "sensor_id": "registered MongoDB sensor ID as a string",
  "quantity": "normalized measurement quantity",
  "event_time_utc": "UTC ISO-8601 timestamp with microseconds",
  "source_event_id": "mapped stable source event ID, or null",
  "sequence": "sequence number, or null"
}
```

Different organizations and sensors are isolated in the identity. Quantity
prevents cross-measurement collisions. UTC normalization makes equivalent
offset timestamps identical. A supplied stable source event ID differentiates
events with the same sensor, quantity and time. The import currently has no
CSV sequence-column mapping, so `sequence` is always null.

MongoDB enforces uniqueness on `(organization_id, event_key)` and indexes
`(organization_id, sensor_id, event_time_utc)`. The first write wins. A later
identical key is a duplicate, not a row error. A repeated key within one file
is reported as `DUPLICATE_IN_FILE`; a key already stored before this import is
`DUPLICATE_EXISTING`. Worker retries preserve row outcomes and do not add
duplicate readings.

## Upload, mapping and row validation

The private UI is available from the selected sensor in `/app` → Factory
Registry → Sensors. An authorized user selects a UTF-8 CSV, previews its
headers/sample, confirms the mapping, and queues the import. Preview does not
store or commit readings.

Accepted content types are `text/csv`, `application/csv` and
`application/vnd.ms-excel`; compressed requests and non-UTF-8 encodings are
rejected. UTF-8 BOMs are supported. Delimiters are comma, semicolon, tab or
pipe. Delimiter detection uses the header and rejects ambiguous input.

Required mapping:

- Timestamp column and timezone. `value` requires UTC or an explicit offset in
  every timestamp. Otherwise provide an IANA timezone; `UTC` permits naive
  timestamps as UTC.
- Numeric value column.
- Exactly one fixed unit or unit column.
- Exactly one fixed registered sensor or sensor-ID/identity column.
- Optional stable source event ID column.

Only ISO-8601 timestamps are accepted. Naive local timestamps are converted
using the selected IANA timezone. A DST fall-back timestamp with two possible
offsets is rejected as `AMBIGUOUS_LOCAL_TIME`; a spring-forward nonexistent
time is rejected as `NONEXISTENT_LOCAL_TIME`. An explicit UTC offset resolves
both cases. No DST fold is guessed.

Measurements are converted through the explicit table in
`UNIT_CONVERSIONS`. The input and the sensor's registered unit must have the
same measurement quantity. Unsupported or incompatible units fail with
`INCOMPATIBLE_UNIT`; custom units must match exactly. Registered calibration
scale/offset is applied in the sensor's registered unit before conversion to
the canonical unit. Calibration offset is therefore expressed in the
registered unit.

Stable rejection codes include `MALFORMED_ROW`, `BAD_TIMESTAMP`,
`AMBIGUOUS_LOCAL_TIME`, `NONEXISTENT_LOCAL_TIME`, `NON_NUMERIC_VALUE`,
`NON_FINITE_VALUE`, `INCOMPATIBLE_UNIT`, `UNKNOWN_SENSOR` and
`SENSOR_NOT_PERMITTED`. Rejected records are kept in bounded per-import
metadata; original rejected row contents are written to a private errors CSV,
not retained in MongoDB. The signed download URL expires after the configured
interval.

## Persistence, privacy and retries

The API stores the original source in private S3-compatible object storage at
an import-scoped key and records its SHA-256 checksum before queueing work.
Objects are uploaded with server-side AES-256 encryption; public ACLs/URLs are
not used. The errors report is private and is available only through an
organization-scoped authorization check followed by a short-lived signed URL.
Configure the bucket's public-access block and encryption policy as a second
storage-side control.

The MongoDB `sensor_imports` record contains the organization, uploader,
machine/sensor context, object key, checksum, confirmed mapping, status,
timestamps, bounded counts, rejected-code totals, error summary, attempts and
schema version. Per-row result records have a unique
`(organization_id, import_id, row_number)` index. Reading and row-result writes
are committed together in MongoDB transactions. The worker claims queued jobs
and expired processing leases; if it crashes, a redelivery safely resumes by
reprocessing the immutable source and skipping committed row outcomes.

Statuses are `queued → processing → completed | completed_with_errors |
failed | cancelled`. Cancelling a queued job prevents a later claim.
Cancelling a processing job takes effect at a bounded batch boundary. Failed
jobs can be retried; completed jobs are not reprocessed by the retry endpoint.

## API

All paths use the existing cookie session, CSRF, role and organization
dependencies:

- `POST /api/v1/sensor-imports/preview?sensor_id=...` — bounded CSV body;
  optionally pass the mapping in `X-Import-Mapping` for sample validation.
- `POST /api/v1/sensor-imports?sensor_id=...` — confirm the same bounded body
  and mapping; returns the queued import.
- `GET /api/v1/sensor-imports?sensor_id=...` and
  `GET /api/v1/sensor-imports/{import_id}` — scoped status and counts.
- `POST /api/v1/sensor-imports/{import_id}/cancel` and
  `POST /api/v1/sensor-imports/{import_id}/retry` — authorized job controls.
- `GET /api/v1/sensor-imports/{import_id}/errors` — scoped, expiring signed
  error-file URL.

## Limits

The defaults are in `backend/app/core/config.py` and may be overridden by
environment variables. Requests beyond a limit receive an explicit error
before the source is stored.

| Setting | Default | Maximum |
|---|---:|---:|
| `SENSOR_IMPORT_MAX_FILE_BYTES` | 10 MiB | 100 MiB |
| `SENSOR_IMPORT_MAX_ROWS` | 50,000 | 1,000,000 |
| `SENSOR_IMPORT_PREVIEW_ROWS` | 25 | 100 |
| `SENSOR_IMPORT_BATCH_SIZE` | 250 | 2,000 |
| `SENSOR_IMPORT_ERROR_URL_TTL_SECONDS` | 300 seconds | 900 seconds |

The worker streams the private source through the CSV reader and commits at
most one configured row batch per transaction. MongoDB row metadata is bounded
by the configured maximum data-row count. Error CSV output is spooled to a
temporary file rather than held entirely in memory.

## Local verification and limitations

Run `npm run test:backend` for the worker, API, migration, tenant-boundary and
fixture-manifest checks. The gate fixture is
`backend/tests/fixtures/sensor-imports/layer6.csv`; its exact expected counts
are in `layer6.expected.json`. The tests use MongoDB and private-storage
doubles; they do not prove live Render, Redis, S3-compatible storage, or MongoDB
transaction behavior.

Layer 7 device credentials, REST/MQTT/OPC UA ingestion, durable edge buffering,
and credential lifecycle are not implemented by Layer 6. Their credential
model and protocol-fixture documentation must be added with Layer 7. Layer 8
simulation pinning and replay format are likewise deferred until that layer
passes its gate.
