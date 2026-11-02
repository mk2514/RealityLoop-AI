"""Versioned contracts and deterministic normalization for measured sensor data."""

import hashlib
import json
import math
from datetime import UTC, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator


ReadingSource = Literal["csv_import", "rest", "mqtt", "opcua"]
Quality = Literal["good", "uncertain", "bad"]


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class NormalizedReadingV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    organization_id: str
    sensor_id: str
    machine_id: str
    quantity: str
    unit: str
    value: float
    event_time_utc: datetime
    received_at_utc: datetime
    source: ReadingSource
    source_ref: str
    quality: Quality | None = None
    event_key: str = Field(pattern=r"^[a-f0-9]{64}$")

    @field_validator("value")
    @classmethod
    def finite_value(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("Reading value must be finite.")
        return value

    @field_validator("event_time_utc", "received_at_utc")
    @classmethod
    def aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Reading timestamps must be timezone-aware.")
        return as_utc(value)


# (measurement type, source unit): (quantity, canonical unit, multiplier, offset)
UNIT_CONVERSIONS: dict[tuple[str, str], tuple[str, str, float, float]] = {
    ("temperature", "C"): ("temperature", "°C", 1, 0),
    ("temperature", "°C"): ("temperature", "°C", 1, 0),
    ("temperature", "F"): ("temperature", "°C", 5 / 9, -32 * 5 / 9),
    ("temperature", "°F"): ("temperature", "°C", 5 / 9, -32 * 5 / 9),
    ("temperature", "K"): ("temperature", "°C", 1, -273.15),
    ("pressure", "Pa"): ("pressure", "Pa", 1, 0),
    ("pressure", "kPa"): ("pressure", "Pa", 1000, 0),
    ("pressure", "MPa"): ("pressure", "Pa", 1_000_000, 0),
    ("pressure", "bar"): ("pressure", "Pa", 100_000, 0),
    ("pressure", "psi"): ("pressure", "Pa", 6894.757293168, 0),
    ("vibration", "mm/s"): ("vibration_velocity", "mm/s", 1, 0),
    ("vibration", "m/s²"): ("vibration_acceleration", "m/s²", 1, 0),
    ("vibration", "g"): ("vibration_acceleration", "m/s²", 9.80665, 0),
    ("speed", "rpm"): ("rotational_speed", "rpm", 1, 0),
    ("speed", "m/s"): ("linear_speed", "m/s", 1, 0),
    ("speed", "ft/min"): ("linear_speed", "m/s", 0.00508, 0),
    ("current", "A"): ("current", "A", 1, 0),
    ("current", "mA"): ("current", "A", 0.001, 0),
    ("voltage", "V"): ("voltage", "V", 1, 0),
    ("voltage", "mV"): ("voltage", "V", 0.001, 0),
    ("voltage", "kV"): ("voltage", "V", 1000, 0),
    ("power", "W"): ("power", "W", 1, 0),
    ("power", "kW"): ("power", "W", 1000, 0),
    ("power", "MW"): ("power", "W", 1_000_000, 0),
    ("flow", "L/min"): ("volumetric_flow", "L/min", 1, 0),
    ("flow", "m³/h"): ("volumetric_flow", "L/min", 1000 / 60, 0),
    ("flow", "gal/min"): ("volumetric_flow", "L/min", 3.785411784, 0),
    ("level", "%"): ("level_percent", "%", 1, 0),
    ("level", "mm"): ("level_length", "m", 0.001, 0),
    ("level", "cm"): ("level_length", "m", 0.01, 0),
    ("level", "m"): ("level_length", "m", 1, 0),
    ("proximity", "bool"): ("proximity", "bool", 1, 0),
    ("proximity", "mm"): ("proximity_distance", "m", 0.001, 0),
    ("proximity", "cm"): ("proximity_distance", "m", 0.01, 0),
    ("proximity", "in"): ("proximity_distance", "m", 0.0254, 0),
    ("position", "mm"): ("position", "m", 0.001, 0),
    ("position", "cm"): ("position", "m", 0.01, 0),
    ("position", "m"): ("position", "m", 1, 0),
    ("position", "in"): ("position", "m", 0.0254, 0),
    ("position", "ft"): ("position", "m", 0.3048, 0),
    ("force", "N"): ("force", "N", 1, 0),
    ("force", "kN"): ("force", "N", 1000, 0),
    ("force", "lbf"): ("force", "N", 4.4482216152605, 0),
    ("humidity", "%"): ("relative_humidity", "%", 1, 0),
    ("humidity", "g/m³"): ("absolute_humidity", "g/m³", 1, 0),
    ("count", "count"): ("count", "count", 1, 0),
    ("count", "units/min"): ("count_rate", "units/min", 1, 0),
    ("count", "units/h"): ("count_rate", "units/min", 1 / 60, 0),
}


def canonicalize_value(
    measurement_type: str,
    source_unit: str,
    value: float,
    *,
    registered_unit: str,
    calibration_scale: float | None = None,
    calibration_offset: float | None = None,
) -> tuple[str, str, float]:
    if not math.isfinite(value):
        raise ValueError("NON_FINITE_VALUE: Reading value must be finite.")
    if measurement_type == "custom":
        if source_unit != registered_unit:
            raise ValueError(
                f"INCOMPATIBLE_UNIT: Custom unit {source_unit!r} must exactly match registered unit {registered_unit!r}."
            )
        calibrated = value
        if calibration_scale is not None:
            calibrated *= calibration_scale
        if calibration_offset is not None:
            calibrated += calibration_offset
        if not math.isfinite(calibrated):
            raise ValueError("NON_FINITE_VALUE: Normalized value must be finite.")
        return f"custom:{registered_unit}", registered_unit, calibrated

    source = UNIT_CONVERSIONS.get((measurement_type, source_unit))
    registered = UNIT_CONVERSIONS.get((measurement_type, registered_unit))
    if source is None or registered is None or source[0] != registered[0]:
        raise ValueError(
            f"INCOMPATIBLE_UNIT: {source_unit!r} is not compatible with registered unit {registered_unit!r} for {measurement_type}."
        )
    canonical = value * source[2] + source[3]
    registered_value = (canonical - registered[3]) / registered[2]
    if calibration_scale is not None:
        registered_value *= calibration_scale
    if calibration_offset is not None:
        registered_value += calibration_offset
    canonical = registered_value * registered[2] + registered[3]
    if not math.isfinite(canonical):
        raise ValueError("NON_FINITE_VALUE: Normalized value must be finite.")
    return source[0], source[1], canonical


def parse_event_time(raw: str, timezone_name: str | None) -> datetime:
    normalized = raw.strip()
    if not normalized:
        raise ValueError("BAD_TIMESTAMP: Timestamp is blank.")
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("BAD_TIMESTAMP: Use an ISO-8601 timestamp.") from error
    if parsed.tzinfo is not None and parsed.utcoffset() is not None:
        return parsed.astimezone(UTC)
    if not timezone_name or timezone_name == "UTC":
        if timezone_name == "UTC":
            return parsed.replace(tzinfo=UTC)
        raise ValueError(
            "BAD_TIMESTAMP: Provide an IANA timezone for timestamps without an offset."
        )
    try:
        zone = ZoneInfo(timezone_name)
    except (ValueError, KeyError) as error:
        raise ValueError(
            "BAD_TIMESTAMP: Choose a valid IANA timezone."
        ) from error

    candidates: list[datetime] = []
    for fold in (0, 1):
        candidate = parsed.replace(tzinfo=zone, fold=fold)
        round_trip = candidate.astimezone(UTC).astimezone(zone).replace(tzinfo=None)
        if round_trip == parsed:
            candidates.append(candidate)
    distinct_offsets = {candidate.utcoffset() for candidate in candidates}
    if not candidates:
        raise ValueError(
            "NONEXISTENT_LOCAL_TIME: This local time does not exist because of a daylight-saving transition."
        )
    if len(distinct_offsets) > 1:
        raise ValueError(
            "AMBIGUOUS_LOCAL_TIME: This local time occurs twice; provide an explicit UTC offset."
        )
    return candidates[0].astimezone(UTC)


def make_event_key(
    organization_id: str,
    sensor_id: str,
    quantity: str,
    event_time_utc: datetime,
    source_event_id: str | None = None,
    sequence: int | None = None,
) -> str:
    event_time = event_time_utc.astimezone(UTC).isoformat(timespec="microseconds")
    identity = {
        "organization_id": organization_id,
        "sensor_id": sensor_id,
        "quantity": quantity,
        "event_time_utc": event_time,
        "source_event_id": source_event_id,
        "sequence": sequence,
    }
    return hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
