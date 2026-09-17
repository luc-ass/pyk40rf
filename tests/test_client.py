"""Client behaviour against a mocked gateway."""

from __future__ import annotations

from collections.abc import AsyncIterator

import aiohttp
import pytest

from pyk40rf import (
    K40AuthError,
    K40Client,
    K40ConnectionError,
    K40NotFoundError,
    K40ProximityError,
    K40ResponseError,
    NumericResource,
    RecordingResource,
)

from .conftest import load
from .gateway import FakeGateway

HOST = "127.0.0.1"
TOKEN = "a-very-long-bearer-token"


@pytest.fixture(name="session")
async def session_fixture() -> AsyncIterator[aiohttp.ClientSession]:
    """Provide an injected session, as Home Assistant would supply one."""
    async with aiohttp.ClientSession() as session:
        yield session


@pytest.fixture(name="gateway")
async def gateway_fixture() -> AsyncIterator[FakeGateway]:
    """Serve a TLS gateway with a self-signed certificate, as the real one has."""
    gateway = FakeGateway()
    await gateway.start()
    try:
        yield gateway
    finally:
        await gateway.stop()


def make_client(
    gateway: FakeGateway, session: aiohttp.ClientSession, *, token: str | None = TOKEN
) -> K40Client:
    """Point a client at the fake gateway; both ports are the same socket."""
    return K40Client(
        HOST,
        session,
        token=token,
        data_port=gateway.port,
        auth_port=gateway.port,
    )


@pytest.fixture(name="client")
def client_fixture(gateway: FakeGateway, session: aiohttp.ClientSession) -> K40Client:
    """Build a client that already holds a token."""
    return make_client(gateway, session)


class TestTokenRequest:
    """The proximity-gated token endpoint."""

    async def test_token_is_returned_and_stored(
        self, gateway: FakeGateway, session: aiohttp.ClientSession
    ) -> None:
        gateway.route("/auth/token", payload={"access_token": TOKEN, "token_type": "Bearer"})
        client = make_client(gateway, session, token=None)
        token = await client.async_request_token("100000001", "aaaa-bbbb-cccc-dddd")

        assert token.access_token == TOKEN
        assert token.token_type == "Bearer"
        assert client.token == TOKEN

    async def test_password_dashes_are_stripped_before_sending(
        self, gateway: FakeGateway, session: aiohttp.ClientSession
    ) -> None:
        gateway.route("/auth/token", payload={"access_token": TOKEN})
        client = make_client(gateway, session, token=None)
        await client.async_request_token("100000001", "aaaa-bbbb-cccc-dddd")

        form = gateway.forms[0]
        assert form["password"] == "aaaabbbbccccdddd"
        assert form["grant_type"] == "password"
        assert form["client_name"] == "pyk40rf"

    async def test_token_is_not_stored_when_asked_not_to(
        self, gateway: FakeGateway, session: aiohttp.ClientSession
    ) -> None:
        gateway.route("/auth/token", payload={"access_token": TOKEN})
        client = make_client(gateway, session, token=None)
        await client.async_request_token("x", "y", store=False)
        assert client.token is None

    async def test_secret_stays_out_of_the_repr(
        self, gateway: FakeGateway, session: aiohttp.ClientSession
    ) -> None:
        gateway.route("/auth/token", payload={"access_token": TOKEN})
        client = make_client(gateway, session, token=None)
        token = await client.async_request_token("x", "y")
        assert TOKEN not in str(token)
        assert TOKEN not in repr(token)

    async def test_412_becomes_a_proximity_error(
        self, gateway: FakeGateway, session: aiohttp.ClientSession
    ) -> None:
        gateway.route("/auth/token", status=412, payload={"error": "physical_proximity_unproven"})
        client = make_client(gateway, session, token=None)
        with pytest.raises(K40ProximityError, match="buttons"):
            await client.async_request_token("x", "y")

    async def test_rejected_credentials_become_an_auth_error(
        self, gateway: FakeGateway, session: aiohttp.ClientSession
    ) -> None:
        gateway.route("/auth/token", status=401, payload={"error": "invalid_grant"})
        client = make_client(gateway, session, token=None)
        with pytest.raises(K40AuthError, match="invalid_grant"):
            await client.async_request_token("x", "y")

    async def test_response_without_a_token_raises(
        self, gateway: FakeGateway, session: aiohttp.ClientSession
    ) -> None:
        gateway.route("/auth/token", payload={"token_type": "Bearer"})
        client = make_client(gateway, session, token=None)
        with pytest.raises(K40ResponseError):
            await client.async_request_token("x", "y")

    async def test_unreachable_gateway_becomes_a_connection_error(
        self, gateway: FakeGateway, session: aiohttp.ClientSession
    ) -> None:
        port = gateway.port
        await gateway.stop()
        client = K40Client(HOST, session, data_port=port, auth_port=port)
        with pytest.raises(K40ConnectionError):
            await client.async_request_token("x", "y")


