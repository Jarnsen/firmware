"""Validate that JARNSEN pairing shows only an instruction, never the numeric PIN.

The actual pairing implementation is committed in the platform Bluetooth
backends. This build-time gate deliberately does not rewrite those sources:
- security remains FIXED_PIN/MITM;
- node displays may say only "BT PIN" / "EINGEBEN";
- logs/status must not reveal the numeric passkey.
"""

from pathlib import Path


def require(text: str, needle: str, label: str) -> None:
    if needle not in text:
        raise SystemExit(f"{label}: missing {needle!r}")


def forbid(text: str, needle: str, label: str) -> None:
    if needle in text:
        raise SystemExit(f"{label}: forbidden numeric pairing-PIN exposure: {needle!r}")


nimble = Path("src/nimble/NimbleBluetooth.cpp").read_text(encoding="utf-8")
nrf52 = Path("src/platform/nrf52/NRF52Bluetooth.cpp").read_text(encoding="utf-8")
nrf54 = Path("src/platform/nrf54l15/NRF54L15Bluetooth.cpp").read_text(encoding="utf-8")

require(nimble, 'display->drawString(cx + x, cy + y - FONT_HEIGHT_MEDIUM, "BT PIN");', "ESP32 pairing instruction")
require(nimble, 'display->drawString(cx + x, cy + y + 3, "EINGEBEN");', "ESP32 pairing instruction")
require(nimble, 'meshtastic::BluetoothStatus newStatus("PAIRING");', "ESP32 pairing status")
require(nrf52, 'const char *ble_message = "BT PIN\\nEINGEBEN";', "nRF52 pairing instruction")
require(nrf54, 'meshtastic::BluetoothStatus pairingStatus("PAIRING");', "nRF54 pairing status")

for text, label in ((nimble, "ESP32"), (nrf52, "nRF52"), (nrf54, "nRF54")):
    for needle in (
        'Enter passkey %06u',
        'Enter this code',
        'Bluetooth pin set to',
        'BLE pairing PIN:',
        'BLE fixed PIN: %06u',
    ):
        forbid(text, needle, label)

print("JARNSEN Bluetooth pairing display contract: PASS (instruction only, numeric PIN hidden)")
