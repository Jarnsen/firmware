from __future__ import annotations

import copy
import json
import re
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml


PROFILE_STANDARD = "standard"
PROFILE_JARNSEN_1 = "jarnsen1"
PROFILE_JARNSEN_2 = "jarnsen2"

PROFILE_LABELS = {
    PROFILE_STANDARD: "Standard",
    PROFILE_JARNSEN_1: "Jarnsen 1",
    PROFILE_JARNSEN_2: "Jarnsen 2",
}
PROFILE_KEYS_BY_LABEL = {label: key for key, label in PROFILE_LABELS.items()}
PROFILE_KEYS = tuple(PROFILE_LABELS)
CONFIG_FILENAME = "radio-profiles.json"

JARNSEN_FREQUENCIES: dict[str, Decimal] = {
    PROFILE_JARNSEN_1: Decimal("915.625"),
    PROFILE_JARNSEN_2: Decimal("917.375"),
}

HOP_KEYS = {
    PROFILE_STANDARD: "standard_hops",
    PROFILE_JARNSEN_1: "jarnsen_1_hops",
    PROFILE_JARNSEN_2: "jarnsen_2_hops",
}
HOP_MAX = {
    PROFILE_STANDARD: 7,
    PROFILE_JARNSEN_1: 20,
    PROFILE_JARNSEN_2: 20,
}

# Keep these canonical names in sync with the firmware's LoRaConfig.ModemPreset
# enum. The UI uses friendly labels, while persisted/YAML values stay canonical.
MODEM_PRESETS = (
    "LONG_FAST",
    "LONG_SLOW",
    "VERY_LONG_SLOW",
    "MEDIUM_SLOW",
    "MEDIUM_FAST",
    "SHORT_SLOW",
    "SHORT_FAST",
    "LONG_MODERATE",
    "SHORT_TURBO",
    "LONG_TURBO",
    "LITE_FAST",
    "LITE_SLOW",
    "NARROW_FAST",
    "NARROW_SLOW",
    "TINY_FAST",
    "TINY_SLOW",
    "MEDIUM_TURBO",
)
MODEM_LABELS = {
    "LONG_FAST": "Long Fast",
    "LONG_SLOW": "Long Slow",
    "VERY_LONG_SLOW": "Very Long Slow",
    "MEDIUM_SLOW": "Medium Slow",
    "MEDIUM_FAST": "Medium Fast",
    "SHORT_SLOW": "Short Slow",
    "SHORT_FAST": "Short Fast",
    "LONG_MODERATE": "Long Moderate",
    "SHORT_TURBO": "Short Turbo",
    "LONG_TURBO": "Long Turbo",
    "LITE_FAST": "Lite Fast",
    "LITE_SLOW": "Lite Slow",
    "NARROW_FAST": "Narrow Fast",
    "NARROW_SLOW": "Narrow Slow",
    "TINY_FAST": "Tiny Fast",
    "TINY_SLOW": "Tiny Slow",
    "MEDIUM_TURBO": "Medium Turbo",
}
MODEM_KEYS_BY_LABEL = {label: key for key, label in MODEM_LABELS.items()}
MODEM_SETTING_KEYS = {
    PROFILE_JARNSEN_1: "jarnsen_1_modem_preset",
    PROFILE_JARNSEN_2: "jarnsen_2_modem_preset",
}

# The flasher keeps a compatibility guard between an explicitly selected
# firmware region and a fixed-frequency radio profile. Unknown regions are left
# to the firmware; known incompatible combinations are rejected before erase.
REGION_FREQUENCY_BANDS: dict[str, tuple[Decimal, Decimal]] = {
    "EU_868": (Decimal("869.400"), Decimal("869.650")),
    "US": (Decimal("902.000"), Decimal("928.000")),
}


def _emit(message: str) -> None:
    try:
        import diagnostics

        diagnostics._emit(message)
    except Exception:
        pass


def _config_file(services: Any) -> Path:
    return Path(services.PATHS.root) / CONFIG_FILENAME


