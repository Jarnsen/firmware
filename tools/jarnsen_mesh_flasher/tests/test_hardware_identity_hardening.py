from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import supreme_bootloader_hardening
from device_core import DeviceFingerprint
from reconnect_identity_guard import select_reconnect_candidate


def fp(
    port: str,
    serial: str,
    *,
    location: str = "",
    vid: int | None = 0x303A,
    pid: int | None = 0x1001,
    hwid: str = "",
) -> DeviceFingerprint:
    return DeviceFingerprint(
        port=port,
        serial_number=serial,
        location=location,
        vid=vid,
        pid=pid,
        hwid=hwid or f"USB VID:PID={vid:04X}:{pid:04X} SER={serial}",
        description="test",
    )


class ReconnectIdentityGuardTests(unittest.TestCase):
    def test_supreme_follows_exact_serial_not_other_esp32(self) -> None:
        expected = fp("COM25", "48:CA:43:5C:2F:EC")
        candidates = [
            fp("COM9", "F0:9E:9E:76:07:10"),
            fp("COM31", "48:CA:43:5C:2F:EC", pid=0x1002),
        ]
        selected, reason = select_reconnect_candidate(
            expected, candidates, "COM25", expected_board="tbeam_supreme"
        )
        self.assertIsNotNone(selected)
        self.assertEqual(selected.port, "COM31")
        self.assertEqual(reason, "physical-id")

    def test_supreme_never_falls_back_to_tracker_with_same_vid_pid(self) -> None:
        expected = fp("COM25", "48:CA:43:5C:2F:EC")
        candidates = [fp("COM9", "F0:9E:9E:76:07:10")]
        selected, reason = select_reconnect_candidate(
            expected, candidates, "COM25", expected_board="tbeam_supreme"
        )
        self.assertIsNone(selected)
        self.assertEqual(reason, "awaiting-physical-id")

    def test_reused_same_com_with_different_serial_is_rejected(self) -> None:
        expected = fp("COM25", "48:CA:43:5C:2F:EC")
        selected, reason = select_reconnect_candidate(
            expected,
            [fp("COM25", "F0:9E:9E:76:07:10")],
            "COM25",
            expected_board="tbeam_supreme",
        )
        self.assertIsNone(selected)
        self.assertEqual(reason, "awaiting-physical-id")

    def test_generic_v3_serial_is_bound_with_usb_location(self) -> None:
        expected = fp("COM13", "0001", location="1-2", vid=0x10C4, pid=0xEA60)
        candidates = [
            fp("COM17", "0001", location="1-5", vid=0x10C4, pid=0xEA60),
            fp("COM18", "0001", location="1-2", vid=0x10C4, pid=0xEA60),
        ]
        selected, reason = select_reconnect_candidate(
            expected, candidates, "COM13", expected_board="repeater"
        )
        self.assertIsNotNone(selected)
        self.assertEqual(selected.port, "COM18")
        self.assertEqual(reason, "physical-id")


class SupremeBootloaderHardeningTests(unittest.TestCase):
    def test_usb_reset_has_no_forced_1200_and_reenumeration_probe_decides(self) -> None:
        manager = SimpleNamespace(remember=Mock())
        visible = {"COM25", "COM31"}
        services = SimpleNamespace(
            FlasherError=RuntimeError,
            live_serial_port=lambda port: port if port in visible else None,
            wait_for_device_reconnect=Mock(return_value="COM31"),
            device_sessions=manager,
        )
        reset_result = SimpleNamespace(returncode=1, stdout="native USB re-enumerated")
        probe_result = SimpleNamespace(returncode=0, stdout="Status value: 0x0000")

        import flash_runtime

        with patch.object(
            flash_runtime,
            "_stream_esptool",
            side_effect=[reset_result, probe_result],
        ) as stream:
            result = supreme_bootloader_hardening.prepare_supreme_download_mode(
                services, "COM25", Mock()
            )

        self.assertEqual(result, "COM31")
        self.assertEqual(stream.call_count, 2)
        reset_args = stream.call_args_list[0].args[2]
        probe_args = stream.call_args_list[1].args[2]
        self.assertNotIn("1200", reset_args)
        self.assertEqual(
            reset_args,
            [
                "--chip",
                "esp32s3",
                "--before",
                "usb-reset",
                "--after",
                "no-reset",
                "read-flash-status",
            ],
        )
        self.assertIn("no-reset", probe_args)
        services.wait_for_device_reconnect.assert_called_once_with(
            "COM25", timeout=20, expected_board="tbeam_supreme"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
