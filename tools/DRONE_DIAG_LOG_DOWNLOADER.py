#!/usr/bin/env python3
"""USB flight-log downloader for the Jarnsen Tracker V1.1 Drone Repeater."""

from __future__ import annotations

import argparse
import datetime as dt
import pathlib
import subprocess
import sys
import time


def serial_modules():
    try:
        import serial  # type: ignore
        from serial.tools import list_ports  # type: ignore
        return serial, list_ports
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--user", "pyserial"])
        import serial  # type: ignore
        from serial.tools import list_ports  # type: ignore
        return serial, list_ports


serial, list_ports = serial_modules()
BEGIN = b"===JARNSEN_DIAG_LOG_BEGIN==="
END = b"===JARNSEN_DIAG_LOG_END==="
DEVICE = b"# device=HELTEC_TRACKER_V1.1"
PROFILE = b"# profile=DRONE_REPEATER"


def choose_port(explicit: str | None) -> str:
    if explicit:
        return explicit
    ports = list(list_ports.comports())
    if not ports:
        raise SystemExit("Kein USB-/COM-Port gefunden.")
    preferred = [p for p in ports if any(x in f"{p.description} {p.manufacturer or ''} {p.hwid}".lower()
                                          for x in ("espressif", "esp32", "usb jtag", "usb serial", "cdc"))]
    candidates = preferred or ports
    if len(candidates) == 1:
        print(f"Port: {candidates[0].device}  {candidates[0].description}")
        return candidates[0].device
    for index, port in enumerate(candidates, 1):
        print(f"  {index}: {port.device}  {port.description}")
    while True:
        try:
            selected = int(input("Drone-Port waehlen: ").strip())
            if 1 <= selected <= len(candidates):
                return candidates[selected - 1].device
        except ValueError:
            pass


def output_path(explicit: str | None) -> pathlib.Path:
    if explicit:
        path = pathlib.Path(explicit).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    base = pathlib.Path.home() / "Downloads"
    if not base.exists():
        base = pathlib.Path.home()
    folder = base / "Meshtastic-Logs"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"DRONE_Flight_Log_{dt.datetime.now():%Y-%m-%d_%H%M%S}.txt"


def main() -> int:
    parser = argparse.ArgumentParser(description="Jarnsen Drone Repeater Flight Log Downloader")
    parser.add_argument("--port")
    parser.add_argument("--output")
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()

    port = choose_port(args.port)
    destination = output_path(args.output)
    ser = serial.Serial()
    ser.port = port
    ser.baudrate = 115200
    ser.timeout = 0.1
    ser.write_timeout = 1.0
    ser.dtr = False
    ser.rts = False
    print(f"Oeffne {port} ...")
    ser.open()

    try:
        settle = time.monotonic() + 1.2
        while time.monotonic() < settle:
            ser.read(4096)
        print("Bereit. GPIO0 am Drone-Repeater einmal kurz druecken.")
        print("Dadurch wird Service geoeffnet und bei aktiver USB-Datenverbindung der Flight-Log exportiert.")

        buffer = bytearray()
        capture = bytearray()
        started = False
        deadline = time.monotonic() + args.timeout
        last_message = 0.0
        while time.monotonic() < deadline:
            chunk = ser.read(4096)
            if chunk:
                buffer.extend(chunk)

            if not started:
                pos = buffer.find(BEGIN)
                if pos >= 0:
                    started = True
                    rest = bytes(buffer[pos + len(BEGIN):])
                    buffer.clear()
                    if rest.startswith(b"\r\n"):
                        rest = rest[2:]
                    elif rest.startswith(b"\n"):
                        rest = rest[1:]
                    buffer.extend(rest)
                    print("Flight-Log Transfer erkannt.")
                else:
                    if len(buffer) > 512:
                        del buffer[:-512]
                    if time.monotonic() - last_message > 5:
                        print("Warte auf GPIO0-Service/Export ...")
                        last_message = time.monotonic()
                    continue

            end = buffer.find(END)
            if end >= 0:
                capture.extend(buffer[:end])
                if DEVICE not in capture or PROFILE not in capture:
                    print("FEHLER: Export ist kein Drone-Repeater Flight-Log.")
                    return 6
                destination.write_bytes(bytes(capture).rstrip(b"\r\n") + b"\r\n")
                print(f"DONE: {destination} ({destination.stat().st_size} Bytes)")
                return 0

            keep = len(END) - 1
            if len(buffer) > keep:
                take = len(buffer) - keep
                capture.extend(buffer[:take])
                del buffer[:take]

        print("TIMEOUT: Kein vollstaendiger Flight-Log empfangen.")
        return 3
    finally:
        ser.close()


if __name__ == "__main__":
    raise SystemExit(main())
