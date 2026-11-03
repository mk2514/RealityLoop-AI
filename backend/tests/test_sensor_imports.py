import csv
import hashlib
import io
import json
from types import SimpleNamespace
from datetime import UTC, datetime
from pathlib import Path

import mongomock
import pytest
from bson import ObjectId
from fastapi.testclient import TestClient

from app.api.routes import auth, device_credentials, telemetry
from app.api.routes.auth import Principal, get_current_principal
from app.api.routes import sensor_imports
from app.core.config import Settings
from app.db.migrations.versions import v0006_sensor_readings, v0007_device_ingestion
from app.main import app
from app.telemetry.readings import (
    as_utc,
    canonicalize_value,
    make_event_key,
    parse_event_time,
)
from app.telemetry import devices
from app.telemetry.devices import (
    new_device_secret,
    sensor_state_payload,
    update_sensor_receipt,
)
from app.telemetry.edge_buffer import (
    DurableEdgeBuffer,
    EdgeBufferFull,
    RestEdgePublisher,
)
from app.telemetry.ingestion import DeviceReading, ingest_readings
from app.telemetry import edge_buffer, mqtt_subscriber, opcua_edge
from app.telemetry.mqtt_subscriber import process_mqtt_message
from app.worker import sensor_imports as worker

FIXTURES = Path(__file__).parent / "fixtures" / "sensor-imports"


class FakeSession:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def with_transaction(self, callback):
        return callback(None)


class FakeMongoClient:
    def start_session(self):
        return FakeSession()


class MemoryStorage:
    def __init__(self):
        self.objects = {}

    def put_object(self, **kwargs):
        self.objects[kwargs["Key"]] = kwargs["Body"]

    def get_object(self, **kwargs):
        return {"Body": io.BytesIO(self.objects[kwargs["Key"]])}

    def generate_presigned_url(self, *_args, **_kwargs):
        return "https://private-storage.example/signed"


@pytest.fixture
def import_environment(monkeypatch):
    database = mongomock.MongoClient().get_database("realityloop")
    org_id = ObjectId()
    user_id = ObjectId()
    machine_id = ObjectId()
    component_id = ObjectId()
    sensor_id = ObjectId()
    database.machines.insert_one(
        {
            "_id": machine_id,
            "organization_id": org_id,
            "archived_at": None,
        }
    )
    database.components.insert_one(
        {
            "_id": component_id,
            "organization_id": org_id,
            "machine_id": machine_id,
            "archived_at": None,
        }
    )
    database.sensors.insert_one(
        {
            "_id": sensor_id,
            "organization_id": org_id,
            "machine_id": machine_id,
            "component_id": component_id,
            "identity": "SENSOR-A",
            "name": "Sensor A",
            "measurement_type": "temperature",
            "unit": "C",
            "expected_reporting_interval_seconds": 10,
            "calibration": {"scale": None, "offset": None},
            "factory_id": ObjectId(),
            "line_id": ObjectId(),
            "archived_at": None,
        }
    )
    readings = database.sensor_readings

    def mongomock_bulk_write(operations, ordered=False, session=None):
        del ordered, session
        upserted_ids = {}
        for index, operation in enumerate(operations):
            result = readings.update_one(
                operation._filter,
                operation._doc,
                upsert=operation._upsert,
            )
            if result.upserted_id is not None:
                upserted_ids[index] = result.upserted_id
        return SimpleNamespace(upserted_ids=upserted_ids)

    readings.bulk_write = mongomock_bulk_write
    settings = Settings(
        _env_file=None,
        sensor_import_max_file_bytes=1_000_000,
        sensor_import_max_rows=100,
        sensor_import_preview_rows=25,
        sensor_import_batch_size=2,
        device_batch_max_readings=10,
        device_batch_max_bytes=4096,
        s3_bucket="private-test-bucket",
    )
    storage = MemoryStorage()
    monkeypatch.setattr(auth, "get_database", lambda: database)
    monkeypatch.setattr(auth, "get_settings", lambda: settings)
    monkeypatch.setattr(sensor_imports, "get_database", lambda: database)
    monkeypatch.setattr(device_credentials, "get_database", lambda: database)
    monkeypatch.setattr(device_credentials, "get_mongo_client", FakeMongoClient)
    monkeypatch.setattr(telemetry, "get_database", lambda: database)
    monkeypatch.setattr(devices, "get_settings", lambda: settings)
    monkeypatch.setattr(sensor_imports, "get_settings", lambda: settings)
    monkeypatch.setattr(telemetry, "get_settings", lambda: settings)
    monkeypatch.setattr(edge_buffer, "get_settings", lambda: settings)
    monkeypatch.setattr(mqtt_subscriber, "get_settings", lambda: settings)
    monkeypatch.setattr(worker, "get_database", lambda: database)
    monkeypatch.setattr(worker, "get_mongo_client", FakeMongoClient)
    monkeypatch.setattr(worker, "get_settings", lambda: settings)
    monkeypatch.setattr(sensor_imports, "get_storage_client", lambda: (storage, "private-test-bucket"))
    monkeypatch.setattr(worker, "get_storage_client", lambda: (storage, "private-test-bucket"))
    monkeypatch.setattr(sensor_imports.process_sensor_import, "delay", lambda *_args: None)
    monkeypatch.setattr(
        sensor_imports,
        "get_current_principal",
        lambda: _principal(user_id, org_id),
    )
    app.dependency_overrides[get_current_principal] = lambda: _principal(user_id, org_id)
    yield {
        "database": database,
        "org_id": org_id,
        "user_id": user_id,
        "machine_id": machine_id,
        "sensor_id": sensor_id,
        "storage": storage,
    }
    app.dependency_overrides.clear()


