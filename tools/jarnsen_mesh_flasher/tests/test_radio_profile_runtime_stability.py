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


def test_profile_identity_ignores_local_desired_hops() -> None:
    # Exact state observed on the physical Build 185 Tracker: J1 is loaded with
    # hop=3 while the PC-side settings can request a different hop count.
    lora = {
        "region": "US",
        "overrideFrequency": 915.625,
        "hopLimit": 3,
        "usePreset": True,
        "overrideDutyCycle": True,
    }
    settings = _settings(jarnsen_1_hops=10)
    assert runtime._infer_profile_from_lora(settings, lora) == "jarnsen1"
    assert runtime._lora_matches_desired_profile(settings, lora, "jarnsen1") is False


def test_desired_profile_validation_accepts_exact_slot_contents() -> None:
    lora = {
        "region": "US",
        "overrideFrequency": 915.625,
        "hopLimit": 3,
        "usePreset": True,
        "modemPreset": "LONG_FAST",
        "overrideDutyCycle": True,
        "txPower": 30,
    }
    settings = _settings(jarnsen_1_hops=3)
    assert runtime._infer_profile_from_lora(settings, lora) == "jarnsen1"
    assert runtime._lora_matches_desired_profile(settings, lora, "jarnsen1") is True


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


def test_identity_is_independent_from_desired_modem_but_strict_check_is_not() -> None:
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

    assert runtime._infer_profile_from_lora(settings, omitted) == "jarnsen1"
    assert runtime._infer_profile_from_lora(settings, matching) == "jarnsen1"
    assert runtime._infer_profile_from_lora(settings, wrong) == "jarnsen1"

    assert runtime._lora_matches_desired_profile(settings, omitted, "jarnsen1") is False
    assert runtime._lora_matches_desired_profile(settings, matching, "jarnsen1") is True
    assert runtime._lora_matches_desired_profile(settings, wrong, "jarnsen1") is False


def test_fixed_frequencies_keep_profile_identity_unambiguous() -> None:
    settings = _settings(
        # Persisted frequency fields are compatibility-only; validation restores
        # the fixed J1/J2 frequencies, so local settings cannot alias slot IDs.
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
    assert runtime._infer_profile_from_lora(settings, lora) == "jarnsen1"
