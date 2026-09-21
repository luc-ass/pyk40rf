"""Parser behaviour, checked against real device responses."""

from __future__ import annotations

import pytest

from pyk40rf import (
    EnergyResource,
    K40ResponseError,
    NumericResource,
    RawResource,
    RecordingResource,
    ReferenceList,
    StringResource,
    parse_resource,
    parse_system_info,
)

from .conftest import load


def test_float_with_sentinel_list_keeps_a_valid_reading() -> None:
    resource = parse_resource(load("heatSources_returnTemperature"))
    assert isinstance(resource, NumericResource)
    assert resource.value == 36.0
    assert resource.unit == "C"
    assert not resource.is_error
    assert not resource.is_enum


@pytest.mark.parametrize(
    ("name", "sentinel", "label"),
    [
        ("heatSources_returnTemperature", -32768.0, "open"),
        ("heatSources_returnTemperature", 32767.0, "short"),
        ("heatSources_hs1_pumpVolumeFlow", 65535, "lowflow"),
        ("heatSources_systemPressure", 255.0, "invalid"),
    ],
)
def test_sentinel_reading_becomes_none(name: str, sentinel: float, label: str) -> None:
    payload = load(name) | {"value": sentinel}
    resource = parse_resource(payload)
    assert isinstance(resource, NumericResource)
    assert resource.value is None
    assert resource.error_label == label
    assert resource.raw_value == sentinel
    assert resource.is_error


def test_non_fault_sentinel_nulls_the_value_but_is_not_an_error() -> None:
    # currentRoomSetpoint reports 0.0 with state [{"off": 0.0}]: the setpoint
    # is disabled, not faulty, and 0 C would be a lie either way.
    resource = parse_resource(load("heatingCircuits_hc1_currentRoomSetpoint"))
    assert isinstance(resource, NumericResource)
    assert resource.value is None
    assert resource.label == "off"
    assert resource.error_label is None
    assert not resource.is_error


def test_numeric_without_state_passes_through() -> None:
    resource = parse_resource(load("heatSources_compressor_powerElecActual"))
    assert isinstance(resource, NumericResource)
    assert resource.value == resource.raw_value
    assert resource.error_label is None


class TestSignalEnums:
    """The /signals branch ships label maps, not fault lists."""

    def test_enum_value_is_decoded_not_nulled(self) -> None:
        resource = parse_resource(load("signals__SC.SeasonOpt.Mode"))
        assert isinstance(resource, NumericResource)
        assert resource.value == 1
        assert resource.label == "HEATING"
        assert resource.is_enum
        assert resource.options == ("HEATING", "IDLE", "COOLING")

    def test_zero_is_a_real_state_not_a_sentinel(self) -> None:
        # OFF: 0 would be nulled by a naive "state means fault" reading.
        resource = parse_resource(load("signals__SRC.HC1.FlowCtrl.PumpRequest"))
        assert isinstance(resource, NumericResource)
        assert resource.value == 0
        assert resource.label == "OFF"
        assert not resource.is_error

    def test_fault_labels_in_an_enum_map_still_null(self) -> None:
        payload = load("signals__SRC.OutdoorTemp") | {"value": -3276.8}
        resource = parse_resource(payload)
        assert isinstance(resource, NumericResource)
        assert resource.value is None
        assert resource.error_label == "NA_OPEN"

    def test_pure_fault_map_is_not_an_enum(self) -> None:
        resource = parse_resource(load("signals__SC.HC1.DewPointTemperature"))
        assert isinstance(resource, NumericResource)
        assert resource.value == 12
        assert resource.options == ()
        assert not resource.is_enum

    def test_fault_label_is_split_out_of_a_mixed_map(self) -> None:
        # CurOpMode mixes operating modes with a SHORT fault label.
        resource = parse_resource(load("signals__VENTILATION.BasicFunction.VENT1.CurOpMode"))
        assert isinstance(resource, NumericResource)
        assert "SHORT" not in resource.options
        assert resource.options == ("UNDEFINED", "MANUAL", "TIME", "HOLIDAY")
        assert resource.label == "MANUAL"

    def test_a_measurement_is_not_an_enum_even_with_a_label_map(self) -> None:
        # SC.HC1.FlowTempSetp is a flow setpoint in C whose map names the two
        # codes it sends while idle. Reading it as an enumeration would null
        # every real setpoint, since 35 C matches no label.
        payload = load("signals__SC.HC1.FlowTempSetp") | {"value": 35}
        resource = parse_resource(payload)
        assert isinstance(resource, NumericResource)
        assert resource.value == 35
        assert resource.unit == "C"
        assert not resource.is_enum
        assert resource.options == ()

    def test_a_measurements_code_replaces_the_reading(self) -> None:
        resource = parse_resource(load("signals__SC.HC1.FlowTempSetp"))
        assert isinstance(resource, NumericResource)
        assert resource.value is None
        assert resource.label == "OFF_HEAT"
        assert not resource.is_error

    def test_a_disabled_setpoint_does_not_report_zero_degrees(self) -> None:
        # {"OFF": 0.0} on a room setpoint: 0 C is the code for off, not a
        # temperature anyone should see on a dashboard.
        resource = parse_resource(load("signals__SC.HC1.RTSD.CurrentRoomTempSetp"))
        assert isinstance(resource, NumericResource)
        assert resource.value is None
        assert resource.label == "OFF"
        assert not resource.is_enum

    def test_options_are_ordered_by_value(self) -> None:
        resource = parse_resource(load("signals__GWEEBUS.Status"))
        assert isinstance(resource, NumericResource)
        assert resource.options[0] == "Ok"
        assert resource.label == "Not_Commissioned"


