from __future__ import annotations

import re
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import radio_profile_legacy_fallback as legacy
import radio_profile_node_sync as node_sync
import radio_profiles
import yaml

_INSTALLED = False

_LORA_ALIASES = {
    "region": ("region",),
    "override_frequency": ("overrideFrequency", "override_frequency"),
    "hop_limit": ("hopLimit", "hop_limit"),
    "use_preset": ("usePreset", "use_preset"),
    "modem_preset": ("modemPreset", "modem_preset"),
    "override_duty_cycle": ("overrideDutyCycle", "override_duty_cycle"),
}


def _emit(message: str) -> None:
    try:
        import diagnostics

        diagnostics._emit(message)
    except Exception:
        pass


def _port_key(port: str) -> str:
    return str(port or "").strip().upper()


def _record_slot_probe(services: Any, port: str, supported: bool) -> None:
    state = getattr(services, "_jarnsen_radio_slot_probe_state", None)
    if not isinstance(state, dict):
        state = {}
        services._jarnsen_radio_slot_probe_state = state
    state[_port_key(port)] = bool(supported)


def _board_hint(services: Any, port: str) -> str:
    try:
        mapping = getattr(services, "_jarnsen_operation_board_by_port", {})
        return str(mapping.get(_port_key(port), "") or "")
    except Exception:
        return ""


def _wait_serial_without_reboot(
    port: str, services: Any, timeout: float = 45.0
) -> None:
    """Wait for a live USB endpoint without issuing a Meshtastic reboot."""
    started = time.monotonic()
    try:
        services.wait_for_serial(port, timeout=max(5.0, float(timeout)))
    except Exception as exc:
        _emit(
            f"RADIO RUNTIME WAIT port={port} type={type(exc).__name__} "
            f"message={str(exc)[:300]!r}"
        )
        raise
    time.sleep(0.8)
    _emit(
        f"RADIO RUNTIME SERIAL READY port={port} elapsed={time.monotonic()-started:.2f}s "
        "extra-reboot=0"
    )


def _field(mapping: dict[str, Any], name: str) -> Any:
    for key in _LORA_ALIASES[name]:
        if key in mapping:
            return mapping[key]
    return None


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return result if result.is_finite() else None


def _bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().casefold()
    if text in {"true", "1", "yes", "on"}:
        return True
    if text in {"false", "0", "no", "off"}:
        return False
    return None


def _canonical_modem(value: Any) -> str:
    return (
        str(value or "")
        .strip()
        .upper()
        .replace("-", "_")
        .replace(" ", "_")
    )


def _profile_identity_from_lora(lora: dict[str, Any]) -> str:
    """Identify the active JARNSEN slot from stable slot-defining fields only.

    Build 185 can report ``active=standard`` after selecting a JARNSEN slot even
    though the selected slot has already been loaded into ``config.lora``.  The
    hop limit and modem preset are user-configurable slot contents, so they must
    not be used to decide *which* slot is active.  The two fixed frequencies are
    the unambiguous slot identities; region/preset mode/duty-cycle guard against
    mistaking an arbitrary Standard configuration for a JARNSEN slot.
    """
    if not isinstance(lora, dict) or not lora:
        return radio_profiles.PROFILE_STANDARD

    region = str(_field(lora, "region") or "").strip().upper()
    frequency = _decimal(_field(lora, "override_frequency"))
    duty = _bool(_field(lora, "override_duty_cycle"))
    use_preset = _bool(_field(lora, "use_preset"))

    if region != node_sync.JARNSEN_REGION or frequency is None:
        return radio_profiles.PROFILE_STANDARD
    if duty is not True:
        return radio_profiles.PROFILE_STANDARD
    if use_preset is False:
        return radio_profiles.PROFILE_STANDARD

    matches = [
        profile
        for profile in node_sync.JARNSEN_PROFILES
        if abs(frequency - radio_profiles.JARNSEN_FREQUENCIES[profile])
        <= Decimal("0.001")
    ]
    return matches[0] if len(matches) == 1 else radio_profiles.PROFILE_STANDARD


def _infer_profile_from_lora(
    settings: dict[str, Any], lora: dict[str, Any]
) -> str:
    """Compatibility wrapper for callers that still pass local settings.

    Slot identity is intentionally independent from the local desired hop/modem
    values.  Desired-state validation belongs in ``_lora_matches_desired_profile``.
    """
    del settings
    return _profile_identity_from_lora(lora)


def _lora_matches_desired_profile(
    settings: dict[str, Any], lora: dict[str, Any], profile: str
) -> bool:
    """Strictly validate that an identified JARNSEN slot matches desired state."""
    if profile not in node_sync.JARNSEN_PROFILES:
        return False
    if _profile_identity_from_lora(lora) != profile:
        return False

    checked = radio_profiles.validate_settings(settings)
    hop_value = _field(lora, "hop_limit")
    try:
        hops = int(hop_value)
    except (TypeError, ValueError):
        return False
    if hops != radio_profiles.hop_limit_for(checked, profile):
        return False

    expected_modem = radio_profiles.modem_preset_for(checked, profile) or "LONG_FAST"
    modem = _canonical_modem(_field(lora, "modem_preset"))
    if modem:
        return modem == _canonical_modem(expected_modem)
    return _canonical_modem(expected_modem) == "LONG_FAST"


