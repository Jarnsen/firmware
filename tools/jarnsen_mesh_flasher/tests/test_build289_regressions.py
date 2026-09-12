from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock


APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import firmware_identity_reliable as identity_reliable
import radio_profile_legacy_fallback as legacy_fallback
import review_team_provisioning_guard as provisioning_guard


class Build289RegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        provisioning_guard._ROLE_INFO_CACHE.clear()

    def test_meshtastic_info_pio_env_is_reused_as_hardware_hint(self) -> None:
        text = (
            'My info: { "myNodeNum": 1130115052, "pioEnv": "tbeam-s3-core", '
            '"firmwareEdition": "VANILLA" }'
        )
        self.assertEqual(identity_reliable._hardware_hint_from_info(text), "tbeam-s3-core")

    def test_service_marker_accepts_final_line_without_newline(self) -> None:
        marker = "===JARNSEN_ROLE==="
        text = (
            "\x1b[32mINFO  \x1b[0m| booting\r\n"
            "\x1b[34mDEBUG \x1b[0m| Free heap 114936\r\n"
            "===JARNSEN_ROLE=== role=tak known=1 persisted=1 allowed=1 role_api=1"
        )
        self.assertEqual(
            legacy_fallback._extract_service_marker(text, marker),
            "===JARNSEN_ROLE=== role=tak known=1 persisted=1 allowed=1 role_api=1",
        )

    def test_service_marker_ignores_ansi_prefix_and_returns_marker_payload(self) -> None:
        marker = "===JARNSEN_ROLE==="
        text = (
            "noise\n"
            "\x1b[32mINFO \x1b[0m ===JARNSEN_ROLE=== role=tak known=1 persisted=1 role_api=1\r\n"
        )
        self.assertEqual(
            legacy_fallback._extract_service_marker(text, marker),
            "===JARNSEN_ROLE=== role=tak known=1 persisted=1 role_api=1",
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
            _parse_role_info=lambda line: {"role_api": "1"} if "role_api=1" in line else {},
            _adaptive_settle_auto_reboot=Mock(),
        )
        base_probe = Mock(side_effect=AssertionError("legacy TOOL_INFO probe must not run"))
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
            _parse_role_info=lambda line: {"role_api": "1"} if "role_api=1" in line else {},
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


if __name__ == "__main__":
    unittest.main()
