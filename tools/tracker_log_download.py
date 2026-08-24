#!/usr/bin/env python3
"""Download the Heltec Tracker V1.1 persistent diagnostic log over USB CDC.

Recommended sequence:
  1. Connect the Tracker by USB-C.
  2. Start this program (or tracker_log_download.bat on Windows).
  3. On the Tracker open Service -> Diagnostic Log -> Export via USB.
  4. Keep the window open until both Tracker and PC report completion.
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

BEGIN = b"===TRACKER_LOG_BEGIN==="
END = b"===TRACKER_LOG_END==="


def available_ports():
    return list(list_ports.comports())


def choose_port(explicit: str | None) -> str:
    if explicit:
        return explicit

    ports = available_ports()
    if not ports:
        raise SystemExit(
            "No serial/USB CDC ports found. Connect the Tracker and try again."
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
        raw = input("Select Tracker port number: ").strip()
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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download Tracker diagnostic log over USB CDC"
    )
    parser.add_argument("--port", help="COM port / tty device, otherwise auto-detected")
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="seconds to wait for Export via USB (default: 300)",
    )
    parser.add_argument(
        "--output", help="output filename; default tracker-log-YYYY-MM-DD_HHMMSS.txt"
    )
    args = parser.parse_args()

    port = choose_port(args.port)
    output = (
        pathlib.Path(args.output)
        if args.output
        else pathlib.Path(
            f"tracker-log-{dt.datetime.now().strftime('%Y-%m-%d_%H%M%S')}.txt"
        )
    )

    print(f"Opening {port} ...")
    print("READY. Now select on the Tracker:")
    print("  Service -> Diagnostic Log -> Export via USB")
    print("The Tracker should show 'Uebertrage Log...' and a percentage.")
    print(f"Waiting up to {args.timeout} seconds ...")

    deadline = time.monotonic() + args.timeout
    last_wait_message = time.monotonic()
    started = False
    captured = bytearray()
    scan = bytearray()

    try:
        with serial.Serial(port, 115200, timeout=0.20) as ser:
            # IMPORTANT: do NOT call reset_input_buffer() here. If the user
            # selected Export just before this program opened the port, the
            # Tracker may already be preparing the begin marker. Clearing the
            # input buffer created a race that could discard that marker and
            # leave the old downloader waiting forever.
            while time.monotonic() < deadline:
                chunk = ser.read(4096)
                if not chunk:
                    now = time.monotonic()
                    if not started and now - last_wait_message >= 5.0:
                        remaining = max(0, int(deadline - now))
                        print(
                            f"Waiting for Tracker export ... ({remaining}s remaining)"
                        )
                        last_wait_message = now
                    continue

                scan.extend(chunk)

                if not started:
                    pos = scan.find(BEGIN)
                    if pos < 0:
                        # Retain only enough tail bytes to detect a marker split
                        # across two serial reads. Normal Meshtastic serial logs
                        # before the marker are intentionally ignored.
                        keep = max(len(BEGIN) - 1, 64)
                        if len(scan) > keep:
                            del scan[:-keep]
                        continue

                    started = True
                    print("Log transfer started ...")
                    after = bytes(scan[pos + len(BEGIN) :])
                    scan.clear()
                    scan.extend(strip_leading_newline(after))

                end_pos = scan.find(END)
                if end_pos >= 0:
                    payload = bytes(scan[:end_pos])
                    # The device intentionally starts END on a fresh line; do
                    # not leave that protocol separator in the saved log.
                    if payload.endswith(b"\r\n"):
                        payload = payload[:-2]
                    elif payload.endswith(b"\n"):
                        payload = payload[:-1]
                    captured.extend(payload)
                    output.write_bytes(bytes(captured))
                    print(f"DONE: {output.resolve()} ({len(captured)} bytes)")
                    return 0

                # Keep a tail large enough to detect END split across reads.
                keep = len(END) - 1
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

    print("No Tracker log start marker received.")
    print(
        "Check that the Tracker shows 'PC erkannt' / 'Uebertrage Log...' after selecting Export via USB."
    )
    return 4


if __name__ == "__main__":
    raise SystemExit(main())
