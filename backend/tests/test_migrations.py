from app.db.migrations.runner import migrate
from app.db.migrations.versions import v0001_identity_foundation as initial_migration


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

    assert migrate(database) == ["0001_identity_foundation"]
    assert migrate(database) == []
    assert {"organizations", "users", "organization_memberships", "schema_migrations"} <= set(
        database.list_collection_names()
    )
    assert len(database["schema_migrations"].documents) == 1
    assert database.organizations.options["validator"] == initial_migration.COLLECTIONS[
        "organizations"
    ]
    assert any(index[1].get("unique") for index in database.organization_memberships.indexes)
