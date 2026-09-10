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

import profile_restore
import profile_runtime_stability_v2 as stability
import profile_runtime_efficiency as efficiency
import functional_profiles
import radio_profile_node_sync as radio_sync


class _FinishedProcess:
    def __init__(self, command):
        self.command = command
        self.stdout = iter(
            [
                "Connected to radio\n",
                "Writing modified configuration to device\n",
                "commit open transaction\n",
            ]
        )

    def poll(self):
        return 0

    def wait(self, timeout=None):
        return 0


class _Clock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += float(seconds)


class ProfileWriteRebootRegressionTests(unittest.TestCase):
    def test_complete_payload_contains_owner_role_and_all_profile_fields(self) -> None:
        source = {
            "config": {
                "device": {"role": "CLIENT"},
                "power": {"is_power_saving": True, "wait_bluetooth_secs": 120},
                "lora": {"hop_limit": 20},
            }
        }
        payload = efficiency._complete_profile_payload(
            source,
            role="TAK",
            long_name="Hardrock OPS 26",
            short_name="HOPS",
        )
        self.assertEqual(payload["owner"], "Hardrock OPS 26")
        self.assertEqual(payload["owner_short"], "HOPS")
        self.assertEqual(payload["config"]["device"]["role"], "TAK")
        self.assertEqual(payload["config"]["power"]["wait_bluetooth_secs"], 120)
        self.assertEqual(payload["config"]["lora"]["hop_limit"], 20)
        self.assertEqual(source["config"]["device"]["role"], "CLIENT")

    def test_profile_only_never_reopens_serial_for_radio_slot_sync(self) -> None:
        base_restore = Mock(return_value="written")
        record = SimpleNamespace(kind="profile_only")
        manager = SimpleNamespace(active=lambda _port: record)
        services = SimpleNamespace(
            restore_profile=base_restore,
            flash_transactions=manager,
        )

        with patch.object(radio_sync, "_install_us_region_policy"):
            radio_sync.install(services)
        result = services.restore_profile("COM25", Path("TAK.yaml"))

        self.assertEqual(result, "written")
        base_restore.assert_called_once_with("COM25", Path("TAK.yaml"))

    def test_configure_waits_for_the_firmware_disconnect(self) -> None:
        commands = []

        def popen(command, **_kwargs):
            commands.append(command)
            return _FinishedProcess(command)

        services = SimpleNamespace(
            helper_command=lambda: [],
            _startupinfo=lambda: None,
            FlasherError=RuntimeError,
        )
        with tempfile.TemporaryDirectory() as folder:
            profile = Path(folder) / "full.yaml"
            profile.write_text("config:\n  device:\n    role: TAK\n", encoding="utf-8")
            with patch.object(profile_restore.subprocess, "Popen", side_effect=popen):
                profile_restore._stream_configure(
                    services,
                    "COM25",
                    profile,
                    {"config": {"device": {"role": "TAK"}}},
                    timeout=10,
                    stage="Grundeinstellungen",
                    allow_disconnect_after_commit=True,
                )

        self.assertEqual(commands[0][-2:], ["--wait-to-disconnect", "1"])

    def test_owner_role_and_power_remain_in_one_profile_transaction(self) -> None:
        safe, final, removed = profile_restore.split_profile_data(
            {
                "owner": "Hardrock OPS 26",
                "owner_short": "HOPS",
                "config": {
                    "device": {"role": "TAK"},
                    "power": {"is_power_saving": True, "wait_bluetooth_secs": 120},
                },
            }
        )
        # The base splitter still defers role/power; the runtime full-write layer
        # merges final into safe before the sole --configure invocation. Owner
        # fields must survive so Meshtastic can call setOwner before commit.
        self.assertEqual(safe["owner"], "Hardrock OPS 26")
        self.assertEqual(safe["owner_short"], "HOPS")
        self.assertEqual(final["config"]["device"]["role"], "TAK")
        self.assertEqual(final["config"]["power"]["is_power_saving"], True)
        self.assertEqual(removed, [])

    def test_reboot_wait_observes_disconnect_and_stable_return(self) -> None:
        clock = _Clock()

        def comports():
            # Present initially, absent during reboot, then continuously present.
            return [] if 2.0 <= clock.now < 5.0 else [SimpleNamespace(device="COM25")]

        services = SimpleNamespace(
            list_ports=SimpleNamespace(comports=comports),
            wait_for_serial=Mock(),
            FlasherError=RuntimeError,
        )
        with patch.object(stability.time, "monotonic", side_effect=clock.monotonic), patch.object(
            stability.time, "sleep", side_effect=clock.sleep
        ):
            stability._settle_auto_reboot(services, "COM25", "profile-config", wait_seconds=8)

        services.wait_for_serial.assert_called_once_with("COM25", timeout=90)
        self.assertGreaterEqual(clock.now, 11.0)

    def test_build_167_keeps_legacy_meshtastic_role_path(self) -> None:
        manager = SimpleNamespace(active=lambda _port: SimpleNamespace(kind="profile_only"))
        services = SimpleNamespace(
            flash_transactions=manager,
            query_jarnsen_identity=lambda *_args, **_kwargs: SimpleNamespace(build=167),
        )
        selected = SimpleNamespace(identifier="tak_tracker")
        with patch.object(functional_profiles, "active_profile", return_value=selected), patch.object(
            radio_sync, "_raw_command"
        ) as raw:
            stability._sync_firmware_role(services, "COM25")
        raw.assert_not_called()

    def test_build_168_persists_authoritative_firmware_role(self) -> None:
        manager = SimpleNamespace(active=lambda _port: SimpleNamespace(kind="profile_only"))
        services = SimpleNamespace(
            flash_transactions=manager,
            query_jarnsen_identity=lambda *_args, **_kwargs: SimpleNamespace(build=168),
            FlasherError=RuntimeError,
        )
        selected = SimpleNamespace(identifier="tak_tracker")
        stability._ROLE_SERVICE_REBOOT_PENDING.discard("COM25")
        replies = (
            "===JARNSEN_ROLE=== role=TAK known=1 persisted=1 allowed=1 role_api=1",
            "===JARNSEN_ROLE_OK=== role=TAK_TRACKER verified=1 reboot_required=1",
        )
        with patch.object(functional_profiles, "active_profile", return_value=selected), patch.object(
            radio_sync, "_raw_command", side_effect=replies
        ) as raw:
            stability._sync_firmware_role(services, "COM25")

        self.assertEqual(raw.call_count, 2)
        self.assertEqual(raw.call_args_list[1].args[1], "JARNSEN_TOOL_ROLE_SET TAK_TRACKER")
        self.assertIn("COM25", stability._ROLE_SERVICE_REBOOT_PENDING)
        stability._ROLE_SERVICE_REBOOT_PENDING.discard("COM25")


if __name__ == "__main__":
    unittest.main(verbosity=2)
