from pathlib import Path

DOWNLOADER = Path("tools/TRACKER_V11_DIAG_LOG_DOWNLOADER.py")
text = DOWNLOADER.read_text()


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        print(f"{label}: already applied")
        return text
    if old not in text:
        raise SystemExit(f"{label}: anchor not found")
    print(f"{label}: applied")
    return text.replace(old, new, 1)


old_open = '''    port = choose_port(args.port)\n    try:\n        ser = serial.Serial()\n        ser.port = port\n        ser.baudrate = 115200\n        ser.timeout = 0.10\n        ser.write_timeout = 1.0\n        ser.rtscts = False\n        ser.dsrdtr = False\n        ser.dtr = True\n        ser.rts = False\n        print(f"Oeffne {port} ...")\n        ser.open()\n    except serial.SerialException as exc:\n        print(f"Port konnte nicht geoeffnet werden: {exc}")\n        print("Falls 'Access denied': Meshtastic-Konsole und andere Serial-Programme schliessen.")\n        return 2\n\n    scan = bytearray()\n'''

new_open = '''    port = choose_port(args.port)\n\n    # Do NOT open the COM port while the operator is navigating the Tracker.\n    # On the ESP32-S3 native USB path an open host CDC session changes the\n    # device's serial state and can interfere with the GPIO0 service-button\n    # interaction. The firmware's exporter already has a WAIT_USB state, so the\n    # safe sequence is: request export on-device first, then open the port.\n    print("")\n    print("COM-Port bleibt jetzt absichtlich GESCHLOSSEN, damit der Tracker bedienbar bleibt.")\n    print("Am Tracker: Service -> Diagnostic Log -> Export via USB")\n    print("Dann auf 'HOLD: EXPORT NOW' gehen und LANG bestaetigen.")\n    print("Der Tracker sollte danach auf den PC/Downloader warten.")\n    try:\n        input("ERST DANN hier Enter druecken, um den COM-Port zu oeffnen ... ")\n    except EOFError:\n        pass\n\n    try:\n        ser = serial.Serial()\n        ser.port = port\n        ser.baudrate = 115200\n        ser.timeout = 0.10\n        ser.write_timeout = 1.0\n        ser.rtscts = False\n        ser.dsrdtr = False\n        # No modem-control handshake is required for the diagnostic stream.\n        # Keep both host control lines deasserted; the downloader only listens.\n        ser.dtr = False\n        ser.rts = False\n        print(f"Oeffne {port} fuer den bereits angeforderten Export ...")\n        ser.open()\n        try:\n            ser.dtr = False\n            ser.rts = False\n        except Exception:\n            pass\n    except serial.SerialException as exc:\n        print(f"Port konnte nicht geoeffnet werden: {exc}")\n        print("Falls 'Access denied': Meshtastic-Konsole und andere Serial-Programme schliessen.")\n        return 2\n\n    scan = bytearray()\n'''
text = replace_once(text, old_open, new_open, "Tracker downloader late COM open")

old_ready = '''        print("USB-Serial ist jetzt offen und bereit.")\n        print("Am Tracker: Service -> Diagnostic Log -> Export via USB")\n        print("Dann 'HOLD: EXPORT NOW' waehlen und LANG halten.")\n        print("Downloader offen lassen, bis DONE erscheint.")\n'''
new_ready = '''        print("USB-Serial ist verbunden. Der bereits angeforderte Export sollte jetzt anlaufen.")\n        print("Downloader offen lassen, bis DONE erscheint; danach wird der COM-Port geschlossen.")\n'''
text = replace_once(text, old_ready, new_ready, "Tracker downloader post-open instructions")

for needle in [
    "COM-Port bleibt jetzt absichtlich GESCHLOSSEN",
    "ERST DANN hier Enter druecken",
    "ser.dtr = False",
    "ser.rts = False",
    "bereits angeforderte Export",
]:
    if needle not in text:
        raise SystemExit(f"Tracker downloader verification failed: {needle}")

if "ser.dtr = True" in text:
    raise SystemExit("Tracker downloader verification failed: DTR is still asserted")

DOWNLOADER.write_text(text)
print("Tracker downloader ready: navigate first, open COM only after HOLD export confirmation")