def _defaults() -> dict[str, Any]:
    return {
        "version": 3,
        "selected": PROFILE_STANDARD,
        # Kept in the persisted shape for backward compatibility and diagnostics,
        # but J1/J2 are fixed presets now rather than free-form text fields.
        "jarnsen_1_mhz": "915.625",
        "jarnsen_2_mhz": "917.375",
        "standard_hops": 7,
        # JARNSEN slots are designed for the extended mesh depth. Existing
        # saved settings still win, but new profiles start with the full limit.
        "jarnsen_1_hops": 20,
        "jarnsen_2_hops": 20,
        "jarnsen_1_modem_preset": "LONG_FAST",
        "jarnsen_2_modem_preset": "LONG_FAST",
    }


def _format_mhz(value: Decimal) -> str:
    return f"{value:.3f}"


def allocation_summary(region: Any) -> str:
    key = str(region or "").strip().upper()
    band = REGION_FREQUENCY_BANDS.get(key)
    if not band:
        return f"{key or 'Region unbekannt'} · keine Flasher-Zuteilung hinterlegt"
    start, end = band
    return f"{key} · {_format_mhz(start)}–{_format_mhz(end)} MHz"


def _validate_frequency_for_region(frequency: Decimal, region: Any, *, label: str) -> None:
    key = str(region or "").strip().upper()
    band = REGION_FREQUENCY_BANDS.get(key)
    if not band:
        return
    start, end = band
    if frequency < start or frequency > end:
        raise ValueError(
            f"{label}: {frequency} MHz liegt außerhalb der Frequenzzuteilung "
            f"{key} ({_format_mhz(start)}–{_format_mhz(end)} MHz)."
        )


def validate_frequency_for_region(frequency: Decimal, region: Any, *, label: str) -> None:
    _validate_frequency_for_region(frequency, region, label=label)


def _normalize_hops(value: Any, profile: str, *, default: int = 7) -> int:
    maximum = HOP_MAX[profile]
    try:
        hops = int(value)
    except Exception:
        hops = default
    return max(1, min(maximum, hops))


def hop_values(profile: str) -> list[str]:
    key = profile if profile in PROFILE_KEYS else PROFILE_STANDARD
    if key in {PROFILE_JARNSEN_1, PROFILE_JARNSEN_2}:
        return ["20"]
    return [str(value) for value in range(1, HOP_MAX[key] + 1)]


def _normalize_modem_preset(value: Any) -> str:
    text = str(value or "LONG_FAST").strip().upper().replace("-", "_").replace(" ", "_")
    return text if text in MODEM_PRESETS else "LONG_FAST"


def modem_preset_values() -> list[str]:
    return [MODEM_LABELS[key] for key in MODEM_PRESETS]


def modem_preset_for(settings: dict[str, Any], profile: str | None = None) -> str | None:
    checked = validate_settings(settings)
    key = profile or checked["selected"]
    setting_key = MODEM_SETTING_KEYS.get(key)
    if setting_key is None:
        return None
    return _normalize_modem_preset(checked.get(setting_key))


def hop_limit_for(settings: dict[str, Any], profile: str | None = None) -> int:
    checked = validate_settings(settings)
    key = profile or checked["selected"]
    if key not in PROFILE_KEYS:
        key = PROFILE_STANDARD
    if key in {PROFILE_JARNSEN_1, PROFILE_JARNSEN_2}:
        return 20
    return int(checked[HOP_KEYS[key]])


def load_settings(services: Any) -> dict[str, Any]:
    result = _defaults()
    path = _config_file(services)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            for key in result:
                if key in raw:
                    result[key] = raw[key]
    except FileNotFoundError:
        pass
    except Exception as exc:
        _emit(f"RADIO PROFILE LOAD ERROR type={type(exc).__name__} message={exc}")

    selected = str(result.get("selected") or PROFILE_STANDARD).strip().lower()
    result["selected"] = selected if selected in PROFILE_KEYS else PROFILE_STANDARD
    result["jarnsen_1_mhz"] = _format_mhz(JARNSEN_FREQUENCIES[PROFILE_JARNSEN_1])
    result["jarnsen_2_mhz"] = _format_mhz(JARNSEN_FREQUENCIES[PROFILE_JARNSEN_2])
    for profile, key in HOP_KEYS.items():
        result[key] = 20 if profile in {PROFILE_JARNSEN_1, PROFILE_JARNSEN_2} else _normalize_hops(result.get(key), profile)
    for profile, key in MODEM_SETTING_KEYS.items():
        result[key] = _normalize_modem_preset(result.get(key))
    result["version"] = 3
    return result