class TestReading:
    """Reads against the bearer-protected data port."""

    async def test_resource_is_parsed(self, gateway: FakeGateway, client: K40Client) -> None:
        gateway.route(
            "/heatSources/returnTemperature", payload=load("heatSources_returnTemperature")
        )
        resource = await client.async_get("/heatSources/returnTemperature")

        assert isinstance(resource, NumericResource)
        assert resource.value == 36.0
        assert resource.unit == "C"

    async def test_bearer_token_is_sent(self, gateway: FakeGateway, client: K40Client) -> None:
        gateway.route(
            "/gateway/brand", payload={"id": "/x", "type": "stringValue", "value": "Bosch"}
        )
        await client.async_get("/gateway/brand")
        assert gateway.auth_headers == [f"Bearer {TOKEN}"]

    async def test_reading_without_a_token_raises(
        self, gateway: FakeGateway, session: aiohttp.ClientSession
    ) -> None:
        client = make_client(gateway, session, token=None)
        with pytest.raises(K40AuthError, match="no bearer token"):
            await client.async_get("/gateway/brand")
        assert not gateway.paths

    async def test_404_becomes_a_not_found_error(self, client: K40Client) -> None:
        with pytest.raises(K40NotFoundError):
            await client.async_get("/heatSources/hs6")

    async def test_revoked_token_becomes_an_auth_error(
        self, gateway: FakeGateway, client: K40Client
    ) -> None:
        gateway.route("/gateway/brand", status=401, payload={"error": "unauthorized"})
        with pytest.raises(K40AuthError):
            await client.async_get("/gateway/brand")

    async def test_non_json_body_raises(self, gateway: FakeGateway, client: K40Client) -> None:
        gateway.route("/gateway/brand", body="<html>nope</html>", content_type="text/html")
        with pytest.raises(K40ResponseError):
            await client.async_get("/gateway/brand")

    async def test_json_array_body_raises(self, gateway: FakeGateway, client: K40Client) -> None:
        gateway.route("/gateway/brand", payload=["not", "an", "object"])
        with pytest.raises(K40ResponseError):
            await client.async_get("/gateway/brand")

    async def test_probe_reports_presence(self, gateway: FakeGateway, client: K40Client) -> None:
        gateway.route("/heatSources/hs1", payload={"id": "/heatSources/hs1", "type": "refEnum"})
        assert await client.async_probe("/heatSources/hs1")
        assert not await client.async_probe("/heatSources/hs2")

    async def test_probe_propagates_real_failures(
        self, gateway: FakeGateway, client: K40Client
    ) -> None:
        gateway.route("/heatSources/hs1", status=401, payload={"error": "unauthorized"})
        with pytest.raises(K40AuthError):
            await client.async_probe("/heatSources/hs1")


