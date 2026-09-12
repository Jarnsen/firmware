from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import postflash_hardening


class PostflashHardeningTests(unittest.TestCase):
    def test_supreme_write_policy_separates_watchdog_reset(self) -> None:
        base = Mock(
            side_effect=lambda board_key, *, before="usb-reset", after="watchdog-reset": [
                "--chip", "esp32s3", "--before", before, "--after", after
            ]
        )
        args = postflash_hardening._supreme_connection_args(
            base,
            "tbeam_supreme",
            before="no-reset",
            after="watchdog-reset",
        )
        self.assertEqual(
            args,
            ["--chip", "esp32s3", "--before", "no-reset", "--after", "no-reset"],
        )

    def test_non_supreme_reset_policy_is_unchanged(self) -> None:
        base = Mock(return_value=[])
        postflash_hardening._supreme_connection_args(
            base, "tracker", before="default-reset", after="watchdog-reset"
        )
        base.assert_called_once_with(
            "tracker", before="default-reset", after="watchdog-reset"
        )

    def test_reset_port_loss_does_not_turn_verified_flash_into_retry(self) -> None:
        services = SimpleNamespace(
            FlasherError=RuntimeError,
            resolve_live_port=lambda _port: "COM25",
            wait_for_device_reconnect=Mock(return_value="COM31"),
        )
        reset_result = SimpleNamespace(returncode=2, stdout="Hash already verified; port vanished")
        ready_result = ("COM31", "node-info", SimpleNamespace(is_jarnsen=True))

        import flash_runtime

        with patch.object(flash_runtime, "_stream_esptool", return_value=reset_result) as stream, patch.object(
            postflash_hardening, "wait_for_node_ready", return_value=ready_result
        ) as ready:
            result = postflash_hardening.finish_supreme_application_start(
                services,
                "COM25",
                log=Mock(),
                expected_version="2.0.0-alpha.28",
                expected_build=178,
            )

        self.assertEqual(result, "COM31")
        self.assertEqual(stream.call_count, 1)
        args = stream.call_args.args[2]
        self.assertIn("watchdog-reset", args)
        self.assertNotIn("write-flash", args)
        services.wait_for_device_reconnect.assert_called_once_with(
            "COM25", timeout=60, expected_board="tbeam_supreme"
        )
        ready.assert_called_once()

    def test_application_ready_waits_for_jarnsen_identity_then_verifies_board(self) -> None:
        identities = [
            SimpleNamespace(is_jarnsen=False, version="", build=None),
            SimpleNamespace(is_jarnsen=True, version="2.0.0-alpha.28", build=178),
        ]
        services = SimpleNamespace(
            FlasherError=RuntimeError,
            resolve_live_port=lambda _port: "COM13",
            query_jarnsen_identity=Mock(side_effect=identities),
            verify_node=Mock(return_value="pioEnv: heltec-v3"),
        )
        with patch.object(postflash_hardening.time, "sleep", return_value=None):
            live, info, identity = postflash_hardening.wait_for_node_ready(
                services,
                "COM13",
                expected_board="repeater",
                timeout=5,
                require_jarnsen=True,
                expected_version="2.0.0-alpha.28",
                expected_build=178,
            )
        self.assertEqual(live, "COM13")
        self.assertEqual(info, "pioEnv: heltec-v3")
        self.assertTrue(identity.is_jarnsen)
        self.assertEqual(services.query_jarnsen_identity.call_count, 2)
        services.verify_node.assert_called_once_with("COM13", expected_board="repeater")


if __name__ == "__main__":
    unittest.main(verbosity=2)
