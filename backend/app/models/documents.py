from datetime import UTC, datetime
from typing import Literal

from bson import ObjectId
from pydantic import BaseModel, ConfigDict, Field


class MongoDocument(BaseModel):
    id: ObjectId = Field(default_factory=ObjectId, alias="_id")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    model_config = ConfigDict(arbitrary_types_allowed=True, populate_by_name=True)


class OrganizationDocument(MongoDocument):
    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", min_length=1, max_length=80)


class UserDocument(MongoDocument):
    email: str = Field(min_length=3, max_length=320)
    full_name: str = Field(min_length=1, max_length=200)
    email_verified_at: datetime | None = None


class MembershipDocument(MongoDocument):
    organization_id: ObjectId
    user_id: ObjectId
    role: Literal["owner", "admin", "member", "viewer"]
