#!/usr/bin/env python3
"""Dedicated USB diagnostic-log downloader for the Jarnsen Heltec V3 repeater build."""

from __future__ import annotations

import argparse
import datetime as dt
import os
import pathlib
import subprocess
import sys
import time


def load_pyserial():
    try:
        import serial  # type: ignore
        from serial.tools import list_ports  # type: ignore
        return serial, list_ports
    except ImportError:
        print("pyserial ist nicht installiert. Installation wird einmalig versucht ...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "--user", "pyserial"])
        except Exception as exc:
            raise SystemExit(f"pyserial konnte nicht installiert werden: {exc}")
        import serial  # type: ignore
        from serial.tools import list_ports  # type: ignore
        return serial, list_ports


serial, list_ports = load_pyserial()

PROTOCOLS = (
    (b"===JARNSEN_DIAG_LOG_BEGIN===", b"===JARNSEN_DIAG_LOG_END===", "V3 shared"),
    (b"===V3_LOG_BEGIN===", b"===V3_LOG_END===", "V3 legacy"),
)
EXPECTED_DEVICE = b"# device=HELTEC_V3_REPEATER"


def default_output_dir() -> pathlib.Path:
    downloads = pathlib.Path.home() / "Downloads"
    base = downloads if downloads.exists() else pathlib.Path.home()
    out = base / "Meshtastic-Logs"
    out.mkdir(parents=True, exist_ok=True)
    return out


def choose_port(explicit: str | None) -> str:
    if explicit:
        return explicit
    ports = list(list_ports.comports())
    if not ports:
        raise SystemExit("Kein COM-/USB-Serial-Port gefunden. V3 per USB anschliessen.")

    preferred = []
    for p in ports:
        text = f"{p.description} {p.manufacturer or ''} {p.hwid}".lower()
        if any(x in text for x in ("espressif", "esp32", "usb jtag", "usb serial", "cdc")):
            preferred.append(p)
    candidates = preferred or ports
    if len(candidates) == 1:
        p = candidates[0]
        print(f"Gefundener Port: {p.device}  {p.description}")
        return p.device

    print("Verfuegbare Ports:")
    for i, p in enumerate(candidates, 1):
        print(f"  {i}: {p.device}  {p.description}")
    while True:
        try:
            i = int(input("V3-Port waehlen: ").strip())
            if 1 <= i <= len(candidates):
                return candidates[i - 1].device
        except ValueError:
            pass
        print("Ungueltige Auswahl.")


def find_begin(data: bytearray):
    best = None
    for begin, end, name in PROTOCOLS:
        pos = data.find(begin)
        if pos >= 0 and (best is None or pos < best[0]):
            best = (pos, begin, end, name)
    return best


def strip_one_newline(data: bytes) -> bytes:
    if data.startswith(b"\r\n"):
        return data[2:]
    if data.startswith(b"\n"):
        return data[1:]
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description="Heltec V3 Jarnsen Diagnostic Log Downloader")
    parser.add_argument("--port", help="COM-Port, z.B. COM7")
    parser.add_argument("--timeout", type=int, default=240, help="Wartezeit in Sekunden (Standard 240)")
    parser.add_argument("--output", help="optionaler kompletter Ausgabepfad")
    args = parser.parse_args()

    out_dir = default_output_dir()
    print("====================================================")
    print(" HELTEC V3 - JARNSEN DIAGNOSTIC LOG DOWNLOADER")
    print("====================================================")
    print("WICHTIG: Meshtastic Serial Console/Monitor vorher schliessen.")
    print(f"Log-Zielordner: {out_dir.resolve()}")

    port = choose_port(args.port)

    # Open the selected port immediately. Firmware input handling must remain
    # independent from the native USB CDC session, so the operator can navigate
    # the complete local menu while this downloader waits for the export marker.
    print("")
    print("COM-Port ausgewaehlt. Der Downloader wird jetzt geoeffnet.")
    print("Danach am V3:")
    print("  Service -> Diagnostic Log -> Export via USB")
    print("  dann 'HOLD: EXPORT NOW' waehlen und LANG bestaetigen")
    print("Der Download startet anschliessend automatisch.")

    try:
        ser = serial.Serial()
        ser.port = port
        ser.baudrate = 115200
        ser.timeout = 0.10
        ser.write_timeout = 1.0
        ser.rtscts = False
        ser.dsrdtr = False
        # DTR is asserted only for the short transfer window. On native ESP32-S3
        # USB CDC, firmware Serial::operator bool() can depend on host-open/DTR.
        ser.dtr = True
        ser.rts = False
        print(f"Oeffne {port} und warte auf den V3-Export ...")
        ser.open()
    except serial.SerialException as exc:
        print(f"Port konnte nicht geoeffnet werden: {exc}")
        print("Falls 'Access denied': Meshtastic-Konsole und andere Serial-Programme schliessen.")
        return 2

    scan = bytearray()
    captured = bytearray()
    started = False
    end_marker = b""
    protocol_name = ""
    received_total = 0

    try:
        # Native ESP32-S3 USB CDC needs a short host-open settle time. Do not
        # clear the input buffer; the begin marker may arrive immediately.
        settle_until = time.monotonic() + 1.5
        while time.monotonic() < settle_until:
            chunk = ser.read(4096)
            if chunk:
                received_total += len(chunk)
                scan.extend(chunk)

        print("USB-Serial ist verbunden. Der V3 bleibt bedienbar; warte auf den Export.")
        print("Nach DONE wird der COM-Port sofort wieder geschlossen.")

        deadline = time.monotonic() + args.timeout
        last_wait = 0.0
        while time.monotonic() < deadline:
            chunk = ser.read(4096)
            if chunk:
                received_total += len(chunk)
                scan.extend(chunk)

            if not started:
                found = find_begin(scan)
                if found is not None:
                    pos, begin_marker, end_marker, protocol_name = found
                    started = True
                    print(f"Transfer erkannt ({protocol_name}).")
                    after = bytes(scan[pos + len(begin_marker):])
                    scan.clear()
                    scan.extend(strip_one_newline(after))
                else:
                    if len(scan) > 512:
                        del scan[:-512]
                    now = time.monotonic()
                    if now - last_wait >= 5.0:
                        print(f"Warte auf V3-Export ... {max(0, int(deadline - now))}s")
                        last_wait = now
                    continue

            end_pos = scan.find(end_marker)
            if end_pos >= 0:
                payload = bytes(scan[:end_pos])
                if payload.endswith(b"\r\n"):
                    payload = payload[:-2]
                elif payload.endswith(b"\n"):
                    payload = payload[:-1]
                captured.extend(payload)

                if EXPECTED_DEVICE not in captured and protocol_name == "V3 shared":
                    print("FEHLER: Exportmarker empfangen, aber Header ist nicht HELTEC_V3_REPEATER.")
                    return 6

                if args.output:
                    output = pathlib.Path(args.output).expanduser().resolve()
                    output.parent.mkdir(parents=True, exist_ok=True)
                else:
                    output = out_dir / ("V3_Diagnostic_Log_" + dt.datetime.now().strftime("%Y-%m-%d_%H%M%S") + ".txt")
                output.write_bytes(bytes(captured))
                print(f"DONE: {output.resolve()} ({len(captured)} Bytes)")
                return 0

            keep = max(1, len(end_marker) - 1)
            if len(scan) > keep:
                take = len(scan) - keep
                captured.extend(scan[:take])
                del scan[:take]

        if started:
            partial = out_dir / ("V3_Diagnostic_Log_PARTIAL_" + dt.datetime.now().strftime("%Y-%m-%d_%H%M%S") + ".txt")
            captured.extend(scan)
            partial.write_bytes(bytes(captured))
            print(f"TIMEOUT nach Transferstart. Teil-Datei: {partial.resolve()}")
            return 3

        if received_total:
            print(f"Kein Exportmarker gesehen, aber {received_total} Serial-Bytes empfangen.")
            print("USB lebt. Export am V3 ggf. erneut anfordern und Downloader neu starten.")
        else:
            print("Gar keine Serial-Daten empfangen. Port pruefen bzw. anderen COM-Port waehlen.")
        return 4
    except serial.SerialException as exc:
        print(f"USB/Serial-Verbindung abgebrochen: {exc}")
        return 5
    finally:
        try:
            ser.close()
            print("COM-Port geschlossen.")
        except Exception:
            pass


if __name__ == "__main__":
    rc = main()
    if os.name == "nt":
        try:
            input("Enter zum Schliessen ...")
        except EOFError:
            pass
    raise SystemExit(rc)