def save_settings(settings: dict[str, Any], services: Any) -> dict[str, Any]:
    current = load_settings(services)
    selected = str(settings.get("selected", current["selected"]) or PROFILE_STANDARD).strip().lower()
    current["selected"] = selected if selected in PROFILE_KEYS else PROFILE_STANDARD

    for profile, key in HOP_KEYS.items():
        current[key] = 20 if profile in {PROFILE_JARNSEN_1, PROFILE_JARNSEN_2} else _normalize_hops(settings.get(key, current[key]), profile)
    for profile, key in MODEM_SETTING_KEYS.items():
        current[key] = _normalize_modem_preset(settings.get(key, current[key]))

    current["jarnsen_1_mhz"] = _format_mhz(JARNSEN_FREQUENCIES[PROFILE_JARNSEN_1])
    current["jarnsen_2_mhz"] = _format_mhz(JARNSEN_FREQUENCIES[PROFILE_JARNSEN_2])
    current["version"] = 3

    path = _config_file(services)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)
    _emit(
        "RADIO PROFILE SAVE "
        f"selected={current['selected']} j1={current['jarnsen_1_mhz']} j2={current['jarnsen_2_mhz']} "
        f"hops=standard:{current['standard_hops']},j1:{current['jarnsen_1_hops']},j2:{current['jarnsen_2_hops']} "
        f"modem=j1:{current['jarnsen_1_modem_preset']},j2:{current['jarnsen_2_modem_preset']}"
    )
    return current


def validate_settings(settings: dict[str, Any]) -> dict[str, Any]:
    checked = _defaults()
    checked.update(settings or {})
    selected = str(checked.get("selected") or PROFILE_STANDARD).strip().lower()
    if selected not in PROFILE_KEYS:
        raise ValueError(f"Unbekanntes Funkprofil: {selected}")
    checked["selected"] = selected
    checked["jarnsen_1_mhz"] = _format_mhz(JARNSEN_FREQUENCIES[PROFILE_JARNSEN_1])
    checked["jarnsen_2_mhz"] = _format_mhz(JARNSEN_FREQUENCIES[PROFILE_JARNSEN_2])
    for profile, key in HOP_KEYS.items():
        checked[key] = 20 if profile in {PROFILE_JARNSEN_1, PROFILE_JARNSEN_2} else _normalize_hops(checked.get(key), profile)
    for profile, key in MODEM_SETTING_KEYS.items():
        checked[key] = _normalize_modem_preset(checked.get(key))
    checked["version"] = 3
    return checked


def selected_frequency(settings: dict[str, Any]) -> Decimal | None:
    checked = validate_settings(settings)
    return JARNSEN_FREQUENCIES.get(checked["selected"])


def profile_frequency(profile: str) -> Decimal | None:
    return JARNSEN_FREQUENCIES.get(profile)


def _lora_mapping(data: dict[str, Any]) -> dict[str, Any]:
    config = data.get("config")
    if isinstance(config, dict):
        lora = config.get("lora")
        if not isinstance(lora, dict):
            lora = {}
            config["lora"] = lora
        return lora

    top_lora = data.get("lora")
    if isinstance(top_lora, dict):
        return top_lora

    config = {}
    data["config"] = config
    lora: dict[str, Any] = {}
    config["lora"] = lora
    return lora