class TestBatchReading:
    """A poll is dozens of GETs; missing ones must not sink it."""

    async def test_missing_resources_are_skipped(
        self, gateway: FakeGateway, client: K40Client
    ) -> None:
        gateway.route(
            "/heatSources/returnTemperature", payload=load("heatSources_returnTemperature")
        )
        resources = await client.async_get_many(
            ["/heatSources/returnTemperature", "/solarCircuits/sc1"]
        )

        assert set(resources) == {"/heatSources/returnTemperature"}

    async def test_other_failures_propagate(self, gateway: FakeGateway, client: K40Client) -> None:
        gateway.route("/a", payload={"id": "/a", "type": "stringValue", "value": "x"})
        gateway.route("/b", status=500, payload={"error": "boom"})
        with pytest.raises(K40ResponseError):
            await client.async_get_many(["/a", "/b"])

    async def test_concurrency_stays_within_the_cap(
        self, gateway: FakeGateway, session: aiohttp.ClientSession
    ) -> None:
        paths = [f"/p{i}" for i in range(12)]
        for path in paths:
            gateway.route(path, payload={"id": path, "type": "stringValue", "value": "x"})
        client = K40Client(
            HOST,
            session,
            token=TOKEN,
            data_port=gateway.port,
            auth_port=gateway.port,
            concurrency=3,
        )
        resources = await client.async_get_many(paths)
        assert len(resources) == len(paths)


class TestRecordings:
    """sampleRate is mandatory and case sensitive."""

    async def test_sample_rate_is_sent_as_a_query_parameter(
        self, gateway: FakeGateway, client: K40Client
    ) -> None:
        payload = load("recordings_heatingCircuits_hc1_roomtemperature_sampleRate_P1D")
        gateway.route("/recordings/heatingCircuits/hc1/roomtemperature", payload=payload)
        recording = await client.async_get_recording(
            "/recordings/heatingCircuits/hc1/roomtemperature", "P1D"
        )

        assert isinstance(recording, RecordingResource)
        assert recording.series[0].sample_rate == "P1D"
        assert gateway.queries[0] == {"sampleRate": "P1D"}

    async def test_date_bounds_are_forwarded(self, gateway: FakeGateway, client: K40Client) -> None:
        payload = load("recordings_heatingCircuits_hc1_roomtemperature_sampleRate_P1D")
        gateway.route("/recordings/x", payload=payload)
        await client.async_get_recording(
            "/recordings/x", "P1D", start_date="2026-01-01", end_date="2026-01-31"
        )
        assert gateway.queries[0] == {
            "sampleRate": "P1D",
            "startDate": "2026-01-01",
            "endDate": "2026-01-31",
        }

    async def test_unknown_sample_rate_is_rejected_before_the_request(
        self, gateway: FakeGateway, client: K40Client
    ) -> None:
        with pytest.raises(ValueError, match="sample_rate"):
            await client.async_get_recording("/recordings/x", "p1d")
        assert not gateway.paths

    async def test_a_non_recording_response_raises(
        self, gateway: FakeGateway, client: K40Client
    ) -> None:
        gateway.route(
            "/recordings/x", payload={"id": "/recordings/x", "type": "stringValue", "value": "x"}
        )
        with pytest.raises(K40ResponseError):
            await client.async_get_recording("/recordings/x", "P1D")


