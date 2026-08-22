#!/usr/bin/env python3
"""Download the Heltec Tracker V1.1 persistent diagnostic log over USB CDC.

Usage:
  1. Connect the Tracker by USB-C.
  2. Run this script (or tracker_log_download.bat on Windows).
  3. On the Tracker open Service -> Diagnostic Log -> Export via USB.
  4. The log is saved beside this script / current working directory.
"""

from __future__ import annotations

import argparse
import datetime as dt
import pathlib
import sys
import time

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    print("Missing dependency: pyserial")
    print("Install it with: python -m pip install pyserial")
    raise SystemExit(2)

BEGIN = b"===TRACKER_LOG_BEGIN==="
END = b"===TRACKER_LOG_END==="


def available_ports():
    return list(list_ports.comports())


def choose_port(explicit: str | None) -> str:
    if explicit:
        return explicit

    ports = available_ports()
    if not ports:
        raise SystemExit("No serial/USB CDC ports found. Connect the Tracker and try again.")

    # ESP32-S3 native USB devices commonly expose Espressif/USB/JTAG/CDC text.
    preferred = []
    for p in ports:
        haystack = f"{p.description} {p.manufacturer or ''} {p.hwid}".lower()
        if any(token in haystack for token in ("espressif", "esp32", "usb jtag", "usb serial", "cdc")):
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Download Tracker diagnostic log over USB CDC")
    parser.add_argument("--port", help="COM port / tty device, otherwise auto-detected")
    parser.add_argument("--timeout", type=int, default=300, help="seconds to wait for Export via USB (default: 300)")
    parser.add_argument("--output", help="output filename; default tracker-log-YYYY-MM-DD_HHMMSS.txt")
    args = parser.parse_args()

    port = choose_port(args.port)
    output = pathlib.Path(args.output) if args.output else pathlib.Path(
        f"tracker-log-{dt.datetime.now().strftime('%Y-%m-%d_%H%M%S')}.txt"
    )

    print(f"Opening {port} ...")
    print("Now select on the Tracker: Service -> Diagnostic Log -> Export via USB")
    print(f"Waiting up to {args.timeout} seconds for log marker ...")

    deadline = time.monotonic() + args.timeout
    started = False
    captured = bytearray()
    line_buffer = bytearray()

    with serial.Serial(port, 115200, timeout=0.25) as ser:
        # Native USB CDC does not depend on baud, but 115200 is harmless and
        # also supports USB/UART adapters if one is used later.
        ser.reset_input_buffer()
        while time.monotonic() < deadline:
            chunk = ser.read(2048)
            if not chunk:
                continue
            line_buffer.extend(chunk)

            while b"\n" in line_buffer:
                raw_line, _, remainder = line_buffer.partition(b"\n")
                line_buffer = bytearray(remainder)
                line = raw_line.rstrip(b"\r")

                if not started:
                    if line == BEGIN:
                        started = True
                        print("Log transfer started ...")
                    continue

                if line == END:
                    output.write_bytes(bytes(captured))
                    print(f"Done: {output.resolve()} ({len(captured)} bytes)")
                    return 0

                captured.extend(raw_line)
                captured.extend(b"\n")

    if started:
        partial = output.with_suffix(output.suffix + ".partial")
        partial.write_bytes(bytes(captured))
        print(f"Transfer timed out after it started. Partial file saved: {partial.resolve()}")
        return 3

    print("No Tracker log marker received.")
    print("Keep this program running, then trigger 'Export via USB' on the device menu.")
    return 4


if __name__ == "__main__":
    raise SystemExit(main())
