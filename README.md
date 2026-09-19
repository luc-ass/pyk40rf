# pyk40rf

Async client for the local API of the **Bosch Connect-Key K 40 RF** heating
gateway (also sold under the Buderus brand). Read-only, no Home Assistant
dependency.

From firmware `15.00.01` the gateway serves a token-authenticated REST API on
the local network. This library speaks it.

> [!WARNING]
> **Beta — version 0.1.4.**
>
> Verified against two gateways and two heating systems, both air-to-water
> heat pumps with a single heating circuit — one Bosch, one Buderus. The API
> covers installations this library has never seen: solar circuits, pool
> heating, cascades of up to six heat sources. Those paths follow the
> published specification but are untested.
>
> The public interface may still change between 0.x releases. Pin an exact
> version.

> [!NOTE]
> **Not affiliated with Bosch.**
>
> This is an independent, community-built project. It is not affiliated with,
> endorsed by, supported by or otherwise connected to Bosch Thermotechnik GmbH,
> the Bosch Home Comfort Group, or Buderus. "Bosch", "Buderus" and
> "Connect-Key" are trademarks of their respective owners and appear here only
> to say which hardware this library talks to.
>
> It is built against the OpenAPI description Bosch publishes at
> [bosch-home-comfort/api-docs](https://github.com/bosch-home-comfort/api-docs)
> (Apache-2.0), extended by what a live gateway reports for the `/signals`
> branch, which that description does not cover. No firmware was modified and
> nothing is bypassed: the gateway hands out the access token itself, to
> whoever can press its buttons.
>
> Using it is at your own risk. See [LICENSE](LICENSE).

## Install

Not on PyPI yet:

```bash
pip install git+https://github.com/luc-ass/pyk40rf@v0.1.4
```

## Use

```python
import aiohttp
from pyk40rf import K40Client, NumericResource

async with aiohttp.ClientSession() as session:
    client = K40Client("192.168.1.50", session)

    # Once, with the device's WLAN + radio buttons just pressed, from its subnet:
    token = await client.async_request_token("100000001", "aaaa-bbbb-cccc-dddd")

    outdoor = await client.async_get("/system/sensors/temperatures/outdoor_t1")
    assert isinstance(outdoor, NumericResource)
    print(outdoor.value, outdoor.unit)   # 13.0 C
```

Keep `token.access_token` -- it does not expire, and reading afterwards works
from anywhere on the network.

## What the API is like

**Getting a token needs physical proximity.** Both conditions must hold or the
gateway answers `412 physical_proximity_unproven`: the WLAN and radio buttons
were pressed within the last few minutes, *and* the request comes from the
gateway's own subnet. Only the token request is gated; reads are not.

**TLS is self-signed.** The leaf's common name is the numeric device id, so
hostname verification cannot succeed. Either leave `verify_ssl=False` (the
default) or pin the certificate:

```python
client = K40Client(host, session, fingerprint=bytes.fromhex("b877a5..."))
```

**Ports.** `9442` serves the token endpoint and is always open; `9443` serves
the data API and stays closed until the gateway has been paired once.

**Discovery.** The gateway announces `_hvac-open-api._tcp` and
`_gateway-tt-local-api._tcp` over mDNS, with an instance name of
`K40RF-<device id>`. That id is also the auth username, so discovery can
prefill the login:

```python
from pyk40rf import device_id_from_zeroconf_name, parse_sticker_qr

device_id_from_zeroconf_name("K40RF-100000001._hvac-open-api._tcp.local.")
parse_sticker_qr("V:1;L:100000001;P:aaaa-bbbb-cccc-dddd;MAC:...;N:K40RF")
```

## Two things that are easy to get wrong

### `state` means three different things

On the **static endpoints** it is a list of error sentinels, and a reading
equal to one of them is not a measurement:

```json
{"value": 36.0, "state": [{"open": -32768.0}, {"short": 32767.0}]}
```

Those become `value=None` with `error_label` set, so nothing ever reports
-32768 °C.

On the **`/signals` branch** it is a *label map*, and the same JSON shape has
two meanings. On a signal with no unit it is an enumeration, not a fault list:

```json
{"value": 1, "state": {"HEATING": 1, "COOLING": 3, "IDLE": 2}}
```

Nulling those would throw away the actual reading. They are decoded instead:

```python
resource.value    # 1
resource.label    # "HEATING"
resource.options  # ("HEATING", "IDLE", "COOLING")
resource.is_enum  # True
```

On a signal that **carries a unit** the same map names the codes the reading
takes instead of a value -- it is a measurement, not an enumeration:

```json
{"value": 0, "unitOfMeasure": "C", "state": {"OFF_COOL": 90, "OFF_HEAT": 0}}
```

That is a flow setpoint in °C, reporting that the circuit is off. Read as an
enumeration it looks right at rest and then returns nothing for every real
setpoint, because 35 °C matches no label. So the label replaces the value here,
exactly as in the sentinel list:

```python
resource.value    # None, while the circuit is idle
resource.label    # "OFF_HEAT"
resource.is_enum  # False -- it is a temperature
```

Labels that name a fault (`NA_OPEN`, `NA_SHORT`, `LOW_FLOW`, `INVALID`, ...)
null the value in every form, and are kept out of `options`. The *shape* of the
field decides between the list and the map, and the unit decides what the map
means -- neither is a property of the path.

### Installations differ

The published spec declares 261 paths covering every possible installation --
up to six heat sources, four heating circuits, solar, pool. A given device
implements a subset and answers `404` for the rest. Probe rather than assume:

```python
installation = await client.async_discover_installation()
installation.heat_sources      # ("hs1",)
installation.heating_circuits  # ("hc1",)
installation.solar_circuits    # ()
installation.has_ventilation   # True
```

`async_get_many()` follows the same rule: resources that 404 are dropped from
the result, everything else propagates.

## History

`/recordings/...` needs a `sampleRate` (`PT1H`, `P1D`, `P1M` or `all`) and
answers `400` without one. Buckets carry a sum and a count, not a mean:

```python
recording = await client.async_get_recording("/recordings/...", "P1D")
bucket = recording.series[0].buckets[0]
bucket.average  # total / count, or None for an empty bucket
```

Bucket timestamps are derived by stepping the sample rate from the series
start and keep that start's UTC offset. Across a DST change the offset goes
stale by an hour; re-localize if you know the installation's timezone.

## Errors

| Exception | Meaning |
|---|---|
| `K40ProximityError` | `412` -- press the buttons, and be on the same subnet |
| `K40AuthError` | credentials or token rejected (`400`/`401`/`403`) |
| `K40NotFoundError` | `404` -- this installation does not have that resource |
| `K40ConnectionError` | the gateway was unreachable |
| `K40ResponseError` | the gateway answered with something unparseable |

All of them derive from `K40Error`; `K40ProximityError` is a subclass of
`K40AuthError`.

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check src tests
mypy src/pyk40rf
```

Tests run against real responses from a live device, curated and redacted into
`tests/fixtures/`. To refresh them from your own harvest:

```bash
python tests/make_fixtures.py path/to/responses/owner
```

The HTTP tests serve those fixtures from a real aiohttp server behind a
self-signed certificate, so the client's TLS handling, bearer headers and query
strings are exercised rather than mocked.

## License

Apache-2.0
