"""Credential parsing and discovery-name handling."""

from __future__ import annotations

import pytest

from pyk40rf import (
    ZEROCONF_PARTNER_TYPE,
    ZEROCONF_TYPE,
    ZEROCONF_TYPES,
    K40Error,
    device_id_from_zeroconf_name,
    is_valid_password,
    normalize_password,
    parse_sticker_qr,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("aaaa-bbbb-cccc-dddd", "aaaabbbbccccdddd"),
        ("aaaabbbbccccdddd", "aaaabbbbccccdddd"),
        ("  aaaa-bbbb-cccc-dddd  ", "aaaabbbbccccdddd"),
    ],
)
def test_password_is_normalised(raw: str, expected: str) -> None:
    assert normalize_password(raw) == expected


@pytest.mark.parametrize(
    "password",
    ["aaaa-bbbb-cccc-dddd", "aaaabbbbccccdddd", "1a2b-3c4d-5e6f-7g8h"],
)
def test_valid_passwords_are_accepted(password: str) -> None:
    assert is_valid_password(password)


@pytest.mark.parametrize(
    "password",
    ["", "aaaa-bbbb-cccc", "aaaa-bbbb-cccc-dddd-eeee", "aaa-bbbb-cccc-dddd", "aaaa bbbb"],
)
def test_malformed_passwords_are_rejected(password: str) -> None:
    assert not is_valid_password(password)


def test_sticker_qr_is_parsed() -> None:
    creds = parse_sticker_qr("V:1;L:100000001;P:aaaa-bbbb-cccc-dddd;MAC:00:11:22:33:44:55;N:K40RF")
    assert creds.username == "100000001"
    assert creds.password == "aaaabbbbccccdddd"
    assert creds.mac == "00:11:22:33:44:55"
    assert creds.model == "K40RF"


def test_sticker_qr_without_credentials_raises() -> None:
    with pytest.raises(K40Error):
        parse_sticker_qr("V:1;MAC:00:11:22:33:44:55;N:K40RF")


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("K40RF-100000001", "100000001"),
        ("K40RF-100000001._hvac-open-api._tcp.local.", "100000001"),
        ("SomethingElse-1", None),
        ("K40RF-", None),
    ],
)
def test_device_id_is_read_from_the_mdns_name(name: str, expected: str | None) -> None:
    assert device_id_from_zeroconf_name(name) == expected


def test_the_partner_service_is_not_advertised_as_ours() -> None:
    """8443/8442 is the installer's mutual-TLS channel, not the owner API."""
    assert ZEROCONF_TYPES == (ZEROCONF_TYPE,)
    assert ZEROCONF_PARTNER_TYPE not in ZEROCONF_TYPES
