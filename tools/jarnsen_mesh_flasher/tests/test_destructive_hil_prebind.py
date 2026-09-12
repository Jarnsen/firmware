from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

APP_DIR = Path(__file__).resolve().parents[1]
TESTS_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

import destructive_multi_board_hil as hil


class DestructiveHilPrebindTests(unittest.TestCase):
    def test_unique_physical_serial_may_rebind_to_new_com_port(self) -> None:
        records = [
            {"port": "COM9", "serial": "F0:9E:9E:76:07:10"},
            {"port": "COM31", "serial": "48:CA:43:5C:2F:EC"},
        ]
        with patch.object(hil, "_usb_records", return_value=records):
            live, usb = hil._locate_expected_usb(
                "COM25",
                "48:CA:43:5C:2F:EC",
                "tbeam_supreme",
                timeout=1,
            )
        self.assertEqual(live, "COM31")
        self.assertEqual(usb["serial"], "48:CA:43:5C:2F:EC")

    def test_generic_duplicate_serial_requires_configured_port_match(self) -> None:
        records = [
            {"port": "COM13", "serial": "0001"},
            {"port": "COM17", "serial": "0001"},
        ]
        with patch.object(hil, "_usb_records", return_value=records):
            live, _usb = hil._locate_expected_usb(
                "COM13",
                "0001",
                "repeater",
                timeout=1,
            )
        self.assertEqual(live, "COM13")

    def test_ambiguous_duplicate_serial_never_guesses_another_port(self) -> None:
        records = [
            {"port": "COM13", "serial": "0001"},
            {"port": "COM17", "serial": "0001"},
        ]
        with patch.object(hil, "_usb_records", return_value=records):
            with self.assertRaisesRegex(RuntimeError, "mehrfach sichtbar"):
                hil._locate_expected_usb(
                    "COM25",
                    "0001",
                    "repeater",
                    timeout=1,
                )

    def test_reacquire_uses_identity_guard_and_rechecks_serial(self) -> None:
        services = SimpleNamespace(
            wait_for_device_reconnect=Mock(return_value="COM31"),
        )
        usb = {"port": "COM31", "serial": "48:CA:43:5C:2F:EC"}
        with patch.object(hil, "_usb", return_value=usb):
            live, seen = hil._require_pinned_device(
                services,
                "COM25",
                "48:CA:43:5C:2F:EC",
                "tbeam_supreme",
                timeout=12,
            )
        self.assertEqual(live, "COM31")
        self.assertIs(seen, usb)
        services.wait_for_device_reconnect.assert_called_once_with(
            "COM25", timeout=12, expected_board="tbeam_supreme"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
