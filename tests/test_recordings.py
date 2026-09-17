"""Bucket timestamps and the defensive edges of recording parsing."""

from __future__ import annotations

from datetime import datetime

import pytest

from pyk40rf import RecordingResource, parse_resource


def recording(sample_rate: str, start: str | None, buckets: list[object]) -> RecordingResource:
    """Build a recording payload with the given series."""
    resource = parse_resource(
        {
            "id": "/recordings/x",
            "type": "yRecordingExtended",
            "unitOfMeasure": "C",
            "recordedResource": {"id": "/x"},
            "recordingType": "actual",
            "values": [
                {
                    "startTime": start,
                    "sampleRate": sample_rate,
                    "endTime": None,
                    "recording": buckets,
                }
            ],
        }
    )
    assert isinstance(resource, RecordingResource)
    return resource


BUCKETS: list[object] = [{"c": 60, "y": 600.0}, {"c": 60, "y": 660.0}, {"c": 60, "y": 720.0}]


@pytest.mark.parametrize(
    ("sample_rate", "expected"),
    [
        ("PT1H", datetime.fromisoformat("2026-01-01T02:00:00+01:00")),
        ("P1D", datetime.fromisoformat("2026-01-03T00:00:00+01:00")),
        ("P1M", datetime.fromisoformat("2026-03-01T00:00:00+01:00")),
    ],
)
def test_bucket_starts_follow_the_sample_rate(sample_rate: str, expected: datetime) -> None:
    result = recording(sample_rate, "2026-01-01T00:00:00+01:00", BUCKETS)
    assert result.series[0].buckets[2].start == expected


def test_month_steps_clamp_to_the_shortest_month() -> None:
    # 31 January plus one month has no 31st to land on.
    result = recording("P1M", "2026-01-31T00:00:00+01:00", BUCKETS[:2])
    assert result.series[0].buckets[1].start == datetime.fromisoformat("2026-02-28T00:00:00+01:00")


def test_month_steps_roll_over_the_year() -> None:
    result = recording("P1M", "2026-11-01T00:00:00+01:00", BUCKETS)
    assert result.series[0].buckets[2].start == datetime.fromisoformat("2027-01-01T00:00:00+01:00")


def test_the_all_sample_rate_has_no_bucket_starts() -> None:
    # "all" collapses the history; there is no period to step by.
    result = recording("all", "2026-01-01T00:00:00+01:00", BUCKETS)
    assert all(bucket.start is None for bucket in result.series[0].buckets)


@pytest.mark.parametrize("start", [None, "", "not-a-date"])
def test_an_unreadable_start_time_leaves_buckets_unstamped(start: str | None) -> None:
    result = recording("P1D", start, BUCKETS)
    assert result.series[0].start_time is None
    assert all(bucket.start is None for bucket in result.series[0].buckets)
    assert len(result.series[0].buckets) == 3


def test_malformed_buckets_are_skipped_not_fatal() -> None:
    result = recording("P1D", "2026-01-01T00:00:00+01:00", [{"c": 1, "y": 2.0}, "junk", None])
    assert len(result.series[0].buckets) == 1


def test_buckets_with_missing_fields_default_to_empty() -> None:
    result = recording("P1D", "2026-01-01T00:00:00+01:00", [{}])
    bucket = result.series[0].buckets[0]
    assert bucket.count == 0
    assert bucket.total == 0.0
    assert bucket.average is None


def test_a_recording_without_values_is_empty_not_broken() -> None:
    resource = parse_resource({"id": "/recordings/x", "type": "yRecordingExtended", "values": []})
    assert isinstance(resource, RecordingResource)
    assert resource.series == ()
    assert resource.unit is None
    assert resource.recorded_resource_id is None