def apply_overlay(data: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    """Apply only radio fields. Device role and unrelated profile values stay untouched."""
    checked = validate_settings(settings)
    staged = copy.deepcopy(data)
    lora = _lora_mapping(staged)
    selected = checked["selected"]

    if selected == PROFILE_STANDARD:
        # Standard remains the normal Meshtastic profile: normal frequency,
        # normal TX/duty/modem handling, with its own selected hop count.
        lora["override_frequency"] = 0.0
        lora["hop_limit"] = hop_limit_for(checked, PROFILE_STANDARD)
        lora["override_duty_cycle"] = False
    else:
        frequency = selected_frequency(checked)
        assert frequency is not None
        _validate_frequency_for_region(
            frequency,
            lora.get("region"),
            label=PROFILE_LABELS.get(selected, "Jarnsen"),
        )
        lora["override_frequency"] = float(frequency)
        # JARNSEN 1/2 use the firmware contract's fixed extended mesh depth.
        lora["hop_limit"] = hop_limit_for(checked, selected)
        # JARNSEN profile overlay does not add a duty-cycle limiter.
        lora["override_duty_cycle"] = True
        # tx_power=0 keeps the flasher on Meshtastic max/auto rather than adding
        # its own fixed dBm cap. Firmware/platform/hardware safeguards remain.
        lora["tx_power"] = 0
        # Each JARNSEN frequency profile has its own modem preset. Enabling
        # use_preset makes the firmware use modem_preset instead of custom BW/SF/CR.
        lora["use_preset"] = True
        lora["modem_preset"] = modem_preset_for(checked, selected) or "LONG_FAST"

    return staged


def summary(settings: dict[str, Any]) -> str:
    checked = validate_settings(settings)
    selected = checked["selected"]
    label = PROFILE_LABELS[selected]
    hops = hop_limit_for(checked, selected)
    if selected == PROFILE_STANDARD:
        return f"Standard · normale Frequenz · {hops} Hops · Modem/TX/Duty nach Profil"
    frequency = JARNSEN_FREQUENCIES[selected]
    modem = modem_preset_for(checked, selected) or "LONG_FAST"
    modem_label = MODEM_LABELS.get(modem, modem)
    return (
        f"{label} · {_format_mhz(frequency)} MHz · {modem_label} · {hops} Hops · "
        "Duty frei · TX max/auto"
    )


def install(services: Any) -> None:
    """Install radio-profile preflight and profile overlay before app imports service functions."""
    if getattr(services, "_jarnsen_radio_profiles_installed", False):
        return
    services._jarnsen_radio_profiles_installed = True

    base_restore = services.restore_profile
    base_flash = services.flash_bundle
    work_dir = Path(services.PATHS.root) / "restore-work"
    work_dir.mkdir(parents=True, exist_ok=True)

    def checked_settings() -> dict[str, Any]:
        return validate_settings(load_settings(services))

    def restore_profile(port: str, profile: Path | None = None) -> None:
        source = Path(profile or services.PATHS.active_profile)
        if not source.exists():
            return base_restore(port, profile)

        settings = checked_settings()
        try:
            raw = yaml.safe_load(source.read_text(encoding="utf-8", errors="replace")) or {}
        except Exception as exc:
            raise services.FlasherError(f"Funkprofil konnte nicht angewendet werden: {exc}") from exc
        if not isinstance(raw, dict):
            raise services.FlasherError("Funkprofil konnte nicht angewendet werden: Profil ist kein YAML-Mapping.")

        staged = apply_overlay(raw, settings)
        safe_port = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(port)) or "serial"
        temp = work_dir / f"{safe_port}-{time.time_ns()}-radio-profile.yaml"
        temp.write_text(yaml.safe_dump(staged, allow_unicode=True, sort_keys=False), encoding="utf-8")
        _emit(
            "RADIO PROFILE APPLY "
            f"port={port} selected={settings['selected']} summary={summary(settings)!r} source={source.name!r}"
        )
        try:
            return base_restore(port, temp)
        finally:
            try:
                temp.unlink(missing_ok=True)
            except Exception:
                pass

    def flash_bundle(port: str, bundle: Any, log: Any = None) -> None:
        settings = checked_settings()
        _emit(
            "RADIO PROFILE PREFLIGHT "
            f"port={port} selected={settings['selected']} summary={summary(settings)!r}"
        )
        return base_flash(port, bundle, log=log)

    services.restore_profile = restore_profile
    services.flash_bundle = flash_bundle
    services.load_radio_profile_settings = lambda: load_settings(services)
    services.save_radio_profile_settings = lambda settings: save_settings(settings, services)
    services.validate_radio_profile_settings = validate_settings
    services.radio_profile_summary = summary
    services.radio_profile_allocation_summary = allocation_summary
    services.apply_radio_profile_overlay = apply_overlay

    _emit(
        "RADIO PROFILES installed presets=standard,jarnsen1@915.625,jarnsen2@917.375 "
        "standard-hop-max=7 jarnsen-hop-fixed=20 separate-modem-presets=1 "
        "duty-override=1 tx=max-auto allocation-check=1 "
        "persistent=1 role-touch=0"
    )
