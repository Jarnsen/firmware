"""v2.1.15: keep target identity separate, expose Hop/TX without artificial tool caps, and avoid fake serial auto-confirm."""
from __future__ import annotations

import re
import sys
from pathlib import Path

APP_VERSION = "2.1.15"


def patch(source: str) -> str:
    source = re.sub(r'APP_VERSION = "[^"]+"', f'APP_VERSION = "{APP_VERSION}"', source, count=1)
    source = source.replace('APP_VERSION != "2.1.14"', 'APP_VERSION != "2.1.15"')
    source = source.replace("App-Version ist nicht v2.1.14", "App-Version ist nicht v2.1.15")

    # Long/Short name remain target-specific. A source identity may be stored as
    # profile metadata for reference, but must never override the target fields.
    identity_old = '''        # Since v2.1.14 Long/Short Name belong to the base profile. Existing\n        # older profiles fall back to the target fields until they are re-read.\n        long_name = str(profile.get("source_long_name") or self.config_target_long_var.get()).strip()\n        short_name = str(profile.get("source_short_name") or self.config_target_short_var.get()).strip()\n'''
    identity_new = '''        # Long/Short Name are target-specific and are deliberately not cloned.\n        # The source names stored in the profile are display/reference metadata only.\n        long_name = self.config_target_long_var.get().strip()\n        short_name = self.config_target_short_var.get().strip()\n'''
    if source.count(identity_old) != 1:
        raise SystemExit("v2.1.15 target identity anchor missing or ambiguous")
    source = source.replace(identity_old, identity_new, 1)

    source = source.replace('text="Long Name"', 'text="Quell-Long Name (Info)"', 1)
    source = source.replace('text="Short Name"', 'text="Quell-Short Name (Info)"', 1)
    source = source.replace('text="TX (dBm)"', 'text="TX-Leistung (dBm)"', 1)

    # Do not impose the ordinary Meshtastic policy limits in the Windows tool.
    # The protobuf type and the target firmware are the final authority. This
    # keeps the profile editor ready for explicitly authorised custom firmware.
    limits_old = '''                hop_limit = int(hop_var.get().strip())\n                tx_power = int(tx_var.get().strip())\n                if not 0 <= hop_limit <= 7:\n                    raise ValueError("Hop-Limit muss zwischen 0 und 7 liegen.")\n                if not 0 <= tx_power <= 30:\n                    raise ValueError("TX muss zwischen 0 und 30 dBm liegen.")\n'''
    limits_new = '''                hop_limit = int(hop_var.get().strip())\n                tx_power = int(tx_var.get().strip())\n                if hop_limit < 0:\n                    raise ValueError("Hop-Limit darf nicht negativ sein.")\n                if tx_power < 0:\n                    raise ValueError("TX-Leistung darf nicht negativ sein.")\n'''
    if source.count(limits_old) != 1:
        raise SystemExit("v2.1.15 Hop/TX validation anchor missing or ambiguous")
    source = source.replace(limits_old, limits_new, 1)
    source = source.replace('"CONFIG_PROFILE_EDIT_V2114",', '"CONFIG_PROFILE_EDIT_V2115",', 1)

    # v2.1.14 assumed Enter was a firmware-side serial export command. The
    # current V3 firmware does not implement such a command: the physical
    # service-page OK event calls the dump function directly. Sending CR/LF is
    # therefore not an automatic confirmation and may interfere with serial
    # traffic. Keep the one-click listener safe and wait for the real export.
    serial_old = '''            ser.open()\n            # The firmware already uses Enter as the serial export confirmation.\n            # Trigger it from the tool so a USB log download needs only one click.\n            try:\n                time.sleep(0.12)\n                ser.write(b"\\r\\n")\n                ser.flush()\n                self.events.put(\n                    ("status", f"{port} offen - Logexport automatisch per Enter gestartet")\n                )\n                self.events.put(("progress_detail", (None, "Export automatisch gestartet", True)))\n                tool_log("SERIAL_LOG_AUTO_ENTER_V2114", port=port, result="sent")\n            except (OSError, serial.SerialException) as exc:\n                self.events.put(\n                    ("status", f"{port} offen - Auto-Enter fehlgeschlagen, Export bitte am Gerät bestätigen")\n                )\n                self.events.put(("progress_detail", (None, "Warte auf Export", True)))\n                tool_log("SERIAL_LOG_AUTO_ENTER_V2114", port=port, result="fallback", error=exc)\n\n            scan = bytearray()\n'''
    serial_new = '''            ser.open()\n            self.events.put(\n                ("status", f"{port} offen - warte auf Logexport der Node")\n            )\n            self.events.put(("progress_detail", (None, "Warte auf Export", True)))\n            tool_log("SERIAL_LOG_WAIT_V2115", port=port, automatic_trigger=False)\n\n            scan = bytearray()\n'''
    if source.count(serial_old) != 1:
        raise SystemExit("v2.1.15 serial safety anchor missing or ambiguous")
    source = source.replace(serial_old, serial_new, 1)

    dialog_old = (
        "Long/Short Name, Rolle, Hop/TX und Bluetooth wurden mit eingelesen. "
        "Node-ID, Device-Keys und feste Position bleiben ausgeschlossen."
    )
    dialog_new = (
        "Rolle, Hop/TX, Bluetooth und Kanäle wurden eingelesen. "
        "Quell-Long/Short Name dienen nur als Info; beim Übertragen gelten die Ziel-Felder oben. "
        "Node-ID, Device-Keys und feste Position bleiben ausgeschlossen."
    )
    source = source.replace(dialog_old, dialog_new, 1)

    required = (
        'APP_VERSION = "2.1.15"',
        "CONFIG_PROFILE_EDIT_V2115",
        "SERIAL_LOG_WAIT_V2115",
        "automatic_trigger=False",
        "Hop-Limit",
        "TX-Leistung (dBm)",
        "Quell-Long Name (Info)",
        "Quell-Short Name (Info)",
        "long_name = self.config_target_long_var.get().strip()",
        "short_name = self.config_target_short_var.get().strip()",
    )
    missing = [marker for marker in required if marker not in source]
    if missing:
        raise SystemExit("v2.1.15 validation failed: " + ", ".join(missing))
    if "SERIAL_LOG_AUTO_ENTER_V2114" in source:
        raise SystemExit("v2.1.15 must not retain fake serial auto-enter")
    return source


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_jarnsen_service_tool_v2115.py <source.py>")
    path = Path(sys.argv[1])
    path.write_text(patch(path.read_text(encoding="utf-8")), encoding="utf-8")
    print(f"Patched {path} to v{APP_VERSION}: Hop/TX + safe serial log wait")


if __name__ == "__main__":
    main()
