from __future__ import annotations

import time
from typing import Any

import radio_profiles
import radio_profile_node_sync as node_sync


PROBE_TIMEOUT = 2.0
PROBE_ATTEMPTS = 2
_UNSUPPORTED_PORTS: set[str] = set()


def _emit(message: str) -> None:
    try:
        import diagnostics

        diagnostics._emit(message)
    except Exception:
        pass


def _port_key(port: str) -> str:
    return str(port or "").strip().upper()


def _compat_active_profile(port: str, services: Any) -> str:
    """Probe the optional three-slot service without breaking VANILLA/legacy nodes."""
    key = _port_key(port)
    node_sync._reboot_to_raw(port, services)
    last_error: Exception | None = None

    for attempt in range(1, PROBE_ATTEMPTS + 1):
        try:
            line = node_sync._raw_command(
                port,
                "JARNSEN_TOOL_RADIO_INFO",
                expected=node_sync.RADIO_INFO_MARKER,
                timeout=PROBE_TIMEOUT,
            )
            match = node_sync.ACTIVE_RE.search(line)
            if not match:
                raise RuntimeError(
                    f"Aktives Funkprofil konnte nicht aus der Firmware-Antwort gelesen werden: {line}"
                )
            active = match.group(1).lower()
            _UNSUPPORTED_PORTS.discard(key)
            _emit(
                "RADIO NODE SYNC compatibility-probe "
                f"port={port} slots-supported=1 active={active} attempt={attempt}"
            )
            return active
        except (TimeoutError, RuntimeError) as exc:
            last_error = exc
            _emit(
                "RADIO NODE SYNC compatibility-probe retry "
                f"port={port} slots-supported=unknown attempt={attempt}/{PROBE_ATTEMPTS} "
                f"type={type(exc).__name__}"
            )
            if attempt < PROBE_ATTEMPTS:
                try:
                    services.wait_for_serial(port, timeout=15)
                except Exception:
                    pass
                time.sleep(0.35)

    _UNSUPPORTED_PORTS.add(key)
    _emit(
        "RADIO NODE SYNC compatibility-fallback "
        f"port={port} slots-supported=0 fallback=standard-only no-fatal=1 "
        f"type={type(last_error).__name__ if last_error is not None else 'unknown'}"
    )
    return radio_profiles.PROFILE_STANDARD


def install(services: Any) -> None:
    """Keep flashing functional when the installed firmware has no three-slot service yet."""
    if getattr(services, "_jarnsen_radio_profile_legacy_fallback", False):
        return

    base_write_slots = node_sync._write_firmware_slots
    base_manual_sync = getattr(services, "sync_radio_profiles_to_node", None)

    def write_slots_compat(
        port: str,
        settings: dict[str, Any],
        active_before: str,
        standard_region: str,
        runtime_services: Any,
    ) -> None:
        key = _port_key(port)
        if key in _UNSUPPORTED_PORTS:
            _emit(
                "RADIO NODE SYNC slot-write skipped "
                f"port={port} reason=firmware-service-unavailable standard-restored=1 "
                "jarnsen-slots-deferred=1"
            )
            return
        try:
            base_write_slots(port, settings, active_before, standard_region, runtime_services)
        except TimeoutError as exc:
            # INFO worked but a later slot command is missing. The original writer
            # restores Standard in its finally path before this fallback is reached.
            _UNSUPPORTED_PORTS.add(key)
            _emit(
                "RADIO NODE SYNC slot-write compatibility-fallback "
                f"port={port} reason=slot-command-timeout standard-restored=1 "
                f"jarnsen-slots-deferred=1 type={type(exc).__name__}"
            )
            return

    node_sync._read_active_profile = _compat_active_profile
    node_sync._write_firmware_slots = write_slots_compat

    if callable(base_manual_sync):
        def manual_sync(port: str) -> None:
            key = _port_key(port)
            _UNSUPPORTED_PORTS.discard(key)
            base_manual_sync(port)
            if key in _UNSUPPORTED_PORTS:
                raise RuntimeError(
                    "Die installierte Firmware unterstützt die 3 Funkprofil-Slots noch nicht. "
                    "Standard wurde nicht beschädigt; Jarnsen 1/2 können erst mit einer Firmware "
                    "mit JARNSEN_TOOL_RADIO-Unterstützung in die Node geschrieben werden."
                )

        services.sync_radio_profiles_to_node = manual_sync

    services._jarnsen_radio_profile_legacy_fallback = True
    services.radio_profile_slots_supported = lambda port: _port_key(port) not in _UNSUPPORTED_PORTS

    _emit(
        "RADIO NODE SYNC LEGACY FALLBACK installed probe-timeout=2s attempts=2 "
        "vanilla-no-fatal=1 standard-restore-continues=1 slot-write-deferred=1"
    )
