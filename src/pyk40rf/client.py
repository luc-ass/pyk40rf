"""Async client for the Bosch K 40 RF local (owner) API."""

from __future__ import annotations

import asyncio
import logging
from types import TracebackType
from typing import Any, Final, Self

import aiohttp
from yarl import URL

from .auth import normalize_password
from .const import (
    AUTH_PATH,
    AUTH_PORT,
    DATA_PORT,
    DEVICE_IDS,
    DHW_CIRCUIT_IDS,
    HEAT_SOURCE_IDS,
    HEATING_CIRCUIT_IDS,
    PROBE_PATHS,
    SAMPLE_RATES,
    SOLAR_CIRCUIT_IDS,
    VENTILATION_ZONE_IDS,
    ZONE_IDS,
)
from .exceptions import (
    K40AuthError,
    K40ConnectionError,
    K40Error,
    K40NotFoundError,
    K40ProximityError,
    K40ResponseError,
)
from .models import (
    Installation,
    JsonDict,
    RecordingResource,
    ReferenceList,
    Resource,
    SystemInfo,
    Token,
)
from .parser import parse_resource, parse_system_info

_LOGGER: Final = logging.getLogger(__name__)

DEFAULT_TIMEOUT: Final = 15.0
DEFAULT_CLIENT_NAME: Final = "pyk40rf"

#: Ceiling on concurrent reads. The gateway is a small embedded device and
#: a full poll is dozens of individual GETs.
DEFAULT_CONCURRENCY: Final = 4

__all__ = ["DEFAULT_CLIENT_NAME", "DEFAULT_CONCURRENCY", "DEFAULT_TIMEOUT", "K40Client"]


