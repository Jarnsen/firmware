from __future__ import annotations

import copy
import json
import re
import time
from decimal import Decimal, InvalidOperation
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
        "version": 1,
        "selected": PROFILE_STANDARD,
        "jarnsen_1_mhz": "",
        "jarnsen_2_mhz": "",
    }


def _clean_frequency_text(value: Any) -> str:
    text = str(value or "").strip().replace(",", ".")
    if not text:
        return ""
    try:
        number = Decimal(text)
    except InvalidOperation:
        return text
    if not number.is_finite():
        return text
    normalized = format(number.normalize(), "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return normalized


def load_settings(services: Any) -> dict[str, Any]:
    result = _defaults()
    path = _config_file(services)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            result.update({key: raw.get(key, result[key]) for key in result})
    except FileNotFoundError:
        pass
    except Exception as exc:
        _emit(f"RADIO PROFILE LOAD ERROR type={type(exc).__name__} message={exc}")

    selected = str(result.get("selected") or PROFILE_STANDARD).strip().lower()
    result["selected"] = selected if selected in PROFILE_KEYS else PROFILE_STANDARD
    result["jarnsen_1_mhz"] = _clean_frequency_text(result.get("jarnsen_1_mhz"))
    result["jarnsen_2_mhz"] = _clean_frequency_text(result.get("jarnsen_2_mhz"))
    result["version"] = 1
    return result


def save_settings(settings: dict[str, Any], services: Any) -> dict[str, Any]:
    current = load_settings(services)
    selected = str(settings.get("selected", current["selected"]) or PROFILE_STANDARD).strip().lower()
    current["selected"] = selected if selected in PROFILE_KEYS else PROFILE_STANDARD
    current["jarnsen_1_mhz"] = _clean_frequency_text(
        settings.get("jarnsen_1_mhz", current["jarnsen_1_mhz"])
    )
    current["jarnsen_2_mhz"] = _clean_frequency_text(
        settings.get("jarnsen_2_mhz", current["jarnsen_2_mhz"])
    )
    current["version"] = 1

    path = _config_file(services)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)
    _emit(
        "RADIO PROFILE SAVE "
        f"selected={current['selected']} j1={current['jarnsen_1_mhz']!r} j2={current['jarnsen_2_mhz']!r}"
    )
    return current


def _frequency_decimal(value: Any, *, label: str) -> Decimal:
    text = _clean_frequency_text(value)
    if not text:
        raise ValueError(f"{label}: Frequenz fehlt.")
    try:
        number = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"{label}: ungültige Frequenz '{value}'.") from exc
    if not number.is_finite() or number <= 0 or number > Decimal("10000"):
        raise ValueError(f"{label}: Frequenz muss zwischen 0 und 10000 MHz liegen.")
    return number


def validate_settings(settings: dict[str, Any]) -> dict[str, Any]:
    checked = _defaults()
    checked.update(settings or {})
    selected = str(checked.get("selected") or PROFILE_STANDARD).strip().lower()
    if selected not in PROFILE_KEYS:
        raise ValueError(f"Unbekanntes Funkprofil: {selected}")
    checked["selected"] = selected
    checked["jarnsen_1_mhz"] = _clean_frequency_text(checked.get("jarnsen_1_mhz"))
    checked["jarnsen_2_mhz"] = _clean_frequency_text(checked.get("jarnsen_2_mhz"))
    checked["version"] = 1

    j1 = None
    j2 = None
    if checked["jarnsen_1_mhz"]:
        j1 = _frequency_decimal(checked["jarnsen_1_mhz"], label="Jarnsen 1")
    if checked["jarnsen_2_mhz"]:
        j2 = _frequency_decimal(checked["jarnsen_2_mhz"], label="Jarnsen 2")
    if j1 is not None and j2 is not None and j1 == j2:
        raise ValueError("Jarnsen 1 und Jarnsen 2 müssen unterschiedliche Frequenzen haben.")

    if selected == PROFILE_JARNSEN_1 and j1 is None:
        raise ValueError("Jarnsen 1 ist gewählt, aber die Frequenz für Jarnsen 1 fehlt.")
    if selected == PROFILE_JARNSEN_2 and j2 is None:
        raise ValueError("Jarnsen 2 ist gewählt, aber die Frequenz für Jarnsen 2 fehlt.")
    return checked


def selected_frequency(settings: dict[str, Any]) -> Decimal | None:
    checked = validate_settings(settings)
    if checked["selected"] == PROFILE_JARNSEN_1:
        return _frequency_decimal(checked["jarnsen_1_mhz"], label="Jarnsen 1")
    if checked["selected"] == PROFILE_JARNSEN_2:
        return _frequency_decimal(checked["jarnsen_2_mhz"], label="Jarnsen 2")
    return None


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


def _standard_hop_limit(value: Any) -> int:
    try:
        current = int(value)
    except Exception:
        current = 7
    return max(0, min(7, current))


def apply_overlay(data: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    """Apply only radio fields. Device role and all unrelated profile values stay untouched."""
    checked = validate_settings(settings)
    staged = copy.deepcopy(data)
    lora = _lora_mapping(staged)
    selected = checked["selected"]

    if selected == PROFILE_STANDARD:
        # Zero disables Meshtastic's explicit frequency override and returns to
        # the normal region/channel calculation. Standard never exceeds 7 hops.
        lora["override_frequency"] = 0.0
        lora["hop_limit"] = _standard_hop_limit(lora.get("hop_limit", 7))
    else:
        frequency = selected_frequency(checked)
        assert frequency is not None
        lora["override_frequency"] = float(frequency)
        lora["hop_limit"] = 20

    return staged


def summary(settings: dict[str, Any]) -> str:
    selected = str(settings.get("selected") or PROFILE_STANDARD).strip().lower()
    label = PROFILE_LABELS.get(selected, "Standard")
    if selected == PROFILE_STANDARD:
        return "Standard · normale Frequenzwahl · max. 7 Hops"
    key = "jarnsen_1_mhz" if selected == PROFILE_JARNSEN_1 else "jarnsen_2_mhz"
    freq = _clean_frequency_text(settings.get(key))
    if not freq:
        return f"{label} · Frequenz fehlt · 20 Hops gesperrt"
    return f"{label} · {freq} MHz · 20 Hops"


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
    services.apply_radio_profile_overlay = apply_overlay

    _emit("RADIO PROFILES installed standard=7-hops jarnsen=20-hops persistent=1 role-touch=0")
