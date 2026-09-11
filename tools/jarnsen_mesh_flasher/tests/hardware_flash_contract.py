from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


def _configured_ports() -> dict[str, str]:
    raw = os.environ.get("JARNSEN_FLASHER_HW_PORTS", "").strip()
    if not raw:
        return {}
    if raw.startswith("{"):
        value = json.loads(raw)
        return {str(key): str(port) for key, port in value.items()}
    result: dict[str, str] = {}
    for item in raw.split(","):
        key, separator, port = item.partition("=")
        if separator and key.strip() and port.strip():
            result[key.strip()] = port.strip()
    return result


def _auto_discover_ports(services) -> dict[str, str]:
    """Safely discover attached wired boards for read-only HIL checks.

    Auto discovery never enables flashing by itself. It only replaces the old
    need to hard-code COM25/COMx for the read/preflight contract on the
    self-hosted Windows runner. Bluetooth serial ports are ignored because they
    normally do not expose a USB VID/PID.
    """
    if os.environ.get("JARNSEN_FLASHER_HW_AUTODISCOVER", "1").strip() == "0":
        return {}

    try:
        from serial.tools import list_ports
    except Exception as exc:
        print(f"Hardware auto-discovery unavailable: {type(exc).__name__}: {exc}")
        return {}

    discovered: dict[str, str] = {}
    for entry in list_ports.comports():
        if getattr(entry, "vid", None) is None:
            continue
        port = str(getattr(entry, "device", "") or "").strip()
        if not port:
            continue
        try:
            info = services.verify_node(port)
            board_key = services.detect_board_from_text(info)
        except Exception as exc:
            print(
                f"Hardware auto-discovery ignored {port}: "
                f"{type(exc).__name__}: {str(exc)[:180]}"
            )
            continue
        if not board_key or board_key not in services.BOARD_PROFILES:
            continue
        previous = discovered.get(board_key)
        if previous and previous != port:
            raise RuntimeError(
                f"Mehrere angeschlossene Boards fuer {board_key}: {previous}, {port}. "
                "JARNSEN_FLASHER_HW_PORTS explizit setzen."
            )
        discovered[board_key] = port
        print(f"Hardware auto-discovery: {board_key}={port}")
    return discovered


def _supreme_full_cycle_enabled() -> bool:
    """Arm the destructive Supreme lab node only in the intended context."""
    if os.environ.get("GITHUB_ACTIONS", "").strip().casefold() == "true":
        return (
            os.environ.get("GITHUB_REF", "").strip()
            == "refs/heads/feat/mini-serial-flasher"
        )
    return (
        os.environ.get("JARNSEN_SUPREME_HIL_CONFIRM", "").strip()
        == "I_ACCEPT_SUPREME_FACTORY_FLASH"
    )


class HardwareFlashContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import _build_version  # noqa: F401 - installs the packaged runtime layers
        import services

        cls.services = services
        cls.ports = _configured_ports() or _auto_discover_ports(services)
        if not cls.ports:
            raise unittest.SkipTest(
                "Keine angeschlossene Test-Hardware gefunden. Optional explizit: "
                "JARNSEN_FLASHER_HW_PORTS=tracker=COM3,repeater=COM4"
            )

    def test_configured_boards_read_and_preflight(self) -> None:
        unknown = sorted(set(self.ports).difference(self.services.BOARD_PROFILES))
        self.assertFalse(unknown, f"Unbekannte Board-Keys: {unknown}")
        for board_key, port in sorted(self.ports.items()):
            with self.subTest(board=board_key, port=port):
                info = self.services.verify_node(port)
                detected = self.services.detect_board_from_text(info)
                self.assertEqual(detected, board_key)
                bundle = self.services.GitHubFirmwareClient().resolve_latest(board_key)
                report = self.services.run_flash_preflight(
                    port, board_key, bundle, "update"
                )
                self.assertTrue(report.ready, report.format())

    def test_unified_role_service_readiness(self) -> None:
        """Catch the Build-289 post-flash role_api failure on real hardware."""
        import review_team_provisioning_v2 as provisioning

        for board_key, port in sorted(self.ports.items()):
            with self.subTest(board=board_key, port=port):
                identity = self.services.query_jarnsen_identity(port)
                build = int(getattr(identity, "build", 0) or 0) if identity else 0
                if build < 168:
                    self.skipTest(
                        f"{board_key} {port}: Build {build or 'unbekannt'} hat keinen "
                        "verbindlichen role_api=1 Vertrag."
                    )
                line = provisioning._raw_command(
                    port,
                    "JARNSEN_TOOL_ROLE_INFO",
                    expected="===JARNSEN_ROLE===",
                    timeout=3.0,
                    attempts=1,
                    services=self.services,
                )
                parsed = provisioning._parse_role_info(line)
                self.assertEqual(
                    parsed.get("role_api"),
                    "1",
                    f"{board_key} {port}: ROLE_INFO={line!r}",
                )

    def test_optional_update_and_postflash_verification(self) -> None:
        enabled = os.environ.get("JARNSEN_FLASHER_HW_FLASH", "").strip() == "1"
        armed = (
            os.environ.get("JARNSEN_FLASHER_HW_FLASH_CONFIRM", "").strip()
            == "I_ACCEPT_FIRMWARE_FLASH"
        )
        if not (enabled and armed):
            self.skipTest(
                "Hardware-Flash ist sicher gesperrt; Read/Preflight/ROLE_INFO wurden "
                "trotzdem automatisch ausgefuehrt."
            )

        from unified_service_v2 import flash_firmware_only_bundle

        for board_key, port in sorted(self.ports.items()):
            with self.subTest(board=board_key, port=port):
                before = self.services.query_jarnsen_identity(port)
                bundle = self.services.GitHubFirmwareClient().resolve_latest(board_key)
                flash_firmware_only_bundle(
                    self.services, port, board_key, bundle, print
                )
                self.services.wait_for_serial(port, timeout=120)
                self.services.verify_node(port, expected_board=board_key)
                after = self.services.query_jarnsen_identity(port)
                self.assertIsNotNone(after)
                self.assertEqual(getattr(after, "version", ""), bundle.version)
                self.assertEqual(getattr(after, "build", None), bundle.run_number)
                if before is not None:
                    print(
                        f"{board_key}: Build {getattr(before, 'build', None)} "
                        f"-> {getattr(after, 'build', None)}"
                    )

    def test_supreme_full_first_flash_cycle(self) -> None:
        """Run the real First-Flash pipeline on the dedicated attached Supreme."""
        if "tbeam_supreme" not in self.ports:
            self.skipTest(
                "Keine LILYGO T-Beam Supreme angeschlossen; destruktiver Full-HIL uebersprungen."
            )
        if not _supreme_full_cycle_enabled():
            self.skipTest(
                "Supreme Full-HIL ist nur auf feat/mini-serial-flasher automatisch "
                "oder lokal mit expliziter Bestaetigung freigegeben."
            )

        import supreme_full_hil

        result = supreme_full_hil.main()
        self.assertEqual(
            result,
            0,
            "Supreme First-Flash HIL ist fehlgeschlagen; siehe "
            "ci-logs/supreme-hil/report.json und trace.txt.",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
