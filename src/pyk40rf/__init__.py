"""Async client for the Bosch Connect-Key K 40 RF local API.

The gateway exposes a read-only, token-authenticated REST API on the local
network from firmware 15.00.01 onwards. This library speaks it and nothing
else -- it has no Home Assistant dependency and is independently testable.
"""

from __future__ import annotations

from .auth import (
    Credentials,
    device_id_from_zeroconf_name,
    is_valid_password,
    normalize_password,
    parse_sticker_qr,
)
from .client import DEFAULT_CLIENT_NAME, DEFAULT_CONCURRENCY, DEFAULT_TIMEOUT, K40Client
from .const import (
    AUTH_PORT,
    DATA_PORT,
    MIN_FIRMWARE,
    SAMPLE_RATES,
    TXT_AUTH_PORT,
    TXT_BRAND,
    TXT_DEVICE_ID,
    TXT_MODEL,
    TXT_SERIAL,
    ZEROCONF_NAME_PREFIX,
    ZEROCONF_PARTNER_TYPE,
    ZEROCONF_TYPE,
    ZEROCONF_TYPES,
)
from .exceptions import (
    K40AuthError,
    K40ConnectionError,
    K40Error,
    K40ForbiddenError,
    K40NotFoundError,
    K40ProximityError,
    K40ResponseError,
)
from .models import (
    EnergyResource,
    Installation,
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
    Token,
)
from .parser import is_error_label, parse_resource, parse_system_info

__version__ = "0.1.4"

__all__ = [
    "AUTH_PORT",
    "DATA_PORT",
    "DEFAULT_CLIENT_NAME",
    "DEFAULT_CONCURRENCY",
    "DEFAULT_TIMEOUT",
    "MIN_FIRMWARE",
    "SAMPLE_RATES",
    "TXT_AUTH_PORT",
    "TXT_BRAND",
    "TXT_DEVICE_ID",
    "TXT_MODEL",
    "TXT_SERIAL",
    "ZEROCONF_NAME_PREFIX",
    "ZEROCONF_PARTNER_TYPE",
    "ZEROCONF_TYPE",
    "ZEROCONF_TYPES",
    "Credentials",
    "EnergyResource",
    "Installation",
    "K40AuthError",
    "K40Client",
    "K40ConnectionError",
    "K40Error",
    "K40ForbiddenError",
    "K40NotFoundError",
    "K40ProximityError",
    "K40ResponseError",
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
    "__version__",
    "device_id_from_zeroconf_name",
    "is_error_label",
    "is_valid_password",
    "normalize_password",
    "parse_resource",
    "parse_sticker_qr",
    "parse_system_info",
]
