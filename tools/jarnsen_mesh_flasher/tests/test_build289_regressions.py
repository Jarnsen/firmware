# ruff: noqa: E402
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import backup_stability  # noqa: E402
import firmware_identity_reliable as identity_reliable  # noqa: E402
import name_write_finalize  # noqa: E402
import radio_profile_legacy_fallback as legacy_fallback  # noqa: E402
import recovery_mode  # noqa: E402
import review_team_provisioning_guard as provisioning_guard  # noqa: E402


class Build289RegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        provisioning_guard._ROLE_INFO_CACHE.clear()

    def test_meshtastic_info_pio_env_is_reused_as_hardware_hint(self) -> None:
        text = (
            'My info: { "myNodeNum": 1130115052, "pioEnv": "tbeam-s3-core", '
            '"firmwareEdition": "VANILLA" }'
        )
        self.assertEqual(
            identity_reliable._hardware_hint_from_info(text), "tbeam-s3-core"
        )

    def test_service_marker_accepts_final_line_without_newline(self) -> None:
        marker = "===JARNSEN_ROLE==="
        text = (
            "\x1b[32mINFO  \x1b[0m| booting\r\n"
            "\x1b[34mDEBUG \x1b[0m| Free heap 114936\r\n"
            "===JARNSEN_ROLE=== role=tak known=1 persisted=1 allowed=1 role_api=1"
        )
        self.assertEqual(
            legacy_fallback._extract_service_marker(
                text,
                marker,
                include_unterminated=True,
            ),
            "===JARNSEN_ROLE=== role=tak known=1 persisted=1 allowed=1 role_api=1",
        )

    def test_service_marker_ignores_ansi_prefix_and_returns_marker_payload(
        self,
    ) -> None:
        marker = "===JARNSEN_ROLE==="
        text = (
            "noise\n"
            "\x1b[32mINFO \x1b[0m ===JARNSEN_ROLE=== role=tak known=1 persisted=1 role_api=1\r\n"
        )
        self.assertEqual(
            legacy_fallback._extract_service_marker(text, marker),
            "===JARNSEN_ROLE=== role=tak known=1 persisted=1 role_api=1",
        )

    def test_name_write_uses_one_meshtastic_session_for_long_and_short(self) -> None:
        meshtastic = Mock(
            return_value=SimpleNamespace(returncode=0, stdout="", stderr="")
        )
        wait_for_serial = Mock()
        services = SimpleNamespace(
            meshtastic=meshtastic,
            wait_for_serial=wait_for_serial,
            resolve_live_port=lambda _port: "COM10",
            FlasherError=RuntimeError,
        )

        live = name_write_finalize._write_names_atomic(
            services,
            "COM9",
            "HIL Tracker",
            "H1",
        )

        self.assertEqual(live, "COM10")
        meshtastic.assert_called_once_with(
            "COM10",
            "--set-owner",
            "HIL Tracker",
            "--set-owner-short",
            "H1",
            timeout=90,
            check=False,
        )
        wait_for_serial.assert_called_once_with("COM9", timeout=45)

    def test_name_readback_follows_reconnected_live_port(self) -> None:
        result = SimpleNamespace(
            stdout="Owner: HIL Tracker (H1)\n",
            stderr="",
        )
        services = SimpleNamespace(
            meshtastic=Mock(return_value=result),
            resolve_live_port=lambda _port: "COM11",
        )

        long_name, short_name = name_write_finalize._read_names(
            services,
            "COM9",
            attempts=1,
        )

        self.assertEqual((long_name, short_name), ("HIL Tracker", "H1"))
        services.meshtastic.assert_called_once_with(
            "COM11",
            "--info",
            timeout=30,
            check=False,
        )

    def test_build168_role_probe_uses_role_info_directly(self) -> None:
        role_line = (
            "===JARNSEN_ROLE=== role=tak known=1 persisted=1 allowed=1 role_api=1"
        )
        services = SimpleNamespace(
            FlasherError=RuntimeError,
            reboot_node=Mock(),
        )
        provisioning = SimpleNamespace(
            _cached_build_hint=lambda _services, _port: 168,
            _parse_role_info=lambda line: (
                {"role_api": "1"} if "role_api=1" in line else {}
            ),
            _adaptive_settle_auto_reboot=Mock(),
        )
        base_probe = Mock(
            side_effect=AssertionError("legacy TOOL_INFO probe must not run")
        )
        base_raw = Mock(return_value=role_line)

        result = provisioning_guard._guarded_probe_role_api(
            services,
            provisioning,
            base_probe,
            base_raw,
            "COM25",
            "tak",
        )

        self.assertEqual(result, (True, None))
        services.reboot_node.assert_not_called()
        self.assertEqual(provisioning_guard._ROLE_INFO_CACHE["COM25"], role_line)
        self.assertEqual(base_raw.call_args.args[1], "JARNSEN_TOOL_ROLE_INFO")

    def test_build168_role_probe_recovers_once_after_boot_timeout(self) -> None:
        role_line = (
            "===JARNSEN_ROLE=== role=tak known=1 persisted=0 allowed=1 role_api=1"
        )
        services = SimpleNamespace(
            FlasherError=RuntimeError,
            reboot_node=Mock(),
        )
        settle = Mock()
        provisioning = SimpleNamespace(
            _cached_build_hint=lambda _services, _port: 168,
            _parse_role_info=lambda line: (
                {"role_api": "1"} if "role_api=1" in line else {}
            ),
            _adaptive_settle_auto_reboot=settle,
        )
        base_raw = Mock(side_effect=[TimeoutError("boot output only"), role_line])

        result = provisioning_guard._guarded_probe_role_api(
            services,
            provisioning,
            Mock(side_effect=AssertionError("legacy probe must not run")),
            base_raw,
            "COM25",
            "tak",
        )

        self.assertEqual(result, (True, None))
        services.reboot_node.assert_called_once_with("COM25")
        settle.assert_called_once()
        self.assertEqual(base_raw.call_count, 2)
        self.assertEqual(provisioning_guard._ROLE_INFO_CACHE["COM25"], role_line)

    def test_pre168_keeps_legacy_probe_path(self) -> None:
        services = SimpleNamespace(FlasherError=RuntimeError, reboot_node=Mock())
        provisioning = SimpleNamespace(_cached_build_hint=lambda _services, _port: 167)
        base_probe = Mock(return_value=(False, None))

        result = provisioning_guard._guarded_probe_role_api(
            services,
            provisioning,
            base_probe,
            Mock(),
            "COM25",
            "tak",
        )

        self.assertEqual(result, (False, None))
        base_probe.assert_called_once_with(services, "COM25", "tak")
        services.reboot_node.assert_not_called()

    def test_supreme_backup_serial_stream_loss_is_retryable(self) -> None:
        error = RuntimeError(
            "ERROR: A fatal error occurred: Serial data stream stopped: "
            "Possible serial noise or corruption."
        )
        self.assertTrue(backup_stability._retryable(error))

    def test_supreme_backup_rebinds_same_device_and_drops_baud(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            backups = Path(tmp)
            calls: list[tuple[str, tuple[str, ...]]] = []
            reconnect = Mock(return_value="COM27")
            remember = Mock(
                return_value=SimpleNamespace(
                    serial_number="48:CA:43:5C:2F:EC",
                    location="",
                )
            )

            def esptool(port: str, *args: str, **_kwargs):
                calls.append((port, tuple(str(value) for value in args)))
                if "flash-id" in args:
                    return SimpleNamespace(
                        returncode=0,
                        stdout="Detected flash size: 1MB\n",
                        stderr="",
                    )

                self.assertIn("read-flash", args)
                baud = str(args[args.index("--baud") + 1])
                target = Path(str(args[-1]))
                if baud == "921600":
                    target.write_bytes(b"partial-high-speed-read")
                    raise RuntimeError(
                        "ERROR: A fatal error occurred: Serial data stream stopped: "
                        "Possible serial noise or corruption."
                    )
                if baud == "460800":
                    self.assertEqual(port, "COM27")
                    target.write_bytes(b"\xA5" * (1024 * 1024))
                    return SimpleNamespace(returncode=0, stdout="", stderr="")
                self.fail(f"unexpected backup baud after recovery: {baud}")

            services = SimpleNamespace(
                backup_flash=Mock(
                    side_effect=AssertionError("ESP32 backup must use stability layer")
                ),
                esptool=esptool,
                PATHS=SimpleNamespace(backups=backups),
                FlasherError=RuntimeError,
                device_sessions=SimpleNamespace(remember=remember),
                wait_for_device_reconnect=reconnect,
                resolve_live_port=lambda port: port,
            )

            backup_stability.install(services)
            with patch.object(backup_stability.time, "sleep"):
                result = services.backup_flash("COM25", "tbeam_supreme")

            self.assertTrue(result.exists())
            self.assertEqual(result.stat().st_size, 1024 * 1024)
            self.assertEqual(result.read_bytes()[:1], b"\xA5")
            remember.assert_called_once_with("COM25")
            reconnect.assert_called_once_with(
                "COM25",
                timeout=25,
                expected_board="tbeam_supreme",
            )
            read_calls = [entry for entry in calls if "read-flash" in entry[1]]
            self.assertEqual(
                [entry[1][entry[1].index("--baud") + 1] for entry in read_calls],
                ["921600", "460800"],
            )
            self.assertEqual([entry[0] for entry in read_calls], ["COM25", "COM27"])

    def _recovery_services(self, esptool_result) -> SimpleNamespace:
        return SimpleNamespace(
            FlasherError=RuntimeError,
            BOARD_PROFILES={
                "tbeam_supreme": {"label": "LILYGO T-Beam Supreme"},
            },
            meshtastic=Mock(
                return_value=SimpleNamespace(returncode=1, stdout="", stderr="")
            ),
            detect_board_from_text=lambda _text: None,
            esptool=Mock(return_value=esptool_result),
        )

    def test_supreme_recovery_accepts_proven_s3_before_port_loss(self) -> None:
        output = (
            "esptool v5.4.0\n"
            "Serial port COM25:\n"
            "Connecting...\n"
            "Detecting chip type... ESP32-S3\n"
            "Connected to ESP32-S3 on COM25:\n"
        )
        services = self._recovery_services(
            SimpleNamespace(
                returncode=1,
                stdout=output,
                stderr=(
                    "ERROR: A serial exception error occurred: Cannot configure port, "
                    "something went wrong. OSError(22, 'Ein nicht vorhandenes Gerät wurde angegeben.', None, 433)"
                ),
            )
        )

        with patch.object(
            recovery_mode, "_port_detail", return_value={"device": "COM25"}
        ):
            result = recovery_mode.probe(services, "COM25", "tbeam_supreme")

        self.assertTrue(result["ready"])
        self.assertEqual(result["detected_board"], "tbeam_supreme")
        self.assertEqual(result["mode"], "esp-bootloader-degraded")
        self.assertEqual(result["transport"], "esptool")
        self.assertEqual(result["proven_chip"], "ESP32-S3")

    def test_supreme_recovery_rejects_wrong_chip_on_nonzero_exit(self) -> None:
        services = self._recovery_services(
            SimpleNamespace(
                returncode=1,
                stdout="Connected to ESP32 on COM25:\n",
                stderr="serial port disappeared",
            )
        )

        with patch.object(
            recovery_mode, "_port_detail", return_value={"device": "COM25"}
        ):
            result = recovery_mode.probe(services, "COM25", "tbeam_supreme")

        self.assertFalse(result["ready"])
        self.assertEqual(result["mode"], "esp-bootloader-mismatch")
        self.assertEqual(result["transport"], "esptool")
        self.assertEqual(result["proven_chip"], "ESP32")

    def test_supreme_recovery_rejects_connecting_only(self) -> None:
        services = self._recovery_services(
            SimpleNamespace(
                returncode=1,
                stdout="Serial port COM25:\nConnecting...\n",
                stderr="Cannot configure port",
            )
        )

        with patch.object(
            recovery_mode, "_port_detail", return_value={"device": "COM25"}
        ):
            result = recovery_mode.probe(services, "COM25", "tbeam_supreme")

        self.assertFalse(result["ready"])
        self.assertEqual(result["mode"], "unresponsive")
        self.assertEqual(result["transport"], "none")
        self.assertEqual(result["proven_chip"], "")

    def test_recovery_does_not_accept_degraded_chip_without_board_confirmation(
        self,
    ) -> None:
        services = self._recovery_services(
            SimpleNamespace(
                returncode=1,
                stdout="Connected to ESP32-S3 on COM25:\n",
                stderr="port disappeared",
            )
        )

        with patch.object(
            recovery_mode, "_port_detail", return_value={"device": "COM25"}
        ):
            result = recovery_mode.probe(services, "COM25", None)

        self.assertFalse(result["ready"])
        self.assertEqual(result["mode"], "esp-bootloader-ambiguous")
        self.assertEqual(result["proven_chip"], "ESP32-S3")

    def test_supreme_recovery_rejects_wrong_chip_even_on_zero_exit(self) -> None:
        services = self._recovery_services(
            SimpleNamespace(
                returncode=0,
                stdout="Connected to ESP32 on COM25:\n",
                stderr="",
            )
        )

        with patch.object(
            recovery_mode, "_port_detail", return_value={"device": "COM25"}
        ):
            result = recovery_mode.probe(services, "COM25", "tbeam_supreme")

        self.assertFalse(result["ready"])
        self.assertEqual(result["mode"], "esp-bootloader-mismatch")
        self.assertEqual(result["proven_chip"], "ESP32")


if __name__ == "__main__":
    unittest.main()
