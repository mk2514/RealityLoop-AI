from urllib.parse import parse_qs, urlparse

import mongomock
import pytest
from fastapi.testclient import TestClient

from app.api.routes import assets, auth, line_models
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
def line_model_environment(monkeypatch):
    emails: list[str] = []
    database = mongomock.MongoClient().get_database("realityloop")
    database.organizations.create_index("slug", unique=True)
    database.users.create_index("email", unique=True)
    database.organization_memberships.create_index(
        [("organization_id", 1), ("user_id", 1)],
        unique=True,
    )
    database.production_lines.create_index(
        [("organization_id", 1), ("factory_id", 1), ("_id", 1)]
    )
    database.machines.create_index(
        [("organization_id", 1), ("identity", 1)],
        unique=True,
    )
    database.production_line_models.create_index(
        [("organization_id", 1), ("line_id", 1)],
        unique=True,
    )
    database.production_line_versions.create_index(
        [("organization_id", 1), ("line_id", 1), ("version", 1)],
        unique=True,
    )
    monkeypatch.setattr(auth, "get_database", lambda: database)
    monkeypatch.setattr(auth, "get_mongo_client", TransactionClient)
    monkeypatch.setattr(assets, "get_database", lambda: database)
    monkeypatch.setattr(assets, "get_mongo_client", TransactionClient)
    monkeypatch.setattr(line_models, "get_database", lambda: database)
    monkeypatch.setattr(line_models, "get_mongo_client", TransactionClient)
    monkeypatch.setattr(auth, "_rate_limit", lambda *_args: None)
    monkeypatch.setattr(
        auth,
        "send_email",
        lambda email, _subject, body: emails.append(
            parse_qs(urlparse(body.splitlines()[2]).query)["token"][0]
        ),
    )
    monkeypatch.setattr(auth, "get_settings", lambda: Settings(_env_file=None))
    return database, emails


def _csrf(client: TestClient) -> dict[str, str]:
    token = client.get("/api/v1/csrf").json()["csrf_token"]
    return {"X-CSRF-Token": token}


def _register(client: TestClient, email: str, emails: list[str]) -> None:
    response = client.post(
        "/api/v1/auth/register",
        headers=_csrf(client),
        json={
            "full_name": "Line Engineer",
            "email": email,
            "password": "correct horse battery",
            "organization_name": f"{email} organization",
        },
    )
    assert response.status_code == 202
    user = auth.get_database().users.find_one({"email": email})
    token_record = auth.get_database().auth_tokens.find_one({"user_id": user["_id"]})
    from app.core.security import hash_token

    token = next(token for token in emails if hash_token(token) == token_record["_id"])
    verified = client.post(
        "/api/v1/auth/verify",
        headers=_csrf(client),
        json={"token": token},
    )
    assert verified.status_code == 200
    login = client.post(
        "/api/v1/auth/login",
        headers=_csrf(client),
        json={"email": email, "password": "correct horse battery"},
    )
    assert login.status_code == 200


def _create_line(client: TestClient) -> tuple[dict, list[dict]]:
    factory = client.post(
        "/api/v1/factories",
        headers=_csrf(client),
        json={"name": "North Plant"},
    )
    assert factory.status_code == 201
    line = client.post(
        f"/api/v1/factories/{factory.json()['id']}/lines",
        headers=_csrf(client),
        json={"name": "Line 1"},
    )
    assert line.status_code == 201
    line_id = line.json()["id"]
    machines = []
    for identity, capability in (
        ("CUT-01", "cut_material"),
        ("CUT-02", "cut_material"),
        ("DRILL-01", "drill_material"),
    ):
        response = client.post(
            f"/api/v1/lines/{line_id}/machines",
            headers=_csrf(client),
            json={
                "identity": identity,
                "name": identity,
                "machine_type": "processing_station",
                "capabilities": [capability],
                "nominal_cycle_time_seconds": 54,
                "capacity_per_hour": 60,
                "operating_state": "offline",
            },
        )
        assert response.status_code == 201, response.text
        machines.append(response.json())
    return line.json(), machines


