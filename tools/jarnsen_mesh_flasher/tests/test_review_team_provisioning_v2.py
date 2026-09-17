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

import functional_profiles  # noqa: E402
import profile_restore  # noqa: E402
import profile_runtime_stability_v2 as stability  # noqa: E402
import radio_profile_node_sync as node_sync  # noqa: E402
import review_team_provisioning_v2 as provisioning  # noqa: E402


class _FinishedProcess:
    def __init__(self, command):
        self.command = command
        self.stdout = iter(
            [
                "Connected to radio\n",
                "Setting device owner to Hardrock OPS 26 and short name to HOPS\n",
                "Set device.role to TAK\n",
                "commit open transaction\n",
                "Writing modified configuration to device\n",
            ]
        )

    def poll(self):
        return 0

    def wait(self, timeout=None):
        return 0


class ProvisioningV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        provisioning._EXPECTED_JARNSEN_ROLE_BY_PORT.clear()
        provisioning._FAST_IDENTITY_BY_PORT.clear()
        stability._ROLE_SERVICE_REBOOT_PENDING.clear()

    def _services(self, *, kind="full", build=168):
        record = SimpleNamespace(
            kind=kind,
            board_key="tbeam_supreme",
            expected_firmware_build=build,
        )
        return SimpleNamespace(
            flash_transactions=SimpleNamespace(active=lambda _port: record),
            cached_jarnsen_identity=lambda _port: None,
            wait_for_serial=Mock(),
            FlasherError=RuntimeError,
            BOARD_PROFILES={
                "tracker": {"label": "Heltec Wireless Tracker V1.1"},
                "repeater": {"label": "Heltec V3"},
                "wio": {"label": "Seeed Wio Tracker L1"},
                "heltec_v4": {"label": "Heltec V4"},
                "tbeam": {"label": "LILYGO T-Beam"},
                "tbeam_supreme": {"label": "LILYGO T-Beam Supreme"},
            },
        )

    def test_full_first_flash_uses_build168_role_service_and_readback(self) -> None:
        services = self._services(kind="full", build=168)
        selected = SimpleNamespace(identifier="tak", meshtastic_role="TAK")
        replies = [
            "===JARNSEN_INFO=== product=JARNSEN-MESH version=v2.0.0-alpha.27 build=168 hardware=LILYGO_TBEAM_SUPREME sha=abc role_api=1",
            "===JARNSEN_ROLE=== role=unconfigured known=0 persisted=0 allowed=1 role_api=1",
            "===JARNSEN_ROLE_OK=== role=tak verified=1 reboot_required=1",
            "===JARNSEN_ROLE=== role=tak known=1 persisted=1 allowed=1 role_api=1",
        ]
        with patch.object(
            functional_profiles, "active_profile", return_value=selected
        ), patch.object(node_sync, "_raw_command", side_effect=replies) as raw:
            provisioning._sync_firmware_role(services, "COM25")

        commands = [call.args[1] for call in raw.call_args_list]
        self.assertEqual(
            commands,
            [
                "JARNSEN_TOOL_INFO",
                "JARNSEN_TOOL_ROLE_INFO",
                "JARNSEN_TOOL_ROLE_SET tak",
                "JARNSEN_TOOL_ROLE_INFO",
            ],
        )
        self.assertEqual(provisioning._EXPECTED_JARNSEN_ROLE_BY_PORT["COM25"], "tak")
        self.assertIn("COM25", stability._ROLE_SERVICE_REBOOT_PENDING)

    def test_matching_but_not_persisted_role_is_written(self) -> None:
        services = self._services(kind="profile_only", build=168)
        selected = SimpleNamespace(
            identifier="tak_tracker", meshtastic_role="TAK_TRACKER"
        )
        replies = [
            "===JARNSEN_INFO=== product=JARNSEN-MESH version=v2.0.0-alpha.27 build=168 hardware=TRACKER sha=abc role_api=1",
            "===JARNSEN_ROLE=== role=tak_tracker known=1 persisted=0 allowed=1 role_api=1",
            "===JARNSEN_ROLE_OK=== role=tak_tracker verified=1 reboot_required=1",
            "===JARNSEN_ROLE=== role=tak_tracker known=1 persisted=1 allowed=1 role_api=1",
        ]
        with patch.object(
            functional_profiles, "active_profile", return_value=selected
        ), patch.object(node_sync, "_raw_command", side_effect=replies) as raw:
            provisioning._sync_firmware_role(services, "COM25")

        self.assertIn(
            "JARNSEN_TOOL_ROLE_SET tak_tracker",
            [call.args[1] for call in raw.call_args_list],
        )

    def test_persisted_matching_role_skips_role_set(self) -> None:
        services = self._services(kind="full", build=168)
        selected = SimpleNamespace(
            identifier="tak_repeater", meshtastic_role="ROUTER_LATE"
        )
        replies = [
            "===JARNSEN_INFO=== product=JARNSEN-MESH version=v2.0.0-alpha.27 build=168 hardware=TBEAM sha=abc role_api=1",
            "===JARNSEN_ROLE=== role=tak_repeater known=1 persisted=1 allowed=1 role_api=1",
        ]
        with patch.object(
            functional_profiles, "active_profile", return_value=selected
        ), patch.object(node_sync, "_raw_command", side_effect=replies) as raw:
            provisioning._sync_firmware_role(services, "COM25")

        self.assertEqual(raw.call_count, 2)
        self.assertNotIn("COM25", stability._ROLE_SERVICE_REBOOT_PENDING)

    def test_build167_keeps_legacy_role_path(self) -> None:
        services = self._services(kind="full", build=167)
        selected = SimpleNamespace(identifier="tak", meshtastic_role="TAK")
        with patch.object(
            functional_profiles, "active_profile", return_value=selected
        ), patch.object(node_sync, "_raw_command") as raw:
            provisioning._sync_firmware_role(services, "COM25")
        raw.assert_not_called()

    def test_drone_is_blocked_on_supreme_before_role_set(self) -> None:
        services = self._services(kind="full", build=168)
        selected = functional_profiles.functional_profile("drone_repeater")
        with patch.object(
            functional_profiles, "active_profile", return_value=selected
        ), self.assertRaises(RuntimeError), patch.object(
            node_sync, "_raw_command"
        ) as raw:
            provisioning._sync_firmware_role(services, "COM25")
        raw.assert_not_called()

    def test_drone_contract_allows_tracker_and_v4_only(self) -> None:
        services = self._services()
        original_compat = functional_profiles.compatibility_for_board
        original_fw = functional_profiles.firmware_compatibility_for_board
        original_require = functional_profiles.require_compatible_board
        original_profiles = functional_profiles.FUNCTIONAL_PROFILES
        original_by_id = functional_profiles._BY_ID
        original_by_label = functional_profiles._BY_LABEL
        try:
            provisioning._install_drone_contract(services)
            self.assertTrue(
                functional_profiles.compatibility_for_board(
                    "drone_repeater", "tracker", services
                )[0]
            )
            allowed_v4, message_v4 = functional_profiles.compatibility_for_board(
                "drone_repeater", "heltec_v4", services
            )
            self.assertTrue(allowed_v4)
            self.assertIn("externes GNSS", message_v4)
            for board in ("repeater", "wio", "tbeam", "tbeam_supreme"):
                with self.subTest(board=board):
                    self.assertFalse(
                        functional_profiles.compatibility_for_board(
                            "drone_repeater", board, services
                        )[0]
                    )
            self.assertTrue(
                functional_profiles.firmware_compatibility_for_board(
                    "drone_repeater", "tracker", services
                )[0]
            )
            self.assertTrue(
                functional_profiles.firmware_compatibility_for_board(
                    "drone_repeater", "heltec_v4", services
                )[0]
            )
        finally:
            functional_profiles.compatibility_for_board = original_compat
            functional_profiles.firmware_compatibility_for_board = original_fw
            functional_profiles.require_compatible_board = original_require
            functional_profiles.FUNCTIONAL_PROFILES = original_profiles
            functional_profiles._BY_ID = original_by_id
            functional_profiles._BY_LABEL = original_by_label
            if hasattr(functional_profiles, "_review_v2_base_firmware_compat"):
                delattr(functional_profiles, "_review_v2_base_firmware_compat")

    def test_same_process_owner_flags_precede_configure_and_pair_counts_two(
        self,
    ) -> None:
        captured = []
        emitted = []
        services = SimpleNamespace(
            helper_command=lambda: ["helper.exe"],
            _startupinfo=lambda: None,
            FlasherError=RuntimeError,
        )
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "profile.yaml"
            path.write_text("config:\n  device:\n    role: TAK\n", encoding="utf-8")
            profile_data = {
                "owner": "Hardrock OPS 26",
                "owner_short": "HOPS",
                "config": {"device": {"role": "TAK"}},
            }
            old_stream = profile_restore._stream_configure
            try:
                provisioning._install_profile_stream(services)

                def popen(command, **_kwargs):
                    captured.append(command)
                    return _FinishedProcess(command)

                with patch.object(
                    provisioning.subprocess, "Popen", side_effect=popen
                ), patch.object(profile_restore, "_emit", side_effect=emitted.append):
                    profile_restore._stream_configure(
                        services,
                        "COM25",
                        path,
                        profile_data,
                        timeout=10,
                        stage="Grundeinstellungen",
                        allow_disconnect_after_commit=True,
                    )
            finally:
                profile_restore._stream_configure = old_stream

        command = captured[0]
        self.assertLess(command.index("--set-owner"), command.index("--configure"))
        self.assertLess(
            command.index("--set-owner-short"), command.index("--configure")
        )
        self.assertTrue(any("seen=3/3" in line for line in emitted))

    def test_fast_backup_tries_921600_then_460800(self) -> None:
        calls = []

        def base_esptool(_port, *args, **_kwargs):
            calls.append(tuple(args))
            if "921600" in args:
                raise TimeoutError("read timeout")
            return "ok"

        services = SimpleNamespace(esptool=base_esptool)
        provisioning._install_fast_backup(services)
        result = services.esptool(
            "COM25",
            "--baud",
            "460800",
            "read-flash",
            "0x0",
            "0x800000",
            "backup.bin",
        )
        self.assertEqual(result, "ok")
        self.assertEqual(calls[0][calls[0].index("--baud") + 1], "921600")
        self.assertEqual(calls[1][calls[1].index("--baud") + 1], "460800")


if __name__ == "__main__":
    unittest.main(verbosity=2)
