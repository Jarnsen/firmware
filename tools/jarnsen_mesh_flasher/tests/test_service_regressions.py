# ruff: noqa: E402
from __future__ import annotations

import importlib
import io
import subprocess
import sys
import threading
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import advanced_flasher as advanced  # noqa: E402
import backup_stability  # noqa: E402
import firmware_identity_sha_match as identities  # noqa: E402
import firmware_status_ui as status  # noqa: E402
import flash_runtime  # noqa: E402
import name_write_finalize as name_finalize  # noqa: E402
import radio_profile_legacy_fallback as legacy  # noqa: E402
import radio_profile_node_sync as radio  # noqa: E402
import radio_profile_runtime_stability as radio_runtime  # noqa: E402
import review_team_provisioning_v2 as provisioning  # noqa: E402
import services as base_services  # noqa: E402
import tls_provisioning as tls  # noqa: E402
import unified_service_v2 as unified  # noqa: E402


class FakeSerial:
    def __init__(self, chunks):
        self.chunks = iter(chunks)
        self.reads = 0
        self.writes = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def reset_input_buffer(self):
        pass

    def write(self, data):
        self.writes.append(data)
        return len(data)

    def flush(self):
        pass

    def read(self, size):
        self.reads += 1
        return next(self.chunks)


class ServiceTests(unittest.TestCase):
    def test_helper_timeout_is_real_wall_clock_limit(self):
        started = time.monotonic()
        with self.assertRaises(subprocess.TimeoutExpired):
            base_services._run_process_hard_timeout(
                [sys.executable, "-c", "import time; time.sleep(10)"],
                timeout=1,
            )
        self.assertLess(time.monotonic() - started, 4.5)

    def test_helper_process_can_be_cancelled_immediately(self):
        base_services.begin_operation()
        timer = threading.Timer(0.35, base_services.cancel_current_operation)
        timer.start()
        started = time.monotonic()
        try:
            with self.assertRaises(base_services.OperationCancelled):
                base_services._run_process_hard_timeout(
                    [sys.executable, "-c", "import time; time.sleep(30)"],
                    timeout=20,
                )
        finally:
            timer.cancel()
            base_services.finish_operation()
        self.assertLess(time.monotonic() - started, 3.5)

    def test_serial_scan_is_normal_mode_and_short_timeout(self):
        source = (Path(__file__).resolve().parents[1] / "serial_probe.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("def scan_devices(probe_timeout: int = 4)", source)
        self.assertIn("normal-mode=1", source)
        self.assertIn("SERIAL FAST IDENTITY", source)

    def test_tracker_identity_probe_retries_inside_fast_window(self):
        source = (
            Path(__file__).resolve().parents[1] / "firmware_status_ui.py"
        ).read_text(encoding="utf-8")
        self.assertIn("send_count < 4", source)
        self.assertIn("next_send = now + 0.32", source)
        self.assertIn("FIRMWARE IDENTITY FAST SEND", source)

    def test_v3_fast_identity_opens_without_dtr_rts_reset_lines(self):
        source = (
            Path(__file__).resolve().parents[1] / "firmware_status_ui.py"
        ).read_text(encoding="utf-8")
        self.assertIn("def _open_identity_serial(", source)
        self.assertIn("handle.dtr = False", source)
        self.assertIn("handle.rts = False", source)
        self.assertIn("with _open_identity_serial(", source)

    def test_tls_session_reuses_reset_safe_ansi_safe_raw_transport(self):
        source = (
            Path(__file__).resolve().parents[1] / "tls_provisioning.py"
        ).read_text(encoding="utf-8")
        self.assertIn("legacy._open_serial_no_control_lines(", source)
        self.assertIn("legacy._extract_service_marker(text, expected)", source)
        self.assertIn("include_unterminated=True", source)

    def test_ansi_prefixed_jarnsen_info_marker_is_extracted(self):
        esc = chr(27)
        wire = (
            f"{esc}[0m{esc}[32mINFO  {esc}[0m| boot\r\n"
            f"{esc}[0m===JARNSEN_INFO=== product=JARNSEN-MESH "
            "version=v2.0.0-alpha.34 build=359 hardware=HELTEC V3 "
            "sha=ad5fff10 tls_provision=1\r\n"
        )
        line = legacy._extract_service_marker(wire, "===JARNSEN_INFO===")
        self.assertIsNotNone(line)
        self.assertTrue(str(line).startswith("===JARNSEN_INFO==="))
        self.assertIn("build=359", str(line))
        self.assertIn("tls_provision=1", str(line))

    def test_tls_raw_session_accepts_ansi_prefixed_info(self):
        esc = chr(27)
        response = (
            f"{esc}[0m===JARNSEN_INFO=== product=JARNSEN-MESH "
            "version=v2.0.0-alpha.34 build=359 hardware=HELTEC V3 "
            "sha=ad5fff10 tls_provision=1\r\n"
        ).encode()
        session = tls._RawSession("COM13")
        session.ser = FakeSerial([response])

        line = session.command(
            "JARNSEN_TOOL_INFO",
            "===JARNSEN_INFO===",
            timeout=0.2,
        )

        self.assertTrue(line.startswith("===JARNSEN_INFO==="))
        self.assertIn("build=359", line)
        self.assertEqual(session.ser.writes, [b"JARNSEN_TOOL_INFO\n"])

    def test_exact_identity_promotes_unknown_board_without_rescan(self):
        source = (
            Path(__file__).resolve().parents[1] / "radio_profile_legacy_fallback.py"
        ).read_text(encoding="utf-8")
        self.assertIn("BOARD AUTO IDENTITY", source)
        self.assertIn("identity_running", source)
        self.assertIn("current.board_key = detected", source)
        self.assertIn("_update_device_list", source)

    def test_actions_fallback_queries_only_unified_workflow(self):
        source = (Path(__file__).resolve().parents[1] / "services.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("/actions/workflows/{workflow_file}/runs", source)
        self.assertNotIn(
            'f"{self.api}/repos/{REPOSITORY}/actions/runs",\n'
            "            branch=UNIFIED_BRANCH,\n"
            '            status="success",\n'
            "            per_page=50,",
            source,
        )

    def test_profile_write_skips_expensive_prewrite_export(self):
        source = (
            Path(__file__).resolve().parents[1] / "profile_runtime_efficiency.py"
        ).read_text(encoding="utf-8")
        restore_start = source.index(
            "    def restore_profile(port: str, profile=None):"
        )
        restore_end = source.index(
            "    # ------------------------------------------------------------------ names are written only after",
            restore_start,
        )
        restore_body = source[restore_start:restore_end]
        self.assertIn("PROFILE DIRECT PLAN", restore_body)
        self.assertIn("prewrite-export=0", restore_body)
        self.assertNotIn("_export_current_profile(", restore_body)

    def test_profile_only_reuses_already_detected_board(self):
        source = (Path(__file__).resolve().parents[1] / "profile_only.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("PROFIL-ONLY BOARD CHECK CACHE", source)
        self.assertIn("zweites --info=übersprungen", source)

    def test_name_finalize_prefers_direct_firmware_owner_service(self):
        services = SimpleNamespace(
            meshtastic=Mock(),
            FlasherError=RuntimeError,
        )
        with patch.object(
            name_finalize.radio_sync,
            "_raw_command",
            return_value="===JARNSEN_OWNER_OK=== action=set persisted=1",
        ) as raw_command, patch.object(name_finalize.time, "sleep"):
            live = name_finalize._write_names_atomic(
                services, "COM13", "REPEATER 1", "R1"
            )

        self.assertEqual(live, "COM13")
        raw_command.assert_called_once_with(
            "COM13",
            "JARNSEN_TOOL_OWNER_SET 52455045415445522031 5231",
            expected="===JARNSEN_OWNER_OK===",
            timeout=8.0,
        )
        services.meshtastic.assert_not_called()

    def test_name_finalize_skips_duplicate_profile_stream_write(self):
        record = SimpleNamespace(
            kind="profile_only",
            completed=["profile"],
            expected_long_name="REPEATER 1",
            expected_short_name="R1",
        )
        manager = SimpleNamespace(active=lambda _port: record)
        services = SimpleNamespace(
            _jarnsen_profile_names_same_process=True,
            flash_transactions=manager,
        )
        self.assertTrue(
            name_finalize._names_already_written_in_profile(
                services, "COM13", "REPEATER 1", "R1"
            )
        )
        self.assertFalse(
            name_finalize._names_already_written_in_profile(
                services, "COM13", "ANDERER NAME", "R1"
            )
        )

    def test_build_hint_uses_fast_jarnsen_identity_when_cache_is_empty(self):
        provisioning._FAST_IDENTITY_BY_PORT.clear()
        identity = SimpleNamespace(is_jarnsen=True, build=283)
        services = SimpleNamespace(
            flash_transactions=None,
            cached_jarnsen_identity=lambda _port: None,
            fast_jarnsen_identity=lambda _port, timeout=1.1: identity,
        )
        self.assertEqual(provisioning._cached_build_hint(services, "COM13"), 283)
        self.assertIs(provisioning._FAST_IDENTITY_BY_PORT["COM13"], identity)

    def test_bridge_reboot_wait_finishes_on_two_fresh_app_replies(self):
        class Clock:
            def __init__(self):
                self.now = 0.0

            def monotonic(self):
                return self.now

            def sleep(self, seconds):
                self.now += float(seconds)

        clock = Clock()
        wait_calls = []
        identity = SimpleNamespace(is_jarnsen=True, build=283)
        services = SimpleNamespace(
            list_ports=SimpleNamespace(
                comports=lambda: [SimpleNamespace(device="COM13")]
            ),
            fast_jarnsen_identity=lambda _port, timeout=0.8: identity,
            wait_for_serial=lambda *_args, **_kwargs: wait_calls.append(True),
            FlasherError=RuntimeError,
        )
        with patch.object(
            provisioning.time, "monotonic", clock.monotonic
        ), patch.object(provisioning.time, "sleep", clock.sleep):
            provisioning._adaptive_settle_auto_reboot(
                services, "COM13", "test", wait_seconds=30
            )

        self.assertFalse(wait_calls)
        self.assertLess(clock.now, 8.0)

    def test_dashboard_exposes_red_cancel_action(self):
        source = (
            Path(__file__).resolve().parents[1] / "reference_dashboard.py"
        ).read_text(encoding="utf-8")
        self.assertIn('text="AKTION ABBRECHEN"', source)
        self.assertIn('fg_color="#B91C1C"', source)
        self.assertIn("cancel_current_operation", source)

    def test_v3_usb_log_is_normal_mode_first_with_manual_reset_fallback(self):
        source = (
            Path(__file__).resolve().parents[1] / "v3_usb_log_stability.py"
        ).read_text(encoding="utf-8")
        self.assertIn("normal-mode-first=1", source)
        self.assertIn("no-auto-reboot=1", source)
        self.assertIn("idle_timeout: float = 60.0", source)
        self.assertIn("timeout=900.0", source)
        self.assertIn("USER/BOOT nicht gedrückt halten", source)

    def test_factory_slot_proof_writes_only_missing_app_slot(self):
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            update = b"\xe9" + b"U" * 63
            factory = bytearray(b"\xff" * 0x300)
            factory[0x100 : 0x100 + len(update)] = update
            factory_path = root / "factory.bin"
            update_path = root / "update.bin"
            factory_path.write_bytes(factory)
            update_path.write_bytes(update)
            bundle = SimpleNamespace(
                factory=factory_path,
                update=update_path,
                flash_targets=[
                    ("app0", 0x100, 0x100),
                    ("app1", 0x200, 0x100),
                ],
            )
            present, missing = flash_runtime._factory_missing_update_targets(
                SimpleNamespace(), bundle
            )

        self.assertEqual(present, [("app0", 0x100, 0x100)])
        self.assertEqual(missing, [("app1", 0x200, 0x100)])

    def test_factory_slot_proof_refuses_unproven_factory(self):
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            update_path = root / "update.bin"
            factory_path = root / "factory.bin"
            update_path.write_bytes(b"\xe9" + b"U" * 31)
            factory_path.write_bytes(b"\xff" * 0x300)
            bundle = SimpleNamespace(
                factory=factory_path,
                update=update_path,
                flash_targets=[
                    ("app0", 0x100, 0x100),
                    ("app1", 0x200, 0x100),
                ],
            )
            with self.assertRaisesRegex(ValueError, "keinem App-Slot"):
                flash_runtime._factory_missing_update_targets(SimpleNamespace(), bundle)

    def test_fragmented_radio_reply(self):
        for reader in (radio._raw_command, legacy._stable_raw_command):
            for separator in (b"\r\n", b"\n"):
                with self.subTest(reader=reader.__name__, separator=separator):
                    port = FakeSerial(
                        [b"===JARNSEN_RADIO=== active=jarn", b"sen1 slots=3", separator]
                    )
                    with patch.object(
                        radio.serial, "Serial", return_value=port
                    ), patch.object(radio.time, "sleep"):
                        result = reader(
                            "COM1",
                            "JARNSEN_TOOL_RADIO_INFO",
                            expected=radio.RADIO_INFO_MARKER,
                        )
                    self.assertEqual(
                        result, "===JARNSEN_RADIO=== active=jarnsen1 slots=3"
                    )
                    self.assertEqual(port.reads, 3)

    def test_fragmented_identity_reply(self):
        for reader in (status.query_jarnsen_identity, legacy._stable_identity_query):
            with self.subTest(reader=reader.__name__):
                port = FakeSerial(
                    [
                        b"===JARNSEN_INFO=== product=JARNSEN-MESH version=2.0.",
                        b"0-alpha.26 build=170 hardware=Heltec V3 sha=abcdef1\r\n",
                    ]
                )
                with patch.object(
                    status.serial, "Serial", return_value=port
                ), patch.object(status.time, "sleep"):
                    result = reader("COM1")
                self.assertEqual(result.version, "2.0.0-alpha.26")
                self.assertEqual(result.build, 170)
                self.assertEqual(result.hardware, "Heltec V3")
                self.assertEqual(result.sha, "abcdef1")

    def test_identity_reply_without_final_newline_is_accepted(self):
        port = FakeSerial(
            [
                (
                    b"===JARNSEN_INFO=== product=JARNSEN-MESH "
                    b"version=2.0.0-alpha.34 build=264 "
                    b"hardware=Heltec V3 sha=abcdef1"
                )
            ]
        )
        with patch.object(status.serial, "Serial", return_value=port), patch.object(
            status.time, "sleep"
        ):
            result = status.query_jarnsen_identity("COM13", timeout=0.5)

        self.assertIsNotNone(result)
        self.assertTrue(result.is_jarnsen)
        self.assertEqual(result.build, 264)
        self.assertEqual(result.hardware, "Heltec V3")

    def test_radio_capture_is_not_replayed_behind_stale_info(self):
        port = FakeSerial(
            [
                (
                    b"===JARNSEN_RADIO=== active=standard slots=3 "
                    b"standard=1 jarnsen1=1 jarnsen2=1\r\n"
                ),
                (
                    b"===JARNSEN_RADIO=== active=standard slots=3 "
                    b"standard=1 jarnsen1=1 jarnsen2=1\r\n"
                ),
                b"===JARNSEN_RADIO_OK=== action=capture profile=standard\r\n",
            ]
        )
        with patch.object(radio.serial, "Serial", return_value=port), patch.object(
            radio.time, "sleep"
        ):
            result = legacy._stable_raw_command(
                "COM13",
                "JARNSEN_TOOL_RADIO_CAPTURE_STANDARD",
                expected=radio.RADIO_OK_MARKER,
                timeout=8.0,
            )

        self.assertEqual(
            result,
            "===JARNSEN_RADIO_OK=== action=capture profile=standard",
        )
        self.assertEqual(
            port.writes,
            [b"JARNSEN_TOOL_RADIO_CAPTURE_STANDARD\n"],
        )

    def test_backup_packet_content_transfer_stop_uses_baud_fallback(self):
        self.assertTrue(
            backup_stability._retryable(
                RuntimeError(
                    "ERROR: A fatal error occurred: Packet content transfer stopped"
                )
            )
        )

    def test_error_reply_is_not_success(self):
        port = FakeSerial([b"===JARNSEN_RADIO_ERROR=== action=set\r\n"])
        with patch.object(radio.serial, "Serial", return_value=port):
            with self.assertRaises(RuntimeError):
                legacy._stable_raw_command(
                    "COM1",
                    "JARNSEN_TOOL_RADIO_SET jarnsen1",
                    expected=radio.RADIO_OK_MARKER,
                )

    def test_multiple_slots_use_one_process(self):
        targets = [("app0", 0x20000, 0x100000), ("app1", 0x120000, 0x100000)]
        with patch.object(flash_runtime, "_stream_esptool") as stream:
            unified._write_update_slots(
                None, "COM1", ["write-flash"], Path("update.bin"), targets, None
            )
        stream.assert_called_once()
        self.assertEqual(
            stream.call_args.args[2],
            ["write-flash", "0x20000", "update.bin", "0x120000", "update.bin"],
        )
        self.assertEqual(stream.call_args.kwargs["progress_parts"], 2)

    def test_empty_slots_rejected(self):
        with patch.object(flash_runtime, "_stream_esptool") as stream:
            with self.assertRaises(ValueError):
                unified._write_update_slots(
                    None, "COM1", ["write-flash"], Path("update.bin"), [], None
                )
            stream.assert_not_called()

    def test_firmware_only_esp32_uses_dynamic_targets_in_one_process(self):
        targets = [("app0", 0x20000, 0x100000), ("app1", 0x120000, 0x100000)]
        services = SimpleNamespace(
            BOARD_PROFILES={"heltec_v4": {"artifact_kind": "esp32"}},
            _jarnsen_flash_baud="460800",
        )
        bundle = SimpleNamespace(update=Path("update.bin"), flash_targets=targets)
        with patch.object(flash_runtime, "_stream_esptool") as stream:
            unified.flash_firmware_only_bundle(
                services, "COM4", "heltec_v4", bundle, None
            )

        self.assertEqual(stream.call_count, 2)
        write = stream.call_args_list[0]
        self.assertEqual(
            write.args[2],
            [
                "--baud",
                "460800",
                "write-flash",
                "--flash-mode",
                "dio",
                "--flash-freq",
                "80m",
                "--flash-size",
                "keep",
                "0x20000",
                "update.bin",
                "0x120000",
                "update.bin",
            ],
        )
        self.assertEqual(write.kwargs["progress_parts"], 2)
        self.assertEqual(stream.call_args_list[1].args[2], ["run"])

    def test_v3_firmware_only_skips_redundant_esptool_run(self):
        services = SimpleNamespace(
            BOARD_PROFILES={"repeater": {"artifact_kind": "esp32"}},
            _jarnsen_flash_baud="921600",
            flash_baud_candidates=lambda value: (str(value),),
            is_retryable_flash_error=lambda _exc: False,
        )
        bundle = SimpleNamespace(
            update=Path("update.bin"),
            flash_targets=[("app0", 0x10000, 0x300000)],
        )
        with patch.object(unified, "_write_update_slots") as write_slots, patch.object(
            flash_runtime, "_stream_esptool"
        ) as stream:
            unified.flash_firmware_only_bundle(
                services,
                "COM13",
                "repeater",
                bundle,
                None,
            )

        write_slots.assert_called_once()
        stream.assert_not_called()

    def test_firmware_only_wio_delegates_to_uf2_runtime(self):
        services = SimpleNamespace(
            BOARD_PROFILES={"wio": {"artifact_kind": "uf2"}},
            flash_bundle=Mock(),
        )
        bundle = SimpleNamespace(update=Path("firmware.uf2"))
        log = Mock()
        with patch.object(flash_runtime, "_stream_esptool") as stream:
            unified.flash_firmware_only_bundle(services, "COM7", "wio", bundle, log)

        services.flash_bundle.assert_called_once_with("COM7", bundle, log=log)
        stream.assert_not_called()

    def test_supreme_uses_native_usb_reset_without_redundant_run(self):
        services = SimpleNamespace(
            BOARD_PROFILES={"tbeam_supreme": {"artifact_kind": "esp32"}},
            _jarnsen_flash_baud="921600",
        )
        bundle = SimpleNamespace(
            update=Path("update.bin"),
            flash_targets=[("app0", 0x10000, 0x300000), ("app1", 0x340000, 0x300000)],
        )
        with patch.object(flash_runtime, "_stream_esptool") as stream:
            stream.return_value.returncode = 0
            unified.flash_firmware_only_bundle(
                services, "COM24", "tbeam_supreme", bundle, None
            )

        self.assertEqual(stream.call_count, 2)
        reset_args = stream.call_args_list[0].args[2]
        self.assertIn("1200", reset_args)
        self.assertIn("read-flash-status", reset_args)
        args = stream.call_args_list[1].args[2]
        self.assertEqual(
            args[:8],
            [
                "--chip",
                "esp32s3",
                "--before",
                "no-reset",
                "--after",
                "watchdog-reset",
                "--baud",
                "921600",
            ],
        )
        self.assertIn("write-flash", args)

    def test_no_serial_data_stops_useless_baud_retries(self):
        services = SimpleNamespace(
            BOARD_PROFILES={"tbeam_supreme": {"artifact_kind": "esp32"}},
            _jarnsen_flash_baud="921600",
            flash_baud_candidates=lambda _value: ("921600", "460800", "115200"),
            is_retryable_flash_error=lambda _exc: True,
            FlasherError=RuntimeError,
        )
        bundle = SimpleNamespace(
            update=Path("update.bin"),
            flash_targets=[("app0", 0x10000, 0x300000)],
        )
        reset_ok = SimpleNamespace(returncode=0)
        failure = RuntimeError(
            "Failed to connect to Espressif device: No serial data received."
        )
        with patch.object(
            flash_runtime, "_stream_esptool", side_effect=(reset_ok, failure)
        ) as stream:
            with self.assertRaisesRegex(RuntimeError, "SUPREME_BOOTLOADER_SYNC"):
                unified.flash_firmware_only_bundle(
                    services, "COM24", "tbeam_supreme", bundle, None
                )
        self.assertEqual(stream.call_count, 2)

    def test_supreme_repeats_failed_1200_bps_reset_once(self):
        services = SimpleNamespace()
        log = Mock()
        with patch.object(
            flash_runtime,
            "_stream_esptool",
            side_effect=(SimpleNamespace(returncode=2), SimpleNamespace(returncode=0)),
        ) as stream, patch.object(unified.time, "sleep"):
            port = unified.prepare_supreme_download_mode(services, "COM24", log)

        self.assertEqual(port, "COM24")
        self.assertEqual(stream.call_count, 2)
        for call in stream.call_args_list:
            self.assertIn("1200", call.args[2])
            self.assertIn("read-flash-status", call.args[2])

    def test_supreme_rejects_registry_only_port_before_esptool(self):
        services = SimpleNamespace(
            live_serial_port=lambda _port: None,
            FlasherError=RuntimeError,
        )
        with patch.object(flash_runtime, "_stream_esptool") as stream:
            with self.assertRaisesRegex(
                RuntimeError, "COM-Port ist nicht mehr vorhanden"
            ):
                unified.prepare_supreme_download_mode(services, "COM22", None)
        stream.assert_not_called()

        summary, guidance = advanced.friendly_error(
            RuntimeError("SUPREME_PORT_MISSING: COM22 ist nicht mehr vorhanden")
        )
        self.assertIn("nicht mehr vorhanden", summary)
        self.assertTrue(any("Neu suchen" in line for line in guidance))

    def test_supreme_follows_com_renumbering_before_write(self):
        services = SimpleNamespace(
            BOARD_PROFILES={"tbeam_supreme": {"artifact_kind": "esp32"}},
            _jarnsen_flash_baud="921600",
            live_serial_port=lambda port: port,
            wait_for_device_reconnect=lambda *_args, **_kwargs: "COM23",
        )
        bundle = SimpleNamespace(
            update=Path("update.bin"),
            flash_targets=[("app0", 0x10000, 0x300000)],
        )
        with patch.object(flash_runtime, "_stream_esptool") as stream:
            stream.return_value.returncode = 0
            unified.flash_firmware_only_bundle(
                services, "COM22", "tbeam_supreme", bundle, None
            )

        self.assertEqual(stream.call_count, 2)
        self.assertEqual(stream.call_args_list[0].args[1], "COM22")
        self.assertEqual(stream.call_args_list[1].args[1], "COM23")

    def test_supreme_port_vanishing_before_reset_has_specific_error(self):
        services = SimpleNamespace(
            live_serial_port=lambda port: port,
            FlasherError=RuntimeError,
        )
        failure = RuntimeError("Could not open COM22: FileNotFoundError(2)")
        with patch.object(
            flash_runtime, "_stream_esptool", side_effect=failure
        ) as stream:
            with self.assertRaisesRegex(RuntimeError, "SUPREME_PORT_MISSING"):
                unified.prepare_supreme_download_mode(services, "COM22", None)
        stream.assert_called_once()

    def test_missing_port_during_write_stops_baud_retries(self):
        services = SimpleNamespace(
            BOARD_PROFILES={"tbeam_supreme": {"artifact_kind": "esp32"}},
            _jarnsen_flash_baud="921600",
            live_serial_port=lambda port: port,
            flash_baud_candidates=lambda _value: ("921600", "460800", "115200"),
            is_retryable_flash_error=lambda _exc: True,
            FlasherError=RuntimeError,
        )
        bundle = SimpleNamespace(
            update=Path("update.bin"),
            flash_targets=[("app0", 0x10000, 0x300000)],
        )
        reset_ok = SimpleNamespace(returncode=0)
        missing = RuntimeError("Could not open COM22: FileNotFoundError(2)")
        with patch.object(
            flash_runtime, "_stream_esptool", side_effect=(reset_ok, missing)
        ) as stream:
            with self.assertRaisesRegex(RuntimeError, "SUPREME_BOOTLOADER_SYNC"):
                unified.flash_firmware_only_bundle(
                    services, "COM22", "tbeam_supreme", bundle, None
                )
        self.assertEqual(stream.call_count, 2)

    def test_bootloader_sync_error_has_specific_guidance(self):
        summary, guidance = advanced.friendly_error(
            RuntimeError("SUPREME_BOOTLOADER_SYNC: No serial data received")
        )
        self.assertIn("manuellen Downloadmodus", summary)
        self.assertTrue(any("BOOT" in line and "USB" in line for line in guidance))
        self.assertFalse(
            advanced.is_retryable_flash_error(RuntimeError("No serial data received"))
        )

    def test_stream_invalidation_and_multislot_progress(self):
        progress = []
        locked = []

        @contextmanager
        def guard(port):
            locked.append(port)
            try:
                yield
            finally:
                locked.pop()

        services = SimpleNamespace(
            helper_command=lambda: ["helper"],
            _startupinfo=lambda: None,
            invalidate_jarnsen_identity=Mock(),
            jarnsen_serial_guard=guard,
            _jarnsen_flash_progress_callback=lambda value, *args: progress.append(
                value
            ),
        )
        process = Mock(
            stdout=io.StringIO(
                "Writing at 0x20000 (100 %)\nHash of data verified.\n"
                "Writing at 0x120000 (50 %)\nWriting at 0x120000 (100 %)\nHash of data verified.\n"
            )
        )
        process.poll.return_value = 0
        process.wait.return_value = 0

        def popen(*args, **kwargs):
            self.assertEqual(locked, ["COM1"])
            return process

        with patch.object(flash_runtime.subprocess, "Popen", side_effect=popen):
            flash_runtime._stream_esptool(
                services,
                "COM1",
                ["write-flash"],
                timeout=5,
                stage="test",
                phase_start=0,
                phase_end=1,
                log=None,
                progress_parts=2,
            )
        self.assertEqual(services.invalidate_jarnsen_identity.call_count, 2)
        self.assertEqual(locked, [])
        self.assertEqual(progress, [0, 0.5, 0.75, 1.0, 1])


class RadioRuntimeFastPathTests(unittest.TestCase):
    def test_full_profile_standard_preflight_skips_meshtastic_export(self):
        services = SimpleNamespace(
            BOARD_PROFILES={"repeater": {"label": "Heltec V3"}},
            load_radio_profile_settings=Mock(return_value={}),
        )
        response = (
            "===JARNSEN_RADIO=== active=standard slots=3 "
            "standard=1 jarnsen1=1 jarnsen2=1"
        )
        with patch.object(
            radio_runtime, "_full_profile_fast_context", return_value=True
        ), patch.object(radio_runtime, "_wait_serial_without_reboot"), patch.object(
            radio_runtime.node_sync, "_raw_command", return_value=response
        ), patch.object(
            radio_runtime, "_resolve_standard_label_from_lora"
        ) as slow_export:
            active = radio_runtime._probe_active_no_reboot(
                "COM13", services, max_wait=8
            )

        self.assertEqual(active, "standard")
        slow_export.assert_not_called()


class AdvancedFlasherTests(unittest.TestCase):
    def test_baud_fallback_order(self):
        self.assertEqual(
            advanced.baud_candidates("460800"),
            ("460800", "230400", "115200"),
        )
        self.assertEqual(advanced.baud_candidates("invalid")[0], "921600")

    def test_preflight_accepts_valid_dynamic_esp_bundle(self):
        identity = status.FirmwareIdentity(
            product="JARNSEN-MESH",
            version="2.0.0-alpha.25",
            build=166,
            hardware="Heltec V4",
        )
        services = SimpleNamespace(
            FlasherError=RuntimeError,
            BOARD_PROFILES={
                "heltec_v4": {"label": "Heltec V4", "artifact_kind": "esp32"}
            },
            validate_firmware_bundle=Mock(
                return_value={"files": ["factory.bin", "update.bin"]}
            ),
            cached_jarnsen_identity=Mock(return_value=identity),
            detect_board_from_text=Mock(return_value="heltec_v4"),
            esp32_update_targets=Mock(),
        )
        bundle = SimpleNamespace(
            board_key="heltec_v4",
            version="2.0.0-alpha.26",
            run_number=167,
            flash_targets=[("app0", 0x10000, 0x300000), ("app1", 0x340000, 0x300000)],
        )
        report = advanced.run_preflight(services, "COM4", "heltec_v4", bundle, "update")
        self.assertTrue(report.ready, report.format())
        self.assertIn("app1@0x340000", report.format())
        self.assertEqual(report.installed_build, 166)
        self.assertEqual(report.target_build, 167)

    def test_preflight_blocks_old_full_profile_firmware_before_flash(self):
        identity = status.FirmwareIdentity(
            product="JARNSEN-MESH",
            version="2.0.0-alpha.34",
            build=312,
            hardware="Heltec V3",
        )
        services = SimpleNamespace(
            FlasherError=RuntimeError,
            BOARD_PROFILES={
                "repeater": {"label": "Heltec V3", "artifact_kind": "esp32"}
            },
            validate_firmware_bundle=Mock(
                return_value={"files": ["factory.bin", "update.bin"]}
            ),
            cached_jarnsen_identity=Mock(return_value=identity),
            detect_board_from_text=Mock(return_value="repeater"),
        )
        bundle = SimpleNamespace(
            board_key="repeater",
            version="2.0.0-alpha.34",
            run_number=315,
            flash_targets=[("app0", 0x10000, 0x300000)],
        )

        report = advanced.run_preflight(
            services, "COM13", "repeater", bundle, "provision"
        )

        self.assertFalse(report.ready)
        self.assertIn("Build 318 oder neuer", report.format())
        self.assertIn("vor Sicherheitsbackup und Flash gestoppt", report.format())

    def test_preflight_accepts_direct_standard_build_for_full_profile(self):
        identity = status.FirmwareIdentity(
            product="JARNSEN-MESH",
            version="2.0.0-alpha.34",
            build=312,
            hardware="Heltec V3",
        )
        services = SimpleNamespace(
            FlasherError=RuntimeError,
            BOARD_PROFILES={
                "repeater": {"label": "Heltec V3", "artifact_kind": "esp32"}
            },
            validate_firmware_bundle=Mock(
                return_value={"files": ["factory.bin", "update.bin"]}
            ),
            cached_jarnsen_identity=Mock(return_value=identity),
            detect_board_from_text=Mock(return_value="repeater"),
        )
        bundle = SimpleNamespace(
            board_key="repeater",
            version="2.0.0-alpha.34",
            run_number=318,
            flash_targets=[("app0", 0x10000, 0x300000)],
        )

        report = advanced.run_preflight(
            services, "COM13", "repeater", bundle, "provision"
        )

        self.assertTrue(report.ready, report.format())
        self.assertIn("direkten STANDARD-Funkprofil-Schreibpfad", report.format())

    def test_preflight_blocks_board_mismatch(self):
        identity = status.FirmwareIdentity(
            product="JARNSEN-MESH",
            version="2.0.0-alpha.26",
            build=167,
            hardware="Heltec V3",
        )
        services = SimpleNamespace(
            FlasherError=RuntimeError,
            BOARD_PROFILES={
                "heltec_v4": {"label": "Heltec V4", "artifact_kind": "esp32"},
                "repeater": {"label": "Heltec V3", "artifact_kind": "esp32"},
            },
            validate_firmware_bundle=Mock(
                return_value={"files": ["factory.bin", "update.bin"]}
            ),
            cached_jarnsen_identity=Mock(return_value=identity),
            detect_board_from_text=Mock(return_value="repeater"),
        )
        bundle = SimpleNamespace(
            board_key="heltec_v4",
            version="2.0.0-alpha.26",
            run_number=167,
            flash_targets=[("app0", 0x10000, 0x300000)],
        )
        report = advanced.run_preflight(services, "COM4", "heltec_v4", bundle, "update")
        self.assertFalse(report.ready)
        self.assertIn("Angeschlossen ist Heltec V3", report.format())

    def test_support_redaction_removes_secrets_and_home(self):
        raw = f"token=abcdef\nPSK: supersecret\nfile={Path.home() / 'logs' / 'run.txt'}"
        safe = advanced.redact_support_text(raw)
        self.assertNotIn("abcdef", safe)
        self.assertNotIn("supersecret", safe)
        self.assertNotIn(str(Path.home()), safe)
        self.assertIn("<HOME>", safe)

    def test_hash_cache_reuses_unchanged_file(self):
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "firmware.bin"
            source.write_bytes(b"firmware")
            cache = advanced.HashCache(root)
            first = cache.digest(source)
            with patch.object(
                advanced.hashlib, "sha256", side_effect=AssertionError("rehash")
            ):
                second = cache.digest(source)
            self.assertEqual(first, second)

    def test_download_continues_partial_zip(self):
        import tempfile

        response = Mock(status_code=206)
        tail = b"d" * 128
        response.iter_content.return_value = [tail]
        client = object.__new__(base_services.GitHubFirmwareClient)
        client.api = "https://api.example.invalid"
        client._request = Mock(return_value=response)
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "artifact.zip"
            destination.with_suffix(".zip.part").write_bytes(b"abc")
            client._download_zip(7, destination)
            self.assertEqual(destination.read_bytes(), b"abc" + tail)
            self.assertEqual(
                client._request.call_args.kwargs["headers"], {"Range": "bytes=3-"}
            )

    def test_full_flash_retries_at_safer_baud(self):
        import tempfile

        class Client:
            def _get_json(self, _url, **_params):
                return {}

        attempts = []

        def flash(_port, _bundle, log=None):
            attempts.append(runtime._jarnsen_flash_baud)
            if len(attempts) == 1:
                raise RuntimeError("serial exception: packet content transfer stopped")
            return None

        with tempfile.TemporaryDirectory() as folder:
            runtime = SimpleNamespace(
                PATHS=SimpleNamespace(root=Path(folder)),
                GitHubFirmwareClient=Client,
                BOARD_PROFILES={"tbeam": {"artifact_kind": "esp32"}},
                _sha256=lambda _path: "",
                _jarnsen_flash_baud="460800",
                flash_bundle=flash,
            )
            with patch.object(advanced.time, "sleep"):
                advanced.install(runtime)
                runtime.flash_bundle(
                    "COM8", SimpleNamespace(board_key="tbeam"), log=Mock()
                )
        self.assertEqual(attempts, ["460800", "230400"])


class IdentityTests(unittest.TestCase):
    def setUp(self):
        importlib.reload(identities)
        self.old_query = status.query_jarnsen_identity
        self.old = status.FirmwareIdentity(
            product="JARNSEN-MESH", version="2.0.0-alpha.25", build=169
        )
        self.new = status.FirmwareIdentity(
            product="JARNSEN-MESH", version="2.0.0-alpha.26", build=170
        )
        self.services = SimpleNamespace(
            scan_devices=Mock(return_value=[]),
            query_jarnsen_identity=Mock(return_value=self.old),
            flash_bundle=Mock(),
        )
        self.query = self.services.query_jarnsen_identity
        self.flash = self.services.flash_bundle
        identities.install(self.services)
        self.services.query_jarnsen_identity("COM1")

    def tearDown(self):
        status.query_jarnsen_identity = self.old_query
        unified._IDENTITY_CACHE.clear()

    def test_cache_reuses_recent_identity(self):
        self.assertIs(self.services.query_jarnsen_identity("COM1"), self.old)
        self.query.assert_called_once()

    def test_expired_cache_requeries_device(self):
        identities._TRUSTED_AT_BY_PORT["COM1"] -= 5
        self.query.return_value = self.new
        self.assertIs(self.services.query_jarnsen_identity("COM1"), self.new)

    def test_flash_invalidates_both_caches_even_on_failure(self):
        for failure in (None, RuntimeError("flash failed")):
            with self.subTest(failure=failure):
                self.services.query_jarnsen_identity("COM1")
                unified._IDENTITY_CACHE["COM1"] = (0, self.old)
                self.flash.side_effect = failure
                if failure:
                    with self.assertRaises(RuntimeError):
                        self.services.flash_bundle("COM1", object())
                else:
                    self.services.flash_bundle("COM1", object())
                self.assertNotIn("COM1", identities._TRUSTED_BY_PORT)
                self.assertNotIn("COM1", unified._IDENTITY_CACHE)

    def test_disconnect_discards_identity(self):
        self.services.scan_devices()
        self.assertIsNone(self.services.cached_jarnsen_identity("COM1"))


if __name__ == "__main__":
    unittest.main()
