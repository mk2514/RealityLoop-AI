from app.db.migrations.runner import migrate
from app.db.migrations.versions import v0001_identity_foundation as initial_migration
from app.db.migrations.versions import v0002_authentication as authentication_migration
from app.db.migrations.versions import v0003_factory_assets as factory_assets_migration
from app.db.migrations.versions import v0004_production_line_models as line_models_migration


class MemoryCollection:
    def __init__(self) -> None:
        self.documents: list[dict] = []
        self.options: dict = {}
        self.indexes: list[tuple] = []

    def find_one(self, query: dict) -> dict | None:
        return next(
            (
                document
                for document in self.documents
                if all(document.get(key) == value for key, value in query.items())
            ),
            None,
        )

    def insert_one(self, document: dict) -> None:
        self.documents.append(document.copy())

    def create_index(self, keys, **options) -> None:
        self.indexes.append((keys, options))

    def update_many(self, query: dict, update: dict) -> None:
        for document in self.documents:
            if all(document.get(key) == value for key, value in query.items()):
                document.update(update.get("$set", {}))

    def update_one(self, query: dict, update: dict, **_kwargs) -> None:
        for document in self.documents:
            if all(document.get(key) == value for key, value in query.items()):
                document.update(update.get("$set", {}))
                return

    def find(self, query: dict) -> list[dict]:
        return [
            document
            for document in self.documents
            if all(
                document.get(key) == value
                for key, value in query.items()
                if not (isinstance(value, dict) and "$exists" in value)
            )
            and all(
                (key in document) == condition["$exists"]
                for key, condition in query.items()
                if isinstance(condition, dict) and "$exists" in condition
            )
        ]


class MemoryDatabase:
    def __init__(self) -> None:
        self.collections: dict[str, MemoryCollection] = {}

    def list_collection_names(self) -> list[str]:
        return list(self.collections)

    def create_collection(self, name: str, **options) -> MemoryCollection:
        collection = self.collections.setdefault(name, MemoryCollection())
        collection.options = options
        return collection

    def command(self, command: dict) -> None:
        self.collections[command["collMod"]].options.update(command)

    def __getitem__(self, name: str) -> MemoryCollection:
        return self.collections.setdefault(name, MemoryCollection())

    def __getattr__(self, name: str) -> MemoryCollection:
        if name.startswith("_"):
            raise AttributeError(name)
        return self[name]


def test_identity_migration_is_versioned_and_repeatable() -> None:
    database = MemoryDatabase()

    database.factories.insert_one(
        {
            "_id": "legacy-factory",
            "organization_id": "legacy-org",
            "name": "Legacy factory",
            "created_at": "created",
            "updated_at": "updated",
        }
    )
    assert migrate(database) == [
        "0001_identity_foundation",
        "0002_authentication",
        "0003_factory_assets",
        "0004_production_line_models",
        "0005_rate_windows",
    ]
    assert migrate(database) == []
    assert {"organizations", "users", "organization_memberships", "schema_migrations"} <= set(
        database.list_collection_names()
    )
    assert len(database["schema_migrations"].documents) == 5
    assert database.organizations.options["validator"] == initial_migration.COLLECTIONS[
        "organizations"
    ]
    assert any(index[1].get("unique") for index in database.organization_memberships.indexes)
    assert database.users.options["validator"] == authentication_migration.USER_VALIDATOR
    assert database.organization_memberships.options["validator"] == (
        authentication_migration.MEMBERSHIP_VALIDATOR
    )
    assert "auth_tokens" in database.list_collection_names()
    assert any(index[1].get("expireAfterSeconds") == 0 for index in database.sessions.indexes)
    assert database.factories.options["validator"] == (
        factory_assets_migration.ASSET_COLLECTIONS["factories"]
    )
    assert database.factories.documents[0]["timezone"] == "UTC"
    assert "sensors" in database.list_collection_names()
    assert "asset_audit_logs" in database.list_collection_names()
    assert database.production_line_models.options["validator"] == (
        line_models_migration.MODEL_VALIDATOR
    )
    assert database.production_line_versions.options["validator"] == (
        line_models_migration.VERSION_VALIDATOR
    )
    assert any(index[1].get("unique") for index in database.production_line_versions.indexes)