class K40Client:
    """Read-only client for one gateway.

    The gateway presents a self-signed leaf certificate whose common name is
    the numeric device id, so ordinary hostname verification cannot succeed.
    Either leave ``verify_ssl`` off, or pin the certificate through
    ``fingerprint`` (SHA-256, 32 bytes).

    The session is injected rather than created, so an embedding application
    keeps control of connector and lifecycle.
    """

    def __init__(
        self,
        host: str,
        session: aiohttp.ClientSession,
        *,
        token: str | Token | None = None,
        data_port: int = DATA_PORT,
        auth_port: int = AUTH_PORT,
        verify_ssl: bool = False,
        fingerprint: bytes | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        concurrency: int = DEFAULT_CONCURRENCY,
    ) -> None:
        """Initialise the client for ``host``."""
        self._host = host
        self._session = session
        self._data_port = data_port
        self._auth_port = auth_port
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._semaphore = asyncio.Semaphore(max(1, concurrency))

        if fingerprint is not None:
            self._ssl: Any = aiohttp.Fingerprint(fingerprint)
        else:
            self._ssl = bool(verify_ssl)

        self._token: str | None = None
        if token is not None:
            self.token = token.access_token if isinstance(token, Token) else token

    @property
    def host(self) -> str:
        """The gateway this client talks to."""
        return self._host

    @property
    def token(self) -> str | None:
        """The bearer token in use, if any."""
        return self._token

    @token.setter
    def token(self, value: str | None) -> None:
        self._token = value.strip() if isinstance(value, str) else value

    async def __aenter__(self) -> Self:
        """Enter the context manager."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Leave the context manager. The injected session is left alone."""

    # -- authentication ----------------------------------------------------

    async def async_request_token(
        self,
        username: str,
        password: str,
        *,
        client_name: str = DEFAULT_CLIENT_NAME,
        store: bool = True,
    ) -> Token:
        """Request a bearer token from the auth port.

        Two conditions must both hold or the gateway answers HTTP 412: the
        WLAN and radio buttons were pressed within the last few minutes, and
        the request comes from the gateway's own subnet. Reading data
        afterwards has neither restriction, and the token does not expire.

        Raises:
            K40ProximityError: proximity was not proven (HTTP 412).
            K40AuthError: the credentials were rejected.
            K40ConnectionError: the gateway was unreachable.
        """
        url = URL.build(scheme="https", host=self._host, port=self._auth_port).with_path(AUTH_PATH)
        payload = {
            "grant_type": "password",
            "username": username,
            "password": normalize_password(password),
            "client_name": client_name,
        }

        try:
            async with self._session.post(
                url, data=payload, ssl=self._ssl, timeout=self._timeout
            ) as response:
                body = await self._read_json(response, url)
                if response.status == 412:
                    raise K40ProximityError(
                        "gateway refused the token: press the WLAN and radio buttons "
                        "for about a second, then retry from inside its subnet "
                        f"({_error_of(body) or 'physical_proximity_unproven'})"
                    )
                if response.status in (400, 401, 403):
                    reason = _error_of(body)
                    raise K40AuthError(
                        f"gateway rejected the credentials ({response.status}"
                        f"{f': {reason}' if reason else ''})"
                    )
                if response.status >= 400:
                    raise K40ResponseError(f"token request failed with HTTP {response.status}")
        except aiohttp.ClientError as err:
            raise K40ConnectionError(f"cannot reach {self._host}: {err}") from err
        except TimeoutError as err:
            raise K40ConnectionError(f"timeout talking to {self._host}") from err

        access_token = body.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise K40ResponseError("token response carries no 'access_token'")

        token = Token(
            access_token=access_token,
            token_type=str(body.get("token_type") or "Bearer"),
            raw=body,
        )
        if store:
            self.token = access_token
        return token

    # -- reading -----------------------------------------------------------

    async def async_get_raw(self, path: str, *, params: dict[str, str] | None = None) -> JsonDict:
        """GET one resource and return its decoded JSON.

        Raises:
            K40NotFoundError: the installation does not have this resource.
            K40AuthError: the token is missing or no longer accepted.
            K40ConnectionError: the gateway was unreachable.
        """
        if not self._token:
            raise K40AuthError("no bearer token set; call async_request_token first")

        url = URL.build(scheme="https", host=self._host, port=self._data_port).with_path(
            path if path.startswith("/") else f"/{path}"
        )
        headers = {
            "Authorization": f"Bearer {self._token}",
            # The gateway is an embedded HTTP server; ask for exactly what the
            # documented client asks for rather than aiohttp's default "*/*".
            "Accept": "application/json",
        }

        try:
            async with (
                self._semaphore,
                self._session.get(
                    url,
                    headers=headers,
                    params=params,
                    ssl=self._ssl,
                    timeout=self._timeout,
                ) as response,
            ):
                if response.status == 404:
                    raise K40NotFoundError(f"{path} does not exist on {self._host}")
                if response.status in (401, 403):
                    raise K40AuthError(
                        f"{path}: gateway rejected the token "
                        f"(HTTP {response.status}{await _detail(response)})"
                    )
                if response.status >= 400:
                    raise K40ResponseError(
                        f"{path} failed with HTTP {response.status}{await _detail(response)}"
                    )
                return await self._read_json(response, url)
        except aiohttp.ClientError as err:
            raise K40ConnectionError(f"cannot reach {self._host}: {err}") from err
        except TimeoutError as err:
            raise K40ConnectionError(f"timeout reading {path} from {self._host}") from err

    async def async_get(self, path: str, *, params: dict[str, str] | None = None) -> Resource:
        """GET one resource and parse it."""
        return parse_resource(await self.async_get_raw(path, params=params))

    async def async_get_many(self, paths: list[str]) -> dict[str, Resource]:
        """GET several resources concurrently, skipping those that 404.

        Concurrency is capped (see ``concurrency``) because a full poll is
        dozens of requests against a small embedded device. Missing resources
        are omitted from the result; every other failure propagates.
        """
        results = await asyncio.gather(
            *(self.async_get(path) for path in paths), return_exceptions=True
        )

        resources: dict[str, Resource] = {}
        for path, result in zip(paths, results, strict=True):
            if isinstance(result, K40NotFoundError):
                _LOGGER.debug("%s is not present on this installation", path)
                continue
            if isinstance(result, BaseException):
                raise result
            resources[path] = result
        return resources

    async def async_probe(self, path: str) -> bool:
        """Whether ``path`` exists on this installation."""
        try:
            await self.async_get_raw(path)
        except K40NotFoundError:
            return False
        except K40Error:
            raise
        return True

    async def async_get_recording(
        self,
        path: str,
        sample_rate: str,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> RecordingResource:
        """Read a ``/recordings/...`` resource.

        ``sample_rate`` is mandatory -- the gateway answers HTTP 400 without
        it -- and case sensitive.

        Raises:
            ValueError: ``sample_rate`` is not one of :data:`SAMPLE_RATES`.
        """
        if sample_rate not in SAMPLE_RATES:
            raise ValueError(
                f"sample_rate must be one of {', '.join(SAMPLE_RATES)}, got {sample_rate!r}"
            )

        params = {"sampleRate": sample_rate}
        if start_date:
            params["startDate"] = start_date
        if end_date:
            params["endDate"] = end_date

        resource = await self.async_get(path, params=params)
        if not isinstance(resource, RecordingResource):
            raise K40ResponseError(f"{path} answered with {resource.type!r}, not a recording")
        return resource

    async def async_get_system_info(self) -> SystemInfo:
        """Read ``/system/basicInfo`` for device-registry material."""
        return parse_system_info(await self.async_get_raw("/system/basicInfo"))

    async def async_get_signals(self) -> tuple[str, ...]:
        """List the ids of the dynamic ``/signals`` branch.

        This branch is not in the published API spec and differs per device,
        so it has to be read rather than assumed.
        """
        try:
            resource = await self.async_get("/signals")
        except K40NotFoundError:
            return ()
        if not isinstance(resource, ReferenceList):
            raise K40ResponseError(f"/signals answered with {resource.type!r}")
        return resource.references

    async def async_discover_installation(
        self, *, include_zones: bool = True, include_devices: bool = True
    ) -> Installation:
        """Probe which optional branches this installation actually has.

        The spec declares ids for every conceivable installation; a given
        device implements a subset and answers 404 for the rest. Probing beats
        assuming, and it is what lets one integration serve every variant.

        Zones and devices are the expensive half of the probe (sixteen and
        thirty-two candidate ids), so a caller that does not need them can
        switch them off.
        """
        (
            heat_sources,
            heating_circuits,
            dhw_circuits,
            solar,
            ventilation,
            zones,
            devices,
            signals,
        ) = await asyncio.gather(
            self._probe_ids("heat_sources", HEAT_SOURCE_IDS),
            self._probe_ids("heating_circuits", HEATING_CIRCUIT_IDS),
            self._probe_ids("dhw_circuits", DHW_CIRCUIT_IDS),
            self._probe_ids("solar_circuits", SOLAR_CIRCUIT_IDS),
            self._probe_ids("ventilation_zones", VENTILATION_ZONE_IDS),
            self._probe_ids("zones", ZONE_IDS if include_zones else ()),
            self._probe_ids("devices", DEVICE_IDS if include_devices else ()),
            self.async_get_signals(),
        )

        return Installation(
            heat_sources=heat_sources,
            heating_circuits=heating_circuits,
            dhw_circuits=dhw_circuits,
            solar_circuits=solar,
            ventilation_zones=ventilation,
            zones=zones,
            devices=devices,
            has_ventilation=bool(ventilation),
            signals=signals,
        )

    async def _probe_ids(self, family: str, candidates: tuple[str, ...]) -> tuple[str, ...]:
        """Return the ids of ``candidates`` that this installation has.

        An id counts as present as soon as one of its probe paths answers. The
        API has no container resource to ask about, so presence has to be read
        off the leaves.
        """
        templates = PROBE_PATHS[family]
        present = await asyncio.gather(
            *(self._probe_any(templates, candidate) for candidate in candidates)
        )
        return tuple(
            candidate for candidate, exists in zip(candidates, present, strict=True) if exists
        )

    async def _probe_any(self, templates: tuple[str, ...], candidate: str) -> bool:
        """Whether any of ``templates`` exists for ``candidate``."""
        for template in templates:
            if await self.async_probe(template.format(id=candidate)):
                return True
        return False

    # -- internals ---------------------------------------------------------

    @staticmethod
    async def _read_json(response: aiohttp.ClientResponse, url: URL) -> JsonDict:
        """Decode a response body, tolerating the gateway's content types."""
        try:
            body = await response.json(content_type=None)
        except ValueError as err:
            raise K40ResponseError(f"{url.path} did not answer with JSON: {err}") from err
        if not isinstance(body, dict):
            raise K40ResponseError(
                f"{url.path} answered with {type(body).__name__}, expected an object"
            )
        return body


async def _detail(response: aiohttp.ClientResponse) -> str:
    """Quote what the gateway said, so a rejection can be diagnosed.

    An embedded device rarely explains itself, but when it does the reason is
    the whole answer -- and without it "the token was rejected" is a dead end
    for whoever has to debug it.
    """
    try:
        body = (await response.text())[:200].strip()
    except (UnicodeDecodeError, aiohttp.ClientError, TimeoutError):
        return ""
    return f": {body}" if body else ""


def _error_of(body: JsonDict) -> str | None:
    """Pull the gateway's ``error`` field out of an error body."""
    error = body.get("error")
    return str(error) if error else None
