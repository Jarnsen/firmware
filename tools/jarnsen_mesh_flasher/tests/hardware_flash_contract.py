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


class HardwareFlashContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ports = _configured_ports()
        if not cls.ports:
            raise unittest.SkipTest(
                "Keine Hardwarezuordnung. Optional: "
                "JARNSEN_FLASHER_HW_PORTS=tracker=COM3,repeater=COM4"
            )
        import _build_version  # noqa: F401 - installs the packaged runtime layers
        import services

        cls.services = services

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

    def test_optional_update_and_postflash_verification(self) -> None:
        enabled = os.environ.get("JARNSEN_FLASHER_HW_FLASH", "").strip() == "1"
        armed = (
            os.environ.get("JARNSEN_FLASHER_HW_FLASH_CONFIRM", "").strip()
            == "I_ACCEPT_FIRMWARE_FLASH"
        )
        if not (enabled and armed):
            self.skipTest(
                "Hardware-Flash ist sicher gesperrt; Read/Preflight-Test wurde trotzdem ausgeführt."
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
