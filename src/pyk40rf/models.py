"""Typed representations of the gateway's KM200-style resources."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

__all__ = [
    "EnergyResource",
    "Installation",
    "NumericResource",
    "RawResource",
    "RecordingBucket",
    "RecordingResource",
    "RecordingSeries",
    "ReferenceList",
    "Resource",
    "StringResource",
    "SystemInfo",
    "SystemInfoModule",
    "Token",
]

type JsonDict = dict[str, Any]


@dataclass(frozen=True, slots=True)
class Resource:
    """Common head of every resource the gateway returns."""

    id: str
    type: str
    raw: JsonDict = field(repr=False)


@dataclass(frozen=True, slots=True)
class NumericResource(Resource):
    """A ``floatValue`` or ``integerValue``.

    ``value`` is ``None`` when the reading equals one of the resource's error
    sentinels (sensor open, shorted, no flow, ...). ``raw_value`` always keeps
    what the gateway actually sent, so callers can still log or diagnose it.

    Some resources carry an enumeration in their ``state`` map instead of --
    or alongside -- error sentinels. For those, ``label`` is the decoded name
    of the current reading and ``options`` lists every selectable label. A
    resource with ``options`` is better modelled as an enum than as a number.
    """

    value: float | int | None
    raw_value: float | int
    unit: str | None = None
    label: str | None = None
    error_label: str | None = None
    options: tuple[str, ...] = ()

    @property
    def is_error(self) -> bool:
        """Whether the current reading is an error sentinel."""
        return self.error_label is not None

    @property
    def is_enum(self) -> bool:
        """Whether this resource enumerates named states."""
        return bool(self.options)


#: The two words the gateway writes when a ``stringValue`` carries a flag.
#: Lower-cased on comparison, because nothing promises the casing stays.
_BOOLEAN_WORDS: dict[str, bool] = {"true": True, "false": False}


@dataclass(frozen=True, slots=True)
class StringResource(Resource):
    """A ``stringValue``, optionally constrained to ``allowedValues``.

    Most of the ``/signals`` branch is flags carried in this shape: across the
    three installations seen so far, every ``stringValue`` signal but the two
    ``GWEEBUS.CEM.*`` identity strings reads exactly ``"true"`` or ``"false"``.
    :attr:`boolean` decodes those and says nothing about the rest, so a caller
    can model a flag as a flag without guessing at a polarity.
    """

    value: str | None
    options: tuple[str, ...] = ()

    @property
    def boolean(self) -> bool | None:
        """The reading as a flag, or ``None`` where it is not one."""
        if self.value is None:
            return None
        return _BOOLEAN_WORDS.get(self.value.strip().lower())

    @property
    def is_boolean(self) -> bool:
        """Whether this reading is one of the gateway's two flag words."""
        return self.boolean is not None


@dataclass(frozen=True, slots=True)
class EnergyResource(Resource):
    """An ``emonValue``: one energy balance split across components.

    Each component is a lifetime counter, so they map to
    ``state_class: total_increasing`` sensors. Dividing ``outputProduced`` by
    the sum of the input components yields the seasonal performance factor.
    """

    unit: str | None
    components: dict[str, float]


@dataclass(frozen=True, slots=True)
class RecordingBucket:
    """One sample bucket: ``count`` samples summing to ``total``."""

    count: int
    total: float
    start: datetime | None = None

    @property
    def average(self) -> float | None:
        """Mean over the bucket, or ``None`` if it holds no samples."""
        if self.count <= 0:
            return None
        return self.total / self.count


@dataclass(frozen=True, slots=True)
class RecordingSeries:
    """A contiguous run of buckets at one sample rate."""

    sample_rate: str
    start_time: datetime | None
    end_time: datetime | None
    buckets: tuple[RecordingBucket, ...]


@dataclass(frozen=True, slots=True)
class RecordingResource(Resource):
    """A ``yRecordingExtended``: history for one recorded resource."""

    unit: str | None
    recorded_resource_id: str | None
    recording_type: str | None
    series: tuple[RecordingSeries, ...]


@dataclass(frozen=True, slots=True)
class ReferenceList(Resource):
    """A ``refEnum``: the ids a branch points at (e.g. ``/signals``)."""

    references: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RawResource(Resource):
    """Any structural type this library does not model further.

    Covers ``apList``, ``arrayData``, ``systeminfo``, ``updateReport``,
    ``updateStatus``, ``inclusionWhitelist``, ``errorList`` and ``configData``.
    The payload stays available through :attr:`Resource.raw`.
    """


@dataclass(frozen=True, slots=True)
class SystemInfoModule:
    """One module entry of ``/system/basicInfo``."""

    name: str | None
    hardware_id: str | None
    version: str | None
    serial_number: str | None


@dataclass(frozen=True, slots=True)
class SystemInfo:
    """``/system/basicInfo``, distilled for a device registry entry."""

    gateway_id: str | None
    modules: tuple[SystemInfoModule, ...]

    @property
    def product_name(self) -> str | None:
        """Name of the first module that carries one (the heat pump)."""
        return next((m.name for m in self.modules if m.name), None)

    @property
    def serial_number(self) -> str | None:
        """Serial of the first module that carries one."""
        return next((m.serial_number for m in self.modules if m.serial_number), None)


@dataclass(frozen=True, slots=True, repr=False)
class Token:
    """A bearer token for the data API. It does not expire.

    Neither ``str`` nor ``repr`` renders the secret: this object travels
    through config flows and tracebacks, and both end up in log files.
    """

    access_token: str
    token_type: str = "Bearer"
    raw: JsonDict = field(default_factory=dict, repr=False)

    def __repr__(self) -> str:
        """Render without leaking the secret."""
        return f"Token(token_type={self.token_type!r}, length={len(self.access_token)})"

    __str__ = __repr__


@dataclass(frozen=True, slots=True)
class Installation:
    """Which optional branches this particular installation implements."""

    heat_sources: tuple[str, ...] = ()
    heating_circuits: tuple[str, ...] = ()
    dhw_circuits: tuple[str, ...] = ()
    solar_circuits: tuple[str, ...] = ()
    ventilation_zones: tuple[str, ...] = ()
    zones: tuple[str, ...] = ()
    devices: tuple[str, ...] = ()
    has_ventilation: bool = False
    signals: tuple[str, ...] = ()
