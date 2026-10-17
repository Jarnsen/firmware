from __future__ import annotations

import sys
import zlib
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import usb_log_download as usb
import v3_usb_log_stability as v3


def frame(
    payload=b"UPTIME+1s | HEALTH | ok=1\n",
    *,
    version=3,
    delivered=None,
    crc=None,
    complete=1,
):
    header = (
        usb.BEGIN
        + f"\r\n# long_name=Test\r\n# log_format={version}\r\n# bytes={len(payload)}\r\n".encode()
    )
    footer = f"\r\n# payload_sent={len(payload)}\r\n".encode()
    if version >= 3:
        footer += f"# crc32={(zlib.crc32(payload) if crc is None else crc):08x}\r\n# transfer_complete={complete}\r\n".encode()
    return (
        header
        + (payload if delivered is None else delivered)
        + footer
        + usb.END
        + b"\r\n"
    )


@pytest.mark.parametrize("version", [2, 3])
def test_valid_export_and_empty_payload(version):
    assert usb._validate_export(frame(version=version)) == 26
    assert usb._validate_export(frame(b"", version=version)) == 0


def test_missing_64_bytes_cannot_be_hidden_by_footer_length():
    payload = b"a" * 200 + b"\n"
    damaged = frame(payload, delivered=payload[64:])
    with pytest.raises(
        usb.UsbLogIntegrityError, match="erwartet 201 Bytes, empfangen 137 Bytes"
    ):
        usb._validate_export(damaged)


@pytest.mark.parametrize(
    "damaged",
    [
        frame(crc=0),
        frame(complete=0),
        frame().replace(b"# crc32=", b"# broken="),
        frame().replace(b"# transfer_complete=1\r\n", b""),
    ],
)
def test_crc_and_completion_are_mandatory_in_format_three(damaged):
    with pytest.raises(usb.UsbLogIntegrityError):
        usb._validate_export(damaged)


def test_end_marker_inside_payload_is_not_transfer_end():
    payload = b"UPTIME+2s | WARN | marker=" + usb.END + b"\n"
    data = frame(payload)
    assert usb._export_end_index(data) == data.rfind(usb.END)
    assert usb._validate_export(data) == len(payload)
    assert usb._validate_export(data[:-1]) == len(payload)


@pytest.fixture
def receiver(monkeypatch):
    sessions = []
    clock = [0.0]

    def monotonic():
        clock[0] += 0.01
        return clock[0]

    monkeypatch.setattr(usb.time, "monotonic", monotonic)
    monkeypatch.setattr(usb.time, "sleep", lambda _seconds: None)

    class Serial:
        frames = []

        def __init__(self, **kwargs):
            self.data = self.frames.pop(0)
            self.ready = False
            self.offset = 0
            self.commands = []
            self.buffer_size = None
            sessions.append(self)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def set_buffer_size(self, **kwargs):
            self.buffer_size = kwargs

        def reset_input_buffer(self):
            pass

        def write(self, command):
            self.commands.append(command)
            self.ready = True
            return len(command)

        def flush(self):
            pass

        def read(self, _size):
            if not self.ready:
                return b""
            chunk = self.data[self.offset : self.offset + 37]
            self.offset += len(chunk)
            return chunk

    monkeypatch.setattr(usb.serial, "Serial", Serial)
    return Serial.frames, sessions


@pytest.mark.parametrize(
    "download", [usb.download_tracker_usb_log, v3._download_v3_usb_log]
)
def test_real_receiver_retries_once_then_saves_only_verified_success(
    receiver, tmp_path, download
):
    frames, sessions = receiver
    payload = b"UPTIME+3s | HEALTH | " + b"a" * 128 + b"\n"
    frames.extend([frame(payload, delivered=payload[64:]), frame(payload)])
    progress = []
    result = download(
        "COM9", tmp_path, progress=lambda value, _detail: progress.append(value)
    )
    assert result.read_bytes() == frame(payload).rstrip(
        b"\r\n"
    ) or result.read_bytes() == frame(payload)
    assert usb._validate_export(result.read_bytes()) == len(payload)
    assert len(sessions) == 2 and progress.count(1.0) == 1
    assert all(session.commands == [usb.COMMAND] for session in sessions)
    assert all(session.buffer_size["rx_size"] == 65536 for session in sessions)
    assert len(list(tmp_path.glob("*-incomplete-*.log"))) == 1


@pytest.mark.parametrize(
    "download", [usb.download_tracker_usb_log, v3._download_v3_usb_log]
)
def test_real_receiver_never_reports_success_for_two_bad_transfers(
    receiver, tmp_path, download
):
    frames, sessions = receiver
    frames.extend([frame(crc=0), frame(crc=0)])
    progress = []
    with pytest.raises(usb.UsbLogIntegrityError, match="CRC"):
        download(
            "COM9", tmp_path, progress=lambda value, _detail: progress.append(value)
        )
    assert len(sessions) == 2 and 1.0 not in progress
    assert len(list(tmp_path.glob("*-incomplete-*.log"))) == 2
