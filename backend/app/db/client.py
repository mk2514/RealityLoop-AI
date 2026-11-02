from functools import lru_cache

from pymongo import MongoClient
from pymongo.database import Database
from redis import Redis

from app.core.config import get_settings


@lru_cache
def get_mongo_client() -> MongoClient:
    settings = get_settings()
    return MongoClient(
        host=settings.mongo_host,
        port=settings.mongo_port,
        username=settings.mongo_username,
        password=settings.mongo_password,
        authSource=settings.mongo_auth_source or settings.mongo_database,
        serverSelectionTimeoutMS=1000,
        connectTimeoutMS=1000,
        appname=settings.app_name,
    )


def get_database() -> Database:
    return get_mongo_client()[get_settings().mongo_database]


@lru_cache
def get_redis_client() -> Redis:
    return Redis.from_url(
        get_settings().redis_url,
        socket_connect_timeout=2,
        socket_timeout=2,
        decode_responses=True,
    )


def close_mongo_client() -> None:
    client = get_mongo_client()
    client.close()
    get_mongo_client.cache_clear()
    get_redis_client().close()
    get_redis_client.cache_clear()
