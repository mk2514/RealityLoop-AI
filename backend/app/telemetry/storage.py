from botocore.client import BaseClient
from boto3 import client as boto3_client

from app.core.config import get_settings


class PrivateStorageUnavailable(RuntimeError):
    pass


def get_storage_client() -> tuple[BaseClient, str]:
    settings = get_settings()
    if not settings.s3_bucket:
        raise PrivateStorageUnavailable(
            "Private object storage is not configured. Set S3_BUCKET and its credentials."
        )
    client = boto3_client(
        "s3",
        endpoint_url=settings.s3_endpoint_url or None,
        region_name=settings.s3_region,
        aws_access_key_id=settings.s3_access_key_id or None,
        aws_secret_access_key=settings.s3_secret_access_key or None,
    )
    return client, settings.s3_bucket
