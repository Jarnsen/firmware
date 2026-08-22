#!/usr/bin/env python3
"""Download the Heltec Tracker V1.1 persistent diagnostic log over USB CDC."""
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
    raise SystemExit(2)
BEGIN = b"===TRACKER_LOG_BEGIN==="
END = b"===TRACKER_LOG_END==="

def choose_port(explicit):
    if explicit:
        return explicit
    ports = list(list_ports.comports())
    if not ports:
        raise SystemExit("No serial/USB CDC ports found. Connect the Tracker and try again.")
    preferred = []
    for p in ports:
        haystack = f"{p.description} {p.manufacturer or ''} {p.hwid}".lower()
        if any(token in haystack for token in ("espressif", "esp32", "usb jtag", "usb serial", "cdc")):
            preferred.append(p)
    candidates = preferred or ports
    if len(candidates) == 1:
        print(f"Using {candidates[0].device}: {candidates[0].description}")
        return candidates[0].device
    print("Available serial ports:")
    for idx, p in enumerate(candidates, 1):
        print(f"  {idx}: {p.device}  {p.description}")
    while True:
        try:
            choice = int(input("Select Tracker port number: ").strip())
            if 1 <= choice <= len(candidates):
                return candidates[choice - 1].device
        except ValueError:
            pass
        print("Invalid selection.")

def main():
    parser = argparse.ArgumentParser(description="Download Tracker diagnostic log over USB CDC")
    parser.add_argument("--port")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--output")
    args = parser.parse_args()
    port = choose_port(args.port)
    output = pathlib.Path(args.output) if args.output else pathlib.Path(f"tracker-log-{dt.datetime.now().strftime('%Y-%m-%d_%H%M%S')}.txt")
    print(f"Opening {port} ...")
    print("Now select: Service -> Diagnostic Log -> Export via USB")
    deadline = time.monotonic() + args.timeout
    started = False
    captured = bytearray()
    line_buffer = bytearray()
    with serial.Serial(port, 115200, timeout=0.25) as ser:
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
        print(f"Transfer timed out. Partial file: {partial.resolve()}")
        return 3
    print("No Tracker log marker received. Trigger 'Export via USB' on the device menu.")
    return 4

if __name__ == "__main__":
    raise SystemExit(main())
