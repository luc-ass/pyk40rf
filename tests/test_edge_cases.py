"""Defensive paths: malformed payloads and TLS configuration."""

from __future__ import annotations

import aiohttp
import pytest

from pyk40rf import (
    EnergyResource,
    K40Client,
    NumericResource,
    ReferenceList,
    StringResource,
    Token,
    is_error_label,
    parse_resource,
    parse_system_info,
)


def numeric(value: object, state: object) -> NumericResource:
    """Build a numeric resource with the given state field."""
    resource = parse_resource({"id": "/x", "type": "floatValue", "value": value, "state": state})
    assert isinstance(resource, NumericResource)
    return resource


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("open", True),
        ("OPEN", True),
        ("NA_SHORT", True),
        ("low_flow", True),
        ("HEATING", False),
        ("ON", False),
        ("", False),
    ],
)
def test_error_labels_are_recognised_case_insensitively(label: str, expected: bool) -> None:
    assert is_error_label(label) is expected


def test_junk_entries_in_a_sentinel_list_are_ignored() -> None:
    assert numeric(21.5, ["junk", None, {"open": -32768.0}]).value == 21.5


def test_an_empty_state_changes_nothing() -> None:
    assert numeric(21.5, []).value == 21.5
    assert numeric(21.5, {}).value == 21.5


def test_an_unusable_state_type_is_ignored() -> None:
    assert numeric(21.5, "nonsense").value == 21.5


def test_booleans_are_not_treated_as_numbers() -> None:
    # True == 1 in Python; a sentinel of 1 must not swallow a boolean reading.
    resource = parse_resource(
        {"id": "/x", "type": "integerValue", "value": 1, "state": {"ON": True}}
    )
    assert isinstance(resource, NumericResource)
    assert resource.value == 1
    assert resource.label is None


def test_float_sentinels_survive_representation_wobble() -> None:
    assert numeric(-3276.8000000000002, {"NA_OPEN": -3276.8}).value is None


def test_non_numeric_enum_values_still_sort() -> None:
    resource = parse_resource(
        {"id": "/x", "type": "integerValue", "value": 1, "state": {"B": "x", "A": 1}}
    )
    assert isinstance(resource, NumericResource)
    assert resource.options == ("A", "B")
    assert resource.label == "A"


def test_a_string_without_allowed_values_has_no_options() -> None:
    resource = parse_resource({"id": "/x", "type": "stringValue", "value": "on"})
    assert isinstance(resource, StringResource)
    assert resource.options == ()


def test_a_null_string_value_stays_none() -> None:
    resource = parse_resource({"id": "/x", "type": "stringValue", "value": None})
    assert isinstance(resource, StringResource)
    assert resource.value is None


def test_energy_ignores_non_numeric_components() -> None:
    resource = parse_resource(
        {
            "id": "/x",
            "type": "emonValue",
            "unit": "kWh",
            "values": [{"compressor": 5.0}, {"broken": "n/a"}, "junk"],
        }
    )
    assert isinstance(resource, EnergyResource)
    assert resource.components == {"compressor": 5.0}


def test_a_reference_list_without_references_is_empty() -> None:
    resource = parse_resource({"id": "/signals", "type": "refEnum"})
    assert isinstance(resource, ReferenceList)
    assert resource.references == ()


def test_reference_entries_without_an_id_are_skipped() -> None:
    resource = parse_resource(
        {"id": "/signals", "type": "refEnum", "references": [{"id": "/a"}, {}, "junk"]}
    )
    assert isinstance(resource, ReferenceList)
    assert resource.references == ("/a",)


def test_system_info_tolerates_an_empty_payload() -> None:
    info = parse_system_info({"id": "/system/basicInfo", "type": "systeminfo"})
    assert info.modules == ()
    assert info.gateway_id is None
    assert info.product_name is None
    assert info.serial_number is None


def test_system_info_skips_blank_fields() -> None:
    info = parse_system_info(
        {
            "gatewayId": "  ",
            "values": [
                {"ProductName": "", "ModuleSerialNumber": "  "},
                {"ProductName": "Compress CS5800iAW", "ProductSerialNumber": "123"},
            ],
        }
    )
    assert info.gateway_id is None
    assert info.product_name == "Compress CS5800iAW"
    assert info.serial_number == "123"


class TestTlsConfiguration:
    """The gateway's leaf is self-signed, so verification has to be chosen."""

    async def test_verification_is_off_by_default(self) -> None:
        async with aiohttp.ClientSession() as session:
            client = K40Client("host", session)
            assert client._ssl is False

    async def test_verification_can_be_turned_on(self) -> None:
        async with aiohttp.ClientSession() as session:
            client = K40Client("host", session, verify_ssl=True)
            assert client._ssl is True

    async def test_a_fingerprint_pins_the_certificate(self) -> None:
        async with aiohttp.ClientSession() as session:
            client = K40Client("host", session, fingerprint=b"\x00" * 32)
            assert isinstance(client._ssl, aiohttp.Fingerprint)


async def test_a_token_object_can_be_passed_instead_of_a_string() -> None:
    async with aiohttp.ClientSession() as session:
        client = K40Client("host", session, token=Token(access_token="abc"))
        assert client.token == "abc"


async def test_the_token_can_be_cleared() -> None:
    async with aiohttp.ClientSession() as session:
        client = K40Client("host", session, token="abc")
        client.token = None
        assert client.token is None