def _branching_model(machines: list[dict]) -> dict:
    nodes = [
        {"id": "source", "type": "source", "label": "Raw stock", "position": {"x": 0, "y": 0}},
        {
            "id": "cut-a",
            "type": "machine",
            "machine_id": machines[0]["id"],
            "label": "Cut A",
            "position": {"x": 100, "y": -60},
        },
        {
            "id": "cut-b",
            "type": "machine",
            "machine_id": machines[1]["id"],
            "label": "Cut B",
            "position": {"x": 100, "y": 60},
        },
        {
            "id": "buffer",
            "type": "buffer",
            "label": "WIP buffer",
            "buffer_capacity": 12,
            "position": {"x": 200, "y": -60},
        },
        {"id": "sink", "type": "sink", "label": "Finished goods", "position": {"x": 300, "y": 0}},
    ]
    edges = [
        {"id": "e1", "source": "source", "target": "cut-a", "source_handle": "out", "target_handle": "in"},
        {"id": "e2", "source": "source", "target": "cut-b", "source_handle": "out", "target_handle": "in"},
        {"id": "e3", "source": "cut-a", "target": "buffer", "source_handle": "out", "target_handle": "in"},
        {"id": "e4", "source": "buffer", "target": "sink", "source_handle": "out", "target_handle": "in"},
        {
            "id": "e5",
            "source": "cut-b",
            "target": "sink",
            "source_handle": "out",
            "target_handle": "in",
            "transfer_time_seconds": 9,
        },
    ]
    return {
        "schema_version": 1,
        "layout": {
            "nodes": nodes,
            "edges": edges,
            "transfer_settings": {
                "use_layout_distance": True,
                "pixels_per_meter": 100,
                "default_speed_meters_per_second": 2,
            },
        },
        "products": [{"id": "product-1", "name": "Housing", "sku": "H-100"}],
        "recipes": [
            {
                "id": "recipe-1",
                "product_id": "product-1",
                "steps": [
                    {
                        "id": "step-1",
                        "operation": "cut_material",
                        "machine_node_ids": ["cut-a", "cut-b"],
                        "cycle_time_seconds": 45,
                        "setup_time_seconds": 10,
                        "changeover_time_seconds": 20,
                        "batch_size": 5,
                        "operator_count": 1,
                        "resources": [{"name": "fixture", "quantity": 1}],
                    }
                ],
            }
        ],
    }


