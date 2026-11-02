# Live sensor ingestion

This layer adds authenticated REST and MQTT ingestion, read-only OPC UA polling,
sensor freshness, and an offline edge outbox. It reuses the Layer 6
[`NormalizedReadingV1` contract](./SENSOR_IMPORTS.md#normalized-reading-v1) and
the same tenant-scoped unique event-key index. The landing-page CSV demo remains
browser-local and is not part of this pipeline.

## Device credentials

Workspace owners, administrators, and engineers can create, rotate, and revoke
sensor credentials from the sensor screen in `/app`. A credential is limited to
registered, active sensors in its organization and may further restrict quantity.
The API returns the `key_id.secret` value once. MongoDB stores only a SHA-256
hash of the secret; it is never returned by list/status endpoints. Rotation
revokes the previous key and inserts the replacement in one MongoDB transaction.
Revocation and creation/rotation are audit events. Device requests update
`last_used_at`; ingestion events record item counts without telemetry payloads.

REST devices send `Authorization: Bearer key_id.secret` to
`POST /api/v1/telemetry/readings`, with a JSON body containing a bounded
`readings` array. The server validates each item and returns accepted, duplicate,
or rejected status with a stable rejection code. Revoked or expired credentials
receive 401 and do not write readings. Out-of-scope sensors are rejected without
writing, even when another organization owns the referenced ID.

## MQTT subscriber

Enable the Render Celery worker subscriber only after configuring a TLS broker:

```text
MQTT_ENABLED=true
MQTT_BROKER_URL=mqtts://<broker-host>:8883
MQTT_CA_FILE=<path-to-trusted-ca>
MQTT_CLIENT_CERT_FILE=<optional-client-certificate>
MQTT_CLIENT_KEY_FILE=<optional-client-private-key>
MQTT_USERNAME=<optional-broker-username>
MQTT_PASSWORD=<optional-broker-password>
```

Client certificate and private key must be supplied together. Broker username
and password must be supplied together. MQTT is disabled by default; enabling it
with a non-TLS URL is a startup configuration error. The subscriber uses QoS 1,
a stable persistent client ID/session, reconnect backoff, manual acknowledgments,
and a bounded in-memory queue. It acknowledges only after processing and
publishing the item result. When the queue is full or a database/result write
fails, it disconnects without acknowledging so the broker redelivers. MongoDB
event-key uniqueness makes redelivery safe.

Topic format:

```text
realityloop/v1/organizations/{organization_id}/devices/{key_id}/readings
```

Payload format:

```json
{
  "credential": "key_id.secret",
  "readings": [
    {
      "sensor_id": "registered-sensor-object-id",
      "value": 21.5,
      "unit": "C",
      "event_time_utc": "2025-01-15T10:00:00Z",
      "sequence": 82,
      "quality": "good"
    }
  ]
}
```

The topic organization and key ID must match the validated scoped credential.
The credential is carried in the JSON body because MQTT subscriber callbacks do
not expose each publishing client's CONNECT credentials. Use TLS, a trusted
private broker, broker-side topic ACLs, and broker settings that do not retain
or log message payloads. The subscriber rejects retained messages and payloads
larger than `MQTT_MESSAGE_MAX_BYTES`. Device secrets must never be copied into
broker logs or retained messages. Per-item and batch outcomes are published at
the corresponding `.../results` topic. The result contains status and rejection
codes, not the credential or raw payload.

The Render worker starts the subscriber only when `MQTT_ENABLED=true`. It does
not provision a broker. `MQTT_QUEUE_CAPACITY` (default 1,000) and
`MQTT_MESSAGE_MAX_BYTES` (default 65,536 bytes) bound process memory/input.

## Sensor state

`GET /api/v1/sensors/{sensor_id}/telemetry-state` reports `never_seen`, `fresh`,
or `stale`, the last server receipt time, the latest device event time, and the
stale threshold. This state is derived from one bounded document per
organization/sensor; it does not embed reading history in a sensor record.
Owners, administrators, and engineers can set a per-sensor threshold with
`PUT /api/v1/sensors/{sensor_id}/telemetry-state`. Without an override, the
threshold is the expected reporting interval multiplied by
`SENSOR_STALE_MULTIPLIER` (default 3). `last_seen_at` is receipt time;
`last_event_time` is device/source time and delayed values do not replace it
with receipt time.

## Durable REST edge buffer

`app.telemetry.edge_buffer.DurableEdgeBuffer` stores an ordered, bounded SQLite
outbox on disk. Each item receives a persistent local sequence and event ID
before the first send. `RestEdgePublisher` posts ordered batches to the REST
endpoint over HTTPS, retains the batch on network loss, and removes only
accepted/duplicate items. A lost HTTP response can cause a replay; the server's
unique event key returns duplicates without creating readings. A rejected item
is retained and raises `EdgePublishRejected` so an operator can correct the
mapping instead of silently dropping data. The OPC UA CLI uses this buffer at
`REALITYLOOP_EDGE_BUFFER` (default `realityloop-edge.sqlite3`).

## Read-only OPC UA adapter

`python -m app.telemetry.opcua_edge --mapping <mapping.json>` polls explicitly
mapped OPC UA nodes and publishes through the same REST device credential and
durable outbox. Configure `OPCUA_ENDPOINT`, `OPCUA_CLIENT_CERT_FILE`,
`OPCUA_CLIENT_KEY_FILE`, `REALITYLOOP_API_URL` (base ending in `/api/v1`),
`REALITYLOOP_DEVICE_CREDENTIAL`, and optionally
`OPCUA_POLL_INTERVAL_SECONDS`. The endpoint must use `opc.tcp://`; client
SignAndEncrypt certificate/key files are required. The adapter exposes only
connection, `read_data_value`, and disconnect operations; it contains no OPC UA
write or method-call path.

Every map must set node ID, registered sensor ID, input unit, scale, and offset.
No unit or scale is inferred:

```json
[
  {
    "node_id": "ns=2;s=Line1.MotorCurrent",
    "sensor_id": "0123456789abcdef01234567",
    "unit": "A",
    "scale": 1.0,
    "offset": 0.0
  }
]
```

The event time uses the OPC UA source timestamp when present, otherwise the
server timestamp; missing or timezone-naive timestamps are rejected. OPC UA
Good/Uncertain/Bad quality codes map to the normalized reading quality field.
OPC UA data is never read directly by a browser.

## Protocol fixtures and verification

Examples are in `backend/tests/fixtures/device-ingestion/`. Run the protocol and
REST gate tests with:

```powershell
.\.venv\Scripts\python.exe -m pytest -c backend\pyproject.toml backend\tests\test_sensor_imports.py -q
```

The tests use a MongoDB double and in-process MQTT/OPC UA client fixtures; they
exercise credential scoping, redelivery idempotency, queue backpressure,
timestamp/quality mapping, and durable edge replay without hardware or a
broker. They do not prove connectivity, TLS trust, ACL behavior, or wire-level
reconnect semantics against a deployed broker or industrial gateway. Those
checks remain required when the user supplies a test environment.

## Configurable limits

| Setting | Default | Purpose |
|---|---:|---|
| `DEVICE_BATCH_MAX_READINGS` | 500 | Maximum readings per REST/MQTT request |
| `DEVICE_BATCH_MAX_BYTES` | 262,144 | Maximum REST/MQTT batch bytes |
| `DEVICE_FUTURE_TOLERANCE_SECONDS` | 300 | Maximum device time ahead of receipt |
| `MQTT_QUEUE_CAPACITY` | 1,000 | Maximum queued broker messages |
| `MQTT_MESSAGE_MAX_BYTES` | 65,536 | Maximum MQTT payload bytes |
| `EDGE_BUFFER_MAX_ROWS` | 100,000 | Maximum durable local outbox rows |
| `EDGE_BATCH_MAX_READINGS` | 100 | Maximum readings per edge POST |
| `EDGE_BATCH_MAX_BYTES` | 131,072 | Maximum serialized edge request bytes |
| `EDGE_RETRY_BASE_SECONDS` | 1 | Initial edge retry wait |
| `EDGE_RETRY_MAX_SECONDS` | 60 | Maximum edge retry wait |
| `SENSOR_STALE_MULTIPLIER` | 3 | Default freshness threshold multiplier |

Historical-import limits are documented in
[`SENSOR_IMPORTS.md`](./SENSOR_IMPORTS.md#limits).
