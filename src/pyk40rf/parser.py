"""Turn gateway JSON into the dataclasses of :mod:`pyk40rf.models`.

Two notes on the ``state`` field, because it does not mean one thing:

* On the **static endpoints** it is a *list* of single-entry dicts naming the
  error sentinels a reading can take, e.g.
  ``[{"open": -32768.0}, {"short": 32767.0}]``. A reading equal to one of them
  is not a measurement and is surfaced as ``None``.
* On the **/signals branch** it is a *dict* mapping labels to values, e.g.
  ``{"HEATING": 1, "COOLING": 3, "IDLE": 2}``. That is an enumeration, not a
  list of faults. Nulling those readings would throw the actual information
  away, so they are decoded to their label instead. Only labels that name a
  fault (``NA_OPEN``, ``LOW_FLOW``, ``INVALID``, ...) null the value.

The shape is what decides, not the path, so a signal that ever ships the list
form -- or a static endpoint the dict form -- is still read correctly.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import math
from typing import Any

from .const import ERROR_STATE_LABELS
from .exceptions import K40ResponseError
from .models import (
    EnergyResource,
    JsonDict,
    NumericResource,
    RawResource,
    RecordingBucket,
    RecordingResource,
    RecordingSeries,
    ReferenceList,
    Resource,
    StringResource,
    SystemInfo,
    SystemInfoModule,
)

__all__ = ["is_error_label", "parse_resource", "parse_system_info"]

_NUMERIC_TYPES = frozenset({"floatValue", "integerValue"})
_FLOAT_TOLERANCE = 1e-9


def is_error_label(label: str) -> bool:
    """Whether a ``state`` label names a fault rather than an operating mode."""
    return label.strip().lower() in ERROR_STATE_LABELS


def _matches(value: Any, sentinel: Any) -> bool:
    """Compare a reading against a sentinel, tolerating float representation."""
    if isinstance(value, bool) or isinstance(sentinel, bool):
        return value is sentinel
    if isinstance(value, (int, float)) and isinstance(sentinel, (int, float)):
        return math.isclose(value, sentinel, rel_tol=0.0, abs_tol=_FLOAT_TOLERANCE)
    return bool(value == sentinel)


def _parse_sentinel_list(
    state: list[Any], value: float
) -> tuple[float | int | None, str | None, str | None]:
    """Read the static-endpoint form: a list of single-entry sentinel dicts."""
    for entry in state:
        if not isinstance(entry, dict):
            continue
        for label, sentinel in entry.items():
            if not _matches(value, sentinel):
                continue
            # Every label in this form marks a non-measurement, including the
            # rare non-fault ones such as "off" on a disabled setpoint.
            if is_error_label(label):
                return None, None, label
            return None, label, None
    return value, None, None


def _parse_enum_map(
    state: dict[str, Any], value: float
) -> tuple[float | int | None, str | None, str | None, tuple[str, ...]]:
    """Read the /signals form: a dict mapping labels to values."""
    faults = {k: v for k, v in state.items() if is_error_label(k)}
    modes = {k: v for k, v in state.items() if not is_error_label(k)}

    for label, sentinel in faults.items():
        if _matches(value, sentinel):
            return None, None, label, _sorted_labels(modes)

    matched: str | None = None
    for label, expected in modes.items():
        if _matches(value, expected):
            matched = label
            break

    return value, matched, None, _sorted_labels(modes)


def _sorted_labels(modes: dict[str, Any]) -> tuple[str, ...]:
    """Order labels by their numeric value, so options stay stable."""

    def key(item: tuple[str, Any]) -> tuple[int, float, str]:
        _, raw = item
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            return (0, float(raw), "")
        return (1, 0.0, str(raw))

    return tuple(label for label, _ in sorted(modes.items(), key=key))


def _parse_numeric(payload: JsonDict) -> NumericResource:
    raw_value = payload.get("value")
    if not isinstance(raw_value, (int, float)) or isinstance(raw_value, bool):
        raise K40ResponseError(
            f"{payload.get('id')!r}: {payload.get('type')!r} without a numeric value"
        )

    state = payload.get("state")
    value: float | int | None = raw_value
    label: str | None = None
    error_label: str | None = None
    options: tuple[str, ...] = ()

    if isinstance(state, list):
        value, label, error_label = _parse_sentinel_list(state, raw_value)
    elif isinstance(state, dict):
        value, label, error_label, options = _parse_enum_map(state, raw_value)

    unit = payload.get("unitOfMeasure") or payload.get("unit")
    return NumericResource(
        id=str(payload.get("id", "")),
        type=str(payload["type"]),
        raw=payload,
        value=value,
        raw_value=raw_value,
        unit=str(unit) if unit else None,
        label=label,
        error_label=error_label,
        options=options,
    )


def _parse_string(payload: JsonDict) -> StringResource:
    value = payload.get("value")
    allowed = payload.get("allowedValues")
    options = tuple(str(v) for v in allowed) if isinstance(allowed, list) else ()
    return StringResource(
        id=str(payload.get("id", "")),
        type=str(payload["type"]),
        raw=payload,
        value=None if value is None else str(value),
        options=options,
    )


def _parse_energy(payload: JsonDict) -> EnergyResource:
    components: dict[str, float] = {}
    for entry in payload.get("values") or []:
        if not isinstance(entry, dict):
            continue
        for name, amount in entry.items():
            if isinstance(amount, (int, float)) and not isinstance(amount, bool):
                components[str(name)] = float(amount)

    unit = payload.get("unit") or payload.get("unitOfMeasure")
    return EnergyResource(
        id=str(payload.get("id", "")),
        type=str(payload["type"]),
        raw=payload,
        unit=str(unit) if unit else None,
        components=components,
    )


def _parse_timestamp(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _advance(start: datetime, sample_rate: str, steps: int) -> datetime | None:
    """Start of bucket ``steps`` at ``sample_rate``, counted from ``start``.

    Calendar periods are advanced on the wall clock and keep the offset the
    series started with. Across a DST change that offset goes stale by an
    hour; a caller that knows the installation's timezone should re-localize
    rather than trust it to the hour.
    """
    if sample_rate == "PT1H":
        return start + timedelta(hours=steps)
    if sample_rate == "P1D":
        return start + timedelta(days=steps)
    if sample_rate == "P1M":
        month_index = start.month - 1 + steps
        year = start.year + month_index // 12
        month = month_index % 12 + 1
        day = min(start.day, _days_in_month(year, month))
        return start.replace(year=year, month=month, day=day)
    return None


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        nxt = datetime(year + 1, 1, 1)
    else:
        nxt = datetime(year, month + 1, 1)
    return (nxt - timedelta(days=1)).day


def _parse_recording(payload: JsonDict) -> RecordingResource:
    series: list[RecordingSeries] = []
    for entry in payload.get("values") or []:
        if not isinstance(entry, dict):
            continue
        sample_rate = str(entry.get("sampleRate", ""))
        start = _parse_timestamp(entry.get("startTime"))
        buckets: list[RecordingBucket] = []
        for index, bucket in enumerate(entry.get("recording") or []):
            if not isinstance(bucket, dict):
                continue
            count = bucket.get("c", 0)
            total = bucket.get("y", 0)
            buckets.append(
                RecordingBucket(
                    count=int(count) if isinstance(count, (int, float)) else 0,
                    total=float(total) if isinstance(total, (int, float)) else 0.0,
                    start=(_advance(start, sample_rate, index) if start is not None else None),
                )
            )
        series.append(
            RecordingSeries(
                sample_rate=sample_rate,
                start_time=start,
                end_time=_parse_timestamp(entry.get("endTime")),
                buckets=tuple(buckets),
            )
        )

    recorded = payload.get("recordedResource")
    recorded_id = (
        str(recorded.get("id")) if isinstance(recorded, dict) and recorded.get("id") else None
    )
    recording_type = payload.get("recordingType")
    unit = payload.get("unitOfMeasure") or payload.get("unit")

    return RecordingResource(
        id=str(payload.get("id", "")),
        type=str(payload["type"]),
        raw=payload,
        unit=str(unit) if unit else None,
        recorded_resource_id=recorded_id,
        recording_type=str(recording_type) if recording_type else None,
        series=tuple(series),
    )


def _parse_reference_list(payload: JsonDict) -> ReferenceList:
    references = tuple(
        str(ref["id"])
        for ref in payload.get("references") or []
        if isinstance(ref, dict) and ref.get("id")
    )
    return ReferenceList(
        id=str(payload.get("id", "")),
        type=str(payload["type"]),
        raw=payload,
        references=references,
    )


def parse_resource(payload: JsonDict) -> Resource:
    """Parse one resource payload into its model.

    Unmodelled structural types fall back to :class:`RawResource`, which keeps
    the payload reachable through ``.raw``.
    """
    if not isinstance(payload, dict):
        raise K40ResponseError(f"expected a JSON object, got {type(payload).__name__}")

    resource_type = payload.get("type")
    if not isinstance(resource_type, str):
        raise K40ResponseError(f"{payload.get('id')!r}: response carries no 'type'")

    if resource_type in _NUMERIC_TYPES:
        return _parse_numeric(payload)
    if resource_type == "stringValue":
        return _parse_string(payload)
    if resource_type == "emonValue":
        return _parse_energy(payload)
    if resource_type == "yRecordingExtended":
        return _parse_recording(payload)
    if resource_type == "refEnum":
        return _parse_reference_list(payload)

    return RawResource(
        id=str(payload.get("id", "")),
        type=resource_type,
        raw=payload,
    )


def parse_system_info(payload: JsonDict) -> SystemInfo:
    """Distil ``/system/basicInfo`` into device-registry material."""
    modules: list[SystemInfoModule] = []
    for entry in payload.get("values") or []:
        if not isinstance(entry, dict):
            continue
        modules.append(
            SystemInfoModule(
                name=_non_empty(entry.get("ProductName")),
                hardware_id=_non_empty(entry.get("ModuleHwIdentStr")),
                version=_non_empty(entry.get("Ver")),
                serial_number=_non_empty(entry.get("ProductSerialNumber"))
                or _non_empty(entry.get("ModuleSerialNumber")),
            )
        )
    return SystemInfo(
        gateway_id=_non_empty(payload.get("gatewayId")),
        modules=tuple(modules),
    )


def _non_empty(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