def test_branching_model_saves_reloads_snapshots_and_rejects_stale_revision(
    line_model_environment,
) -> None:
    database, emails = line_model_environment
    client = TestClient(app)
    _register(client, "line-owner@example.com", emails)
    line, machines = _create_line(client)
    model = _branching_model(machines)

    initial = client.get(f"/api/v1/lines/{line['id']}/model")
    assert initial.status_code == 200
    assert initial.json()["revision"] == 0

    saved = client.put(
        f"/api/v1/lines/{line['id']}/model",
        headers=_csrf(client),
        json={"expected_revision": 0, "model": model},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["revision"] == 1
    assert saved.json()["validation"]["valid"] is True
    assert {
        transfer["method"] for transfer in saved.json()["validation"]["transfer_times"]
    } == {"derived_from_layout", "configured_time"}

    reloaded = client.get(f"/api/v1/lines/{line['id']}/model")
    assert reloaded.json()["revision"] == 1
    assert reloaded.json()["model"] == saved.json()["model"]
    versions = client.get(f"/api/v1/lines/{line['id']}/versions")
    assert [version["version"] for version in versions.json()["versions"]] == [1]
    original_snapshot = client.get(f"/api/v1/lines/{line['id']}/versions/1")
    assert original_snapshot.json()["model"] == saved.json()["model"]

    changed = {**model, "layout": {**model["layout"], "nodes": model["layout"]["nodes"][:-1]}}
    conflict = client.put(
        f"/api/v1/lines/{line['id']}/model",
        headers=_csrf(client),
        json={"expected_revision": 0, "model": changed},
    )
    assert conflict.status_code == 409
    assert database.production_line_versions.count_documents(
        {"line_id": database.production_lines.find_one({})["_id"]}
    ) == 1


def test_model_validation_reports_ports_capacity_routes_and_missing_steps(
    line_model_environment,
) -> None:
    _database, emails = line_model_environment
    client = TestClient(app)
    _register(client, "line-validation@example.com", emails)
    line, machines = _create_line(client)
    model = _branching_model(machines)
    model["layout"]["nodes"][3]["buffer_capacity"] = 0
    model["layout"]["edges"][0]["target_handle"] = "output"
    model["layout"]["edges"].append(
        {
            "id": "cycle",
            "source": "buffer",
            "target": "cut-a",
            "source_handle": "out",
            "target_handle": "in",
        }
    )
    model["recipes"][0]["steps"] = []

    response = client.post(
        f"/api/v1/lines/{line['id']}/validate",
        headers=_csrf(client),
        json=model,
    )
    assert response.status_code == 200
    assert response.json()["valid"] is False
    codes = {error["code"] for error in response.json()["errors"]}
    assert {
        "invalid_buffer_capacity",
        "invalid_input_port",
        "unbounded_loop",
        "missing_process_steps",
    } <= codes
    assert all(error["action"] for error in response.json()["errors"])


def test_invalid_transfer_assumptions_return_actionable_errors_without_crashing(
    line_model_environment,
) -> None:
    _database, emails = line_model_environment
    client = TestClient(app)
    _register(client, "line-transfer-validation@example.com", emails)
    line, machines = _create_line(client)
    model = _branching_model(machines)
    model["layout"]["transfer_settings"]["pixels_per_meter"] = 0
    model["layout"]["edges"][0]["distance_meters"] = 12
    model["layout"]["edges"][0]["speed_meters_per_second"] = 0

    response = client.post(
        f"/api/v1/lines/{line['id']}/validate",
        headers=_csrf(client),
        json=model,
    )

    assert response.status_code == 200
    result = response.json()
    assert result["valid"] is False
    assert {
        "invalid_transfer_setting",
        "invalid_transfer_speed",
    } <= {error["code"] for error in result["errors"]}
    assert result["transfer_times"][0] == {
        "edge_id": "e1",
        "seconds": None,
        "method": "invalid_distance_and_speed",
    }


def test_explicit_rework_rule_bounds_loop_and_machine_capability_is_checked(
    line_model_environment,
) -> None:
    _database, emails = line_model_environment
    client = TestClient(app)
    _register(client, "line-rework@example.com", emails)
    line, machines = _create_line(client)
    model = _branching_model(machines)
    model["layout"]["edges"].append(
        {
            "id": "rework",
            "source": "buffer",
            "target": "cut-a",
            "source_handle": "out",
            "target_handle": "in",
            "route_kind": "rework",
            "rework_rule": {"condition": "inspection_failed", "max_revisits": 2},
        }
    )
    model["recipes"][0]["steps"][0]["machine_node_ids"].append("drill")
    model["layout"]["nodes"].append(
        {
            "id": "drill",
            "type": "machine",
            "machine_id": machines[2]["id"],
            "label": "Drill",
            "position": {"x": 120, "y": 140},
        }
    )

    response = client.post(
        f"/api/v1/lines/{line['id']}/validate",
        headers=_csrf(client),
        json=model,
    )
    codes = {error["code"] for error in response.json()["errors"]}
    assert "unbounded_loop" not in codes
    assert "incompatible_operation" in codes


def test_line_models_and_versions_are_organization_scoped(line_model_environment) -> None:
    _database, emails = line_model_environment
    first_client = TestClient(app)
    _register(first_client, "line-first@example.com", emails)
    line, machines = _create_line(first_client)
    saved = first_client.put(
        f"/api/v1/lines/{line['id']}/model",
        headers=_csrf(first_client),
        json={"expected_revision": 0, "model": _branching_model(machines)},
    )
    assert saved.status_code == 200

    second_client = TestClient(app)
    _register(second_client, "line-second@example.com", emails)
    assert second_client.get(f"/api/v1/lines/{line['id']}/model").status_code == 404
    assert second_client.get(f"/api/v1/lines/{line['id']}/versions/1").status_code == 404
