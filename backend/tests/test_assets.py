from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

import mongomock
import pytest
from fastapi.testclient import TestClient

from app.api.routes import auth
from app.core.config import Settings
from app.main import app


class TransactionSession:
    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def with_transaction(self, callback):
        return callback(None)


class TransactionClient:
    def start_session(self) -> TransactionSession:
        return TransactionSession()


@pytest.fixture
def asset_environment(monkeypatch):
    _issued_tokens.clear()
    database = mongomock.MongoClient().get_database("realityloop")
    database.organizations.create_index("slug", unique=True)
    database.users.create_index("email", unique=True)
    database.organization_memberships.create_index(
        [("organization_id", 1), ("user_id", 1)],
        unique=True,
    )
    database.factories.create_index(
        [("organization_id", 1), ("_id", 1)],
    )
    database.machines.create_index(
        [("organization_id", 1), ("identity", 1)],
        unique=True,
    )
    database.components.create_index(
        [("organization_id", 1), ("identity", 1)],
        unique=True,
    )
    database.sensors.create_index(
        [("organization_id", 1), ("identity", 1)],
        unique=True,
    )
    monkeypatch.setattr(auth, "get_database", lambda: database)
    monkeypatch.setattr(auth, "get_mongo_client", TransactionClient)
    monkeypatch.setattr(auth, "_rate_limit", lambda *_args: None)
    monkeypatch.setattr(
        auth,
        "send_email",
        lambda email, _subject, body: _issued_tokens.append(
            parse_qs(urlparse(body.splitlines()[2]).query)["token"][0]
        ),
    )
    monkeypatch.setattr(auth, "get_settings", lambda: Settings(_env_file=None))
    from app.api.routes import assets

    monkeypatch.setattr(assets, "get_database", lambda: database)
    monkeypatch.setattr(assets, "get_mongo_client", TransactionClient)
    return database


def _csrf(client: TestClient) -> dict[str, str]:
    token = client.get("/api/v1/csrf").json()["csrf_token"]
    return {"X-CSRF-Token": token}


def _register(client: TestClient, email: str) -> None:
    headers = _csrf(client)
    response = client.post(
        "/api/v1/auth/register",
        headers=headers,
        json={
            "full_name": "Registry Owner",
            "email": email,
            "password": "correct horse battery",
            "organization_name": "Registry Organization",
        },
    )
    assert response.status_code == 202
    database = auth.get_database()
    user = database.users.find_one({"email": email})
    token_record = database.auth_tokens.find_one({"user_id": user["_id"]})
    from app.core.security import hash_token

    token = next(
        (
            candidate
            for candidate in _issued_tokens
            if hash_token(candidate) == token_record["_id"]
        ),
        None,
    )
    if token is None:
        pytest.fail("Test verification token was not captured.")
    verified = client.post(
        "/api/v1/auth/verify",
        headers=_csrf(client),
        json={"token": token},
    )
    assert verified.status_code == 200
    logged_in = client.post(
        "/api/v1/auth/login",
        headers=_csrf(client),
        json={"email": email, "password": "correct horse battery"},
    )
    assert logged_in.status_code == 200
_issued_tokens: list[str] = []


def _create_complete_hierarchy(client: TestClient) -> dict[str, dict]:
    headers = _csrf(client)
    factory_response = client.post(
        "/api/v1/factories",
        headers=headers,
        json={
            "name": "North Plant",
            "timezone": "America/Chicago",
            "description": "Machining facility",
            "unit_preferences": {"system": "imperial", "temperature": "F"},
            "operating_calendar": {
                "shifts": [
                    {"day": 0, "name": "Night", "start": "22:00", "end": "06:00"}
                ]
            },
        },
    )
    assert factory_response.status_code == 201, factory_response.text
    factory = factory_response.json()
    line_response = client.post(
        f"/api/v1/factories/{factory['id']}/lines",
        headers=_csrf(client),
        json={"name": "Line A", "description": "Primary line"},
    )
    assert line_response.status_code == 201, line_response.text
    line = line_response.json()
    machine_response = client.post(
        f"/api/v1/lines/{line['id']}/machines",
        headers=_csrf(client),
        json={
            "identity": "CNC-001",
            "name": "CNC cell",
            "machine_type": "cnc_cutting",
            "capabilities": ["cut_material"],
            "manufacturer": "Example",
            "model": "C-1",
            "nominal_cycle_time_seconds": 54,
            "capacity_per_hour": 60,
            "operating_state": "offline",
        },
    )
    assert machine_response.status_code == 201, machine_response.text
    machine = machine_response.json()
    component_response = client.post(
        f"/api/v1/machines/{machine['id']}/components",
        headers=_csrf(client),
        json={
            "identity": "MOTOR-001",
            "name": "Spindle motor",
            "component_type": "motor",
        },
    )
    assert component_response.status_code == 201, component_response.text
    component = component_response.json()
    sensor_response = client.post(
        f"/api/v1/components/{component['id']}/sensors",
        headers=_csrf(client),
        json={
            "identity": "TEMP-001",
            "name": "Spindle temperature",
            "measurement_type": "temperature",
            "unit": "°C",
            "expected_reporting_interval_seconds": 2,
            "thresholds": {"minimum": 5, "maximum": 90},
            "calibration": {
                "last_calibrated_at": "2026-01-01T10:00:00Z",
                "calibration_due_at": "2027-01-01T10:00:00Z",
                "offset": 0.1,
                "scale": 1.0,
                "notes": "Annual calibration",
            },
        },
    )
    assert sensor_response.status_code == 201, sensor_response.text
    return {
        "factory": factory,
        "line": line,
        "machine": machine,
        "component": component,
        "sensor": sensor_response.json(),
    }


