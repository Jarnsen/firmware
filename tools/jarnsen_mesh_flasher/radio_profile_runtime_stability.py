from __future__ import annotations

import time
from typing import Any

import radio_profile_legacy_fallback as legacy
import radio_profile_node_sync as node_sync
import radio_profiles


_INSTALLED = False


def _emit(message: str) -> None:
    try:
        import diagnostics

        diagnostics._emit(message)
    except Exception:
        pass


def _port_key(port: str) -> str:
    return str(port or "").strip().upper()


def _board_hint(services: Any, port: str) -> str:
    try:
        mapping = getattr(services, "_jarnsen_operation_board_by_port", {})
        return str(mapping.get(_port_key(port), "") or "")
    except Exception:
        return ""


def _wait_serial_without_reboot(port: str, services: Any, timeout: float = 45.0) -> None:
    """Wait for a live USB endpoint without issuing a Meshtastic reboot.

    The previous radio-slot preflight called services.reboot_node() merely to
    switch from protobuf to the raw JARNSEN console. Current JARNSEN firmware
    accepts explicit JARNSEN_TOOL_* lines directly, so that reboot is both
    unnecessary and harmful on native-USB boards such as T-Beam Supreme.
    """
    started = time.monotonic()
    try:
        services.wait_for_serial(port, timeout=max(5.0, float(timeout)))
    except Exception as exc:
        _emit(
            f"RADIO RUNTIME WAIT port={port} type={type(exc).__name__} "
            f"message={str(exc)[:300]!r}"
        )
        raise
    # A COM endpoint can reappear slightly before the application task is ready.
    # Keep this a short settle only; the raw service probe below performs the real
    # readiness handshake and resends its command while boot output is arriving.
    time.sleep(0.8)
    _emit(
        f"RADIO RUNTIME SERIAL READY port={port} elapsed={time.monotonic()-started:.2f}s "
        "extra-reboot=0"
    )


def _probe_active_no_reboot(port: str, services: Any, *, max_wait: float = 24.0) -> str:
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
            active = match.group(1).lower()
            legacy._UNSUPPORTED_PORTS.discard(key)
            _emit(
                f"RADIO RUNTIME PREFLIGHT port={port} board={board!r} active={active} "
                f"attempt={attempt} elapsed={time.monotonic()-started:.2f}s extra-reboot=0"
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

    # Slot service is optional on VANILLA/old images. Never reboot or abort the
    # normal YAML profile write just because the optional radio-slot service is
    # unavailable. Standard remains the safe active-profile fallback.
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

    # Capture the already layered V3 function only as a diagnostic fallback.
    # We intentionally replace the final node_sync hook for every board so all
    # six boards use the same non-destructive preflight semantics.
    previous_read_active = node_sync._read_active_profile

    def read_active_profile(port: str, runtime_services: Any) -> str:
        board = _board_hint(runtime_services, port)
        # V3 still benefits from its application-level readiness check after a
        # fresh flash, but it must not gain an additional pre-profile reboot.
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

    # Original slot-writing code also called _reboot_to_raw() around region and
    # slot operations. Explicit service takeover makes those reboots unnecessary.
    # Replace it with a readiness wait, preserving all actual slot write/verify
    # behavior while eliminating native-USB re-enumeration races.
    def no_reboot_to_raw(port: str, runtime_services: Any) -> None:
        _wait_serial_without_reboot(port, runtime_services, timeout=45.0)
        _emit(f"RADIO RUNTIME RAW TAKEOVER port={port} extra-reboot=0")

    node_sync._reboot_to_raw = no_reboot_to_raw
    node_sync._read_active_profile = read_active_profile
    legacy._compat_active_profile = read_active_profile

    services._jarnsen_radio_profile_runtime_stability = True
    services.read_active_radio_profile_stable = lambda port: read_active_profile(port, services)
    _emit(
        "RADIO PROFILE RUNTIME STABILITY installed all-boards=1 preprofile-reboot=0 "
        "raw-takeover=1 native-usb-safe=1 optional-slot-fallback=1"
    )
