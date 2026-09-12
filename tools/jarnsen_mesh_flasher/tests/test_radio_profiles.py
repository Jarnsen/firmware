from __future__ import annotations

import copy

import pytest
import radio_profiles


def _base(region: str = "EU_868") -> dict:
    return {
        "config": {
            "device": {"role": "TRACKER"},
            "lora": {
                "region": region,
                "hop_limit": 5,
                "tx_power": 22,
                "override_frequency": 868.5,
                "override_duty_cycle": False,
                "use_preset": True,
                "modem_preset": "MEDIUM_FAST",
            },
        }
    }


def test_defaults_define_fixed_jarnsen_frequencies_and_modems() -> None:
    checked = radio_profiles.validate_settings({"selected": "standard"})
    assert checked["jarnsen_1_mhz"] == "915.625"
    assert checked["jarnsen_2_mhz"] == "917.375"
    assert checked["jarnsen_1_modem_preset"] == "LONG_FAST"
    assert checked["jarnsen_2_modem_preset"] == "LONG_FAST"
    assert checked["standard_hops"] == 7
    assert checked["jarnsen_1_hops"] == 20
    assert checked["jarnsen_2_hops"] == 20


def test_standard_uses_its_own_hops_and_normal_radio_rules() -> None:
    data = _base()
    result = radio_profiles.apply_overlay(
        data,
        {
            "selected": "standard",
            "standard_hops": 4,
            "jarnsen_1_hops": 11,
            "jarnsen_2_hops": 15,
            "jarnsen_1_modem_preset": "LONG_FAST",
            "jarnsen_2_modem_preset": "SHORT_FAST",
        },
    )
    assert result["config"]["lora"]["override_frequency"] == 0.0
    assert result["config"]["lora"]["hop_limit"] == 4
    assert result["config"]["lora"]["override_duty_cycle"] is False
    assert result["config"]["device"]["role"] == "TRACKER"
    assert result["config"]["lora"]["tx_power"] == 22
    assert result["config"]["lora"]["modem_preset"] == "MEDIUM_FAST"
    assert result["config"]["lora"]["use_preset"] is True


def test_standard_hops_are_capped_at_seven() -> None:
    result = radio_profiles.validate_settings(
        {"selected": "standard", "standard_hops": 99}
    )
    assert result["standard_hops"] == 7
    assert radio_profiles.hop_values("standard") == [
        str(value) for value in range(1, 8)
    ]


def test_jarnsen_1_uses_fixed_frequency_fixed_hops_and_selected_modem() -> None:
    data = _base("US")
    original = copy.deepcopy(data)
    result = radio_profiles.apply_overlay(
        data,
        {
            "selected": "jarnsen1",
            "standard_hops": 3,
            "jarnsen_1_hops": 12,
            "jarnsen_2_hops": 18,
            "jarnsen_1_modem_preset": "MEDIUM_FAST",
            "jarnsen_2_modem_preset": "SHORT_FAST",
        },
    )
    assert result["config"]["lora"]["override_frequency"] == 915.625
    assert result["config"]["lora"]["hop_limit"] == 20
    assert result["config"]["lora"]["override_duty_cycle"] is True
    assert result["config"]["lora"]["tx_power"] == 0
    assert result["config"]["lora"]["use_preset"] is True
    assert result["config"]["lora"]["modem_preset"] == "MEDIUM_FAST"
    assert result["config"]["device"]["role"] == original["config"]["device"]["role"]
    assert data == original


def test_jarnsen_2_uses_fixed_frequency_own_hops_and_modem() -> None:
    result = radio_profiles.apply_overlay(
        _base("US"),
        {
            "selected": "jarnsen2",
            "standard_hops": 3,
            "jarnsen_1_hops": 9,
            "jarnsen_2_hops": 17,
            "jarnsen_1_modem_preset": "LONG_FAST",
            "jarnsen_2_modem_preset": "SHORT_SLOW",
        },
    )
    assert result["config"]["lora"]["override_frequency"] == 917.375
    assert result["config"]["lora"]["hop_limit"] == 20
    assert result["config"]["lora"]["override_duty_cycle"] is True
    assert result["config"]["lora"]["tx_power"] == 0
    assert result["config"]["lora"]["use_preset"] is True
    assert result["config"]["lora"]["modem_preset"] == "SHORT_SLOW"


def test_jarnsen_hops_are_forced_to_twenty() -> None:
    low = radio_profiles.validate_settings(
        {"selected": "jarnsen1", "jarnsen_1_hops": 5}
    )
    high = radio_profiles.validate_settings(
        {"selected": "jarnsen1", "jarnsen_1_hops": 99}
    )
    assert low["jarnsen_1_hops"] == 20
    assert high["jarnsen_1_hops"] == 20
    assert radio_profiles.hop_values("jarnsen1") == ["20"]


def test_modem_preset_list_tracks_current_firmware_enum() -> None:
    assert "Long Fast" in radio_profiles.modem_preset_values()
    assert "Medium Fast" in radio_profiles.modem_preset_values()
    assert "Short Fast" in radio_profiles.modem_preset_values()
    assert "Long Turbo" in radio_profiles.modem_preset_values()
    assert "Narrow Slow" in radio_profiles.modem_preset_values()
    assert "Medium Turbo" in radio_profiles.modem_preset_values()


def test_invalid_modem_preset_falls_back_to_long_fast() -> None:
    checked = radio_profiles.validate_settings(
        {
            "selected": "jarnsen1",
            "jarnsen_1_modem_preset": "does-not-exist",
        }
    )
    assert checked["jarnsen_1_modem_preset"] == "LONG_FAST"


def test_eu868_rejects_fixed_jarnsen_frequencies() -> None:
    with pytest.raises(ValueError, match="Frequenzzuteilung"):
        radio_profiles.apply_overlay(
            _base("EU_868"),
            {"selected": "jarnsen1", "jarnsen_1_hops": 7},
        )


def test_us_region_accepts_both_fixed_jarnsen_frequencies() -> None:
    j1 = radio_profiles.apply_overlay(_base("US"), {"selected": "jarnsen1"})
    j2 = radio_profiles.apply_overlay(_base("US"), {"selected": "jarnsen2"})
    assert j1["config"]["lora"]["override_frequency"] == 915.625
    assert j2["config"]["lora"]["override_frequency"] == 917.375


def test_allocation_summaries() -> None:
    assert radio_profiles.allocation_summary("EU_868") == "EU_868 · 869.400-869.650 MHz"
    assert radio_profiles.allocation_summary("US") == "US · 902.000-928.000 MHz"
