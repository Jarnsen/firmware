from __future__ import annotations

import radio_profile_runtime_stability as runtime


def _settings(**overrides):
    values = {
        "selected": "standard",
        "jarnsen_1_mhz": "915.625",
        "jarnsen_2_mhz": "917.375",
        "jarnsen_1_hops": 10,
        "jarnsen_2_hops": 3,
        "jarnsen_1_modem_preset": "LONG_FAST",
        "jarnsen_2_modem_preset": "LONG_FAST",
    }
    values.update(overrides)
    return values


def test_infers_jarnsen1_from_real_build185_lora_state() -> None:
    lora = {
        "region": "US",
        "overrideFrequency": 915.625,
        "hopLimit": 10,
        "usePreset": True,
        # LONG_FAST can be protobuf-omitted as the default enum value.
        "overrideDutyCycle": True,
        "txPower": 30,
    }
    assert runtime._infer_profile_from_lora(_settings(), lora) == "jarnsen1"


def test_infers_jarnsen2_with_snake_case_aliases() -> None:
    lora = {
        "region": "US",
        "override_frequency": 917.375,
        "hop_limit": 3,
        "use_preset": True,
        "modem_preset": "LONG_FAST",
        "override_duty_cycle": True,
        "tx_power": 30,
    }
    assert runtime._infer_profile_from_lora(_settings(), lora) == "jarnsen2"


def test_tx_normalization_does_not_break_profile_inference() -> None:
    base = {
        "region": "US",
        "overrideFrequency": 915.625,
        "hopLimit": 10,
        "usePreset": True,
        "overrideDutyCycle": True,
    }
    for tx_power in (0, 20, 30):
        lora = dict(base, txPower=tx_power)
        assert runtime._infer_profile_from_lora(_settings(), lora) == "jarnsen1"


def test_does_not_infer_when_hops_do_not_match_saved_profile() -> None:
    lora = {
        "region": "US",
        "overrideFrequency": 915.625,
        "hopLimit": 3,
        "usePreset": True,
        "overrideDutyCycle": True,
    }
    assert runtime._infer_profile_from_lora(_settings(), lora) == "standard"


def test_does_not_infer_wrong_region_or_frequency() -> None:
    wrong_region = {
        "region": "EU_868",
        "overrideFrequency": 915.625,
        "hopLimit": 10,
        "usePreset": True,
        "overrideDutyCycle": True,
    }
    wrong_frequency = {
        "region": "US",
        "overrideFrequency": 916.0,
        "hopLimit": 10,
        "usePreset": True,
        "overrideDutyCycle": True,
    }
    assert runtime._infer_profile_from_lora(_settings(), wrong_region) == "standard"
    assert runtime._infer_profile_from_lora(_settings(), wrong_frequency) == "standard"


def test_does_not_infer_when_duty_or_preset_contract_is_wrong() -> None:
    duty_limited = {
        "region": "US",
        "overrideFrequency": 915.625,
        "hopLimit": 10,
        "usePreset": True,
        "overrideDutyCycle": False,
    }
    custom_modem = {
        "region": "US",
        "overrideFrequency": 915.625,
        "hopLimit": 10,
        "usePreset": False,
        "overrideDutyCycle": True,
    }
    assert runtime._infer_profile_from_lora(_settings(), duty_limited) == "standard"
    assert runtime._infer_profile_from_lora(_settings(), custom_modem) == "standard"


def test_non_default_modem_requires_matching_exported_value() -> None:
    settings = _settings(jarnsen_1_modem_preset="MEDIUM_FAST")
    omitted = {
        "region": "US",
        "overrideFrequency": 915.625,
        "hopLimit": 10,
        "usePreset": True,
        "overrideDutyCycle": True,
    }
    matching = dict(omitted, modemPreset="MEDIUM_FAST")
    wrong = dict(omitted, modemPreset="SHORT_FAST")
    assert runtime._infer_profile_from_lora(settings, omitted) == "standard"
    assert runtime._infer_profile_from_lora(settings, matching) == "jarnsen1"
    assert runtime._infer_profile_from_lora(settings, wrong) == "standard"


def test_ambiguous_custom_profiles_fail_closed_to_standard() -> None:
    settings = _settings(
        jarnsen_1_mhz="915.625",
        jarnsen_2_mhz="915.625",
        jarnsen_1_hops=10,
        jarnsen_2_hops=10,
    )
    lora = {
        "region": "US",
        "overrideFrequency": 915.625,
        "hopLimit": 10,
        "usePreset": True,
        "overrideDutyCycle": True,
    }
    assert runtime._infer_profile_from_lora(settings, lora) == "standard"