def _principal(user_id: ObjectId, organization_id: ObjectId) -> Principal:
    return Principal(
        user_id=user_id,
        organization_id=organization_id,
        role="owner",
        email="owner@example.test",
        full_name="Owner",
        organization_name="Test Organization",
        organization_slug="test-organization",
    )


def _mapping(sensor_id: ObjectId) -> dict:
    return {
        "timestamp_column": "timestamp",
        "timestamp_timezone": "value",
        "value_column": "reading",
        "unit_column": "unit",
        "sensor_column": "sensor",
        "fixed_sensor_id": None,
        "fixed_unit": None,
        "source_event_id_column": "source_event_id",
    }


def _headers(mapping: dict | None = None) -> dict[str, str]:
    headers = {"X-CSRF-Token": "csrf", "Content-Type": "text/csv"}
    if mapping is not None:
        headers["X-Import-Mapping"] = json.dumps(mapping)
    return headers


def test_reading_unit_conversion_timezone_and_dst_rejections() -> None:
    quantity, unit, value = canonicalize_value(
        "temperature", "F", 68, registered_unit="C"
    )
    assert (quantity, unit, value) == ("temperature", "°C", 20)
    assert parse_event_time("2025-01-01T10:00:00+02:00", None) == datetime(
        2025, 1, 1, 8, tzinfo=UTC
    )
    assert parse_event_time("2025-01-01 10:00:00", "UTC") == datetime(
        2025, 1, 1, 10, tzinfo=UTC
    )
    with pytest.raises(ValueError, match="AMBIGUOUS_LOCAL_TIME"):
        parse_event_time("2024-11-03 01:30:00", "America/New_York")
    with pytest.raises(ValueError, match="NONEXISTENT_LOCAL_TIME"):
        parse_event_time("2024-03-10 02:30:00", "America/New_York")
    with pytest.raises(ValueError, match="INCOMPATIBLE_UNIT"):
        canonicalize_value("temperature", "kg", 1, registered_unit="C")