def test_string_value_exposes_allowed_values() -> None:
    resource = parse_resource(load("heatSources_flameStatus"))
    assert isinstance(resource, StringResource)
    assert resource.value == "off"
    assert resource.options == ("off", "on")


def test_string_value_decodes_the_gateway_flag_words() -> None:
    """Most of the /signals branch is flags written as "true"/"false"."""
    for word, expected in (("true", True), ("false", False), ("TRUE", True), (" false ", False)):
        resource = parse_resource(
            {"id": "/signals/SRC.CUHP.HP1.CompressorStatus", "type": "stringValue", "value": word}
        )
        assert isinstance(resource, StringResource)
        assert resource.boolean is expected
        assert resource.is_boolean


def test_a_string_that_is_not_a_flag_stays_a_string() -> None:
    """An identity string must not be mistaken for a flag with a false value."""
    for word in ("", "off", "Not_Commissioned", "HomeAssistant-EEBUS-Bridge"):
        resource = parse_resource(
            {"id": "/signals/GWEEBUS.CEM.ID", "type": "stringValue", "value": word}
        )
        assert isinstance(resource, StringResource)
        assert resource.boolean is None
        assert not resource.is_boolean


def test_a_missing_string_is_not_a_flag() -> None:
    resource = parse_resource({"id": "/signals/x", "type": "stringValue", "value": None})
    assert isinstance(resource, StringResource)
    assert resource.boolean is None


def test_energy_splits_into_components() -> None:
    resource = parse_resource(load("heatSources_emon_totalConsumption"))
    assert isinstance(resource, EnergyResource)
    assert resource.unit == "kWh"
    assert "compressor" in resource.components
    assert "outputProduced" in resource.components
    assert all(isinstance(v, float) for v in resource.components.values())


def test_energy_allows_a_performance_factor() -> None:
    resource = parse_resource(load("heatSources_emon_totalConsumption"))
    assert isinstance(resource, EnergyResource)
    consumed = resource.components["compressor"] + resource.components["eheater"]
    assert resource.components["outputProduced"] / consumed > 1.0


class TestRecordings:
    """History buckets carry a sum and a count, not a mean."""

    def test_series_and_buckets_are_parsed(self) -> None:
        resource = parse_resource(
            load("recordings_heatingCircuits_hc1_roomtemperature_sampleRate_P1D")
        )
        assert isinstance(resource, RecordingResource)
        assert resource.unit == "C"
        assert resource.recorded_resource_id == "/heatingCircuits/hc1/roomtemperature"
        assert len(resource.series) == 1
        assert resource.series[0].sample_rate == "P1D"
        assert resource.series[0].buckets

    def test_average_is_sum_over_count(self) -> None:
        resource = parse_resource(
            load("recordings_heatingCircuits_hc1_roomtemperature_sampleRate_P1D")
        )
        assert isinstance(resource, RecordingResource)
        bucket = resource.series[0].buckets[0]
        assert bucket.average == pytest.approx(bucket.total / bucket.count)
        assert 5.0 < (bucket.average or 0) < 35.0

    def test_empty_bucket_has_no_average(self) -> None:
        resource = parse_resource(
            load("recordings_heatingCircuits_hc1_roomtemperature_sampleRate_P1D")
        )
        assert isinstance(resource, RecordingResource)
        empty = type(resource.series[0].buckets[0])(count=0, total=0.0)
        assert empty.average is None

    def test_bucket_starts_advance_by_the_sample_rate(self) -> None:
        resource = parse_resource(
            load("recordings_heatingCircuits_hc1_roomtemperature_sampleRate_P1D")
        )
        assert isinstance(resource, RecordingResource)
        series = resource.series[0]
        first, second = series.buckets[0], series.buckets[1]
        assert first.start == series.start_time
        assert second.start is not None
        assert first.start is not None
        assert (second.start - first.start).days == 1


def test_reference_list_lists_signal_ids() -> None:
    resource = parse_resource(load("signals"))
    assert isinstance(resource, ReferenceList)
    assert len(resource.references) > 50
    assert all(ref.startswith("/signals/") for ref in resource.references)


@pytest.mark.parametrize(
    "name",
    ["notifications", "zones_configuration", "gateway_wifi_apList", "heatSources_actualHeatDemand"],
)
def test_structural_types_fall_back_to_raw(name: str) -> None:
    resource = parse_resource(load(name))
    assert isinstance(resource, RawResource)
    assert resource.raw == load(name)


def test_system_info_yields_device_registry_material() -> None:
    info = parse_system_info(load("system_basicInfo"))
    assert info.gateway_id
    assert info.product_name
    assert info.serial_number
    assert info.modules


@pytest.mark.parametrize(
    "payload",
    [
        {"id": "/x"},
        {"id": "/x", "type": "floatValue"},
        {"id": "/x", "type": "floatValue", "value": "warm"},
    ],
)
def test_malformed_payloads_raise(payload: dict[str, object]) -> None:
    with pytest.raises(K40ResponseError):
        parse_resource(payload)