def _export_lora_no_reboot(port: str, services: Any) -> dict[str, Any]:
    work_dir = Path(services.PATHS.root) / "restore-work"
    work_dir.mkdir(parents=True, exist_ok=True)
    safe_port = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(port)) or "serial"
    target = work_dir / f"radio-active-{safe_port}-{time.time_ns()}.yaml"
    try:
        services.meshtastic(port, "--export-config", str(target), timeout=90)
        if not target.exists():
            return {}
        data = yaml.safe_load(
            target.read_text(encoding="utf-8", errors="replace")
        ) or {}
        if not isinstance(data, dict):
            return {}
        config = data.get("config")
        if isinstance(config, dict) and isinstance(config.get("lora"), dict):
            return dict(config["lora"])
        if isinstance(data.get("lora"), dict):
            return dict(data["lora"])
        return {}
    finally:
        try:
            target.unlink(missing_ok=True)
        except Exception:
            pass


def _resolve_standard_label_from_lora(port: str, services: Any) -> str:
    try:
        settings = dict(services.load_radio_profile_settings())
        lora = _export_lora_no_reboot(port, services)
        inferred = _infer_profile_from_lora(settings, lora)
        _emit(
            "RADIO RUNTIME ACTIVE COMPAT "
            f"port={port} firmware=standard inferred={inferred} "
            f"region={_field(lora, 'region')!r} "
            f"frequency={_field(lora, 'override_frequency')!r} "
            f"hops={_field(lora, 'hop_limit')!r} identity-only=1 tx-normalization-safe=1"
        )
        return inferred
    except Exception as exc:
        _emit(
            "RADIO RUNTIME ACTIVE COMPAT WARNING "
            f"port={port} type={type(exc).__name__} message={str(exc)[:300]!r} "
            "fallback=standard"
        )
        return radio_profiles.PROFILE_STANDARD


def _probe_active_no_reboot(
    port: str, services: Any, *, max_wait: float = 24.0
) -> str:
    key = _port_key(port)
    board = _board_hint(services, port)
    started = time.monotonic()
    deadline = started + max(8.0, float(max_wait))
    last_error: Exception | None = None
    attempt = 0

    while time.monotonic() < deadline:
        attempt += 1
        remaining = max(1.0, deadline - time.monotonic())
        try:
            _wait_serial_without_reboot(port, services, timeout=min(12.0, remaining))
            line = node_sync._raw_command(
                port,
                "JARNSEN_TOOL_RADIO_INFO",
                expected=node_sync.RADIO_INFO_MARKER,
                timeout=min(8.0, remaining),
            )
            match = node_sync.ACTIVE_RE.search(line)
            if not match:
                raise RuntimeError(
                    f"Aktives Funkprofil konnte nicht aus der Firmware-Antwort gelesen werden: {line}"
                )
            firmware_active = match.group(1).lower()
            active = firmware_active
            if firmware_active == radio_profiles.PROFILE_STANDARD:
                active = _resolve_standard_label_from_lora(port, services)
            _record_slot_probe(services, port, True)
            legacy._UNSUPPORTED_PORTS.discard(key)
            _emit(
                f"RADIO RUNTIME PREFLIGHT port={port} board={board!r} "
                f"firmware-active={firmware_active} active={active} attempt={attempt} "
                f"elapsed={time.monotonic()-started:.2f}s extra-reboot=0"
            )
            return active
        except (TimeoutError, RuntimeError, OSError) as exc:
            last_error = exc
            _emit(
                f"RADIO RUNTIME PREFLIGHT RETRY port={port} board={board!r} "
                f"attempt={attempt} type={type(exc).__name__} message={str(exc)[:260]!r}"
            )
            if time.monotonic() < deadline:
                time.sleep(0.9)

    _record_slot_probe(services, port, False)
    legacy._UNSUPPORTED_PORTS.add(key)
    _emit(
        f"RADIO RUNTIME PREFLIGHT FALLBACK port={port} board={board!r} "
        f"slots-supported=0 active=standard extra-reboot=0 "
        f"type={type(last_error).__name__ if last_error is not None else 'unknown'}"
    )
    return radio_profiles.PROFILE_STANDARD


def install(services: Any) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    previous_read_active = node_sync._read_active_profile

    def read_active_profile(port: str, runtime_services: Any) -> str:
        board = _board_hint(runtime_services, port)
        if board == "repeater":
            ready = getattr(runtime_services, "wait_v3_meshtastic_ready", None)
            if callable(ready):
                try:
                    ready(port, timeout=90)
                except Exception as exc:
                    _emit(
                        f"RADIO RUNTIME V3 READY WARNING port={port} "
                        f"type={type(exc).__name__} message={str(exc)[:320]!r}"
                    )
                    raise
        try:
            return _probe_active_no_reboot(port, runtime_services)
        except Exception as exc:
            _emit(
                f"RADIO RUNTIME ACTIVE FALLBACK port={port} board={board!r} "
                f"type={type(exc).__name__} previous-hook={getattr(previous_read_active, '__name__', 'unknown')!r}"
            )
            raise

    def no_reboot_to_raw(port: str, runtime_services: Any) -> None:
        _wait_serial_without_reboot(port, runtime_services, timeout=45.0)
        _emit(f"RADIO RUNTIME RAW TAKEOVER port={port} extra-reboot=0")

    node_sync._reboot_to_raw = no_reboot_to_raw
    node_sync._read_active_profile = read_active_profile
    legacy._compat_active_profile = read_active_profile

    services._jarnsen_radio_profile_runtime_stability = True
    services.read_active_radio_profile_stable = lambda port: read_active_profile(
        port, services
    )
    _emit(
        "RADIO PROFILE RUNTIME STABILITY installed all-boards=1 preprofile-reboot=0 "
        "raw-takeover=1 native-usb-safe=1 optional-slot-fallback=1 "
        "active-lora-compat=1 identity-desired-separated=1 tx-normalization-safe=1"
    )
