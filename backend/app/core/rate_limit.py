from datetime import UTC, datetime
from pymongo import ReturnDocument
from pymongo.errors import PyMongoError

import hashlib
import logging

from fastapi import HTTPException, Request
from redis import Redis
from redis.exceptions import RedisError

from app.core.config import get_settings
from app.db.client import get_database, get_redis_client

logger = logging.getLogger(__name__)

INCREMENT_WINDOW = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return count
"""


def rate_limit_key(action: str, identity: str, ip_address: str) -> str:
    digest = hashlib.sha256(f"{ip_address}:{identity}".encode("utf-8")).hexdigest()
    return f"auth-rate:{action}:{digest}"


def check_rate_limit(
    redis: Redis,
    *,
    action: str,
    identity: str,
    ip_address: str,
    limit: int,
    window_seconds: int | None = None,
) -> None:
    window = window_seconds or get_settings().auth_rate_limit_window_seconds
    try:
        count = int(redis.eval(INCREMENT_WINDOW, 1, rate_limit_key(action, identity, ip_address), window))
    except RedisError:
        logger.warning("Authentication rate limiter unavailable")
        raise HTTPException(status_code=503, detail="Authentication is temporarily unavailable.")
    if count > limit:
        raise HTTPException(
            status_code=429,
            detail="Too many attempts. Please wait before trying again.",
            headers={"Retry-After": str(window)},
        )


def check_request_limit(
    request: Request,
    *,
    action: str,
    identity: str,
    limit: int,
) -> None:
    settings = get_settings()
    if settings.mongo_only_infra:
        window = settings.auth_rate_limit_window_seconds
        bucket = int(datetime.now(UTC).timestamp()) // window
        ip = request.client.host if request.client else "unknown"
        key = rate_limit_key(action, identity, ip)
        expires = datetime.fromtimestamp((bucket + 1) * window, UTC)
        try:
            record = get_database().auth_rate_windows.find_one_and_update(
                {"_id": f"{key}:{bucket}"},
                {"$inc": {"count": 1}, "$setOnInsert": {"expires_at": expires}},
                upsert=True, return_document=ReturnDocument.AFTER,
            )
        except PyMongoError:
            raise HTTPException(status_code=503, detail="Authentication is temporarily unavailable.")
        if record["count"] > limit:
            raise HTTPException(status_code=429, detail="Too many attempts.", headers={"Retry-After": str(window)})
        return
    client = get_redis_client()
    check_rate_limit(
        client,
        action=action,
        identity=identity,
        ip_address=request.client.host if request.client else "unknown",
        limit=limit,
    )
