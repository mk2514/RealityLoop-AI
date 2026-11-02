from typing import Any

from pymongo import UpdateOne


def bulk_upsert_readings(
    database,
    readings: list[dict[str, Any]],
    *,
    session=None,
) -> dict[str, str]:
    unique: dict[str, dict[str, Any]] = {}
    for reading in readings:
        unique.setdefault(reading["event_key"], reading)
    if not unique:
        return {}

    keys = list(unique)
    existing = {
        record["event_key"]
        for record in database.sensor_readings.find(
            {
                "organization_id": unique[keys[0]]["organization_id"],
                "event_key": {"$in": keys},
            },
            {"event_key": 1},
            session=session,
        )
    }
    new_readings = [
        reading for key, reading in unique.items() if key not in existing
    ]
    operations = [
        UpdateOne(
            {
                "organization_id": reading["organization_id"],
                "event_key": reading["event_key"],
            },
            {"$setOnInsert": reading},
            upsert=True,
        )
        for reading in new_readings
    ]
    result = (
        database.sensor_readings.bulk_write(
            operations, ordered=False, session=session
        )
        if operations
        else None
    )
    inserted_indexes = result.upserted_ids if result is not None else {}
    statuses = {
        key: "duplicate" if key in existing else "pending"
        for key in unique
    }
    for index, reading in enumerate(new_readings):
        statuses[reading["event_key"]] = (
            "inserted" if index in inserted_indexes else "duplicate"
        )
    return statuses