def test_complete_asset_hierarchy_persists_editing_and_audit(asset_environment) -> None:
    database = asset_environment
    client = TestClient(app)
    _register(client, "registry@example.com")
    hierarchy = _create_complete_hierarchy(client)

    factory = hierarchy["factory"]
    assert factory["timezone"] == "America/Chicago"
    assert factory["unit_preferences"] == {"system": "imperial", "temperature": "F"}
    assert factory["operating_calendar"]["shifts"][0]["end"] == "06:00"
    assert hierarchy["machine"]["model_validation_status"] == "not_validated"
    assert hierarchy["sensor"]["calibration"]["offset"] == 0.1

    updated = client.patch(
        f"/api/v1/factories/{factory['id']}",
        headers=_csrf(client),
        json={"description": "Updated facility description"},
    )
    assert updated.status_code == 200
    assert updated.json()["description"] == "Updated facility description"
    line_update = client.patch(
        f"/api/v1/lines/{hierarchy['line']['id']}",
        headers=_csrf(client),
        json={"name": "Updated line"},
    )
    assert line_update.status_code == 200
    machine_update = client.patch(
        f"/api/v1/machines/{hierarchy['machine']['id']}",
        headers=_csrf(client),
        json={"operating_state": "maintenance"},
    )
    assert machine_update.status_code == 200
    sensor_update = client.patch(
        f"/api/v1/sensors/{hierarchy['sensor']['id']}",
        headers=_csrf(client),
        json={"expected_reporting_interval_seconds": 5},
    )
    assert sensor_update.status_code == 200

    assert database.asset_audit_logs.count_documents(
        {"organization_id": database.organizations.find_one({})["_id"]}
    ) >= 9

    client.post("/api/v1/auth/logout", headers=_csrf(client))
    assert client.get("/api/v1/factories").status_code == 401
    signed_in = client.post(
        "/api/v1/auth/login",
        headers=_csrf(client),
        json={
            "email": "registry@example.com",
            "password": "correct horse battery",
        },
    )
    assert signed_in.status_code == 200
    reopened_session = client.get(f"/api/v1/factories/{factory['id']}")
    assert reopened_session.status_code == 200
    assert reopened_session.json()["description"] == "Updated facility description"
    assert client.get(
        f"/api/v1/components/{hierarchy['component']['id']}/sensors"
    ).json()["sensors"][0]["id"] == hierarchy["sensor"]["id"]


def test_archive_reopen_cascades_and_is_audited(asset_environment) -> None:
    database = asset_environment
    client = TestClient(app)
    _register(client, "archive@example.com")
    hierarchy = _create_complete_hierarchy(client)
    factory_id = hierarchy["factory"]["id"]
    organization_id = database.factories.find_one({})["organization_id"]

    archived = client.delete(
        f"/api/v1/factories/{factory_id}",
        headers=_csrf(client),
    )
    assert archived.status_code == 200
    assert client.get("/api/v1/factories").json()["factories"] == []
    assert client.get(
        f"/api/v1/factories/{factory_id}?include_archived=true"
    ).status_code == 200
    reopened_child = client.post(
        f"/api/v1/lines/{hierarchy['line']['id']}/reopen",
        headers=_csrf(client),
    )
    assert reopened_child.status_code == 409
    line = database.production_lines.find_one(
        {"factory_id": database.factories.find_one({})["_id"]}
    )
    assert line["archived_at"] is not None
    for collection in ("production_lines", "machines", "components", "sensors"):
        assert database[collection].count_documents(
            {"organization_id": organization_id, "archived_at": {"$ne": None}}
        ) == 1

    reopened = client.post(
        f"/api/v1/factories/{factory_id}/reopen",
        headers=_csrf(client),
    )
    assert reopened.status_code == 200
    assert client.get("/api/v1/factories").json()["factories"][0]["id"] == factory_id
    assert client.get(
        f"/api/v1/components/{hierarchy['component']['id']}/sensors"
    ).json()["sensors"][0]["id"] == hierarchy["sensor"]["id"]
    assert database.asset_audit_logs.count_documents(
        {"action": "archived", "organization_id": organization_id}
    ) == 5
    assert database.asset_audit_logs.count_documents(
        {"action": "reopened", "organization_id": organization_id}
    ) == 5