def test_import_worker_exact_counts_private_errors_and_retry_idempotency(import_environment) -> None:
    database = import_environment["database"]
    org_id = import_environment["org_id"]
    sensor_id = import_environment["sensor_id"]
    machine_id = import_environment["machine_id"]
    source = (FIXTURES / "layer6.csv").read_bytes()
    import_id = ObjectId()
    source_key = f"sensor-imports/{org_id}/{import_id}/source.csv"
    storage = import_environment["storage"]
    storage.objects[source_key] = source

    existing_time = datetime(2025, 1, 15, 11, tzinfo=UTC)
    existing_key = make_event_key(
        str(org_id),
        str(sensor_id),
        "temperature",
        existing_time,
        source_event_id="existing-event",
    )
    database.sensor_readings.insert_one(
        {
            "organization_id": org_id,
            "sensor_id": str(sensor_id),
            "machine_id": str(machine_id),
            "quantity": "temperature",
            "unit": "°C",
            "value": 30,
            "event_time_utc": existing_time,
            "received_at_utc": datetime.now(UTC),
            "source": "rest",
            "source_ref": "prior-device",
            "schema_version": 1,
            "event_key": existing_key,
        }
    )
    record = {
        "_id": import_id,
        "organization_id": org_id,
        "uploader_id": import_environment["user_id"],
        "sensor_id": sensor_id,
        "machine_id": machine_id,
        "source_object_key": source_key,
        "source_checksum": hashlib.sha256(source).hexdigest(),
        "mapping": _mapping(sensor_id),
        "status": "queued",
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
        "counts": {"total": 0, "inserted": 0, "duplicates": 0, "rejected": 0},
        "cancel_requested": False,
    }
    database.sensor_imports.insert_one(record)

    first_result = worker.process_sensor_import.run(str(import_id))
    expected = json.loads((FIXTURES / "layer6.expected.json").read_text(encoding="utf-8"))
    stored = database.sensor_imports.find_one({"_id": import_id})
    assert first_result["status"] == "completed_with_errors"
    assert stored["counts"] == {key: expected[key] for key in ("total", "inserted", "duplicates", "rejected")}
    assert stored["rejected_by_code"] == expected["rejected_by_code"]
    assert database.sensor_readings.count_documents({"organization_id": org_id}) == 2, {
        "result": first_result,
        "record": stored,
        "rows": list(database.sensor_import_rows.find({"import_id": import_id})),
        "readings": list(database.sensor_readings.find({"organization_id": org_id})),
    }
    assert database.sensor_import_rows.count_documents({"import_id": import_id}) == 8
    assert database.sensor_readings.find_one({"event_key": existing_key})["value"] == 30
    assert "readings" not in database.sensors.find_one({"_id": sensor_id})
    assert stored["source_checksum"] == hashlib.sha256(source).hexdigest()
    assert source_key in storage.objects
    error_content = storage.objects[stored["error_object_key"]].decode("utf-8")
    error_rows = list(csv.reader(io.StringIO(error_content)))
    assert [row[1] for row in error_rows[1:]] == [
        "MALFORMED_ROW",
        "UNKNOWN_SENSOR",
        "BAD_TIMESTAMP",
        "NON_NUMERIC_VALUE",
        "INCOMPATIBLE_UNIT",
    ]
    assert error_rows[3][3] == "not-a-date"

    before_count = database.sensor_readings.count_documents({"organization_id": org_id})
    database.sensor_imports.update_one(
        {"_id": import_id},
        {"$set": {"status": "processing", "lease_until": datetime(2000, 1, 1, tzinfo=UTC)}},
    )
    retry_result = worker.process_sensor_import.run(str(import_id))
    assert retry_result["status"] == "completed_with_errors"
    assert database.sensor_readings.count_documents({"organization_id": org_id}) == before_count
    assert database.sensor_imports.find_one({"_id": import_id})["counts"] == stored["counts"]


def test_preview_upload_limits_checksum_and_cross_org_access(import_environment, monkeypatch) -> None:
    database = import_environment["database"]
    client = TestClient(app)
    source = (FIXTURES / "layer6.csv").read_bytes()
    mapping = _mapping(import_environment["sensor_id"])
    url = f"/api/v1/sensor-imports/preview?sensor_id={import_environment['sensor_id']}"
    preview = client.post(
        url,
        content=source,
        headers=_headers(mapping),
        cookies={"rl_csrf": "csrf"},
    )
    assert preview.status_code == 200
    assert preview.json()["rows_total"] == 8
    assert preview.json()["sample_rows"][0]["parse_status"] == "valid"

    uploaded = client.post(
        f"/api/v1/sensor-imports?sensor_id={import_environment['sensor_id']}",
        content=source,
        headers={**_headers(mapping), "X-File-Name": "factory.csv"},
        cookies={"rl_csrf": "csrf"},
    )
    assert uploaded.status_code == 202
    imported = uploaded.json()["import"]
    record = database.sensor_imports.find_one({"_id": ObjectId(imported["import_id"])})
    assert record["source_checksum"] == hashlib.sha256(source).hexdigest()
    assert record["source_object_key"] in import_environment["storage"].objects
    assert record["original_filename"] == "factory.csv"
    assert record["status"] == "queued"

    other_org = ObjectId()
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        user_id=ObjectId(),
        organization_id=other_org,
        role="owner",
        email="other@example.test",
        full_name="Other",
        organization_name="Other",
        organization_slug="other",
    )
    denied = client.get(
        f"/api/v1/sensor-imports/{imported['import_id']}",
        cookies={"rl_csrf": "csrf"},
    )
    assert denied.status_code == 404

    app.dependency_overrides[get_current_principal] = lambda: _principal(
        import_environment["user_id"], import_environment["org_id"]
    )
    too_large = client.post(
        url,
        content=b"x" * 1_000_001,
        headers=_headers(),
        cookies={"rl_csrf": "csrf"},
    )
    assert too_large.status_code == 413


