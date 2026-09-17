"""Credential helpers: sticker QR, password shape, discovery names."""

from __future__ import annotations

from dataclasses import dataclass
import re

from .const import QR_FIELD_SEPARATOR, ZEROCONF_NAME_PREFIX
from .exceptions import K40Error

__all__ = [
    "Credentials",
    "device_id_from_zeroconf_name",
    "is_valid_password",
    "normalize_password",
    "parse_sticker_qr",
]

#: Four groups of four alphanumerics; the dashes are cosmetic.
_PASSWORD_RE = re.compile(r"^([0-9a-zA-Z]{4}-?){3}[0-9a-zA-Z]{4}$")


@dataclass(frozen=True, slots=True)
class Credentials:
    """What the device sticker carries."""

    username: str
    password: str
    mac: str | None = None
    model: str | None = None


def normalize_password(password: str) -> str:
    """Strip the cosmetic dashes the sticker prints.

    Users may type the password either way; the gateway wants it without.
    """
    return password.replace("-", "").strip()


def is_valid_password(password: str) -> bool:
    """Whether the password has the documented ``aaaa-bbbb-cccc-dddd`` shape."""
    return bool(_PASSWORD_RE.match(password.strip()))


def parse_sticker_qr(payload: str) -> Credentials:
    """Parse ``V:1;L:<login>;P:<pass>;MAC:<mac>;N:<model>``.

    Raises:
        K40Error: if login or password are missing.
    """
    fields: dict[str, str] = {}
    for part in payload.split(QR_FIELD_SEPARATOR):
        key, separator, value = part.partition(":")
        if separator:
            fields[key.strip().upper()] = value.strip()

    login = fields.get("L")
    password = fields.get("P")
    if not login or not password:
        raise K40Error("sticker QR carries no login/password (expected 'L:' and 'P:')")

    return Credentials(
        username=login,
        password=normalize_password(password),
        mac=fields.get("MAC"),
        model=fields.get("N"),
    )


def device_id_from_zeroconf_name(name: str) -> str | None:
    """Extract the device id from a ``K40RF-<id>`` mDNS instance name.

    That id is also the auth username and the TLS certificate's common name,
    so discovery can prefill the login.
    """
    instance = name.split(".", 1)[0].strip()
    if not instance.startswith(ZEROCONF_NAME_PREFIX):
        return None
    device_id = instance[len(ZEROCONF_NAME_PREFIX) :]
    return device_id or None
