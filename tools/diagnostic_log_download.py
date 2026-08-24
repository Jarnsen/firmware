#!/usr/bin/env python3
"""Download persistent diagnostic logs from Jarnsen Meshtastic builds over USB CDC.

Works with:
- Heltec Tracker V1.1 vehicle tracker
- Heltec WiFi LoRa 32 V3 repeater

The downloader accepts the shared protocol and the older Tracker/V3 marker pairs,
so it can also retrieve logs from previously flashed builds.
"""

from __future__ import annotations

import argparse
import datetime as dt
import pathlib
import time

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    print("Missing dependency: pyserial")
    print("Install it with: python -m pip install pyserial")
    raise SystemExit(2) from None

PROTOCOLS = (
    (b"===JARNSEN_DIAG_LOG_BEGIN===", b"===JARNSEN_DIAG_LOG_END===", "shared"),
    (b"===TRACKER_LOG_BEGIN===", b"===TRACKER_LOG_END===", "tracker-legacy"),
    (b"===V3_LOG_BEGIN===", b"===V3_LOG_END===", "v3-legacy"),
)


def available_ports():
    return list(list_ports.comports())


def choose_port(explicit: str | None) -> str:
    if explicit:
        return explicit

    ports = available_ports()
    if not ports:
        raise SystemExit(
            "No serial/USB CDC ports found. Connect the device and try again."
        )

    preferred = []
    for p in ports:
        haystack = f"{p.description} {p.manufacturer or ''} {p.hwid}".lower()
        if any(
            token in haystack
            for token in ("espressif", "esp32", "usb jtag", "usb serial", "cdc")
        ):
            preferred.append(p)

    candidates = preferred or ports
    if len(candidates) == 1:
        p = candidates[0]
        print(f"Using {p.device}: {p.description}")
        return p.device

    print("Available serial ports:")
    for idx, p in enumerate(candidates, 1):
        print(f"  {idx}: {p.device}  {p.description}")
    while True:
        raw = input("Select device port number: ").strip()
        try:
            choice = int(raw)
            if 1 <= choice <= len(candidates):
                return candidates[choice - 1].device
        except ValueError:
            pass
        print("Invalid selection.")


def strip_leading_newline(data: bytes) -> bytes:
    if data.startswith(b"\r\n"):
        return data[2:]
    if data.startswith(b"\n"):
        return data[1:]
    return data


def find_begin(buffer: bytearray):
    best = None
    for begin, end, name in PROTOCOLS:
        pos = buffer.find(begin)
        if pos >= 0 and (best is None or pos < best[0]):
            best = (pos, begin, end, name)
    return best


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download Tracker/V3 diagnostic log over USB CDC"
    )
    parser.add_argument("--port", help="COM port / tty device, otherwise auto-detected")
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="seconds to wait for Export via USB (default: 300)",
    )
    parser.add_argument(
        "--output", help="output filename; default diagnostic-log-YYYY-MM-DD_HHMMSS.txt"
    )
    args = parser.parse_args()

    port = choose_port(args.port)
    output = (
        pathlib.Path(args.output)
        if args.output
        else pathlib.Path(
            f"diagnostic-log-{dt.datetime.now().strftime('%Y-%m-%d_%H%M%S')}.txt"
        )
    )

    print(f"Opening {port} ...")
    print("READY. On the device select:")
    print("  Service -> Diagnostic Log -> Export via USB")
    print("Keep this window open until device and PC report completion.")
    print(f"Waiting up to {args.timeout} seconds ...")

    deadline = time.monotonic() + args.timeout
    last_wait_message = time.monotonic()
    started = False
    captured = bytearray()
    scan = bytearray()
    end_marker = None
    protocol_name = None

    try:
        with serial.Serial(port, 115200, timeout=0.20) as ser:
            # Do not clear the input buffer. The device may already be emitting
            # the begin marker while Windows/pyserial finishes opening the CDC port.
            while time.monotonic() < deadline:
                chunk = ser.read(4096)
                if not chunk:
                    now = time.monotonic()
                    if not started and now - last_wait_message >= 5.0:
                        remaining = max(0, int(deadline - now))
                        print(
                            f"Waiting for diagnostic export ... ({remaining}s remaining)"
                        )
                        last_wait_message = now
                    continue

                scan.extend(chunk)

                if not started:
                    found = find_begin(scan)
                    if found is None:
                        keep = max(max(len(p[0]) for p in PROTOCOLS) - 1, 96)
                        if len(scan) > keep:
                            del scan[:-keep]
                        continue

                    pos, begin_marker, end_marker, protocol_name = found
                    started = True
                    print(f"Log transfer started ({protocol_name}) ...")
                    after = bytes(scan[pos + len(begin_marker) :])
                    scan.clear()
                    scan.extend(strip_leading_newline(after))

                end_pos = scan.find(end_marker)
                if end_pos >= 0:
                    payload = bytes(scan[:end_pos])
                    if payload.endswith(b"\r\n"):
                        payload = payload[:-2]
                    elif payload.endswith(b"\n"):
                        payload = payload[:-1]
                    captured.extend(payload)
                    output.write_bytes(bytes(captured))
                    print(f"DONE: {output.resolve()} ({len(captured)} bytes)")
                    return 0

                keep = len(end_marker) - 1
                if len(scan) > keep:
                    take = len(scan) - keep
                    captured.extend(scan[:take])
                    del scan[:take]

    except serial.SerialException as exc:
        partial = output.with_suffix(output.suffix + ".partial")
        if captured:
            partial.write_bytes(bytes(captured))
            print(f"USB/serial connection failed: {exc}")
            print(f"Partial transfer saved: {partial.resolve()}")
        else:
            print(f"USB/serial connection failed: {exc}")
        return 5

    if started:
        captured.extend(scan)
        partial = output.with_suffix(output.suffix + ".partial")
        partial.write_bytes(bytes(captured))
        print(
            f"Transfer timed out after it started. Partial file saved: {partial.resolve()}"
        )
        return 3

    print("No diagnostic log start marker received.")
    print("Check USB, then select Service -> Diagnostic Log -> Export via USB again.")
    return 4


if __name__ == "__main__":
    raise SystemExit(main())
