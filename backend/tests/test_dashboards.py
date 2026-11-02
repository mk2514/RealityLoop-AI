from datetime import UTC, datetime, timedelta

import pytest

from app.api.routes.dashboards import _convert_for_display, aggregate_samples
from app.telemetry.readings import parse_event_time


def test_hand_calculated_aggregation_keeps_empty_buckets_as_null() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    samples = [
        (start, 10.0),
        (start + timedelta(seconds=1), 20.0),
        (start + timedelta(seconds=3), 30.0),
    ]
    buckets = aggregate_samples(samples, start, 1)

    assert buckets[0]["min"] == 10.0
    assert buckets[0]["max"] == 10.0
    assert buckets[0]["avg"] == 10.0
    assert buckets[0]["count"] == 1
    assert buckets[1]["min"] == 20.0
    assert buckets[1]["max"] == 20.0
    assert buckets[1]["avg"] == 20.0
    assert buckets[2]["min"] is None
    assert buckets[2]["max"] is None
    assert buckets[2]["avg"] is None
    assert buckets[2]["count"] == 0
    assert buckets[3]["last"] == 30.0


def test_unit_conversion_and_timezone_conversion() -> None:
    assert _convert_for_display(100.0, "temperature", "°C", "°F") == pytest.approx(212.0)
    assert _convert_for_display(1000.0, "pressure", "Pa", "kPa") == pytest.approx(1.0)
    assert parse_event_time("2026-03-08T07:30:00+00:00", "UTC").isoformat() == "2026-03-08T07:30:00+00:00"
    assert parse_event_time("2026-03-08T01:30:00-06:00", "America/Chicago").isoformat() == "2026-03-08T07:30:00+00:00"


def test_ambiguous_dst_is_rejected_actionably() -> None:
    with pytest.raises(ValueError, match="AMBIGUOUS_LOCAL_TIME"):
        parse_event_time("2026-11-01T01:30:00", "America/Chicago")
