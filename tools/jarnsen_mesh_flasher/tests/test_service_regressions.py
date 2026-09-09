from __future__ import annotations

import importlib
import io
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from contextlib import contextmanager

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import firmware_identity_sha_match as identities
import firmware_status_ui as status
import flash_runtime
import radio_profile_legacy_fallback as legacy
import radio_profile_node_sync as radio
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
                    port = FakeSerial([b"===JARNSEN_RADIO=== active=jarn", b"sen1 slots=3", separator])
                    with patch.object(radio.serial, "Serial", return_value=port), patch.object(radio.time, "sleep"):
                        result = reader("COM1", "JARNSEN_TOOL_RADIO_INFO", expected=radio.RADIO_INFO_MARKER)
                    self.assertEqual(result, "===JARNSEN_RADIO=== active=jarnsen1 slots=3")
                    self.assertEqual(port.reads, 3)

    def test_fragmented_identity_reply(self):
        for reader in (status.query_jarnsen_identity, legacy._stable_identity_query):
            with self.subTest(reader=reader.__name__):
                port = FakeSerial([
                    b"===JARNSEN_INFO=== product=JARNSEN-MESH version=2.0.",
                    b"0-alpha.26 build=170 hardware=Heltec V3 sha=abcdef1\r\n",
                ])
                with patch.object(status.serial, "Serial", return_value=port), patch.object(status.time, "sleep"):
                    result = reader("COM1")
                self.assertEqual(result.version, "2.0.0-alpha.26")
                self.assertEqual(result.build, 170)
                self.assertEqual(result.hardware, "Heltec V3")
                self.assertEqual(result.sha, "abcdef1")

    def test_error_reply_is_not_success(self):
        port = FakeSerial([b"===JARNSEN_RADIO_ERROR=== action=set\r\n"])
        with patch.object(radio.serial, "Serial", return_value=port):
            with self.assertRaises(RuntimeError):
                legacy._stable_raw_command("COM1", "JARNSEN_TOOL_RADIO_SET jarnsen1", expected=radio.RADIO_OK_MARKER)

    def test_multiple_slots_use_one_process(self):
        targets = [("app0", 0x20000, 0x100000), ("app1", 0x120000, 0x100000)]
        with patch.object(flash_runtime, "_stream_esptool") as stream:
            unified._write_update_slots(None, "COM1", ["write-flash"], Path("update.bin"), targets, None)
        stream.assert_called_once()
        self.assertEqual(stream.call_args.args[2], ["write-flash", "0x20000", "update.bin", "0x120000", "update.bin"])
        self.assertEqual(stream.call_args.kwargs["progress_parts"], 2)

    def test_empty_slots_rejected(self):
        with patch.object(flash_runtime, "_stream_esptool") as stream:
            with self.assertRaises(ValueError):
                unified._write_update_slots(None, "COM1", ["write-flash"], Path("update.bin"), [], None)
            stream.assert_not_called()

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
            helper_command=lambda: ["helper"], _startupinfo=lambda: None,
            invalidate_jarnsen_identity=Mock(),
            jarnsen_serial_guard=guard,
            _jarnsen_flash_progress_callback=lambda value, *args: progress.append(value),
        )
        process = Mock(stdout=io.StringIO(
            "Writing at 0x20000 (100 %)\nHash of data verified.\n"
            "Writing at 0x120000 (50 %)\nWriting at 0x120000 (100 %)\nHash of data verified.\n"
        ))
        process.poll.return_value = 0
        process.wait.return_value = 0
        def popen(*args, **kwargs):
            self.assertEqual(locked, ["COM1"])
            return process

        with patch.object(flash_runtime.subprocess, "Popen", side_effect=popen):
            flash_runtime._stream_esptool(services, "COM1", ["write-flash"], timeout=5,
                                         stage="test", phase_start=0, phase_end=1, log=None, progress_parts=2)
        self.assertEqual(services.invalidate_jarnsen_identity.call_count, 2)
        self.assertEqual(locked, [])
        self.assertEqual(progress, [0, 0.5, 0.75, 1.0, 1])


class IdentityTests(unittest.TestCase):
    def setUp(self):
        importlib.reload(identities)
        self.old_query = status.query_jarnsen_identity
        self.old = status.FirmwareIdentity(product="JARNSEN-MESH", version="2.0.0-alpha.25", build=169)
        self.new = status.FirmwareIdentity(product="JARNSEN-MESH", version="2.0.0-alpha.26", build=170)
        self.services = SimpleNamespace(scan_devices=Mock(return_value=[]),
                                        query_jarnsen_identity=Mock(return_value=self.old), flash_bundle=Mock())
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
