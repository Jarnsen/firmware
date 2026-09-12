from __future__ import annotations

import unittest

import hardware_flash_contract_base as base
from serial.tools import list_ports

# Dedicated destructive lab node. This exact USB serial was independently
# observed as LILYGO T-Beam Supreme in multiple prior Flasher hardware logs.
# Never broaden this to a COM number or VID/PID: other attached nodes share
# the same 303A:1001 USB identity.
SUPREME_RECOVERY_SERIAL = "48:CA:43:5C:2F:EC"

_BASE_AUTO_DISCOVER = base._auto_discover_ports


def _auto_discover_ports(services):
    """Add only the historically proven Supreme as a physical recovery candidate.

    Normal live Meshtastic discovery always runs first. The physical fallback is
    armed only for the dedicated destructive feature-branch HIL, only for one
    exact USB serial, and only when that exact device does not answer the app
    protocol. A live response identifying another/unknown board is never
    reinterpreted as Supreme.
    """
    discovered = _BASE_AUTO_DISCOVER(services)
    if not base._supreme_full_cycle_enabled() or "tbeam_supreme" in discovered:
        return discovered

    matches = [
        entry
        for entry in list_ports.comports()
        if getattr(entry, "vid", None) is not None
        and str(getattr(entry, "serial_number", "") or "").strip().casefold()
        == SUPREME_RECOVERY_SERIAL.casefold()
    ]
    if not matches:
        return discovered
    if len(matches) > 1:
        ports = ", ".join(str(getattr(entry, "device", "") or "?") for entry in matches)
        raise RuntimeError(
            "Historische Supreme-USB-Identität ist mehrfach sichtbar "
            f"({ports}); destruktiver HIL stoppt."
        )

    entry = matches[0]
    port = str(getattr(entry, "device", "") or "").strip()
    if not port:
        raise RuntimeError("Supreme-Recovery-USB-Identität hat keinen seriellen Port.")

    try:
        info = services.verify_node(port)
    except Exception as exc:
        info = ""
        print(
            "Hardware Supreme recovery candidate: "
            f"{port} serial={SUPREME_RECOVERY_SERIAL!r}; "
            f"app identity unavailable ({type(exc).__name__}: {str(exc)[:180]}). "
            "Only the destructive Supreme HIL may recover it."
        )

    if info:
        detected = services.detect_board_from_text(info)
        if detected != "tbeam_supreme":
            raise RuntimeError(
                f"{port}: exakte historische Supreme-USB-Identität antwortet live als "
                f"{detected!r}; automatische destruktive Recovery wird verweigert."
            )
        discovered["tbeam_supreme"] = port
        return discovered

    manager = getattr(services, "device_sessions", None)
    remember = getattr(manager, "remember", None)
    if callable(remember):
        fingerprint = remember(port)
        if fingerprint is not None:
            remembered_serial = str(fingerprint.serial_number or "").strip()
            if remembered_serial.casefold() != SUPREME_RECOVERY_SERIAL.casefold():
                raise RuntimeError(
                    f"{port}: physische Bindung wechselte unerwartet von "
                    f"{SUPREME_RECOVERY_SERIAL!r} auf {remembered_serial!r}."
                )
            print(
                "Hardware Supreme physical recovery lock: "
                f"{port} serial={remembered_serial!r} "
                f"location={fingerprint.location!r}"
            )

    discovered["tbeam_supreme"] = port
    return discovered


# The inherited setUpClass resolves this helper through the base module globals.
# Patch only that discovery hook; all existing contract logic remains unchanged.
base._auto_discover_ports = _auto_discover_ports


class HardwareFlashContract(base.HardwareFlashContract):
    # Disable the inherited late-running name and re-expose the exact same full
    # cycle first. This lets a physically proven but app-silent Supreme recover
    # before ordinary read/preflight/role contracts are executed.
    test_supreme_full_first_flash_cycle = None

    def test_00_supreme_full_first_flash_cycle(self) -> None:
        original_port = self.ports.get("tbeam_supreme", "")
        base.HardwareFlashContract.test_supreme_full_first_flash_cycle(self)

        # Physical identity is authoritative only for entering recovery. Once
        # the full cycle has completed, require an independent live app-level
        # Supreme proof before any later tests may use this device.
        live_port, info = base._verify_bound_node(
            self.services,
            original_port,
            "tbeam_supreme",
            timeout=90,
        )
        detected = self.services.detect_board_from_text(info)
        self.assertEqual(detected, "tbeam_supreme")
        self.ports["tbeam_supreme"] = live_port
        print(
            "Supreme recovery re-verified: "
            f"{original_port} -> {live_port} board={detected}"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
