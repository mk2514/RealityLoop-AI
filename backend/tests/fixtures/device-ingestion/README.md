# Device ingestion fixtures

- `rest-batch.json` is the REST batch envelope; replace the example sensor ID
  with an organization-scoped registered sensor.
- `mqtt-message.json` is the MQTT payload and contains only a credential
  placeholder. Never commit a real key.
- `opcua-node-map.json` is the explicit node, registered sensor, unit, scale,
  and offset mapping used by the read-only OPC UA adapter.

No fixtures contain production credentials or real telemetry.
