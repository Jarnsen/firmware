"""Hide the fixed JARNSEN Bluetooth pairing PIN on every supported node display.

Pairing security is intentionally unchanged: FIXED_PIN mode, bonding,
encryption, MITM and secure connections remain enabled. This transform only
prevents the local node display (and serial log) from revealing the already
provisioned fixed passkey. The phone/peer still prompts for that passkey.
"""

from pathlib import Path

TARGET = Path("src/nimble/NimbleBluetooth.cpp")
MARKER = "JARNSEN_HIDE_BT_PAIRING_PIN_ALL_BOARDS"

text = TARGET.read_text(encoding="utf-8")

if MARKER not in text:
    log_anchor = '        LOG_INFO("*** Enter passkey %06u on the peer side ***", passkey);\n'
    if text.count(log_anchor) != 1:
        raise SystemExit(f"Bluetooth passkey log anchor: expected one, got {text.count(log_anchor)}")
    text = text.replace(
        log_anchor,
        '        LOG_INFO("BLE peer requested the configured JARNSEN pairing passkey"); // ' + MARKER + '\n',
        1,
    )

    tracker_owner = '''#if defined(HELTEC_TRACKER_V1_1)\n        trackerCommonSetPairingDisplay(true);\n#endif\n'''
    if text.count(tracker_owner) != 1:
        raise SystemExit(f"Tracker pairing display owner anchor: expected one, got {text.count(tracker_owner)}")
    text = text.replace(tracker_owner, "", 1)

    display_start_anchor = '''        bluetoothStatus->updateStatus(&newStatus);\n#if HAS_SCREEN\n'''
    display_end_anchor = '''#endif\n        passkeyShowing = true;\n'''
    start = text.find(display_start_anchor)
    if start < 0:
        raise SystemExit("Bluetooth pairing display start anchor not found")
    end = text.find(display_end_anchor, start)
    if end < 0:
        raise SystemExit("Bluetooth pairing display end anchor not found")
    end += len(display_end_anchor)
    replacement = '''        bluetoothStatus->updateStatus(&newStatus);\n        // Fixed pairing remains active, but the passkey is intentionally never\n        // rendered on a JARNSEN node display.\n        passkeyShowing = false;\n'''
    text = text[:start] + replacement + text[end:]

for forbidden in (
    'Enter passkey %06u on the peer side',
    'display->drawString(x_offset + x, y_offset + y, "Enter this code")',
    'trackerCommonSetPairingDisplay(true)',
):
    if forbidden in text:
        raise SystemExit(f"Bluetooth pairing PIN suppression incomplete: {forbidden}")
if MARKER not in text or "passkeyShowing = false;" not in text:
    raise SystemExit("Bluetooth pairing PIN suppression marker/state missing")

TARGET.write_text(text, encoding="utf-8")
