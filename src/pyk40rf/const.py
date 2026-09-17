"""Protocol constants for the K 40 RF local API."""

from __future__ import annotations

from typing import Final

#: Bearer-protected data API. Closed until the gateway has been paired once.
DATA_PORT: Final = 9443

#: Token endpoint. Open even before pairing.
AUTH_PORT: Final = 9442

AUTH_PATH: Final = "/auth/token"

#: Lowest firmware exposing the owner API at all.
MIN_FIRMWARE: Final = "15.00.01"

#: The mDNS service that advertises the owner API. The gateway announces a
#: second one, ``_gateway-tt-local-api._tcp``, on ports 8443/8442 -- that is
#: the mutual-TLS partner channel used by installers and energy providers, and
#: an owner cannot authenticate against it. Discovering it would only offer a
#: setup that must fail, so only this one counts.
ZEROCONF_TYPE: Final = "_hvac-open-api._tcp.local."

#: Announced too, but not ours. Kept named so the distinction is not lost.
ZEROCONF_PARTNER_TYPE: Final = "_gateway-tt-local-api._tcp.local."

ZEROCONF_TYPES: Final = (ZEROCONF_TYPE,)

#: The instance name follows ``K40RF-<device id>``, and that device id doubles
#: as the auth username. Note that the mDNS *hostname* carries a different,
#: shorter id (``K40RF-a1b2c3.local``) -- reading the username from there would
#: be wrong.
ZEROCONF_NAME_PREFIX: Final = "K40RF-"

#: TXT keys the gateway publishes. ``uuid`` is the device id, and is a more
#: robust source for it than parsing the instance name. ``authport`` is the
#: token endpoint, which is not the port the service record points at.
TXT_DEVICE_ID: Final = "uuid"
TXT_AUTH_PORT: Final = "authport"
TXT_BRAND: Final = "brand"
TXT_MODEL: Final = "model"
TXT_SERIAL: Final = "serial"

#: Sticker QR payload: ``V:1;L:<login>;P:<pass>;MAC:<mac>;N:<model>``.
QR_FIELD_SEPARATOR: Final = ";"

#: ``sampleRate`` values accepted by ``/recordings/*`` (case sensitive).
SAMPLE_RATES: Final = ("PT1H", "P1D", "P1M", "all")

#: Static endpoints label an unreadable measurement with these ``state`` keys.
#: Signals use upper-case spellings instead; see :mod:`pyk40rf.parser`.
ERROR_STATE_LABELS: Final = frozenset(
    {
        "open",
        "short",
        "invalid",
        "invalid2",
        "lowflow",
        "na_open",
        "na_short",
        "low_flow",
        "not_available",
        "na",
    }
)

#: Enum ids from the API spec. A given installation implements a subset; the
#: client probes which ones answer with 200 rather than 404.
HEAT_SOURCE_IDS: Final = tuple(f"hs{i}" for i in range(1, 7))
HEATING_CIRCUIT_IDS: Final = tuple(f"hc{i}" for i in range(1, 5))
DHW_CIRCUIT_IDS: Final = tuple(f"dhw{i}" for i in range(1, 3))
ZONE_IDS: Final = tuple(f"zone{i}" for i in range(1, 17))
DEVICE_IDS: Final = tuple(f"device{i}" for i in range(1, 33))
SOLAR_CIRCUIT_IDS: Final = ("sc1",)
VENTILATION_ZONE_IDS: Final = ("zone1",)

#: There is no ``/heatSources/hs1`` style container to ask about -- the API has
#: only leaf resources. Presence of an id is therefore decided by asking for a
#: couple of resources that it would have, and taking any 200 as a yes. Several
#: per family, because installations differ in kind as well as in count: a gas
#: boiler has no compressor, a heating circuit may report no humidity.
PROBE_PATHS: Final = {
    "heat_sources": (
        "/heatSources/{id}/numberOfStarts",
        "/heatSources/{id}/pumpVolumeFlow",
        "/heatSources/{id}/actualPower",
    ),
    "heating_circuits": (
        "/heatingCircuits/{id}/currentRoomSetpoint",
        "/heatingCircuits/{id}/operationMode",
        "/heatingCircuits/{id}/overallStatus",
    ),
    "dhw_circuits": (
        "/dhwCircuits/{id}/actualTemp",
        "/dhwCircuits/{id}/operationMode",
        "/dhwCircuits/{id}/currentSetpoint",
    ),
    "solar_circuits": (
        "/solarCircuits/{id}/collectorTemperature",
        "/solarCircuits/{id}/pumpModulation",
    ),
    "ventilation_zones": (
        "/ventilation/{id}/operationMode",
        "/ventilation/{id}/exhaustFanLevel",
    ),
    "zones": (
        "/zones/{id}/averageCurrentTemperature",
        "/zones/{id}/name",
    ),
    "devices": (
        "/devices/{id}/type",
        "/devices/{id}/rfPairedStatus",
    ),
}
