"""Curate a redacted fixture set from a live harvest.

The raw harvest in ``recon/responses/owner/`` is device specific and stays out
of version control. This copies a representative subset into ``fixtures/`` and
scrubs the identifying values, so the test suite ships real response shapes
without shipping one household's data.

Usage:
    python tests/make_fixtures.py [path/to/recon/responses/owner]
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys
from typing import Any

HERE = Path(__file__).parent
OUT = HERE / "fixtures"
DEFAULT_SOURCE = HERE / "../../../recon/responses/owner"

#: One file per response type, plus every distinct ``state`` shape.
WANTED = [
    # numeric, classic sentinel list
    "heatSources_returnTemperature.json",
    "heatSources_hs1_pumpVolumeFlow.json",
    "heatSources_systemPressure.json",
    "heatingCircuits_hc1_currentRoomSetpoint.json",
    "ventilation_zone1_sensors_internalAirQuality.json",
    # numeric, no state at all
    "heatSources_compressor_powerElecActual.json",
    # emonValue that carries no unit
    "heatSources_hs1_numberOfStarts.json",
    # string
    "heatSources_flameStatus.json",
    # energy
    "heatSources_emon_dhwConsumption.json",
    "heatSources_emon_totalConsumption.json",
    # history
    "recordings_heatingCircuits_hc1_roomtemperature_sampleRate_P1D.json",
    # structural
    "system_basicInfo.json",
    "notifications.json",
    "zones_configuration.json",
    "gateway_wifi_apList.json",
    "heatSources_actualHeatDemand.json",
    # the signals branch: enum maps, not sentinel lists
    "signals.json",
    "signals/SC.SeasonOpt.Mode.json",
    "signals/SRC.HC1.FlowCtrl.PumpRequest.json",
    "signals/SRC.OutdoorTemp.json",
    "signals/SRC.HC1.FlowCtrl.PumpVolumeFlow.json",
    "signals/SC.HC1.DewPointTemperature.json",
    "signals/VENTILATION.BasicFunction.VENT1.CurOpMode.json",
    "signals/GWEEBUS.Status.json",
    "signals/SC.HC1.RTSD.CurrentRoomTempSetp.json",
]

FAKE_GATEWAY_ID = "100000001"
_IPV4 = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
_MAC = re.compile(r"\b(?:[0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}\b")
_SERIAL_KEYS = {"ProductSerialNumber", "ModuleSerialNumber"}


def gateway_id(source: Path) -> str | None:
    """Read the gateway's own id out of the harvest.

    Taking it from the data rather than hard-coding it keeps this script from
    carrying one household's device id in a public repository.
    """
    basic = source / "system_basicInfo.json"
    if not basic.is_file():
        return None
    try:
        payload = json.loads(basic.read_text())
    except ValueError:
        return None
    found = payload.get("gatewayId")
    return str(found) if found else None


def scrub(value: Any, key: str | None = None, device_id: str | None = None) -> Any:
    """Replace device-identifying values, keeping shapes and lengths intact."""
    if isinstance(value, dict):
        return {k: scrub(v, k, device_id) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v, None, device_id) for v in value]
    if isinstance(value, str):
        if key in _SERIAL_KEYS and value:
            return "0" * len(value)
        text = _IPV4.sub("192.0.2.10", value)
        text = _MAC.sub("00:11:22:33:44:55", text)
        return text.replace(device_id, FAKE_GATEWAY_ID) if device_id else text
    return value


def main() -> int:
    """Copy and scrub the wanted fixtures."""
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SOURCE
    source = source.resolve()
    if not source.is_dir():
        print(f"no harvest at {source}", file=sys.stderr)
        return 1

    device_id = gateway_id(source)
    if device_id is None:
        print("  no gatewayId in the harvest; ids will not be scrubbed", file=sys.stderr)

    OUT.mkdir(parents=True, exist_ok=True)
    written = missing = 0
    for name in WANTED:
        origin = source / name
        if not origin.is_file():
            print(f"  missing: {name}", file=sys.stderr)
            missing += 1
            continue
        payload = scrub(json.loads(origin.read_text()), None, device_id)
        target = OUT / name.replace("/", "__")
        target.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
        written += 1

    print(f"{written} fixtures written to {OUT}" + (f", {missing} missing" if missing else ""))
    return 0 if not missing else 1


if __name__ == "__main__":
    raise SystemExit(main())
