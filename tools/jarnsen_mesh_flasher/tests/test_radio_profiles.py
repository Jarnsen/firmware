from __future__ import annotations

import copy

import pytest

import radio_profiles


def _base() -> dict:
    return {
        "config": {
            "device": {"role": "TRACKER"},
            "lora": {
                "region": "EU_868",
                "hop_limit": 5,
                "tx_power": 22,
                "override_frequency": 868.5,
                "override_duty_cycle": False,
            },
        }
    }


def test_standard_disables_frequency_override_and_caps_hops() -> None:
    data = _base()
    data["config"]["lora"]["hop_limit"] = 20
    result = radio_profiles.apply_overlay(data, {"selected": "standard"})
    assert result["config"]["lora"]["override_frequency"] == 0.0
    assert result["config"]["lora"]["hop_limit"] == 7
    assert result["config"]["lora"]["override_duty_cycle"] is False
    assert result["config"]["device"]["role"] == "TRACKER"
    assert result["config"]["lora"]["tx_power"] == 22


def test_standard_preserves_lower_hop_limit() -> None:
    data = _base()
    data["config"]["lora"]["hop_limit"] = 3
    result = radio_profiles.apply_overlay(data, {"selected": "standard"})
    assert result["config"]["lora"]["hop_limit"] == 3


def test_jarnsen_1_sets_exact_frequency_and_preserves_lower_hops() -> None:
    data = _base()
    original = copy.deepcopy(data)
    result = radio_profiles.apply_overlay(
        data,
        {
            "selected": "jarnsen1",
            "jarnsen_1_mhz": "915,125",
            "jarnsen_2_mhz": "916.250",
        },
    )
    assert result["config"]["lora"]["override_frequency"] == 915.125
    assert result["config"]["lora"]["hop_limit"] == 5
    assert result["config"]["lora"]["override_duty_cycle"] is True
    assert result["config"]["lora"]["tx_power"] == 0
    assert result["config"]["device"]["role"] == original["config"]["device"]["role"]
    assert data == original


def test_jarnsen_2_sets_its_frequency_and_max_auto_tx() -> None:
    result = radio_profiles.apply_overlay(
        _base(),
        {
            "selected": "jarnsen2",
            "jarnsen_1_mhz": "915.125",
            "jarnsen_2_mhz": "916.250",
        },
    )
    assert result["config"]["lora"]["override_frequency"] == 916.25
    assert result["config"]["lora"]["hop_limit"] == 5
    assert result["config"]["lora"]["override_duty_cycle"] is True
    assert result["config"]["lora"]["tx_power"] == 0


def test_jarnsen_caps_hops_at_twenty() -> None:
    data = _base()
    data["config"]["lora"]["hop_limit"] = 99
    result = radio_profiles.apply_overlay(
        data,
        {
            "selected": "jarnsen1",
            "jarnsen_1_mhz": "915.125",
            "jarnsen_2_mhz": "916.250",
        },
    )
    assert result["config"]["lora"]["hop_limit"] == 20


def test_selected_jarnsen_profile_requires_frequency() -> None:
    with pytest.raises(ValueError, match="Frequenz"):
        radio_profiles.validate_settings({"selected": "jarnsen1"})


def test_jarnsen_frequencies_must_differ() -> None:
    with pytest.raises(ValueError, match="unterschiedliche"):
        radio_profiles.validate_settings(
            {
                "selected": "standard",
                "jarnsen_1_mhz": "915.125",
                "jarnsen_2_mhz": "915,125",
            }
        )