def test_update_does_not_overwrite_asset_archived_during_update(
    asset_environment,
    monkeypatch,
) -> None:
    database = asset_environment
    client = TestClient(app)
    _register(client, "archive-race@example.com")
    hierarchy = _create_complete_hierarchy(client)
    machine_id = database.machines.find_one({})["_id"]
    original_update = database.machines.update_one
    archive_time = datetime.now(UTC)

    def archive_before_update(query, update, **options):
        if query.get("_id") == machine_id and query.get("archived_at") is None:
            original_update(
                {"_id": machine_id},
                {"$set": {"archived_at": archive_time}},
            )
        return original_update(query, update, **options)

    monkeypatch.setattr(database.machines, "update_one", archive_before_update)
    response = client.patch(
        f"/api/v1/machines/{hierarchy['machine']['id']}",
        headers=_csrf(client),
        json={"operating_state": "maintenance"},
    )
    assert response.status_code == 404
    machine = database.machines.find_one({"_id": machine_id})
    assert machine["archived_at"] is not None
    assert machine["operating_state"] == "offline"
    assert database.asset_audit_logs.count_documents(
        {"entity_id": machine_id, "action": "updated"}
    ) == 0


def test_units_parent_ownership_shifts_and_template_metadata_are_validated(
    asset_environment,
) -> None:
    _database = asset_environment
    client = TestClient(app)
    _register(client, "first@example.com")
    hierarchy = _create_complete_hierarchy(client)

    invalid_unit = client.post(
        f"/api/v1/components/{hierarchy['component']['id']}/sensors",
        headers=_csrf(client),
        json={
            "identity": "BAD-UNIT",
            "name": "Invalid sensor",
            "measurement_type": "temperature",
            "unit": "psi",
            "expected_reporting_interval_seconds": 5,
        },
    )
    assert invalid_unit.status_code == 422

    missing_parent = client.post(
        f"/api/v1/factories/000000000000000000000000/lines",
        headers=_csrf(client),
        json={"name": "Invalid line"},
    )
    assert missing_parent.status_code == 404

    invalid_shift = client.post(
        "/api/v1/factories",
        headers=_csrf(client),
        json={
            "name": "Invalid calendar",
            "timezone": "Not/A_Timezone",
            "operating_calendar": {
                "shifts": [
                    {"day": 1, "name": "A", "start": "08:00", "end": "12:00"},
                    {"day": 1, "name": "B", "start": "11:00", "end": "14:00"},
                ]
            },
        },
    )
    assert invalid_shift.status_code == 422

    templates = client.get("/api/v1/asset-templates")
    assert templates.status_code == 200
    assert len(templates.json()["templates"]) == 8
    assert templates.json()["custom_type_available"] is True
    assert all(
        template["model_validation_status"] == "not_validated"
        and template["physics_model"] is None
        for template in templates.json()["templates"]
    )


def test_cross_organization_parent_and_asset_ids_are_hidden(asset_environment) -> None:
    _database = asset_environment
    first_client = TestClient(app)
    _register(first_client, "first-org@example.com")
    hierarchy = _create_complete_hierarchy(first_client)

    second_client = TestClient(app)
    _register(second_client, "second-org@example.com")
    guessed_factory = second_client.get(f"/api/v1/factories/{hierarchy['factory']['id']}")
    guessed_machine = second_client.get(f"/api/v1/machines/{hierarchy['machine']['id']}")
    foreign_parent = second_client.post(
        f"/api/v1/factories/{hierarchy['factory']['id']}/lines",
        headers=_csrf(second_client),
        json={"name": "Cross-org line"},
    )
    assert guessed_factory.status_code == guessed_machine.status_code == 404
    assert foreign_parent.status_code == 404


def test_templates_states_and_unit_catalog_are_public_and_explicit(asset_environment) -> None:
    _database = asset_environment
    client = TestClient(app)

    templates = client.get("/api/v1/asset-templates").json()["templates"]
    assert {template["key"] for template in templates} == {
        "conveyor",
        "processing_station",
        "cnc_cutting",
        "drilling",
        "assembly",
        "inspection",
        "packaging",
        "buffer_storage",
    }
    states = client.get("/api/v1/machine-states").json()
    assert set(states) == {
        "running",
        "idle",
        "starved",
        "blocked",
        "faulted",
        "maintenance",
        "offline",
    }
    assert "°C" in client.get("/api/v1/sensor-units").json()["temperature"]