def test_sensor_import_migration_creates_scoped_unique_indexes() -> None:
    database = mongomock.MongoClient().get_database("realityloop")
    v0006_sensor_readings.upgrade(database)
    indexes = database.sensor_readings.index_information()
    assert indexes["uq_sensor_readings_org_event_key"]["unique"] is True
    assert indexes["ix_sensor_readings_sensor_event_time"]["key"] == [
        ("organization_id", 1),
        ("sensor_id", 1),
        ("event_time_utc", 1),
    ]


def test_device_ingestion_migration_creates_credential_and_state_indexes() -> None:
    database = mongomock.MongoClient().get_database("realityloop")
    v0007_device_ingestion.upgrade(database)
    assert database.device_credentials.index_information()[
        "uq_device_credentials_key_id"
    ]["unique"]
    assert database.sensor_states.index_information()[
        "uq_sensor_states_org_sensor"
    ]["unique"]


def test_rest_device_credentials_scoping_idempotency_revocation_and_limits(import_environment) -> None:
    database = import_environment["database"]
    org_id = import_environment["org_id"]
    other_sensor_id = ObjectId()
    sensor = database.sensors.find_one({"_id": import_environment["sensor_id"]})
    database.sensors.insert_one(
        {
            **sensor,
            "_id": other_sensor_id,
            "identity": "SENSOR-B",
            "name": "Sensor B",
        }
    )
    client = TestClient(app)
    created = client.post(
        "/api/v1/device-credentials",
        json={
            "name": "Conveyor gateway",
            "sensor_permissions": [
                {"sensor_id": str(import_environment["sensor_id"]), "quantities": ["temperature"]}
            ],
        },
        headers={"X-CSRF-Token": "csrf"},
        cookies={"rl_csrf": "csrf"},
    )
    assert created.status_code == 201
    credential = created.json()["credential"]
    secret = created.json()["secret"]
    stored = database.device_credentials.find_one({"_id": ObjectId(credential["credential_id"])})
    assert stored["secret_hash"] != secret
    assert secret not in json.dumps(stored, default=str)
    assert stored["last_used_at"] is None

    token = f"{credential['key_id']}.{secret}"
    payload = {
        "readings": [
            {
                "sensor_id": str(import_environment["sensor_id"]),
                "value": 68,
                "unit": "F",
                "event_time_utc": "2025-01-15T12:00:00+02:00",
                "sequence": 1,
            },
            {
                "sensor_id": str(import_environment["sensor_id"]),
                "value": 68,
                "unit": "F",
                "event_time_utc": "2025-01-15T12:00:00+02:00",
                "sequence": 1,
            },
            {
                "sensor_id": str(other_sensor_id),
                "value": 1,
                "unit": "C",
                "event_time_utc": "2025-01-15T12:00:00Z",
            },
            {
                "sensor_id": str(import_environment["sensor_id"]),
                "value": "not numeric",
                "unit": "C",
                "event_time_utc": "2025-01-15T12:00:00Z",
            },
            {
                "sensor_id": str(import_environment["sensor_id"]),
                "value": 10,
                "unit": "C",
                "event_time_utc": "2028-01-01T00:00:00Z",
            },
        ]
    }
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    ingested = client.post("/api/v1/telemetry/readings", json=payload, headers=headers)
    assert ingested.status_code == 200
    result = ingested.json()
    assert result["counts"] == {"accepted": 1, "duplicates": 1, "rejected": 3}
    assert [item["index"] for item in result["results"]] == [0, 1, 2, 3, 4]
    assert result["results"][0]["status"] == "accepted"
    assert result["results"][1]["code"] == "DUPLICATE_IN_BATCH"
    assert result["results"][2]["code"] == "SENSOR_NOT_PERMITTED"
    assert result["results"][3]["code"] == "INVALID_ITEM"
    assert result["results"][4]["code"] == "FUTURE_TIMESTAMP"
    reading = database.sensor_readings.find_one({"organization_id": org_id})
    assert reading["value"] == pytest.approx(20)
    assert as_utc(reading["event_time_utc"]) == datetime(2025, 1, 15, 10, tzinfo=UTC)
    assert reading["received_at_utc"] >= reading["event_time_utc"]
    assert reading["source"] == "rest"
    assert database.sensor_readings.count_documents({"organization_id": org_id}) == 1
    assert database.device_credentials.find_one({"_id": stored["_id"]})["last_used_at"]

    replay = client.post(
        "/api/v1/telemetry/readings",
        json={"readings": payload["readings"][:1]},
        headers=headers,
    )
    assert replay.status_code == 200
    assert replay.json()["counts"] == {"accepted": 0, "duplicates": 1, "rejected": 0}
    assert database.sensor_readings.count_documents({"organization_id": org_id}) == 1

    oversized = client.post(
        "/api/v1/telemetry/readings",
        content=b"x" * 4097,
        headers={**headers, "Content-Type": "application/json"},
    )
    assert oversized.status_code == 413

    rotated = client.post(
        f"/api/v1/device-credentials/{credential['credential_id']}/rotate",
        headers={"X-CSRF-Token": "csrf"},
        cookies={"rl_csrf": "csrf"},
    )
    assert rotated.status_code == 200
    rotated_credential = rotated.json()["credential"]
    rotated_token = f"{rotated_credential['key_id']}.{rotated.json()['secret']}"
    old_token_response = client.post(
        "/api/v1/telemetry/readings",
        json={"readings": payload["readings"][:1]},
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    assert old_token_response.status_code == 401

    other_org = ObjectId()
    app.dependency_overrides[get_current_principal] = lambda: _principal(
        ObjectId(), other_org
    )
    hidden = client.get(
        f"/api/v1/device-credentials?sensor_id={import_environment['sensor_id']}"
    )
    assert hidden.status_code == 404
    app.dependency_overrides[get_current_principal] = lambda: _principal(
        import_environment["user_id"], org_id
    )
    revoked = client.post(
        f"/api/v1/device-credentials/{rotated_credential['credential_id']}/revoke",
        headers={"X-CSRF-Token": "csrf"},
        cookies={"rl_csrf": "csrf"},
    )
    assert revoked.status_code == 200
    after_revoke = client.post(
        "/api/v1/telemetry/readings",
        json={"readings": payload["readings"][:1]},
        headers={"Authorization": f"Bearer {rotated_token}", "Content-Type": "application/json"},
    )
    assert after_revoke.status_code == 401
    assert database.sensor_readings.count_documents({"organization_id": org_id}) == 1


def test_sensor_stale_fresh_transition_and_device_time_ordering(import_environment) -> None:
    database = import_environment["database"]
    sensor = database.sensors.find_one({"_id": import_environment["sensor_id"]})
    org_id = import_environment["org_id"]
    base = datetime(2025, 1, 1, tzinfo=UTC)
    initial = sensor_state_payload(
        database, organization_id=org_id, sensor=sensor, now=base
    )
    assert initial["connection_state"] == "never_seen"
    update_sensor_receipt(
        database,
        organization_id=org_id,
        sensor=sensor,
        event_time_utc=base,
        received_at_utc=base,
    )
    fresh = sensor_state_payload(
        database, organization_id=org_id, sensor=sensor, now=base.replace(second=29)
    )
    stale = sensor_state_payload(
        database, organization_id=org_id, sensor=sensor, now=base.replace(second=31)
    )
    assert fresh["connection_state"] == "fresh"
    assert stale["connection_state"] == "stale"
    update_sensor_receipt(
        database,
        organization_id=org_id,
        sensor=sensor,
        event_time_utc=base.replace(second=2),
        received_at_utc=base.replace(second=32),
    )
    recovered = sensor_state_payload(
        database, organization_id=org_id, sensor=sensor, now=base.replace(second=33)
    )
    assert recovered["connection_state"] == "fresh"
    assert recovered["last_seen_at"] == base.replace(second=32).isoformat()
    assert recovered["last_event_time"] == base.replace(second=2).isoformat()


def _insert_device_credential(database, organization_id: ObjectId, sensor_id: ObjectId):
    key_id, secret, secret_hash = new_device_secret()
    now = datetime.now(UTC)
    record = {
        "_id": ObjectId(),
        "organization_id": organization_id,
        "created_by": ObjectId(),
        "key_id": key_id,
        "secret_hash": secret_hash,
        "name": "Protocol fixture",
        "sensor_permissions": [{"sensor_id": sensor_id, "quantities": None}],
        "created_at": now,
        "updated_at": now,
        "expires_at": datetime(2099, 1, 1, tzinfo=UTC),
        "last_used_at": None,
        "revoked_at": None,
        "credential_version": 1,
    }
    database.device_credentials.insert_one(record)
    return record, f"{key_id}.{secret}"


def test_mqtt_fixture_authentication_permissions_duplicates_and_revocation(import_environment) -> None:
    database = import_environment["database"]
    organization_id = import_environment["org_id"]
    sensor_id = import_environment["sensor_id"]
    credential, token = _insert_device_credential(database, organization_id, sensor_id)
    event_time = datetime(2025, 1, 15, 10, tzinfo=UTC)
    received_at = datetime(2025, 1, 15, 10, 5, tzinfo=UTC)
    payload = json.dumps(
        {
            "credential": token,
            "readings": [
                {
                    "sensor_id": str(sensor_id),
                    "value": 21.5,
                    "unit": "C",
                    "event_time_utc": event_time.isoformat(),
                    "sequence": 55,
                }
            ],
        }
    ).encode()
    topic = (
        f"realityloop/v1/organizations/{organization_id}/devices/"
        f"{credential['key_id']}/readings"
    )

    first = process_mqtt_message(
        database=database,
        topic=topic,
        payload=payload,
        received_at=received_at,
    )
    redelivery = process_mqtt_message(
        database=database,
        topic=topic,
        payload=payload,
        received_at=received_at,
    )
    assert first["counts"] == {"accepted": 1, "duplicates": 0, "rejected": 0}
    assert redelivery["counts"] == {"accepted": 0, "duplicates": 1, "rejected": 0}
    stored = database.sensor_readings.find_one({"organization_id": organization_id})
    assert stored["source"] == "mqtt"
    assert as_utc(stored["event_time_utc"]) == event_time
    assert as_utc(stored["received_at_utc"]) == received_at
    assert database.sensor_readings.count_documents({"organization_id": organization_id}) == 1
    assert database.device_credentials.find_one({"_id": credential["_id"]})["last_used_at"]

    wrong_org_topic = topic.replace(str(organization_id), str(ObjectId()))
    with pytest.raises(PermissionError, match="topic does not match"):
        process_mqtt_message(
            database=database,
            topic=wrong_org_topic,
            payload=payload,
            received_at=received_at,
        )

    database.device_credentials.update_one(
        {"_id": credential["_id"]},
        {"$set": {"revoked_at": received_at}},
    )
    with pytest.raises(PermissionError, match="invalid, revoked, or expired"):
        process_mqtt_message(
            database=database,
            topic=topic,
            payload=payload,
            received_at=received_at,
        )
    assert database.sensor_readings.count_documents({"organization_id": organization_id}) == 1


def test_mqtt_subscriber_uses_qos1_and_disconnects_on_bounded_queue_pressure(monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        mqtt_enabled=True,
        mqtt_broker_url="mqtts://broker.example.test:8883",
        mqtt_queue_capacity=1,
        mqtt_message_max_bytes=1024,
    )
    monkeypatch.setattr(mqtt_subscriber, "get_settings", lambda: settings)

    class FakeClient:
        def __init__(self, **options):
            self.options = options
            self.subscriptions = []
            self.disconnect_count = 0
            self.acks = []

        def reconnect_delay_set(self, **_kwargs):
            return None

        def tls_set(self, **_kwargs):
            return None

        def subscribe(self, topic, qos):
            self.subscriptions.append((topic, qos))

        def disconnect(self):
            self.disconnect_count += 1

        def ack(self, mid, qos):
            self.acks.append((mid, qos))

    monkeypatch.setattr(mqtt_subscriber.mqtt, "Client", FakeClient)
    subscriber = mqtt_subscriber.MQTTIngestSubscriber()
    assert subscriber.client.options["manual_ack"] is True
    subscriber._on_connect(
        subscriber.client,
        None,
        None,
        SimpleNamespace(is_failure=False),
        None,
    )
    assert subscriber.client.subscriptions == [
        ("realityloop/v1/organizations/+/devices/+/readings", 1)
    ]
    first = SimpleNamespace(retain=False, payload=b"{}", mid=1, qos=1)
    second = SimpleNamespace(retain=False, payload=b"{}", mid=2, qos=1)
    subscriber._on_message(subscriber.client, None, first)
    subscriber._on_message(subscriber.client, None, second)
    assert subscriber.messages.qsize() == 1
    assert subscriber.client.disconnect_count == 1
    assert subscriber.client.acks == []


def test_edge_buffer_replays_after_lost_connection_without_duplicate_storage(
    import_environment, tmp_path
) -> None:
    database = import_environment["database"]
    organization_id = import_environment["org_id"]
    sensor_id = import_environment["sensor_id"]
    credential, token = _insert_device_credential(database, organization_id, sensor_id)
    buffer_path = tmp_path / "edge-buffer.sqlite3"
    buffer = DurableEdgeBuffer(
        buffer_path,
        max_rows=5,
        max_batch_readings=2,
        max_batch_bytes=4096,
    )
    source_times = [
        "2025-01-15T09:00:00+00:00",
        "2025-01-15T09:01:00+00:00",
        "2025-01-15T09:02:00+00:00",
    ]
    for index, event_time in enumerate(source_times):
        buffer.enqueue(
            {
                "sensor_id": str(sensor_id),
                "value": 20 + index,
                "unit": "C",
                "event_time_utc": event_time,
            }
        )
    initial_batch = buffer.peek_batch()
    stable_ids = [
        (item.reading["sequence"], item.reading["source_event_id"])
        for item in initial_batch
    ]
    publisher = RestEdgePublisher(
        buffer,
        api_url="http://127.0.0.1:8000/api/v1",
        credential=token,
    )
    attempted = 0

    def disconnected_post(readings):
        nonlocal attempted
        attempted += 1
        result = ingest_readings(
            database=database,
            credential=credential,
            items=[DeviceReading.model_validate(item) for item in readings],
            source="rest",
            received_at=datetime(2025, 1, 15, 10, tzinfo=UTC),
        )
        if attempted == 1:
            raise TimeoutError("simulated lost response after server commit")
        return result

    with pytest.raises(TimeoutError):
        publisher.publish_pending(disconnected_post)
    assert database.sensor_readings.count_documents({"organization_id": organization_id}) == 2
    assert buffer.count() == 3
    buffer.close()

    restarted_buffer = DurableEdgeBuffer(
        buffer_path,
        max_rows=5,
        max_batch_readings=2,
        max_batch_bytes=4096,
    )
    restarted_ids = [
        (item.reading["sequence"], item.reading["source_event_id"])
        for item in restarted_buffer.peek_batch()
    ]
    assert restarted_ids == stable_ids
    restarted_publisher = RestEdgePublisher(
        restarted_buffer,
        api_url="http://127.0.0.1:8000/api/v1",
        credential=token,
    )
    duplicate_count = 0

    def reconnected_post(readings):
        nonlocal duplicate_count
        result = ingest_readings(
            database=database,
            credential=credential,
            items=[DeviceReading.model_validate(item) for item in readings],
            source="rest",
            received_at=datetime(2025, 1, 15, 10, 1, tzinfo=UTC),
        )
        duplicate_count += sum(item["status"] == "duplicate" for item in result)
        return result

    assert restarted_publisher.publish_pending(reconnected_post) == 1
    assert duplicate_count == 2
    assert restarted_buffer.count() == 0
    assert database.sensor_readings.count_documents({"organization_id": organization_id}) == 3
    stored_times = [
        as_utc(item["event_time_utc"]).isoformat()
        for item in database.sensor_readings.find(
            {"organization_id": organization_id}
        ).sort("event_time_utc", 1)
    ]
    assert stored_times == source_times
    restarted_buffer.close()


def test_edge_buffer_enforces_capacity_and_reopens_durably(tmp_path) -> None:
    path = tmp_path / "bounded-buffer.sqlite3"
    buffer = DurableEdgeBuffer(
        path,
        max_rows=1,
        max_batch_readings=1,
        max_batch_bytes=512,
    )
    buffer.enqueue({"sensor_id": "sensor-a"})
    with pytest.raises(EdgeBufferFull, match="configured 1-reading limit"):
        buffer.enqueue({"sensor_id": "sensor-b"})
    buffer.close()
    reopened = DurableEdgeBuffer(
        path,
        max_rows=1,
        max_batch_readings=1,
        max_batch_bytes=512,
    )
    assert reopened.count() == 1
    reopened.close()


def test_opcua_adapter_maps_units_quality_and_source_time_without_write_surface(monkeypatch) -> None:
    source_time = datetime(2025, 1, 15, 10, tzinfo=UTC)
    server_time = datetime(2025, 1, 15, 10, 1, tzinfo=UTC)
    data_value = SimpleNamespace(
        Value=SimpleNamespace(Value=2.5),
        SourceTimestamp=source_time,
        ServerTimestamp=server_time,
        StatusCode=SimpleNamespace(name="Good"),
    )
    mapping = opcua_edge.OpcUaSensorMap.from_json(
        {
            "node_id": "ns=2;s=Line/Motor/Current",
            "sensor_id": "0123456789abcdef01234567",
            "unit": "A",
            "scale": 2,
            "offset": 1,
        }
    )
    reading = opcua_edge.mapped_reading(mapping, data_value)
    assert reading["value"] == 6
    assert reading["unit"] == "A"
    assert reading["quality"] == "good"
    assert reading["event_time_utc"] == source_time.isoformat()

    calls = []

    class ReadOnlyNode:
        async def read_data_value(self):
            calls.append("read")
            return data_value

    class FakeUaClient:
        async def set_security_string(self, _security):
            calls.append("secure")

        async def connect(self):
            calls.append("connect")

        def get_node(self, node_id):
            calls.append(node_id)
            return ReadOnlyNode()

        async def disconnect(self):
            calls.append("disconnect")

    monkeypatch.setattr(opcua_edge, "Client", lambda _endpoint: FakeUaClient())
    adapter = opcua_edge.AsyncUaReadOnlyAdapter(
        "opc.tcp://127.0.0.1:4840",
        certificate_file="client.der",
        private_key_file="client.pem",
    )

    async def read_once():
        await adapter.connect()
        await adapter.read_data_value(mapping.node_id)
        await adapter.disconnect()

    import asyncio

    asyncio.run(read_once())
    assert calls == ["secure", "connect", mapping.node_id, "read", "disconnect"]
    assert not hasattr(adapter, "write_value")
    assert not hasattr(adapter, "call_method")


def test_opcua_mapping_rejects_implicit_units_and_bad_timestamps() -> None:
    with pytest.raises(ValueError, match="explicitly provide"):
        opcua_edge.OpcUaSensorMap.from_json(
            {"node_id": "ns=2;s=x", "sensor_id": "sensor-a", "scale": 1, "offset": 0}
        )
    mapping = opcua_edge.OpcUaSensorMap(
        node_id="ns=2;s=x",
        sensor_id="sensor-a",
        unit="A",
        scale=1,
        offset=0,
    )
    invalid_time = SimpleNamespace(
        Value=SimpleNamespace(Value=1),
        SourceTimestamp=None,
        ServerTimestamp=None,
        StatusCode=SimpleNamespace(name="Bad"),
    )
    with pytest.raises(ValueError, match="no timezone-aware"):
        opcua_edge.mapped_reading(mapping, invalid_time)


def test_historical_analysis_missing_key_and_tenant_scope(import_environment, monkeypatch) -> None:
    database = import_environment["database"]
    org_id = import_environment["org_id"]
    user_id = import_environment["user_id"]
    principal = _principal(user_id, org_id)
    payload = sensor_imports.HistoricalAnalysisRequest(
        evidence_summary={
            "dataset": "MetroPT3 local source subset",
            "tp3_observed_mean_bar": 8.5,
            "sample_count": 218,
        }
    )
    result = sensor_imports.create_historical_analysis(payload, principal=principal)
    assert result["status"] == "missing_key"

    job = database.historical_analysis_jobs.find_one({"organization_id": org_id})
    assert job is not None
    visible = sensor_imports.get_historical_analysis(str(job["_id"]), principal=principal)
    assert visible["status"] == "missing_key"

    other_org = _principal(ObjectId(), ObjectId())
    with pytest.raises(Exception) as exc:
        sensor_imports.get_historical_analysis(str(job["_id"]), principal=other_org)
    assert getattr(exc.value, "status_code", None) == 404


def test_historical_analysis_runs_gemini_without_worker(import_environment, monkeypatch) -> None:
    database = import_environment["database"]
    org_id = import_environment["org_id"]
    principal = _principal(import_environment["user_id"], org_id)
    monkeypatch.setattr(
        sensor_imports,
        "get_settings",
        lambda: SimpleNamespace(gemini_api_key="test-key", gemini_model="test-model"),
    )
    expected = {
        "anomaly_prediction": {"assessment": "anomaly_candidate", "evidence": ["Test evidence"]},
        "possible_causes": [{"hypothesis": "Inspect data quality", "evidence": "Test evidence"}],
        "effects": {"measured": [], "potential": []},
        "cost": {"status": "unavailable", "time": "unknown", "money": "unknown"},
        "suggestions": ["Verify the source timestamp and sensor mapping."],
        "alternatives": ["No confirmed alternative without additional evidence."],
    }
    monkeypatch.setattr(
        sensor_imports,
        "_call_gemini_historical_analysis",
        lambda settings, evidence: expected,
    )

    payload = sensor_imports.HistoricalAnalysisRequest(
        evidence_summary={"sample_count": 218, "heldout_absolute_error_bar": 0.4}
    )
    result = sensor_imports.create_historical_analysis(payload, principal=principal)

    assert result["status"] == "completed"
    assert result["result"] == expected
    job = database.historical_analysis_jobs.find_one({"organization_id": org_id})
    assert job["status"] == "completed"
    assert job["result"] == expected
