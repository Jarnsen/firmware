from __future__ import annotations

import time
from types import MethodType
from typing import Any, Iterable

from serial.tools import list_ports

from device_core import DeviceFingerprint


_INSTALLED = False


def _emit(message: str) -> None:
    try:
        import diagnostics
        diagnostics._emit(message)
    except Exception:
        pass


def _key(value: str) -> str:
    return str(value or "").strip().upper()


def _has_strong_identity(fingerprint: DeviceFingerprint | None) -> bool:
    if fingerprint is None:
        return False
    return bool(
        str(fingerprint.serial_number or "").strip()
        or str(fingerprint.location or "").strip()
        or str(fingerprint.hwid or "").strip()
    )


def _same_physical_device(
    expected: DeviceFingerprint,
    candidate: DeviceFingerprint,
) -> bool:
    expected_serial = str(expected.serial_number or "").strip().casefold()
    candidate_serial = str(candidate.serial_number or "").strip().casefold()
    expected_location = str(expected.location or "").strip().casefold()
    candidate_location = str(candidate.location or "").strip().casefold()

    # A generic USB-UART serial such as "0001" becomes safe when Windows also
    # exposes a physical USB location. Native ESP32-S3 USB normally exposes a
    # MAC-derived serial and no location, so the serial alone is authoritative.
    if expected_serial and expected_location:
        return (
            candidate_serial == expected_serial
            and candidate_location == expected_location
        )
    if expected_serial:
        return bool(candidate_serial) and candidate_serial == expected_serial
    if expected_location:
        return bool(candidate_location) and candidate_location == expected_location

    expected_hwid = str(expected.hwid or "").strip().casefold()
    candidate_hwid = str(candidate.hwid or "").strip().casefold()
    if expected_hwid:
        return bool(candidate_hwid) and candidate_hwid == expected_hwid
    return False


def select_reconnect_candidate(
    expected: DeviceFingerprint | None,
    candidates: Iterable[DeviceFingerprint],
    original_port: str,
    *,
    expected_board: str | None = None,
) -> tuple[DeviceFingerprint | None, str]:
    """Choose only a candidate that can be tied to the same physical device.

    VID/PID and a board name are capabilities, not physical identity. In
    particular, two ESP32-S3 native USB devices can both be 303A:1001. A job is
    therefore never allowed to jump to another such node just because the
    original COM port temporarily disappeared.
    """
    items = list(candidates)
    original_key = _key(original_port)

    if expected is not None and _has_strong_identity(expected):
        matches = [item for item in items if _same_physical_device(expected, item)]
        if len(matches) == 1:
            selected = matches[0]
            reason = "same-port-physical-id" if _key(selected.port) == original_key else "physical-id"
            return selected, reason
        if len(matches) > 1:
            return None, "ambiguous-physical-id"
        # Never degrade a known serial/location/HWID to VID/PID. Waiting is
        # safer than flashing the wrong device.
        return None, "awaiting-physical-id"

    same_port = next((item for item in items if _key(item.port) == original_key), None)
    if same_port is not None:
        return same_port, "same-port-no-strong-id"

    # Last-resort compatibility for older hosts that expose no serial/location:
    # only one Espressif USB device may be followed for the explicitly selected
    # Supreme. Multiple native ESP32 devices are deliberately ambiguous.
    if str(expected_board or "").strip().casefold() == "tbeam_supreme":
        espressif = [item for item in items if item.vid == 0x303A]
        if len(espressif) == 1:
            return espressif[0], "single-espressif-no-strong-id"
        if len(espressif) > 1:
            return None, "ambiguous-espressif-no-strong-id"

    return None, "no-safe-candidate"


def _fingerprints(services: Any) -> list[DeviceFingerprint]:
    result: list[DeviceFingerprint] = []
    for item in list_ports.comports():
        bluetooth_check = getattr(services, "is_bluetooth_serial", None)
        if callable(bluetooth_check) and bluetooth_check(item):
            continue
        port = str(getattr(item, "device", "") or "").strip()
        if not port:
            continue
        result.append(
            DeviceFingerprint(
                port=port,
                serial_number=str(getattr(item, "serial_number", "") or ""),
                location=str(getattr(item, "location", "") or ""),
                vid=getattr(item, "vid", None),
                pid=getattr(item, "pid", None),
                hwid=str(getattr(item, "hwid", "") or ""),
                description=str(getattr(item, "description", "") or ""),
            )
        )
    return result


def install(services: Any) -> None:
    """Make reconnect tracking fail-safe in multi-device USB environments."""
    global _INSTALLED
    if _INSTALLED or getattr(services, "_jarnsen_reconnect_identity_guard", False):
        return

    manager = getattr(services, "device_sessions", None)
    if manager is None:
        raise RuntimeError("Reconnect identity guard requires device_sessions")

    def wait_for_reconnect(
        self: Any,
        port: str,
        timeout: int = 90,
        *,
        expected_board: str | None = None,
    ) -> str:
        original = str(port or "").strip()
        original_key = self._key(original)
        expected = self._fingerprints.get(original_key) or self.remember(original)
        deadline = time.monotonic() + max(1, int(timeout))
        last_signature: tuple[tuple[str, str], ...] = ()

        while time.monotonic() < deadline:
            candidates = _fingerprints(services)
            selected, reason = select_reconnect_candidate(
                expected,
                candidates,
                original,
                expected_board=expected_board,
            )

            if selected is not None:
                live = selected.port
                with self._registry_lock:
                    self._aliases[original_key] = live
                    self._fingerprints[original_key] = selected
                    self._fingerprints[self._key(live)] = selected
                _emit(
                    "RECONNECT IDENTITY SAFE "
                    f"original={original} live={live} reason={reason} "
                    f"serial={selected.serial_number!r} location={selected.location!r} "
                    f"board={expected_board or ''!r}"
                )
                time.sleep(2.0)
                return live

            signature = tuple(
                sorted((item.port, str(item.serial_number or "")) for item in candidates)
            )
            if signature != last_signature:
                last_signature = signature
                _emit(
                    "RECONNECT IDENTITY WAIT "
                    f"original={original} reason={reason} expected_serial="
                    f"{getattr(expected, 'serial_number', '')!r} visible={signature!r}"
                )
            time.sleep(0.5)

        raise services.FlasherError(
            f"{original}: Dasselbe physische USB-Gerät konnte nach {timeout}s nicht "
            "eindeutig wiedergefunden werden. Ein Wechsel auf ein anderes angeschlossenes "
            "Gerät wurde aus Sicherheitsgründen verhindert."
        )

    manager.wait_for_reconnect = MethodType(wait_for_reconnect, manager)
    services.wait_for_device_reconnect = manager.wait_for_reconnect
    services._jarnsen_reconnect_identity_guard = True
    _INSTALLED = True
    _emit(
        "RECONNECT IDENTITY GUARD installed serial-location-lock=1 "
        "vidpid-only-rebind=0 multi-esp-ambiguity-block=1 same-port-reuse-check=1"
    )
