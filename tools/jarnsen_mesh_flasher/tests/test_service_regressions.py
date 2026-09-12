from __future__ import annotations

import importlib
import io
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import advanced_flasher as advanced
import firmware_identity_sha_match as identities
import firmware_status_ui as status
import flash_runtime
import radio_profile_legacy_fallback as legacy
import radio_profile_node_sync as radio
import services as base_services
import unified_service_v2 as unified


class FakeSerial:
    def __init__(self, chunks):
        self.chunks = iter(chunks)
        self.reads = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def reset_input_buffer(self):
        pass

    def write(self, data):
        return len(data)

    def flush(self):
        pass

    def read(self, size):
        self.reads += 1
        return next(self.chunks)


class ServiceTests(unittest.TestCase):
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