class TestDiscovery:
    """Which branches this particular installation implements."""

    async def test_installation_reflects_what_answers(
        self, gateway: FakeGateway, client: K40Client
    ) -> None:
        # The API has no container resource, so presence is read off the
        # leaves: these are the paths a single-circuit heat pump answers.
        for path in (
            "/heatSources/hs1/numberOfStarts",
            "/heatingCircuits/hc1/currentRoomSetpoint",
            "/dhwCircuits/dhw1/actualTemp",
            "/ventilation/zone1/operationMode",
        ):
            gateway.route(path, payload={"id": path, "type": "integerValue", "value": 1})
        gateway.route("/signals", payload=load("signals"))

        installation = await client.async_discover_installation()

        assert installation.heat_sources == ("hs1",)
        assert installation.heating_circuits == ("hc1",)
        assert installation.dhw_circuits == ("dhw1",)
        assert installation.solar_circuits == ()
        assert installation.ventilation_zones == ("zone1",)
        assert installation.zones == ()
        assert installation.devices == ()
        assert installation.has_ventilation
        assert len(installation.signals) > 50

    async def test_any_probe_path_is_enough(self, gateway: FakeGateway, client: K40Client) -> None:
        # A gas boiler has no pumpVolumeFlow; the later probe path still finds it.
        gateway.route(
            "/heatSources/hs2/actualPower",
            payload={"id": "/heatSources/hs2/actualPower", "type": "floatValue", "value": 4.0},
        )
        installation = await client.async_discover_installation()
        assert installation.heat_sources == ("hs2",)

    async def test_a_cascade_of_heat_sources_is_found(
        self, gateway: FakeGateway, client: K40Client
    ) -> None:
        for index in (1, 2, 3):
            path = f"/heatSources/hs{index}/numberOfStarts"
            gateway.route(path, payload={"id": path, "type": "integerValue", "value": 0})
        installation = await client.async_discover_installation()
        assert installation.heat_sources == ("hs1", "hs2", "hs3")

    async def test_zones_and_devices_can_be_skipped(
        self, gateway: FakeGateway, client: K40Client
    ) -> None:
        # They are the expensive half of the probe: 16 and 32 candidate ids.
        await client.async_discover_installation(include_zones=False, include_devices=False)
        assert not any(path.startswith("/zones/") for path in gateway.paths)
        assert not any(path.startswith("/devices/") for path in gateway.paths)

    async def test_zones_are_found_when_asked_for(
        self, gateway: FakeGateway, client: K40Client
    ) -> None:
        gateway.route(
            "/zones/zone3/name",
            payload={"id": "/zones/zone3/name", "type": "stringValue", "value": "Kitchen"},
        )
        installation = await client.async_discover_installation(include_devices=False)
        assert installation.zones == ("zone3",)

    async def test_an_installation_with_nothing_optional_is_fine(
        self, gateway: FakeGateway, client: K40Client
    ) -> None:
        installation = await client.async_discover_installation()
        assert installation.heat_sources == ()
        assert not installation.has_ventilation
        assert installation.signals == ()

    async def test_a_gateway_without_signals_is_fine(self, client: K40Client) -> None:
        assert await client.async_get_signals() == ()

    async def test_a_wrong_signals_type_raises(
        self, gateway: FakeGateway, client: K40Client
    ) -> None:
        gateway.route("/signals", payload={"id": "/signals", "type": "stringValue", "value": "x"})
        with pytest.raises(K40ResponseError):
            await client.async_get_signals()


async def test_system_info_is_distilled(gateway: FakeGateway, client: K40Client) -> None:
    gateway.route("/system/basicInfo", payload=load("system_basicInfo"))
    info = await client.async_get_system_info()

    assert info.gateway_id == "100000001"
    assert info.product_name
    assert info.serial_number


async def test_client_works_as_a_context_manager(
    gateway: FakeGateway, session: aiohttp.ClientSession
) -> None:
    async with make_client(gateway, session) as client:
        assert client.host == HOST
    # The injected session must outlive the client.
    assert not session.closed


class TestErrorDetail:
    """A rejection the user cannot diagnose is a dead end."""

    async def test_the_gateways_reason_reaches_the_error(
        self, gateway: FakeGateway, client: K40Client
    ) -> None:
        gateway.route("/gateway/brand", status=403, payload={"error": "token_expired"})
        with pytest.raises(K40AuthError, match="token_expired"):
            await client.async_get("/gateway/brand")

    async def test_the_status_code_is_named(self, gateway: FakeGateway, client: K40Client) -> None:
        gateway.route("/gateway/brand", status=401, payload={})
        with pytest.raises(K40AuthError, match="401"):
            await client.async_get("/gateway/brand")

    async def test_a_silent_rejection_still_names_the_path(
        self, gateway: FakeGateway, client: K40Client
    ) -> None:
        gateway.route("/gateway/brand", status=401, body="", content_type="text/plain")
        with pytest.raises(K40AuthError, match="/gateway/brand"):
            await client.async_get("/gateway/brand")

    async def test_other_failures_carry_the_body_too(
        self, gateway: FakeGateway, client: K40Client
    ) -> None:
        gateway.route("/gateway/brand", status=500, payload={"error": "overloaded"})
        with pytest.raises(K40ResponseError, match="overloaded"):
            await client.async_get("/gateway/brand")

    async def test_the_documented_accept_header_is_sent(
        self, gateway: FakeGateway, client: K40Client
    ) -> None:
        gateway.route("/gateway/brand", payload={"id": "/x", "type": "stringValue", "value": "B"})
        await client.async_get("/gateway/brand")
        assert gateway.accepts == ["application/json"]
