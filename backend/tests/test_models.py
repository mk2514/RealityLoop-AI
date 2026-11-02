import mongomock
import pytest
from pymongo.errors import DuplicateKeyError

from app.db.migrations.versions import v0001_identity_foundation as initial_migration
from app.models import MembershipDocument, OrganizationDocument, UserDocument


def test_organization_user_membership_documents_persist_and_read_back() -> None:
    database = mongomock.MongoClient().get_database("realityloop")
    organization = OrganizationDocument(name="Example Factory", slug="example")
    user = UserDocument(email="operator@example.test", full_name="Factory Operator")
    membership = MembershipDocument(
        organization_id=organization.id,
        user_id=user.id,
        role="owner",
    )
    initial_migration.create_indexes(database)

    database.organizations.insert_one(organization.model_dump(by_alias=True))
    database.users.insert_one(user.model_dump(by_alias=True))
    database.organization_memberships.insert_one(membership.model_dump(by_alias=True))

    stored_membership = database.organization_memberships.find_one(
        {"organization_id": organization.id, "user_id": user.id}
    )
    stored_organization = database.organizations.find_one({"_id": organization.id})
    stored_user = database.users.find_one({"_id": user.id})

    assert stored_membership is not None
    assert stored_membership["role"] == "owner"
    assert stored_organization["name"] == "Example Factory"
    assert stored_user["email"] == "operator@example.test"


def test_unique_indexes_reject_duplicate_slugs_emails_and_memberships() -> None:
    database = mongomock.MongoClient().get_database("realityloop")
    initial_migration.create_indexes(database)
    organization = OrganizationDocument(name="Example Factory", slug="example")
    user = UserDocument(email="operator@example.test", full_name="Factory Operator")
    membership = MembershipDocument(
        organization_id=organization.id,
        user_id=user.id,
        role="owner",
    )
    database.organizations.insert_one(organization.model_dump(by_alias=True))
    database.users.insert_one(user.model_dump(by_alias=True))
    database.organization_memberships.insert_one(membership.model_dump(by_alias=True))

    with pytest.raises(DuplicateKeyError):
        database.organizations.insert_one(
            OrganizationDocument(name="Another Factory", slug="example").model_dump(
                by_alias=True
            )
        )
    with pytest.raises(DuplicateKeyError):
        database.users.insert_one(
            UserDocument(email="operator@example.test", full_name="Another User").model_dump(
                by_alias=True
            )
        )
    with pytest.raises(DuplicateKeyError):
        database.organization_memberships.insert_one(
            MembershipDocument(
                organization_id=organization.id,
                user_id=user.id,
                role="admin",
            ).model_dump(by_alias=True)
        )
