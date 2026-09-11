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
import radio_profiles
import role_write_finalize
import write_choice_guard


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

    def test_full_flash_consumes_pending_names_into_the_configure_payload(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "active.yaml"
            source.write_text(
                "config:\n  device:\n    role: CLIENT\n  power:\n    is_power_saving: true\n",
                encoding="utf-8",
            )
            captured = []
            record = SimpleNamespace(
                kind="full",
                expected_profile="",
                expected_role="",
                expected_long_name="",
                expected_short_name="",
            )
            manager = SimpleNamespace(active=lambda _port: record, _save=Mock())

            def base_restore(_port, profile):
                captured.append(efficiency._load_yaml(Path(profile)))

            services = SimpleNamespace(
                restore_profile=base_restore,
                set_names=Mock(),
                reboot_node=Mock(),
                verify_node=Mock(),
                flash_transactions=manager,
                PATHS=SimpleNamespace(root=root, active_profile=source),
            )
            old_installed = efficiency._INSTALLED
            efficiency._INSTALLED = False
            try:
                with patch.object(write_choice_guard, "_read_current_summary"), patch.object(
                    profile_restore, "split_profile_data"
                ), patch.object(radio_sync, "_read_active_profile"), patch.object(
                    radio_sync, "_write_firmware_slots"
                ), patch.object(role_write_finalize, "_set_role_explicit"):
                    efficiency.install(services)
                    services.prepare_profile_write("COM25", "Hardrock OPS 26", "HOPS")
                    services.restore_profile("COM25", source)
            finally:
                efficiency._INSTALLED = old_installed
                efficiency._PENDING_NAMES_BY_PORT.pop("COM25", None)
                efficiency._PROFILE_DIRTY.discard("COM25")

        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0]["owner"], "Hardrock OPS 26")
        self.assertEqual(captured[0]["owner_short"], "HOPS")
        self.assertEqual(record.expected_long_name, "Hardrock OPS 26")
        self.assertEqual(record.expected_short_name, "HOPS")

    def test_full_flash_waits_for_configure_reboot_without_an_explicit_second_reboot(self) -> None:
        record = SimpleNamespace(kind="full", status="running")
        manager = SimpleNamespace(
            active=lambda _port: record,
            stage_start=Mock(),
            stage_ok=Mock(),
            stage_fail=Mock(),
        )
        base_reboot = Mock()
        services = SimpleNamespace(
            restore_profile=Mock(),
            set_names=Mock(),
            reboot_node=base_reboot,
            verify_node=Mock(return_value=""),
            meshtastic=Mock(),
            flash_transactions=manager,
        )
        old_installed = stability._INSTALLED
        stability._INSTALLED = False
        stability._AUTO_REBOOT_PENDING["COM25"] = "profile-config"
        try:
            with patch.object(write_choice_guard, "_read_current_summary"), patch.object(
                radio_sync, "_read_active_profile"
            ), patch.object(stability, "_settle_auto_reboot") as settle:
                stability.install(services)
                services.reboot_node("COM25")
        finally:
            stability._INSTALLED = old_installed
            stability._AUTO_REBOOT_PENDING.pop("COM25", None)

        base_reboot.assert_not_called()
        settle.assert_called_once_with(services, "COM25", "profile-config")

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

    def test_successful_export_with_omitted_region_means_unset(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)

            def meshtastic(_port, _flag, target, **_kwargs):
                Path(target).write_text(
                    "config:\n  lora:\n    hop_limit: 7\n",
                    encoding="utf-8",
                )

            services = SimpleNamespace(
                PATHS=SimpleNamespace(root=root),
                meshtastic=meshtastic,
            )
            self.assertEqual(radio_sync._export_current_region("COM25", services), "UNSET")

    def test_full_flash_writes_selected_overlay_when_slot_service_is_unavailable(self) -> None:
        selected_during_write = []

        def base_restore(_port, _profile):
            selected_during_write.append(radio_profiles.load_settings(None)["selected"])

        services = SimpleNamespace(
            restore_profile=base_restore,
            flash_transactions=SimpleNamespace(active=lambda _port: SimpleNamespace(kind="full")),
            load_radio_profile_settings=lambda: {"selected": radio_profiles.PROFILE_JARNSEN_1},
            PATHS=SimpleNamespace(active_profile=Path("TAK.yaml")),
            _jarnsen_radio_slot_probe_state={"COM25": False},
        )

        with patch.object(radio_sync, "_install_us_region_policy"), patch.object(
            radio_sync, "_read_active_profile", return_value=radio_profiles.PROFILE_STANDARD
        ), patch.object(
            radio_profiles,
            "load_settings",
            return_value={"selected": radio_profiles.PROFILE_JARNSEN_1},
        ), patch.object(radio_sync, "_export_current_region") as export_region, patch.object(
            radio_sync, "_write_firmware_slots"
        ) as write_slots:
            radio_sync.install(services)
            services.restore_profile("COM25", Path("TAK.yaml"))

        self.assertEqual(selected_during_write, [radio_profiles.PROFILE_JARNSEN_1])
        export_region.assert_not_called()
        write_slots.assert_not_called()

    def test_full_flash_overwrites_unreadable_region_with_unset(self) -> None:
        base_restore = Mock()
        services = SimpleNamespace(
            restore_profile=base_restore,
            flash_transactions=SimpleNamespace(active=lambda _port: SimpleNamespace(kind="full")),
            load_radio_profile_settings=lambda: {"selected": radio_profiles.PROFILE_STANDARD},
            PATHS=SimpleNamespace(active_profile=Path("TAK.yaml")),
            _jarnsen_radio_slot_probe_state={"COM25": True},
        )

        with patch.object(radio_sync, "_install_us_region_policy"), patch.object(
            radio_sync, "_read_active_profile", return_value=radio_profiles.PROFILE_STANDARD
        ), patch.object(radio_sync, "_profile_region", return_value=""), patch.object(
            radio_sync, "_export_current_region", side_effect=RuntimeError("nicht lesbar")
        ), patch.object(radio_sync, "_write_firmware_slots") as write_slots:
            radio_sync.install(services)
            services.restore_profile("COM25", Path("TAK.yaml"))

        base_restore.assert_called_once_with("COM25", Path("TAK.yaml"))
        self.assertEqual(write_slots.call_args.args[3], "UNSET")

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

    def test_build_168_skips_unchanged_role_for_all_function_profiles(self) -> None:
        manager = SimpleNamespace(active=lambda _port: SimpleNamespace(kind="profile_only"))
        services = SimpleNamespace(
            flash_transactions=manager,
            query_jarnsen_identity=lambda *_args, **_kwargs: SimpleNamespace(build=168),
            FlasherError=RuntimeError,
        )
        roles = {
            "tak": "TAK",
            "tak_tracker": "TAK_TRACKER",
            "tak_repeater": "TAK_REPEATER",
            "drone_repeater": "DRONE_REPEATER",
        }

        for identifier, role in roles.items():
            with self.subTest(role=role):
                selected = SimpleNamespace(identifier=identifier)
                reply = (
                    f"===JARNSEN_ROLE=== role={role.lower()} known=1 "
                    "persisted=0 allowed=1 role_api=1"
                )
                stability._ROLE_SERVICE_REBOOT_PENDING.discard("COM25")
                with patch.object(
                    functional_profiles, "active_profile", return_value=selected
                ), patch.object(radio_sync, "_raw_command", return_value=reply) as raw:
                    stability._sync_firmware_role(services, "COM25")

                raw.assert_called_once_with(
                    "COM25",
                    "JARNSEN_TOOL_ROLE_INFO",
                    expected="===JARNSEN_ROLE===",
                    timeout=3.0,
                )
                self.assertNotIn("COM25", stability._ROLE_SERVICE_REBOOT_PENDING)


if __name__ == "__main__":
    unittest.main(verbosity=2)
